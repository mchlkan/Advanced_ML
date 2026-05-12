"""Inventory routes — joined view of listings, predictions, publish state,
and live Vinted wardrobe snapshots.

  POST   /inventory/sync          pull the Vinted wardrobe, write a snapshot row per item
  GET    /inventory               per-listing summary (latest prediction + per-platform
                                  publish state + joined wardrobe snapshot); lazily syncs
                                  when the last successful sync is older than INVENTORY_STALE_MS
  GET    /inventory/summary       the same data reduced to status counts
  POST   /listings/{id}/sold      mark sold: unlist from the platforms it was posted on,
                                  then drop the local record + photos
  DELETE /listings/{id}           combined delete: unlist from the platforms (best-effort,
                                  reported per-platform in the response) then drop the local record
  GET    /listings/{id}/prediction  reshape the latest prediction into an UploadResponse
                                    so the "Open" action reuses ResultsScreen
  PATCH  /listings/{id}/fields    edit fields; also pushes to live posted listings
  GET    /listings/{id}/image     serve the uploaded garment JPEG (InventoryItem.thumbnail_url)
  GET    /listings/{id}/label     serve the care-label JPEG, if one was uploaded
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from backend import db
from backend.integrations import (
    kleinanzeigen as ka_integration,
    vinted as vinted_integration,
)
from backend.routes import upload as upload_route

# backend/__init__.py adds repo/shared to sys.path.
from listing_mappings import to_kleinanzeigen, to_vinted  # noqa: E402
from backend.schemas import (
    FieldReview,
    Identification,
    InventoryBucket,
    InventoryItem,
    InventoryResponse,
    InventoryStatusCounts,
    InventorySummary,
    KleinanzeigenBlock,
    PatchFieldsRequest,
    PlatformPublishState,
    PredictionSummary,
    PriceBand,
    PricingStatus,
    SyncResponse,
    UploadResponse,
    VintedBlock,
    VintedLiveSnapshot,
)


router = APIRouter()
logger = logging.getLogger(__name__)

INVENTORY_STALE_MS = 5 * 60 * 1000


async def _do_vinted_sync() -> dict:
    """Fetch wardrobe, normalize, persist snapshots + sync row. Returns the
    fresh wardrobe_syncs row dict on success, raises on transport errors.
    Returning the row lets callers skip a follow-up get_last_wardrobe_sync."""
    started_at = db.now_ms()
    try:
        raw_items = await vinted_integration.fetch_wardrobe()
    except Exception as exc:
        await db.record_wardrobe_sync(
            "vinted", started_at, status="error",
            error=f"{type(exc).__name__}: {exc}"[:500],
        )
        raise

    normalized: list[dict] = []
    for item in raw_items:
        try:
            normalized.append(vinted_integration.normalize_wardrobe_item(item))
        except Exception:
            logger.warning(
                "skipping wardrobe item that failed to normalize: %s",
                traceback.format_exc(limit=1),
            )

    await db.insert_wardrobe_snapshots("vinted", normalized, started_at)
    await db.record_wardrobe_sync(
        "vinted", started_at, status="ok", item_count=len(normalized)
    )
    fresh = await db.get_last_wardrobe_sync("vinted")
    assert fresh is not None  # we just inserted one
    return fresh


@router.post("/inventory/sync", response_model=SyncResponse)
async def inventory_sync() -> SyncResponse:
    if not vinted_integration.is_session_ready():
        raise HTTPException(status_code=409, detail="vinted not onboarded")
    try:
        sync_row = await _do_vinted_sync()
    except vinted_integration.VintedNotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except vinted_integration.VintedAuthExpired as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except vinted_integration.VintedBlocked as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"vinted sync failed: {exc}") from exc

    return SyncResponse(
        platform="vinted",
        item_count=int(sync_row["item_count"] or 0),
        fetched_at=int(sync_row["finished_at"]),
    )


async def _load_inventory() -> tuple[list[InventoryItem], int | None]:
    """Shared by GET /inventory and GET /inventory/summary: lazy-refresh
    when stale + Vinted is configured (best-effort), then fold rows.

    Returns (items, last_synced_at). last_synced_at is None unless the most
    recent sync row has status='ok' — error rows don't count."""
    last = await db.get_last_wardrobe_sync("vinted")
    is_stale = (
        last is None
        or last.get("finished_at") is None
        or (db.now_ms() - int(last["finished_at"]) > INVENTORY_STALE_MS)
    )
    if is_stale and vinted_integration.is_session_ready():
        try:
            last = await _do_vinted_sync()
        except Exception as exc:
            logger.info("lazy wardrobe sync failed, serving cached data: %s", exc)

    rows = await db.get_inventory_rows()
    last_synced_at = (
        int(last["finished_at"])
        if last and last.get("status") == "ok" and last.get("finished_at")
        else None
    )
    items = _fold_inventory_rows(rows, last_synced_at)
    return items, last_synced_at


