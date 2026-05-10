import type { DraftResponse, PublishRequest, PublishResponse, PublishStatusResponse } from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function publishListing(
  req: PublishRequest
): Promise<PublishResponse> {
  const res = await fetch(`${BASE}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`Publish failed: ${res.status}`);
  return res.json() as Promise<PublishResponse>;
}

export async function getPublishStatus(jobId: number): Promise<PublishStatusResponse> {
  const res = await fetch(`${BASE}/publish/status/${jobId}`);
  if (!res.ok) throw new Error(`Status check failed: ${res.status}`);
  return res.json() as Promise<PublishStatusResponse>;
}

export async function draftListing(req: PublishRequest): Promise<DraftResponse> {
  const res = await fetch(`${BASE}/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`Draft failed: ${res.status}`);
  return res.json() as Promise<DraftResponse>;
}
