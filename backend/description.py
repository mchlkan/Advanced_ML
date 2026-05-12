"""Model #6 — Grounded listing-copy generator (English title + English description).

One Groq (Llama 3.1 8B) call per platform, grounded on Model #1's structured
fields and Model #2's visual_wear_probability. Produces:
  - a compact English title in the form "{brand} {garment} {colour} {size}", and
  - an English listing description in the platform's house style — Vinted: short,
    casual, friendly closer; Kleinanzeigen: longer, factual, with a shipping/
    pickup line and a private-sale disclaimer (appended deterministically).

Falls back to deterministic templates on any failure, so the main pipeline is
never blocked. Skips the API call (templates only) when VLM_BACKEND=stub so
tests stay deterministic and network-free.
"""

from __future__ import annotations

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"
_TIMEOUT = 10.0
_TITLE_MAX_LEN = 90

# Appended to every Kleinanzeigen description (private sales on KA come with no
# warranty / right of return; the disclaimer protects the seller).
_KA_DISCLAIMER = "This is a private sale — no warranty, guarantee, or right of return."


def _condition_phrase(condition: str | None) -> str:
    if not condition:
        return "second-hand"
    return condition.lower()  # "new with tags", "very good", "good", …


def _wear_phrase(visual_wear: float) -> str:
    if visual_wear < 0.25:
        return "no notable signs of wear"
    if visual_wear < 0.55:
        return "light signs of wear, nothing serious"
    return "visible signs of wear — please check the photos closely"


def _size_short(size) -> str | None:
    if not size:
        return None
    toks = str(size).replace("/", " ").split()
    return toks[0] if toks else None


# --- prompt pieces -----------------------------------------------------------

_TITLE_RULES = (
    "TITLE — EXACTLY four space-separated parts in this order and NOTHING else: "
    "{brand} {garment type} {colour} {size}. No condition, notes, parentheses, "
    "quotes, commas, or trailing punctuation. Drop a part only if it is genuinely "
    "missing (no brand → start with the garment type; no size → end with the "
    "colour). Brand: from the Brand field, else from the rough title (it usually "
    'leads with the brand: "Polo Ralph Lauren" → "Ralph Lauren") — include it '
    "even if low-confidence. Garment type: a clean noun phrase from the rough "
    'title + category — "Polo Shirt", "Hoodie", "Bomber Jacket", "Slim Jeans", '
    '"Air Max 90"; "polo" anywhere → "Polo Shirt" (not "T-Shirt") even if the '
    'category slug is "tshirts". Never echo the rough title verbatim — rewrite it.'
)

_VINTED_DESC_RULES = (
    "DESCRIPTION — Vinted style: short, casual, friendly, easy to skim — about "
    "3–5 short sentences in this order:\n"
    "1. one catchy opening line about the item;\n"
    "2. what it is (brand, type, colour, size);\n"
    "3. the condition, with any flaws stated honestly;\n"
    "4. fit / material / a nice detail — ONLY if you actually know it from the data;\n"
    '5. a friendly closer like "Happy to answer any questions :)".'
)

_KA_DESC_RULES = (
    "DESCRIPTION — Kleinanzeigen style: a bit longer, factual and trustworthy — "
    "about 4–7 sentences in this order:\n"
    "1. a short line on what is being sold;\n"
    "2. the product details (brand, type, colour, size, plus a model name if the "
    "rough title gives one);\n"
    "3. condition and flaws, stated transparently;\n"
    '4. one line on shipping/pickup — write exactly "Shipping or local pickup available.";\n'
    "5. do NOT write the legal private-sale disclaimer yourself — it is appended automatically."
)

_GENERAL_DESC_RULES = (
    "DESCRIPTION rules for both platforms: fluent, natural ENGLISH; do not sound "
    "like AI; no hype or superlatives; honest about condition and flaws; never "
    "mention a price; never promise things you weren't told (material, fit, "
    "model name) — if you don't know, leave it out; refer to the item by the "
    "garment type you put in the title (don't drift to a different garment word "
    'in the description); at most a single minimal emoji in a sign-off (":)"), '
    "nothing else."
)

_BASE_SYSTEM = (
    "You turn structured data (extracted from a photo) into one product listing. "
    "Use ONLY the given facts — never invent details, prices, brands, or "
    "materials that aren't there. Start your reply with a `Title:` line, then "
    "`Description:` followed by the listing text.\n\n"
)

