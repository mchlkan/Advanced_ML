# Repo cleanup session — 2026-05-08

Working session with Claude Code (Opus 4.7, 1M context) to clean up
accumulated cruft and impose a clearer folder structure on the repo.
Committed as `1910514` on `main` and pushed to `origin/main` (45 files
changed, +41 / -73).

---

## What changed

### Deletions
- `AGENTS.md` — byte-identical duplicate of `CLAUDE.md` (verified with `diff`).
- `eval/run_ours.py` — 2-line comment-only stub.
- `eval/compute_metrics.py` — 2-line comment-only stub.

### Folder restructure: `/src/` split into `/shared/` + `/data_prep/`

The old `/src/` was doing two unrelated jobs — runtime modules imported
by the FastAPI backend and the runpod handler, AND one-time data-prep
scripts. The mix was glued together with a `sys.path` hack in
`backend/__init__.py`. After the split:

```
shared/          # runtime (imported by backend + runpod)
  __init__.py
  prompts.py
  listing_mappings.py
  translations.py

data_prep/       # offline scripts (run once against /data parquets)
  __init__.py
  build_splits.py
  build_targets.py
  data_prep.py
  merge_datasets.py
  translate_text.py
```

Code edits to make the split work:
- `backend/__init__.py`: `sys.path` tuple `("models","src")` → `("models","shared")` + docstring update.
- `backend/vlm_backend/stub.py`: `_SRC_DIR` → `_SHARED_DIR`.
- Stale `repo/src` comments patched in `backend/{bootstrap,pipeline}.py`, `backend/vlm_backend/{local_mps,runpod_http}.py`, `backend/queue/runner.py`, `backend/routes/publish.py`.
- `sys.path.insert(0, "src")` → `"shared"` in `backend/tests/test_vinted_integration.py`.
- Extra `src/` references found and fixed in `models/extract_vlm_features.py`, `models/train_vlm.py`, `eval/run_qwen_field_eval.py` (these weren't in the original plan but would have broken at import time).
- `data_prep/build_targets.py` got a small `sys.path` shim so it can still find `translations` when run as a script.
- `runpod/Dockerfile`: `COPY src` → `COPY shared`. `runpod/handler.py` and `runpod/README.md` updated to match.

### Scratch docs moved under `/docs/`
- `project_memory_day1.md` → `docs/decisions/day1.md`
- `project_memory_day2.md` → `docs/decisions/day2.md`
- `review_prompts/*` → `docs/review_prompts/`
- `frontend/ClaudeDesignProposals/*.html` → `docs/design-mockups/*.html` (renamed to drop the literal spaces in filenames)
- Inbound cross-references patched in `docs/decisions/day2.md` and `docs/review_prompts/prof_04_defensibility_wrapper.md`.
- `.dockerignore`: removed now-redundant `review_prompts` line (it lives under `docs/` which is already ignored).

### Left alone (out of scope per session decisions)
- `/models/` reorg
- `/notebooks/` archive
- `backend/queue/` + `test_publish_runner.py` (confirmed as production code, not temp scripts)
- frontend code, SQLite DB
- Pre-existing in-flight work (inventory route, schema/main/vinted/conftest tweaks, `docs/ka_endpoints.md`) — left unstaged for separate commit.

### Verification
- `python -c "from backend.main import app"` → loads cleanly, 15 routes.
- `pytest backend/tests -x -q` → **90 passed in 62s**.
- `git grep` for stale `src/` references → zero hits in code, Dockerfile, or markdown.

---

## Interaction log

### 1. User invoked `/plan`

> "to clean up the repo with everything that is not needed anymore or
> was just a temporory test skript also maybe change the folder strucutre
> so it looks more strucutered"

Open-ended cleanup brief — no prescribed steps. Translated into a planning
exercise rather than direct edits because plan mode was active.

### 2. Phase 1 — Audit (3 parallel Explore agents)

Three subagents launched in a single message so they ran concurrently:

- **Agent 1: Repo cruft inventory.** Walked every top-level directory and
  reported what was active vs leftover scaffolding. Found the `AGENTS.md`
  duplicate, the two empty `eval/` stubs, the `/src/` mixed-purpose smell,
  `frontend/ClaudeDesignProposals/` HTML wireframes, and the
  `notebooks/99_spike.ipynb` historical artifact.
- **Agent 2: Import graph.** Traced what `backend/main.py` actually
  imports vs what's just sitting in `backend/`. Confirmed
  `backend/queue/` and `test_publish_runner.py` (both untracked at the
  time) are real production code, not scratch. Identified which `/src/`
  files are imported at runtime (`prompts`, `listing_mappings`,
  `translations`) vs offline-only.
- **Agent 3: Documentation audit.** Compared `AGENTS.md` and `CLAUDE.md`
  (byte-identical), assessed the two `project_memory_day*.md` files,
  `review_prompts/`, and config files. Confirmed `.gitignore`/
  `.dockerignore` are correct and no secrets are tracked.

### 3. Verification before asking the user

Bash checks to confirm specific claims:
- `diff CLAUDE.md AGENTS.md` (empty — duplicates confirmed)
- `git ls-files | grep DS_Store` (none tracked — good)
- `wc -l eval/run_ours.py eval/compute_metrics.py` (2 lines each — stubs confirmed)
- `git ls-files src/ models/ review_prompts/ docs/` (mapped tracked vs untracked)

### 4. Phase 2 — Scoping questions (`AskUserQuestion`)

Three multiple-choice questions to nail down judgment calls before writing
the plan:

1. **How aggressive on `/src/`?** → User picked "Split into runtime vs data-prep" (the most thorough option).
2. **What about scratch docs?** → User picked "Move all into `/docs/`" (preserve history, declutter root).
3. **Are `backend/queue/` + `test_publish_runner.py` real or temp?** → User confirmed "Keep — they're production".

### 5. Pre-plan verification

Before drafting the plan, more bash checks to nail the exact import sites
that would need editing:

- `grep "from src\." / "import src\." / "prompts" / "listing_mappings"`
  across `backend/` and `runpod/` to map every call site.
- Found that imports use bare names (`from prompts import ...`, not
  `from src.prompts import ...`), held together by `sys.path` shims in
  `backend/__init__.py` and `runpod/handler.py`.
- Read `runpod/Dockerfile` to confirm `COPY src /workspace/src`.
- Read `backend/tests/conftest.py` to understand the test setup.

### 6. Phase 3 — Plan written

Plan saved to `~/.claude/plans/harmonic-nibbling-frost.md` with four phases:
A (safe deletions), B (doc moves + reference patches), C (`src/` split with
exact file-by-file edits), D (verification: pytest + smoke imports + grep).

### 7. Plan approval (`ExitPlanMode`)

User approved, exiting plan mode.

### 8. Execution — sequential phases with `TaskCreate`/`TaskUpdate`

Tasks:
1. Phase A: delete duplicates and stubs ✓
2. Phase B: move scratch docs into `/docs/` ✓
3. Phase C: split `/src/` into `/shared/` and `/data_prep/` ✓
4. Phase D: verify with pytest and import smoke checks ✓

Mid-execution discovery: a `git grep` after Phase C found three additional
`src/` references the plan hadn't anticipated (`models/extract_vlm_features.py`,
`models/train_vlm.py`, `eval/run_qwen_field_eval.py`). All three import
`prompts` — patched on the spot.

