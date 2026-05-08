"""Deterministic stub VLM backend — for frontend dev without GPU.

Returns a fixed-shape (2560,) hidden state derived from an image hash so the
same image yields the same predictions across requests. Field values are
plausible-looking placeholders pulled from the platform's allowed vocabulary.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from . import VLMOutput

_SHARED_DIR = Path(__file__).resolve().parent.parent.parent / "shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
from prompts import (  # noqa: E402
    CONDITION_VALUES_EN,
    KLEINANZEIGEN_CATEGORIES_EN,
    VINTED_CATEGORIES_EN,
)


VLM_DIM = 2560
_BRANDS = ["Zara", "H&M", "Nike", "Adidas", "Levi's", "Uniqlo"]
_COLORS = ["black", "white", "blue", "red", "green", "grey"]


def _seeded_rng(image: Image.Image, platform: str, hints: str | None) -> np.random.Generator:
    h = hashlib.sha256()
    h.update(image.tobytes())
    h.update(platform.encode())
    if hints:
        h.update(hints.encode())
    seed = int.from_bytes(h.digest()[:8], "big") & 0xFFFFFFFF
    return np.random.default_rng(seed)


class StubVLM:
    name = "stub"

    async def warmup(self) -> None:
        pass

    async def predict(self, image: Image.Image, platform: str, hints: str | None = None) -> VLMOutput:
        rng = _seeded_rng(image, platform, hints)
        cats = VINTED_CATEGORIES_EN if platform == "vinted" else KLEINANZEIGEN_CATEGORIES_EN
        cat = cats[rng.integers(len(cats))]
        cond = CONDITION_VALUES_EN[rng.integers(len(CONDITION_VALUES_EN))]
        brand = _BRANDS[rng.integers(len(_BRANDS))]
        color = _COLORS[rng.integers(len(_COLORS))]
        size = ["XS", "S", "M", "L", "XL"][rng.integers(5)]
        price = round(float(rng.uniform(8, 80)), 2)
        title = f"{brand} {cat} in {color}"
        description = (
            f"{cond} {color} {cat} from {brand}, size {size}. "
            "Worn a few times, still in great shape. Smoke-free home."
        )
        fields = {
            "brand": brand,
            "category": cat,
            "condition": cond,
            "color": color,
            "size": size,
            "title": title,
            "description": description,
            "price_eur": price,
        }
        hidden_state = rng.normal(0, 1, size=VLM_DIM).astype(np.float32)
        return VLMOutput(
            hidden_state=hidden_state,
            fields=fields,
            raw_text=str(fields),
        )
