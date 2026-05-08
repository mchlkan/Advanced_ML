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


def _save_jpeg(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=92)


@router.post("/upload", response_model=UploadResponse)
async def upload(request: Request, image: UploadFile = File(...)) -> UploadResponse:
    raw = await image.read()
    try:
        pil_image = Image.open(io.BytesIO(raw)).convert("RGB")
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="Could not decode image") from exc

    listing_id = uuid.uuid4().hex
    image_path = UPLOADS_DIR / f"{listing_id}.jpg"
    state = request.app.state

    save_task = asyncio.to_thread(_save_jpeg, pil_image, image_path)
    pipeline_task = run_pipeline(pil_image, state.models, state.vlm)
    _, result = await asyncio.gather(save_task, pipeline_task)

    await db.log_listing(listing_id, image_path, state.vlm.name)
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
        vlm_backend=state.vlm.name,
        visual_wear_probability=result["visual_wear_probability"],
        vinted=result["vinted"],
        kleinanzeigen=result["kleinanzeigen"],
        latency_ms=result["latency_ms"],
    )
