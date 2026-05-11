"""Model #6 — Grounded listing-copy generator (title + description).

Calls Groq (Llama 3.1 8B) with a category-matched few-shot prompt built from
Model #1's structured fields (brand / type / colour / size, plus the VLM's own
rough title) and Model #2's visual_wear_probability. Produces a compact
"Brand Type Colour Size" title and a 2–4 sentence description in one call.
Falls back to deterministic templates on any failure so the main pipeline is
never blocked.

Skips the API call and returns the templates when VLM_BACKEND=stub (test
environments) so tests remain deterministic and free of network calls.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"
_TIMEOUT = 8.0
_TITLE_MAX_LEN = 90

_SYSTEM = (
    "You write the title and description for second-hand clothing listings. "
    "Use ONLY the facts you are given — never invent details not in the data; "
    "if a field is marked unreliable, leave it out entirely. Write in English.\n"
    'TITLE: a compact, search-friendly line — brand, garment type, colour, size '
    '(e.g. "Ralph Lauren Polo Shirt Navy L", "Levi\'s 501 Jeans Blue 32"). '
    "No marketing words, no quotes, no trailing punctuation. If the photo model's "
    "rough title names a specific garment (polo, hoodie, parka, …), use that wording.\n"
    "DESCRIPTION: 2–4 sentences, personal and honest — the seller talking to the "
    "buyer. Mention wear, fit, or why it stands out. No bullet points.\n"
    "Output EXACTLY two lines:\n"
    "Title: <the title>\n"
    "Description: <the description>"
)

# Category-matched few-shot examples: (field_summary, title, description) tuples.
# Descriptions are taken from sold Vinted listings.
_EXAMPLES: dict[str, list[tuple[str, str, str]]] = {
    "jackets": [
        (
            "Brand: Zara | Condition: Very good | Color: black | Size: M | Wear: minimal",
            "Zara Blazer Black M",
            "Zara blazer in very good condition — no pilling, marks, or structural wear. "
            "Slim cut, true to size. A solid work-to-weekend layer at a fair price.",
        ),
        (
            "Brand: Columbia | Condition: Good | Color: olive | Size: L | Wear: light",
            "Columbia Fleece-Lined Windbreaker Olive L",
            "Columbia fleece-lined windbreaker, olive green. Picked this up for hiking but barely used it — "
            "some light crease marks from storage, nothing structural. Roomy L, great for layering.",
        ),
    ],
    "jeans": [
        (
            "Brand: Levi's | Condition: Good | Color: blue | Size: 32 | Wear: light",
            "Levi's 501 Jeans Blue 32",
            "Levi's 501 in classic mid-blue. Light fading and minor softening from regular "
            "wear — still plenty of life left. Straight fit, comfortable all day.",
        ),
        (
            "Brand: Mango | Condition: Very good | Color: black | Size: 36 | Wear: minimal",
            "Mango Straight-Leg Jeans Black 36",
            "Mango straight-leg jeans in black. Worn maybe five times — still crisp, no fading. "
            "Size 36, fits true. One of those pieces I kept reaching for but never quite felt like mine.",
        ),
    ],
    "tshirts": [
        (
            "Brand: H&M | Condition: New with tags | Color: white | Size: S | Wear: minimal",
            "H&M T-Shirt White S (new with tags)",
            "Brand new with the original tag still attached. "
            "Clean white, completely unworn. Size S runs true.",
        ),
        (
            "Brand: Carhartt | Condition: Good | Color: grey | Size: L | Wear: light",
            "Carhartt Pocket Tee Washed Grey L",
            "Carhartt pocket tee in washed grey. Regular fit, size L. "
            "Shows the kind of soft wear you'd expect from a well-loved tee — no holes, no stains. Honest listing.",
        ),
    ],
    "sneakers": [
        (
            "Brand: Nike | Condition: Very good | Color: white | Size: 42 | Wear: minimal",
            "Nike Running Shoes White 42",
            "Nike runners in very good condition — uppers clean, minimal sole wear. "
            "Small scuff on the right toe cap, barely visible. "
            "Solid pair with a lot of miles left.",
        ),
        (
            "Brand: New Balance | Condition: Good | Color: grey | Size: 44 | Wear: light",
            "New Balance 574 Grey 44",
            "New Balance 574 in grey. Worn regularly for about a year — soles have visible wear "
            "but uppers are clean and the cushioning is still solid. Priced to move.",
        ),
    ],
}

_DEFAULT_EXAMPLES: list[tuple[str, str, str]] = [
    (
        "Brand: Adidas | Condition: Very good | Color: navy | Size: M | Wear: minimal",
        "Adidas Crewneck Sweatshirt Navy M",
        "Barely worn and in very good condition overall. "
        "No visible damage or fading. Straightforward listing — what you see is what you get.",
    ),
    (
        "Brand: Uniqlo | Condition: Good | Color: beige | Size: S | Wear: light",
        "Uniqlo Crewneck Tee Beige S",
        "Uniqlo piece in beige, size S. Worn a handful of times, washed cold every time — "
        "keeps its shape well. Light use, no damage worth hiding.",
    ),
]


def _wear_label(visual_wear: float) -> str:
    if visual_wear < 0.25:
        return "minimal"
    if visual_wear < 0.55:
        return "light"
    return "visible"


def _field_summary(fields: dict, visual_wear: float, unreliable: set[str]) -> str:
    parts: list[str] = []
    for key in ("brand", "condition", "color", "size"):
        val = fields.get(key)
        if val and key not in unreliable:
            parts.append(f"{key.capitalize()}: {val}")
    parts.append(f"Wear: {_wear_label(visual_wear)}")
    return " | ".join(parts)


def _build_prompt(fields: dict, platform: str, visual_wear: float, field_review: dict) -> str:
    unreliable = set(field_review.get("needs_review", []))
    category = (fields.get("category") or "").lower()
    examples = _EXAMPLES.get(category, _DEFAULT_EXAMPLES)
    summary = _field_summary(fields, visual_wear, unreliable)
    platform_note = (
        "Vinted (casual, personal tone — write as the seller talking to the buyer)"
        if platform == "vinted"
        else "Kleinanzeigen (clear, matter-of-fact tone)"
    )
    unreliable_note = (
        f"\nDo not mention these unreliable fields: {', '.join(sorted(unreliable))}."
        if unreliable
        else ""
    )
    vlm_title = (fields.get("title") or "").strip()
    vlm_title_note = (
        f"\nPhoto model's rough title (use it for the garment type): {vlm_title}"
        if vlm_title
        else ""
    )
    example_block = "\n\n".join(
        f"[Example {i + 1}]\n{ex_f}\nTitle: {ex_t}\nDescription: {ex_d}"
        for i, (ex_f, ex_t, ex_d) in enumerate(examples)
    )
    return (
        f"{example_block}\n\n"
        f"[Write the title and description for]\n"
        f"Platform: {platform_note}\n"
        f"Category: {fields.get('category', 'clothing')}\n"
        f"{summary}"
        f"{vlm_title_note}"
        f"{unreliable_note}"
    )


def _size_short(size) -> str | None:
    if not size:
        return None
    first = str(size).replace("/", " ").split()
    return first[0] if first else None


def _title_fallback(fields: dict, field_review: dict) -> str:
    """Deterministic title used when Groq is unavailable. Worst case it matches
    the VLM's own title (i.e. no regression vs. today); usually it's a touch
    better because the colour/size get appended if they aren't already in it."""
    unreliable = set(field_review.get("needs_review", []))
    color = fields.get("color") if "color" not in unreliable else None
    size = _size_short(fields.get("size")) if "size" not in unreliable else None
    vlm = (fields.get("title") or "").strip()
    if vlm:
        title = vlm
        for extra in (str(color) if color else None, size):
            if extra and f" {extra.lower()} " not in f" {title.lower()} ":
                title = f"{title} {extra}"
        return title[:_TITLE_MAX_LEN].strip()
    brand = fields.get("brand") if "brand" not in unreliable else None
    category = fields.get("category") or "Clothing"
    title = " ".join(str(x) for x in (brand, category, color, size) if x).strip()
    return (title or "Second-hand clothing item")[:_TITLE_MAX_LEN].strip()


