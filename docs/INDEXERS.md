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
| music: CLAP **audio** embedding at ingest | the editor's own machine, in the companion | onnxruntime + the exported audio tower (280 MB, `export_audio_encoder.py`); **no GPU** — 93 ms per 10 s window on CPU | an embedding uploaded to the NAS; the container turns it into tags/axes |
| music: export the audio tower to ONNX | GPU host, once per model version | torch + transformers, the library mounted for the check corpus | `music-clap-audio-<ver>.onnx` + `.params.json` → the release feed |
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
| the data root | `MUSIC_DATA_ROOT` | proxies, staging. A preview proxy is named by track id and `tracks.id` is reused (see below), so every path that deletes a row or creates one now drops the file at that id with it (music-4, 2026-08-21) |
| the library | `MUSIC_LIBRARY_ROOT` | where this host has the music share mounted |
| ffmpeg | `FFMPEG` / `FFPROBE`, else `PATH` | required; `require_tools()` refuses up front rather than failing per track |
| CLAP weights | `MUSIC_MODEL_CACHE` (or `HF_HOME`) | ~600 MB |
| the exported audio tower | `MUSIC_AUDIO_ENCODER_DIR` | where `export_audio_encoder.py` writes; default `<MUSIC_DATA_ROOT>/audio_encoder`. **Not shipped to the NAS** — see below |
| the exported text tower | `MUSIC_TEXT_ENCODER_DIR` | where `export_text_encoder.py` writes; default `<MUSIC_DATA_ROOT>/text_encoder`. This one **is** shipped: the container embeds every query with it |

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

**Fetching the weights: `CCSYNC_DOWNLOAD_STREAMS`** (default 6, clamped 1..16;
set it to 1 for one connection). `download_verified` splits a ranged download
across that many connections, because a single long-lived one to Hugging Face
was measured decaying to ~2 MB/s while six ran at ~38 MB/s (KNOWN_BUGS
BROLL-ING-4). The same variable governs the companion's model fetch and the
music CLAP artefact, which go through the same function.

## Customers without a GPU

This is the v1 scope-out, and it is a real product, not a degraded one. Two
things have narrowed it since it was written, and both are about *whose*
machine has the card:

- **Music no longer needs one at all** (2026-08-18). The sentence that used to
  stand here, "CLAP embedding has no non-GPU path", was true of the torch
  pipeline and is not true of the exported ONNX tower an editor's companion
  runs: ~90 ms per 10 s window on one CPU core. A customer with no GPU
  anywhere still gets immediate, searchable music ingest, as long as their
  editors are on companion 0.9.0+ and the fleet has a release feed configured.
- **B-roll can be indexed on an editor's machine**, not only on a base rig, if
  any one machine in the fleet has a card that fits a tier: they drag clips
  onto the b-roll page and that machine crunches them
  (`docs/BROLL_INGEST_PLAN.md`). The tiers in the table above are the same ones
  `GET /broll/ingest/capabilities` gates on, and a tier that does not fit is
  refused rather than run on the CPU.

For **b-roll** with no card anywhere, `indexer.backend: anthropic` is a second
way for a no-GPU customer to index their own new footage without one at all,
an Anthropic API key instead of a GPU (`broll/docs/indexing-api.md`).
Everything below still holds for a customer who wants neither: a vendor-built
index they only search.

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

- indexing new *footage* themselves: each addition is a round trip to a
  machine that has a card (or to the Anthropic backend);
- drag-and-drop music ingest becoming searchable immediately **on a companion
  older than 0.9.0, or in a fleet with no release feed**. That drop takes the
  base-rig path: the upload is accepted, validated, de-duplicated, transcoded
  and landed in the library by the container, and sits `pending` in the ingest
  journal until a drain runs. The UI says so. With 0.9.0+ and a feed, this
  bullet does not apply, because no GPU was needed for it in the first place.

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

**Failures travel too, since 2026-08-21** (music-3). A file the base rig could
not analyse used to be parked `failed` only in the pulled copy, so on the live
index the row stayed `pending` for good: the editor's ingest panel counted it
as waiting, the duplicate defences went on treating the file as held (a fixed
re-export of the same track was refused as a duplicate), and every later drain
decoded the broken file again. The bundle now carries those rows, and `apply`
parks them with their reason — under the same agreement checks, and never over
a row that has since finished.

