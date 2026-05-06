"""Assemble the canonical English training schema.

Joins LLM translations with the filtered DataFrame, applies the lookup tables
in ``translations.py``, and produces the ``target_text_canon`` string used as
the assistant turn during fine-tuning.

Pure functions, no I/O. The orchestrator notebook handles persistence.
"""

from __future__ import annotations

import pandas as pd

from translations import (
    COLOR_DE_TO_EN,
    CONDITION_DE_TO_EN,
    KA_CATEGORY_DE_TO_EN,
    assert_coverage,
)

_UNK_BRAND = "UNK"
_KA_PLACEHOLDER_BRAND = "Sonstige"


def _canon_category(row: pd.Series) -> str:
    if row["platform"] == "kleinanzeigen":
        return KA_CATEGORY_DE_TO_EN[row["category_name"]]
    return row["category_name"]  # Vinted is already English-canonical.


def _canon_brand(brand) -> str:
    if brand is None or (isinstance(brand, float) and pd.isna(brand)):
        return _UNK_BRAND
    if brand == _KA_PLACEHOLDER_BRAND:
        return _UNK_BRAND
    return brand


def _format_target_text(title: str, description: str, category: str, price: float) -> str:
    return (
        f"Title: {title}\n"
        f"Description: {description}\n"
        f"Category: {category}\n"
        f"Price: {price:.2f} EUR"
    )


def build_canonical(df: pd.DataFrame, translations: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` augmented with canonical English columns.

    ``df`` must already be platform-tagged + filtered (output of
    ``data_prep.apply_filters`` + ``build_combined``). ``translations`` is the
    cache parquet from ``translate_text.translate_dataframe`` with columns
    ``platform``, ``id``, ``title_en``, ``description_en``.

    Adds columns: ``title_canon``, ``description_canon``, ``category_canon``,
    ``condition_canon``, ``color_canon``, ``brand_canon``,
    ``target_text_canon``, plus ``title_orig``, ``description_orig``.
    """
    assert_coverage(df)

    out = df.copy()
    out["title_orig"] = out["title"]
    out["description_orig"] = out["description"]

    trans = translations[["platform", "id", "title_en", "description_en"]].copy()
    trans["id"] = trans["id"].astype(out["id"].dtype)
    out = out.merge(trans, how="left", on=["platform", "id"], validate="one_to_one")

    missing = out[out["title_en"].isna() | out["description_en"].isna()]
    if len(missing):
        raise ValueError(
            f"{len(missing)} rows missing translations after merge — re-run translate_text "
            f"or delete the cache. First few ids: {missing[['platform','id']].head().to_dict('records')}"
        )

    out["title_canon"] = out["title_en"]
    out["description_canon"] = out["description_en"]
    out["condition_canon"] = out["condition"].map(CONDITION_DE_TO_EN)
    out["color_canon"] = out["color"].map(COLOR_DE_TO_EN)
    out["category_canon"] = out.apply(_canon_category, axis=1)
    out["brand_canon"] = out["brand"].map(_canon_brand)

    out["target_text_canon"] = out.apply(
        lambda r: _format_target_text(
            r["title_canon"], r["description_canon"], r["category_canon"], r["price"]
        ),
        axis=1,
    )

    out = out.drop(columns=["title_en", "description_en"])
    return out
