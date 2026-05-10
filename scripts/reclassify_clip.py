"""CLIP zero-shot reclassifier for scrapes that lack CLIP type tags.

The scrape ``clothing_2026-05-05_1146`` was collected before Leon's scraper
gained the CLIP-tagging step, so every photo in its ``items.jsonl`` carries
``type: "garment"`` (or no type at all). This script emits a sibling file
``items.jsonl.reclassified`` with the ``type`` field overwritten using
zero-shot CLIP scores, so ``scripts/build_manifest.py`` can pick the right
photo as the label.

Run on the pod (needs a GPU for reasonable speed; CPU works but is slow)::

    python scripts/reclassify_clip.py \\
        --scrape-dir /workspace/data/raw/clothing_2026-05-05_1146 \\
        --device cuda

Defaults to ``openai/clip-vit-base-patch32`` (~150 MB, fast enough). The
prompts are tuned for second-hand clothing scrapes but can be overridden
with ``--prompt-config``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

import torch
from PIL import Image
from tqdm.auto import tqdm
from transformers import CLIPModel, CLIPProcessor


# Class -> list of natural-language prompts. We average the text embeddings
# within a class to make the score less prompt-sensitive. The label class
# subsumes both care labels (sewn-in, listing brand/size/material) and
# retail tags (still attached to new-with-tags items) — both are useful to
# pull as the "label" image at training time.
DEFAULT_PROMPTS: dict[str, list[str]] = {
    "garment": [
        "a photo of a piece of clothing on a hanger or laid flat",
        "a photo of a t-shirt, sweater, jacket, jeans, dress, or shoes",
        "a full view of a clothing item being sold second-hand",
    ],
    "label": [
        "a close-up photo of a clothing care label with washing instructions",
        "a close-up of a sewn-in clothing tag showing brand, size, and material",
        "a photo of a retail price tag attached to a garment",
        "a photo of small printed text on a fabric label",
    ],
}

# Below this margin we mark the photo "uncertain" — manifest builder treats
# uncertain photos as garment by default (safer than mis-tagging a label).
DEFAULT_MARGIN = 0.05


def _build_text_embeddings(
    model: CLIPModel,
    processor: CLIPProcessor,
    prompts: dict[str, list[str]],
    device: str,
) -> tuple[list[str], torch.Tensor]:
    """Mean-pool prompts within each class. Returns (class_names, embedding matrix)."""
    classes = list(prompts.keys())
    flat_texts: list[str] = []
    counts: list[int] = []
    for cls in classes:
        flat_texts.extend(prompts[cls])
        counts.append(len(prompts[cls]))

    inputs = processor(text=flat_texts, return_tensors="pt", padding=True).to(device)
    with torch.no_grad():
        feats = model.get_text_features(**inputs)
    feats = feats / feats.norm(dim=-1, keepdim=True)

    pooled = []
    cursor = 0
    for n in counts:
        pooled.append(feats[cursor:cursor + n].mean(dim=0))
        cursor += n
    pooled = torch.stack(pooled, dim=0)
    pooled = pooled / pooled.norm(dim=-1, keepdim=True)
    return classes, pooled


def _classify_batch(
    model: CLIPModel,
    processor: CLIPProcessor,
    images: list[Image.Image],
    text_embeds: torch.Tensor,
    device: str,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return (probs, image_features) for a list of PIL images."""
    inputs = processor(images=images, return_tensors="pt").to(device)
    with torch.no_grad():
        img_feats = model.get_image_features(**inputs)
    img_feats = img_feats / img_feats.norm(dim=-1, keepdim=True)
    logits = img_feats @ text_embeds.T  # [B, n_classes]
    probs = logits.softmax(dim=-1)
    return probs, img_feats


def _iter_jsonl(path: Path) -> Iterable[dict]:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _resolve_image_path(scrape_dir: Path, obj: dict) -> Path | None:
    """Return the photo path for a single items.jsonl row.

    Supports format A (one row per listing with ``images`` list) by
    *pre-flattening* upstream — this function expects format B (one row
    per photo) so the caller can identify the row to update.
    """
    rel = obj.get("image") or obj.get("path") or obj.get("file")
    if rel is None:
        return None
    return scrape_dir / rel


