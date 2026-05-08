"""Backend-wide VLM utilities — kept dependency-light (stdlib + Pillow only)
so importers like runpod_http don't pull torch / transformers / peft just
for a regex helper."""

from __future__ import annotations

import base64
import io
import json
import logging
import re

from PIL import Image

logger = logging.getLogger(__name__)


def parse_json_lenient(text: str) -> dict:
    """Best-effort JSON extraction. The VLM may wrap output in markdown fences
    or trail prose. Falls back to ``{}`` so callers can ``.get()`` defensively —
    but logs a warning so silent garbage predictions leave a breadcrumb."""
    if not text:
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass
    logger.warning(
        "parse_json_lenient: could not extract JSON from VLM output (first 200 chars): %r",
        text[:200],
    )
    return {}


def resize_and_b64(image: Image.Image, max_dim: int = 1024, quality: int = 85) -> str:
    """Downscale to max_dim on the longest side, encode as JPEG base64.

    Caps payload size for HTTP transport to remote VLM workers. Qwen3-VL's
    processor downscales internally anyway, so the visible quality impact is
    minimal but the network and per-request CPU cost drops by ~10x for typical
    phone photos."""
    img = image.convert("RGB")
    w, h = img.size
    longest = max(w, h)
    if longest > max_dim:
        scale = max_dim / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")
