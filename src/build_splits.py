"""Build locked train/val/test splits for the Day 2 QLoRA fine-tune.

Consumes ``data/combined_clothing.parquet`` (produced by ``merge_datasets.py``)
and produces three split parquets plus committed id-list JSONs that pin the
splits per brief §4.5.

Stratification: ``category_en × condition_en × platform``. Test = 500 rows
locked, then 90/10 train/val on the remainder. Seed 42 throughout via
``data_prep.train_test_split_by_id``, which handles rare-strata edge cases.

Run from repo root::

    python src/build_splits.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd

import data_prep


SEED = 42
TEST_SIZE = 500
VAL_FRACTION = 0.1
STRATA_COLS = ["category_en", "condition_en", "platform"]

_KA_PLACEHOLDER_BRAND = "Sonstige"
_UNK_BRAND = "UNK"


def add_brand_canon(df: pd.DataFrame) -> pd.DataFrame:
    """Map ``Sonstige`` and nulls to a single ``UNK`` token.

    Per EDA, KA's ``Sonstige`` placeholder is ~25% of brands and provides no
    learning signal. Vinted has ~1.7% null brands. Collapsing both to ``UNK``
    keeps the brand vocabulary clean for downstream brand embedding.
    """
    out = df.copy()
    brand = out["brand"]
    is_null = brand.isna()
    is_sonstige = brand == _KA_PLACEHOLDER_BRAND
    out["brand_canon"] = brand.where(~(is_null | is_sonstige), _UNK_BRAND)
    return out


def _ids_payload(df: pd.DataFrame) -> list[dict]:
    return [
        {"platform": str(p), "id": int(i)}
        for p, i in zip(df["platform"], df["id"])
    ]


def _print_breakdown(name: str, df: pd.DataFrame) -> None:
    print(f"\n[{name}] {len(df):,} rows")
    print(df.groupby(["platform", "category_en"]).size().to_string())


def build_splits(combined: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Produce (train, val, test) DataFrames with stratified splits."""
    canon = add_brand_canon(combined)

    rest_df, test_df = data_prep.train_test_split_by_id(
        canon, test_size=TEST_SIZE, strata_cols=STRATA_COLS, seed=SEED,
    )
    val_size = max(1, int(round(len(rest_df) * VAL_FRACTION)))
    train_df, val_df = data_prep.train_test_split_by_id(
        rest_df, test_size=val_size, strata_cols=STRATA_COLS, seed=SEED,
    )
    return train_df, val_df, test_df


def _check_no_nulls(df: pd.DataFrame, cols: Iterable[str], name: str) -> None:
    bad = [c for c in cols if df[c].isna().any()]
    if bad:
        raise ValueError(f"{name} split has null values in required columns: {bad}")


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    combined_path = repo_root / "data" / "combined_clothing.parquet"
    splits_dir = repo_root / "data" / "splits"
    splits_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {combined_path}...")
    combined = pd.read_parquet(combined_path)
    print(f"  {len(combined):,} rows  ({combined['platform'].value_counts().to_dict()})")

    train_df, val_df, test_df = build_splits(combined)
    print(f"\nSplit sizes:")
    print(f"  train : {len(train_df):,}")
    print(f"  val   : {len(val_df):,}")
    print(f"  test  : {len(test_df):,}  (locked, brief §4.5)")
    print(f"  total : {len(train_df) + len(val_df) + len(test_df):,}")

    required = ["title_en", "description_en", "category_en",
                "condition_en", "color_en", "brand_canon"]
    for name, df in [("train", train_df), ("val", val_df), ("test", test_df)]:
        _check_no_nulls(df, required, name)

    for name, df in [("train", train_df), ("val", val_df), ("test", test_df)]:
        _print_breakdown(name, df)

    print("\nWriting splits...")
    for name, df in [("train", train_df), ("val", val_df), ("test", test_df)]:
        ids_path = splits_dir / f"{name}_ids.json"
        parquet_path = splits_dir / f"{name}.parquet"
        with open(ids_path, "w") as f:
            json.dump(_ids_payload(df), f, indent=2)
        df.to_parquet(parquet_path, index=False)
        print(f"  {name:>5}: {ids_path.relative_to(repo_root)}  +  {parquet_path.relative_to(repo_root)}")


if __name__ == "__main__":
    main()
