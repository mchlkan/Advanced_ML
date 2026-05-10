# Inventory feature — session log (2026-05-08 → 2026-05-10)

This document captures everything we built across one collaboration session
on the inventory feature, plus a chronological log of how we worked together.

---

## Part 1 — What was built

A backend inventory layer that lets the frontend show every listing, its AI
prediction, where it's published, and how it's actually doing live on Vinted —
all in one call.

### New endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/inventory/sync` | Pull the user's Vinted wardrobe and append a snapshot row per item. Used both explicitly (pull-to-refresh) and inline by GET /inventory when stale. |
| `GET` | `/inventory` | Per-listing summary: latest prediction, per-platform publish state, plus the live wardrobe snapshot joined in for posted Vinted items. Lazy auto-refresh when stale > 5 min and Vinted is configured (best-effort; failures fall through to cached data). |
| `GET` | `/inventory/summary` | Header-strip aggregates: status counts, Σ q50 of active items, total live views/favourites. |
| `GET` | `/listings/{listing_id}/image` | Serves the uploaded JPEG. Path-traversal guard via `is_relative_to(UPLOADS_DIR)`. |

### Database — append-only snapshot model

Two new tables in `backend/db.py`:

- `wardrobe_snapshots` — one row per (platform_listing_id, sync). Captures
  title, price_eur, currency, views, favourites, url, primary_photo_url, plus
  raw_json for forward compatibility. Append-only: doubles as ML training
  signal ("which predictions converted to attention").
- `wardrobe_syncs` — one row per sync attempt. Status `ok` / `error` with
  item_count and error message. Used as the freshness stamp for lazy refresh.

A 3-CTE query (`_INVENTORY_QUERY`) folds listings ↔ latest prediction ↔
latest publish per platform ↔ latest wardrobe snapshot in a single round trip.

Helpers added: `insert_wardrobe_snapshots`, `record_wardrobe_sync`,
`get_last_wardrobe_sync`, `get_inventory_rows`.

### Vinted client additions

In `backend/integrations/vinted.py`:

- `VintedClient.get_wardrobe()` — paginates `GET /api/v2/wardrobe/{user_id}/items`. Confirmed via Lorry171717/vinted-automation.
- `normalize_wardrobe_item()` — pure mapper from raw API shape to our DB columns.
- `fetch_wardrobe()` — async wrapper that loads session, calls the client,
  saves the rotated DataDome cookie, returns raw items.
- `is_session_ready()` — public yes/no readiness check used by both
  `/inventory/sync` and inline by `/inventory`. Replaces a private-name leak
  that initially mirrored `routes/onboarding._vinted_status`.

### Pydantic schemas

Added to `backend/schemas.py`:

- `PredictionSummary` — english_fields plus `vinted: PriceBand | None` and
  `kleinanzeigen: PriceBand | None`. Optional rather than zero-band sentinels.
- `VintedLiveSnapshot` — fetched_at, title, price_eur, views, favourites,
  primary_photo_url, `is_sold_or_removed`, **`pricing_status`** (enum), and
  signed **`delta_vs_q50_pct`**.
- `PlatformPublishState` — publish_id, status, platform_listing_id/url,
  error, optional `live: VintedLiveSnapshot`.
- `InventoryItem` — listing_id, created_at, thumbnail_url, prediction,
  vinted, kleinanzeigen.
- `InventoryResponse`, `SyncResponse`, `InventoryStatusCounts`,
  `InventorySummary`.
- `PricingStatus = Literal["underpriced", "ok", "overpriced", "unknown"]`
  — always present in `VintedLiveSnapshot` so the FE never needs a null branch.
- `InventoryBucket = Literal["posted", "sold_or_removed", "pending", "failed", "unpublished"]` — return type of `_bucket_for`; mutually exclusive
  buckets, priority `posted > sold_or_removed > pending > failed > unpublished`.

### Pricing-drift overlay

`_classify_pricing(price, band)` compares live `wardrobe.price_eur` to the
predicted band: underpriced if below q10, overpriced if above q90, ok in
between, unknown otherwise. Plus a signed `delta_vs_q50_pct` so the UI can
render `−18%` without recomputing thresholds. Surfaces directly inside
`VintedLiveSnapshot` — one badge per inventory card.

