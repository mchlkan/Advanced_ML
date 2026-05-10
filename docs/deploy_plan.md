# Deploy Plan — Resell Copilot to Vercel + AWS EC2

**Status:** DRAFT for review. No code changes have been made — everything below is a proposal.

**Goal:** Persistent public URL (Vercel) for the frontend, gated by a shared
password. Backend hosted on user's existing free-tier AWS EC2 instance.
Real Vinted + KA publishing enabled for anyone who clears the password.

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

### 4.1 Slim down `requirements.txt`

Current `requirements.txt` (32 lines) includes training-time deps that the hosted
backend doesn't need: `torch`, `transformers`, `peft`, `bitsandbytes`, `accelerate`,
`trl`, `datasets`, `scikit-learn`, `evaluate`, `bert-score`, `nltk`, `wandb`.

Total install size with these: ~5 GB. EC2 image will be huge and slow to build.

Proposal: create `requirements-prod.txt` with only what the hosted backend imports
at runtime. VLM goes through `runpod_http.py` so no torch needed locally:

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
python-multipart>=0.0.9
pillow>=10.3.0
pydantic>=2.7.0
aiosqlite>=0.20.0
httpx>=0.27.0
python-dotenv>=1.0.0
openai>=1.55.0      # used by description.py (Groq is OpenAI-compat)
tenacity>=8.0.0
pyjwt>=2.8.0        # KA JWT decode (verify which version)
```

Estimated install size: ~150 MB. EC2 image stays small.

**Caveat:** I need to verify by tracing imports that nothing in `backend/` reaches
into the heavy deps. If `backend/description.py` imports from `transformers` somewhere
this won't work. Will check before executing this step.

### 4.2 Inline session credentials (instead of file paths)

Currently `backend/integrations/vinted.py` reads from `VINTED_SESSION_PATH` (a file).
Same for KA. This is awkward in a containerized deploy because we'd need to either:
- Mount a secret file (extra Docker complexity)
- Encode the file content as an env var (works but env-var size limits matter)

Proposal: add a fallback path. If `VINTED_SESSION_JSON` (env var) is set, use it
directly; else fall back to `VINTED_SESSION_PATH` (file). Backwards compatible —
local dev keeps working unchanged.

Same for KA.

### 4.3 Lock down CORS

Currently `backend/main.py:67` uses `allow_origins=["*"]`. With public access and
real publishing enabled, this is too open. Propose:

```python
allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
```

In production set `CORS_ORIGINS=https://resell-copilot.vercel.app` (or whatever the
Vercel URL is). Local dev unchanged (default `*`).

### 4.4 Production Dockerfile

New `Dockerfile` at repo root (separate from `runpod/Dockerfile` which is GPU-flavored):

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps for Pillow + lxml (KA mobile API uses XML)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg-dev zlib1g-dev libxml2-dev libxslt-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY backend/ ./backend/
COPY shared/ ./shared/

# Data dir is volume-mounted in production
RUN mkdir -p /app/data/uploads

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 4.5 Add a healthcheck endpoint

Backend doesn't currently expose `/health`. Need this for nginx upstream check
and for Vercel to be able to verify backend is alive.

Proposal: add `GET /health` returning `{"status": "ok", "vlm_backend": "<name>"}`.
~5 lines in `backend/main.py`.

---

## 5. Phase 3 — AWS EC2 setup (you run, I provide commands)

Assumes: Ubuntu 22.04, t3.micro, public IPv4, a domain pointing at it.

### 5.1 SSH in + base setup

```bash
ssh ubuntu@<your-ec2-ip>
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose-v2 nginx certbot python3-certbot-nginx
sudo usermod -aG docker ubuntu
# log out and back in for docker group to take effect
```

### 5.2 Add 2 GB swap (RAM safety net for t3.micro)

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 5.3 Persistent data directory

```bash
sudo mkdir -p /opt/resell/data/uploads
sudo chown -R ubuntu:ubuntu /opt/resell
```

