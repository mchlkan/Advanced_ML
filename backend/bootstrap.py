"""Load DINOv2 + the three trained MLP heads once at FastAPI startup.

Each MLP checkpoint carries ``model_config`` (ctor kwargs) and ``vocab``
(field→index mappings) so the inference path doesn't need training data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel

# backend/__init__.py adds repo/models and repo/shared to sys.path.
from train_flaw_head import FlawHead
from train_price_head import PriceHead
from train_sell_head import SellHead
from extract_features import choose_device


REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKPOINTS_DIR = REPO_ROOT / "models" / "checkpoints"

DINOV2_MODEL_ID = "facebook/dinov2-base"
FLAW_CKPT = CHECKPOINTS_DIR / "flaw_head_vinted.pt"
PRICE_CKPT = CHECKPOINTS_DIR / "price_head.pt"
SELL_CKPT = CHECKPOINTS_DIR / "sell_head.pt"


@dataclass
class LoadedModels:
    device: torch.device
    dinov2_processor: object
    dinov2: torch.nn.Module
    flaw_head: FlawHead
    flaw_input_dim: int
    price_head: PriceHead
    sell_head: SellHead
    price_vocab: dict
    sell_vocab: dict
    price_uses_flaw: bool
    sell_uses_flaw: bool
    sell_uses_vlm: bool
    flaw_threshold: float

    def inventory(self) -> list[str]:
        return [
            f"DINOv2 ({DINOV2_MODEL_ID})",
            f"FlawHead (in_dim={self.flaw_input_dim})",
            f"PriceHead (uses_flaw={self.price_uses_flaw})",
            f"SellHead (uses_vlm={self.sell_uses_vlm}, uses_flaw={self.sell_uses_flaw})",
        ]


def _load_mlp(cls, ckpt_path: Path, device: torch.device):
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    model = cls(**ckpt["model_config"])
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    model.to(device)
    return model, ckpt


def load_models(device_pref: str = "auto") -> LoadedModels:
    device = choose_device(device_pref)

    dinov2_processor = AutoImageProcessor.from_pretrained(DINOV2_MODEL_ID)
    dinov2 = AutoModel.from_pretrained(DINOV2_MODEL_ID).eval().to(device)

    flaw_head, flaw_ckpt = _load_mlp(FlawHead, FLAW_CKPT, device)
    price_head, price_ckpt = _load_mlp(PriceHead, PRICE_CKPT, device)
    sell_head, sell_ckpt = _load_mlp(SellHead, SELL_CKPT, device)

    return LoadedModels(
        device=device,
        dinov2_processor=dinov2_processor,
        dinov2=dinov2,
        flaw_head=flaw_head,
        flaw_input_dim=int(flaw_ckpt["model_config"].get("input_dim", 768)),
        price_head=price_head,
        sell_head=sell_head,
        price_vocab=price_ckpt["vocab"],
        sell_vocab=sell_ckpt["vocab"],
        price_uses_flaw=bool(price_ckpt.get("uses_visual_wear_probability", True)),
        sell_uses_flaw=bool(sell_ckpt.get("uses_visual_wear_probability", True)),
        sell_uses_vlm=int(sell_ckpt["model_config"].get("vlm_dim", 0)) > 0,
        flaw_threshold=float(flaw_ckpt.get("threshold", 0.5)),
    )


@torch.no_grad()
def dinov2_embed(image: Image.Image, models: LoadedModels) -> torch.Tensor:
    """Single-image DINOv2 CLS embedding. Returns shape [768]."""
    encoded = models.dinov2_processor(images=image, return_tensors="pt")
    encoded = {k: v.to(models.device) for k, v in encoded.items()}
    out = models.dinov2(**encoded)
    return out.last_hidden_state[0, 0, :].detach().float().cpu()
