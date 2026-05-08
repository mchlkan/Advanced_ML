"""HTTP client for a RunPod Serverless VLM endpoint.

Two-call protocol per request: POST /run returns a job id, then poll
/status/{id} until COMPLETED. Polling absorbs cold-start latency
(~10-30 s with FlashBoot, ~5-15 min on the very first worker boot)
inside a single client-visible await.

Endpoint contract — handler.py returns:
    {"hidden_state": [2560 floats], "raw_text": "<JSON the VLM emitted>"}

We parse `raw_text` with parse_json_lenient on the client so the local_mps
and runpod_http backends share the parser implementation.
"""

from __future__ import annotations

import asyncio
import os
import time

import httpx
import numpy as np
from PIL import Image

from . import VLMOutput
from .util import parse_json_lenient, resize_and_b64


DEFAULT_TIMEOUT_S = 120
POLL_INTERVAL_S = 0.5
COMPLETED_STATUSES = {"COMPLETED"}
FAILED_STATUSES = {"FAILED", "CANCELLED", "TIMED_OUT"}


class RunpodHTTPVLM:
    name = "runpod_http"

    def __init__(
        self,
        endpoint_id: str | None = None,
        api_key: str | None = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_image_dim: int = 1024,
    ):
        self.endpoint_id = endpoint_id or os.environ.get("RUNPOD_ENDPOINT_ID")
        self.api_key = api_key or os.environ.get("RUNPOD_API_KEY")
        if not self.endpoint_id or not self.api_key:
            raise RuntimeError(
                "runpod_http backend requires RUNPOD_ENDPOINT_ID and "
                "RUNPOD_API_KEY in the environment (or .env)."
            )
        self.timeout_s = timeout_s
        self.max_image_dim = max_image_dim
        self._base = f"https://api.runpod.ai/v2/{self.endpoint_id}"
        self._headers = {"Authorization": f"Bearer {self.api_key}"}

    async def warmup(self) -> None:
        """No-op. RunPod workers spin up lazily on first /run; we don't pay
        cold-start cost at FastAPI startup. Set min_workers=1 in the dashboard
        if you want a worker pre-warmed for the demo window."""
        return

    async def predict(self, image: Image.Image, platform: str, hints: str | None = None) -> VLMOutput:
        payload = {
            "input": {
                "image_b64": resize_and_b64(image, max_dim=self.max_image_dim),
                "platform": platform,
                "hints": hints,
            }
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            run_resp = await client.post(f"{self._base}/run", json=payload, headers=self._headers)
            run_resp.raise_for_status()
            run_data = run_resp.json()
            job_id = run_data.get("id")
            if not job_id:
                raise RuntimeError(f"RunPod /run returned no job id: {run_data}")

            output = await self._poll_until_done(client, job_id)

        hidden = np.asarray(output["hidden_state"], dtype=np.float32)
        raw_text = output.get("raw_text", "")
        return VLMOutput(
            hidden_state=hidden,
            fields=parse_json_lenient(raw_text),
            raw_text=raw_text,
        )

    async def _poll_until_done(self, client: httpx.AsyncClient, job_id: str) -> dict:
        status_url = f"{self._base}/status/{job_id}"
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            r = await client.get(status_url, headers=self._headers)
            r.raise_for_status()
            data = r.json()
            status = data.get("status")
            if status in COMPLETED_STATUSES:
                output = data.get("output")
                if output is None:
                    raise RuntimeError(f"RunPod job {job_id} COMPLETED with no output")
                return output
            if status in FAILED_STATUSES:
                err = data.get("error") or data.get("output") or status
                raise RuntimeError(f"RunPod job {job_id} {status}: {err}")
            await asyncio.sleep(POLL_INTERVAL_S)
        raise TimeoutError(f"RunPod job {job_id} did not complete within {self.timeout_s}s")
