# Project Status Update — Day 2

Handoff doc. Assumes you've read `../../resell_copilot_tech_brief_v2.md` and `day1.md`. This file only captures what changed since Day 1 and what the next agent should do.

---

## What changed since Day 1

### Data — combined parquets now exist

Four input files merged into two combined files:

- `data/vinted_clothing_v2.parquet` (native, has `state` column) + `data/vinted_clothing_v2_en.parquet` (EN translations) → `data/vinted_clothing_combined.parquet` — **6,409 rows × 26 cols** (606 MB)
- `data/kleinanzeigen_clothing_v1.parquet` (native, has `state`) + `data/kleinanzeigen_clothing_v1_en.parquet` (EN) → `data/kleinanzeigen_clothing_combined.parquet` — **2,302 rows × 26 cols** (218 MB)

Inner-joined on `id` (1:1 validated). Native treated as source of truth; only EN-only columns pulled from the translated files (`platform`, `title_en`, `description_en`, `condition_en`, `color_en`, `category_en`).

**Coverage:** Vinted native→EN 83.0%, KA native→EN 57.6%. The dropped rows are expected — already filtered out earlier in the pipeline (descriptions < 30 chars, nulls, etc.). Combined files are the right ones to use going forward.

These parquets are gitignored. They live locally only — not yet on HF Hub.

### State column — sold-status labels found

The `state` column exists on both v2 native files (was missing on the `_en` files, which is why the earlier check missed it).

**Vinted state distribution (n=7,723 in native, 6,409 in combined):**
- `active` 4,952 / `sold` 1,743 / `delisted` 942 / `hidden` 81 / `reserved` 4 / `error` 1
- Clean three-way label. **`state == 'sold'` is ground truth for Model #5.**

**Kleinanzeigen state distribution (n=4,000 in native, 2,302 in combined):**
- `active` 3,611 / `inactive` 347 / `disappeared` 42
- No explicit sold marker. `inactive` conflates sold + withdrawn + expired.

### Time window — locked at ~8 days, not 7/14/30

The brief assumed we'd choose 7/14/30. We don't get to choose — the scrape did. `last_checked_at - uploaded_at` has median ~8.3 days across all non-active states on Vinted. This is when the re-scrape ran, not how long items took to sell.

What we actually have: a **point-in-time snapshot** at ~8 days post-upload. Each row tells us whether the item was sold/active/delisted at the moment of the re-check.

**Model #5 framing:** "Did this item sell within ~8 days of listing on Vinted?" Binary classification. `state == 'sold'` → positive (1,743 rows), everything else → negative (4,666 rows). Class balance ~1:2.7 — manageable with class-weighted BCE.

**Known limitation (document in the pitch):** items uploaded close to the scrape date have less observation time (right-censoring). For v1 we treat all `state == active` as negatives even if they were only listed for 3 days. Acknowledge openly.

### Model #5 scope — Vinted-only, KA dropped to v2

Decision locked. KA's 9.7% non-active rate on a noisy proxy ("inactive" ≠ sold) would produce a calibration-broken model that the AI judge would correctly tear apart. Cleaner pitch: "Vinted has ground-truth sold labels; KA doesn't expose sold status; v2 adds KA via partnership or a longer-window re-scrape."

Cross-platform recommendation in the UI still works: Vinted shows price + sell-likelihood, KA shows price + qualitative platform note.

### Model #1 — fine-tune complete

QLoRA adapter trained on RunPod (Leon's session). Lives on HF Hub (private repo, write token on Leon's machine). Hyperparams: 2 epochs, LR 1e-4, eff batch 8 (per-device 1 × grad-accum 8). Note: this is one epoch fewer and half the effective batch size relative to brief §3.1 — Leon's call based on overfitting risk at ~7k rows. Re-evaluate against val loss before scaling up if needed.

### Sold-rate findings worth keeping for the pitch

