"""Unit tests for backend.queue.runner.

Cover the FSM transitions and error classification with a mocked Vinted
integration. Backoff is collapsed to zero so tests don't sleep.
"""

from __future__ import annotations

import asyncio


def test_classify_error_retryable_vs_permanent():
    from backend.integrations.vinted import (
        VintedAuthExpired, VintedBlocked, VintedError, VintedNotConfigured,
    )
    from backend.queue.runner import classify_error

    assert classify_error(VintedBlocked("429")) == "retryable"
    assert classify_error(asyncio.TimeoutError()) == "retryable"
    assert classify_error(VintedAuthExpired("401")) == "permanent"
    assert classify_error(VintedNotConfigured("missing")) == "permanent"
    # Generic VintedError with HTTP 5xx text → retryable
    assert classify_error(VintedError("draft create: HTTP 503 — gateway")) == "retryable"
    # Generic VintedError with HTTP 4xx (validation) → permanent
    assert classify_error(VintedError("draft create: HTTP 400 — validation_error")) == "permanent"


def test_runner_returns_false_when_queue_empty(app_client):
    """process_one_job returns False when nothing is pending so the loop
    can sleep instead of busy-waiting."""
    from backend.queue.runner import PublishRunner

    runner = PublishRunner()
    result = asyncio.run(runner.process_one_job())
    assert result is False


def test_runner_keeps_retry_count_under_budget(app_client, jpeg_bytes, monkeypatch, tmp_path):
    """Three failures with backoff schedule of length 3 → fail terminal,
    retry_count=3, integration called 4 times (initial + 3 retries)."""
    from backend.integrations.vinted import VintedBlocked
    from backend.queue.runner import PublishRunner

    session_file = tmp_path / "vinted.json"
    session_file.write_text("{}")
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_file))

    call_count = {"n": 0}

    async def always_blocked(image_path, payload):
        call_count["n"] += 1
        raise VintedBlocked("DataDome 429")

    monkeypatch.setattr("backend.queue.runner.vinted_integration.publish", always_blocked)

    # Seed a job
    upload = app_client.post("/upload", files={"image": ("hero.jpg", jpeg_bytes, "image/jpeg")})
    listing_id = upload.json()["listing_id"]
    enq = app_client.post("/publish", json={
        "listing_id": listing_id, "platform": "vinted",
        "final_fields": {
            "category": "tshirts", "condition": "Very good", "brand": "X",
            "title": "X", "description": "Y", "price_eur": 5.0,
        },
    })
    job_id = enq.json()["job_id"]

    runner = PublishRunner(backoff_schedule=(0.0, 0.0, 0.0))

    async def _drain():
        while await runner.process_one_job():
            pass

    asyncio.run(_drain())

    final = app_client.get(f"/publish/status/{job_id}").json()
    assert final["status"] == "failed"
    assert final["retry_count"] == 3
    assert call_count["n"] == 4  # 1 initial + 3 retries


def test_runner_records_next_attempt_at_after_retry(app_client, jpeg_bytes, monkeypatch, tmp_path):
    """After a single retryable failure, the job should be 'pending' again
    with retry_count=1 and next_attempt_at set."""
    from backend.integrations.vinted import VintedBlocked
    from backend.queue.runner import PublishRunner

    session_file = tmp_path / "vinted.json"
    session_file.write_text("{}")
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_file))

    async def always_blocked(image_path, payload):
        raise VintedBlocked("DataDome 429")

    monkeypatch.setattr("backend.queue.runner.vinted_integration.publish", always_blocked)

    upload = app_client.post("/upload", files={"image": ("hero.jpg", jpeg_bytes, "image/jpeg")})
    listing_id = upload.json()["listing_id"]
    enq = app_client.post("/publish", json={
        "listing_id": listing_id, "platform": "vinted",
        "final_fields": {
            "category": "tshirts", "condition": "Very good", "brand": "X",
            "title": "X", "description": "Y", "price_eur": 5.0,
        },
    })
    job_id = enq.json()["job_id"]

    # Backoff long enough that the second attempt isn't yet eligible
    runner = PublishRunner(backoff_schedule=(60.0, 60.0, 60.0))
    asyncio.run(runner.process_one_job())  # first attempt → fails → schedules retry

    intermediate = app_client.get(f"/publish/status/{job_id}").json()
    assert intermediate["status"] == "pending"
    assert intermediate["retry_count"] == 1
    assert intermediate["next_attempt_at"] is not None
    # Second process_one_job should be a no-op (next_attempt_at is in the future)
    did_work = asyncio.run(runner.process_one_job())
    assert did_work is False
