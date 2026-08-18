# Music

AI genre/mood/vibe search over the royalty-free music library on
`W:\Creators_Club\Assets\Music` (376 instrumental tracks, 18.5 h).

Find a cue by describing it — *"tense driving synth pulse"*, *"triumphant orchestral
finale"* — instead of remembering which file it was. About a third of the library is named
only by a numeric library ID or a UUID, so this is the only way to find those at all.

Folded in from the standalone `music-tagger` repo on 2026-08-10 (pre-fold git history stays
there). `SPEC.md` is the design and the reasoning behind it, including what is still to
port.

## Run it

```powershell
cd music\web
.venv\Scripts\python.exe -m uvicorn musicweb.main:app --port 8790     # http://127.0.0.1:8790
```

The package is **`musicweb`**, not `app` — `broll/web` already deploys as top-level `app`
and two packages of that name collide in `sys.modules` once both are mounted in the
dashboard. The FastAPI instance inside `main.py` is still called `app`.

`web/.venv` has no torch, on purpose: only `/api/search` needs CLAP and it is imported
lazily. Browse, filters, similarity, streaming and the UI all work without it.

## Tests

```powershell
cd music\web;      .venv\Scripts\python.exe -m pytest tests -q
cd music\indexer;  python -m pytest tests -q      # system python, torch-free half
```

`indexer/tests` runs on the system interpreter on purpose. The CLAP half needs
a GPU rig, so what is tested there is the surface that does not: the required
paths, the model catalogue, and `mel_numpy` — whose bit-parity test against the
real `ClapFeatureExtractor` skips (loudly) wherever transformers is not
installed and runs wherever it is.

## Re-index after adding music (base rig only — it needs the RTX 3080)

```powershell
cd music\indexer
python index_music.py           # new/changed files only
python index_music.py --retag   # re-score after editing music_index\vocab.py
python index_music.py --peaks   # backfill missing waveforms
python index_music.py --force   # rebuild everything
python index_music.py --queue --db ..\..\nas-index\music.db --export-drain drain.db
```

Queued uploads are the one case that does **not** work against the local index: the
`pending` rows live in the NAS's copy of `music.db`, so `--queue` needs `--db` pointed at
a copy pulled down from there.

**The drained file does not go back — the bundle does.** Pushing the whole
database over the live one overwrites everything editors queued while the drain
ran (minutes to hours of lost uploads, undetectable afterwards). `--export-drain`
writes the analysed results of the rows it closed, and those are merged in place
where the live index is:

```powershell
python -m musicweb.drain apply drain.db --db <live music.db>
```

`apply` is one transaction, stdlib only (no torch, no numpy), every write keyed
and idempotent, and a row is closed only if the live journal still agrees about
its `rel_path` and `content_hash`. `python -m musicweb.drain inspect drain.db`
shows what a bundle holds. See `../docs/INDEXERS.md` and `web/DEPLOY.md`.

### The two exported model halves

Neither the NAS container nor the frozen companion may carry torch, so both
halves of CLAP are exported once on the base rig and run with onnxruntime:

```powershell
cd music\indexer
python export_text_encoder.py                              # -> data\text_encoder\  (ships to the NAS)
python export_audio_encoder.py --db ..\web\data\music.db   # -> data\audio_encoder\ (ships to the release feed)
```

The **text** tower embeds every search query in the container. The **audio**
tower (280 MB fp32, 512-d, cosine 0.9999999 vs torch on 20 library tracks) is
what the companion will run to embed dropped music where it was dropped
(`docs/MUSIC_INGEST_PLAN.md`); `mel_numpy.py` is the numpy front end that feeds
it, bit-identical to the checkpoint's own feature extractor, and
`music_models.py` pins both files by sha256 for the download. Neither exporter
publishes anything that failed its own check. `../docs/INDEXERS.md` has the
rules and the numbers.

Indexing is resumable and skips unchanged files by size+mtime. A full rebuild of 376
tracks takes ~9 min on the RTX 3080. `--retag` takes seconds because it re-scores from
stored embeddings without touching audio.

A full sweep also **prunes**: a row whose file is no longer under the root is deleted, so
a renamed cue does not survive as a ghost that ranks in search and only fails at "send to
Resolve" (MUSIC-3, 2026-08-14). It refuses to delete in bulk — an empty or badly thinned
scan is a half-mounted share far more often than it is a purge — so a genuine bulk removal
needs `--prune`, and `--no-prune` turns the pass off. Orphaned previews go with
`make_proxies.py --prune`.

The indexer writes `music/web/data/music.db` — the database lives with the tree that gets
shipped to the NAS. It imports `musicweb.db` and `web/schema.sql` rather than keeping its
own copy, so the writer and the reader cannot drift.

After re-indexing while the server is running: `curl -X POST localhost:8790/api/reload`.
That also picks up a database file that was REPLACED rather than rewritten in place — it
drops every cached connection first, since a sqlite3 connection is bound to an inode and
kept reading the old one otherwise (MUSIC-10, 2026-08-14).

## Using it

**Free-text search** is the main event. Describe the feeling, the instrumentation, the
edit it has to sit under. The `any moment` / `whole track` toggle chooses between "some
10-second stretch of this track matches" and "this track matches overall" — use *whole
track* when you want sustained character, *any moment* when you want a cue that
*contains* a big hit.

**Filters** (left panel) are better than free text for anything about density or energy.
CLAP is weak on absolute loudness and sparseness, so for interview-bed material, drag the
**arousal** slider down rather than searching "quiet". The bottom of the arousal range is
reliably the calm, sustained material.

**Similar** finds neighbours by overall character — usually the fastest way to turn one
track that nearly works into five more like it.

Clicking any tag chip filters the library by that tag. **Reveal** opens the file in
Explorer.

