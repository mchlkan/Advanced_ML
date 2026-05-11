# VLM cost model

_Last updated: 2026-05-11._

Per-scan cost of the vision-language step (Qwen3-VL-4B + LoRA on RunPod
Serverless), token accounting, the GPU-cost mapping, a comparison against the
hosted-API alternatives (GPT-4o, GPT-4o-mini, Claude Haiku 4.5), and the
optimization backlog. Numbers are estimates with the assumptions stated; the
formulas at the end let you recompute when rates or image sizes change.

> **TL;DR** — at the per-call level all four options are within ~2× of each
> other (≈ 0.2–0.8 ¢ / scan), so raw cost is **not** the deciding factor. What
> actually differs: (1) **cold-start / idle overhead** — the APIs have none,
> self-host has a lot at low volume; (2) the **fine-tune** — we own a
> task-tuned model, the APIs are generic and can't be cheaply fine-tuned;
> (3) the **pooled hidden state** the price/sell/flaw heads consume — only
> self-host produces it; (4) **latency** — APIs ~1–4 s, ours ~7–12 s warm;
> (5) **ops burden**. Recommendation: §6.

---

## 1. What gets billed

This is a **self-hosted** model on RunPod Serverless — the unit of cost is
**GPU-seconds**, not tokens. Tokens matter only because they set the latency
(prefill is ~linear in prompt length; decode is ~linear in output length),
which sets the GPU-seconds, which sets the bill. So the chain is:

```
image px → vision tokens → prompt length → prefill GPU-s
                                         ↘ + decode GPU-s → $ = GPU-s × $/s
```

Two structural facts about the current pipeline:

- **Each `/upload` fans out to two RunPod invocations** — one with the Vinted
  prompt, one with the Kleinanzeigen prompt (`runpod/README.md`,
  `backend/routes/upload.py`). The image is encoded twice and the prompt
  prefilled twice. So per-upload cost ≈ 2× the per-invocation cost.
- **Per invocation, the handler now does one forward pass** — `generate(...,
  output_hidden_states=True, return_dict_in_generate=True)`: the prefill step's
  last-token hidden state feeds the price/sell heads, and the same pass decodes
  the JSON (`runpod/handler.py`). Before 2026-05-11 it did *two* prefills (a
  standalone `output_hidden_states` forward, then a separate `generate`) — see
  §5.1.

The backend downscales every image to **max 1024 px on the long side, JPEG
q85** before sending (`backend/vlm_backend/util.py` `resize_and_b64`,
`max_image_dim=1024` in `runpod_http.py`). That cap — not the model — is what
keeps vision-token counts in the ~1 K range.

---

## 2. Token accounting per scan — the actual numbers

### Vision tokens (exact — deterministic from the image dimensions)

Qwen-VL's processor `smart_resize`s each image so both sides are multiples of
**28 px** (a 14 px patch × a 2×2 merge), bounded by min/max-pixel limits, then
emits **one token per 28×28 region** → `tokens = (h/28) × (w/28)`. The backend
first downscales to **max 1024 px on the long side** (`resize_and_b64`), so the
count is fully determined:

| input photo | after 1024 px cap + smart_resize | vision tokens |
|---|---|---|
| **4:3 / 3:4 phone photo** (e.g. 4032×3024) — **the common case** | 1036×756 | **999** |
| square crop (e.g. 3000×3000) | 980×980 | 1,225 |
| 16:9 (e.g. 4096×2304) | 1036×588 | 777 |
| already-small (≤ ~900 px, e.g. 800×600) | 812×588 | 609 |
| a tight care-label crop (e.g. 1200×900, ~4:3) | 1036×756 | 999 |

So: **~1,000 vision tokens per photo** for a normal phone shot; a square crop
is the worst case at ~1,225.

### Text tokens (measured with the Qwen tokenizer)

| component | tokens | note |
|---|---|---|
| `get_prompt("vinted")` | **143** | the fixed 6-field JSON-spec prompt (507 chars) |
| `get_prompt("kleinanzeigen")` | **144** | same, German-platform category vocab (541 chars) |
| chat-template scaffolding | **~20** | default system line (`You are a helpful assistant.`) + `<\|im_start\|>`/`user`/`assistant` turn headers + `<\|vision_start\|>`/`<\|vision_end\|>` delimiters; +2 for a 2nd image |
| `hints` (optional, on `/verify`) | ~10–30 | only when the user re-analyzes with corrections |
| generated output | **~46–50** typical; ~50–70 with a long brand/title | the 6-field JSON (+1 EOS); hard cap `MAX_NEW_TOKENS=256`, but greedy stops at EOS so the cap essentially never binds |

### Per request (one platform invocation)

