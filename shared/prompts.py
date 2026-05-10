"""Single source of truth for the VLM prompt.

The brief mandates the inference prompt match the training prompt exactly
(§3.1) — both training-time chat-template construction and backend inference
must call ``get_prompt`` with the same platform string.

Schema as of multi-v2 (2026-05-10): the prompt asks for six fields — brand,
category, condition, color, size, title. The training target adds ``price_eur``
as an auxiliary task so the pooled hidden state encodes price-relevant signal
for the downstream price head, even though inference does not ask for it.
``description`` was removed from both prompt and target: its multi-sentence
output overflowed the JSON-completion budget on KA listings, dropping clean
parse rate to 40.9%. With v2 the KA clean-parse rate is 100%.
"""

from __future__ import annotations

import json

SUPPORTED_PLATFORMS = ("vinted", "kleinanzeigen")
# Pooled hidden-state dimension of Qwen3-VL-4B. Pinned because the price/sell
# heads were trained against this size; changing the base VLM means retraining.
EXPECTED_HIDDEN_DIM = 2560

VINTED_CATEGORIES_EN = ["jackets", "jeans", "tshirts", "sneakers"]
KLEINANZEIGEN_CATEGORIES_EN = [
    "Women's clothing",
    "Men's clothing",
    "Women's shoes",
    "Men's shoes",
]
CONDITION_VALUES_EN = ["New with tags", "New", "Very good", "Good"]


def get_prompt(platform: str) -> str:
    """Return the English VLM prompt for ``platform``.

    ``platform`` must be ``"vinted"`` or ``"kleinanzeigen"``. The platform
    name and its English-canonical category vocabulary are baked into the
    instruction so the model emits a value the listing-time lookup tables
    can resolve.
    """
    if platform == "vinted":
        platform_name = "Vinted"
        cats = VINTED_CATEGORIES_EN
    elif platform == "kleinanzeigen":
        platform_name = "Kleinanzeigen"
        cats = KLEINANZEIGEN_CATEGORIES_EN
    else:
        raise ValueError(f"Unknown platform: {platform!r}")

    cats_str = json.dumps(cats, ensure_ascii=False)
    cond_str = json.dumps(CONDITION_VALUES_EN, ensure_ascii=False)
    return (
        f"You are an expert at writing {platform_name} listings for second-hand clothing. "
        f"Look at the photo and return ONLY a single JSON object — no prose, "
        f"no markdown, no code fence.\n\n"
        f"Format:\n"
        f"{{\n"
        f'  "brand": <brand name as a string, or null>,\n'
        f'  "category": <one of {cats_str}>,\n'
        f'  "condition": <one of {cond_str}>,\n'
        f'  "color": <color in English>,\n'
        f'  "size": <size as a string, or null>,\n'
        f'  "title": <listing title in English>\n'
        f"}}\n\n"
        f"Respond with the JSON object only."
    )
