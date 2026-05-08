"""POST /verify — re-run the VLM with seller hints + re-run heads."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.schemas import VerifyRequest, VerifyResponse


router = APIRouter()


@router.post("/verify", response_model=VerifyResponse)
async def verify(body: VerifyRequest) -> VerifyResponse:
    raise HTTPException(status_code=501, detail="Not implemented")
