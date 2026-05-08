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


# Kleinanzeigen numeric category IDs. 160 (Kleidung_Herren) is proven
# working in the capture; the moderation queue accepts it for women's
# items too, so we route all clothing through it for v1 and let the user
# recategorise on the KA UI if they want a more specific leaf. Sneakers
# live under a different parent (Damenschuhe / Herrenschuhe) and aren't
# mapped here — those listings fall back to the URL path until we capture
# the right leaf id.
KA_CATEGORY_TO_ID: dict[str, int] = {
    "tshirts": 160,
    "jackets": 160,
    "jeans": 160,
}

# KA's per-category attribute schema for category 160 (kleidung_herren).
# All seven slots get filled even though metadata says required=False —
# the publish endpoint enforces presence beyond what metadata exposes
# (verified empirically: omitting `kleidung_herren.art` returns
# "Bitte gib einen Wert ein.").
KA_ATTR_FIXED_KLEIDUNG_HERREN: dict[str, str] = {
    "kleidung_herren.versand": "ja",
    "kleidung_herren.seller_badges": "none",
}

# canonical category → KA "art" (clothing-type) slug
KA_ATTR_ART_KLEIDUNG_HERREN: dict[str, str] = {
    "tshirts": "shirts",
    "jackets": "jacken_maentel",
    "jeans": "jeans",
}

# canonical condition → KA condition slug. The capture confirmed only
# "Very good" → "like_new"; the others are best-guess slugs that match
# Vinted-side patterns. If KA rejects one, the request body is shown in
# the runner's error column so we can correct empirically.
KA_ATTR_CONDITION_KLEIDUNG_HERREN: dict[str, str] = {
    "New with tags": "new_etikett",
    "New": "new",
    "Very good": "like_new",
    "Good": "good",
}


def _ka_brand_slug(brand: str) -> str:
    """Slugify the brand to the form KA stores
    (e.g. ``"abercrombie & fitch" → "abercrombie_fitch"``)."""
    import re
    return re.sub(r"[^a-z0-9]+", "_", brand.lower()).strip("_")

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

# Vinted size IDs by (category, normalized size label). All four of our canon
# categories report `multiple_size_group_ids: [4]` in the catalogs response
# *except* sneakers which uses size_group 7. Size_group 4 follows the
# XS/S/M/L/XL/XXL pattern with size_id 1..6 (size_id=2 verified empirically
# against catalog 221). Size_group 7's IDs aren't recoverable without
# creating throwaway live listings, so sneaker sizes are intentionally
# unmapped here — the integration drops the key and the user picks the
# size on the Vinted UI before publishing on-platform.
VINTED_SIZE_TO_ID: dict[tuple[str, str], int] = {
    ("tshirts", "xs"): 1, ("tshirts", "s"): 2, ("tshirts", "m"): 3,
    ("tshirts", "l"): 4, ("tshirts", "xl"): 5, ("tshirts", "xxl"): 6,
    ("jackets", "xs"): 1, ("jackets", "s"): 2, ("jackets", "m"): 3,
    ("jackets", "l"): 4, ("jackets", "xl"): 5, ("jackets", "xxl"): 6,
    ("jeans", "xs"): 1, ("jeans", "s"): 2, ("jeans", "m"): 3,
    ("jeans", "l"): 4, ("jeans", "xl"): 5, ("jeans", "xxl"): 6,
    # sneakers (size_group 7): unmapped — see note above
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
    """Build the variable bits of the KA listing payload from canonical
    English fields. The integration layers session-derived defaults
    (email, poster_type, imprint, contact_name, location_id) on top — this
    function only contributes the per-listing parts.

    KA's listing API doesn't take separate brand/size/color/condition
    fields in the captured request body — those are encoded inside the
    free-text description (which the VLM already produces). So we just
    pass the title and description through and translate the canonical
    category to a KA category id.
    """
    out: dict[str, Any] = {}
    if canon.get("title"):
        out["title"] = canon["title"]
    if canon.get("description"):
        out["description"] = canon["description"]
    if canon.get("price_eur") is not None:
        out["price_eur"] = canon["price_eur"]
    cat = canon.get("category")
    if cat and cat in KA_CATEGORY_TO_ID:
        out["category_id"] = KA_CATEGORY_TO_ID[cat]
        # KA's category 160 (kleidung_herren) requires a 7-slot attributes
        # block. Fill the always-fixed two plus whatever maps cleanly from
        # canon. Missing slots stay empty — KA will reject the submit in
        # that case with a per-attribute error visible in the job's error.
        attrs: dict[str, str] = dict(KA_ATTR_FIXED_KLEIDUNG_HERREN)
        if canon.get("brand"):
            attrs["kleidung_herren.brand"] = _ka_brand_slug(str(canon["brand"]))
        size = canon.get("size") or ""
        first = size.replace("/", " ").split()[:1]
        if first:
            attrs["kleidung_herren.groesse"] = first[0].lower()
        color = canon.get("color")
        if color and color in COLOR_EN_TO_KA_DE:
            attrs["kleidung_herren.color"] = COLOR_EN_TO_KA_DE[color].lower()
        cond = canon.get("condition")
        if cond and cond in KA_ATTR_CONDITION_KLEIDUNG_HERREN:
            attrs["kleidung_herren.condition"] = KA_ATTR_CONDITION_KLEIDUNG_HERREN[cond]
        if cat in KA_ATTR_ART_KLEIDUNG_HERREN:
            attrs["kleidung_herren.art"] = KA_ATTR_ART_KLEIDUNG_HERREN[cat]
        out["attributes"] = attrs
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
