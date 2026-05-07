# 07 — Problem-Solution Fit Audit

**Source:** Original — drafted by Claude to plug a gap in the professor's set
**Focus:** Is the user pain a real friction, or did we invent it?

## Why this prompt exists

The professor's email says the AI judge will check "whether your project solves a real problem" and praises projects that "identify a real friction." Prompt 1 (business model) and prompt 4 (wrapper) circle this question but never isolate it. This prompt does — it forces an evidence-based audit of the pain itself, separate from any commercial framing.

## Prompt

> You are a UX researcher and a domain expert in second-hand fashion resale. Evaluate whether the following AI startup is solving a real friction that target users actually feel today, or a hypothetical problem the founders imagined.
>
> For each claimed user pain point in the project's pitch:
> 1. Estimate how often this pain is encountered by a typical target user (per week, per month).
> 2. Describe the workaround users currently rely on, and how painful that workaround actually is on a 1–10 scale.
> 3. Identify whether the pain claim is supported by **evidence** (interview quotes, marketplace complaint data, app-store reviews, churn analytics, observed seller behavior) or whether it is **assumed** by the founders.
> 4. Flag any pain that looks invented to justify the AI capability rather than discovered from users.
>
> Then propose the three most informative customer-discovery questions the team should answer before launch — questions that would *change the product* depending on the answer, not questions whose answers only confirm the existing plan.
>
> Be skeptical. Founders frequently mistake "this would be cool" for "users want this."

## When to use

Before final presentation, especially if Pair B's plan leans heavily on assumed pain points. Use the output to either (a) cite real evidence in the deck, or (b) downgrade pain claims to "hypothesized — to validate post-launch."
