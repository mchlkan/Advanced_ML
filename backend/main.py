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
    device_pref = os.environ.get("DEVICE", "auto")
    app.state.models = load_models(device_pref)
    app.state.vlm = get_backend()
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
