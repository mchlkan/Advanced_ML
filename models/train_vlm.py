"""QLoRA fine-tune Qwen3-VL-4B-Instruct on the merged Vinted + KA dataset.

Reads pre-computed splits produced by ``notebooks/02_data_prep.ipynb``:
  data/splits/train.parquet   — ~7k rows, canonical English columns
  data/splits/val.parquet     — ~800 rows, used for per-epoch eval loss
  data/splits/test.parquet    — 500-row locked test, NOT touched here

Designed for a single RunPod 4090 (24 GB). At default flags the memory budget is:
  ~5 GB Qwen3-VL-4B in 4-bit + ~1 GB LoRA adapters + ~12 GB activations
  + KV cache at bsz=1, max_len=2048. Headroom for grad_accumulation>=8.

The training prompt MUST match ``src.prompts.get_prompt`` exactly (brief §3.1)
— inference re-uses the same function so any drift here breaks the eval.

Run:
    python -m models.train_vlm \\
        --train-path data/splits/train.parquet \\
        --val-path   data/splits/val.parquet \\
        --out-dir    models/checkpoints/qwen3vl4b-resell-v1

After training, evaluate the adapter against ``data/splits/test.parquet`` by
loading ``model = PeftModel.from_pretrained(base, out_dir)`` and re-running the
spike eval logic from ``notebooks/99_spike.ipynb``.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import torch
from PIL import Image
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForImageTextToText,
    AutoProcessor,
    BitsAndBytesConfig,
    Trainer,
    TrainingArguments,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
from prompts import get_prompt  # noqa: E402  same prompt as inference


MODEL_ID = "Qwen/Qwen3-VL-4B-Instruct"
DEFAULT_TRAIN = REPO_ROOT / "data" / "splits" / "train.parquet"
DEFAULT_VAL = REPO_ROOT / "data" / "splits" / "val.parquet"
DEFAULT_OUT = REPO_ROOT / "models" / "checkpoints" / "qwen3vl4b-resell-v1"


# ---------------------------------------------------------------------------
# Data prep
# ---------------------------------------------------------------------------

_REQUIRED_COLS = (
    "id", "platform", "image",
    "title_en", "description_en", "category_en",
    "condition_en", "color_en", "brand_canon",
    "size", "price",
)


def _decode_image(cell) -> Image.Image:
    """Decode the parquet `image` cell (HF Image feature: {bytes, path})."""
    if isinstance(cell, dict):
        if cell.get("bytes"):
            return Image.open(io.BytesIO(cell["bytes"])).convert("RGB")
        if cell.get("path"):
            return Image.open(cell["path"]).convert("RGB")
    if isinstance(cell, (bytes, bytearray)):
        return Image.open(io.BytesIO(cell)).convert("RGB")
    raise ValueError(f"Unrecognized image cell: {type(cell).__name__}")


def _build_target_json(row: pd.Series) -> str:
    """Build the assistant-turn JSON string from canonical English columns.

    Schema must match ``src.prompts.get_prompt`` field order. Uses indent=2
    to mirror the prompt's `Format:` example so the model imitates layout
    rather than learning to re-format.
    """
    brand = row.get("brand_canon")
    if brand in (None, "UNK") or (isinstance(brand, float) and pd.isna(brand)):
        brand = None
    size = row.get("size")
    if size in (None, "") or (isinstance(size, float) and pd.isna(size)):
        size = None
    obj = {
        "brand": brand,
        "category": row["category_en"],
        "condition": row["condition_en"],
        "color": row["color_en"],
        "size": size,
        "title": row["title_en"],
        "description": row["description_en"],
        "price_eur": float(row["price"]),
    }
    return json.dumps(obj, ensure_ascii=False, indent=2)


def load_split(path: Path) -> pd.DataFrame:
    """Load a pre-built split parquet and shape-check the canonical columns."""
    df = pd.read_parquet(path)
    missing = [c for c in _REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            f"{path} is missing canonical columns: {missing}. "
            f"Re-run notebooks/02_data_prep.ipynb so build_canonical writes them."
        )
    return df


def to_chat_dataset(df: pd.DataFrame) -> Dataset:
    """Wrap each row as {messages, image} matching processor.apply_chat_template."""
    records = []
    for _, row in df.iterrows():
        messages = [
            {"role": "user", "content": [
                {"type": "image"},
                {"type": "text", "text": get_prompt(row["platform"])},
            ]},
            {"role": "assistant", "content": [
                {"type": "text", "text": _build_target_json(row)},
            ]},
        ]
        records.append({"messages": messages, "image": _decode_image(row["image"])})
    return Dataset.from_list(records)


# ---------------------------------------------------------------------------
# Collator: applies the chat template, processes image+text, masks pad tokens.
# ---------------------------------------------------------------------------

class VLMCollator:
    """Builds a batch from chat-formatted records.

    Loss is computed on the full sequence (prompt + answer) — for ~500 training
    rows the prompt-token contribution is small, and proper prompt-masking on
    Qwen3-VL is fiddly because image tokens expand to hundreds of visual
    features in the encoded sequence.
    """

    def __init__(self, processor):
        self.processor = processor
        self.pad_id = processor.tokenizer.pad_token_id
        # Qwen3-VL image placeholder; not in loss.
        self.image_token_id = processor.tokenizer.convert_tokens_to_ids("<|image_pad|>")

    def __call__(self, batch):
        texts = [self.processor.apply_chat_template(
                    b["messages"], tokenize=False, add_generation_prompt=False)
                 for b in batch]
        images = [b["image"] for b in batch]
        encoded = self.processor(
            text=texts, images=images, return_tensors="pt",
            padding=True, truncation=True, max_length=2048,
        )
        labels = encoded["input_ids"].clone()
        labels[labels == self.pad_id] = -100
        if isinstance(self.image_token_id, int) and self.image_token_id >= 0:
            labels[labels == self.image_token_id] = -100
        encoded["labels"] = labels
        return encoded


# ---------------------------------------------------------------------------
# Model + LoRA
# ---------------------------------------------------------------------------

def load_model_and_processor(model_id: str = MODEL_ID):
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForImageTextToText.from_pretrained(
        model_id,
        quantization_config=bnb,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    return model, processor


def attach_lora(model, r: int = 16, alpha: int = 32, dropout: float = 0.05):
    cfg = LoraConfig(
        r=r,
        lora_alpha=alpha,
        lora_dropout=dropout,
        bias="none",
        task_type="CAUSAL_LM",
        # `all-linear` lets peft find every nn.Linear in the language tower.
        # Vision tower attention also gets adapters but rank 16 is cheap.
        target_modules="all-linear",
    )
    model = get_peft_model(model, cfg)
    model.print_trainable_parameters()
    return model


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--train-path", type=Path, default=DEFAULT_TRAIN,
                   help="Train split parquet (canonical English columns). Single-image mode.")
    p.add_argument("--val-path", type=Path, default=DEFAULT_VAL,
                   help="Val split parquet for per-epoch eval loss. Pass empty string to disable.")
    # Multi-image mode: when --manifest is given, --train-path / --val-path
    # are ignored and the dataset is filtered from the manifest by `split`.
    p.add_argument("--manifest", type=Path, default=None,
                   help="Multi-image manifest parquet (output of scripts/build_manifest.py). "
                        "When set, switches to multi-image training and ignores --train-path/--val-path.")
    p.add_argument("--max-images", type=int, default=2,
                   help="Multi-image mode: max photos per listing fed to the model (1 or 2).")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT,
                   help="Where to save the LoRA adapter + processor.")
    p.add_argument("--model-id", default=MODEL_ID)
    # 1-2 epochs is the QLoRA sweet spot at ~7k rows; 3 starts overfitting on
    # a tight LoRA adapter. Watch val loss for the trigger.
    p.add_argument("--epochs", type=int, default=2)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--per-device-batch", type=int, default=1)
    p.add_argument("--grad-accum", type=int, default=8,
                   help="Effective batch = per_device_batch * grad_accum.")
    p.add_argument("--lora-r", type=int, default=16)
    p.add_argument("--lora-alpha", type=int, default=32)
    p.add_argument("--lora-dropout", type=float, default=0.05)
    p.add_argument("--warmup-ratio", type=float, default=0.03)
    p.add_argument("--logging-steps", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--max-train-rows", type=int, default=0,
                   help="Cap training rows (0 = all). Useful for smoke runs.")
    return p.parse_args()


def _build_single_image_datasets(args):
    train_df = load_split(args.train_path)
    if args.max_train_rows > 0 and len(train_df) > args.max_train_rows:
        train_df = train_df.sample(n=args.max_train_rows,
                                    random_state=args.seed).reset_index(drop=True)
        print(f"capped to {len(train_df)} train rows for smoke run")
    train_ds = to_chat_dataset(train_df)
    print(f"train rows: {len(train_ds)}")

    val_ds = None
    val_path_str = str(args.val_path) if args.val_path else ""
    if val_path_str and Path(val_path_str).exists():
        val_df = load_split(args.val_path)
        val_ds = to_chat_dataset(val_df)
        print(f"val rows:   {len(val_ds)}")
    return train_ds, val_ds


def _build_multi_image_datasets(args):
    """Build train/val from manifest. Returns torch Datasets, not HF Datasets."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from multi_image_dataset import VintedMultiImageDataset  # noqa: E402

    train_ds = VintedMultiImageDataset(
        manifest_path=args.manifest, split="train", max_images=args.max_images,
    )
    if args.max_train_rows > 0 and len(train_ds) > args.max_train_rows:
        # Cap by sampling listing_ids deterministically.
        train_ds.df = train_ds.df.sample(
            n=args.max_train_rows, random_state=args.seed,
        ).reset_index(drop=True)
        print(f"capped to {len(train_ds)} train rows for smoke run")
    print(f"train rows: {len(train_ds)}  (multi-image, max_images={args.max_images})")

    val_ds = VintedMultiImageDataset(
        manifest_path=args.manifest, split="val", max_images=args.max_images,
    )
    if len(val_ds) == 0:
        val_ds = None
    else:
        print(f"val rows:   {len(val_ds)}")
    return train_ds, val_ds


