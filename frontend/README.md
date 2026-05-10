# Resell Copilot — Frontend

Next.js 14 (App Router) · TypeScript · Tailwind CSS 4

## Requirements

- Node.js ≥ 20

## Run locally

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 \
  RESELL_ACCESS_PASSWORD=local \
  npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The password gate
will prompt for the value of `RESELL_ACCESS_PASSWORD` — use any value
for local dev.

## Backend

The frontend talks to a FastAPI backend over HTTP. Configure via
`NEXT_PUBLIC_API_URL`:

- Local: `http://localhost:8000` (run `uvicorn backend.main:app --reload`
  from the repo root)
- Production: set in Vercel project settings to the deployed backend URL

## Auth

A single shared password gates the entire app via Next.js middleware
(`src/middleware.ts`). Login state is stored in an httpOnly cookie that
expires after 30 days. Configure the password via `RESELL_ACCESS_PASSWORD`
on the server side (Vercel env var in production).

## Other commands

```bash
npm run type-check   # TypeScript check, no emit
npm run lint         # ESLint
npm run build        # Production build
```

## Deployment

See `docs/deploy_plan.md` in the repo root for the full Vercel + AWS EC2
deploy guide.
