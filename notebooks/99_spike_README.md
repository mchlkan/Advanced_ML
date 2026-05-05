# 99_spike — what it decides and how to read the output

## Purpose

The Day 1 spike answers one question: **which Qwen3-VL Instruct variant should we lock in for the Day 2 QLoRA fine-tune?** Reference: `resell_copilot_tech_brief_v2.md` §2.

Three candidate base models are smoke-tested in 4-bit on a Colab T4, then full zero-shot evaluated on a locked 100-row test set, and compared head-to-head with GPT-4o-mini on the same 100 items.

This notebook does **not** train, fine-tune, or build any heads. It is a model-selection harness only.

## How to run

1. Open `notebooks/99_spike.ipynb` in Colab on a T4 runtime (free tier).
2. Run cells top-to-bottom.
3. The only manual step: paste your `OPENAI_API_KEY` when cell 11 prompts (or set it as an env var beforehand).
4. Total wall-clock: ~30–60 min depending on which Qwen variants load.

If the data parquets aren't on Drive, cell 5 will fail with a `FileNotFoundError` pointing to the expected Drive path (`/content/drive/MyDrive/Resell_Copilot_data/`). Put both parquets there or copy them into `data/` after cloning.

## How to read the output table (cell 12)

| column          | what it means                                                              | rule of thumb                |
|-----------------|----------------------------------------------------------------------------|------------------------------|
| `n`             | number of test rows scored                                                 | should be 100                |
| `parse_rate`    | fraction of rows where the model emitted a parseable JSON object           | < 0.8 → prompt issue         |
| `brand_acc`     | exact-match brand accuracy (case-normalized)                               | GPT-4o-mini ~0.5 expected    |
| `category_acc`  | top-1 category accuracy against the row's own platform vocabulary          | should be ≥ 0.85             |
| `condition_acc` | top-1 condition accuracy on the 4 normalized buckets                       | hard task; ~0.4–0.6 expected |
| `color_acc`     | top-1 color match (case-normalized)                                        | German labels — noisy        |
| `price_mape`    | mean absolute % error on rows where price was parsed                       | **headline metric**          |
| `price_n`       | how many rows contributed to the MAPE (parse rate × price-emitted)         | should be near `parse_rate × n` |

## Decision rule (per brief §2.4)

- **A Qwen variant beats GPT-4o-mini on at least one of {brand_acc, category_acc, price_mape}** → the idea works. Lock that variant. Commit to the full week. Fill in cell 14 and proceed to Day 2.
- **A Qwen variant matches GPT-4o-mini roughly across the board** → on the bubble. Diagnose: prompt? hyperparameter? wrong base model? Don't scale up yet.
- **No Qwen variant produces sensible outputs** → reframe. Possibly drop the price-head ambition and pitch as "structured listing generation only" — see brief §11 fallback path.

## Latency / VRAM table (cell 13)

Used for the cost & latency story in the pitch. Numbers to grab:
- `median_latency_s` per Qwen variant → user-facing inference time (twice this at runtime since we call the VLM once per platform).
- `peak_vram_gb` per variant → confirms which GPU class is needed for Day 2 (T4 = 16 GB, 4090 = 24 GB, A100-40 = 40 GB).
- `gpt-4o-mini` median latency → API baseline to compare against.

## Outputs left on disk (idempotent)

- `data/splits/spike_test.parquet` — locked 100-row test set.
- `data/splits/spike_test_ids.json` — list of `id`s, for reproducing the split outside the notebook.
- `results/spike/qwen3-vl-2b-instruct_predictions.json` (and 4B, 8B) — raw + parsed outputs + ground truth + per-row latency.
- `results/spike/gpt4omini_predictions.json` — same shape, for the baseline.

Re-running any cell is a no-op once its output exists. Delete the file to force a re-run.

## What this does **not** test

- Fine-tuned performance (Day 2).
- Visible-flaw head, price head, sell-likelihood head (Day 2–3).
- Prompt sensitivity (we use one prompt per platform).
- Multi-image listings, French/Italian Vinted rows, post-edit verify flows.

These are deliberately deferred. The spike is throwaway — its only job is "does the idea work?"
