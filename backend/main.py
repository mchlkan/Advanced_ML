"""FastAPI entry point for Resell Copilot."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

# Load .env at import time so any module reading os.environ (e.g.
# vlm_backend factory) sees the values regardless of import order.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from backend import db  # noqa: E402
from backend.bootstrap import load_models  # noqa: E402
from backend.queue import PublishRunner  # noqa: E402
from backend.routes import inventory, listings, onboarding, publish, upload, verify  # noqa: E402
from backend.routes.upload import UPLOADS_DIR  # noqa: E402
from backend.schemas import HealthzResponse  # noqa: E402
from backend.vlm_backend import get_backend  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    skip_ml = os.environ.get("SKIP_ML", "0") == "1"

    if skip_ml:
        app.state.vlm = None
        app.state.models = None
    else:
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

    # Tests run with DISABLE_PUBLISH_RUNNER=1 so they can drive process_one_job()
    # directly without racing against the loop.
    runner: PublishRunner | None = None
    if not os.environ.get("DISABLE_PUBLISH_RUNNER"):
        runner = PublishRunner()
        runner.start()
    app.state.publish_runner = runner
    try:
        yield
    finally:
        if runner is not None:
            await runner.stop()


app = FastAPI(title="Resell Copilot API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(upload.router)
app.include_router(verify.router)
app.include_router(publish.router)
app.include_router(onboarding.router)
app.include_router(inventory.router)
app.include_router(listings.router)

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


@app.get("/healthz", response_model=HealthzResponse)
async def healthz() -> HealthzResponse:
    models = app.state.models
    vlm = app.state.vlm
    return HealthzResponse(
        ok=True,
        vlm_backend=vlm.name if vlm else "skip_ml",
        models_loaded=models.inventory() if models else [],
        device=str(models.device) if models else "none",
    )
