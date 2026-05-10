# Development guide — backend, frontend, and how to push changes

Quick operational reference. For the full engineering retrospective see
`docs/technical_report.md`; for the day-by-day collaboration log see
`docs/ai_usage_log.md`.

---

## Quick deploy reference

| What changed | Command | Time |
|---|---|---|
| Backend Python code (any file under `backend/` or `shared/`) | `git push && ssh -i ~/Downloads/Resell_Copilot.pem ubuntu@13.49.21.29 '/opt/resell/app/scripts/ec2_redeploy.sh'` | ~10 s |
| Backend dependency (`requirements-prod.txt` or `Dockerfile`) | `git push && ssh ... '/opt/resell/app/scripts/ec2_rebuild.sh'` | ~3-5 min |
| Frontend (anything under `frontend/`) | `cd frontend && vercel deploy --prod --yes` | ~30 s |
| ML head checkpoint (`*.pt` file under `models/checkpoints/`) | `scp -i ~/Downloads/Resell_Copilot.pem models/checkpoints/foo.pt ubuntu@13.49.21.29:/opt/resell/checkpoints/ && ssh ... 'sudo docker restart resell-backend'` | ~30 s |
| VLM adapter (RunPod side) | Edit `runpod/handler.py:ADAPTER_ID` default → push → rebuild RunPod worker from the dashboard | ~10 min |

EC2 IP: `13.49.21.29`. Public URLs: API
`https://resell-copilot.duckdns.org`, frontend
`https://resell-copilot-three.vercel.app` (password gate).

---

## Backend logic

### Where it runs

- **Process**: single FastAPI app via `uvicorn backend.main:app`,
  inside a Docker container on AWS EC2 (`t2.small`, Ubuntu 26.04).
- **Code source**: bind-mounted from `/opt/resell/app/{backend,shared,models}`
  on the host into `/app/{backend,shared,models}` in the container.
  The git checkout on the host is the single source of truth.
- **Data source**: SQLite at `/opt/resell/data/resell.db` (host path),
  mounted at `/app/data/resell.db` in the container. Survives
  container restarts.

### Startup (what happens when the container boots)

1. `backend/main.py` runs at import time:
   - `load_dotenv(.env)` → secrets become process env.
   - `_materialize_session(VINTED_SESSION_JSON, ...)` writes the JSON
     blob env var to `/app/data/vinted_session.json` on disk and
     sets `VINTED_SESSION_PATH` to that path. Same for KA. Lets the
     existing file-based session loaders work in containers.
2. FastAPI lifespan handler (`@asynccontextmanager`) runs:
   - `db.init_db()` — creates schema if missing, runs idempotent
     ALTER TABLE migrations.
   - `bootstrap.load_models()` — downloads/caches DINOv2 from HF, loads
     the three head checkpoints from `/app/models/checkpoints/`.
   - `vlm_backend.factory()` — picks `runpod_http` (prod), `local_mps`
     (dev), or `stub` (tests) per `VLM_BACKEND` env var.
   - `PublishRunner` started — async loop polling for pending publish
     jobs.
3. Uvicorn binds 0.0.0.0:8000.
4. Container's `HEALTHCHECK` polls `/health` every 30 s.

### Routes (one file per surface area)

Each file under `backend/routes/` is a FastAPI `APIRouter` registered
in `main.py`. The full surface:

