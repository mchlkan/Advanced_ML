import type {
  InventoryResponse,
  PatchFieldsRequest,
  UploadResponse,
} from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function fetchInventory(): Promise<InventoryResponse> {
  const res = await fetch(`${BASE}/inventory`);
  if (!res.ok) throw new Error("Failed to fetch inventory");
  return res.json();
}

export async function markAsSold(id: string): Promise<void> {
  const res = await fetch(`${BASE}/listings/${id}/sold`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to mark as sold");
}

export async function fetchListingPrediction(id: string): Promise<UploadResponse> {
  const res = await fetch(`${BASE}/listings/${id}/prediction`);
  if (!res.ok) throw new Error(`Failed to fetch listing: ${res.status}`);
  return res.json() as Promise<UploadResponse>;
}

export interface PushResult {
  ok: boolean;
  error?: string;
}

export interface PatchFieldsResponse {
  stored: boolean;
  pushed: Partial<Record<"vinted" | "kleinanzeigen", PushResult>>;
}

export async function patchListingFields(
  id: string,
  fields: PatchFieldsRequest,
): Promise<PatchFieldsResponse> {
  const res = await fetch(`${BASE}/listings/${id}/fields`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  if (!res.ok) throw new Error(`Failed to update listing: ${res.status}`);
  return res.json() as Promise<PatchFieldsResponse>;
}

export async function deleteListing(id: string): Promise<void> {
  const res = await fetch(`${BASE}/listings/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete listing: ${res.status}`);
}

export { BASE };
