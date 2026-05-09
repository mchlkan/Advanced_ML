# Multi-Image VLM Fine-Tuning Plan

Goal: retrain the Qwen3-VL-4B LoRA on multi-image input (garment + label) so the
model can read brand, size, and material directly from care labels instead of
guessing from the cover photo alone.

## Decisions locked in

| | |
|---|---|
| GPU | Dedicated 24 GB RunPod pod (network volume for persistent storage) |
| Drive access | Private — needs auth (`rclone` with OAuth, or upload to HF) |
| No-CLIP scrape (`clothing_2026-05-05_1146`) | Re-classify with CLIP, include in training |
| Description target augmentation | Out of scope (teammate is doing this separately) |
| Base model | Qwen3-VL-4B (unchanged) |
| Adapter retraining | New LoRA from scratch |

## Scope

**In scope**: data verification, data prep, multi-image dataset class, eval harness.
**Out of scope** (separate plans): the training run itself, inference-side
integration (`/upload` accepting 2 photos, RunPod handler updates, frontend
photo picker), description target augmentation.

## Time budget

| Phase | Active work | Wall time |
|---|---|---|
| 1. Verify CLIP classification | 1.5 hrs | 2 hrs |
| 2. Pull data + re-classify no-CLIP scrape | 1.5 hrs | 2-4 hrs (download wait) |
| 3. Build multi-image dataset class | 2 hrs | 2-3 hrs |
| 4. Eval harness + baseline | 1.5 hrs | 1-2 hrs |
| **Total to "ready to train"** | **~6-7 hrs** | **~1 day** |

Training and inference integration are separate plans, ~1.5 days combined.

---

## Phase 1 — Verify CLIP classification (~2 hrs)

The bulk of the dataset (6,898 listings) was tagged at scrape time with CLIP
zero-shot classification (prompts in
`/Users/leonschmidt/Projekte/Vinted/vinted-lister/src/scrape_dataset.py:39-42`).
Need to confirm those tags are accurate before training on them.

