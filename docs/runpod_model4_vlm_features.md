# RunPod: Extract VLM Features For Model #4

This is the expensive feature-caching step. It produces one pooled Qwen vector
per listing for the Model #4 price head.

## 1. Start A Pod

Recommended GPU: RTX 4090 or A100. Use a PyTorch image with CUDA.

## 2. Clone And Install

```bash
git clone https://github.com/mchlkan/Advanced_ML.git
cd Advanced_ML
pip install -r requirements.txt
pip install -U transformers accelerate peft bitsandbytes huggingface_hub pandas pyarrow pillow tqdm
huggingface-cli login
```

Accept access to both Hugging Face repos before logging in:

- `Qwen/Qwen3-VL-4B-Instruct`
- `Rengo33/qwen3vl4b-resell-adapter`

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
