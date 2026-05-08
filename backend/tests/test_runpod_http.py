"""Mocked HTTP tests for RunpodHTTPVLM.

We don't hit the real RunPod API in CI — respx intercepts httpx calls and
lets us script /run + /status responses for warm, cold-start, FAILED, and
timeout scenarios."""

from __future__ import annotations

import asyncio
import os

import httpx
import numpy as np
import pytest
import respx
from PIL import Image

from backend.vlm_backend.runpod_http import RunpodHTTPVLM


ENDPOINT_ID = "test-endpoint-123"
API_KEY = "test-key"
BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"
JOB_ID = "job-abc"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", ENDPOINT_ID)
    monkeypatch.setenv("RUNPOD_API_KEY", API_KEY)


@pytest.fixture
def jpeg_image() -> Image.Image:
    return Image.new("RGB", (640, 480), color=(80, 140, 200))


def _completed_payload(text: str = '{"brand": "Zara", "category": "jackets"}') -> dict:
    hidden = [0.0] * 2560
    hidden[0] = 1.5
    return {
        "id": JOB_ID,
        "status": "COMPLETED",
        "output": {"hidden_state": hidden, "raw_text": text},
    }


def test_missing_env_vars_raises(monkeypatch):
    monkeypatch.delenv("RUNPOD_ENDPOINT_ID", raising=False)
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="RUNPOD_ENDPOINT_ID"):
        RunpodHTTPVLM()


@respx.mock
def test_warm_completes_in_one_status_call(jpeg_image):
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": JOB_ID, "status": "IN_QUEUE"}))
    respx.get(f"{BASE_URL}/status/{JOB_ID}").mock(return_value=httpx.Response(200, json=_completed_payload()))

    vlm = RunpodHTTPVLM(timeout_s=10)
    out = asyncio.run(vlm.predict(jpeg_image, "vinted"))

    assert out.fields["brand"] == "Zara"
    assert out.fields["category"] == "jackets"
    assert isinstance(out.hidden_state, np.ndarray)
    assert out.hidden_state.shape == (2560,)
    assert out.hidden_state.dtype == np.float32
    assert out.hidden_state[0] == pytest.approx(1.5)


@respx.mock
def test_cold_start_polls_until_completed(jpeg_image):
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": JOB_ID, "status": "IN_QUEUE"}))
    status_route = respx.get(f"{BASE_URL}/status/{JOB_ID}").mock(side_effect=[
        httpx.Response(200, json={"id": JOB_ID, "status": "IN_QUEUE"}),
        httpx.Response(200, json={"id": JOB_ID, "status": "IN_PROGRESS"}),
        httpx.Response(200, json={"id": JOB_ID, "status": "IN_PROGRESS"}),
        httpx.Response(200, json=_completed_payload()),
    ])

    vlm = RunpodHTTPVLM(timeout_s=10)
    out = asyncio.run(vlm.predict(jpeg_image, "kleinanzeigen"))

    assert status_route.call_count == 4
    assert out.fields["brand"] == "Zara"


@respx.mock
def test_failed_status_raises(jpeg_image):
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": JOB_ID, "status": "IN_QUEUE"}))
    respx.get(f"{BASE_URL}/status/{JOB_ID}").mock(return_value=httpx.Response(200, json={
        "id": JOB_ID, "status": "FAILED", "error": "OOM in worker",
    }))

    vlm = RunpodHTTPVLM(timeout_s=10)
    with pytest.raises(RuntimeError, match="FAILED.*OOM"):
        asyncio.run(vlm.predict(jpeg_image, "vinted"))


@respx.mock
def test_timeout_raises(jpeg_image):
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": JOB_ID, "status": "IN_QUEUE"}))
    respx.get(f"{BASE_URL}/status/{JOB_ID}").mock(return_value=httpx.Response(200, json={
        "id": JOB_ID, "status": "IN_PROGRESS",
    }))

    vlm = RunpodHTTPVLM(timeout_s=1)
    with pytest.raises(TimeoutError, match="did not complete"):
        asyncio.run(vlm.predict(jpeg_image, "vinted"))


