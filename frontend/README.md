# Resell Copilot — Frontend

Next.js 14 (App Router) · TypeScript · Tailwind CSS 4

## Requirements

- Node.js ≥ 20

## Run locally

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser, or on your phone by navigating to `http://<your-laptop-ip>:3000` on the same Wi-Fi network.

## Backend

The frontend currently runs with **mock API responses** — no backend needed to try the UI. When the backend is ready, set the API base URL:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Then uncomment the real `fetch` calls in `src/api/upload.ts`, `src/api/verify.ts`, and `src/api/publish.ts` (each has a `// TODO: backend` block).

## Other commands

```bash
npm run type-check   # TypeScript check, no emit
npm run lint         # ESLint
npm run build        # Production build
```
