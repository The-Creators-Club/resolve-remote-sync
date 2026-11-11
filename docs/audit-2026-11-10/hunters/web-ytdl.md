# web-ytdl - the YouTube research/download service mounted at /ytdl (worker, db, API, fleet routes, AI calls, vendored downloader, SPA)
Files read (approximate coverage): ytdl/web/ytdlweb/worker.py (all), db.py (schema handling, jobs, queue, claim, terms, videos, ledger, serialisers: ~1-1000, 1360-2135), routes_api.py (health, poll, manifest, active, downloads, cancel: ~120-590, 1097-1300, 1911-1944), routes_fleet.py (client config, manifest, status, hand-back: 290-370, 604-895), claude_cli.py (invoke, ask_json, relevance, health cache), ai_backend.py (anthropic path, client build), vendor/downloader.py (conversion, probe, download), vendor/ytsearch.py (all), ytdlp_nightly.py (outline), ytdl_evidence.py / ytdl_canary.py (outline), schema.sql (all), static/app.js (polling, progress, downloads list, review grid, term review, toggle: ~180-400, 1140-2090, 3340-3360). Companion ytdl_executor.py read only for the drift comparison (timeouts, conversion).
Probes run: (1) temp ytdl.db built from the real schema via `ytdlweb.db` (dashboard venv), one search job with 400 candidates, 24 terms, 1,200 term links: 400 `db.set_video` calls (one commit each) = 927 ms vs the same 400 UPDATEs in one transaction = 11 ms; the `/api/jobs/{id}/manifest` body as routes_api builds it = 296,156 bytes (3.3 ms to build), of which the download list uses 40 rows; the poll body = 6,968 bytes; DB file for that one job = 356 KB. (2) The relevance system prompt as composed for the default mode = 2,772 chars (about 690 tokens). (3) `import yt_dlp.version` = 546 ms, 19.6 MB peak, 70 modules. Scripts and DB under scratchpad\web-ytdl\.

## Findings

### web-ytdl-1 - A live stream wedges the fleet-wide server worker with no bound (pasted /live/ link, or a ticked live result)
- Category: resilience
- Severity: high
- Confidence: PLAUSIBLE
- Where: ytdl/web/ytdlweb/vendor/downloader.py:638-668 (`download`, `build_opts` 158-282: no `match_filter`, no deadline); ytdl/web/ytdlweb/routes_api.py:834 (`_ID_PATHS` accepts `/live/` links); ytdl/web/ytdlweb/worker.py:1882-1990 (cancel and lease read only between clips)
- What: the server executor downloads whatever the URL resolves to with no live-stream refusal and no wall-clock limit, and the worker reads `cancel_requested` only between clips. `parse_url_list` explicitly accepts `youtube.com/live/<id>` links, a paste never passes the filter phase, and on a search job the filter's "live or no duration" drop is a soft deselect the editor can overrule. yt-dlp records an ongoing live stream until it ends, which for a 24/7 channel is never.
- Cost / failure scenario: an editor pastes a news channel's `/live/` link -> the ONE fleet-wide worker (serial by design) sits in that clip indefinitely: every other editor's search and download queues behind it ("waiting to start: N jobs ahead"), the term folder grows a `.part` at roughly 3-4 GB/hour at 1080p (estimated, ~80 GB/day) on the NAS, CANCEL only sets a flag nobody reads until the clip ends, and a container restart does not clear it either (`reset_stale_jobs` keeps `downloading` jobs and puts the row back to `pending`, so the worker re-attaches to the same stream unless the cancel was pressed first). The companion executor is bounded by `CLIP_TIMEOUT_SECONDS = 2 h`; the server is not.
- Evidence: read `build_opts`/`download` (no `match_filter`, no `is_live` check, only retry counts); `_ID_PATHS = ('shorts', 'embed', 'live', 'v')`; `_phase_download` checks `_cancelled` and the lease only at the top of each iteration; companion ytdl_executor.py:324 `CLIP_TIMEOUT_SECONDS = 2 * 3600.0`. Not run against YouTube (brief rule); yt-dlp's live behaviour is its documented default.
- Ledger: new (bug-ytdl-web-1 and CR-80/83 are different failures)
- Suggested change: refuse live/upcoming before any bytes are fetched (a `match_filter` of `!is_live & live_status != is_upcoming` in `build_opts`, which both the search and paste paths share, with a clip-row note "this is a live stream"), and give the server the companion's per-clip deadline by aborting from the progress hook on the worker thread when the deadline or `cancel_requested` is hit, so the abort travels the same path as any yt-dlp failure (`_record_failure` -> `_disown_output` + `_clear_partials`). That keeps the "never torn down from another thread" rule the cancel route's docstring states.
- Effort / risk: S effort; low risk (a match filter only refuses what cannot finish)

