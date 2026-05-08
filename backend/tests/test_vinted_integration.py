"""Unit tests for backend.integrations.vinted — payload shapes + error class.

Covers the slim MVP surface: load_session, save_session, _build_item_payload,
and the public is_configured/publish guards. No real HTTP — we don't go near
Vinted from CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.integrations import vinted


def _session_dict() -> dict:
    return {
        "access_token": "eyJ.fake.jwt",
        "refresh_token": "rtok",
        "expires_at": 9999999999.0,
        "datadome_cookie": "cookie",
        "anon_id": "anon",
        "device_uuid": "duuid",
        "device_token": "dtok",
        "user_id": "1",
        "session_id": "s",
        "domain": "www.vinted.fr",
    }


def test_load_save_session_round_trip(tmp_path: Path):
    p = tmp_path / "session.json"
    p.write_text(json.dumps(_session_dict()))
    sess = vinted.load_session(p)
    assert sess is not None
    assert sess.access_token == "eyJ.fake.jwt"
    assert sess.refresh_token == "rtok"

    sess2 = vinted.VintedSession(**{**_session_dict(), "access_token": "rotated"})
    out = tmp_path / "session2.json"
    vinted.save_session(sess2, out)
    rt = vinted.load_session(out)
    assert rt is not None
    assert rt.access_token == "rotated"


def test_load_session_missing_returns_none(tmp_path: Path):
    assert vinted.load_session(tmp_path / "does_not_exist.json") is None


def test_is_configured_false_when_env_unset(monkeypatch):
    monkeypatch.delenv("VINTED_SESSION_PATH", raising=False)
    assert vinted.is_configured() is False


def test_is_configured_false_when_path_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VINTED_SESSION_PATH", str(tmp_path / "missing.json"))
    assert vinted.is_configured() is False


def test_is_configured_true_when_path_exists(monkeypatch, tmp_path: Path):
    p = tmp_path / "exists.json"
    p.write_text("{}")
    monkeypatch.setenv("VINTED_SESSION_PATH", str(p))
    assert vinted.is_configured() is True


def test_build_item_payload_shape():
    """The payload sent to Vinted's draft endpoint must include catalog_id as
    a string, condition under item_attributes, and assigned_photos with the
    given photo IDs."""
    p = vinted._build_item_payload(
        {
            "title": "Zara T-shirt",
            "description": "Like new",
            "catalog_id": 221,
            "condition_id": 2,
            "brand": "Zara",
            "price": 10.0,
            "currency": "EUR",
        },
        photo_ids=[42, 43],
    )
    assert p["title"] == "Zara T-shirt"
    assert p["catalog_id"] == "221"  # stringified per Vinted's API
    assert p["assigned_photos"] == [{"id": "42"}, {"id": "43"}]
    condition_attr = next(a for a in p["item_attributes"] if a["code"] == "condition")
    assert condition_attr["ids"] == [2]


def test_build_item_payload_handles_missing_optional_fields():
    """Brand/size/color/material missing → None or empty without KeyError."""
    p = vinted._build_item_payload(
        {
            "title": "x",
            "description": "y",
            "catalog_id": 221,
            "price": 5.0,
        },
        photo_ids=[1],
    )
    assert p["brand"] is None
    assert p["brand_id"] is None
    assert p["size_id"] is None
    assert p["color_ids"] == []
    color_attr = next(a for a in p["item_attributes"] if a["code"] == "color")
    assert color_attr["ids"] == []
    material_attr = next(a for a in p["item_attributes"] if a["code"] == "material")
    assert material_attr["ids"] == []


def test_publish_raises_not_configured_when_env_missing(monkeypatch, tmp_path: Path):
    """The public publish() helper raises VintedNotConfigured when the env
    var is unset, so the route's try/except can map it cleanly."""
    monkeypatch.delenv("VINTED_SESSION_PATH", raising=False)

    import asyncio

    with pytest.raises(vinted.VintedNotConfigured):
        asyncio.run(vinted.publish(tmp_path / "img.jpg", {"title": "t"}))


def test_to_vinted_populates_size_and_color_ids():
    """to_vinted should map English color names + size labels to Vinted IDs
    when the canon fields cover them, and drop the keys when they don't."""
    import sys
    sys.path.insert(0, "src")
    from listing_mappings import to_vinted

    out = to_vinted({
        "category": "tshirts", "condition": "Very good", "color": "Pink", "size": "S",
        "title": "x", "description": "y", "price_eur": 5.0,
    })
    assert out["catalog_id"] == 221
    assert out["condition_id"] == 2
    assert out["size_id"] == 2
    assert out["color_ids"] == [5]


def test_to_vinted_size_normalization():
    """Verify-time sizes can look like 'M / 38 / 8' — the first known token wins."""
    import sys
    sys.path.insert(0, "src")
    from listing_mappings import to_vinted

    out = to_vinted({
        "category": "tshirts", "color": "navy", "size": "M / 38 / 8",
        "title": "x", "description": "y", "price_eur": 5.0,
    })
    assert out["size_id"] == 3  # M
    assert out["color_ids"] == [27]  # Marineblau


def test_to_vinted_drops_unmapped_color_and_size():
    """Unknown color or size → just doesn't emit the key, no crash."""
    import sys
    sys.path.insert(0, "src")
    from listing_mappings import to_vinted

    out = to_vinted({
        "category": "tshirts", "color": "Aubergine", "size": "Onesize",
        "title": "x", "description": "y", "price_eur": 5.0,
    })
    assert "size_id" not in out
    assert out["color_ids"] == []


def test_publish_raises_not_configured_when_session_file_missing(monkeypatch, tmp_path: Path):
    """Env var points at a non-existent file → still raise NotConfigured."""
    monkeypatch.setenv("VINTED_SESSION_PATH", str(tmp_path / "ghost.json"))

    import asyncio

    with pytest.raises(vinted.VintedNotConfigured):
        asyncio.run(vinted.publish(tmp_path / "img.jpg", {"title": "t"}))
