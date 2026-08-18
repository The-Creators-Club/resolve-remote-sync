# Music ingest from the dashboard — drag-and-drop → local analysis on the companion → NAS

Written 2026-08-18, companion to `BROLL_INGEST_PLAN.md`. Owner's ask: "Music
needs a similar ingest pipeline to b-roll. Click-and-drag or folder select,
then the indexing gets pinged to the user's companion; the companion shows a
progress window (styled like the copy-to-project-folder popup): model pull
progress if it has to pull a model, per-track indexing progress, overall
progress and a time estimate; the same window for b-roll and for proxies."

Everything the b-roll plan builds is reused: batches + fleet/session routes,
the loopback `prepare/upload/pick/run/control/progress` shape, the
`BrollIngestor` gate/checkpoint/upload orchestration, the `WorkProgressWindow`
+ `ProgressModel`, the sidecar-download pattern with sha256 pins, and the
tray/reporter/fleet-grid surfaces. This document only records what is
different for music.

## 0. Ground truths (2026-08-18)

- Music already has a browser-upload → NAS-queue → base-rig-drain loop
  (`music/web/musicweb/routes_ingest.py`, `ingest_queue` + `uid` journal
  (migrations 002/003), `music/indexer/index_music.py --queue`,
  `musicweb/drain.py` bundle export/apply with identity/agreement/atomicity).
  Uploads land flat under the music share (`db.unique_dest`), duplicates are
  refused twice (normalised stem + duration; blake2b content hash), `.ogg` is
  transcoded to 320k mp3, and the container's `MAX_INGEST_*` are 64 files /
  512 MiB per request.
- Per-track analysis (`index_music.analyse_one`) = decode → **CLAP audio
  embedding** (`laion/clap-htsat-unfused`, torch, base rig GPU) → DSP
  features → vocabulary tagging (CLAP text-vs-audio cosine) → axes / debias
  (library-relative percentiles) → waveform peaks. Tags/axes are
  library-relative, which is why `drain.export_bundle` carries a whole-library
  rescore.
- The container has NO torch. It already runs the CLAP **text tower as ONNX**
  for query embedding (`music/indexer/export_text_encoder.py`,
  `musicweb/text_encoder.py`, `onnxruntime` in `dashboard/deploy/requirements.txt`).
- The frozen companion has no torch either and must not gain it (~2 GB).

## 1. The one design decision: where the audio embedding runs

**Export the CLAP audio tower to ONNX and run it in the companion via
onnxruntime; the server computes tags/axes/debias from the uploaded
embedding with the text tower it already has.**

- `music/indexer/export_audio_encoder.py` (new, base rig, one-off per model
  version): exports `audio_model` + `audio_projection` (HTSAT, ~90 M params
  → ~350 MB fp32 / ~180 MB fp16) plus a small JSON of the feature-extractor
  parameters (48 kHz mono, 10 s windows, mel bins/hop, log-mel scaling) —
  the same numbers `analyse_one` uses. Verifies cosine ≥ 0.999 vs the torch
  model on 20 library tracks and writes the sha256s into
  `music/indexer/music_models.py` (catalogue, like `broll_index/local_models.py`).
  The artefact is published to the vendor release feed (WP E) as
  `music-clap-audio-<ver>.onnx`, not to HF — it is ours.
- Companion sidecar `music_clap_sidecar.py`: downloads the ONNX + params
  (sha-pinned, host allow-list = the release feed host), runs on
  onnxruntime with the best available EP (CUDA if the DirectML/CUDA package
  is present, else CPU — a 3-minute track is ~18 windows, ~10–20 s on CPU;
  acceptable at ingest cadence), mel spectrogram in numpy from the params
  JSON (**bit-parity test** against the torch feature extractor on the same
  20 tracks). New companion deps: `numpy` (BSD), `onnxruntime` (MIT) — both
  clear `tools/check_licenses.py`; +~60 MB frozen. GPU is not required, so
  no VRAM refusal here — the tier concept does not apply.
- Server: `POST /music/api/fleet/ingest/items/{iuid}/result` receives
  `{embedding (float32 base64, dim), duration, peaks, transcoded, content_hash,
  probe}`; the container writes the track row and computes **tags/axes/debias
  itself** using the text-tower ONNX it already loads for queries — the same
  code `drain.apply_bundle`'s rescore uses, moved into a `musicweb/rescore.py`
  callable from both the bundle path and the ingest path. Nothing here needs
  torch. Embedding dim/model version is recorded per row (a model change
  re-embeds, exactly as the b-roll `embeddings.model` column does).

