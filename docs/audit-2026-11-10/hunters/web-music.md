# web-music - music/web: the CLAP music search app mounted at /music (musicweb/ + static/)

Files read (approximate coverage): musicweb/main.py, search.py, text_encoder.py, db.py,
routes_api.py, routes_media.py (all 100%); routes_fleet.py (~70%), ingest_batches.py (~45%:
naming, leases, reserved names, result path), routes_ingest.py (grep + handler shapes),
config.py (paths, proxies); static/app.js (~95%), static/ingest.js (polling + structure),
schema.sql, migrations/004; for wire/duplication checks: broll/web/app/ingest_batches.py,
broll/web/static/ingest.js, dashboard music.py (mount), companion music_server.py (status
probe), server/install_dashboard_app.py (music-proxies bind), music/web/DEPLOY.md.

Probes run (all under the scratch folder `...\scratchpad\web-music\`, music/web venv):
- `probe_encoder.py`: cold load, process working set and query latency of the real
  exported ONNX text tower (artefact only, no music.db).
- `probe_index.py`: synthetic music.db at 5,000 and 50,000 tracks x 12 windows x 512 dims;
  `search.Index` build time, tracemalloc held/peak, `text_search` (max/mean) vs a
  vectorised equivalent (top-60 verified identical), `similar`.
- `probe_routes.py`: `stats`, `facets`, `tracks` on the same synthetic DBs + EXPLAIN QUERY PLAN.
- `probe_ledger.py`: `reserved_names` / `db._name_promised` over 100,000 synthetic
  `ingest_items` rows.
- AST diff of the 29 same-named functions in music vs broll `ingest_batches.py`.

## Findings

### web-music-1 - An open /music tab spawns a Resolve worker child on the editor's machine every 30 s, forever
- Category: idle
- Severity: medium
- Confidence: CONFIRMED
- Where: music/web/static/app.js:1032 (`setInterval(refreshResolveStatus, 30000)`), app.js:424-441; companion music_server.py:221 (`PROBE_TTL_S = 3.0`), :297-306, :156-200 (`call` = `subprocess.run` of the frozen exe as a worker)
- What: The status dot polls `GET 127.0.0.1:8899/music/status` every 30 s from page load until the tab closes, with no visibility check and regardless of whether a player pane is open. Each call is answered by `cached_probe`, whose TTL is 3 s, so every 30 s tick misses the cache and `subprocess.run`s the companion exe re-entered as a Resolve worker that calls `resolve_bridge.connect()`.
- Cost / failure scenario: 120 child processes per hour per open music tab (hidden tabs are throttled to ~1/min by Chrome, so still ~60/h), each a frozen-companion start (CR-107's own note: ~80 MB each; PRAC-77: the exe is onefile) plus one scripting connection to fuscript, on the machine whose CPU/RAM Resolve needs. An editor who leaves the music page open in a tab all day = ~500-1,000 worker spawns for a dot nobody is looking at. Measured: the cadence and TTL by reading; per-spawn cost estimated from CR-107/PRAC-77 (not measured, the live companion is off limits).
- Evidence: app.js has no `visibilitychange`/`document.hidden` anywhere; `refreshResolveStatus` is also called after every send (app.js:387), the only time the answer matters.
- Ledger: related to CR-107 (fixed the burst of <img> probes, not the steady cadence); related to PRAC-77 (open)
- Suggested change: Poll only while the document is visible AND a player pane is open (start on `openPane`, stop on `closePane`/`visibilitychange`), keeping the post-send refresh; optionally have the companion answer `/music/status` from its in-process Resolve watcher state instead of a child. Must not break: the CR-68 rule (one `scriptapp()` caller) and the CR-107 single-flight slot.
- Effort / risk: S effort; low risk

### web-music-2 - Fleet-ingested tracks never get a preview proxy, so every preview streams the ~60 MB original, and replays re-download it
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: musicweb/routes_media.py:82-103 (`audio_source`), :145-179 (206 path); server/install_dashboard_app.py:3610 (`music-proxies:/music-proxies:ro`); musicweb/routes_fleet.py (no proxy route); music/web/DEPLOY.md:202
- What: A proxy is used only if `<PROXIES_DIR>/<id>.mp3` exists. That directory is a read-only bind filled by a base-rig push, and neither the fleet ingest path (companion -> `/batches/.../result` + `uploaded`) nor the container creates one, so every track added through the companion since 2026-08-18 previews from its original. Browsers always open `<audio>` with `Range: bytes=0-`, which goes down the StreamingResponse branch, which sends no `ETag`/`Last-Modified`/`Cache-Control`, so nothing about the response is reusable and a second click re-fetches it.
- Cost / failure scenario: DEPLOY.md's own figure is "streams the 60 MB originals over Tailscale"; a 128k proxy of the same 4-min cue is ~3.8 MB, so ~15x the bytes per preview for every fleet-added track, every time it is clicked, to every remote editor, until someone re-runs make_proxies on the base rig and re-pushes 864+ MB. At commercial scale (no GPU base rig, bug-music-5) that is never.
- Evidence: grep: no writer of `proxy_path` outside the base-rig indexer; the bind is `:ro`; `chunks()` response headers carry only Accept-Ranges/Content-Length/Content-Range/X-Audio-Source.
- Ledger: new (related to bug-music-5, open; bug-music-7 is about stale proxies, not missing ones)
- Suggested change: Have the companion (which already runs ffmpeg for the .ogg transcode) upload a 128k proxy beside the original, or let the container's ffmpeg build one into a writable proxies dir on first `uploaded`; and add a strong `ETag` (size+mtime_ns+id) and `Cache-Control: private, max-age=86400` to both audio branches so a replay is a cache hit. Must keep the rule that a Range is never answered from the other file (proxy vs original) and the id-reuse guard (music-4: the ETag must include mtime/size).
- Effort / risk: M effort; low risk

### web-music-3 - The ONNX text tower holds ~560 MB in the dashboard process for its whole life after one search
- Category: leak
- Severity: medium
- Confidence: CONFIRMED
- Where: musicweb/search.py:176-188 (`shared_encoder`, module global, never released); text_encoder.py:242-268
- What: The encoder is lazy (good: import of `musicweb.search` costs 0.10 s and ~30 MB, dashboard boot is unaffected), but once any editor runs one text search the ~500 MB fp32 InferenceSession stays resident in the single dashboard process until restart; there is no idle unload. Music search is an occasional, bursty activity.
- Cost / failure scenario: Measured with the real artefact: working set 31 MB -> 592 MB after load (peak 744 MB during load), cold load 0.67 s (warm file cache), 9.2 ms per query. So one search a week pins ~560 MB for the week, in the container that also runs the fleet dashboard, Cards engines and b-roll's semantic index. On a small NAS (8-16 GB, ZFS ARC) that is the largest single resident consumer music adds.
- Evidence: `probe_encoder.py` output: `import musicweb.search: 0.10 s ws 31.5 MB`; `cold load 0.67 s ws 592 MB private 1344 MB peak 744 MB`; `median of 40 9.2 ms`.
- Ledger: new (bug-music-2's fix list suggests pre-warming at mount, which would make this unconditional - do not)
- Suggested change: Drop `_encoder` after N minutes without a query (a timestamp checked under `_encoder_lock` by the next search, or a single daemon timer), accepting a ~0.7-2 s first query after idle; optionally try `SessionOptions.enable_cpu_mem_arena = False`. Must keep MUSIC-5/MUSIC-8 single-flight (one load under the lock) and must not unload while a request holds the reference (callers keep the object they got, so dropping the global is safe).
- Effort / risk: S effort; low risk

### web-music-4 - The search index costs ~27 KB/track resident and ~2x that on every rebuild: 1.34 GB held and 2.84 GB peak at 50k tracks, with no single-flight
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: musicweb/db.py:337-358 (`load_matrix`, `load_window_matrix`: `fetchall()` then `np.stack` of per-row `frombuffer`); search.py:24-41, 257-270 (`refresh` builds outside the lock, no in-flight guard); routes_fleet.py:133-148, 251-254, 172
- What: Up to 12 window vectors per track are held as one float32 matrix (12 x 512 x 4 B = 24 KB/track) plus the track matrix. The loaders materialise every row as a Python `sqlite3.Row` with its blob before stacking, so the build peaks at ~2.1x the result, and `refresh()` builds a NEW index while the old one is still live (another +1x). Nothing stops two refreshes at once: a fleet `result` refresh, `_settle_scores` at release, a search tripping `_looks_stale`, and `/api/reload` all build independently.
- Cost / failure scenario: Measured on synthetic DBs: 5k tracks: build 0.76 s, held 134 MB, peak 284 MB. 50k tracks: build 8.2 s, held 1,342 MB, peak 2,843 MB (plus the old index still referenced -> ~4.2 GB transient in the worst case, more if two builds overlap). Today's ~400 tracks: ~11 MB, harmless. A commercial customer with a 50k-cue production library would OOM a small NAS on the first fleet ingest batch. bug-music-6 (open) means every heartbeat-induced rebuild pays this too.
- Evidence: `probe_index.py`: `Index build 8.18 s; held 1342 MB, peak during build 2843 MB; win_mat 1229 MB track_mat 102 MB`.
- Ledger: related to bug-music-6 (open; the revision-counter fix there removes most rebuilds but not the size) and PL-RES-75 (b-roll's twin, which says "check the music CLAP index too" - this is that check)
- Suggested change: Fill a preallocated array from a streaming cursor (`SELECT COUNT(*)` then `np.empty((n, d))` and copy row by row: peak ~= held); serialise `refresh` behind one in-flight lock that later callers wait on instead of building again; consider float16 storage for `win_mat` (halves it; verify top-k on the eval set first). Append-only for a single fleet result is the bigger win but needs the delete path (prune, `_drop_unlanded_tracks`) to force a full rebuild.
- Effort / risk: M effort; low risk (streaming + single-flight), medium (float16, needs the eval)

### web-music-5 - Text search pools window scores in a Python loop: 4x slower than numpy at scale
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: musicweb/search.py:116-127
- What: After one matmul, `pool='max'` walks every window in Python (`for tid, s in zip(...)` with a dict update) and `pool='mean'` does the same per track, then sorts the whole dict to take 60.
- Cost / failure scenario: Per search (every editor query and every filter change under a query). Measured: 5k tracks: 10 ms (max) / 2 ms (mean) vs 3.2 ms vectorised; 50k tracks: 108 ms / 25 ms vs 26.3 ms vectorised, of which 22.7 ms is the matmul itself. The loop is ~80 ms of GIL-holding Python per query on the dashboard's single worker at 50k. Negligible today (~400 tracks).
- Evidence: `probe_index.py`; the vectorised version (`np.maximum.reduceat` over `win_tids` boundaries, which are sorted by `ORDER BY track_id, idx`, then `argpartition` for k) returned the identical top-60 ids.
- Ledger: new
- Suggested change: Replace both loops with reduceat + argpartition; keep the ids as Python ints on the way out (the comment at :113-115 about numpy int64 binding still applies).
- Effort / risk: S effort; low risk

### web-music-6 - An open player pane redraws the waveform and rewrites two DOM nodes 60 times a second, even when paused
- Category: idle
- Severity: low
- Confidence: CONFIRMED
- Where: music/web/static/app.js:253-260 (`tick`), 146-180 (`drawWave`)
- What: `tick` re-arms `requestAnimationFrame` unconditionally while `state.playing === t.id`, so a pane left open on a paused track repaints the whole canvas (clear + one `fillRect` per 3 px of width) and assigns `time.textContent` and `pbtn.textContent` every frame, which invalidates layout each frame.
- Cost / failure scenario: 60 wakeups/s (120 on a 120 Hz monitor) for as long as the tab is visible with a pane open, typically on the editor's second monitor beside Resolve. Estimated well under 1 ms CPU per frame, but it keeps the compositor and the GPU awake for a paused player. Hidden tabs stop rAF, so the cost is bounded to visible time.
- Evidence: code reading; nothing in `tick` checks `a.paused`.
- Ledger: new
- Suggested change: Run the loop only between `play` and `pause`/`ended` events (start on `playing`, stop on `pause`), and paint once on seek/resize/peaks arrival as it already does; write the text nodes only when the displayed second changes.
- Effort / risk: S effort; low risk

### web-music-7 - The SPA's 205 KB of static files are re-read from disk and re-sent uncompressed on every /music load
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: musicweb/main.py:47-92; routes_media.py:182-187 (`/api/peaks`)
- What: Each static route `read_text()`s the file per request and returns a bare `Response` with no `ETag`, `Last-Modified` or `Cache-Control`, and the dashboard has no gzip middleware (PRAC-72), so every page load downloads app.js 44 KB + ingest.js 62 KB + style.css 71 KB + cc_spa.js 14 KB + index.html 13 KB = 205 KB. `/api/peaks/{id}` (900 bytes, immutable for an id until a prune) is also uncached, so reopening a track refetches it after a reload.
- Cost / failure scenario: Per /music page load per editor: ~205 KB over Tailscale and 5 file reads on the single worker; with validators it would be 5 x 304s (~2 KB). Small per load, but it is the whole SPA every time.
- Evidence: code reading; `wc -c static/*`.
- Ledger: related to PRAC-72 (open, dashboard-wide compression)
- Suggested change: Serve these five through the dashboard's `static_files.py` pattern (validators + `Cache-Control: no-cache`), or add an ETag from mtime+size; keep the document-relative URLs and the pinned content types (tests/test_mounted_prefix.py, test_api.py). Give peaks a `private, max-age` + ETag that includes the row's track rel_path or a hash, so music-4's id reuse cannot serve a stale waveform.
- Effort / risk: S effort; low risk

### web-music-8 - Every metadata read scans the tracks table with its 2 KB embedding inline, and browse sorts without an index
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: schema.sql:16-37 (`tracks.embedding BLOB` inline), routes_api.py:57-100 (`stats`: 3 scans; `facets`: SUM over tracks), :180-206 (`tracks`: `ORDER BY t.filename` / `t.analyzed_at`)
- What: The 2 KB vector lives in every `tracks` row, so `COUNT(*)`, `SUM(duration)`, `SUM(bytes)`, `SUM(bpm IS NULL)` and the browse scan all read every vector page; browse uses a temp B-tree (EXPLAIN: `SCAN t` + `USE TEMP B-TREE FOR ORDER BY`) because `filename` and `analyzed_at` have no index.
- Cost / failure scenario: Each page load runs stats + facets + tracks. Measured: 5k tracks 8 / 9 / 11 ms; 50k tracks 93 / 94 / 101 ms (newest: 146 ms), i.e. ~290 ms of single-worker time per /music page load at 50k, and again after every batch completion (`refreshLibrary`).
- Evidence: `probe_routes.py` output and EXPLAIN QUERY PLAN.
- Ledger: new
- Suggested change: Cheapest safe step: one aggregate query for stats, plus covering indexes `tracks(filename)` and `tracks(analyzed_at)` (and `(duration, bytes, bpm)` for the sums) in schema.sql, which is CREATE ... IF NOT EXISTS and needs no migration. Moving the embedding out of `tracks` is the real fix but is a migration the indexer shares.
- Effort / risk: S effort; low risk (indexes) / M, medium (moving the column)

### web-music-9 - The ingest-batch lease machinery exists twice (music and b-roll) and is kept in step by hand
- Category: streamline
- Severity: low
- Confidence: CONFIRMED
- Where: music/web/musicweb/ingest_batches.py (1,336 lines) vs broll/web/app/ingest_batches.py (1,410 lines); music/web/static/ingest.js (1,543) vs broll/web/static/ingest.js (1,963)
- What: 29 functions share a name; 11 are byte-identical after stripping docstrings (`lease_live`, `heartbeat`, `_check_transition`, `new_uid`, `set_upload_paused`, ...), and the lease/cancel/expiry set (`expire_stale_leases`, `cancel`, `cancel_requested_for`, `retry_failed`, `_recount`, `list_batches`) differs only in log text, type hints and the b-roll-only `proxies_live` state. The ledger shows fixes landing as "twins" (music-1's twin, bug-broll-4 music twin, bug-music-ytdl-2). They have NOT drifted in behaviour today (the 2026-09-18b cancelled-lease fix is in both). The two ingest.js files share 43 function names but only 29% of their lines, so they have already diverged and are not worth merging.
- Cost / failure scenario: Every lease/claim/cancel fix is two edits, two test files and two reviews; the ~300 lines of lease code are where three twin fixes have already been needed. Saving: ~300 lines and one class of "fixed on one side" bug.
- Evidence: AST diff of the 29 same-named functions (scratch `ingest_batches` comparison).
- Ledger: new
- Suggested change: Only if a third ingest kind arrives: lift the lease state machine (lease_live, heartbeat, expire_stale_leases, cancel*, _check_transition, now_iso/_parse_iso, new_uid) into one stdlib-only module vendored into both trees with a test that pins the two copies byte-equal, rather than a shared import (the two apps deploy separately and `app` vs `musicweb` packaging is load-bearing per CLAUDE.md).
- Effort / risk: M effort; medium risk

### web-music-10 - The ingest ledger is never pruned, and the name checks scan all of it on every result
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED
- Where: musicweb/ingest_batches.py:360-366 (`reserved_names`), :963 (called per item `result`), :493 (per precheck); db.py:557-578 (`_name_promised`, `lower(dest_name)` per candidate x 3 spellings)
- What: Nothing deletes `ingest_batches`/`ingest_items` rows. `reserved_names` is documented as "every name an unlanded item has already been promised" but its filter keeps `live` items (landed for good), so it returns every name ever ingested; `lower(dest_name)` defeats any index.
- Cost / failure scenario: Measured at 100,000 ledger rows: `reserved_names` 54 ms per call, `_name_promised` 11.8 ms per candidate (x up to 3 spellings, x collisions). One `reserved_names` runs per item result, so a 500-track drop at that ledger size spends ~27 s of single-worker time on it. Today's ledger is hundreds of rows: negligible; 100k rows is several years of a 20-editor customer.
- Evidence: `probe_ledger.py`.
- Ledger: new
- Suggested change: Add `'live'` to the excluded states in both places (a landed name is already covered by the `tracks` and disk checks; confirm with the music-3 / bug-music-ytdl-2 tests) and add a partial expression index `ON ingest_items(lower(dest_name)) WHERE state NOT IN (...)`; optionally age out terminal batches older than N months.
- Effort / risk: S effort; low risk

## What is already good
- The text encoder is lazy and single-flight (MUSIC-5/8): importing musicweb costs 0.10 s and ~30 MB, so the /music mount adds nothing measurable to dashboard boot; a query is 9 ms.
- One shared `<audio>` element for the whole list; peaks are fetched only for the opened row and cached (900 B each); list renders use a DocumentFragment; the ingest panel's four pollers run only while the panel is open and are all cleared on close.
- The stale check is rate-limited to one `stat` pair per 2 s, and Index swaps are a single rebind (MUSIC-10) - the problem is what a rebuild costs, not the swap.
- Range handling is correct (suffix, open-ended, invalid-ignored, 416, HEAD) and the streaming generator's `with open()` closes the handle when Starlette drops it on disconnect.
- `similar` is 3.4 ms at 50k tracks; leave it.

## Coverage note
drain.py, rescore.py, routes_ingest.py's inline/queued upload path, identity.py/fleet_auth.py and most of ingest.js's rendering were read only by grep; staging-file cleanup under DATA_ROOT/staging was not traced. No headless-browser listener count was taken (the rAF finding is from code reading).

## OUT OF TERRITORY
- companion/src/ccsync_companion/music_server.py:221: `PROBE_TTL_S = 3.0` cannot absorb a 30 s poller; the status could come from the in-process Resolve watcher instead of a worker child (pairs with web-music-1).
- broll/web/app/semantic.py: PL-RES-75's streaming/single-flight fix and web-music-4's are the same change; do them together.
