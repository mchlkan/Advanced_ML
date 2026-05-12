# Resell Copilot

Photo-first selling assistant for second-hand clothing. Upload a photo → get brand/category/condition identification, per-platform price band (Vinted + Kleinanzeigen), sell-likelihood, and a generated listing. One click pre-fills the platform's listing form.

**Course:** 2758-T4 Advanced Machine Learning — Nova SBE final project (Pair A)

---

## Stack

| Layer | Tech |
|---|---|
| Frontend | TypeScript / Next.js (Node 20) |
| Backend | Python 3.11 / FastAPI |
| Database | SQLite |
| VLM | Qwen3-VL-4B-Instruct + LoRA adapter (`mchlkan/qwen3vl4b-resell-adapter-multi-v3`) |
| Vision features | DINOv2-base (frozen) |
| Listing copy | Groq `llama-3.1-8b-instant` (with deterministic template fallbacks) |
| Production VLM serving | RunPod Serverless (bf16 on RTX A5000 / 4090 class GPUs) |

---

## Repo layout

```
Advanced_ML/
├── data/               # parquet data files + locked splits (gitignored except splits)
├── data_prep/          # offline data pipeline (translate → splits → targets → merge)
├── models/             # training scripts for the model components
│   └── checkpoints/    # gitignored
├── eval/               # baseline runner + Qwen field eval (+ results JSONs)
├── backend/            # FastAPI app
│   ├── routes/         # /upload  /verify  /publish  /onboarding  /inventory
│   ├── integrations/   # Vinted + Kleinanzeigen mobile-API clients
│   └── vlm_backend/    # pluggable VLM backends (stub / local_mps / runpod_http)
├── runpod/             # Docker image + handler for the RunPod Serverless worker
├── frontend/           # Next.js TypeScript app
├── docs/               # technical report, AI-usage log, model-stack evolution, …
└── requirements.txt
```

---

## Setup (backend)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` at the repo root (gitignored):

```bash
# Required for runpod_http mode (production):
RUNPOD_API_KEY=rpa_...
RUNPOD_ENDPOINT_ID=...

# Required for local_mps mode and the worker container (gated HF repos):
HF_TOKEN=hf_...

# Listing-copy generation (Model #6) — without it, /upload falls back to
# deterministic template copy:
GROQ_API_KEY=gsk_...

# Optional, for the LLM-as-judge eval baselines:
OPENAI_API_KEY=sk-...

# Optional, for direct Vinted publishing via /publish (Phase 6a):
VINTED_SESSION_PATH=/path/to/.vinted-session.json
```

Run the backend:

```bash
# Stub backend — no GPU, deterministic fakes, fastest dev loop:
uvicorn backend.main:app --reload

# Local MPS backend — runs Qwen3-VL on Apple Silicon, ~10-15 s/call, needs ~12 GB free RAM:
VLM_BACKEND=local_mps uvicorn backend.main:app --reload

# RunPod backend — production path; Mac calls a Serverless endpoint over HTTP:
VLM_BACKEND=runpod_http RUNPOD_TIMEOUT_S=900 uvicorn backend.main:app --port 8000
```

Send a test request:

```bash
curl -F "image=@some_jacket.jpg" http://localhost:8000/upload | jq
```

---

## VLM backends

Selected via the `VLM_BACKEND` env var. Same `/upload` contract for all three.

| Backend | Where it runs | Latency | When to use |
|---|---|---|---|
| `stub` (default) | In-process | < 50 ms | Frontend dev, CI, no-GPU machines |
| `local_mps` | In-process (Mac MPS) | 10–15 s | Single-user dev with a 16 GB+ Mac, no RunPod credit |
| `runpod_http` | RunPod Serverless | 3–6 min cold / 3–20 s warm | Production, demo, multi-user |

Stub returns deterministic placeholder fields and a (2560,) hidden state seeded from the image hash — fine for verifying frontend wiring without spending GPU minutes.

---

## Production deploy (RunPod)

Full deploy steps in [`runpod/README.md`](runpod/README.md). Quick summary:

```bash
docker buildx build --platform linux/amd64 \
  -f runpod/Dockerfile \
  -t ghcr.io/rengo33/resell-vlm:latest \
  --push .
```

Then on RunPod dashboard: Serverless → Endpoints → Create New Endpoint, point at the GHCR image, and set the env vars. The container expects `HF_TOKEN` (gated-repo access) and the same `BASE_MODEL` / `ADAPTER_ID` / `MAX_NEW_TOKENS` overrides used during training.

## Direct publishing — Vinted & Kleinanzeigen

`/publish` posts listings directly to the platform's mobile API — Vinted via
the draft-mode flow (which bypasses DataDome on the protected submission
endpoint), Kleinanzeigen via its Auth0-authenticated ad-create endpoint. A
single tap can cross-post to both. Editing (`PATCH /listings/{id}/fields`) and
deleting (`DELETE /listings/{id}`) propagate to whichever platforms the listing
is live on.