| File | Endpoints | Purpose |
|---|---|---|
| `upload.py` | `POST /upload` | Multipart photo upload → runs the analysis pipeline → returns the unified `UploadResponse` |
| `verify.py` | `POST /verify` | Re-run the pipeline with user-supplied hint corrections; logs every changed field as a row in `edits` |
| `publish.py` | `POST /publish`, `GET /publish/status/{job_id}`, `DELETE /publish/{platform}/{platform_listing_id}` | Enqueue a publish job (returns 202 + job_id); poll status; admin endpoint to delete a platform listing directly |
| `inventory.py` | `GET /inventory`, `GET /inventory/summary`, `POST /inventory/sync`, `POST /listings/{id}/sold`, `GET /listings/{id}/image`, `GET /listings/{id}/label`, `GET /listings/{id}/prediction`, `PATCH /listings/{id}/fields`, `DELETE /listings/{id}` | Inventory list + per-listing actions (open, edit, change price, delete). Includes pull-Vinted-wardrobe-and-fold logic for the live-stats overlay. |
| `onboarding.py` | `GET /onboarding/status`, `POST /onboarding/login` (Vinted), `POST /onboarding/kleinanzeigen/initiate` + `verify-mfa` + `login` (KA) | Per-platform session bootstrap: full Auth0 + SMS MFA flow for KA, password+DataDome flow for Vinted. |

### The pipeline (`backend/pipeline.py`)

The single `run_pipeline()` async function is what `/upload` and
`/verify` both call. It runs **two VLM forwards in parallel** (one
per platform prompt) and **two LLM description calls in parallel**
(one per platform), then runs the three heads on the resulting
hidden states + DINOv2 features:

```
                    ┌─ vlm.predict(image, "vinted",         label_image)  ─┐
asyncio.gather  ┤                                                          │ → vinted_vlm.fields, vinted_vlm.hidden_state
                    └─ vlm.predict(image, "kleinanzeigen",  label_image)  ─┘   (and ka_vlm.* analogously)

dinov2_embed(image)  → 768-dim CLS                                            ─┐
flaw_head(dinov2)    → visual_wear_probability                                │
                                                                              │
                    ┌─ generate_description(vinted_vlm.fields, ...)        ─┐│
asyncio.gather  ┤                                                          │ │ → vinted_desc, ka_desc
                    └─ generate_description(ka_vlm.fields, ...)            ─┘│
                                                                              │
price_head(vinted_vlm.hidden_state, visual_wear, ..., "vinted")         ─────┘ → q10/q50/q90 vinted
price_head(ka_vlm.hidden_state, visual_wear, ..., "kleinanzeigen")      ─────  → q10/q50/q90 ka
sell_head(meta + visual_wear)                                           ─────  → vinted sell_prob
```

Returns a dict with two parallel platform blocks, each containing
identification + price band + (optional) sell probability +
description. The route layer wraps this in `UploadResponse`.

### The publish runner (`backend/queue/runner.py`)

Async task started at app boot. Polls the `publishes` table for
`status='pending'` rows where `next_attempt_at <= now`. For each:

1. Validate fields (catalog_id present for Vinted, category_id
   present for KA — short-circuits with a clear error if mapping
   misses).
2. Build per-platform payload via `to_vinted` / `to_kleinanzeigen`
   from `shared/listing_mappings.py`.
3. Call the integration: `vinted.publish(image_path, payload)` or
   `ka.publish(image_path, payload)`. These do photo upload → submit
   → return `(item_id, listing_url)`.
4. On success: update row to `status='posted'` with the URL.
5. On retryable failure (DataDome 429, network blip): re-queue with
   exponential backoff, increment `retry_count`.
6. On permanent failure (validation, auth): `status='failed'` with
   the error in the `error` column.

Frontend polls `GET /publish/status/{job_id}` every 1.5 s with a 90 s
budget.

### Integrations (the reverse-engineered bits)

| Module | What it does | Notable |
|---|---|---|
| `backend/integrations/vinted.py` | Vinted mobile API client. Photo upload → 3-step draft → completion. Includes DataDome cookie refresh, brand resolution + caching. Live-item edit (`update_listing`) and delete (`delete_live_item`) discovered via OPTIONS+POST probing. | 738 lines |
| `backend/integrations/kleinanzeigen.py` | KA mobile API client. JAXB-XML body builder, full Auth0 PKCE login + SMS MFA, refresh-token rotation, picture-link extraction, edit/delete on `/api/users/{user_id}/ads/{ad_id}.json`. | 910+ lines |
| `backend/vlm_backend/runpod_http.py` | Async client for the RunPod Serverless endpoint serving Qwen3-VL + LoRA. Two-call protocol (`POST /run` → poll `/status/{id}`) wrapped in one `await predict()`. | ~130 lines |
| `backend/vlm_backend/local_mps.py` | In-process Qwen3-VL on Apple MPS for local dev. Loads base + adapter from HF. | ~160 lines |
| `backend/description.py` | Model #6: Groq Llama 3.1 8B with category-matched few-shot prompt. Falls back to a deterministic template on failure so the pipeline never blocks. | |