| | input tokens | output tokens | request total |
|---|---|---|---|
| **1 photo** | 999 + 143 + 20 ≈ **~1,160** | ~50 | **≈ 1,210** |
| **2 photos** (item + label) | 999 + 999 + 144 + 22 ≈ **~2,165** | ~50 | **≈ 2,215** |

(`/upload` issues two of these — Vinted + Kleinanzeigen — so per **upload**:
**~2,320 in / ~100 out (≈ 2,420 total) for 1 photo**, **~4,330 in / ~100 out
(≈ 4,430 total) for 2 photos**. Adding the second photo ≈ doubles the upload's
prompt-token volume — the label image is added to *both* platform calls and the
text prompt is tiny next to the images.)

### Compute (the thing that costs GPU-seconds)

Prefill dominates; one prefill of ~1,160–2,165 tokens >> ~50 decode steps.
After the prefill fusion (§5.1) each invocation prefills **once**:

| per `/upload` | prefill+decode token-equivalents | vs. before the fusion (2 prefills/call) |
|---|---|---|
| 1 photo | 2 × (~1,160 + ~50) ≈ **~2,420** | 2 × (~2,320 + ~50) ≈ ~4,740 |
| 2 photos | 2 × (~2,165 + ~50) ≈ **~4,430** | 2 × (~4,330 + ~50) ≈ ~8,760 |

> **Ground truth going forward:** the handler now logs `[infer] platform=… 
> prompt_tokens=… new_tokens=…` per request and returns `prompt_tokens` /
> `output_tokens` in its response (`runpod/handler.py`), so the real per-request
> counts are visible in the RunPod worker logs once the new image is deployed —
> use those to replace the estimates above if they drift.

---

## 3. GPU cost per scan

RunPod Serverless **flex** (per-second, scale-to-zero) pricing, approximate —
**verify current rates at runpod.io/pricing**:

| GPU | $/s (flex) | $/hr |
|---|---|---|
| RTX 4090 (24 GB) — current | ~$0.00031 | ~$1.12 |
| RTX A4000 (16 GB) — fits the 4B model, ~half the price | ~$0.00016 | ~$0.58 |

Measured warm latency before the 2026-05-11 changes: **~12.3 s per `/upload`**
(`docs/demo_strategy.md`). The prefill-fusion + bf16 changes (§5.1–5.2) should
take that to **~7–9 s** on the 4090 (needs re-measurement). A 2-photo upload
adds ~40–70 % (more vision patches + ~80 % more prefill; fixed decode/overhead)
→ ~+50 %.

| path | warm latency | GPU $ / scan | per 10,000 scans |
|---|---|---|---|
| **Ours — 4090, pre-2026-05-11** | ~12 s | ~$0.0037 | ~$37 |
| **Ours — 4090, after prefill-fusion + bf16** | ~7–9 s (est.) | ~$0.0022–0.0028 | ~$22–28 |
| **Ours — A4000, after the same changes** | ~10–14 s (est.) | ~$0.0016–0.0022 | ~$16–22 |
| **Ours — 2-photo (4090, after changes)** | ~11–14 s (est.) | ~$0.0033–0.0042 | ~$33–42 |

…**plus** the cost structure in §4, which dominates at low volume.

---

## 4. The cost that actually bites: cold starts & idle

The per-scan numbers above are the *warm marginal* cost. The real bill at our
volume is dominated by:

- **Cold starts.** Idle timeout is 600 s; after that the worker shuts down. A
  cold start *with* FlashBoot is ~10–30 s of **paid** GPU before it serves
  anything; a fresh boot (no snapshot) is minutes. If traffic is sparse
  (< ~1 scan / 10 min) almost every scan eats a cold start → effective cost per
  scan jumps to ~1–3 ¢+, well above the ~0.2 ¢ warm figure.
- **`min_workers ≥ 1`** (recommended during demo windows for zero cold starts)
  = a 4090 billed **24/7 ≈ ~$27/day ≈ ~$800/mo**, regardless of volume. Purely
  on per-scan savings vs. the ~$0.003/scan API option, that only pays for
  itself at **hundreds of thousands of scans/month**. So `min_workers=1` is
  justified by *latency* (demo day), not by cost — flip it back to `0` after.

The hosted APIs have **zero** cold-start and **zero** idle cost — true
pay-per-call, free scale-to-zero. That's their decisive structural advantage
while volume is low and bursty (i.e. now).

---

## 5. Optimization backlog

### Done (2026-05-11)

**5.1 Fuse the two prefills.** The handler used to run a standalone
`output_hidden_states` forward *and then* `generate()`, which re-prefilled the
same ~1.2–2.2 K-token prompt (§2) from scratch. Replaced with a single
`generate(..., output_hidden_states=True, return_dict_in_generate=True)` and
read the prefill last-token hidden state from `gen.hidden_states[0][-1][0,-1,:]`.
Prefill dwarfs the ~50 decode steps, so dropping one prefill is **≈ −30–45 %
GPU-seconds per invocation**. No infra change, no retrain. (`runpod/handler.py`)

