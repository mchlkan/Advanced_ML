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
    # Default tests run with no platform integrations configured. Individual
    # tests can monkeypatch these back in if they're testing the real-publish
    # path explicitly.
    for var in (
        "VINTED_SESSION_PATH", "VINTED_DATADOME_SEED",
        "VINTED_ANON_ID", "VINTED_DEVICE_UUID", "VINTED_DEVICE_TOKEN",
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
def jpeg_bytes() -> bytes:
    img = Image.new("RGB", (320, 320), color=(80, 140, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()