### The DB (`backend/db.py`)

Single SQLite file, six tables. Schema is created at startup; missing
columns are added via idempotent `ALTER TABLE` migrations. All access
goes through `aiosqlite`. Tables:

- **`listings`** — one row per upload. Holds the image path(s),
  vlm_backend used, created_at.
- **`predictions`** — append-only. One row per upload + one per
  /verify + one per PATCH. Latest-wins on read. Carries the canonical
  English fields (JSON) + per-platform price quantiles + visual wear.
- **`edits`** — audit trail of user-corrected fields (one row per
  field change).
- **`publishes`** — per-publish-job state machine row. Includes
  `final_fields` (the exact payload sent), `status`, `retry_count`,
  `platform_listing_id`, `platform_listing_url`, `error`.
- **`wardrobe_snapshots`** — fetched live state of posted Vinted
  items (price, views, favourites). Used by the inventory overlay.
- **`wardrobe_syncs`** — sync attempts (timestamps + status) so we
  can detect stale data.

---

## Frontend logic

### Stack

- Next.js 14 App Router, TypeScript, single SPA route at `/`.
- Inline styles only (no Tailwind, no CSS modules) — easy to grep,
  no build pipeline beyond Next's own.
- oklch color tokens (`oklch(0.62 0.15 145)` is the brand green).
- Middleware password gate — `frontend/src/middleware.ts` checks
  `resell-auth=ok` cookie; redirects to `/login` if missing.

### Screen state machine (`frontend/src/app/page.tsx`)

A single `useState` holds an `AppState` discriminated union. Six
states, transitions are all explicit `setState` calls:

```
   ┌──────────────────────────────────────────────────────────────────┐
   │                                                                  │
   │  ┌─────────┐                ┌──────────┐                         │
   │  │ upload  │ ── handleSubmit ▶ analyzing ── /upload finishes ─┐  │
   │  └─────────┘                └──────────┘                      │  │
   │       ▲                                                        ▼ │
   │       │                                            ┌─────────────┴─┐
   │       │ handleReset                                │    results    │
   │       │ (Sell another / cancel)                    │  edit fields  │
   │       │                                            │   /verify     │
   │       │                                            └────┬──────────┘
   │       │                                                 │ Publish CTA
   │       │                                                 ▼
   │       │                                      ┌────────────────────┐
   │       │                                      │     publishing     │
   │       │                                      │   /publish + poll  │
   │       │                                      └────┬───────────────┘
   │       │                                           │
   │       │      ┌────────────────────────────────────┘
   │       │      ▼
   │       │  ┌─────────────────────┐
   │       │  │      published      │
   │       │  │ (link opens in tab) │
   │       │  └─────────────────────┘
   │       │
   │       │  Inventory branch (entered from any screen via "My listings"):
   │       │
   │       │  ┌──────────┐  kebab → Open       ┌─────────────┐
   │       └──┤inventory ├──────────────────────▶  results    │ (with stored prediction)
   │          └────┬─────┘                     └─────────────┘
   │               │  kebab → Relist (one-click)
   │               ├──────────▶ publishing → published
   │               │
   │               │  kebab → Change price (modal stays open during save)
   │               │  kebab → Mark sold / Delete (confirm + cleanup)
   └───────────────┘
```

State variants (in `page.tsx:22-44`):

