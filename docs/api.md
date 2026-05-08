# Resell Copilot — Frontend API Reference

Backend HTTP API for the Next.js / Vite frontend. **Base URL** in dev: `http://localhost:8000`.
**OpenAPI spec** (machine-readable): `GET /openapi.json` — feeds `openapi-typescript` to generate
typed clients.

CORS is open for `localhost:3000` (Next.js) and `localhost:5173` (Vite) by default; override via
`CORS_ORIGINS` env var.

All error responses are `{"detail": "<human readable string>"}`. The HTTP status code distinguishes
the failure mode (see per-route tables below).

---

## Quick map

| # | Endpoint | Verb | Purpose |
|---|---|---|---|
| 1 | `/healthz` | GET | Boot check, models loaded |
| 2 | `/upload` | POST | New photo → predictions |
| 3 | `/verify` | POST | Re-run with seller hints |
| 4 | `/publish` | POST | Enqueue platform publish (async) |
| 5 | `/publish/status/{job_id}` | GET | Poll publish status |
| 6 | `/publish/{platform}/{listing_id}` | DELETE | Delete a draft on the platform |
| 7 | `/onboarding/login` | POST | Vinted email+password login |
| 8 | `/onboarding/kleinanzeigen` | POST | KA refresh-token onboarding |
| 9 | `/onboarding/status` | GET | Per-platform readiness |
| 10 | `/inventory` | GET | All listings + their state |
| 11 | `/inventory/sync` | POST | Force pull live Vinted wardrobe |
| 12 | `/inventory/summary` | GET | Aggregate counts |
| 13 | `/listings/{id}/image` | GET | Serve the uploaded JPEG |

---

## 1. `GET /healthz`

```json
{
  "ok": true,
  "vlm_backend": "runpod_http",
  "models_loaded": ["DINOv2 (facebook/dinov2-base)", "FlawHead (in_dim=768)", ...],
  "device": "mps"
}
```

Use to confirm the backend is up. Frontend should display a "backend offline" banner if this 5xx's.

---

## 2. `POST /upload`

Upload a photo → run the full pipeline (VLM ×2 + DINOv2 + flaw + price + sell).

**Request:** `multipart/form-data` with one field `image` (any JPEG/PNG/WEBP).

```js
const fd = new FormData();
fd.append("image", file);
await fetch("/upload", { method: "POST", body: fd });
```

**Response (200):**
```json
{
  "listing_id": "e30d480b9cc44555aea7840431dff86c",
  "visual_wear_probability": 0.38,
  "vinted": {
    "price": { "q10": 5.67, "q50": 12.58, "q90": 21.80 },
    "sell_probability": 0.72,
    "identification": {
      "brand": "adidas", "category": "tshirts", "condition": "Very good",
      "color": "Rose", "size": "S / 36 / 8",
      "title": "Adidas T-shirt", "description": "...", "price_eur": 10.0
    }
  },
  "kleinanzeigen": {
    "price": { "q10": 5.21, "q50": 16.14, "q90": 31.50 },
    "identification": { ... },
    "qualitative_note": "Kleinanzeigen does not expose a sold marker. ..."
  },
  "latency_ms": 122732,
  "vlm_backend": "runpod_http"
}
```

**Latency**: 3-30 s warm against a hot RunPod worker, up to 2 min on cold start. Show a spinner.

**Errors:**
| Status | When |
|---|---|
| `400` | uploaded file isn't a decodable image |

---

## 3. `POST /verify`

User edits one or more identification fields (brand/category/condition/color/size). Backend re-runs the VLM with `[Hint: ...]` appended to the prompt, overlays the user's hints onto the VLM output before the price/sell heads, logs each changed field to the `edits` table, and returns the revised predictions.

**Request:**
```json
{
  "listing_id": "e30d480b9cc44555aea7840431dff86c",
  "hints": {
    "brand": "Zara",
    "size": "M",
    "category": null,
    "condition": null,
    "color": null
  }
}
```

Only fields the user *actually edited* should be set; null/missing fields are left alone.

**Response (200):** same shape as `/upload` plus `"revised": true`.

| Status | When |
|---|---|
| `404` | `listing_id` unknown |
| `410` | listing's image is no longer on disk |

