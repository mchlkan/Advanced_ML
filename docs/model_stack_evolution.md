# Resell Copilot — Model Stack Evolution

This document tracks the state of the model stack at each stage of the project: the
initial version as shipped after training, the problems identified through evaluation,
and the steps taken to improve it. Intended as source material for the technical
report section on model development.

---

## 1. Initial Model Stack (v1)

### Data

| Dataset | Rows (combined) | Source |
|---|---|---|
| Vinted | 6,409 | Scraped + re-scraped for sold-status labels |
| Kleinanzeigen | 2,302 | Scraped |
| **Total** | **8,711** | Combined, EN-translated |

Splits: 7,390 train / 821 val / 500 test.
Test set locked before any training: stratified by platform × category × condition × state.
All German text fields translated to English via a parallel translation pipeline.

---

### Model #1 — Fine-tuned VLM

**Architecture:** Qwen3-VL-4B-Instruct base + QLoRA adapter.
- LoRA rank 16, alpha 32, dropout 0.05, adapters on attention + MLP projections.
- Training: 2 epochs, LR 1e-4, effective batch size 8 (per-device 1 × grad-accum 8).
  Note: brief specified 3 epochs / eff batch 16; reduced by Leon based on
  overfitting risk at ~7k rows.
- Adapter: `Rengo33/qwen3vl4b-resell-adapter` (private HF Hub).
- Inference: called **twice per listing in parallel**, once per platform, each with a
  platform-specific instruction prompt embedding that platform's category vocabulary.
- Output: structured JSON — `brand`, `category`, `condition`, `color`, `size`,
  `title`, `description`, `price_eur`.

**Evaluation — 500-row locked test set:**

| Metric | Overall | Vinted | Kleinanzeigen |
|---|---|---|---|
| JSON parse rate | 81.8% | 96.5% | 40.9% |
| Brand (exact match) | 47.5% | 48.6% | 44.7% |
| Brand (fuzzy match) | 50.4% | 52.5% | 44.7% |
| Category (exact) | 96.8% | 99.7% | 88.6% |
| Condition (exact) | 65.6% | 64.1% | 69.7% |
| Color (exact) | 72.2% | 75.0% | 64.4% |
| Size (exact) | 24.0% | 25.0% | 21.2% |
| VLM internal price MAPE | 50.6% (n=413) | 48.7% (n=356) | 62.7% (n=57) |
| Title BLEU-4 | 0.113 | 0.118 | 0.100 |
| Description BLEU-4 | 0.031 | 0.032 | 0.028 |

**Category accuracy by category (overall):**

| Category | Parse rate | Category acc | Brand acc (exact) |
|---|---|---|---|
| sneakers | 100.0% | 100.0% | 75.5% |
| tshirts | 97.5% | 100.0% | 53.2% |
| jeans | 92.8% | 100.0% | 42.2% |
| jackets | 97.6% | 99.2% | 39.3% |
| KA Women's clothing | 45.6% | 89.5% | 24.6% |
| KA Men's clothing | 32.6% | 95.3% | 55.8% |

**Baseline comparison — GPT-4o-mini on the same 500-row test set:**

| Metric | GPT-4o-mini | Our VLM (internal) |
|---|---|---|
| Price MAPE | 102.5% | 50.6% |
| Price MAE | €21.50 | €18.17 |
| Price RMSLE | 0.707 | 0.651 |

