"""Pydantic request/response models for the FastAPI backend.

The shape mirrors the brief §5.4 result page layout: identification block plus
a per-platform recommendation block. Field names match the VLM's English-canonical
output (see `src.prompts.get_prompt`) so frontend and pipeline don't drift.
"""

from __future__ import annotations

from typing import Any, Literal

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
    """Legacy synchronous response — retained for tests but no longer
    returned by /publish (which is now async)."""
    listing_id: str
    platform: Platform
    prefill_url: str
    posted: bool = False
    platform_listing_id: str | None = None
    platform_listing_url: str | None = None
    error: str | None = None


JobStatus = Literal["pending", "running", "posted", "failed"]


class PublishCreatedResponse(BaseModel):
    job_id: int
    status: JobStatus
    listing_id: str
    platform: Platform


class PublishStatusResponse(BaseModel):
    job_id: int
    status: JobStatus
    listing_id: str
    platform: Platform
    retry_count: int
    next_attempt_at: int | None = None
    platform_listing_id: str | None = None
    platform_listing_url: str | None = None
    prefill_url: str
    error: str | None = None
    updated_at: int


class HealthzResponse(BaseModel):
    ok: bool
    vlm_backend: str
    models_loaded: list[str]
    device: str


class OnboardingLoginRequest(BaseModel):
    platform: Platform
    email: str
    password: str


class OnboardingLoginResponse(BaseModel):
    platform: Platform
    status: Literal["ready"]
    user_id: str
    expires_at: float


class PlatformStatus(BaseModel):
    state: Literal["ready", "expired", "not_configured", "not_implemented"]
    expires_at: float | None = None
    user_id: str | None = None


class OnboardingStatusResponse(BaseModel):
    vinted: PlatformStatus
    kleinanzeigen: PlatformStatus


class KleinanzeigenOnboardingRequest(BaseModel):
    """Bootstrap a KA session from a captured refresh_token. The maintainer
    extracts the refresh_token once via mitmproxy on a real device (Auth0 +
    Akamai BMP + MFA SMS make programmatic login impractical) and posts it
    here; backend refreshes the access_token forever after.

    `imprint` is the legally-required Impressum block for COMMERCIAL
    accounts. PRIVATE sellers leave it blank.
    """
    refresh_token: str
    email: str
    poster_type: Literal["PRIVATE", "COMMERCIAL"] = "PRIVATE"
    imprint: str = ""
    contact_name: str = ""
    home_location_id: int | None = None


class KleinanzeigenOnboardingResponse(BaseModel):
    platform: Literal["kleinanzeigen"] = "kleinanzeigen"
    status: Literal["ready"]
    user_id: int
    expires_at: float


class PredictionSummary(BaseModel):
    english_fields: dict[str, Any]
    # None means we have no per-platform price quantiles for this listing
    # (the prediction row exists but the bands weren't populated). The FE
    # should render "no estimate" rather than €0.
    vinted: PriceBand | None = None
    vinted_sell_probability: float = 0.0
    kleinanzeigen: PriceBand | None = None
    visual_wear_probability: float = 0.0


PricingStatus = Literal["underpriced", "ok", "overpriced", "unknown"]


class VintedLiveSnapshot(BaseModel):
    fetched_at: int
    title: str | None = None
    price_eur: float | None = None
    views: int | None = None
    favourites: int | None = None
    primary_photo_url: str | None = None
    is_sold_or_removed: bool
    # Pricing-drift overlay: live price vs the model's recommended band.
    # Frontend-facing enum so the UI can switch over named cases instead of
    # recomputing thresholds. "unknown" means we lack data (no live price or
    # no prediction); always present so the UI doesn't need a null branch.
    pricing_status: PricingStatus = "unknown"
    # Signed % delta against q50 (negative = below recommendation). None when
    # we can't compute it. Lets the UI render a tag like "−18%" without math.
    delta_vs_q50_pct: float | None = None


class PlatformPublishState(BaseModel):
    publish_id: int
    status: JobStatus
    platform_listing_id: str | None = None
    platform_listing_url: str | None = None
    error: str | None = None
    live: VintedLiveSnapshot | None = None


class InventoryItem(BaseModel):
    listing_id: str
    created_at: int
    thumbnail_url: str
    prediction: PredictionSummary | None = None
    vinted: PlatformPublishState | None = None
    kleinanzeigen: PlatformPublishState | None = None


class InventoryResponse(BaseModel):
    items: list[InventoryItem]
    last_synced_at: int | None = None


class SyncResponse(BaseModel):
    platform: Literal["vinted"]
    item_count: int
    fetched_at: int


InventoryBucket = Literal[
    "posted", "sold_or_removed", "pending", "failed", "unpublished"
]


class InventoryStatusCounts(BaseModel):
    """Per-listing buckets, mutually exclusive — they sum to `total`. Priority
    when a listing has multiple platform states: posted > sold_or_removed >
    pending > failed > unpublished. The frontend can render one badge per
    card without recomputing."""
    total: int = 0
    unpublished: int = 0
    pending: int = 0
    posted: int = 0
    sold_or_removed: int = 0
    failed: int = 0


class InventorySummary(BaseModel):
    counts: InventoryStatusCounts
    # Σ vinted q50 across actively-posted items with a prediction. EUR.
    estimated_value_eur: float = 0.0
    # Σ across live wardrobe snapshots of actively-posted vinted items.
    live_views: int = 0
    live_favourites: int = 0
    last_synced_at: int | None = None
