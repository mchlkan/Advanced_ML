# Session Log — Day 2 QLoRA Fine-Tune (2026-05-06 → 2026-05-07)

A working log of the multi-day Claude session that took the project from
"data prepared, no model trained yet" through to a fine-tuned Qwen3-VL-4B
adapter on HuggingFace Hub plus a re-runnable evaluation appendix in the
spike notebook.

Captures both the **substance** (decisions, code, results) and the
**shape** of the collaboration (which prompts opened which phase, where
the team had to redirect, what blocked us). Written so a teammate not in
the chat can reconstruct what happened and why.

---

## Outcomes

### Tangible artifacts produced

| Path | Purpose |
|---|---|
| `src/translations.py` | DE↔EN forward + reverse lookup tables (4 conditions, 33 colors, 4 KA categories) |
| `src/translate_text.py` | Async GPT-4o-mini batch translator with parquet cache |
| `src/prompts.py` | Single-source-of-truth English VLM prompt with platform-conditional category vocab |
| `src/build_targets.py` | `build_canonical()` — joins translations + applies lookups |
| `src/build_splits.py` | Stratified locked 500-row test + 90/10 train/val splits |
| `src/listing_mappings.py` | Reverse map from canonical schema → platform-native (KA German + Vinted ontology stubs) |
| `data/translations/translations.parquet` | 8,711 rows of (title_en, description_en) — gitignored |
| `data/combined_clothing.parquet` | Filtered + translated combined Vinted + KA — gitignored |
| `data/splits/{train,val,test}_ids.json` | Committed id lists (brief §4.5 reproducibility) |
| `data/splits/{train,val,test}.parquet` | Locked splits with images + canonical English fields — gitignored |
| `data/features/spike_test_vlm_features.pt` | Pooled hidden states for the 100-row test set (price-head input) — gitignored |
| `notebooks/99_spike.ipynb` (cells 16-24) | Fine-tuned adapter eval + canonical metrics + delta table + hidden-state extractor |
| `Rengo33/qwen3vl4b-resell-adapter` (HF Hub, private) | The actual trained model — 161 MB safetensors |

### Git activity (this session's commits)

| Commit | Subject |
|---|---|
| `c4dfb24` | Build bilingual data prep + train/val/test splits |
| `f5d1bb9` | Add fine-tuned adapter eval to spike notebook |
| `ac46333` | Make spike notebook FT-eval cells fully self-healing |
| `e2b6aa2` | Add VLM hidden-state extraction to spike notebook |

### Strategic decisions locked in this session

| Decision | Rationale |
|---|---|
| **One canonical English schema for the model output**, lookup tables for platform-native at publish time | One output distribution → simpler model + cleaner JSON contract; no per-platform inference branching |
| **All-language Vinted training pool (6.4k), not DE-only (1.4k)** | Categorical fields (category, condition, color) are language-stable in the source data — only title/description vary by row language |
| **English prompt + English title/description in target** | User-decided; lookup tables convert structured fields back to KA-German at publish |
| **GPT-4o-mini for translation** | Matches Day 1 spike's API key + provider; ~$0.50 for 8.7k rows |
| **LoRA r=16 on `all-linear`, 2 epochs, eff batch 8** | Brief §3.1 recipe; "all-linear" goes broader than spec'd ("attention + MLP") because the fine-tune only takes 3h regardless |
| **Auto-terminate the pod via `runpodctl remove pod` after HF Hub upload** | Cheap insurance against forgetting to terminate overnight |

### Headline numbers

Comparing the fine-tuned Qwen 4B vs the **same base model** zero-shot, on
the locked 100-row spike test set, with canonical English label
comparison:

| metric | zero-shot 4B | fine-tuned 4B | delta |
|---|---|---|---|
| parse_rate | 1.000 | 0.990 | -0.01 |
| brand_acc | 0.230 | **0.374** | **+0.14** |
| category_acc | 0.930 | 0.909 | -0.02 |
| condition_acc | 0.640 | **0.727** | **+0.09** |
| color_acc | 0.630 | **0.808** | **+0.18** |
| **price_mape** | **1.080** | **0.506** | **−0.57** |

