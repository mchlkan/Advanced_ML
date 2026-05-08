# 08 — AI Necessity Audit (per-component non-AI baseline)

**Source:** Original — drafted by Claude to plug a gap in the professor's set
**Focus:** For each AI component, what's the simplest non-AI alternative, and what's actually lost by removing it?

## Why this prompt exists

The professor's email lists "whether the AI component is genuinely necessary" as a top LLM-judge concern. Prompt 2 (technical architecture) checks this superficially and prompt 4 (wrapper) checks it from a moat angle. Neither forces a per-component audit. Without that, "AI is necessary" is asserted, not proven. This prompt makes the case that has to survive a CTO's scrutiny.

## Prompt

> You are a pragmatic CTO with 15 years of experience and a deep skepticism of AI for AI's sake. You have shut down two products that turned out to be AI when they should have been a SQL query.
>
> Evaluate the AI components of the following startup. For **each AI component** in the system (each model, each LLM call, each embedding, each generative step):
>
> 1. State what the component does and what it produces.
> 2. Propose the simplest non-AI alternative: a deterministic rule, a lookup table, a regex, a small dataset + classical ML, a manual workflow, or a pre-computed catalog.
> 3. Estimate what fraction of the user-visible value would be retained by the non-AI alternative (0–100%).
> 4. List the specific capability that **only** the AI version provides.
> 5. Judge: does that residual AI-only capability justify the operational cost of using AI — latency, hallucination risk, GPU/API spend, vendor lock-in, model upkeep, regression risk, evaluation complexity?
>
> Flag any AI component that scores below 70% irreplaceable — those are decorative AI, not load-bearing AI.
>
> Conclude with: "AI necessity rating: X/Y components are load-bearing." Anything below 50% load-bearing means the project is described as an AI startup but is actually a SaaS product with AI sprinkled in.

## When to use

Run this on the architecture in `resell_copilot_tech_brief_v2.md` §3. For Resell Copilot specifically, the answer must defend: Model #1 (VLM extraction — clearly AI-load-bearing), Model #2 (DINOv2 flaw head — could be a small CNN; defend), Model #4 (quantile price head — could be gradient boosting; defend), Model #5 (sell-likelihood — same), and the description-variant generation (LLM cosmetic layer — possibly decorative; flag honestly).