### One-off bootstrap

Vinted's password endpoint requires a "high-trust" DataDome cookie that
can't be minted from a clean IP — it has to come from a real Android
device once. Use vinted-lister's existing CLI to extract the four
phone-derived values via ADB:

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

On success: returns `{platform, status:"ready", user_id, expires_at}` and
writes the session JSON to `VINTED_SESSION_PATH`. The password is used
once for the OAuth password grant and never logged or persisted.

```bash
curl http://localhost:8000/onboarding/status
# {"vinted": {"state": "ready", ...}, "kleinanzeigen": {"state": "ready", ...}}
```

### Publish behaviour (async)

`POST /publish` enqueues a job and returns 202 immediately:

```json
{"job_id": 42, "status": "pending", "listing_id": "abc123", "platform": "vinted"}
```

A background runner picks the job up, calls Vinted, and updates its row
in the `publishes` table. Frontend polls `GET /publish/status/{job_id}`
every ~2s and stops once `status` is `posted` or `failed`:

```json
{
  "job_id": 42, "status": "posted",
  "platform_listing_id": "1234567890",
  "platform_listing_url": "https://www.vinted.fr/items/1234567890",
  "retry_count": 0, "next_attempt_at": null,
  "error": null
}
```

Transient failures (DataDome 429, network blips) auto-retry with
exponential backoff (`5s → 30s → 120s`, configurable via
`PUBLISH_RETRY_BACKOFF`). Permanent failures (auth expired, validation
errors, missing config) skip retries and go straight to `status: failed`
with a populated `error` field.

### Known publish-side gaps

- **Sneaker sizes are unmapped.** Sneakers (catalog 2632) use Vinted's
  `size_group=7` whose IDs aren't recoverable without creating throwaway
  live listings. The mapper drops `size_id` for sneakers and the user
  picks the size on Vinted's confirmation page before going live.
- **Material is free-text.** Vinted has no public materials endpoint;
  `to_vinted` passes through `material` as-is (Vinted treats it as a
  hint string, not an enum).
- **Brand_id resolves dynamically.** First publish per unique brand
  hits `/api/v2/item_upload/brands?keyword=...` and caches the top-hit
  ID per process. Unknown brands fall back to free-text `brand`, which
  Vinted accepts but doesn't link to a brand page.

---

### Current production settings (verified working)

| Setting | Value | Why |
|---|---|---|
| Container image | `ghcr.io/rengo33/resell-vlm:latest` | GHCR private package |
| Container disk | 25 GB | 8 GB Qwen base + 50 MB adapter + cache headroom |
| GPU types allowed | 24 GB (1st), 48 GB (2nd) | Allows fallback when RTX A5000 pool is saturated |
| Min workers | 0 | Pay nothing when idle |
| **Max workers** | **1** | Two parallel calls per /upload would otherwise summon two workers; cap to 1 to avoid crash-loop fanout. Bump to 2 only when stable |
| Idle timeout | 5–60 s | Workers die quickly between calls; raise to 300+ for demo windows |
| FlashBoot | ON | Snapshots warm workers so cold starts don't redownload 8 GB |
| Env vars on endpoint | `HF_TOKEN`, optional `BASE_MODEL`, `ADAPTER_ID`, `MAX_NEW_TOKENS` | Adapter is gated; token must have access |

---

## Models

See [`docs/model_stack_evolution.md`](docs/model_stack_evolution.md) for the full development narrative.

| # | Name | Architecture | Status |
|---|---|---|---|
| 1 | VLM identifier | Qwen3-VL-4B-Instruct + LoRA | trained, deployed via RunPod |
| 2 | Flaw head | DINOv2 (frozen) + MLP | trained |
| 3 | Tag detector | folded into #1's prompt schema | n/a |
| 4 | Price head | MLP quantile regression (q10/q50/q90), per platform | trained |
| 5 | Sell-likelihood head | MLP binary classifier | trained |
| 6 | Listing-copy generator | Groq `llama-3.1-8b-instant` + deterministic template fallbacks | live |

---

## Evaluation

```bash
python eval/run_baseline.py          # GPT-4o-mini / Claude Haiku baselines on the test set
python eval/run_qwen_field_eval.py   # field-level eval of the fine-tuned Qwen identifier
python scripts/eval_lora.py          # single- vs multi-image LoRA yardstick
```

Results land in `eval/results/*.json`. Headline metric: **price MAPE per platform**, our pipeline vs GPT-4o-mini.

---

## Tests

```bash
.venv/bin/pytest backend/tests -q
```

The suite covers the FastAPI routes (`/upload`, `/verify`, `/publish`, `/inventory`), the SQLite logging, and the VLM backends (including respx-mocked RunPod scenarios for cold start, FAILED status, timeout, malformed output, wrong hidden-state dim, and worker error payloads).
