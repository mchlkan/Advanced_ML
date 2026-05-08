"""RunPod Serverless handler — Qwen3-VL-4B + LoRA in 4-bit.

Loads the model + adapter once at module import (cached across warm calls).
Per request: forward pass for the prefill last-token hidden state, then a
greedy generate for the JSON output. Returns both — the backend parses the
JSON with its own lenient parser so we don't couple the handler to the
schema.

Mirrors the recipe in models/extract_vlm_features.py to keep the
training/serving paths identical.
"""

from __future__ import annotations

import base64
import io
import os
import sys

import runpod
import torch
from peft import PeftModel
from PIL import Image
from transformers import (
    AutoModelForImageTextToText,
    AutoProcessor,
    BitsAndBytesConfig,
)

# /workspace contains the source files COPY'd by the Dockerfile.
sys.path.insert(0, "/workspace/src")
sys.path.insert(0, "/workspace/models")

from extract_vlm_features import build_inputs, model_device  # noqa: E402
from prompts import get_prompt  # noqa: E402


BASE_MODEL = os.environ.get("BASE_MODEL", "Qwen/Qwen3-VL-4B-Instruct")
ADAPTER_ID = os.environ.get("ADAPTER_ID", "Rengo33/qwen3vl4b-resell-adapter")
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "256"))


print(f"Loading {BASE_MODEL} (4-bit) + adapter {ADAPTER_ID}...", flush=True)
_processor = AutoProcessor.from_pretrained(BASE_MODEL, trust_remote_code=True)
_quant = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)
_base = AutoModelForImageTextToText.from_pretrained(
    BASE_MODEL,
    trust_remote_code=True,
    device_map="auto",
    quantization_config=_quant,
)
_model = PeftModel.from_pretrained(_base, ADAPTER_ID)
_model.eval()
print(f"Model ready on {model_device(_model)}", flush=True)


@torch.no_grad()
def handler(event):
    body = event.get("input", {})
    img_b64 = body.get("image_b64")
    platform = body.get("platform")
    hints = body.get("hints")

    if not img_b64 or platform not in ("vinted", "kleinanzeigen"):
        return {"error": f"bad input: image_b64 required, platform must be 'vinted' or 'kleinanzeigen' (got {platform!r})"}

    try:
        img = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
    except Exception as exc:
        return {"error": f"could not decode image_b64: {type(exc).__name__}: {exc}"}

    prompt = get_prompt(platform)
    if hints:
        prompt = f"{prompt}\n{hints}"

    inputs = build_inputs(_processor, img, platform, model_device(_model), prompt=prompt)

    out = _model(**inputs, output_hidden_states=True, return_dict=True)
    hidden = out.hidden_states[-1][0, -1, :].float().cpu().numpy().tolist()

    gen = _model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False)
    new_tokens = gen[0, inputs["input_ids"].shape[1]:]
    raw_text = _processor.decode(new_tokens, skip_special_tokens=True).strip()

    return {"hidden_state": hidden, "raw_text": raw_text}


runpod.serverless.start({"handler": handler})
