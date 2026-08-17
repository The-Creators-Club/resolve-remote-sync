# Local (non-Claude) b-roll indexing: what exists, what it costs, what we measured

*Written 2026-08-17. Research + a small measured prototype; no indexer code was
changed. Companion to `indexing-api.md` (the Anthropic path as it ships) and
`docs/INDEXERS.md` (what runs where). This reconsiders one line of
`docs/ZERO_TOUCH_PLAN.md` §8 — "the GPU indexers stay a vendor/pro-services
thing on a GPU box (item 14)" — for the b-roll `claude` stage only. Resolve's
own IntelliSearch storage is being investigated separately and is out of scope
here.*

## The question, and the short answer

The customer objection: *indexing with Claude is too expensive for other
studios.* Can the per-clip vision+text step — contact sheets in, the
`index_clip_v6.md` JSON out (themes, `category_hint`, `quality_flags`, and
per-segment `description` / `objects` / `setting` / `motion` /
`onscreen_text` / `onscreen_text_en`) — run on local models at acceptable
quality, at what hardware/time cost, and what would the pipeline change be?

**Verdict, in one paragraph.** Yes for *speed and cost*, not yet for *quality
as-is*. A 4B-parameter open VLM (Qwen3-VL-4B-Instruct, Apache-2.0) ran the
indexer's own prompt on the archive's own contact sheets on this base rig's
RTX 3080 in **10–16 s per clip** through llama.cpp — roughly **5–7x faster
than the measured 69 s/call Claude latency** and at zero marginal cost — and
returned contract-valid JSON on 3 of 4 clips without any schema constraint. But
the *content* was noticeably weaker than the Haiku baseline on the same
sheets: one clip came back with zero segments, one merged nine visibly
different shots into a single 0–59 s segment, on-screen Chinese was
mis-transcribed, and one clip fell into a repetition loop that ran to the token
limit. Two of those four failures have known engineering fixes (feed
individual frames rather than 384x216 sheet cells — llama.cpp warned about it
in so many words; constrain the decode with the contract as a JSON schema and
cap segments); the third (weak segmentation / hallucinated OCR) is model
capacity and improves with the 8B model or a 24 GB card. The recommendation is
therefore a **tiered backend — `local` by default, `anthropic` optional per
site** — shipped after a real eval on ~100 clips against the existing Haiku
index, not after four. Details, numbers and the plan follow.

## 0. What the `claude` stage actually asks for today (recap, from the code)

Read `broll/indexer/broll_index/pipeline.py::stage_claude` and
`claude_client.py`; this is what any replacement must reproduce.

- **Input.** For each clip the `frames` stage extracts scene-cut frames (plus
  filler so no gap exceeds `sampling.max_gap_s`, default 4 s) from the 540p
  proxy and tiles them **9 per 3x3 contact sheet at 1152x648** (each cell
  384x216 with the absolute `HH:MM:SS` burned in). Sheets are capped per clip
  (`sampling.max_sheets_per_video`, 24 on the base rig) and windowed
  `frames_per_call/9` sheets per call (36 → 4 sheets; the base rig runs 108 →
  12 sheets). Measured on the real archive: **1.27 calls/clip** (8,996 calls
  for 7,107 clips in `E:\broll-queue\usage.jsonl`), 43,382 sheets in total —
  ~6 sheets/clip.
- **Prompt.** `prompts/index_clip_v6.md` (~3k tokens): "describe what is
  visible, don't narrate", one segment per distinct shot with absolute
  timecodes, terse noun-list descriptions, `objects` with synonyms/hypernyms
  (this is what search matches), canonical labels for newsreader / title card /
  black frame, verbatim CJK on-screen text + English rendering, clip-level
  `themes`, `category_hint` from the site's taxonomy (40 slugs on this
  archive), `quality_flags` from a fixed 6-word vocabulary. **STRICT JSON only.**
- **Contract.** `claude_client.parse_claude_response` → `validate_contract`:
  strips code fences, tolerates trailing junk (`_first_json_object`), requires
  the four top-level keys and six per-segment keys, drops unknown quality
  flags rather than failing. `call_claude_with_retry` gives one retry on
  invalid JSON, then the clip is `error`. `merge_index_results` unions
  themes/flags across windows and concatenates segments.
- **The seam.** `InvokeFn = Callable[[prompt: str, model: str], str]`; the real
  one is `invoke_claude(prompt, model, *, images, settings, client)` returning
  a JSON *envelope* string (`_build_envelope`: text + usage + duration).
  `stage_claude` binds images/settings with `functools.partial` when
  `invoke is invoke_claude`. Every test injects a fake `InvokeFn`. **This is
  exactly where a local backend plugs in** — see §3.
