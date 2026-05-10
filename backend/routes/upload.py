"""POST /upload — accept an image, run the full inference pipeline, log to SQLite."""

from __future__ import annotations

import asyncio
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from PIL import Image, UnidentifiedImageError

from backend import db
from backend.pipeline import run_pipeline
from backend.schemas import UploadResponse


router = APIRouter()
UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "uploads"

_MOCK_RESULT = {
    "vinted": {
        "identification": {
            "brand": "[MOCK] brand", "category": "[MOCK] category", "condition": "[MOCK] condition",
            "color": "[MOCK] color", "size": "[MOCK] size", "title": "[MOCK] title",
            "description": "[MOCK] description — SKIP_ML=1, no real inference", "price_eur": -1,
        },
        "price": {"q10": -1.0, "q50": -1.0, "q90": -1.0},
        "sell_probability": -1.0,
        "field_review": {"needs_review": [], "reasons": {}},
    },
    "kleinanzeigen": {
        "identification": {
            "brand": "[MOCK] brand", "category": "[MOCK] category", "condition": "[MOCK] condition",
            "color": "[MOCK] color", "size": "[MOCK] size", "title": "[MOCK] title",
            "description": "[MOCK] description — SKIP_ML=1, no real inference", "price_eur": -1,
        },
        "price": {"q10": -1.0, "q50": -1.0, "q90": -1.0},
        "field_review": {"needs_review": [], "reasons": {}},
    },
    "visual_wear_probability": -1.0,
    "latency_ms": -1,
    "vlm_call_count": -1,
}


def _save_jpeg(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=92)


@router.post(
    "/upload",
    response_model=UploadResponse,
    responses={400: {"description": "uploaded file is not a decodable image"}},
)
async def upload(
    request: Request,
    image: UploadFile = File(..., description="Garment / cover photo (required)."),
    label_image: UploadFile | None = File(
        None,
        description="Optional close-up of the care label. When supplied, the multi-image "
                    "VLM uses it for brand/size; without it the model falls back to single-image.",
    ),
) -> UploadResponse:
    raw = await image.read()
    try:
        pil_image = Image.open(io.BytesIO(raw)).convert("RGB")
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="Could not decode image") from exc

    pil_label: Image.Image | None = None
    if label_image is not None:
        label_raw = await label_image.read()
        if label_raw:  # FastAPI gives us an empty UploadFile when the field is omitted
            try:
                pil_label = Image.open(io.BytesIO(label_raw)).convert("RGB")
            except UnidentifiedImageError as exc:
                raise HTTPException(status_code=400, detail="Could not decode label_image") from exc

    listing_id = uuid.uuid4().hex
    image_path = UPLOADS_DIR / f"{listing_id}.jpg"
    label_image_path: Path | None = UPLOADS_DIR / f"{listing_id}_label.jpg" if pil_label is not None else None
    state = request.app.state

    if state.models is None:
        await asyncio.to_thread(_save_jpeg, pil_image, image_path)
        if pil_label is not None and label_image_path is not None:
            await asyncio.to_thread(_save_jpeg, pil_label, label_image_path)
        result = _MOCK_RESULT
        vlm_name = "skip_ml"
    else:
        save_tasks = [asyncio.to_thread(_save_jpeg, pil_image, image_path)]
        if pil_label is not None and label_image_path is not None:
            save_tasks.append(asyncio.to_thread(_save_jpeg, pil_label, label_image_path))
        pipeline_task = run_pipeline(pil_image, state.models, state.vlm, label_image=pil_label)
        *_, result = await asyncio.gather(*save_tasks, pipeline_task)
        vlm_name = state.vlm.name

    await db.log_listing(listing_id, image_path, vlm_name, label_image_path=label_image_path)
    await db.log_prediction(
        listing_id=listing_id,
        source="upload",
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

    return UploadResponse(
        listing_id=listing_id,
        vlm_backend=vlm_name,
        visual_wear_probability=result["visual_wear_probability"],
        vinted=result["vinted"],
        kleinanzeigen=result["kleinanzeigen"],
        latency_ms=result["latency_ms"],
    )
