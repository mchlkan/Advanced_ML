# AI Usage Log — Resell Copilot

How AI tooling (primarily Claude Code) was used to build this 7-day course
project. Captures both the **substance** (what AI produced) and the **shape**
of the collaboration (how prompts evolved, where AI had to be redirected,
what it got wrong).

This is the top-level rollup for the course submission. The detailed
session-by-session logs already in `docs/` (linked in §6) are the primary
source — this file synthesizes them and is the entry point a grader should
read first.

---

## 1. AI tools used

| Tool | Where | What it did |
|---|---|---|
| **Claude Code** (Opus 4.7, 1M context) | Terminal, primary IDE assistant | Architecture planning, backend implementation, test writing, refactoring, doc writing, debugging on RunPod, frontend reconciliation |
| **Claude Sonnet 4.6** | Parallel chat sessions | Frontend implementation pass (commit `ff659bb`), used to deliberately split work across two contexts so backend and frontend reviewed each other |
| **GPT-4o-mini** (via OpenAI API) | Translation pipeline + price-prediction baseline | (a) Translated 8,711 listings DE/IT/FR → EN for the canonical schema (~$0.50). (b) Served as the "comparison model" the fine-tuned VLM was benchmarked against |
| **Groq Llama 3.1 8B** | Production runtime (Model #6) | Generates the listing description prose from the VLM's grounded fields. Anti-hallucination by construction: the LLM never sees the photo |
| **Qwen3-VL-4B + LoRA** | Production runtime (Model #1) | The fine-tuned vision-language model that does identification (brand / size / condition / color / category). Trained on RunPod via Claude-orchestrated session |

Total external-API spend across the whole project: **~$3.50** (translation
~$0.50 + RunPod ~$3 for the QLoRA fine-tune + Groq usage negligible at
demo volume).

---

## 2. How AI was used (high-level)

The project was built by **two humans + Claude as a third collaborator**,
not by Claude alone. Concretely, AI was used for:

- **Architecture decisions** as a structured brainstorming partner —
  produces option lists with trade-offs, then humans pick. Examples:
  canonical English schema vs bilingual (Day 2), one-call-per-platform
  vs two (Day 0), drop description from training target vs not (Day 4).
- **Backend implementation** — Claude wrote most of the FastAPI routes,
  Pydantic schemas, SQLite migrations, and tests. Humans reviewed and
  corrected.
- **Long-running ops orchestration** — RunPod SSH setup, dependency
  installs in tmux, training-loop monitoring via background `Monitor`
  on log files, auto-terminate-on-success wrapper scripts.
- **Refactoring** — `/simplify` runs that cleaned up duplication and
  type-safety gaps after each major feature landed.
- **Doc writing** — every major decision has a `.md` file under `docs/`,
  most drafted by Claude from chat context, then human-edited.
- **Debugging** — diagnosing the conftest `.env` leak, the `qwen3_vl`
  config registry mismatch, the `UPLOADS_DIR` import-time capture bug.

Where AI was **deliberately not used**: the model architecture decisions
(quantile loss, LoRA rank, base model choice) came from the project brief
not from Claude. Claude implemented and tuned within those constraints
but did not pick them.

---

## 3. Chronological log

Dates are session dates, not commit dates (commits sometimes lag by a day).

### Day 0 — pre-2026-05-07: scaffold + EDA + decision freeze

- Pair-programming session (Pair A) locked the architecture additions
  to the brief: **canonical English schema** internally + reverse lookup
  tables at publish time, **one VLM call per platform**, **categories
  stay native** (no unified taxonomy).
- EDA notebook (`notebooks/01_data_exploration.ipynb`) — Vinted is 38%
  French / 21% Italian / 21% German; KA is 98% German; 15 brands appear
  in both top-30 lists (validates cross-platform pitch).
- Doc: `docs/decisions/day1.md` (originally `project_memory_day1.md`).

### Day 1 — 2026-05-07: VLM spike + Qwen3-VL family selection

- Smoke-tested Qwen3-VL candidates on Colab T4. Locked Qwen3-VL-4B as
  the base model (4B fits on a 24 GB RunPod, 8B does not without
  aggressive quantization).
- Notebook: `notebooks/99_spike.ipynb` — zero-shot baseline + 1-epoch
  QLoRA + canonical-metric eval.
- Adapter shipped to HF Hub: `Rengo33/qwen3vl4b-resell-adapter`.

### Day 2 — 2026-05-07/08: Day-2 fine-tune session + backend bring-up

Detailed log: **`docs/session_log_day2_finetune.md`**.

Two parallel tracks:

**ML track** — built the bilingual data prep + canonical schema:
- `src/translations.py`, `src/translate_text.py`, `src/prompts.py`,
  `src/build_targets.py`, `src/build_splits.py`, `src/listing_mappings.py`
- 8,711 rows translated DE/IT/FR → EN via async GPT-4o-mini (~45 min)
- Locked stratified 90/10/test=500 splits
- QLoRA training on RunPod 4090 (3h, ~$3, auto-terminate on success)
- Result vs zero-shot 4B base: brand +14pp, color +18pp, condition +9pp,
  price MAPE −57pp. Beats GPT-4o-mini on every metric.

**Backend track** — Phase 1, 2, 3 of the FastAPI backend:
- `53ac8a4` Phase 1 — FastAPI skeleton + stub VLM + SQLite logging
- `c63eba7` Phase 2 — local_mps VLM (Qwen3-VL+LoRA on Mac MPS)
- `f185093` Phase 3 — RunPod Serverless VLM + Docker handler
- `b79bf4d` simplify pass on the RunPod VLM path

### Day 3 — 2026-05-08: backend phases 4-6 + KA mobile-API + repo cleanup + inventory

The biggest implementation day. Rough order:

- **Repo cleanup** (`1910514`) — split `/src/` into `/shared/` (runtime)
  + `/data_prep/` (offline). Detailed log: **`docs/repo_cleanup_session.md`**.
  Three parallel `Explore` agents audited cruft, design questions surfaced
  via `AskUserQuestion`, plan written, executed in 4 phases, all 90 tests
  green.
- **Phase 4 + 5** — `/verify` and `/publish` endpoints (`22966d6`, `f983a62`)
- **Phase 6a/b/c** — direct Vinted publishing (`f02db17` + brand/size
  mapping fixes), async `/publish` with background runner (`05cb53e`),
  Kleinanzeigen direct publishing via mobile API (`c709dfd`, `c63a088`,
  `9add251`). KA mobile API was reverse-engineered via mitmproxy on a
  rooted Android — Claude documented the capture in `docs/ka_endpoints.md`.
- **Inventory feature** (`7eee614`) — `wardrobe_snapshots` + `wardrobe_syncs`
  tables, lazy-refresh `/inventory` endpoint with pricing-drift overlay,
  22 new tests (116 backend tests total). Detailed log:
  **`docs/inventory_session_2026-05-10.md`** Part 1-3.
- **CORS + OpenAPI** (`13f579a`) — enabled `CORSMiddleware` and declared
  every route's 4xx/5xx so `openapi-typescript` could generate typed FE
  clients without retrofit.

### Day 4 — 2026-05-09: frontend reconcile + Model #6 + multi-image plan + KA parse fix scoping

- **Frontend reconcile** (`ff659bb`, Claude Sonnet 4.6) — first FE pass
  (`f99bd58`) had created a duplicate `routes/listings.py`. Sonnet
  rewired `InventoryScreen` to consume the rich `/inventory` shape and
  deleted the duplicate. Two-author cross-checking pattern: backend was
  built in one Claude session, frontend reconciled in a separate Claude
  session — any contract mismatch surfaced as real review, not papered
  over.
- **Model #6** (`f2e69ab`) — Groq Llama 3.1 8B description generator.
  Takes the VLM's grounded fields + platform + tone, returns prose.
  LLM never sees the photo → cannot hallucinate beyond what was extracted.
- **Multi-image fine-tuning plan** (`b984cd0`) — Claude wrote the
  `docs/multi_image_finetuning_plan.md` after a 4-question
  `AskUserQuestion` about constraints (dedicated 24GB pod, private Drive,
  reclassify with CLIP, Michael owns execution). Plan executed overnight
  by Michael; result landed Day 5 as `22d01c7`.
- **KA parse fix doc** (`b4059c1`, `7ec3887`, `af171a8`) — strategy
  documented but execution deferred. See Day 5.

### Day 5 — 2026-05-10: planning session + demo strategy + this log

Detailed log: **`docs/session_log_2026-05-10.md`** (10 phases).

- Pulled overnight commits: multi-image retrain shipped (`22d01c7`),
  brand +20pp / size +19pp on the Vinted slice. The plan Claude wrote
  in Phase 6 of the previous session was executed and landed almost
  exactly as predicted.
- Brainstormed remaining model improvements (4B vs 4B-fp16 vs 8B,
  separate description model). Honest comparison vs GPT-4o-mini reframed
  the pitch away from "cheaper than 4o-mini" toward "better on the
  metrics that matter + own the integrations."
- Decision: **skip the KA parse-rate retrain.** Recovery handles 100%
  of failures, another 4 GPU-hours not worth it for cosmetic clean-rate
  gains. Verified against current code (`models/train_vlm.py:104`,
  `scripts/build_manifest.py:197`) before deciding.
- Wrote `docs/demo_strategy.md` — pitch-line candidates, metric story,
  open team-debate questions, demo-day risk table.
- Investigated `origin/frontend_development` branch — found it stale
  (predates multi-image retrain). Identified a draft-first UX shift
  (`/draft` endpoint) that needs verifying against the new VLM output.
- **This file** written end-of-day to consolidate the AI-usage record
  for course submission.

---

## 4. Cross-cutting patterns observed across all sessions

### What consistently worked

- **Plan mode before implementation.** Used 4+ times across the project.
  Every single time the planning step caught something before code was
  written: API research that forced canonical-schema design, discovery
  that `train_vlm.py` was already shipped, constraint surfacing via
  `AskUserQuestion` before drafting the multi-image plan.
- **Background `Monitor` for long-running ops.** Translation runs,
  pip installs on RunPod, training-loop milestones — all monitored
  via `tail -f log | grep <keywords>` so the chat fired only on real
  events. Saved hours of polling.
- **Idempotent caches at every step.** Translation cache, splits parquets,
  prediction JSONs, hidden-state `.pt` files — re-running any cell is a
  no-op if the artifact exists. Made notebook appendices runnable
  without redoing 1-hour inferences.
- **Auto-terminate on the GPU pod.** `&&`-chained wrapper script:
  train → upload to HF Hub → `runpodctl remove pod`. Only terminates
  if everything succeeded; failures kept the pod alive for debugging.
- **User pushback on weak claims.** *"Did this really work how do we
  know?"* and *"But we just retrained model 1 again, wasn't this
  implemented there?"* — each pushback caught something Claude had
  glossed over. Verifying against current code rather than the planning
  doc became the rule by Day 5.
- **Two-author cross-checking via separate Claude sessions.** Backend
  built in one chat, frontend reconciled in another chat — contract
  mismatches surfaced as real review.

### What required course correction

- **Claude's over-engineering tendency.** Twice on Day 5 (slot-aware
  multi-image, CLIP classifier) Claude proposed structured solutions
  when the simpler unstructured one was right. Friend's input cut
  through both.
- **Trusting docs over code.** The KA parse fix was documented as
  planned and Claude initially assumed the multi-image retrain had
  included it. Forced to verify against actual files.
- **One-shot claims from one piece of evidence.** *"Photos are tagged"*
  ≠ *"Photos are tagged correctly."* Claude proclaimed the data was
  clean before verifying the CLIP classifications were accurate.
- **Mid-stream version drift.** Hit twice on RunPod: `transformers 5.x`
  broke torch 2.4 compat; smoke test BEFORE pip install would have
  caught it.

### Friction points worth knowing about

- **RunPod community cloud** — cheaper but two real risks: GPU reclaim
  on Stop, and bursty PyPI throughput. Plan for both. Use `uv` not
  `pip` and always run inside `tmux`.
- **HuggingFace `transformers` is moving fast.** Don't pin
  `transformers>=X.Y` without an upper bound — major versions break
  torch compat.
- **Conftest `.env` leaks.** `monkeypatch.delenv` inside a fixture is
  silently undone by `load_dotenv` running in the imported app module.
  Eager-import the app at conftest module load.

---

## 5. What AI did NOT do

Worth being explicit about for the course submission:

- Did not pick the model architecture (quantile loss, LoRA rank, base
  model). Those came from the brief.
- Did not collect or label the dataset. Scrapes were built by humans
  before this project started; CLIP zero-shot tagging on the multi-image
  scrape was Michael's work.
- Did not write the training script for the price head (Model #4) or
  the QLoRA trainer (`models/train_vlm.py`). Both written by Lenn /
  Michael.
- Did not make the demo-day strategic calls (Vinted-first, skip retrain,
  etc.) — surfaced trade-offs via option lists, humans decided.
- Did not reverse-engineer the KA mobile API (mitmproxy-on-rooted-Android
  was a human-driven session). Claude documented the captures and
  implemented the publishing client from those notes.

---

## 6. Detailed session logs (read these for specifics)

| File | What it covers |
|---|---|
| `docs/session_log_day2_finetune.md` | Day 2 — translation pipeline, RunPod SSH setup, QLoRA training, eval integration. The most operationally detailed log |
| `docs/repo_cleanup_session.md` | Day 3 — repo restructure session with parallel Explore agents and pre-commit verification |
| `docs/inventory_session_2026-05-10.md` | Day 3 — inventory feature build (substance + interaction log) |
| `docs/session_log_2026-05-10.md` | Day 5 — planning session: ML brainstorm, multi-image plan, KA parse-fix decision, demo strategy doc, frontend critique |
| `docs/decisions/day1.md` | Day 0/1 — locked architecture decisions before any code |
| `docs/decisions/day2.md` | Day 2 — combined-parquets + sold-status framing + Model #5 scope |
| `docs/project_memory_2026-05-09.md` | Day 4 — point-in-time project state snapshot |
| `docs/model_stack_evolution.md` | Authoritative state of all 6 models in the stack |
| `docs/multi_image_finetuning_plan.md` | The plan Claude wrote that Michael executed overnight (+20pp brand, +19pp size) |
| `docs/demo_strategy.md` | Pitch framing for the team meeting |

---

## 7. Prompt-by-prompt log (going forward)

Each session is a chronological list of **every user prompt** + **what
Claude decided to do** in response. Brief is fine. Quote the prompt
verbatim; summarize the response in 1-3 sentences with file paths or
artifact names.

### Template

```markdown
### Day N — YYYY-MM-DD: <one-line topic>

**AI tool:** <Claude Code Opus 4.7 / Sonnet 4.6 / etc.>
**Detailed log:** `docs/<filename>.md` (if any)
**Commits:** `<hash>` <subject>, `<hash>` <subject>

#### Prompt 1
> "<exact user prompt, verbatim>"

**Decision:** <what Claude did and why — files touched, tools used,
trade-offs surfaced, things deferred.>

**Outcome:** <what landed, or what blocked.>

#### Prompt 2
> "<...>"

**Decision:** ...
**Outcome:** ...

(repeat for every prompt in the session)

**End-of-session reflection** (optional, one paragraph): what worked,
what required correction, what to do differently next time.
```

---

### Day 5 — 2026-05-10 (continued): writing this AI usage log

**AI tool:** Claude Code Opus 4.7 (1M context)
**Detailed log:** this file is the detailed log
**Commits:** `ac7b8ff` Add inventory + repo cleanup session logs and AI usage rollup

#### Prompt 1
> "First can you write a .md file of our whole conversation so we can log it on how we used AI in the End? save this as a memory for the whole project"

**Decision:** Pushed back with two clarifying questions before writing
anything, because (a) the session was fresh — there was no prior
conversation to "log" yet, and (b) "save as memory for the project"
was ambiguous between memory storage (private to Claude across sessions)
and a committed project doc (visible to graders). Used `AskUserQuestion`
with two multi-choice questions: scope (reconstruct past / template /
both) and location (docs + memory pointer / memory only / docs only).
Recommended `docs/ + memory pointer` as the default.

**Outcome:** Two design decisions surfaced before any file was touched.

#### Prompt 2 (via AskUserQuestion)
> Scope: "Both — reconstruct + template"
> Location: "docs/ai_usage_log.md + memory pointer (Recommended)"

**Decision:** Read four existing session logs in parallel
(`session_log_2026-05-10.md`, `inventory_session_2026-05-10.md`,
`repo_cleanup_session.md`, `demo_strategy.md`), plus `git log -50`
and a `docs/` listing. Then a second parallel batch for completeness:
`session_log_day2_finetune.md`, `decisions/day1.md`, partial
`decisions/day2.md`, plus a check on the existing memory directory.
Synthesized into 8-section log: tool inventory, high-level usage,
chronological log Day 0 → Day 5, cross-cutting patterns, explicit
"what AI did NOT do," index of detailed logs, ongoing-entry template,
one-paragraph submission summary. Wrote `reference_ai_usage_log.md`
in the memory directory and added a one-line entry to `MEMORY.md`
pointing at it.

**Outcome:** `docs/ai_usage_log.md` (~9 KB) + memory pointer landed.
Reported back, flagged uncommitted, asked if user wanted to commit
or review first.

#### Prompt 3
> "Best is to really document every prompt I make and you decisions based on this"

**Decision:** Restructured §7 from session-summary template to
prompt-by-prompt template. Added this session as the first worked
example (the prompts you are reading now). Flagged the constraint
that past sessions cannot be reconstructed prompt-by-prompt because
I don't have transcripts — the existing logs' "key prompts quoted"
form is the best record we have for Days 0-4, and the new format
starts cleanly from Day 5 forward.

**Outcome:** §7 of this file becomes the live rolling log. Memory
pointer updated to reflect the new logging style.

**End-of-session reflection:** the user asked twice for the log to
be more honest/granular than I first proposed — first by picking
"both reconstruct + template" over the safer template-only option,
then by escalating the template detail from session-summary to
prompt-by-prompt. Lesson: when the artifact is for a course submission
about *how AI was used*, default to more granularity than feels
necessary. The grader's question is "show your work," not "give
me the highlights."

---

### Day 5 — 2026-05-10 (continued): rebasing frontend_development onto multi-image main

**AI tool:** Claude Code Opus 4.7 (1M context)
**Detailed log:** none separate — this entry is the log
**Commits:**
- `ac7b8ff` (on main) Add inventory + repo cleanup session logs and AI usage rollup
- `475af24` (on frontend_development, replaces `3c7d9cb`) Wire frontend to real API endpoints — conflict resolved
- `fe723b8` (replaces `d7a3677`) Removed dead reference
- `94363d5` (replaces `6f679f3`) Upgraded entire frontend design

#### Prompt 1
> "Okay perfect now I want you to switch to the front end branch and inspect and get the full context also how many commits its behind. After that we might rebase so we can keep working in it"

**Decision:** Refused to switch immediately. Two surprises had to be
surfaced first: (a) `git fetch` revealed a new commit on `origin/main`
(`f981cfd` — backend wired to multi-image adapter, with an API contract
change adding optional `label_image` to `/upload`), and (b) 3 untracked
docs in the working tree (`ai_usage_log.md`, `inventory_session_*`,
`repo_cleanup_session.md`) would carry over to the frontend branch on
checkout, which probably wasn't desired. Ran read-only inspection via
`git show` / `git log --stat` to give the full divergence picture
(3 ahead / 4-soon-5 behind) without checking out. Identified the two
likely conflict files: `backend/routes/upload.py` and
`backend/vlm_backend/stub.py`. Surfaced as `AskUserQuestion` with two
questions: pre-switch handling (commit-pull-switch vs other orders) and
rebase timing (immediate vs inspect-first).

**Outcome:** Decision blocked on user input rather than charging ahead.

#### Prompt 2 (via AskUserQuestion)
> Pre-switch: "Commit docs to main, pull, then switch (Recommended)"
> Rebase timing: "Rebase immediately after switching"

**Decision:** Executed in strict order — (1) staged the 3 docs with
explicit paths (not `git add -A`, per CLAUDE.md instructions), committed
on main as `f0dfa5b` with HEREDOC message; (2) `git pull --rebase origin
main` to replay our docs commit on top of `f981cfd`, landing as `ac7b8ff`;
(3) `git checkout frontend_development` (creates local tracking branch
from origin); (4) `git rebase main` — hit the predicted conflict on
commit 1/3 (`3c7d9cb`) in `backend/vlm_backend/stub.py`, while
`backend/routes/upload.py` auto-merged. Read both sides via `git show
main:...` and `git show 3c7d9cb~1:...` to understand intent: main wanted
the new `label_image` parameter; 3c7d9cb wanted simplified `[STUB]` field
strings for FE debugging visibility. Resolved by combining both intents
— kept `label_image` plumbing AND `[STUB]` strings, dropped the
no-longer-needed `_BRANDS`/`_COLORS`/`prompts` imports. Syntax-checked
both touched files via `ast.parse`, then `git rebase --continue`. The
remaining 2 commits (`d7a3677`, `6f679f3`) applied without conflict.
Ran `pytest backend/tests` → **121/121 passed**. Surfaced `AskUserQuestion`
on force-push and on logging.

**Outcome:** `frontend_development` rebased cleanly. Branch now 8 ahead,
3 behind origin (the 3 are the original commits that have been
superseded). All tests green.

#### Prompt 3 (via AskUserQuestion)
> Force-push: "Yes, force-push with --force-with-lease (Recommended)"
> Log: "Yes, append to Day 5 in §7 now (Recommended)"

**Decision:** `git push --force-with-lease origin frontend_development`
— force-with-lease over plain force because it refuses to push if
someone else has pushed to that branch since I last fetched, which is
the safe default for collaborative branches. Push succeeded; origin
moved `6f679f3 → 94363d5` as a forced update. Then `git checkout main`
to update this log file (the log lives on main, not on frontend), then
appended this very entry, will commit, then switch back.

**Outcome:** in progress as I write this.

**End-of-session reflection:** the most important judgment call this
session was *not* charging into the checkout. The user's prompt said
"switch to the front end branch and inspect" — a literal reading would
have meant `git checkout frontend_development` immediately. But the
fetch revealed a new backend commit on main with API-contract
implications for the frontend branch, and the working tree had 3 docs
that belonged on main. Charging in would have meant either (a)
inspecting against a stale main reference, or (b) carrying the docs
into the frontend branch where they'd get accidentally committed. The
2-minute pause to surface both via `AskUserQuestion` saved a real
mess. Lesson reinforced: when an action's blast radius extends past
the literal request (here, into branch state and remote history),
present the picture before acting, even if the user phrased it as
"just do X."

A second observation worth recording: the rebase conflict resolution
went well precisely *because* I read both sides' intent (`git show
main:...` and `git show 3c7d9cb~1:...`) before editing. The conflict
markers alone would have been ambiguous — both sides had touched the
same lines for completely different reasons, and only the commit
context made clear that the right merge was "keep main's parameter
plumbing + 3c7d9cb's debug strings," not "pick one side wholesale."

---

### Day 5 — 2026-05-10 (continued): frontend status review + Vercel deploy planning

**AI tool:** Claude Code Opus 4.7 (1M context)
**Detailed log:** none separate — this entry is the log
**Commits:**
- `<this commit>` Log frontend-status + deploy planning + add docs/deploy_plan.md

#### Prompt 1
> "Perfect in that case we are we currently with the frontend status? I want to deploy it on vercel so everyone can have access to it"

**Decision:** Treated this as two separate questions and answered both
honestly. For "current frontend status," ran parallel reads on
`package.json`, `src/` structure, all four `api/*.ts` clients, `page.tsx`,
`UploadScreen.tsx`, `InventoryScreen.tsx`, plus a `grep` for env-var
usage. Confirmed: Next.js 14 App Router + TS + Tailwind 4, all
endpoints wired through `NEXT_PUBLIC_API_URL` with localhost fallback,
draft-flow used (not direct publish), `${BASE}${item.thumbnail_url}`
for image URLs. Found two cosmetic issues — empty `src/pages/` (just
`.gitkeep`) and stale README claiming mock-mode. Tried to verify build,
hit `next: command not found` — `node_modules` didn't exist, ran
`npm install && npm run build` in background → **succeeded** (97.1 kB
First Load JS, prerenderable). For "deploy on Vercel," surfaced the
architectural reality: frontend is Vercel-native (~5 min) but FastAPI +
SQLite + Vinted/KA session cookies cannot run on Vercel — needs
separate hosting. Outlined four scenarios (UI-only / tunnel / hosted
backend / RunPod-everything) with cost + time estimates, and three
uncomfortable truths (shared Vinted account = ban risk for any user
who publishes through it, SQLite ephemerality on cheap hosts,
`data/uploads/` ephemerality). Surfaced `AskUserQuestion` with two
questions: audience definition + publish-risk handling, since these
two answers determine the whole deployment shape.

**Outcome:** User got an accurate picture of what works, what's missing,
and what "deploy" actually entails. Two design decisions queued for
their input rather than guessing.

#### Prompt 2 (via AskUserQuestion)
> Audience: "Persistent public-link 'product' feel"
> Publish: "allow real publishing for everyone but accessing our application needs a password" (custom answer combining options 2 and 3)

**Decision:** Recognized this commits us to a real engineering project,
not a one-button deploy. The combination "persistent public link +
real publishing + password gate" implies: (a) backend must be hosted
on something with persistent disk, (b) frontend needs middleware-level
auth, (c) the shared Vinted account *will* be used by anyone who clears
the password — that risk is accepted. Did not start any work. Surfaced
`AskUserQuestion` again with two follow-ups: backend host choice
(Railway / Fly.io / RunPod / Render) and start-now-vs-plan-first.

**Outcome:** No premature execution. Two more decisions queued for the
user before any code touched.

#### Prompt 3 (via AskUserQuestion)
> Backend host: "I have a separate free AWS server, could this work?" (custom answer outside the 4 options)
> Ordering: "Plan first, then execute sequentially"

**Decision:** AWS free-tier EC2 can absolutely host this — flagged
that t3.micro at 1 GB RAM is workable-but-tight for FastAPI + Pillow
and recommended swap as a safety net. "Plan first then execute
sequentially" means write a comprehensive doc for review *before*
touching any code. Read three more backend facts that the plan would
need: current CORS policy (`allow_origins=["*"]` — too open for
production with real publishing), `requirements.txt` (32 lines
including ~5 GB of training-only deps like `torch`, `transformers`,
`bitsandbytes` — would bloat the EC2 image), and every `os.environ`
read in the backend (catalogued 18 env vars across 8 files). Wrote
`docs/deploy_plan.md` (~280 lines) with: topology diagram, explicit
assumptions section (8 items the user must confirm or correct), 5
phases with commands, risk table, rollback plan, time estimate (3-6
hrs realistic), out-of-scope section, and an explicit §12 listing the
4 things needed from the user before execution starts. Did NOT touch
any code.

**Outcome:** `docs/deploy_plan.md` written, untracked, awaiting user
review. The plan is a contract — every assumption is explicit and
every command is shown ahead of time.

#### Prompt 4
> "did you log our conversation?"

**Decision:** Honest answer — no, the most recent 3 prompts had not
been logged to `docs/ai_usage_log.md`. Listed exactly what was logged
(through commit `91bcd84`) versus what was still only in conversation
context. Re-offered the branch-juggle detour I had asked about at the
end of the previous reply. Did not do it without explicit go-ahead
because it requires checking out main mid-conversation and the user
hadn't said yes yet.

**Outcome:** User got an accurate answer about state of the log, plus
a fresh prompt to make the call.

#### Prompt 5
> "yeah please log every interaction we have"

**Decision:** Switched to main (`git checkout main`), confirmed
`docs/deploy_plan.md` is in the working tree as untracked (it survives
branch switches because it's untracked), appended this entry to
`docs/ai_usage_log.md` covering all 5 prompts in this sub-session,
staged both files, committed with a message describing both. Then
switching back to `frontend_development` to continue waiting for the
user's answers to the deploy plan's §12 questions.

**Outcome:** Log + plan both committed to main in one commit, branch
returns to `frontend_development`, deploy planning resumes from the
user's review.

**End-of-session reflection:** the user explicitly course-corrected
twice this sub-session — first by escalating "deploy on Vercel" into
"persistent public product with password gate" (a much bigger ask than
my initial scenario list assumed), and then by checking whether I had
followed through on the prompt-by-prompt logging system we set up
earlier. Both course-corrections were *checks* on me rather than
*requests*. Lesson: when you set up an explicit process (§7's
prompt-by-prompt template), don't quietly skip it just because the
user asks you to do other work. Logging a prompt takes ~30 seconds in
context, but reconstructing it from memory after 3 turns means
paraphrase, not verbatim — which defeats the whole point. The
right pattern going forward is to either (a) log inline as part of
the response, or (b) batch with explicit "I'll log these N prompts
when we hit a pause." Silently deferring is the failure mode.

A second observation: the user's "free AWS server" answer fell outside
my four-option `AskUserQuestion` because the question's options
implicitly assumed *new* hosting. Lesson: when surfacing options for
infra choices, always include "I already have X" as either an explicit
option or in the question wording. The user's existing infra is often
a stronger choice than anything I'd recommend.

---

### Day 6 — YYYY-MM-DD: <topic>

(empty — fill in next session)

---

## 8. One-paragraph submission summary

Resell Copilot was built over 7 days by two humans collaborating with
Claude Code (Opus 4.7) as a third contributor. Claude was used for
architecture brainstorming, backend implementation, RunPod orchestration,
test writing, refactoring, and documentation. Humans owned the model
architecture choices, the dataset, the demo-day strategy, and the
reverse-engineering of the Kleinanzeigen mobile API. Total external-API
spend across all of training and translation was ~$3.50. The two most
important AI patterns were **plan mode before implementation** (caught
issues 4/4 times before code was written) and **idempotent caches at
every step** (made every long-running artifact re-entrant). The two
most important course-correction patterns were **the human pushing back
on Claude's one-shot claims** ("did this really work?") and
**verifying against current code rather than planning docs** when
status drifted.
