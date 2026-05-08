"""POST /publish — try direct platform posting, fall back to a new-listing URL.

Direct publish path (Phase 6a, Vinted only):
  - If `VINTED_SESSION_PATH` is set and the file exists, attempt a real
    publish via the mobile draft-mode flow (see backend/integrations/vinted.py).
  - On success, the response includes `platform_listing_url` pointing at
    the live listing.
  - On any failure (DataDome 429, session expired, network), the response
    falls back to the new-listing page URL with `posted=false` and a
    machine-readable `error` string. Never 5xx.

Kleinanzeigen always falls back to the URL path for now (Phase 6c).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

# backend/__init__.py adds repo/src to sys.path.
from listing_mappings import NEW_LISTING_URLS, to_vinted

from backend import db, integrations
from backend.integrations import vinted as vinted_integration
from backend.schemas import PublishRequest, PublishResponse, Platform


router = APIRouter()
logger = logging.getLogger(__name__)

PUBLISH_TIMEOUT_S = 60


@router.post("/publish", response_model=PublishResponse)
async def publish(body: PublishRequest) -> PublishResponse:
    rec = await db.get_listing(body.listing_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"listing {body.listing_id} not found")

    fallback_url = NEW_LISTING_URLS[body.platform]
    canon_fields = body.final_fields.model_dump()

    posted = False
    platform_listing_id: str | None = None
    platform_listing_url: str | None = None
    error: str | None = None

    if body.platform == "vinted" and integrations.is_configured("vinted"):
        try:
            payload = to_vinted(canon_fields)
            if "catalog_id" not in payload:
                error = f"category {canon_fields.get('category')!r} has no Vinted catalog mapping"
            elif not payload.get("title") or not payload.get("description") or not payload.get("price"):
                error = "title, description, and price are required for Vinted"
            else:
                item_id, url = await asyncio.wait_for(
                    vinted_integration.publish(rec["image_path"], payload),
                    timeout=PUBLISH_TIMEOUT_S,
                )
                posted = True
                platform_listing_id = str(item_id)
                platform_listing_url = url
        except asyncio.TimeoutError:
            error = f"Vinted publish timed out after {PUBLISH_TIMEOUT_S}s"
        except vinted_integration.VintedError as exc:
            error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            logger.exception("unexpected Vinted publish failure")
            error = f"unexpected error: {type(exc).__name__}: {exc}"
    elif body.platform == "kleinanzeigen":
        error = "Kleinanzeigen direct publishing not implemented (Phase 6c)"

    final_url = platform_listing_url or fallback_url
    await db.log_publish(body.listing_id, body.platform, canon_fields, final_url)

    return PublishResponse(
        listing_id=body.listing_id,
        platform=body.platform,
        prefill_url=final_url,
        posted=posted,
        platform_listing_id=platform_listing_id,
        platform_listing_url=platform_listing_url,
        error=error,
    )


@router.delete("/publish/{platform}/{platform_listing_id}", status_code=204, response_class=Response)
async def delete_listing(platform: Platform, platform_listing_id: str) -> Response:
    """Delete a published listing or unpublished draft on the platform.
    Same endpoint serves both — Vinted's API doesn't distinguish."""
    if platform != "vinted":
        raise HTTPException(status_code=501, detail=f"delete on {platform} not implemented")
    if not integrations.is_configured("vinted"):
        raise HTTPException(status_code=503, detail="Vinted integration not configured")
    try:
        await vinted_integration.delete_listing(platform_listing_id)
    except vinted_integration.VintedError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=502, detail=msg) from exc
    return Response(status_code=204)