```ts
type AppState =
  | { screen: "upload" }
  | { screen: "inventory" }
  | { screen: "analyzing"; imageUrl; file; labelImageUrl?; labelFile? }
  | { screen: "results"; imageUrl; data; labelImageUrl? }
  | { screen: "publishing"; imageUrl; data; platform; labelImageUrl? }
  | { screen: "published"; platform; listingUrl; results }
```

### Components (`frontend/src/components/`)

| Component | Renders | Key props |
|---|---|---|
| `UploadScreen` | Two-phase picker: PickPhase (camera + library buttons) → ReviewPhase (main thumbnail + optional brand/size tag panel + Continue). Owns object-URL lifecycle. | `onSubmit(file, url, labelFile?, labelUrl?)` |
| `AnalyzingScreen` | Spinner + step indicators while `/upload` is in flight. Shows main image with optional label thumbnail overlay. | `imageUrl, labelImageUrl?, onCancel` |
| `ResultsScreen` | The big one. Shows identification chips, edit form, price bands per platform, draft listing copy, sticky Publish CTA. Reused by both fresh-upload and inventory-Open paths. | `imageUrl, data, labelImageUrl?, connectionStatus, onPublish, onReset, onConnectPlatform, error?` |
| `PublishingScreen` | Spinner during the publish + poll loop. | `platform` |
| `PublishedScreen` | Success page with "Live on Vinted" badge + Reopen tab + cross-post tip. | `platform, listingUrl, results, onReset` |
| `InventoryScreen` | Inventory list with per-card kebab → ActionSheet (Open / Change price / Relist / Mark sold / Delete) + inline PriceEditModal + ConfirmDialog. | `onBack, onOpenListing, onRelistListing` |
| `PlatformConnectionBanner` | Persistent banner at top showing per-platform connection state; tap to open login modal. | `status, onConnect` |
| `PlatformLoginModal` | Multi-phase modal: credentials → MFA → refresh-token. Per-platform forms. | `platform, onClose, onSuccess` |

### API clients (`frontend/src/api/*.ts`)

Thin typed wrappers over `fetch`. One file per backend route group:

- `upload.ts` — `uploadImage(file, labelFile?)`
- `verify.ts` — `verifyListing({ listing_id, hints })`
- `publish.ts` — `publishListing(req)`, `pollPublishStatus(jobId, opts?)`
- `inventory.ts` — `fetchInventory()`, `markAsSold(id)`,
  `fetchListingPrediction(id)`, `patchListingFields(id, fields)`,
  `deleteListing(id)`
- `onboarding.ts` — `fetchOnboardingStatus()`, `loginVinted(...)`,
  `initiateKaLogin(...)`, `verifyKaMfa(...)`, etc.

All return typed promises against the interfaces in
`frontend/src/types/api.ts`.

### How edits propagate (the multi-platform push pattern)

When the user changes a price on a listing posted to both platforms:

1. PriceEditModal calls `patchListingFields(listingId, {price_eur:
   new_price})`
2. Backend `PATCH /listings/{id}/fields`:
   - Stores a new `predictions` row with `source='edit'` and merged
     fields.
   - Looks up the listing's posted publishes.
   - For each posted platform, calls the integration's
     `update_listing(platform_id, payload)` **in parallel via
     `asyncio.gather`** (since Vinted + KA are independent).
   - Returns `{stored: true, pushed: {vinted: {ok: true}, kleinanzeigen: {ok: false, error: "..."}}}`.
3. PriceEditModal stays open during save, then renders ✓/✗ per
   platform. Auto-closes 1.2 s after a fully successful save; stays
   open with the error visible if any push failed.

---

## How to push changes

### A) Backend Python code change (most common)

Edit any `.py` file under `backend/` or `shared/`. Then:

```bash
git add backend/foo.py
git commit -m "..."
git push origin feature/deploy-prep

ssh -i ~/Downloads/Resell_Copilot.pem ubuntu@13.49.21.29 \
  '/opt/resell/app/scripts/ec2_redeploy.sh'
```

