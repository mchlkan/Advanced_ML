"""RunPod Serverless handler — Qwen3-VL-4B + LoRA, bf16.

Loads the model + adapter once at module import (cached across warm calls).
Per request: one greedy ``generate`` with ``output_hidden_states=True`` — the
prefill step's last-token hidden state feeds the downstream price/sell heads,
the generated tokens are the JSON output. Returns both; the backend parses the
JSON with its own lenient parser so the handler isn't coupled to the schema.

Self-contained: only depends on prompts.py from shared/. The chat-template
input construction is inlined here (originally in
models/extract_vlm_features.py) so worker boot is independent of the
training module's churn.
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
from transformers import AutoModelForImageTextToText, AutoProcessor

# /workspace/shared is COPY'd by the Dockerfile.
sys.path.insert(0, "/workspace/shared")
from prompts import EXPECTED_HIDDEN_DIM, SUPPORTED_PLATFORMS, get_prompt  # noqa: E402


BASE_MODEL = os.environ.get("BASE_MODEL", "Qwen/Qwen3-VL-4B-Instruct")
ADAPTER_ID = os.environ.get("ADAPTER_ID", "mchlkan/qwen3vl4b-resell-adapter-multi-v3")
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "256"))
HF_TOKEN = os.environ.get("HF_TOKEN")


_token_status = f"set (len={len(HF_TOKEN)})" if HF_TOKEN else "MISSING"
print(f"[boot] HF_TOKEN: {_token_status}", flush=True)
print(f"[boot] BASE_MODEL: {BASE_MODEL}", flush=True)
print(f"[boot] ADAPTER_ID: {ADAPTER_ID}", flush=True)


print(f"[boot] Loading processor for {BASE_MODEL}...", flush=True)
_processor = AutoProcessor.from_pretrained(
    BASE_MODEL, trust_remote_code=True, token=HF_TOKEN
)

print(f"[boot] Loading base model {BASE_MODEL} (bf16)...", flush=True)
# bf16, not bnb-4bit: the 4B model is ~8 GB in bf16 — fits a 24 GB GPU with
# room to spare, and runs faster than nf4 (which dequantizes to bf16 on every
# matmul anyway) with no accuracy loss. If a smaller GPU ever forces 4-bit,
# prefer an AWQ/GPTQ build over bitsandbytes.
_base = AutoModelForImageTextToText.from_pretrained(
    BASE_MODEL,
    trust_remote_code=True,
    device_map="auto",
    torch_dtype=torch.bfloat16,
    token=HF_TOKEN,
)

print(f"[boot] Loading LoRA adapter {ADAPTER_ID}...", flush=True)
_model = PeftModel.from_pretrained(_base, ADAPTER_ID, token=HF_TOKEN)
_model.eval()
_device = next(_model.parameters()).device
print(f"[boot] Model ready on {_device}", flush=True)


def _build_inputs(image: Image.Image, platform: str, prompt: str, label_image: Image.Image | None = None):
    content = [{"type": "image", "image": image}]
    if label_image is not None:
        content.append({"type": "image", "image": label_image})
    content.append({"type": "text", "text": prompt})
    messages = [{"role": "user", "content": content}]
    inputs = _processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    )
    return inputs.to(_device)


@torch.no_grad()
def handler(event):
    body = event.get("input", {})
    img_b64 = body.get("image_b64")
    label_b64 = body.get("label_image_b64")  # optional second photo
    platform = body.get("platform")
    hints = body.get("hints")

    if not img_b64 or platform not in SUPPORTED_PLATFORMS:
        return {"error": f"bad input: image_b64 required, platform must be one of {SUPPORTED_PLATFORMS} (got {platform!r})"}

    try:
        img = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
    except Exception as exc:
        return {"error": f"could not decode image_b64: {type(exc).__name__}: {exc}"}

    label_img = None
    if label_b64:
        try:
            label_img = Image.open(io.BytesIO(base64.b64decode(label_b64))).convert("RGB")
        except Exception as exc:
            return {"error": f"could not decode label_image_b64: {type(exc).__name__}: {exc}"}

    prompt = get_prompt(platform)
    if hints:
        prompt = f"{prompt}\n{hints}"

    inputs = _build_inputs(img, platform, prompt, label_image=label_img)

    # One pass does both jobs: `generate` with `output_hidden_states` runs the
    # prefill once — its last-token hidden state is what the price/sell heads
    # consume — and then decodes the JSON. Avoids a separate forward pass over
    # the same ~1–2K-token prompt (the dominant cost of the request).
    gen = _model.generate(
        **inputs,
        max_new_tokens=MAX_NEW_TOKENS,
        do_sample=False,
        output_hidden_states=True,
        return_dict_in_generate=True,
    )

    # gen.hidden_states: one entry per generated token; [0] is the prefill step,
    # [0][-1] its final layer (shape: batch, prompt_len, hidden), [0, -1, :] the
    # last prompt token — same pooled state the old standalone forward produced.
    hidden_tensor = gen.hidden_states[0][-1][0, -1, :].float().cpu()
    if hidden_tensor.shape != (EXPECTED_HIDDEN_DIM,):
        return {"error": f"unexpected hidden state shape {tuple(hidden_tensor.shape)}, expected ({EXPECTED_HIDDEN_DIM},)"}
    hidden = hidden_tensor.numpy().tolist()

    prompt_tokens = int(inputs["input_ids"].shape[1])
    new_tokens = gen.sequences[0, prompt_tokens:]
    raw_text = _processor.decode(new_tokens, skip_special_tokens=True).strip()
    print(
        f"[infer] platform={platform} prompt_tokens={prompt_tokens} "
        f"new_tokens={int(new_tokens.shape[0])}",
        flush=True,
    )

    return {
        "hidden_state": hidden,
        "raw_text": raw_text,
        "prompt_tokens": prompt_tokens,
        "output_tokens": int(new_tokens.shape[0]),
    }


runpod.serverless.start({"handler": handler})
