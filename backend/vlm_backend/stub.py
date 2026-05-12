"""Deterministic stub VLM backend — for frontend dev without GPU.

Returns a fixed-shape (2560,) hidden state derived from an image hash so the
same image yields the same predictions across requests. Field values are
plausible-looking placeholders pulled from the platform's allowed vocabulary.
"""

from __future__ import annotations

import hashlib

import numpy as np
from PIL import Image

# backend/__init__.py adds repo/shared to sys.path.
from prompts import EXPECTED_HIDDEN_DIM

from . import VLMOutput

VLM_DIM = EXPECTED_HIDDEN_DIM


def _seeded_rng(
    image: Image.Image,
    platform: str,
    hints: str | None,
    label_image: Image.Image | None = None,
) -> np.random.Generator:
    h = hashlib.sha256()
    h.update(image.tobytes())
    h.update(platform.encode())
    if hints:
        h.update(hints.encode())
    if label_image is not None:
        h.update(label_image.tobytes())
    seed = int.from_bytes(h.digest()[:8], "big") & 0xFFFFFFFF
    return np.random.default_rng(seed)


class StubVLM:
    name = "stub"

    async def warmup(self) -> None:
        pass

    async def predict(
        self,
        image: Image.Image,
        platform: str,
        hints: str | None = None,
        label_image: Image.Image | None = None,
    ) -> VLMOutput:
        rng = _seeded_rng(image, platform, hints, label_image)
        fields = {
            "brand": "[STUB] brand",
            "category": "[STUB] category",
            "condition": "[STUB] condition",
            "color": "[STUB] color",
            "size": "[STUB] size",
            "title": "[STUB] title",
            "description": "[STUB] description — VLM_BACKEND=stub, no real image analysis",
            "price_eur": -1,
        }
        hidden_state = rng.normal(0, 1, size=VLM_DIM).astype(np.float32)
        return VLMOutput(
            hidden_state=hidden_state,
            fields=fields,
            raw_text=str(fields),
        )
