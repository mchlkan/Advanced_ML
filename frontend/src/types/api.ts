export type Platform = "vinted" | "kleinanzeigen";

// Backend may also emit "expired" as a deprecated alias for "needs_login"
// — treat it the same on the FE.
export type PlatformConnectionState =
  | "ready"
  | "needs_login"
  | "expired"
  | "not_configured"
  | "not_implemented";

export interface PlatformStatus {
  state: PlatformConnectionState;
  expires_at: number | null;
  user_id: string | null;
}

export interface OnboardingStatus {
  vinted: PlatformStatus;
  kleinanzeigen: PlatformStatus;
}

export interface OnboardingLoginResponse {
  platform: Platform;
  status: "ready";
  user_id: string;
  expires_at: number;
}

export interface KleinanzeigenInitiateResponse {
  challenge_id: string | null;
  status: "mfa_required" | "ready";
  phone_hint?: string;
  // Populated when status === "ready" (the maintainer's phone had a
  // rememberBrowser cookie and Auth0 skipped MFA).
  user_id?: string;
  expires_at?: number;
}

export interface KleinanzeigenVerifyMfaRequest {
  challenge_id: string;
  sms_code: string;
  email: string;
  poster_type?: "PRIVATE" | "COMMERCIAL";
  imprint?: string;
  contact_name?: string;
  home_location_id?: number;
}

export interface KleinanzeigenRefreshTokenRequest {
  refresh_token: string;
  email: string;
  poster_type?: "PRIVATE" | "COMMERCIAL";
  imprint?: string;
  contact_name?: string;
  home_location_id?: number;
}

export interface PriceBand {
  q10: number;
  q50: number;
  q90: number;
}

export interface FieldReview {
  needs_review: string[];
  reasons: Record<string, string>;
}

export interface Identification {
  brand: string | null;
  category: string | null;
  condition: string | null;
  color: string | null;
  size: string | null;
  title: string | null;
  description: string | null;
  price_eur: number | null;
}

export interface PatchFieldsRequest {
  brand?: string | null;
  category?: string | null;
  condition?: string | null;
  color?: string | null;
  size?: string | null;
  title?: string | null;
  description?: string | null;
  price_eur?: number | null;
}

export interface VintedBlock {
  price: PriceBand;
  sell_probability: number;
  identification: Identification;
  field_review: FieldReview;
}

export interface KleinanzeigenBlock {
  price: PriceBand;
  identification: Identification;
  field_review: FieldReview;
  qualitative_note: string;
}

export interface UploadResponse {
  listing_id: string;
  visual_wear_probability: number;
  vinted: VintedBlock;
  kleinanzeigen: KleinanzeigenBlock;
  latency_ms: number;
  vlm_backend: string;
}

export interface VerifyHints {
  brand?: string | null;
  category?: string | null;
  condition?: string | null;
  color?: string | null;
  size?: string | null;
}

export interface VerifyRequest {
  listing_id: string;
  hints: VerifyHints;
}

export interface VerifyResponse extends UploadResponse {
  revised: boolean;
}

export interface PublishRequest {
  listing_id: string;
  platform: Platform;
  final_fields: Identification;
}

export interface PublishResponse {
  job_id: number;
  status: JobStatus;
  listing_id: string;
  platform: Platform;
}

export interface PublishStatusResponse {
  job_id: number;
  status: JobStatus;
  listing_id: string;
  platform: Platform;
  retry_count: number;
  next_attempt_at: number | null;
  platform_listing_id: string | null;
  platform_listing_url: string | null;
  prefill_url: string;
  error: string | null;
  updated_at: number;
}

export type PricingStatus = "underpriced" | "ok" | "overpriced" | "unknown";

export interface PredictionSummary {
  english_fields: Record<string, unknown>;
  vinted: PriceBand | null;
  vinted_sell_probability: number;
  kleinanzeigen: PriceBand | null;
  visual_wear_probability: number;
}

export interface VintedLiveSnapshot {
  fetched_at: number;
  title: string | null;
  price_eur: number | null;
  views: number | null;
  favourites: number | null;
  primary_photo_url: string | null;
  is_sold_or_removed: boolean;
  pricing_status: PricingStatus;
  delta_vs_q50_pct: number | null;
}

export type JobStatus = "pending" | "running" | "posted" | "failed";

export interface PlatformPublishState {
  publish_id: number;
  status: JobStatus;
  platform_listing_id: string | null;
  platform_listing_url: string | null;
  error: string | null;
  live: VintedLiveSnapshot | null;
}

export interface InventoryItem {
  listing_id: string;
  created_at: number;
  thumbnail_url: string;
  prediction: PredictionSummary | null;
  vinted: PlatformPublishState | null;
  kleinanzeigen: PlatformPublishState | null;
}

export interface InventoryResponse {
  items: InventoryItem[];
  last_synced_at: number | null;
}

export interface SyncResponse {
  platform: "vinted";
  item_count: number;
  fetched_at: number;
}

export interface InventoryStatusCounts {
  total: number;
  unpublished: number;
  pending: number;
  posted: number;
  sold_or_removed: number;
  failed: number;
}

export interface InventorySummary {
  counts: InventoryStatusCounts;
  estimated_value_eur: number;
  live_views: number;
  live_favourites: number;
  last_synced_at: number | null;
}
