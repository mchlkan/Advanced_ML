# RunPod: Extract VLM Features For Model #4

This is the expensive feature-caching step. It produces one pooled Qwen vector
per listing for the Model #4 price head.

## 1. Start A Pod

Recommended GPU: RTX 4090 or A100. Recommended template:
`runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04` — torch and CUDA
are already paired, so they must not be touched by pip.

Before doing anything else, verify the template is healthy:

```bash
python -c "import torch; print(torch.cuda.is_available())"
```

If this prints `False`, switch templates immediately. Do **not** try to fix
it with pip — that is what the previous session burned 90 min on.

## 2. Clone And Install

```bash
git clone https://github.com/mchlkan/Advanced_ML.git
cd Advanced_ML

# Install only what is missing on a stock pytorch image. Do NOT run
# `pip install -r requirements.txt` and do NOT pass `-U` here — both can
# upgrade torch/transformers and break the template's CUDA pairing.
pip install 'transformers>=4.56,<5' peft bitsandbytes accelerate huggingface_hub gdown
pip install pandas pyarrow pillow

huggingface-cli login
```

Accept access to both Hugging Face repos before logging in:

- `Qwen/Qwen3-VL-4B-Instruct`
- `Rengo33/qwen3vl4b-resell-adapter`

## 2.5. Preflight (mandatory)

```bash
python scripts/preflight.py
```

This verifies torch+CUDA, transformers >= 4.56 (Qwen3-VL needs `qwen3_vl`
model_type, added in 4.56), peft, bitsandbytes, and HF auth. It exits
non-zero with the exact pip command needed if anything is missing.

If transformers is too old, the preflight will tell you to run:

```bash
pip install --no-deps 'transformers>=4.56'
```

`--no-deps` is essential — it prevents pip from cascading into a torch
upgrade. Re-run preflight until everything passes.

## 3. Upload Data

Copy these files into `data/` on the pod:

```text
data/vinted_clothing_combined.parquet
data/kleinanzeigen_clothing_combined.parquet
data/splits/train_ids.json
data/splits/val_ids.json
data/splits/test_ids.json
```

The split JSONs come from git; the two combined parquets are local/Drive only.

## 4. Smoke Test

```bash
python models/extract_vlm_features.py \
  --adapter-id Rengo33/qwen3vl4b-resell-adapter \
  --load-in-4bit \
  --limit 5
```

Expected:

```text
shape=(5, 2560)
first 8 = [...]
```

## 5. Full Extraction

```bash
python models/extract_vlm_features.py \
  --adapter-id Rengo33/qwen3vl4b-resell-adapter \
  --load-in-4bit \
  --resume
```

Outputs:

```text
data/embeddings/vlm_pooled_combined.npy
data/embeddings/vlm_pooled_combined_index.parquet
```

If the pod disconnects, rerun the same command with `--resume`.

## 6. Bring Files Back

Download/copy both outputs back to the local repo at the same paths. Then run:

```bash
python models/build_price_dataset.py
python models/train_price_head.py
python models/train_price_head.py \
  --no-flaw \
  --output models/checkpoints/price_head_no_flaw.pt \
  --metrics eval/results/price_head_no_flaw.json
```