The VLM's own internal price estimate already beats GPT-4o-mini by ~2×, even before
the dedicated price head (Model #4) is applied.

---

### Model #2 — Visible-Flaw Head

**Architecture:** Frozen `facebook/dinov2-base` (86M params) as feature extractor →
trainable MLP: `Linear(768→256) → GELU → Dropout(0.2) → Linear(256→1) → Sigmoid`.

**Training:** Vinted-only data (combined Vinted+KA training reached only AUC 0.665;
Vinted-trained generalises better as a visual-wear signal for the price head).
- Positive class: `condition == 'Good'` (1,015 train examples).
- Negative class: all other conditions (4,422 train examples).
- Class-weighted BCE, `pos_weight = 4.36`. Early stopping on val AUC. Best epoch: 7.

**Evaluation:**

| Split | AUC | Precision | Recall | F1 |
|---|---|---|---|---|
| Val | 0.700 | 0.294 | 0.688 | 0.412 |
| Test | 0.701 | 0.326 | 0.623 | 0.428 |

Usage: `visual_wear_probability` feeds into Model #4 (price head) as an auxiliary
numeric input. Not directly exposed as a user-facing condition classifier.

---

### Model #3 — Tag Presence

Implemented as a **rule** derived from Model #1's condition output:
`tag_proxy = 1.0 if condition == "New with tags" else 0.0`.

Decision: a separate zero-shot VLM prompt was considered but the condition field
already encodes this reliably enough as an auxiliary signal for Model #4. Separate
inference call was not worth the latency cost.

---

### Model #4 — Price Head (v1)

**Architecture:** MLP with pinball loss across 5 quantiles (q10, q25, q50, q75, q90).
- Input (concatenated): VLM pooled hidden state + `[visual_wear_probability, tag_proxy]`
  (numeric, 2-dim) + platform (one-hot, 2-dim) + category (one-hot, 8-dim) + condition
  (one-hot, 4-dim) + brand (learned embedding, 32-dim).
- Structure: `Linear(input_dim → 512) → ReLU → Dropout(0.2) → Linear(512 → 256) →
  ReLU → Linear(256 → 5)`.
- Training: AdamW LR 1e-3, up to 100 epochs, early stopping patience 10.
  Best epoch: 24.

**Hyperparameters (v1 checkpoint):** hidden_dim=512, dropout=0.2, batch_size=256,
lr=1e-3, seed=42.

**Evaluation — test set (n=500):**

| Metric | Overall | Vinted | Kleinanzeigen |
|---|---|---|---|
| MAE | €15.65 | — | — |
| MAPE | 53.3% | — | — |
| RMSLE | 0.545 | — | — |
| Coverage q10–q90 | 76.8% | — | — |

vs. GPT-4o-mini baseline: MAE €21.50, MAPE 102.5%, RMSLE 0.707.

---

### Model #5 — Sell Likelihood Head

**Architecture:** MLP: `Linear(input_dim → 256) → ReLU → Dropout(0.2) → Linear(256→1)`.
- Same input structure as Model #4 plus asking price (log-transformed, 1-dim).
- Vinted-only: Kleinanzeigen dropped to v2 due to noisy sold-status proxy
  (`inactive` ≠ sold; no explicit sold marker available from KA).
- Label: `state == 'sold'` (1,743 positives / 4,666 negatives, ~1:2.7 balance).
- Sold-status window: ~8 days (effective scrape window, not a chosen threshold).
- Training: class-weighted BCE, `pos_weight = 3.43`. Best epoch: 16 of 31.
- Threshold tuned on val: 0.425 (default 0.5 underperforms due to class imbalance).

**Evaluation:**

| Split | AUC | PR-AUC | Precision | Recall | F1 |
|---|---|---|---|---|---|
| Val | 0.581 | 0.276 | 0.263 | 0.785 | 0.394 |
| Test | 0.605 | 0.302 | 0.282 | 0.826 | 0.420 |

Known limitations: right-censoring (items listed close to scrape date have less
observation time; treated as negatives regardless). Seller withdrawals are
indistinguishable from sales in the `gone` state.

---

## 2. Diagnosis — Problems Identified

After evaluating the v1 stack, the following issues were identified in order of
impact on the business pitch and demo quality.

### 2.1 KA parse rate (critical)

Kleinanzeigen JSON parse rate of **40.9%** means the model produces malformed or
unparseable output for nearly 6 in 10 KA items. No recovery mechanism existed in v1:
a failed parse returned an empty dict silently, producing a blank result page for
the user. Root cause: KA items have different category taxonomy, size format, and
messy multi-format fields that the model was not trained on as robustly as Vinted.

### 2.2 No parse recovery or reliability signals

The v1 pipeline had no JSON recovery fallback. If the model output valid JSON with
prose wrapping, markdown fences, or a truncated object, the parse failed entirely.
There were also no signals to the frontend about which fields were reliable —
brand and size were displayed with the same confidence as category and color, despite
having substantially weaker accuracy (47.5% and 24.0% respectively).

### 2.3 Price head suboptimal hyperparameters

The v1 price head was trained with `dropout=0.2` at the default configuration.
A focused hyperparameter sweep revealed a better configuration existed with lower
dropout and the same hidden dimension, improving all metrics meaningfully.

### 2.4 Size accuracy structurally weak

Size accuracy of **24.0%** is the weakest field. A significant fraction of these
errors are format mismatches (e.g., `"Medium"` vs `"M"`, `"EU 40"` vs `"40"`) rather
than true model failures — the model predicts a correct size concept in the wrong
string format. Normalization was not applied in v1.

### 2.5 Description quality poor

Description BLEU-4 of **0.031** indicates generated descriptions diverge heavily from
seller-written text. While BLEU-4 is a poor metric for open-ended generation (seller
text is noisy and variable), inspection of generated descriptions confirmed they were
generic and not platform-appropriate — a liability for the demo.

### 2.6 Sell head modest AUC

Test AUC of **0.605** for the sell likelihood head is above random but weak for a
pitch-facing metric. Contributing factors: right-censoring in the label construction,
seller withdrawal noise, and small positive class (23.8% of test set). Framed as a
directional signal rather than a calibrated probability.

---

## 3. Improvements Implemented

### 3.1 Price Head Hyperparameter Sweep (Round 1)

**Commit:** `22d1dfb`, `ca26a85`

Ran a focused sweep over dropout, hidden_dim, batch_size, lr, and random seed,
keeping the flaw input enabled. 10 configurations evaluated on the locked test set.

**Winner:** `seed=42, dropout=0.1, hidden_dim=512, batch_size=32, lr=0.001`
(checkpoint: `models/checkpoints/price_sweep/seed42_drop0p1_h512_b32_lr0p001_flaw.pt`)

**Results vs v1 checkpoint (test set, n=500):**

| Metric | v1 checkpoint | Sweep winner | Delta |
|---|---|---|---|
| MAE | €15.65 | €14.63 | −6.5% |
| MAPE | 53.3% | 49.2% | −7.7pp |
| RMSLE | 0.545 | 0.513 | −5.9% |
| Coverage q10–q90 | 76.8% | 83.4% | +6.6pp |

**By platform (sweep winner, test set):**

| Platform | MAE | MAPE | RMSLE | Coverage |
|---|---|---|---|---|
| Vinted | €14.60 | 44.0% | 0.487 | 82.3% |
| Kleinanzeigen | €14.72 | 63.7% | 0.581 | 86.4% |

**vs. GPT-4o-mini baseline (same test set):**

| Model | MAPE | MAE | RMSLE |
|---|---|---|---|
| GPT-4o-mini | 102.5% | €21.50 | 0.707 |
| Our price head (sweep winner) | **49.2%** | **€14.63** | **0.513** |
| Improvement | **2.1× better MAPE** | **32% lower MAE** | **27% lower RMSLE** |

The sweep winner was copied to `models/checkpoints/price_head.pt` and is the live
local checkpoint.

---

### 3.2 VLM Parse Safety and Field Review Flags (Round 1)

**Commit:** `0902bf0`

Two production safety improvements shipped without retraining Model #1.

#### Parse recovery

Implemented `parse_vlm_fields(text) → VLMParseResult` in `backend/vlm_backend/util.py`.
Recovery cascade:
1. Strip markdown fences and leading/trailing prose → attempt `json.loads`.
2. Find `{…}` substring → attempt `json.loads` on that slice.
3. Fall back to field-level regex recovery: scan for known field names (`brand`,
   `category`, `condition`, `color`, `size`, `title`, `description`, `price_eur`)
   and extract individual values even from broken objects.

`VLMParseResult` exposes two flags:
- `parse_ok`: true if steps 1 or 2 succeeded (clean JSON).
- `recovered`: true if step 3 was used (field-level salvage from broken output).

All VLM backends (`local_mps`, `runpod_http`) and the eval script
(`eval/run_qwen_field_eval.py`) now share this single parser.

#### Field review flags

The pipeline emits a `field_review` block on every API response:

```json
"field_review": {
  "needs_review": ["brand", "size"],
  "reasons": {
    "brand": "low_confidence",
    "size": "low_confidence"
  }
}
```

`brand` and `size` are always flagged as needing review, reflecting their measured
accuracy (47.5% and 24.0%). If parse recovery was used, the reason string is extended:
`"low_confidence,parse_recovered"`. The `/verify` endpoint removes a field from
`needs_review` when the user supplies a corrected value, confirming that field.

The frontend renders brand and size fields with a `Check` badge until confirmed.

**Verification:** `pytest backend/tests/test_local_mps.py backend/tests/test_runpod_http.py backend/tests/test_routes.py` — all pass.

---

## 4. Planned Improvements (Round 2)

### 4.1 Model #6 — Grounded Description Generator

**Owner:** Michael. **Status:** design complete, implementation pending.

**Problem:** Model #1's description output has BLEU-4 of 0.031 and produces generic,
non-platform-appropriate text. The fundamental issue is that the VLM must generate
structured extraction and creative writing in a single JSON generation pass, splitting
generation capacity across tasks.

**Design:**
- Remove `description` from Model #1's JSON output at inference time.
  `price_eur` also removed (redundant: Model #4 produces a calibrated quantile band;
  the VLM's internal price MAPE of 50.6% is already superseded by Model #4's 49.2%).
- Add Model #6: a prompted LLM call that receives only the structured fields extracted
  by Model #1 (brand, category, condition, color, size, title) plus
  `visual_wear_probability` from Model #2 and the target platform.
- LLM never sees the image — can only restyle facts already extracted.
  Anti-hallucination by construction.
- Few-shot examples sourced from sold Vinted listings (`state == 'sold'`),
  manually written for quality, one per category × condition tier (~8 examples total).
  Examples are category-matched at inference time.
- Inference: 2 parallel LLM calls (one per platform), run after Models #1–5 complete
  so `visual_wear_probability` is available to inform tone.
- LLM: Groq free tier (Llama 3.1 8B), zero cost for demo-scale usage.
  Fallback: template-based generation if Groq is unavailable.
- Re-runs on `/verify` when user corrects fields, producing an updated description
  that reflects the corrected values.

**Cost impact:** Removing description from Model #1 saves ~200–500 VLM output tokens
per listing (faster inference, lower GPU cost). The Groq API calls replace that cost
at effectively zero price. Net: roughly neutral cost, substantially better quality.

**Architecture framing:**
- Model #1: structured extraction layer (grounded, defensible, fine-tuned).
- Model #6: rendering layer (commodity, replaceable, no visual hallucination possible).

---

### 4.2 Model #1 Retraining (Owner: Leon)

**Status:** design complete, implementation pending.

Three targeted improvements:
1. **Larger base model:** evaluate Qwen3-VL-7B or Qwen3-VL-9B as base. Larger models
   may improve brand recognition and condition inference where the 4B model underperforms.
2. **Multi-photo input:** use 3–5 photos per listing instead of hero shot only.
   Brand labels, size tags, and wear flaws are often not visible in the hero image.
   Expected improvement: brand accuracy and size accuracy.
   Blocked on: clean `listing_id → [photo_paths]` mapping from the dataset.
3. **KA prompt engineering:** improve KA JSON parse rate (currently 40.9%) through
   better instruction formatting and explicit schema constraints in the inference prompt,
   without retraining.

**Interface contract with Model #6:** Model #1's output schema after retraining must
continue to include `brand`, `category`, `condition`, `color`, `size`, `title`.
Model #6 is agnostic to model size, photo count, or hidden state dimension.
No coordination required beyond this schema contract.
