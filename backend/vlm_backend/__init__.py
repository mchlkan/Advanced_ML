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
    parse_ok: bool = True      # True when raw_text parsed as valid JSON after light cleanup
    recovered: bool = False    # True when fields were salvaged from malformed/truncated JSON


class VLMBackend(Protocol):
    name: str

    async def warmup(self) -> None: ...
    async def predict(self, image: Image.Image, platform: str, hints: str | None = None) -> VLMOutput: ...


def get_backend() -> VLMBackend:
    name = os.environ.get("VLM_BACKEND", "stub").lower()
    if name == "stub":
        from .stub import StubVLM
        return StubVLM()
    if name == "local_mps":
        from .local_mps import DEFAULT_ADAPTER, DEFAULT_BASE_MODEL, LocalMPSVLM
        return LocalMPSVLM(
            base_model=os.environ.get("VLM_BASE_MODEL", DEFAULT_BASE_MODEL),
            adapter_id=os.environ.get("VLM_ADAPTER_ID", DEFAULT_ADAPTER),
            device_pref=os.environ.get("DEVICE", "auto"),
        )
    if name == "runpod_http":
        from .runpod_http import RunpodHTTPVLM
        timeout_s = int(os.environ.get("RUNPOD_TIMEOUT_S", "120"))
        return RunpodHTTPVLM(timeout_s=timeout_s)
    raise ValueError(f"Unknown VLM_BACKEND: {name!r}")
