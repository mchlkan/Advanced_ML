"""Data prep for the Resell Copilot Day 1 spike.

Loads Vinted + Kleinanzeigen parquets, applies the filters from the tech
brief §4.4 and project_memory_day1.md, and produces a stratified train/test
split for zero-shot model evaluation.

Run ``python src/data_prep.py`` from the repo root for a sanity-check pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import pandas as pd
from sklearn.model_selection import train_test_split


_DROP_CONDITIONS = {"in ordnung", "zufriedenstellend"}
_VALID_PLATFORMS = {"vinted", "kleinanzeigen"}


def load_vinted(path: str) -> pd.DataFrame:
    """Load the Vinted parquet file."""
    return pd.read_parquet(path)


def load_kleinanzeigen(path: str) -> pd.DataFrame:
    """Load the Kleinanzeigen parquet file."""
    return pd.read_parquet(path)


def normalize_condition(s: str) -> str:
    """Normalize a single condition string: lowercase, strip commas + whitespace."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return s
    return s.lower().replace(",", "").strip()


def apply_filters(df: pd.DataFrame, platform: str) -> pd.DataFrame:
    """Apply spike filters and tag rows with platform.

    Adds ``platform`` column, normalizes ``condition``, drops rows where
    price/category_name is null, drops short descriptions, drops rare condition
    buckets, and (for KA) drops ``price_type == 'PLEASE_CONTACT'``.
    """
    if platform not in _VALID_PLATFORMS:
        raise ValueError(f"platform must be one of {_VALID_PLATFORMS}, got {platform!r}")
    out = df.copy()
    out["platform"] = platform
    out["condition"] = out["condition"].apply(normalize_condition)
    out = out[out["price"].notna()]
    out = out[out["category_name"].notna()]
    out = out[out["description"].str.len() >= 30]
    out = out[~out["condition"].isin(_DROP_CONDITIONS)]
    if platform == "kleinanzeigen":
        out = out[out["price_type"] != "PLEASE_CONTACT"]
    return out.reset_index(drop=True)


def filter_vinted_de_only(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only Vinted rows where ``language == 'de'``."""
    return df[df["language"] == "de"].reset_index(drop=True)


def build_combined(vinted_df: pd.DataFrame, ka_df: pd.DataFrame) -> pd.DataFrame:
    """Concatenate Vinted + KA into one frame, preserving the union of columns."""
    return pd.concat([vinted_df, ka_df], ignore_index=True, sort=False)


def _stratify_key(df: pd.DataFrame, cols: List[str]) -> pd.Series:
    return df[cols].astype(str).agg("|".join, axis=1)


def stratified_sample(
    df: pd.DataFrame,
    n_per_platform: int,
    strata_cols: List[str],
    seed: int,
) -> pd.DataFrame:
    """Sample ``n_per_platform`` rows per platform, stratified on ``strata_cols``.

    Strata with <2 rows are kept whole (sklearn can't stratify singletons).
    """
    chunks = []
    for platform, sub in df.groupby("platform"):
        n = min(n_per_platform, len(sub))
        if n == len(sub):
            chunks.append(sub)
            continue
        strata = _stratify_key(sub, strata_cols)
        counts = strata.value_counts()
        rare_keys = counts[counts < 2].index
        rare = sub[strata.isin(rare_keys)]
        rest = sub[~strata.isin(rare_keys)]
        rest_strata = strata[~strata.isin(rare_keys)]
        target = n - len(rare)
        if target <= 0 or len(rest) == 0:
            chunks.append(sub.sample(n=n, random_state=seed))
            continue
        target = min(target, len(rest) - 1)
        _, picked = train_test_split(
            rest, test_size=target, stratify=rest_strata, random_state=seed
        )
        chunks.append(pd.concat([rare, picked]))
    return (
        pd.concat(chunks, ignore_index=True)
        .sample(frac=1, random_state=seed)
        .reset_index(drop=True)
    )


def train_test_split_by_id(
    df: pd.DataFrame,
    test_size: int,
    strata_cols: List[str],
    seed: int,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Stratified train/test split. ``test_size`` is an absolute count.

    Strata with <2 rows are routed to train (sklearn can't split them).
    """
    strata = _stratify_key(df, strata_cols)
    counts = strata.value_counts()
    rare_keys = counts[counts < 2].index
    rare_mask = strata.isin(rare_keys)
    rare_rows = df[rare_mask]
    rest = df[~rare_mask]
    rest_strata = strata[~rare_mask]

    train_df, test_df = train_test_split(
        rest, test_size=test_size, stratify=rest_strata, random_state=seed
    )
    if len(rare_rows) > 0:
        train_df = pd.concat([train_df, rare_rows], ignore_index=True)
    return (
        train_df.reset_index(drop=True),
        test_df.reset_index(drop=True),
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    vinted_path = repo_root / "data" / "vinted_clothing_v1_5_full.parquet"
    ka_path = repo_root / "data" / "kleinanzeigen_clothing_v1.parquet"

    print("Loading parquets...")
    vt_raw = load_vinted(str(vinted_path))
    ka_raw = load_kleinanzeigen(str(ka_path))
    print(f"  Vinted        : {len(vt_raw):,}")
    print(f"  Kleinanzeigen : {len(ka_raw):,}")

    print("\nApplying filters...")
    vt = apply_filters(vt_raw, "vinted")
    ka = apply_filters(ka_raw, "kleinanzeigen")
    print(f"  Vinted (filtered)        : {len(vt):,}")
    print(f"  Kleinanzeigen (filtered) : {len(ka):,}")

    print("\nFiltering Vinted to de-only...")
    vt = filter_vinted_de_only(vt)
    print(f"  Vinted (de)   : {len(vt):,}")

    print("\nBuilding combined dataset...")
    combined = build_combined(vt, ka)
    print(f"  Combined      : {len(combined):,}")
    print(combined["platform"].value_counts().to_string())

    print("\nStratified sample (300/platform = 600) on category_name × condition...")
    sampled = stratified_sample(
        combined,
        n_per_platform=300,
        strata_cols=["category_name", "condition"],
        seed=42,
    )
    print(f"  Sampled       : {len(sampled):,}")
    print(sampled["platform"].value_counts().to_string())

    print("\nTrain/test split (test=100) on category_name × condition × platform...")
    train_df, test_df = train_test_split_by_id(
        sampled,
        test_size=100,
        strata_cols=["category_name", "condition", "platform"],
        seed=42,
    )
    print(f"  Train         : {len(train_df):,}")
    print(f"  Test          : {len(test_df):,}")
    print("  Test by platform:")
    print(test_df["platform"].value_counts().to_string())


if __name__ == "__main__":
    main()
