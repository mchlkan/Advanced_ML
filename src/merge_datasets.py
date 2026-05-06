"""Merge Vinted + Kleinanzeigen parquets and print dataset structure.

Applies the same filters as data_prep.py but without any language filter,
since both datasets will be fully translated to English.

Run from repo root:
    python src/merge_datasets.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


_DROP_CONDITIONS = {"in ordnung", "zufriedenstellend"}


def _normalize_condition(s: str) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return s
    return s.lower().replace(",", "").strip()


def _apply_filters(df: pd.DataFrame, platform: str) -> pd.DataFrame:
    out = df.copy()
    out["platform"] = platform
    out["condition"] = out["condition"].apply(_normalize_condition)
    out = out[out["price"].notna()]
    out = out[out["category_name"].notna()]
    out = out[out["description"].str.len() >= 30]
    out = out[~out["condition"].isin(_DROP_CONDITIONS)]
    if platform == "kleinanzeigen":
        out = out[out["price_type"] != "PLEASE_CONTACT"]
    return out.reset_index(drop=True)


def _print_structure(df: pd.DataFrame) -> None:
    print(f"\n{'='*60}")
    print(f"Shape: {df.shape[0]:,} rows × {df.shape[1]} columns")

    print("\n-- dtypes & null counts --")
    info = pd.DataFrame({
        "dtype": df.dtypes.astype(str),
        "nulls": df.isna().sum(),
        "null%": (df.isna().mean() * 100).round(1),
    })
    print(info.to_string())

    print("\n-- platform --")
    print(df["platform"].value_counts().to_string())

    print("\n-- category_name --")
    print(df["category_name"].value_counts().to_string())

    print("\n-- condition (normalized) --")
    print(df["condition"].value_counts().to_string())

    print("\n-- price summary --")
    print(df["price"].describe().round(2).to_string())

    print("\n-- state --")
    print(df["state"].value_counts(dropna=False).to_string())

    print(f"\n-- sample row (index 0) --")
    row = df.iloc[0].drop(labels=["image"], errors="ignore")
    for col, val in row.items():
        print(f"  {col}: {val!r}")
    print("="*60)


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    vinted_path = repo_root / "data" / "vinted_clothing_v2.parquet"
    ka_path = repo_root / "data" / "kleinanzeigen_clothing_v1_en.parquet"

    print("Loading parquets...")
    vt_raw = pd.read_parquet(vinted_path)
    ka_raw = pd.read_parquet(ka_path)
    print(f"  Vinted raw        : {len(vt_raw):,}")
    print(f"  Kleinanzeigen raw : {len(ka_raw):,}")

    print("\nApplying filters...")
    vt = _apply_filters(vt_raw, "vinted")
    ka = _apply_filters(ka_raw, "kleinanzeigen")
    print(f"  Vinted filtered        : {len(vt):,}  (dropped {len(vt_raw)-len(vt):,})")
    print(f"  Kleinanzeigen filtered : {len(ka):,}  (dropped {len(ka_raw)-len(ka):,})")

    print("\nMerging...")
    combined = pd.concat([vt, ka], ignore_index=True, sort=False)
    print(f"  Combined : {len(combined):,}")

    print("\nDataset structure:")
    _print_structure(combined)

    out_path = repo_root / "data" / "combined_clothing.parquet"
    combined.to_parquet(out_path, index=False)
    print(f"\nSaved → {out_path}  ({len(combined):,} rows)")


if __name__ == "__main__":
    main()
