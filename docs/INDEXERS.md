# The GPU indexers: what runs where, and what a customer without a GPU gets

*Written 2026-08-17 for `docs/COMMERCIAL_READINESS.md` item 14. Updated
2026-08-18: the b-roll `claude` stage is now `describe` — local by default
(Qwen3-VL via llama.cpp, `broll/docs/indexing-local.md`), Anthropic optional
per site (`broll/docs/indexing-api.md`).*

Two of this product's four web surfaces are search over a precomputed index:
`/broll` searches a b-roll archive described by a vision model plus speech
transcription, and `/music` searches a music library embedded with CLAP. Both
indexes are **built on a machine with an NVIDIA GPU and read by a machine
without one**. This document is the seam between those two machines.

## The one rule

> **Nothing in the NAS container ever needs a GPU.** It embeds *query text* —
> measured at 18 ms per query on CPU, and only the 125M-parameter text tower of
> a 194M model. Every audio embedding, tag, axis, percentile, waveform peak,
> source-bias axis, contact-sheet description and transcript is precomputed into
> a SQLite file by the indexers and shipped.

That is what makes "search-only, from a vendor-built index" a shippable v1 (see
[Customers without a GPU](#customers-without-a-gpu)). It is also a constraint on
every future change: the moment a search path needs torch, the deployment stops
fitting on the NAS.

| Job | Where it runs | Needs | Writes |
|---|---|---|---|
| b-roll: scan / probe / proxy / frames | GPU host (ffmpeg-bound; a GPU makes it faster, not possible) | ffmpeg | `data_root`, `broll.db` |
| b-roll: `describe` (shot indexing, `indexer.backend: local`, the default) | GPU host, GPU-bound | an 8 GB+ NVIDIA GPU (or Apple Silicon), `broll-index models pull` | `broll.db` |
| b-roll: `describe` (`indexer.backend: anthropic`, optional per site) | GPU host, but network-bound | an Anthropic API key | `broll.db` |
| b-roll: `transcribe` (faster-whisper) | GPU host | CUDA + cuDNN, the sidecar venv | `data_root/transcripts`, `broll.db` |
| b-roll: `embed` (fastembed, ONNX) | GPU host | — (CPU is fine) | `broll.db` |
| music: CLAP embed / tag / peaks / debias | **GPU host only** — an RTX-class card; ~9 min for a full 376-track rebuild | torch + CUDA, ffmpeg, the library on a local mount | `music.db` |
| music: queue drain | GPU host, against a copy of the NAS index | as above | a result bundle |
| **anything served to a browser** | **NAS container** | nothing but CPU | — |

## Required paths: nothing is guessed any more

Both indexers used to default their paths to one workstation's directories. As
of 2026-08-17 every path is **required**, and every refusal names both the
config key and the environment variable that would supply it — the container
mounts its config read-only, so "edit the file" is not always available.

### b-roll (`broll/indexer/config.yaml`, see `config.example.yaml`)

| Key | Environment override | What it is |
|---|---|---|
| `data_root` | `BROLL_DATA_ROOT` | frames, proxies, posters, sprites, transcripts. Tens of GB — local disk, never the share |
| `db.path` | `BROLL_DB_PATH` | the index, when `db.mode: sqlite` |
| `db.url` / `db.token` | `BROLL_DB_URL` / `BROLL_DB_TOKEN` | the ingest API, when `db.mode: api` |
| `whisper.python` | `CCSYNC_WHISPER_PYTHON` | the faster-whisper interpreter (below) |
| `whisper.script` | `CCSYNC_WHISPER_SCRIPT` | `broll/indexer/tools/whisper_transcribe.py` |
| `whisper.model_dir` | `CCSYNC_WHISPER_MODEL_DIR` | model cache; ~1.6 GB for `large-v3-turbo` |
| `embedding.cache_dir` | `BROLL_MODEL_CACHE` | fastembed's ONNX weights |
| `indexer.local_cache_dir` | `BROLL_LOCAL_CACHE_DIR` | the local backend's llama.cpp runtime + GGUF weights; `""` = per-OS default, see `broll/docs/indexing-local.md` |
| `indexer.llama_server_path` | `BROLL_LLAMA_SERVER_PATH` | use an already-installed `llama-server` instead of the vendored download |
| `indexer.dashboard_url` | `BROLL_DASHBOARD_URL` | where to ask `GET /api/v1/site` for `indexer.model_tier` when config.yaml doesn't say; `""` = derived from `db.url` |
| — | `ANTHROPIC_API_KEY` (named by `anthropic.api_key_env`) | **never** in config.yaml; needed only when `indexer.backend: anthropic` (or for `taxonomy propose`, always) |

### music (`music/indexer/music_index/config.py`)

| Setting | Environment | What it is |
|---|---|---|
| the index | `MUSIC_DB_PATH`, or `--db` | **required**: `index_music.py` refuses to pick one. Guessing is how a drain reports "nothing to analyse" about a database nobody was asking about (MUSIC-3) |
| the data root | `MUSIC_DATA_ROOT` | proxies, staging |
| the library | `MUSIC_LIBRARY_ROOT` | where this host has the music share mounted |
| ffmpeg | `FFMPEG` / `FFPROBE`, else `PATH` | required; `require_tools()` refuses up front rather than failing per track |
| CLAP weights | `MUSIC_MODEL_CACHE` (or `HF_HOME`) | ~600 MB |

## The faster-whisper environment is in the repo now

Transcription shells out to a separate interpreter rather than importing
faster-whisper, and that is not going to change: ctranslate2 pins its own CUDA
runtime and loads cuDNN through plain `LoadLibrary`, so sharing an interpreter
with torch and everything else is how the DLL wiring breaks. What *was* wrong is
that the environment lived outside the repo, at one operator's `~/tools/whisper`,
named as the **default** of `whisper.python`/`whisper.script` — so on any other
machine the stage skipped in silence.

Build it:

```powershell
cd broll\indexer
.\tools\make_whisper_env.ps1            # GPU; -Cpu for a machine with no card
```

```bash
cd broll/indexer
./tools/make_whisper_env.sh             # --cpu inside a container: CUDA comes
                                        # from the image, not from pip
```

It creates `.whisper-env` with pinned `faster-whisper==1.1.1` /
`ctranslate2==4.5.0`, imports them once to prove the libraries actually load,
and prints the two config values. `tools/whisper_transcribe.py` is the helper it
runs — same command line as the old out-of-repo script, so **an existing base
rig can keep pointing at its own environment**: set

```yaml
whisper:
  python: "C:/…/tools/whisper/.venv/Scripts/python.exe"   # whatever it has today
  script: "C:/…/tools/whisper/transcribe.py"
```

and nothing changes. There is no longer a default, so it must be said.

`pip install -e .[transcribe]` is the alternative for a single-purpose machine
that wants them in-process; the pins are the same.

## The GPU image

`tools/Dockerfile.indexer-gpu` is one image with both indexers and three
entrypoints (`index`, `transcribe`, `music-embed`, plus `drain`), on a pinned
`nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04` base with pinned torch cu124
wheels. It runs as 3000:3001 — the dashboard container's ids, so a host
directory shared between them needs one ownership — and takes four volumes:
`/library` (read-only where the workflow allows), `/data`, `/index`, `/models`.

```bash
docker build -f tools/Dockerfile.indexer-gpu -t ccsync/indexer-gpu:1 .
docker compose -f tools/compose.indexer-gpu.yaml run --rm broll-index
```

The compose file requests the GPU through
`deploy.resources.reservations.devices` (driver `nvidia`), which needs the
NVIDIA Container Toolkit on the host. **Without the toolkit the container still
starts** and every CUDA call quietly falls back to CPU — not an error, just
twenty times slower, which is worth knowing before blaming the model.

`/models` is a named volume on purpose: without it every container start
re-downloads ~1.6 GB of whisper and ~600 MB of CLAP into a layer that is thrown
away.

**ffmpeg comes from the distro (`apt install ffmpeg`), not vendored.** The
image is a build recipe, and what it pulls at build time is Ubuntu's own binary
under Ubuntu's own licence; nothing is redistributed as part of the product.
That changes if the image is ever **published to a registry** — a published
image distributes those binaries, Ubuntu's ffmpeg build includes GPL
components, and the published artefact must then be treated as a GPL-covered
aggregate. Same caveat as the dashboard's pinned static ffmpeg
(`server/install_dashboard_app.py`). Decide it before pushing, not after.

The image is **not built by `tools/ship.cmd`** and is not part of any deploy: it
is multi-GB and belongs to whoever runs the indexing.

## Hardware guidance for the b-roll `describe` stage (local backend)

Full detail, tiers table and troubleshooting: `broll/docs/indexing-local.md`.
The short version, `broll-index doctor`'s own logic
(`broll_index/local_runtime.recommend_tier`):

| This machine's GPU | Tier | Config |
|---|---|---|
| 12 GB+ NVIDIA VRAM (or 24 GB+ Apple Silicon unified memory) | **Best** (Qwen3-VL-8B) | `indexer.model_tier: best` |
| 8–11 GB NVIDIA VRAM (or 16–23 GB Apple Silicon) | **Good** (Qwen3-VL-4B, the default) | `indexer.model_tier: good`, or leave it unset |
| < 8 GB VRAM, or no discrete GPU | none — `indexer.backend: anthropic`, or search-only from a vendor-built index (below) | |
| Resolve is open on this machine | treat the GPU as unavailable — the eval measured Resolve alone holding 9.3 of 10 GB on an RTX 3080; run indexing off-hours or on a second machine | |

## Customers without a GPU

This is the v1 scope-out, and it is a real product, not a degraded one. It
still applies in full to **music** (CLAP embedding has no non-GPU path). For
**b-roll**, `indexer.backend: anthropic` is now a second way for a no-GPU
customer to index their own new footage without a card at all — an Anthropic
API key instead of a GPU, `broll/docs/indexing-api.md`. Everything below still
holds for a customer who wants neither: a vendor-built index they only search.

A customer with no NVIDIA card and no Anthropic key gets **search-only, over a
vendor-built index**:

1. The vendor (or the customer's own GPU host) runs the indexers over the
   customer's library and produces `broll.db` / `music.db`, plus the b-roll
   `data_root` stills the UI shows.
2. Those files are published to the customer's NAS. **The publish is not a file
   copy** — the databases are in WAL mode and are being read live. Use
   `server/publish_db.py` (checkpoint, stage, verify, swap, delete the stale
   `-wal`/`-shm`); **see there** and `docs/BACKUP_RESTORE.md` for the procedure
   and the recovery path.
3. Everything the browser does then works: search, facets, similarity, waveform
   scrubbing, previews, "send to Resolve". None of it touches a GPU.

What such a customer does **not** get:

- indexing new footage or new music themselves — each addition is a round trip
  to a machine that has a card;
- drag-and-drop music ingest becoming searchable *immediately*. The upload is
  accepted, validated, de-duplicated, transcoded and landed in the library by
  the container, and sits `pending` in the ingest journal until a drain runs.
  The UI says so.

If that round trip is not acceptable for a given customer, the honest answers
are a GPU in their NAS, a small GPU box beside it running
`tools/compose.indexer-gpu.yaml`, or a hosted indexing service — not a CPU
fallback. CPU CLAP over a real library is hours, not minutes.

## Draining the music ingest queue without losing writes

The container accepts music uploads it cannot analyse. Until 2026-08-17 the
handoff was "pull the NAS's `music.db`, drain it on the base rig, push the file
back", and the push overwrote everything editors queued in the meantime —
minutes to hours of lost uploads per drain, undetectable afterwards.

The file is no longer pushed. `ingest_queue` carries a `uid` per accepted upload
(migration `003_ingest_journal.sql`), the drain exports the **analysed results**
of the rows it closed, and those are merged into the live index in place:

```powershell
# 1. pull the NAS index (see music/web/DEPLOY.md for the -wal/-shm rules)
# 2. drain it where the GPU is, and export the bundle
cd music\indexer
python index_music.py --queue --db ..\..\nas-index\music.db --export-drain drain.db

# 3. apply the bundle where the LIVE index is -- stdlib only, no torch, no numpy
python -m musicweb.drain apply drain.db --db /path/to/live/music.db
```

`apply` is one transaction, every write is keyed and idempotent, and a row is
closed only if the live journal still agrees about its `rel_path` and
`content_hash`. Anything queued while the drain ran is not named by the bundle,
is not touched, and is still `pending` afterwards. `python -m musicweb.drain
inspect drain.db` shows what a bundle holds. The design and its three safety
properties are in `music/web/musicweb/drain.py`.

## See also

- `broll/docs/indexing-local.md` — the local (Qwen3-VL/llama.cpp) backend:
  tiers, fetching, the compact format, the segment-merge post-process,
  troubleshooting.
- `broll/docs/indexing-api.md` — the Anthropic backend, now optional per site.
- `broll/SPEC.md`, `broll/docs/indexing-findings.md` — what the b-roll stages
  cost, per clip, in money and hours.
- `music/SPEC.md` — the CLAP model, the vocabulary, the debias axes.
- `music/web/DEPLOY.md` — shipping a music index to the NAS.
- `docs/BACKUP_RESTORE.md` and `server/publish_db.py` — the database publish
  procedure (**see there**; do not hand-copy a WAL-mode database).

The b-roll indexer's local vision model (Qwen3-VL 4B "good" vs 8B "best") is
chosen on the dashboard's Settings page and published in the site manifest as
`indexer.model_tier` (`docs/CONFIG.md` `[indexer]`, `docs/API.md`); it can be
overridden per machine in the indexer's own config.
