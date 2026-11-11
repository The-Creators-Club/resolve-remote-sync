# web-broll - the b-roll search app mounted at /broll (broll/web: app/ and static/)
Files read (approximate coverage): app/search.py (all), app/semantic.py (all), app/fuzzy.py (cache + correction half), app/db.py (all), app/media.py (all), app/routes_media.py (all), app/routes_share.py (all), app/client_folders.py (schema, connections, items, resolve, ~60%), app/routes_client_folders.py (list route), app/routes_api.py (all), app/main.py (all), app/ingest_batches.py (name allocation, function map), schema.sql (all); static/app.js (search, grid, card, detail wiring, ~45%), static/sprite.js (scrub), static/share.js (grid), static/ingest.js (polling, upload), static/clientfolders.js (card hook, popover load), style.css (sprite overlay rules only).
Probes run (all under scratchpad\web-broll\, broll/web's own venv, nothing live touched):
- `probe_search.py`: synthetic broll.db built with the real schema.sql at 5k and 50k clips, real per-clip ratios from the 2026-08-14 live measurement (3.5 segments, 2 transcript cues, 5.5 embeddings of dim 384 per clip; 5k -> 27,464 embeddings, 50k -> 274,950), fake encoder injected the way the suite does; timed browse, keyword, hybrid, semantic, fuzzy, each component, plus `tracemalloc` over the semantic index build and `EXPLAIN QUERY PLAN` on the cache-key queries.
- `p_share.py`: client_shares.db with one 500-clip folder against the 50k index, `_member_id` timed per card with stored ids intact and after a simulated renumbering rebuild.
- `p_tree.py`: `/api/tree` and `/api/videos/{id}` at 5k and 50k.
- Sprite / poster sizes: `ls -l` of the 12,101 sheets in `E:\broll-queue\sprites` and 12,110 posters in `E:\broll-queue\posters` (file sizes only, no DB opened).

## Findings

### web-broll-1 - A public share link costs a full-folder re-resolve on EVERY media request once the index has been renumbered, and never heals
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: broll/web/app/routes_share.py:95-111 (`_member_id`), app/client_folders.py:795-818 (`member_video_id`), :907-977 (`resolve_items` / `public_video_ids`)
- What: `_member_id` first asks `member_video_id`, which looks the item up by its STORED `video_id`; the page, though, asks with the CURRENT id (`resolve_items` puts `v["id"]` in each card). After a rebuild that renumbers `videos.id` (the premise the module documents for publish_db.py) the two never agree again, so every poster, sprite, detail and proxy Range request falls through to `public_video_ids`, i.e. `resolve_items` over the whole folder (1-2 `SELECT *` per item). Nothing rewrites `client_folder_items.video_id` on the read path (only `add_items` -> `_rekey_stale_item`, and `_refresh_item_path` updates rel_path only), so the slow path is permanent for every folder made before the rebuild.
- Cost / failure scenario: measured on the 50k index, 500-clip folder (MAX_ITEMS): `_member_id` 0.01 ms per card with ids intact, 9.0 ms per card after renumbering; one page open = 500 posters + 500 sprites (see web-broll-2) = 1,000 requests x 9 ms = ~9 s of dashboard threadpool CPU, ~1,000,000 SQL statements, repeated on every open (media is `no-cache`, so a return visit revalidates every file through the same gate) and on every Range request while the client plays a clip. The route is the anonymous, Funnel-published door, so anyone holding a link can repeat it at will inside the one dashboard process. Each request also pays `get_shares_db` -> `ensure_schema_best_effort` (mkdir + connect + 2 PRAGMAs, 0.35 ms) and opens two SQLite connections.
- Evidence: p_share.py: shift=0 -> 3 ms for all 500 cards; shift=100000 (stored ids no longer current) -> 4,594 ms for the same 500 `_member_id` calls.
- Ledger: new (related to broll-1 2026-08-21 / MEDIA-1, whose correctness fixes this keeps)
- Suggested change: heal on read: when `resolve_items` (or the `_member_id` fallback) resolves an item by name or hash to a current id that is free in that folder, write that id back to `client_folder_items.video_id` (the move `_rekey_stale_item` already does, best effort like `_refresh_item_path`), so the next request takes the one-lookup path. Keep the per-request `_live_folder` token/revoke check and the (share, rel_path) identity check exactly as they are; this only changes which id is stored.
- Effort / risk: S effort; low risk (the rekey rule and its UNIQUE handling already exist and are tested)

### web-broll-2 - Every card downloads its full hover-scrub sprite sheet up front, hovered or not; the share page does it for the whole folder at once
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: broll/web/static/app.js:956-958 (`buildCard`), static/share.js:240-242 (`shareCard`), static/style.css:640-650
- What: the sprite overlay's `background-image` is set when the card is built. It sits at `opacity: 0` until hover, and opacity does not stop a browser fetching a background image (only `display: none` does), and a CSS background has no `loading="lazy"`. So every rendered card pulls its whole sheet immediately, while the 10x smaller poster beneath it is the only lazy image. In search mode the static hit frame is a deliberate use of the sheet; in browse mode and on the client share page nothing shows it until a pointer arrives.
- Cost / failure scenario: sheet sizes across the 12,101 real sheets: median 58 KB, mean 215 KB, p90 613 KB, max 4.2 MB (posters average 23 KB). A 24-card browse page = ~5.2 MB of sprite bytes against ~0.55 MB of posters, on every folder click and pager step, over Tailscale. The client share page renders every item at once (`shareRenderGrid`), so a 500-clip folder pulls ~107 MB on open through the Funnel, multiplied by web-broll-1's per-request cost.
- Evidence: read of the three files above; sizes from `ls -l E:\broll-queue\sprites` (sum 2.6 GB / 12,101).
- Ledger: new
- Suggested change: set `backgroundImage` on the first `pointerenter` inside `wireSpriteScrub` (sprite.js, shared by both pages) for browse cards and share cards; keep the eager assignment only for search cards with a `sprite-static` hit frame (or defer those with one IntersectionObserver). Must not break BROLL-1's geometry (the cell height is still computed from the row, not the image).
- Effort / risk: S effort; low risk

### web-broll-3 - The semantic index rebuild peaks at about three times the matrix in the one dashboard process, on every search_generation bump
- Category: leak
- Severity: medium
- Confidence: CONFIRMED
- Where: broll/web/app/semantic.py:229-250 (`_ensure_index`)
- What: the rebuild does `fetchall()` of every `(source, source_id, video_id, dim, vec)` row (all vector blobs held at once as Python bytes), then allocates the full float32 matrix and copies into it, while `self._index` still holds the previous matrix until the final assignment. Peak is therefore old matrix + all blobs + new matrix + a Python tuple per row.
- Cost / failure scenario: measured at 50k clips (274,950 embeddings): matrix 422 MB, `tracemalloc` peak 951 MB for a first build (no old index); a rebuild adds the old 422 MB on top, ~1.37 GB transient. Today's live archive (82,889 rows, 127 MB matrix per the 2026-08-14 measurement) is therefore ~290 MB first build and ~415 MB per rebuild, and a rebuild follows every write that bumps `search_generation` (each `/api/ingest/index` post, each indexer write), in the container that also hosts the dashboard, music, ytdl and Cards. Build time 4.0 s at 50k, during which every semantic/hybrid query waits on `self._lock`.
- Evidence: probe_search.py: "first index build ms 4045.6; index build traced MB cur/peak 473.4/951.0; matrix MB 422.3" (50k); 5k: 42 MB matrix, 95 MB peak.
- Ledger: related to bug-hunt-2026-08-14 (corpus-wide invalidation granularity, which is about HOW OFTEN this runs; this finding is about what each run costs)
- Suggested change: iterate the cursor instead of `fetchall()`, preallocating `np.empty((count, dim))` from the `count` the key already computed and `np.frombuffer` straight into each row; drop the old index reference before the build (queries are blocked on the lock anyway). That takes the peak from ~3x to ~1x. Storing the matrix as float16 (cast at load, dot in float32) would halve the resident 127-422 MB if the 9/9 top-1 check still holds; measure before adopting.
- Effort / risk: S effort; low risk (cache key and invalidation untouched)

### web-broll-4 - Fixed per-search overhead: two full COUNTs over embeddings, every visible video id into a Python set, and a Python-level mask, before the matmul
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/app/semantic.py:150-174 (`availability` -> `_count_for_model`), :207-225 (`_ensure_index` key), :329-339 (mask); app/search.py:922-940 (`_allowed_video_ids`); app/routes_api.py:363-364 (`mode_availability` on every /api/search)
- What: every `/api/search` (browse, keyword and every pager click included) runs `mode_availability`, which does `SELECT COUNT(*) FROM embeddings WHERE model = ?` only to learn whether the count is non-zero. Every hybrid/semantic query then does the same COUNT again for the cache key, materialises `SELECT id FROM videos v WHERE <BROWSE_PREDICATE...>` into a Python set even when no filter is active, and builds the mask with a Python generator over every embedding row. Paging re-runs the whole fused search for each page.
- Cost / failure scenario: at 50k clips: COUNT 25.9 ms (covering index scan; MAX(rowid) is 0.0 ms), `_allowed_video_ids` 34.9 ms, Python mask 8.5 ms, the actual matmul 8.3 ms; hybrid "taiwan" 117 ms, page 5 of the same query 166 ms; browse page 9 ms of which the availability COUNT is a share. At 5k: hybrid 11.6 ms. Today (15k clips / 83k embeddings) estimated ~30 ms per hybrid search, ~8 ms of COUNT on every browse page. Not a cliff, but the matmul it exists for is under a tenth of it.
- Evidence: probe_search.py timings above; mode_availability shows 0.1 ms in the probe only because fastembed is not installed in this venv (it returns before the COUNT), production has it.
- Ledger: new
- Suggested change: `availability` -> `SELECT 1 FROM embeddings WHERE model = ? LIMIT 1` (same boolean, ~0 ms). Keep the count in the cache key (belt and braces, KNOWN_BUGS R2) but it could then be the only COUNT. Cache the index's video_id and source columns as numpy arrays at build time and mask with `np.isin(vid_col, allowed_array)`; skip `_allowed_video_ids` entirely when only BROWSE_PREDICATE is in force by precomputing that mask per (index key, max videos rowid).
- Effort / risk: S effort; low risk

### web-broll-5 - Thumbnails and sprites that never change carry no Cache-Control, so every grid render revalidates every image
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/app/media.py:64-69, app/routes_media.py:50-59; static/app.js:943, 957
- What: editor-side `/media/poster` and `/media/sprite` answer with an ETag only: no `Cache-Control`, no `Last-Modified`, so a browser has no heuristic freshness and must send a conditional request for each image every time a card is drawn. Nothing in the dashboard mount adds a header (grep of broll.py/app.py).
- Cost / failure scenario: 24 posters + 24 sprites = 48 conditional round trips per page render (folder click, pager, back from detail), each through the dashboard's login gate and Tailscale, for files written once by the indexer. Estimated tens to a few hundred ms of extra latency per render on a remote editor's link.
- Evidence: read of media.py headers; the share side's `no-cache` is deliberate (MEDIA-22) and is not this finding.
- Ledger: new
- Suggested change: version the editor-side URLs with what identifies the file (`?v=<videos.hash>-<sprite_cells>`, both already in the row the grid holds) and answer them `Cache-Control: private, max-age=31536000, immutable`. Safe under an id-renumbering rebuild because the version changes with the clip. Leave the `/share/` media headers exactly as they are.
- Effort / risk: S effort; low risk

### web-broll-6 - The detail route lists the archive folders twice per open
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/app/routes_api.py:412 and :416 (`get_video` -> `_insert_target` -> `insert_target_detail`, then `_insert_object` -> `insert_target_detail` again)
- What: `insert_target_detail` does two `os.listdir` calls (the top-slot folder and its `Proxy/`) plus an NFC normalise per entry and `is_file` per match; `get_video` calls it twice for the same row to fill `insert_share`/`insert_rel_path` and then `insert`.
- Cost / failure scenario: 4 listdirs instead of 2 per clip opened; a Downloads category folder holds every top-slot file of that category, so each listing is O(folder size). On an unreadable mount each proxy-tiers-3 warning is logged twice per open (seen in the probe output).
- Evidence: p_tree.py output printed each of the two warnings twice for one `get_video` call.
- Ledger: new
- Suggested change: compute `insert_target_detail` once in `get_video` and derive `insert_share`/`insert_rel_path` from it (`_insert_target` is exactly `target["share"], target["rel_path"]`); pass the dict into `_insert_object`.
- Effort / risk: S effort; low risk

### web-broll-7 - The ingest panel keeps polling at full rate in a background tab
- Category: idle
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/ingest.js:914-930 (`ingestStartPolling`), constants :93-95
- What: while the ingest panel is open the page polls the companion loopback every 1.5 s, the batch every 5 s and the batch list every 10 s, with no `visibilitychange` handling, so a tab left open behind other windows keeps going for as long as it is open.
- Cost / failure scenario: per hidden hour: 2,400 loopback calls into the editor's tray process and up to 1,080 dashboard requests (720 batch + 360 list, each a SQLite read). Small per call, but open for days on an editor machine beside Resolve.
- Evidence: read; no `document.hidden` / `visibilitychange` anywhere in ingest.js or app.js.
- Ledger: new
- Suggested change: on `visibilitychange` to hidden, stop the list and server polls and stretch the loopback poll (or stop it when no upload is running); poll once immediately on visible. Must not stop an upload in flight (that is XHR-driven, not timer-driven).
- Effort / risk: S effort; low risk

### web-broll-8 - style.css exists three times (b-roll, music, ytdl), ~70% shared, and the client viewer loads the editors' whole sheet
- Category: streamline
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/style.css (2,574 lines, 94 KB), music/web/static/style.css (1,930 lines, 71 KB), ytdl/web/static/style.css (1,987 lines, 75 KB); app/main.py:82-85 (`SHARE_ASSETS` includes style.css)
- What: 915 of music's 1,282 distinct lines and 884 of ytdl's 1,299 also appear in b-roll's sheet. A rule fixed in one copy (the terminal HUD R16 note in main.py is one) has to be fixed three times, and every app serves its copy `no-cache`. The public share page pulls the 94 KB editor sheet for a page that uses a fraction of it.
- Cost / failure scenario: ~165 KB of near-duplicate CSS shipped and revalidated per app, three edit sites per shared rule (drift lens for the duplication hunter).
- Evidence: `comm -12` of sorted unique lines.
- Ledger: new
- Suggested change: one shared base sheet served by the dashboard (the topbar partial already comes from there) plus a small per-app sheet; give the share viewer its own trimmed sheet. Must keep the document-relative URL rule (test_mounted_prefix.py) and the SHARE_ASSETS allow-list.
- Effort / risk: M effort; low risk

## What is already good
- FTS is real FTS5 with per-source LIMIT 1000 and MAX_HITS_PER_VIDEO 20 (BROLL-WEB-3): keyword search at 50k clips is 58 ms on a broad term, and payloads are bounded. Leave the RRF design and the caps alone.
- The embedding matrix and the fuzzy vocabulary are held in memory and keyed correctly (generation + count + high-water); the vector work per query is one 8 ms matmul at 50k. The problem is only the rebuild's memory shape (web-broll-3) and the bookkeeping around the matmul (web-broll-4).
- Media delivery streams 64 KB chunks with full Range support and an ETag; no file is read into memory and nothing is generated per request.
- The SPA ignores superseded search responses by token, loads posters lazily, keeps one `<video>` element and releases its `src` on close, and wires detail listeners once at init; `/api/tree` is fetched once (70 ms at 50k).
- The share door's per-request token/revoke check is cheap (one indexed lookup); only the membership fallback (web-broll-1) is expensive.

## Coverage note
Not read: routes_ingest.py, routes_fleet.py and most of ingest_batches.py's state machine (only allocation and the polling client), fleet_auth.py, identity.py, normalize.py, archive_names.py; app.js's settings/companion/shuttle half and ingest.js's staging/upload UI beyond the timers. Did not run a headless browser to count listeners; the sprite fetch claim rests on the CSS rule (opacity) and is standard browser behaviour. Did not verify against the live archive that a publish actually renumbers ids today; web-broll-1 takes the module's own documented premise.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/broll.py: no Cache-Control is added on the mount either; worth checking whether the login gate wraps `StreamingResponse` media in BaseHTTPMiddleware (per-chunk overhead on every proxy byte).
- broll/indexer/broll_index/ffmpeg_tools.py:670: SPRITE_MAX_CELLS 240 at 240 px wide allows 4.2 MB sheets for a hover preview; a smaller cell or lower JPEG quality for long clips would cut web-broll-2's bytes at the source.
