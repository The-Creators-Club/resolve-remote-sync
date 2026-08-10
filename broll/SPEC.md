# B-Roll Platform — Shared Specification

Searchable b-roll library: Claude-driven visual indexing, web search UI with per-segment
hits, in/out selection, and one-click insert into DaVinci Resolve on each editor's machine.

Three components, three directories. Each component is built independently against the
contracts in this file. **Do not change a contract without updating this file.**

- `indexer/`   — Python CLI worker. Runs on Alex's Windows PC. Probes media, generates
  proxies/sprites/contact-sheets with ffmpeg, calls Claude Code headless for visual
  indexing, writes results to the database, sorts inbox clips into category folders.
- `web/`       — FastAPI app + single-page frontend. Owns the SQLite database. Serves
  search API, proxy media (HTTP range), and ingest endpoints. Deployed later as a Docker
  container on a TrueNAS server (not live yet); for now runs locally.
- `companion/` — Small local agent each editor runs. Listens on 127.0.0.1:8899, receives
  insert requests from the web page's JS, translates canonical paths to local mount
  paths, drives DaVinci Resolve Studio via its Python scripting API.

## Path model (load-bearing)

The DB **never stores absolute paths** for source media. Every video is identified by
`(share, rel_path)`:

- `share`: logical share name, e.g. `broll` (lowercase slug).
- `rel_path`: forward-slash relative path within that share, e.g. `military/naval/clip_0021.mov`.

Translation to a real path happens at the edge:
- Indexer config maps share → local root (e.g. `broll` → `Y:/broll`).
- Companion config maps share → local root per editor (Windows `B:/`, macOS `/Volumes/broll`).

Proxies/sprites/posters are keyed by **video id**, not path, so category-sort moves never
break them.

## Data layout (DATA_ROOT)

All generated data lives under a single configurable `DATA_ROOT` directory:

```
DATA_ROOT/
  broll.db            # SQLite database (owned by web app; indexer may write directly in
                      # co-located dev mode, or via HTTP ingest when remote)
  proxies/{id}.mp4    # 720p H.264 + AAC preview, faststart
  sprites/{id}.jpg    # sprite sheet, 1 frame / 2s, 10 columns, 240px-wide cells
  posters/{id}.jpg    # single poster frame (~640px wide)
  sheets/{id}/*.jpg   # contact sheets (indexer working files, keep for debugging)
```

## Database

Schema in `schema.sql` at repo root — the single source of truth. SQLite, WAL mode.
Applied on startup by the web app via `PRAGMA user_version` migrations (v1 = the
original schema, v2 = on-screen text + dual-tokenizer search). `CREATE TABLE IF NOT
EXISTS` style is NOT used.

**Two FTS tables, on purpose** (measured, see `docs/indexing-findings.md`):

- `segments_fts` — `porter unicode61` over `description`, `objects`, `setting`,
  `onscreen_text_en`. English stemming and precision.
- `segments_cjk_fts` — `trigram` over `onscreen_text`, `objects`. Substring matching
  for Chinese.

`unicode61` treats an unbroken run of CJK characters as ONE token, so Chinese text
indexed there is only findable by typing the entire run — partial queries return
nothing, silently. `trigram` fixes that but needs ≥3 characters and loses English
stemming, so neither tokenizer alone is sufficient. `/api/search` MUST query both and
merge by best rank, deduplicating by segment id. Two-character CJK terms (惡龍, 台北)
fall below trigram's minimum and are reachable only as discrete `objects` entries,
which `unicode61` tokenizes exactly — hence the prompt rule about proper nouns.

## Claude indexing output contract

The indexer invokes Claude Code headless (`claude -p`) with contact-sheet images and must
parse this exact JSON shape (retry once on invalid JSON):