### Sold/removed detection

A Vinted publish with `status='posted'` whose `platform_listing_id` is missing
from the most recent `wardrobe_syncs` row (and the sync ran after the publish
was last updated) is marked `is_sold_or_removed=true`. We don't try to
distinguish sold vs deleted — both are "no longer listed."

### Tests — `backend/tests/test_inventory.py`

22 tests covering:
- shaping (empty DB, prediction-only, publish state, wardrobe join, sold detection)
- lazy refresh skipped when not configured
- sync 409 / 502 / writes snapshots / writes error row on transport failure
- inline lazy sync inside GET /inventory
- image serve + 404
- pricing classification (underpriced / ok / overpriced / unknown)
- summary aggregation (empty / unpublished / value+engagement / sold excluded
  from value / posted-beats-failed priority)

All 116 backend tests pass.

### Adjacent fixes that fell out of the work

- **conftest .env leak** — `monkeypatch.delenv("VINTED_SESSION_PATH")` was
  silently undone by `load_dotenv` running inside `from backend.main import
  app` later in the fixture. Fixed by eagerly importing `backend.main` at
  conftest module load. This unblocked pre-existing publish tests
  (`test_runner_marks_unconfigured_failed` etc.) that had been silently
  contacting real Vinted.
- **UPLOADS_DIR import-time capture** — `from backend.routes.upload import
  UPLOADS_DIR` captures the value at import, so conftest's
  `monkeypatch.setattr` couldn't redirect the image route to the test
  uploads dir. Fixed by importing the module and reading the attribute at
  call time.

---

## Part 2 — Files touched

| File | Change |
| --- | --- |
| `backend/db.py` | Two new tables (`wardrobe_snapshots`, `wardrobe_syncs`), 4 helpers, `_INVENTORY_QUERY` CTE. |
| `backend/integrations/vinted.py` | `VintedClient.get_wardrobe`, `normalize_wardrobe_item`, async `fetch_wardrobe`, public `is_session_ready`. |
| `backend/schemas.py` | `PredictionSummary`, `VintedLiveSnapshot`, `PlatformPublishState`, `InventoryItem`, `InventoryResponse`, `SyncResponse`, `InventoryStatusCounts`, `InventorySummary`, `PricingStatus`, `InventoryBucket`. |
| `backend/routes/inventory.py` | **NEW** — sync, get, summary, image endpoints + folding/summary/pricing helpers. |
| `backend/main.py` | Router registration. |
| `backend/tests/test_inventory.py` | **NEW** — 22 tests. |
| `backend/tests/conftest.py` | Eager `import backend.main` so `load_dotenv` runs once before any `monkeypatch.delenv`. |

---

## Part 3 — Interaction log

How we worked, in order. Each turn is labelled with the user's intent and the
mode of collaboration.

### Turn 1 — open question / brainstorm
**User:** "Regarding the backend what could we integrate more I think for an
inventory in the frontend what would we need to integrate there"

**Mode:** exploratory question. I gave a 2–3 sentence shape of the gap
(read-side endpoints missing, image serving needed) and surfaced two design
choices the user should decide before any code: a `state` column for
sold/archived, and the inventory rollup shape (one row per listing vs one
per (listing, platform)).

### Turn 2 — challenge / counter-proposal
**User:** Pointed at `https://github.com/Lorry171717/vinted-automation` —
"could we just build an inventory from there?"

**Mode:** brainstorm with pushback. Inspected the repo, confirmed the
wardrobe endpoint exists. Pushed back on "just use it": KA blind spot, loses
our predictions, doesn't cover failed publishes. Proposed the **hybrid**
— keep our DB as the spine, sync wardrobe state as live overlay, capture
views/favourites as ML signal. Asked: want me to sketch the sync endpoint?

### Turn 3 — `/plan`
**User:** Invoked `/plan` for "a sync endpoint + joined inventory response."

**Mode:** structured plan workflow.
1. Read `db.py`, `integrations/vinted.py`, `routes/onboarding.py`,
   `tests/conftest.py`, `tests/test_publish.py`. Launched one `Explore`
   agent to map: Vinted client constructor + auth, wardrobe-fetch absence,
   onboarding readiness pattern, publish runner state machine, brief §5.5
   (inventory not out of scope).
