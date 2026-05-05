# Resell Copilot — Technical Brief (Pair A) — v2

**Project:** Resell Copilot — a photo-first selling assistant for second-hand clothing.
**Course:** 2758-T4 Advanced Topics in Machine Learning (Nova SBE), final project — "Build an AI-Driven Startup."
**Timeline:** 7 days.
**Team scope:** 2 people on model + prototype. Other pair (B) handles business plan + pitch.
**Headline metric for the pitch:** Price MAPE on a held-out test set, our pipeline vs GPT-4o-mini (or Claude Haiku) on the same images.

---

## 0. What changed since v1

Read this first if you read the previous brief.

- **Model selection is now open.** Three candidates to smoke-test on Day 1: Qwen2.5-VL-7B, Qwen3.5-4B, Qwen3.5-9B. Lock based on the smoke test, not in advance.
- **Architecture expanded to cover cross-platform comparison.** The price head is now per-platform (Vinted + Kleinanzeigen). New sell-likelihood head added.
- **Data scope expanded.** 7,723-row Vinted scrape (improved condition balance), plus a fresh Kleinanzeigen scrape (in progress), plus a sold-status re-scrape pass for binary "sold within window" labels.
- **Day 1 is now a spike, not the start of the full plan.** Cheap end-to-end test on Colab + minimal RunPod to validate the idea works directionally before committing the rest of the week.
- **Stack changed.** No Streamlit. TypeScript frontend (framework TBD) + Python FastAPI backend + SQLite. Hosting and auth deferred — local demo, no auth for v1.
- **One-click publish reframed honestly.** v1 pre-fills the platform's own listing form; user taps publish on the platform. Full automation lives in the v2 B2B path via Vinted Pro Integrations.
- **Add-on features deferred.** Bundle suggestions, photo coach, validate-then-reprice multi-pass UX — all parked as "core features for post-MVP." Focus is on the core: photo → output → optional verify → cross-platform recommendation → publish.
- **Budget tight.** Total project ~$25-30, with ~$2-5 spent on the Day 1 spike.

---

## 1. What we're building, in one paragraph

A web app where a user uploads a photo of a clothing item and gets back: identification (brand, category, material, size, condition, era), a recommendation on which platform to list on (Vinted or Kleinanzeigen), the suggested price band on each, the likelihood of selling within a window, and a generated listing. The user can optionally edit any field before publishing. On publish, the app opens the chosen platform's own listing form with all fields pre-filled. Behind it: one fine-tuned VLM emitting structured JSON, plus four small heads (visible-flaw via DINOv2 transfer learning, tag-presence via zero-shot prompt, quantile price per platform, sell-likelihood per platform). SQLite logs every model call and user edit from line one.

---

## 2. Day 1 — the spike (read this section before anything else)

The full week's plan only makes sense if the core idea works. The spike validates that on Day 1 for ~$2-5.

**Goal:** by tomorrow evening, you know whether (a) one of the candidate base models loads cleanly, (b) zero-shot or lightly-fine-tuned predictions are sensible, (c) the visible-flaw head and price head produce non-trivial signal on a small subset.

### 2.1 Phase 1 — Colab (free, ~3 hours)

Free Colab T4 runtime is enough for this phase.

1. **Prep the spike data.** Pick 600 rows from the 7,723-row Vinted dataset, stratified by category and condition. Split 500 train / 100 test. Hold out the 100 strictly.

2. **Smoke-test the three model candidates** in 4-bit quantization. For each one:
 - Try to load the model on T4 (16GB VRAM). If it OOMs or throws framework errors, mark as failed.
 - Run zero-shot inference on 10 sample images from your dataset.
 - Eyeball outputs: are they roughly the right format? Does the model identify obvious things correctly?
 - Time the inference per image.

 Candidates, in order of preference for speed of iteration:
 - `Qwen/Qwen3.5-4B` — newest, smallest, fastest to fine-tune later.
 - `Qwen/Qwen2.5-VL-7B-Instruct` — most ecosystem support, safest fallback.
 - `Qwen/Qwen3.5-9B` — best quality if it loads cleanly, may be tight on T4.

 Selection rule: pick the smallest model that (a) loads cleanly, (b) produces sensible zero-shot outputs on your samples. Smaller wins ties because faster fine-tunes mean more iteration.

3. **Run the chosen model zero-shot on the full 100-item held-out set.** Save predictions to disk.

