"""Direct pipeline test (no HTTP layer)."""

from __future__ import annotations

import asyncio

import pytest
from PIL import Image

from backend.pipeline import run_pipeline
from backend.vlm_backend import get_backend


def test_pipeline_smoke(loaded_models):
    img = Image.new("RGB", (256, 256), color=(110, 200, 50))
    vlm = get_backend()
    result = asyncio.run(run_pipeline(img, loaded_models, vlm))

    assert 0.0 <= result["visual_wear_probability"] <= 1.0
    for platform in ("vinted", "kleinanzeigen"):
        price = result[platform]["price"]
        assert price["q10"] <= price["q50"] <= price["q90"]
        assert price["q10"] >= 0
    assert 0.0 <= result["vinted"]["sell_probability"] <= 1.0
    for platform in ("vinted", "kleinanzeigen"):
        ident = result[platform]["identification"]
        assert ident["brand"] is not None
        assert ident["category"] is not None
        assert ident["condition"] is not None
    assert result["vlm_call_count"] == 2


def test_pipeline_deterministic(loaded_models):
    """Same image → same output (stub backend hashes pixel bytes)."""
    img = Image.new("RGB", (256, 256), color=(50, 50, 50))
    vlm = get_backend()
    a = asyncio.run(run_pipeline(img, loaded_models, vlm))
    b = asyncio.run(run_pipeline(img, loaded_models, vlm))
    assert a["vinted"]["identification"] == b["vinted"]["identification"]
    assert a["kleinanzeigen"]["identification"] == b["kleinanzeigen"]["identification"]
    assert a["vinted"]["price"] == pytest.approx(b["vinted"]["price"])
