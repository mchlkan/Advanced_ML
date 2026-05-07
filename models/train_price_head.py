"""Train Model #4: quantile price head with pinball loss.

Requires:
  - data/embeddings/vlm_pooled_combined.npy
  - data/features/price_features_combined.parquet
  - data/features/price_feature_vocab.json

Default:

    python models/train_price_head.py

Ablation without Model #2:

    python models/train_price_head.py --no-flaw \
        --output models/checkpoints/price_head_no_flaw.pt \
        --metrics eval/results/price_head_no_flaw.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VLM = REPO_ROOT / "data" / "embeddings" / "vlm_pooled_combined.npy"
DEFAULT_FEATURES = REPO_ROOT / "data" / "features" / "price_features_combined.parquet"
DEFAULT_VOCAB = REPO_ROOT / "data" / "features" / "price_feature_vocab.json"
DEFAULT_OUTPUT = REPO_ROOT / "models" / "checkpoints" / "price_head.pt"
DEFAULT_METRICS = REPO_ROOT / "eval" / "results" / "price_head.json"

SEED = 42
QUANTILES = torch.tensor([0.10, 0.25, 0.50, 0.75, 0.90], dtype=torch.float32)


class PriceDataset(Dataset):
    def __init__(self, vlm: np.ndarray, features: pd.DataFrame, mask: np.ndarray, no_flaw: bool):
        self.vlm = torch.from_numpy(np.asarray(vlm[mask], dtype=np.float32).copy())
        sub = features.loc[mask].reset_index(drop=True)
        numeric_cols = ["tag_proxy"]
        if not no_flaw:
            numeric_cols.insert(0, "visual_wear_probability")
        self.numeric = torch.from_numpy(sub[numeric_cols].to_numpy(dtype=np.float32).copy())
        self.platform = torch.from_numpy(sub["platform_idx"].to_numpy(dtype=np.int64).copy())
        self.category = torch.from_numpy(sub["category_idx"].to_numpy(dtype=np.int64).copy())
        self.condition = torch.from_numpy(sub["condition_idx"].to_numpy(dtype=np.int64).copy())
        self.brand = torch.from_numpy(sub["brand_idx"].to_numpy(dtype=np.int64).copy())
        self.y = torch.from_numpy(sub["log_price"].to_numpy(dtype=np.float32).copy())

    def __len__(self) -> int:
        return len(self.y)

    def __getitem__(self, idx: int):
        return {
            "vlm": self.vlm[idx],
            "numeric": self.numeric[idx],
            "platform": self.platform[idx],
            "category": self.category[idx],
            "condition": self.condition[idx],
            "brand": self.brand[idx],
            "target": self.y[idx],
        }


class PriceHead(nn.Module):
    def __init__(
        self,
        vlm_dim: int,
        numeric_dim: int,
        n_platforms: int,
        n_categories: int,
        n_conditions: int,
        n_brands: int,
        brand_dim: int = 32,
        hidden_dim: int = 512,
        dropout: float = 0.2,
    ):
        super().__init__()
        self.brand_embedding = nn.Embedding(n_brands, brand_dim)
        input_dim = vlm_dim + numeric_dim + n_platforms + n_categories + n_conditions + brand_dim
        self.n_platforms = n_platforms
        self.n_categories = n_categories
        self.n_conditions = n_conditions
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 256),
            nn.ReLU(),
            nn.Linear(256, len(QUANTILES)),
        )

    def forward(self, batch: dict[str, torch.Tensor]) -> torch.Tensor:
        platform_oh = nn.functional.one_hot(batch["platform"], self.n_platforms).float()
        category_oh = nn.functional.one_hot(batch["category"], self.n_categories).float()
        condition_oh = nn.functional.one_hot(batch["condition"], self.n_conditions).float()
        brand_emb = self.brand_embedding(batch["brand"])
        x = torch.cat(
            [batch["vlm"], batch["numeric"], platform_oh, category_oh, condition_oh, brand_emb],
            dim=1,
        )
        return self.net(x)


@dataclass
class GroupMetrics:
    n: int
    mae: float
    mape: float | None
    mape_n: int
    rmsle: float
    coverage_q10_q90: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vlm-embeddings", type=Path, default=DEFAULT_VLM)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--vocab", type=Path, default=DEFAULT_VOCAB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--hidden-dim", type=int, default=512)
    parser.add_argument("--brand-dim", type=int, default=32)
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument("--no-flaw", action="store_true", help="Ablation: remove visual_wear_probability.")
    parser.add_argument("--device", choices=["auto", "cuda", "mps", "cpu"], default="auto")
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


def pinball_loss(pred: torch.Tensor, target: torch.Tensor, quantiles: torch.Tensor) -> torch.Tensor:
    errors = target.unsqueeze(1) - pred
    q = quantiles.to(pred.device).view(1, -1)
    return torch.maximum(q * errors, (q - 1) * errors).mean()


def load_inputs(vlm_path: Path, features_path: Path, vocab_path: Path):
    vlm = np.load(vlm_path, mmap_mode="r")
    features = pd.read_parquet(features_path)
    with open(vocab_path) as f:
        vocab = json.load(f)
    if len(vlm) != len(features):
        raise ValueError(f"VLM rows ({len(vlm):,}) != feature rows ({len(features):,})")
    if not (features["row_idx"].to_numpy() == np.arange(len(features))).all():
        raise ValueError("Feature row_idx must align with VLM row order")
    return vlm, features, vocab


def move_batch(batch: dict[str, torch.Tensor], device: torch.device) -> dict[str, torch.Tensor]:
    return {k: v.to(device) for k, v in batch.items()}


@torch.no_grad()
def predict(model: nn.Module, loader: DataLoader, device: torch.device) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    preds, targets = [], []
    for batch in loader:
        batch = move_batch(batch, device)
        pred = model(batch).detach().cpu().numpy()
        preds.append(pred)
        targets.append(batch["target"].detach().cpu().numpy())
    return np.concatenate(preds, axis=0), np.concatenate(targets, axis=0)


def compute_group_metrics(pred_log_q: np.ndarray, y_log: np.ndarray) -> GroupMetrics:
    pred_log_q = np.sort(pred_log_q, axis=1)
    q10_log = pred_log_q[:, 0]
    q50_log = pred_log_q[:, 2]
    q90_log = pred_log_q[:, 4]
    pred_price = np.expm1(q50_log).clip(min=0)
    true_price = np.expm1(y_log).clip(min=0)
    mae = float(np.mean(np.abs(pred_price - true_price)))
    nonzero = true_price > 0
    mape = None
    if nonzero.any():
        mape = float(np.mean(np.abs(pred_price[nonzero] - true_price[nonzero]) / true_price[nonzero]))
    rmsle = float(np.sqrt(np.mean((np.log1p(pred_price) - np.log1p(true_price)) ** 2)))
    coverage = float(np.mean((y_log >= q10_log) & (y_log <= q90_log)))
    return GroupMetrics(
        n=int(len(y_log)),
        mae=mae,
        mape=mape,
        mape_n=int(nonzero.sum()),
        rmsle=rmsle,
        coverage_q10_q90=coverage,
    )


def metrics_by_group(pred: np.ndarray, y: np.ndarray, features: pd.DataFrame, mask: np.ndarray) -> dict:
    sub = features.loc[mask].reset_index(drop=True)
    out = {"overall": asdict(compute_group_metrics(pred, y))}
    for group_name, cols in {
        "by_platform": ["platform"],
        "by_category": ["category_en"],
        "by_platform_category": ["platform", "category_en"],
    }.items():
        group_metrics = {}
        groupby_key = cols[0] if len(cols) == 1 else cols
        for key, idx in sub.groupby(groupby_key, sort=True).groups.items():
            key_str = key if isinstance(key, str) else " | ".join(map(str, key))
            rows = np.fromiter(idx, dtype=np.int64)
            group_metrics[key_str] = asdict(compute_group_metrics(pred[rows], y[rows]))
        out[group_name] = group_metrics
    return out


def train(args: argparse.Namespace) -> dict:
    set_seed(SEED)
    device = choose_device(args.device)
    print(f"Using device: {device}")

    vlm, features, vocab = load_inputs(args.vlm_embeddings, args.features, args.vocab)
    train_mask = features["split"].eq("train").to_numpy()
    val_mask = features["split"].eq("val").to_numpy()
    test_mask = features["split"].eq("test").to_numpy()

    train_ds = PriceDataset(vlm, features, train_mask, no_flaw=args.no_flaw)
    val_ds = PriceDataset(vlm, features, val_mask, no_flaw=args.no_flaw)
    test_ds = PriceDataset(vlm, features, test_mask, no_flaw=args.no_flaw)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False)

    model = PriceHead(
        vlm_dim=int(vlm.shape[1]),
        numeric_dim=1 if args.no_flaw else 2,
        n_platforms=len(vocab["platform"]),
        n_categories=len(vocab["category_en"]),
        n_conditions=len(vocab["condition_en"]),
        n_brands=len(vocab["brand_canon"]),
        brand_dim=args.brand_dim,
        hidden_dim=args.hidden_dim,
        dropout=args.dropout,
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    best_state = None
    best_val_loss = float("inf")
    best_epoch = 0
    stale = 0
    history = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for batch in train_loader:
            batch = move_batch(batch, device)
            optimizer.zero_grad(set_to_none=True)
            pred = model(batch)
            loss = pinball_loss(pred, batch["target"], QUANTILES)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))

        val_pred, val_y = predict(model, val_loader, device)
        val_loss = float(pinball_loss(
            torch.from_numpy(val_pred),
            torch.from_numpy(val_y),
            QUANTILES,
        ))
        row = {"epoch": epoch, "train_loss": float(np.mean(losses)), "val_pinball": val_loss}
        history.append(row)
        print(f"epoch={epoch:03d} train_loss={row['train_loss']:.4f} val_pinball={val_loss:.4f}")

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_epoch = epoch
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= args.patience:
                print(f"Early stopping after {epoch}; best epoch was {best_epoch}")
                break

    if best_state is None:
        raise RuntimeError("Training did not produce a best checkpoint")
    model.load_state_dict(best_state)

    val_pred, val_y = predict(model, val_loader, device)
    test_pred, test_y = predict(model, test_loader, device)
    metrics = {
        "model": "price_quantile_head",
        "quantiles": QUANTILES.tolist(),
        "target": "log(price + 1)",
        "uses_visual_wear_probability": not args.no_flaw,
        "best_epoch": best_epoch,
        "best_val_pinball": best_val_loss,
        "split_counts": {k: int(v) for k, v in features["split"].value_counts().sort_index().items()},
        "val": metrics_by_group(val_pred, val_y, features, val_mask),
        "test": metrics_by_group(test_pred, test_y, features, test_mask),
        "history": history,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "model_config": {
                "vlm_dim": int(vlm.shape[1]),
                "numeric_dim": 1 if args.no_flaw else 2,
                "n_platforms": len(vocab["platform"]),
                "n_categories": len(vocab["category_en"]),
                "n_conditions": len(vocab["condition_en"]),
                "n_brands": len(vocab["brand_canon"]),
                "brand_dim": args.brand_dim,
                "hidden_dim": args.hidden_dim,
                "dropout": args.dropout,
            },
            "vocab": vocab,
            "quantiles": QUANTILES.tolist(),
            "uses_visual_wear_probability": not args.no_flaw,
        },
        args.output,
    )

    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    with open(args.metrics, "w") as f:
        json.dump(metrics, f, indent=2)

    overall = metrics["test"]["overall"]
    mape_str = "None" if overall["mape"] is None else f"{overall['mape']:.4f}"
    print(f"Saved checkpoint: {args.output}")
    print(f"Saved metrics   : {args.metrics}")
    print(
        "Test overall: "
        f"MAE={overall['mae']:.2f}, "
        f"MAPE={mape_str}, "
        f"RMSLE={overall['rmsle']:.4f}, "
        f"coverage={overall['coverage_q10_q90']:.4f}"
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
