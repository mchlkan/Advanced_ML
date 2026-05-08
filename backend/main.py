"""FastAPI entry point for Resell Copilot."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend import db
from backend.bootstrap import load_models
from backend.routes import publish, upload, verify
from backend.schemas import HealthzResponse
from backend.vlm_backend import get_backend


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    device_pref = os.environ.get("DEVICE", "auto")
    app.state.vlm = get_backend()

    # load_models (DINOv2 + 3 heads) and vlm.warmup (Qwen3-VL + LoRA) are independent;
    # run concurrently so cold start isn't the sum of both.
    models, _ = await asyncio.gather(
        asyncio.to_thread(load_models, device_pref),
        app.state.vlm.warmup(),
    )
    app.state.models = models

    await db.init_db()
    yield


app = FastAPI(title="Resell Copilot API", lifespan=lifespan)
app.include_router(upload.router)
app.include_router(verify.router)
app.include_router(publish.router)


@app.get("/healthz", response_model=HealthzResponse)
async def healthz() -> HealthzResponse:
    models = app.state.models
    return HealthzResponse(
        ok=True,
        vlm_backend=app.state.vlm.name,
        models_loaded=models.inventory(),
        device=str(models.device),
    )