**5.2 bf16 instead of bnb 4-bit.** The 4B model is ~8 GB in bf16 — fits a
24 GB (or 16 GB) GPU with room for the KV cache. bitsandbytes nf4 is *slower*
than bf16 (dequant-to-bf16 on every matmul) **and** slightly less accurate.
Switched `from_pretrained` to `torch_dtype=torch.bfloat16`, dropped the
`BitsAndBytesConfig` and the `bitsandbytes` dependency. Faster + better
predictions, no downside on this GPU. (`runpod/handler.py`,
`runpod/requirements.txt`) — **rebuild + push the image** for both to take
effect (`docker buildx build … --push`; one cold boot on the new image).

Combined, 5.1 + 5.2 ≈ a **~2–2.5× speedup** (≈ −50–60 % GPU-$ / scan) with no
model retraining and no accuracy risk.

### Cheap, needs a quick A/B

**5.3 Smaller, asymmetric image caps.** Vision tokens scale with pixels, and
images are ~80 % of the prompt. Dropping the *item* photo from 1024 px to
**768 px (~570 tokens)** is ≈ −35 % prefill compute; keep the *care-label*
photo at 1024–1280 px (reading a size tag needs the pixels). One constant in
`resize_and_b64` / a per-image branch, plus a 10-minute accuracy check on the
eval set for brand/category/color/condition.

**5.4 Cache by image hash.** Same image uploaded twice (retries, double-taps)
→ return the cached result. Cheap; happens in practice.

### Bigger — needs a retrain

**5.5 One prompt for both platforms.** `/upload` currently fans out to two
invocations (Vinted prompt, KA prompt); the fields overlap ~90 % (brand, color,
size, condition are identical — only the category vocab and title style
differ). One prompt asking for both platforms' fields → one image encode, one
prefill, ~2× the output tokens → cuts a `/upload` from ~2 invocations to ~1
≈ **−45–50 %**. Catch: the brief mandates inference prompt == training prompt,
so the LoRA adapter needs a retrain on the combined target (~few GPU-hours,
~$3), and the price/sell heads would get one pooled state instead of two
(probably fine; possibly a head retrain). Stacks on top of §5.1–5.2.

### The big unlock — a research call, not a quick task

**5.6 Drop the VLM hidden-state extraction → serve under vLLM.** The only
reason every call uses raw HF `generate()` (no continuous batching, no
PagedAttention, no CUDA graphs) is that the price/sell heads need the VLM's
pooled hidden state, which vLLM/SGLang/TGI don't expose. There's *also* a
frozen DINOv2 tower feeding the price head — if DINOv2 features alone are
"good enough" for price (a price-MAE comparison would tell you), the VLM could
be cut down to *just generate the JSON* and run under vLLM → realistically
**2–5× throughput** on the same GPU. Gated on a model-quality study; only worth
it if §5.1–5.5 aren't enough.

### Infra knobs (anytime)

- **Switch the endpoint GPU to A4000 16 GB** — fits, ~half the $/s, ~1.5–2×
  slower per call. One dropdown.
- **Shorter idle timeout** if usage is bursty-then-quiet — ends the
  paid-but-idle window sooner, at the cost of more cold starts. Tune to the
  real session shape.

---

## 6. Self-host vs. hosted API

### Cost comparison

API rates below are approximate as of writing — **verify current pricing**.
Image-token counts: OpenAI tiles to 512 px tiles → `gpt-4o` at `detail:high` ≈
85 + 170/tile ≈ **~765 tokens** for a ~1024×768 photo (4 tiles); **`gpt-4o-mini`
bills images at ~30–33× that token count** (a documented quirk — so its image
cost is *comparable to or higher than* 4o despite the cheap text rate);
Anthropic counts ≈ (w×h)/750 ≈ **~1,050 tokens**. An API version would
naturally be **one call** returning both platforms' fields (you control the
prompt — no train/infer-parity constraint), modelled here at ~400 text-input +
the image(s) + ~150 output (6 fields × 2 platforms + a price estimate, since
the API can't give you the price head's calibrated output).

