# Planning Session Log — 2026-05-10

A working log of a single Claude planning session. Captures both the
substance (decisions made, docs written) and the *shape* of the
collaboration (how prompts evolved, where I had to be redirected, what
worked).

Pre-compaction context: the session continued from earlier conversations
covering Phases 3-6 of backend implementation, /publish async flow,
Vinted + KA integrations, and frontend prep. This log covers the
post-compaction portion: model improvement brainstorming through demo
strategy.

---

## Outcomes (the tangible things this session produced)

### Documents created
| Path | Lines | Purpose |
|---|---|---|
| `docs/multi_image_finetuning_plan.md` | 309 | Full plan for verifying CLIP tags + building multi-image training dataset |
| `docs/demo_strategy.md` | ~250 | Pitch framing, metric story, open questions for team discussion |
| `docs/session_log_2026-05-10.md` | this file | Meta-log of the session |

### Git activity
- Pulled 5 incoming commits from `origin/main` (Michael's multi-image retrain + Model #6 + parse-fix docs)
- Committed + pushed `multi_image_finetuning_plan.md` to `origin/main` (commit `b984cd0`)
- Identified `origin/frontend_development` branch as stale (created before multi-image retrain landed)

### Strategic decisions made
| Decision | Rationale |
|---|---|
| **Lead demo with Vinted, KA as extensibility proof** | Multi-image retrain was Vinted-only, gives stronger numbers |
| **Skip the KA parse-rate retrain (Option A)** | Recovery handles 100% of failures; another 4 GPU-hours not worth it |
| **Description generation stays on Groq Llama 3.1 8B (Model #6)** | Commodity prose, focus retraining budget elsewhere |
| **Multi-photo training via "untyped multi-image"** | Friend's input — let model figure out per-image relevance vs slot tags |
| **No base-model swap (Qwen3-VL stays)** | LoRA already trained; switching invalidates 1 day of work |

---

## Timeline (phase by phase, with the prompts that opened each phase)

### Phase 1 — Brainstorm: improving model quality
**Opening prompt:** *"Now we have to think on how to improve our model, because our professor wants either our model to be cheaper or much better than chatgpt4o mini..."* (continuation of earlier discussion)

**Shape of interaction:** open-ended brainstorm. I produced a structured
list across all 5 models in the stack with effort/impact tags, then a
prioritized "what would actually move the demo" pick-list.

**What I got wrong on first pass:** initially anchored too heavily on
MAPE comparison vs GPT-4o-mini. Got course-corrected:

> *"Not focus completely on MAPE as Vinted itself already has a price
> suggestion, our focus is that you can upload one picture and you can
> instantly list on all platforms with much afford."*

Updated framing to lead with description quality and platform extensibility.

---

### Phase 2 — VLM scaling: 4B vs 4B-fp16 vs 8B
**Opening prompt:** *"Okay good work we think about that for the future, right now I want to stress 4b, 4b fp16, vs 8b model + new finetuning we have enough credits lap for runpods"*

**Shape of interaction:** focused tradeoff analysis. User redirected
twice mid-explanation:
- *"idk what fp16 does?"* → I had to step back and explain quantization from first principles
- *"what about in terms of speed and costs?"* → economics, then *"always in terms of costs compare to 4o mini"* → honest comparison showing 4o-mini wins on per-call cost at demo volume

**Key turning point:** the honest comparison ("at <100 uploads/day,
4o-mini is cheaper than your stack") reframed the entire pitch strategy
away from "cheaper than 4o-mini" toward "better on the metrics that
matter + own the integrations."

---

### Phase 3 — Architecture: separate model for descriptions?
**Opening prompt:** *"okay but for description we could also choose another model that does the description based on category etc. right?"*

**Shape of interaction:** I laid out 4 options (two VLM calls, text-only LLM, hybrid with visual cues, GPT-4o-mini for descriptions). User implicitly accepted the principle ("yes, decoupled identification and description") and moved on. Discussion seeded what later became Model #6.

---

### Phase 4 — Multi-photo training
**Opening prompts (multiple):**
1. *"okay so what I also thought about to train the model with 2/3 pictures?"*
2. *"I think qwen3.5 is multimodal so they dont have a specific model another thing is we dont have for example label pictures for every listing, also some have 2 front, 2 back etc. so we dont know"*
3. *"is there any way we can classify the images in a easy way"*
4. (friend) *"doesnt additional pictures add more value to the model? kann doch die bilder einfach als zusätzlichen input nehmen"*

**Shape of interaction:** I oversold the structured-slot approach
("Flavor B: photo-type-aware via slot ordering"). User identified the
data structure problem. Then I overcorrected and proposed a CLIP
classifier. Then the **friend's input cut through both complications**:
*"just feed all images, the model figures out per-image relevance."*

**What I got wrong:** I anchored on "we don't have structured data → we
need to structure it" twice in a row. The right answer was simpler — the
VLM already does cross-image attention, no preprocessing needed.

**Lesson:** when I propose ascending-complexity solutions to a
seemingly-hard problem, often the right answer is to challenge the
problem's premise.

---

### Phase 5 — Data audit
**Opening prompt:** *"Okay we have the pictures but not locally they are on a google drive as a zip"* → *"/Users/leonschmidt/Projekte/Vinted/vinted-lister/data this is the structure"*

**Shape of interaction:** I ran the bash audit, found photo type tags,
got excited and proclaimed the data was "in much better shape than we
thought." User immediately pushed back:

> *"did this really work how do we know that?"*

That was a sharp engineering question I hadn't asked myself. Forced me
to investigate the scraper code, find the CLIP zero-shot logic, and
admit we hadn't actually verified the labels were correct.

**Mid-task interrupt:** *"because I think I ran most scraping without clip"*

User was partially right — one of the 5 scrapes (825 listings) didn't
use CLIP. The other 4 (6,898 listings) did. We resolved the discrepancy
by re-running the audit grouped per-scrape.

**Lesson:** I claim things from one piece of evidence too readily.
*"Photos are tagged"* ≠ *"Photos are tagged correctly."* The right move
was to verify the classification logic, not assume it.

---

### Phase 6 — Plan creation
**Opening prompt:** *"can you write a full plan for checking the classification and than building the data for the fine tuning phase?"*

**Shape of interaction:** I drafted a 5-phase plan in chat. User asked
for it as a .md file. I asked 4 clarifying questions; user answered
inline:

> *"dedicated 24gb pod, its not public for the drive access, reclassify with clip, not in scope my mate does this"*

Saved as `docs/multi_image_finetuning_plan.md`. Committed and pushed.

**What worked:** asking the 4 clarifying questions before writing the
.md file caught important constraints (private Drive, dedicated pod)
that would have made parts of the plan wrong.

---

### Phase 7 — Catching up on team progress
**Opening prompt:** *"okay can you pull the newest repo? and tell me what the changes are"*

**Shape of interaction:** straight reporting. 5 incoming commits from
Michael, including:
- **The multi-image retrain plan I'd written had been executed** — adapter shipped to HF Hub as `mchlkan/qwen3vl4b-resell-adapter-multi-v1`, brand +20pp / size +19pp
- Model #6 (Groq description generator) shipped
- KA parse fix root-caused but not yet executed

**Notable observation:** the plan I wrote in Phase 6 was actually
executed by Michael overnight, with results matching the predicted
direction. The collaboration loop (plan → execute → report) closed
cleanly across human + AI.

---

### Phase 8 — KA parse fix decision
**Opening prompt:** *"okay what do we need to do to fix the KA parse rate fix?"*

**Shape of interaction:** I gave the documented fix steps. User
pushed back:

> *"but we just trained model 1 again, wasnt this implemented there?"*

Sharp question. I had to actually verify the current code rather than
trusting the doc. Confirmed: the multi-image retrain did NOT include the
parse fix. Both target builders (`train_vlm.py:104` and the duplicate
in `build_manifest.py:197`) still emit `description` and `price_eur`.

**Decision:** *"no retrain we dont have time anymore so we go with option A"*

I confirmed Option A still allows posting on both platforms (parse
recovery + Model #6 + Model #4 means /publish gets clean fields
regardless of malformed VLM JSON).

**Lesson:** the doc's "implementation status" can lag the code. Always
verify against current files, not against the planning doc.

---

### Phase 9 — Demo strategy doc
**Opening prompt:** *"Okay so our full focus now will be on vinted as our model 1 is better optimized for vinted correct?... Can you somehow make a .md file where we keep our thoughts so I can discuss with the team in the end?"*

**Shape of interaction:** synthesizing prior discussion. Wrote
`docs/demo_strategy.md` with:
- 3 pitch-line candidates to vote on
- Metric story (headline numbers + GPT-4o-mini comparison)
- 8 open questions for team debate
- Risk + mitigation table for demo day

---

### Phase 10 — Frontend status + critical critique
**Opening prompts:**
1. *"okay what about the frontend do we have some changes in a specific branch?"*
2. *"okay but whats the status on the frontend and can you be critical if what we build is a chatgpt wrapper?"*

**Shape of interaction:** investigation + honest critique.

Found `origin/frontend_development` with 3 commits (publishing flow,
design upgrade). Identified the branch is stale (branched before
multi-image retrain). Discovered an architectural shift: new `/draft`
endpoint, draft-first UX ("user reviews and publishes themselves").

For the wrapper critique, I gave a structured "where you are NOT a
wrapper / where you ARE wrapper-y" breakdown. Conceded that Model #6
(description) is genuinely a wrapper component, and that the most
user-visible polish is API-derived. Strongest defensibility claim:
the price head (49% MAPE vs 4o-mini's 102%).

**Lesson on this kind of question:** when asked to be critical, be
critical. The user explicitly asked for honest critique and the
response would have been less useful if I'd softened it.

---

## Interaction patterns observed

### What worked
- **User pushed back on weak claims.** *"Did this really work how do we
  know?"* → *"But we just retrained model 1 again."* Each pushback
  caught something I'd glossed over.
- **User redirected scope quickly.** *"Not focus on MAPE..."* and
  *"no retrain we don't have time"* prevented me from investing in
  options the budget didn't support.
- **User asked for written artifacts at decision points.** Plan →
  .md, demo strategy → .md, session → .md. Forces alignment to be
  explicit and durable.
- **User integrated outside input.** Friend's "just feed multi-image"
  cut through two layers of complication I'd added.
- **Open-ended brainstorming first, narrow down later.** "What can we
  do to improve the model?" produced a long option list; subsequent
  prompts narrowed to specific paths.

### What required course correction
- **My over-engineering tendency.** Twice (slot-aware multi-image,
  CLIP classifier) I proposed structured solutions when the simpler
  unstructured one was right.
- **My one-shot-claim tendency.** I proclaimed the data was clean
  before verifying the CLIP classifications were accurate.
- **Trusting docs over code.** The KA parse fix was documented as
  planned; the user assumed it had been implemented in the multi-image
  retrain. I had to verify against actual code, not the doc.

### Patterns the user used effectively
1. **Concrete grounding:** *"/Users/leonschmidt/.../data this is the
   structure"* — gave me a path to inspect rather than a description.
2. **Constraint-first answers:** *"dedicated 24gb pod, not public, reclassify, out of scope"* — answered all 4 clarifying questions in
   one line.
3. **Time-budget framing:** *"we don't have time anymore"* — turned
   open-ended choice into a forced-rank decision.
4. **Permission to be honest:** *"can you be critical"* — explicit
   permission produces better critique than implicit politeness.

---

## Open items for the team meeting

(Cross-reference `docs/demo_strategy.md` for full list.)

1. Vote on pitch line (3 candidates)
2. Live publish on stage vs pre-published demo material
3. Groq disclosure — admit it or hide it?
4. GPT-4o-mini comparison framing — lead with price (we win) or skip
   identification (untested)?
5. Run head-to-head identification benchmark vs 4o-mini? (~2 hrs work,
   eliminates a class of demo-day questions)
6. Rebase `frontend_development` onto current main + verify against
   multi-image VLM
7. Demo-day infrastructure: dedicated 24 GB RunPod pod, refreshed
   DataDome cookie, refreshed KA token

---

## Files referenced or modified during this session

```
Modified / written:
  docs/multi_image_finetuning_plan.md      (NEW, committed)
  docs/demo_strategy.md                    (NEW, uncommitted)
  docs/session_log_2026-05-10.md           (NEW, this file)

Read but not modified:
  docs/model_stack_evolution.md            (488 lines, Michael's authoritative state doc)
  docs/api.md                              (existing API reference)
  models/train_vlm.py                      (verified target builder still has description)
  scripts/build_manifest.py                (verified duplicate target builder)
  shared/prompts.py                        (verified inference prompt unchanged)
  backend/description.py                   (Model #6 implementation, Groq Llama 3.1 8B)
  src/multi_image_dataset.py               (Michael's dataset class)
  frontend/src/components/PublishingScreen.tsx
  frontend/src/api/publish.ts

External codebase consulted:
  /Users/leonschmidt/Projekte/Vinted/vinted-lister/src/scrape_dataset.py
  /Users/leonschmidt/Projekte/Vinted/vinted-lister/data/raw/clothing_*/items.jsonl
```

---

## One-line summary

A planning session that brainstormed ML improvements, scoped a
multi-image training plan (which the team executed overnight to a
+20pp brand / +19pp size lift), discovered Michael's parallel work
on Model #6, decided to ship the demo with parse-recovery instead
of another retrain, and locked in Vinted-first demo strategy with
a critical look at the wrapper question.
