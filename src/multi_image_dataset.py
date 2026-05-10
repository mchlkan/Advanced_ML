"""Multi-image dataset + collator for Qwen3-VL fine-tuning.

Lazy-loads PIL images from the manifest produced by ``scripts/build_manifest.py``.
Each example is one listing with one or two photos:

    [garment]            — listings without a label-tagged photo
    [garment, label]     — listings whose scrape contains a label-tagged photo

Mixed-mode by design: a single trained adapter handles both cases at inference
because it sees both during training.

Manifest schema (Parquet, produced by ``scripts/build_manifest.py``)::

    listing_id    int       listing id from the scrape
    platform      str       'vinted' | 'kleinanzeigen'
    garment_path  str       absolute path to garment photo
    label_path    str|null  absolute path to label photo, or null
    target_text   str       JSON the assistant turn must emit
    split         str       'train' | 'val' | 'test'
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import pandas as pd
from PIL import Image
from torch.utils.data import Dataset

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
from prompts import get_prompt  # noqa: E402  same prompt source as inference


# Token budget for the processor. Single-image trainer uses 2048; with two
# images Qwen3-VL emits ~2700-3000 tokens of visual features at 768-px input.
# 3072 leaves headroom for the prompt + target without forcing truncation.
DEFAULT_MAX_LEN = 3072


def _load_image(path: str | Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def _is_present(value) -> bool:
    """Truthy iff a path string is set and not pandas-NaN."""
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    return bool(str(value))


def build_messages(num_images: int, prompt: str, target_text: str) -> list[dict]:
    """Chat template with N image placeholders, the prompt, and the target.

    Image order is the convention the model learns: index 0 is the garment,
    index 1 (if present) is the care-label close-up. No slot tags in the
    prompt — positional convention only, per the plan §3.2.
    """
    return [
        {
            "role": "user",
            "content": [
                *[{"type": "image"} for _ in range(num_images)],
                {"type": "text", "text": prompt},
            ],
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": target_text}],
        },
    ]


class VintedMultiImageDataset(Dataset):
    """Torch Dataset over a multi-image manifest parquet.

    Lazy: paths are kept in memory, image bytes are decoded only in
    ``__getitem__`` so the worker processes amortize the I/O.
    """

    def __init__(
        self,
        manifest_path: str | Path,
        split: str | None = None,
        max_images: int = 2,
        prompt_fn: Callable[[str], str] = get_prompt,
    ):
        df = pd.read_parquet(manifest_path)
        required = {"listing_id", "platform", "garment_path", "target_text", "split"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"manifest is missing columns: {sorted(missing)}")
        if split is not None:
            df = df[df["split"] == split].reset_index(drop=True)
        self.df = df
        self.max_images = max_images
        self.prompt_fn = prompt_fn

    def __len__(self) -> int:
        return len(self.df)

    def __getitem__(self, idx: int) -> dict:
        row = self.df.iloc[idx]
        images = [_load_image(row["garment_path"])]
        if self.max_images >= 2:
            label_path = row.get("label_path") if "label_path" in row else None
            if _is_present(label_path):
                images.append(_load_image(label_path))

        messages = build_messages(
            num_images=len(images),
            prompt=self.prompt_fn(row["platform"]),
            target_text=row["target_text"],
        )
        return {"messages": messages, "images": images}


class MultiImageVLMCollator:
    """Mirror of ``models.train_vlm.VLMCollator`` for variable-image batches.

    Qwen3-VL's processor accepts ``images`` either as a flat list (when each
    text contains image placeholders in order) or as a list of per-example
    lists. We use the list-of-lists form because per-example image counts
    vary across the batch (1 vs 2).
    """

    def __init__(self, processor, max_length: int = DEFAULT_MAX_LEN):
        self.processor = processor
        self.max_length = max_length
        self.pad_id = processor.tokenizer.pad_token_id
        self.image_token_id = processor.tokenizer.convert_tokens_to_ids("<|image_pad|>")

    def __call__(self, batch):
        texts = [
            self.processor.apply_chat_template(
                b["messages"], tokenize=False, add_generation_prompt=False
            )
            for b in batch
        ]
        images = [b["images"] for b in batch]
        encoded = self.processor(
            text=texts,
            images=images,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=self.max_length,
        )
        labels = encoded["input_ids"].clone()
        labels[labels == self.pad_id] = -100
        if isinstance(self.image_token_id, int) and self.image_token_id >= 0:
            labels[labels == self.image_token_id] = -100
        encoded["labels"] = labels
        return encoded
