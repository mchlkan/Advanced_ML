# Resell Copilot

Photo-first selling assistant for second-hand clothing. 7-day course project (Nova SBE, Advanced ML).

**Source of truth:** `resell_copilot_tech_brief_v2.md`. Read it before making architecture decisions.

**Course instructions:** `Project_Description.pdf` in the repo root.

## Stack

- Python 3.11
- Backend: FastAPI + SQLite
- Frontend: TypeScript, framework TBD (locked Day 2)
- Monorepo, frontend lives in `/frontend`

## Environment

The maintainer of this repo uses **conda** for the Python env (`conda activate resell-copilot`). Other contributors use plain `pip + venv`. Either works — `requirements.txt` is the source of truth for dependencies. Do not run `conda install`; use `pip install` inside whichever env is active.

## Conventions

- Data files (`*.parquet`, `*.csv`) and model checkpoints are gitignored — never commit them.
- Notebooks: `/notebooks`, prefixed with order (`01_`, `02_`, …).
- Logs go to SQLite from the first endpoint onward.

## Out of scope for v1

See §5.5 of the brief. If asked to add something on that list, push back and ask.

## Open decisions

- Base VLM model (locked Day 1 via spike, Qwen3-VL family)
- Sold-status time window (7/14/30 days)
- Frontend framework (Next.js vs Vite + React)
