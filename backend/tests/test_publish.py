"""Async /publish round-trip tests.

POST /publish enqueues a job and returns 202 with {job_id, status:'pending'}.
Tests then drive the runner once via the `drain_publish_jobs` fixture and
read the terminal state via GET /publish/status/{job_id} (or directly from
the publishes table for stronger assertions).
"""

from __future__ import annotations

import json
import sqlite3


def _upload(client, jpeg_bytes) -> str:
    r = client.post("/upload", files={"image": ("hero.jpg", jpeg_bytes, "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()["listing_id"]


def _enqueue(client, listing_id: str, platform: str, final_fields: dict) -> tuple[int, dict]:
    r = client.post(
        "/publish",
        json={"listing_id": listing_id, "platform": platform, "final_fields": final_fields},
    )
    return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"detail": r.text}


def _status(client, job_id: int) -> dict:
    r = client.get(f"/publish/status/{job_id}")
    assert r.status_code == 200, r.text
    return r.json()


def test_publish_enqueues_pending_job(app_client, jpeg_bytes):
    """POST /publish returns 202 with a job_id; the publishes row is in
    'pending' state and the integration hasn't been called yet."""
    listing_id = _upload(app_client, jpeg_bytes)
    status, body = _enqueue(app_client, listing_id, "vinted", {
        "category": "tshirts", "title": "Tee", "description": "...", "price_eur": 5.0
    })
    assert status == 202
    assert body["status"] == "pending"
    assert body["platform"] == "vinted"
    assert body["listing_id"] == listing_id
    assert isinstance(body["job_id"], int)

    job = _status(app_client, body["job_id"])
    assert job["status"] == "pending"
    assert job["retry_count"] == 0
    assert job["platform_listing_id"] is None


def test_status_unknown_job_404(app_client):
    r = app_client.get("/publish/status/999999")
    assert r.status_code == 404


def test_publish_missing_listing_returns_404(app_client):
    status, body = _enqueue(app_client, "deadbeef", "vinted", {
        "title": "x", "description": "y", "price_eur": 5.0
    })
    assert status == 404
    assert "not found" in body["detail"].lower()


def test_runner_marks_unconfigured_failed(app_client, jpeg_bytes, drain_publish_jobs):
    """No VINTED_SESSION_PATH → runner picks up the job and marks it failed
    with a clear error string. (Not a graceful pending state — there's
    nothing to retry waiting for.)"""
    listing_id = _upload(app_client, jpeg_bytes)
    _, body = _enqueue(app_client, listing_id, "vinted", {
        "category": "tshirts", "title": "Tee", "description": "...", "price_eur": 5.0
    })
    drain_publish_jobs()

    job = _status(app_client, body["job_id"])
    assert job["status"] == "failed"
    assert "configured" in (job["error"] or "").lower()


def test_runner_marks_kleinanzeigen_unconfigured_failed(app_client, jpeg_bytes, drain_publish_jobs):
    """No KA_SESSION_PATH → runner fails the job with a clear setup-hint error."""
    listing_id = _upload(app_client, jpeg_bytes)
    _, body = _enqueue(app_client, listing_id, "kleinanzeigen", {
        "category": "tshirts", "title": "Tee", "description": "...", "price_eur": 5.0
    })
    drain_publish_jobs()

    job = _status(app_client, body["job_id"])
    assert job["status"] == "failed"
    assert "ka_session_path" in (job["error"] or "").lower()


def test_runner_posts_kleinanzeigen_successfully(app_client, jpeg_bytes, drain_publish_jobs, monkeypatch, tmp_path):
    """Configured KA + integration succeeds → terminal status='posted'
    with platform_listing_id and platform_listing_url populated."""
    session_file = tmp_path / "ka.json"
    session_file.write_text("{}")
    monkeypatch.setenv("KA_SESSION_PATH", str(session_file))

    async def fake_publish(image_path, payload):
        assert payload["category_id"] == 160       # Men's clothing → Herrenbekleidung
        assert payload["title"] == "Olive You T-Shirt"
        assert payload["price_eur"] == 8.0
        return 2929292929, "https://www.kleinanzeigen.de/s-anzeige/2929292929"

    monkeypatch.setattr("backend.queue.runner.ka_integration.publish", fake_publish)

    listing_id = _upload(app_client, jpeg_bytes)
    _, body = _enqueue(app_client, listing_id, "kleinanzeigen", {
        "category": "Men's clothing", "condition": "Very good",
        "title": "Olive You T-Shirt", "description": "Cotton tee, size M.",
        "price_eur": 8.0,
    })
    drain_publish_jobs()

    job = _status(app_client, body["job_id"])
    assert job["status"] == "posted"
    assert job["platform_listing_id"] == "2929292929"
    assert job["platform_listing_url"] == "https://www.kleinanzeigen.de/s-anzeige/2929292929"


def test_runner_kleinanzeigen_unmapped_category_falls_back(app_client, jpeg_bytes, drain_publish_jobs, monkeypatch, tmp_path):
    """sneakers has no KA category mapping → runner short-circuits without
    calling the integration."""
    session_file = tmp_path / "ka.json"
    session_file.write_text("{}")
    monkeypatch.setenv("KA_SESSION_PATH", str(session_file))

    async def fake_publish(image_path, payload):
        raise AssertionError("integration should not be called when category_id is missing")

    monkeypatch.setattr("backend.queue.runner.ka_integration.publish", fake_publish)

    listing_id = _upload(app_client, jpeg_bytes)
    _, body = _enqueue(app_client, listing_id, "kleinanzeigen", {
        "category": "sneakers",  # not mapped for KA
        "title": "x", "description": "y", "price_eur": 5.0,
    })
    drain_publish_jobs()

    job = _status(app_client, body["job_id"])
    assert job["status"] == "failed"
    assert "category" in (job["error"] or "").lower()


def test_runner_marks_unmapped_category_failed(app_client, jpeg_bytes, drain_publish_jobs, monkeypatch, tmp_path):
    """Configured Vinted but the canon category has no Vinted catalog mapping
    → runner fails immediately rather than calling the API with a bad payload."""
    session_file = tmp_path / "vinted.json"
    session_file.write_text("{}")
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_file))

    async def fake_publish(image_path, payload):
        raise AssertionError("integration should not be called when catalog_id is missing")

    monkeypatch.setattr("backend.queue.runner.vinted_integration.publish", fake_publish)

    listing_id = _upload(app_client, jpeg_bytes)
    _, body = _enqueue(app_client, listing_id, "vinted", {
        "category": "scarves",
        "title": "x", "description": "y", "price_eur": 5.0,
    })
    drain_publish_jobs()

    job = _status(app_client, body["job_id"])
    assert job["status"] == "failed"
    assert "catalog" in (job["error"] or "").lower()


