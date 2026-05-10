# Deploy Plan — Resell Copilot to Vercel + AWS EC2

**Status:** Phase 1 + 2 code changes landed on `feature/deploy-prep`. Phase 3 (AWS EC2 setup) and Phase 1.6 (Vercel deploy) still need execution.

**Goal:** Persistent public URL (Vercel) for the frontend, gated by a shared
password. Backend hosted on user's existing free-tier AWS EC2 instance.
Real Vinted + KA publishing enabled for anyone who clears the password.

## Confirmed inputs (2026-05-10)

| Item | Value |
|---|---|
| EC2 instance | t2.small (2 GB RAM) — upgraded from t3.micro mid-planning |
| EC2 OS | Ubuntu 26.04 LTS |
| EC2 public IP | `13.49.21.29` (eu-north-1, Stockholm) |
| Domain | `resell-copilot.duckdns.org` (DuckDNS A-record points at the IP) |
| SSH key | `/Users/leonschmidt/Downloads/Resell_Copilot.pem` (chmod 400, ED25519 host key trusted) |
| Password | `Advanced_ML` (corrected from typed `Advancded_ML`) |

## Course corrections vs the original plan

1. **Architecture (§4.1):** original plan claimed `requirements.txt` could
   slim to ~150 MB because "VLM goes through runpod_http.py so no torch
   needed locally." This was wrong — `backend/bootstrap.py` loads DINOv2
   (~340 MB) + 3 head MLPs at startup, which require `torch`,
   `transformers`, `numpy`, `huggingface_hub`. Production image is ~1.5 GB.
   Memory pressure was a concern on t3.micro (1 GB) but is fine on t2.small (2 GB).
2. **Instance:** upgraded from t3.micro to t2.small mid-planning for DINOv2 headroom.
3. **IP:** changed from `51.21.3.235` (t3.micro) to `13.49.21.29` (t2.small).

---

## 1. Topology

```
                              ┌────────────────────────────────┐
                              │  Browser (anyone w/ password)  │
                              └───────────────┬────────────────┘
                                              │ HTTPS
                                              ▼
        ┌──────────────────────────────────────────────────────┐
        │  Vercel — Next.js frontend                           │
        │  - Middleware password gate (cookie-based)           │
        │  - NEXT_PUBLIC_API_URL → AWS backend                 │
        └──────────────────────┬───────────────────────────────┘
                               │ HTTPS (CORS-locked to Vercel domain)
                               ▼
        ┌──────────────────────────────────────────────────────┐
        │  AWS EC2 — FastAPI + SQLite + uploads                │
        │  - Docker container or systemd service               │
        │  - SQLite + uploads on EBS persistent volume         │
        │  - nginx reverse proxy + Let's Encrypt SSL           │
        └────────┬───────────────────┬────────────────┬────────┘
                 │                   │                │
                 ▼                   ▼                ▼
       ┌──────────────────┐  ┌───────────────┐  ┌──────────────┐
       │ RunPod Serverless│  │ Vinted API    │  │ KA mobile API│
       │ (VLM, Model #1)  │  │ + DataDome    │  │              │
       └──────────────────┘  └───────────────┘  └──────────────┘
                 │
                 ▼
       ┌──────────────────┐
       │ Groq Llama 3.1 8B│
       │ (Model #6 prose) │
       └──────────────────┘
```

---

## 2. Assumptions to confirm or correct

If any of these are wrong, the plan needs to change. Please flag.

