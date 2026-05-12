import type { VlmStatus } from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** GET /vlm/status — RunPod endpoint health (worker counts incl. `throttled`).
 *  Best-effort: returns null rather than throwing, so a status hiccup never
 *  blocks the analyzing screen. */
export async function fetchVlmStatus(): Promise<VlmStatus | null> {
  try {
    const res = await fetch(`${BASE}/vlm/status`);
    if (!res.ok) return null;
    return (await res.json()) as VlmStatus;
  } catch {
    return null;
  }
}