---

## 4. `POST /publish` *(async)*

Enqueue a publish job. Returns **202** with a `job_id` immediately; the actual platform call runs in a background runner. Frontend then polls `/publish/status/{job_id}` until terminal.

**Request:**
```json
{
  "listing_id": "e30d480b9cc44555aea7840431dff86c",
  "platform": "vinted",
  "final_fields": {
    "category": "tshirts",
    "condition": "Very good",
    "brand": "Adidas",
    "color": "Pink",
    "size": "S",
    "title": "Adidas Trefoil tee in pink",
    "description": "...",
    "price_eur": 10.0
  }
}
```

**Response (202):**
```json
{
  "job_id": 13,
  "status": "pending",
  "listing_id": "e30d480b9cc44555aea7840431dff86c",
  "platform": "vinted"
}
```

| Status | When |
|---|---|
| `404` | `listing_id` unknown |

---

## 5. `GET /publish/status/{job_id}`

Poll target for the async publish. Status transitions: `pending → running → posted` (terminal) **or** `pending → running → failed` (terminal) **or** `pending → running → pending (retry)` for transient errors with backoff.

```json
{
  "job_id": 13,
  "status": "posted",
  "listing_id": "e30d480b9cc44555aea7840431dff86c",
  "platform": "vinted",
  "retry_count": 0,
  "next_attempt_at": 1778263633562,
  "platform_listing_id": "8859515451",
  "platform_listing_url": "https://www.vinted.fr/items/8859515451",
  "prefill_url": "https://www.vinted.de/items/new",
  "error": null,
  "updated_at": 1778263635363
}
```

**Frontend polling pattern (~10 lines of React):**
```ts
const TERMINAL = new Set(["posted", "failed"]);
const interval = setInterval(async () => {
  const job = await fetch(`/publish/status/${jobId}`).then(r => r.json());
  setJob(job);
  if (TERMINAL.has(job.status)) clearInterval(interval);
}, 2000);
```

