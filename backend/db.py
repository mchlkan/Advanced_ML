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

# `publishes` is the publish-job state machine. Status values:
#   pending  — waiting to be picked up by the runner (next_attempt_at <= now)
#   running  — runner has claimed and is currently posting
#   posted   — terminal, success
#   failed   — terminal, gave up after max retries or hit a permanent error
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
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id           TEXT NOT NULL REFERENCES listings(id),
  created_at           INTEGER NOT NULL,
  platform             TEXT NOT NULL,
  final_fields         TEXT NOT NULL,
  prefill_url          TEXT NOT NULL,
  status               TEXT NOT NULL DEFAULT 'posted',
  retry_count          INTEGER NOT NULL DEFAULT 0,
  next_attempt_at      INTEGER,
  platform_listing_id  TEXT,
  platform_listing_url TEXT,
  error                TEXT,
  updated_at           INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_predictions_listing ON predictions(listing_id);
CREATE INDEX IF NOT EXISTS idx_edits_listing       ON edits(listing_id);
CREATE INDEX IF NOT EXISTS idx_publishes_listing   ON publishes(listing_id);
"""

# Columns that need ALTER TABLE on existing databases. Each runs idempotently
# at startup; SQLite raises OperationalError on duplicate column adds, which
# we swallow.
_PUBLISH_MIGRATIONS = [
    "ALTER TABLE publishes ADD COLUMN status TEXT NOT NULL DEFAULT 'posted'",
    "ALTER TABLE publishes ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE publishes ADD COLUMN next_attempt_at INTEGER",
    "ALTER TABLE publishes ADD COLUMN platform_listing_id TEXT",
    "ALTER TABLE publishes ADD COLUMN platform_listing_url TEXT",
    "ALTER TABLE publishes ADD COLUMN error TEXT",
    "ALTER TABLE publishes ADD COLUMN updated_at INTEGER NOT NULL DEFAULT 0",
]


def now_ms() -> int:
    return int(time.time() * 1000)


def _resolve(db_path: Path | None) -> Path:
    return db_path if db_path is not None else DEFAULT_DB_PATH


async def init_db(db_path: Path | None = None) -> None:
    db_path = _resolve(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(SCHEMA)
        for stmt in _PUBLISH_MIGRATIONS:
            try:
                await conn.execute(stmt)
            except aiosqlite.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
        # The pending-job index references columns added by the migrations
        # above, so it must run *after* the ALTER TABLE block. (Fresh DBs
        # already have those columns from the SCHEMA's CREATE TABLE.)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_publishes_pending ON publishes(status, next_attempt_at)"
        )
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


async def get_listing(
    listing_id: str,
    db_path: Path | None = None,
) -> dict | None:
    """Return the listing's image path and most-recent english_fields, or None
    if the id is unknown. The fields come from the latest row in `predictions`
    so a 3rd /verify diffs against the 2nd, not the original /upload."""
    async with aiosqlite.connect(_resolve(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        listing_row = await (await conn.execute(
            "SELECT image_path FROM listings WHERE id = ?", (listing_id,)
        )).fetchone()
        if listing_row is None:
            return None
        latest = await (await conn.execute(
            "SELECT english_fields FROM predictions "
            "WHERE listing_id = ? ORDER BY id DESC LIMIT 1",
            (listing_id,),
        )).fetchone()
        return {
            "image_path": listing_row["image_path"],
            "last_english_fields": json.loads(latest["english_fields"]) if latest else {},
        }


# ---------- publish-job state machine ----------


async def create_publish_job(
    listing_id: str,
    platform: str,
    final_fields: dict,
    prefill_url: str,
    db_path: Path | None = None,
) -> int:
    """Insert a row in 'pending' state, eligible for the runner to claim
    immediately. Returns the auto-incremented job id."""
    now = now_ms()
    async with aiosqlite.connect(_resolve(db_path)) as conn:
        cur = await conn.execute(
            """INSERT INTO publishes(
                listing_id, created_at, platform, final_fields, prefill_url,
                status, retry_count, next_attempt_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)""",
            (listing_id, now, platform, json.dumps(final_fields), prefill_url, now, now),
        )
        await conn.commit()
        return int(cur.lastrowid)


async def claim_next_pending_job(db_path: Path | None = None) -> dict | None:
    """Pick the oldest 'pending' job whose next_attempt_at has elapsed and
    flip it to 'running' atomically. Returns the row dict (with parsed
    final_fields), or None if nothing is ready."""
    now = now_ms()
    async with aiosqlite.connect(_resolve(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("BEGIN IMMEDIATE")
        try:
            row = await (await conn.execute(
                """SELECT * FROM publishes
                   WHERE status = 'pending' AND next_attempt_at <= ?
                   ORDER BY next_attempt_at ASC LIMIT 1""",
                (now,),
            )).fetchone()
            if row is None:
                await conn.commit()
                return None
            await conn.execute(
                "UPDATE publishes SET status = 'running', updated_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        d = dict(row)
        d["final_fields"] = json.loads(d["final_fields"])
        return d


async def update_publish_job(
    job_id: int,
    db_path: Path | None = None,
    **fields,
) -> None:
    """Set arbitrary columns on a publishes row. Auto-stamps updated_at."""
    if not fields:
        return
    fields["updated_at"] = now_ms()
    cols = ", ".join(f"{k} = ?" for k in fields)
    async with aiosqlite.connect(_resolve(db_path)) as conn:
        await conn.execute(
            f"UPDATE publishes SET {cols} WHERE id = ?",
            (*fields.values(), job_id),
        )
        await conn.commit()


async def get_publish_job(job_id: int, db_path: Path | None = None) -> dict | None:
    async with aiosqlite.connect(_resolve(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        row = await (await conn.execute(
            "SELECT * FROM publishes WHERE id = ?", (job_id,)
        )).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["final_fields"] = json.loads(d["final_fields"])
        return d