| | input / output rate (per 1M) | $ / scan, 1 photo | $ / scan, 2 photos | per 10,000 scans (1-photo) | cold-start / idle |
|---|---|---|---|---|---|
| **Ours — Qwen3-VL-4B, 4090, today** | (GPU-seconds) | ~$0.0022–0.0028 | ~$0.0033–0.0042 | ~$22–28 | **High** — cold starts at low volume; ~$800/mo if kept warm |
| **Ours — after §5.1–5.2, on A4000** | (GPU-seconds) | ~$0.0016–0.0022 | ~$0.0025–0.0035 | ~$16–22 | same |
| **GPT-4o** | $2.50 / $10 | ~$0.0044 | ~$0.0063 | ~$44 | **None** |
| **GPT-4o-mini** | $0.15 / $0.60 | ~$0.0040 | ~$0.0078 | ~$40 | **None** — image-heavy ⇒ *not* the cheap option; barely beats 4o |
| **Claude Haiku 4.5** | ~$1 / ~$5 | ~$0.0022 | ~$0.0033 | ~$22 | **None** — cheapest per-scan here (sane image-token count + modest rates); Claude 3.5 Haiku (`$0.80`/`$4`) is a touch cheaper still |

(All three APIs support prompt caching — a small win for our tiny prompt, a
bigger one if you build a richer few-shot prompt and cache the static part.)

Per scan, everyone is within ~2×. The self-hosted numbers *understate* the
real cost because they exclude idle/cold GPU; the API numbers are all-in.
**Below ~5–10 K scans/month, an API is cheaper all-in.**

### The non-cost axes

- **Accuracy / the fine-tune.** Our Qwen adapter is trained on resale-clothing
  field extraction (multi-image fine-tune: brand +20 pp, size +19 pp). On
  *this narrow task* a fine-tuned 4B can match or beat GPT-4o zero-shot and
  clearly beats 4o-mini / Haiku zero-shot. None of the three APIs can be
  cheaply fine-tuned for vision (4o-mini vision FT is limited/expensive; Haiku
  FT effectively doesn't exist). The fine-tune is the moat — "switch to the
  API" = "give up the accuracy you already built".
- **The pooled hidden state.** The price/sell/flaw heads are trained on the
  VLM's hidden state. No API exposes that. API-only ⇒ either ask the LLM to
  guess a price (no calibration from real sales data — worse) or move price
  entirely to DINOv2 + sales data (a real project).
- **Latency.** APIs ~1–4 s, no cold-start tail. Ours ~7–12 s warm, minutes
  cold. APIs win the user-facing latency story today.
- **Ops & dependency.** Self-host = we own the image, the handler, the
  cold-start runbook, GPU cost monitoring, version pins — but no third-party
  dependency, no surprise deprecations, photos stay on infra we control. API =
  one HTTP call, their problem — but their rate limits, their deprecations
  (gpt-4o *will* sunset; re-validate on the successor), their data policy.

### Recommendation — phased, not binary

1. **Now / low, bursty volume:** an API is the right default — cheapest all-in
   (no idle GPU), lowest latency, near-zero ops. **Claude Haiku 4.5 or
   GPT-4o-mini** for the field extraction; GPT-4o only if the smaller models
   miss too often on brands/logos. Keep DINOv2 for price.
2. **At steady volume / once accuracy or pricing-calibration is core:** the
   self-hosted fine-tuned model earns its keep — better task accuracy, the
   hidden-state-driven pricing, a latency floor we control, no third-party
   dependency, and (after §5.1–5.2 + A4000) the cheapest per-scan of anything
   here.
3. **Pragmatic hybrid:** self-hosted model primary, API (Haiku / 4o-mini) as
   the **fallback when the RunPod worker is cold** — kills the cold-start
   latency spike without paying for an always-warm GPU. Best of both for the
   demo and early launch.

---

## 7. How to recompute

**Vision tokens for an image** — exact: downscale so the long side ≤ 1024 px,
round each side to the nearest multiple of 28, then `tokens = (h/28) × (w/28)`
(bounded by the processor's min/max-pixel limits). See the table in §2; rough
shortcut ≈ `round(downscaled_w × downscaled_h / 784)`.

**Self-hosted $ per scan** ≈ `warm_latency_s × $_per_s × calls_per_scan`. Today
`calls_per_scan = 2` (the platform fan-out); `$_per_s` from the table in §3;
`warm_latency_s` should be **re-measured** from `UploadResponse.latency_ms`
after the §5.1–5.2 image rebuild. A 2-photo upload ≈ ×1.5.

**API $ per scan** ≈
`((image_tokens + text_in_tokens) × input_rate + out_tokens × output_rate)`
with `image_tokens` per the per-provider rule in §6, `text_in ≈ 400`,
`out ≈ 150`, rates per the §6 table. Subtract the cached fraction × (1 −
cache-read discount) if you use prompt caching on a static prompt prefix.

**Break-even for an always-warm 4090** (`min_workers=1`, ~$800/mo) vs. a
~$0.003/scan API, on per-scan savings alone: `$800 / ($0.003 − $0.002) ≈
800 K scans/month`. I.e. don't keep a worker warm for cost reasons — only for
demo-day latency.
