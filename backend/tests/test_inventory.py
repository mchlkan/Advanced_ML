"""Inventory endpoint tests.

Covers GET /inventory shaping (empty DB, prediction-only, publish state,
wardrobe join, sold detection), POST /inventory/sync (readiness gate +
happy path with monkeypatched fetch_wardrobe), and GET /listings/{id}/image.

Direct sqlite3 inserts are used to seed posted publishes and wardrobe
snapshots — going through the runner would force real Vinted credentials
and is covered by test_publish.py.
"""

from __future__ import annotations

import json
import sqlite3
import time


def _upload(client, jpeg_bytes) -> str:
    r = client.post("/upload", files={"image": ("hero.jpg", jpeg_bytes, "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()["listing_id"]


def _seed_posted_publish(
    db_path,
    listing_id: str,
    *,
    platform: str = "vinted",
    platform_listing_id: str = "1234567890",
    platform_listing_url: str = "https://www.vinted.fr/items/1234567890",
    updated_at_ms: int | None = None,
) -> int:
    """Insert a row directly into publishes with status='posted'. Returns the
    publish row id. Bypasses the runner — tests for join/shaping logic."""
    now = int(time.time() * 1000) if updated_at_ms is None else updated_at_ms
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO publishes(
                listing_id, created_at, platform, final_fields, prefill_url,
                status, retry_count, next_attempt_at,
                platform_listing_id, platform_listing_url,
                error, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'posted', 0, NULL, ?, ?, NULL, ?)""",
            (
                listing_id, now, platform, json.dumps({}), "",
                platform_listing_id, platform_listing_url, now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def _seed_wardrobe_snapshot(
    db_path,
    *,
    platform: str = "vinted",
    platform_listing_id: str = "1234567890",
    fetched_at_ms: int | None = None,
    title: str = "Test item",
    price_eur: float = 12.50,
    views: int = 42,
    favourites: int = 7,
) -> None:
    fetched_at = int(time.time() * 1000) if fetched_at_ms is None else fetched_at_ms
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO wardrobe_snapshots(
                fetched_at, platform, platform_listing_id, title,
                price_eur, currency, views, favourites,
                url, primary_photo_url, raw_json
            ) VALUES (?, ?, ?, ?, ?, 'EUR', ?, ?, NULL, NULL, '{}')""",
            (fetched_at, platform, platform_listing_id, title, price_eur, views, favourites),
        )
        conn.commit()


def _seed_wardrobe_sync(
    db_path,
    *,
    platform: str = "vinted",
    finished_at_ms: int | None = None,
    status: str = "ok",
    item_count: int = 1,
) -> None:
    finished = int(time.time() * 1000) if finished_at_ms is None else finished_at_ms
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO wardrobe_syncs(
                platform, started_at, finished_at, status, item_count, error
            ) VALUES (?, ?, ?, ?, ?, NULL)""",
            (platform, finished - 100, finished, status, item_count),
        )
        conn.commit()


def _write_vinted_session(tmp_path, monkeypatch, *, expires_in_s: float = 3600) -> None:
    session_file = tmp_path / "vinted_session.json"
    session_file.write_text(json.dumps({
        "access_token": "tok", "refresh_token": "ref",
        "expires_at": time.time() + expires_in_s,
        "datadome_cookie": "dd", "anon_id": "an",
        "device_uuid": "uu", "device_token": "dt",
        "user_id": "12345",
    }))
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_file))


# ---------- GET /inventory shaping ----------


def test_inventory_empty_db_returns_empty_list(app_client):
    r = app_client.get("/inventory")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"items": [], "last_synced_at": None}


def test_inventory_includes_listing_with_prediction_only(app_client, jpeg_bytes):
    listing_id = _upload(app_client, jpeg_bytes)
    r = app_client.get("/inventory")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["listing_id"] == listing_id
    assert item["thumbnail_url"] == f"/listings/{listing_id}/image"
    assert item["prediction"] is not None
    assert item["vinted"] is None
    assert item["kleinanzeigen"] is None


def test_inventory_includes_publish_state_without_live(app_client, jpeg_bytes):
    """Listing + posted Vinted publish but no wardrobe sync yet → vinted state
    populated, vinted.live=None (we haven't pulled live data)."""
    listing_id = _upload(app_client, jpeg_bytes)
    _seed_posted_publish(app_client.db_path, listing_id, platform_listing_id="555")

    r = app_client.get("/inventory")
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["vinted"]["status"] == "posted"
    assert item["vinted"]["platform_listing_id"] == "555"
    assert item["vinted"]["live"] is None


def test_inventory_joins_wardrobe_snapshot(app_client, jpeg_bytes):
    listing_id = _upload(app_client, jpeg_bytes)
    _seed_posted_publish(app_client.db_path, listing_id, platform_listing_id="777")
    _seed_wardrobe_snapshot(
        app_client.db_path, platform_listing_id="777",
        title="Zara tee", price_eur=15.0, views=99, favourites=3,
    )
    _seed_wardrobe_sync(app_client.db_path, item_count=1)

    r = app_client.get("/inventory")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["last_synced_at"] is not None
    live = body["items"][0]["vinted"]["live"]
    assert live is not None
    assert live["is_sold_or_removed"] is False
    assert live["title"] == "Zara tee"
    assert live["price_eur"] == 15.0
    assert live["views"] == 99
    assert live["favourites"] == 3


def test_inventory_marks_sold_when_missing_from_latest_sync(app_client, jpeg_bytes):
    """Item was published, then a fresh wardrobe sync didn't see it →
    is_sold_or_removed=True. Sold detection requires that the sync ran AFTER
    the publish was last updated."""
    listing_id = _upload(app_client, jpeg_bytes)
    publish_updated = int(time.time() * 1000) - 10_000
    _seed_posted_publish(
        app_client.db_path, listing_id,
        platform_listing_id="999", updated_at_ms=publish_updated,
    )
    # Sync ran 1s ago, after the publish update — but no snapshot for id 999.
    _seed_wardrobe_sync(app_client.db_path, finished_at_ms=int(time.time() * 1000) - 1000)

    r = app_client.get("/inventory")
    assert r.status_code == 200, r.text
    live = r.json()["items"][0]["vinted"]["live"]
    assert live is not None
    assert live["is_sold_or_removed"] is True
    assert live["views"] is None  # no snapshot data


def test_inventory_lazy_refresh_skipped_when_not_configured(app_client, jpeg_bytes, monkeypatch):
    """Vinted not onboarded → GET /inventory must NOT attempt a sync, even if
    cache is stale. The endpoint serves cached data and never errors."""
    listing_id = _upload(app_client, jpeg_bytes)
    _seed_posted_publish(app_client.db_path, listing_id)

    called = {"n": 0}

    async def boom():
        called["n"] += 1
        raise AssertionError("fetch_wardrobe should not be called when not configured")

    monkeypatch.setattr(
        "backend.routes.inventory.vinted_integration.fetch_wardrobe", boom
    )
    r = app_client.get("/inventory")
    assert r.status_code == 200
    assert called["n"] == 0


# ---------- POST /inventory/sync ----------


def test_sync_endpoint_409_when_not_onboarded(app_client):
    r = app_client.post("/inventory/sync")
    assert r.status_code == 409
    assert "onboarded" in r.json()["detail"].lower()


def test_sync_endpoint_writes_snapshots(app_client, jpeg_bytes, monkeypatch, tmp_path):
    _write_vinted_session(tmp_path, monkeypatch)

    fake_items = [
        {
            "id": 111,
            "title": "Black tee",
            "price": {"amount": "8.50", "currency_code": "EUR"},
            "view_count": 12, "favourite_count": 1,
            "url": "https://www.vinted.fr/items/111",
            "photos": [{"url": "https://photo.cdn/111.jpg"}],
        },
        {
            "id": 222,
            "title": "Levi 501",
            "price": {"amount": "29.00", "currency_code": "EUR"},
            "view_count": 80, "favourite_count": 9,
            "url": "https://www.vinted.fr/items/222",
            "photos": [{"url": "https://photo.cdn/222.jpg"}],
        },
    ]

    async def fake_fetch():
        return fake_items

    monkeypatch.setattr(
        "backend.routes.inventory.vinted_integration.fetch_wardrobe", fake_fetch
    )

    r = app_client.post("/inventory/sync")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["platform"] == "vinted"
    assert body["item_count"] == 2

    with sqlite3.connect(app_client.db_path) as conn:
        snaps = conn.execute(
            "SELECT platform_listing_id, title, views FROM wardrobe_snapshots ORDER BY id"
        ).fetchall()
        assert snaps == [("111", "Black tee", 12), ("222", "Levi 501", 80)]
        sync_status = conn.execute(
            "SELECT status, item_count FROM wardrobe_syncs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert sync_status == ("ok", 2)


def test_sync_endpoint_records_error_row_on_transport_failure(app_client, monkeypatch, tmp_path):
    _write_vinted_session(tmp_path, monkeypatch)

    async def fake_fetch():
        raise RuntimeError("network down")

    monkeypatch.setattr(
        "backend.routes.inventory.vinted_integration.fetch_wardrobe", fake_fetch
    )

    r = app_client.post("/inventory/sync")
    assert r.status_code == 502

    with sqlite3.connect(app_client.db_path) as conn:
        sync_row = conn.execute(
            "SELECT status, error FROM wardrobe_syncs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert sync_row[0] == "error"
        assert "network down" in (sync_row[1] or "")


def test_sync_lazy_refresh_inside_get_inventory(app_client, jpeg_bytes, monkeypatch, tmp_path):
    """When Vinted is configured and no sync has ever run, GET /inventory
    triggers one inline."""
    _write_vinted_session(tmp_path, monkeypatch)
    listing_id = _upload(app_client, jpeg_bytes)
    _seed_posted_publish(app_client.db_path, listing_id, platform_listing_id="42")

    async def fake_fetch():
        return [{
            "id": 42, "title": "Found item",
            "price": {"amount": "20.0", "currency_code": "EUR"},
            "view_count": 5, "favourite_count": 0,
            "url": "https://www.vinted.fr/items/42",
            "photos": [],
        }]

    monkeypatch.setattr(
        "backend.routes.inventory.vinted_integration.fetch_wardrobe", fake_fetch
    )

    r = app_client.get("/inventory")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["last_synced_at"] is not None
    live = body["items"][0]["vinted"]["live"]
    assert live is not None and live["title"] == "Found item"


# ---------- GET /listings/{id}/image ----------


def test_image_endpoint_returns_jpeg_for_known_listing(app_client, jpeg_bytes):
    listing_id = _upload(app_client, jpeg_bytes)
    r = app_client.get(f"/listings/{listing_id}/image")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/jpeg"
    assert len(r.content) > 0


def test_image_endpoint_404_for_unknown_listing(app_client):
    r = app_client.get("/listings/deadbeef/image")
    assert r.status_code == 404


# ---------- pricing-drift overlay ----------


def _upload_and_band(client, jpeg_bytes) -> tuple[str, dict]:
    """POST /upload, return (listing_id, vinted_price_band) so pricing tests
    can pick wardrobe prices relative to the model's predicted band."""
    r = client.post("/upload", files={"image": ("hero.jpg", jpeg_bytes, "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["listing_id"], body["vinted"]["price"]


def test_pricing_status_ok_when_inside_band(app_client, jpeg_bytes):
    listing_id, band = _upload_and_band(app_client, jpeg_bytes)
    _seed_posted_publish(app_client.db_path, listing_id, platform_listing_id="1")
    _seed_wardrobe_snapshot(
        app_client.db_path, platform_listing_id="1", price_eur=band["q50"],
    )
    _seed_wardrobe_sync(app_client.db_path)

    live = app_client.get("/inventory").json()["items"][0]["vinted"]["live"]
    assert live["pricing_status"] == "ok"
    assert live["delta_vs_q50_pct"] == 0.0


def test_pricing_status_underpriced_when_below_q10(app_client, jpeg_bytes):
    listing_id, band = _upload_and_band(app_client, jpeg_bytes)
    cheap = max(band["q10"] - 1.0, 0.01)
    _seed_posted_publish(app_client.db_path, listing_id, platform_listing_id="2")
    _seed_wardrobe_snapshot(
        app_client.db_path, platform_listing_id="2", price_eur=cheap,
    )
    _seed_wardrobe_sync(app_client.db_path)

    live = app_client.get("/inventory").json()["items"][0]["vinted"]["live"]
    assert live["pricing_status"] == "underpriced"
    assert live["delta_vs_q50_pct"] is not None
    assert live["delta_vs_q50_pct"] < 0


def test_pricing_status_overpriced_when_above_q90(app_client, jpeg_bytes):
    listing_id, band = _upload_and_band(app_client, jpeg_bytes)
    expensive = band["q90"] + 5.0
    _seed_posted_publish(app_client.db_path, listing_id, platform_listing_id="3")
    _seed_wardrobe_snapshot(
        app_client.db_path, platform_listing_id="3", price_eur=expensive,
    )
    _seed_wardrobe_sync(app_client.db_path)

    live = app_client.get("/inventory").json()["items"][0]["vinted"]["live"]
    assert live["pricing_status"] == "overpriced"
    assert live["delta_vs_q50_pct"] > 0


def test_pricing_status_unknown_when_no_live_price(app_client, jpeg_bytes):
    """Sold/removed items have no live price → pricing_status is 'unknown',
    delta is null. Frontend can fall through that case cleanly."""
    listing_id = _upload(app_client, jpeg_bytes)
    publish_updated = int(time.time() * 1000) - 10_000
    _seed_posted_publish(
        app_client.db_path, listing_id,
        platform_listing_id="4", updated_at_ms=publish_updated,
    )
    _seed_wardrobe_sync(app_client.db_path, finished_at_ms=int(time.time() * 1000) - 1000)

    live = app_client.get("/inventory").json()["items"][0]["vinted"]["live"]
    assert live["is_sold_or_removed"] is True
    assert live["pricing_status"] == "unknown"
    assert live["delta_vs_q50_pct"] is None


# ---------- GET /inventory/summary ----------


def test_summary_empty_db(app_client):
    r = app_client.get("/inventory/summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["total"] == 0
    assert body["counts"]["unpublished"] == 0
    assert body["counts"]["posted"] == 0
    assert body["estimated_value_eur"] == 0.0
    assert body["live_views"] == 0
    assert body["live_favourites"] == 0
    assert body["last_synced_at"] is None


def test_summary_counts_unpublished_listings(app_client, jpeg_bytes):
    _upload(app_client, jpeg_bytes)
    _upload(app_client, jpeg_bytes)
    body = app_client.get("/inventory/summary").json()
    assert body["counts"]["total"] == 2
    assert body["counts"]["unpublished"] == 2
    assert body["counts"]["posted"] == 0


def test_summary_aggregates_value_and_engagement(app_client, jpeg_bytes):
    """Two posted Vinted items with snapshots → estimated_value_eur sums q50,
    live_views and live_favourites sum across snapshots."""
    a, band_a = _upload_and_band(app_client, jpeg_bytes)
    b, band_b = _upload_and_band(app_client, jpeg_bytes)
    _seed_posted_publish(app_client.db_path, a, platform_listing_id="aaa")
    _seed_posted_publish(app_client.db_path, b, platform_listing_id="bbb")
    _seed_wardrobe_snapshot(
        app_client.db_path, platform_listing_id="aaa",
        price_eur=band_a["q50"], views=10, favourites=2,
    )
    _seed_wardrobe_snapshot(
        app_client.db_path, platform_listing_id="bbb",
        price_eur=band_b["q50"], views=30, favourites=4,
    )
    _seed_wardrobe_sync(app_client.db_path, item_count=2)

    body = app_client.get("/inventory/summary").json()
    assert body["counts"]["posted"] == 2
    assert body["counts"]["sold_or_removed"] == 0
    expected_value = round(band_a["q50"] + band_b["q50"], 2)
    assert body["estimated_value_eur"] == expected_value
    assert body["live_views"] == 40
    assert body["live_favourites"] == 6


def test_summary_excludes_sold_from_value_and_engagement(app_client, jpeg_bytes):
    """A sold/removed item still counts in `sold_or_removed` but its q50
    must not inflate estimated_value_eur and its (absent) views must not
    contribute to live_views."""
    listing_id, band = _upload_and_band(app_client, jpeg_bytes)
    publish_updated = int(time.time() * 1000) - 10_000
    _seed_posted_publish(
        app_client.db_path, listing_id,
        platform_listing_id="ccc", updated_at_ms=publish_updated,
    )
    _seed_wardrobe_sync(app_client.db_path, finished_at_ms=int(time.time() * 1000) - 1000)

    body = app_client.get("/inventory/summary").json()
    assert body["counts"]["sold_or_removed"] == 1
    assert body["counts"]["posted"] == 0
    assert body["estimated_value_eur"] == 0.0
    assert body["live_views"] == 0


def test_summary_priority_posted_beats_failed(app_client, jpeg_bytes):
    """A listing posted on Vinted AND failed on KA → bucket = 'posted'.
    Priority order ensures the user sees the dominant active state."""
    listing_id = _upload(app_client, jpeg_bytes)
    _seed_posted_publish(app_client.db_path, listing_id, platform="vinted",
                         platform_listing_id="ddd")
    # Seed a KA failure directly.
    with sqlite3.connect(app_client.db_path) as conn:
        conn.execute(
            """INSERT INTO publishes(
                listing_id, created_at, platform, final_fields, prefill_url,
                status, retry_count, next_attempt_at, error, updated_at
            ) VALUES (?, ?, 'kleinanzeigen', '{}', '', 'failed', 1, NULL, 'KA failed', ?)""",
            (listing_id, int(time.time() * 1000), int(time.time() * 1000)),
        )
        conn.commit()

    body = app_client.get("/inventory/summary").json()
    assert body["counts"]["posted"] == 1
    assert body["counts"]["failed"] == 0


def test_summary_includes_pricing_classification_in_inventory_response(app_client, jpeg_bytes):
    """End-to-end: pricing overlay surfaces in GET /inventory so the FE can
    render badges per-card without recomputing thresholds."""
    listing_id, band = _upload_and_band(app_client, jpeg_bytes)
    _seed_posted_publish(app_client.db_path, listing_id, platform_listing_id="eee")
    _seed_wardrobe_snapshot(
        app_client.db_path, platform_listing_id="eee", price_eur=band["q50"],
    )
    _seed_wardrobe_sync(app_client.db_path)

    items = app_client.get("/inventory").json()["items"]
    live = items[0]["vinted"]["live"]
    assert "pricing_status" in live
    assert live["pricing_status"] in {"underpriced", "ok", "overpriced", "unknown"}