def _description_fallback(fields: dict, visual_wear: float, field_review: dict) -> str:
    unreliable = set(field_review.get("needs_review", []))
    brand = fields.get("brand") if "brand" not in unreliable else None
    category = fields.get("category", "item")
    condition = (fields.get("condition") or "").lower()
    color = fields.get("color")
    size = fields.get("size") if "size" not in unreliable else None

    head = " ".join(filter(None, [brand, color, category])).capitalize()
    cond_str = f"in {condition} condition" if condition else ""
    size_str = f"Size {size}." if size else ""
    wear = _wear_label(visual_wear)
    wear_str = f"Shows {wear} signs of wear." if wear != "minimal" else ""
    return " ".join(filter(None, [head, cond_str + ".", size_str, wear_str])).strip()


def _fallback_copy(fields: dict, visual_wear: float, field_review: dict) -> dict[str, str]:
    return {
        "title": _title_fallback(fields, field_review),
        "description": _description_fallback(fields, visual_wear, field_review),
    }


def _parse_copy(content: str, fields: dict, visual_wear: float, field_review: dict) -> dict[str, str]:
    """Parse Groq's two-line 'Title: …' / 'Description: …' output, tolerant of a
    bit of markdown decoration and a multi-line description. Any field that
    can't be recovered falls back to the template."""
    title: str | None = None
    desc_lines: list[str] = []
    capturing_desc = False
    for raw in content.splitlines():
        s = raw.strip().lstrip("*#-• ").strip()
        low = s.lower()
        if title is None and low.startswith("title:"):
            title = s[s.index(":") + 1:].strip().strip("\"'*. ").strip()
            capturing_desc = False
            continue
        if low.startswith("description:"):
            desc_lines = [s[s.index(":") + 1:].strip()]
            capturing_desc = True
            continue
        if capturing_desc and s:
            desc_lines.append(s)
    description = " ".join(p for p in desc_lines if p).strip()
    out = _fallback_copy(fields, visual_wear, field_review)
    if title:
        out["title"] = title[:_TITLE_MAX_LEN].strip()
    if description:
        out["description"] = description
    return out


async def generate_listing_copy(
    fields: dict,
    platform: str,
    visual_wear: float,
    field_review: dict | None = None,
) -> dict[str, str]:
    """Generate ``{"title": ..., "description": ...}`` for a listing via Groq.

    Returns deterministic template copy if GROQ_API_KEY is missing, the VLM
    backend is set to stub (test mode), or the API call fails. Never raises.
    """
    field_review = field_review or {}

    if os.environ.get("VLM_BACKEND") == "stub":
        return _fallback_copy(fields, visual_wear, field_review)

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        logger.warning("GROQ_API_KEY not set — using template fallback for listing copy")
        return _fallback_copy(fields, visual_wear, field_review)

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _build_prompt(fields, platform, visual_wear, field_review)},
        ],
        "max_tokens": 250,
        "temperature": 0.4,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                GROQ_API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content:
                return _parse_copy(content, fields, visual_wear, field_review)
            logger.warning("Groq returned empty content — using template fallback")
    except Exception as exc:
        logger.warning("Groq listing-copy call failed (%s) — using template fallback", exc)

    return _fallback_copy(fields, visual_wear, field_review)
