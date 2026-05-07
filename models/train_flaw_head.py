"""Train Model #2: visible-flaw MLP head on frozen DINOv2 embeddings.

Default run from repo root:

    python models/train_flaw_head.py \
        --embeddings data/embeddings/dinov2_combined.npy \
        --index data/embeddings/dinov2_combined_index.parquet \
        --output models/checkpoints/flaw_head.pt \
        --metrics eval/results/flaw_head.json

Use ``--sampler weighted`` only as a fallback if default class weighting gives
unstable curves or very poor positive recall.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import (
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)
from torch import nn
from torch.utils.data import DataLoader, TensorDataset, WeightedRandomSampler


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EMBEDDINGS = REPO_ROOT / "data" / "embeddings" / "dinov2_combined.npy"
DEFAULT_INDEX = REPO_ROOT / "data" / "embeddings" / "dinov2_combined_index.parquet"
DEFAULT_OUTPUT = REPO_ROOT / "models" / "checkpoints" / "flaw_head.pt"
DEFAULT_METRICS = REPO_ROOT / "eval" / "results" / "flaw_head.json"
SEED = 42
THRESHOLD = 0.5


class FlawHead(nn.Module):
    def __init__(self, input_dim: int = 768, hidden_dim: int = 256, dropout: float = 0.2):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


@dataclass
class SplitMetrics:
    auc: float
    precision: float
    recall: float
    f1: float
    confusion_matrix: list[list[int]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--patience", type=int, default=8)
    parser.add_argument("--hidden-dim", type=int, default=256)
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument(
        "--platform-filter",
        choices=["all", "vinted", "kleinanzeigen"],
        default="all",
        help="Optional platform-specific training/eval subset for quick diagnostics.",
    )
    parser.add_argument(
        "--sampler",
        choices=["none", "weighted"],
        default="none",
        help="Optional WeightedRandomSampler fallback. Default uses pos_weight instead.",
    )
    parser.add_argument(
        "--device",
        choices=["auto", "cuda", "mps", "cpu"],
        default="auto",
    )
    return parser.parse_args()


def choose_device(requested: str) -> torch.device:
    if requested != "auto":
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def set_seed(seed: int = SEED) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def load_inputs(embeddings_path: Path, index_path: Path) -> tuple[np.ndarray, pd.DataFrame]:
    embeddings = np.load(embeddings_path)
    index = pd.read_parquet(index_path)

    required = ["platform", "id", "split", "condition_en", "flaw_label"]
    missing = [col for col in required if col not in index.columns]
    if missing:
        raise ValueError(f"Index file missing required columns: {missing}")
    if len(index) != len(embeddings):
        raise ValueError(
            f"Index rows ({len(index):,}) != embedding rows ({len(embeddings):,})"
        )
    if embeddings.ndim != 2 or embeddings.shape[1] != 768:
        raise ValueError(f"Expected embeddings shape [N, 768], got {embeddings.shape}")
    duplicate_keys = index.duplicated(["platform", "id"]).sum()
    if duplicate_keys:
        raise ValueError(f"Found {duplicate_keys} duplicate (platform, id) rows")
    expected_splits = {"train", "val", "test"}
    bad_splits = set(index["split"]) - expected_splits
    if bad_splits:
        raise ValueError(f"Unexpected split labels: {sorted(bad_splits)}")
    bad_labels = set(index["flaw_label"].dropna().astype(int)) - {0, 1}
    if bad_labels:
        raise ValueError(f"flaw_label must be binary, found {sorted(bad_labels)}")

    return embeddings.astype("float32"), index


def make_dataset(
    embeddings: np.ndarray,
    labels: np.ndarray,
    row_mask: np.ndarray,
) -> TensorDataset:
    x = torch.from_numpy(embeddings[row_mask])
    y = torch.from_numpy(labels[row_mask].astype("float32"))
    return TensorDataset(x, y)


def make_train_loader(
    dataset: TensorDataset,
    labels: np.ndarray,
    batch_size: int,
    sampler_mode: str,
) -> DataLoader:
    if sampler_mode == "none":
        return DataLoader(dataset, batch_size=batch_size, shuffle=True)

    class_counts = np.bincount(labels.astype(int), minlength=2)
    if class_counts.min() == 0:
        raise ValueError(f"Cannot build weighted sampler with class counts {class_counts}")
    class_weights = 1.0 / class_counts
    sample_weights = class_weights[labels.astype(int)]
    sampler = WeightedRandomSampler(
        weights=torch.as_tensor(sample_weights, dtype=torch.double),
        num_samples=len(sample_weights),
        replacement=True,
    )
    return DataLoader(dataset, batch_size=batch_size, sampler=sampler)


@torch.no_grad()
def predict(model: nn.Module, loader: DataLoader, device: torch.device) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    logits_chunks: list[np.ndarray] = []
    labels_chunks: list[np.ndarray] = []
    for x, y in loader:
        x = x.to(device)
        logits = model(x).detach().cpu().numpy()
        logits_chunks.append(logits)
        labels_chunks.append(y.numpy())
    logits_all = np.concatenate(logits_chunks)
    labels_all = np.concatenate(labels_chunks).astype(int)
    probs = 1.0 / (1.0 + np.exp(-logits_all))
    return probs, labels_all


def compute_metrics(probs: np.ndarray, labels: np.ndarray, threshold: float = THRESHOLD) -> SplitMetrics:
    preds = (probs >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels,
        preds,
        average="binary",
        zero_division=0,
    )
    try:
        auc = float(roc_auc_score(labels, probs))
    except ValueError:
        auc = float("nan")
    cm = confusion_matrix(labels, preds, labels=[0, 1]).astype(int).tolist()
    return SplitMetrics(
        auc=float(auc),
        precision=float(precision),
        recall=float(recall),
        f1=float(f1),
        confusion_matrix=cm,
    )


def train(args: argparse.Namespace) -> dict:
    set_seed(SEED)
    device = choose_device(args.device)
    print(f"Using device: {device}")

    embeddings, index = load_inputs(args.embeddings, args.index)
    if args.platform_filter != "all":
        keep = index["platform"].eq(args.platform_filter).to_numpy()
        embeddings = embeddings[keep]
        index = index.loc[keep].reset_index(drop=True)
        print(f"Platform filter active: {args.platform_filter} ({len(index):,} rows)")

    labels = index["flaw_label"].to_numpy(dtype=np.int64)

    train_mask = index["split"].eq("train").to_numpy()
    val_mask = index["split"].eq("val").to_numpy()
    test_mask = index["split"].eq("test").to_numpy()
    if not (train_mask.any() and val_mask.any() and test_mask.any()):
        raise ValueError("Expected non-empty train, val, and test splits")

    train_labels = labels[train_mask]
    train_pos = int(train_labels.sum())
    train_neg = int(len(train_labels) - train_pos)
    if train_pos == 0 or train_neg == 0:
        raise ValueError(f"Train split needs both classes, got pos={train_pos}, neg={train_neg}")

    train_ds = make_dataset(embeddings, labels, train_mask)
    val_ds = make_dataset(embeddings, labels, val_mask)
    test_ds = make_dataset(embeddings, labels, test_mask)

    train_loader = make_train_loader(
        train_ds,
        labels=train_labels,
        batch_size=args.batch_size,
        sampler_mode=args.sampler,
    )
    eval_batch_size = max(args.batch_size, 512)
    val_loader = DataLoader(val_ds, batch_size=eval_batch_size, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=eval_batch_size, shuffle=False)

    model = FlawHead(hidden_dim=args.hidden_dim, dropout=args.dropout).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=args.lr,
        weight_decay=args.weight_decay,
    )

    if args.sampler == "weighted":
        pos_weight_value = 1.0
        print("Using WeightedRandomSampler; pos_weight is set to 1.0")
    else:
        pos_weight_value = train_neg / train_pos
        print(f"Using BCEWithLogitsLoss pos_weight={pos_weight_value:.4f}")

    criterion = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor(pos_weight_value, dtype=torch.float32, device=device)
    )

    best_state = None
    best_val_auc = -float("inf")
    best_epoch = 0
    stale_epochs = 0
    history: list[dict] = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        train_losses: list[float] = []
        for x, y in train_loader:
            x = x.to(device)
            y = y.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(x)
            loss = criterion(logits, y)
            loss.backward()
            optimizer.step()
            train_losses.append(float(loss.detach().cpu()))

        val_probs, val_labels = predict(model, val_loader, device)
        val_metrics = compute_metrics(val_probs, val_labels)
        mean_loss = float(np.mean(train_losses))
        history_row = {
            "epoch": epoch,
            "train_loss": mean_loss,
            "val_auc": val_metrics.auc,
            "val_precision": val_metrics.precision,
            "val_recall": val_metrics.recall,
            "val_f1": val_metrics.f1,
        }
        history.append(history_row)
        print(
            f"epoch={epoch:03d} loss={mean_loss:.4f} "
            f"val_auc={val_metrics.auc:.4f} val_f1={val_metrics.f1:.4f} "
            f"val_recall={val_metrics.recall:.4f}"
        )

        if val_metrics.auc > best_val_auc:
            best_val_auc = val_metrics.auc
            best_epoch = epoch
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= args.patience:
                print(f"Early stopping after {epoch} epochs; best epoch was {best_epoch}")
                break

    if best_state is None:
        raise RuntimeError("Training finished without a best model state")
    model.load_state_dict(best_state)

    val_probs, val_labels = predict(model, val_loader, device)
    test_probs, test_labels = predict(model, test_loader, device)
    val_metrics = compute_metrics(val_probs, val_labels)
    test_metrics = compute_metrics(test_probs, test_labels)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "model_state_dict": model.state_dict(),
        "model_config": {
            "input_dim": 768,
            "hidden_dim": args.hidden_dim,
            "dropout": args.dropout,
        },
        "threshold": THRESHOLD,
        "label_definition": "flaw_label = 1 if condition_en == 'Good', else 0",
        "best_epoch": best_epoch,
        "best_val_auc": best_val_auc,
    }
    torch.save(checkpoint, args.output)

    split_counts = index["split"].value_counts().sort_index().to_dict()
    class_balance = {
        split: {
            "positive": int(index.loc[index["split"].eq(split), "flaw_label"].sum()),
            "negative": int(index["split"].eq(split).sum() - index.loc[index["split"].eq(split), "flaw_label"].sum()),
        }
        for split in ("train", "val", "test")
    }
    metrics = {
        "model": "dinov2_base_mlp_flaw_head",
        "label_definition": checkpoint["label_definition"],
        "threshold": THRESHOLD,
        "platform_filter": args.platform_filter,
        "sampler": args.sampler,
        "pos_weight": pos_weight_value,
        "best_epoch": best_epoch,
        "best_val_auc": best_val_auc,
        "split_counts": {key: int(value) for key, value in split_counts.items()},
        "class_balance": class_balance,
        "val": asdict(val_metrics),
        "test": asdict(test_metrics),
        "history": history,
    }

    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    with open(args.metrics, "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"Saved checkpoint: {args.output}")
    print(f"Saved metrics   : {args.metrics}")
    print(
        "Test metrics: "
        f"AUC={test_metrics.auc:.4f}, precision={test_metrics.precision:.4f}, "
        f"recall={test_metrics.recall:.4f}, F1={test_metrics.f1:.4f}"
    )
    return metrics


def main() -> None:
    args = parse_args()
    if args.epochs <= 0:
        raise ValueError("--epochs must be positive")
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")
    train(args)


if __name__ == "__main__":
    main()
