"""Train Model #5: Vinted-only sell-likelihood head with BCE loss.

Predicts ``state == 'sold'`` within the ~8-day scrape window. Trains on
Vinted only (KA has no ground-truth sold marker). Drops the small
hidden/reserved/error rows whose semantics are ambiguous.

Requires:
  - data/embeddings/vlm_pooled_combined.npy
  - data/features/price_features_combined.parquet
  - data/features/price_feature_vocab.json
  - data/vinted_clothing_combined.parquet  (for the ``state`` column)

Default:

    python models/train_sell_head.py

Ablation without Model #2:

    python models/train_sell_head.py --no-flaw \\
        --output models/checkpoints/sell_head_no_flaw.pt \\
        --metrics eval/results/sell_head_no_flaw.json
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
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from torch import nn
from torch.utils.data import DataLoader, Dataset


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VLM = REPO_ROOT / "data" / "embeddings" / "vlm_pooled_combined.npy"
DEFAULT_FEATURES = REPO_ROOT / "data" / "features" / "price_features_combined.parquet"
DEFAULT_VOCAB = REPO_ROOT / "data" / "features" / "price_feature_vocab.json"
DEFAULT_VINTED = REPO_ROOT / "data" / "vinted_clothing_combined.parquet"
DEFAULT_OUTPUT = REPO_ROOT / "models" / "checkpoints" / "sell_head.pt"
DEFAULT_METRICS = REPO_ROOT / "eval" / "results" / "sell_head.json"

SEED = 42
KEEP_STATES = {"sold", "active", "delisted"}


class SellDataset(Dataset):
    def __init__(self, vlm: np.ndarray, features: pd.DataFrame, mask: np.ndarray, no_flaw: bool, no_vlm: bool):
        if no_vlm:
            self.vlm = torch.zeros((int(mask.sum()), 0), dtype=torch.float32)
        else:
            self.vlm = torch.from_numpy(np.asarray(vlm[mask], dtype=np.float32).copy())
        sub = features.loc[mask].reset_index(drop=True)
        numeric_cols = ["tag_proxy", "log_price"]
        if not no_flaw:
            numeric_cols.insert(0, "visual_wear_probability")
        self.numeric = torch.from_numpy(sub[numeric_cols].to_numpy(dtype=np.float32).copy())
        self.category = torch.from_numpy(sub["category_idx"].to_numpy(dtype=np.int64).copy())
        self.condition = torch.from_numpy(sub["condition_idx"].to_numpy(dtype=np.int64).copy())
        self.brand = torch.from_numpy(sub["brand_idx"].to_numpy(dtype=np.int64).copy())
        self.y = torch.from_numpy(sub["sold_label"].to_numpy(dtype=np.float32).copy())

    def __len__(self) -> int:
        return len(self.y)

    def __getitem__(self, idx: int):
        return {
            "vlm": self.vlm[idx],
            "numeric": self.numeric[idx],
            "category": self.category[idx],
            "condition": self.condition[idx],
            "brand": self.brand[idx],
            "target": self.y[idx],
        }


class SellHead(nn.Module):
    def __init__(
        self,
        vlm_dim: int,
        numeric_dim: int,
        n_categories: int,
        n_conditions: int,
        n_brands: int,
        brand_dim: int = 32,
        hidden_dim: int = 512,
        dropout: float = 0.2,
    ):
        super().__init__()
        self.brand_embedding = nn.Embedding(n_brands, brand_dim)
        self.n_categories = n_categories
        self.n_conditions = n_conditions
        input_dim = vlm_dim + numeric_dim + n_categories + n_conditions + brand_dim
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 1),
        )

    def forward(self, batch: dict[str, torch.Tensor]) -> torch.Tensor:
        category_oh = nn.functional.one_hot(batch["category"], self.n_categories).float()
        condition_oh = nn.functional.one_hot(batch["condition"], self.n_conditions).float()
        brand_emb = self.brand_embedding(batch["brand"])
        x = torch.cat([batch["vlm"], batch["numeric"], category_oh, condition_oh, brand_emb], dim=1)
        return self.net(x).squeeze(-1)


@dataclass
class GroupMetrics:
    n: int
    pos_rate: float
    auc: float | None
    pr_auc: float | None
    precision: float
    recall: float
    f1: float
    brier: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vlm-embeddings", type=Path, default=DEFAULT_VLM)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--vocab", type=Path, default=DEFAULT_VOCAB)
    parser.add_argument("--vinted-path", type=Path, default=DEFAULT_VINTED)
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
    parser.add_argument("--no-vlm", action="store_true", help="Ablation: drop VLM features, metadata only.")
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


def load_inputs(vlm_path: Path, features_path: Path, vocab_path: Path, vinted_path: Path):
    vlm_full = np.load(vlm_path, mmap_mode="r")
    features = pd.read_parquet(features_path)
    with open(vocab_path) as f:
        vocab = json.load(f)
    if len(vlm_full) != len(features):
        raise ValueError(f"VLM rows ({len(vlm_full):,}) != feature rows ({len(features):,})")
    if not (features["row_idx"].to_numpy() == np.arange(len(features))).all():
        raise ValueError("Feature row_idx must align with VLM row order")

    vinted = pd.read_parquet(vinted_path, columns=["id", "state"])
    vinted["platform"] = "vinted"
    features = features.merge(vinted, on=["platform", "id"], how="left", validate="one_to_one")

    keep_mask = (features["platform"] == "vinted") & (features["state"].isin(KEEP_STATES))
    keep_idx = np.flatnonzero(keep_mask.to_numpy())
    print(
        f"Vinted rows: {(features['platform']=='vinted').sum():,}; "
        f"after dropping non-{sorted(KEEP_STATES)} states: {len(keep_idx):,}"
    )

    vlm = np.asarray(vlm_full[keep_idx], dtype=np.float32)
    sub = features.iloc[keep_idx].copy().reset_index(drop=True)
    sub["sold_label"] = (sub["state"] == "sold").astype("float32")
    return vlm, sub, vocab


def move_batch(batch: dict[str, torch.Tensor], device: torch.device) -> dict[str, torch.Tensor]:
    return {k: v.to(device) for k, v in batch.items()}


@torch.no_grad()
def predict(model: nn.Module, loader: DataLoader, device: torch.device) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    logits, targets = [], []
    for batch in loader:
        batch = move_batch(batch, device)
        out = model(batch).detach().cpu().numpy()
        logits.append(out)
        targets.append(batch["target"].detach().cpu().numpy())
    return np.concatenate(logits, axis=0), np.concatenate(targets, axis=0)


def find_best_threshold(probs: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
    """Sweep thresholds, return (best_threshold, best_f1) for max F1 on val."""
    if labels.sum() == 0 or labels.sum() == len(labels):
        return 0.5, 0.0
    candidates = np.unique(np.concatenate([np.linspace(0.05, 0.95, 19), probs]))
    best_t, best_f1 = 0.5, -1.0
    for t in candidates:
        preds = (probs >= t).astype(int)
        f = f1_score(labels, preds, zero_division=0)
        if f > best_f1:
            best_f1, best_t = f, float(t)
    return best_t, float(best_f1)


def compute_group_metrics(probs: np.ndarray, labels: np.ndarray, threshold: float) -> GroupMetrics:
    preds = (probs >= threshold).astype(int)
    pos_rate = float(labels.mean()) if len(labels) else 0.0
    has_both_classes = (labels.sum() > 0) and (labels.sum() < len(labels))
    auc = float(roc_auc_score(labels, probs)) if has_both_classes else None
    pr_auc = float(average_precision_score(labels, probs)) if has_both_classes else None
    return GroupMetrics(
        n=int(len(labels)),
        pos_rate=pos_rate,
        auc=auc,
        pr_auc=pr_auc,
        precision=float(precision_score(labels, preds, zero_division=0)),
        recall=float(recall_score(labels, preds, zero_division=0)),
        f1=float(f1_score(labels, preds, zero_division=0)),
        brier=float(brier_score_loss(labels, probs)),
    )


def metrics_by_group(probs: np.ndarray, labels: np.ndarray, sub: pd.DataFrame, mask: np.ndarray, threshold: float) -> dict:
    sliced = sub.loc[mask].reset_index(drop=True)
    out = {"overall": asdict(compute_group_metrics(probs, labels, threshold))}
    for group_name, col in {"by_category": "category_en", "by_condition": "condition_en"}.items():
        group_metrics = {}
        for key, idx in sliced.groupby(col, sort=True).groups.items():
            rows = np.fromiter(idx, dtype=np.int64)
            group_metrics[str(key)] = asdict(compute_group_metrics(probs[rows], labels[rows], threshold))
        out[group_name] = group_metrics
    return out


def train(args: argparse.Namespace) -> dict:
    set_seed(SEED)
    device = choose_device(args.device)
    print(f"Using device: {device}")

    vlm, sub, vocab = load_inputs(args.vlm_embeddings, args.features, args.vocab, args.vinted_path)
    train_mask = sub["split"].eq("train").to_numpy()
    val_mask = sub["split"].eq("val").to_numpy()
    test_mask = sub["split"].eq("test").to_numpy()

    n_pos = int(sub.loc[train_mask, "sold_label"].sum())
    n_neg = int(train_mask.sum() - n_pos)
    pos_weight = n_neg / max(n_pos, 1)
    print(
        f"Split sizes: train={int(train_mask.sum())}, val={int(val_mask.sum())}, test={int(test_mask.sum())}; "
        f"train pos={n_pos}, neg={n_neg}, pos_weight={pos_weight:.3f}"
    )

    train_ds = SellDataset(vlm, sub, train_mask, no_flaw=args.no_flaw, no_vlm=args.no_vlm)
    val_ds = SellDataset(vlm, sub, val_mask, no_flaw=args.no_flaw, no_vlm=args.no_vlm)
    test_ds = SellDataset(vlm, sub, test_mask, no_flaw=args.no_flaw, no_vlm=args.no_vlm)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False)

    numeric_dim = (2 if args.no_flaw else 3)
    vlm_dim = 0 if args.no_vlm else int(vlm.shape[1])
    model = SellHead(
        vlm_dim=vlm_dim,
        numeric_dim=numeric_dim,
        n_categories=len(vocab["category_en"]),
        n_conditions=len(vocab["condition_en"]),
        n_brands=len(vocab["brand_canon"]),
        brand_dim=args.brand_dim,
        hidden_dim=args.hidden_dim,
        dropout=args.dropout,
    ).to(device)
    pos_weight_tensor = torch.tensor([pos_weight], dtype=torch.float32, device=device)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight_tensor)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    best_state = None
    best_val_auc = -1.0
    best_epoch = 0
    stale = 0
    history = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for batch in train_loader:
            batch = move_batch(batch, device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(batch)
            loss = loss_fn(logits, batch["target"])
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))

        val_logits, val_y = predict(model, val_loader, device)
        val_probs = 1.0 / (1.0 + np.exp(-val_logits))
        val_auc = float(roc_auc_score(val_y, val_probs)) if 0 < val_y.sum() < len(val_y) else float("nan")
        val_preds = (val_probs >= 0.5).astype(int)
        val_f1 = float(f1_score(val_y, val_preds, zero_division=0))
        val_recall = float(recall_score(val_y, val_preds, zero_division=0))

        row = {
            "epoch": epoch,
            "train_loss": float(np.mean(losses)),
            "val_auc": val_auc,
            "val_f1": val_f1,
            "val_recall": val_recall,
        }
        history.append(row)
        print(
            f"epoch={epoch:03d} loss={row['train_loss']:.4f} "
            f"val_auc={val_auc:.4f} val_f1={val_f1:.4f} val_recall={val_recall:.4f}"
        )

        if not np.isnan(val_auc) and val_auc > best_val_auc:
            best_val_auc = val_auc
            best_epoch = epoch
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= args.patience:
                print(f"Early stopping after {epoch} epochs; best epoch was {best_epoch}")
                break

    if best_state is None:
        raise RuntimeError("Training did not produce a best checkpoint")
    model.load_state_dict(best_state)

    val_logits, val_y = predict(model, val_loader, device)
    val_probs = 1.0 / (1.0 + np.exp(-val_logits))
    test_logits, test_y = predict(model, test_loader, device)
    test_probs = 1.0 / (1.0 + np.exp(-test_logits))

    tuned_threshold, tuned_val_f1 = find_best_threshold(val_probs, val_y)
    print(f"Tuned threshold on val: {tuned_threshold:.4f} (val F1={tuned_val_f1:.4f})")

    metrics = {
        "model": "sell_likelihood_head",
        "platform": "vinted_only",
        "label": "state == 'sold'",
        "uses_visual_wear_probability": not args.no_flaw,
        "threshold_tuned_on_val": tuned_threshold,
        "pos_weight": pos_weight,
        "best_epoch": best_epoch,
        "best_val_auc": best_val_auc,
        "split_counts": {
            "train": int(train_mask.sum()),
            "val": int(val_mask.sum()),
            "test": int(test_mask.sum()),
        },
        "train_class_balance": {"positive": n_pos, "negative": n_neg},
        "val": metrics_by_group(val_probs, val_y, sub, val_mask, tuned_threshold),
        "test": metrics_by_group(test_probs, test_y, sub, test_mask, tuned_threshold),
        "history": history,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "model_config": {
                "vlm_dim": vlm_dim,
                "numeric_dim": numeric_dim,
                "n_categories": len(vocab["category_en"]),
                "n_conditions": len(vocab["condition_en"]),
                "n_brands": len(vocab["brand_canon"]),
                "brand_dim": args.brand_dim,
                "hidden_dim": args.hidden_dim,
                "dropout": args.dropout,
            },
            "vocab": vocab,
            "uses_visual_wear_probability": not args.no_flaw,
            "threshold_tuned_on_val": tuned_threshold,
        },
        args.output,
    )

    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    with open(args.metrics, "w") as f:
        json.dump(metrics, f, indent=2)

    overall = metrics["test"]["overall"]
    auc_str = "None" if overall["auc"] is None else f"{overall['auc']:.4f}"
    pr_str = "None" if overall["pr_auc"] is None else f"{overall['pr_auc']:.4f}"
    print(f"Saved checkpoint: {args.output}")
    print(f"Saved metrics   : {args.metrics}")
    print(
        "Test overall: "
        f"AUC={auc_str}, "
        f"PR-AUC={pr_str}, "
        f"P={overall['precision']:.4f}, "
        f"R={overall['recall']:.4f}, "
        f"F1={overall['f1']:.4f}, "
        f"Brier={overall['brier']:.4f}, "
        f"pos_rate={overall['pos_rate']:.4f}"
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