| Assumption | If wrong, impact |
|---|---|
| AWS instance is **t3.micro or larger** (≥1 GB RAM) | t2.nano won't fit FastAPI + Pillow. Would need swap or a larger instance |
| AWS instance is **Ubuntu 22.04 or 24.04** (or Amazon Linux 2023) | Different distro = different package install commands |
| AWS instance has a **public IPv4** (or Elastic IP) | Required for Vercel to reach it. Without one, you'd need a tunnel |
| You have or can register **a domain name** pointing at the EC2 IP | Required for Let's Encrypt SSL. Without one, browsers will block mixed-content (HTTPS Vercel calling HTTP backend) |
| AWS security group can **open ports 80 + 443 + 22** to public | Required for HTTP, HTTPS, and SSH |
| You have **SSH key-based access** to the instance | Required for me to walk you through deploy commands |
| The EC2 region is **eu-central-1 / eu-west-1** (close to EU users) | If it's us-east-1, Vinted API latency will add ~100ms per call. Not a blocker |
| **Nothing else is running on port 80/443** on the instance | Otherwise nginx setup needs adjusting |

**Action for you:** reply with corrections. Anything missing assume "yes default."

---

## 3. Phase 1 — Frontend changes (Vercel-ready)

Code changes (~30 min):

### 3.1 Password gate via Next.js middleware

New file `frontend/src/middleware.ts`:
- Intercepts every route
- Checks for a `resell-auth` cookie
- If missing, redirects to a `/login` page
- `/login` accepts the password (compared against `RESELL_ACCESS_PASSWORD` env var
  on Vercel), sets the cookie on success, redirects to `/`

New file `frontend/src/app/login/page.tsx`:
- Minimal password input form, server action checks and sets cookie
- Cookie set with `httpOnly: true, sameSite: "lax", maxAge: 30 days`

**Why this approach:** Vercel's built-in password protection requires Pro plan ($20/mo).
Middleware-based gate is free, simple, sufficient for a single shared password.

**Limitations:**
- One password for everyone. Anyone who clears it has full access (including publish).
- Password rotation requires updating the env var + redeploying.
- The password is shared in cleartext over your team channel. Treat accordingly.

### 3.2 Update stale README

