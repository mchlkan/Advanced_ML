"""POST /publish — log intent and return prefilled platform listing URL."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.schemas import PublishRequest, PublishResponse


router = APIRouter()


@router.post("/publish", response_model=PublishResponse)
async def publish(body: PublishRequest) -> PublishResponse:
    raise HTTPException(status_code=501, detail="Not implemented")
