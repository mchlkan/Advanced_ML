"""Export Model #2 visual-wear probabilities for downstream price modeling.

Run from repo root:

    python models/export_flaw_probs.py \
        --checkpoint models/checkpoints/flaw_head_vinted.pt \
        --embeddings data/embeddings/dinov2_combined.npy \
        --index data/embeddings/dinov2_combined_index.parquet \
        --output data/features/flaw_probs_combined.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, TensorDataset

from train_flaw_head import FlawHead, choose_device, load_inputs


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHECKPOINT = REPO_ROOT / "models" / "checkpoints" / "flaw_head_vinted.pt"
DEFAULT_EMBEDDINGS = REPO_ROOT / "data" / "embeddings" / "dinov2_combined.npy"
DEFAULT_INDEX = REPO_ROOT / "data" / "embeddings" / "dinov2_combined_index.parquet"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "features" / "flaw_probs_combined.parquet"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--device", choices=["auto", "cuda", "mps", "cpu"], default="auto")
    return parser.parse_args()


def load_model(checkpoint_path: Path, device: torch.device) -> tuple[FlawHead, dict]:
    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    config = checkpoint["model_config"]
    model = FlawHead(
        input_dim=int(config.get("input_dim", 768)),
        hidden_dim=int(config.get("hidden_dim", 256)),
        dropout=float(config.get("dropout", 0.2)),
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    model.to(device)
    return model, checkpoint


@torch.no_grad()
def predict_probs(
    model: FlawHead,
    embeddings: np.ndarray,
    batch_size: int,
    device: torch.device,
) -> np.ndarray:
    dataset = TensorDataset(torch.from_numpy(embeddings.astype("float32")))
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)
    chunks: list[np.ndarray] = []
    for (x,) in loader:
        logits = model(x.to(device)).detach().cpu().numpy()
        chunks.append(logits)
    logits_all = np.concatenate(chunks)
    return (1.0 / (1.0 + np.exp(-logits_all))).astype("float32")


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")

    device = choose_device(args.device)
    print(f"Using device: {device}")

    embeddings, index = load_inputs(args.embeddings, args.index)
    model, checkpoint = load_model(args.checkpoint, device)
    probs = predict_probs(model, embeddings, args.batch_size, device)

    out = index[["platform", "id", "split", "condition_en", "flaw_label"]].copy()
    out["visual_wear_probability"] = probs
    out["source_checkpoint"] = str(args.checkpoint)

    if len(out) != len(embeddings):
        raise ValueError("Output row count does not match embeddings")
    if out.duplicated(["platform", "id"]).any():
        raise ValueError("Output contains duplicate (platform, id) rows")
    if not out["visual_wear_probability"].between(0, 1).all():
        raise ValueError("Probabilities outside [0, 1]")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.output, index=False)

    print(f"Saved flaw probabilities: {args.output}  rows={len(out):,}")
    print(f"Checkpoint best epoch: {checkpoint.get('best_epoch')}")
    print("Split counts:")
    print(out["split"].value_counts().sort_index().to_string())
    print("Mean visual_wear_probability by platform:")
    print(out.groupby("platform")["visual_wear_probability"].mean().round(4).to_string())


if __name__ == "__main__":
    main()
