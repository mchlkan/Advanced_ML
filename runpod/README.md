# RunPod Serverless VLM endpoint

The Qwen3-VL-4B + LoRA half of the inference pipeline runs here. The Mac
FastAPI backend calls this endpoint via HTTP for the heavy VLM forward +
generate; everything else (DINOv2, MLP heads) stays in-process.

## What's in this directory

- `Dockerfile` — base `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04`,
  pip-installs the deps in `requirements.txt`, copies `shared/` and
  `handler.py` into the image. Build context is the repo root. The handler
  is self-contained: `build_inputs` and `model_device` are inlined so the
  worker doesn't depend on the training module's churn.
- `handler.py` — module-init loads the model + adapter once. `handler(event)`
  runs forward + generate and returns `{hidden_state, raw_text}`.
- `requirements.txt` — pinned dep set; same versions used during the Day-3
  training extraction, so the runtime API matches what we trained against.
- `.dockerignore` — excludes data, notebooks, checkpoints, frontend, etc.,
  to keep the build context small.

## Build + push (from repo root)

The build context is the **repo root**, not the `runpod/` directory, because
the Dockerfile `COPY`s files from `shared/` and `models/`.

```bash
# One-time GHCR login (assumes $GH_TOKEN is a PAT with write:packages):
echo $GH_TOKEN | docker login ghcr.io -u Leon-71644 --password-stdin

# Build for x86_64 GPU hardware. ~10-15 min on Apple Silicon (QEMU emulation).
docker buildx build \
  --platform linux/amd64 \
  -f runpod/Dockerfile \
  -t ghcr.io/rengo33/resell-vlm:latest \
  --push \
  .
```

If GHCR is awkward, swap the `-t` tag to `docker.io/<user>/resell-vlm:latest`
and `docker login docker.io` instead — no other change needed.

## Deploy on RunPod

1. RunPod dashboard → **Serverless** → **Endpoints** → **Create New Endpoint**.
2. **Container image:** `ghcr.io/rengo33/resell-vlm:latest` (mark as private if your GHCR package is private — provide the GHCR PAT as a registry credential).
3. **Container disk:** 25 GB. The 8 GB Qwen base + adapter + cache fit comfortably with headroom.
4. **Workers:**
   - **GPU type:** RTX 4090 (24 GB VRAM — plenty for the 4B model in bf16, ~8 GB weights + a few GB of activations) or A4000 16 GB (cheaper; also fits).
   - **Min workers:** `0` for dev, `1` during the demo window for zero cold starts.
   - **Max workers:** `1` recommended. The backend issues two parallel `/run`
     calls per `/upload` (one per platform prompt). With `max_workers > 1`,
     RunPod's autoscaler tries to spawn a second worker — fine when stable,
     but during a crash loop it multiplies failures across N workers. Keep
     `max_workers=1` until you've confirmed warm calls succeed end-to-end;
     the second platform call queues for ~2 s, so /upload latency is
     ~4-6 s warm instead of ~2-3 s. Bump to `2` only after you're stable.
   - **Idle timeout:** `600` seconds — workers stay warm 10 min between calls.
   - **FlashBoot:** ON. Snapshots warm workers so subsequent cold starts skip the 8 GB model download.
5. **Environment variables:**
   - `HF_TOKEN` = your HF read token (gated-repo access required for `Qwen/Qwen3-VL-4B-Instruct` + `Rengo33/qwen3vl4b-resell-adapter`).
   - Optional: `MAX_NEW_TOKENS=256`, `BASE_MODEL=Qwen/Qwen3-VL-4B-Instruct`, `ADAPTER_ID=Rengo33/qwen3vl4b-resell-adapter`.
6. Save → note the **Endpoint ID**.

## Wire into the FastAPI backend

Add to `.env` at the repo root (gitignored):

```
RUNPOD_API_KEY=<your runpod api key from Settings → API Keys>
RUNPOD_ENDPOINT_ID=<the endpoint id from above>
```

Then run the backend:

```bash
VLM_BACKEND=runpod_http uvicorn backend.main:app --port 8000
```

## Verifying it works

```bash
curl http://localhost:8000/healthz
curl -F image=@some_jacket.jpg http://localhost:8000/upload | jq
```

**Latencies:**
- First-ever call after endpoint creation: 5–15 min (cold start + 8 GB
  Qwen download to the worker).
- Subsequent calls within 600 s idle: ~2–4 s warm.
- Cold start after idle expires: ~10–30 s (FlashBoot snapshot).

## Demo-day runbook

15 min before the panel:
1. Set `min_workers=1` in the endpoint config — RunPod spins up a worker now.
2. Send one warm-up `/upload` call to make sure the snapshot is fully ready.
3. Watch the dashboard — worker should be in "Ready" state.

After the panel: flip `min_workers` back to `0` so you stop paying for an
idle worker.

## Troubleshooting

- **401 from RunPod API**: `RUNPOD_API_KEY` wrong or revoked.
- **Worker `FAILED` immediately**: check worker logs in RunPod dashboard. The
  handler prints `[boot] HF_TOKEN: set (len=...)` or `MISSING` first. If
  MISSING, the env var didn't reach the endpoint — check Settings → Env Vars.
  If set but boot fails on adapter load with `Can't find 'adapter_config.json'`,
  the token doesn't have access to the private adapter repo. Regenerate at
  https://huggingface.co/settings/tokens with "Read" role and the adapter
  repo explicitly granted.
- **Worker `FAILED` mid-run with OOM**: GPU smaller than ~16 GB, or something
  else is sharing the VRAM — switch to a ≥16 GB GPU. The bf16 4B model is
  ~8 GB of weights plus a few GB of activations on a ~2K-token prefill.
- **Backend `RuntimeError: worker error: ...`**: handler returned an error
  payload (bad input or shape mismatch). The error string in the message
  is verbatim from the worker.
- **Backend `RuntimeError: hidden_state of shape ...`**: model returned a
  hidden state of the wrong dimension. Check `EXPECTED_HIDDEN_DIM` env var
  on both the endpoint and `runpod_http.py` — must match the base model.
- **Backend gets `TimeoutError`**: cold start exceeding the default 120 s.
  Either flip `min_workers=1` or bump `timeout_s` on `RunpodHTTPVLM`.
- **Workers keep spawning even when idle**: cancel pending jobs in the
  endpoint's *Requests* tab — failed jobs get retried on fresh workers
  until they hit their per-job timeout. Set `Max Workers = 1` to cap the
  blast radius.