Total time: ~10 s (the script does `git pull` + `docker restart` +
polls `/health` until ready). Code is bind-mounted, so no image
rebuild needed.

If you forget the push and the EC2 still has older code, the script
prints the new git hash so you can confirm.

### B) Backend dep change (`requirements-prod.txt` or `Dockerfile`)

```bash
git add requirements-prod.txt
git commit -m "Add some-package"
git push origin feature/deploy-prep

ssh -i ~/Downloads/Resell_Copilot.pem ubuntu@13.49.21.29 \
  '/opt/resell/app/scripts/ec2_rebuild.sh'
```

Total time: ~3-5 min (full image rebuild). Uses `docker build` with
the existing layer cache; only new pip deps need to be downloaded.

### C) Frontend change

```bash
# Either commit/push first (recommended for git history) or skip
git add frontend/src/foo.tsx
git commit -m "..."
git push origin feature/deploy-prep

cd frontend
vercel deploy --prod --yes
```

Total time: ~30 s. **Must `cd frontend` first** — running from repo
root auto-detects FastAPI and 400s with "Project names cannot
contain '---'".

The deploy returns an alias URL — the canonical alias
`resell-copilot-three.vercel.app` always points at the latest
production deploy.

### D) ML head checkpoint update (`*.pt` file)

`.pt` files are gitignored. Drop them on EC2 directly:

```bash
# Optional: back up the existing version
ssh -i ~/Downloads/Resell_Copilot.pem ubuntu@13.49.21.29 \
  'sudo cp /opt/resell/checkpoints/foo.pt /opt/resell/checkpoints/foo.pt.bak.$(date +%s)'

# Upload the new one
scp -i ~/Downloads/Resell_Copilot.pem \
  models/checkpoints/foo.pt \
  ubuntu@13.49.21.29:/opt/resell/checkpoints/

# Restart the container so bootstrap.load_models() re-reads it
ssh -i ~/Downloads/Resell_Copilot.pem ubuntu@13.49.21.29 \
  'sudo docker restart resell-backend'
```

`bootstrap.py` reads model architecture from the `.pt`'s pickled
`model_config` so most architecture changes are absorbed
automatically — no code change needed.

### E) VLM adapter update (RunPod side)

Two changes needed:

```bash
# 1. Bump the default in the worker source
edit runpod/handler.py:ADAPTER_ID
git commit -am "Adapter v3"
git push

# 2. Rebuild the RunPod worker from the dashboard:
#    https://www.runpod.io/console/serverless
#    → your endpoint → Settings → Edit Template → save (triggers rebuild)
```

