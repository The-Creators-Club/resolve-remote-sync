# sorter-page - the Footage Sorter page (footage-sorter `public/`) served at /sorter
Files read (approximate coverage): public/index.html (all), grid.js (all), app.js (state load, refreshRows, dest-tree poll, selection, assign/unassign, afterManifestChange, boot: ~20%), ledger.js (header, volumes, volume sets, changed/noteVersion, polling, wiring: ~30%), ingest.js (session poll + SSE), audio.js (data, polling, player), dev-mock.js (guard); footage_sorter/web.py (serve_blob, _json, thumbs/strips, static mount) and engine.py (dest_tree, refresh_tree, clips_view, ledger_summaries*) and ledger.py (_tx version bump) to price the calls; docs/PERFORMANCE-PLAN.md, SPEC.md, ccsync docs/SORTER_DEPLOY.md.
Probes run: (1) destination-tree size lower bound from the local data/clips.json (35,936 clips): >= 1,131 folders under Projects, ~190 KB as tree JSON, 23 KB gzipped; (2) slim clip payload: all 35,936 rows 25.0 MB raw / 2.7 MB gzip, source-only 419 rows 212 KB / 23 KB; (3) node JSON.parse + id Map + stem grouping of the full slim list: ~40-45 ms parse + ~16 ms index, heap +100 MB; (4) manifest the edit routes return: 13,595 assignments, 2.92 MB raw / 0.30 MB gzip; (5) page assets: 606 KB raw, 158 KB gzip -9 (dev-mock.js 41 KB raw / 12 KB gz). All scripts in scratchpad\sorter-page\.

## Findings