@router.get("/inventory", response_model=InventoryResponse)
async def get_inventory() -> InventoryResponse:
    items, last_synced_at = await _load_inventory()
    return InventoryResponse(items=items, last_synced_at=last_synced_at)


@router.get("/inventory/summary", response_model=InventorySummary)
async def get_inventory_summary() -> InventorySummary:
    items, last_synced_at = await _load_inventory()
    return _summarize(items, last_synced_at)


def _unlink_quietly(paths) -> None:
    for path_str in paths or ():
        if path_str:
            try:
                Path(path_str).unlink(missing_ok=True)
            except Exception:
                pass


async def _posted_targets(listing_id: str) -> list[tuple[str, str]]:
    """`(platform, platform_listing_id)` for each platform the listing is
    currently posted on — most recent successful publish row per platform."""
    publishes = await db.get_publishes_for_listing(listing_id)  # newest first
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for p in publishes:
        if p.get("status") != "posted" or not p.get("platform_listing_id"):
            continue
        if p["platform"] in seen:
            continue
        seen.add(p["platform"])
        targets.append((p["platform"], p["platform_listing_id"]))
    return targets


async def _unlist_from_platforms(listing_id: str) -> dict[str, dict]:
    """Best-effort: delete the listing on every platform it was posted on.

    Returns ``{platform: {"ok": bool, "error": str | None}}`` — one entry per
    platform that has a posted publish row. Removing the local record is the
    caller's job; this only touches the live platforms."""
    results: dict[str, dict] = {}
    for platform, platform_id in await _posted_targets(listing_id):
        try:
            if platform == "vinted":
                await vinted_integration.delete_listing(platform_id)
            elif platform == "kleinanzeigen":
                await ka_integration.delete_listing(platform_id)
            else:
                logger.info("no platform-delete for %s on %s — skipping", platform_id, platform)
                continue
            results[platform] = {"ok": True, "error": None}
        except Exception as exc:
            logger.warning(
                "%s delete failed for %s (listing %s): %s",
                platform, platform_id, listing_id, exc,
            )
            results[platform] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return results


@router.post("/listings/{listing_id}/sold", status_code=204, response_class=Response)
async def mark_sold(listing_id: str) -> Response:
    """Mark an item sold: unlist it from the platforms it was posted on, then
    drop the local record and its photos. Platform-delete failures are logged
    but not surfaced — a sold item that briefly lingers on a platform is benign."""
    rec = await db.get_listing(listing_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"listing {listing_id} not found")
    await _unlist_from_platforms(listing_id)
    _unlink_quietly(await db.delete_listing(listing_id))
    return Response(status_code=204)


@router.get("/listings/{listing_id}/prediction", response_model=UploadResponse)
async def get_listing_prediction(listing_id: str) -> UploadResponse:
    """Reshape the listing's most recent prediction into the same UploadResponse
    the frontend renders for fresh uploads. Lets the inventory "Open" action
    reuse ResultsScreen unmodified."""
    rec = await db.get_listing(listing_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="listing not found")
    pred = await db.get_latest_prediction(listing_id)
    if pred is None:
        raise HTTPException(status_code=404, detail="no prediction stored for this listing")

    fields = pred["english_fields"]
    identification = Identification(**{k: fields.get(k) for k in Identification.model_fields})
    vinted_band = PriceBand(q10=pred["vinted_q10"], q50=pred["vinted_q50"], q90=pred["vinted_q90"])
    ka_band = PriceBand(q10=pred["ka_q10"], q50=pred["ka_q50"], q90=pred["ka_q90"])
    return UploadResponse(
        listing_id=listing_id,
        vlm_backend=rec.get("vlm_backend") or "unknown",
        visual_wear_probability=pred["visual_wear_probability"] or 0.0,
        vinted=VintedBlock(
            price=vinted_band,
            sell_probability=pred["vinted_sell_prob"] or 0.0,
            identification=identification,
            field_review=FieldReview(),
        ),
        kleinanzeigen=KleinanzeigenBlock(
            price=ka_band,
            identification=identification,
            field_review=FieldReview(),
        ),
        latency_ms=int(pred["latency_ms"] or 0),
    )


