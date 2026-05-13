# Resell Copilot

**Photo-first selling assistant for second-hand clothing.** Upload a photo and get brand, category, condition, a per-platform price band (Vinted + Kleinanzeigen), a sell-likelihood score, and a generated listing. One tap publishes the item directly to either platform — or both at once — through their mobile APIs.

> **Course:** 2758-T4 Advanced Machine Learning · Nova SBE final project (Pair A)

| | |
|---|---|
| **Live app** | <https://resell-copilot-three.vercel.app> |
| **Backend API** | <https://resell-copilot.duckdns.org> |
| **VLM adapter** | [`mchlkan/qwen3vl4b-resell-adapter-multi-v3`](https://huggingface.co/mchlkan/qwen3vl4b-resell-adapter-multi-v3) on HuggingFace |
| **Tech report** | [`docs/technical_report.md`](docs/technical_report.md) |

---

## Contents

- [What it does](#what-it-does)
- [Try it on your iPhone — install as a Home Screen app](#try-it-on-your-iphone--install-as-a-home-screen-app)
- [System architecture](#system-architecture)
- [Stack](#stack)
- [Repo layout](#repo-layout)
- [Local development](#local-development)
- [VLM backends](#vlm-backends)
- [Production deployment](#production-deployment)
- [Direct publishing — Vinted & Kleinanzeigen](#direct-publishing--vinted--kleinanzeigen)
- [Models](#models)
- [Evaluation](#evaluation)
- [Tests](#tests)
- [Documentation index](#documentation-index)
- [Known limitations](#known-limitations)

---

## What it does

The whole loop is photo → published listing in under a minute on a warm GPU. The user takes one or two photos of an item (the second is optional and is used for the brand/size tag); the backend pipelines six models in roughly the following order:

1. A fine-tuned vision–language model (Qwen3-VL-4B + LoRA adapter) reads the photo and emits structured fields: brand, category, condition, colour, size, material, plus a free-form description hint.
2. A frozen DINOv2 backbone extracts a flaw-relevant feature vector for the condition head.
3. A small per-platform price head (MLP, 5-quantile pinball loss) takes the VLM's pooled hidden state plus the structured fields and predicts a price band (q10/q50/q90) for Vinted and Kleinanzeigen separately.
4. A sell-likelihood head scores how likely the item is to sell within 30 days at the suggested price.
5. A listing-copy generator (Groq Llama 3.1 8B Instant, with deterministic template fallbacks) writes the title and description in the platform-appropriate style and language (English on Vinted, German on Kleinanzeigen).

The user reviews and tweaks the result on a clean mobile-first UI, drags a price slider inside the predicted band, and taps publish. The publish runner (background async queue) calls each platform's mobile API and returns a live listing URL. A wardrobe tab shows everything ever published; deletion and field edits propagate back to the platforms.

The whole front-end is a Progressive Web App (PWA) — installable on iPhone and Android with a real standalone-app experience, no App Store required.

---

## Try it on your iPhone — install as a Home Screen app

The website is a fully-configured PWA. When you "Add to Home Screen" on iOS, you get a real standalone app: full-screen (no Safari chrome), its own icon, status bar styled to the brand, and proper portrait orientation lock. There's no App Store install — Apple has supported this since iOS 11.3 and it costs nothing.

### Step-by-step (iPhone, Safari)

You **must** use Safari for this — Chrome / Firefox on iOS use a sandboxed WebKit and don't expose the "Add to Home Screen" hook reliably.

1. Open **Safari** and go to <https://resell-copilot-three.vercel.app>.
2. Tap the **Share** button at the bottom of the screen (the square with an arrow pointing up).

   <sub>(If your Safari toolbar is at the top, the Share button is in the same place — top-right on iPad, top-centre after a recent iOS update.)</sub>

3. Scroll the share sheet down until you see **"Add to Home Screen"** (the icon is a square with a `+` inside). Tap it.
4. iOS pre-fills the name as "Resell Copilot" and shows the app icon. Edit the name if you want, then tap **Add** in the top-right.
5. The app icon now sits on your Home Screen. **Tap it** — the app opens full-screen, with no URL bar, no tab strip, and the camera button works the same as in Safari.

### What you actually get

- **Full-screen, no browser chrome.** The app behaves like any native iOS app once launched from the Home Screen icon.
- **Camera access.** Tapping the photo button opens the iPhone camera or photo picker the same way native apps do (iOS prompts for permission the first time).
- **Portrait-locked.** The PWA manifest sets `orientation: portrait`, so the app stays upright the way the UI is designed.
- **Themed status bar.** The status bar adopts the app's warm-off-white theme (`#fafaf8`) so it blends in instead of looking pasted-on.
- **Persistent login.** Your session and any in-progress listings stay between launches.
- **One important caveat — there are no push notifications.** Apple's WebKit doesn't support web-push for sites added to the Home Screen on iOS 16 or below; iOS 16.4+ added it but only for sites the user explicitly grants notification permission to. Resell Copilot doesn't currently use push at all, so this is moot — but if a future feature relies on background pings (e.g. "your item just sold"), iOS will require an extra permission tap.

### Removing the app

Long-press the icon on the Home Screen → **Remove App** → **Delete from Home Screen**. This only removes the shortcut and the cached site data; nothing is uninstalled at the OS level.

### Android (for completeness)

Open the same URL in **Chrome** on Android, tap the **⋮** menu → **Install app** (or **Add to Home Screen**). The PWA installs into the app drawer with the same icon and standalone behaviour. Chrome will sometimes also prompt with an install banner the second or third time you visit.

### Why a PWA, not an App Store binary

For a course project the answer is obvious — distribution friction is zero, no developer-account fee, no review queue, no native build. The trade-offs (no push on iOS, no background tasks, no access to the platform's contact / payment frameworks) don't bind on this product, so the PWA path was the right call.

---

## System architecture

```
┌──────────────────────────┐         ┌──────────────────────────────────┐
│  iPhone PWA / browser    │  HTTPS  │  EC2 (Stockholm, t2.small)        │
│  (Next.js, Vercel CDN)   │ ──────▶ │  Nginx + Let's Encrypt TLS        │
│                          │         │  ┌────────────────────────────┐  │
│  resell-copilot-three    │         │  │ FastAPI app (Docker)       │  │
│   .vercel.app            │ ◀────── │  │  • /upload  /verify        │  │
└──────────────────────────┘   JSON  │  │  • /publish (async queue)  │  │
                                     │  │  • /inventory  /onboarding │  │
                                     │  │  • DINOv2 + price/sell heads│ │
                                     │  └─────────┬──────────────────┘  │
                                     │            │                     │
                                     │  SQLite ◀──┘ (predictions, edits,│
                                     │              publishes, sessions)│
                                     └────────────┬─────────────────────┘
                                                  │ HTTPS (RunPod /run + /status)
                                                  ▼
                                     ┌──────────────────────────────────┐
                                     │  RunPod Serverless (EU region)    │
                                     │  Qwen3-VL-4B + LoRA adapter v3    │
                                     │  bf16, RTX 4090 / A5000 / 6000Ada │
                                     │  Docker: ghcr.io/rengo33/         │
                                     │           resell-vlm:latest       │
                                     └──────────────────────────────────┘

         Listing copy:    Groq llama-3.1-8b-instant   (called from EC2)
         Publishing:      Vinted + Kleinanzeigen mobile-API clients
                          (called from EC2; reverse-engineered)
```

All user data — photos, predictions, listings — stays in the EU inference path.

---

## Stack

| Layer | Tech |
|---|---|
| Frontend | TypeScript / Next.js 14 (App Router) on Vercel, PWA-installable |
| Backend | Python 3.11 / FastAPI, async, on AWS EC2 (`eu-north-1`) |
| Database | SQLite with WAL (predictions, edits, publishes, sessions) |
| Vision–language model | Qwen3-VL-4B-Instruct + LoRA adapter ([`mchlkan/qwen3vl4b-resell-adapter-multi-v3`](https://huggingface.co/mchlkan/qwen3vl4b-resell-adapter-multi-v3)) |
| Vision features | DINOv2-base (frozen) for the condition head |
| Listing copy | Groq `llama-3.1-8b-instant`, with deterministic template fallbacks |
| Production VLM serving | RunPod Serverless (bf16 on RTX 4090 / A5000 / 6000 Ada class GPUs, EU region) |
| TLS / DNS | Nginx + Let's Encrypt + DuckDNS (`resell-copilot.duckdns.org`) |

---

## Repo layout

```
Advanced_ML/
├── data/                  # parquet datasets + locked train/val/test splits (gitignored except split manifests)
├── data_prep/             # offline data pipeline (translate → splits → targets → merge)
├── models/                # training scripts: VLM LoRA, price head, sell head, condition head
│   └── checkpoints/       # local model weights (gitignored)
├── eval/                  # baseline runners + Qwen field eval (+ results JSONs in eval/results/)
├── backend/               # FastAPI app
│   ├── routes/            # /upload  /verify  /publish  /onboarding  /inventory  /vlm/status
│   ├── integrations/      # Vinted + Kleinanzeigen mobile-API clients (reverse-engineered)
│   ├── vlm_backend/       # pluggable VLM backends: stub / local_mps / runpod_http
│   ├── queue.py           # PublishRunner background task (async retry/backoff)
│   ├── db.py              # SQLite schema + helpers (predictions, edits, publishes, sessions)
│   └── tests/             # pytest, 123 tests, respx-mocked RunPod scenarios
├── runpod/                # Dockerfile + Python handler for the RunPod Serverless worker
├── shared/                # shared between backend + RunPod handler (prompts, mappings, schemas)
├── frontend/              # Next.js TypeScript app
│   ├── public/            # PWA manifest, icons, service worker
│   ├── src/api/           # typed fetch wrappers (one module per backend route group)
│   ├── src/components/    # screen components (Upload / Analyzing / Results / Publishing / Inventory …)
│   ├── src/lib/           # shared frontend utilities (platform tokens, formatting)
│   └── src/app/           # App Router entrypoints + global layout (PWA metadata)
├── scripts/               # one-off utilities: ec2 deploy, eval_lora, KA/Vinted endpoint probes
├── docs/                  # technical report, AI-usage log, model-stack evolution, demo strategy
├── notebooks/             # 01_…_data, 03_…_train, 06_…_eval, 99_scratch
├── requirements.txt       # backend + training dependencies
├── requirements-prod.txt  # backend-only dependencies (slimmer container build)
└── CLAUDE.md              # project instructions for AI pair-programming sessions
```

---

## Local development

### Prerequisites

- Python 3.11
- Node.js 20+
- (Optional) An Apple Silicon Mac with ≥ 16 GB unified memory if you want to run the VLM locally on MPS

### Backend setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The maintainer of this repo uses **conda** (`conda activate resell-copilot`); other contributors can use plain `pip + venv`. Either works — `requirements.txt` is the source of truth.

Create a `.env` at the repo root (gitignored):

```bash
# Production VLM serving (runpod_http backend):
RUNPOD_API_KEY=rpa_...
RUNPOD_ENDPOINT_ID=...

# Required for local_mps backend and the worker container (gated HF repos):
HF_TOKEN=hf_...

# Listing-copy generation (Model #6) — without it /upload falls back to template copy:
GROQ_API_KEY=gsk_...

# Optional — only used by the LLM-as-judge eval baselines:
OPENAI_API_KEY=sk-...

# Optional — for direct Vinted publishing via /publish:
VINTED_SESSION_PATH=/path/to/.vinted-session.json
VINTED_DATADOME_SEED=...
VINTED_ANON_ID=...
VINTED_DEVICE_UUID=...
VINTED_DEVICE_TOKEN=...

# Optional — for direct Kleinanzeigen publishing:
KA_SESSION_PATH=/path/to/.ka-session.json
```

Run the backend:

```bash
# Stub backend — no GPU, deterministic fakes, instant /upload, fastest dev loop:
uvicorn backend.main:app --reload

# Local MPS — runs Qwen3-VL on Apple Silicon, ~10–15 s/call, needs ~12 GB free RAM:
VLM_BACKEND=local_mps uvicorn backend.main:app --reload

# RunPod — production path; calls a Serverless endpoint over HTTP:
VLM_BACKEND=runpod_http RUNPOD_TIMEOUT_S=900 uvicorn backend.main:app --port 8000
```

Send a test request:

```bash
curl -F "image=@some_jacket.jpg" http://localhost:8000/upload | jq
```

### Frontend setup

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Open <http://localhost:3000>. The frontend talks to whichever backend `NEXT_PUBLIC_API_URL` points at — for production it's `https://resell-copilot.duckdns.org`, but any backend served over HTTPS (or `http://localhost:8000` for local dev) works.

To exercise the PWA install path locally, build and serve the production bundle:

```bash
npm run build
npm run start                # serves on http://localhost:3000
```

PWA install works on `localhost` even without HTTPS (browsers exempt `localhost` from the secure-context requirement).

---

## VLM backends

Selected via the `VLM_BACKEND` env var. All three implement the same `/upload` contract.

| Backend | Where it runs | Latency | When to use |
|---|---|---|---|
| `stub` (default) | In-process | < 50 ms | Frontend dev, CI, no-GPU machines |
| `local_mps` | In-process (Mac MPS) | 10–15 s | Single-user dev with a 16 GB+ Mac, no RunPod credit |
| `runpod_http` | RunPod Serverless | 3–6 min cold / 3–20 s warm | Production, demo, multi-user |

The stub returns deterministic placeholder fields and a `(2560,)` hidden state seeded from the image hash — fine for verifying frontend wiring without spending GPU minutes. Tests run with `VLM_BACKEND=stub` so the suite is hermetic.

The `runpod_http` backend long-polls the RunPod `/status` endpoint with a 900 s timeout, which absorbs even a worst-case cold start without raising. The frontend's Analyzing screen polls `GET /vlm/status` every 6 s during the wait and surfaces a "warming up" / "queued" state to the user via the worker counts that endpoint exposes.

---

## Production deployment

The deployment has three independently-scaled tiers, each with its own deploy story.

### Frontend → Vercel

```bash
cd frontend
vercel deploy --prod
```

Vercel reads `NEXT_PUBLIC_API_URL` from the project settings and bakes it into the build. The hobby plan covers all current traffic; Pro is on the upgrade path if bandwidth becomes the limit. Custom alias is `resell-copilot-three.vercel.app`.

### Backend → AWS EC2 (Docker + Nginx + Let's Encrypt)

A `t2.small` instance in `eu-north-1` (Stockholm) runs the FastAPI backend in Docker, fronted by Nginx with Let's Encrypt TLS termination at `resell-copilot.duckdns.org`. The SQLite DB lives on the host at `/opt/resell/data/resell.db` and is bind-mounted into the container. Nginx is configured with `proxy_read_timeout 900s` to match the RunPod cold-start budget.

To redeploy after a code change on the local repo:

```bash
./scripts/ec2_redeploy.sh
```

The script `rsync`s the changed files, restarts the container, and tails the logs until `/health` returns 200.

### VLM → RunPod Serverless

Full deploy steps in [`runpod/README.md`](runpod/README.md). Quick summary:

```bash
docker buildx build --platform linux/amd64 \
  -f runpod/Dockerfile \
  -t ghcr.io/rengo33/resell-vlm:latest \
  --push .
```

Then in the RunPod dashboard: **Serverless → Endpoints → Create New Endpoint**, point at the GHCR image, and set the env vars. The container expects `HF_TOKEN` (gated-repo access) and the same `BASE_MODEL` / `ADAPTER_ID` / `MAX_NEW_TOKENS` overrides used during training.

#### Current production settings (verified working)

| Setting | Value | Why |
|---|---|---|
| Container image | `ghcr.io/rengo33/resell-vlm:latest` | GHCR private package |
| Container disk | 25 GB | 8 GB Qwen base + 50 MB adapter + cache headroom |
| GPU types allowed | 24 GB (1st), 48 GB (2nd) | Allows fallback when RTX A5000 pool is saturated |
| Min workers | 0 | Pay nothing when idle |
| **Max workers** | **1** | Two parallel calls per `/upload` would otherwise summon two workers; cap to 1 to avoid crash-loop fan-out. Bump to 2 only when stable. |
| Idle timeout | 5–60 s | Workers die quickly between calls; raise to 300+ for demo windows |
| FlashBoot | ON | Snapshots warm workers so cold starts don't redownload 8 GB |
| Env vars on endpoint | `HF_TOKEN`, optional `BASE_MODEL`, `ADAPTER_ID`, `MAX_NEW_TOKENS` | Adapter is gated; token must have access |

---

## Direct publishing — Vinted & Kleinanzeigen

`/publish` posts listings directly to the platform's mobile API — Vinted via the draft-mode flow (which bypasses DataDome on the protected submission endpoint), Kleinanzeigen via its Auth0-authenticated ad-create endpoint. A single tap can cross-post to both. Editing (`PATCH /listings/{id}/fields`) and deleting (`DELETE /listings/{id}`) propagate to whichever platforms the listing is live on.

### One-off bootstrap (Vinted)

Vinted's password endpoint requires a "high-trust" DataDome cookie that can't be minted from a clean IP — it has to come from a real Android device once. Use vinted-lister's existing CLI to extract the four phone-derived values via ADB:

```bash
cd ~/Projekte/Vinted/vinted-lister
python -m src.main extract-cookie
# prints datadome_cookie / anon_id / device_uuid / device_token
```

Drop those four values into resell-copilot's `.env`:

```bash
VINTED_DATADOME_SEED=<datadome cookie>
VINTED_ANON_ID=<anon id>
VINTED_DEVICE_UUID=<device uuid>
VINTED_DEVICE_TOKEN=<device token>
VINTED_SESSION_PATH=/path/to/.vinted-session.json   # where /onboarding/login will write
```

The seed values self-refresh indefinitely — extract once per machine.

### Login from the backend

```bash
curl -X POST http://localhost:8000/onboarding/login \
  -H 'content-type: application/json' \
  -d '{"platform": "vinted", "email": "you@example.com", "password": "..."}'
```

On success: returns `{platform, status:"ready", user_id, expires_at}` and writes the session JSON to `VINTED_SESSION_PATH`. The password is used once for the OAuth password grant and never logged or persisted.

```bash
curl http://localhost:8000/onboarding/status
# {"vinted": {"state": "ready", ...}, "kleinanzeigen": {"state": "ready", ...}}
```

### Publish behaviour (async)

`POST /publish` enqueues a job and returns 202 immediately:

```json
{"job_id": 42, "status": "pending", "listing_id": "abc123", "platform": "vinted"}
```

A background runner picks the job up, calls the platform, and updates its row in the `publishes` table. The frontend polls `GET /publish/status/{job_id}` every ~2 s and stops once `status` is `posted` or `failed`:

```json
{
  "job_id": 42, "status": "posted",
  "platform_listing_id": "1234567890",
  "platform_listing_url": "https://www.vinted.fr/items/1234567890",
  "retry_count": 0, "next_attempt_at": null,
  "error": null
}
```

Transient failures (DataDome 429, network blips) auto-retry with exponential backoff (`5 s → 30 s → 120 s`, configurable via `PUBLISH_RETRY_BACKOFF`). Permanent failures (auth expired, validation errors, missing config) skip retries and go straight to `status: failed` with a populated `error` field.

### Known publish-side gaps

- **Sneaker sizes are unmapped.** Sneakers (catalog 2632) use Vinted's `size_group=7`, whose IDs aren't recoverable without creating throwaway live listings. The mapper drops `size_id` for sneakers and the user picks the size on Vinted's confirmation page before going live.
- **Material is free-text.** Vinted has no public materials endpoint; `to_vinted` passes through `material` as-is (Vinted treats it as a hint string, not an enum).
- **Brand_id resolves dynamically.** First publish per unique brand hits `/api/v2/item_upload/brands?keyword=...` and caches the top-hit ID per process. Unknown brands fall back to free-text `brand`, which Vinted accepts but doesn't link to a brand page.

---

## Models

See [`docs/model_stack_evolution.md`](docs/model_stack_evolution.md) for the full development narrative across v1 → v2 → v3 of the LoRA adapter and the parallel iteration on the price/sell heads.

| # | Name | Architecture | Status |
|---|---|---|---|
| 1 | VLM identifier | Qwen3-VL-4B-Instruct + LoRA (multi-v3) | trained, deployed via RunPod |
| 2 | Flaw / wear head | DINOv2-base (frozen) + MLP | trained |
| 3 | Tag detector | folded into #1's prompt schema | n/a |
| 4 | Price head | MLP, 5-quantile pinball loss, per platform | trained |
| 5 | Sell-likelihood head | MLP binary classifier | trained |
| 6 | Listing-copy generator | Groq `llama-3.1-8b-instant` + deterministic template fallbacks | live |

The four trained categories are `tshirts / jackets / jeans / sneakers` — chosen for their combined weight of inventory on Vinted DE and Kleinanzeigen and for being visually distinct enough that one adapter generalises across them.

---

## Evaluation

```bash
python eval/run_baseline.py          # GPT-4o-mini / Claude Haiku baselines on the test set
python eval/run_qwen_field_eval.py   # field-level eval of the fine-tuned Qwen identifier
python scripts/eval_lora.py          # single- vs multi-image LoRA yardstick
```

Results land in `eval/results/*.json`. Headline metric: **price MAPE per platform**, our pipeline vs GPT-4o-mini. The price head currently sits at ~53% MAPE on the locked 500-row test set, against ~102% for GPT-4o-mini at the same task, and the field-level identification accuracy on brand / category / colour / condition tracks closely with the v3 adapter card on HuggingFace.

---

## Tests

```bash
.venv/bin/pytest backend/tests -q
```

123 tests cover the FastAPI routes (`/upload`, `/verify`, `/publish`, `/inventory`, `/onboarding`, `/vlm/status`), the SQLite logging schema (predictions, edits, publishes, sessions), and the VLM backends — including respx-mocked RunPod scenarios for cold start, FAILED status, timeout, malformed output, wrong hidden-state dimension, and worker error payloads. Tests run with `VLM_BACKEND=stub` and `DISABLE_PUBLISH_RUNNER=1` so they're hermetic and don't race the background queue.

---

## Documentation index

| File | What's in it |
|---|---|
| [`docs/technical_report.md`](docs/technical_report.md) | Course-deliverable technical report: data, models, evaluation, deployment |
| [`docs/model_stack_evolution.md`](docs/model_stack_evolution.md) | The v1 → v2 → v3 adapter story and the parallel head iteration |
| [`docs/cost_model.md`](docs/cost_model.md) | Token-level cost analysis and the prefill-fusion optimisation |
| [`docs/api.md`](docs/api.md) | Per-route request / response shapes |
| [`docs/deploy_plan.md`](docs/deploy_plan.md) | Three-tier deploy (Vercel + EC2 + RunPod), DNS, TLS, monitoring |
| [`docs/development.md`](docs/development.md) | Day-to-day dev workflow, conventions, gotchas |
| [`docs/ai_usage_log.md`](docs/ai_usage_log.md) | Course-required log of AI-pair-programming sessions |
| [`docs/demo_strategy.md`](docs/demo_strategy.md) | Live-demo playbook: warm-up routine, fallback story, items to bring |
| [`runpod/README.md`](runpod/README.md) | RunPod Serverless container build + endpoint config |

---

## Known limitations

- **Single-user architecture.** The prototype runs with one shared session per platform. A commercially deployable multi-user system needs per-account session storage and an OAuth-ish onboarding flow for users to authenticate their own marketplace accounts. This is the largest engineering gap between the prototype and a shippable product.
- **Reverse-engineered platform integrations.** Vinted (DataDome bypass) and Kleinanzeigen (Auth0 + JAXB-XML) talk to undocumented mobile-API endpoints. Either platform could change the contract at any time. The medium-term mitigation is an official Vinted Pro Integrations partnership; until then the integration is fragile by design.
- **No PWA push notifications on iOS.** Apple's WebKit only added web-push support in iOS 16.4+, and only with explicit per-site permission. Resell Copilot doesn't currently use push at all, so this doesn't bite — but a future "your item just sold" feature would need a permission grant per user, and is unavailable on older iOS versions.
- **Trained category vocabulary is four classes.** `tshirts / jackets / jeans / sneakers`. Out-of-vocabulary photos (e.g. dresses, watches) get classified into the nearest of the four, which is rarely useful. Expanding the vocabulary is the next obvious training run.
- **Sneaker sizes need a confirmation tap on Vinted.** See [Known publish-side gaps](#known-publish-side-gaps).
