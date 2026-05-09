# Project Memory - 2026-05-09

This file is a handoff for a new chat/agent. It captures what changed recently, what is currently true locally, and what should happen next.

## Current Git State

- Branch: `main`
- Latest pushed commit: `0902bf0 Add VLM parse recovery and field review flags`
- Worktree was clean before creating this file.
- This file is intentionally **not committed or pushed yet**.

Recent pushed commits:

- `0902bf0` - Added production VLM parse recovery and field review flags.
- `22d1dfb` - Fixed price-head sweep support so `--seed` does not change original DataLoader training order.
- `ca26a85` - Added Qwen field-eval result JSON and Model #4 price-head sweep runner.

## Current Local Artifact State

Model/data artifacts are gitignored. Do not expect Git to carry them.

Important local files:

- Improved deployed local price head:
  - `models/checkpoints/price_head.pt`
  - This was copied from `models/checkpoints/price_sweep/seed42_drop0p1_h512_b32_lr0p001_flaw.pt`.
  - It smoke-loaded successfully with:
    - `dropout=0.1`
    - `hidden_dim=512`
    - `brand_dim=32`
    - `uses_flaw=True`
- Present locally:
  - `models/checkpoints/flaw_head_vinted.pt`
- Missing locally at last check:
  - `models/checkpoints/sell_head.pt`
- Available in local artifact bundle:
  - `data/resell-copilot-artifacts/models/checkpoints/price_head.pt`
  - `data/resell-copilot-artifacts/models/checkpoints/sell_head.pt`
  - `data/resell-copilot-artifacts/models/checkpoints/flaw_head_vinted.pt`
  - `data/resell-copilot-artifacts/data/embeddings/vlm_pooled_combined.npy`
  - `data/resell-copilot-artifacts/data/features/price_features_combined.parquet`
  - `data/resell-copilot-artifacts/data/features/price_feature_vocab.json`

If starting the full backend with real ML, first copy `sell_head.pt` from the artifact bundle into `models/checkpoints/`.

## What We Did Recently

### Model #1 Qwen Field Eval

Ran field-level Qwen evaluation on 500 locked test examples via RunPod GPU.

Committed summary result:

- `eval/results/qwen_field_eval.json`

Local ignored artifacts:

- `eval/results/qwen_field_predictions.parquet`
- `eval/results/qwen_field_eval_full.log`

Headline result:

| Field | Overall |
|---|---:|
| JSON parse rate | 81.8% |
| Brand fuzzy | 50.4% |
| Category exact | 96.8% |
| Condition exact | 65.6% |
| Color exact | 72.2% |
| Size exact | 24.0% |

Interpretation:

- Category is strong.
- Brand and size are weak.
- Kleinanzeigen parse reliability is weak.
- Model #1 should be framed as an editable listing draft, not automatic reliable extraction.

### Model #1 Safety Quick Win

Implemented production safety improvements in `0902bf0`.

Backend:

- Added `parse_vlm_fields(text)` in `backend/vlm_backend/util.py`.
- Existing `parse_json_lenient(text)` still returns a dict.
- Parser now handles:
  - clean JSON,
  - markdown-wrapped JSON,
  - leading/trailing prose,
  - truncated/malformed JSON where scalar fields can be recovered.
- Parser still does not accept Python-style single-quote dicts.
- `VLMOutput` now includes:
  - `parse_ok`
  - `recovered`
- `local_mps` and `runpod_http` now use the shared metadata parser.
- `eval/run_qwen_field_eval.py` now uses the same backend parser.

API/product:

- Both platform blocks now include:

```json
"field_review": {
  "needs_review": ["brand", "size"],
  "reasons": {
    "brand": "low_confidence",
    "size": "low_confidence"
  }
}
```

- If malformed JSON recovery was needed, reasons include `parse_recovered`.
- `/verify` removes `brand` and/or `size` from review when the user supplies those hints.
- Frontend result chips show compact `Check` state for brand/size when review is needed.
- Publish behavior is unchanged.

Verification passed:

- `conda run -n AD_ML pytest backend/tests/test_local_mps.py backend/tests/test_runpod_http.py -q`
- `conda run -n AD_ML pytest backend/tests/test_routes.py -q`
- `cd frontend && npm run type-check`

