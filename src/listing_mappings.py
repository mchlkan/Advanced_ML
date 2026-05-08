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

# Color IDs need a GetOntologies fetch we haven't wired up; leave empty so
# the listing posts without a color and the user can pick one in the form.
VINTED_COLOR_TO_ID: dict[str, int] = {}


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
    color = canon.get("color")
    if color and color in VINTED_COLOR_TO_ID:
        out["color_ids"] = [VINTED_COLOR_TO_ID[color]]
    return out
