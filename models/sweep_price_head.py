"""Run a focused Model #4 price-head sweep and aggregate results.

This script is intentionally small-grid and artifact-friendly: it writes each
candidate checkpoint/metrics pair separately, then creates CSV/Markdown summary
files that are easy to paste into the deck or handoff.

Example:

    python models/sweep_price_head.py --device cuda

Dry run:

    python models/sweep_price_head.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
TRAIN_SCRIPT = REPO_ROOT / "models" / "train_price_head.py"

DEFAULT_VLM = REPO_ROOT / "data" / "embeddings" / "vlm_pooled_combined.npy"
DEFAULT_FEATURES = REPO_ROOT / "data" / "features" / "price_features_combined.parquet"
DEFAULT_VOCAB = REPO_ROOT / "data" / "features" / "price_feature_vocab.json"
DEFAULT_SWEEP_CKPTS = REPO_ROOT / "models" / "checkpoints" / "price_sweep"
DEFAULT_SWEEP_RESULTS = REPO_ROOT / "eval" / "results" / "price_sweep"
DEFAULT_SUMMARY = REPO_ROOT / "eval" / "results" / "price_sweep_summary.csv"
DEFAULT_COMPARISON = REPO_ROOT / "eval" / "results" / "price_sweep_comparison.csv"
DEFAULT_CATEGORY_DELTAS = REPO_ROOT / "eval" / "results" / "price_sweep_category_deltas.csv"
DEFAULT_ABLATION = REPO_ROOT / "eval" / "results" / "price_sweep_ablation.md"

CURRENT_PRICE = REPO_ROOT / "eval" / "results" / "price_head.json"
CURRENT_NO_FLAW = REPO_ROOT / "eval" / "results" / "price_head_no_flaw.json"
GPT_BASELINE = REPO_ROOT / "eval" / "results" / "gpt4o_mini_baseline.json"

BASELINE_TARGETS = {
    "mae": 15.646772384643555,
    "mape": 0.5332475304603577,
    "rmsle": 0.5451677441596985,
    "coverage_q10_q90": 0.768,
}


@dataclass(frozen=True)
class Config:
    seed: int = 42
    dropout: float = 0.2
    hidden_dim: int = 512
    brand_dim: int = 32
    lr: float = 1e-3
    no_flaw: bool = False

    @property
    def name(self) -> str:
        flaw = "noflaw" if self.no_flaw else "flaw"
        return (
            f"seed{self.seed}_drop{fmt_float(self.dropout)}_h{self.hidden_dim}_"
            f"b{self.brand_dim}_lr{fmt_float(self.lr)}_{flaw}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vlm-embeddings", type=Path, default=DEFAULT_VLM)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--vocab", type=Path, default=DEFAULT_VOCAB)
    parser.add_argument("--checkpoint-dir", type=Path, default=DEFAULT_SWEEP_CKPTS)
    parser.add_argument("--metrics-dir", type=Path, default=DEFAULT_SWEEP_RESULTS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--comparison", type=Path, default=DEFAULT_COMPARISON)
    parser.add_argument("--category-deltas", type=Path, default=DEFAULT_CATEGORY_DELTAS)
    parser.add_argument("--ablation-report", type=Path, default=DEFAULT_ABLATION)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--device", choices=["auto", "cuda", "mps", "cpu"], default="auto")
    parser.add_argument("--force", action="store_true", help="Re-run configs even if metrics already exist.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without training.")
    parser.add_argument("--summarize-only", action="store_true", help="Only aggregate existing sweep metrics.")
    return parser.parse_args()


def fmt_float(value: float) -> str:
    return f"{value:g}".replace(".", "p").replace("-", "m")


def base_configs() -> list[Config]:
    base = Config()
    configs = [
        base,
        replace(base, seed=7),
        replace(base, seed=123),
        replace(base, dropout=0.1),
        replace(base, dropout=0.3),
        replace(base, hidden_dim=384),
        replace(base, hidden_dim=768),
        replace(base, brand_dim=16),
        replace(base, brand_dim=64),
        replace(base, lr=5e-4),
    ]
    seen = set()
    unique = []
    for cfg in configs:
        if cfg.name not in seen:
            seen.add(cfg.name)
            unique.append(cfg)
    return unique


def require_inputs(args: argparse.Namespace) -> None:
    missing = [p for p in (args.vlm_embeddings, args.features, args.vocab) if not p.exists()]
    if missing:
        joined = "\n".join(f"  - {p}" for p in missing)
        raise FileNotFoundError(
            "Missing required price-head training artifacts:\n"
            f"{joined}\n"
            "Copy these gitignored files from Leon/RunPod before running the sweep."
        )


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def metrics_path(args: argparse.Namespace, cfg: Config) -> Path:
    return args.metrics_dir / f"{cfg.name}.json"


def checkpoint_path(args: argparse.Namespace, cfg: Config) -> Path:
    return args.checkpoint_dir / f"{cfg.name}.pt"


def train_command(args: argparse.Namespace, cfg: Config) -> list[str]:
    cmd = [
        sys.executable,
        str(TRAIN_SCRIPT),
        "--vlm-embeddings", str(args.vlm_embeddings),
        "--features", str(args.features),
        "--vocab", str(args.vocab),
        "--output", str(checkpoint_path(args, cfg)),
        "--metrics", str(metrics_path(args, cfg)),
        "--epochs", str(args.epochs),
        "--batch-size", str(args.batch_size),
        "--lr", str(cfg.lr),
        "--weight-decay", str(args.weight_decay),
        "--patience", str(args.patience),
        "--hidden-dim", str(cfg.hidden_dim),
        "--brand-dim", str(cfg.brand_dim),
        "--dropout", str(cfg.dropout),
        "--seed", str(cfg.seed),
        "--device", args.device,
    ]
    if cfg.no_flaw:
        cmd.append("--no-flaw")
    return cmd


def run_config(args: argparse.Namespace, cfg: Config) -> dict | None:
    path = metrics_path(args, cfg)
    if path.exists() and not args.force:
        metrics = load_json(path)
        validate_metrics(metrics, cfg.name)
        print(f"skip existing: {cfg.name}")
        return metrics

    cmd = train_command(args, cfg)
    print("$ " + " ".join(cmd))
    if args.dry_run:
        return None

    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    args.metrics_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)
    metrics = load_json(path)
    validate_metrics(metrics, cfg.name)
    return metrics


def validate_metrics(metrics: dict, name: str) -> None:
    for section in ("val", "test"):
        if section not in metrics or "overall" not in metrics[section]:
            raise ValueError(f"{name}: metrics missing {section}.overall")
    for key in ("best_val_pinball",):
        value = metrics.get(key)
        if value is None or not math.isfinite(float(value)):
            raise ValueError(f"{name}: non-finite {key}={value}")
    for section in ("val", "test"):
        overall = metrics[section]["overall"]
        for key in ("mae", "rmsle", "coverage_q10_q90"):
            value = overall.get(key)
            if value is None or not math.isfinite(float(value)):
                raise ValueError(f"{name}: non-finite {section}.{key}={value}")
        coverage = float(overall["coverage_q10_q90"])
        if coverage < 0 or coverage > 1:
            raise ValueError(f"{name}: invalid coverage={coverage}")
        mape = overall.get("mape")
        if mape is not None and not math.isfinite(float(mape)):
            raise ValueError(f"{name}: non-finite {section}.mape={mape}")


def score_tuple(metrics: dict) -> tuple[float, float, float, float]:
    overall = metrics["test"]["overall"]
    return (
        float(metrics["best_val_pinball"]),
        float(overall["rmsle"]),
        float(overall["mae"]),
        abs(float(overall["coverage_q10_q90"]) - 0.80),
    )


def choose_best(rows: list[dict]) -> dict:
    candidates = [row for row in rows if not row["no_flaw"]]
    if not candidates:
        raise ValueError("No flaw-enabled sweep rows available for winner selection")
    return min(
        candidates,
        key=lambda row: (
            row["best_val_pinball"],
            row["test_overall_rmsle"],
            row["test_overall_mae"],
            abs(row["test_overall_coverage_q10_q90"] - 0.80),
        ),
    )


def metric_get(metrics: dict, section: str, group: str, metric: str) -> float | None:
    value = metrics.get(section, {}).get(group, {}).get(metric)
    return None if value is None else float(value)


def flatten_for_summary(name: str, cfg: Config, metrics: dict) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": name,
        "seed": cfg.seed,
        "dropout": cfg.dropout,
        "hidden_dim": cfg.hidden_dim,
        "brand_dim": cfg.brand_dim,
        "lr": cfg.lr,
        "no_flaw": cfg.no_flaw,
        "uses_visual_wear_probability": bool(metrics.get("uses_visual_wear_probability", not cfg.no_flaw)),
        "best_epoch": metrics.get("best_epoch"),
        "best_val_pinball": float(metrics["best_val_pinball"]),
    }
    for section in ("val", "test"):
        overall = metrics[section]["overall"]
        for metric in ("n", "mae", "mape", "rmsle", "coverage_q10_q90"):
            row[f"{section}_overall_{metric}"] = overall.get(metric)
        for platform in ("vinted", "kleinanzeigen"):
            plat = metrics[section].get("by_platform", {}).get(platform, {})
            for metric in ("n", "mae", "mape", "rmsle", "coverage_q10_q90"):
                row[f"{section}_{platform}_{metric}"] = plat.get(metric)
    return row


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    preferred = [key for key in [
        "name", "is_best", "seed", "dropout", "hidden_dim", "brand_dim", "lr", "no_flaw",
        "best_epoch", "best_val_pinball",
        "test_overall_mae", "test_overall_mape", "test_overall_rmsle", "test_overall_coverage_q10_q90",
    ] if key in fieldnames]
    rest = [key for key in fieldnames if key not in preferred]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=preferred + rest)
        writer.writeheader()
        writer.writerows(rows)


def collect_existing_sweep(args: argparse.Namespace) -> list[tuple[Config, dict]]:
    out = []
    for cfg in base_configs():
        path = metrics_path(args, cfg)
        if path.exists():
            metrics = load_json(path)
            validate_metrics(metrics, cfg.name)
            out.append((cfg, metrics))
    for path in sorted(args.metrics_dir.glob("*_noflaw.json")):
        metrics = load_json(path)
        validate_metrics(metrics, path.stem)
        hp = metrics.get("hyperparameters", {})
        cfg = Config(
            seed=int(metrics.get("seed", hp.get("seed", 42))),
            dropout=float(hp.get("dropout", 0.2)),
            hidden_dim=int(hp.get("hidden_dim", 512)),
            brand_dim=int(hp.get("brand_dim", 32)),
            lr=float(hp.get("lr", 1e-3)),
            no_flaw=True,
        )
        if not any(existing_cfg.name == cfg.name for existing_cfg, _ in out):
            out.append((cfg, metrics))
    return out


def comparison_rows(best_name: str, best_metrics: dict | None) -> list[dict]:
    rows = []
    for label, path in [
        ("current_price_head", CURRENT_PRICE),
        ("current_price_head_no_flaw", CURRENT_NO_FLAW),
        ("gpt4o_mini_baseline", GPT_BASELINE),
    ]:
        if path.exists():
            rows.extend(comparison_rows_from_metrics(label, load_json(path)))
    if best_metrics is not None:
        rows.extend(comparison_rows_from_metrics(best_name, best_metrics))
    return rows


def comparison_rows_from_metrics(label: str, metrics: dict) -> list[dict]:
    out = []
    if "test" in metrics:
        overall = metrics["test"]["overall"]
        out.append(compare_row(label, "overall", overall))
        for platform, sub in metrics["test"].get("by_platform", {}).items():
            out.append(compare_row(label, str(platform), sub))
    else:
        overall = metrics["overall"]
        out.append(compare_row(label, "overall", overall))
        for platform, sub in metrics.get("by_platform", {}).items():
            out.append(compare_row(label, str(platform), sub))
    return out


def compare_row(label: str, slice_name: str, metrics: dict) -> dict:
    return {
        "model": label,
        "slice": slice_name,
        "n": metrics.get("n"),
        "mae": metrics.get("mae"),
        "mape": metrics.get("mape"),
        "rmsle": metrics.get("rmsle"),
        "coverage_q10_q90": metrics.get("coverage_q10_q90"),
    }


def category_delta_rows(best_name: str, best_metrics: dict | None) -> list[dict]:
    if best_metrics is None or not CURRENT_PRICE.exists():
        return []
    current = load_json(CURRENT_PRICE)
    current_cats = current["test"].get("by_category", {})
    best_cats = best_metrics["test"].get("by_category", {})
    rows = []
    for cat in sorted(set(current_cats) & set(best_cats)):
        base = current_cats[cat]
        new = best_cats[cat]
        row = {"category": cat, "best_model": best_name, "n": new.get("n")}
        for metric in ("mae", "mape", "rmsle", "coverage_q10_q90"):
            row[f"current_{metric}"] = base.get(metric)
            row[f"best_{metric}"] = new.get(metric)
            if base.get(metric) is not None and new.get(metric) is not None:
                row[f"delta_{metric}"] = float(new[metric]) - float(base[metric])
        rows.append(row)
    return rows


def write_ablation_report(path: Path, best_name: str | None, best_metrics: dict | None, no_flaw_metrics: dict | None) -> None:
    lines = ["# Price Head Ablation Verdict", ""]
    if CURRENT_PRICE.exists() and CURRENT_NO_FLAW.exists():
        current = load_json(CURRENT_PRICE)
        no_flaw = load_json(CURRENT_NO_FLAW)
        lines.extend(ablation_lines("Current checkpoint", current, no_flaw))
    if best_metrics is not None and no_flaw_metrics is not None:
        lines.extend(["", "## Best Sweep Config"])
        lines.extend(ablation_lines(best_name or "best sweep model", best_metrics, no_flaw_metrics))
    lines.extend([
        "",
        "## Backend Recommendation",
        backend_recommendation(best_metrics, no_flaw_metrics),
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def ablation_lines(label: str, flaw_metrics: dict, no_flaw_metrics: dict) -> list[str]:
    flaw = flaw_metrics["test"]["overall"]
    no_flaw = no_flaw_metrics["test"]["overall"]
    lines = [f"## {label}", ""]
    for metric in ("mae", "mape", "rmsle", "coverage_q10_q90"):
        f_val = flaw.get(metric)
        nf_val = no_flaw.get(metric)
        if f_val is None or nf_val is None:
            continue
        delta = float(f_val) - float(nf_val)
        direction = "better" if (
            (metric == "coverage_q10_q90" and abs(float(f_val) - 0.80) < abs(float(nf_val) - 0.80))
            or (metric != "coverage_q10_q90" and delta < 0)
        ) else "worse"
        lines.append(f"- `{metric}`: flaw={float(f_val):.4f}, no_flaw={float(nf_val):.4f} ({direction})")
    return lines


def backend_recommendation(best_metrics: dict | None, no_flaw_metrics: dict | None) -> str:
    if best_metrics is None:
        return "No sweep winner available yet; keep the current flaw-enabled checkpoint until the sweep runs."
    if no_flaw_metrics is None:
        return "Keep the best flaw-enabled checkpoint unless a matching no-flaw ablation beats it on validation pinball and RMSLE."
    flaw_score = score_tuple(best_metrics)
    no_flaw_score = score_tuple(no_flaw_metrics)
    if flaw_score <= no_flaw_score:
        return "Use the flaw-enabled checkpoint: it wins the validation-first selection rule."
    return "Use the no-flaw ablation only if the team accepts losing the visual-wear signal for better validation/test metrics."


def main() -> None:
    args = parse_args()
    if args.epochs <= 0:
        raise ValueError("--epochs must be positive")
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")

    if not args.summarize_only and not args.dry_run:
        require_inputs(args)

    configs = base_configs()
    completed: list[tuple[Config, dict]] = []

    if args.summarize_only:
        completed = collect_existing_sweep(args)
    else:
        for cfg in configs:
            metrics = run_config(args, cfg)
            if metrics is not None:
                completed.append((cfg, metrics))

        if not args.dry_run and completed:
            rows_for_choice = [flatten_for_summary(cfg.name, cfg, metrics) for cfg, metrics in completed]
            best_row = choose_best(rows_for_choice)
            best_cfg = next(cfg for cfg, _ in completed if cfg.name == best_row["name"])
            no_flaw_cfg = replace(best_cfg, no_flaw=True)
            no_flaw_metrics = run_config(args, no_flaw_cfg)
            if no_flaw_metrics is not None:
                completed.append((no_flaw_cfg, no_flaw_metrics))

    if args.dry_run:
        return

    if not completed:
        raise SystemExit("No sweep metrics found. Run without --summarize-only or check --metrics-dir.")

    rows = [flatten_for_summary(cfg.name, cfg, metrics) for cfg, metrics in completed]
    best = choose_best(rows)
    for row in rows:
        row["is_best"] = row["name"] == best["name"]
    write_csv(args.summary, rows)

    best_metrics = next(metrics for cfg, metrics in completed if cfg.name == best["name"])
    matching_no_flaw = next((metrics for cfg, metrics in completed if cfg.no_flaw and cfg.seed == best["seed"]
                             and cfg.dropout == best["dropout"] and cfg.hidden_dim == best["hidden_dim"]
                             and cfg.brand_dim == best["brand_dim"] and cfg.lr == best["lr"]), None)
    write_csv(args.comparison, comparison_rows(best["name"], best_metrics))
    write_csv(args.category_deltas, category_delta_rows(best["name"], best_metrics))
    write_ablation_report(args.ablation_report, best["name"], best_metrics, matching_no_flaw)

    print(f"Best flaw-enabled config: {best['name']}")
    print(f"Saved summary          : {args.summary}")
    print(f"Saved comparison       : {args.comparison}")
    print(f"Saved category deltas  : {args.category_deltas}")
    print(f"Saved ablation report  : {args.ablation_report}")


if __name__ == "__main__":
    main()
