# dash-db - dashboard SQLite: db.py (schema, migrations, queries), site_store.py, sessions.py, subject_data.py
Files read (approximate coverage): db.py connect/bulk_insert/migrate (640-760, 2100-2375), upsert_lane_report, upsert_completion, replace_missing_files (3385-3585), prune + purge (10677-10850), media presence writes (11330-11500), fetch_sync_backlog and helpers (11845-12060), table and index list of the whole schema (built, see probes); sessions.py whole; site_store.py outline + feature/telemetry/manifest cache (995-1150); subject_data.py outline; callers in api.py (report handler 11040-11430, build_transfers_view 624-760, owed cache 976-1060), ui.py/ui_home.py polled partials, collector._run_prune, companion reporter.py section resend (196-222, 1161-1200).
Probes run (all in the scratch folder `...\scratchpad\dash-db\`, dashboard venv, SQLite 3.49.1, this desktop's NVMe): (1) real `db.migrate` into an empty file: 0.081 s to v61, no-op re-run 5 us; `db.connect` 0.49 ms vs bare 0.06 ms. (2) filled to a 20-machine fleet: 100 projects x 4,000 originals + 4,000 proxies in nas_media (800k), 10 ticks per machine with 2,000+2,000 manifest rows (760k editor_media), 4,000 media-tree clips per tick (800k), 300 missing files per pair, a month of lane/completion history, 180 d audit, 120 d alerts: 515 MB. (3) EXPLAIN QUERY PLAN of every prune DELETE and the backlog queries; timings of fetch_sync_backlog, build_transfers_view, prune, replace_editor_media / replace_media_tree with WAL growth. (4) one companion report through the real app (TestClient, no lifespan) with a SQL trace: 44 statements, 2 connections, 42 ms warm, no full scan of a large table. (5) GET of the polled pages with an admin session and a trace. (6) rowid vs WITHOUT ROWID copies of the three media tables. (7) WAL growth with a writer and 0/1/2 overlapping backlog readers. (8) cache_size / mmap_size effect on a fresh-connection backlog read (none worth having: 166 / 189 / 150 ms).

## Findings

### dash-db-1 - Every machine's unchanged manifest and media tree are deleted and rewritten in full every 10 minutes
- Category: perf / disk-growth
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:11423 (replace_editor_media), :11458 (replace_media_tree); caller api.py:11378-11410; sender companion reporter.py:212 (SECTION_RESEND_SECONDS = 600)
- What: ops-efficiency-1 made the companion omit an unchanged `local_manifest` / `media_tree`, but it still force-resends both every 600 s, and the dashboard answers every resend with DELETE + re-INSERT of up to 4,000 editor_media rows and 4,000 media_tree_clips rows per ticked project, even when the content is byte-identical. The rewrite also bumps `editor_media_project.reported_at`, which is in the owed-files cache fingerprint (api.py:993), so each resend also invalidates that cache (the PL-RES-74 "cache never hits" half).
- Cost / failure scenario: measured per ticked project, unchanged content: replace_editor_media 3,808 rows 27.5 ms + 0.84 MB WAL; replace_media_tree 4,000 rows 30.6 ms + 0.80 MB WAL. Today (4 machines x ~10 ticks): ~40 x 1.64 MB per 10 min = ~9.5 GB/day written to /data on ZFS for no change. At 20 machines x 10 ticks: 200 x 1.64 MB / 600 s = 0.55 MB/s, ~47 GB/day, ~11.6 s of write-lock time per 10 min; and because the whole of both tables (156 MB + 147 MB at that scale) is rewritten several times an hour, every hourly snapshot pins roughly that much changed data (estimated, the companion's own comment already names snapshot retention as the cost).
- Evidence: probe (3) above; the server path has no digest or compare (api.py:11388-11391 calls replace whenever the lists are present).
- Ledger: new (related to PL-RES-74 / PRAC-73, open, which is the read side)
- Suggested change: store a digest of each project's file list on `editor_media_project` (and a per-(editor, machine, project) digest row for the media tree); when the incoming digest equals the stored one, skip the replace and only touch the small row. Move retention to that small row (prune pairs whose small row is old, then delete their big-table rows by PK prefix) so per-row `refreshed_at` need not be rewritten. Keep the 600 s resend itself: it is what heals a restored or pruned dashboard, and a missing/different digest still does the full replace. Fingerprint the owed cache on the digest, not `reported_at`.
- Effort / risk: M effort; low risk (a schema step adds one nullable column; NULL digest = old behaviour)

### dash-db-2 - Overlapping long backlog reads can starve WAL checkpoints, and the WAL file never shrinks
- Category: disk-growth / perf
- Severity: medium
- Confidence: PLAUSIBLE (mechanism CONFIRMED by probe; the live overlap depends on fleet size and open tabs)
- Where: dashboard/src/ccsync_dashboard/db.py:710-728 (connect: no journal_size_limit, no checkpoint policy); readers via db.py:11845 fetch_sync_backlog from ui_home.py:423 / ui.py:1870 (2 s polls)
- What: a WAL can only restart from the beginning when no reader holds a snapshot that uses it. The admin-scope backlog read takes ~0.9 s at 20 machines on this desktop (PL-RES-74 measured 6 s at 50 editors on its probe), and it is polled every 2 s per open tab; once two such reads overlap continuously, every commit appends and the WAL grows without bound. No `journal_size_limit` is set, so after the overlap ends the -wal file stays at its high-water size for the life of the process, and every read pays a longer wal-index search meanwhile.
- Cost / failure scenario: probe (7): a writer committing one manifest replace every 50 ms with 2 continuously overlapping backlog readers grew the WAL to 549 MB in 45 s (0 readers: 5 MB). At realistic cadence (one replace per 1.5 s, readers with a 1 s pause, i.e. today's query speed) it stayed at 6-8 MB, so this needs the slow-query regime: 20+ machines on NAS CPU, or 3+ admin tabs. Then at the dash-db-1 write rate (0.55 MB/s) the WAL grows ~2 GB per hour of starvation on /data, and is never given back.
- Evidence: walstarve.py / walstarve_real.py in the scratch folder.
- Ledger: new (aggravated by PL-RES-74, open)
- Suggested change: `PRAGMA journal_size_limit` (for example 64 MB) in `connect`, and have the collector run `PRAGMA wal_checkpoint(RESTART)` (bounded busy wait) once per prune cycle and log the WAL size when it exceeds a threshold. The real cure is making the reads short (PL-RES-74's cache / per-pair counts), which removes the overlap.
- Effort / risk: S effort; low risk

### dash-db-3 - editor_media and media_tree_clips store a four/five-TEXT key twice (rowid table + autoindex)
- Category: perf / disk-growth
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:86 (editor_media), :97 (media_tree_clips)
- What: both tables are ordinary rowid tables whose PRIMARY KEY is a composite of long TEXT columns, so SQLite keeps the row in the rowid b-tree and a full copy of the key in `sqlite_autoindex_*`. Every lookup (the backlog anti-join) and every replace touches both.
- Cost / failure scenario: probe (6) at 20 machines x 10 ticks: editor_media 156.2 MB -> 100.8 MB WITHOUT ROWID (-35%), full replace of one project 15.7 -> 12.6 ms (-20%); media_tree_clips 146.6 -> 120.7 MB (-18%), 19.8 -> 17.3 ms. These are the two tables dash-db-1 rewrites continuously, so the saving multiplies by that write rate. nas_media is NOT a candidate (it has two secondary indexes and grew 178 -> 217 MB WITHOUT ROWID).
- Evidence: norowid.py in the scratch folder.
- Ledger: new
- Suggested change: one migration step that rebuilds the two tables WITHOUT ROWID (create _new, INSERT SELECT, drop, rename, in migrate's single transaction). Both are full-replace caches the companions repopulate within 10 minutes, so the step may even simply drop and recreate them empty, which keeps boot-time migration cost near zero on a large DB.
- Effort / risk: S effort; low risk

### dash-db-4 - The hourly prune full-scans the largest tables while holding the write lock
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:10691-10839 (prune), :10842 (purge_nas_media_for_inactive)
- What: EXPLAIN QUERY PLAN shows SCAN (no index) for `editor_media WHERE refreshed_at <`, `media_tree_clips WHERE refreshed_at <`, `missing_files`, `editor_media_project`, `lane_report_history WHERE ts <` (that table has no index at all), `transfer_history WHERE received_at <` (indexed only on completed_at), `completion_history` twice (the thinning statement adds a temp b-tree GROUP BY), and `nas_media WHERE project_id NOT IN (...)` (800k rows). All of it runs in one transaction that the collector commits only afterwards (collector.py:2413-2426).
- Cost / failure scenario: once an hour; measured 352 ms steady state at the 20-machine fill on NVMe (estimated 1-2 s on NAS CPU), during which every report and session write waits. Below the 5 s request busy timeout, hence low; it grows linearly with machines x ticks.
- Evidence: probe (3) plans and timing.
- Ledger: new
- Suggested change: delete media rows by PK prefix for the (editor, machine, project) pairs whose `editor_media_project.reported_at` is old (pairs with dash-db-1); purge nas_media only for project ids that are inactive (`project_id IN (SELECT id FROM projects WHERE active=0)` plus orphans checked once at boot); prune transfer_history on the indexed column or add the index; commit between groups of deletes. Do not add a `refreshed_at` index to editor_media: it would tax the dash-db-1 write path more than it saves.
- Effort / risk: S effort; low risk

### dash-db-5 - lane_report_history and completion_history are written and pruned but nothing displays them
- Category: streamline
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:3559-3565 (lane_report_history insert), :3446-3457 (completion_history read-last + insert), prune :10696-10707
- What: a grep of the whole dashboard package finds no reader of either table except the person-data export / purge (db.py:10001-10003), the machine rename (:9466) and `upsert_completion` reading its own last row to decide whether to write the next. No route, template or alert reads them.
- Cost / failure scenario: completion: one extra SELECT (plus an occasional INSERT) per (project, device) pair per 60 s collector cycle, i.e. ~200 queries/min at 20 machines x 10 ticks, plus the hourly thinning DELETE with its GROUP BY temp b-tree over ~170k rows at that scale; lane history: one row per lane state change (72k/month at 20 machines in the fill). Small, but it is code, schema, export surface and prune time for data no one sees.
- Evidence: grep for both names across dashboard/src (only the sites listed).
- Ledger: new
- Suggested change: either give them a reader (a per-lane state timeline on the machine page would be useful for "when did it stop") or stop writing them and drop them in a migration step, keeping the export's table list in step.
- Effort / risk: S effort; low risk

### dash-db-6 - The home page computes the fleet backlog three times per render, and each pair's download diff twice
- Category: perf
- Severity: low (the polling cost itself is PL-RES-74 / PRAC-73, open)
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:11900-11907 + 11956-11960 (down_totals_q then down_files_q, the same NOT EXISTS anti-join run twice); `/` render through ui_home.py:141 + api.py:1057 + a third build_transfers_view
- What: within one GET `/` as admin the trace shows 600 executions of the originals query (3 x 200 pairs), 9 separate connections and 2,793 statements; inside fetch_sync_backlog the proxy anti-join is computed once for COUNT/SUM and again for the 50 names.
- Cost / failure scenario: at the 20-machine fill on this desktop: GET `/` 2.8 s, `/partials/home-transfers` 0.91 s and `/partials/transfers` 1.0 s (823 statements each; polled every 2 s); fetch_sync_backlog alone 0.86 s, 99% of it inside `execute` (SQL, not Python). Today's 4-machine share: ~170 ms per call.
- Evidence: probes (3) and (5), profile_backlog.py / trace_pages.py.
- Ledger: related to PL-RES-74 / PRAC-73 (open) - cited, not re-described
- Suggested change: inside PL-RES-74's fix, compute the backlog once per request (pass it down) and fetch totals and the first 50 names in one pass (window `COUNT(*) OVER ()` / `SUM() OVER ()` with LIMIT 50).
- Effort / risk: S effort; low risk

## What is already good
- The light report path: 44 statements, 2 connections, 42 ms warm at the 20-machine fill, PK lookups only; lane history and completion snapshots are written on change only, and bulk_insert (CR-351) keeps the big replaces to one statement each.
- migrate(): no-op on an up-to-date DB costs microseconds (one `PRAGMA user_version`), and a full build from empty is 81 ms, so boot-time migration is not a cost.
- Every growing table found has a retention rule (prune covers audit, alerts, notices, diagnostics, jobs, history, tokens, poll_runs; sessions and login_attempts are pruned in sessions.py; file moves and setting requests expire). Do not add more indexes for prune; fix prune's shape instead (dash-db-4).
- The session touch is rate-limited (60 s) and best-effort with a 250 ms busy wait; the site manifest is cached on app.state. Per-connection page cache and mmap made no measurable difference to the hot read (probe 8), so connection-per-request is not the problem it looks like.

## Coverage note
- subject_data.py was only outlined (admin-only export, rare). site_store.py beyond the predicates and manifest cache was not read line by line.
- Not measured on the NAS itself (forbidden); all times are this desktop's NVMe and CPU, so NAS numbers are labelled estimated.
- Not reached: the collector's other writers (completion/inventory transaction shape per cycle), jobs queue queries under a large queued backlog, VACUUM / auto_vacuum (the file never shrinks after a large purge), boot-time migration on a large DB with a table-rebuild step.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/api.py:988: the owed-files cache TTL (15 s) equals the fleet grid's 15 s poll, so the TTL backstop alone expires most entries; with dash-db-1 the fingerprint also changes every manifest resend.
- dashboard/src/ccsync_dashboard/sessions.py:258: `_schema_ready` is set but never read (dead).