The backend doesn't need redeployment — it just talks to whatever
endpoint `RUNPOD_ENDPOINT_ID` is set to in `.env.prod`. If you spin
up a NEW endpoint with the new adapter, update `RUNPOD_ENDPOINT_ID`
on EC2 and `docker rm -f resell-backend && ec2_rebuild.sh` (env-file
isn't re-read on simple restart).

### F) Secrets / `.env.prod` change

```bash
# Edit on EC2 directly
ssh -i ~/Downloads/Resell_Copilot.pem ubuntu@13.49.21.29
sudo nano /opt/resell/app/.env.prod
# add/change values, save

# env-file is only re-read at container CREATION, so:
sudo docker rm -f resell-backend
sudo /opt/resell/app/scripts/ec2_rebuild.sh
```

**Don't commit `.env.prod`** — it's in `.gitignore` (`.env.*`
pattern catches it).

---

## Common debug operations

### Watch the live container logs

```bash
ssh -i ~/Downloads/Resell_Copilot.pem ubuntu@13.49.21.29 \
  'sudo docker logs -f --tail 100 resell-backend'
```

Useful filters:
```bash
... | grep -iE "POST /publish|publish job|kleinanzeigen|vinted|error"
```

### Inspect production DB

```bash
ssh -i ~/Downloads/Resell_Copilot.pem ubuntu@13.49.21.29 \
  'sudo docker exec resell-backend python -c "
import sqlite3
con = sqlite3.connect(\"/app/data/resell.db\")
for r in con.execute(\"SELECT id, platform, status, platform_listing_url FROM publishes ORDER BY rowid DESC LIMIT 10\"):
    print(r)
"'
```

(`sqlite3` isn't installed on the host; using the container's Python
is the workaround.)

### Run a probe script inside the container

The probe scripts under `scripts/probe_*.py` import the integrations
and need the live session env vars. Container run pattern:

```bash
scp -i ~/Downloads/Resell_Copilot.pem scripts/probe_X.py \
  ubuntu@13.49.21.29:/tmp/

ssh -i ~/Downloads/Resell_Copilot.pem ubuntu@13.49.21.29 \
  'sudo docker cp /tmp/probe_X.py resell-backend:/app/probe_X.py && \
   sudo docker exec -e VINTED_SESSION_PATH=/app/data/vinted_session.json \
                    -e KA_SESSION_PATH=/app/data/ka_session.json \
                    resell-backend python /app/probe_X.py <args>'
```

### Run backend tests locally

```bash
.venv/bin/python -m pytest backend/tests/ -q
```

123 tests at last count, ~85 s wall-clock.

### Frontend dev with the live backend

```bash
cd frontend
NEXT_PUBLIC_API_URL=https://resell-copilot.duckdns.org npm run dev
```

Then `http://localhost:3000`. The middleware password gate still
applies on first visit.

### Vercel inspect a specific deploy

```bash
cd frontend
vercel inspect <deployment-url-from-deploy-output>
```

Or list recent: `vercel ls`.

---

## Where stuff lives — top-level repo map

```
Advanced_ML/
├── backend/                # FastAPI app (see "Backend logic" above)
├── shared/                 # Used by both backend and training
│   ├── prompts.py          # VLM prompt per platform
│   ├── translations.py     # DE↔EN field maps
│   └── listing_mappings.py # Canonical fields → per-platform payloads + KA color/category enums
├── models/                 # Training scripts (run offline / on Colab)
│   └── checkpoints/        # gitignored .pt files, bind-mounted on EC2
├── runpod/handler.py       # RunPod Serverless worker (built+deployed via RunPod dashboard)
├── frontend/               # Next.js SPA (see "Frontend logic" above)
├── scripts/
│   ├── ec2_rebuild.sh      # Slow-path backend deploy (image rebuild)
│   ├── ec2_redeploy.sh     # Fast-path backend deploy (bind-mount restart)
│   └── probe_*.py          # API discovery utilities (commit reusable!)
├── docs/
│   ├── deploy_plan.md      # Original full deploy runbook
│   ├── ka_endpoints.md     # KA mobile API reference
│   ├── ka_category_probe.json   # KA discovery output
│   ├── model_stack_evolution.md # Per-version model history
│   ├── ai_usage_log.md     # Prompt-by-prompt collaboration log
│   ├── technical_report.md # Engineering retrospective
│   └── development.md      # This document
├── .env                    # local dev secrets (gitignored)
├── requirements-prod.txt   # backend pip deps
└── Dockerfile              # backend container image
```

---

## TL;DR if you only read one section

- **Backend on EC2** at `13.49.21.29`, code bind-mounted from
  `/opt/resell/app/`. To deploy a Python change: `git push` then
  `ssh ... ec2_redeploy.sh`. **10 seconds**.
- **Frontend on Vercel**. To deploy: `cd frontend && vercel deploy
  --prod --yes`. **30 seconds**.
- **VLM on RunPod** (separate infrastructure). Backend doesn't need
  redeploy when the adapter changes — just bump
  `RUNPOD_ENDPOINT_ID` if the endpoint moves.
- **DB on EC2** at `/opt/resell/data/resell.db`. Inspect via
  `docker exec resell-backend python -c "..."` (sqlite3 isn't
  installed on the host).
- **Probe scripts** under `scripts/probe_*.py` are how we discovered
  every undocumented platform endpoint. Reusable for future
  spelunking.