def reclassify_scrape(
    scrape_dir: Path,
    model_id: str,
    device: str,
    batch_size: int,
    margin: float,
    prompts: dict[str, list[str]],
) -> Path:
    items_path = scrape_dir / "items.jsonl"
    out_path = scrape_dir / "items.jsonl.reclassified"
    if not items_path.exists():
        raise FileNotFoundError(items_path)

    print(f"loading CLIP: {model_id}")
    processor = CLIPProcessor.from_pretrained(model_id)
    model = CLIPModel.from_pretrained(model_id, use_safetensors=True).to(device).eval()
    classes, text_embeds = _build_text_embeddings(model, processor, prompts, device)
    print(f"classes: {classes}")

    rows = list(_iter_jsonl(items_path))
    print(f"{len(rows)} items.jsonl rows")

    # Decide row format. If the first row has a list of photo dicts under
    # `all_photos` (Leon's scraper) or `images` (older guess), explode it so
    # we have one row per photo, then re-collapse on write.
    photos_key = None
    for k in ("all_photos", "images"):
        if isinstance(rows[0].get(k), list) and rows[0].get(k):
            photos_key = k
            break
    is_listing_per_row = photos_key is not None

    if is_listing_per_row:
        photo_rows = []
        for row_idx, obj in enumerate(rows):
            for img_idx, img in enumerate(obj[photos_key]):
                if isinstance(img, str):
                    rec = {"path": img, "type": None}
                else:
                    rec = dict(img)
                photo_rows.append({
                    "_listing_row": row_idx,
                    "_image_idx": img_idx,
                    "abs_path": str(scrape_dir / (rec.get("path") or rec.get("image"))),
                })
        print(f"format A ({photos_key}): {len(photo_rows)} photos across {len(rows)} listings")
    else:
        photo_rows = []
        for row_idx, obj in enumerate(rows):
            p = _resolve_image_path(scrape_dir, obj)
            if p is None:
                continue
            photo_rows.append({
                "_listing_row": row_idx,
                "_image_idx": 0,
                "abs_path": str(p),
            })
        print(f"format B: {len(photo_rows)} photos")

    # Classify in batches.
    new_types: list[tuple[int, int, str, float]] = []
    for start in tqdm(range(0, len(photo_rows), batch_size), desc="classify"):
        chunk = photo_rows[start:start + batch_size]
        imgs = []
        keep = []
        for c in chunk:
            try:
                imgs.append(Image.open(c["abs_path"]).convert("RGB"))
                keep.append(c)
            except Exception as e:
                print(f"  skipping {c['abs_path']}: {e}")
        if not imgs:
            continue
        probs, _ = _classify_batch(model, processor, imgs, text_embeds, device)
        top = probs.topk(2, dim=-1)
        for i, c in enumerate(keep):
            top1_idx = top.indices[i, 0].item()
            top1_prob = top.values[i, 0].item()
            top2_prob = top.values[i, 1].item()
            cls = classes[top1_idx]
            if (top1_prob - top2_prob) < margin:
                cls = "garment"  # uncertain → safer default
            new_types.append((c["_listing_row"], c["_image_idx"], cls, top1_prob))

    # Apply types back into rows.
    if is_listing_per_row:
        for row_idx, img_idx, cls, prob in new_types:
            row = rows[row_idx]
            img = row[photos_key][img_idx]
            if isinstance(img, str):
                row[photos_key][img_idx] = {"path": img, "type": cls, "clip_prob": float(prob)}
            else:
                img["type"] = cls
                img["clip_prob"] = float(prob)
    else:
        for row_idx, _img_idx, cls, prob in new_types:
            rows[row_idx]["type"] = cls
            rows[row_idx]["clip_prob"] = float(prob)

    with open(out_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {out_path}")

    # Quick distribution
    flat = [t[2] for t in new_types]
    from collections import Counter
    print(f"type distribution: {Counter(flat)}")
    return out_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--scrape-dir", type=Path, required=True,
                   help="Path to one clothing_YYYY-MM-DD_HHMM/ directory.")
    p.add_argument("--model-id", default="openai/clip-vit-base-patch32")
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--margin", type=float, default=DEFAULT_MARGIN,
                   help="Min top1-top2 prob gap to trust the label class.")
    p.add_argument("--prompt-config", type=Path, default=None,
                   help="Optional JSON file overriding DEFAULT_PROMPTS.")
    return p.parse_args()


def main():
    args = parse_args()
    prompts = DEFAULT_PROMPTS
    if args.prompt_config:
        prompts = json.load(open(args.prompt_config))
    reclassify_scrape(
        scrape_dir=args.scrape_dir,
        model_id=args.model_id,
        device=args.device,
        batch_size=args.batch_size,
        margin=args.margin,
        prompts=prompts,
    )


if __name__ == "__main__":
    main()
