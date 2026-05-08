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


def test_publish_vinted_not_configured_falls_back(app_client, jpeg_bytes):
    """Without VINTED_SESSION_PATH set, /publish returns the new-listing URL
    with posted=false and no error (it's not a failure, just not set up)."""
    listing_id = _upload(app_client, jpeg_bytes)
    status, body = _publish(app_client, listing_id, "vinted", {
        "brand": "Zara", "title": "Tee", "description": "..."
    })
    assert status == 200
    assert body["posted"] is False
    assert body["platform_listing_url"] is None
    assert body["error"] is None
    assert body["prefill_url"] == "https://www.vinted.de/items/new"


def test_publish_kleinanzeigen_reports_not_implemented(app_client, jpeg_bytes):
    """KA always falls back in 6a but the response's error field says why."""
    listing_id = _upload(app_client, jpeg_bytes)
    status, body = _publish(app_client, listing_id, "kleinanzeigen", {
        "brand": "Zara", "title": "Tee", "description": "..."
    })
    assert status == 200
    assert body["posted"] is False
    assert body["error"] is not None
    assert "phase 6c" in body["error"].lower() or "not implemented" in body["error"].lower()


def test_publish_vinted_real_success(app_client, jpeg_bytes, monkeypatch, tmp_path):
    """When VINTED_SESSION_PATH is set and the integration succeeds, the
    response includes the live listing URL and posted=true."""
    session_file = tmp_path / "vinted.json"
    session_file.write_text("{}")  # is_configured only checks existence
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_file))

    async def fake_publish(image_path, payload):
        assert payload["catalog_id"] == 221  # tshirts → Damen T-Shirts
        assert payload["condition_id"] == 2  # Very good
        return 1234567890, "https://www.vinted.fr/items/1234567890"

    monkeypatch.setattr("backend.routes.publish.vinted_integration.publish", fake_publish)

    listing_id = _upload(app_client, jpeg_bytes)
    status, body = _publish(app_client, listing_id, "vinted", {
        "category": "tshirts",
        "condition": "Very good",
        "brand": "Zara",
        "title": "Zara T-shirt",
        "description": "A nice tee.",
        "price_eur": 10.0,
    })
    assert status == 200
    assert body["posted"] is True
    assert body["platform_listing_id"] == "1234567890"
    assert body["platform_listing_url"] == "https://www.vinted.fr/items/1234567890"
    assert body["prefill_url"] == "https://www.vinted.fr/items/1234567890"
    assert body["error"] is None


def test_publish_vinted_real_failure_falls_back(app_client, jpeg_bytes, monkeypatch, tmp_path):
    """When the Vinted integration raises, /publish falls back to the URL
    with posted=false and a populated error string. Never 5xx."""
    from backend.integrations.vinted import VintedBlocked

    session_file = tmp_path / "vinted.json"
    session_file.write_text("{}")
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_file))

    async def fake_publish(image_path, payload):
        raise VintedBlocked("draft create: DataDome blocked at status 429")

    monkeypatch.setattr("backend.routes.publish.vinted_integration.publish", fake_publish)

    listing_id = _upload(app_client, jpeg_bytes)
    status, body = _publish(app_client, listing_id, "vinted", {
        "category": "tshirts",
        "condition": "Very good",
        "title": "Zara T-shirt",
        "description": "A nice tee.",
        "price_eur": 10.0,
    })
    assert status == 200
    assert body["posted"] is False
    assert body["platform_listing_url"] is None
    assert body["error"] is not None
    assert "datadome" in body["error"].lower()
    assert body["prefill_url"] == "https://www.vinted.de/items/new"


def test_publish_vinted_unmapped_category_falls_back(app_client, jpeg_bytes, monkeypatch, tmp_path):
    """When the canon category has no Vinted catalog mapping, surface a clear
    error rather than calling the API with a missing catalog_id."""
    session_file = tmp_path / "vinted.json"
    session_file.write_text("{}")
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_file))

    async def fake_publish(image_path, payload):
        raise AssertionError("integration should not be called when catalog_id is missing")

    monkeypatch.setattr("backend.routes.publish.vinted_integration.publish", fake_publish)

    listing_id = _upload(app_client, jpeg_bytes)
    status, body = _publish(app_client, listing_id, "vinted", {
        "category": "scarves",  # not in VINTED_CATEGORY_TO_CATALOG_ID
        "title": "x", "description": "y", "price_eur": 5.0,
    })
    assert status == 200
    assert body["posted"] is False
    assert body["error"] is not None
    assert "catalog" in body["error"].lower()