**And the running app notices, since the same day** (music-2). `apply` writes
straight to the file; `musicweb` caches a connection per worker thread and
builds its search matrices once per process, so the drained tracks used to be
in browse and invisible to search until someone POSTed `/music/api/reload`.
It now re-stats the database on the way through (at most every couple of
seconds) and reopens or rebuilds when it has moved. A container running a
musicweb from before 2026-08-21 still needs that POST, or a restart.

## Publishing `broll.db` without deleting what the fleet ingested

*BROLL-1, 2026-09-04.* `broll.db` is published as a **file** (the index really
is rebuilt on the base rig), and the live copy on the NAS is the **only** place
drag-and-drop ingest exists: the `videos` rows the dashboard mints at claim
time with their segments and vectors, the `share_roots` row for the shoot, and
the whole of `ingest_batches` / `ingest_items` - every batch's state, lease and
per-clip progress. The base rig's copy has never seen any of it, so until this
date the rename took the lot, silently: the shrink check compares row counts,
and 200 ingested clips against a 15,000-clip archive is a 1.3% difference
against a 10% threshold.

`publish_db.py --which broll` now does the music trick in the other direction,
by itself, as part of the publish:

```
checkpoint -> snapshot -> verify -> upload -> DRAIN the live copy
           -> rename    -> MERGE the drain back
```

The drain is a small SQLite bundle written **beside the live index** by the
dashboard container, `broll.db.drain-<ts>`. It is never deleted, and the merge
is one transaction in which every write is keyed: a clip the newly published
index already has is left exactly as the publish left it, and one it lacks is
re-inserted with a fresh id, its children and its vector.

Two things an operator will meet:

- **A drain that cannot be taken stops the publish**, before anything is
  renamed, naming the reason (a container that is not running is the usual
  one). `--allow-loss` publishes anyway and says what that costs. A NAS with
  no `broll.db` yet is not this case: a first publish has nothing to lose and
  proceeds.
- **A merge that fails after the rename is not a loss.** The new index is
  live, the drained rows are in the bundle, and the command to put them back
  is printed:

  ```powershell
  python publish_db.py --which broll --apply-drain /broll-data/broll.db.drain-<ts> --apply
  ```

  It is idempotent, so running it twice is safe, and so is running it after a
  `--rollback` (the `.prev` carries the rows too).

**Pause ingest first if you can.** The drain is taken as late as possible, but
a batch that starts between the drain and the rename is the one thing it
cannot see; that batch's rows would be lost by the swap. Look at Dashboard ->
B-roll -> the ingest panel, or at the `open_batches` count the publish prints,
before you publish over a working day.

## The CLAP audio tower is an artefact now (`export_audio_encoder.py`)

*2026-08-18, `docs/MUSIC_INGEST_PLAN.md` step 1.* The drain above is the
fallback path, not the destination. Music ingest is moving to "the indexing
gets pinged to the editor's companion": the machine the files were dropped on
embeds them, and the NAS turns the embedding into tags. Neither end may grow a
torch dependency — the container by the rule at the top of this document, the
frozen companion because torch is ~2 GB — so the audio half of CLAP is
exported to ONNX exactly as the text half already was:

```powershell
cd music\indexer
python export_audio_encoder.py --db ..\web\data\music.db   # export + verify + report
python export_audio_encoder.py --check                     # re-verify an existing one
python export_audio_encoder.py --print-catalogue           # the music_models.py block
```

It writes four files into `MUSIC_AUDIO_ENCODER_DIR`:

| file | what |
|---|---|
| `music-clap-audio-<ver>.onnx` | `audio_model` + `audio_projection` + the L2 normalise, fp32 |
| `music-clap-audio-<ver>.params.json` | the feature-extractor parameters, read off the checkpoint's own `ClapFeatureExtractor` — sample rate, window length, mel geometry, log-mel scaling, padding/truncation rule, pooling, graph input/output names |
| `music-clap-audio-<ver>.fp16.onnx` | optional half-precision copy; measured, not shipped (below) |
| `report.md` | what was measured, on what audio, with which torch/transformers |

**These do not go to the NAS.** `music/web/DEPLOY.md` ships `data/` item by
item and this is not one of the items: the container never embeds audio. They
go to the vendor release feed (`docs/RELEASE_FEED.md`) beside the companion
binaries, and `music/indexer/music_models.py` is the catalogue the companion's
sidecar verifies the download against (sha256 + size per file). The exporter
prints that block; paste it in after every export.

Three rules the code enforces rather than documents:

- **Nothing is published until it matches torch.** Cosine >= 0.999 against
  `ClapModel.get_audio_features` on every window of a real-library check
  corpus *and* on every mean-pooled track vector, with the same
  stage-verify-swap as the text exporter (MUSIC-1). The 2026-08-18 export
  measured min 0.9999999 over 80 windows of 20 tracks.
- **`mel_numpy.py` is bit-identical to `ClapFeatureExtractor`**, not merely
  close — the export refuses on any difference, and
  `tests/test_mel_numpy.py::test_bit_parity_with_transformers` repeats it on 20
  library windows wherever transformers is installed. A slightly different
  spectrogram yields a *plausible* embedding of the wrong audio, which no
  cosine threshold downstream can catch.
- **A change of weights, graph or feature parameters is a version bump** in
  `music_models.py`, because the version is in the filename and everything
  already ingested would otherwise sit in a different space from everything new.

fp16 is exported and measured because it halves the download (141.0 MB vs
280.0 MB) but is *not* what the catalogue pins: cosine drops to 0.99997, and
onnxruntime's CPU provider — which is what an editor laptop with no usable GPU
EP actually runs — executes fp16 by inserting casts. The numbers are in
`report.md`; revisit them with a measurement from a machine in the field, not
with instinct.

## Music has two indexing paths now, and only one of them is here

*2026-08-18, `docs/MUSIC_INGEST_PLAN.md` steps 3-4.* Everything above this
section describes the BASE RIG path. Since companion 0.9.0 there is a second
one, and it is the one an editor meets:

| | the companion path (new, default) | the base-rig path (older, kept) |
|---|---|---|
| Who analyses | the editor's own machine, in the tray app | the base rig, `index_music.py --queue` |
| Reached by | drag onto `/music` with a companion running | drag with no companion, or one older than 0.9.0 |
| Audio model | the exported CLAP tower on **onnxruntime, CPU** (`music_clap_sidecar.py`) | `laion/larger_clap_music_and_speech` on **torch, GPU** |
| Where the file goes | rclone straight into the library, under the name the SERVER allocated | uploaded to the NAS by the browser, `ingest_queue` row, drained later |
| Tags, axes, debias | the **container**, from the uploaded embedding (`musicweb/rescore.py`) | the base rig, then a `--export-drain` bundle |
| bpm / key / lufs / peak | **not computed** (KNOWN_BUGS MUSIC-ING-1) | computed (librosa) |
| Searchable | seconds after the editor drops it | after somebody runs the drain |

Both write the same `tracks` row into the same database and both produce a
vector in the same 512-dimensional space -- that is what the export's cosine
>= 0.999 gate is for, and why `tracks.model` records which produced a row
(`laion/...@onnx1` for the companion path).

What an operator needs to know about the new path:

- **It needs a release feed.** The artefact is fetched from
  `release_feed_base` in `GET /api/v1/site` (the dashboard's
  `DASH_RELEASE_FEED_URL` minus `channel.json`), sha256-verified against the
  catalogue baked into the companion. A fleet with no feed configured sees
  "this fleet has no release feed configured" in the tray and on the fleet
  grid, and every drop falls back to the base-rig path. `docs/RELEASE_FEED.md`
  §6 is how the artefact is published.
- **It needs no GPU and it does not use one.** ~90 ms per 10 s window on one
  CPU core, so a music batch never stands proxy generation down the way a
  b-roll batch does.
- **It creates rows on the NAS, and `tracks.id` is reused.** `id` is an
  INTEGER PRIMARY KEY with no AUTOINCREMENT, so a new row takes the id of the
  highest one ever deleted — and a preview proxy is `<id>.mp3`, chosen on
  existence alone. Every editor previewing the new cue heard the deleted one
  (music-4, 2026-08-21). Creating a row and pruning one now both drop the file
  at that id. Shipping a base rig's whole `proxies/` directory over the NAS's
  is still unsafe once the two indexes have diverged: regenerate with
  `make_proxies.py --prune` there first, or push nothing.
- **A track it could not analyse is not lost.** The item ends
  `queued_for_base_rig` in the ledger with the reason, the file stays staged
  on the editor's machine, and the page offers the browser upload -- which is
  the base-rig path above, unchanged.
- **A base-rig sweep still works on top of it.** Rows the companion wrote have
  a `file_hash` (the content hash), so a later `index_music.py` pass over the
  library does not re-analyse them; a `--retag` fills in nothing they are
  missing except the DSP features, which is what MUSIC-ING-1 is about.

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
