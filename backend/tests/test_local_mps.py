"""Unit tests for the local_mps JSON parser. The model load is too heavy for
CI; we test the parsing surface in isolation and rely on manual smoke tests
for end-to-end validation."""

from __future__ import annotations

from backend.vlm_backend.util import parse_json_lenient, parse_vlm_fields


def test_clean_json():
    text = '{"brand": "Zara", "category": "jackets", "price_eur": 25}'
    out = parse_json_lenient(text)
    assert out["brand"] == "Zara"
    assert out["category"] == "jackets"
    assert out["price_eur"] == 25


def test_markdown_fenced_json():
    text = '```json\n{"brand": "Nike", "category": "sneakers"}\n```'
    out = parse_json_lenient(text)
    assert out["brand"] == "Nike"
    assert out["category"] == "sneakers"


def test_markdown_fence_without_json_tag():
    text = '```\n{"brand": "Adidas"}\n```'
    out = parse_json_lenient(text)
    assert out["brand"] == "Adidas"


def test_trailing_prose():
    text = '{"brand": "H&M", "color": "red"} Hope this helps!'
    out = parse_json_lenient(text)
    assert out["brand"] == "H&M"
    assert out["color"] == "red"


def test_leading_and_trailing_prose():
    text = 'Sure! Here is the JSON: {"brand": "Levi\'s"}. Let me know if you need more.'
    out = parse_json_lenient(text)
    assert out["brand"] == "Levi's"


def test_empty_text():
    assert parse_json_lenient("") == {}
    assert parse_json_lenient("   ") == {}


def test_malformed_returns_empty():
    assert parse_json_lenient("just some prose, no json here") == {}
    assert parse_json_lenient("{not real json}") == {}


def test_nested_object():
    text = '{"brand": "Zara", "meta": {"era": "2020s", "tag_visible": true}}'
    out = parse_json_lenient(text)
    assert out["meta"]["era"] == "2020s"
    assert out["meta"]["tag_visible"] is True


def test_python_style_single_quotes_returns_empty():
    """VLM occasionally emits Python-style dict literals; not valid JSON."""
    assert parse_json_lenient("{'brand': 'Zara'}") == {}


def test_unicode_brand():
    out = parse_json_lenient('{"brand": "Müller", "color": "schwarz"}')
    assert out["brand"] == "Müller"
    assert out["color"] == "schwarz"


def test_truncated_json_recovers_scalar_fields():
    text = '{"brand": "Zara", "category": "jackets", "size": "M", "description": "Nice jacket'
    out = parse_vlm_fields(text)
    assert out.parse_ok is False
    assert out.recovered is True
    assert out.fields["brand"] == "Zara"
    assert out.fields["category"] == "jackets"
    assert out.fields["size"] == "M"


def test_raw_newline_in_description_recovers_other_fields():
    text = '{"brand": "Nike", "category": "sneakers", "description": "Line one\nLine two, "price_eur": 40}'
    out = parse_vlm_fields(text)
    assert out.parse_ok is False
    assert out.recovered is True
    assert out.fields["brand"] == "Nike"
    assert out.fields["category"] == "sneakers"
    assert out.fields["price_eur"] == 40
