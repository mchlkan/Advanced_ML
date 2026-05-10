"""Yardstick eval for the Qwen3-VL LoRA — single-image OR multi-image.

Same script runs against:
  * the current single-image LoRA (baseline, mode=single via --vinted-parquet)
  * the new multi-image LoRA           (mode=multi via --manifest)
  * the new LoRA against single-image inputs (graceful-degradation check)

Outputs a per-listing predictions Parquet + a metrics CSV with the field
accuracies, ``parse_ok`` rate, and average latency the plan §4.2 calls for.

Run on the pod (needs a GPU)::

    # baseline against current single-image LoRA
    python scripts/eval_lora.py \\
        --adapter models/checkpoints/qwen3vl4b-resell-v1 \\
        --vinted-parquet data/vinted_clothing_combined.parquet \\
        --splits-dir data/splits \\
        --out-csv eval_results/baseline_single_image.csv

    # new multi-image LoRA against multi-image test split
    python scripts/eval_lora.py \\
        --adapter models/checkpoints/qwen3vl4b-resell-multi-v1 \\
        --manifest /workspace/data/manifest.parquet \\
        --max-images 2 \\
        --out-csv eval_results/multi_image_v1.csv
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import torch
from PIL import Image
from tqdm.auto import tqdm

REPO_ROOT = Path(__file__).resolve().parent.parent
for sub in ("shared", "backend", "src"):
    p = REPO_ROOT / sub
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from prompts import get_prompt  # noqa: E402
from vlm_backend.util import parse_vlm_fields  # noqa: E402


DEFAULT_BASE_MODEL = "Qwen/Qwen3-VL-4B-Instruct"
TARGET_FIELDS = ["brand", "category", "condition", "color", "size"]


# ---------------------------------------------------------------------------
# Test-set loading: single-image (from canonical parquet) or multi-image (manifest)
# ---------------------------------------------------------------------------

def _load_split_ids(splits_dir: Path, split: str = "test") -> set[tuple[str, int]]:
    path = splits_dir / f"{split}_ids.json"
    return {(e["platform"], int(e["id"])) for e in json.load(open(path))}


def _decode_image_cell(cell) -> Image.Image:
    if isinstance(cell, dict):
        if cell.get("bytes"):
            return Image.open(io.BytesIO(cell["bytes"])).convert("RGB")
        if cell.get("path"):
            return Image.open(cell["path"]).convert("RGB")
    if isinstance(cell, (bytes, bytearray)):
        return Image.open(io.BytesIO(cell)).convert("RGB")
    raise ValueError(f"unrecognized image cell: {type(cell).__name__}")


def load_test_single(
    parquet_path: Path,
    splits_dir: Path,
    limit: int | None,
) -> list[dict]:
    """Load test rows from the canonical parquet using the locked test_ids."""
    df = pd.read_parquet(parquet_path)
    test_ids = _load_split_ids(splits_dir, "test")
    df["_key"] = list(zip(df["platform"], df["id"].astype(int)))
    df = df[df["_key"].isin(test_ids)].reset_index(drop=True)
    if limit:
        df = df.head(limit)
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "listing_id": int(r["id"]),
            "platform": r["platform"],
            "images": [_decode_image_cell(r["image"])],
            "expected": {
                "brand": r.get("brand") if pd.notna(r.get("brand")) else None,
                "category": r["category_en"],
                "condition": r["condition_en"],
                "color": r["color_en"],
                "size": r.get("size") if pd.notna(r.get("size")) else None,
            },
        })
    return rows


def load_test_multi(
    manifest_path: Path,
    max_images: int,
    limit: int | None,
) -> list[dict]:
    """Load test rows from the multi-image manifest."""
    df = pd.read_parquet(manifest_path)
    df = df[df["split"] == "test"].reset_index(drop=True)
    if limit:
        df = df.head(limit)
    rows = []
    for _, r in df.iterrows():
        images = [Image.open(r["garment_path"]).convert("RGB")]
        if max_images >= 2 and pd.notna(r.get("label_path")):
            images.append(Image.open(r["label_path"]).convert("RGB"))
        # Manifest carries target_text as JSON; parse it for the expected fields
        target = json.loads(r["target_text"])
        rows.append({
            "listing_id": int(r["listing_id"]),
            "platform": r["platform"],
            "images": images,
            "expected": {
                "brand": target.get("brand"),
                "category": target.get("category"),
                "condition": target.get("condition"),
                "color": target.get("color"),
                "size": target.get("size"),
            },
        })
    return rows


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def load_model(base_model: str, adapter: Path | None, load_in_4bit: bool):
    from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
    from peft import PeftModel

    bnb = None
    if load_in_4bit:
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
    print(f"loading base: {base_model}")
    processor = AutoProcessor.from_pretrained(adapter or base_model, trust_remote_code=True)
    model = AutoModelForImageTextToText.from_pretrained(
        base_model,
        quantization_config=bnb,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )
    if adapter is not None:
        print(f"attaching LoRA adapter: {adapter}")
        model = PeftModel.from_pretrained(model, str(adapter))
    model.eval()
    return model, processor


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def _build_messages(num_images: int, prompt: str) -> list[dict]:
    return [
        {"role": "user", "content": [
            *[{"type": "image"} for _ in range(num_images)],
            {"type": "text", "text": prompt},
        ]},
    ]


def predict_one(model, processor, images: list[Image.Image], platform: str,
                max_new_tokens: int = 512) -> tuple[str, float]:
    prompt = get_prompt(platform)
    messages = _build_messages(len(images), prompt)
    text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = processor(
        text=[text], images=[images], return_tensors="pt",
        padding=True, truncation=True,
    ).to(model.device)
    t0 = time.perf_counter()
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=processor.tokenizer.pad_token_id,
        )
    elapsed = time.perf_counter() - t0
    # Strip the prompt from the output
    new_tokens = out[0][inputs["input_ids"].shape[1]:]
    completion = processor.tokenizer.decode(new_tokens, skip_special_tokens=True)
    return completion, elapsed


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _norm(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    return s if s else None


def score_row(predicted: dict, expected: dict) -> dict[str, bool]:
    out = {}
    for f in TARGET_FIELDS:
        out[f] = _norm(predicted.get(f)) == _norm(expected.get(f))
    return out


def summarize(records: list[dict]) -> dict[str, float]:
    if not records:
        return {}
    df = pd.DataFrame(records)
    summary = {}
    for f in TARGET_FIELDS:
        summary[f"{f}_acc"] = df[f"match_{f}"].mean()
    summary["parse_ok"] = df["parse_ok"].mean()
    summary["recovered"] = df["recovered"].mean()
    summary["avg_latency_warm_s"] = df.iloc[1:]["latency_s"].mean() if len(df) > 1 else df["latency_s"].mean()
    summary["avg_description_words"] = df["pred_description_words"].mean()
    summary["n"] = float(len(df))
    return summary


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run_eval(
    rows: list[dict],
    model,
    processor,
    out_csv: Path,
    out_parquet: Path | None,
) -> dict[str, float]:
    records = []
    for r in tqdm(rows, desc="eval"):
        completion, latency = predict_one(model, processor, r["images"], r["platform"])
        parsed = parse_vlm_fields(completion)
        match = score_row(parsed.fields, r["expected"])
        desc = parsed.fields.get("description") or ""
        records.append({
            "listing_id": r["listing_id"],
            "platform": r["platform"],
            "n_images": len(r["images"]),
            "completion": completion,
            "parse_ok": parsed.parse_ok,
            "recovered": parsed.recovered,
            "latency_s": latency,
            "pred_description_words": len(str(desc).split()),
            **{f"match_{k}": v for k, v in match.items()},
            **{f"pred_{k}": parsed.fields.get(k) for k in TARGET_FIELDS},
            **{f"expected_{k}": r["expected"].get(k) for k in TARGET_FIELDS},
        })

    summary = summarize(records)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([summary]).to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv}")
    print(pd.DataFrame([summary]).T.to_string())

    if out_parquet:
        out_parquet.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(records).to_parquet(out_parquet, index=False)
        print(f"wrote {out_parquet}")

    return summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--adapter", type=Path, default=None,
                   help="LoRA adapter dir. Omit for base-model-only eval.")
    p.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    p.add_argument("--load-in-4bit", action="store_true", default=True)
    p.add_argument("--no-4bit", dest="load_in_4bit", action="store_false")

    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest", type=Path,
                     help="Multi-image manifest parquet (uses split=='test').")
    src.add_argument("--vinted-parquet", type=Path,
                     help="Single-image canonical parquet (filtered by --splits-dir).")

    p.add_argument("--splits-dir", type=Path, default=REPO_ROOT / "data" / "splits",
                   help="Used with --vinted-parquet to filter to the test split.")
    p.add_argument("--max-images", type=int, default=2)
    p.add_argument("--limit", type=int, default=0,
                   help="Cap rows for smoke. 0 = all.")
    p.add_argument("--out-csv", type=Path, required=True,
                   help="Summary metrics CSV.")
    p.add_argument("--out-parquet", type=Path, default=None,
                   help="Optional per-row predictions parquet.")
    return p.parse_args()


def main():
    args = parse_args()
    limit = args.limit if args.limit > 0 else None
    if args.manifest:
        rows = load_test_multi(args.manifest, args.max_images, limit)
        mode = f"multi (max_images={args.max_images})"
    else:
        rows = load_test_single(args.vinted_parquet, args.splits_dir, limit)
        mode = "single"
    print(f"mode: {mode}")
    print(f"test rows: {len(rows)}")

    model, processor = load_model(args.base_model, args.adapter, args.load_in_4bit)
    run_eval(rows, model, processor, args.out_csv, args.out_parquet)


if __name__ == "__main__":
    main()
