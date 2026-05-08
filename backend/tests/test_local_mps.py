"""Unit tests for the local_mps JSON parser. The model load is too heavy for
CI; we test the parsing surface in isolation and rely on manual smoke tests
for end-to-end validation."""

from __future__ import annotations

from backend.vlm_backend.local_mps import _parse_json_lenient


def test_clean_json():
    text = '{"brand": "Zara", "category": "jackets", "price_eur": 25}'
    out = _parse_json_lenient(text)
    assert out["brand"] == "Zara"
    assert out["category"] == "jackets"
    assert out["price_eur"] == 25


def test_markdown_fenced_json():
    text = '```json\n{"brand": "Nike", "category": "sneakers"}\n```'
    out = _parse_json_lenient(text)
    assert out["brand"] == "Nike"
    assert out["category"] == "sneakers"


def test_markdown_fence_without_json_tag():
    text = '```\n{"brand": "Adidas"}\n```'
    out = _parse_json_lenient(text)
    assert out["brand"] == "Adidas"


def test_trailing_prose():
    text = '{"brand": "H&M", "color": "red"} Hope this helps!'
    out = _parse_json_lenient(text)
    assert out["brand"] == "H&M"
    assert out["color"] == "red"


def test_leading_and_trailing_prose():
    text = 'Sure! Here is the JSON: {"brand": "Levi\'s"}. Let me know if you need more.'
    out = _parse_json_lenient(text)
    assert out["brand"] == "Levi's"


def test_empty_text():
    assert _parse_json_lenient("") == {}
    assert _parse_json_lenient("   ") == {}


def test_malformed_returns_empty():
    assert _parse_json_lenient("just some prose, no json here") == {}
    assert _parse_json_lenient("{not real json}") == {}


def test_nested_object():
    text = '{"brand": "Zara", "meta": {"era": "2020s", "tag_visible": true}}'
    out = _parse_json_lenient(text)
    assert out["meta"]["era"] == "2020s"
    assert out["meta"]["tag_visible"] is True


def test_python_style_single_quotes_returns_empty():
    """VLM occasionally emits Python-style dict literals; not valid JSON."""
    assert _parse_json_lenient("{'brand': 'Zara'}") == {}


def test_unicode_brand():
    out = _parse_json_lenient('{"brand": "Müller", "color": "schwarz"}')
    assert out["brand"] == "Müller"
    assert out["color"] == "schwarz"
