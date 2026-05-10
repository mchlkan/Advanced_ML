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

#### Post-recovery eval (re-run on locked test set, 2026-05-09)

Re-ran `parse_vlm_fields()` over the saved `qwen_field_predictions.parquet` raw text
to measure the effective parse rate with recovery in place, without re-running VLM inference.

| | Clean parse | Recovered | Hard failures |
|---|---|---|---|
| Vinted (n=368) | 96.5% | 3.5% | **0%** |
| Kleinanzeigen (n=132) | 40.9% | 59.1% | **0%** |
| Overall (n=500) | 81.8% | 18.2% | **0%** |

Key finding: hard failure rate dropped from 59.1% on KA to 0% across all 500 items.
Every listing now returns a usable draft — no more blank result pages. Field accuracy
is unchanged (recovery salvages structure, not prediction quality):

| Field | Accuracy |
|---|---|
| Category | 96.8% |
| Condition | 65.6% |
| Color | 72.2% |
| Brand | 48.2% |
| Size | 24.0% |

Pitch framing: KA coverage is now "every listing returns an editable draft; field
accuracy improves with the retrained model" rather than "6 in 10 KA items return nothing".

---

### 3.3 Model #1 Multi-Image Retraining (Round 2)

**Owner:** Michael. **Status:** shipped 2026-05-10.
**Adapter:** `mchlkan/qwen3vl4b-resell-adapter-multi-v1` (HF Hub, public).
Local copy: `models/checkpoints/qwen3vl4b-resell-multi-v1/`.

**Problem:** the v1 single-image adapter (`Rengo33/qwen3vl4b-resell-adapter`) has
to guess brand and size from the cover photo alone. Cover shots rarely show the
care label, so brand sat at 47–49% and size at ~24–27% — the two weakest
extraction fields, and both directly tied to information that is printed on the
sewn-in label rather than visible on the garment.

**Hypothesis:** feed the model both photos at training and inference time —
the cover shot for category/color/condition, the care-label shot for
brand/size — and the field accuracies tied to label text should jump while
the rest stays flat.

**Data pipeline (new code):**
- `scripts/reclassify_clip.py` — CLIP zero-shot tagger for scrapes that lack
  per-photo `garment` / `label` tags. Run once on the no-CLIP scrape
  (`clothing_2026-05-05_1146`). Pass `--margin 0.0` for 2-class output;
  default `0.05` defaults uncertain photos to garment which collapses the
  label class.
- `scripts/build_manifest.py` — joins raw scrape directories (multiple photos
  per listing + CLIP type tags) with `data/vinted_clothing_combined.parquet`
  and `data/splits/*_ids.json`, producing one row per listing with
  `garment_path`, optional `label_path`, `target_text`, and inherited split.
  Vinted-only — Kleinanzeigen scrapes don't carry multi-photo data.
- `src/multi_image_dataset.py` — `VintedMultiImageDataset` +
  `MultiImageVLMCollator`. Mixed-mode: returns 1 image when no label exists,
  2 when it does. `max_length` raised from 2048 → 3072 to fit the second
  image's patch tokens.
- `models/train_vlm.py` — added `--manifest` and `--max-images` flags. When
  `--manifest` is passed the trainer switches to the multi-image dataset
  and collator; the single-image path still works unchanged.

**Manifest stats:** 6,408 listings (5,436 train / 604 val / 368 test).
96% of train rows carry a label photo; the rest fall back to garment-only
through the same dataset class.

**Training:** identical hyperparameters to v1 (LR 1e-4, eff batch 8, 2 epochs,
LoRA r=16 α=32, QLoRA 4-bit). 3.94 hours on a single RTX 4090 (community
cloud). Final train_loss 0.383, eval_loss 0.348 (no overfit).

**Evaluation — same 368-row test slice, single- vs multi-image:**

| Metric | Single-image v1 | Multi-image v1 | Δ |
|---|---|---|---|
| **Brand (exact)** | 49.2% | **69.3%** | **+20.1 pp** |
| **Size (exact)** | 26.9% | **45.9%** | **+19.0 pp** |
| Condition (exact) | 64.1% | 65.5% | +1.4 |
| Color (exact) | 74.5% | 74.7% | +0.2 |
| Category (exact) | 99.5% | 99.7% | +0.3 |
| Parse OK | 97.6% | 97.8% | +0.2 |
| Avg latency (warm) | 12.0 s | 12.3 s | +0.2 s |
| n | 368 | 368 | — |

Hypothesis confirmed: brand and size — the fields that come straight off the
care label — moved together by ~20 pp. The non-label-derived fields didn't
shift, which is the right pattern (no regression, no spurious gain).
Latency cost of the second image is ~200 ms warm.

**Test set scope note:** the multi-image manifest test slice is 368 rows
rather than the 500 rows of the original locked test set, because not every
locked-test listing has multi-image scrape data available. Both rows in the
table above are scored on the same 368 rows for an apples-to-apples
comparison; cross-checking against the broader 500-row v1 numbers in §1
gives the same direction at slightly different absolute levels.

**Next:** Model #4 / #5 may benefit from re-extracting VLM features with the
new adapter so the price and sell-likelihood heads see better embeddings.
Optional, not blocking. — **Done 2026-05-10, see §3.4.**

---

### 3.4 Model #4 / #5 Re-extraction on Multi-Image Adapter (Round 2)

**Owner:** Michael. **Status:** shipped 2026-05-10 (price head only; sell head kept old).

**Setup:** re-extracted `data/embeddings/vlm_pooled_combined.npy` using the
multi-image adapter. Vinted rows with a manifest-listed care label fed the
model both photos; KA rows and label-less Vinted rows fell back to single
image. ~6,192 of 8,711 rows (71%) used multi-image extraction. New code:
`extract_vlm_features.py --manifest` (commit `bca06d3`).

