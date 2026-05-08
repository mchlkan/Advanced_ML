# Resell Copilot — Claude Design Workflow

This doc is the brief for designing the Resell Copilot frontend using Claude Design (claude.ai/design). Read it before opening the design tool, and keep it open as a reference while iterating.

---

## What we're building

A **photo-first selling assistant** for second-hand clothing. The core promise is simple: drag a photo in, get a structured listing out — with a cross-platform price recommendation between Vinted and Kleinanzeigen, and a one-tap "publish" that pre-fills the platform's own listing form.

This is a **course demo**, not a production app. The audience is a professor + mock investors. The bar is "clean and fast on hero items," not pixel-perfect. We record a backup screencast in case live demo fails.

---

## Stack constraints

- **Framework:** Next.js 14 (App Router), React 18, TypeScript — already set up in `frontend/`
- **Target environment:** local dev server, accessed on a **mobile phone as a PWA / web app** (Chrome or Safari on iOS/Android)
- **No auth, no multi-user UI** — single-session, no login screen, no nav beyond what's described below
- **No component library locked yet** — suggest one in the design if it makes sense (Tailwind + shadcn/ui is a natural fit)

---

## The three screens to design

### Screen 1 — Upload / Landing

The app opens here. This is the only entry point.

**What it needs:**
- Full-viewport tap zone to trigger the camera or photo library
- Primary CTA: **"Take a photo"** (opens device camera via `capture="environment"`)
- Secondary CTA: **"Choose from library"** (standard file picker)
- App name + one-line tagline ("Photo → listing. In seconds.")
- No drag-and-drop (irrelevant on mobile) — the whole zone should be tappable
- Loading/spinner state that appears immediately after the user picks a photo (backend call is ~3-10s)

**Tone:** purposeful, a little premium. This is a tool for someone who resells clothes regularly. Not a toy.

**Key design decision:** the upload zone should feel like a camera viewfinder — dominant, full-screen, inviting you to shoot. Don't drown it in copy.

---

### Screen 2 — Results

Appears after the backend responds. Replaces the upload screen (or transitions into it).

Backend response shape (from `backend/schemas.py: UploadResponse`):
```
listing_id
visual_wear_probability      // 0.0–1.0, flaw signal from DINOv2
vinted:
  price: { q10, q50, q90 }  // price band in EUR
  sell_probability           // 0.0–1.0
  identification:
    brand, category, condition, color, size, title, description, price_eur
kleinanzeigen:
  price: { q10, q50, q90 }
  identification: (same fields)
  qualitative_note           // no sell probability for KA
latency_ms
vlm_backend
```

**Layout (top to bottom):**

1. **Photo preview** — the uploaded image, prominent at top or left.

2. **Identification block** — the VLM's read on the item:
   - Brand, category, condition, color, size
   - Each field shown as a read-only chip/tag with a small "edit" affordance
   - Visual wear indicator — if `visual_wear_probability > 0.4`, show a subtle "visible wear detected" badge

3. **"Edit details" expandable section** — clicking opens an inline form pre-filled with identification fields (brand, category, condition, color, size). On submit, calls `POST /verify` and updates price/sell numbers. This is optional; most users skip it.

4. **Cross-platform recommendation block** — the hero of the results page:
   - Two platform cards **stacked vertically** (single-column on mobile): **Vinted** on top, **Kleinanzeigen** below
   - Each card shows:
     - Platform logo/wordmark
     - Suggested price: `€{q50}` prominent, `€{q10}–€{q90}` as a small range below
     - Sell probability (Vinted only) — shown as a progress bar or percentage chip: "~65% chance to sell within 30 days"
     - Kleinanzeigen card shows the `qualitative_note` instead of a sell probability
   - **Recommendation callout** — a sentence below the cards: e.g., "Kleinanzeigen is faster; Vinted gets €8 more." Derived from comparing the two.
   - The recommended platform card should be visually highlighted (subtle border/bg difference, not aggressive)

5. **Generated listing block** — the title + description the VLM produced, shown as an editable textarea. Pre-filled from the recommended platform's `identification.title` + `identification.description`. User can edit freely before publishing.