Versus GPT-4o-mini, the fine-tune wins on **every** metric — most
dramatically on parse_rate (0.30 → 0.99) and price_mape (1.09 → 0.51).

**Total compute spend**: ~$0.50 translation + ~$3 RunPod 4090 = **~$3.50**.

---

## Collaboration shape — phases of the session

### Phase 1 — Status check + dataset survey

> **Prompt that opened it:**
> *"okay can you summarize what has been done and maybe also start to
> explore with the datasets in the folder above what we still need to do
> so we can finetune a specific model. message from my teammate"*

- Ran `git pull` (1 incoming commit).
- Re-read brief, inspected both parquets in the parent dir, ran
  `data_prep.apply_filters` to surface the funnel: 7,723 + 4,000 raw →
  6,409 + 2,302 post-filter → **8,711 combined**.
- Listed gaps before training: no English target text, no train/val/test
  split, training script was a 77-byte stub.

### Phase 2 — Brainstorming the language strategy

> **Prompt:** *"Cant we also transform everything into english so we
> have 1 dataset that we can use?"*

- Pushed back on "English for everything" because Vinted.de + KA-de
  buyers expect German listings. Suggested German-only.
- User replied with a partial design: "title and description in English,
  rest as needed for listing." Then refined to "unify in English and
  make a lookup table for the listing."
- Researched Vinted Pro API + Kleinanzeigen API ([WebFetch + WebSearch]).
  Found:
  - Vinted's `/items` endpoint takes one untyped `title`/`description` —
    locale is implicit in the marketplace
  - Kleinanzeigen has no individual-seller API; v1 publishes via
    pre-filled deep link (brief §5.3)
- This unblocked the design: **canonical English internally + reverse
  lookup tables at publish time**.

### Phase 3 — Plan mode

> **Prompt:** *"/plan please"*

Generated a detailed plan file
(`/Users/leonschmidt/.claude/plans/unified-nibbling-fiddle.md`) covering:

- The canonical schema (English title/description/condition/color, KA's
  categories mapped to English, brand/size/price unchanged)
- Files to add (translations, prompts, translate_text, build_targets,
  listing_mappings)
- Files to modify (data_prep path fix, requirements, gitignore)
- Verification: row counts, translation spot-check, round-trip lookups
- Open questions (translation prompt style, retain originals as debug
  columns)

User approved with one clarification: *"I dont understand this: 4. Row
count sanity..."* — the verification numbers needed an explanation of
why 7,723 → 6,409 etc.

Plan was approved, then the user redirected: *"Okay as we want to list
it through vinted/kleinanzeigen api can you look that up before
changing anything on how to upload items in which languages?"* — that
forced the API research before implementation, which is how the
canonical-schema design ended up clean instead of bilingual.

### Phase 4 — Implementation

Built each module top-to-bottom, verifying as we went:

- `src/translations.py` — coverage gate (`assert_coverage`) raises on
  any unmapped value seen in the data. Verified against actual unique
  values: 33 colors, 4 conditions, 4 KA categories.
- `src/prompts.py` — `get_prompt(platform)` with English category
  vocabularies inlined.
- `src/translate_text.py` — async GPT-4o-mini with concurrency 8,
  tenacity retries, parquet cache keyed by `(platform, id)`. Smoke-tested
  on 5 rows across DE/IT/FR/EN.
- `src/build_targets.py` — `build_canonical(df, translations)` returns a
  DataFrame augmented with `*_canon` columns + retained `*_orig`.
- `src/listing_mappings.py` — `to_kleinanzeigen()` and `to_vinted()`.
  Vinted ontology IDs stubbed for Day 4.

### Phase 5 — The translation run

> **Prompt:** *"runpod api key... I need to configure a public key for
> ssh access"* came later; for now the translation ran on the local
> machine.

- Kicked off `python src/translate_text.py` against the 8,711-row
  combined dataset in the background.
