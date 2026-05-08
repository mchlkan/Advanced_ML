import type { UploadResponse } from "@/types/api";

const MOCK_RESPONSE: UploadResponse = {
  listing_id: "a4f1b22c",
  visual_wear_probability: 0.52,
  vinted: {
    price: { q10: 28, q50: 38, q90: 52 },
    sell_probability: 0.65,
    identification: {
      brand: "Acne Studios",
      category: "Wool jumper",
      condition: "Good",
      color: "Cream",
      size: "M",
      title: "Acne Studios wool jumper — cream, barely worn",
      description:
        "Gorgeous Acne Studios oversized wool jumper in a warm cream tone. Size M, fits true to size. Only worn a handful of times — light pilling on one sleeve, otherwise perfect condition. Comes from a smoke-free home.",
      price_eur: 38,
    },
  },
  kleinanzeigen: {
    price: { q10: 22, q50: 32, q90: 44 },
    identification: {
      brand: "Acne Studios",
      category: "Wollpullover",
      condition: "Gut",
      color: "Creme",
      size: "M",
      title: "Acne Studios Wollpullover Creme M",
      description:
        "Acne Studios Wollpullover in Creme, Größe M. Nur wenige Male getragen, leichte Pillen an einem Ärmel. Nicht-Raucher-Haushalt. Versand möglich.",
      price_eur: 32,
    },
    qualitative_note:
      "Kleinanzeigen does not expose a sold marker. Sell-likelihood not predicted; ask price only.",
  },
  latency_ms: 4200,
  vlm_backend: "mock",
};

export async function uploadImage(file: File): Promise<UploadResponse> {
  // TODO: backend — uncomment when API is ready
  // const formData = new FormData()
  // formData.append("file", file)
  // const res = await fetch(
  //   `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/upload`,
  //   { method: "POST", body: formData }
  // )
  // if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
  // return res.json() as Promise<UploadResponse>

  await new Promise((r) => setTimeout(r, 3200));
  return { ...MOCK_RESPONSE };
}
