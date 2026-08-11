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
cd music\web;  .venv\Scripts\python.exe -m pytest tests -q
```

## Re-index after adding music (base rig only — it needs the RTX 3080)

```powershell
cd music\indexer
python index_music.py           # new/changed files only
python index_music.py --retag   # re-score after editing music_index\vocab.py
python index_music.py --peaks   # backfill missing waveforms
python index_music.py --force   # rebuild everything
python index_music.py --queue --db ..\..\nas-index\music.db   # drain what editors uploaded
```

Queued uploads are the one case that does **not** work against the local index: the
`pending` rows live in the NAS's copy of `music.db`, so `--queue` needs `--db` pointed at
a copy pulled down from there, and the drained copy pushed back afterwards
(`web/DEPLOY.md`, "Draining the NAS ingest queue").

Indexing is resumable and skips unchanged files by size+mtime. A full rebuild of 376
tracks takes ~9 min on the RTX 3080. `--retag` takes seconds because it re-scores from
stored embeddings without touching audio.

The indexer writes `music/web/data/music.db` — the database lives with the tree that gets
shipped to the NAS. It imports `musicweb.db` and `web/schema.sql` rather than keeping its
own copy, so the writer and the reader cannot drift.

After re-indexing while the server is running: `curl -X POST localhost:8790/api/reload`.

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

**Drag audio files anywhere onto the page.** They are copied into the library,
analysed, tagged and indexed, and appear as "Just added". `.ogg` is transcoded to 320k
mp3; the file you dragged is not touched.

Duplicates are refused two ways: by content hash, and by matching filename + duration —
the second catches a re-encode of something already held, which hashing cannot see.

This needs the indexer (GPU + ffmpeg), so it only works on the base rig; anywhere else
`/api/ingest` answers 503. Port step 7 turns it into a queued handoff.

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
retrieval rank. `eval.py --sweep` compares calibration settings. `eval/validate.py`
spot-checks tags against tracks whose filenames state what they are.

## Honest limits

- Tags are a browsing aid, not ground truth. Genre and instrument are reliable; `texture`
  is the noisiest category.
- Retrieval measured 40% top-10 on a 10-query filename-derived benchmark. That understates
  real quality (the "correct" answer is inferred from a filename), but it is not 95%.
- CLAP cannot hear absolute quietness or density well. Use the arousal axis for that.
- `_stems/` is deliberately not indexed.
- Nothing here writes to `W:` — the library is read-only to this tool.

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
    routes_ingest.py        ingest / resolve / reveal   (the write routes)
    resolve_link.py         spawns the Resolve worker with a timeout   <- port step 8
    resolve_worker.py       the actual Resolve calls (child process)   <- port step 8
  static/                   index.html, app.js, style.css
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
eval/
  eval.py                   quality measurement
  validate.py               tag spot-checks
```
