# Music — Specification

AI genre/mood/vibe tagging and search for the centralised royalty-free music library at
`W:\Creators_Club\Assets\Music` (376 instrumental tracks, 18.5 h, no lyrics, flat folder).

Goal: find the right cue by *feeling* — "tense driving synth pulse", "warm nostalgic
piano" — not by remembering a filename. Roughly a third of the library is named only by a
numeric library ID or a UUID, so name-based search is useless for those.

Folded in from the standalone `music-tagger` repo on **2026-08-10**, mirroring the b-roll
fold of the same day; the pre-fold git history stays in `E:\Projects\music-tagger`.
`PORT_PLAN.md` there is the fold plan; **step 1 (fold only) is what has landed.** Steps 2–8
are listed under "Still to port" at the bottom and are each marked with a
`TODO(port step N)` comment at the place they touch.

## Where the halves live

| Piece | Dir | Runs where |
|---|---|---|
| FastAPI search API + SPA | `music/web` | mounted in-process at `/music` by the dashboard, on the NAS |
| CLAP embed / tag / waveform / queue drain | `music/indexer` | **base rig only** — it needs the RTX 3080 |
| Resolve actions (`music_worker.py`, `music_server.py`) | `ccsync_companion` | every editor machine, on the existing 127.0.0.1:8899 loopback |
| `eval.py`, `validate.py` | `music/eval` | ad hoc |
| `music.db` | `music/web/data` | shipped to the NAS like `broll-web` |

Same split as `broll/`: web is mounted, the indexer stays on the base rig, the local
Resolve half belongs in the companion.

### The web package is `musicweb`, not `app`

`broll/web` is deployed by putting its tree on `PYTHONPATH` and importing it as the
top-level package `app`. A second package called `app` would collide in `sys.modules`
and one of the two would silently win — with two FastAPI apps mounted in the same
dashboard process, that is a coin flip between "b-roll serves music's routes" and the
reverse. The FastAPI *instance* inside `musicweb/main.py` is still called `app`, because
that is the object the dashboard mounts.

### One storage layer, shared both ways

`musicweb/db.py` and `web/schema.sql` describe the database the indexer **writes** and the
web app **reads**, so there is exactly one copy of each and `music_index/__init__.py` puts
`music/web` on `sys.path` to reach them. Two copies of a schema would drift, and a drift
between writer and reader is silent. For the same reason `music_index/config.py`
re-exports `MUSIC_ROOT`/`DATA_ROOT`/`DB_PATH` from `musicweb.config` instead of restating
them — which is also why the database lives under `music/web/data/`, with the tree that
gets shipped.

The dependency in the other direction is lazy and optional: the web app touches the
indexer in exactly two places (drag-and-drop ingest, and the on-demand waveform fallback),
both through `config.add_indexer_to_path()`, so a web-only checkout answers those two
routes with a clear error instead of failing to start.

### Why the mount must be in-process (not a proxy)

`dashboard/src/ccsync_dashboard/broll.py` spells this out for video and it applies
identically here: `/api/audio` serves **HTTP Range / 206** responses so the player can
seek, and a reverse proxy in front of it reintroduces the "pass Range through unmodified"
problem. Mounted in-process, uvicorn serves the 206s directly. The mount also inherits the
dashboard's `login_gate` for free. Copy the b-roll tri-state contract exactly —
**absent / degraded / ok** — and a broken or missing music checkout must never stop the
dashboard booting.

## Why CLAP and not Essentia/MTG

The original plan was Essentia + the MTG-Jamendo mood/genre heads. **Essentia has no
Windows wheels** (`essentia-tensorflow` has no Windows distribution; plain `essentia` is a
source-only C++ build), and the base rig has no WSL and no Docker. So the taxonomy models
are unavailable there.

CLAP (Contrastive Language-Audio Pretraining) replaces them and is arguably better for
this use case: one model gives zero-shot tagging against *our own* vocabulary, free-text
search, and similarity — all from the same embedding, on the RTX 3080. A fixed taxonomy
never has the tag you want at 2am in the timeline; free text does.

If MTG tags are ever wanted, run Essentia on a Linux box and add its labels as another
`tags` category — the schema already allows it.

## Components

