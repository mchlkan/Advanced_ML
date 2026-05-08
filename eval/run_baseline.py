"""Run GPT-4o-mini on the locked 500-row test set for the Day-4 headline chart.

Sends image + listing metadata, parses a single euro number, and writes
predictions + metrics aligned with Model #4's evaluation. Predictions are
checkpointed every 25 rows so the run resumes cleanly after interruption.

Requires ``OPENAI_API_KEY`` in environment (via .env or shell export).

Default:

    python eval/run_baseline.py
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from openai import OpenAI
from tqdm.auto import tqdm


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FEATURES = REPO_ROOT / "data" / "features" / "price_features_combined.parquet"
DEFAULT_VINTED = REPO_ROOT / "data" / "vinted_clothing_combined.parquet"
DEFAULT_KA = REPO_ROOT / "data" / "kleinanzeigen_clothing_combined.parquet"
DEFAULT_PREDICTIONS = REPO_ROOT / "eval" / "results" / "gpt4o_mini_baseline_predictions.parquet"
DEFAULT_METRICS = REPO_ROOT / "eval" / "results" / "gpt4o_mini_baseline.json"

DEFAULT_MODEL = "gpt-4o-mini"
PROMPT_TEMPLATE = """You are pricing a second-hand clothing listing for a resale assistant.
Given the photo and the listing metadata, predict the fair asking price in EUR.
Respond with ONLY a single number (no currency symbol, no text, no explanation).

