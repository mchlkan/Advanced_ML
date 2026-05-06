"""Batch-translate listing titles + descriptions to English via GPT-4o-mini.

The translator is the slow + costly step in the data prep pipeline (~$1 for
~10k rows). It writes incrementally to a parquet cache keyed by
``(platform, id)`` so partial runs are recoverable and reruns are no-ops.

Usage as a library::

    from translate_text import translate_dataframe
    out = translate_dataframe(combined_df, cache_path="data/translations/translations.parquet")

Usage as a CLI::

    python src/translate_text.py \\
        --vinted-parquet ../vinted_clothing_v2.parquet \\
        --ka-parquet     ../kleinanzeigen_clothing_v1.parquet \\
        --out            data/translations/translations.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import pandas as pd
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

try:
    from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError
except ImportError as e:
    raise ImportError(
        "translate_text.py requires `openai>=1.55`. Install: pip install openai tenacity"
    ) from e


MODEL_ID = "gpt-4o-mini"
CONCURRENCY = 8
MAX_OUTPUT_TOKENS = 600
REQUEST_TIMEOUT_S = 60

SYSTEM_PROMPT = (
    "You translate second-hand clothing listings into natural English. "
    "Preserve brand names verbatim. Preserve fashion-specific terminology "
    "(e.g. 'loafers', 'blazer', 'button placket', 'bootcut'). Do not add or "
    "remove information. If the source already reads as English, output it "
    "lightly cleaned. Respond ONLY with a single JSON object — no prose, no "
    "code fence."
)


def _user_prompt(title: str, description: str) -> str:
    title = (title or "").strip()
    description = (description or "").strip()
    return (
        f"Translate this listing into English. Return:\n"
        f'{{"title_en": "<English title>", "description_en": "<English description>"}}\n\n'
        f"Title: {title}\n"
        f"Description: {description}"
    )


# Tolerant JSON parser — same shape as the spike's parse_model_output.
def _parse_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return None
    snippet = text[start:end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", snippet)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


@retry(
    retry=retry_if_exception_type((RateLimitError, APIError, APITimeoutError, asyncio.TimeoutError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
async def _translate_one(
    client: AsyncOpenAI,
    title: str,
    description: str,
) -> tuple[Optional[str], Optional[str]]:
    resp = await client.chat.completions.create(
        model=MODEL_ID,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(title, description)},
        ],
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.0,
        response_format={"type": "json_object"},
        timeout=REQUEST_TIMEOUT_S,
    )
    raw = resp.choices[0].message.content or ""
    parsed = _parse_json(raw)
    if not parsed:
        return None, None
    title_en = parsed.get("title_en")
    description_en = parsed.get("description_en")
    title_en = title_en.strip() if isinstance(title_en, str) else None
    description_en = description_en.strip() if isinstance(description_en, str) else None
    return title_en, description_en


def _load_cache(cache_path: Path) -> pd.DataFrame:
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    return pd.DataFrame(columns=["platform", "id", "title_en", "description_en"])


def _persist_cache(rows: list[dict], cache_path: Path) -> None:
    if not rows:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    new_df = pd.DataFrame(rows)
    if cache_path.exists():
        existing = pd.read_parquet(cache_path)
        out = pd.concat([existing, new_df], ignore_index=True)
        # Last entry wins on duplicate (platform, id).
        out = out.drop_duplicates(subset=["platform", "id"], keep="last")
    else:
        out = new_df
    out.to_parquet(cache_path, index=False)


async def _translate_async(
    pending: pd.DataFrame,
    cache_path: Path,
    flush_every: int = 50,
) -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not set. Source the .env (`set -a; source .env; set +a`) before running."
        )
    client = AsyncOpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_S)
    sem = asyncio.Semaphore(CONCURRENCY)
    total = len(pending)
    pending_rows = pending.to_dict("records")
    buffer: list[dict] = []
    done = 0
    failures = 0
    started = time.time()

    async def worker(row: dict) -> None:
        nonlocal done, failures
        async with sem:
            try:
                title_en, description_en = await _translate_one(
                    client, row.get("title", ""), row.get("description", "")
                )
            except Exception as e:
                failures += 1
                print(f"  ! ({row['platform']}, {row['id']}): {type(e).__name__}: {e}", file=sys.stderr)
                title_en, description_en = None, None
            buffer.append({
                "platform": row["platform"],
                "id": int(row["id"]),
                "title_en": title_en,
                "description_en": description_en,
            })
            done += 1
            if done % flush_every == 0:
                _persist_cache(buffer.copy(), cache_path)
                buffer.clear()
                rate = done / max(time.time() - started, 1e-6)
                print(f"  ... {done:>5}/{total}  (~{rate:.1f}/s, {failures} failed)")

    await asyncio.gather(*(worker(r) for r in pending_rows))
    if buffer:
        _persist_cache(buffer, cache_path)
    print(f"Done: {done} translated, {failures} failed.")


def translate_dataframe(
    df: pd.DataFrame,
    cache_path: str | Path,
    force: bool = False,
) -> pd.DataFrame:
    """Translate ``df['title']`` + ``df['description']`` to English.

    ``df`` must contain ``platform``, ``id``, ``title``, ``description``. Already-cached
    ``(platform, id)`` pairs are skipped unless ``force=True``. Returns the cache
    contents (a DataFrame with ``platform``, ``id``, ``title_en``, ``description_en``).
    """
    cache_path = Path(cache_path)
    cache = _load_cache(cache_path)
    if force:
        pending = df[["platform", "id", "title", "description"]].copy()
    else:
        seen = set(zip(cache["platform"], cache["id"])) if len(cache) else set()
        mask = ~df.apply(lambda r: (r["platform"], int(r["id"])) in seen, axis=1)
        pending = df.loc[mask, ["platform", "id", "title", "description"]].copy()

    if len(pending) == 0:
        print("All rows already cached — nothing to do.")
        return _load_cache(cache_path)

    print(f"Translating {len(pending):,} rows (cache hits: {len(df) - len(pending):,})...")
    asyncio.run(_translate_async(pending, cache_path))
    return _load_cache(cache_path)


def _cli() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vinted-parquet", required=True)
    p.add_argument("--ka-parquet", required=True)
    p.add_argument("--out", required=True, help="Path to translations cache parquet.")
    p.add_argument("--force", action="store_true", help="Re-translate even cached rows.")
    args = p.parse_args()

    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    import data_prep

    vt = data_prep.apply_filters(data_prep.load_vinted(args.vinted_parquet), "vinted")
    ka = data_prep.apply_filters(data_prep.load_kleinanzeigen(args.ka_parquet), "kleinanzeigen")
    combined = data_prep.build_combined(vt, ka)
    print(f"Combined post-filter: {len(combined):,} rows")
    translate_dataframe(combined, args.out, force=args.force)


if __name__ == "__main__":
    _cli()