_VINTED_EXAMPLE = (
    "[Example]\n"
    "Brand: Levi's | Colour: blue | Size: 32 | Category: jeans | "
    "Condition: good | Wear: light signs of wear, nothing serious | "
    "Rough title: Levi's 511 slim denim\n"
    "Title: Levi's 511 Jeans Blue 32\n"
    "Description: Classic Levi's 511 in mid-blue, size 32. Slim fit, true to size. "
    "Good condition — light wear and a touch of fading from regular use, but no holes or stains. "
    "Don't reach for them much anymore, so passing them on. Happy to answer any questions :)"
)

_KA_EXAMPLE = (
    "[Example]\n"
    "Brand: Nike | Colour: white | Size: 42 | Category: sneakers | "
    "Condition: very good | Wear: light signs of wear, nothing serious | "
    "Rough title: Nike Air Max 90 sneakers\n"
    "Title: Nike Air Max 90 White 42\n"
    "Description: Selling a pair of Nike Air Max 90 in white, size 42. Classic model, easy to pair with anything. "
    "Condition is very good — only lightly worn, with small scuffs on the outer sole; the uppers are clean. "
    "Shipping or local pickup available. Feel free to message with any questions."
)


def _system_for(platform: str) -> str:
    desc_rules = _VINTED_DESC_RULES if platform == "vinted" else _KA_DESC_RULES
    return f"{_BASE_SYSTEM}{_TITLE_RULES}\n\n{desc_rules}\n\n{_GENERAL_DESC_RULES}"


def _build_prompt(fields: dict, platform: str, visual_wear: float, field_review: dict) -> str:
    unreliable = sorted(set(field_review.get("needs_review", [])) & {"brand", "color", "size", "condition"})
    parts: list[str] = []
    for key in ("brand", "color", "size"):
        v = fields.get(key)
        if v:
            parts.append(f"{key.capitalize()}: {v}")
    parts.append(f"Category: {fields.get('category', 'clothing')}")
    parts.append(f"Condition: {_condition_phrase(fields.get('condition'))}")
    parts.append(f"Wear: {_wear_phrase(visual_wear)}")
    rough = (fields.get("title") or "").strip()
    if rough:
        parts.append(f"Rough title: {rough}")
    summary = " | ".join(parts)
    low_conf = (
        f"\nLow-confidence reads ({', '.join(unreliable)}): keep them in the title; "
        "hedge them or leave them out of the description."
        if unreliable
        else ""
    )
    example = _VINTED_EXAMPLE if platform == "vinted" else _KA_EXAMPLE
    return f"{example}\n\n[Now write for]\n{summary}{low_conf}"


# --- title cleanup -----------------------------------------------------------

_CONDITION_WORDS = (
    "new with tags", "new with tag", "brand new", "like new", "very good condition",
    "good condition", "fair condition", "very good", "good", "fair", "used",
    "pre-owned", "preowned", "worn",
)

# Letter sizes the model occasionally expands ("L" → "Large"); enforce the short
# form so the title matches the size value the user actually picked.
_SIZE_EXPANSIONS = {
    "S": ("small",),
    "M": ("medium",),
    "L": ("large",),
    "XL": ("x-large", "extra large", "xlarge"),
    "XXL": ("xx-large", "xxlarge"),
}


def _clean_title(t: str, fields: dict) -> str:
    """Belt-and-suspenders on the title: drop parenthetical notes / a trailing
    condition phrase, normalise letter sizes back to their short form, and fix
    the common 'tshirts-category polo read as a T-Shirt' miss when the rough
    title clearly says 'polo'."""
    t = re.sub(r"\s*\([^)]*\)", "", t)
    rough = (fields.get("title") or "").lower()
    if re.search(r"\bpolo\b", rough) and not re.search(r"\bpolo\b", t.lower()):
        t = re.sub(r"\bt[\- ]?shirts?\b", "Polo Shirt", t, flags=re.I)
        t = re.sub(r"\btees?\b", "Polo Shirt", t, flags=re.I)
    size_short = _size_short(fields.get("size") or "")
    if size_short and size_short.upper() in _SIZE_EXPANSIONS:
        for expansion in _SIZE_EXPANSIONS[size_short.upper()]:
            t = re.sub(rf"\b{re.escape(expansion)}\b", size_short, t, flags=re.I)
    low = t.lower().rstrip(" .-—,")
    for cw in _CONDITION_WORDS:
        # word-boundary match only — a bare `endswith(cw)` would clip
        # "Hollywood" → "Hollywoo" (ends with "good") or "Mayfair" → "May".
        if low == cw or low.endswith(" " + cw):
            t = t.rstrip(" .-—,")[: -len(cw)]
            break
    t = re.sub(r"\s+", " ", t).strip(" .-—,\"'")
    return t[:_TITLE_MAX_LEN].strip()