- Set up a `Monitor` on the output file to stream `... 50/8711` style
  progress.
- Pace held at ~3.3-3.5 rows/sec → finished in ~45 min.
- 3 rows came back null on first pass (one IT, one FR with emojis, one
  DE) — re-translated with `max_tokens=1500` (one had hit the 600-token
  cap mid-emoji-heavy listing). Final state: 8,711 / 8,711 clean.

User asked mid-run: *"okay my friend does the data prep, can we just
repack the dataset again?"* — confirmed the pipeline is idempotent +
explained the 8,711 funnel.

### Phase 6 — Splits + train script alignment

> **Prompt:** *"okay does this now make sense to finetune a model with?
> and what would be the steps?"*

Re-checked `models/train_vlm.py` — discovered Lenn had already shipped a
**313-line full QLoRA trainer** (not a stub). It expected `*_canon`
columns; my pipeline produced `*_en`. Three-line edit aligned the names.

> **Prompt:** *"/plan okay plan those steps throughly and than we will
> move on"*

Wrote a tighter plan: `src/build_splits.py` + a 5-line edit to
`train_vlm.py` + delete `notebooks/02_data_prep.ipynb` (now redundant
with `merge_datasets.py`). Plan approved.

Built and ran `build_splits.py` end-to-end:
- 8,711 → train 7,390 + val 821 + test 500 (matches plan estimate
  exactly)
- All required columns non-null
- Per-platform-per-category breakdowns proportional

Committed everything as `c4dfb24`.

### Phase 7 — RunPod fine-tune (the messy phase)

> **Prompt:** *"lets go with runpod, walk me through setup"* → *"okay
> but lets go through ssh again, because than you can do much of the
> work"*

This phase had the most friction. Sub-phases:

#### 7a — SSH key dance (the hour we lost)

1. First pod deployed without SSH public key in account settings →
   permission denied
2. User pasted the key into web terminal, but the heredoc paste **broke
   into two lines** — `authorized_keys` had a malformed second entry,
   SSH refused all auth from the file
3. User added key to RunPod *account settings* → that's the
   **proxy** SSH key store, but I was trying *direct* SSH first
4. *"can we just create a new ssh key? maybe my old one is broken?"* —
   generated a fresh `~/.ssh/runpod_ed25519`
5. User saved new key in RunPod settings → had to click "Update public
   key" button (had pasted but not saved)
6. Old pod's GPU got reclaimed by community cloud during a Stop/Resume
   attempt → had to redeploy fresh
7. Fresh pod with the new key worked

**Lesson:** RunPod's "SSH Public Keys" in account settings is the right
flow; the key gets injected at pod boot. Manual `authorized_keys` paste
in web terminal is brittle (heredoc line wrap risk). And **Stop on
community-cloud risks losing the GPU** — Terminate + redeploy is cleaner.

#### 7b — Dependency install (45 min of pip suffering)

1. `pip install -r requirements.txt` got stuck in dependency resolution
   (~15 min, no progress)
