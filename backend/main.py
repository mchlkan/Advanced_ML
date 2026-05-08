"""FastAPI entry point for Resell Copilot."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

# Load .env at import time so any module reading os.environ (e.g.
# vlm_backend factory) sees the values regardless of import order.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from backend import db  # noqa: E402
from backend.bootstrap import load_models  # noqa: E402
from backend.routes import onboarding, publish, upload, verify  # noqa: E402
from backend.schemas import HealthzResponse  # noqa: E402
from backend.vlm_backend import get_backend  # noqa: E402


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
app.include_router(onboarding.router)


@app.get("/healthz", response_model=HealthzResponse)
async def healthz() -> HealthzResponse:
    models = app.state.models
    return HealthzResponse(
        ok=True,
        vlm_backend=app.state.vlm.name,
        models_loaded=models.inventory(),
        device=str(models.device),
    )