**Playing** a track slides a waveform player open directly beneath its card. Click
anywhere on the waveform to seek. Only one is open at a time.

## Adding music

**Drag audio files or folders anywhere onto the page.** Since 2026-08-18
(`docs/MUSIC_INGEST_PLAN.md`) **your own machine does the work**: the CC Sync
companion converts what needs converting, analyses each track with the CLAP
audio model on one CPU core, uploads the finished file to the library, and the
NAS turns the vector into tags, axes and a waveform. The dashboard never sees
the audio, and nothing needs a GPU.

An ingest panel opens with the drop. It shows, per track: what it will be
called, anything already in the library, and how far the upload and the
analysis have got. Two choices only -- **when to run** (only when you are away
from the keyboard, or now while you work) and which tracks to include. There is
no model to pick: there is one, and it runs on the CPU. The first run on a
machine downloads it (about 280 MB) and asks first.

`.ogg` is transcoded to 320k mp3, and the file you dragged is never touched.

Duplicates are refused two ways, and shown to you unticked with the reason: by
content hash, and by matching filename + duration — the second catches a
re-encode of something already held, which hashing cannot see.

**If you have no companion**, or one published before 0.8.x, the drop falls
back to the older loop: the browser uploads the files here, they land in the
library, and a base rig indexes them the next time somebody runs the drain
(`docs/INDEXERS.md`, "Music has two indexing paths now"). Nothing is lost
either way -- the fallback is the path this feature replaced, kept.

Batches survive a reload and a reboot: they live in the database, they can be
paused or cancelled from the panel (or from the tray on the machine doing the
work), and an admin can see every machine's on the fleet grid.

## Sending a cue to Resolve

The header shows the live Resolve connection and current timeline. Three buttons in the
player pane:

- **import to bin** — into the `Music` bin in the media pool. No timeline touched.
- **place underneath** — at the playhead, on the first free audio track from A2 down,
  adding a track if needed. Nothing else moves. This is the one you want almost always.
- **insert at playhead** — ripple insert on A2: clips at/after the playhead *on that
  track* shift later. It refuses if that track is linked to video, rather than silently
  desyncing sync sound.

A1 is never used, so sync audio is safe. Resolve needs
`Preferences > System > General > External scripting = Local` and a project open, and the
web app has to be running on the same machine — until port step 8 moves this into the
companion on 127.0.0.1:8899.

## Tuning the tags

`indexer/music_index/vocab.py` is the tuning surface: the label lists and their descriptive
captions. Add a label, give it 2–3 natural-language captions, run `--retag`, done. Captions
work far better than bare words — CLAP was trained on sentences.

`eval/eval.py` measures two failure modes: label bias (one label winning everywhere) and
retrieval rank. `eval.py --sweep` compares calibration settings — it re-scores the whole
library once per alpha, so it does that on a scratch COPY of the index and never on the
file that ships (MUSIC-4, 2026-08-14). `eval/validate.py` spot-checks tags against tracks
whose filenames state what they are.

## Honest limits

- Tags are a browsing aid, not ground truth. Genre and instrument are reliable; `texture`
  is the noisiest category.
- Retrieval measured 40% top-10 on a 10-query filename-derived benchmark. That understates
  real quality (the "correct" answer is inferred from a filename), but it is not 95%.
- CLAP cannot hear absolute quietness or density well. Use the arousal axis for that.
- `_stems/` is deliberately not indexed.
- Nothing here writes to `W:` — the library is read-only to this tool.
- A track added through the **companion** path has no bpm, key or loudness
  yet: those are librosa's and the companion has no librosa (KNOWN_BUGS
  MUSIC-ING-1). Everything else about it -- search, tags, axes, the waveform --
  is complete, and a base-rig `--retag` fills the rest in.

## Layout

```
SPEC.md                     the contract
web/
  musicweb/
    config.py               paths, env overrides, share->root stub
    db.py                   storage layer + thread-local connections   <- shared with the indexer
    search.py               Index: text_search / similar, lazy CLAP
    projection.py           applies the source-bias axes (query time)
    main.py                 FastAPI app + the SPA routes
    routes_api.py           stats / facets / tracks / search / similar / reload
    routes_media.py         audio (HTTP Range) / peaks
    routes_ingest.py        browser upload -> the NAS queue (the fallback path)
                            resolve + reveal are the companion's, on 127.0.0.1:8899
    routes_batches.py       the ingest panel's own API (create/list/cancel)
    routes_fleet.py         the companion's half: claim, checkpoints, result
    ingest_batches.py       every rule about what a batch or an item may become
    rescore.py              tags/axes/debias, called by both ingest paths
  static/                   index.html, app.js, style.css, ingest.js
  schema.sql                SQLite schema                              <- shared with the indexer
  migrations/               empty for now; see its README
  tests/
  data/music.db             the index
indexer/
  music_index/
    config.py               index-time settings; paths come from musicweb.config
    vocab.py                label vocabulary            <- tune here
    audio.py                ffmpeg decode + windowing
    clap_model.py           CLAP wrapper
    features.py             BPM / key / loudness
    tagging.py              vocabulary scoring
    debias.py               finds the source-bias axes (index time)
    ingest.py               drag-and-drop ingest + transcode + dedupe
  index_music.py            indexer CLI
  export_text_encoder.py    CLAP text tower -> ONNX (the container runs it)
  export_audio_encoder.py   CLAP audio tower -> ONNX (the companion runs it)
  mel_numpy.py              the log-mel front end in numpy alone      <- vendored by the companion
  music_models.py           the sidecar model catalogue: sha256, size, feed URL
  tests/                    torch-free by design; system interpreter
eval/
  eval.py                   quality measurement
  validate.py               tag spot-checks
```
