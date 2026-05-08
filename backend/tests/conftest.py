"""Pytest fixtures for the backend smoke tests.

Each test gets a fresh tempdir-backed DB and a stub VLM. Models load on CPU so
tests don't depend on MPS/CUDA availability.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

# Import backend.main at conftest module load so its top-level load_dotenv()
# call runs ONCE, before any fixture begins. Otherwise the first fixture's
# `from backend.main import app` line triggers load_dotenv AFTER the
# preceding monkeypatch.delenv calls, silently re-populating env vars like
# VINTED_SESSION_PATH from the project .env and breaking "unconfigured" tests.
import backend.main  # noqa: F401 — side effect: load_dotenv


@pytest.fixture(scope="session")
def loaded_models():
    os.environ.setdefault("VLM_BACKEND", "stub")
    from backend.bootstrap import load_models
    return load_models("cpu")


@pytest.fixture
def app_client(tmp_path, monkeypatch, loaded_models):
    db_path = tmp_path / "test.db"
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()

    monkeypatch.setenv("VLM_BACKEND", "stub")
    # Tests drive the publish runner manually via the drain_publish_jobs
    # helper below; the lifespan-managed runner would race with assertions.
    monkeypatch.setenv("DISABLE_PUBLISH_RUNNER", "1")
    # Default tests run with no platform integrations configured. Individual
    # tests can monkeypatch these back in if they're testing the real-publish
    # path explicitly.
    for var in (
        "VINTED_SESSION_PATH", "VINTED_DATADOME_SEED",
        "VINTED_ANON_ID", "VINTED_DEVICE_UUID", "VINTED_DEVICE_TOKEN",
        "KA_SESSION_PATH",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("backend.db.DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr("backend.routes.upload.UPLOADS_DIR", uploads_dir)

    from backend.main import app
    with TestClient(app) as client:
        client.db_path = db_path  # expose for assertions
        client.uploads_dir = uploads_dir
        yield client


@pytest.fixture
def drain_publish_jobs():
    """Run the publish runner over all currently-pending jobs synchronously.
    Backoff is collapsed to zero so retry tests don't sleep."""
    import asyncio
    from backend.queue.runner import PublishRunner

    def _drain() -> None:
        runner = PublishRunner(backoff_schedule=(0.0, 0.0, 0.0))

        async def _go() -> None:
            while await runner.process_one_job():
                pass

        asyncio.run(_go())

    return _drain


@pytest.fixture
def jpeg_bytes() -> bytes:
    img = Image.new("RGB", (320, 320), color=(80, 140, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()