def main():
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    multi_image = args.manifest is not None
    if multi_image:
        train_ds, val_ds = _build_multi_image_datasets(args)
    else:
        train_ds, val_ds = _build_single_image_datasets(args)

    model, processor = load_model_and_processor(args.model_id)
    model = attach_lora(model,
                        r=args.lora_r, alpha=args.lora_alpha,
                        dropout=args.lora_dropout)
    model.config.use_cache = False  # required when grad-ckpt is on

    if multi_image:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from multi_image_dataset import MultiImageVLMCollator  # noqa: E402
        collator = MultiImageVLMCollator(processor)
    else:
        collator = VLMCollator(processor)

    training_args = TrainingArguments(
        output_dir=str(args.out_dir),
        overwrite_output_dir=True,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.per_device_batch,
        per_device_eval_batch_size=args.per_device_batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        warmup_ratio=args.warmup_ratio,
        lr_scheduler_type="cosine",
        bf16=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        optim="paged_adamw_32bit",
        logging_steps=args.logging_steps,
        eval_strategy="epoch" if val_ds is not None else "no",
        save_strategy="epoch",
        save_total_limit=1,
        load_best_model_at_end=val_ds is not None,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to="none",
        remove_unused_columns=False,  # keep `messages` / `image[s]` through Trainer
        dataloader_num_workers=2,
        seed=args.seed,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        data_collator=collator,
    )
    trainer.train()

    print(f"saving adapter + processor to {args.out_dir}")
    trainer.model.save_pretrained(args.out_dir)
    processor.save_pretrained(args.out_dir)


if __name__ == "__main__":
    main()
