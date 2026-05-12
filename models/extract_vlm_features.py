"""Extract fine-tuned Qwen pooled hidden states for Model #4.

This is the expensive RunPod/Colab step. It loads the Qwen base model plus the
LoRA adapter, runs one forward pass per item with the platform-specific English
listing prompt, and caches one 2560-dim vector per row.

RunPod smoke test:

    python models/extract_vlm_features.py \
        --adapter-id mchlkan/qwen3vl4b-resell-adapter-multi-v2 \
        --load-in-4bit \
        --limit 5

Full single-image run:

    python models/extract_vlm_features.py \
        --adapter-id mchlkan/qwen3vl4b-resell-adapter-multi-v2 \
        --load-in-4bit

Full multi-image run (feeds the care-label photo when available):

    python models/extract_vlm_features.py \
        --adapter-id mchlkan/qwen3vl4b-resell-adapter-multi-v2 \
        --manifest /workspace/data/manifest.parquet \
        --load-in-4bit
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from peft import PeftModel
from tqdm.auto import tqdm
from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig

# decode_image / load_combined are imported lazily in main() so serving
# environments can reuse build_inputs / model_device without installing pandas.


REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_DIR = REPO_ROOT / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from prompts import get_prompt  # noqa: E402


DEFAULT_BASE_MODEL = "Qwen/Qwen3-VL-4B-Instruct"
# Multi-image v3 (2026-05-11). Adds KA listings to the training manifest (was
# Vinted-only through v2): CLIP-tagged care-label photos for KA via
# scripts/reclassify_clip.py, then build_manifest.py merged. Same hyperparams
# and target schema as v2 (no description, includes price_eur auxiliary). See §4.4.
DEFAULT_ADAPTER = "mchlkan/qwen3vl4b-resell-adapter-multi-v3"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "embeddings" / "vlm_pooled_combined.npy"
DEFAULT_INDEX = REPO_ROOT / "data" / "embeddings" / "vlm_pooled_combined_index.parquet"
DEFAULT_VINTED = REPO_ROOT / "data" / "vinted_clothing_combined.parquet"
DEFAULT_KA = REPO_ROOT / "data" / "kleinanzeigen_clothing_combined.parquet"
DEFAULT_SPLITS = REPO_ROOT / "data" / "splits"


def load_label_lookup(manifest_path: Path) -> dict[tuple[str, int], str]:
    """Build (platform, id) -> label_path from the multi-image manifest.

    Only rows whose ``label_path`` is non-null and points to an existing file
    are included. Missing files are dropped silently — this is best-effort
    enrichment, not a hard requirement.
    """
    import pandas as pd

    df = pd.read_parquet(manifest_path)
    required = {"platform", "listing_id", "label_path"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"manifest is missing columns: {sorted(missing)}")
    lookup: dict[tuple[str, int], str] = {}
    for plat, lid, lpath in zip(df["platform"], df["listing_id"], df["label_path"]):
        if lpath is None:
            continue
        if isinstance(lpath, float) and pd.isna(lpath):
            continue
        s = str(lpath)
        if not s or not Path(s).exists():
            continue
        lookup[(str(plat), int(lid))] = s
    return lookup


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER)
    parser.add_argument("--vinted-path", type=Path, default=DEFAULT_VINTED)
    parser.add_argument("--ka-path", type=Path, default=DEFAULT_KA)
    parser.add_argument("--splits-dir", type=Path, default=DEFAULT_SPLITS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--index-output", type=Path, default=DEFAULT_INDEX)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=(
            "Optional multi-image manifest parquet (from scripts/build_manifest.py). "
            "When set, rows with a matching (platform, id) in the manifest are "
            "extracted with both the garment photo from the combined parquet and "
            "the care-label photo from the manifest. Rows without a label fall back "
            "to single-image extraction. Use only with the multi-image adapter."
        ),
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional smoke-test row limit.")
    parser.add_argument(
        "--load-in-4bit",
        action="store_true",
        help="Load base model in 4-bit. Recommended for 24GB GPUs.",
    )
    parser.add_argument(
        "--torch-dtype",
        choices=["auto", "float16", "bfloat16", "float32"],
        default="auto",
        help="Model dtype when not using 4-bit.",
    )
    parser.add_argument("--device-map", default="auto")
    parser.add_argument(
        "--pool",
        choices=["last", "mean"],
        default="last",
        help="Pooling strategy. 'last' matches the spike notebook.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the progress sidecar if the output .npy already exists.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=50,
        help="Flush output and update progress sidecar every N rows.",
    )
    return parser.parse_args()


def dtype_from_arg(name: str):
    return {
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
        "float32": torch.float32,
    }.get(name)


def load_model_and_processor(args: argparse.Namespace):
    processor = AutoProcessor.from_pretrained(args.model_id, trust_remote_code=True)
    model_kwargs = {"trust_remote_code": True, "device_map": args.device_map}
    if args.load_in_4bit:
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
    elif args.torch_dtype != "auto":
        model_kwargs["torch_dtype"] = dtype_from_arg(args.torch_dtype)

    base = AutoModelForImageTextToText.from_pretrained(args.model_id, **model_kwargs)
    model = PeftModel.from_pretrained(base, args.adapter_id)
    model.eval()
    return processor, model


def model_device(model) -> torch.device:
    return next(model.parameters()).device


def build_inputs(
    processor,
    image,
    platform: str,
    device: torch.device,
    prompt: str | None = None,
    label_image=None,
):
    """Build the VLM chat-template inputs. ``prompt`` overrides ``get_prompt(platform)``
    so callers (e.g. backend with seller hints) can append text without bypassing the
    canonical prompt prefix.

    ``label_image`` (optional) feeds a second photo (the care label) alongside the
    garment shot — the multi-image adapter was trained on this pairing and uses
    the label for brand/size. When None, the single-image path is used.
    """
    if prompt is None:
        prompt = get_prompt(platform)
    content = [{"type": "image", "image": image}]
    if label_image is not None:
        content.append({"type": "image", "image": label_image})
    content.append({"type": "text", "text": prompt})
    messages = [{"role": "user", "content": content}]
    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    )
    return inputs.to(device)


@torch.no_grad()
def extract_one(processor, model, image, platform: str, pool: str, label_image=None) -> np.ndarray:
    inputs = build_inputs(
        processor, image, platform, model_device(model), label_image=label_image,
    )
    out = model(**inputs, output_hidden_states=True, return_dict=True)
    last_hidden = out.hidden_states[-1]  # [1, seq_len, hidden_dim]
    if pool == "last":
        vec = last_hidden[0, -1, :]
    elif pool == "mean":
        mask = inputs["attention_mask"][0].to(last_hidden.device).unsqueeze(-1)
        vec = (last_hidden[0] * mask).sum(dim=0) / mask.sum()
    else:
        raise ValueError(f"Unknown pool: {pool}")
    return vec.detach().float().cpu().numpy().astype("float32")


def progress_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".progress.json")


def write_index(df, args: argparse.Namespace, hidden_dim: int) -> None:
    args.index_output.parent.mkdir(parents=True, exist_ok=True)
    index = df[["platform", "id", "split"]].copy()
    index["row_idx"] = np.arange(len(index), dtype=np.int64)
    index["hidden_dim"] = hidden_dim
    index["base_model"] = args.model_id
    index["adapter_id"] = args.adapter_id
    index["pool"] = args.pool
    index["prompt_source"] = "shared/prompts.py:get_prompt"
    index["manifest"] = str(args.manifest) if args.manifest is not None else ""
    index.to_parquet(args.index_output, index=False)


def main() -> None:
    from extract_features import decode_image, load_combined  # lazy import: see top of file

    args = parse_args()
    if args.progress_every <= 0:
        raise ValueError("--progress-every must be positive")

    df = load_combined(args.vinted_path, args.ka_path, args.splits_dir)
    if args.limit is not None:
        df = df.head(args.limit).copy()
        print(f"Smoke-test limit active: {len(df):,} rows")

    label_lookup: dict[tuple[str, int], str] = {}
    if args.manifest is not None:
        label_lookup = load_label_lookup(args.manifest)
        keys = [(str(p), int(i)) for p, i in zip(df["platform"], df["id"])]
        n_with_label = sum(1 for k in keys if k in label_lookup)
        print(
            f"Manifest loaded: {len(label_lookup):,} rows have a usable label photo. "
            f"{n_with_label:,} of {len(df):,} rows in this run will use multi-image extraction."
        )

    def _label_for(row) -> "Image.Image | None":
        if not label_lookup:
            return None
        path = label_lookup.get((str(row["platform"]), int(row["id"])))
        if path is None:
            return None
        try:
            from PIL import Image as _Image
            return _Image.open(path).convert("RGB")
        except Exception as exc:  # pragma: no cover — best-effort
            print(f"  WARN: failed to decode label {path}: {exc}")
            return None

    processor, model = load_model_and_processor(args)

    start = 0
    progress_file = progress_path(args.output)
    features = None
    hidden_dim = None

    if args.resume and args.output.exists() and progress_file.exists():
        progress = json.loads(progress_file.read_text())
        start = int(progress["next_row"])
        hidden_dim = int(progress["hidden_dim"])
        features = np.lib.format.open_memmap(
            args.output, mode="r+", dtype="float32", shape=(len(df), hidden_dim)
        )
        print(f"Resuming from row {start:,} / {len(df):,}")

    if features is None:
        first_row = df.iloc[0]
        first_image = decode_image(first_row["image"])
        first_label = _label_for(first_row)
        first_vec = extract_one(
            processor, model, first_image, first_row["platform"], args.pool,
            label_image=first_label,
        )
        hidden_dim = int(first_vec.shape[0])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        features = np.lib.format.open_memmap(
            args.output, mode="w+", dtype="float32", shape=(len(df), hidden_dim)
        )
        features[0] = first_vec
        start = 1
        print(f"Initialized {args.output} with shape {(len(df), hidden_dim)}")
        print(f"first 8 = {first_vec[:8].tolist()}")

    assert hidden_dim is not None
    write_index(df, args, hidden_dim)

    for i in tqdm(range(start, len(df)), desc="Extracting VLM pooled states"):
        row = df.iloc[i]
        image = decode_image(row["image"])
        label_image = _label_for(row)
        features[i] = extract_one(
            processor, model, image, row["platform"], args.pool,
            label_image=label_image,
        )
        if (i + 1) % args.progress_every == 0:
            features.flush()
            progress_file.write_text(
                json.dumps({"next_row": i + 1, "total": len(df), "hidden_dim": hidden_dim}, indent=2)
            )

    features.flush()
    progress_file.write_text(
        json.dumps({"next_row": len(df), "total": len(df), "hidden_dim": hidden_dim}, indent=2)
    )
    print(f"Saved VLM pooled states: {args.output}  shape={(len(df), hidden_dim)}")
    print(f"Saved index            : {args.index_output}  rows={len(df):,}")


if __name__ == "__main__":
    main()
