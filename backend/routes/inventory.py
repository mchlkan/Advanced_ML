"""Inventory routes — joined view of listings, predictions, publish state,
and live Vinted wardrobe snapshots.

POST /inventory/sync
  Pull the user's Vinted wardrobe and write a snapshot row per item. Used
  both explicitly (frontend pull-to-refresh) and inline by GET /inventory
  when its cached data is stale.

GET /inventory
  Per-listing summary: latest prediction, per-platform publish state, plus
  the live wardrobe snapshot joined in for posted Vinted items. Lazily
  triggers a sync when the last successful one is older than INVENTORY_STALE_MS
  (failures fall through to cached data so the read never blocks).

GET /listings/{listing_id}/image
  Serve the uploaded JPEG so the frontend can render thumbnails referenced
  by InventoryItem.thumbnail_url.
"""

from __future__ import annotations

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


@router.post("/listings/{listing_id}/sold", status_code=204, response_class=Response)
async def mark_sold(listing_id: str) -> Response:
    deleted = await db.delete_listing(listing_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail=f"listing {listing_id} not found")
    image_path, label_image_path = deleted
    for path_str in (image_path, label_image_path):
        if path_str is None:
            continue
        try:
            Path(path_str).unlink(missing_ok=True)
        except Exception:
            pass
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
    merged = {**pred["english_fields"], **overrides}
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

    pushed: dict[str, dict] = {}
    publishes = await db.get_publishes_for_listing(listing_id)
    for p in publishes:
        if p.get("status") != "posted" or not p.get("platform_listing_id"):
            continue
        platform = p["platform"]
        platform_id = p["platform_listing_id"]
        if platform in pushed:
            continue  # only push to the most recent successful row per platform
        try:
            if platform == "vinted":
                payload = to_vinted(merged)
                if "catalog_id" not in payload:
                    raise ValueError(f"category {merged.get('category')!r} has no Vinted catalog mapping")
                await vinted_integration.update_listing(platform_id, payload)
            elif platform == "kleinanzeigen":
                payload = to_kleinanzeigen(merged)
                if "category_id" not in payload:
                    raise ValueError(f"category {merged.get('category')!r} has no Kleinanzeigen category mapping")
                await ka_integration.update_listing(platform_id, payload)
            else:
                raise ValueError(f"update on {platform!r} not implemented")
            pushed[platform] = {"ok": True}
            logger.info("pushed edit to %s listing %s for %s", platform, platform_id, listing_id)
        except Exception as exc:
            pushed[platform] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            logger.warning(
                "push edit to %s listing %s failed for %s: %s",
                platform, platform_id, listing_id, exc,
            )
    return {"stored": True, "pushed": pushed}


@router.delete("/listings/{listing_id}", status_code=204, response_class=Response)
async def delete_listing_combined(listing_id: str) -> Response:
    """Combined delete: best-effort platform cleanup (Vinted only — KA's
    integration doesn't expose delete) followed by guaranteed local cleanup.
    Returns 204 even if the platform delete fails; the local row is gone
    either way."""
    rec = await db.get_listing(listing_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="listing not found")
    publishes = await db.get_publishes_for_listing(listing_id)
    seen_platforms: set[str] = set()
    for p in publishes:
        if p.get("status") != "posted" or not p.get("platform_listing_id"):
            continue
        platform = p["platform"]
        if platform in seen_platforms:
            continue  # only delete the most recent successful row per platform
        seen_platforms.add(platform)
        try:
            if platform == "vinted":
                await vinted_integration.delete_listing(p["platform_listing_id"])
            elif platform == "kleinanzeigen":
                await ka_integration.delete_listing(p["platform_listing_id"])
            else:
                logger.info(
                    "skipping platform delete for %s on %s (not implemented)",
                    p["platform_listing_id"], platform,
                )
        except Exception as exc:
            logger.warning(
                "%s delete failed for %s during combined delete of listing %s: %s",
                platform, p["platform_listing_id"], listing_id, exc,
            )
    deleted = await db.delete_listing(listing_id)
    if deleted is not None:
        for path_str in deleted:
            if path_str:
                try:
                    Path(path_str).unlink(missing_ok=True)
                except Exception:
                    pass
    return Response(status_code=204)


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
