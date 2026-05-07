"""Feature extraction utilities for Resell Copilot models.

Currently implements Model #2's frozen DINOv2 image embeddings. The cached
embeddings feed ``models/train_flaw_head.py`` and later Model #4.

Run from repo root:

    python models/extract_features.py \
        --feature-type dinov2 \
        --output-dir data/embeddings \
        --batch-size 32
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import torch
from PIL import Image
from tqdm.auto import tqdm
from transformers import AutoImageProcessor, AutoModel


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VINTED = REPO_ROOT / "data" / "vinted_clothing_combined.parquet"
DEFAULT_KA = REPO_ROOT / "data" / "kleinanzeigen_clothing_combined.parquet"
DEFAULT_SPLITS = REPO_ROOT / "data" / "splits"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "embeddings"
DINO_MODEL_ID = "facebook/dinov2-base"

VALID_CONDITIONS = {"Good", "Very good", "New", "New with tags"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--feature-type",
        choices=["dinov2"],
        default="dinov2",
        help="Feature family to extract. Only dinov2 is implemented for Model #2.",
    )
    parser.add_argument("--vinted-path", type=Path, default=DEFAULT_VINTED)
    parser.add_argument("--ka-path", type=Path, default=DEFAULT_KA)
    parser.add_argument("--splits-dir", type=Path, default=DEFAULT_SPLITS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model-id", default=DINO_MODEL_ID)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--device",
        choices=["auto", "cuda", "mps", "cpu"],
        default="auto",
        help="Device for feature extraction. auto prefers CUDA, then MPS, then CPU.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional smoke-test row limit. Omit for the full combined dataset.",
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


def load_split_lookup(splits_dir: Path) -> dict[tuple[str, int], str]:
    lookup: dict[tuple[str, int], str] = {}
    for split in ("train", "val", "test"):
        path = splits_dir / f"{split}_ids.json"
        with open(path) as f:
            payload = json.load(f)
        for item in payload:
            key = (str(item["platform"]), int(item["id"]))
            if key in lookup:
                raise ValueError(f"Duplicate split id across split files: {key}")
            lookup[key] = split
    return lookup


def load_combined(vinted_path: Path, ka_path: Path, splits_dir: Path) -> pd.DataFrame:
    vinted = pd.read_parquet(vinted_path)
    ka = pd.read_parquet(ka_path)
    df = pd.concat([vinted, ka], ignore_index=True, sort=False)

    required = ["platform", "id", "image", "condition_en"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Combined data missing required columns: {missing}")

    bad_conditions = sorted(set(df["condition_en"].dropna()) - VALID_CONDITIONS)
    if bad_conditions:
        raise ValueError(f"Unexpected condition_en values: {bad_conditions}")

    split_lookup = load_split_lookup(splits_dir)
    df["split"] = [
        split_lookup.get((str(platform), int(item_id)))
        for platform, item_id in zip(df["platform"], df["id"])
    ]
    missing_split = df["split"].isna().sum()
    if missing_split:
        examples = df[df["split"].isna()][["platform", "id"]].head().to_dict("records")
        raise ValueError(f"{missing_split} rows missing locked split assignment: {examples}")

    duplicate_keys = df.duplicated(["platform", "id"]).sum()
    if duplicate_keys:
        raise ValueError(f"Found {duplicate_keys} duplicate (platform, id) rows")

    df["flaw_label"] = (df["condition_en"] == "Good").astype("int64")
    return df.reset_index(drop=True)


def decode_image(cell) -> Image.Image:
    """Decode an HF-style parquet image cell into RGB PIL."""
    if isinstance(cell, dict):
        if cell.get("bytes") is not None:
            return Image.open(io.BytesIO(cell["bytes"])).convert("RGB")
        if cell.get("path"):
            return Image.open(cell["path"]).convert("RGB")
    if isinstance(cell, (bytes, bytearray)):
        return Image.open(io.BytesIO(cell)).convert("RGB")
    if isinstance(cell, Image.Image):
        return cell.convert("RGB")
    raise ValueError(f"Unrecognized image cell type: {type(cell).__name__}")


def batched_indices(n_rows: int, batch_size: int) -> Iterable[range]:
    for start in range(0, n_rows, batch_size):
        yield range(start, min(start + batch_size, n_rows))


@torch.no_grad()
def extract_dinov2_embeddings(
    df: pd.DataFrame,
    model_id: str,
    batch_size: int,
    device: torch.device,
) -> np.ndarray:
    processor = AutoImageProcessor.from_pretrained(model_id)
    model = AutoModel.from_pretrained(model_id)
    model.eval()
    model.to(device)

    chunks: list[np.ndarray] = []
    for batch_idx in tqdm(
        batched_indices(len(df), batch_size),
        total=(len(df) + batch_size - 1) // batch_size,
        desc="Extracting DINOv2 CLS embeddings",
    ):
        images = [decode_image(df.iloc[i]["image"]) for i in batch_idx]
        encoded = processor(images=images, return_tensors="pt")
        encoded = {key: value.to(device) for key, value in encoded.items()}
        outputs = model(**encoded)
        cls = outputs.last_hidden_state[:, 0, :].detach().cpu().float().numpy()
        chunks.append(cls)

    embeddings = np.concatenate(chunks, axis=0).astype("float32")
    if embeddings.shape != (len(df), 768):
        raise ValueError(
            f"Expected embeddings shape ({len(df)}, 768), got {embeddings.shape}"
        )
    return embeddings


def save_outputs(df: pd.DataFrame, embeddings: np.ndarray, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    emb_path = output_dir / "dinov2_combined.npy"
    index_path = output_dir / "dinov2_combined_index.parquet"

    np.save(emb_path, embeddings)
    index_cols = ["platform", "id", "split", "condition_en", "flaw_label"]
    df[index_cols].to_parquet(index_path, index=False)

    print(f"Saved embeddings: {emb_path}  shape={embeddings.shape}")
    print(f"Saved index     : {index_path}  rows={len(df):,}")
    print("Split counts:")
    print(df["split"].value_counts().sort_index().to_string())
    print("Class balance:")
    print(df["flaw_label"].value_counts().sort_index().rename({0: "negative", 1: "positive"}).to_string())


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")

    device = choose_device(args.device)
    print(f"Using device: {device}")

    df = load_combined(args.vinted_path, args.ka_path, args.splits_dir)
    if args.limit is not None:
        df = df.head(args.limit).copy()
        print(f"Smoke-test limit active: {len(df):,} rows")

    embeddings = extract_dinov2_embeddings(
        df=df,
        model_id=args.model_id,
        batch_size=args.batch_size,
        device=device,
    )
    save_outputs(df, embeddings, args.output_dir)


if __name__ == "__main__":
    main()
