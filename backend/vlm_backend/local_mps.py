"""In-process Qwen3-VL-4B + LoRA backend for local Mac dev.

fp16 on MPS, no quantisation. bitsandbytes is CUDA-focused and MLX-style
Apple-Silicon quantisation is out of scope for a 7-day project. Latency on
M-series MPS: roughly 8-15s per /upload (forward + generate, twice — once per
platform — serialising on the single MPS device).

Two passes per call (forward + generate) because we need both the prefill
last-token hidden state (for the price head) and the generated JSON. The
single-pass `generate(..., output_hidden_states=True)` form returns hidden
states per generation step, and slicing the prefill is fiddly enough that
two passes is the safer prototype path.

If transformers 5.x breaks the Qwen3-VL load (the pod used 4.57; locally
we're on 5.8), downgrade with: ``uv pip install --no-deps 'transformers>=4.57,<5'``.
"""

from __future__ import annotations

import asyncio
import os

import torch
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError
from peft import PeftModel
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor

# backend/__init__.py adds repo/models and repo/src to sys.path.
from extract_features import choose_device
from extract_vlm_features import DEFAULT_ADAPTER, DEFAULT_BASE_MODEL, build_inputs
from prompts import EXPECTED_HIDDEN_DIM, get_prompt

from . import VLMOutput
from .util import parse_json_lenient


MAX_NEW_TOKENS = 256
RECOMMENDED_MIN_MEMORY_GB = 12


def _check_memory(device: torch.device) -> None:
    if device.type != "mps" or not hasattr(torch.mps, "recommended_max_memory"):
        return
    gb_avail = torch.mps.recommended_max_memory() / (1024 ** 3)
    if gb_avail < RECOMMENDED_MIN_MEMORY_GB:
        print(
            f"WARNING: MPS recommended_max_memory={gb_avail:.1f} GB is below the "
            f"recommended {RECOMMENDED_MIN_MEMORY_GB} GB. Loading may swap or OOM."
        )


class LocalMPSVLM:
    name = "local_mps"

    def __init__(
        self,
        base_model: str = DEFAULT_BASE_MODEL,
        adapter_id: str = DEFAULT_ADAPTER,
        device_pref: str = "auto",
        torch_dtype: torch.dtype = torch.float16,
    ):
        self.base_model = base_model
        self.adapter_id = adapter_id
        self.device = choose_device(device_pref)
        self.torch_dtype = torch_dtype
        self.processor = None
        self.model = None

    async def warmup(self) -> None:
        """Idempotent eager load. First run downloads ~8 GB from HF (~5-15 min)."""
        if self.model is not None:
            return
        await asyncio.to_thread(self._load)

    def _load(self) -> None:
        _check_memory(self.device)
        token = os.environ.get("HF_TOKEN")
        try:
            processor = AutoProcessor.from_pretrained(
                self.base_model, trust_remote_code=True, token=token
            )
            base = AutoModelForImageTextToText.from_pretrained(
                self.base_model,
                trust_remote_code=True,
                torch_dtype=self.torch_dtype,
                device_map={"": self.device},
                token=token,
            )
            model = PeftModel.from_pretrained(base, self.adapter_id, token=token)
            model.eval()
        except GatedRepoError as exc:
            raise RuntimeError(
                f"HF gated-repo error loading {self.base_model}. "
                "Run `huggingface-cli login` and accept access at "
                f"https://huggingface.co/{self.base_model}"
            ) from exc
        except HfHubHTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status == 401:
                raise RuntimeError(
                    f"HF auth (401) loading {self.base_model}. Run `huggingface-cli login`."
                ) from exc
            raise

        # Commit to self only after every step succeeded so a failed reload doesn't
        # leave a partially populated instance behind.
        self.processor = processor
        self.model = model
        print(f"LocalMPSVLM loaded {self.base_model} + {self.adapter_id} on {self.device}")

    @torch.no_grad()
    def _predict_sync(self, image: Image.Image, platform: str, hints: str | None) -> VLMOutput:
        if self.model is None:
            raise RuntimeError("LocalMPSVLM.warmup() must be awaited before predict()")
        prompt = get_prompt(platform)
        if hints:
            prompt = f"{prompt}\n{hints}"
        inputs = build_inputs(self.processor, image, platform, self.device, prompt=prompt)

        out = self.model(**inputs, output_hidden_states=True, return_dict=True)
        hidden = out.hidden_states[-1][0, -1, :].float().cpu().numpy()
        if hidden.shape != (EXPECTED_HIDDEN_DIM,):
            raise RuntimeError(
                f"LocalMPSVLM hidden_state shape {hidden.shape}, expected ({EXPECTED_HIDDEN_DIM},)"
            )

        gen = self.model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False)
        new_tokens = gen[0, inputs["input_ids"].shape[1]:]
        raw_text = self.processor.decode(new_tokens, skip_special_tokens=True).strip()

        return VLMOutput(
            hidden_state=hidden,
            fields=parse_json_lenient(raw_text),
            raw_text=raw_text,
        )

    async def predict(self, image: Image.Image, platform: str, hints: str | None = None) -> VLMOutput:
        return await asyncio.to_thread(self._predict_sync, image, platform, hints)