@router.patch("/listings/{listing_id}/fields")
async def patch_listing_fields(listing_id: str, body: PatchFieldsRequest) -> dict:
    """Edit a listing's fields. Always stores locally; if the listing has
    posted publishes, also pushes the changes to those live platforms.
    Vinted/KA both require a full payload on PUT — we rebuild via
    `to_vinted` / `to_kleinanzeigen` from the merged fields and either
    re-attach existing photos (Vinted) or re-fetch picture links (KA).

    Response shape:
        {"stored": True, "pushed": {"vinted": {...}, "kleinanzeigen": {...}}}
    Each entry is either {"ok": True} or {"ok": False, "error": "..."}.
    Missing platform key = listing wasn't posted there, nothing to push."""
    pred = await db.get_latest_prediction(listing_id)
    if pred is None:
        raise HTTPException(status_code=404, detail="listing has no prediction to edit")
    overrides = body.model_dump(exclude_unset=True, exclude_none=True)
    if not overrides:
        return {"stored": True, "pushed": {}}
    old_fields = pred["english_fields"]
    merged = {**old_fields, **overrides}
    await db.log_edits(
        listing_id,
        [
            (k, None if old_fields.get(k) is None else str(old_fields.get(k)), str(v))
            for k, v in overrides.items()
        ],
    )
    await db.log_prediction(
        listing_id=listing_id,
        source="edit",
        english_fields=merged,
        vinted_q10=pred["vinted_q10"],
        vinted_q50=pred["vinted_q50"],
        vinted_q90=pred["vinted_q90"],
        vinted_sell_prob=pred["vinted_sell_prob"],
        ka_q10=pred["ka_q10"],
        ka_q50=pred["ka_q50"],
        ka_q90=pred["ka_q90"],
        visual_wear_probability=pred["visual_wear_probability"],
        latency_ms=0,
        vlm_call_count=0,
    )

    targets = await _posted_targets(listing_id)

    async def _push_one(platform: str, platform_id: str) -> tuple[str, dict]:
        try:
            await _push_edit(platform, platform_id, merged)
            logger.info("pushed edit to %s listing %s for %s", platform, platform_id, listing_id)
            return platform, {"ok": True}
        except Exception as exc:
            logger.warning(
                "push edit to %s listing %s failed for %s: %s",
                platform, platform_id, listing_id, exc,
            )
            return platform, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    results = await asyncio.gather(*(_push_one(p, pid) for p, pid in targets))
    return {"stored": True, "pushed": dict(results)}


async def _push_edit(platform: str, platform_id: str, fields: dict) -> None:
    """Build the per-platform payload and call the integration's update.
    Raises whatever the underlying integration raises."""
    if platform == "vinted":
        payload = to_vinted(fields)
        if "catalog_id" not in payload:
            raise ValueError(f"category {fields.get('category')!r} has no Vinted catalog mapping")
        await vinted_integration.update_listing(platform_id, payload)
    elif platform == "kleinanzeigen":
        payload = to_kleinanzeigen(fields)
        if "category_id" not in payload:
            raise ValueError(f"category {fields.get('category')!r} has no Kleinanzeigen category mapping")
        await ka_integration.update_listing(platform_id, payload)
    else:
        raise ValueError(f"update on {platform!r} not implemented")


