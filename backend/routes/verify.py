"""POST /verify — re-run the VLM with seller hints + re-run heads.

The user has corrected one or more identification fields. We:
1. Append a "[Hint: ...]" suffix to the VLM prompt so it can regenerate
   title/description with the correction in mind.
2. Overlay the corrections onto the VLM's emitted fields *before* feeding
   the price/sell heads, so a stubborn VLM can't ignore the user.
3. Log every changed field as a separate row in `edits` (preference data).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from PIL import Image, UnidentifiedImageError

from backend import db
from backend.pipeline import run_pipeline
from backend.schemas import VerifyRequest, VerifyResponse


router = APIRouter()


def _format_hints(hint_dict: dict) -> str | None:
    """`{brand: "Zara", size: "M"}` → `"[Hint: brand is Zara, size is M]"`.
    Empty dict → None so the VLM prompt is unchanged."""
    if not hint_dict:
        return None
    parts = [f"{k} is {v}" for k, v in hint_dict.items()]
    return f"[Hint: {', '.join(parts)}]"


def _diff_fields(old: dict, new: dict) -> list[tuple[str, str | None, str]]:
    """One tuple per (field, old_value, new_value) where new_value differs
    from the previously-stored value. Stringifies only on storage so that
    int 0 vs str "0" don't false-match."""
    changes: list[tuple[str, str | None, str]] = []
    for field, new_val in new.items():
        old_val = old.get(field)
        if old_val == new_val:
            continue
        old_str = None if old_val is None else str(old_val)
        changes.append((field, old_str, str(new_val)))
    return changes


@router.post(
    "/verify",
    response_model=VerifyResponse,
    responses={
        404: {"description": "listing_id unknown"},
        410: {"description": "listing's image is no longer on disk"},
    },
)
async def verify(request: Request, body: VerifyRequest) -> VerifyResponse:
    state = request.app.state
    rec = await db.get_listing(body.listing_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"listing {body.listing_id} not found")
    image_path = Path(rec["image_path"])
    if not image_path.exists():
        raise HTTPException(status_code=410, detail=f"image for {body.listing_id} no longer on disk")
    try:
        image = Image.open(image_path).convert("RGB")
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=410, detail="Stored image could not be decoded") from exc

    hint_dict = body.hints.model_dump(exclude_none=True)

    result = await run_pipeline(
        image, state.models, state.vlm,
        hints=_format_hints(hint_dict),
        field_overrides=hint_dict or None,
    )

    changes = _diff_fields(rec["last_english_fields"], hint_dict)
    await db.log_edits(body.listing_id, changes)
    await db.log_prediction(
        listing_id=body.listing_id,
        source="verify",
        english_fields=result["vinted"]["identification"],
        vinted_q10=result["vinted"]["price"]["q10"],
        vinted_q50=result["vinted"]["price"]["q50"],
        vinted_q90=result["vinted"]["price"]["q90"],
        vinted_sell_prob=result["vinted"]["sell_probability"],
        ka_q10=result["kleinanzeigen"]["price"]["q10"],
        ka_q50=result["kleinanzeigen"]["price"]["q50"],
        ka_q90=result["kleinanzeigen"]["price"]["q90"],
        visual_wear_probability=result["visual_wear_probability"],
        latency_ms=result["latency_ms"],
        vlm_call_count=result["vlm_call_count"],
    )

    return VerifyResponse(
        listing_id=body.listing_id,
        vlm_backend=state.vlm.name,
        visual_wear_probability=result["visual_wear_probability"],
        vinted=result["vinted"],
        kleinanzeigen=result["kleinanzeigen"],
        latency_ms=result["latency_ms"],
        revised=True,
    )
