"""Unit tests for backend.integrations.kleinanzeigen.

Cover the things that don't need real HTTP: session round-trip,
is_configured branching, JAXB-XML body shape, error classification.
The runner-level happy path (success / failure / retry) is covered in
test_publish.py via mocked ka_integration.publish.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path

import pytest

from backend.integrations import kleinanzeigen as ka


def _session_dict(**overrides) -> dict:
    base = {
        "access_token": "header." + base64.urlsafe_b64encode(
            json.dumps({
                "https://www.kleinanzeigen.de/user_id": 45852425,
                "exp": time.time() + 3600,
            }).encode()
        ).decode().rstrip("=") + ".signature",
        "refresh_token": "rtok-1234",
        "expires_at": time.time() + 3600,
        "user_id": 45852425,
        "email": "demo@example.com",
        "poster_type": "PRIVATE",
        "imprint": "",
        "contact_name": "Demo",
        "home_location_id": 7615,
    }
    base.update(overrides)
    return base


def test_load_save_session_round_trip(tmp_path: Path):
    p = tmp_path / "ka.json"
    p.write_text(json.dumps(_session_dict()))
    sess = ka.load_session(p)
    assert sess is not None
    assert sess.user_id == 45852425
    assert sess.email == "demo@example.com"
    assert sess.home_location_id == 7615

    rotated = ka.KASession(**{**_session_dict(), "refresh_token": "rotated"})
    out = tmp_path / "ka2.json"
    ka.save_session(rotated, out)
    rt = ka.load_session(out)
    assert rt is not None
    assert rt.refresh_token == "rotated"


def test_load_session_missing_returns_none(tmp_path: Path):
    assert ka.load_session(tmp_path / "missing.json") is None


def test_is_configured_branches(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("KA_SESSION_PATH", raising=False)
    assert ka.is_configured() is False

    monkeypatch.setenv("KA_SESSION_PATH", str(tmp_path / "ghost.json"))
    assert ka.is_configured() is False

    p = tmp_path / "exists.json"
    p.write_text("{}")
    monkeypatch.setenv("KA_SESSION_PATH", str(p))
    assert ka.is_configured() is True


def test_xml_escape_handles_specials():
    """Title with & < > must round-trip safely. The KA submit body is XML
    despite content-type=application/json, so escaping is non-optional."""
    out = ka._xml_escape('A & B "<3>" \'foo\'')
    assert "&amp;" in out
    assert "&lt;" in out
    assert "&gt;" in out
    assert "&quot;" in out
    assert "&apos;" in out


def test_build_ad_xml_minimal_payload():
    xml = ka.build_ad_xml(
        {
            "title": "Test T-Shirt",
            "description": "Sehr guter Zustand & viel getragen",
            "category_id": 160,
            "location_id": 7615,
            "price_eur": 5,
            "poster_type": "PRIVATE",
            "email": "demo@example.com",
        },
        picture_links=[
            {"href": "https://img.kleinanzeigen.de/api/v1/x?Access=1&jwt=abc", "rel": "thumbnail"},
        ],
    )
    assert xml.startswith("<?xml ")
    assert "<ad:title>Test T-Shirt</ad:title>" in xml
    # & in description and href both escaped
    assert "Sehr guter Zustand &amp; viel getragen" in xml
    assert "Access=1&amp;jwt=abc" in xml
    assert '<cat:category id="160" />' in xml
    assert '<loc:location id="7615" />' in xml
    assert "<types:amount>5</types:amount>" in xml
    assert "<ad:value>OFFERED</ad:value>" in xml
    assert "<ad:value>PRIVATE</ad:value>" in xml
    # No imprint or contact-name when not provided
    assert "<ad:imprint>" not in xml
    assert "<ad:contact-name>" not in xml


def test_build_ad_xml_commercial_includes_imprint_and_contact():
    xml = ka.build_ad_xml(
        {
            "title": "x", "description": "y", "category_id": 160, "location_id": 7615,
            "price_eur": 10, "poster_type": "COMMERCIAL",
            "email": "biz@example.com",
            "contact_name": "ACME",
            "imprint": "ACME GmbH\nMusterstr. 1",
        },
        picture_links=[],
    )
    assert "<ad:value>COMMERCIAL</ad:value>" in xml
    assert "<ad:contact-name>ACME</ad:contact-name>" in xml
    assert "ACME GmbH" in xml


def test_classify_error_handles_ka_exceptions():
    from backend.queue.runner import classify_error

    assert classify_error(ka.KAAuthExpired("401")) == "permanent"
    assert classify_error(ka.KANotConfigured("no path")) == "permanent"
    # 4xx-style validation errors → permanent
    assert classify_error(ka.KAError("listing submit: HTTP 400 — bad payload")) == "permanent"
    # 5xx → retryable
    assert classify_error(ka.KAError("listing submit: HTTP 503 — gateway")) == "retryable"


def test_publish_raises_not_configured_when_env_missing(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("KA_SESSION_PATH", raising=False)
    with pytest.raises(ka.KANotConfigured):
        asyncio.run(ka.publish(tmp_path / "img.jpg", {"title": "t"}))


def test_publish_raises_not_configured_when_session_file_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("KA_SESSION_PATH", str(tmp_path / "ghost.json"))
    with pytest.raises(ka.KANotConfigured):
        asyncio.run(ka.publish(tmp_path / "img.jpg", {"title": "t"}))


def test_to_kleinanzeigen_routes_clothing_to_proper_leaves():
    """KA-side prompt vocab (KLEINANZEIGEN_CATEGORIES_EN) maps to the
    real KA leaf ids captured by scripts/probe_ka_categories.py."""
    import sys
    sys.path.insert(0, "shared")
    from listing_mappings import to_kleinanzeigen

    out_w = to_kleinanzeigen({
        "category": "Women's clothing", "title": "Tee", "description": "Nice", "price_eur": 5.0,
    })
    assert out_w["category_id"] == 154   # Damenbekleidung
    assert out_w["title"] == "Tee"
    assert out_w["price_eur"] == 5.0
    # Parent-tier input falls back to the per-cat default art slug
    assert out_w["attributes"]["kleidung_damen.art"] == "sonstige"

    out_m = to_kleinanzeigen({
        "category": "Men's clothing", "title": "Hemd", "description": "x", "price_eur": 7.0,
    })
    assert out_m["category_id"] == 160   # Herrenbekleidung
    assert out_m["attributes"]["kleidung_herren.art"] == "sonstige"


def test_to_kleinanzeigen_color_uses_ka_enum_slugs():
    """KA's color attribute is a fixed lowercase German enum (rose, schwarz,
    blau, ...). Translating English colors via display names + .lower()
    produces invalid values like 'rosé' or 'hellblau'. Verify the new
    _KA_COLOR_SLUG map yields valid enum values."""
    import sys
    sys.path.insert(0, "shared")
    from listing_mappings import to_kleinanzeigen

    # KA enum from probe: 'rose' (no accent), 'schwarz', 'blau', 'grün'
    out = to_kleinanzeigen({
        "category": "Women's clothing", "color": "Rose",
        "title": "x", "description": "y", "price_eur": 5.0,
    })
    assert out["attributes"]["kleidung_damen.color"] == "rose"

    out = to_kleinanzeigen({
        "category": "Men's clothing", "color": "Black",
        "title": "x", "description": "y", "price_eur": 5.0,
    })
    assert out["attributes"]["kleidung_herren.color"] == "schwarz"

    # Out-of-enum colors fold to 'sonstige' instead of failing the publish
    out = to_kleinanzeigen({
        "category": "Women's clothing", "color": "ChartreuseUnicornGold",
        "title": "x", "description": "y", "price_eur": 5.0,
    })
    assert out["attributes"]["kleidung_damen.color"] == "sonstige"


def test_to_kleinanzeigen_drops_unmapped_category():
    """Vinted-side leaf vocab (e.g. "sneakers" alone) has no KA mapping —
    runner sees no category_id and short-circuits with a clear error."""
    import sys
    sys.path.insert(0, "shared")
    from listing_mappings import to_kleinanzeigen

    out = to_kleinanzeigen({
        "category": "sneakers", "title": "x", "description": "y", "price_eur": 5.0,
    })
    assert "category_id" not in out
