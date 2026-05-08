"""Pluggable VLM backend.

Backends: ``stub`` (deterministic fake), ``local_mps`` (in-process Qwen+adapter),
``runpod_http`` (RunPod Serverless endpoint). Selected via ``VLM_BACKEND`` env var.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image


@dataclass
class VLMOutput:
    hidden_state: np.ndarray  # shape (vlm_dim,), dtype float32
    fields: dict               # parsed JSON: brand, category, condition, color, size, title, description, price_eur
    raw_text: str              # raw VLM output text for debugging


class VLMBackend(Protocol):
    name: str

    async def predict(self, image: Image.Image, platform: str, hints: str | None = None) -> VLMOutput: ...


def get_backend() -> VLMBackend:
    name = os.environ.get("VLM_BACKEND", "stub").lower()
    if name == "stub":
        from .stub import StubVLM
        return StubVLM()
    if name == "local_mps":
        raise NotImplementedError("local_mps backend ships in Phase 2")
    if name == "runpod_http":
        raise NotImplementedError("runpod_http backend ships in Phase 3")
    raise ValueError(f"Unknown VLM_BACKEND: {name!r}")