# --- deterministic fallbacks -------------------------------------------------

def _title_fallback(fields: dict) -> str:
    rough = (fields.get("title") or "").strip()
    color = fields.get("color")
    size = _size_short(fields.get("size"))
    if rough:
        t = rough
        for extra in (str(color) if color else None, size):
            if extra and f" {extra.lower()} " not in f" {t.lower()} ":
                t = f"{t} {extra}"
        return _clean_title(t, fields) or "Second-hand clothing item"
    brand = fields.get("brand")
    cat = fields.get("category") or "Clothing"
    return _clean_title(" ".join(str(x) for x in (brand, cat, color, size) if x), fields) or "Second-hand clothing item"


def _description_fallback(fields: dict, platform: str, visual_wear: float) -> str:
    brand = fields.get("brand")
    cat = fields.get("category") or "item"
    color = fields.get("color")
    size = fields.get("size")
    cond = _condition_phrase(fields.get("condition"))
    wear = _wear_phrase(visual_wear)
    what = " ".join(str(x) for x in ([brand] if brand else []) + ([color.lower()] if color else []) + [cat])
    size_str = f", size {size}" if size else ""
    cond_line = f"Condition: {cond} — {wear}."
    if platform == "vinted":
        return f"{what.capitalize()}{size_str}. {cond_line} Happy to answer any questions :)"
    return _finalize_ka(f"Selling a {what}{size_str}. {cond_line} Shipping or local pickup available.")


def _finalize_ka(desc: str) -> str:
    d = (desc or "").strip()
    # Use a stable substring of the disclaimer to detect "already appended".
    if "private sale" not in d.lower():
        d = f"{d}\n\n{_KA_DISCLAIMER}"
    return d


def _fallback_copy(fields: dict, platform: str, visual_wear: float) -> dict[str, str]:
    return {
        "title": _title_fallback(fields),
        "description": _description_fallback(fields, platform, visual_wear),
    }


# --- response parsing --------------------------------------------------------

def _parse_copy(content: str, fields: dict, platform: str, visual_wear: float) -> dict[str, str]:
    title: str | None = None
    desc_lines: list[str] = []
    capturing = False
    for raw in content.splitlines():
        s = raw.strip().lstrip("*#-• ").strip()
        low = s.lower()
        if title is None and low.startswith("title:"):
            title = s[s.index(":") + 1:].strip().strip("\"'*. ").strip()
            capturing = False
            continue
        if low.startswith("description:"):
            desc_lines = [s[s.index(":") + 1:].strip()]
            capturing = True
            continue
        if capturing:
            desc_lines.append(raw.rstrip())
    description = re.sub(r"\n{3,}", "\n\n", "\n".join(desc_lines).strip()).strip()

    out = _fallback_copy(fields, platform, visual_wear)
    if title:
        ct = _clean_title(title, fields)
        if ct:
            out["title"] = ct
    if description:
        out["description"] = description
    if platform == "kleinanzeigen":
        out["description"] = _finalize_ka(out["description"])
    return out


async def generate_listing_copy(
    fields: dict,
    platform: str,
    visual_wear: float,
    field_review: dict | None = None,
) -> dict[str, str]:
    """Generate ``{"title": ..., "description": ...}`` for a listing.

    Returns deterministic template copy if GROQ_API_KEY is missing, the VLM
    backend is set to stub (test mode), or the API call fails. Never raises.
    """
    field_review = field_review or {}

    vlm_is_stub = (os.environ.get("VLM_BACKEND") or "").lower() == "stub"
    if vlm_is_stub or not os.environ.get("GROQ_API_KEY"):
        if not os.environ.get("GROQ_API_KEY") and not vlm_is_stub:
            logger.warning("GROQ_API_KEY not set — using template fallback for listing copy")
        return _fallback_copy(fields, platform, visual_wear)

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _system_for(platform)},
            {"role": "user", "content": _build_prompt(fields, platform, visual_wear, field_review)},
        ],
        "max_tokens": 450,
        "temperature": 0.5,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                GROQ_API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content:
                return _parse_copy(content, fields, platform, visual_wear)
            logger.warning("Groq returned empty content — using template fallback")
    except Exception as exc:
        logger.warning("Groq listing-copy call failed (%s) — using template fallback", exc)

    return _fallback_copy(fields, platform, visual_wear)