(EBS root volume is persistent across reboots — no separate volume needed at
free-tier scale. If usage grows, attach a dedicated EBS volume here later.)

### 5.4 Clone repo + secrets file

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

### 5.5 Build + run

```bash
docker build -t resell-backend .
docker run -d \
  --name resell-backend \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  --env-file .env.prod \
  -v /opt/resell/data:/app/data \
  resell-backend
```

`-p 127.0.0.1:8000:8000` binds only to localhost — nginx will reverse-proxy to
this. Backend is NOT exposed to the public internet directly.

### 5.6 nginx reverse proxy

```bash
sudo tee /etc/nginx/sites-available/resell <<'EOF'
server {
    server_name <your-domain>;

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

### 5.7 SSL via Let's Encrypt

```bash
sudo certbot --nginx -d <your-domain>
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
# enter: https://<your-domain>
npx vercel --prod
```

Frontend redeploys, now talking to the AWS backend.

---

## 7. Phase 5 — Smoke tests

Once deployed, verify in this order:

1. `curl https://<your-domain>/health` → `{"status": "ok", ...}`
2. Open Vercel URL in incognito → password page renders
3. Enter password → upload screen renders
4. Upload a photo → identification + price band appears (catches: backend up,
   RunPod reachable, Groq reachable)
5. Click "draft" → opens new tab to draft URL (catches: Vinted/KA session valid
   from a datacenter IP — the riskiest unknown)
6. View inventory → renders previously uploaded items
7. Hit `/inventory/sync` button → wardrobe data refreshes from Vinted

If step 5 fails (DataDome challenge), fallback options:
- Refresh DataDome cookie locally + redeploy backend
- Add cookie-rotation logic to handle the challenge
- Limit publish to "draft only, manual paste" for the deployed version

---

## 8. Risks + mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Vinted DataDome blocks the AWS IP | Medium-high | Fall back to draft-only mode. Or warm DataDome from EC2 IP before demo |
| t3.micro OOMs under concurrent uploads | Low at small scale | Swap configured (5.2). Upgrade to t3.small if it happens |
| Backend SQLite gets corrupted on container restart mid-write | Very low | aiosqlite uses WAL mode. EBS persistent. Acceptable for demo scale |
| Vinted account flagged for unusual login pattern (Mac IP + EC2 IP) | Medium | Use only EC2 IP after deploy; stop using Vinted from Mac for the demo period |
| RunPod cold-start times out the 180s nginx limit | Low (warm pods finish in 12s) | Pre-warm pod before demo. Or extend nginx timeout to 300s |
| Cert renewal fails | Low | Certbot's auto-renewal cron handles it. Monitor first renewal at ~60 days |
| Password leaks via team chat | Medium (human factor) | Rotate password if URL spreads beyond intended audience |
| Costs exceed free tier (egress > 100GB/mo) | Very low for demo | Free tier covers more than enough for course demo |

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

| Phase | Time | Blocking on you |
|---|---|---|
| 1. Frontend prep + push | 30 min | Vercel login, password value |
| 2. Backend code changes + Dockerfile | 1 hr | Nothing |
| 3. AWS EC2 setup | 1-2 hrs | SSH access, domain, secrets |
| 4. Wire FE → BE | 10 min | Nothing |
| 5. Smoke tests + iteration | 30 min - 2 hrs | Depends on DataDome behaviour |
| **Total** | **3-6 hrs realistic** | |

---

## 12. What I need from you to start

Confirm or correct:

1. **AWS:** instance type, OS, public IP / Elastic IP, domain name (or "I'll register one")
2. **Password value:** the shared password for the Vercel gate (or "set in dashboard later")
3. **Phase ordering:** sequential as written, or any reordering
4. **Anything in §8 risks** you want to address before deploying (e.g. accept
   DataDome risk and proceed, vs warm cookies first)

After you confirm, I execute Phase 2 (backend code changes) on this branch — those
are local edits, reviewable in a normal commit. Phase 3 (AWS setup) and Phase 1.6
(Vercel deploy) are commands you run interactively, with me in the loop guiding
each step.