`frontend/README.md` currently claims "currently runs with mock API responses,
uncomment fetch calls in src/api/*". This is no longer true. Replace with
real instructions.

### 3.3 Drop `frontend/src/pages/`

Empty (just `.gitkeep`). Single-router (App Router) is cleaner.

### 3.4 Vercel config

Add `frontend/vercel.json`:
```json
{
  "buildCommand": "npm run build",
  "framework": "nextjs",
  "regions": ["fra1"]
}
```
(`fra1` = Frankfurt, lowest latency to EU users + close to AWS eu-central-1)

### 3.5 Build verification

Already verified: `npm run build` passes cleanly. Output: 9.76 kB page, 97.1 kB First Load JS.

### 3.6 Vercel deploy steps (you run interactively)

```bash
cd frontend
npx vercel login                # interactive — opens browser
npx vercel link                 # creates .vercel/project.json
npx vercel env add RESELL_ACCESS_PASSWORD production
                                # paste password when prompted
npx vercel env add NEXT_PUBLIC_API_URL production
                                # placeholder for now: https://example.com
npx vercel --prod               # deploys
```

After this we know the public URL. Save it — needed for backend CORS in Phase 2.

---

## 4. Phase 2 — Backend prep (code changes)

### 4.1 Trim training-only deps from `requirements.txt`

**[CORRECTED 2026-05-10]** — initial plan claimed we could skip torch
because the VLM runs on RunPod. Wrong: `backend/bootstrap.py` loads
DINOv2 + 3 head MLPs locally at startup. So torch + transformers stay,
but training-only deps go.

`requirements-prod.txt` (now landed):

```
fastapi, uvicorn, python-multipart       # web
pillow                                    # image
pydantic                                  # schemas
aiosqlite                                 # db
httpx, openai                             # HTTP clients
python-dotenv, tenacity                   # utils
torch, transformers, numpy, huggingface_hub  # DINOv2 + heads
```

Dropped (training-only): `peft`, `bitsandbytes`, `accelerate`, `trl`,
`datasets`, `pandas`, `pyarrow`, `scikit-learn`, `evaluate`,
`bert-score`, `nltk`, `wandb`.

Estimated image size: ~1.5 GB (down from ~5 GB if we'd kept everything).
KA JWT decode confirmed hand-rolled in `_oauth.py` — no `pyjwt` needed.

### 4.2 Inline session credentials (LANDED)

`backend/main.py` now has `_materialize_session()` at module load that
checks for `VINTED_SESSION_JSON` / `KA_SESSION_JSON` env vars. If set
(and no `_PATH` is explicitly provided), the JSON blob is written to
`data/{vinted,ka}_session.json` and the `_PATH` env var is set to that
location. The existing file-based loaders work unchanged.

**Refresh-rotation semantics:** the materialized file is only written
if it doesn't already exist. After Vinted rotates the DataDome cookie,
the on-disk session is the freshest version; it's preserved across
container restarts (data dir is bind-mounted to host EBS). To force
re-seeding from env, manually `rm /opt/resell/data/vinted_session.json`
on the host.

### 4.3 Lock down CORS (LANDED)

`backend/main.py` now reads `CORS_ORIGINS` env var (comma-separated).
Default `*` preserves local dev behavior; production sets it to the
Vercel deploy URL.

### 4.4 Production Dockerfile (LANDED)

`Dockerfile` at repo root (separate from `runpod/Dockerfile` which is
GPU-flavored). Uses `python:3.11-slim` base, installs `requirements-prod.txt`,
copies `backend/`, `shared/`, `models/` (with `models/checkpoints/`
excluded via `.dockerignore`). Sets `HF_HOME=/app/data/.huggingface` so
DINOv2 weights cache to the persistent volume. Exposes 8000. Includes a
`HEALTHCHECK` that hits `/health`.

`.dockerignore` rewritten to be a single config covering both this
Dockerfile and `runpod/Dockerfile`.

### 4.5 Healthcheck endpoint (LANDED)

`backend/main.py` now exposes:
- `GET /health` — lightweight, returns `{"status": "ok"}` without
  touching `app.state`. Used by nginx upstream check + Docker HEALTHCHECK.
  Works even before model loading completes.
- `GET /healthz` — existing detailed probe that reports VLM backend +
  loaded models + device.

---

## 5. Phase 3 — AWS EC2 setup (you run, I provide commands)

**Confirmed:** Ubuntu 26.04 LTS, t2.small (2 GB RAM), public IPv4 `13.49.21.29`,
domain `resell-copilot.duckdns.org` already pointing at it.

### 5.1 SSH in + base setup

```bash
ssh -i ~/Downloads/Resell_Copilot.pem ubuntu@13.49.21.29
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose-v2 nginx certbot python3-certbot-nginx
sudo usermod -aG docker ubuntu
# log out and back in for docker group to take effect
```

### 5.2 Add 2 GB swap (insurance, not strictly required at 2 GB RAM)

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 5.3 Persistent data directory + checkpoints

```bash
sudo mkdir -p /opt/resell/data/uploads /opt/resell/checkpoints
sudo chown -R ubuntu:ubuntu /opt/resell
```

(EBS root volume is persistent across reboots — no separate volume needed at
free-tier scale. If usage grows, attach a dedicated EBS volume here later.)

### 5.4 Copy model checkpoints from your Mac

The `.pt` files are gitignored (training artifacts), so they need to be
shipped to EC2 once. From your Mac:

```bash
scp -i ~/Downloads/Resell_Copilot.pem \
  models/checkpoints/flaw_head_vinted.pt \
  models/checkpoints/price_head.pt \
  models/checkpoints/sell_head.pt \
  ubuntu@13.49.21.29:/opt/resell/checkpoints/
```

(Total ~7 MB — quick.)

### 5.5 Clone repo + secrets file

```bash
cd /opt/resell
git clone https://github.com/mchlkan/Advanced_ML.git app
cd app
git checkout main

# Create env file (NEVER commit this)
cat > .env.prod <<EOF
VLM_BACKEND=runpod_http
RUNPOD_ENDPOINT_ID=<your endpoint id>
RUNPOD_API_KEY=<your key>
GROQ_API_KEY=<your key>
VINTED_SESSION_JSON=<paste full JSON content of session file>
VINTED_DATADOME_SEED=<value>
VINTED_ANON_ID=<value>
VINTED_DEVICE_UUID=<value>
VINTED_DEVICE_TOKEN=<value>
KA_SESSION_JSON=<paste full JSON content of session file>
CORS_ORIGINS=https://<vercel-url>
EOF
chmod 600 .env.prod
```

### 5.6 Build + run

```bash
docker build -t resell-backend .
docker run -d \
  --name resell-backend \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  --env-file .env.prod \
  -v /opt/resell/data:/app/data \
  -v /opt/resell/checkpoints:/app/models/checkpoints:ro \
  resell-backend
```

`-p 127.0.0.1:8000:8000` binds only to localhost — nginx will reverse-proxy to
this. Backend is NOT exposed to the public internet directly. The checkpoints
volume is mounted read-only since the heads aren't retrained at inference time.

### 5.7 nginx reverse proxy

```bash
sudo tee /etc/nginx/sites-available/resell <<'EOF'
server {
    server_name resell-copilot.duckdns.org;

    client_max_body_size 20M;  # for image uploads

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Long timeouts for VLM cold-start
        proxy_read_timeout 180s;
        proxy_connect_timeout 60s;
    }

    listen 80;
}
EOF
sudo ln -s /etc/nginx/sites-available/resell /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 5.8 SSL via Let's Encrypt

```bash
sudo certbot --nginx -d resell-copilot.duckdns.org
# follow prompts, accept TOS, email for expiry warnings
```

certbot rewrites the nginx config to add HTTPS + auto-renewal cron.

---

## 6. Phase 4 — Wire frontend to backend

```bash
# locally on your Mac
cd frontend
npx vercel env rm NEXT_PUBLIC_API_URL production
npx vercel env add NEXT_PUBLIC_API_URL production
# enter: https://resell-copilot.duckdns.org
npx vercel --prod
```

Frontend redeploys, now talking to the AWS backend.

---

## 7. Phase 5 — Smoke tests

Once deployed, verify in this order:

1. `curl https://resell-copilot.duckdns.org/health` → `{"status": "ok"}`
2. `curl https://resell-copilot.duckdns.org/healthz` → reports VLM backend + loaded models
3. Open Vercel URL in incognito → password page renders
4. Enter `Advanced_ML` → upload screen renders
5. Upload a photo → identification + price band appears (catches: backend up,
   RunPod reachable, Groq reachable, DINOv2 + heads loaded)
6. Click "draft" → opens new tab to draft URL (catches: Vinted/KA session valid
   from a datacenter IP — the riskiest unknown)
7. View inventory → renders previously uploaded items
8. Hit `/inventory/sync` button → wardrobe data refreshes from Vinted

If step 6 fails (DataDome challenge), fallback options:
- Refresh DataDome cookie locally + push fresh `VINTED_SESSION_JSON` to EC2 + restart container
- Add cookie-rotation logic to handle the challenge
- Limit publish to "draft only, manual paste" for the deployed version

---

## 8. Risks + mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Vinted DataDome blocks the AWS IP | Medium-high | Fall back to draft-only mode. Or warm DataDome from EC2 IP before demo |
| t2.small OOMs under concurrent uploads | Low at demo scale (DINOv2 ~350 MB on a 2 GB box leaves ample headroom) | Swap configured (§5.2). Upgrade to t3.medium if it happens |
| Backend SQLite gets corrupted on container restart mid-write | Very low | aiosqlite uses WAL mode. EBS persistent. Acceptable for demo scale |
| Vinted account flagged for unusual login pattern (Mac IP + EC2 IP) | Medium | Use only EC2 IP after deploy; stop using Vinted from Mac for the demo period |
| RunPod cold-start times out the 180s nginx limit | Low (warm pods finish in 12s) | Pre-warm pod before demo. Or extend nginx timeout to 300s |
| Cert renewal fails | Low | Certbot's auto-renewal cron handles it. Monitor first renewal at ~60 days |
| Password leaks via team chat | Medium (human factor) | Rotate password if URL spreads beyond intended audience |
| Costs exceed free tier (egress > 100GB/mo) | Very low for demo | Free tier covers more than enough for course demo |
| DINOv2 weights download fails on first start (HF Hub outage) | Very low | Pre-pull on EC2 once via `python -c "from transformers import AutoModel; AutoModel.from_pretrained('facebook/dinov2-base')"` after first container build |

---

## 9. Rollback plan

If a deploy goes bad:

- **Frontend:** Vercel keeps every deploy. `npx vercel rollback` swaps the alias
  back to the previous build instantly
- **Backend:** keep the previous Docker image. `docker stop resell-backend &&
  docker run ... resell-backend:previous-tag` restores in <30s
- **DB schema:** all migrations are idempotent ALTER TABLE. Rollback by reverting
  the Docker image, DB shape stays compatible

---

## 10. Out of scope for this deploy

- Multi-user accounts (everyone shares the password and the Vinted/KA account)
- Rate limiting (nginx default is fine; add if needed)
- Monitoring / alerting (Vercel Analytics is free for the FE; backend has no
  observability beyond systemd logs)
- Backups of the SQLite (volume snapshots can be added later)
- A staging environment (only prod)
- CDN for uploaded images (served directly from EC2 via the backend)

---

## 11. Time estimate

| Phase | Time | Status |
|---|---|---|
| 1. Frontend prep | 30 min | ✅ **DONE** — middleware, login page, README, vercel.json all on `feature/deploy-prep` |
| 2. Backend code changes + Dockerfile | 1 hr | ✅ **DONE** — `requirements-prod.txt`, `Dockerfile`, `.dockerignore`, CORS env var, `/health`, session JSON materialization on `feature/deploy-prep` |
| 1.6. Vercel deploy | 30 min | ⏳ User runs `vercel login` + `vercel --prod` interactively |
| 3. AWS EC2 setup | 1-2 hrs | ⏳ User runs SSH commands from §5; I guide |
| 4. Wire FE → BE | 10 min | ⏳ Set NEXT_PUBLIC_API_URL on Vercel, redeploy |
| 5. Smoke tests + iteration | 30 min - 2 hrs | ⏳ Depends on DataDome behaviour |
| **Remaining total** | **2-4 hrs realistic** | |

---

## 12. Inputs (all confirmed 2026-05-10)

1. **AWS:** t2.small Ubuntu 26.04 at `13.49.21.29` — ✅ confirmed
2. **Domain:** `resell-copilot.duckdns.org` (DuckDNS A-record points at IP) — ✅ confirmed
3. **Password:** `Advanced_ML` — ✅ confirmed (typo corrected)
4. **Phase ordering:** Phase 2 + 1 done locally, Phase 1.6 + 3 + 4 + 5 next
5. **Risks:** all accepted as-is; DataDome behaviour discovered at smoke-test time

---

## 13. Open items still requiring you

Before we can run Phase 1.6 + 3:

1. **AWS Security Group:** confirm in EC2 console that ports **80** + **443**
   are open to `0.0.0.0/0` (port 22 already verified). Without these, nginx
   installs but is unreachable from outside.
2. **Secret values for `.env.prod`** (Phase 5.5) — I'll need from you when
   we get to that step:
   - `RUNPOD_ENDPOINT_ID`, `RUNPOD_API_KEY`
   - `GROQ_API_KEY`
   - Full content of `~/.../vinted_session.json` (paste as `VINTED_SESSION_JSON`)
   - `VINTED_DATADOME_SEED` / `VINTED_ANON_ID` / `VINTED_DEVICE_UUID` / `VINTED_DEVICE_TOKEN`
   - Full content of KA session file (paste as `KA_SESSION_JSON`)
3. **Vercel account** access — you'll run `npx vercel login` interactively
   when we kick off Phase 1.6.