4. **Run GPT-4o-mini (or Claude Haiku) on the same 100 items** with a comparable prompt. Save predictions. Cost: ~$1-2.

5. **Extract DINOv2 embeddings** for all 600 images using `facebook/dinov2-base`. Cache to disk.

6. **Train a tiny visible-flaw head** on the 500 training embeddings. Class-weighted BCE, 50 epochs, MLP. Evaluate AUC on 100 held-out.

7. **Train a tiny price head** on the 500 training examples (zero-shot VLM features for now, since no fine-tune yet). Quantile regression, log-transformed price target. Evaluate MAPE on held-out.

### 2.2 Phase 2 — RunPod (paid, ~1-2 hours, ~$1-3)

Reserved for what Colab can't do well — the actual VLM fine-tune.

8. **Spin up a RunPod community-cloud RTX 4090** (~$0.35/hr) or A100 if needed (~$1.10/hr).

9. **Run a 1-epoch QLoRA fine-tune** on the 500 training examples. Should take 20-40 min on a 4090 for the smaller models.

10. **Save the LoRA adapter, kill the instance immediately.**

### 2.3 Phase 3 — back to Colab (free, ~1 hour)

11. **Reload the base model + your fine-tuned adapter** on Colab.

12. **Run the fine-tuned model on the 100-item held-out set.**

13. **Re-train the price head and flaw head** if you want to use the fine-tuned VLM's features (optional for the spike).

14. **Compute final metrics:**
 - Brand accuracy: zero-shot Qwen vs fine-tuned Qwen vs GPT-4o-mini
 - Category accuracy: same comparison
 - Price MAPE: same comparison
 - Flaw head AUC

### 2.4 Decision gate end of Day 1

Three possible outcomes:

- **Fine-tuned Qwen beats zero-shot Qwen and is competitive with or better than GPT-4o-mini on at least one of {brand, category, price MAPE}.** Idea works. Commit to the full week. Scale up: full data, more epochs, all heads.
- **Fine-tuned Qwen is roughly equal to zero-shot or to GPT-4o-mini.** On the bubble. Diagnose: data quality issue, hyperparameter issue, or wrong base model. Adjust before committing more compute.
- **Nothing works — model doesn't converge, MAPE is huge, flaw head is at chance.** Reframe. Possibly drop the price-head ambition and pitch as "structured listing generation only," with simpler benchmarks.

### 2.5 What you do NOT do during the spike

- Don't tune hyperparameters.
- Don't refactor for production.
- Don't add features.
- Don't try to make it pretty.
- Don't run on the full dataset.

The spike is throwaway. Its only job is to answer "does this work?"

---

## 3. Models to build (full version, post-spike)

### 3.1 Model #1 — Fine-tuned VLM

**Base model:** locked Day 1 via spike. Default expectation: Qwen3.5-4B if it works, Qwen2.5-VL-7B as fallback.

**Purpose:** main VLM. Takes 1 image + a fixed German instruction prompt, emits structured JSON: brand, category, sub-category, material, size, colour, era, title, description, plus tag_visible field (zero-shot from same prompt).

**Input format — image + prompt, always:**

The chat template needs *something* in the user turn — you cannot feed it an image alone.

1. **Base instruction prompt (fixed, hidden from user).** From the dataset README:
 ```
 Erstelle einen Vinted-Eintrag fuer dieses Kleidungsstueck mit Titel,
 Beschreibung, Kategorie und Preis.
 ```
 Hardcoded in the inference pipeline. The user never sees or types it.

2. **Optional seller hints (inference-only).** If the user opts to verify and edits a field, the verified answer is appended on a follow-up call:
 ```
 Erstelle einen Vinted-Eintrag... [Hinweis: Marke ist Zara, Größe M]
 ```

**Critical:** the inference-time prompt must match the training-time prompt exactly. The dataset README's `to_chat` helper bakes in the German instruction; use that same helper at inference.

**Recipe (QLoRA):**
- 4-bit base, LoRA rank 16-32, alpha 32-64, dropout 0.05.
- Adapters on attention + MLP projections.
- 3 epochs, LR 1e-4, cosine schedule + warmup.
- Effective batch size 16 with gradient accumulation.
- Mixed precision (bf16).

**Hardware:** A100 40GB or RTX 4090 24GB (depending on chosen model size). 4B fine-tunes in ~2-3 hours on a 4090; 7B/9B may need an A100 and 4-8 hours.