@router.delete("/listings/{listing_id}")
async def delete_listing_combined(listing_id: str) -> dict:
    """Combined delete: best-effort cleanup on every platform the listing was
    posted on, then guaranteed local cleanup. The local record is always
    removed; the response reports per-platform success so the caller can warn
    when a platform delete failed.

    Response shape:
        {"local_deleted": True, "platforms": {"vinted": {"ok": bool, "error": str | None}, ...}}
    Platform keys are present only for platforms the listing was posted on."""
    rec = await db.get_listing(listing_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="listing not found")
    platforms = await _unlist_from_platforms(listing_id)
    _unlink_quietly(await db.delete_listing(listing_id))
    return {"local_deleted": True, "platforms": platforms}


@router.get("/listings/{listing_id}/image")
async def get_listing_image(listing_id: str) -> FileResponse:
    record = await db.get_listing(listing_id)
    if record is None:
        raise HTTPException(status_code=404, detail="listing not found")

    raw_path = Path(record["image_path"]).resolve()
    uploads_root = upload_route.UPLOADS_DIR.resolve()
    # image_path is written by upload.py as `UPLOADS_DIR / f"{uuid_hex}.jpg"`,
    # so traversal is implausible by construction — but the DB is data, not
    # code, so reject anything outside the upload root before opening.
    if not raw_path.is_relative_to(uploads_root) or not raw_path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(raw_path, media_type="image/jpeg")


@router.get("/listings/{listing_id}/label")
async def get_listing_label_image(listing_id: str) -> FileResponse:
    """Return the care-label photo for the listing, or 404 if none was uploaded."""
    record = await db.get_listing(listing_id)
    if record is None:
        raise HTTPException(status_code=404, detail="listing not found")

    label_path_str = record.get("label_image_path")
    if not label_path_str:
        raise HTTPException(status_code=404, detail="label image not uploaded")

    raw_path = Path(label_path_str).resolve()
    uploads_root = upload_route.UPLOADS_DIR.resolve()
    if not raw_path.is_relative_to(uploads_root) or not raw_path.is_file():
        raise HTTPException(status_code=404, detail="label image not found")
    return FileResponse(raw_path, media_type="image/jpeg")


# ---------- response shaping ----------


def _price_band(q10, q50, q90) -> PriceBand | None:
    if q10 is None or q50 is None or q90 is None:
        return None
    return PriceBand(q10=q10, q50=q50, q90=q90)


def _prediction_from_row(row: dict) -> PredictionSummary | None:
    vinted = _price_band(row["vinted_q10"], row["vinted_q50"], row["vinted_q90"])
    ka = _price_band(row["ka_q10"], row["ka_q50"], row["ka_q90"])
    if vinted is None and ka is None and row.get("english_fields") is None:
        return None
    fields = json.loads(row["english_fields"]) if row.get("english_fields") else {}
    return PredictionSummary(
        english_fields=fields,
        vinted=vinted,
        vinted_sell_probability=row.get("vinted_sell_prob") or 0.0,
        kleinanzeigen=ka,
        visual_wear_probability=row.get("visual_wear_probability") or 0.0,
    )


def _publish_state_from_row(row: dict, *, last_synced_at: int | None) -> PlatformPublishState:
    platform = row["publish_platform"]
    state = PlatformPublishState(
        publish_id=int(row["publish_id"]),
        status=row["publish_status"],
        platform_listing_id=row.get("publish_platform_listing_id"),
        platform_listing_url=row.get("publish_platform_listing_url"),
        error=row.get("publish_error"),
    )
    if platform != "vinted":
        return state
    if state.status != "posted" or not state.platform_listing_id:
        return state

    fetched_at = row.get("wardrobe_fetched_at")
    has_snapshot = fetched_at is not None
    publish_updated_at = int(row.get("publish_updated_at") or 0)

    if has_snapshot:
        state.live = VintedLiveSnapshot(
            fetched_at=int(fetched_at),
            title=row.get("wardrobe_title"),
            price_eur=row.get("wardrobe_price_eur"),
            views=row.get("wardrobe_views"),
            favourites=row.get("wardrobe_favourites"),
            primary_photo_url=row.get("wardrobe_primary_photo_url"),
            is_sold_or_removed=False,
        )
    elif (
        last_synced_at is not None
        and last_synced_at >= publish_updated_at
    ):
        # We've synced since this item was published, and it didn't appear
        # in the wardrobe — Vinted no longer lists it (sold or deleted).
        state.live = VintedLiveSnapshot(
            fetched_at=last_synced_at,
            is_sold_or_removed=True,
        )
    return state


