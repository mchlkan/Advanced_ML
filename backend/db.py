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

CREATE TABLE IF NOT EXISTS wardrobe_snapshots (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  fetched_at          INTEGER NOT NULL,
  platform            TEXT NOT NULL,
  platform_listing_id TEXT NOT NULL,
  title               TEXT,
  price_eur           REAL,
  currency            TEXT,
  views               INTEGER,
  favourites          INTEGER,
  url                 TEXT,
  primary_photo_url   TEXT,
  raw_json            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wardrobe_syncs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  platform     TEXT NOT NULL,
  started_at   INTEGER NOT NULL,
  finished_at  INTEGER,
  status       TEXT NOT NULL,
  item_count   INTEGER,
  error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_predictions_listing ON predictions(listing_id);
CREATE INDEX IF NOT EXISTS idx_edits_listing       ON edits(listing_id);
CREATE INDEX IF NOT EXISTS idx_publishes_listing   ON publishes(listing_id);
CREATE INDEX IF NOT EXISTS idx_wardrobe_lookup
  ON wardrobe_snapshots(platform, platform_listing_id, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_wardrobe_syncs_recent
  ON wardrobe_syncs(platform, started_at DESC);
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
        # PRAGMA table_info tells us which columns already exist, so we only
        # run ALTER TABLE for missing ones — no exception-driven control flow,
        # zero overhead on the common (already-migrated) path.
        existing = {
            row[1]
            for row in await (await conn.execute("PRAGMA table_info(publishes)")).fetchall()
        }
        for stmt in _PUBLISH_MIGRATIONS:
            col = stmt.split("ADD COLUMN ", 1)[1].split()[0]
            if col not in existing:
                await conn.execute(stmt)
        # Created after the migrations above so existing DBs that lack the
        # `status` column at SCHEMA-eval time don't fail. (Fresh DBs already
        # have the column from CREATE TABLE.)
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


# Whitelisted to prevent f-string SQL surprises if a future caller passes
# a typo'd or hostile column name. Add to the set as the schema evolves.
_PUBLISH_UPDATABLE_COLUMNS = frozenset({
    "status", "retry_count", "next_attempt_at",
    "platform_listing_id", "platform_listing_url", "error",
})


async def update_publish_job(
    job_id: int,
    db_path: Path | None = None,
    **fields,
) -> None:
    """Set columns on a publishes row. Only fields in _PUBLISH_UPDATABLE_COLUMNS
    are accepted; auto-stamps updated_at."""
    if not fields:
        return
    bad = set(fields) - _PUBLISH_UPDATABLE_COLUMNS
    if bad:
        raise ValueError(f"update_publish_job: disallowed columns {sorted(bad)}")
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


# ---------- wardrobe sync ----------


async def insert_wardrobe_snapshots(
    platform: str,
    items: list[dict],
    fetched_at: int,
    db_path: Path | None = None,
) -> None:
    """Bulk insert one snapshot row per item. `items` are dicts shaped by
    integrations.vinted.normalize_wardrobe_item — they MUST contain the raw
    API blob under the key 'raw' (so we don't lose fields we don't model)."""
    if not items:
        return
    rows = [
        (
            fetched_at, platform, item["platform_listing_id"],
            item.get("title"), item.get("price_eur"), item.get("currency"),
            item.get("views"), item.get("favourites"),
            item.get("url"), item.get("primary_photo_url"),
            json.dumps(item.get("raw", {})),
        )
        for item in items
    ]
    async with aiosqlite.connect(_resolve(db_path)) as conn:
        await conn.executemany(
            """INSERT INTO wardrobe_snapshots(
                fetched_at, platform, platform_listing_id,
                title, price_eur, currency, views, favourites,
                url, primary_photo_url, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await conn.commit()


async def record_wardrobe_sync(
    platform: str,
    started_at: int,
    *,
    status: str,
    item_count: int | None = None,
    error: str | None = None,
    db_path: Path | None = None,
) -> int:
    """Insert a wardrobe_syncs row stamped with `finished_at = now`. Returns
    the row id."""
    async with aiosqlite.connect(_resolve(db_path)) as conn:
        cur = await conn.execute(
            """INSERT INTO wardrobe_syncs(
                platform, started_at, finished_at, status, item_count, error
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (platform, started_at, now_ms(), status, item_count, error),
        )
        await conn.commit()
        return int(cur.lastrowid)


async def get_last_wardrobe_sync(
    platform: str,
    db_path: Path | None = None,
) -> dict | None:
    """Most recent wardrobe_syncs row for the platform, or None if never run."""
    async with aiosqlite.connect(_resolve(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        row = await (await conn.execute(
            "SELECT * FROM wardrobe_syncs WHERE platform = ? "
            "ORDER BY id DESC LIMIT 1",
            (platform,),
        )).fetchone()
        return dict(row) if row else None


_INVENTORY_QUERY = """
WITH latest_prediction AS (
  SELECT p.* FROM predictions p
  JOIN (SELECT listing_id, MAX(id) AS max_id FROM predictions GROUP BY listing_id) m
    ON p.id = m.max_id
),
latest_publish AS (
  SELECT pb.* FROM publishes pb
  JOIN (SELECT listing_id, platform, MAX(id) AS max_id
        FROM publishes GROUP BY listing_id, platform) m
    ON pb.id = m.max_id
),
latest_wardrobe AS (
  SELECT w.* FROM wardrobe_snapshots w
  JOIN (SELECT platform, platform_listing_id, MAX(id) AS max_id
        FROM wardrobe_snapshots GROUP BY platform, platform_listing_id) m
    ON w.id = m.max_id
)
SELECT
  l.id              AS listing_id,
  l.created_at      AS listing_created_at,
  lp.english_fields AS english_fields,
  lp.vinted_q10, lp.vinted_q50, lp.vinted_q90, lp.vinted_sell_prob,
  lp.ka_q10, lp.ka_q50, lp.ka_q90, lp.visual_wear_probability,
  lpb.platform             AS publish_platform,
  lpb.id                   AS publish_id,
  lpb.status               AS publish_status,
  lpb.platform_listing_id  AS publish_platform_listing_id,
  lpb.platform_listing_url AS publish_platform_listing_url,
  lpb.error                AS publish_error,
  lpb.updated_at           AS publish_updated_at,
  lw.fetched_at            AS wardrobe_fetched_at,
  lw.title                 AS wardrobe_title,
  lw.price_eur             AS wardrobe_price_eur,
  lw.views                 AS wardrobe_views,
  lw.favourites            AS wardrobe_favourites,
  lw.primary_photo_url     AS wardrobe_primary_photo_url
FROM listings l
LEFT JOIN latest_prediction lp ON lp.listing_id = l.id
LEFT JOIN latest_publish lpb ON lpb.listing_id = l.id
LEFT JOIN latest_wardrobe lw
  ON lw.platform = lpb.platform
  AND lw.platform_listing_id = lpb.platform_listing_id
ORDER BY l.created_at DESC, l.id, lpb.platform
"""


async def get_inventory_rows(db_path: Path | None = None) -> list[dict]:
    """Return one row per (listing, publish-platform) — listings without any
    publish appear once with null publish_* fields. Caller folds platforms
    into per-listing dicts."""
    async with aiosqlite.connect(_resolve(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (await conn.execute(_INVENTORY_QUERY)).fetchall()
        return [dict(r) for r in rows]