2. Read the publish runner directly to confirm `platform_listing_id` is
   set as `str(item_id)` post-publish (the join key against `wardrobe_snapshots`).
3. **AskUserQuestion** with three real design choices, all answered as
   recommended:
   - Sync trigger → on-demand + lazy refresh
   - Scope → only listings created via our app
   - Image endpoint → include in this PR
4. Wrote the plan to `~/.claude/plans/zesty-orbiting-hejlsberg.md`.
5. `ExitPlanMode`.

### Turn 4 — implementation
**User:** Approved the plan.

**Mode:** sequential implementation, one task at a time, tests at the end.
Hit two real bugs along the way:
- conftest `.env` leak via `monkeypatch.delenv` running before `load_dotenv`.
  Diagnosed by adding a print of `VINTED_SESSION_PATH` inside the failing
  test, confirmed the var was set, traced to the `from backend.main import
  app` line inside the fixture. Fixed at conftest module load.
- `UPLOADS_DIR` captured at import time by inventory.py, breaking the
  conftest's `monkeypatch.setattr`. Fixed by accessing the module attribute
  at call time.

Result: 12 inventory tests, 90 backend tests total, all green. Reported back
with a concise file-by-file summary.

### Turn 5 — what next
**User:** "Okay any more ideas for the inventory?"

**Mode:** exploratory ideation, filtered. Brainstormed ~10 ideas, surfaced
the top 3 ranked by bang-for-buck (pricing-drift overlay, /inventory/summary,
per-listing history endpoint). Recommended skipping bulk actions explicitly.

### Turn 6 — implementation, with constraint
**User:** "yeah go for it btu always think about making them frontend compatible"

**Mode:** implementation with an explicit constraint applied throughout.
"Frontend compatibility" was interpreted as:
- Always-present fields with sensible defaults (no null branches the FE has
  to handle for routine cases — e.g. `pricing_status` always present, never
  None).
- Named string Literals over booleans where the UI may render distinct
  labels (`pricing_status`, bucket names).
- Pre-computed signed deltas so the UI doesn't recompute math
  (`delta_vs_q50_pct`).
- Counts default to 0 not null so card headers render directly.

10 more tests added (22 total). All 116 backend tests pass.

### Turn 7 — `/simplify`
**User:** Invoked `/simplify`.

**Mode:** review + cleanup. Launched three review agents in parallel
(reuse, quality, efficiency), aggregated findings, fixed:
- Extracted `is_session_ready()` to remove duplication + private-name leak.
- `_do_vinted_sync()` returns the fresh sync row (one fewer DB roundtrip per call).
- Moved `from pathlib import Path` to module top.
- `InventoryBucket` Literal for bucket names (was raw strings).
- `PredictionSummary.vinted` and `.kleinanzeigen` made Optional; dropped the
  `PriceBand(0, 0, 0)` placeholder that hid type-safety holes.
- `english_fields: dict` → `dict[str, Any]`.

Skipped (with reason): CTE indexing (fine at single-user scale), tuple →
NamedTuple for `_classify_pricing` (one caller, ceremony), the sold-detection
comment (it explains a non-obvious WHY).

### Turn 8 — this document

---

## Part 4 — Working-style observations

A few patterns that worked well across the session:

- **Plan before code.** Two of the seven turns were planning/brainstorm
  with explicit design choices surfaced via `AskUserQuestion`. None of the
  three picks turned out wrong on implementation.
- **Push back before lifting code from elsewhere.** When the Lorry repo came
  up, the right answer wasn't "sure" or "no" — it was "yes for the data,
  no for the architecture." That conversation shaped the hybrid approach,
  which is what actually shipped.
- **Diagnose root causes, don't paper over.** The conftest `.env` leak
  affected several pre-existing tests too. Fixing it at the conftest level
  was the right call rather than making the new tests robust to the leak
  in isolation.
- **Apply the constraint throughout, not just at the boundary.** "Frontend
  compatibility" wasn't a single check at the end; it shaped enum names,
  default values, pre-computed deltas, and which fields were Optional.
- **Run the full suite after every refactor.** `/simplify` only landed because
  every change was test-gated.

---

## Part 5 — How the work landed in git

The chat-side work is one stream of a multi-stream weekend. The relevant
commit chronology:

| Commit | Date | Author | Role of this session |
| --- | --- | --- | --- |
| `13f579a` | 2026-05-08 | Leon | **Adjacent prep.** Enabled `CORSMiddleware` for localhost:3000/5173 and declared every existing route's 4xx/5xx in OpenAPI so `openapi-typescript` could generate typed FE clients. Not produced in this chat, but it's the reason the inventory work could go straight from "endpoint defined" to "frontend consuming it" without retrofit. |
| `7eee614` | 2026-05-08 | Leon | **Main inventory commit.** Everything we built in turns 3–7: `wardrobe_snapshots` + `wardrobe_syncs` tables, `VintedClient.get_wardrobe`, `is_session_ready()`, `routes/inventory.py` (sync + get + summary + image), pricing-drift overlay on `VintedLiveSnapshot`, 22 tests. Also bundled the new `docs/api.md` frontend reference so the FE side could integrate without reverse-engineering Pydantic. |
| `f99bd58` | 2026-05-08 | Lenn (collab) | **Parallel-track frontend.** A first frontend inventory pass that didn't yet know about our rich `/inventory`. Created `backend/routes/listings.py` (a slimmer duplicate exposing just thumbnails) and an `InventoryScreen.tsx` driven by it. Useful because it forced an explicit reconciliation the next day. |
| `ff659bb` | 2026-05-09 | Lenn (collab, w/ Claude Sonnet 4.6) | **Reconciliation.** Deleted `routes/listings.py`, the simple `ListingsResponse` schema, `get_all_listings()`, and the `/uploads` static mount. Rewired `InventoryScreen` to consume our `InventoryItem` / `PlatformPublishState` / `PredictionSummary` shapes. Image serving consolidated onto our `GET /listings/{id}/image` (with the path-traversal guard). The `POST /listings/{id}/sold` route was lifted into `inventory.py` at the same URL. |

The `routes/inventory.py` you see today is post-`ff659bb`: it carries the
`mark_sold` route that wasn't in the original Phase-6 plan.

### What the commit messages reveal

A few things worth pulling out of the commit history that aren't obvious
from the chat alone:

- **`docs/api.md` was a deliverable, not a side product.** The 408-line
  frontend reference shipped in the same commit as the inventory routes.
  It's the contract the FE was meant to read — quick endpoint map, request
  /response shapes, error tables. Future sessions touching API surface
  should update it in the same PR.
- **The `is_session_ready()` extraction was load-bearing for both onboarding
  and inventory.** The `/simplify` pass collapsed two near-identical
  readiness checks; the commit message frames it as "single source of
  truth for 'Vinted usable right now'."
- **The Optional bands change is an FE-facing decision, not a refactor.**
  The commit explains: "FE renders 'no estimate' rather than €0." Worth
  remembering — making bands `PriceBand | None` was about being honest
  with the UI, not about purity.
- **22 tests, but seeded directly via `sqlite3`, not via the runner.** The
  commit message calls this out explicitly: runner-level testing stays in
  `test_publish.py`. Direct DB seeds are the right path for shaping/join
  tests because the runner needs real platform credentials.
- **Two-author cross-checking.** The reconciliation commit `ff659bb` is
  Co-Authored with Claude Sonnet 4.6. That's a useful pattern: one chat
  builds the backend contract, a separate session does the FE reconcile —
  any mismatch is forced into a real review rather than papered over by a
  single context.

### Adjacent commits, same weekend

Not part of the chat but happening in parallel and worth knowing about
if you're reading the history:

- **Phase 6c Kleinanzeigen direct publishing** (`c709dfd`, `c63a088`,
  `9add251`). Why our `schemas.py` ended up with `KleinanzeigenOnboardingRequest`
  and `conftest` started deleting `KA_SESSION_PATH`: KA mobile-API publishing
  was being built in the same window. The KA work is independent of inventory
  — KA simply has no equivalent of the Vinted wardrobe endpoint, so KA
  inventory is "what's in our `publishes` table" and nothing more.
- **Model/research stream** (`f2e69ab` Model #6, `b984cd0` multi-image
  fine-tuning plan, `22d01c7` Model #1 multi-image FT shipped). Independent
  of inventory but the same person is doing both, so commits interleave.