### web-ytdl-2 - The two executors' conversion step has drifted: the server's ffmpeg/ffprobe have no timeout and cannot be cancelled
- Category: streamline
- Severity: medium
- Confidence: CONFIRMED
- Where: ytdl/web/ytdlweb/vendor/downloader.py:305 (`probe_streams`) and :456 (`ensure_edit_ready`, `subprocess.run(..., capture_output=True)` with no `timeout`); compare companion/src/ccsync_companion/ytdl_executor.py:482-554 (Popen + `kill_tree` + `on_spawn`), :1639 (`CONVERT_TIMEOUT_SECONDS = 3 h`)
- What: the companion's copy of the edit-ready conversion was hardened (Popen, a 3 h ceiling, a cancellable child, tree kill); the server's vendored copy still runs a blocking `subprocess.run` with no timeout, so a hung or pathologically slow libx264 re-encode (or a hung ffprobe on a damaged file) holds the single fleet-wide worker for as long as it takes, and a CANCEL waits for it. The encode also runs inside the dashboard container at full thread count with no `nice` or `-threads` cap, beside the one uvicorn process.
- Cost / failure scenario: a 1440p/2160p clip is VP9/AV1-only (no AVC rung above 1080p), so every such clip is a full crf-18 `-preset medium` re-encode on the NAS CPU: tens of minutes per clip-hour (estimated). During it the worker is unavailable to every editor, a cancel is not honoured, and dashboard requests compete with ffmpeg for the CPU. A wedged ffmpeg (stalled read on a damaged file) is a worker wedged until a container restart.
- Evidence: read both functions side by side; `ytdl_common` already exists as the shared contract module "BOTH executors run under" (worker.py:33-40) but carries neither timeout.
- Ledger: new (CR-93/YT-3 era work hardened only the companion side)
- Suggested change: move `CLIP_TIMEOUT_SECONDS`/`CONVERT_TIMEOUT_SECONDS` into `ytdl_common` and use them on both sides; run the server's ffmpeg via Popen with a poll loop that also reads `db.is_cancelled` (passed in as a callable), kill on either, and leave the staged original under its own name exactly as the existing failure path (`unstage()`) does. Optionally `-threads` half the cores so the dashboard keeps a core.
- Effort / risk: M effort; low risk (failure path already exists and is tested)

### web-ytdl-3 - Every download-phase poll re-fetches the whole manifest (296 KB for 400 candidates) to draw 40 rows, uncompressed, in hidden tabs too
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: ytdl/web/static/app.js:1228-1237 (manifest fetched each tick while `downloading`), :1165-1169 (1.5 s for 2 min, then 5 s), :1696-1697 (the list uses only `dl_state != 'none'` rows); ytdl/web/ytdlweb/routes_api.py:1234-1258
- What: while a job downloads, each poll tick makes two requests: the 7 KB poll and the full manifest (every candidate, every column, term ids, reveal paths), only to read `dl_state`/`dl_error` of the selected rows. Nothing pauses on `document.hidden` (no `visibilitychange` anywhere in the SPA), and the dashboard has no response gzip.
- Cost / failure scenario: measured 296 KB per manifest for a 400-candidate search with 40 clips selected. A 40-clip download is easily 30+ minutes: ~360 ticks at 5 s = ~107 MB per open tab per job, over the tailnet for a remote editor, plus 360 serialisations of 400 rows on the single uvicorn process (3.3 ms each measured, so CPU is minor; the bytes are the cost). Two tabs or a forgotten background tab doubles it.
- Evidence: probe (1) above; read `poll()` and `renderDownloads`.
- Ledger: new
- Suggested change: add the download rows to the poll response while `phase == 'downloading'` (a `SELECT video_id,title,thumbnail,dl_state,dl_error,filepath FROM job_videos WHERE job_id=? AND dl_state!='none'`, about 6 KB for 40 rows) and drop the per-tick manifest fetch; keep the final `loadManifest` at the terminal phase as today. Skip ticks (or stretch to 30 s) while `document.hidden`.
- Effort / risk: S effort; low risk (the terminal-phase manifest load that YTDL-34 protects is unchanged)

### web-ytdl-4 - The poll never stops at terms_review and re-renders the checkbox list every tick
- Category: idle
- Severity: low
- Confidence: CONFIRMED
- Where: ytdl/web/static/app.js:1250-1279 (stop set is ready_for_review/done/failed/cancelled only), :1501-1530 (`renderTermReview` rebuilds `#termlist` from scratch on every poll)
- What: `terms_review` is a person-wait phase exactly like `ready_for_review` (the worker never touches it), but the page keeps polling it at 5 s for as long as the tab is open, and each tick throws away and rebuilds every checkbox row. The editor's ticks survive (`state.termsOn`) but keyboard focus does not, and a click landing during the rebuild hits a detached node.
- Cost / failure scenario: a review left open overnight = ~17,000 requests per tab per day, each 5-6 SQL statements on the dashboard's single process; at 20 editors with a tab parked each, ~350k useless requests/day (estimated). Tabbing through 24 terms with the keyboard resets every 5 s.
- Evidence: read `poll()` and `renderTermReview`.
- Ledger: new
- Suggested change: add `terms_review` to the phases that stop polling (SEARCH WITH THESE already calls the continue route and can `schedulePoll()` itself), or slow it to 30 s; render the list once per job (`state.termsOn === null` is already the "first sight" signal) and only update counts afterwards.
- Effort / risk: S effort; low risk

