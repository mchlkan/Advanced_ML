# 09 — Live Demo Robustness Audit

**Source:** Original — drafted by Claude to plug a gap in the professor's set
**Focus:** Will the live demo survive a 5-minute slot in front of investors with no manual rescue?

## Why this prompt exists

The professor's email holds up the *Built with Opus* hackathon winners as the bar — projects that "deliver a working product rather than only a concept." That is a demo-execution claim. Prompts 2 and 6 touch on prototype quality, but neither audits demo failure modes specifically. Brief §11 also says "demo crashes live" is one of the top three ways the team can lose the 20. This prompt is the dedicated check.

## Prompt

> You are a hackathon judge who has watched ~500 startup demos go wrong on stage. You can predict in the first 30 seconds which demos will fail. Evaluate the following AI startup prototype for **demo readiness only**, not for product quality or business viability.
>
> Audit:
>
> 1. **Happy path.** Does the end-to-end golden flow work without any manual intervention, hardcoded inputs, or "let me just refresh"? List every step the presenter must perform live.
>
> 2. **Failure modes.** What are the most likely things to break during a live 5-minute demo on shared conference Wi-Fi? Rank by probability and impact:
>    - Network timeout to model API
>    - Model refusal / safety filter triggering on user image
>    - Model OOM on a larger image than the demo set
>    - Edge-case input the team forgot to test (multi-item photo, blurry, screenshot, non-clothing)
>    - Cold-start latency on the first call
>    - GPU instance being reclaimed mid-demo
>    - Browser caching showing a stale state
>    - Authentication/session timeout on a hosted backend
>
> 3. **Fallback.** Is there a pre-recorded screencast of the full happy path that can be played if the live demo dies? Is the screencast actually in sync with the latest UI?
>
> 4. **Sub-10-second legibility.** A non-technical investor watches the first 10 seconds. Can they tell what the product *does* without reading documentation or hearing the presenter explain? Yes / partial / no.
>
> 5. **Hostile inputs.** Which user input patterns are most likely to break the system, and have they been tested? Specifically: empty upload, oversized upload (10MB+), wrong-format file, non-clothing image, image of someone wearing the item (vs flat-lay), screenshot of an existing listing.
>
> 6. **Demo data hygiene.** Is the demo using cherry-picked hero items, randomly sampled items, or live user uploads? Each has a different failure profile — name which.
>
> Conclude with: "Top three changes the team must make in the next 48 hours to reduce demo risk."

## When to use

Day 5 of the week (per brief §8 — screencast is recorded that day). Run twice: once before recording the screencast (informs which 5–8 hero items to curate), once before demo day (catches regressions introduced during polish).
