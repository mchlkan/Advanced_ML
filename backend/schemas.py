"""Pydantic request/response models for the FastAPI backend.

The shape mirrors the brief §5.4 result page layout: identification block plus
a per-platform recommendation block. Field names match the VLM's English-canonical
output (see `src.prompts.get_prompt`) so frontend and pipeline don't drift.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Platform = Literal["vinted", "kleinanzeigen"]


class Identification(BaseModel):
    brand: str | None = None
    category: str | None = None
    condition: str | None = None
    color: str | None = None
    size: str | None = None
    title: str | None = None
    description: str | None = None
    price_eur: float | None = None


class PriceBand(BaseModel):
    q10: float
    q50: float
    q90: float


class VintedBlock(BaseModel):
    price: PriceBand
    sell_probability: float
    identification: Identification


class KleinanzeigenBlock(BaseModel):
    price: PriceBand
    identification: Identification
    qualitative_note: str = Field(
        default=(
            "Kleinanzeigen does not expose a sold marker. "
            "Sell-likelihood not predicted; ask price only."
        ),
        description="Per Day-2 memo: KA has no ground-truth sold labels.",
    )


class UploadResponse(BaseModel):
    listing_id: str
    visual_wear_probability: float
    vinted: VintedBlock
    kleinanzeigen: KleinanzeigenBlock
    latency_ms: int
    vlm_backend: str


class VerifyHints(BaseModel):
    brand: str | None = None
    category: str | None = None
    condition: str | None = None
    color: str | None = None
    size: str | None = None


class VerifyRequest(BaseModel):
    listing_id: str
    hints: VerifyHints


class VerifyResponse(UploadResponse):
    revised: bool = True


class PublishRequest(BaseModel):
    listing_id: str
    platform: Platform
    final_fields: Identification


class PublishResponse(BaseModel):
    listing_id: str
    platform: Platform
    prefill_url: str
    posted: bool = False
    platform_listing_id: str | None = None
    platform_listing_url: str | None = None
    error: str | None = None


class HealthzResponse(BaseModel):
    ok: bool
    vlm_backend: str
    models_loaded: list[str]
    device: str
