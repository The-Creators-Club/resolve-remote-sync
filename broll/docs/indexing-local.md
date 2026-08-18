# Local indexing (Qwen3-VL via llama.cpp) — tiers, fetching, format, troubleshooting

*Written 2026-08-18. Companion to `broll/docs/local-indexing-options-2026-08-17.md`
(why this design, and the eval that proved it out) and `broll/docs/indexing-api.md`
(the Anthropic path, now the optional backend). `docs/INDEXERS.md` is the
top-level "what runs where" map; this is the local backend's own detail.*

## Ship decision

`[indexer] backend = local | anthropic`, default **`local`** for a new install.
Local runs [Qwen3-VL](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF)
(Apache-2.0) through a vendored [llama.cpp](https://github.com/ggml-org/llama.cpp)
(MIT) `llama-server`, at zero marginal cost, on the indexing machine's own GPU.
`anthropic` is the original Messages API path (`broll/docs/indexing-api.md`),
unchanged, selectable per site for a studio that wants the better first
impression or has no spare GPU.

An **existing** `config.yaml` that already has an `anthropic:` section and no
`indexer:` section keeps calling the Anthropic API exactly as before — see
`broll_index/config.py`'s `_build_indexer` for the exact heuristic. Nothing
here silently switches a running site's backend.

## The two tiers

| Tier | Model | Quant | VRAM | Apple Silicon | Speed (RTX 3080) |
|---|---|---|---|---|---|
| **Good** (default) | Qwen3-VL-4B-Instruct | Q4_K_M | 8 GB NVIDIA | 16 GB unified | ~20 s/clip |
| **Best** | Qwen3-VL-8B-Instruct | Q4_K_M | 12 GB NVIDIA | 24 GB unified | ~2x Good |

Both are pinned in `broll_index/local_models.py` (`TIERS`) — exact Hugging
Face repo, revision, filename and sha256 for the weights and the mmproj
projector, and the llama.cpp release (**b10470**) with per-platform asset
names and sha256. `Q8_0` is not shipped: the eval found no quality gain worth
the extra ~4 GB over `Q4_K_M`. The label/description/`vram_note` strings in
`TIERS` are the single source of truth — the dashboard's tier picker copies
them verbatim (CLAUDE.md), so a wording change here is a wording change there.

There is no dedicated CUDA build of llama.cpp b10470 for Linux x64 in this
release (checked 2026-08-18: Windows has `win-cuda-12.4`/`win-cuda-13.3`,
Linux only has `ubuntu-vulkan-x64`, `ubuntu-x64` (CPU), and `ubuntu-sycl-*`).
`local_models.RUNTIMES["linux"]` pins the Vulkan build instead, which runs on
NVIDIA/AMD/Intel GPUs through llama.cpp's Vulkan backend — not benchmarked in
the eval, so `broll-index doctor` says so rather than implying parity with
the Windows numbers.

## Choosing a tier

Precedence, highest wins: **CLI `--tier`** (`broll-index run --tier best`) >
**`indexer.model_tier` in config.yaml** > **the dashboard's site manifest**
(`GET {dashboard_url}/api/v1/site` → `{"indexer": {"model_tier": ...}}`, when
this indexer is pointed at one — `broll_index/dashboard_site.py`) > **default
`good`**.

`broll-index doctor` reports the resolved tier and probes this machine's GPU
(`nvidia-smi` on Windows/Linux, `sysctl hw.memsize` on Apple Silicon) to
recommend one. `broll-index models pull [--tier good|best] [--force]` refuses
to download a tier the probed GPU looks too small for — e.g. *"Best needs
12 GB VRAM; this machine reports 10 GB — choose Good or add --force"* — unless
`--force` is given.

## Fetching — what lands where

Nothing is bundled into the repo or a pip package. `broll_index/local_runtime.py`
downloads, on first use (or via `broll-index models pull`):

- the pinned llama.cpp `b10470` build for this platform (Windows CUDA 12.4,
  macOS arm64 Metal, Linux Vulkan) into `local_cache_dir/runtime/`,
- the tier's two GGUF files (weights + mmproj) into `local_cache_dir/models/<tier>/`.

`local_cache_dir` defaults per OS (`local_runtime.default_cache_dir()`):
Windows `%LOCALAPPDATA%\ccsync\indexer`, macOS
`~/Library/Application Support/ccsync/indexer`, Linux `~/.cache/ccsync/indexer`.
This is **not** `data_root` — the model/runtime cache is the same handful of
GB on every machine of a given tier and is never site data; `data_root` is
the archive's own frames/proxies/transcripts and gets backed up per site.

Every download is **sha256-verified against the pin before being trusted**; a
mismatch deletes the partial file and raises rather than silently keeping a
corrupt or tampered download around for the next run. Downloads resume (HTTP
Range) across a killed process. `llama_server_path` in config.yaml points at
an already-installed `llama-server` instead (a distro package, a hand build)
and skips the runtime fetch entirely.

## The compact format (why frames, not sheets, and why a grammar)

`broll/docs/local-indexing-options-2026-08-17.md` §2 measured the naive
drop-in (Claude's own contact-sheet JSON prompt, run through a 4B model) and
found two fixable failures: 384x216 sheet cells are below what a small VLM
needs for OCR (llama.cpp's own warning: *"Qwen-VL models require at minimum
1024 image tokens"*), and unconstrained decoding loops on structured output.
The fix, proven in `broll/eval/local_vlm/` and shipped in
`broll_index/compact_format.py` + `broll_index/local_vlm.py`:

- **Frames, not sheets.** Each call sends up to `frames_per_call` (default 9)
  native-resolution (960x540) frames as individual image blocks, labelled
  `F1..Fn` with the timecode **in the text**, not burned into the image.
- **One line per shot, not JSON.**
  `S <frames> | <description> | <objects> | <onscreen text> // <english>`,
  then one `T <themes>` line (`prompt_v7_compact.md` /
  `broll_index/prompts/index_clip_v7_compact.md`).
- **A GBNF grammar bounds the decode**, not just its syntax: `F` ids are
  limited to the window's actual frames, at most one `S` line per frame, one
  `T` line, then the grammar is exhausted — EOS is the only legal next token,
  which is what stops a repetition loop (a sampler `repeat_penalty` alone did
  not, per the eval's §2 finding 2).
- **Segment times are looked up from the frame table, never trusted from the
  model** — `t_start`/`t_end` come from the extracted frame's real timestamp,
  which also kills the "246 s on an 88 s clip" class of hallucinated timecode.
- **Category is assigned in code**, not asked of the model: nearest-neighbour
  cosine similarity between the clip's text and each taxonomy slug's
  label+description, using the indexer's own fastembed model when available
  (the same space `stage_embed` already populates) or a TF-IDF fallback with
  no dependency at all.
- **Exposure flags come from pixel statistics** (`compact_format.pixel_quality_flags`):
  luminance mean/clipped-fraction and a Laplacian-variance sharpness proxy
  over the extracted frames, not asked of the model.

`parse_compact` returns the exact same contract dict
`claude_client.validate_contract` accepts, so everything downstream of the
model call — `merge_index_results`, `write_index_result`, `stage_embed`,
`usage.jsonl` — is unchanged.

## The segment-merge post-process

The eval's remaining measured gap (`broll/eval/local_vlm/results/report.md`):
the compact format **over-segments** — 10.3 predicted segments/clip against
Haiku's 4.3, because a per-frame window naturally produces close to one line
per frame, and several consecutive frames of the same unbroken shot describe
it almost identically. `broll_index/local_vlm.merge_similar_segments`
collapses ADJACENT segments (by `t_start`) when their `objects` Jaccard
similarity is ≥ 0.6 **and** their `description`s are near-duplicates
(`difflib.SequenceMatcher` ratio ≥ 0.75), keeping the earlier `t_start`, the
later `t_end`, and the union of `objects`/on-screen text. It is not
transitive across a dissimilar middle segment — a real cut is never merged
away just because the shot on either side of it looks similar to something
else nearby.

Controlled by `indexer.merge_similar_segments` (default `true`), applied to
the **local backend only** — Claude's segments were already close to per-shot
from the v6 JSON prompt, so there is nothing to merge there, and turning it on
for that path would risk collapsing two real cuts that happen to look similar
in text. Every merge is logged (`local vlm: video %s merged %d
over-segmented pair(s) (%d -> %d segments)`).

## Usage/cost logging

Every window call appends one line to `DATA_ROOT/usage.jsonl`, same shape the
Anthropic path writes (so `tools/cost_report.py` keeps working unmodified):
`model` is `local:qwen3-vl-4b-q4_k_m` / `local:qwen3-vl-8b-q4_k_m`,
`input_tokens`/`output_tokens` are llama-server's own reported token counts,
`total_cost_usd` is always `0.0`, `duration_ms` is the wall time. Additional
fields carry local-specific detail cost_report.py does not read but a
by-hand analysis can: `backend`, `tier`, `encode_ms`/`decode_ms` (llama-server's
own `prompt_ms`/`predicted_ms` — image encode vs text decode).

## Troubleshooting

- **`broll-index doctor` first.** Reports the configured backend, the probed
  GPU (name, VRAM/unified memory), the recommended tier, the resolved tier,
  where the runtime/weights/mmproj are expected and whether they are present,
  the llama-server version string, and the dashboard manifest URL (if any).
- **"no GPU detected"** — `nvidia-smi` is not on `PATH`, or this is a Mac not
  running Apple Silicon. Use `backend: anthropic`, or move indexing to a
  machine with a GPU.
- **"Best needs 12 GB VRAM; this machine reports N GB"** — choose `good`, or
  `--force` to try anyway (llama.cpp will spill to shared memory and run at a
  small fraction of the measured speed — the eval measured 0.76 tok/s for a
  bf16 4B that didn't fit a 10 GB card; a quantised model that overflows is
  the same story).
- **Resolve is open** — the eval measured Resolve alone holding 9.3 of 10 GB
  on the 3080. Close it, or run indexing on a second machine/off-hours.
- **`sha256 mismatch downloading ...`** — a corrupted or interrupted download;
  the partial file is deleted automatically and the next run retries.
- **The server won't start (`llama-server did not become healthy`)** — check
  `DATA_ROOT/local_vlm_server.log`; usually a port already in use (unlikely,
  a free port is picked automatically) or a GPU driver mismatch with the
  pinned CUDA 12.4 build.
- **A clip comes back with zero segments, or the same segment repeated to the
  clip's end** — this is the exact failure mode the frames+grammar+compact
  design fixed in the eval; if it recurs, check `DATA_ROOT/local_vlm_server.log`
  for a truncated response (`finish_reason: length` — raise
  `TOKENS_PER_FRAME_BUDGET` in `local_vlm.py`, or reduce `frames_per_call`).

## See also

- `broll/docs/local-indexing-options-2026-08-17.md` — the market survey, the
  four-clip prototype, and why Qwen3-VL/llama.cpp specifically.
- `broll/eval/local_vlm/` — the 100-clip eval that proved the frames+compact+
  grammar design out; `results/report.md` is the scored comparison against
  Haiku.
- `docs/INDEXERS.md` — what runs where across both indexers, hardware
  guidance for a customer's base rig.
- `broll/docs/indexing-api.md` — the Anthropic backend, now optional.
- `docs/legal/THIRD_PARTY_NOTICES.md` — Qwen3-VL (Apache-2.0) and llama.cpp
  (MIT) in the hand-maintained non-pip inventory.
