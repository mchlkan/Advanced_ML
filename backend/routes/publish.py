"""POST /publish — enqueue a publish job and return the job_id immediately.

The actual platform API call happens in the background runner
(`backend.queue.runner.PublishRunner`). The runner picks up the job from
the `publishes` table, calls the integration, and updates the job's
status. Frontend polls GET /publish/status/{job_id} to follow along.

For Vinted that means: the user clicks "Publish to Vinted", gets a
job_id back in milliseconds, and sees the listing URL appear once the
runner finishes posting (~3-8 s warm). Transient failures (DataDome 429,
network blips) retry automatically with backoff.

Direct delete of an already-published listing is still synchronous via
DELETE /publish/{platform}/{platform_listing_id}.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response

# backend/__init__.py adds repo/src to sys.path.
from listing_mappings import NEW_LISTING_URLS

from backend import db, integrations
from backend.integrations import vinted as vinted_integration
from backend.schemas import (
    Platform,
    PublishCreatedResponse,
    PublishRequest,
    PublishStatusResponse,
)


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/publish", response_model=PublishCreatedResponse, status_code=202)
async def publish(request: Request, body: PublishRequest) -> PublishCreatedResponse:
    rec = await db.get_listing(body.listing_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"listing {body.listing_id} not found")

    fallback_url = NEW_LISTING_URLS[body.platform]
    canon_fields = body.final_fields.model_dump()

    job_id = await db.create_publish_job(
        listing_id=body.listing_id,
        platform=body.platform,
        final_fields=canon_fields,
        prefill_url=fallback_url,
    )
    runner = getattr(request.app.state, "publish_runner", None)
    if runner is not None:
        runner.notify()  # pull the new job into the runner without waiting for the idle poll
    return PublishCreatedResponse(
        job_id=job_id,
        status="pending",
        listing_id=body.listing_id,
        platform=body.platform,
    )


@router.get("/publish/status/{job_id}", response_model=PublishStatusResponse)
async def publish_status(job_id: int) -> PublishStatusResponse:
    row = await db.get_publish_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"publish job {job_id} not found")
    return PublishStatusResponse(
        job_id=row["id"],
        status=row["status"],
        listing_id=row["listing_id"],
        platform=row["platform"],
        retry_count=row["retry_count"],
        next_attempt_at=row.get("next_attempt_at"),
        platform_listing_id=row.get("platform_listing_id"),
        platform_listing_url=row.get("platform_listing_url"),
        prefill_url=row["prefill_url"],
        error=row.get("error"),
        updated_at=row["updated_at"],
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
