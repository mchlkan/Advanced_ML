"""POST /publish — log the user's publish intent and return the platform's
new-listing URL.

v1 limitation: neither Vinted nor Kleinanzeigen accepts URL-based field
prefill on their public listing forms, and their listing-creation APIs
require OAuth or aren't public. ``prefill_url`` therefore returns the
platform's new-listing *page* — the frontend handles the actual prefill
UX (copy-to-clipboard buttons next to each field) using the data it
already has from /upload or /verify.

The ``publishes`` row captures whatever the user actually chose to publish
(possibly different from the latest /verify if they edited freely in the
UI), which is the analytics signal we want.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

# backend/__init__.py adds repo/src to sys.path.
from listing_mappings import NEW_LISTING_URLS

from backend import db
from backend.schemas import PublishRequest, PublishResponse


router = APIRouter()


@router.post("/publish", response_model=PublishResponse)
async def publish(body: PublishRequest) -> PublishResponse:
    rec = await db.get_listing(body.listing_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"listing {body.listing_id} not found")

    url = NEW_LISTING_URLS[body.platform]
    canon_fields = body.final_fields.model_dump()
    await db.log_publish(body.listing_id, body.platform, canon_fields, url)

    return PublishResponse(
        listing_id=body.listing_id,
        platform=body.platform,
        prefill_url=url,
    )
