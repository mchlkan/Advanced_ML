# Demo Strategy — Pre-Pitch Team Discussion

Internal alignment doc. Not the final pitch deck — captures the framing,
trade-offs, and open questions so the team can disagree before the demo locks.

---

## TL;DR

**Lead with Vinted. Keep Kleinanzeigen as the "platform-extensibility proof."**
Don't try to close the Vinted/KA gap in the remaining time — lean into the
asymmetry as deliberate scope.

Pitch line candidates:
- "Photo-first cross-listing assistant for second-hand clothing — upload once,
  list everywhere."
- "Domain-specialized VLM that reads brand and size directly from care labels.
  Beats GPT-4o-mini 2× on price prediction."
- "Production-grade marketplace integration + a fine-tuned model on real
  Vinted data."

---

## Why Vinted is the natural primary

1. **Multi-image retrain was Vinted-only.** The KA scrape didn't capture
   multi-photo data, so the +20pp brand / +19pp size lift only applies to
   Vinted-shaped inputs. Re-doing this on KA would need a fresh scrape
   and another retrain — out of scope.
2. **Cleaner downstream metrics.** Vinted hits 96.5% clean parse rate; KA hits
   40.9% (clean) / 100% (post-recovery, the more honest number).
3. **Better integration polish.** Vinted publishing tested live multiple
   times (e.g. listing 8859515451). KA tested live once (3403101406) and is
   more brittle — refresh-token-only onboarding, two-tier auth, JAXB-XML body.
4. **Audience familiarity.** Nova SBE professor and most students know Vinted.
   KA reads as a German-specific niche to non-German evaluators.

## Why KA stays in (don't drop it)

1. Demonstrates the architecture **generalizes**. Single-platform demo looks
   like a Vinted clone; two-platform demo looks like a unification layer.
2. The KA integration is **technically the harder one** (mobile-only API,
   captured via mitmproxy on a rooted Android, JAXB-XML serialization,
   two-tier auth). Shipping it at all is a real achievement worth one slide.
3. Future work has somewhere credible to go — gives the project a roadmap
   slide that doesn't feel like hand-waving.

---

## Demo narrative (proposed)

