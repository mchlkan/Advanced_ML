"""Round-trip + edge-case tests for POST /verify (stub VLM)."""

from __future__ import annotations

import sqlite3


def _upload(client, jpeg_bytes) -> dict:
    r = client.post("/upload", files={"image": ("hero.jpg", jpeg_bytes, "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()


def _verify(client, listing_id: str, hints: dict) -> tuple[int, dict]:
    r = client.post("/verify", json={"listing_id": listing_id, "hints": hints})
    return r.status_code, r.json() if r.status_code == 200 else {"detail": r.text}


def test_verify_overlays_hints_on_both_platforms(app_client, jpeg_bytes):
    """User says brand=Zara → both vinted and ka identification reflect it,
    even if the stub VLM would have emitted something else."""
    listing_id = _upload(app_client, jpeg_bytes)["listing_id"]
    status, body = _verify(app_client, listing_id, {"brand": "Zara", "size": "M"})
    assert status == 200
    assert body["revised"] is True
    for plat in ("vinted", "kleinanzeigen"):
        assert body[plat]["identification"]["brand"] == "Zara"
        assert body[plat]["identification"]["size"] == "M"


def test_verify_missing_listing_returns_404(app_client):
    status, body = _verify(app_client, "not-a-real-id", {"brand": "Zara"})
    assert status == 404
    assert "not found" in body["detail"].lower()


def test_verify_returns_410_when_image_missing(app_client, jpeg_bytes):
    """Image was uploaded then deleted from disk → 410 Gone, not 500."""
    listing_id = _upload(app_client, jpeg_bytes)["listing_id"]
    (app_client.uploads_dir / f"{listing_id}.jpg").unlink()
    status, body = _verify(app_client, listing_id, {"brand": "Zara"})
    assert status == 410


def test_verify_empty_hints_still_succeeds(app_client, jpeg_bytes):
    """Calling /verify with no hint fields is a 'regenerate' — should return
    200 with revised=True and write zero edit rows."""
    listing_id = _upload(app_client, jpeg_bytes)["listing_id"]
    status, body = _verify(app_client, listing_id, {})
    assert status == 200
    assert body["revised"] is True

    conn = sqlite3.connect(app_client.db_path)
    edit_count = conn.execute(
        "SELECT COUNT(*) FROM edits WHERE listing_id = ?", (listing_id,)
    ).fetchone()[0]
    conn.close()
    assert edit_count == 0


def test_verify_logs_one_row_per_changed_field(app_client, jpeg_bytes):
    """User edits brand and size → exactly 2 rows in `edits`, with the
    correct field names and new_values."""
    upload_body = _upload(app_client, jpeg_bytes)
    listing_id = upload_body["listing_id"]
    _verify(app_client, listing_id, {"brand": "TestBrand", "size": "9XL"})

    conn = sqlite3.connect(app_client.db_path)
    rows = conn.execute(
        "SELECT field_name, new_value FROM edits WHERE listing_id = ? ORDER BY field_name",
        (listing_id,),
    ).fetchall()
    conn.close()
    assert rows == [("brand", "TestBrand"), ("size", "9XL")]


def test_verify_skips_logging_unchanged_fields(app_client, jpeg_bytes):
    """If the user's hint matches what was previously stored, no edit row."""
    upload_body = _upload(app_client, jpeg_bytes)
    listing_id = upload_body["listing_id"]
    existing_brand = upload_body["vinted"]["identification"]["brand"]

    _verify(app_client, listing_id, {"brand": existing_brand})

    conn = sqlite3.connect(app_client.db_path)
    edit_count = conn.execute(
        "SELECT COUNT(*) FROM edits WHERE listing_id = ?", (listing_id,)
    ).fetchone()[0]
    conn.close()
    assert edit_count == 0


def test_verify_writes_prediction_with_source_verify(app_client, jpeg_bytes):
    """The new prediction must be tagged source='verify' so we can distinguish
    upload vs verify in analytics later."""
    listing_id = _upload(app_client, jpeg_bytes)["listing_id"]
    _verify(app_client, listing_id, {"brand": "Zara"})

    conn = sqlite3.connect(app_client.db_path)
    sources = [
        row[0]
        for row in conn.execute(
            "SELECT source FROM predictions WHERE listing_id = ? ORDER BY id", (listing_id,)
        )
    ]
    conn.close()
    assert sources == ["upload", "verify"]


def test_verify_diffs_against_latest_prediction(app_client, jpeg_bytes):
    """A 3rd verify diffs against the 2nd's stored fields, not the original
    upload's. Brand values are outside the stub VLM's vocabulary so the upload's
    randomly-generated brand can't accidentally collide with either."""
    listing_id = _upload(app_client, jpeg_bytes)["listing_id"]
    _verify(app_client, listing_id, {"brand": "FirstBrand"})
    _verify(app_client, listing_id, {"brand": "SecondBrand"})

    conn = sqlite3.connect(app_client.db_path)
    rows = conn.execute(
        "SELECT field_name, old_value, new_value FROM edits WHERE listing_id = ? ORDER BY id",
        (listing_id,),
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert rows[0][0] == "brand" and rows[0][2] == "FirstBrand"
    assert rows[1] == ("brand", "FirstBrand", "SecondBrand")