6. **"Publish on [Platform]" CTA** — a primary button. Calls `POST /publish`, then opens the returned `prefill_url` in a new tab. The button label updates based on which platform card is selected/recommended. Below it, a smaller "Publish on [other platform]" secondary link.

---

### Screen 3 — Post-publish confirmation

Minimal. Shown inline (no new page needed) after the `POST /publish` call resolves and the tab opens.

- "Listing opened on [Platform]. Complete it there."
- Small "Start a new listing" link that resets to Screen 1
- No confetti, no celebration — keep it professional

---

## Visual direction

**Aesthetic:** Clean, editorial, task-focused. Reference points:
- Vinted's own UI (functional, card-heavy, not flashy)
- Linear / Vercel (monochrome base, sharp typography, no visual noise)

**Color palette:**
- Base: white or very light grey background
- Accent: one strong color for CTAs and highlights. Suggested: a warm green (`#22c55e` family) — the "money/sell" connotation fits
- Platform-specific: Vinted is teal/green, Kleinanzeigen is orange. Use their brand colors sparingly in the platform cards only

**Typography:**
- One sans-serif family throughout — Inter or Geist
- Size hierarchy: H1 for app name, H2 for section headings (Identification, Platform Recommendation), body for field values
- Tight line-height, generous white space between sections

**Spacing:** generous padding. Each section on the results page should breathe.

**No illustrations, no icons beyond what's strictly needed** (platform logos, the edit pencil, camera icon on the upload zone, native camera capture button).

**Touch targets:** all interactive elements (buttons, chips, edit affordances) must be at minimum 44×44px. No hover-only interactions — everything must work on tap.

**Bottom-anchored CTAs:** the "Publish on [Platform]" primary button should be sticky at the bottom of the viewport on the results screen so it's always reachable with a thumb without scrolling to the end.

---

## Data states to design

Don't design only the happy path. These states need to work:

| State | Where | What to show |
|---|---|---|
| Uploading / processing | Screen 1 → 2 | Spinner or skeleton on the results page, "Analyzing your item..." |
| Low-confidence field | Identification block | Dimmed chip with an "uncertain" indicator (e.g., italic text or `?` suffix) |
| Visual wear detected | Identification block | `visual_wear_probability > 0.4` → "Visible wear detected" badge, affect condition chip |
| Verify re-calculating | Edit form submit | Show a mini-spinner on price/sell numbers while `/verify` resolves |
| Publish success | Screen 2 | Inline confirmation, no full-page redirect |
| Backend error | Screen 1 or 2 | Toast or inline error: "Something went wrong. Try again." |

---

## What NOT to design (out of scope for v1)

Don't add or suggest these — they are explicitly deferred:

- Login / user accounts / history
- Bundle suggestions
- Photo coach / quality scoring
- Closet scan (multi-item from one photo)
- Listing history page
- Dark mode
- Tablet/desktop breakpoints (phone is the only target for v1)

---

## Iteration order

Recommended sequence to avoid rework:

1. **Upload zone + loading state** — simple, establishes visual language
2. **Results page layout** — overall structure, sections, spacing (no real data yet, use placeholders)
3. **Platform recommendation cards** — the most data-dense component, needs the most iteration
4. **Identification block + edit form** — secondary importance but needs to look polished for demo
5. **Listing copy block + publish CTA** — mostly typography + a button, should be fast
6. **Error / uncertain states** — last, so you're not designing for edge cases before the happy path is locked

Each step: generate in Claude Design → export to Next.js component → drop into `frontend/src/components/` → wire to real API response shape from `backend/schemas.py`.

---

## Handoff notes

- Component files go in `frontend/src/components/`
- Page files go in `frontend/src/app/` (Next.js App Router)
- API calls go in `frontend/src/api/` — one file per backend endpoint (`upload.ts`, `verify.ts`, `publish.ts`)
- Keep components dumb (props in, JSX out) — no API calls inside components
- The `UploadResponse` type from the backend maps directly to what the results page needs; define a matching TypeScript type in `frontend/src/types/api.ts`