From the cross-tab analysis:
- **T-shirts sell fastest** on Vinted (29.0% sold rate), then sneakers (24.4%), jeans (20.0%), jackets (19.6%).
- **"Neu mit Etikett" sells fastest by condition** (27.5%), followed by "neu" (25.4%) and "sehr gut" (23.4%); "gut" sells slowest (15.4%).
- Strong category × condition signal — useful input for the price head AND a defensible pitch slide ("our model learns category-conditioned demand").

---

## Where we are

- ✅ EDA done (`notebooks/01_data_exploration.ipynb` extended in place, all cells run cleanly)
- ✅ Combined parquets produced
- ✅ Model #1 (VLM) fine-tuned, adapter on HF Hub
- ⏳ VLM features not yet extracted on the combined dataset
- ⏳ DINOv2 embeddings not yet extracted
- ⏳ Models #2, #3, #4, #5 untrained
- ⏳ Backend/frontend skeleton not started
- ⏳ Locked 500-row test set not yet re-built on the combined data with state-aware stratification

---

## What to do next

Focus today on Models #2, #3, #4. Model #5 follows immediately after #4.

### Step 1 — Spot-check `_en` translations (10 min)

Pull 20–30 rows from `vinted_clothing_combined.parquet`. Look at `title` vs `title_en`, `description` vs `description_en`, especially on fashion-specific vocab (brand names, materials, era terms like "vintage", "y2k"). Confirm translations are clean enough to use as canonical.

If clean → use `_en` columns as canonical for VLM training and price head text features.
If mangled on fashion vocab → use native for those columns, `_en` only for free-text where it helps.

This decision blocks the next steps — make it explicit in the notebook before moving on.

### Step 2 — Extract DINOv2 embeddings (30–60 min, fully unblocked)

Run `facebook/dinov2-base` on all images in the combined Vinted file (and KA if needed for the price head). Cache the 768-dim CLS embeddings to disk as `data/embeddings/dinov2_{vinted,ka}.npy` with a parallel `id` index file.

Free Colab T4 or local CPU is fine. No VLM dependency.

### Step 3 — Train Model #2 (flaw head, <15 min)

MLP on cached DINOv2 embeddings. Architecture per brief §3.2: `Linear(768→256) → GELU → Dropout(0.2) → Linear(256→1) → Sigmoid`. Class-weighted BCE with `pos_weight ≈ 5`, AdamW LR 1e-3, 50 epochs, early stopping on val AUC.

Positive class: `condition ∈ {gut, zufriedenstellend}` after normalization. Drop `zufriedenstellend` rows from training (54 rows, too few).

Save checkpoint to `models/checkpoints/flaw_head.pt`. Save metrics (AUC, P/R at 0.5, confusion matrix, calibration plot) to `eval/results/flaw_head.json`.

### Step 4 — Tag-presence (Model #3) — decide and ship (5–10 min)

Two implementation paths from brief §3.3:
- **Bake into Model #1's JSON output** — already trained, would need to check if the adapter learned it.
- **Run as separate zero-shot prompt** — "Is a clothing tag, label, or price tag visible in this image? Answer only with 'yes' or 'no'." — adds ~500ms per listing.

Quickest answer: run a 50-image sample through the fine-tuned VLM, check whether `tag_visible` shows up in the JSON output. If yes, bake it in. If no, ship the separate zero-shot prompt. Decide and move on.

### Step 5 — Extract VLM pooled hidden states (blocks #4 and #5)

Once the adapter is loaded locally (or from HF Hub):
- Run inference on all combined-dataset images
- Save pooled hidden states (3072 or 3584-dim depending on the locked base model) to `data/embeddings/vlm_pooled_{vinted,ka}.npy`
- Cache aggressively — these are slow to recompute and feed both #4 and #5

This is the gating step for the rest of the day. If the adapter isn't accessible from your machine yet, sync with Leon to push or transfer.

### Step 6 — Train Model #4 (price head, ~30 min)