def test_runner_posts_successfully(app_client, jpeg_bytes, drain_publish_jobs, monkeypatch, tmp_path):
    """Configured Vinted + integration succeeds → terminal status='posted'
    with platform_listing_id and platform_listing_url populated."""
    session_file = tmp_path / "vinted.json"
    session_file.write_text("{}")
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_file))

    async def fake_publish(image_path, payload):
        assert payload["catalog_id"] == 221
        assert payload["condition_id"] == 2
        return 1234567890, "https://www.vinted.com/items/1234567890"

    monkeypatch.setattr("backend.queue.runner.vinted_integration.publish", fake_publish)

    listing_id = _upload(app_client, jpeg_bytes)
    _, body = _enqueue(app_client, listing_id, "vinted", {
        "category": "tshirts", "condition": "Very good", "brand": "Zara",
        "title": "Zara T-shirt", "description": "A nice tee.", "price_eur": 10.0,
    })
    drain_publish_jobs()

    job = _status(app_client, body["job_id"])
    assert job["status"] == "posted"
    assert job["platform_listing_id"] == "1234567890"
    assert job["platform_listing_url"] == "https://www.vinted.com/items/1234567890"
    assert job["error"] is None


def test_runner_retries_on_blocked_then_succeeds(app_client, jpeg_bytes, drain_publish_jobs, monkeypatch, tmp_path):
    """Transient VintedBlocked (DataDome 429) → job goes pending again with
    retry_count++; eventually succeeds when the integration stops failing."""
    from backend.integrations.vinted import VintedBlocked

    session_file = tmp_path / "vinted.json"
    session_file.write_text("{}")
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_file))

    call_count = {"n": 0}

    async def fake_publish(image_path, payload):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise VintedBlocked(f"draft create: DataDome blocked at status 429")
        return 9999, "https://www.vinted.com/items/9999"

    monkeypatch.setattr("backend.queue.runner.vinted_integration.publish", fake_publish)

    listing_id = _upload(app_client, jpeg_bytes)
    _, body = _enqueue(app_client, listing_id, "vinted", {
        "category": "tshirts", "condition": "Very good", "brand": "Zara",
        "title": "Zara T-shirt", "description": "A nice tee.", "price_eur": 10.0,
    })
    # Backoff = 0,0,0 in the test fixture so retries fire immediately
    drain_publish_jobs()

    job = _status(app_client, body["job_id"])
    assert job["status"] == "posted"
    assert job["retry_count"] == 2
    assert call_count["n"] == 3


