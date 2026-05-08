import type { PublishRequest, PublishResponse } from "@/types/api";

const PREFILL_URLS: Record<string, string> = {
  vinted: "https://www.vinted.de/sell",
  kleinanzeigen: "https://www.kleinanzeigen.de/anzeige-aufgeben",
};

export async function publishListing(
  req: PublishRequest
): Promise<PublishResponse> {
  // TODO: backend — uncomment when API is ready
  // const res = await fetch(
  //   `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/publish`,
  //   {
  //     method: "POST",
  //     headers: { "Content-Type": "application/json" },
  //     body: JSON.stringify(req),
  //   }
  // )
  // if (!res.ok) throw new Error(`Publish failed: ${res.status}`)
  // return res.json() as Promise<PublishResponse>

  return {
    listing_id: req.listing_id,
    platform: req.platform,
    prefill_url: PREFILL_URLS[req.platform],
  };
}
