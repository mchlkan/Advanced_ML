"""Inference orchestration: image → VLM ×2 + DINOv2 → flaw → price ×2 + sell.

Two VLM calls run in parallel because each platform-specific prompt embeds a
different category vocabulary and the price head was trained with
platform-matched hidden states. The sync DINOv2 + head forwards run inside a
single asyncio.to_thread call so concurrent requests don't starve the event loop.
"""

from __future__ import annotations

import asyncio
import math
import time

import numpy as np
import torch
from PIL import Image

# backend/__init__.py adds repo/models and repo/shared to sys.path.
from build_price_dataset import canon_brand

from .bootstrap import LoadedModels, dinov2_embed
from .vlm_backend import VLMBackend


def _idx(value: str | None, mapping: dict, unk_key: str | None = None) -> int:
    if value is not None and value in mapping:
        return int(mapping[value])
    if unk_key is not None and unk_key in mapping:
        return int(mapping[unk_key])
    return 0


def _tag_proxy(condition: str | None) -> float:
    return 1.0 if condition == "New with tags" else 0.0


def _price_numeric(visual_wear: float, tag_proxy: float, use_flaw: bool) -> torch.Tensor:
    cols = [visual_wear, tag_proxy] if use_flaw else [tag_proxy]
    return torch.tensor([cols], dtype=torch.float32)


def _sell_numeric(visual_wear: float, tag_proxy: float, log_price: float, use_flaw: bool) -> torch.Tensor:
    cols = [visual_wear, tag_proxy, log_price] if use_flaw else [tag_proxy, log_price]
    return torch.tensor([cols], dtype=torch.float32)


@torch.no_grad()
def _run_price_head(
    models: LoadedModels,
    vlm_hidden: np.ndarray,
    visual_wear: float,
    platform: str,
    fields: dict,
) -> tuple[float, float, float]:
    vocab = models.price_vocab
    device = models.device
    batch = {
        "vlm": torch.from_numpy(vlm_hidden).unsqueeze(0).to(device),
        "numeric": _price_numeric(visual_wear, _tag_proxy(fields.get("condition")), models.price_uses_flaw).to(device),
        "platform": torch.tensor([_idx(platform, vocab["platform"])], dtype=torch.int64, device=device),
        "category": torch.tensor([_idx(fields.get("category"), vocab["category_en"])], dtype=torch.int64, device=device),
        "condition": torch.tensor([_idx(fields.get("condition"), vocab["condition_en"])], dtype=torch.int64, device=device),
        "brand": torch.tensor(
            [_idx(canon_brand(fields.get("brand")), vocab["brand_canon"], unk_key=vocab.get("unk_brand", "UNK"))],
            dtype=torch.int64, device=device,
        ),
    }
    log_q = models.price_head(batch).cpu().numpy()[0]
    log_q.sort()
    prices = np.expm1(log_q).clip(min=0)
    return float(prices[0]), float(prices[2]), float(prices[4])


@torch.no_grad()
def _run_sell_head(
    models: LoadedModels,
    vlm_hidden: np.ndarray | None,
    visual_wear: float,
    asking_price: float,
    fields: dict,
) -> float:
    vocab = models.sell_vocab
    device = models.device
    if models.sell_uses_vlm:
        if vlm_hidden is None:
            raise ValueError("sell_head requires a VLM hidden state when sell_uses_vlm is True")
        vlm_t = torch.from_numpy(vlm_hidden).unsqueeze(0).to(device)
    else:
        vlm_t = torch.zeros((1, 0), dtype=torch.float32, device=device)
    log_price = math.log1p(max(asking_price, 0.0))
    batch = {
        "vlm": vlm_t,
        "numeric": _sell_numeric(visual_wear, _tag_proxy(fields.get("condition")), log_price, models.sell_uses_flaw).to(device),
        "category": torch.tensor([_idx(fields.get("category"), vocab["category_en"])], dtype=torch.int64, device=device),
        "condition": torch.tensor([_idx(fields.get("condition"), vocab["condition_en"])], dtype=torch.int64, device=device),
        "brand": torch.tensor(
            [_idx(canon_brand(fields.get("brand")), vocab["brand_canon"], unk_key=vocab.get("unk_brand", "UNK"))],
            dtype=torch.int64, device=device,
        ),
    }
    logit = models.sell_head(batch)
    return float(torch.sigmoid(logit).item())


@torch.no_grad()
def _run_flaw_head(models: LoadedModels, dinov2_cls: torch.Tensor) -> float:
    logit = models.flaw_head(dinov2_cls.unsqueeze(0).to(models.device))
    return float(torch.sigmoid(logit).item())


def _run_local_inference(image: Image.Image, models: LoadedModels, vinted_vlm, ka_vlm) -> dict:
    """Sync tail: DINOv2 + flaw + 2× price + sell. Wrapped in asyncio.to_thread."""
    dinov2_cls = dinov2_embed(image, models)
    visual_wear = _run_flaw_head(models, dinov2_cls)

    v_q10, v_q50, v_q90 = _run_price_head(models, vinted_vlm.hidden_state, visual_wear, "vinted", vinted_vlm.fields)
    k_q10, k_q50, k_q90 = _run_price_head(models, ka_vlm.hidden_state, visual_wear, "kleinanzeigen", ka_vlm.fields)

    sell_prob = _run_sell_head(
        models,
        vinted_vlm.hidden_state if models.sell_uses_vlm else None,
        visual_wear,
        v_q50,  # asking price input is our predicted vinted median
        vinted_vlm.fields,
    )
    return {
        "visual_wear_probability": visual_wear,
        "vinted_price": (v_q10, v_q50, v_q90),
        "ka_price": (k_q10, k_q50, k_q90),
        "sell_prob": sell_prob,
    }


async def run_pipeline(
    image: Image.Image,
    models: LoadedModels,
    vlm: VLMBackend,
    hints: str | None = None,
    field_overrides: dict | None = None,
) -> dict:
    started = time.perf_counter()

    vinted_vlm, ka_vlm = await asyncio.gather(
        vlm.predict(image, "vinted", hints=hints),
        vlm.predict(image, "kleinanzeigen", hints=hints),
    )

    if field_overrides:
        for vlm_out in (vinted_vlm, ka_vlm):
            vlm_out.fields = {**vlm_out.fields, **field_overrides}

    local = await asyncio.to_thread(_run_local_inference, image, models, vinted_vlm, ka_vlm)

    v_q10, v_q50, v_q90 = local["vinted_price"]
    k_q10, k_q50, k_q90 = local["ka_price"]
    return {
        "visual_wear_probability": local["visual_wear_probability"],
        "vinted": {
            "price": {"q10": v_q10, "q50": v_q50, "q90": v_q90},
            "sell_probability": local["sell_prob"],
            "identification": vinted_vlm.fields,
        },
        "kleinanzeigen": {
            "price": {"q10": k_q10, "q50": k_q50, "q90": k_q90},
            "identification": ka_vlm.fields,
        },
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "vlm_call_count": 2,
    }
