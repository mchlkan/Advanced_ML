"""Run Model #3: zero-shot tag/preis-label visibility detector.

This is intentionally a prompt-only VLM pass. It does not train a model.

Example:

    python models/run_tag_detector.py \
        --model-id Qwen/Qwen3-VL-4B-Instruct \
        --adapter-id <your-finetuned-adapter-or-local-path> \
        --load-in-4bit \
        --output data/features/tag_visible_combined.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import torch
from tqdm.auto import tqdm
from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig

from extract_features import decode_image, load_combined


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VINTED = REPO_ROOT / "data" / "vinted_clothing_combined.parquet"
DEFAULT_KA = REPO_ROOT / "data" / "kleinanzeigen_clothing_combined.parquet"
DEFAULT_SPLITS = REPO_ROOT / "data" / "splits"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "features" / "tag_visible_combined.parquet"
TAG_PROMPT = (
    "Is a clothing tag, label, or price tag visible in this image? "
    "Answer only with 'yes' or 'no'."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", required=True, help="Base VLM model id or local path.")
    parser.add_argument(
        "--adapter-id",
        default=None,
        help="Optional PEFT/LoRA adapter id or local path for the fine-tuned model.",
    )
    parser.add_argument("--vinted-path", type=Path, default=DEFAULT_VINTED)
    parser.add_argument("--ka-path", type=Path, default=DEFAULT_KA)
    parser.add_argument("--splits-dir", type=Path, default=DEFAULT_SPLITS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--max-new-tokens", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None, help="Optional smoke-test row limit.")
    parser.add_argument(
        "--load-in-4bit",
        action="store_true",
        help="Load the base model in 4-bit. Recommended for Colab T4.",
    )
    parser.add_argument(
        "--torch-dtype",
        choices=["auto", "float16", "bfloat16", "float32"],
        default="auto",
        help="Model dtype when not using 4-bit.",
    )
    parser.add_argument(
        "--device-map",
        default="auto",
        help="Passed to from_pretrained. Use 'auto' on RunPod/Colab; use 'none' to call model.to(device).",
    )
    parser.add_argument(
        "--device",
        choices=["auto", "cuda", "mps", "cpu"],
        default="auto",
        help="Used only when --device-map none.",
    )
    return parser.parse_args()


def choose_device(requested: str) -> torch.device:
    if requested != "auto":
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def parse_tag_response(raw: str) -> int | None:
    text = raw.strip().lower()
    text = text.replace(".", "").replace(",", "").replace("!", "")
    first = text.split()[0] if text.split() else ""
    if first in {"yes", "y"}:
        return 1
    if first in {"no", "n"}:
        return 0
    if "yes" in text and "no" not in text:
        return 1
    if "no" in text and "yes" not in text:
        return 0
    return None


def load_model_and_processor(args: argparse.Namespace):
    processor = AutoProcessor.from_pretrained(args.model_id, trust_remote_code=True)
    model_kwargs = {"trust_remote_code": True}
    if args.load_in_4bit:
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
    elif args.torch_dtype != "auto":
        model_kwargs["torch_dtype"] = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }[args.torch_dtype]
    if args.device_map != "none":
        model_kwargs["device_map"] = args.device_map
    model = AutoModelForImageTextToText.from_pretrained(args.model_id, **model_kwargs)

    if args.adapter_id:
        try:
            from peft import PeftModel
        except ImportError as exc:
            raise ImportError("Install peft to load --adapter-id") from exc
        model = PeftModel.from_pretrained(model, args.adapter_id)

    if args.device_map == "none":
        model.to(choose_device(args.device))
    model.eval()
    return model, processor


def model_device(model) -> torch.device:
    return next(model.parameters()).device


def build_messages() -> list[dict]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": TAG_PROMPT},
            ],
        }
    ]


@torch.no_grad()
def run_batch(model, processor, images: list, max_new_tokens: int) -> list[str]:
    texts = [
        processor.apply_chat_template(
            build_messages(),
            tokenize=False,
            add_generation_prompt=True,
        )
        for _ in images
    ]
    encoded = processor(text=texts, images=images, return_tensors="pt", padding=True)
    device = model_device(model)
    encoded = {key: value.to(device) for key, value in encoded.items()}
    generated = model.generate(**encoded, max_new_tokens=max_new_tokens, do_sample=False)
    prompt_len = encoded["input_ids"].shape[1]
    new_tokens = generated[:, prompt_len:]
    return processor.batch_decode(new_tokens, skip_special_tokens=True)


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")

    df = load_combined(args.vinted_path, args.ka_path, args.splits_dir)
    if args.limit is not None:
        df = df.head(args.limit).copy()
        print(f"Smoke-test limit active: {len(df):,} rows")

    model, processor = load_model_and_processor(args)

    rows: list[dict] = []
    for start in tqdm(range(0, len(df), args.batch_size), desc="Detecting visible tags"):
        batch = df.iloc[start:start + args.batch_size]
        images = [decode_image(cell) for cell in batch["image"]]
        raw_responses = run_batch(model, processor, images, args.max_new_tokens)
        for (_, row), raw in zip(batch.iterrows(), raw_responses):
            rows.append(
                {
                    "platform": row["platform"],
                    "id": int(row["id"]),
                    "split": row["split"],
                    "tag_visible": parse_tag_response(raw),
                    "raw_response": raw.strip(),
                }
            )

    out = pd.DataFrame(rows)
    if len(out) != len(df):
        raise ValueError(f"Expected {len(df):,} outputs, got {len(out):,}")
    if out.duplicated(["platform", "id"]).any():
        raise ValueError("Output contains duplicate (platform, id) rows")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.output, index=False)
    print(f"Saved tag-visible features: {args.output}  rows={len(out):,}")
    print("Parsed value counts:")
    print(out["tag_visible"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