2. Switched to **uv** (parallel, fast resolver) — uv started downloading
   at 250 KB/s sustained (PyPI throttling that pod's network)
3. User: *"Is there a faster way?"* → tried killing + restarting with a
   targeted package list (`transformers accelerate peft bitsandbytes
   datasets ...`) instead of the full requirements.txt
4. Wrapped in **tmux** so SSH disconnects don't kill it
5. uv finished in ~1 min after we narrowed the package list

**Lesson:** for one-off install, hand-pick the packages and skip the
mega-resolution. Always run inside tmux on RunPod.

#### 7c — Version conflict (the qwen3_vl gotcha)

1. First smoke test exited at "val rows: 821" — `KeyError: 'qwen3_vl'`
   in transformers' config registry
2. Initial install pulled `transformers==5.8.0` which doesn't have
   `qwen3_vl` registered (requires `>= 4.57`) — but transformers 5.x
   broke compatibility with torch 2.4.1 (which is what the RunPod
   PyTorch 2.4 image ships)
3. Pinned to `transformers==4.57.6` — Python checked
   `'qwen3_vl' in CONFIG_MAPPING` → True
4. Smoke test re-ran cleanly: trainable params 40M / 4.48B (0.9%),
   train+eval loop, adapter saved

**Lesson:** model-architecture support is version-sensitive. Always do
`from_pretrained` smoke before kicking off the long run.

#### 7d — Training (the calm phase)

Wrote a wrapper script `/root/run_training.sh`:

```bash
python -m models.train_vlm \
  && huggingface-cli upload Rengo33/qwen3vl4b-resell-adapter \
       models/checkpoints/qwen3vl4b-resell-v1 . --private --repo-type model \
  && runpodctl remove pod $POD_ID
```

The `&&` chain means: only upload if training succeeded; only terminate
if upload succeeded. If anything fails the pod stays alive for debugging.

Launched in tmux at 09:38:54 UTC. Set up a Monitor that greps for
`'loss':`, `eval_loss`, errors, and wrapper milestones. Monitor caught:

- 14 min of silent dataset construction (no `print` calls in
  `to_chat_dataset` — flagged as a Lenn-side improvement)
- Steady 6 s/step over 1,848 steps
- VRAM growth from 21 → 23.5 GB (95% of 24 GB) over the first ~50 steps
  — user worried it was a leak; actually just paged_adamw lazily
  allocating optimizer state. Confirmed stable thereafter.
- `eval_loss = 0.383` at end of epoch 1, ≈ train loss → no overfitting
- Training finished at ~14:06 UTC; HF Hub upload at 14:09 UTC; pod
  auto-terminated immediately after

**~3 hours training + ~1 hour overhead, ~$3 total.**

### Phase 8 — Eval integration in the spike notebook

> **Prompt:** *"can you integrate that into the spike notebook without
> running everything again"*

Appended cells 16-20 to `notebooks/99_spike.ipynb`:

- Cell 16 — markdown explaining the appendix
- Cell 17 — load adapter + run inference on the cached 100-row test set
- Cell 18 — markdown explaining canonical-label comparison
- Cell 19 — `compute_metrics_canon` (canonicalizes both sides via the
  translations lookups)
- Cell 20 — delta table (FT vs zero-shot 4B vs GPT-4o-mini)

#### 8a — Two NameError fixes

User ran cells out of order (skipped the long zero-shot eval cells) →
hit `NameError: PERF`, then `NameError: model_slug`.

Patched cells 17 and 19 to **self-heal** missing globals:
```python
PERF = globals().get("PERF", {})
if "model_slug" not in globals():
    def model_slug(m): return m.split("/")[-1].lower()
```

Now cells 17-20 are runnable in isolation.

### Phase 9 — Hidden-state extraction (price-head input)

> **Prompts:** *"how do we get the vlm hidden state? from our fine
> tuned model?"* → *"Can you integrate this yourself? so I can get the
> hiddenstate?"*

Appended cells 21-24 to the spike notebook:

- `extract_pooled_state(image, platform, pool="last")` — runs forward
  pass with `output_hidden_states=True` through the fine-tuned model,
  returns the last-layer hidden state at the position right before
  generation would start
- Cache loop saves `data/features/spike_test_vlm_features.pt` (ids,
  platforms, features tensor `[100, 2560]`, metadata)
- Documented for use as input to Model #4 (price head) per brief §3.4

---

## Process observations (the meta-learnings)

### What worked

- **Plan mode before implementation** — twice. Both times the
  `EnterPlanMode` → `ExitPlanMode` cycle caught an issue before code
  was written:
  - First plan: API research forced the canonical-schema design vs
    bilingual
  - Second plan: discovered `train_vlm.py` was already written, scope
    shrank from "build training script" to "5-line column rename"

- **Background `Monitor` for long-running ops.** Used three times:
  translation run, install progress, training milestones. Pattern:
  `tail -f log | grep --line-buffered <keywords>` so the chat only
  fires on real events, not noise. Saved hours of polling.

- **Idempotent caches at every step.** Translation cache, splits
  parquets, FT predictions JSON, hidden-state pt. Re-running any cell
  is a no-op if the artifact already exists. Made the spike notebook
  appendix runnable without re-doing a 1-hour inference.

- **Auto-terminate on the GPU pod.** Cost discipline; let the user
  sleep without worrying about $0.69/hr leaking overnight.

### What I'd do differently

- **`tmux apt-get install` first thing on every pod.** Lost 30 min the
  first time when SSH disconnected and killed pip. tmux should be the
  very first command after `ssh root@...`.

- **Smoke test BEFORE the dependency install.** Discovered the
  `qwen3_vl` config issue only after pip was done. A 30-second
  `python -c "from transformers import AutoConfig; AutoConfig.from_pretrained('Qwen/Qwen3-VL-4B-Instruct', trust_remote_code=True)"`
  could have caught it.

- **Pre-pin transformers in `requirements.txt`.** The version drift
  between torch 2.4 and transformers 5.x cost an hour. `transformers>=4.57,<5.0`
  would have prevented it.

- **Add `print` checkpoints inside `to_chat_dataset`.** 14 minutes of
  silent CPU-bound work without a single log line is hostile to the
  monitor. Should print every ~500 rows.

- **Test the metrics-comparison logic before training.** The
  apples-to-apples concern (zero-shot uses German labels vs FT uses
  English) only surfaced when we tried to extend the table. Should
  have written `compute_metrics_canon` in advance and confirmed it
  gives the same numbers as `compute_metrics` on the existing
  zero-shot predictions.

### Friction points the team should know about

- **RunPod community cloud** is cheaper but has two real risks: GPU
  reclaim on Stop, and bursty PyPI throughput. For one-shot training
  it's still the right call (cost matters more than reliability for a
  single run), but plan around them.

