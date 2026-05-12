# Resell Copilot — Technical Report

**Project:** Photo-first selling assistant for second-hand clothing
**Course:** Nova SBE Advanced ML, 7-day project
**Production URL:** https://resell-copilot-three.vercel.app (password-gated)
**API:** https://resell-copilot.duckdns.org
**Repository:** github.com/mchlkan/Advanced_ML (`main`)

---

## 1. Executive summary

Resell Copilot turns one photo of a second-hand clothing item into a
ready-to-publish listing on **two competing marketplaces** (Vinted +
Kleinanzeigen) in roughly **6–10 seconds end-to-end**. The user picks
one platform or cross-posts to both in a single tap; the app submits
the listing live via the platform's mobile API and returns a clickable
link to each live ad. The user can then manage the listing — change the
price, edit fields, relist, or delete — directly from the inventory
tab, with edits and deletes propagating to the live platform listings
in parallel.

The system runs **six trained models** in a layered stack
(VLM identification → DINOv2 visual features → 3 specialised MLP heads
→ grounded LLM description), three **reverse-engineered** mobile-app
integrations (Vinted, Kleinanzeigen, RunPod Serverless), and a
**bind-mount Docker** deploy that pushes Python code changes to
production in **10 seconds** (vs. 5 minutes for a full image rebuild).

Total external API spend across all training and inference iterations:
**~$3.50** (Groq for Model #6, RunPod Serverless for VLM forward
passes). Backend tests at submission time: **123 passing**.

---

## 2. System architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            User (mobile / desktop)                      │
│                                                                         │
│                              HTTPS + cookie gate                        │
│                                    │                                    │
│                                    ▼                                    │
│   ┌──────────────────────────────────────────────────────────────────┐  │
│   │  Next.js 14 SPA (Vercel — resell-copilot-three.vercel.app)       │  │
│   │   - App Router, TypeScript, inline-style components              │  │
│   │   - Middleware password gate (httpOnly cookie)                   │  │
│   │   - Single screen state machine: upload → analyzing → results    │  │
│   │     → publishing → published; plus inventory branch              │  │
│   │   - PWA manifest + service worker (install-readiness)            │  │
│   └────────────────────────────┬─────────────────────────────────────┘  │
│                                │ JSON over HTTPS                        │
│                                ▼                                        │
│   ┌──────────────────────────────────────────────────────────────────┐  │
│   │  FastAPI backend (AWS EC2 t2.small, Ubuntu 26.04)                │  │
│   │   - Docker container, code bind-mounted from host                │  │
│   │   - Nginx + Let's Encrypt → resell-copilot.duckdns.org           │  │
│   │   - SQLite at /opt/resell/data/resell.db                         │  │
│   │   - Async PublishRunner (in-process queue + retry/backoff)       │  │
│   │                                                                  │  │
│   │  At startup loads:                                               │  │
│   │   - DINOv2 base (HuggingFace facebook/dinov2-base, ~95 MB)       │  │
│   │   - FlawHead, PriceHead, SellHead MLP checkpoints                │  │
│   │     (gitignored .pt files, bind-mounted from host)               │  │
│   │                                                                  │  │
│   │  External integrations:                                          │  │
│   │   - VLM: HTTP to RunPod Serverless                               │  │
│   │   - Description: HTTP to Groq (Llama 3.1 8B)                     │  │
│   │   - Vinted: mobile API via stored session                        │  │
│   │   - Kleinanzeigen: mobile API via stored session                 │  │
│   └────┬─────────────────┬───────────────────┬──────────┬────────────┘  │
│        │                 │                   │          │               │
│        ▼                 ▼                   ▼          ▼               │
│   ┌────────┐   ┌──────────────────┐   ┌──────────┐  ┌───────────┐       │
│   │ RunPod │   │ Groq (Llama 3.1) │   │  Vinted  │  │   Klein-  │       │
│   │ (VLM)  │   │  description     │   │  mobile  │  │  anzeigen │       │
│   │ Qwen3- │   │   generation     │   │   API    │  │  mobile   │       │
│   │ VL-4B  │   │                  │   │          │  │   API     │       │
│   │+ multi-│   │   ~150 ms        │   │  draft → │  │  Auth0 +  │       │
│   │  v3    │   │  per platform    │   │  publish │  │   JAXB-   │       │
│   │ adapter│   │                  │   │  → link  │  │   XML     │       │
│   └────────┘   └──────────────────┘   └──────────┘  └───────────┘       │
│   ~3-8 s                                                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Data flow on a single upload

1. **User taps "Take photo"** in the SPA.
2. **(Optional)** User adds a brand/size tag close-up in a "review"
   phase before continuing.