```json
{
  "themes": ["naval exercise", "harbor", "overcast", "telephoto"],
  "category_hint": "military/naval",
  "quality_flags": ["shaky"],
  "segments": [
    {
      "t_start": 0.0,
      "t_end": 8.5,
      "description": "Grey navy frigate moored at a concrete pier, sailors on deck",
      "objects": ["navy ship", "warship", "frigate", "military vessel", "pier", "sailors"],
      "setting": "harbor, overcast daylight",
      "motion": "slow pan left",
      "onscreen_text": "華視新聞 | 警匪激烈槍戰 惡龍中彈落網",
      "onscreen_text_en": "CTS News | Fierce police shootout, suspect 'Evil Dragon' captured"
    }
  ]
}
```

`onscreen_text` is verbatim visible text in its original script (empty string if
none); `onscreen_text_en` is a short English rendering. Both are required keys.
Burned-in broadcast chyrons routinely name the event, people and place — often the
only place a clip's actual subject is stated — so they are treated as first-class
search data, not decoration. Proper nouns read from the frame must ALSO appear as
discrete entries in `objects` in both scripts (see the tokenizer note below for why
that matters).

Rules baked into the indexing prompt: objects must include synonyms and hypernyms
(that's what makes plain-text search work); segment boundaries in seconds relative to
clip start; `quality_flags` from the fixed vocabulary
`shaky | soft_focus | overexposed | underexposed | noisy | rolling_shutter`;
`category_hint` chosen from the approved taxonomy list passed in the prompt, or null
before the taxonomy exists.

## Web API contract

Base: `/api`. JSON. No auth in v1 (Tailscale-only deployment).

- `GET  /api/search?q=<text>&category=<slug>&flags=<csv>&limit=<n>&offset=<n>`
  → `{results: [{video: {...}, score, hits: [{segment_id, t_start, t_end, description, snippet}]}], total}`
  FTS5 query over segments; results grouped by video, ordered by best rank.
- `GET  /api/videos/{id}` → full video row + all segments + themes + flags.
- `GET  /api/categories` → approved taxonomy list.
- `GET  /api/shares` → `[{share, description}]` (from config) — the settings UI uses this.
- `GET  /media/proxy/{id}.mp4` — must support HTTP Range requests (seeking).
- `GET  /media/sprite/{id}.jpg`, `GET /media/poster/{id}.jpg`.
- Ingest (used by indexer when not co-located; token header `X-Ingest-Token`):
  - `POST /api/ingest/video` — upsert video row by `(share, rel_path)`, returns `{id}`.
  - `POST /api/ingest/index` — body `{video_id, themes, quality_flags, category_hint, segments:[...]}`,
    replaces existing segments for that video atomically.
  - `POST /api/ingest/moved` — body `{video_id, new_rel_path}` (category sort).

## Companion API contract

`http://127.0.0.1:8899`, CORS: `Access-Control-Allow-Origin: *` (binds loopback only).

- `GET  /status` → `{ok, resolve_connected, mounts: {share: local_root}, version}`
- `POST /insert` — body:
  `{share, rel_path, in_frame, out_frame, fps, mode}` where frames are in **original-media
  frames** (web UI converts player seconds → frames using the video's fps from the DB),
  `mode` is `"append"` (v1; `"playhead"` reserved).
  Behaviour: translate path via mounts config → verify file exists → connect to Resolve →
  import into bin `B-Roll` (reuse existing MediaPoolItem if already imported, matched by
  file path) → `AppendToTimeline([{mediaPoolItem, startFrame: in_frame, endFrame: out_frame}])`
  on the current timeline. → `{ok, message}` with useful error text on every failure path
  (no mount, file missing, Resolve not running, no project open, no timeline).

Config file: `~/.broll-companion.json` → `{"server_url": "...", "mounts": {"broll": "B:/"}}`.
On macOS, auto-detect `/Volumes/<share>` and `-1`/`-2` collision suffixes at request time.

## Indexer CLI contract

Package `indexer/`, entry point `broll-index`:

- `broll-index scan --share broll --root Y:/broll [--inbox military-inbox]` — walk tree,
  upsert `videos` rows (status `discovered`), fast partial hash (xxhash of first+last 8 MiB + size).
- `broll-index run [--model sonnet|haiku|fable] [--limit N] [--stages probe,proxy,frames,claude]`
  — drain the job queue, resumable, per-file status transitions
  `discovered → probed → proxied → indexed` (`error` + message on failure, never crash the queue).
- `broll-index taxonomy propose` — cluster all themes via one big-model Claude call,
  write `taxonomy_proposal.md` for human review.
- `broll-index taxonomy apply taxonomy.yaml` — load approved taxonomy into `categories`.
- `broll-index rebase --to-share broll --root <new root> [--apply] [--prune-duplicates]`
  — re-point an existing index at a new storage location, matching videos to their new
  paths by **content hash** (not filename or path), so proxies and Claude index passes
  survive a consolidation. Dry-run by default; writes `rebase_report.md`. Rows sharing a
  hash collapse to the best-indexed one, the rest reported as superseded and only deleted
  with `--prune-duplicates`. `--apply` requires `db.mode: sqlite` (the ingest API has no
  rename/delete endpoint). This is what makes "index the scattered archive now, consolidate
  onto the NAS later" safe.
- `broll-index duplicates [--verify/--no-verify] [--apply]` — find clips that already
  exist elsewhere in the index and mark them `duplicate_of` the canonical copy.
  **Two-stage by design:** the fast partial `hash` only produces *candidates*; the
  whole-file `full_hash` confirms them. A false positive here is not cosmetic — a
  duplicate is skipped during the NAS copy, so wrongly flagging a unique clip loses
  footage. Verification is therefore ON by default and `--no-verify` must warn.
  Canonical copy = the most-indexed one (status rank, then segment count, then lowest
  id), so existing index work is never discarded.
- `broll-index export-manifest --out <file> [--format list|robocopy|rsync]` — the
  set of files to copy to the NAS: every video EXCEPT confirmed duplicates. This is
  what makes the consolidation copy skip redundant footage.
- Duplicates are excluded from indexing (never spend model calls on them), from
  search results, and from the copy manifest — but their rows are kept, so the index
  still knows every location a given clip exists at.
- `broll-index sort [--dry-run]` — for videos under the inbox root with a category:
  move file to `share/<category>/…`, update DB (direct or `/api/ingest/moved`), atomic per file.
- Config `indexer/config.yaml`: shares→roots, DATA_ROOT, db mode (`sqlite` path | `api` url+token),
  model default, sampling params.

ffmpeg specifics: proxy = `-vf scale=-2:720 -c:v h264_nvenc -preset p4 -cq 26 -c:a aac -movflags +faststart`
(fallback libx264 if NVENC unavailable — detect once at startup). Scene sampling: ffmpeg
`select='gt(scene,0.3)'` frames, plus fill so max gap ≤ 4 s. Contact sheets: 3×3 tiles,
384px cells, timecode `HH:MM:SS` burned bottom-left per cell (drawtext), jpeg q=4.

Claude invocation: `claude -p <prompt> --output-format json --model <model>` with the
contact-sheet file paths listed in the prompt for Claude to Read. Long clips: window at
~36 frames (4 sheets) per call, merge segment lists. The model flag maps
haiku→claude-haiku-4-5-20251001, sonnet→claude-sonnet-5, fable→claude-fable-5.

## Conventions

- Python 3.12, type hints, `pyproject.toml` per component, minimal deps
  (indexer: xxhash, pyyaml, requests; web: fastapi, uvicorn; companion: stdlib http.server
  or flask + the Resolve scripting module loaded from its standard install path).
- Frontend: single-page, no build step — one `index.html` + `app.js` + `style.css`,
  vanilla JS. Dark, dense, keyboard-driven (J/K/L transport, I/O to set in/out points,
  Enter to send to Resolve). Player uses the proxy; hit markers on the seek bar.
- Tests: pytest for pure logic (path translation, hash, JSON parsing, FTS queries with a
  temp DB, frame math). Do NOT invoke live `claude`, live Resolve, or NVENC in tests —
  mock at the subprocess boundary.
- Never write outside your component directory except reading this file and `schema.sql`.
