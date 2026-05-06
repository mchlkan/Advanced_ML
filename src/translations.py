"""Lookup tables for canonicalizing structured fields to English.

Forward maps (DE → EN) are used during data prep to build the canonical
training schema. Reverse maps (EN → DE / EN → KA-cased) are used at listing
time to convert the model's English output back to each platform's expected
values.

Coverage is enforced by ``assert_coverage``: any unmapped value in the data
raises a ``KeyError`` at prep time so we never silently drop information.
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd


# ----- Forward maps (DE → EN) ------------------------------------------------

# Keys are post-``data_prep.normalize_condition`` (lowercased, comma-stripped).
CONDITION_DE_TO_EN: dict[str, str] = {
    "neu mit etikett": "New with tags",
    "neu": "New",
    "sehr gut": "Very good",
    "gut": "Good",
}

KA_CATEGORY_DE_TO_EN: dict[str, str] = {
    "Damenbekleidung": "Women's clothing",
    "Herrenbekleidung": "Men's clothing",
    "Damenschuhe": "Women's shoes",
    "Herrenschuhe": "Men's shoes",
}

COLOR_DE_TO_EN: dict[str, str] = {
    "Andere Farben": "Other",
    "Aprikose": "Apricot",
    "Beige": "Beige",
    "Blau": "Blue",
    "Braun": "Brown",
    "Bunt": "Multicolor",
    "Burgunderrot": "Burgundy",
    "Creme": "Cream",
    "Dunkelgrün": "Dark green",
    "Flieder": "Lilac",
    "Gelb": "Yellow",
    "Gold": "Gold",
    "Grau": "Gray",
    "Grün": "Green",
    "Hellblau": "Light blue",
    "Khaki": "Khaki",
    "Klar": "Clear",
    "Korallenrot": "Coral",
    "Lavendel": "Lavender",
    "Lila": "Purple",
    "Marineblau": "Navy",
    "Mintgrün": "Mint",
    "Orange": "Orange",
    "Pink": "Pink",
    "Print": "Print",
    "Rose": "Rose",
    "Rosé": "Rose",
    "Rot": "Red",
    "Schwarz": "Black",
    "Senffarben": "Mustard",
    "Silber": "Silver",
    "Türkis": "Turquoise",
    "Weiß": "White",
}


# ----- Reverse maps (EN → platform-native) -----------------------------------
# Used by ``listing_mappings.py`` at publish time. KA-cased values match the
# strings the platform actually displays (note ``Sehr Gut`` capital G, where
# Vinted uses ``Sehr gut`` lowercase).

CONDITION_EN_TO_KA_DE: dict[str, str] = {
    "New with tags": "Neu mit Etikett",
    "New": "Neu",
    "Very good": "Sehr Gut",
    "Good": "Gut",
}

KA_CATEGORY_EN_TO_DE: dict[str, str] = {
    en: de for de, en in KA_CATEGORY_DE_TO_EN.items()
}

# Color reverse: Rose maps to "Rosé" since that's the canonical KA form.
# Build by inverting, with explicit overrides where multiple DE values share an EN value.
_COLOR_REVERSE_OVERRIDES = {"Rose": "Rosé"}
COLOR_EN_TO_KA_DE: dict[str, str] = {}
for de, en in COLOR_DE_TO_EN.items():
    COLOR_EN_TO_KA_DE.setdefault(en, de)
COLOR_EN_TO_KA_DE.update(_COLOR_REVERSE_OVERRIDES)


# ----- Coverage gate ---------------------------------------------------------

def _check(values: Iterable[str], lookup: dict[str, str], field: str) -> list[str]:
    missing = sorted({v for v in values if v is not None and not (isinstance(v, float) and pd.isna(v)) and v not in lookup})
    return missing


def assert_coverage(df: pd.DataFrame) -> None:
    """Raise ``KeyError`` if any observed value is missing from a forward map.

    ``df`` must already be normalized (condition lowercased) and tagged with a
    ``platform`` column (``vinted`` / ``kleinanzeigen``).
    """
    issues: list[str] = []

    missing_cond = _check(df["condition"], CONDITION_DE_TO_EN, "condition")
    if missing_cond:
        issues.append(f"condition not in CONDITION_DE_TO_EN: {missing_cond}")

    missing_color = _check(df["color"], COLOR_DE_TO_EN, "color")
    if missing_color:
        issues.append(f"color not in COLOR_DE_TO_EN: {missing_color}")

    ka_rows = df[df["platform"] == "kleinanzeigen"]
    missing_ka_cat = _check(ka_rows["category_name"], KA_CATEGORY_DE_TO_EN, "category_name")
    if missing_ka_cat:
        issues.append(f"KA category_name not in KA_CATEGORY_DE_TO_EN: {missing_ka_cat}")

    if issues:
        raise KeyError("Missing lookup entries:\n  " + "\n  ".join(issues))
