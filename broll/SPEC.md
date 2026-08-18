# B-Roll Platform — Shared Specification

Searchable b-roll library: Claude-driven visual indexing, web search UI with per-segment
hits, in/out selection, and one-click insert into DaVinci Resolve on each editor's machine.

Three components, three directories. Each component is built independently against the
contracts in this file. **Do not change a contract without updating this file.**

- `indexer/`   — Python CLI worker. Runs on the operator's Windows indexing rig
  (the base rig, in this deployment). Probes media, generates
  proxies/sprites/contact-sheets with ffmpeg, calls Claude Code headless for visual
  indexing, writes results to the database, sorts inbox clips into category folders.
- `web/`       — FastAPI app + single-page frontend. Owns the SQLite database. Serves
  search API, proxy media (HTTP range), and ingest endpoints. Deployed later as a Docker
  container on a TrueNAS server (not live yet); for now runs locally.
- ~~`companion/`~~ — Small local agent each editor runs. Listens on 127.0.0.1:8899,
  receives insert requests from the web page's JS, translates canonical paths to local
  mount paths, drives DaVinci Resolve Studio via its Python scripting API. **No longer a
  directory here.** It was absorbed into the CC Sync companion on 2026-08-10 — the fleet
  was shipping two tray apps to every editor and the small one was the one nobody
  upgraded. It now lives at `companion/src/ccsync_companion/broll_server.py` (with
  `perform_insert` in that package's `resolve_bridge.py`, which was already a fork of
  this one's). The contract below is unchanged and still authoritative.

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
  client_shares.db    # client folders + their links (docs/CLIENT_FOLDERS.md). A SEPARATE
                      # file on purpose: broll.db is replaced wholesale by an index publish
                      # and a customer's client links must survive that
```

On the NAS, `DATA_ROOT` **is** the shared archive root
(`<prefix>\Assets\B-roll Archive`), which is what lets the web app verify an
upload with a `stat()` rather than a promise — see "Dashboard ingest" below.

`.ingest/` (`app.config.ARCHIVE_INGEST_DIR`) is the one directory in that tree
that is NOT footage: it is where a companion stages dropped bytes inside the
editor's own local mirror, `<local archive root>/.ingest/<staging_id>/`. It is
named on the server side too so anything walking the archive knows to skip it.

## Database

Schema in `schema.sql` at repo root — the single source of truth. SQLite, WAL mode.
Applied on startup by the web app via `PRAGMA user_version` migrations (v1 = the
original schema, v2 = on-screen text + dual-tokenizer search; v11 = dashboard
ingest). `CREATE TABLE IF NOT EXISTS` style is NOT used.

**Four describers, one database.** `schema.sql` (fresh install, and its bundled
twin at `web/schema.sql`), `migrations/NNN_*.sql` (existing databases, copied
into `web/migrations/` and `indexer/broll_index/migrations/`), `web/app/db.py`'s
`_MIGRATIONS` and `broll_index/migrate.py`'s `_MIGRATION_STEPS` all describe the
same thing, and a version added to one and not the others produces a startup
failure on exactly one path. That has happened once; `web/tests/test_migration.py`
now compares the two paths column-for-column.

`videos.status` values: `discovered | probed | proxied | indexed | sorted |
skipped | excluded | ingesting | error`. The last three are invisible to
browse, tree and search (`search.BROWSE_PREDICATE`).

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
- `GET  /api/videos/{id}` → full video row + all segments + themes + flags. The video
  additionally carries `insert_share`/`insert_rel_path` (added 2026-08-12): the identity
  "Send to Resolve" must reference. For an archived clip that is the archive **top-slot**
  file under the `broll` share (best media, sibling of its `Proxy/` preview, found by stem
  at request time; no unique sibling → the preview itself) — NOT the ingest share, which
  only machines with a hand-written mount can translate, and which resolved to the clip's
  pre-archive location (the base rig inserted from `Z:\` and tripped the out-of-tree
  fixer, 2026-08-12). Un-archived clips carry their ingest identity unchanged.
- `GET  /api/categories` → approved taxonomy list.
- `GET  /api/shares` → `[{share, description}]` (from config) — the settings UI uses this.
- `GET  /media/proxy/{id}.mp4` — must support HTTP Range requests (seeking).
- `GET  /media/sprite/{id}.jpg`, `GET /media/poster/{id}.jpg`.
- Ingest (used by indexer when not co-located; token header `X-Ingest-Token`):
  - `POST /api/ingest/video` — upsert video row by `(share, rel_path)`, returns `{id}`.
  - `POST /api/ingest/index` — body `{video_id, themes, quality_flags, category_hint, segments:[...]}`,
    replaces existing segments for that video atomically.
  - `POST /api/ingest/moved` — body `{video_id, new_rel_path}` (category sort).

  `/api/ingest/index` computes `segments.search_norm` itself since 2026-08-18.
  It used to insert an empty one — the indexer's `HttpBackend` said search_norm
  "is not supported over the ingest API" — so anything indexed over HTTP was
  keyword-searchable only after somebody remembered to run a base-rig
  `broll-index run --stages embed`. A two-character CJK term is not findable at
  all without that blob, so the gap was silent: the clip was in the archive,
  indexed, and unreachable by the words on its own screen.
  `app/normalize.py` is `broll_index/normalize.py` vendored byte-for-byte, so
  both ends tokenise identically (`tests/test_normalize_parity.py`).

### Dashboard ingest (2026-08-18)

Drag-and-drop onto the b-roll page; the editor's own machine crunches the clips
and uploads them. Full design in `docs/BROLL_INGEST_PLAN.md`; the wire contract
is `docs/API.md` §6a. What it adds to *this* component:

- **Tables** `ingest_batches` + `ingest_items` (`migrations/011`), and
  `share_roots.collection`. That last column is why an ingested shoot browses
  under Our Footage at all: `search.creators_shares()` derives own-footage
  membership from `source='proxies'`, and an ingested camera clip archives
  ORIGINALS, so without it a customer's own footage would file under Downloads.
  NULL keeps the old rule for every share the indexer has ever pushed.
- **`videos.status = 'ingesting'`** — a row that exists but whose media is not
  on the NAS yet. Minted at claim so the name is reserved and the segments have
  somewhere to land; excluded from browse, tree and search exactly as `skipped`
  and `excluded` are (`search.BROWSE_PREDICATE`), because there is no proxy,
  poster or sprite behind it. It becomes `indexed` — and visible — only when
  `ingest_batches.mark_uploaded` has `stat()`ed the files under `DATA_ROOT` and
  found the sizes the companion declared. A cancelled batch DELETES the rows
  that never got media and leaves the `live` ones alone.
- **Two route groups**, deliberately in separate modules because they
  authenticate differently and must not learn each other's habits:
  `routes_batches.py` (`/api/ingest-batches`, the browser, identity stamped by
  the dashboard's `BrollGate`) and `routes_fleet.py`
  (`/api/fleet/ingest`, the companion, shared fleet token PLUS a signed
  identity, no session anywhere). Every rule about what a batch or an item may
  become lives once, in `ingest_batches.py`.
- **The archive name is allocated by the server**, inside the claim
  transaction, against the names already published in that folder ∪ this batch
  (`archive_names.claim_name`, lifted from `build_archive`). Two editors
  dropping the same camera card into one shoot on two machines would otherwise
  both pick `A001_C003` and the second upload would land on a file already
  recorded on another row and already cut into a timeline.
  `archive_path = <archive_dir>/Proxy/<stem>.mp4`, `archive_dir =
  <BROLL_ARCHIVE_CREATORS_DIR>/<shoot>/<sub folders>` — the same layout
  `build_archive.dest_dir` writes, so what an editor sees in search is where
  the file actually is.

### Client folders (2026-08-18)

Curated sets of clips with a token link a prospective licensee opens with no
account (`docs/CLIENT_FOLDERS.md`). What it adds to *this* component:

- **`client_shares.db`** beside `broll.db` (`app/client_folders.py`): tables
  `client_folders`, `client_folder_items`, `client_share_settings`,
  `user_version 1`. Items carry `video_id` AND `(share, rel_path)`, and are
  re-resolved by name when the id no longer matches, so a rebuilt index keeps
  its folders.
- **Two route groups**, again in separate modules for the same reason as
  ingest: `routes_client_folders.py` (`/api/client-folders`, the editor,
  identity stamped by `BrollGate`) and `routes_share.py` (`/share/{token}/…`,
  the public, read-only, token re-checked per request, an allow-list of
  `videos` columns and never a path). The static tree is mounted a second time
  at `/share/assets` so the viewer page (`static/share.html` + `share.js`,
  document-relative URLs) needs nothing outside `/share/`; that prefix is what
  the operator publishes past the tailnet.
- **`static/sprite.js`**: the sprite-sheet geometry, extracted from `app.js` so
  both pages read the sheets with one copy of the arithmetic
  (`tests/test_sprite_geometry.py` pins it against the generator).

## Companion API contract

Still authoritative; implemented since 2026-08-10 by
`companion/src/ccsync_companion/broll_server.py` (the CC Sync companion), not by a
`companion/` directory in this component tree.

`http://127.0.0.1:8899`, binds loopback only. CORS was `Access-Control-Allow-Origin: *`
until **2026-08-17**; a loopback bind is not an authorisation decision (any page in the
editor's browser is also "local"), so it is now an allow-list — see
`docs/LOOPBACK_API.md`. In short: the dashboard's own origin gets CORS headers and
nothing else does; a POST needs that origin **or** the `X-CCSync-Loopback` token, plus
`Content-Type: application/json`. This UI is served from the dashboard, so it is
unaffected — but a companion whose `dashboard_url` does not match the URL editors
actually browse will 403 every call, and says so in its log.

- `GET  /status` → `{ok, resolve_connected, mounts: {share: local_root}, version}`
- `POST /insert` — body:
  `{share, rel_path, in_frame, out_frame, fps, mode}` where frames are in **original-media
  frames** (web UI converts player seconds → frames using the video's fps from the DB),
  `mode` is `"append"` | `"playhead"` (playhead implemented 2026-08-14; before that it was
  reserved and pre-playhead companions answer it `{ok: false, "not implemented yet"}`,
  which the web UI rewrites into "update the companion").
  Behaviour: translate path via mounts config → verify file exists → connect to Resolve →
  import into bin `B-Roll/Archive` (reuse existing MediaPoolItem if already imported, matched
  by file path) → place on the current timeline. `append`:
  `AppendToTimeline([{mediaPoolItem, startFrame: in_frame, endFrame: out_frame, trackIndex: 1}])`.
  `playhead`: place at the playhead (recordFrame, absolute timeline frames) on the lowest
  overlay track ≥ V2 whose video AND audio lanes are clear across the clip's extent
  (one trackIndex serves both streams; no mediaType, so nat sound comes along), adding
  video/audio tracks when none is free; the returned item's GetStart() is verified against
  the requested frame and a misplaced clip is deleted rather than reported as success.
  → `{ok, message}` with useful error text on every failure path
  (no mount, file missing, Resolve not running, no project open, no timeline).
  **Missing-file behaviour (added 2026-08-11):** when the share is `broll` at its *derived*
  mount (no hand-written entry, not a base rig) and the companion has a working rclone
  remote, a missing file is pulled from the NAS (`<remote_root>/Assets/B-roll Archive/<rel>`
  → `<local_root>/Assets/B-roll Archive/<rel>`, single-file `rclone copyto`) instead of
  failing. While the download runs, `/insert` answers
  `{ok: false, state: "downloading", message, progress: {bytes, total_bytes, speed_bps,
  eta_seconds, percent}}`; the web UI re-POSTs the same body every ~1.5 s (the companion
  joins the running job, keyed by destination path — re-clicks never start a second rclone),
  and the poll that finds the file in place performs the ordinary insert. Terminal download
  failures come back as plain `{ok: false, message}` and the next POST retries from scratch.

Config file: `~/.broll-companion.json` → `{"server_url": "...", "mounts": {"broll": "B:/"}}`.
Unchanged by the move — editors already have this file. The `broll` share alone no longer
needs an entry: the CC Sync companion knows where the tree is and defaults it to
`<local_root>/Assets/B-roll Archive`; an explicit entry still wins. Other shares are not
derivable and still need one line each.
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
  (indexer: xxhash, pyyaml, requests; web: fastapi, uvicorn; the companion half, now in
  `companion/`: stdlib http.server only — it ships in a PyInstaller bundle — plus the
  Resolve scripting module loaded from its standard install path).
- Frontend: single-page, no build step — one `index.html` + `app.js` + `style.css`,
  vanilla JS. Dark, dense, keyboard-driven (J/K/L transport, I/O to set in/out points,
  Enter to send to Resolve). Player uses the proxy; hit markers on the seek bar.
- Tests: pytest for pure logic (path translation, hash, JSON parsing, FTS queries with a
  temp DB, frame math). Do NOT invoke live `claude`, live Resolve, or NVENC in tests —
  mock at the subprocess boundary.
- Never write outside your component directory except reading this file and `schema.sql`.
