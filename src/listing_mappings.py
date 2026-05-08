"""Convert the model's canonical English schema to platform-native fields.

Used by the publish endpoint (Day 4 work) — given the model's canonical
output, ``to_kleinanzeigen`` and ``to_vinted`` produce the field values each
platform's listing form / API expects.

Vinted's API takes ontology IDs for catalog and color; those need to be
fetched live from ``GetOntologies`` and cached locally. Stubbed here as
``None`` until the publish flow lands.
"""

from __future__ import annotations

from typing import Any

from translations import (
    COLOR_EN_TO_KA_DE,
    CONDITION_EN_TO_KA_DE,
    KA_CATEGORY_EN_TO_DE,
)

# Used by /publish to redirect the user to the platform's new-listing form.
# Neither platform supports URL-based field prefill on these forms, so this
# is just the page URL — the frontend handles the prefill UX (copy buttons).
NEW_LISTING_URLS: dict[str, str] = {
    "vinted": "https://www.vinted.de/items/new",
    "kleinanzeigen": "https://www.kleinanzeigen.de/p-anzeige-aufgeben.html",
}


# TODO(day4): populate from a cached GetOntologies response.
# Keys are canonical English; values are Vinted ontology IDs.
VINTED_CATEGORY_TO_CATALOG_ID: dict[str, int | None] = {
    "jackets": None,
    "jeans": None,
    "tshirts": None,
    "sneakers": None,
}
VINTED_COLOR_TO_ID: dict[str, int | None] = {}  # populated at publish time


def to_kleinanzeigen(canon: dict[str, Any]) -> dict[str, Any]:
    """Map canonical English fields to Kleinanzeigen-form values (German).

    ``canon`` keys: ``category``, ``condition``, ``color``, plus passthroughs
    ``brand``, ``size``, ``price_eur``, ``title``, ``description``.

    Title and description stay English — translating them back to German is
    a separate downstream concern (and may be left to the user, who can edit
    the prefilled form before publishing).
    """
    return {
        "kategorie": KA_CATEGORY_EN_TO_DE[canon["category"]],
        "zustand": CONDITION_EN_TO_KA_DE[canon["condition"]],
        "farbe": COLOR_EN_TO_KA_DE[canon["color"]],
        "marke": canon.get("brand"),
        "groesse": canon.get("size"),
        "preis": canon.get("price_eur"),
        "titel": canon.get("title"),
        "beschreibung": canon.get("description"),
    }


def to_vinted(canon: dict[str, Any]) -> dict[str, Any]:
    """Map canonical English fields to Vinted ``POST /items`` payload values.

    ``catalog_id`` and ``color_ids`` are stubbed until the GetOntologies fetch
    is wired up in Day 4. Title / description / brand / size / price pass
    through unchanged.
    """
    return {
        "title": canon.get("title"),
        "description": canon.get("description"),
        "catalog_id": VINTED_CATEGORY_TO_CATALOG_ID.get(canon["category"]),
        "color_ids": [VINTED_COLOR_TO_ID[canon["color"]]] if canon["color"] in VINTED_COLOR_TO_ID else [],
        "condition_label": canon["condition"],  # Vinted accepts the EN label; ID lookup TBD.
        "brand": canon.get("brand"),
        "size": canon.get("size"),
        "price": canon.get("price_eur"),
    }
