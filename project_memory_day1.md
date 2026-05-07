# Project Memory — Resell Copilot

Working notes from the Pair A planning conversation. The full architecture lives in `resell_copilot_tech_brief_v2.md`; this file captures decisions and findings that came out of discussion and aren't in the brief.

## Decisions locked

### Architecture additions to the brief

- **Description-variant generation:** Model #1 outputs structured fields + a short list of grounded keywords/phrases. A separate (post-hoc) LLM call takes those + platform + tone and generates 2-3 description variants. The LLM never sees the photo — it can only restyle facts the VLM extracted. Anti-hallucination by construction. Frame as "grounded extraction layer (defensible) + cosmetic rendering layer (commodity)" in the pitch.

- **Cross-platform inference pattern:** Model #1 trains on combined Vinted + Kleinanzeigen data with a platform indicator in the prompt. At inference, the VLM is called **twice** in parallel — once per platform — producing platform-native categories and platform-tone descriptions. No translation table, no unified taxonomy.

- **Categories stay native.** Each platform keeps its own vocabulary (Vinted: jackets/jeans/tshirts/sneakers; KA: Damen/Herrenbekleidung, Damen/Herrenschuhe). The price head's category one-hot expands to 8-dim (4 per platform) instead of 4-dim. Category mapping is not built — at the UI level, both platforms' suggestions are shown side by side.

- **Recommendation logic (UX):** show both platforms with price + sell-likelihood. Optionally elicit user preference (speed vs price) with one button question. No ML model for this — just a rule. If Model #5 (sell-likelihood) is dropped to v2, recommendation falls back to price + qualitative platform-level note.

### Scalability — known limitation, acknowledged not solved

Two-VLM-calls scales linearly with platform count. Fine for 2 platforms (~3s latency); breaks down at 10. **For v1: do not solve.** Add to honest-limitations section (§7). v2 path is canonical-extraction + per-platform rendering adapters (one expensive call + N cheap calls). Mention in pitch when asked "how does this scale?"

### Data filters before any training

- Drop rows with `description.str.len() < 30`
- Drop rows with null `price` or `category_name`
- Drop KA rows where `price_type == 'PLEASE_CONTACT'` (placeholder prices)
- Drop conditions `in ordnung` (56 rows) and `zufriedenstellend` (54 rows) — too few
- Filter Vinted to `language == 'de'` for the spike (revisit post-spike)
- Map `Sonstige` brand and OOV brands → single UNK token

### Class imbalance handling (already in brief, confirmed)

- Flaw head: ~1:5 imbalance after filtering. Class-weighted BCE, `pos_weight ≈ 5`. Threshold tuned on val, not 0.5.
- Price head: log-transform target + quantile loss. Already handles skew.
- Sell head: balance unknown until scrape lands; use balance distribution as the signal for choosing time window (7/14/30 days).
- Brand: long tail → OOV/Sonstige → UNK.
- Stratify the locked 500-row test set on category × condition × platform.

## EDA findings (from `notebooks/01_data_exploration.ipynb`)

- Schemas nearly identical. Only KA has `price_type`. Condition strings differ in case/punctuation; collapse cleanly with `.lower().replace(",", "").strip()`.
- Zero overlap in category names between platforms — different taxonomies entirely.
- Vinted is multilingual (38% French, 21% Italian, 21% German). KA is 98% German.
- 15 brands appear in both platforms' top 30 — validates cross-platform pitch.
- KA size formats are messy (mix of letter sizes, EU numbers, shoe floats) — Model #1 won't learn a clean schema for size.
- Image storage: HuggingFace dict format `{'bytes': ..., 'path': ...}` on both. 50/50 sanity check passed.

## Working sequence (Pair A side)

Day 0 done: repo scaffold, EDA notebook, decisions above.

Day 1 (spike — see brief §2):
- Smoke-test Qwen3-VL candidates on Colab T4
- Pick 600 stratified rows (de-only Vinted + KA), 500 train / 100 test
- Zero-shot baseline → 1-epoch QLoRA on RunPod → re-evaluate
- Compute brand acc, category acc, price MAPE vs GPT-4o-mini
- Decision gate: commit / diagnose / reframe

Day 2+: scale up if spike succeeds. See brief §8.

## Sold-status data

Re-scrape in progress (~3hr at time of writing). Not blocking the spike — Models #1, #2, #4 don't need it. Model #5 is droppable if scrape data is delayed or noisy. When the scrape lands, it'll add columns to existing parquets — no path changes expected.

## Stack reminders

- Python 3.11 (maintainer uses conda; collaborators use pip+venv; `requirements.txt` is source of truth)
- Backend: FastAPI + SQLite from line one (logging every model call + user edit)
- Frontend: TypeScript, framework decided Day 2 — leaning Vite + React over Next.js (no SSR/auth needs, faster to set up)
- Repo path: `Advanced_ML/` on GitHub (mchlkan/Advanced_ML)
- Data files and checkpoints are gitignored — never commit them

## Things deliberately NOT decided yet

- Which exact Qwen3-VL variant (locked Day 1 via spike)
- Sold-status time window (locked when scrape data shape is known)
- Frontend framework (Day 2)
- Whether tag-presence is baked into Model #1 output or a separate zero-shot call (Day 1, based on what's faster)
- Whether Model #5 ships in v1 (Day 2-3, based on scrape quality)
- Whether non-German Vinted languages are included post-spike

## Things explicitly out of scope for v1

User accounts, bundle suggestions, photo coach, closet scan, era-specific pricing, per-platform tone-tuned LoRA adapters, comp retrieval, hosted backend, full publish automation. All on the v2 roadmap.