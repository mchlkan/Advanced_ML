"""Convert the model's canonical English schema to platform-native fields.

Used by the publish endpoint — given the model's canonical output,
``to_kleinanzeigen`` and ``to_vinted`` produce the field values each
platform's listing form / API expects.

Mappings are lenient: missing or unknown values drop their corresponding
keys rather than KeyError, so a partial /verify edit (e.g., user clears
brand) still produces a valid payload.
"""

from __future__ import annotations

from typing import Any

from translations import (
    COLOR_EN_TO_KA_DE,
    CONDITION_EN_TO_KA_DE,
    KA_CATEGORY_EN_TO_DE,
)

# Used by /publish to redirect the user to the platform's new-listing form
# when direct publishing isn't available.
NEW_LISTING_URLS: dict[str, str] = {
    "vinted": "https://www.vinted.de/items/new",
    "kleinanzeigen": "https://www.kleinanzeigen.de/p-anzeige-aufgeben.html",
}


# Vinted catalog IDs picked from vinted-lister/config/categories.yaml. These
# default to the Damen (women's) catalog because our training data skews that
# way; if the listing should be in the Herren catalog the user can switch
# it manually in the Vinted form before submitting.
VINTED_CATEGORY_TO_CATALOG_ID: dict[str, int] = {
    "jackets": 1908,    # Damen Jacken & Mäntel
    "jeans": 183,       # Damen Jeans
    "tshirts": 221,     # Damen T-Shirts
    "sneakers": 2632,   # Damen Sneaker
}

# Vinted condition IDs (extracted from the mobile-API captures):
# 1=Neu, 2=Sehr gut, 3=Gut, 4=Zufriedenstellend, 6=Neu mit Etikett.
VINTED_CONDITION_TO_ID: dict[str, int] = {
    "New with tags": 6,
    "New": 1,
    "Very good": 2,
    "Good": 3,
}

# Vinted color IDs — full table dumped from /api/v2/item_upload/colors.
# Keys are matched case-insensitively against the VLM's English color output.
VINTED_COLOR_TO_ID: dict[str, int] = {
    "black": 1,
    "brown": 2,
    "grey": 3, "gray": 3,
    "beige": 4,
    "pink": 5,
    "purple": 6, "lila": 6,
    "red": 7,
    "yellow": 8,
    "blue": 9,
    "green": 10,
    "orange": 11,
    "white": 12,
    "silver": 13,
    "gold": 14,
    "various": 15, "multicolor": 15,
    "khaki": 16,
    "turquoise": 17,
    "cream": 20,
    "apricot": 21,
    "coral": 22,
    "burgundy": 23,
    "rose": 24,
    "lilac": 25,
    "light blue": 26, "light-blue": 26,
    "navy": 27, "marineblau": 27, "dark blue": 27,
    "dark green": 28, "dark-green": 28,
    "mustard": 29,
    "mint": 30,
    "clear": 32,
}

# Vinted size IDs — partial best-guess mapping per category. size_id=2 is
# verified working against catalog 221 (T-Shirts) per our day-6 smoke test.
# Other entries are extrapolated from the standard XS/S/M/L/XL pattern of
# size_group 4 and may need correction if Vinted rejects a draft completion.
# Keyed by (canonical category, normalized size label) tuples.
VINTED_SIZE_TO_ID: dict[tuple[str, str], int] = {
    # Tops — size_group 4 (XS/S/M/L/XL/XXL)
    ("tshirts", "xs"): 1,
    ("tshirts", "s"): 2,
    ("tshirts", "m"): 3,
    ("tshirts", "l"): 4,
    ("tshirts", "xl"): 5,
    ("tshirts", "xxl"): 6,
    ("jackets", "xs"): 1,
    ("jackets", "s"): 2,
    ("jackets", "m"): 3,
    ("jackets", "l"): 4,
    ("jackets", "xl"): 5,
    ("jackets", "xxl"): 6,
    # Sneakers — EU sizes 35-44 (rough guesses; needs empirical verification)
    ("sneakers", "35"): 100,
    ("sneakers", "36"): 101,
    ("sneakers", "37"): 102,
    ("sneakers", "38"): 103,
    ("sneakers", "39"): 104,
    ("sneakers", "40"): 105,
    ("sneakers", "41"): 106,
    ("sneakers", "42"): 107,
    # Jeans — waist sizes (rough guesses)
    ("jeans", "w26"): 200, ("jeans", "26"): 200,
    ("jeans", "w28"): 201, ("jeans", "28"): 201,
    ("jeans", "w30"): 202, ("jeans", "30"): 202,
    ("jeans", "w32"): 203, ("jeans", "32"): 203,
}


def _lookup_color_id(color: str | None) -> int | None:
    if not color:
        return None
    return VINTED_COLOR_TO_ID.get(color.strip().lower())


def _lookup_size_id(category: str | None, size: str | None) -> int | None:
    if not category or not size:
        return None
    # Normalize sizes like "S / 36 / 8" → try the first space-or-slash chunk
    for token in size.replace("/", " ").split():
        cand = token.strip().lower()
        if (category, cand) in VINTED_SIZE_TO_ID:
            return VINTED_SIZE_TO_ID[(category, cand)]
    return None


def to_kleinanzeigen(canon: dict[str, Any]) -> dict[str, Any]:
    """Map canonical English fields to Kleinanzeigen-form values (German).
    Unknown/missing values drop their key rather than KeyError."""
    out: dict[str, Any] = {
        "marke": canon.get("brand"),
        "groesse": canon.get("size"),
        "preis": canon.get("price_eur"),
        "titel": canon.get("title"),
        "beschreibung": canon.get("description"),
    }
    cat = canon.get("category")
    if cat and cat in KA_CATEGORY_EN_TO_DE:
        out["kategorie"] = KA_CATEGORY_EN_TO_DE[cat]
    cond = canon.get("condition")
    if cond and cond in CONDITION_EN_TO_KA_DE:
        out["zustand"] = CONDITION_EN_TO_KA_DE[cond]
    color = canon.get("color")
    if color and color in COLOR_EN_TO_KA_DE:
        out["farbe"] = COLOR_EN_TO_KA_DE[color]
    return out


def to_vinted(canon: dict[str, Any]) -> dict[str, Any]:
    """Map canonical English fields to Vinted item-payload values.

    Returns enough to feed `backend.integrations.vinted._build_item_payload`
    once photo IDs are attached. Missing brand / color / size are passed as
    None / empty so Vinted accepts the listing and the user can fill them in
    the Vinted UI if needed.
    """
    out: dict[str, Any] = {
        "title": canon.get("title"),
        "description": canon.get("description"),
        "brand": canon.get("brand"),
        "size": canon.get("size"),
        "price": canon.get("price_eur"),
        "currency": "EUR",
        "color_ids": [],
    }
    cat = canon.get("category")
    if cat and cat in VINTED_CATEGORY_TO_CATALOG_ID:
        out["catalog_id"] = VINTED_CATEGORY_TO_CATALOG_ID[cat]
    cond = canon.get("condition")
    if cond and cond in VINTED_CONDITION_TO_ID:
        out["condition_id"] = VINTED_CONDITION_TO_ID[cond]
    color_id = _lookup_color_id(canon.get("color"))
    if color_id is not None:
        out["color_ids"] = [color_id]
    size_id = _lookup_size_id(cat, canon.get("size"))
    if size_id is not None:
        out["size_id"] = size_id
    return out