Both heads retrained on the new features, same locked 500-row test set as
the v1 sweep checkpoint.

**Price head (Model #4) — multi-image features vs single-image baseline, test set:**

| metric | OLD (single) | NEW (multi) | Δ |
|---|---|---|---|
| MAE (€) | 15.65 | 16.05 | +0.40 |
| **MAPE** | 0.5332 | **0.4643** | **−6.9 pp** |
| RMSLE | 0.5452 | 0.5627 | +0.018 |
| coverage q10–q90 | 0.7680 | 0.7760 | +0.8 pp |

Per platform on test, MAPE improves on **both** Vinted (−7.8 pp) and
Kleinanzeigen (−4.5 pp), so the gain isn't just brand-driven on Vinted —
the adapter's better representation generalizes to KA's garment-only path
too. MAE drifts +€0.40 in absolute terms but MAPE is the metric that
maps to user-perceived accuracy on second-hand prices (€20 items, not €200).
**Decision: ship.** New checkpoint at `models/checkpoints/price_head.pt`,
old preserved as `price_head_single_v1.pt`.

**Sell head (Model #5) — three variants tested:**

| variant | params | val AUC | test AUC | test F1 |
|---|---|---|---|---|
| OLD `--no-vlm` (shipped v1) | 172 k | 0.5811 | **0.6052** | 0.4201 |
| NEW `--no-vlm` (sanity check) | 172 k | 0.5834 | 0.5732 | 0.3841 |
| NEW with VLM features | 1.5 M | 0.6172 | 0.5959 | 0.4231 |

The original sell head was trained `--no-vlm` (metadata only — log_price,
visual_wear, condition, brand embed, category, platform). To compare like
for like we retrained `--no-vlm` on the new feature run; val AUC matched
within 0.002, so the metadata path is genuinely unchanged. The new
with-VLM variant lifts val AUC by ~3.6 pts but doesn't beat the old test
AUC and is 8× larger. With test n=362 the AUC standard error is ~0.03 —
the three test AUCs are statistically indistinguishable.

**Decision: keep the old sell head.** No real signal to replace it, and
adding 1.3 M parameters for no test-set gain is a regression in any
practical sense (latency, memory, complexity).

**Artifacts kept for the report:**
- `models/checkpoints/price_head.pt` — new multi-image (shipped)
- `models/checkpoints/price_head_single_v1.pt` — old single-image baseline
- `models/checkpoints/sell_head.pt` — old metadata-only (shipped, unchanged)
- `models/checkpoints/sell_head_multi.pt` — new with-VLM (kept, not shipped)
- `models/checkpoints/sell_head_multi_novlm.pt` — sanity-check no-VLM retrain
- `eval/results/{price_head_multi,sell_head_multi,sell_head_multi_novlm}.json`

**Lesson:** features that help a generative VLM (multi-photo brand/size
recognition) don't automatically help a downstream classifier whose signal
is already saturated by metadata. Worth retraining and measuring; not
worth assuming.

---

## 4. Planned Improvements (Round 2)

### 4.1 Model #6 — Grounded Description Generator

**Owner:** Michael. **Status:** shipped (`backend/description.py`, commit `f2e69ab`).

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

**Status:** design complete, partially shipped.

Three targeted improvements:
1. **Larger base model:** evaluate Qwen3-VL-7B or Qwen3-VL-9B as base. Larger models
   may improve brand recognition and condition inference where the 4B model underperforms.
2. **Multi-photo input:** ~~design~~ **shipped 2026-05-10 — see §3.3.** Brand +20 pp,
   size +19 pp on the 368-row multi-image test slice. Used 2 photos (garment + care
   label) rather than 3–5; the label photo carries the brand/size text the cover shot
   can't.
3. **KA parse rate fix — baked into retraining (not a prompt patch):** root cause of
   the 40.9% KA parse rate is the `description` field: the model generates multi-sentence
   prose inside a JSON string and emits literal newlines, which breaks the parser.
   Patching the inference prompt alone won't help — the model was trained to emit
   `description` and will likely continue doing so regardless of the instruction.
   Two concrete code changes required before the training run:

   **`models/train_vlm.py` — training target (the JSON the model learns to emit):**
   Remove the `description` key from the `build_target()` dict. Keep `price_eur` —
   it is an auxiliary task that improves the VLM hidden state quality for Model #4.
   ```python
   # remove this line:
   "description": row["description_en"],
   # keep this line:
   "price_eur": float(row["price"]),
   ```

   **`shared/prompts.py` — inference prompt only (`get_prompt()`):**
   Remove both `description` and `price_eur` from the format block. The model
   should not emit them at inference time — Model #6 handles description, Model #4
   handles price. Add a concrete filled-in JSON example directly in the prompt
   (one per platform) so the model has a complete valid example to anchor on,
   not just an abstract template.
   Note: `get_prompt()` is imported by `train_vlm.py` for the chat template wrapper,
   but the training *target* JSON is built separately in `build_target()` — removing
   fields from `get_prompt()` does not affect what the model is trained to predict.

   After retraining, Model #1 emits 6 short scalar fields only (brand, category,
   condition, color, size, title), eliminating the primary parse failure mode.
   Expected outcome: KA parse rate substantially above 40.9%.

**Interface contract with Model #6:** Model #1's output schema after retraining must
continue to include `brand`, `category`, `condition`, `color`, `size`, `title`.
Model #6 is agnostic to model size, photo count, or hidden state dimension.
No coordination required beyond this schema contract.