**On `posted`** → open `platform_listing_url` in a new tab.
**On `failed`** → show `error` and link `prefill_url` (the platform's new-listing page) as the manual fallback.

| Status | When |
|---|---|
| `404` | unknown `job_id` |

---

## 6. `DELETE /publish/{platform}/{platform_listing_id}`

Delete a draft (or, on Vinted, sometimes a published listing) on the platform. **Vinted-only** in v1; KA returns 501. Note: Vinted's endpoint reliably deletes drafts but may 403 on already-published listings — handle 502 by linking to the platform UI.

```bash
DELETE /publish/vinted/8859515451
→ 204 No Content
```

| Status | When |
|---|---|
| `404` | listing not found on the platform |
| `501` | `kleinanzeigen` (Phase 6c+ TBD) |
| `502` | upstream platform error (e.g. 403 on a live listing) |
| `503` | platform integration not configured |

---

## 7. `POST /onboarding/login` *(Vinted only)*

Vinted email+password login. Backend handles the full Auth0 + DataDome flow internally (requires `VINTED_DATADOME_SEED` + 3 device env vars to be pre-set on the backend; frontend doesn't need to know).

**Request:**
```json
{
  "platform": "vinted",
  "email": "you@example.com",
  "password": "..."
}
```

**Response (200):**
```json
{
  "platform": "vinted",
  "status": "ready",
  "user_id": "55707471",
  "expires_at": 1778264151.0
}
```

**Important: KA does NOT support this route** — it returns 501 because Auth0 + Akamai BMP + MFA SMS make programmatic login impractical. For KA, use the next route.

| Status | When |
|---|---|
| `401` | credentials rejected |
| `429` | DataDome challenge — try again later |
| `501` | `kleinanzeigen` (use `/onboarding/kleinanzeigen` instead) |
| `502` | upstream platform error |
| `503` | backend missing seed env vars (admin issue) |

---

## 8. `POST /onboarding/kleinanzeigen`

KA's login flow can't be replayed server-side. Maintainer captures a `refresh_token` once via mitmproxy on a real device (see `docs/ka_endpoints.md`); the user pastes the captured values into this route. Backend stores them and refreshes the access_token forever after.

**Request:**
```json
{
  "refresh_token": "v_1U_ArL...",
  "email": "you@example.com",
  "poster_type": "PRIVATE",
  "imprint": "",
  "contact_name": "",
  "home_location_id": 7615
}
```

`poster_type`: `"PRIVATE"` or `"COMMERCIAL"`. `imprint` is required for COMMERCIAL accounts (legal Impressum block). `home_location_id` is the numeric KA location id (e.g. 7615 = "85051 Ingolstadt").

**Response (200):**
```json
{
  "platform": "kleinanzeigen",
  "status": "ready",
  "user_id": 45852425,
  "expires_at": 1778265870.0
}
```

| Status | When |
|---|---|
| `401` | refresh_token rejected (expired/revoked) — capture a fresh one |
| `502` | upstream KA / Auth0 error |
| `503` | backend missing `KA_SESSION_PATH` env var (admin issue) |

---

## 9. `GET /onboarding/status`

Cheap, idempotent, safe to call on app boot. Use to decide which "log in" buttons to show vs which platforms are ready.

```json
{
  "vinted": {
    "state": "ready",
    "expires_at": 1778264151.0,
    "user_id": "55707471"
  },
  "kleinanzeigen": {
    "state": "ready",
    "expires_at": 1778265870.0,
    "user_id": "45852425"
  }
}
```

`state` values:
- `"ready"` — session valid, can publish
- `"expired"` — session file exists but access_token has lapsed; routes will refresh transparently, but the user may want to re-login if refresh fails
- `"not_configured"` — no session file → frontend should prompt onboarding
- `"not_implemented"` — never returned in v1, reserved

---

## 10. `GET /inventory`

All the user's listings joined with their latest prediction, per-platform publish state, and the live Vinted wardrobe snapshot if posted. Lazily triggers a wardrobe sync when stale. Safe to call on every result-page render.

```json
{
  "items": [
    {
      "listing_id": "e30d4...",
      "created_at": 1778263510000,
      "thumbnail_url": "/listings/e30d4.../image",
      "prediction": {
        "english_fields": { "brand": "adidas", ... },
        "vinted": { "q10": 5.67, "q50": 12.58, "q90": 21.80 },
        "vinted_sell_probability": 0.72,
        "kleinanzeigen": { "q10": 5.21, "q50": 16.14, "q90": 31.50 },
        "visual_wear_probability": 0.38
      },
      "vinted": {
        "publish_id": 13,
        "status": "posted",
        "platform_listing_id": "8859515451",
        "platform_listing_url": "https://www.vinted.fr/items/8859515451",
        "error": null,
        "live": {
          "fetched_at": 1778263700000,
          "title": "Adidas T-shirt",
          "price_eur": 11.20,
          "views": 4,
          "favourites": 1,
          "primary_photo_url": "https://img.vinted.fr/...",
          "is_sold_or_removed": false,
          "pricing_status": "ok",
          "delta_vs_q50_pct": -10.9
        }
      },
      "kleinanzeigen": null
    }
  ],
  "last_synced_at": 1778263700000
}
```

---

## 11. `POST /inventory/sync`

Force a wardrobe pull. Returns when sync completes (or fails). Requires Vinted to be `state="ready"` per `/onboarding/status`.

```json
{
  "platform": "vinted",
  "item_count": 7,
  "fetched_at": 1778263700000
}
```

---

## 12. `GET /inventory/summary`

Aggregate counts for a small "you have N listings" header.

---

## 13. `GET /listings/{listing_id}/image`

Serve the uploaded JPEG by `listing_id`. Use as a `<img src="...">`:

```html
<img src="/listings/e30d4.../image" />
```

| Status | When |
|---|---|
| `404` | listing or image file not found |

---

## Generated TypeScript types

```bash
npx openapi-typescript http://localhost:8000/openapi.json -o src/api.ts
```

Then in code:
```ts
import { paths } from "./api";
type UploadResponse = paths["/upload"]["post"]["responses"]["200"]["content"]["application/json"];
```

All 4xx/5xx codes are declared in OpenAPI, so error handling can be exhaustive (`switch (resp.status) { case 404: ...; case 410: ... }`).