| File | What it is |
|---|---|
| `indexer/index_music.py` | CLI worker. Decodes audio, embeds with CLAP, scores the vocabulary, extracts BPM/key/loudness, writes SQLite. Resumable and idempotent. |
| `indexer/music_index/vocab.py` | The label vocabulary. **This is the tuning surface.** Editing it and re-running `index_music.py --retag` re-scores every track in seconds; no re-embedding. |
| `indexer/music_index/debias.py` | Finds the source-bias axes (index time only). |
| `web/musicweb/main.py` | FastAPI app. Owns nothing; reads the DB the indexer writes. |
| `web/musicweb/routes_api.py` | stats / facets / tracks / search / similar / reload |
| `web/musicweb/routes_media.py` | audio streaming (HTTP Range) + waveform peaks |
| `web/musicweb/routes_ingest.py` | ingest — the only write route left here; the Resolve actions and reveal are the companion's, on the editor's own 127.0.0.1:8899 |
| `web/musicweb/search.py` | query logic; CLAP is loaded lazily and only here, once per process |
| `web/musicweb/projection.py` | applies the source-bias axes (query time) |

## Text search needs CLAP at query time — but not a GPU

`/api/search` embeds the query text with CLAP on every request. Measured on CPU:

- **18 ms per query**, 4.3 s one-time model load
- text tower + projection is **125M** of the model's 194M params

So search runs fine in a container. Everything else — audio embeddings, tags, axes,
percentiles, waveforms, debias axes — is **precomputed into the DB by the base rig**. The
container only ever embeds text.

torch is therefore **not** a dependency of `web/pyproject.toml` and must not become one:
`musicweb/search.py` imports CLAP lazily inside `Index.clap`, so browse, filter,
similarity, streaming and the UI all work in a venv without it. `tests/` runs with no torch
installed, and `test_similar_no_torch.py` pins that.

## Path model

b-roll's load-bearing rule, and now this one's: **the DB never stores absolute paths.**
Every asset is `(share, rel_path)`, translated to a real path at the edge, so the library
can be remounted per machine without invalidating the index. `tracks.share` is `'music'`;
`rel_path` is forward-slash relative to that share's root.

| host | root |
|---|---|
| base rig (indexer) | `W:\Creators_Club\Assets\Music` |
| editor machines | `P:\Assets\Music` |

That sits alongside `P:\Assets\B-roll Archive`. The editor tree root is deliberately
hardcoded to `P:` fleet-wide — do not add a configurable drive letter.

`musicweb/config.py` resolves the root in this order: `MUSIC_SHARE_ROOT` → `MUSIC_ROOT`
(kept because it predates the share model and is what DEPLOY.md and the test conftest
use) → `W:` if present → `P:`. An unknown share raises rather than falling back to the
music root.

Every path is built through `config.resolve_path(share, rel_path)`, never by joining a
root to a DB value. It rejects absolute paths, UNC prefixes, drive letters, `..`
components and components ending in `:`, then does a final containment check against the
resolved root — mirroring the validation in the companion's `broll_server.py`.

`_stems/` is **excluded from indexing**. Those 21 files are BASS/DRUMS/INSTRUMENTS/MELODY
splits whose full mixes are already in the library; a drums-only pass classifies
nonsensically and pollutes similarity results.

### Schema migrations: do not stamp the version from `schema.sql`

This app re-applies `schema.sql` to *existing* databases on every open — that is how
`peaks` and `debias` reached the live index. So a `PRAGMA user_version` stamp at the foot
of `schema.sql` (which is what `broll/web/schema.sql` does, correctly, for its own
lifecycle) is actively wrong here: it advances the version on a database that has not
had the migration applied, after which a version-driven runner skips that migration
forever. This actually happened during port step 3 and took the live 376-row index to
`user_version=1` without the `share` column.

`ensure_schema` owns the version, and each entry in `db._MIGRATIONS` carries an
**already-applied predicate** (e.g. `'share' in columns(tracks)`) which — not the
recorded version — decides whether it runs. That makes migrations idempotent and repairs
a database whose version claims more than its schema holds.
`tests/test_migration.py::test_a_db_stamped_current_but_missing_the_column_is_repaired`
pins the incident.

## Embeddings (load-bearing)

Two levels, both L2-normalised float32, stored as raw BLOBs:

- **Window embeddings** — 10s windows sampled evenly across each track (max 12). CLAP's
  audio encoder takes 10s at 48 kHz, so this is its native unit.