Verification (Phase D):
- Smoke-imported `shared/` modules via `python3 -c`.
- Switched to project venv (`.venv/bin/python`) for the real tests.
- `from backend.main import app` → 15 routes loaded.
- `pytest backend/tests -x -q` → 90 passed.

### 9. User: "can you commit and push?"

Inspected git status carefully because the working tree had pre-existing
in-flight work (inventory route, schema/main edits) mixed with the cleanup.

Verified the diffs to `backend/queue/runner.py` and `backend/routes/publish.py`
were exactly the comment-only edits I'd made — no overlap with user work.

Staged cleanup files **only** (21 explicit paths), leaving 5 modified files
and 3 untracked files for the user to commit separately. Committed with a
detailed multi-paragraph message matching the repo's existing style.

`git push origin main` succeeded: `6131c38..1910514`.

### 10. User: "summarize everything … also a log how we interacted"

This file.

---

## Files changed (quick reference)

| Category | Count |
|----------|-------|
| Deleted | 3 (`AGENTS.md`, 2 eval stubs) |
| Renamed (moves) | 27 (src → shared/data_prep, doc moves) |
| Modified | 14 (sys.path hacks, comments, `.dockerignore`, runpod) |
| Created | 1 (`shared/__init__.py`) |
| **Total** | **45 files, +41 / -73 lines** |

## Commit

```
1910514 Repo cleanup: split src/ into shared/ + data_prep/, move scratch docs
```

## Plan file (preserved for reference)

`~/.claude/plans/harmonic-nibbling-frost.md`