### 1.1 Pull a verification sample (30 min)
- Use `rclone` (configured with the maintainer's Google account) to pull the
  `images/` directory of one CLIP-classified scrape — `clothing_2026-04-26_2110`
  is smallest (474 listings, ~1700 photos).
- Don't pull the full zip yet; verify on the sample first.

### 1.2 Write `notebooks/06_verify_clip_tags.ipynb` (45 min)
Two outputs:

**(a) Programmatic OCR-density check.** For 200 random "label"-tagged photos
and 200 random "garment"-tagged photos, run pytesseract OCR and count detected
words. Real labels have 5-30 detected words; real garment shots have <3.

```python
import pytesseract
from PIL import Image

def label_score(image_path):
    txt = pytesseract.image_to_string(Image.open(image_path))
    return len([w for w in txt.split() if len(w) > 2])
```

Expected output:
```
"label" tags:    195/200 have ≥5 words (97.5% likely correct)
"garment" tags:   18/200 have ≥5 words (91.0% likely correct)
```

**(b) Manual sample export.** Copy 50 random photos from each tag class into
`./samples/label/` and `./samples/garment/` for eyeball verification.

### 1.3 Decision gate (15 min)

| Outcome | Next action |
|---|---|
| ≥80% of "label" tags pass OCR + eyeball | Use tags as-is |
| 60-80% pass | Use tags but add OCR-density override at training time |
| <60% pass | Re-classify all photos with stricter CLIP thresholds or OCR-only |

### Deliverable
A confidence number for the existing tags + the script that produced it.

---

## Phase 2 — Pull data + re-classify no-CLIP scrape (~2-4 hrs)

### 2.1 Configure RunPod pod (30 min)
- Provision a 24 GB pod (RTX 4090 or A5000)
- Attach a network volume (≥80 GB; persists across pod restarts)
- Mount at `/workspace/data/`

### 2.2 Configure rclone for Drive access (15 min)
The Drive folder isn't public, so `gdown` won't work. Use `rclone`:

```bash
apt install rclone
rclone config  # OAuth flow — paste link into browser, paste token back
rclone copy gdrive:vinted-images.zip /workspace/data/
```

If rclone proves flaky on the pod, fallback: download the zip to laptop, then
`huggingface-cli upload` to a private dataset, then `huggingface-cli download`
on the pod. More reliable for large files.

### 2.3 Unzip and verify (30 min)
```bash
unzip /workspace/data/vinted-images.zip -d /workspace/data/raw/
# Verify: a sample image referenced in items.jsonl actually exists on disk
python -c "
import json
from pathlib import Path
sample = next(open('/workspace/data/raw/clothing_2026-04-27_1243/items.jsonl'))
obj = json.loads(sample)
img = Path('/workspace/data/raw/clothing_2026-04-27_1243') / obj['image']
print('exists:', img.exists())
"
```

### 2.4 Re-classify the no-CLIP scrape (30-60 min compute)
For `clothing_2026-05-05_1146` (825 listings, currently all tagged "garment"):

Option A — re-run the scraper script with `--use-clip` against existing photos
(needs the scraper's CLIP loader; check
`/Users/leonschmidt/Projekte/Vinted/vinted-lister/src/scrape_dataset.py:86-135`).

Option B — simpler: write a standalone script
`scripts/reclassify_clip.py` that loads CLIP once, iterates the scrape's
photos, emits a new `items.jsonl.reclassified` with type tags filled in.

Update the manifest to reflect `use_clip_classification: true (reclassified)`.

### 2.5 Build the unified manifest (1 hr)
Single Parquet file as the training source of truth. Notebook
`notebooks/07_build_manifest.ipynb`:

```python
# columns:
#   listing_id          int
#   garment_path        str   (first garment-tagged photo, absolute path)
#   label_path          str?  (first label-tagged photo, or null)
#   target_text         str   (JSON the LoRA learns to emit)
#   split               str   ('train' | 'val' | 'test')
```

Splits deterministic by `hash(listing_id) % 100`: 0-79 train, 80-89 val, 90-99 test.

Filter rules:
- Drop listings without a garment photo (shouldn't happen, but guard)
- Keep listings without a label photo (mixed-mode training; `label_path = null`)
- Drop listings with target_text < 10 chars or > 2000 chars

### Deliverable
- `/workspace/data/manifest.parquet`
- ~6,200 train / ~770 val / ~770 test listings

---

## Phase 3 — Multi-image dataset class (~2-3 hrs)

### 3.1 `src/multi_image_dataset.py` (1 hr)

```python
class VintedMultiImageDataset(Dataset):
    def __init__(self, manifest_path, processor, max_images=2):
        self.df = pd.read_parquet(manifest_path)
        self.processor = processor
        self.max_images = max_images

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        images = [load_image(row.garment_path)]
        if row.label_path is not None and self.max_images >= 2:
            images.append(load_image(row.label_path))

        messages = build_messages(images, target_text=row.target_text)
        return self.processor.apply_chat_template(messages, ...)
```

### 3.2 Prompt template (30 min)
Stick with the simplest approach (your friend's recommendation): no slot tags
in the prompt, fixed image order `[garment, label]`, model learns positional
convention from training.

```python
def build_messages(images, target_text, platform="vinted"):
    return [
        {"role": "user", "content": [
            *[{"type": "image", "image": img} for img in images],
            {"type": "text", "text": get_prompt(platform)},
        ]},
        {"role": "assistant", "content": target_text},
    ]
```

`get_prompt()` from `shared/prompts.py` stays untouched. Same JSON schema target.

### 3.3 Sanity-check on 5 examples (30 min)
Before training, feed 5 examples through the processor and verify:
- Token counts (vision + text combined): expect ~3000 with 2 images
- Images correctly placed in the chat template
- Target JSON parses cleanly
- Memory footprint of one batch: should be <12 GB on the 24 GB pod

### 3.4 max_images decision
Default to 2 (`garment + label`). Tradeoffs already analyzed; revisit only if
GPU memory turns out to be more generous than expected.

### Deliverable
A `VintedMultiImageDataset` class returning properly formatted multi-image
training examples, validated on 5 sample inputs.

---

## Phase 4 — Eval harness + baseline (~1-2 hrs)

Built **before** training so we have the yardstick ready.

### 4.1 Test set (30 min)
The 770 listings with `split == "test"` from `manifest.parquet`. Ground-truth
fields come from the original Vinted scrape.

### 4.2 `scripts/eval_lora.py` (1 hr)
Inputs: any VLMBackend.

Outputs per backend (CSV):

| Metric | How |
|---|---|
| Brand exact-match | string equality after lowercasing |
| Category accuracy | exact match |
| Condition accuracy | exact match against canonical set |
| Color accuracy | exact match |
| Size accuracy | exact match |
| `parse_ok` rate | JSON parses successfully |
| Avg latency (warm) | wall-clock minus first-call cold-start |
| Avg description word count | sanity-check description length |

Same script runs against current single-image LoRA, the new multi-image LoRA,
and (later) GPT-4o-mini for the comparison slide.

### 4.3 Lock in baseline numbers (30 min)
Run `eval_lora.py` against the current production VLMBackend (single-image,
4B + existing LoRA, 4-bit). Save to `eval_results/baseline_single_image.csv`.

### Deliverable
The yardstick: a CSV of current model performance on the held-out 770.

---

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| CLIP tags <60% accurate | Low | Phase 1 catches this; fallback to OCR-density tagging |
| Drive download fails / rate-limits | Medium | rclone first, HuggingFace dataset upload as backup |
| Photos referenced in JSONL don't exist on disk | Medium | Phase 2.3 sanity-check catches it before training |
| Multi-image training OOMs on 24 GB | Medium | Lower image resolution to 672×672; drop to max_images=1 with mixed-mode |
| LoRA regresses on description quality | Medium | Eval harness catches this; keep best checkpoint not last |
| LoRA overfits to label-reading and loses style understanding | Low-medium | Validation loss with early stopping |

---

## Files to create

```
docs/
  multi_image_finetuning_plan.md      (this file)

notebooks/
  06_verify_clip_tags.ipynb           (Phase 1.2)
  07_build_manifest.ipynb             (Phase 2.5)
  08_eval_harness.ipynb               (Phase 4.2 wrapper if useful)

scripts/
  reclassify_clip.py                  (Phase 2.4)
  eval_lora.py                        (Phase 4.2)

src/
  multi_image_dataset.py              (Phase 3.1)

# On the pod, not in repo:
/workspace/data/raw/                  (unzipped images)
/workspace/data/manifest.parquet      (Phase 2.5 output)

# In repo, generated:
eval_results/
  baseline_single_image.csv           (Phase 4.3)
```

---

## What's next after this plan

Two follow-up plans, separately:

1. **Training plan** — kick off the multi-image LoRA training run, monitor
   eval loss, save checkpoints, deploy the best one. ~1 day wall time
   (~8 GPU-hours active training).

2. **Inference integration plan** — extend `VLMBackend` interface to accept
   image lists, update RunPod handler, update `/upload` endpoint for multipart
   with 1-2 files, update frontend photo picker. ~half day.

Both gate on this plan completing successfully.
