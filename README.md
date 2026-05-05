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
| VLM | Qwen (base model locked Day 1 via spike) + QLoRA |
| Vision features | DINOv2-base (frozen) |

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
│   └── routes/         # /upload  /verify  /publish
├── frontend/           # Next.js TypeScript app
│   └── src/
│       ├── pages/
│       ├── components/
│       └── api/
└── requirements.txt
```

---

## Setup (backend)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

## Setup (frontend)

```bash
cd frontend
node --version   # must be >=20
npm install
npm run dev
```

---

## Models

| # | Name | Architecture | Status |
|---|---|---|---|
| 1 | VLM | Qwen (QLoRA) | stub |
| 2 | Flaw head | DINOv2 + MLP | stub |
| 3 | Tag detector | Zero-shot / baked into #1 | stub |
| 4 | Price head | MLP quantile regression | stub |
| 5 | Sell-likelihood | MLP binary classifier | stub |

---

## Evaluation

```bash
python eval/run_baseline.py   # GPT-4o-mini + Claude Haiku on test set
python eval/run_ours.py       # our pipeline on test set
python eval/compute_metrics.py --predictions eval/results/<file>.json
```

Headline metric: **Price MAPE per platform**, our pipeline vs GPT-4o-mini.
