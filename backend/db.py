"""SQLite persistence for Resell Copilot.

Per brief §5.1: log every model call, every user edit, every publish action.
Schema lives in this file so it's the one place to grep for table changes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import aiosqlite


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "resell.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  id          TEXT PRIMARY KEY,
  created_at  INTEGER NOT NULL,
  image_path  TEXT NOT NULL,
  vlm_backend TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS predictions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id      TEXT NOT NULL REFERENCES listings(id),
  source          TEXT NOT NULL,
  created_at      INTEGER NOT NULL,
  english_fields  TEXT NOT NULL,
  vinted_q10      REAL,
  vinted_q50      REAL,
  vinted_q90      REAL,
  vinted_sell_prob REAL,
  ka_q10          REAL,
  ka_q50          REAL,
  ka_q90          REAL,
  visual_wear_probability REAL,
  latency_ms      INTEGER NOT NULL,
  vlm_call_count  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS edits (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id   TEXT NOT NULL REFERENCES listings(id),
  created_at   INTEGER NOT NULL,
  field_name   TEXT NOT NULL,
  old_value    TEXT,
  new_value    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publishes (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id   TEXT NOT NULL REFERENCES listings(id),
  created_at   INTEGER NOT NULL,
  platform     TEXT NOT NULL,
  final_fields TEXT NOT NULL,
  prefill_url  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_predictions_listing ON predictions(listing_id);
CREATE INDEX IF NOT EXISTS idx_edits_listing       ON edits(listing_id);
CREATE INDEX IF NOT EXISTS idx_publishes_listing   ON publishes(listing_id);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


def _resolve(db_path: Path | None) -> Path:
    return db_path if db_path is not None else DEFAULT_DB_PATH


async def init_db(db_path: Path | None = None) -> None:
    db_path = _resolve(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(SCHEMA)
        await conn.commit()


async def log_listing(
    listing_id: str,
    image_path: Path,
    vlm_backend: str,
    db_path: Path | None = None,
) -> None:
    async with aiosqlite.connect(_resolve(db_path)) as conn:
        await conn.execute(
            "INSERT INTO listings(id, created_at, image_path, vlm_backend) VALUES (?, ?, ?, ?)",
            (listing_id, now_ms(), str(image_path), vlm_backend),
        )
        await conn.commit()


async def log_prediction(
    listing_id: str,
    source: str,
    english_fields: dict,
    vinted_q10: float,
    vinted_q50: float,
    vinted_q90: float,
    vinted_sell_prob: float,
    ka_q10: float,
    ka_q50: float,
    ka_q90: float,
    visual_wear_probability: float,
    latency_ms: int,
    vlm_call_count: int,
    db_path: Path | None = None,
) -> None:
    async with aiosqlite.connect(_resolve(db_path)) as conn:
        await conn.execute(
            """INSERT INTO predictions(
                listing_id, source, created_at, english_fields,
                vinted_q10, vinted_q50, vinted_q90, vinted_sell_prob,
                ka_q10, ka_q50, ka_q90,
                visual_wear_probability, latency_ms, vlm_call_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                listing_id, source, now_ms(), json.dumps(english_fields),
                vinted_q10, vinted_q50, vinted_q90, vinted_sell_prob,
                ka_q10, ka_q50, ka_q90,
                visual_wear_probability, latency_ms, vlm_call_count,
            ),
        )
        await conn.commit()


async def log_edits(
    listing_id: str,
    changes: list[tuple[str, str | None, str]],
    db_path: Path | None = None,
) -> None:
    if not changes:
        return
    async with aiosqlite.connect(_resolve(db_path)) as conn:
        await conn.executemany(
            "INSERT INTO edits(listing_id, created_at, field_name, old_value, new_value) VALUES (?, ?, ?, ?, ?)",
            [(listing_id, now_ms(), field, old, new) for field, old, new in changes],
        )
        await conn.commit()


async def log_publish(
    listing_id: str,
    platform: str,
    final_fields: dict,
    prefill_url: str,
    db_path: Path | None = None,
) -> None:
    async with aiosqlite.connect(_resolve(db_path)) as conn:
        await conn.execute(
            """INSERT INTO publishes(listing_id, created_at, platform, final_fields, prefill_url)
               VALUES (?, ?, ?, ?, ?)""",
            (listing_id, now_ms(), platform, json.dumps(final_fields), prefill_url),
        )
        await conn.commit()