**Tag-presence as part of the structured output.** Bake `tag_visible: yes/no` directly into the JSON output during fine-tuning if the dataset has it auto-labelable. If not, run as a separate zero-shot prompt at inference time. Decide based on what's faster to set up — both are fine.

### 3.2 Model #2 — Visible-flaw head (DINOv2 + MLP)

**Purpose:** binary classifier — does the photo show visible flaws (pilling, stains, holes, fading, structural wear)?

**Architecture:**
- **Frozen** `facebook/dinov2-base` as feature extractor. ~86M params, no training.
- For each image, extract CLS token embedding (768-dim).
- Trainable MLP: `Linear(768 → 256) → GELU → Dropout(0.2) → Linear(256 → 1) → Sigmoid`.

**Training data (relabeled from the Vinted scrape):**
- Positive class: `condition ∈ {Gut, Zufriedenstellend}` → ~1,540 examples (up from ~717 in v1, after the targeted scrape).
- Negative class: the other three tiers → ~6,180 examples.
- Drop Zufriedenstellend's 54 rows from training (still too few).
- Class-weighted BCE (positive weight ~4× given the new balance).

**Training:**
- Pre-extract DINOv2 embeddings for all images once, cache.
- Train MLP on cached embeddings, AdamW, LR 1e-3, 50 epochs, early stopping on val AUC.
- Trains in <10 min on CPU once embeddings are cached.

**Eval metrics:**
- Binary AUC on held-out test set.
- Precision/recall at threshold 0.5.
- Confusion matrix.
- Calibration plot.

**Critical:** keep DINOv2 frozen.

### 3.3 Model #3 — Tag-presence detector

**Implementation:** either bake into Model #1's output (preferred) or run as a separate zero-shot prompt at inference time.

**Zero-shot prompt:**
> "Ist auf diesem Bild ein Etikett oder Preisschild sichtbar? Antworte nur mit 'ja' oder 'nein'."

No training needed. ~500ms extra per listing if separate, 0ms if baked into Model #1.

### 3.4 Model #4 — Price head, per-platform

**Purpose:** calibrated price band per platform.

**Architecture:**
- MLP: `Linear(input_dim → 512) → ReLU → Dropout(0.2) → Linear(512 → 256) → ReLU → Linear(256 → 5)`.
- Output: 5 quantile values q={0.1, 0.25, 0.5, 0.75, 0.9}.

