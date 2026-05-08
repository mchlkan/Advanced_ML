export type Platform = "vinted" | "kleinanzeigen";

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
  listing_id: string;
  platform: Platform;
  prefill_url: string;
}

export interface HealthzResponse {
  ok: boolean;
  vlm_backend: string;
  models_loaded: string[];
  device: string;
}

export interface ListingItem {
  id: string;
  created_at: number;
  image_url: string;
  title: string | null;
  brand: string | null;
  category: string | null;
  published_platforms: string[];
}

export interface InventoryResponse {
  listings: ListingItem[];
}
