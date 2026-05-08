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
| VLM | Qwen3-VL-4B-Instruct + QLoRA adapter (`Rengo33/qwen3vl4b-resell-adapter`) |
| Vision features | DINOv2-base (frozen) |
| Production VLM serving | RunPod Serverless (4-bit nf4 on RTX A5000 / 4090 class GPUs) |

---

## Repo layout

```
resell-copilot/
├── data/               # parquet data files + locked splits (gitignored except splits)
├── models/             # training scripts for all 5 model components
│   └── checkpoints/    # gitignored
├── eval/               # baseline runner, our pipeline runner, metrics
│   └── results/        # gitignored
├── backend/            # FastAPI app
│   ├── routes/         # /upload  /verify  /publish
│   └── vlm_backend/    # pluggable VLM backends (stub / local_mps / runpod_http)
├── runpod/             # Docker image + handler for the RunPod Serverless worker
├── frontend/           # Next.js TypeScript app
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

# Optional, for the LLM-as-judge eval baselines:
OPENAI_API_KEY=sk-...
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

| # | Name | Architecture | Status |
|---|---|---|---|
| 1 | VLM | Qwen3-VL-4B-Instruct + LoRA | trained, deployed via RunPod |
| 2 | Flaw head | DINOv2 + MLP | trained |
| 3 | Tag detector | Baked into #1 prompt schema | n/a |
| 4 | Price head | MLP quantile regression (q10/q50/q90) | trained |
| 5 | Sell-likelihood | MLP binary classifier | trained |

---

## Evaluation

```bash
python eval/run_baseline.py   # GPT-4o-mini + Claude Haiku on test set
python eval/run_ours.py       # our pipeline on test set
python eval/compute_metrics.py --predictions eval/results/<file>.json
```

Headline metric: **Price MAPE per platform**, our pipeline vs GPT-4o-mini.

---

## Tests

```bash
.venv/bin/pytest backend/tests -q
```

28 tests cover the FastAPI routes, the SQLite logging, and the three VLM backends (including respx-mocked RunPod scenarios for cold start, FAILED status, timeout, malformed output, wrong hidden-state dim, and worker error payloads).
