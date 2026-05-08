"""Round-trip + edge-case tests for POST /publish (stub VLM)."""

from __future__ import annotations

import json
import sqlite3


def _upload(client, jpeg_bytes) -> str:
    r = client.post("/upload", files={"image": ("hero.jpg", jpeg_bytes, "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()["listing_id"]


def _publish(client, listing_id: str, platform: str, final_fields: dict) -> tuple[int, dict]:
    r = client.post(
        "/publish",
        json={"listing_id": listing_id, "platform": platform, "final_fields": final_fields},
    )
    return r.status_code, r.json() if r.status_code == 200 else {"detail": r.text}


def test_publish_vinted_returns_new_listing_url(app_client, jpeg_bytes):
    listing_id = _upload(app_client, jpeg_bytes)
    status, body = _publish(app_client, listing_id, "vinted", {
        "brand": "Zara", "title": "Tee", "description": "..."
    })
    assert status == 200
    assert body["platform"] == "vinted"
    assert body["prefill_url"] == "https://www.vinted.de/items/new"


def test_publish_kleinanzeigen_returns_new_listing_url(app_client, jpeg_bytes):
    listing_id = _upload(app_client, jpeg_bytes)
    status, body = _publish(app_client, listing_id, "kleinanzeigen", {
        "brand": "Zara", "title": "Tee", "description": "..."
    })
    assert status == 200
    assert body["platform"] == "kleinanzeigen"
    assert body["prefill_url"] == "https://www.kleinanzeigen.de/p-anzeige-aufgeben.html"


def test_publish_missing_listing_returns_404(app_client):
    status, body = _publish(app_client, "deadbeef", "vinted", {
        "brand": "X", "title": "t", "description": "d"
    })
    assert status == 404
    assert "not found" in body["detail"].lower()


def test_publish_persists_canonical_english_fields(app_client, jpeg_bytes):
    """publishes.final_fields stores the request's canonical English fields
    verbatim, so analytics can re-derive any platform-native mapping later."""
    listing_id = _upload(app_client, jpeg_bytes)
    final = {"brand": "Zara", "size": "M", "title": "Zara t-shirt", "description": "..."}
    _publish(app_client, listing_id, "vinted", final)

    conn = sqlite3.connect(app_client.db_path)
    row = conn.execute(
        "SELECT final_fields, prefill_url FROM publishes WHERE listing_id = ?",
        (listing_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    stored = json.loads(row[0])
    assert stored["brand"] == "Zara"
    assert stored["size"] == "M"
    assert stored["title"] == "Zara t-shirt"
    assert row[1] == "https://www.vinted.de/items/new"


def test_publish_supports_both_platforms_for_same_listing(app_client, jpeg_bytes):
    """User may publish the same item to both platforms — both rows persist
    with distinct platform values."""
    listing_id = _upload(app_client, jpeg_bytes)
    fields = {"brand": "Zara", "title": "t", "description": "d"}
    _publish(app_client, listing_id, "vinted", fields)
    _publish(app_client, listing_id, "kleinanzeigen", fields)

    conn = sqlite3.connect(app_client.db_path)
    platforms = sorted(
        row[0]
        for row in conn.execute("SELECT platform FROM publishes WHERE listing_id = ?", (listing_id,))
    )
    conn.close()
    assert platforms == ["kleinanzeigen", "vinted"]


def test_publish_preserves_null_fields_in_log(app_client, jpeg_bytes):
    """Optional fields (brand, color, size, etc.) may be null after editing —
    the stored JSON keeps the null instead of dropping the key."""
    listing_id = _upload(app_client, jpeg_bytes)
    final = {"brand": None, "color": None, "title": "Tee", "description": "..."}
    status, _ = _publish(app_client, listing_id, "vinted", final)
    assert status == 200

    conn = sqlite3.connect(app_client.db_path)
    stored_json = conn.execute(
        "SELECT final_fields FROM publishes WHERE listing_id = ?", (listing_id,)
    ).fetchone()[0]
    conn.close()
    stored = json.loads(stored_json)
    assert stored["brand"] is None
    assert stored["color"] is None
    assert stored["title"] == "Tee"