- **Track embedding** — mean of the window embeddings, re-normalised.

Search scores a track as **max similarity over its windows**, not the mean. A cue with a
quiet intro and a huge finish has a washed-out mean embedding; max-over-windows finds
"tracks that *contain* a tense moment", which is what an editor actually wants. The mean
embedding is kept for "more like this", where overall character is the right comparison.

Measured, not assumed — `eval.py` over 10 text queries with a known target track:

| pooling | top-10 | MRR |
|---|---|---|
| **window-max** | **40%** | **0.150** |
| window top-2 mean | 40% | 0.077 |
| track-mean | 20% | 0.045 |
| window-mean | 0% | 0.028 |

Raw query text also beat both `"This is a music track that sounds {q}"` and `"{q} music"`
templating, so queries are embedded verbatim.

Treat those absolute numbers as a floor, not a score: the eval's "correct" track is
inferred from its filename, and a cue called *Winter Rain* need not actually sound like
"gentle rain". Qualitatively the top-5 for a query is consistently on-brief.

## Source-bias removal (similarity only)

Similarity was returning too many tracks from one catalogue. Filenames are never
fed to CLAP — it only sees decoded audio — so this was not name matching. The
measured causes:

- every catalogue has a house sound and a mastering chain, and
- **source correlates with codec here**: `corr(is_ES, is_lossless) = +0.48`.
  117 of 176 `.wav` files are Epidemic Sound, and none of the 89 `.aac`, 31
  `.flac` or 7 `.ogg` are. Lossy encoders lowpass, and CLAP sees the rolloff.

`indexer/music_index/debias.py` finds the one-vs-rest axis for each source group (groups
keyed on the *shape* of a filename — `ES_` prefix, UUID, numeric id — never its words,
and only at index time) and projects those 4 axes out of 512.

| | ES-seed → ES | lossless → lossless | neighbour tag agreement |
|---|---|---|---|
| base rate | 36% | 55% | 0.167 (random pairs) |
| raw | 53.7% | 64.9% | 0.445 |
| **debiased** | **40.5%** | **56.7%** | **0.419** |

Source and codec bias essentially gone; musical coherence still ~2.5× chance.

**Applied to similarity only.** The same projection takes text retrieval from
40% to 20% top-10 — those axes carry content that text queries lean on, and text
sits on the far side of CLAP's modality gap. `Index` therefore keeps a raw
matrix for search and a debiased one for `similar`. (Debiasing documents and
debiasing the query score identically, as they must for an orthogonal
projector.)

Rejected, all measured: whitening (tag agreement fell to 0.38, bias barely
moved), MMR diversification (no effect — diversifying inside an already
monoculture neighbourhood still returns it), similarity over the tag vector
(49.6%; tags inherit the bias because they come from the same embedding), and
lowpassing all audio to a common bandwidth (discards brightness, which is
musically real).

**The split across the fold:** finding the axes needs the whole library's embedding matrix
and its filenames, so `compute_directions()` and `source_group()` stay index-time, in
`indexer/music_index/debias.py`, and run on every retag. Applying them is three lines of
numpy per query and lives in `web/musicweb/projection.py`. The computation is deliberately
**not** duplicated into the web app; the axes travel in the `debias` table.

## Scoring

- **Categories** (`genre`, `mood`, `instrument`, `use_case`, `texture`) are multi-label
  sets. Each label is the mean of several prompt templates. Cosine similarity against the
  track embedding, softmaxed within the category; top-k stored in `tags`.
- **Axes** (`arousal`, `valence`, `tension`, `organic`) are bipolar pairs scored as
  `sim(positive) - sim(negative)`.

Raw CLAP similarities are poorly calibrated in absolute terms — everything lands in a
narrow band — but their *ordering* is reliable. So every axis and tag score is also stored
as a **percentile rank within this library** (`pct`). The UI filters and sorts on
percentile. This is why filters behave sensibly on 376 tracks and would need a re-rank
(`--retag`) if the library grew substantially.

## Database

SQLite at `DATA_ROOT/music.db` (`music/web/data/music.db`). Schema in `web/schema.sql`.
Tables:

- `tracks` — one row per file: rel_path, duration, bpm, key, loudness, embedding, hash
- `windows` — 10s window embeddings (track_id, idx, t0, t1, embedding)
- `tags` — (track_id, category, label, score, pct, rank)
- `axes` — (track_id, axis, raw, pct)
- `peaks` — 900 uint8 waveform buckets per track
- `debias` — the source-bias axes, refreshed on every retag
- `meta` — model name, vocab hash, index timestamps

A track is re-analysed only if its size+mtime hash changed. `--retag` re-scores from
stored embeddings without touching audio (seconds, not minutes).

WAL, and **one SQLite connection per thread** (`musicweb.db.con`): FastAPI dispatches sync
endpoints across a threadpool, and sharing one connection raises "SQLite objects created in
a thread can only be used in that same thread" as soon as two requests land on different
workers.

The schema is entirely `CREATE ... IF NOT EXISTS` and is re-run on every open, so additive
changes need no migration — see `web/migrations/README.md` for when one is needed.

## API

- `GET  /api/tracks` — list with filters (category/label, bpm range, duration, axis pct)
- `POST /api/search` — `{query, k, pool}` free-text CLAP search, max-over-windows
- `GET  /api/similar/{id}` — nearest neighbours by track embedding (no CLAP needed)
- `GET  /api/facets` — all labels with counts, for the filter UI
- `GET  /api/audio/{id}` — audio stream with HTTP range support
- `GET  /api/peaks/{id}` — 900-byte waveform overview
- `GET  /api/stats` — library summary
- `POST /api/reload` — pick up a fresh index without restarting (drops the cached
  connections first, so a music.db that was REPLACED by rename is picked up too)
- `POST /api/ingest` — the one write route. "Send to Resolve" and "reveal" are **not**
  routes of this app: they are `POST /music/send` and `POST /music/reveal` on the
  editor's own companion (127.0.0.1:8899), because this process runs on the NAS

`/api/facets` returns categories as JSON keys and the frontend renders them in key order,
so that order is load-bearing. It used to come from `vocab.CATEGORIES`; `vocab.py` is the
indexer's tuning surface and is not shipped with the web tree, so the *membership* now
comes from the database and only the **order** lives in `musicweb/config.CATEGORY_ORDER`.
Anything the indexer grows that is not listed there is appended alphabetically rather than
dropped.

## Ingest (drag and drop)

Files dropped anywhere on the page `POST /api/ingest`. Per file:

1. written to `DATA_ROOT/staging` first — never straight into the library, so a
   half-written file is never visible to a re-index or to Resolve
2. rejected unless ffprobe finds a decodable audio stream
3. **`.ogg` is transcoded to 320k mp3.** The dropped `.ogg` itself is left alone
4. de-duplicated, two ways:
   - content hash against every file in the library
   - **normalised filename + duration within 2s.** Hashing cannot catch a
     re-encode — transcoding an `.ogg` to mp3 changes every byte — and `.ogg`
     previews sitting beside their masters are exactly what gets dragged in by
     accident. This check runs *before* transcoding, so a duplicate costs nothing
5. moved into `MUSIC_ROOT` under a collision-free flat name
6. CLAP embed + DSP features + waveform + DB row
7. the whole library is re-tagged, because percentiles are library-relative

All of that needs the GPU and ffmpeg, so `/api/ingest` answers **503** on a host without
the indexer rather than half-working. Port step 7 turns it into a queued handoff: accept
the upload, transcode, land it in the share, write a `pending` row, return "queued", and
let a base-rig `index_music.py` run (already resumable and hash-driven) fill in the
embeddings/tags/waveform. **Do not try to run CLAP audio embedding in the NAS container.**

## Resolve integration

Three actions per track, modelled on the timeline-cards bar in
`E:\Projects\Editing\Resolve\MulticamPipeline`:

| action | effect |
|---|---|
| `bin` | import into the `Music` bin. No timeline touched. Idempotent. |
| `under` | place at the playhead on the first free audio track **from A2 down**, adding a track if needed. Nothing moves. |
| `insert` | ripple insert on A2: clips at/after the playhead on that track shift later by the cue's length. |

"Place on top" from the cards means the first free track *above* the edit; for
audio the equivalent is a free track *below*, and A1 is skipped so sync audio is
never disturbed.