Rejected: (a) companion uploads audio to the NAS and the base rig drains — the
existing loop; kept as the fallback when the sidecar is unavailable
(`item.state = 'queued_for_base_rig'`, journal row pending), but it does not
meet "the indexing gets pinged to the user's companion"; (b) torch in the
companion — size; (c) tags on the companion — needs the text tower there
too, and tags are library-relative.

## 2. Reuse map (what changes vs b-roll)

| Layer | b-roll (built) | music (this plan) |
|---|---|---|
| Server tables | `ingest_batches/ingest_items` in broll.db (migration 011) | same two tables in `music.db` (migration 004) with `track_id` instead of `video_id`; reuse the SQL and `ingest_batches.py` helpers via a small `musicweb/ingest_batches.py` that imports the shared logic if `broll/web/app/ingest_batches.py` is importable in the container (both trees are on `PYTHONPATH`) — else vendor with a parity pair |
| Session routes | `/broll/api/ingest-batches` | `/music/api/ingest-batches` (same bodies; `share` = the music share, no shoot folder: uploads stay flat under `share_root()` with `unique_dest`) |
| Fleet routes | `/broll/api/fleet/ingest/…` | `/music/api/fleet/ingest/…` (same auth: fleet token + identity + `X-CCSync-Machine`; `result` body differs as above; `uploaded` verifies the audio file under `share_root()`) |
| Dashboard gate | `BrollGate` stamps identity | `MusicGate` (`dashboard/src/ccsync_dashboard/music.py`) gets the same stamping; `login_gate` carve-out regex for `/music/api/fleet/ingest/...` |
| Loopback | `/broll/ingest/*` | `/music/ingest/*` — same handlers parameterised by "kind"; `capabilities` reports the CLAP sidecar instead of tiers/VRAM; PUT upload identical (audio extensions filter, per-file cap 512 MiB matching the container's) |
| Companion pipeline | proxy → sprite/poster → frames → Qwen | probe → (ogg→mp3 transcode, same rule as the container) → peaks (ffmpeg) → CLAP audio embedding (sidecar) → `result` → upload the audio file → `uploaded` |
| Precheck / dedupe | xxh64 head+tail vs `videos.hash` | blake2b-16 vs `tracks`+`ingest_queue` (`db.find_content_duplicate`) and stem+duration (`db.find_reencode`) — the container's existing two defences, exposed as `POST /music/api/ingest-batches/precheck` |
| Orchestrator | `BrollIngestor` | `MusicIngestor` = the same class with a `kind` strategy object (pipeline steps, sidecar, result shape); ONE state file per kind; ONE progress window model; the same gate/run mode/precedence rules (music never needs the GPU, so it does not block proxies — set `blocking_reason()` to None for music) |
| Tray / reporter / grid | `broll_ingest` section, `[ INDEXING B-ROLL ]` chip | `music_ingest` section (same `BrollIngestIn`-shaped model, `kind` field), `[ INDEXING MUSIC ]` chip; the window title says "Indexing music" |
| SPA | b-roll `#ingest-panel` | the same panel component in `music/web/static/app.js` (music already has the drop overlay — it becomes the entry to this flow; the old "upload to the NAS queue" path stays as the fallback branch when no companion answers) |
| Search freshness | `search_norm` server-side | tags/axes computed server-side at `result`; `refresh` of facets like `_ingest_inline` does today |

## 3. Phasing (after b-roll PR-H/J land; ~7 days)
1. `export_audio_encoder.py` + `music_models.py` catalogue + parity fixtures (1) — base rig.
2. `musicweb/rescore.py` (extract from `drain.apply_bundle`) + migration 004 + session/fleet routes + `MusicGate` stamping + carve-out (1.5).
3. Companion `music_clap_sidecar.py` (numpy mel + onnxruntime; deps; parity test) + `MusicIngestor` kind strategy + loopback `/music/ingest/*` + tray/reporter/window title (2.5).
4. SPA panel in `music/web/static` (1.5).
5. Docs (`docs/INDEXERS.md`, `music/README.md`, `LOOPBACK_API.md`, `API.md`) + ledger (0.5).

## 4. Verification
Unit per component as b-roll; parity tests: mel features and embeddings vs
torch on 20 fixture tracks (cosine ≥ 0.999); end-to-end on the base rig: drop
6 tracks incl. one `.ogg`, one duplicate, one re-encode → companion window
shows model pull (first time), per-track progress, ETA → tracks live in the
music search with tags/axes → the same tracks are findable by CLAP text query.