@respx.mock
def test_run_without_job_id_raises(jpeg_image):
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"status": "ERROR"}))

    vlm = RunpodHTTPVLM(timeout_s=10)
    with pytest.raises(RuntimeError, match="no job id"):
        asyncio.run(vlm.predict(jpeg_image, "vinted"))


@respx.mock
def test_worker_error_payload_raises(jpeg_image):
    """Worker returned COMPLETED with output={'error': ...} — bad input or
    shape mismatch in the handler. Must surface as a clear RuntimeError, not
    a confusing KeyError on output['hidden_state']."""
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": JOB_ID, "status": "IN_QUEUE"}))
    respx.get(f"{BASE_URL}/status/{JOB_ID}").mock(return_value=httpx.Response(200, json={
        "id": JOB_ID,
        "status": "COMPLETED",
        "output": {"error": "could not decode image_b64"},
    }))

    vlm = RunpodHTTPVLM(timeout_s=10)
    with pytest.raises(RuntimeError, match="worker error.*decode"):
        asyncio.run(vlm.predict(jpeg_image, "vinted"))


@respx.mock
def test_malformed_output_raises(jpeg_image):
    """Worker returned COMPLETED but output is missing required keys —
    surface a clear error rather than KeyError downstream."""
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": JOB_ID, "status": "IN_QUEUE"}))
    respx.get(f"{BASE_URL}/status/{JOB_ID}").mock(return_value=httpx.Response(200, json={
        "id": JOB_ID,
        "status": "COMPLETED",
        "output": {"hidden_state": [0.0] * 2560},  # missing raw_text
    }))

    vlm = RunpodHTTPVLM(timeout_s=10)
    with pytest.raises(RuntimeError, match="malformed output"):
        asyncio.run(vlm.predict(jpeg_image, "vinted"))


@respx.mock
def test_wrong_hidden_dim_raises(jpeg_image):
    """Worker returned hidden_state of unexpected dimension — likely a model
    config mismatch. Catch it client-side rather than letting downstream
    matmuls fail with a tensor shape error."""
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": JOB_ID, "status": "IN_QUEUE"}))
    respx.get(f"{BASE_URL}/status/{JOB_ID}").mock(return_value=httpx.Response(200, json={
        "id": JOB_ID,
        "status": "COMPLETED",
        "output": {"hidden_state": [0.0] * 1024, "raw_text": "{}"},
    }))

    vlm = RunpodHTTPVLM(timeout_s=10)
    with pytest.raises(RuntimeError, match="hidden_state of shape"):
        asyncio.run(vlm.predict(jpeg_image, "vinted"))


@respx.mock
def test_authorization_header_sent(jpeg_image):
    run_route = respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": JOB_ID, "status": "IN_QUEUE"}))
    respx.get(f"{BASE_URL}/status/{JOB_ID}").mock(return_value=httpx.Response(200, json=_completed_payload()))

    vlm = RunpodHTTPVLM(timeout_s=10)
    asyncio.run(vlm.predict(jpeg_image, "vinted"))

    assert run_route.called
    sent = run_route.calls[0].request
    assert sent.headers.get("authorization") == f"Bearer {API_KEY}"


@respx.mock
def test_payload_includes_b64_image_and_platform(jpeg_image):
    import json as _json
    run_route = respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": JOB_ID, "status": "IN_QUEUE"}))
    respx.get(f"{BASE_URL}/status/{JOB_ID}").mock(return_value=httpx.Response(200, json=_completed_payload()))

    vlm = RunpodHTTPVLM(timeout_s=10)
    asyncio.run(vlm.predict(jpeg_image, "kleinanzeigen", hints="brand=Zara"))

    body = _json.loads(run_route.calls[0].request.content)
    assert body["input"]["platform"] == "kleinanzeigen"
    assert body["input"]["hints"] == "brand=Zara"
    assert isinstance(body["input"]["image_b64"], str)
    assert len(body["input"]["image_b64"]) > 100  # non-empty JPEG