`insert` **refuses** when any affected clip is linked to video, or has no media
pool source (compound/fusion/generator). Rippling one audio track under locked
picture would silently desync sync sound — the expensive kind of mistake to
notice late. It verifies every re-placed clip landed on its intended frame and
rolls the track back if not.

Every call runs in a **child process** (`ccsync_companion/music_worker.py`) with a 90s
timeout. The scripting API blocks indefinitely when Resolve is modal, busy, or sitting on
the Project Manager, and that must not wedge the tray app.

### The browser calls the companion, not this server

`POST /music/send` and `GET /music/status` live on the **existing** loopback at
127.0.0.1:8899 (`ccsync_companion/music_server.py`), added to `broll_server.py`'s handler —
that port is already owned, and a second server holding it breaks the tray app.

**The page calls it directly, and must.** This app is served from the NAS, whose
127.0.0.1 is the NAS; only the editor's own browser can reach the Resolve that editor is
sitting in front of. Those two URLs are therefore the only absolute ones in `static/`.
Proxying them through the API would drive Resolve *on the NAS*.

The body is `{action, share, rel_path}` — never a path. The companion translates the pair
against its own mount table (`P:\Assets\Music` for an editor, `W:\...` on the base rig),
which is the whole reason the DB stores the pair. Traversal is rejected in three layers:
an absolute-`rel_path` check, `broll_server.translate_path`'s component rules, and a final
containment check that also catches a symlink no component rule can see.

Status codes follow b-roll's existing split: **400** only for a malformed request;
**200 + `{"ok": false, "error": …}`** for anything an editor can act on, because the
page's fetch helper throws on non-2xx and would show only the status number.

**Known wart:** Resolve advances the playhead past whatever it just appended, so
consecutive presses stack cues end-to-end rather than layering them at one point.

### API landmines this is written around

Learned in MulticamPipeline, plus one found here:

- `AppendToTimeline` without `trackIndex` obeys the UI's destination-track
  buttons — with the destination off it places **nothing and reports no error**.
  Always pass explicit `trackIndex` + `mediaType`.
- Appending to a track that does not exist returns an item yet places nothing.
  `AddTrack` first.
- A returned item is **not proof of placement**. Verify `GetStart()`.
- `AppendToTimeline` always lands on the *current* timeline whatever object you
  hold. Re-read and guard.
- `GetLeftOffset`/source frames come back a hair under the integer. `round()`.
- **`endFrame` is exclusive** (placed length = `endFrame - startFrame`). Passing
  `dur - 1` produces a clip one frame short, and every ripple computed from it
  is then one frame out. Found by the scratch-timeline test; the ripple now
  shifts by the *actually placed* duration rather than the requested one.

## Port status — all eight steps landed 2026-08-10

`PORT_PLAN.md` in the standalone repo has the original reasoning.

| # | | Outcome |
|---|---|---|
| 1 | fold into the repo | `musicweb` package (never `app` — collides with `broll/web`) |
| 2 | prefix-safe frontend | document-relative; the bare `/music` → `/music/` redirect is load-bearing |
| 3 | `(share, rel_path)` | `share` column + validated `resolve_path`, W: base rig / P: editors |
| 4 | dashboard mount | in-process at `/music`, tri-state, best-effort |
| 5 | text-tower artefact | ONNX; onnxruntime 54 MB vs torch 675 MB unpacked, retrieval identical |
| 6 | mp3 proxies | preview payload 9.49 GB → 1.04 GB (9.16×) |
| 7 | queued ingest | upload → transcode → `pending`; base rig drains it |
| 8 | companion Resolve | `POST /music/send` on the existing 8899 loopback |

**Remaining operational work, not code:** the companion must be rebuilt and published
(`tools\release.ps1`, then `-Publish -MakeCurrent`) before editors have `/music/*` — the
deployed build 404s on it. The text-encoder artefact (482 MB) and the proxies (906 MB)
ship to the NAS alongside `music.db`. Draining the ingest queue is a manual
`index_music.py --queue` for now; phase 2 (a timer, or the dashboard poking the base rig)
is untouched.

Unmeasured option: int8 dynamic quantisation would cut the text artefact to ~126 MB. It
has **not** been checked against the ≥0.999 cosine bar — treat it as a follow-up, not a
recommendation.

## Non-goals

Not a DAW, not a player library, does not modify or re-encode the audio, does not write
tags back into the files. The audio on `W:` is read-only to this system.
