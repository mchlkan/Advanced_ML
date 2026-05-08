# Review Prompts

LLM-as-judge prompts for stress-testing the project before final presentation. Used independently against the business plan, the tech brief, and the working prototype.

## Naming convention

- `prof_NN_*.md` — verbatim from the professor's pre-review email. **Course-provided.**
- `extra_NN_*.md` — written by Claude (during Day 3 prep) to plug gaps in the professor's set, based on the rubric described in that same email.

## What the dual-review system grades

Per the professor's email, two parallel reviews:

**Human judges:** business logic, market fit, technical execution, presentation quality.

**LLM-as-Judge:** focuses especially on
- Whether the project solves a real problem
- Whether the AI component is genuinely necessary
- Whether the unit economics are plausible
- Whether the technical solution is deployable
- Whether the system has a meaningful moat beyond being a simple wrapper

Excellence benchmark named in the email: Anthropic's *Built with Opus* hackathon winners — projects starting from a concrete domain problem, using AI as the core engine of value, and shipping a working product rather than only a concept.

## How to use

1. Pick a prompt that targets the dimension you want to stress-test.
2. Paste it into Claude / GPT / Gemini.
3. Attach the relevant artifacts: `resell_copilot_tech_brief_v2.md`, the business plan from Pair B, screenshots of the working prototype, the spike verdict from `notebooks/99_spike.ipynb`.
4. Note the verdict in `docs/genai_log/` (per the GenAI Transparency Logs requirement).
5. Run **prompt 6 last** — it is the panel-grading simulation.

## Index

### Professor's set (course-provided)

| # | File | Focus |
|---|------|-------|
| 1 | `prof_01_business_model.md` | Target market, pain, value prop, GTM, revenue, commercial feasibility |
| 2 | `prof_02_technical_architecture.md` | Feasibility, FE/BE wiring, AI necessity, deployability, docs |
| 3 | `prof_03_unit_economics.md` | Token costs, hosting, pricing model, gross margin, scale economics |
| 4 | `prof_04_defensibility_wrapper.md` | Moat vs wrapper risk, switching costs, replicability by big AI labs |
| 5 | `prof_05_safety_risk.md` | Hallucination, privacy, leakage, bias, misuse, transparency |
| 6 | `prof_06_final_presentation.md` | Panel simulation across all four grading axes — run this last |

### Extras (Claude-drafted, gap-filling)

| # | File | Why it exists |
|---|------|---------------|
| 7 | `extra_07_problem_solution_fit.md` | Forces "is this a real friction or did we invent it?" — the email emphasizes "identify a real friction" but no professor prompt isolates this from the business model |
| 8 | `extra_08_ai_necessity.md` | Sharper than the wrapper prompt: for each AI component, what's the non-AI baseline and what's actually lost? Targets the email's "AI genuinely necessary" criterion directly |
| 9 | `extra_09_demo_robustness.md` | The email cites *Built with Opus* winners shipping a working product. This prompt audits the demo flow specifically — failure modes, fallback screencast, edge inputs, sub-10s legibility |