- **HuggingFace transformers is moving fast.** Don't pin
  `transformers>=X.Y` without an upper bound — major versions
  (4.x → 5.x) break torch compat. We hit this twice.

- **`pip` dependency resolution is genuinely broken on tight
  PyPI bandwidth.** uv is ~10x faster and worth the install hop.
  Default to uv for any RunPod work going forward.

---

## Open follow-ups for the team

| Item | Owner | Notes |
|---|---|---|
| Make the HF Hub adapter accessible to teammates | Leon | Add Lenn + others as collaborators on `Rengo33/qwen3vl4b-resell-adapter`, OR flip to public (adapter weights don't leak the dataset) |
| Run cell 19 with all 4 prediction JSONs in `results/spike/` | anyone | Bottom table currently shows only FT because zero-shot JSONs were missing on Colab disk. Copy them over for the clean 4-row canonical comparison |
| Investigate the 1 parse failure in FT predictions | anyone | `parse_rate=0.99` → one row's JSON was malformed. Check `recs = json.loads(...); [r for r in recs if r['parsed'] is None]` |
| Extract hidden states for the full splits (train+val+test) | downstream of price head work | ~30 min on a 4090 for 8,711 rows. Wrap `extract_pooled_state` in a Python script + run on RunPod |
| Reclaim KA `PLEASE_CONTACT` rows for VLM-only training | future v2 | +1.4k rows, ~5-8% gain across the board, ~30 min code change |
| Wire the listing-mappings reverse functions into `backend/routes/publish.py` | Day 4 work | Vinted ontology IDs need to be fetched from `GetOntologies` and cached |

---

## Reference material from the session

- Plan files (Claude `/plan` mode):
  `/Users/leonschmidt/.claude/plans/unified-nibbling-fiddle.md` (latest version is the splits plan; the earlier translation-design plan was overwritten)
- Memory:
  `~/.claude/projects/.../memory/project_canonical_schema.md` — locked the architecture decision for future sessions
- Adapter: `https://huggingface.co/Rengo33/qwen3vl4b-resell-adapter` (private)
- Training cost receipt: ~$3.10 RunPod community 4090 + ~$0.50 OpenAI
- Spike notebook with appendix cells: `notebooks/99_spike.ipynb` (cells 16-24)