def _classify_pricing(
    price: float | None, band: PriceBand | None
) -> tuple[PricingStatus, float | None]:
    """Compare actual live price to the model's predicted band.
    underpriced: below q10. overpriced: above q90. ok: in [q10, q90].
    unknown: missing data."""
    if price is None or band is None or band.q50 <= 0:
        return ("unknown", None)
    if price < band.q10:
        status: PricingStatus = "underpriced"
    elif price > band.q90:
        status = "overpriced"
    else:
        status = "ok"
    delta_pct = round((price - band.q50) / band.q50 * 100.0, 1)
    return (status, delta_pct)


def _attach_pricing(item: InventoryItem) -> None:
    """Populate vinted.live.pricing_status / delta_vs_q50_pct in place. Runs
    after fold so we have both prediction and snapshot in one place."""
    if item.vinted is None or item.vinted.live is None:
        return
    band = item.prediction.vinted if item.prediction else None
    status, delta = _classify_pricing(item.vinted.live.price_eur, band)
    item.vinted.live.pricing_status = status
    item.vinted.live.delta_vs_q50_pct = delta


def _fold_inventory_rows(rows: list[dict], last_synced_at: int | None) -> list[InventoryItem]:
    """Group SQL rows by listing_id. Each listing can appear with one row per
    publish-platform (or one row with null publish_* if it has never been
    published)."""
    by_listing: dict[str, InventoryItem] = {}
    for row in rows:
        listing_id = row["listing_id"]
        item = by_listing.get(listing_id)
        if item is None:
            item = InventoryItem(
                listing_id=listing_id,
                created_at=int(row["listing_created_at"]),
                thumbnail_url=f"/listings/{listing_id}/image",
                prediction=_prediction_from_row(row),
            )
            by_listing[listing_id] = item

        if row.get("publish_id") is None:
            continue
        platform = row["publish_platform"]
        state = _publish_state_from_row(row, last_synced_at=last_synced_at)
        if platform == "vinted":
            item.vinted = state
        elif platform == "kleinanzeigen":
            item.kleinanzeigen = state

    items = list(by_listing.values())
    for item in items:
        _attach_pricing(item)
    return items


# ---------- summary aggregation ----------


def _bucket_for(item: InventoryItem) -> InventoryBucket:
    """Pick one bucket per listing for the summary counts. Priority:
    posted > sold_or_removed > pending > failed > unpublished. An item
    actively posted on Vinted stays "posted" even if a separate KA attempt
    failed — the dominant active state wins."""
    states: list[PlatformPublishState] = [
        s for s in (item.vinted, item.kleinanzeigen) if s is not None
    ]
    if not states:
        return "unpublished"

    has_active_posted = any(
        s.status == "posted"
        and not (s.live is not None and s.live.is_sold_or_removed)
        for s in states
    )
    if has_active_posted:
        return "posted"

    has_sold = any(
        s.status == "posted"
        and s.live is not None
        and s.live.is_sold_or_removed
        for s in states
    )
    if has_sold:
        return "sold_or_removed"

    if any(s.status in ("pending", "running") for s in states):
        return "pending"

    if any(s.status == "failed" for s in states):
        return "failed"

    return "unpublished"


def _summarize(items: list[InventoryItem], last_synced_at: int | None) -> InventorySummary:
    counts = InventoryStatusCounts(total=len(items))
    estimated_value = 0.0
    live_views = 0
    live_favourites = 0

    for item in items:
        bucket = _bucket_for(item)
        setattr(counts, bucket, getattr(counts, bucket) + 1)

        # Aggregate value/views over actively-posted vinted items only.
        v = item.vinted
        if v is None or v.status != "posted":
            continue
        if v.live is not None and v.live.is_sold_or_removed:
            continue
        band = item.prediction.vinted if item.prediction else None
        if band is not None and band.q50 > 0:
            estimated_value += band.q50
        if v.live is not None:
            live_views += v.live.views or 0
            live_favourites += v.live.favourites or 0

    return InventorySummary(
        counts=counts,
        estimated_value_eur=round(estimated_value, 2),
        live_views=live_views,
        live_favourites=live_favourites,
        last_synced_at=last_synced_at,
    )