- **Downstream, unchanged by any of this.** `stage_transcribe` (faster-whisper,
  already local, `CCSYNC_WHISPER_*`, `tools/make_whisper_env.ps1`),
  `stage_embed` (fastembed ONNX,
  `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384-d, text
  only, over `_segment_search_text` = description+objects+setting+onscreen
  text and over transcript cues), plus jieba/OpenCC keyword normalisation. All
  CPU, all already local, all licence-clean.
- **Cost as measured.** `usage.jsonl` for the archive to date: 8,996 Haiku
  calls, 445.6M input tokens (mostly cached prompt) + 59.1M output tokens,
  **USD 642.55 recorded**, i.e. **~USD 0.09 per clip** on Haiku (via the old
  CLI's cost field), average **69 s per call** wall time. `indexing-api.md`'s
  forward estimate at API prices: a 1152x648 sheet bills ~1k tokens, so a
  12-sheet call is ~15k in / 0.5–2k out → **~USD 0.02–0.03 per call on Haiku,
  ~USD 0.07–0.10 on Sonnet** (the new-install default). For a 5,000-clip
  archive at 1.3 calls/clip: **Haiku ≈ USD 130–200, Sonnet ≈ USD 450–650**,
  plus 5,000 × 1.3 × 69 s ≈ **125 h serial** (÷ workers). The wall-clock, not
  the dollars, is what actually hurt on the base rig
  (`E:\broll-queue\USAGE_TIMING.md`).

## 1. The market, concretely

### 1.1 Open vision-language models on one consumer GPU

Base rig hardware, for reference: **NVIDIA GeForce RTX 3080, 10 GB VRAM**,
driver 595.79 / CUDA 13.2, Intel Core Ultra 7 270K Plus (24 threads), 127 GB
RAM. Note the 3080 is a *10 GB* card — most "single-GPU" guidance assumes
12–24 GB, and Resolve alone held 9.3 GB of it while open (measured; the
prototype could not touch the GPU until Resolve was closed). A customer base
rig running Resolve and an indexer at the same time needs a 16–24 GB card or
a second machine.

Licence column is the thing our gate cares about (`tools/check_licenses.py`
judges shipped artefacts; a model we *download at install time* is not a pip
package and is not seen by it — see §3.3). "Permissive" = Apache-2.0/MIT.

| Model | Params | VRAM fp16 / 4-bit | Licence | Runtimes | JSON / instruction following | Notes for our task |
|---|---|---|---|---|---|---|
| **Qwen3-VL-2B/4B/8B-Instruct** (Alibaba, Oct 2025) | 2B / 4B / 8B | 4B: ~8.8 GB bf16 (**12.8 GB peak measured** on our prompt in transformers) / **2.5 GB Q4_K_M** + 0.9 GB F16 mmproj; 8B: ~16 GB / ~6 GB | **Apache-2.0** ([HF: Qwen3-VL-4B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF)) | transformers ≥ 4.57, **official GGUFs** for llama.cpp/Ollama/LM Studio, vLLM, SGLang, MLX | Good; strict-JSON prompt obeyed 3/4 in our test with no grammar; 4B OCRBench ~85, 8B 89.6, DocVQA 91 vs 96.1 ([codersera](https://codersera.com/blog/qwen3-vl-4b-vs-qwen3-vl-8b-benchmarks-vram-guide/)) | **The first choice.** Native dynamic resolution, multilingual incl. CJK OCR, 8B is the quality tier for a 16–24 GB card |
| Qwen2.5-VL-3B / 7B-Instruct | 3.75B / 8.3B | 3B: ~8 GB / ~3 GB; 7B: ~16 GB / ~6 GB | **3B: Qwen RESEARCH LICENSE — "NON-COMMERCIAL PURPOSES ONLY"** ([LICENSE](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct/raw/main/LICENSE)); 7B: Apache-2.0 | transformers, GGUF (`qwen2.5vl:3b/7b` in Ollama), vLLM | Good; DocVQA 95.7 (7B) | **The 3B named in this task is not shippable to a customer.** Superseded by Qwen3-VL anyway |
| Florence-2 base / large (Microsoft) | 0.23B / 0.77B | ~0.5 / ~1.5 GB | MIT | transformers (custom code); no GGUF | **None** — task-token model (`<MORE_DETAILED_CAPTION>`, `<OD>`, `<OCR_WITH_REGION>`), no free-form prompt | Cheap and fast, but our JSON would have to be *assembled in code* from caption+detections+OCR per cell; no segmentation reasoning, no synonyms, no taxonomy pick. A component, not a backend |
| Moondream2 (2025-06 rev) | 1.9B | ~4 GB / ~1–2 GB | Apache-2.0 | transformers (custom), Moondream Station | Weak on long structured JSON; good short captions/point/detect | Edge-grade; fine for a CPU-only "something is better than nothing" tier |
| Moondream 3 preview | 9B MoE (2B active) | ~19 GB loaded | **Business Source License 1.1** + use grant ([HF](https://huggingface.co/moondream/moondream3-preview)) | transformers | Better | Non-permissive; needs 24 GB. Skip |
| SmolVLM2 256M / 500M / 2.2B (HF) | ≤2.2B | 2.2B: ~4.5 / ~2 GB | Apache-2.0 | transformers, llama.cpp | Basic; captioning/VQA grade | Below the bar for a shot list with OCR |
| InternVL3 / 3.5 small (1B–8B, OpenGVLab) | 1–8B | 8B ~16 / ~6 GB | Repo MIT; weights inherit Qwen2.5 LLM licence per checkpoint (verify each) | transformers, lmdeploy, some GGUF | Good | Comparable to Qwen2.5-VL of the same size; less runtime support |
| LLaVA-OneVision 0.5B / 7B | 0.5B / 7B | 7B ~16 / ~5 GB | Apache-2.0 | transformers, llama.cpp | OK | Older; outclassed by Qwen3-VL |
| PaliGemma 2 3B / 10B | 3B / 10B | 3B ~6 GB | **Gemma Terms of Use** (source-available, revocable) | transformers | Fine-tune-first model, weak zero-shot instruction following | Skip |
| MiniCPM-V 2.6 / 4.5 (OpenBMB) | 8B / 8.7B | ~16 / ~5–6 GB | Code Apache-2.0; **weights under "MiniCPM Model License"** (commercial use requires registration) | transformers, llama.cpp/Ollama | Good, strong OCR/video | Licence paperwork; not permissive |
| Gemma 3 4B / 12B (vision) | 4B / 12B | 4B ~8 / ~2.6 GB (QAT); 12B ~24 / ~6.6 GB | **Gemma Terms of Use** (Gemma 1–3) — *not* Apache, despite some 2026 roundups listing it so | Ollama, llama.cpp, transformers, vLLM | Good | Skip on licence. **Gemma 4** (Apr 2026: E2B/E4B/12B/26B-A4B/31B) **is Apache-2.0** ([Google Open Source Blog](https://opensource.googleblog.com/2026/03/gemma-4-expanding-the-gemmaverse-with-apache-20.html)) and is the credible second candidate — E4B/12B untested here |
| Phi-3.5-vision 4.2B / Phi-4-multimodal 5.6B | 4–6B | ~9–11 GB / ~3–4 GB | MIT | transformers, vLLM; patchy GGUF | Decent | English-centric; CJK OCR weaker than Qwen |
| Pixtral 12B | 12B | ~24 / ~7 GB | Apache-2.0 | vLLM, llama.cpp/Ollama | Good | Needs 16 GB+; no small sibling |

Throughput ballpark from the 2026 roundups (Q4 decode, tokens/s):
Qwen3-VL-8B **100–140 on a 4090, 80–120 on a 3090, 40–60 on an M4 Pro, 8–15
CPU-only** ([InsiderLLM](https://insiderllm.com/guides/vision-models-locally/));
image encoding adds 2–5 s first-token latency. **Our own measurement**
(§2): Qwen3-VL-4B Q4_K_M on the RTX 3080 decodes at **140 tok/s**, prompt
processing 290–700 tok/s (the mmproj image encode dominates), **10–16 s per
clip** for 1–3 sheets and 300–1,200 output tokens.

What a 3B–8B VLM gets wrong versus Claude on *this* task, from the literature
and confirmed in the prototype: (a) **under-segmentation** — averaging a sheet
into one segment, exactly the failure v6's prompt spends a paragraph on;
(b) **OCR of small CJK** — 384x216 cells are far below what these models were
tuned on (llama.cpp warns *"Qwen-VL models require at minimum 1024 image
tokens to function correctly"* — our sheets went in at only ~225–515 tokens each, judging by the prompt-token deltas between the 1-, 2- and 3-sheet calls, i.e. a few dozen tokens per 384x216 cell);
(c) **repetition loops** on long structured output; (d) hallucinated or
generic `objects`, weak counting; (e) taxonomy adherence is fine when the list
is in the prompt (both runs picked a valid slug or `general/unsorted`), but
`themes` came back empty twice. Hallucination benchmarks put Qwen3-VL-235B at
HallusionBench 66.7 ([Qwen3-VL technical report](https://arxiv.org/pdf/2511.21631));
the 4B/8B are well below that and Claude Haiku/Sonnet above it. None of this
is fatal — v6's own hard rules exist because *Haiku* invented emergency
vehicles — but the small models need the frames bigger and the decode
constrained.

### 1.2 Embeddings for search — and the "no captions" path

Today: text-only, `fastembed` ONNX, MiniLM-L12 multilingual 384-d over caption
text and transcripts (`embed.py`), brute-force numpy scan in the web app.
Nothing visual is embedded, so a clip is only findable through what the VLM
*wrote*. A joint image–text space would let a query find footage the caption
missed, and would keep search working on a machine that never ran a VLM at
all.

| Model | Type | Params | Licence | Runtime | Fit |
|---|---|---|---|---|---|
| **SigLIP 2** (Google, Feb 2025; base/large/so400m; NaFlex variants) | image↔text, **multilingual** | 86M–1B | **Apache-2.0** ([HF](https://huggingface.co/google/siglip2-so400m-patch16-naflex), [blog](https://huggingface.co/blog/siglip2)) | transformers, ONNX export, open_clip | **Best fit**: multilingual text tower (CJK queries), strong retrieval, so400m fits any GPU; NaFlex takes non-square frames |
| Perception Encoder (Meta, PE-Core B/L/G) | image/video↔text | 90M–2B | Apache-2.0 ([repo](https://github.com/facebookresearch/perception_models)) | transformers/own | Beats SigLIP2 on fine-grained retrieval; **video-finetuned** (frame sets); English-first text tower |
| CLIP ViT-L/14 (OpenAI) / OpenCLIP | image↔text | 428M | MIT | open_clip, ONNX | Baseline; English text tower; weaker than the two above |
| InternVideo2 / ViCLIP | **video**↔text | 1B–6B | MIT ([HF](https://huggingface.co/OpenGVLab/InternVideo2-Stage2_6B)) | own code | True clip-level embeddings from 8 frames; heavy, research-grade packaging; the 6B needs 24 GB |
| nomic-embed-vision v1.5 (+ nomic-embed-text v1.5) | image↔text shared space | ~90M + 137M | Apache-2.0 ([HF](https://huggingface.co/nomic-ai/nomic-embed-vision-v1.5)) | transformers, ONNX (fastembed has the text side) | Neat: the *text* model already covers our caption/transcript embedding job; English-centric |
| jina-clip-v2 | image↔text, 89 languages | 0.9B | **CC-BY-NC-4.0** ([HF](https://huggingface.co/jinaai/jina-clip-v2)) | transformers | Non-commercial. Skip |
| bge-m3 / multilingual-e5 / nomic-embed-text | text only | 0.1–0.6B | MIT / MIT / Apache-2.0 | fastembed/ONNX (all three are in fastembed's list) | Drop-in upgrades to MiniLM for the *text* half; not visual |

Design that follows: keep the existing text embedding table for caption and
transcript text (a `bge-m3` swap is a config change, `embedding.model`, and
`stage_embed` already re-embeds on a model change), and **add a second
`embeddings.source = 'frame'` row family from SigLIP 2** — one vector per
extracted frame (the `frames` stage already has them on disk), query text
through the same model's text tower at search time. The web app's
`search.py` brute-force dot product handles a second family the same way it
handles two today; the container-side cost is one more small ONNX text tower
(SigLIP2-base text is ~110M params, in the same class as the 18 ms/query rule
in `INDEXERS.md`). That is what makes "search works even without captions"
true, and it is independent of which VLM writes the captions.

### 1.3 Local ASR

Already local and licence-clean: `faster-whisper==1.1.1` / `ctranslate2==4.5.0`
(MIT/MIT), model `large-v3-turbo` (MIT weights, ~1.6 GB), sidecar venv from
`broll/indexer/tools/make_whisper_env.ps1|.sh`, `tools/whisper_transcribe.py`
as the subprocess boundary. Nothing to change. Alternatives if the sidecar
ever has to go: **whisper.cpp** (MIT; GGUF Whisper; CPU/Metal/CUDA; ships in
the same llama.cpp binary family) — attractive on a Mac base rig; and
Ollama does *not* serve Whisper, so ASR stays a separate process either way.

### 1.4 Ollama vs a Python `transformers` env as the customer-facing runtime

| | Ollama (or bare llama.cpp `llama-server`) | Python + transformers/vLLM |
|---|---|---|
| Install | one signed installer per OS (Windows/macOS/Linux), user-level, ~1 GB; models pulled by name into `~/.ollama` | a venv per machine with a CUDA torch wheel (2.5+ GB) matched to the driver; a Mac needs MPS/MLX; PyInstaller cannot freeze it sanely |
| GPU coverage | CUDA, ROCm, **Metal**, Vulkan; **automatic CPU/GPU split** when the model does not fit; CPU-only works (slowly) | CUDA first-class; MPS partial; CPU = "the machine is unusable for 20 minutes" (measured 22 threads at 100 % and 19 GB RSS for one clip on this rig — do not do this on a customer's workstation) |
| Model format | GGUF, quantised; Qwen3-VL/Gemma 4 official | safetensors bf16; needs 2x the VRAM of Q4; **Qwen3-VL-4B did not fit the 10 GB 3080** (12.8 GB peak → spilled to shared memory at 0.76 tok/s) |
| Structured output | `format: <json-schema>` (Ollama ≥ 0.5) / `response_format: json_schema` and `--grammar` (llama-server) — grammar-constrained decode ([Ollama docs](https://docs.ollama.com/capabilities/structured-outputs), [llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)) | outlines/xgrammar in vLLM; nothing built into transformers `generate` |
| API | HTTP, OpenAI-compatible `/v1/chat/completions` with data-URL images — the client is 40 lines of urllib | in-process; batching is where vLLM wins (10x throughput on a 24 GB card) |
| Ops | one service, one log, `ollama ps`; version pin = one binary version | pip resolution, CUDA/cuDNN DLL wiring (the reason the whisper env is a *separate* venv today) |
| Licence | MIT (Ollama), MIT (llama.cpp) | Apache/BSD stack, fine |
| Downsides | image encode is single-request serial in llama-server (no continuous batching for mmproj); Ollama's vision support lags llama.cpp by weeks for new architectures (Qwen 3.6 vision "unsupported in Ollama" as of the 2026 roundup); Ollama binds `*` CORS by default — same lesson as our loopback guard, bind 127.0.0.1 and set an API key | best raw throughput per GPU-hour if someone owns the ops |

For a *customer's* base rig the answer is llama.cpp-family: **`llama-server`
driven by the indexer** (we control the exact build, `-ngl`, `--image-min-tokens`,
port, no CORS) rather than a user-installed Ollama, with "point me at an
existing Ollama/OpenAI-compatible URL" as the escape hatch since the wire
format is identical. That also answers **Apple Silicon**: the same GGUFs run
on Metal (M-series 16–32 GB unified memory runs the 8B at 40–60 tok/s per the
InsiderLLM figures; MLX-VLM is the faster native alternative), so a Mac base
rig is a real option for a small studio for the first time — today's whisper
sidecar and CLAP already run there, and the platform envelope
(`docs/ARCHITECTURE.md` §12) does not need to grow a new OS.

### 1.5 Cost model, 5,000-clip archive (~1.3 calls/clip, ~6 sheets/clip)

| Path | Money | Wall clock | Quality (today) |
|---|---|---|---|
| Claude Haiku (API) | ~USD 130–200 | ~125 h serial at 69 s/call; ÷ `--workers` up to the org rate limit | the archive baseline; good, with the v6 guard-rails |
| Claude Sonnet (API, new-install default) | ~USD 450–650 | same shape | better segmentation and OCR than Haiku |
| **Local, Qwen3-VL-4B Q4 on the RTX 3080 (measured)** | 0 marginal; ~0.3 kWh/1,000 clips (negligible) | 5,000 × 1.3 × ~13 s ≈ **23 h serial**, no rate limit; ~10 h with 2 slots | below Haiku as run here (§2); fixable-to-close-with-eval |
| Local, Qwen3-VL-8B Q4 on a 3090/4090/24 GB M-series | 0 marginal | ~2x the 4B time on the same card, ~1x on a 4090 | expected near-Haiku on description/objects, still weaker on tiny CJK text |
| Cloud GPU rental (RunPod community 4090 ≈ USD 0.34/h, Vast spot ≈ 0.17–0.59/h ([RunPod](https://www.runpod.io/gpu-models/rtx-4090), [getdeploying](https://getdeploying.com/gpus/nvidia-rtx-4090))) | 8B on a 4090 ≈ 6–8 h ≈ **USD 2–5** | hours, plus the archive's *sheets* have to be uploaded (~43k × 100 KB ≈ 4 GB — fine) | as above; keeps the customer's footage off-site only as stills |
| Hybrid: local first pass, Claude only for clips flagged weak (empty segments, no OCR on a chyron-heavy share, low frame-embedding agreement) | a fraction of the API bill | dominated by the local pass | the pragmatic best |

Electricity is genuinely a rounding error (a 320 W card for 23 h ≈ 7 kWh).
The GPU itself is the cost: a used 3090 (24 GB) is the sensible floor for a
customer who wants the 8B tier; a 12 GB 3060/4070 runs the 4B tier.

## 2. The prototype (this machine, 2026-08-17 22:40–23:10)

Setup: scratch venv at
`%TEMP%\claude\E--Projects-resolve-remote-sync\c169e858-…\scratchpad\vlm\venv`
(torch 2.11.0+cu128, transformers 5.15.0, accelerate, pillow, qwen-vl-utils),
`HF_HOME=%LOCALAPPDATA%\ccsync\hf-cache`. Model chosen: **Qwen3-VL-4B-Instruct**
— *not* the Qwen2.5-VL-3B suggested, because that one's licence is
non-commercial (§1.1) and Qwen3-VL-4B is the same size, newer and Apache-2.0.
Two runtimes: transformers (bf16, `device_map=cuda`) and llama.cpp b10470
`llama-server` (CUDA 12.4 build, `Qwen3VL-4B-Instruct-Q4_K_M.gguf` +
`mmproj-…-F16.gguf`, `-ngl 99`, `-c 16384`). Same four archive clips, the same
sheets the archive was indexed with (`E:\broll-queue\sheets\<id>`), the
**unmodified** `build_index_prompt` and `parse_claude_response` imported from
`broll_index.claude_client`, taxonomy read from `broll.db` read-only. Baseline:
Haiku's stored segments for those clips (`claude_baseline.json`). Scripts and
raw outputs are kept in **`broll/docs/prototypes/local-vlm/`** (small, and
they are the seed of a `local_client.py`).

Clips: 8724 (17 s, referendum crowd, 1 sheet), 13454 (58 s, hard-hat worker
walking through a nursery, 2 sheets), 2555 (62 s, 商業周刊 recycling news
piece with chyrons, 3 sheets), 5495 (88 s, police evidence presentation, 3
sheets). Sheets capped at 3 per clip for time.

**Measured:**

| Runtime | Device | Load | Clip | Sheets | Prompt tok | Out tok | Wall | Contract-valid |
|---|---|---|---|---|---|---|---|---|
| transformers bf16 | RTX 3080 (Resolve closed, 9.0 GB free) | 4.6 s | 8724 | 1 | 3,652 | 234 | **310 s**, 0.76 tok/s, **12.8 GB peak** → spilled to shared system memory | yes |
| transformers fp32 | CPU, 22 threads (before the GPU was free — killed by the operator, rightly; 19 GB RSS, all cores pegged) | 2 s | 8724 | 1 | 3,652 | 234 | 125 s | yes |
| **llama.cpp Q4_K_M** | RTX 3080 | 50–64 s (incl. mmproj) | 8724 | 1 | 3,652 | 314 | **16 s** (pp 274 tok/s, tg 144 tok/s) | yes |
| llama.cpp Q4_K_M | RTX 3080 | | 13454 | 2 | 3,877 | 33 | **12 s** | yes — but **zero segments** |
| llama.cpp Q4_K_M | RTX 3080 | | 2555 | 3 | 4,392 | 415 | **10 s** (pp 693 tok/s) | yes |
| llama.cpp Q4_K_M | RTX 3080 | | 5495 | 3 | 4,392 | 1,200 (cap) | 11 s | **no** — repetition loop, unterminated string at the token cap |
| llama.cpp Q4_K_M + `response_format: json_schema` (the contract as a schema) | RTX 3080 | | 13454 / 5495 | 2 / 3 | | 33 / 1,200 | 14 s / 15 s | code fences gone; **content identical** — the grammar cannot stop a loop, only shape it |

Note the prompt-processing rate climbing 274 → 693 → 2,173 tok/s across
calls: llama-server's prompt cache reuses the shared 3k-token prefix, so a
long run pays the text prompt once; the per-call cost is the image encode
(~4–13 s for 1–3 sheets on this card) plus decode at 140 tok/s.

**Quality, honestly, clip by clip** (raw JSON in
`results_llamacpp_cuda.json`, Haiku in `claude_baseline.json`):

- **8724 (crowd, 1 sheet).** Local: three segments — two "back view of crowd,
  people wearing white shirts with Chinese characters, dim lighting" and a
  "green screen, no content" for the empty ninth cell. Haiku: "indoor
  gathering, multiple people in light-coloured clothing viewed from behind,
  banners in blurred background" + a "black frame" at 16 s. **Comparable.**
  Both missed that the shirts read 同意 (a referendum "agree" slogan — the one
  searchable fact in the shot); the local model was arguably *more* literal
  about the padding cell. `themes` empty, category `general/unsorted` (Haiku:
  `general/public-life`).
- **13454 (worker in a nursery, 2 sheets).** Local: **`segments: []`** — a
  total miss on 18 cells of clearly visible content, twice (with and without
  the schema). Haiku: six segments, though its first two ("urban apartment
  complex, person *running*, striped balconies") are also wrong for what is a
  shade-house and a walking man; its later segments (grassy field, hard hat,
  vehicles, mountains, overexposed frames, steering wheel) are right. **Local
  fails, Haiku is mediocre.** Flat log-profile footage at 384x216 is hard for
  both.
- **2555 (news piece with chyrons, 3 sheets).** Local: **one** segment,
  0–59 s, "industrial waste sorting facility, workers, machinery, stacked
  recyclables, control room, magazine cover, green screen"; `objects`
  contaminated with `"onscreen_text"`, `"onscreen_text_en"` (it copied field
  names) and `"text on screen"`; `onscreen_text` = "商業周刊 |
  這兩年廢棄酒廠得幾天價錢 | 00:00:00 | 00:00:06 | …" — the channel name is
  right, the chyron is **hallucinated** (the frame reads 這兩年循環經濟喊得震天價響
  … 早已默默做了20年), and it transcribed the burned-in timecodes as on-screen
  text. Category `environment/waste-recycling` — **correct** (Haiku left it
  null). Haiku: **eight** segments with tight timecodes (factory floor 3–8,
  warehouse 8–18, excavator 20–25, control room 28–34, snowy kiosks 38–42,
  truck 44–48, control room 49–51, magazine cover 55–60), the closing title
  card's text read correctly (2月9日 | 商業周刊 | 歐洲回收王 …), but chyrons
  reduced to "[Chinese text overlay, statistics]" — Haiku *also* did not read
  them at this cell size. **Haiku clearly better on segmentation; neither read
  the chyrons.**
- **5495 (police evidence, 3 sheets).** Local: a plausible first segment
  ("officials in uniform at table with equipment, masked attendees, indoor
  setting, daylight", themes "police operation, press conference, Taiwan",
  category `general/public-life`) then the same segment repeated every 30 s
  out to 246 s on an 88 s clip until the token cap. Haiku: six distinct
  segments (uniformed personnel/vertical blinds, stacked items in a display
  case, portraits, close-ups, blurred detail, civilians), category
  `society/policing-crime`. **Local invalid; Haiku good.**

**Score on four clips: local ≈ 1 comparable, 1 partial (right category, wrong
segmentation, invented OCR), 2 failed (empty; loop). Haiku: 3 good, 1
mediocre.** That is a 4B model at Q4 with a few hundred image tokens per sheet, no
grammar tuned for the loop, no repeat penalty, one shot. It is not the ceiling
of local; it is where a naive drop-in lands, and it says the drop-in is not
acceptable *as-is*.

**Three findings that change the design more than the score does:**

1. **The sheets are the problem as much as the model.** llama.cpp printed
   *"Qwen-VL models require at minimum 1024 image tokens to function
   correctly … try adding --image-min-tokens 1024"*. Our 1152x648 sheets went
   in at ~225–515 tokens each under llama.cpp's default image sizing (the
   deltas between the 1-, 2- and 3-sheet prompts) — a few dozen tokens per
   384x216 cell. Claude copes; a 4B model does not. The `frames` stage already has every frame on
   disk at 960x540; a local backend should send **frames, not sheets** (or
   3-up strips at full cell width) with the timecode passed *in the text* rather
   than burned in and re-read. That alone attacks the empty-segments and the
   OCR failures, at the price of more image tokens per call (still local, still
   free — Qwen3-VL spends one token per 32x32 px, so ~500 tokens/frame at
   960x540 and ~9 frames/call ≈ 4.5k image tokens ≈ 8–15 s of encode on this
   card).
2. **Constrain the decode structurally, not just syntactically.** The schema
   grammar fixed the code fences but not the loop. The fix is
   `maxItems` on `segments` bound to the number of frames in the window, a
   `repeat_penalty`/`dry` sampler, and — because llama-server's grammar can
   express it — `t_start`/`t_end` as an **enum of the window's actual
   timecodes**, which also kills the "246 s on an 88 s clip" class of error.
3. **The 10 GB card is a 4B-Q4 card.** bf16 4B does not fit under a running
   Resolve or even alone with this prompt; Q4 fits with 5 GB to spare. Product
   guidance has to say "8 GB VRAM: 4B Q4, cells enlarged; 16–24 GB: 8B Q4/Q8;
   Mac 32 GB+: 8B; no GPU: search-only from a vendor-built index (INDEXERS.md
   stands)".

## 3. Recommendation: tiered, local by default, Claude per site

**Ship `[indexer] backend = local | anthropic`** (config.yaml `backend:` with
`BROLL_INDEX_BACKEND` override, same required-key discipline as every other
path key), default **`local`** in the vendor build so a new site never needs
an Anthropic key to get *an* index, with `anthropic` selectable per site for
studios that want the better first impression `indexing-api.md` describes —
and, once measured, a **`hybrid`** mode that runs local first and sends only
the flagged clips to Claude. Order of work:

1. **Eval before design (2–3 days, the gate for everything else).** Take
   ~100 clips stratified across shares (news with chyrons, log-profile
   b-roll, dashcam, interviews) that already have Haiku segments; run
   Qwen3-VL-4B-Q4 and 8B-Q4 with (a) sheets as-is, (b) frames at 960x540 with
   timecodes in text, (c) + grammar with `maxItems`/timecode enum. Score
   segment count vs Haiku, timecode overlap, `objects` recall against a
   hand-checked set of ~20, OCR exact-match on chyron clips, taxonomy hit
   rate, invalid-JSON rate. `broll/eval/` already has the harness shape
   (`run_eval.py`); the prototype scripts are the invocation. Decision rule
   agreed up front: 8B-with-frames within ~15 % of Haiku on segment/objects
   recall and ≤ 2 % invalid → ship `local` as default; otherwise ship it as an
   opt-in "no-key" tier and keep `anthropic` the default.
2. **The seam (≈ 3–4 days).** New `broll_index/local_client.py` implementing
   the same `InvokeFn` shape and returning the same envelope
   (`{"text": …, "usage": {...}, "duration_ms": …}`), so
   `call_claude_with_retry`, `parse_claude_response`, `merge_index_results`,
   `_log_usage` and every test double stay untouched. Inside it: start (or
   attach to) a `llama-server` — vendored binary + pinned GGUFs downloaded on
   first run into `embedding.cache_dir`'s sibling `models/` (BROLL_MODEL_CACHE
   already exists for exactly this), health-check, one HTTP call per window
   with data-URL images and `response_format: json_schema` built from
   `validate_contract`'s rules. `stage_claude` gains a
   `backend` switch where it currently does `real_call = invoke is
   invoke_claude` — a `build_invoke(cfg)` factory returning
   `(invoke, cost_model)`; the loop body does not change. Rename nothing yet
   (`stage_claude`, `usage.jsonl`, `videos.model`) — `model` becomes
   `local:qwen3-vl-4b-q4_k_m` in the DB, which is enough for `indexing-findings`
   style comparisons later. Windowing for the local path: frames not sheets,
   so `chunk_sheets`'s input is a list of frame paths and the prompt's
   `__SHEET_PATHS__` block becomes a frame/timecode list — a second template
   `index_clip_v6_frames.md`, not a fork of v6.
3. **Frame embeddings for search (≈ 3 days, independent, and worth doing
   even if `local` loses the eval).** SigLIP 2 base/so400m over the `frames`
   directory in the indexer (GPU or CPU, ~20 ms/frame on the 3080), a second
   `embeddings.source='frame'` family, the text tower exported to ONNX for the
   container's query path, `search.py` merges the two similarity lists. Adds
   ~400 MB to `BROLL_MODEL_CACHE` and one ONNX model to the container image.
4. **Packaging + docs (≈ 2 days).** `INDEXERS.md` grows a "local backend"
   section with the VRAM tiers above; `config.example.yaml` gains
   `backend:` and a `local:` block (`server_url` for BYO-Ollama, `model`,
   `image_min_tokens`, `frames_per_call`, `slots`); `Dockerfile.indexer-gpu`
   gets llama.cpp CUDA (or the container just talks to a host llama-server);
   the macOS story is the same GGUF on Metal. `THIRD_PARTY_NOTICES.md`
   hand-maintained block: Qwen3-VL weights (Apache-2.0), llama.cpp (MIT),
   SigLIP 2 (Apache-2.0), plus the existing Whisper (MIT) entry.

Total: roughly **two engineer-weeks** including the eval, with the eval as an
explicit go/no-go at the end of week one.

### 3.1 Which models to ship first

- **Tier A, "any NVIDIA/Apple GPU ≥ 8 GB": Qwen3-VL-4B-Instruct Q4_K_M** (2.5
  GB + 0.9 GB mmproj), frames not sheets, grammar on. What we measured.
- **Tier B, "16 GB+ VRAM or 32 GB Mac": Qwen3-VL-8B-Instruct Q4_K_M/Q8_0** (~6/9
  GB). Same code path, different pull; expected to close most of the gap.
- **Second family to keep in the eval: Gemma 4 E4B / 12B** (Apache-2.0 since
  Apr 2026, official Ollama/llama.cpp support) — a different training lineage
  hedges the "Qwen misreads Traditional Chinese chyrons" risk.
- **Not** Qwen2.5-VL-3B (non-commercial), Moondream 3 (BSL), Gemma 3 / PaliGemma
  2 (Gemma Terms), MiniCPM-V (registration licence), jina-clip-v2 (NC).
- Embeddings: **SigLIP 2** for frames; consider **bge-m3** to replace MiniLM
  for text (MIT, better CJK) as a config-only change.

### 3.2 Hardware guidance for a customer's base rig

| Base rig | Local tier | Expected pace (frames path, ~1.3 calls/clip) |
|---|---|---|
| No discrete GPU / < 8 GB | none — search-only over a vendor-built index (INDEXERS.md); or `anthropic` | — |
| 8–12 GB NVIDIA (3060 12 GB, 3080 10 GB, 4070) | 4B Q4 | ~15–25 s/clip → 5,000 clips ≈ 1–1.5 days unattended |
| 16–24 GB NVIDIA (4080/3090/4090/5090) | 8B Q4/Q8 | ~10–20 s/clip; 4090 ≈ 8–12 h for 5,000 |
| Apple Silicon 32 GB+ (M2 Pro and up) | 8B Q4 on Metal | roughly 2x the 3090's time |
| Any of the above while Resolve is open | assume the card is *not* available (Resolve took 9.3 of 10 GB here) — schedule indexing off-hours or on a second box |

### 3.3 What the licence gate needs

`tools/check_licenses.py` judges pip locks of the two shipped artefacts; a
local backend adds three things it does not see and one it does:

- **Model weights** (Qwen3-VL, SigLIP 2, Whisper) are downloaded at run time,
  not conveyed by us — same posture as the whisper and CLAP weights today —
  but they should be *inventoried* in `THIRD_PARTY_NOTICES.md`'s hand block
  with licence and URL, and the downloader should refuse a model id that is
  not on an allow-list (so a site cannot point `local.model` at a
  non-commercial GGUF and put us in the "we shipped it" argument).
- **llama.cpp binary** — MIT, vendored per platform like ffmpeg is today
  (`server/install_dashboard_app.py` precedent); the CUDA build redistributes
  NVIDIA's cudart/cublas DLLs under NVIDIA's redistribution terms — counsel
  note, same as the whisper sidecar's ctranslate2 CUDA wheels.
- The Python client is stdlib `urllib`; **no new pip dependency** in the
  indexer for Tier A/B. SigLIP 2 needs `onnxruntime` in the *container* (BSD;
  already present via fastembed) and `transformers`+`torch` only in the
  indexer venv (already there for CLAP).

## 4. Cleanup — what this left on the machine

Everything below is deletable; nothing in the repo depends on it.

| Path | Size | What |
|---|---|---|
| `C:\Users\alex\AppData\Local\Temp\claude\E--Projects-resolve-remote-sync\c169e858-154e-4947-bb34-621fa6225a72\scratchpad\vlm\venv` | 4.6 GB | scratch venv (torch cu128, transformers 5.15) |
| `…\scratchpad\vlm\llamacpp-cuda` | 1.7 GB | llama.cpp b10470 CUDA 12.4 build + cudart |
| `…\scratchpad\vlm\llamacpp` | 63 MB | llama.cpp b10470 CPU build (unused in the end) |
| `%LOCALAPPDATA%\ccsync\hf-cache` | **12 GB** | `hub/models--Qwen--Qwen3-VL-4B-Instruct` 8.3 GB (safetensors) + `models--Qwen--Qwen3-VL-4B-Instruct-GGUF` 3.2 GB (Q4_K_M + mmproj) |
| `broll/docs/prototypes/local-vlm/` (in the repo) | 37 KB | the two runner scripts and the raw result/baseline JSON — kept deliberately |

`E:\broll-queue\broll.db` was opened read-only; no indexer code, config, DB or
sheet was modified.

## Sources

- Qwen3-VL-4B-Instruct-GGUF model card (Apache-2.0, quant sizes, llama.cpp/Ollama): https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF
- Qwen2.5-VL-3B-Instruct LICENSE (Qwen Research License, non-commercial): https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct/raw/main/LICENSE
- Qwen3-VL-4B vs 8B benchmarks/VRAM: https://codersera.com/blog/qwen3-vl-4b-vs-qwen3-vl-8b-benchmarks-vram-guide/
- Qwen3-VL technical report: https://arxiv.org/pdf/2511.21631
- Local vision models by GPU tier, throughput table (note: lists Gemma 3 as Apache — it is not; Gemma 4 is): https://insiderllm.com/guides/vision-models-locally/
- Gemma 4 under Apache-2.0: https://opensource.googleblog.com/2026/03/gemma-4-expanding-the-gemmaverse-with-apache-20.html
- Moondream 3 preview licence (BSL 1.1): https://huggingface.co/moondream/moondream3-preview ; Moondream2 (Apache-2.0): https://huggingface.co/vikhyatk/moondream2
- SigLIP 2: https://huggingface.co/blog/siglip2 , https://huggingface.co/google/siglip2-so400m-patch16-naflex
- Perception Encoder: https://github.com/facebookresearch/perception_models
- InternVideo2 (MIT): https://huggingface.co/OpenGVLab/InternVideo2-Stage2_6B
- nomic-embed-vision v1.5: https://huggingface.co/nomic-ai/nomic-embed-vision-v1.5 ; jina-clip-v2 (CC-BY-NC): https://huggingface.co/jinaai/jina-clip-v2
- Ollama structured outputs: https://docs.ollama.com/capabilities/structured-outputs , https://ollama.com/blog/structured-outputs ; GPU/CPU fallback: https://docs.ollama.com/gpu
- llama.cpp multimodal + server grammar/json_schema: https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md , https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- Cloud GPU prices: https://www.runpod.io/gpu-models/rtx-4090 , https://getdeploying.com/gpus/nvidia-rtx-4090
- Ollama model pages: https://ollama.com/library/qwen2.5vl:3b , https://ollama.com/library/qwen2.5vl:7b
