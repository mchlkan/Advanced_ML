import type {
  PublishRequest,
  PublishResponse,
  PublishStatusResponse,
} from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function publishListing(
  req: PublishRequest,
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

export class PublishTimeoutError extends Error {
  constructor(public readonly jobId: number) {
    super(`Publish job ${jobId} did not finish in time`);
    this.name = "PublishTimeoutError";
  }
}

// Poll /publish/status/{jobId} until it's in a terminal state (posted /
// failed). Backend's PublishRunner typically completes a Vinted publish
// in 3-8 s warm; the timeout caps an unresponsive backend, not a slow
// publish path.
export async function pollPublishStatus(
  jobId: number,
  opts: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<PublishStatusResponse> {
  const interval = opts.intervalMs ?? 1500;
  const timeout = opts.timeoutMs ?? 90_000;
  const start = Date.now();
  for (;;) {
    const status = await getPublishStatus(jobId);
    if (status.status === "posted" || status.status === "failed") return status;
    if (Date.now() - start > timeout) throw new PublishTimeoutError(jobId);
    await new Promise((r) => setTimeout(r, interval));
  }
}
