"""Verify the pod is ready for VLM feature extraction.

Run before any other command on a fresh pod. Exits non-zero on any failure
with the exact pip command needed to fix it.

    python scripts/preflight.py
"""

from __future__ import annotations

import sys


CHECKS: list[tuple[str, callable]] = []


def check(name: str):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


@check("Python >= 3.10")
def py():
    v = sys.version_info
    if v < (3, 10):
        raise AssertionError(f"Python {v.major}.{v.minor} too old (need 3.10+)")
    return f"{v.major}.{v.minor}.{v.micro}"


@check("torch + CUDA")
def torch_cuda():
    import torch

    if not torch.cuda.is_available():
        raise AssertionError(
            "torch.cuda.is_available() is False. The pod template's torch+CUDA "
            "pairing is broken. Switch to a different template — DO NOT pip-install "
            "torch. Recommended: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"
        )
    return f"torch {torch.__version__}, CUDA {torch.version.cuda}, GPU {torch.cuda.get_device_name(0)}"


@check("transformers >= 4.56 (Qwen3-VL support)")
def transformers_version():
    import transformers

    parts = transformers.__version__.split(".")
    major_minor = (int(parts[0]), int(parts[1]))
    if major_minor < (4, 56):
        raise AssertionError(
            f"transformers {transformers.__version__} is too old for Qwen3-VL "
            "(model_type='qwen3_vl' was added in 4.56). Run:\n"
            "    pip install --no-deps 'transformers>=4.56'\n"
            "Use --no-deps so it does not pull in a torch upgrade."
        )
    return transformers.__version__


@check("transformers imports used by extract_vlm_features.py")
def transformers_imports():
    from transformers import (  # noqa: F401
        AutoModelForImageTextToText,
        AutoProcessor,
        BitsAndBytesConfig,
    )
    return "ok"


@check("peft")
def peft_import():
    import peft

    return peft.__version__


@check("bitsandbytes (CUDA build)")
def bnb_import():
    import bitsandbytes as bnb

    return bnb.__version__


@check("pandas + pyarrow + pillow (parquet + image IO)")
def data_libs():
    import pandas as pd
    import pyarrow  # noqa: F401
    from PIL import Image  # noqa: F401

    return f"pandas {pd.__version__}"


@check("huggingface_hub auth")
def hf_auth():
    from huggingface_hub import whoami

    try:
        info = whoami()
    except Exception as e:
        raise AssertionError(
            f"Not logged into Hugging Face ({type(e).__name__}). Run: huggingface-cli login\n"
            "Then accept access to Qwen/Qwen3-VL-4B-Instruct and Rengo33/qwen3vl4b-resell-adapter."
        )
    return info.get("name", "<authenticated>")


def main() -> int:
    print("=" * 60)
    print("Resell Copilot pod preflight")
    print("=" * 60)
    failed: list[str] = []
    for name, fn in CHECKS:
        try:
            result = fn()
            print(f"  [PASS] {name}: {result}")
        except AssertionError as e:
            print(f"  [FAIL] {name}")
            for line in str(e).splitlines():
                print(f"         {line}")
            failed.append(name)
        except Exception as e:
            print(f"  [FAIL] {name}: {type(e).__name__}: {e}")
            failed.append(name)
    print("=" * 60)
    if failed:
        print(f"FAIL: {len(failed)} check(s) failed: {', '.join(failed)}")
        print("Fix the above before running models/extract_vlm_features.py")
        return 1
    print("PASS: pod is ready. Safe to run models/extract_vlm_features.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