### sorter-page-1 - Any ledger write makes every open page re-download and re-adopt the whole clip list
- Category: perf
- Severity: medium
- Confidence: CONFIRMED (by reading both sides; not timed live)
- Where: footage-sorter public/ledger.js:380 (noteVersion -> changed), :358-370, :1351-1386; public/app.js:443 (refreshRows), :376-430 (loadState); footage_sorter/engine.py:694-718 (clips_view ETag deps include the summaries generation), :778-812
- What: the page treats ANY change of `ledger.version` as "the ledger changed" and calls `changed()`, which clears the copy and volume-set caches and refetches the clip views (source, and the 35k destination rows once a view has loaded them). `ledger.version` is bumped by every committed ledger transaction (ledger.py `_tx`), and the clips ETag moves with `_sum_gen`, which increments on every summary rebuild even when no clip's copy count changed, so the conditional GET is never a 304 after a write. The client then rebuilds `clipById`, `duplicateMarks()`, re-filters, re-sorts and repaints the grid and info pane.
- Cost / failure scenario: during a drive scan (a companion posts 5,000-row chunks, one transaction each; a 500k-file drive is ~100 commits) or an auto-backup, every poll sees a new version: every 30 s normally, every 2 s with the Backups panel open. With the destination loaded that is 2.7 MB gzip (25 MB raw) per poll per open tab, plus ~60 ms parse/index measured in node (more in a browser, plus dupMarks/filter/sort over 36k rows) and the server re-serialising the 25 MB view (sorter-py's half). A 30-minute scan with the panel open = up to 900 refetches = ~2.4 GB over the tailnet for one tab, for copy-count badges that mostly did not change.
- Evidence: ledger.py:322-329 bumps on every bump=True commit; engine.py:695-716 etag = sha1(token+name+repr(deps)) with deps including gen; ledger.js:384 `if (v !== S.ver) { S.ver = v; changed(); }`; probes 2 and 3.
- Ledger: related to PERFORMANCE-PLAN.md (the ETag design), not reported there
- Suggested change: make the clips ETag depend on a hash of the summaries actually built (bump `_sum_gen` only when `val != previous val`), and have the page refetch rows only when the activity reply says the summaries generation moved (send it in `api/ledger/activity`), not on any ledger version. Must keep: badges/Where filter update after a real copy change.
- Effort / risk: S effort; low risk

### sorter-page-2 - Destination tree polled every 15 s, uncompressed and uncached, while the server only re-reads it every 60 s
- Category: idle
- Severity: medium
- Confidence: CONFIRMED (cadences); tree size ESTIMATED
- Where: footage-sorter public/app.js:479-506 (DEST_POLL_MS 15000, setInterval at :4540); footage_sorter/engine.py:297 (`loop("dests", lambda: 60, self.refresh_tree)`), :1346-1351 (dest_tree deep-copies under the engine lock); web.py:89-92 (`_json`: no gzip, no ETag, no-store)
- What: each visible tab GETs `api/desttree` every 15 s. The server's copy changes at most once a minute (refresh_tree, which already computes a sha1 signature of the tree), so 3 of 4 polls are guaranteed identical. Each answer is `copy.deepcopy` of the whole tree while holding `engine.lock` (which also serialises assign/state work), then `json.dumps`, then sent raw; the client then walks the whole tree to build its own signature string to discover nothing changed.
- Cost / failure scenario: 240 requests/hour/tab. Tree >= 1,131 folders today (lower bound from clip paths; real tree also has non-clip folders), ~190 KB raw per answer = >= 45 MB/hour/tab and 240 deep copies under the lock. At 500 projects roughly 5x. PERFORMANCE-PLAN.md lists this route as "a few KB"; it is not.
- Evidence: probe 1; code read above.
- Ledger: new
- Suggested change: serve desttree through `serve_blob` (gzip + ETag = the existing `_tree_sig` + planned-folders version) so an unchanged poll is a 304 with no deepcopy, and poll at 60 s to match the server's refresh. Must keep: a folder made in Explorer still appears without a reload.
- Effort / risk: S effort; low risk

### sorter-page-3 - Every assign/unassign downloads the whole manifest UNCOMPRESSED and redraws every pane twice
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: footage-sorter public/app.js:2068-2106 (assign/unassign), :2029-2050 (adoptResponse, afterManifestChange); footage_sorter/engine.py:1082, :1095; web.py:89-92 (`_json`, no Content-Encoding)
- What: the edit answer carries the whole manifest. PERFORMANCE-PLAN.md "Not changed" knows that and prices it at ~0.3 MB gzip, but `_json` never gzips and the dashboard has no GZip middleware in front of /sorter, so the real wire cost is the raw 2.9 MB. On the page, `afterManifestChange()` runs once optimistically and again on the reply: each run re-renders the source tree, the whole destination tree (with `coverageByDest()`), the events list, re-filters and re-sorts the grid, `renderMissing()` and `updateMissingBadge()` (coverage, emptyEvents, rosterGaps, duplicateGroups again), plus `leanManifest` copying 13.6k assignments.
- Cost / failure scenario: sorting is click-after-click: 100 drags in a session = ~290 MB downloaded and 200 full-page redraw passes. On a phone over Tailscale (~20 Mbit/s, PERFORMANCE-PLAN's figure) each drag waits ~1.2 s for the reply.
- Evidence: probe 4 (2,915,125 bytes); `_json` builds a plain Response; grep found no GZipMiddleware in dashboard/src.
- Ledger: related to footage-sorter docs/PERFORMANCE-PLAN.md "Not changed" (whole manifest per edit) - the missing compression and the double redraw are new
- Suggested change: gzip `_json` bodies above ~8 KB (or answer edits with only the changed assignments + leaves, which the plan already proposes), and skip the second `afterManifestChange()` when the reply's assignments for the edited ids equal the optimistic ones. Must keep: rollback on failure.
- Effort / risk: S (gzip) / M (delta reply); low risk

### sorter-page-4 - Page assets shipped uncompressed, unversioned, and with the development mock
- Category: deploy
- Severity: low
- Confidence: CONFIRMED
- Where: footage-sorter public/index.html:288-296; footage_sorter/web.py:559, :571-575 (`_PublicFiles`, no-cache)
- What: the 11 JS/CSS files go out raw (Starlette StaticFiles does not compress) with `no-cache`, and no version in their URLs, so every page open makes 12 revalidation round trips (fonts aside) before the scripts can run, and a cold load is 606 KB instead of 158 KB. `dev-mock.js` (772 lines, 41 KB, only active with `?mock=1`) ships to the NAS and is parsed on every load.
- Cost / failure scenario: per cold open 448 KB avoidable; per warm open 12 serial-ish 304s over the tailnet (~12 x RTT; on a phone ~0.5-1 s before first grid paint). Correctness is fine: no-cache means a deploy IS picked up without a hard refresh.
- Evidence: probe 5.
- Ledger: related to PERFORMANCE-PLAN.md P2 (done as ETag + no-cache, not hashed)
- Suggested change: add `?v=<DEPLOYED_COMMIT>` to the script/style URLs (the deploy already writes the commit) and serve them `immutable` + gzip (pre-compressed or GZip middleware on the mount); load dev-mock.js only when `?mock=1` (one inline loader) or leave it out of the deploy allow-list. Must keep: document-relative URLs.
- Effort / risk: S effort; low risk

### sorter-page-5 - Audio tab poll keeps running in a hidden browser tab and is never cleared
- Category: idle
- Severity: low
- Confidence: CONFIRMED
- Where: footage-sorter public/audio.js:460-472
- What: once the Audio tab has been opened, a 30 s `setInterval` lives for the life of the page. It checks only whether the Audio panel is the active right-hand tab, not `document.hidden` (every other poller on the page checks it), so a backgrounded browser tab left on Audio fetches `api/audio` and rebuilds the whole worklist/transcript DOM every 30 s forever.
- Cost / failure scenario: 120 requests/hour per forgotten tab; the `/api/audio` overview is a map over every scored clip (server re-scoring cost is sorter-py's) plus a full transcript re-render client side.
- Evidence: code read; contrast ingest.js:1455, ledger.js:1352, app.js:493.
- Ledger: new
- Suggested change: `if (!visible() || document.hidden) return;` and clear the interval when the tab is left.
- Effort / risk: S effort; low risk

### sorter-page-6 - Session list polled every 5 s although an event stream for it is open
- Category: idle
- Severity: low
- Confidence: PLAUSIBLE (did not read what the SSE carries beyond `open`)
- Where: footage-sorter public/ingest.js:1251-1272, :1417-1455 (POLL_SESSIONS_MS 5000)
- What: every visible tab GETs `api/ingest/sessions` every 5 s and JSON.stringify-compares it, while `api/ingest/events` (SSE) is held open by the same page. With no card in, the answer is the same every time.
- Cost / failure scenario: 720 requests/hour/visible tab; together with sorter-page-2 and the ledger's 30 s tick, an idle open sorter is ~1,000 requests/hour per tab against the one dashboard process.
- Evidence: code read.
- Ledger: new
- Suggested change: have the server push a `sessions` event on change over the existing SSE and drop the poll to 30-60 s as a fallback. Must keep: a card finishing its scan still reloads the clips.
- Effort / risk: M effort; low risk

### sorter-page-7 - Hover intent can queue an ffmpeg filmstrip job on the NAS for every card the pointer crosses
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE
- Where: footage-sorter public/grid.js:723-737 (90 ms intent -> loadStrip), :809-827; footage_sorter/web.py:262-274 (`strip` enqueues `thumbs.request(clip, "strip")` and waits up to 20 s)
- What: resting 90 ms on a card fires `api/strip/<key>`; for a clip with no strip yet the server starts a strip job and holds the request up to 20 s. The fetch is never aborted when the pointer leaves, so sweeping across a row of cold cards queues one ffmpeg job per card even though only the last one will be scrubbed.
- Cost / failure scenario: estimated: a sweep across 20 cold cards = 20 strip jobs (each reads the proxy over the pool) ahead of the one the editor wants; harmless once strips are backfilled. Did not confirm whether a background strip backfill exists.
- Evidence: code read.
- Ledger: new
- Suggested change: prefetch only strips that already exist (a `?nowait=1` that 404s instead of enqueuing), and enqueue at the 300 ms scrub start. Must keep: scrub start latency for strips that exist.
- Effort / risk: S effort; low risk

### sorter-page-8 - Em dashes and Node-era instructions in user-visible strings
- Category: bug
- Severity: low
- Confidence: CONFIRMED
- Where: footage-sorter public/app.js (~42 string literals, e.g. :1935, :2412, :4102), grid.js:330-337 (duplicate badge titles), ingest.js (~19), calendar.js (~7), cards.js (3), audio.js (2), ledger.js (1); app.js:4524 "is server.js running?", app.js:1179 "build it with npm run roster"
- What: the page is now a CC Sync dashboard module and the owner's rule bans em dashes in visible copy; ~81 string literals carry one, and no ccsync scan test covers footage-sorter/public. Two messages tell a NAS user to run things that do not exist there (server.js, npm).
- Cost / failure scenario: every toast/tooltip/empty-state shown; a NAS boot failure toast sends the operator to look for a Node server.
- Evidence: grep of string literals containing U+2014.
- Ledger: new
- Suggested change: replace with " - " / colon, reword the two messages, and add the dashboard suites' em-dash scan over footage-sorter/public to the sorter tests.
- Effort / risk: S effort; low risk

## What is already good
- grid.js is properly virtualised: only visible rows +2 overscan exist, rows and cards are pooled (60/400), per-card listeners are attached once at creation, not per render; selection repaint touches only on-screen cards.
- Thumbnails are lazy and scroll-aware (deferred during a fling, nearest-the-middle first, fetchPriority), at immutable URLs with a server-side byte-capped LRU; hover scrub uses 15-60 KB filmstrips and the <video> fallback is torn down (src removed, load()) on leave.
- First load is lean: early fetches of meta (lean) + 419 source rows (23 KB gzip), destination fetched only when a view needs it, then revalidated by ETag.
- Every URL is document-relative (no root-relative /api or /static found); index.html is no-cache so deploys are picked up.
- The ledger and ingest pollers stop while document.hidden.

## Coverage note
Did not read: most of app.js render code (source/dest tree render cost at 500 projects, renderMissing complexity), ledger.js volume browser rendering at 500k files (loadVolumeSet pages 5,000 ids up to 60 pages = 300k ids, not timed), calendar.js, cards.js, style.css, phone.js; no headless-browser listener count or render timing was run.

## OUT OF TERRITORY
- footage_sorter/web.py:89 `_json`: no gzip on any non-blob JSON answer (move status, ledger routes, audio) - sorter-py.
- footage_sorter/engine.py:806-808: a new daemon thread per stale summary request (guarded by a non-blocking lock check that is released before the thread takes it, so two can start) - sorter-py.