1. **Hero flow** — upload a Vinted-style photo (garment + label).
   - Show structured extraction (brand, size, condition, color, category)
   - Show price quantile band (q10 / q50 / q90) + sell-likelihood
   - Show generated draft listing (description by Model #6 / Groq)
   - Confirm → publish → real listing appears live on Vinted (open in browser tab)

2. **Cross-list flow** — same listing, click "also post to Kleinanzeigen"
   - Show the platform-mapping layer: German category, KA's condition vocab,
     location code
   - Demonstrates the unification layer is real, not theoretical
   - (Decision: do we actually publish to KA live, or just show the prepared
     payload? Live KA carries refresh-token risk.)

3. **Active feedback** — edit a field on the result page, hit /verify,
   show downstream fields update (price quantile shifts when condition changes).
   Logs a learning signal for the active-learning slide.

4. **Honest framing** — "We focused on Vinted because that's where our
   multi-photo training data lives. The architecture is platform-agnostic —
   adding more platforms (Depop, Mercari, Whatnot) is a data + integration
   step, not a model step."

---

## Metric story (what to put on the slide)

### Headline numbers — Vinted, 368-row test slice

| Metric | Number | Comparison |
|---|---|---|
| Brand exact-match | **69.3%** | +20.1 pp vs single-image baseline |
| Size exact-match | **45.9%** | +19.0 pp vs single-image baseline |
| Category | 99.7% | near-perfect |
| Color | 74.7% | strong |
| Parse OK (clean) | 97.8% | near-perfect |
| Latency warm | 12.3 s | acceptable for upload flow |

### Price head — Vinted + KA combined, 500-row test slice

| Metric | Our Price Head | GPT-4o-mini | Improvement |
|---|---|---|---|
| MAPE | **49.2%** | 102.5% | **2.1× better** |
| MAE | **€14.63** | €21.50 | 32% lower |
| RMSLE | **0.513** | 0.707 | 27% lower |
| Coverage q10–q90 | 83.4% | n/a | calibrated |

### Effective parse rate framing (skip the clean number)

| | Vinted | Kleinanzeigen |
|---|---|---|
| Hard failures (user-visible) | **0%** | **0%** |
| Clean parse | 96.5% | 40.9% |
| Recovered parse | 3.5% | 59.1% |

Pitch this as **"100% of listings return an editable draft"** — the user-visible
reality. The clean-vs-recovered split is technical detail the audience doesn't
need.

---

## Why we beat GPT-4o-mini (and where we don't)

| Where we win | Where we tie | Where we lose |
|---|---|---|
| Price prediction (2× MAPE) | Description quality (we use Groq Llama 3.1 8B for prose, like a wrapper would, but anchored to OUR extracted fields) | Per-call cost at our volume (~2× more) |
| Brand recognition on long-tail / German marketplace brands | | Arbitrary-task generalization (4o-mini knows luxury bags + electronics; we don't) |
| Size extraction from care labels (label-photo input) | | Cold-start latency (we have RunPod cold-start; 4o-mini doesn't) |
| Domain-specific marketplace tone in descriptions | | |

**The "not a wrapper" defensibility line:**
> "A wrapper around 4o-mini uses the API for the *hard* part (identification,
> price, condition). We use the API for the *easy* part (writing prose).
> The hard parts — fine-tuned on real Vinted data, multi-image care-label
> extraction, calibrated price quantiles, real platform integrations — are
> ours and don't exist outside this project."

---

## What's deliberately not in scope (don't apologize, just state it)

- **KA multi-image training** — KA scrape lacks photo metadata
- **8B base model upgrade** — would invalidate the LoRA, no retrain budget
- **KA parse-rate retrain** (drop description from training target) —
  recovery handles 100% of failures already, retrain is cosmetic
- **More platforms beyond Vinted + KA** — architecture supports it,
  integration work not done
- **Cost-per-request below GPT-4o-mini** — economic break-even needs 1000+
  uploads/day; not realistic for course volume
- **Mobile app / browser extension / native uploads** — web demo only
- **Active learning loop in production** — `/verify` edits already log
  learning signals; closing the loop (periodic re-train on user edits)
  is documented future work
- **fp16 deployment** — could improve quality ~5%, not done; demo runs
  4-bit on serverless

---

## Open questions for team discussion

1. **Live demo or pre-recorded video?**
   Live is more impressive, but: cold-start risk (60-180s on serverless),
   live API failure risk, DataDome challenges. Recommend hybrid — pre-record
   the riskier KA flow, do live Vinted upload + extract.

2. **Publish to Vinted live during demo?**
   Real listing appears in browser → high-impact. But account ban risk if
   we post too many test items. Recommend: pre-publish one fresh listing
   that morning, show it in browser as if just-posted. (Less risk, same
   visual outcome.)

3. **Publish to KA live during demo?**
   Refresh-token expiration risk; KA is more sensitive. Recommend: show
   the prepared payload + mapping, don't actually call the API.

4. **Mention Groq / Llama 3.1 8B for descriptions?**
   It's a third-party API. Honest framing: "we use a generic LLM for prose
   because it's commodity; we own the parts that matter." Or hide it as
   implementation detail. **Recommend: be honest** — the framing is good,
   it's the architectural argument.

5. **GPT-4o-mini comparison in the deck?**
   Strongest data point, but invites "why not just use 4o-mini?"
   Recommend: include but lead with **price prediction** comparison
   (where we win 2×), not raw cost (where we lose at our volume).

6. **One-sentence pitch — vote among:**
   - (a) "Photo-first cross-listing assistant for second-hand clothing —
     upload once, list everywhere."
   - (b) "Domain-specialized VLM trained on real marketplace data, with
     calibrated price prediction beating GPT-4o-mini 2×."
   - (c) "Production-grade marketplace integration powered by a fine-tuned
     vision-language model."

7. **Sell-likelihood — how much to feature?**
   Test AUC is 0.605 — directional, not strong. Recommend: include as
   "directional signal" with a confidence caveat, not as a headline metric.
   It's defensible but not impressive.

8. **Scope of "extensibility" claim?**
   We say "platforms" plural, but we've only really done two. Recommend:
   stop at "two platforms shipped + architecture supports more"; don't
   list platforms we haven't actually integrated.

---

## Risks for the demo day itself

| Risk | Mitigation |
|---|---|
| RunPod cold start during live demo | Spin up dedicated 24 GB pod 1 hr before; warm with a dummy upload right before going on stage |
| Vinted DataDome challenge mid-demo | Refresh DataDome cookie an hour before; keep one pre-published listing as backup demo material |
| KA refresh token expired | Refresh that morning; manual fallback is "open KA's new-listing page in browser" |
| VLM produces a bad listing on stage | Pre-vet 5 hand-picked demo photos that produce known-good output; use only those |
| Groq API down / rate-limited | Model #6 has template fallback — description degrades but pipeline doesn't break |
| Internet flaky in demo room | Pre-record a full demo run as video; can switch to that if needed |
| Question: "why not just use GPT-4o-mini?" | Have the price-comparison table memorized; pivot to "we beat it 2× on the metric that matters and own the data" |

---

## What to bring to the demo

- Pitch deck (final)
- 5 hand-picked demo photos (vetted that morning)
- One pre-published Vinted listing URL (backup, in case live fails)
- Backup demo video (~3 min)
- Laptop on charger, phone hotspot if room WiFi is bad
- This doc + `docs/model_stack_evolution.md` + `docs/api.md` printed for
  professor's reference questions

---

## Action items before the team meeting

- [ ] Vote on the pitch line (Q6)
- [ ] Decide live KA publish vs prepared payload (Q3)
- [ ] Decide Groq disclosure framing (Q4)
- [ ] Decide GPT-4o-mini comparison framing (Q5)
- [ ] Vet the 5 demo photos as a team
- [ ] Pre-publish one Vinted listing as backup material
- [ ] Confirm dedicated RunPod pod is provisioned for demo day
- [ ] Run end-to-end demo dry-run against the pod (find cold-start issues
      before stage)

---

## Documents to read alongside this

- `docs/model_stack_evolution.md` — full model state, eval numbers, problems
  identified, improvements implemented
- `docs/api.md` — API surface (in case professor asks "is this real?")
- `docs/multi_image_finetuning_plan.md` — the plan that drove the +20pp
  brand / +19pp size lift
- `docs/project_memory_2026-05-09.md` — project memory snapshot
