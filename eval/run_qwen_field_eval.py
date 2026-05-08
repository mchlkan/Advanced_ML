"""Evaluate fine-tuned Qwen field extraction on the locked test set.

Runs the Qwen3-VL base + LoRA adapter on each held-out listing image, parses
the emitted JSON, and reports field-level accuracy against seller metadata.

RunPod GPU example:

    python eval/run_qwen_field_eval.py --load-in-4bit

Smoke test:

    python eval/run_qwen_field_eval.py --load-in-4bit --limit 5
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from peft import PeftModel
from tqdm.auto import tqdm
from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig


REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "models"
SHARED_DIR = REPO_ROOT / "shared"
BACKEND_DIR = REPO_ROOT / "backend"
for path in (MODELS_DIR, SHARED_DIR, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from extract_features import decode_image, load_combined  # noqa: E402
from extract_vlm_features import DEFAULT_ADAPTER, DEFAULT_BASE_MODEL, build_inputs  # noqa: E402
from vlm_backend.util import parse_json_lenient  # noqa: E402


DEFAULT_VINTED = REPO_ROOT / "data" / "vinted_clothing_combined.parquet"
DEFAULT_KA = REPO_ROOT / "data" / "kleinanzeigen_clothing_combined.parquet"
DEFAULT_SPLITS = REPO_ROOT / "data" / "splits"
DEFAULT_PREDICTIONS = REPO_ROOT / "eval" / "results" / "qwen_field_predictions.parquet"
DEFAULT_METRICS = REPO_ROOT / "eval" / "results" / "qwen_field_eval.json"

FIELD_MAP = {
    "brand": "brand",
    "category": "category_en",
    "condition": "condition_en",
    "color": "color_en",
    "size": "size",
}
REQUIRED_OUTPUT_FIELDS = ["brand", "category", "condition", "color", "size", "title", "description", "price_eur"]
WORD_RE = re.compile(r"\w+")
JSON_FIELD_RE = re.compile(
    r'"(?P<key>brand|category|condition|color|size|title|description|price_eur)"\s*:\s*'
    r'(?P<value>"(?:[^"\\]|\\.)*"?|-?\d+(?:\.\d+)?|null)',
    re.IGNORECASE | re.DOTALL,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER)
    parser.add_argument("--vinted-path", type=Path, default=DEFAULT_VINTED)
    parser.add_argument("--ka-path", type=Path, default=DEFAULT_KA)
    parser.add_argument("--splits-dir", type=Path, default=DEFAULT_SPLITS)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--limit", type=int, default=None, help="Optional smoke-test row cap.")
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--save-every", type=int, default=25)
    parser.add_argument("--load-in-4bit", action="store_true")
    parser.add_argument(
        "--torch-dtype",
        choices=["auto", "float16", "bfloat16", "float32"],
        default="auto",
    )
    parser.add_argument("--device-map", default="auto")
    parser.add_argument(
        "--bert-score",
        action="store_true",
        help="Also compute BERTScore for title/description. Slow and downloads extra models.",
    )
    return parser.parse_args()


def dtype_from_arg(name: str):
    return {
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
        "float32": torch.float32,
    }.get(name)


def load_model_and_processor(args: argparse.Namespace):
    processor = AutoProcessor.from_pretrained(args.model_id, trust_remote_code=True)
    model_kwargs: dict[str, Any] = {"trust_remote_code": True, "device_map": args.device_map}
    if args.load_in_4bit:
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
    elif args.torch_dtype != "auto":
        model_kwargs["torch_dtype"] = dtype_from_arg(args.torch_dtype)

    base = AutoModelForImageTextToText.from_pretrained(args.model_id, **model_kwargs)
    model = PeftModel.from_pretrained(base, args.adapter_id)
    model.eval()
    return processor, model


def model_device(model) -> torch.device:
    return next(model.parameters()).device


def load_test_rows(args: argparse.Namespace) -> pd.DataFrame:
    df = load_combined(args.vinted_path, args.ka_path, args.splits_dir)
    test = df[df["split"].eq("test")].copy()
    if args.limit is not None:
        test = test.head(args.limit).copy()
    return test.reset_index(drop=True)


def norm(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return " ".join(WORD_RE.findall(str(value).casefold()))


def brand_fuzzy_match(pred: Any, truth: Any) -> bool:
    pred_n = norm(pred)
    truth_n = norm(truth)
    if not pred_n or not truth_n:
        return False
    if pred_n == truth_n:
        return True
    pred_tokens = set(pred_n.split())
    truth_tokens = set(truth_n.split())
    if pred_tokens and truth_tokens and pred_tokens <= truth_tokens:
        return True
    if pred_tokens and truth_tokens and truth_tokens <= pred_tokens:
        return True
    try:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, pred_n, truth_n).ratio() >= 0.85
    except Exception:
        return False


def as_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) and out >= 0 else None


def parse_model_output(raw_text: str) -> tuple[dict, bool]:
    fields = parse_json_lenient(raw_text)
    if fields:
        return fields, True

    # Fallback for common Qwen failure mode: JSON object starts correctly but a
    # long description contains raw newlines or truncates before the closing
    # quote/brace. Recover scalar fields so accuracy metrics remain useful.
    recovered: dict[str, Any] = {}
    for match in JSON_FIELD_RE.finditer(raw_text or ""):
        key = match.group("key")
        value = match.group("value").strip()
        if value == "null":
            recovered[key] = None
        elif value.startswith('"'):
            recovered[key] = value[1:].rstrip('"').replace('\\"', '"').replace("\\n", "\n").strip()
        else:
            recovered[key] = as_float(value)
    return recovered, False


@torch.no_grad()
def predict_one(processor, model, row: pd.Series, max_new_tokens: int) -> dict:
    image = decode_image(row["image"])
    inputs = build_inputs(processor, image, row["platform"], model_device(model))
    generated = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    new_tokens = generated[0, inputs["input_ids"].shape[1] :]
    raw_text = processor.decode(new_tokens, skip_special_tokens=True).strip()
    fields, parse_ok = parse_model_output(raw_text)
    return {"raw_text": raw_text, "fields": fields, "parse_ok": parse_ok}


def load_existing(path: Path) -> dict[tuple[str, int], dict]:
    if not path.exists():
        return {}
    df = pd.read_parquet(path)
    out: dict[tuple[str, int], dict] = {}
    for _, row in df.iterrows():
        if bool(row.get("parse_ok", False)) and not row.get("error"):
            out[(str(row["platform"]), int(row["id"]))] = row.to_dict()
    return out


def row_from_prediction(row: pd.Series, pred: dict) -> dict:
    fields = pred.get("fields") or {}
    out = {
        "platform": row["platform"],
        "id": int(row["id"]),
        "category_en": row.get("category_en"),
        "condition_en": row.get("condition_en"),
        "brand": row.get("brand"),
        "color_en": row.get("color_en"),
        "size": row.get("size"),
        "title_en": row.get("title_en"),
        "description_en": row.get("description_en"),
        "true_price": float(row["price"]),
        "raw_text": pred.get("raw_text"),
        "parse_ok": bool(pred.get("parse_ok", False)),
        "error": pred.get("error"),
        "latency_ms": pred.get("latency_ms"),
    }
    for key in REQUIRED_OUTPUT_FIELDS:
        out[f"pred_{key}"] = fields.get(key)
    return out


def save_predictions(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def tokenized_bleu(preds: list[str], refs: list[str]) -> float | None:
    try:
        from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu
    except Exception:
        return None
    scores = []
    smoothing = SmoothingFunction().method1
    for pred, ref in zip(preds, refs):
        pred_tokens = WORD_RE.findall(norm(pred))
        ref_tokens = WORD_RE.findall(norm(ref))
        if not pred_tokens or not ref_tokens:
            scores.append(0.0)
        else:
            scores.append(sentence_bleu([ref_tokens], pred_tokens, smoothing_function=smoothing))
    return float(np.mean(scores)) if scores else None


def compute_slice_metrics(df: pd.DataFrame, bert_score: bool = False) -> dict:
    total = int(len(df))
    out: dict[str, Any] = {
        "n": total,
        "parse_rate": float(df["parse_ok"].mean()) if total else None,
        "field_fill_rate": {},
        "accuracy": {},
    }
    for field in REQUIRED_OUTPUT_FIELDS:
        out["field_fill_rate"][field] = float(df[f"pred_{field}"].map(lambda x: bool(norm(x))).mean()) if total else None

    for pred_field, true_field in FIELD_MAP.items():
        valid_truth = df[true_field].map(lambda x: bool(norm(x)))
        denom_df = df[valid_truth].copy()
        if len(denom_df) == 0:
            out["accuracy"][pred_field] = {"n": 0, "exact": None}
            continue
        exact = denom_df.apply(lambda r: norm(r[f"pred_{pred_field}"]) == norm(r[true_field]), axis=1)
        out["accuracy"][pred_field] = {"n": int(len(denom_df)), "exact": float(exact.mean())}

    brand_valid = df["brand"].map(lambda x: bool(norm(x)))
    brand_df = df[brand_valid].copy()
    if len(brand_df):
        fuzzy = brand_df.apply(lambda r: brand_fuzzy_match(r["pred_brand"], r["brand"]), axis=1)
        out["accuracy"]["brand"]["fuzzy"] = float(fuzzy.mean())

    price_df = df[df["true_price"].astype(float) > 0].copy()
    pred_price = price_df["pred_price_eur"].map(as_float)
    price_df = price_df[pred_price.notna()].copy()
    if len(price_df):
        pred = price_df["pred_price_eur"].map(as_float).astype(float).to_numpy()
        true = price_df["true_price"].astype(float).to_numpy()
        out["vlm_price_eur"] = {
            "n": int(len(price_df)),
            "mae": float(np.mean(np.abs(pred - true))),
            "mape": float(np.mean(np.abs(pred - true) / true)),
            "rmsle": float(np.sqrt(np.mean((np.log1p(np.clip(pred, 0, None)) - np.log1p(true)) ** 2))),
        }
    else:
        out["vlm_price_eur"] = {"n": 0, "mae": None, "mape": None, "rmsle": None}

    out["title_bleu4"] = tokenized_bleu(
        df["pred_title"].fillna("").astype(str).tolist(),
        df["title_en"].fillna("").astype(str).tolist(),
    )
    out["description_bleu4"] = tokenized_bleu(
        df["pred_description"].fillna("").astype(str).tolist(),
        df["description_en"].fillna("").astype(str).tolist(),
    )
    if bert_score:
        out["bertscore"] = compute_bert_score(df)
    return out


def compute_bert_score(df: pd.DataFrame) -> dict | None:
    try:
        import evaluate
    except Exception:
        return None
    scorer = evaluate.load("bertscore")
    out = {}
    for field in ("title", "description"):
        preds = df[f"pred_{field}"].fillna("").astype(str).tolist()
        refs = df[f"{field}_en"].fillna("").astype(str).tolist()
        scores = scorer.compute(predictions=preds, references=refs, lang="en")
        out[field] = {
            "precision": float(np.mean(scores["precision"])),
            "recall": float(np.mean(scores["recall"])),
            "f1": float(np.mean(scores["f1"])),
        }
    return out


def compute_metrics(df: pd.DataFrame, bert_score: bool = False) -> dict:
    metrics = {"overall": compute_slice_metrics(df, bert_score=bert_score), "by_platform": {}, "by_category": {}}
    for platform, sub in df.groupby("platform"):
        metrics["by_platform"][str(platform)] = compute_slice_metrics(sub, bert_score=False)
    for category, sub in df.groupby("category_en"):
        metrics["by_category"][str(category)] = compute_slice_metrics(sub, bert_score=False)
    return metrics


def main() -> None:
    args = parse_args()
    if args.save_every <= 0:
        raise ValueError("--save-every must be positive")

    test = load_test_rows(args)
    print(f"Test rows: {len(test):,}")
    existing = load_existing(args.predictions)
    print(f"Existing successful predictions: {len(existing):,}")

    processor, model = load_model_and_processor(args)
    completed: dict[tuple[str, int], dict] = dict(existing)

    def write_out() -> None:
        rows = []
        for _, item in test.iterrows():
            key = (str(item["platform"]), int(item["id"]))
            pred = completed.get(key, {"raw_text": None, "fields": {}, "parse_ok": False, "error": "missing"})
            if "fields" not in pred:
                pred = {
                    "raw_text": pred.get("raw_text"),
                    "fields": {field: pred.get(f"pred_{field}") for field in REQUIRED_OUTPUT_FIELDS},
                    "parse_ok": bool(pred.get("parse_ok", False)),
                    "error": pred.get("error"),
                    "latency_ms": pred.get("latency_ms"),
                }
            rows.append(row_from_prediction(item, pred))
        save_predictions(rows, args.predictions)

    todo = [
        row for _, row in test.iterrows()
        if (str(row["platform"]), int(row["id"])) not in completed
    ]
    failures = 0
    for i, row in enumerate(tqdm(todo, desc="Evaluating Qwen fields"), start=1):
        key = (str(row["platform"]), int(row["id"]))
        started = time.perf_counter()
        try:
            pred = predict_one(processor, model, row, args.max_new_tokens)
            pred["latency_ms"] = int((time.perf_counter() - started) * 1000)
            pred["error"] = None
        except Exception as exc:
            failures += 1
            pred = {
                "raw_text": "",
                "fields": {},
                "parse_ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": f"{type(exc).__name__}: {exc}",
            }
        completed[key] = pred
        if i % args.save_every == 0:
            write_out()

    write_out()
    pred_df = pd.read_parquet(args.predictions)
    metrics = {
        "model": args.model_id,
        "adapter": args.adapter_id,
        "n_total": int(len(pred_df)),
        "n_parse_ok": int(pred_df["parse_ok"].sum()),
        "n_errors": int(pred_df["error"].notna().sum()),
        "generation_failures_this_run": int(failures),
        **compute_metrics(pred_df, bert_score=args.bert_score),
    }
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    with open(args.metrics, "w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    acc = metrics["overall"]["accuracy"]
    print(f"Saved predictions: {args.predictions}")
    print(f"Saved metrics    : {args.metrics}")
    print(f"Parse OK         : {metrics['n_parse_ok']} / {metrics['n_total']}")
    print(
        "Accuracy         : "
        f"brand fuzzy={acc['brand'].get('fuzzy')}, "
        f"category={acc['category']['exact']}, "
        f"condition={acc['condition']['exact']}, "
        f"color={acc['color']['exact']}, "
        f"size={acc['size']['exact']}"
    )


if __name__ == "__main__":
    main()
