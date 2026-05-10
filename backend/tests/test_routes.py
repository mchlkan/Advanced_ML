"""HTTP-level round-trip tests with TestClient + tmpdir SQLite."""

from __future__ import annotations

import sqlite3


def test_healthz(app_client):
    r = app_client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["vlm_backend"] == "stub"
    assert any("PriceHead" in line for line in body["models_loaded"])


def test_upload_round_trip(app_client, jpeg_bytes):
    r = app_client.post("/upload", files={"image": ("hero.jpg", jpeg_bytes, "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()

    assert "listing_id" in body
    assert body["vlm_backend"] == "stub"
    assert 0.0 <= body["visual_wear_probability"] <= 1.0
    for plat in ("vinted", "kleinanzeigen"):
        price = body[plat]["price"]
        assert price["q10"] <= price["q50"] <= price["q90"]
        ident = body[plat]["identification"]
        assert ident["brand"] is not None
        assert ident["category"] is not None
        assert body[plat]["field_review"]["needs_review"] == ["brand", "size"]
        assert body[plat]["field_review"]["reasons"]["brand"] == "low_confidence"
    assert 0.0 <= body["vinted"]["sell_probability"] <= 1.0

    image_path = app_client.uploads_dir / f"{body['listing_id']}.jpg"
    assert image_path.exists()

    conn = sqlite3.connect(app_client.db_path)
    listings = conn.execute("SELECT id, image_path, vlm_backend FROM listings").fetchall()
    preds = conn.execute("SELECT listing_id, source, vlm_call_count FROM predictions").fetchall()
    conn.close()

    assert len(listings) == 1
    assert listings[0][0] == body["listing_id"]
    assert listings[0][2] == "stub"
    assert len(preds) == 1
    assert preds[0][0] == body["listing_id"]
    assert preds[0][1] == "upload"
    assert preds[0][2] == 2


def test_verify_round_trip(app_client, jpeg_bytes):
    upload = app_client.post("/upload", files={"image": ("hero.jpg", jpeg_bytes, "image/jpeg")})
    listing_id = upload.json()["listing_id"]

    r = app_client.post("/verify", json={
        "listing_id": listing_id,
        "hints": {"brand": "Zara", "size": "L"},
    })
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["listing_id"] == listing_id
    assert body["revised"] is True
    assert body["vinted"]["identification"]["brand"] == "Zara"
    assert body["vinted"]["identification"]["size"] == "L"
    assert body["kleinanzeigen"]["identification"]["brand"] == "Zara"
    assert body["kleinanzeigen"]["identification"]["size"] == "L"
    assert "brand" not in body["vinted"]["field_review"]["needs_review"]
    assert "size" not in body["vinted"]["field_review"]["needs_review"]
    assert body["vinted"]["field_review"]["needs_review"] == []
    assert body["kleinanzeigen"]["field_review"]["needs_review"] == []


def test_publish_round_trip(app_client, jpeg_bytes):
    upload = app_client.post("/upload", files={"image": ("hero.jpg", jpeg_bytes, "image/jpeg")})
    listing_id = upload.json()["listing_id"]

    r = app_client.post(
        "/publish",
        json={
            "listing_id": listing_id,
            "platform": "vinted",
            "final_fields": {"brand": "Zara", "title": "t", "description": "d"},
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["listing_id"] == listing_id
    assert body["platform"] == "vinted"
    assert body["status"] == "pending"
    assert isinstance(body["job_id"], int)


def test_upload_rejects_non_image(app_client):
    r = app_client.post("/upload", files={"image": ("evil.bin", b"\x00\x01\x02not an image", "application/octet-stream")})
    assert r.status_code == 400


def test_upload_with_label_image_persists_both(app_client, jpeg_bytes):
    """Multi-image upload: cover + care label both saved, label_image_path tracked in DB."""
    r = app_client.post(
        "/upload",
        files={
            "image": ("hero.jpg", jpeg_bytes, "image/jpeg"),
            "label_image": ("label.jpg", jpeg_bytes, "image/jpeg"),
        },
    )
    assert r.status_code == 200, r.text
    listing_id = r.json()["listing_id"]

    cover = app_client.uploads_dir / f"{listing_id}.jpg"
    label = app_client.uploads_dir / f"{listing_id}_label.jpg"
    assert cover.exists()
    assert label.exists()

    conn = sqlite3.connect(app_client.db_path)
    row = conn.execute(
        "SELECT image_path, label_image_path FROM listings WHERE id = ?",
        (listing_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0].endswith(f"{listing_id}.jpg")
    assert row[1] is not None and row[1].endswith(f"{listing_id}_label.jpg")

    # Both image and label endpoints should serve the saved JPEGs.
    assert app_client.get(f"/listings/{listing_id}/image").status_code == 200
    assert app_client.get(f"/listings/{listing_id}/label").status_code == 200


def test_upload_without_label_image_404s_label_endpoint(app_client, jpeg_bytes):
    r = app_client.post("/upload", files={"image": ("hero.jpg", jpeg_bytes, "image/jpeg")})
    listing_id = r.json()["listing_id"]
    assert app_client.get(f"/listings/{listing_id}/image").status_code == 200
    assert app_client.get(f"/listings/{listing_id}/label").status_code == 404
