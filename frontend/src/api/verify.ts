import type { VerifyRequest, VerifyResponse } from "@/types/api";
import { uploadImage } from "./upload";

export async function verifyListing(
  req: VerifyRequest
): Promise<VerifyResponse> {
  // TODO: backend — uncomment when API is ready
  // const res = await fetch(
  //   `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/verify`,
  //   {
  //     method: "POST",
  //     headers: { "Content-Type": "application/json" },
  //     body: JSON.stringify(req),
  //   }
  // )
  // if (!res.ok) throw new Error(`Verify failed: ${res.status}`)
  // return res.json() as Promise<VerifyResponse>

  await new Promise((r) => setTimeout(r, 1000));
  // Mock: return the base upload mock with hints merged into both platform identifications
  const base = await uploadImage(new File([], "mock"));
  return {
    ...base,
    listing_id: req.listing_id,
    latency_ms: 980,
    vinted: {
      ...base.vinted,
      identification: { ...base.vinted.identification, ...req.hints },
    },
    kleinanzeigen: {
      ...base.kleinanzeigen,
      identification: { ...base.kleinanzeigen.identification, ...req.hints },
    },
    revised: true,
  };
}
