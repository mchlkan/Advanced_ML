import type { InventoryResponse } from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function fetchInventory(): Promise<InventoryResponse> {
  const res = await fetch(`${BASE}/listings`);
  if (!res.ok) throw new Error("Failed to fetch inventory");
  return res.json();
}

export async function markAsSold(id: string): Promise<void> {
  const res = await fetch(`${BASE}/listings/${id}/sold`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to mark as sold");
}

export { BASE };
