# Resell Copilot

Photo-first selling assistant for second-hand clothing. 7-day course project (Nova SBE, Advanced ML).

**Source of truth:** `resell_copilot_tech_brief_v2.md`. Read it before making architecture decisions.

**Course instructions:** `Project_Description.pdf` in the repo root.

## Stack

- Python 3.11
- Backend: FastAPI + SQLite (on EC2); VLM served from RunPod Serverless; Groq for listing copy
- Frontend: TypeScript / Next.js 14 (on Vercel), in `/frontend`
- Monorepo

## Environment

The maintainer of this repo uses **conda** for the Python env (`conda activate resell-copilot`). Other contributors use plain `pip + venv`. Either works — `requirements.txt` is the source of truth for dependencies. Do not run `conda install`; use `pip install` inside whichever env is active.

## Conventions

- Data files (`*.parquet`, `*.csv`) and model checkpoints are gitignored — never commit them.
- Notebooks: `/notebooks`, prefixed with order (`01_`, `02_`, …).
- Logs go to SQLite from the first endpoint onward.

## Out of scope for v1

See §5.5 of the brief. If asked to add something on that list, push back and ask.

## Settled decisions (kept here for context)

- Base VLM: Qwen3-VL-4B-Instruct + LoRA (`mchlkan/qwen3vl4b-resell-adapter-multi-v3`)
- Frontend: Next.js 14 + TypeScript (Vercel)
- Categories: `tshirts / jackets / jeans / sneakers` (the trained vocabulary)
- Sold-status detection: wardrobe-diff based (an item absent from the latest wardrobe sync after it was synced is treated as sold/removed) — no fixed time window
