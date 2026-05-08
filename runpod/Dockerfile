FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/runpod-volume/hf-cache \
    TRANSFORMERS_CACHE=/runpod-volume/hf-cache

WORKDIR /workspace

COPY runpod/requirements.txt /workspace/runpod-requirements.txt
RUN pip install --no-cache-dir -r /workspace/runpod-requirements.txt

# Source files needed at runtime — keep this minimal so rebuilds are fast.
COPY src /workspace/src
COPY models/extract_vlm_features.py /workspace/models/extract_vlm_features.py
COPY runpod/handler.py /workspace/handler.py

CMD ["python", "-u", "/workspace/handler.py"]