3. **POST /upload** (multipart) to backend with `image` + optional
   `label_image`.
4. Backend persists both files to `/app/data/uploads/`, opens them as
   PIL images, and runs the **pipeline** in parallel:
   - VLM call ×2 (one with `platform=vinted` prompt, one with
     `platform=kleinanzeigen` prompt) → emits identification fields +
     a 2560-dim pooled hidden state per platform.
   - DINOv2 forward on the cover photo → 768-dim CLS embedding.
   - FlawHead on the DINOv2 embedding → wear probability.
   - PriceHead ×2 (one per platform's hidden state, conditioned on
     wear probability) → q10/q50/q90 EUR.
   - SellHead on the metadata + wear → sell-through probability.
   - Model #6 (Groq) ×2 → grounded English description per platform.
5. Pipeline returns a unified `UploadResponse`: per-platform
   identification + price band + sell probability + description +
   visual wear probability.
6. **Frontend** renders the `ResultsScreen` — user can edit fields
   (re-running the pipeline via `/verify`) or hit Publish.
7. **POST /publish** enqueues one job per chosen platform (Vinted, KA,
   or both); the backend's runner posts to each asynchronously; the
   frontend polls `/publish/status/{job_id}` for each until terminal
   (`posted` / `failed`), ticking each platform's row over as it lands.
8. On `posted`, the live platform URL is stored to the `publishes`
   table and shown as a clickable link on the published screen (one
   per platform — no auto-opened tab; opening another site's tab
   without the user asking was removed as confusing).

End-to-end latency from "tap photo" to "platform tab opens":
**6–10 seconds** warm path; up to ~30s on cold-start (RunPod worker
boot).

---

## 3. Model stack

Six trained models in a layered design — each is small and
specialised, with the VLM doing the heavy multimodal reading and the
heads doing tight numeric refinement.

| # | Model | Inputs | Output | Architecture | Training data |
|---|---|---|---|---|---|
| 1 | **VLM (identification)** | Cover photo + (optional) brand/size tag photo | 6 fields: brand, category, condition, color, size, title | Qwen3-VL-4B-Instruct + LoRA adapter `mchlkan/qwen3vl4b-resell-adapter-multi-v3` (rank 16, all-linear) | Scraped Vinted + KA listings, English-canonical schema |
| 2 | **FlawHead** | DINOv2 CLS embedding (768-d) | Visual wear probability (0-1) | 3-layer MLP, BCE loss, threshold 0.5 | Manually-labelled wear photos |
| 3 | **PriceHead** | Per-platform VLM hidden state (2560-d) + wear probability + categorical fields | Quantile prices q10/q50/q90 (EUR) | MLP with quantile-loss output heads | Sold listings with final prices |
| 4 | **SellHead** | Categorical fields + wear (no VLM features) | Sell-through probability (0-1, 30 day window) | MLP, BCE loss | Vinted listings with sold/unsold labels |
| 5 | **DINOv2** | Cover photo | 768-d CLS visual embedding | `facebook/dinov2-base`, frozen | Pretrained, no fine-tune |
| 6 | **Description generator** | Identification fields + visual wear from #1/#2 | 2-3 sentence English description | Groq Llama 3.1 8B with category-matched few-shot prompt | Hand-crafted prompt templates |

### 3.1 Why a layered stack instead of one big VLM

The course brief required defending the model architecture. Three
reasons to split:

- **Different update cadences.** PriceHead retrains nightly on fresh
  sold-listing data; the VLM adapter retrains when prompt vocab
  changes. Splitting lets each move at its own pace.
- **Cheap per-call inference for the heads.** Heads are <10 MB MLPs
  that load into memory at startup. Once we have the VLM hidden
  state, all three heads run in <5 ms total. No reason to push price
  prediction through a 4B-parameter VLM forward.
- **Auditability.** When a price suggestion looks wrong, we can
  inspect the input fields, the wear probability, and the head's
  output independently. With one monolithic VLM we'd be guessing.

### 3.2 The `multi-v2` adapter retrain (Day 5 evening)

The original `multi-v1` adapter emitted seven fields including a
multi-sentence `description` and `price_eur`. KA's clean-parse rate
was only **40.9%** because the description's length frequently broke
the JSON-completion budget. The fix:

- **Drop `description` and `price_eur` from the inference prompt.**
  Description moves to Model #6 (Groq) downstream; price moves to
  PriceHead. The VLM now emits 6 short fields.
- **Keep `price_eur` as a training-time auxiliary target** so the
  pooled hidden state still encodes price-relevant signal — the
  PriceHead reads that signal and quantifies it.