### Model #4 Price Head Sweep

Implemented and ran focused local sweep using recovered artifacts.

Winner:

- `models/checkpoints/price_sweep/seed42_drop0p1_h512_b32_lr0p001_flaw.pt`

Current baseline vs winner:

| Model | MAE | MAPE | RMSLE | Coverage |
|---|---:|---:|---:|---:|
| Current saved price head | 15.65 | 0.533 | 0.545 | 0.768 |
| Best sweep checkpoint | 14.63 | 0.492 | 0.513 | 0.834 |
| Best sweep no-flaw | 14.69 | 0.491 | 0.515 | 0.850 |
| GPT-4o-mini baseline | 21.50 | 1.025 | 0.707 | n/a |

Verdict:

- Use the flaw-enabled `dropout=0.1` checkpoint.
- It beats the saved baseline on MAE, MAPE, and RMSLE.
- No-flaw has a tiny MAPE edge only, but flaw-enabled is better overall and wins validation-first selection.

Local deployment already done:

```bash
cp models/checkpoints/price_sweep/seed42_drop0p1_h512_b32_lr0p001_flaw.pt \
   models/checkpoints/price_head.pt
```

This is local only because checkpoints are gitignored.

## What To Do Next

### Immediate Next Step: Full App Smoke Test

Goal: confirm the backend/frontend path works end-to-end after recent backend/frontend changes and the improved local price checkpoint.

Checklist:

1. Copy missing checkpoint:

```bash
cp data/resell-copilot-artifacts/models/checkpoints/sell_head.pt models/checkpoints/sell_head.pt
```

2. Confirm required local checkpoint files exist:

```text
models/checkpoints/flaw_head_vinted.pt
models/checkpoints/price_head.pt
models/checkpoints/sell_head.pt
```

3. Start backend with desired VLM backend.

For fast non-ML smoke:

```bash
SKIP_ML=1 uvicorn backend.main:app --reload
```

For real local pipeline, ensure env vars/checkpoints are available and run backend normally.

4. Hit:

```bash
curl http://localhost:8000/healthz
```

5. Start frontend:

```bash
cd frontend
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

6. Test flow:

- Upload image.
- Confirm result page renders.
- Confirm price band appears.
- Confirm brand/size show `Check` review state.
- Edit brand/size and verify.
- Confirm review flags clear after verify.
- Confirm listing appears in inventory.

### Next Engineering Fix: Verify/Publish Frontend Wiring

Earlier inspection showed:

- `frontend/src/api/upload.ts` is wired to the real backend.
- `frontend/src/api/inventory.ts` is wired to the real backend.
- `frontend/src/api/verify.ts` still looked mock-ish.
- `frontend/src/api/publish.ts` still looked mock-ish.

Next chat should inspect those files again and wire them to the real backend if still mocked.

Important: backend `/publish` currently returns async job response (`job_id`, `status`, etc.), while frontend type may still expect legacy `prefill_url`. This likely needs a small frontend type/API adjustment.

### Next ML/Quality Improvements

Keep these in mind after smoke test:

1. Analyze 30-50 weak Qwen examples:
   - brand misses,
   - size misses,
   - Kleinanzeigen parse/recovery cases.
   - Classify as label noise, invisible field, taxonomy mismatch, or model failure.

2. Add simple normalization:
   - brand casing/aliases (`h&m`, `H and M` -> `H&M`),
   - size cleanup (`Medium` -> `M`, `EU 40` -> `40`).

3. Multi-photo experiment:
   - Only start when Leon provides a clean `listing_id -> multiple photo paths` mapping.
   - Likely improves brand/size/tag/wear because those are often not visible in the hero image.

4. Human-labeled mini-set:
   - 300-500 images for tag/wear/brand-visible/size-visible.
   - Useful for honest evaluation and later retraining, not essential before demo smoke test.

## Operational Notes

- Use `conda run -n AD_ML ...` for Python commands on this machine.
- `AD_ML` has torch and core ML deps.
- We installed `pytest` and `respx` into `AD_ML` during testing.
- `frontend/node_modules/` exists locally after `npm ci`.
- Generated/cache folders are ignored and should not be committed.
- Do not commit model checkpoints or data parquet/npy artifacts unless explicitly forced for a specific handoff.
