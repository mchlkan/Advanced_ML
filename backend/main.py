"""FastAPI entry point for Resell Copilot."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


# Load .env at import time so any module reading os.environ (e.g.
# vlm_backend factory) sees the values regardless of import order.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# iPhone photos default to HEIC, which plain Pillow can't decode. Registering
# the HEIF/HEIC opener makes Image.open() handle .heic/.heif uploads
# transparently in /upload (and /verify). Degrade rather than crash if the
# wheel is missing — HEIC uploads just keep returning the 400 they did before.
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    import logging

    logging.getLogger(__name__).warning(
        "pillow-heif not installed — HEIC/HEIF uploads will be rejected with 400"
    )


def _materialize_session(env_json_var: str, env_path_var: str, default_path: Path) -> None:
    """Containerized deploys can't easily mount secret files. If the JSON
    blob is supplied via env var, write it to disk so the existing file-based
    loaders work unchanged. Skip if a session file already exists on disk —
    that means a previous run rotated the tokens and the on-disk version is
    fresher than the env seed."""
    json_blob = os.environ.get(env_json_var)
    if not json_blob:
        return
    if os.environ.get(env_path_var):
        return  # explicit path wins
    default_path.parent.mkdir(parents=True, exist_ok=True)
    if not default_path.exists():
        default_path.write_text(json_blob)
    os.environ[env_path_var] = str(default_path)


_DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
_materialize_session("VINTED_SESSION_JSON", "VINTED_SESSION_PATH", _DATA_DIR / "vinted_session.json")
_materialize_session("KA_SESSION_JSON", "KA_SESSION_PATH", _DATA_DIR / "ka_session.json")


from backend import db  # noqa: E402
from backend.bootstrap import load_models  # noqa: E402
from backend.queue import PublishRunner  # noqa: E402
from backend.routes import inventory, onboarding, publish, upload, verify  # noqa: E402
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

# CORS: comma-separated list of origins via env var. Default "*" preserves
# local-dev behavior; production sets this to the Vercel deploy URL.
_cors_env = os.environ.get("CORS_ORIGINS", "*")
_allow_origins = ["*"] if _cors_env.strip() == "*" else [o.strip() for o in _cors_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(upload.router)
app.include_router(verify.router)
app.include_router(publish.router)
app.include_router(onboarding.router)
app.include_router(inventory.router)

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/health")
async def health() -> dict[str, str]:
    """Lightweight liveness probe — does not touch app.state, so it works
    even before model loading completes. Used by nginx upstream checks +
    the Docker HEALTHCHECK."""
    return {"status": "ok"}


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


@app.get("/vlm/status")
async def vlm_status() -> dict:
    """Status of the VLM serving backend. For the RunPod backend this proxies
    the worker/job counts from ``RunpodHTTPVLM.health()`` so a slow ``/upload``
    can be told apart as a cold start vs. RunPod throttling us. The stub /
    local_mps backends just report the backend name."""
    vlm = app.state.vlm
    if vlm is None:
        return {"backend": "skip_ml"}
    health_fn = getattr(vlm, "health", None)
    if health_fn is None:
        return {"backend": vlm.name}
    try:
        data = await health_fn()
    except Exception as exc:
        return {"backend": vlm.name, "error": f"{type(exc).__name__}: {exc}"}
    if not isinstance(data, dict):
        data = {}
    workers = data.get("workers", {})
    return {
        "backend": vlm.name,
        "throttled": int(workers.get("throttled", 0)) > 0,
        "workers": workers,
        "jobs": data.get("jobs", {}),
    }