- **Result:** KA clean-parse rate **40.9% → 100%**. Price head test
  coverage **77.6% → 85.8%** (closer to the 80% calibration target).

This was a clean separation-of-concerns win driven by a real
production failure mode.

A follow-up retrain — **`multi-v3`** (shipped 2026-05-11), the adapter
currently in production — added Kleinanzeigen listings to the
multi-image training manifest (which until then was Vinted-only).
Accuracy improved on every test-set platform on the metrics that
matter; full per-field deltas are in `docs/model_stack_evolution.md`
§4.4.

---

## 4. Reverse-engineering case studies

The most interesting engineering work was making the system speak the
two marketplace mobile APIs without ever using a documented public
endpoint. None of these were strictly necessary for a course
demo — but the alternative (open the platform's web UI in a popup
and ask the user to paste the prefill) would have made the
end-to-end story trivial. Here's what we built instead.

### 4.1 Vinted mobile API + DataDome bypass

**Challenge.** Vinted aggressively bot-protects its public web
endpoints with DataDome, returning 403 + CAPTCHA challenges to any
unrecognised client. The mobile app uses a separate auth tier that
trusts a **rotating `datadome` cookie** seeded once via a real
device.

**Solution.**
1. Capture the initial DataDome cookie + four device-identity values
   (`anon_id`, `device_uuid`, `device_token`, `datadome_seed`) from a
   real Android device using mitmproxy. Store as env vars.
2. On each call, refresh the DataDome cookie via a dedicated `/refresh`
   endpoint that the mobile app uses to keep the cookie warm without
   a full re-handshake.
3. Use a 3-step "draft → put → completion" publish flow that bypasses
   DataDome on the high-cost completion call:
   - `POST /api/v2/item_upload/drafts` with just `{title}` (creates
     an empty draft, ~100ms)
   - `PUT /api/v2/item_upload/drafts/{id}` with the full payload
     (attaches everything)
   - `POST /api/v2/item_upload/drafts/{id}/completion` with
     server-side photo IDs (publishes live)

**Edit endpoint discovery (Day 5 evening).** The same draft URL
returned **403 access_denied** on a published item — Vinted locks
the draft URL once it transitions to "live". Instead, we OPTIONS-
probed candidate URLs and discovered:

```
PUT /api/v2/item_upload/items/{item_id}
```

returns `400 validation_error` with field-by-field hints, confirming
the verb is accepted. The full payload is required (no partial
patches), and **brand changes are partially restricted** —
Vinted's own error message says "Bestimmte Marken können nur geändert
werden, wenn du den Artikel löschst und erneut hochlädst."

**Probe script:** `scripts/probe_vinted_edit.py` — committed for
reproducibility.

**Files:** `backend/integrations/vinted.py`,
`backend/routes/onboarding.py` (the password + MFA login flow).

### 4.2 Kleinanzeigen mobile API — Auth0 + SMS MFA + JAXB-XML

**Challenge.** KA's mobile API is a different beast:
- Auth via Auth0 + Akamai BMP + SMS MFA — programmatic login is
  infeasible without a real browser and an SMS-receiving phone.
- Listing submit body is **JAXB XML** (despite a JSON content-type),
  embedded in a payload structure inherited from eBay Classifieds.
- Per-category attribute schema is enforced server-side beyond what
  the metadata endpoint advertises (e.g., omitting
  `kleidung_herren.art` returns "Bitte gib einen Wert ein.").

**Solution.**
1. **Bootstrap once via mitmproxy capture** of a real Android device
   walking the full login flow. Persist the resulting `refresh_token`
   to env. Refresh the access token forever after via
   `POST /oauth/token` with `grant_type=refresh_token`.
2. **Implement password + SMS MFA login** for the onboarding UI when
   a refresh fails (`backend/integrations/kleinanzeigen.py:password_login_initiate`
   + `complete_mfa_login` — ported from a sibling `vinted-lister`
   project, ~440 lines covering full Auth0 PKCE + Akamai BMP-aware
   sensor flows).
3. **Build the JAXB XML body from canonical fields** via
   `build_ad_xml(payload, picture_links)` — ~70 lines that handle
   namespacing, attribute injection, and HTML-escaping descriptions.

