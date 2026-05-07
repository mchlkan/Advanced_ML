"""Build the tabular sidecar dataset for Model #4 price-head training.

The VLM pooled matrix stays in ``.npy`` form; this script creates an aligned
parquet with metadata encodings and targets.

Run after VLM feature extraction:

    python models/build_price_dataset.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VLM = REPO_ROOT / "data" / "embeddings" / "vlm_pooled_combined.npy"
DEFAULT_VLM_INDEX = REPO_ROOT / "data" / "embeddings" / "vlm_pooled_combined_index.parquet"
DEFAULT_FLAW = REPO_ROOT / "data" / "features" / "flaw_probs_combined.parquet"
DEFAULT_VINTED = REPO_ROOT / "data" / "vinted_clothing_combined.parquet"
DEFAULT_KA = REPO_ROOT / "data" / "kleinanzeigen_clothing_combined.parquet"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "features" / "price_features_combined.parquet"
DEFAULT_VOCAB = REPO_ROOT / "data" / "features" / "price_feature_vocab.json"

UNK = "UNK"
KA_PLACEHOLDER_BRAND = "Sonstige"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vlm-embeddings", type=Path, default=DEFAULT_VLM)
    parser.add_argument("--vlm-index", type=Path, default=DEFAULT_VLM_INDEX)
    parser.add_argument("--flaw-probs", type=Path, default=DEFAULT_FLAW)
    parser.add_argument("--vinted-path", type=Path, default=DEFAULT_VINTED)
    parser.add_argument("--ka-path", type=Path, default=DEFAULT_KA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--vocab-output", type=Path, default=DEFAULT_VOCAB)
    parser.add_argument("--max-brands", type=int, default=500)
    return parser.parse_args()


def canon_brand(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return UNK
    value = str(value).strip()
    if not value or value == KA_PLACEHOLDER_BRAND:
        return UNK
    return value


def load_metadata(vinted_path: Path, ka_path: Path) -> pd.DataFrame:
    df = pd.concat(
        [pd.read_parquet(vinted_path), pd.read_parquet(ka_path)],
        ignore_index=True,
        sort=False,
    )
    required = ["platform", "id", "price", "brand", "category_en", "condition_en"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Combined metadata missing required columns: {missing}")
    df = df[required].copy()
    df["brand_canon"] = df["brand"].map(canon_brand)
    df["tag_proxy"] = df["condition_en"].eq("New with tags").astype("float32")
    df["log_price"] = np.log1p(df["price"].astype("float32"))
    return df


def build_vocab(df: pd.DataFrame, max_brands: int) -> dict:
    train = df[df["split"].eq("train")]
    platforms = sorted(df["platform"].dropna().unique().tolist())
    categories = sorted(df["category_en"].dropna().unique().tolist())
    conditions = ["New with tags", "New", "Very good", "Good"]

    brand_counts = train["brand_canon"].value_counts()
    brands = [b for b in brand_counts.index.tolist() if b != UNK][:max_brands]
    brands = [UNK] + brands

    return {
        "platform": {v: i for i, v in enumerate(platforms)},
        "category_en": {v: i for i, v in enumerate(categories)},
        "condition_en": {v: i for i, v in enumerate(conditions)},
        "brand_canon": {v: i for i, v in enumerate(brands)},
        "unk_brand": UNK,
        "max_brands": max_brands,
    }


def map_with_unk(series: pd.Series, mapping: dict[str, int], unk: str | None = None) -> pd.Series:
    if unk is None:
        mapped = series.map(mapping)
    else:
        mapped = series.where(series.isin(mapping), unk).map(mapping)
    if mapped.isna().any():
        missing = sorted(series[mapped.isna()].dropna().unique().tolist())
        raise ValueError(f"Missing mapping values: {missing[:10]}")
    return mapped.astype("int64")


def main() -> None:
    args = parse_args()
    if args.max_brands <= 0:
        raise ValueError("--max-brands must be positive")

    vlm = np.load(args.vlm_embeddings, mmap_mode="r")
    vlm_index = pd.read_parquet(args.vlm_index)
    if len(vlm) != len(vlm_index):
        raise ValueError(f"VLM rows ({len(vlm):,}) != index rows ({len(vlm_index):,})")
    if vlm.ndim != 2:
        raise ValueError(f"Expected VLM matrix [N, D], got {vlm.shape}")
    if "row_idx" not in vlm_index.columns:
        vlm_index = vlm_index.copy()
        vlm_index["row_idx"] = np.arange(len(vlm_index), dtype=np.int64)

    meta = load_metadata(args.vinted_path, args.ka_path)
    flaw = pd.read_parquet(args.flaw_probs)

    out = vlm_index[["platform", "id", "split", "row_idx"]].copy()
    out = out.merge(meta, on=["platform", "id"], how="left", validate="one_to_one")
    out = out.merge(
        flaw[["platform", "id", "visual_wear_probability"]],
        on=["platform", "id"],
        how="left",
        validate="one_to_one",
    )
    model_required = [
        "platform", "id", "split", "row_idx", "price", "log_price",
        "brand_canon", "category_en", "condition_en",
        "visual_wear_probability", "tag_proxy",
    ]
    if out[model_required].isna().any().any():
        bad_cols = out[model_required].columns[out[model_required].isna().any()].tolist()
        raise ValueError(f"Price feature table has nulls in: {bad_cols}")
    if out.duplicated(["platform", "id"]).any():
        raise ValueError("Duplicate (platform, id) rows after joins")
    if not (out["row_idx"].to_numpy() == np.arange(len(out))).all():
        raise ValueError("row_idx must align with VLM matrix row order")

    vocab = build_vocab(out, args.max_brands)
    out["platform_idx"] = map_with_unk(out["platform"], vocab["platform"])
    out["category_idx"] = map_with_unk(out["category_en"], vocab["category_en"])
    out["condition_idx"] = map_with_unk(out["condition_en"], vocab["condition_en"])
    out["brand_idx"] = map_with_unk(out["brand_canon"], vocab["brand_canon"], unk=UNK)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.output, index=False)
    with open(args.vocab_output, "w") as f:
        json.dump(vocab, f, indent=2, ensure_ascii=False)

    print(f"Saved price features: {args.output}  rows={len(out):,}")
    print(f"Saved vocab         : {args.vocab_output}")
    print(f"VLM shape           : {vlm.shape}")
    print("Split counts:")
    print(out["split"].value_counts().sort_index().to_string())
    print("Vocab sizes:")
    print({k: len(v) for k, v in vocab.items() if isinstance(v, dict)})


if __name__ == "__main__":
    main()
