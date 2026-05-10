# Production image for the Resell Copilot FastAPI backend.
# DINOv2 + the 3 head MLPs run inside this container; the VLM (Qwen3-VL)
# itself runs on RunPod Serverless and is reached via httpx.

FROM python:3.11-slim

WORKDIR /app

# System deps:
#   libjpeg62-turbo, zlib1g — Pillow runtime
#   libgomp1               — torch runtime (OpenMP)
#   gcc, python3-dev       — only needed for some pip wheels; purged after install
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo zlib1g libgomp1 \
        gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .

# CPU-only torch wheel from PyTorch's index, NOT the default PyPI one which
# bundles ~1.5 GB of CUDA libs (cuDNN, NCCL, etc) we can't use on a CPU box.
# Install torch first so the rest of the requirements skip it.
RUN pip install --no-cache-dir torch>=2.3.0 \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements-prod.txt

# Drop the build toolchain to keep the image smaller.
RUN apt-get purge -y gcc python3-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Application code is bind-mounted at runtime, not baked in. The container
# expects /app/{backend,shared,models} to be mounted from the host's git
# checkout. See scripts/ec2_rebuild.sh for the canonical run flags and
# docs/deploy_plan.md §5.6 for the rationale (code-only deploys become
# `git pull && docker restart` instead of a full rebuild).
RUN mkdir -p /app/backend /app/shared /app/models /app/data/uploads

ENV PYTHONUNBUFFERED=1
# Keep DINOv2 weights inside the persistent volume so they're cached
# across container restarts.
ENV HF_HOME=/app/data/.huggingface

EXPOSE 8000

# nginx upstream check + Docker healthcheck both hit /health (no model state read).
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=5).raise_for_status()" || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