### web-ytdl-5 - Filter and enrich phases commit once per row (927 ms vs 11 ms for 400 rows)
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: ytdl/web/ytdlweb/db.py:1567-1571 (`set_video` commits), used per row by worker.py:800-835 (mechanical drops), :870-874 (verdicts), :969-977 (`mark_duplicates`), :712-729 (enrich)
- What: every row write in a phase whose progress the SPA does not show per row (the filter phase has no counter at all) is its own WAL commit and fsync.
- Cost / failure scenario: measured on this NVMe: 400 per-row commits = 927 ms, one transaction = 11 ms. On the NAS (ZFS, sync writes) each commit is slower, so a 400-candidate filter phase spends seconds in fsync and holds the ytdl.db write lock 400 times, contending with select clicks on the request threads. Once per search; small but free to remove.
- Evidence: probe (1).
- Ledger: new
- Suggested change: wrap each filter sub-step (mechanical, verdicts, duplicates) in one transaction with a `set_video(..., commit=False)` variant; keep the per-chunk commit in enrich (its counter is shown) and every phase transition committed, which is what the module docstring's "every counter bump is committed" is about.
- Effort / risk: S effort; low risk

### web-ytdl-6 - Each review-grid checkbox click rebuilds the whole grid twice
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE
- Where: ytdl/web/static/app.js:2043-2073 (`toggle` calls `renderGrid()` optimistically and again on the reply), :1925-1946 (`renderGrid` empties `#grid` and rebuilds every visible card with a new `<img>`)
- What: one tick re-creates up to 400 cards (about 2,400 nodes and 400 image elements) twice.
- Cost / failure scenario: estimated 10-40 ms of DOM work per rebuild in Chrome, x2 per click; an editor curating 100 clips does 200 full rebuilds and re-decodes the thumbnails each time (lazy images re-enter the loader). Visible as flicker/jank on a laptop beside Resolve.
- Evidence: read; not measured in a browser.
- Ledger: new
- Suggested change: update the one card's class/checkbox and re-run only the footer/header counts (`#gridfoot`, `#reviewsum`, `#download`); keep `renderGrid()` for filter, term-chip and bulk changes.
- Effort / risk: S effort; low risk

### web-ytdl-7 - Search candidates are kept forever: job_videos / job_video_terms are never pruned
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED
- Where: ytdl/web/schema.sql:208-258; no `DELETE` on these tables outside boot recovery, erase, and `_drop_forgotten_terms` (db.py)
- What: every candidate of every search (title, channel, thumbnail URL, notes, term links) stays in ytdl.db after the job is done; nothing reads a job older than the 20-job Recent list except a deep link.
- Cost / failure scenario: measured 356 KB for one 400-candidate job. Today about 2 searches a day (job ids ~120 by 2026-10-05) = ~250 MB/year; at 20 editors and ~15 searches/day, ~2 GB/year in a DB the container holds open and the hourly snapshots copy.
- Evidence: probe (1); grep for DELETE in db.py.
- Ledger: related to com-privacy-telemetry-7 (open, no retention for search history) - this is the disk/size side of the same gap
- Suggested change: in the retention pass that item asks for, drop `job_videos`/`job_video_terms` of terminal jobs older than N days (keep the `jobs` row and its counters, and never touch `downloads`, the permanent dedupe ledger). The folder's `manifest.json` already keeps the provenance of what was downloaded.
- Effort / risk: S effort; low risk

## What is already good
- The worker's idle cost is one indexed SELECT every 5 s (`claim_next_job`, `idx_jobs_queue`/`idx_jobs_phase`), plus at most one AI health probe per 5 minutes only while the cache is red. Leased jobs are filtered in SQL, so a local download never spins the loop.
- The fleet routes the companions call are event-driven (claim, 30 s heartbeat during a lease only, one manifest with ONE rglob, one post per clip); nothing polls them while idle. Leave them alone.
- The in-memory `_progress` map is cleared on every exit path (done, failure, cancel, lease stand-down, breaker trip); the yt-dlp nightly refresher is bounded (20 h interval, pip `--timeout 20`, prunes old version dirs); health never probes the AI provider per request and caches the PO-token probe for 60 s.
- Enrichment is paced and chunked with an abort-on-bot-check, and the relevance prompt keeps instructions identical across batches. (Prompt caching would not apply anyway: the system prompt is ~690 tokens, under the minimum cacheable prefix.)

## Coverage note
Not read in full: routes_api.py start_download/free-space helpers (1400-1870), projects.py, session.py, identity.py, attestation.py, config.py beyond the env names, style.css, index.html, cc_spa.js, the companion's ytdl_executor beyond the timeout/conversion code. No browser-side measurement (findings 3, 4, 6 are read, with 3 sized by the server-side probe). The vendored downloader's other differences from the companion copy (format ladder, sidecar) were not diffed line by line.

## OUT OF TERRITORY
- companion/src/ccsync_companion/ytdl_executor.py: also has no live-stream refusal; its 2 h `CLIP_TIMEOUT_SECONDS` bounds it, but a pasted `/live/` link still records 2 h of stream onto an editor's disk and then fails.