**Inputs (concatenated):**
- VLM pooled hidden state from Model #1 (~3584-dim or ~3072-dim depending on chosen base model).
- Visible-flaw probability (1-dim, from Model #2).
- Tag-presence flag (1-dim, from Model #3 / Model #1).
- Category one-hot (4-dim).
- Brand embedding (32-dim, learned lookup, OOV → UNK).
- **Platform one-hot (2-dim, Vinted / Kleinanzeigen).**

**Loss:** sum of pinball losses across the 5 quantiles. Standard formulation.

**Training:**
- Target: `price` column. Asking prices, not sold prices. Documented limitation.
- Log-transform target: `log(price + 1)`. Exp at inference.
- Train on combined Vinted + Kleinanzeigen data with platform as input feature (single head, not two).
- Stratify train/val/test by platform AND category.
- AdamW, LR 1e-3, 100 epochs, early stopping.

**Eval metrics:**
- MAE, MAPE, RMSLE per platform.
- Coverage of q10-q90 band per platform (target ~80%).
- Headline chart for the deck.

### 3.5 Model #5 — Sell-likelihood head (per platform)

**Purpose:** binary probability — will this item sell within the chosen time window?

**Architecture:**
- MLP: `Linear(input_dim → 256) → ReLU → Dropout(0.2) → Linear(256 → 1) → Sigmoid`.

**Inputs (concatenated):**
- Same as Model #4 inputs PLUS the asking price (1-dim, log-transformed).
- The model needs to know what price is being evaluated against.

**Training data:**
- From the sold-status re-scrape pass.
- Positive: items that disappeared from the platform within the time window.
- Negative: items still listed at end of window.

**Time window — open decision for Day 1.** Three options:
- 7 days: noisy, but matches the "fast sale" framing.
- 14 days: middle ground.
- 30 days: standard for resale analysis, less noisy, harder to claim "fast sale."

Lock this once the re-scrape data shape is clear. Document the choice and frame honestly: "we use disappearance from the platform as a proxy for sale; some fraction is sellers withdrawing." This caveat goes in the honest limitations section regardless of window.

**Training:**
- Class-weighted BCE.
- Same train/val/test splits as Model #4.

**Eval metrics:**
- AUC per platform.
- Precision/recall at threshold 0.5.
- Calibration plot.

**Critical dependency:** this model only works if the re-scrape produces clean labels. If the scrape is delayed or produces too-noisy data, drop Model #5 from v1 — the cross-platform price comparison still works without it.

---

## 4. Data

### 4.1 Current Vinted dataset (in hand)

7,723 rows. New condition distribution after the targeted scrape:

| Condition | Count | % |
|---|---|---|
| Sehr gut | 4,167 | 54.0% |
| Gut | 1,488 | 19.3% |
| Neu | 1,181 | 15.3% |
| Neu, mit Etikett | 833 | 10.8% |
| Zufriedenstellend | 54 | 0.7% |

The "Gut" class doubled from the v1 dataset — strong improvement for the flaw head.

Schema unchanged from the v1 README (image, target_text, price, brand, category, condition, etc.).

### 4.2 Kleinanzeigen scrape (in progress)

Schema unknown until the scrape lands. **Day 1 task: compare schemas field by field.** Likely differences:
- Different condition vocabulary. May have fewer or different tiers; need to map to the Vinted vocabulary.
- Different category taxonomy. May not have the 4-category structure exactly.
- Different price/currency format.
- Possibly different language coverage (more German-only, less French).

Build a `normalize_kleinanzeigen.py` script that maps the Kleinanzeigen schema to the Vinted-canonical schema. Run it as the first data-prep step.

If condition labels don't align cleanly, normalize to a 3-tier coarse mapping (Premium / Standard / Worn) on both platforms. Train the flaw head on this coarsened binary (Worn = positive class).

### 4.3 Sold-status re-scrape (planned)

For each item ID in the Vinted dataset (and Kleinanzeigen once available), check the listing's status some time after the original scrape. Three possible labels:
- Active (still listed)
- Sold (Vinted shows a "sold" marker on the listing page; verify if Kleinanzeigen does too)
- Delisted (gone but no sold marker — could be sold or seller-withdrawn)

If Vinted exposes a "sold" marker, use it. Otherwise treat "still listed" vs "gone" as a noisier proxy and frame honestly.

**Day 1 decision:** lock the time window (7/14/30 days) and the label vocabulary based on what the re-scrape can actually produce. Tell the business pair the result so they can write Section 9 of the business plan accordingly.

### 4.4 Filtering before training

- Drop `condition == "Zufriedenstellend"` (54 rows).
- Filter `description.str.len() >= 30` (~15% drop).
- Drop rows where critical fields (price, category) are null.
- Result: ~6,200-6,500 usable Vinted rows + whatever Kleinanzeigen produces.

### 4.5 Splits

- **Test set: 500 rows, locked from training**, stratified by category and condition AND platform once Kleinanzeigen is in.
- **Train/val: 90/10 of the remainder**, stratified the same way.
- Save splits as a fixed list of `id` values committed to the repo.

### 4.6 Public datasets

Not used in v1. The DINOv2 pretraining (free, downloaded once) is the only "public data" leveraged.

---

## 5. The application

### 5.1 Stack (locked)

- **Frontend:** TypeScript. Framework TBD (recommend Next.js — handles file upload, easy deploy). Decided by Pair A on Day 2.
- **Backend:** **Python + FastAPI.**
- **Database:** **SQLite** (file-based, no setup). Migrate to Postgres post-MVP if needed.
- **Auth:** **Deferred.** No login for v1 demo. If time permits late in the week, add SQLite users table + JWT sessions.
- **Hosting:** **Default local** (laptop runs both frontend dev server and backend during demo). Hosted backend is a stretch decision for Day 5.
- **Logging:** SQLite table from line one. Every model call, every user edit, every publish action.

### 5.2 Repo structure

```
resell-copilot/
├── data/
│ ├── vinted_clothing_v1.parquet
│ ├── kleinanzeigen.parquet # arrives Day 1+
│ ├── splits/{train,val,test}.json
├── models/
│ ├── train_vlm.py
│ ├── extract_features.py
│ ├── train_flaw_head.py
│ ├── train_price_head.py
│ ├── train_sell_head.py
│ └── checkpoints/ # gitignored
├── eval/
│ ├── run_baseline.py # GPT-4o-mini predictions
│ ├── run_ours.py
│ ├── compute_metrics.py
│ └── results/
├── backend/ # FastAPI
│ ├── main.py # app entry
│ ├── pipeline.py # inference orchestration
│ ├── db.py # SQLite logging
│ └── routes/
│ ├── upload.py # POST /upload (image in, predictions out)
│ ├── publish.py # POST /publish (logs intent, returns prefilled platform URL)
│ └── verify.py # POST /verify (user edits, re-runs price head)
├── frontend/ # TypeScript
│ ├── src/
│ │ ├── pages/
│ │ ├── components/
│ │ └── api/
│ └── ...
├── notebooks/
│ ├── 01_data_exploration.ipynb # done
│ ├── 02_data_prep.ipynb
│ ├── 03_baseline_apis.ipynb
│ ├── 04_eval.ipynb
│ ├── 05_demo_sandbox.ipynb
│ └── 99_spike.ipynb # Day 1 spike
└── README.md
```

### 5.3 Backend endpoints (FastAPI)

`POST /upload`
- Input: image file.
- Backend: runs full pipeline (Model #1 → #2 → #3 → #4 → #5 for both platforms).
- Output: JSON with all predictions, confidence scores, and per-platform price + sell-likelihood.
- Logged to SQLite.

`POST /verify`
- Input: image_id + user-edited fields (brand, size, etc.).
- Backend: re-runs Model #4 (and optionally #5) with the validated fields.
- Output: updated price band and sell-likelihood.
- Logged to SQLite as user-edit preference data.

`POST /publish`
- Input: image_id + chosen platform + final field values.
- Backend: logs the publish action, returns a URL to the platform's listing form pre-filled with all fields as URL query parameters or a deep link if the platform supports it.
- The frontend opens this URL in a new tab. User completes publish on the platform.

`GET /history` (post-MVP, only with auth)
- Returns user's past listings.

### 5.4 Frontend flow

1. **Landing:** "Upload a photo of your clothing item."
2. **After upload:** spinner, then result page.
3. **Result page:**
 - Photo preview at top.
 - Identification block (brand, category, condition tier, etc.) with each field marked confident or uncertain.
 - **"Edit details"** button (opens an editable form for verification — optional for the user).
 - Cross-platform recommendation block:
 - "List on **Vinted** at €38 — sells in 30 days at ~65% probability."
 - "List on **Kleinanzeigen** at €30 — sells in 30 days at ~78% probability."
 - "Recommendation: Kleinanzeigen sells faster, Vinted gets better price."
 - Generated listing copy preview (title + description) for the chosen platform, editable.
 - **"Publish on [platform]"** button. Opens the platform's listing form pre-filled.
4. **Optional:** edit-and-republish loop if the user wants to change the platform.

### 5.5 What's NOT in v1

These are explicitly out of scope; mention as "core features for post-MVP" in the business plan roadmap:

- User accounts and login.
- Bundle suggestions across the user's listing history.
- Quantified photo coach (e.g., "adding a tag photo lifts price by €X"). Inline tooltips are fine if they fit naturally; full feature is not.
- Closet scan (multi-item detection from one wide photo).
- Validate-then-reprice as a forced flow. Verify is optional via the edit button.
- Active-learning dashboard. Logging happens; visualization is post-MVP.
- Era-specific pricing (vintage Levi's etc.).
- Per-platform tone-tuned LoRA adapters.
- Comp retrieval for the price head.
- Hosted backend.
- Authentication / authorization.

---

## 6. Evaluation harness

Build on Day 1 alongside data prep. Must be ready before any model training so we measure consistently.

### 6.1 Files

- `eval/test_set.parquet` — locked 500-row test set (per-platform stratified once Kleinanzeigen is in).
- `eval/run_baseline.py` — runs GPT-4o-mini and Claude Haiku on the test set, saves predictions.
- `eval/run_ours.py` — runs our pipeline.
- `eval/compute_metrics.py` — computes all metrics from a predictions file.

### 6.2 Metrics to report

**For the headline benchmark (price head, per platform):**
- MAPE, MAE, RMSLE.
- Coverage of q10-q90 band.
- All metrics computed per category × platform.

**For the VLM (categorical fields):**
- Brand exact-match accuracy (with case normalization).
- Category top-1 accuracy.
- Color top-1 accuracy.
- Title/description: BLEU-4 and BERTScore vs. seller's text.

**For the flaw head:**
- AUC, precision/recall at 0.5, confusion matrix.

**For the sell-likelihood head:**
- AUC per platform, calibration plot.

### 6.3 The headline charts for the deck

1. **Price MAPE per category × platform**, our pipeline vs GPT-4o-mini. Should clearly show our model winning on at least 2 of 4 categories.
2. **Cross-platform comparison example:** one picture, two platforms, two prices and two sell probabilities, side by side.

---

## 7. Honest limitations to acknowledge

These come up in the pitch. Lead with them rather than be ambushed.

- **Asking prices, not sold prices.** v1 trains on the asking-price distribution; v2 with platform partnership trains on clearing prices.
- **Sold-status proxy noise.** Re-scrape distinguishes "still listed" from "gone" with a sold marker where available. Some "gone" items are seller withdrawals, not sales. Documented.
- **One photo per listing.** Production users upload 4-8 photos; we have hero shots only. Multi-photo cross-referencing is on the v2 roadmap.
- **DE-dominant data.** Strong on DE Vinted and DE Kleinanzeigen; weaker on French and EN markets. Single-market launch in the GTM.
- **Brand labels are seller-claimed.** No authenticity verification. Uncertain luxury items abstain and route to existing authentication services.
- **Two platforms, not many.** v1 is the cross-platform proof of concept. Adding Vestiaire, Depop, Grailed is roadmap.
- **No user accounts.** Demo runs without auth. Adding it in v2.
- **Manual publish via prefilled forms, not full automation.** Vinted and Kleinanzeigen do not expose listing APIs to individual sellers. The B2B path via Vinted Pro Integrations is in the v2 roadmap.

---

## 8. Day-by-day for Pair A

### Day 1 — the spike (see Section 2 for full detail)

**Morning (Colab):**
- Smoke-test all 3 candidate models. Lock the choice.
- Pick 600 rows, split 500 train / 100 test.
- Run zero-shot baseline on chosen model and on GPT-4o-mini for the 100-item set.
- Pre-extract DINOv2 embeddings for the 600.

**Afternoon (RunPod, then back to Colab):**
- 1-epoch QLoRA fine-tune on 500 examples.
- Run fine-tuned model on held-out 100.
- Train tiny flaw head and price head on the 500.
- Compute metrics, compare.

**EOD: decision gate.** Hand baseline numbers + Day 1 verdict to Pair B.

### Day 2 — scale up (assuming spike succeeded)

- Apply data filters (drop Zufriedenstellend, length filter, null drops). Save filtered train+val.
- Build the locked 500-row held-out test set with platform stratification.
- Run baseline APIs (GPT-4o-mini + Claude Haiku) on the locked test set. Save predictions.
- Pre-extract DINOv2 embeddings for full dataset (cache).
- Train final visible-flaw head on full data.
- Kick off full QLoRA fine-tune of the chosen VLM on RunPod (background, several hours).
- Set up FastAPI backend skeleton + SQLite schema + first endpoint stubs.

**Day 2 also: compare Vinted and Kleinanzeigen schemas, write normalization.** Critical task — without this, you can't combine the data for training.

### Day 3 — heads + integration

- After VLM training finishes: pre-extract pooled hidden states for all training images.
- Train per-platform price head with pinball loss.
- Train sell-likelihood head if re-scrape data is ready.
- Wire up FastAPI inference pipeline. End-to-end test: image POST → JSON response.
- Build the TypeScript frontend skeleton: upload UI, results page, edit form, publish button.
- Add SQLite logging on every endpoint.

### Day 4 — features + headline benchmark

- Wire up the cross-platform recommendation logic.
- Wire up the optional verify flow (edit form → re-call /verify endpoint → updated price/sell numbers).
- Wire up the publish flow (open prefilled platform URL).
- **Run the full pipeline on the held-out test set. Compute MAPE per platform vs GPT-4o-mini. Generate the headline chart.**
- **Hand chart + latency/cost numbers to Pair B EOD.** Critical handoff.

### Day 5 — polish + screencast

- Curate 5-8 hero items that demo the model at its best.
- Polish the UI (acceptable visual quality, not pixel-perfect).
- **Record a backup screencast of the full demo flow.**
- Hand unit-economics inputs to Pair B.

### Day 6 — mock judging + fixes

- Run the full prototype through Claude/ChatGPT acting as a critical AI judge.
- Bug-bash the demo flow on hero items.
- If ahead of schedule: pick ONE add-on feature (validate-then-reprice multi-pass, or simple bundle UI on a fabricated profile, or photo-coach inline hints).

### Day 7 — buffer

- No new work. Final smoke tests. Sleep.

---

## 9. Cross-pair sync points (non-negotiable)

| When | What you give to Pair B | What you receive |
|---|---|---|
| EOD Day 1 | Spike verdict + GPT-4o-mini baseline numbers | (nothing) |
| EOD Day 2 | Confirmation of scale-up training kicked off | (nothing) |
| EOD Day 3 | Latency, GPU $/hr, throughput per call | (nothing) |
| EOD Day 4 | **Headline MAPE chart, our pipeline vs GPT-4o-mini per platform** | (nothing) |
| EOD Day 5 | Hero items, screencast, screenshots | Mock-judge questions for Day 6 |
| EOD Day 6 | Mock-judge feedback (joint session) | (nothing) |

If any of these handoffs slip, flag immediately.

---

## 10. Infrastructure and budget

### 10.1 Accounts to set up Day 0

- GitHub (free).
- RunPod ($30 credit; will use ~$15-20 across the week).
- HuggingFace (free; for model downloads, optional adapter uploads).
- OpenAI (~$5 credit for GPT-4o-mini baseline calls).
- Optional: Anthropic API for Claude Haiku as second baseline (~$3).
- Wandb (free tier; for tracking training runs).

### 10.2 Cost breakdown (estimated)

| Item | Cost |
|---|---|
| Day 1 spike (RunPod 4090, 1 hour) | $1 |
| Full VLM fine-tune (Day 2, A100 4-8 hrs) | $5-10 |
| Feature extraction passes | $2 |
| Re-runs for bug fixes | $5 |
| Inference during demo prep | $2 |
| GPT-4o-mini + Claude Haiku baselines | $5 |
| **Total** | **~$22-25** |

Split among 4 people: <€7 each.

### 10.3 GPU choice rules

- **For inference and small-MLP training:** Colab T4 (free) or laptop CPU.
- **For QLoRA fine-tune on 4B model:** RunPod community-cloud RTX 4090 (~$0.35/hr).
- **For QLoRA fine-tune on 7B/9B model:** RunPod A100 40GB (~$1.10/hr).
- Save adapter weights only. Kill instances immediately after each job.

---

## 11. What success looks like

**Minimum viable for the grade:**
- Frontend uploads a photo, calls backend, renders structured JSON.
- Cross-platform price comparison (even if sell-likelihood is dropped to v2 due to data issues).
- Backup screencast in case live demo fails.
- All metrics reported in the deck.

**What gets us the 20:**
- Clean, fast demo on hero items with no live failures.
- Fine-tuned model beats GPT-4o-mini on MAPE on both platforms.
- Optional verify flow visibly tightens the price band.
- Sell-likelihood numbers per platform produce intuitive recommendations.
- One stretch feature (photo-coach inline hint, or simple bundle profile) integrated cleanly.

**What loses us the 20:**
- Fine-tune doesn't converge (mitigation: spike on Day 1 catches this; fall back to zero-shot Qwen + heads-only).
- MAPE chart is unfavorable (mitigation: by Day 4 EOD we know; reframe pitch around categories where we win, or around the cross-platform recommendation rather than absolute price accuracy).
- Demo crashes live (mitigation: screencast).
- Tried to do too much and shipped nothing well (mitigation: this brief — stick to the core, defer add-ons).

---

## 12. Open decisions (lock by Day 1 EOD)

1. **Base model:** Qwen3.5-4B vs Qwen3.5-9B vs Qwen2.5-VL-7B. Lock via spike.
2. **Sold-status time window:** 7/14/30 days. Lock based on re-scrape data shape.
3. **Tag-presence:** baked into Model #1 output, or separate zero-shot call. Lock based on what's faster to implement.
4. **Whether Model #5 ships in v1.** If re-scrape labels are noisy or delayed, drop sell-likelihood and ship cross-platform price comparison only.
5. **Frontend framework:** Next.js vs Vite + React vs other. Pair A decides Day 2.

---

## 13. Reference files

- `vinted_clothing_v1_README.md` — original dataset README. Use the `to_chat` helper.
- `resell_copilot_proposal.pdf` — the original business framing. Quote freely for the moat story.
- `Project_Description.pdf` — the course rubric. Keep next to you.
- `resell_copilot_business_brief.md` — Pair B's brief. Their handoff requirements drive your sync points.