def test_runner_gives_up_on_permanent_error_first_try(app_client, jpeg_bytes, drain_publish_jobs, monkeypatch, tmp_path):
    """VintedAuthExpired is permanent — runner fails immediately, no retry."""
    from backend.integrations.vinted import VintedAuthExpired

    session_file = tmp_path / "vinted.json"
    session_file.write_text("{}")
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_file))

    call_count = {"n": 0}

    async def fake_publish(image_path, payload):
        call_count["n"] += 1
        raise VintedAuthExpired("refresh failed: 401")

    monkeypatch.setattr("backend.queue.runner.vinted_integration.publish", fake_publish)

    listing_id = _upload(app_client, jpeg_bytes)
    _, body = _enqueue(app_client, listing_id, "vinted", {
        "category": "tshirts", "condition": "Very good", "brand": "Zara",
        "title": "Zara T-shirt", "description": "A nice tee.", "price_eur": 10.0,
    })
    drain_publish_jobs()

    job = _status(app_client, body["job_id"])
    assert job["status"] == "failed"
    assert job["retry_count"] == 0
    assert call_count["n"] == 1
    assert "expired" in (job["error"] or "").lower() or "401" in (job["error"] or "")


def test_persisted_canonical_fields(app_client, jpeg_bytes):
    """publishes.final_fields stores the request's canonical English fields
    verbatim, including nulls."""
    listing_id = _upload(app_client, jpeg_bytes)
    final = {"brand": None, "color": None, "title": "Tee", "description": "..."}
    _, body = _enqueue(app_client, listing_id, "vinted", final)

    conn = sqlite3.connect(app_client.db_path)
    stored = json.loads(conn.execute(
        "SELECT final_fields FROM publishes WHERE id = ?", (body["job_id"],)
    ).fetchone()[0])
    conn.close()
    assert stored["brand"] is None
    assert stored["title"] == "Tee"


def test_supports_both_platforms_for_same_listing(app_client, jpeg_bytes):
    """User may enqueue publish jobs for both platforms on the same listing —
    both rows persist with distinct platform values and unique job_ids."""
    listing_id = _upload(app_client, jpeg_bytes)
    fields = {"title": "t", "description": "d", "price_eur": 5.0}
    _, b1 = _enqueue(app_client, listing_id, "vinted", fields)
    _, b2 = _enqueue(app_client, listing_id, "kleinanzeigen", fields)
    assert b1["job_id"] != b2["job_id"]

    conn = sqlite3.connect(app_client.db_path)
    platforms = sorted(
        row[0]
        for row in conn.execute("SELECT platform FROM publishes WHERE listing_id = ?", (listing_id,))
    )
    conn.close()
    assert platforms == ["kleinanzeigen", "vinted"]


# ---------- DELETE /publish/{platform}/{platform_listing_id} ----------


def test_delete_listing_vinted_success(app_client, monkeypatch, tmp_path):
    session_file = tmp_path / "vinted.json"
    session_file.write_text("{}")
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_file))

    called_with = []

    async def fake_delete(item_id):
        called_with.append(item_id)

    monkeypatch.setattr("backend.routes.publish.vinted_integration.delete_listing", fake_delete)

    r = app_client.delete("/publish/vinted/8858700111")
    assert r.status_code == 204
    assert called_with == ["8858700111"]


def test_delete_listing_vinted_not_configured(app_client):
    r = app_client.delete("/publish/vinted/8858700111")
    assert r.status_code == 503


def test_delete_listing_vinted_not_found(app_client, monkeypatch, tmp_path):
    from backend.integrations.vinted import VintedError

    session_file = tmp_path / "vinted.json"
    session_file.write_text("{}")
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_file))

    async def fake_delete(item_id):
        raise VintedError(f"delete: item {item_id} not found")

    monkeypatch.setattr("backend.routes.publish.vinted_integration.delete_listing", fake_delete)

    r = app_client.delete("/publish/vinted/9999999999")
    assert r.status_code == 404


def test_delete_listing_kleinanzeigen_returns_501(app_client):
    r = app_client.delete("/publish/kleinanzeigen/abc")
    assert r.status_code == 501