MLP per brief §3.4. Inputs concatenated:
- VLM pooled hidden state
- Visible-flaw probability (Model #2 output)
- Tag-presence flag (Model #3 output)
- Category one-hot — **8-dim now (4 per platform, native vocabularies kept separate)** per Day-1 architecture decision
- Brand embedding (32-dim, OOV/Sonstige → UNK)
- Platform one-hot (2-dim)

Pinball loss across q={0.1, 0.25, 0.5, 0.75, 0.9}. Log-transform target. AdamW LR 1e-3, 100 epochs, early stopping. Train on combined Vinted + KA (single head, platform as input feature). Stratify train/val/test by category × platform.

This is the **headline metric** — MAPE per platform vs GPT-4o-mini is the chart Pair B needs by EOD Day 4. Don't skimp on debugging here.

### Step 7 — Train Model #5 (sell-likelihood, ~30 min, Vinted-only)

MLP per brief §3.5. Same inputs as Model #4 plus the asking price (1-dim, log-transformed).

Training data: Vinted combined only (6,409 rows). Label: `state == 'sold'` (1,743 positives) vs everything else (4,666 negatives). Class-weighted BCE with `pos_weight ≈ 2.7`.

Drop the 86 hidden/reserved/error Vinted rows from training (too few, ambiguous semantics).

### Step 8 — Run fine-tuned VLM on the locked test set (background)

Re-build the locked 500-row test set on the combined data with stratification on category × condition × platform × state (so the test set has a representative sold/active mix on Vinted).

Run the fine-tuned VLM on it, save predictions to `eval/results/ours_predictions.parquet`. Run GPT-4o-mini on the same 500 rows for the baseline comparison. Both feed the Day 4 headline chart.

---

## Open decisions still pending

- **Tag-presence implementation** — see Step 4.
- **`_en` vs native as canonical text source** — see Step 1.
- **Frontend framework** — Pair A's Day 2 decision per brief §12.5. Project memory leans Vite + React.
- **Right-censoring on Model #5** — for v1, treat all `state == active` as negatives regardless of upload-to-scrape window. Document as limitation. Don't over-engineer survival analysis for a 7-day project.

---

## Model #2 decision update

Model #2 is locked as a **Vinted-trained visual-wear signal**, not a standalone
condition classifier and not a user-facing flaw detector.

Selected checkpoint:
- `models/checkpoints/flaw_head_vinted.pt`

Selected metrics:
- `eval/results/flaw_head_vinted.json`
- Test AUC `0.7015`, precision `0.3258`, recall `0.6232`, F1 `0.4279`

Rationale:
- Combined Vinted+KA training reached only test AUC `0.6651`.
- KA-only contribution appeared noisy; test AUC on KA was weak while Vinted was
  materially stronger.
- Since visual wear is a generic image cue, the Vinted-trained probability is
  still useful as an auxiliary feature for Model #4 across both platforms.

Usage:
- Qwen remains the source of truth for displayed condition.
- Model #2 exports `visual_wear_probability` for the price head.
- Do not claim this as a high-accuracy visible-damage detector in the pitch.

Model #3 decision:
- Use a separate English zero-shot prompt for tag/label/price-tag visibility for now.
- Do not bake `tag_visible` into Qwen output unless later evidence shows the
  fine-tuned adapter already emits it reliably.

## Things still NOT decided

Everything in `day1.md` § "Things deliberately NOT decided yet" still applies, except:
- ~~Sold-status time window~~ → **locked at ~8 days (effective scrape window)**
- ~~Whether Model #5 ships in v1~~ → **yes, Vinted-only**

## Files Pair A still owes Pair B

Per brief §9 sync points:
- EOD Day 3: latency, GPU $/hr, throughput per call
- EOD Day 4: **headline MAPE chart, our pipeline vs GPT-4o-mini per platform** ← critical
- EOD Day 5: hero items, screencast, screenshots