Platform: {platform}
Category: {category_en}
Condition: {condition_en}
Brand: {brand}
Title: {title_en}
Description: {description_en}
"""

NUMBER_RE = re.compile(r"-?\d+[.,]?\d*")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--vinted-path", type=Path, default=DEFAULT_VINTED)
    parser.add_argument("--ka-path", type=Path, default=DEFAULT_KA)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None, help="Smoke-test row cap.")
    parser.add_argument("--max-tokens", type=int, default=20)
    parser.add_argument("--temperature", type=float, default=0.0)
    return parser.parse_args()


def load_dotenv_key(env_path: Path) -> None:
    if os.getenv("OPENAI_API_KEY"):
        return
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            return


def load_test_rows(features_path: Path, vinted_path: Path, ka_path: Path) -> pd.DataFrame:
    features = pd.read_parquet(features_path)
    test = features[features["split"] == "test"].copy()
    cols = ["platform", "id", "image", "title_en", "description_en", "brand"]
    raw = pd.concat(
        [pd.read_parquet(vinted_path)[cols], pd.read_parquet(ka_path)[cols]],
        ignore_index=True,
        sort=False,
    )
    merged = test.merge(raw, on=["platform", "id"], how="left", validate="one_to_one")
    if merged["image"].isna().any():
        raise ValueError("Some test rows have no image after merge.")
    return merged


def encode_image(cell) -> str:
    if isinstance(cell, dict) and cell.get("bytes") is not None:
        return base64.standard_b64encode(cell["bytes"]).decode("utf-8")
    if isinstance(cell, (bytes, bytearray)):
        return base64.standard_b64encode(cell).decode("utf-8")
    raise ValueError(f"Unsupported image cell type: {type(cell).__name__}")


def parse_price(text: str) -> float | None:
    match = NUMBER_RE.search(text or "")
    if not match:
        return None
    raw = match.group(0).replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def predict_one(client: OpenAI, model: str, row: pd.Series, max_tokens: int, temperature: float) -> dict:
    text_prompt = PROMPT_TEMPLATE.format(
        platform=row.get("platform") or "",
        category_en=row.get("category_en") or "",
        condition_en=row.get("condition_en") or "",
        brand=row.get("brand") or "",
        title_en=row.get("title_en") or "",
        description_en=(row.get("description_en") or "")[:600],
    )
    img_b64 = encode_image(row["image"])
    last_err: Exception | None = None
    for attempt in range(8):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": text_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                        ],
                    }
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            raw = (response.choices[0].message.content or "").strip()
            return {"raw": raw, "pred_price": parse_price(raw), "error": None}
        except Exception as exc:  # rate limits, transient errors
            last_err = exc
            # Linear backoff with jitter — TPM rate limits clear once per minute,
            # so longer waits than exponential 2^n would imply.
            time.sleep(min(60, 5 + 5 * attempt))
    return {"raw": "", "pred_price": None, "error": f"{type(last_err).__name__}: {last_err}"}


def load_existing_preds(path: Path) -> dict[tuple[str, int], dict]:
    """Only successful parses count — rate-limited rows fall back to 'todo' for retry."""
    if not path.exists():
        return {}
    df = pd.read_parquet(path)
    df = df[df["pred_price"].notna()]
    out: dict[tuple[str, int], dict] = {}
    for _, r in df.iterrows():
        out[(str(r["platform"]), int(r["id"]))] = {
            "raw": r["raw"],
            "pred_price": float(r["pred_price"]),
            "error": None,
        }
    return out


def save_preds(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def compute_metrics(df: pd.DataFrame) -> dict:
    df = df.dropna(subset=["pred_price", "true_price"]).copy()
    df = df[df["true_price"] > 0]

    def slice_metrics(sub: pd.DataFrame) -> dict:
        if len(sub) == 0:
            return {"n": 0}
        err = (sub["pred_price"] - sub["true_price"]).to_numpy()
        rel = err / sub["true_price"].to_numpy()
        return {
            "n": int(len(sub)),
            "mae": float(np.mean(np.abs(err))),
            "mape": float(np.mean(np.abs(rel))),
            "rmsle": float(np.sqrt(np.mean(
                (np.log1p(sub["pred_price"].clip(lower=0).to_numpy()) - np.log1p(sub["true_price"].to_numpy())) ** 2
            ))),
        }

    out: dict = {"overall": slice_metrics(df), "by_platform": {}, "by_category": {}, "by_platform_category": {}}
    for plat, sub in df.groupby("platform"):
        out["by_platform"][plat] = slice_metrics(sub)
    for cat, sub in df.groupby("category_en"):
        out["by_category"][cat] = slice_metrics(sub)
    for (plat, cat), sub in df.groupby(["platform", "category_en"]):
        out["by_platform_category"][f"{plat} | {cat}"] = slice_metrics(sub)
    return out


def main() -> None:
    args = parse_args()
    load_dotenv_key(REPO_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY not set; put it in .env or export it.")

    test = load_test_rows(args.features, args.vinted_path, args.ka_path)
    if args.limit:
        test = test.head(args.limit).copy()
    test["true_price"] = test["price"].astype(float)
    print(f"Test rows: {len(test):,}")

    existing = load_existing_preds(args.predictions)
    todo = test[~test.apply(lambda r: (str(r["platform"]), int(r["id"])) in existing, axis=1)].copy()
    print(f"Already predicted: {len(existing)}; remaining: {len(todo)}")

    client = OpenAI()
    completed: dict[tuple[str, int], dict] = dict(existing)

    def write_out() -> None:
        rows = []
        for _, r in test.iterrows():
            key = (str(r["platform"]), int(r["id"]))
            pred = completed.get(key, {"raw": None, "pred_price": None, "error": "missing"})
            rows.append({
                "platform": r["platform"],
                "id": int(r["id"]),
                "category_en": r["category_en"],
                "condition_en": r["condition_en"],
                "true_price": float(r["true_price"]),
                "raw": pred.get("raw"),
                "pred_price": pred.get("pred_price"),
                "error": pred.get("error"),
            })
        save_preds(rows, args.predictions)

    if len(todo):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(predict_one, client, args.model, row, args.max_tokens, args.temperature): (
                    str(row["platform"]),
                    int(row["id"]),
                )
                for _, row in todo.iterrows()
            }
            done = 0
            with tqdm(total=len(futures), desc=f"Querying {args.model}") as pbar:
                for fut in as_completed(futures):
                    key = futures[fut]
                    completed[key] = fut.result()
                    done += 1
                    pbar.update(1)
                    if done % 25 == 0:
                        write_out()

    write_out()
    df = pd.read_parquet(args.predictions)
    parsed = df["pred_price"].notna().sum()
    errors = df["error"].notna().sum()
    print(f"Parsed predictions: {parsed} / {len(df)}; errors: {errors}")

    metrics = {
        "model": args.model,
        "n_total": int(len(df)),
        "n_parsed": int(parsed),
        "n_errors": int(errors),
        **compute_metrics(df),
    }
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    with open(args.metrics, "w") as f:
        json.dump(metrics, f, indent=2)

    overall = metrics["overall"]
    print(f"Saved predictions: {args.predictions}")
    print(f"Saved metrics    : {args.metrics}")
    if "mae" in overall:
        print(
            f"Test overall (n={overall['n']}): "
            f"MAE={overall['mae']:.2f}, MAPE={overall['mape']:.4f}, RMSLE={overall['rmsle']:.4f}"
        )


if __name__ == "__main__":
    main()
