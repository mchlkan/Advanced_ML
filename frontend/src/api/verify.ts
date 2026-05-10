import type { VerifyRequest, VerifyResponse } from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function verifyListing(
  req: VerifyRequest
): Promise<VerifyResponse> {
  const res = await fetch(`${BASE}/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`Verify failed: ${res.status}`);
  return res.json() as Promise<VerifyResponse>;
}