**Category discovery (Day 5 evening).** The first KA publishes failed
because the runner's pre-validation reported "no Kleinanzeigen
category mapping". The VLM was emitting parent-tier labels
("Women's clothing", "Men's clothing", "Women's shoes", "Men's
shoes") but the mapping table only had Vinted-style leaves
(`tshirts`, `jackets`, `jeans`).

**`scripts/probe_ka_categories.py`** uses the live KA mobile session
to call `/api/categories.json` and `/api/ads/metadata/{cat_id}.json`
for each candidate parent. The probe revealed:

| English | KA leaf | Per-category prefix | art enum size |
|---|---|---|---|
| Women's clothing | 154 (Damenbekleidung) | `kleidung_damen` | 15 |
| Men's clothing | 160 (Herrenbekleidung) | `kleidung_herren` | 13 |
| Women's shoes | 159 (Damenschuhe) | `schuhe_damen` | 9 |
| Men's shoes | 158 (Herrenschuhe) | `schuhe_herren` | 7 |

The probe also surfaced that the existing **condition slugs were
wrong** in the codebase (`new_etikett`, `good`) — KA's actual enum
is `new_with_tag/new/like_new/ok/alright`. And the **color
attribute** required lowercase German enum slugs
(`rose`, not `Rosé`; `schwarz`, not `Schwarz`) — distinct from the
display names the existing `COLOR_EN_TO_KA_DE` table returned.

After three iterative fixes (category, condition, color), the first
successful KA publish landed at
**`https://www.kleinanzeigen.de/s-anzeige/3405034173`** — verified
via direct SQL on the production DB.

**Edit endpoint discovery.** OPTIONS on
`/api/users/{user_id}/ads/{ad_id}.json` returned
`Allow: GET,HEAD,DELETE,PUT,OPTIONS`. So edit (PUT) and delete
(DELETE) work on the same URL the create POST goes to. Pictures
must be preserved by re-fetching them via GET and re-attaching to
the PUT body — implemented via `KAClient.get_listing_picture_links`.

**Files:** `backend/integrations/kleinanzeigen.py` (910+ lines),
`docs/ka_endpoints.md` (320-line reference distilled from captures),
`docs/ka_category_probe.json` (audit trail of the discovery).

### 4.3 Programmatic API discovery via `OPTIONS` + minimal-body probes

Across both platforms we developed a generic probe pattern:

```python
# 1. OPTIONS to discover allowed verbs
r = client.http.request("OPTIONS", url, headers=auth_headers)
allow = r.headers.get("Allow")  # e.g. "GET,HEAD,DELETE,PUT,OPTIONS"

# 2. For each allowed write verb, send a minimal body
r = client.http.request("PUT", url, json={"item": {"title": "x"}})
# 200 → verb works as-is
# 400 with field-by-field hints → verb works, payload incomplete
# 403/405 → verb rejected, try a different URL
```

This caught the right Vinted edit endpoint
(`/api/v2/item_upload/items/{id}`) on the **second probe attempt**,
faster than wading through Vinted's mobile-app traffic capture.
**Insight: validation errors are the cheapest API spec.**

### 4.4 Bringing the model adapter into prod

The VLM is served by **RunPod Serverless** — the worker is a Docker
image that loads the Qwen3-VL base + LoRA adapter at startup, then
serves async forward passes via the standard RunPod `/run` +
`/status/{id}` polling protocol. Our backend's `RunpodHTTPVLM`
client implements the polling under a single `await
predict(image, platform, hints, label_image)` call, absorbing
cold-start latency (~5–15 min on first worker boot) inside one
client-visible promise.

Every adapter retrain is a pull-request on `runpod/handler.py`
changing the `ADAPTER_ID` env default + a worker rebuild on
RunPod's UI. The backend doesn't need redeployment — it just
points at whichever endpoint URL is configured in `.env.prod`.

---

## 5. Notable engineering decisions

### 5.1 Bind-mount Docker for backend deploys (Day 5)

**Problem.** Backend deploys took ~5 minutes per cycle even for
one-line code changes — the pip install layer is ~3 GB resolved
(torch + transformers + pandas + sklearn + ...) and even with the
layer cache, a `COPY`-only rebuild still spent 30–60s on layer
commits + container recreation.

**Solution.** Stop baking application code into the image.
Bind-mount `/opt/resell/app/{backend,shared,models}` into the running
container at `/app/{backend,shared,models}`. Code changes become:

```bash
ssh ec2 'cd /opt/resell/app && git pull && sudo docker restart resell-backend'
```

**Result:** **5 min → ~10 seconds** for code-only deploys
(measured `ec2_redeploy.sh` end-to-end at 10.2s). Image is rebuilt
only when `requirements-prod.txt` or the `Dockerfile` itself
changes.

**Architecture decision:** the image is dep-only, not "app + deps".
The host's git checkout is the single source of truth for what code
is running. Two scripts: `scripts/ec2_redeploy.sh` (fast path,
~10s) and `scripts/ec2_rebuild.sh` (slow path, ~3-5 min).
Single canonical `docker run` flag set lives in `ec2_rebuild.sh`
only.

### 5.2 Per-platform identification block, single canonical store

The VLM is called twice per upload — once with `platform=vinted` and
once with `platform=kleinanzeigen`. The two prompts have **different
category vocabularies**:

```python
VINTED_CATEGORIES_EN        = ["jackets", "jeans", "tshirts", "sneakers"]
KLEINANZEIGEN_CATEGORIES_EN = ["Women's clothing", "Men's clothing",
                                "Women's shoes",   "Men's shoes"]
```

Vinted-side emits Vinted-friendly leaves; KA-side emits parent-tier
labels (since KA's mobile API resolves leaves at submit-time via
the per-category attribute schema). The pipeline keeps both
platform-specific identification blocks separately in the
`UploadResponse`, and the frontend's edit/publish flow always sends
the right block for the right platform.

This was deliberate: trying to force a single canonical category
vocabulary onto both platforms either lost gender information
(critical for KA's brand/size accuracy) or broke Vinted's strict
leaf-ID enforcement.

### 5.3 Async PublishRunner with retry/backoff

The publish flow couldn't be synchronous — Vinted's draft completion
takes 3–8 seconds warm and up to 30s on cold start, and we don't
want a frontend HTTP request to hang that long. Solution:

- **`POST /publish`** enqueues a row in the `publishes` table with
  `status='pending'` and returns a `job_id` immediately (HTTP 202).
- **`PublishRunner`** is an in-process async loop that polls for
  pending jobs, claims one, dispatches to the platform integration,
  and updates the row's status (`running` → `posted` / `failed`).
- **Retry logic:** transient errors (`VintedBlocked` for DataDome
  429s, network timeouts) re-queue with exponential backoff. Hard
  errors (validation, auth) go straight to `failed` with the
  message stored in the `error` column.
- **Frontend polls** `/publish/status/{job_id}` every 1.5s with a 90s
  budget.

### 5.4 Inventory edit pushes to live platforms in parallel

The "Change price" modal stores locally **and** pushes the new price
to every posted platform. Originally we awaited each platform call
sequentially — for a listing posted to both Vinted and KA, that's
~6–16 seconds wall-clock. The /simplify pass replaced this with:

```python
async def _push_one(platform, platform_id):
    try: ...
    except: ...

results = await asyncio.gather(
    *(_push_one(p, pid) for p, pid in targets)
)
```

Halves the latency for dual-platform listings. The frontend
modal stays open during the call, shows per-platform ✓/✗ result
lines after the response, and auto-closes 1.2s after a fully
successful save (stays open with the error visible if any platform
push failed).

### 5.5 Failing loud over silent fallback

A real bug we caught: KA's `submit_listing` had a silent fallback
that returned the user's KA dashboard URL if the response was
unparseable, with the runner happily marking the job `posted`. So
users would click a "your listing is live" link and land on their
own dashboard — listing potentially never created. Vinted's
equivalent crashes on the same condition; KA was the asymmetric one.

**Fix:** replace the silent fallback with `raise KAError(f"listing
submit: no listing id in response (Location={loc!r}, body_keys=...)")`.
The error message includes diagnostic data so a single log line
identifies what's wrong on the next failure.

This pattern — **fail loud with diagnostic context** — surfaced two
subsequent KA bugs (color slug `rosé` vs `rose`, condition slug
`good` vs `ok`) within minutes of each other, because the user could
see the actual KA API error in the new ResultsScreen banner instead
of staring at a silent UI.

### 5.6 Vinted display URLs decoupled from API base URL

Vinted's session cookies are tied to a specific regional domain
(`vinted.fr` in our case — that's where the captured Auth0 session
is valid). But users wanted shareable `vinted.com` URLs. The fix
took 1 line:

```python
# vinted.py:512
listing_url = f"https://www.vinted.com/items/{item_id}"
# (used to be f"{self.base_url}/items/{item_id}")
```

The internal `self.base_url` (used for all API calls) stays
`vinted.fr`. Vinted normalises `/items/{id}` to the viewer's regional
domain on resolve, so `vinted.com/items/...` works for everyone.

### 5.7 Probe scripts as a discovery primitive

For both KA and Vinted we wrote one-off `scripts/probe_*.py` files
that:
1. Load the live session (via the same code path the backend uses).
2. Hit candidate endpoints with OPTIONS + GET + minimal-body probes.
3. Dump structured findings to `docs/*_probe.json` for audit.

These probes are **committed** alongside the integrations they
informed. If the platforms change their APIs, the probe scripts are
the cheapest way to re-discover the new shape.

---

## 6. Production deployment

### 6.1 Frontend — Vercel

- **Vercel CLI deploy** from `frontend/`: `vercel deploy --prod --yes`
  → ~30s to live at `resell-copilot-three.vercel.app`.
- **Middleware password gate** (`frontend/src/middleware.ts`) checks
  an httpOnly `resell-auth=ok` cookie; missing → redirects to
  `/login` page. Single shared password (env var `APP_PASSWORD`).
- **PWA install-readiness:** manifest, icons, service worker registered
  at root. Mobile users can "Add to Home Screen" and the app launches
  fullscreen.
- **No auto-deploy on push** — Vercel for this project is configured
  for **manual CLI deploys only** (deliberate: deploys are gated on a
  passing local `npm run build`, not on every push).

### 6.2 Backend — AWS EC2

- **AWS EC2 t2.small** (Ubuntu 26.04, 2 GB RAM, 16 GB EBS).
  Free-tier eligible.
- **Docker container** runs FastAPI + uvicorn on internal port 8000.
- **Code bind-mounted** from `/opt/resell/app/` (host) — `git pull
  && docker restart` deploys in 10s.
- **Nginx** as TLS terminator + reverse proxy. Let's Encrypt cert
  managed via certbot with auto-renewal cron.
- **DuckDNS** for the dynamic DNS — `resell-copilot.duckdns.org`
  resolves to the EC2 elastic IP (`13.49.21.29`).
- **SQLite** at `/opt/resell/data/resell.db` (persists outside the
  container so restarts don't lose data).

### 6.3 VLM serving — RunPod Serverless

- **Container image** built from `runpod/handler.py` — loads
  Qwen3-VL-4B + the `multi-v3` LoRA adapter at worker startup
  (~5–15 min cold-start, then warm; loaded in bf16).
- **Async protocol:** `POST /run` → `job_id` → poll
  `/status/{job_id}` until COMPLETED. Backend's `RunpodHTTPVLM`
  client encapsulates this in one async `predict()` call.
- **Auto-scales** to zero when idle. We don't pre-warm — typical demo
  flow has natural delays that absorb cold-start.

### 6.4 Per-deploy cycle time

| What changed | Deploy verb | Time |
|---|---|---|
| Frontend (any) | `vercel deploy --prod --yes` | ~30s |
| Backend Python code | `ssh ec2 ec2_redeploy.sh` (bind-mount restart) | ~10s |
| Backend deps (`requirements-prod.txt`) | `ssh ec2 ec2_rebuild.sh` (full image rebuild) | ~3-5 min |
| ML head checkpoints (`.pt` files) | `scp` to `/opt/resell/checkpoints/` + restart | ~30s |
| VLM adapter | Mike rebuilds RunPod worker from `runpod/handler.py` | ~10 min |

---

## 7. Data + database schema

SQLite, six tables, all migrations idempotent at startup:

| Table | Purpose | Key columns |
|---|---|---|
| `listings` | Per-upload row | id (uuid), image_path, label_image_path, vlm_backend, created_at |
| `predictions` | Multi-row append-only history per listing | id, listing_id, source ('upload'/'verify'/'edit'), english_fields (JSON), per-platform price quantiles, sell_prob, visual_wear_probability, latency_ms |
| `edits` | Audit trail of user-corrected fields | listing_id, field_name, old_value, new_value |
| `publishes` | Per-publish-attempt job state | id, listing_id, platform, final_fields (JSON), status, retry_count, platform_listing_id, platform_listing_url, error |
| `wardrobe_snapshots` | Fetched live state of posted Vinted items | platform_listing_id, title, price_eur, views, favourites, fetched_at |
| `wardrobe_syncs` | Wardrobe sync attempts | platform, started_at, finished_at, status, item_count, error |

The `predictions` table is **append-only** — every /upload writes
one row, every /verify writes another, every PATCH /listings/{id}/fields
writes a third. The frontend always reads "the latest" via
`get_latest_prediction()`. This gives us free auditability without
needing a separate audit table.

---

## 8. Outcomes + metrics

### 8.1 What works at submission time

- **Full upload → publish loop** on both Vinted (5 successful
  publishes in production) and Kleinanzeigen (1+ successful
  publishes after all the API debugging).
- **Inventory management** — Open / Change price / Relist / Mark sold
  / Delete; price + delete actions push to live platforms in parallel.
- **Re-inference via /verify** — user corrects a field, full pipeline
  re-runs in ~5s with the correction baked in.
- **Multi-image upload** — optional brand/size tag photo improves
  brand accuracy +20pp and size accuracy +19pp (Mike's eval).
- **123 backend tests passing.**

### 8.2 Model performance (per Mike's eval logs)

- **VLM (`multi-v2` → `multi-v3`):** KA clean parse rate **100%**
  (was 40.9% on `multi-v1`); `multi-v3` adds KA listings to the
  training manifest and improves per-field accuracy on every test-set
  platform vs. `multi-v2` (deltas in `model_stack_evolution.md` §4.4).
- **PriceHead:** test coverage 85.8% (target 80%); median MAPE
  Vinted -7.8 pp + KA -4.5 pp vs. previous head.
- **Brand accuracy with label photo:** +20pp vs. cover-only.
- **Size accuracy with label photo:** +19pp vs. cover-only.

### 8.3 Cost

| Item | Spend |
|---|---|
| External API (Groq + RunPod, training + inference) | **~$3.50** |
| AWS EC2 (free tier t2.small) | $0 |
| Vercel (free tier hobby) | $0 |
| HuggingFace (model hosting, free) | $0 |
| **Total** | **~$3.50** |

---

## 9. Limitations + future work

| Limitation | Mitigation/future |
|---|---|
| **Single user** — auth is one shared password on Vercel + one Vinted/KA session per platform | True multi-user requires per-account session storage + Auth0/Clerk integration; out of scope for course project |
| **KA shoe categories not mapped beyond clothing** | Probe script can extend; just need a captured shoe-listing example to confirm the leaf IDs |
| **Vinted brand changes restricted** by platform | Vinted's own constraint — would need delete + re-publish for brand edits |
| **No live price-band recompute on PATCH** | PATCH stores fields without re-running the price head; user explicit `/verify` re-runs the pipeline. Trade-off: cheap edits vs. fresh price band |
| **No support for sneaker sizes on Vinted** | Vinted uses size_group 7 with size IDs we'd need to capture by creating throwaway listings; deferred |
| **English-only frontend** | All copy is hardcoded in TypeScript; i18n is a 2-day refactor we decided to skip |
| **No retry UX on publish failure** | Errors surface in the ResultsScreen banner; user manually re-publishes |
| **Inventory list isn't paginated** | 8 listings in prod so far; would need cursor pagination for >100 |

### 9.1 Model adapter — current state & next step

The **`multi-v3`** retrain (KA-inclusive manifest) shipped 2026-05-11
and is the adapter in production — it closed the field-accuracy gap
the v2 field-eval surfaced for Kleinanzeigen (per-field deltas in
`docs/model_stack_evolution.md` §4.4). The next obvious step is
extending the canonical category vocabulary beyond the current four
(`tshirts / jackets / jeans / sneakers`) — each new category needs
training data plus Vinted catalog-ID and KA leaf-ID mappings.

---

## 10. Tech stack summary

| Layer | Tech |
|---|---|
| **Language** | Python 3.11 (backend), TypeScript (frontend) |
| **Backend framework** | FastAPI 0.115 + uvicorn |
| **Database** | SQLite (via aiosqlite) |
| **ORM/queries** | Hand-written SQL (no ORM — schema is small enough) |
| **Frontend framework** | Next.js 14 (App Router) |
| **Frontend styling** | Inline styles + oklch color tokens (no Tailwind / CSS-in-JS lib) |
| **HTTP client (backend)** | httpx (async + sync) |
| **ML framework** | PyTorch 2.3 (CPU), HuggingFace transformers, peft (for LoRA) |
| **VLM** | Qwen3-VL-4B-Instruct (base) + custom LoRA adapter |
| **DINOv2** | facebook/dinov2-base (frozen) |
| **External LLM** | Groq Llama 3.1 8B (Model #6 description) |
| **VLM serving** | RunPod Serverless (Docker container, async polling) |
| **Container orchestration** | Single Docker container on EC2, bind-mount for code |
| **Reverse proxy + TLS** | Nginx + Let's Encrypt (certbot auto-renewal) |
| **Frontend hosting** | Vercel (manual CLI deploys, password gate via middleware) |
| **DNS** | DuckDNS (free dynamic DNS for EC2 elastic IP) |
| **VCS** | GitHub — `main` is the submission/deployable branch |
| **Sessions** | Pickled Vinted/KA session JSON, materialised from env vars at container startup |

---

## 11. Repo structure

```
Advanced_ML/
├── backend/                       # FastAPI app
│   ├── main.py                    # App factory, startup hooks, CORS
│   ├── bootstrap.py               # Loads DINOv2 + 3 head checkpoints
│   ├── pipeline.py                # Orchestrates VLM + heads + description
│   ├── description.py             # Model #6 (Groq) + template fallback
│   ├── db.py                      # aiosqlite + migrations
│   ├── schemas.py                 # Pydantic request/response models
│   ├── routes/                    # FastAPI routers
│   │   ├── upload.py              # POST /upload (multipart)
│   │   ├── verify.py              # POST /verify (hint-driven re-inference)
│   │   ├── publish.py             # POST /publish, GET /publish/status, DELETE
│   │   ├── inventory.py           # GET /inventory, PATCH/DELETE /listings/{id}
│   │   └── onboarding.py          # Vinted+KA login flows
│   ├── integrations/              # Per-platform API clients
│   │   ├── vinted.py              # 738 lines — DataDome + draft flow
│   │   └── kleinanzeigen.py       # 910 lines — Auth0 + JAXB-XML
│   ├── vlm_backend/               # VLM dispatch
│   │   ├── runpod_http.py         # Production: RunPod Serverless client
│   │   ├── local_mps.py           # Local-dev: in-process MPS
│   │   └── stub.py                # Tests: deterministic fake
│   └── queue/runner.py            # Async PublishRunner with retry/backoff
├── shared/                        # Used by both backend and training
│   ├── prompts.py                 # VLM prompt templates per platform
│   ├── translations.py            # DE↔EN field translation tables
│   └── listing_mappings.py        # Canonical fields → platform payloads
├── models/                        # Training scripts + checkpoints
│   ├── train_flaw_head.py
│   ├── train_price_head.py
│   ├── train_sell_head.py
│   ├── train_vlm.py               # QLoRA fine-tune Qwen3-VL
│   ├── extract_features.py        # DINOv2 features for head training
│   ├── extract_vlm_features.py    # VLM hidden states for head training
│   └── checkpoints/               # gitignored .pt files
├── runpod/handler.py              # RunPod Serverless worker
├── frontend/                      # Next.js 14 SPA
│   └── src/
│       ├── middleware.ts          # Password gate
│       ├── app/                   # Next.js App Router
│       │   ├── page.tsx           # Main screen state machine
│       │   └── login/page.tsx     # Password entry
│       ├── components/            # UploadScreen, ResultsScreen, InventoryScreen, ...
│       ├── api/                   # Typed client functions per route
│       ├── lib/                   # Shared constants/helpers (e.g. platforms.ts)
│       └── types/api.ts           # Shared TS interfaces
├── scripts/
│   ├── ec2_rebuild.sh             # Slow-path deploy (full image rebuild)
│   ├── ec2_redeploy.sh            # Fast-path deploy (bind-mount restart)
│   ├── probe_ka_categories.py    # Discovery: KA category tree + attribute schemas
│   ├── probe_ka_edit.py           # Discovery: KA edit/delete verbs
│   └── probe_vinted_edit.py       # Discovery: Vinted edit endpoint
└── docs/
    ├── deploy_plan.md             # Full deploy runbook
    ├── ka_endpoints.md            # KA mobile API reference
    ├── ka_category_probe.json     # Audit of KA category discovery
    ├── model_stack_evolution.md   # Per-version model history
    ├── ai_usage_log.md            # Prompt-by-prompt collaboration log
    └── technical_report.md        # This document
```

---

## 12. Submission summary (one paragraph)

Resell Copilot is a 7-day Nova SBE Advanced ML project that turns
one photo of a second-hand clothing item into a live listing on
Vinted and Kleinanzeigen in roughly 6–10 seconds. The system layers
six trained models (a Qwen3-VL-4B identification model with a custom
LoRA adapter, three specialised MLP heads for wear/price/sell-through,
DINOv2 visual features, and a Groq-served description generator),
reverse-engineers the mobile APIs of both marketplaces (including
DataDome bypass for Vinted and Auth0 + SMS MFA + JAXB-XML for
Kleinanzeigen), and ships in production on AWS EC2 + Vercel + RunPod
Serverless with a 10-second backend deploy cycle via bind-mount
Docker. Total external API spend: $3.50. The work pattern that mattered
most was **plan mode before implementation** (caught issues 4-for-4
times before code was written) and **idempotent caches at every step**
(made every long-running artifact re-entrant). The most interesting
engineering moments were two iterative API-discovery sessions that
turned silent platform failures into visible, actionable errors —
KA's category-mapping bug (40.9% parse rate jumped to 100% after a
prompt + adapter retrain) and the Vinted vs. KA edit-verb probe that
unlocked direct in-place price editing on live listings. A complete
prompt-by-prompt collaboration log of human + Claude Opus 4.7 (1M
context) is preserved in `docs/ai_usage_log.md`.
