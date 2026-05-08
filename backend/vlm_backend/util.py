"""Backend-wide VLM utilities — kept dependency-light (stdlib + Pillow only)
so importers like runpod_http don't pull torch / transformers / peft just
for a regex helper."""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VLMParseResult:
    fields: dict
    parse_ok: bool
    recovered: bool


JSON_FIELD_RE = re.compile(
    r'"?(?P<key>brand|category|condition|color|size|title|description|price_eur)"?\s*:\s*'
    r'(?P<value>"(?:[^"\\]|\\.)*"?|-?\d+(?:\.\d+)?|null)',
    re.IGNORECASE | re.DOTALL,
)


def parse_json_lenient(text: str) -> dict:
    """Best-effort JSON extraction. The VLM may wrap output in markdown fences
    or trail prose. Falls back to ``{}`` so callers can ``.get()`` defensively —
    but logs a warning so silent garbage predictions leave a breadcrumb."""
    return parse_vlm_fields(text).fields


def _as_float(value: str) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out >= 0 else None


def _recover_json_fields(text: str) -> dict[str, Any]:
    recovered: dict[str, Any] = {}
    for match in JSON_FIELD_RE.finditer(text or ""):
        key = match.group("key")
        value = match.group("value").strip()
        if value == "null":
            recovered[key] = None
        elif value.startswith('"'):
            recovered[key] = value[1:].rstrip('"').replace('\\"', '"').replace("\\n", "\n").strip()
        else:
            recovered[key] = _as_float(value)
    return recovered


def parse_vlm_fields(text: str) -> VLMParseResult:
    """Parse VLM output and expose whether recovery was needed.

    ``parse_ok`` means the model emitted valid JSON after normal fence/prose
    cleanup. ``recovered`` means we salvaged individual fields from a broken or
    truncated object, which is good enough for the UI but should be reviewed.
    """
    if not text:
        return VLMParseResult(fields={}, parse_ok=False, recovered=False)
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return VLMParseResult(fields=parsed, parse_ok=True, recovered=False)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if 0 <= start < end:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            if isinstance(parsed, dict):
                return VLMParseResult(fields=parsed, parse_ok=True, recovered=False)
        except json.JSONDecodeError:
            pass
    recovered = _recover_json_fields(cleaned)
    if recovered:
        logger.warning(
            "parse_vlm_fields: recovered fields from malformed VLM output (first 200 chars): %r",
            text[:200],
        )
        return VLMParseResult(fields=recovered, parse_ok=False, recovered=True)
    logger.warning(
        "parse_json_lenient: could not extract JSON from VLM output (first 200 chars): %r",
        text[:200],
    )
    return VLMParseResult(fields={}, parse_ok=False, recovered=False)


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
