# dash-api - the dashboard's JSON API (api.py) and its helpers (assignments, links, locate, project_groups, netclass, android, published_docs)
Files read (approximate coverage): api.py - the whole report route (10860-11860) and every helper it calls (auth/credential checks, _WriteHolds, _auto_map_has_rival, _upgrade_info, broll/music_cancel_requested, _ignored_sections_to_log), the selection read/tick routes and _selection_view/_project_roots_view, build_editors_view and the _OWED_CACHE, package publish/download/prune (7290-7840, 6870-6930), _move_proxy_siblings; perhaps 20% of the file by lines. locate.py, netclass.py (cache), published_docs.py fully; assignments.py, links.py, project_groups.py, android.py skimmed. Read in db.py: connect, bulk_insert, replace_editor_media/media_tree/active_transfers, standins_known, queue_depth, machine_settings_map, upsert_machine_state. Read in auth.py: identity_status/_identity_revoked. Companion side of two wires: selection.py (fetch, _write_cache), reporter.py (section resend, cadence).
Probes run (all under scratchpad\dash-api\, dashboard venv, DASH_DEV_INSECURE=1, temp data dir):
- probe_report*.py: FastAPI TestClient, 20 machines, 200 realistic light reports (3 lanes, 4 transfers, sync_guard, capabilities, machine_settings), SQLite trace callback on every dashboard connection. Result: 6 ms mean / 6.7 ms p95 per report, 63 statements, 1 commit, 2 dashboard connections + 1 music.db connection per report; reply 292 B with no stand-ins, 14,181 B with 200 stand-ins; 275 WAL frames for 40 reports (about 28 KB of WAL per report).
- probe_views.py: migrated schema, 100 projects x 4 machines x 25 ticks x 400 files, and 500 projects x 20 machines x 50 ticks x 400 files (400k editor_media, 200k nas_media). build_editors_view cold 31.6 / 220.7 ms, warm (cache hit) 1.4 / 6.3 ms; _selection_view 0.29 / 1.11 ms but 23,054 / 103,791 bytes, of which project_roots is 18,770 / 95,170 bytes.
- provision.scan_unregistered_dirs on a synthetic 500-project tree (marker per project, 10 subdirs each): 46-51 ms warm, local SSD.
- db.connect + close: 0.155 ms local. flatten_sync_guard: 1.9 us (called 7 times per report - not a finding).

## Findings

### dash-api-1 - The selection reply re-sends the fleet-wide project_roots map every 30 s, and its per-response timestamp defeats the companion's write-on-change cache
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/api.py:2917 (`"generated_at": db.utcnow_iso()`), api.py:2919 (`_project_roots_view(conn)`), api.py:3068 (`api_get_selection`); companion/src/ccsync_companion/selection.py:364 (`if response == self._last_written ...`)
- What: GET /api/v1/selection/<editor>?machine= answers with every sticky Resolve-project mapping in the fleet (project_roots is only ever pruned by an admin delete, so it grows with every Resolve project ever mapped) plus `generated_at` stamped to the second. The companion fetches it every `selection_fetch_ttl` (30 s) and its AUDIT_2 P11 "write only on change" guard compares the WHOLE response, timestamp included, so it never matches: every fetch is a full download AND a tmp+replace rewrite of selection.json on the editor's disk.
- Cost / failure scenario: per machine, 2,880 fetches/day. At 100 mappings the reply is 23 KB (measured) = 66 MB/day down the tailnet and 66 MB/day of SSD writes beside Resolve; at 500 projects it is 104 KB = 300 MB/day per machine each way, 6 GB/day across a 20-machine fleet, for an answer that changes a few times a week. Server cost is small (1.1 ms per call at 500), the waste is wire + editor disk.
- Evidence: probe_views.py (sizes above); read selection.py:350-390 - the comparison is `response == self._last_written` on the parsed dict, and the dict always carries the new `generated_at`.
- Ledger: new (it silently undoes AUDIT_2 P11's write-on-change fix)
- Suggested change: two independent halves. (a) Companion: compare the response with `generated_at` removed (one line; keeps the stamp in the file). (b) Dashboard: add a strong ETag over the response minus `generated_at` and answer `If-None-Match` with 304, so the 30 s poll costs headers only; the companion keeps its "fetched OK" stamp on a 304 (comp-sync-14 needs that). Must not break: the editor-keyed cache (bug-comp-syncthing-6) and "unreachable vs no mapping" (AUDIT_2 CORE-H9) - a 304 is "live, unchanged", never "unreachable".
- Effort / risk: S effort for (a), M for (b); low risk

### dash-api-2 - The report holds the database write lock across a filesystem walk of the Projects tree (CR-379 rival check)
- Category: concurrency
- Severity: medium
- Confidence: CONFIRMED (ordering); cost PLAUSIBLE (estimated on the NAS)
- Where: dashboard/src/ccsync_dashboard/api.py:10981 (`holds.begin(conn, "fleet state")` = BEGIN IMMEDIATE), api.py:11122 (`_auto_map_has_rival(...)`), api.py:4327-4357 (`provision.scan_unregistered_dirs`, cached 60 s)
- What: the auto-map block runs after BEGIN IMMEDIATE has taken the write lock and before the first commit at 11376. On a cache miss `_auto_map_has_rival` does an `os.walk` of `projects_dir` (depth up to 8, pruned at markers) with the lock held. When a rival IS found the mapping is deliberately not written, so the same Resolve project triggers the walk again on the first report after every 60 s cache expiry, for as long as that project stays open.
- Cost / failure scenario: measured 46-51 ms for a warm 500-project tree on local SSD; on the NAS with a cold ARC (after a reboot, during a scrub, while lane A writes) a walk of a few hundred directories is estimated at hundreds of ms to seconds - all of it time in which the collector, session touches and every other machine's report wait on busy_timeout (5 s), which is exactly the 2026-09-03 "database is locked" shape. The comment at api.py:10973-10976 already states the rule this breaks ("no write transaction may be open across" a lookup, LG-4).
- Evidence: read the order of statements in api_report; timed scan_unregistered_dirs on a synthetic tree; `_WriteHolds.begin` executes BEGIN IMMEDIATE (api.py:133-139).
- Ledger: related to CR-379 (fixed) and CR-351; new
- Suggested change: compute `detected_slug`/`match`/rival verdict BEFORE `holds.begin` (it is reads plus a walk; nothing in it depends on the writes above it except `clear_report_refused`, which it does not read), and keep only `db.sticky_project_root` inside the transaction. Must not change: the rival refusal, the 60 s cache, or "tree unreadable means ask".
- Effort / risk: S effort; low risk

### dash-api-3 - `standins_known` re-sends up to 200 archive paths on every report reply to every machine
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/api.py:11777; db.py:11348 (`standins_known`: GROUP BY over the whole broll_standins table, ORDER BY MAX(last_seen) - a temp B-tree sort per report)
- What: the reply always carries the full fleet list (by contract, empty included), whether or not it changed since the last reply to that machine.
- Cost / failure scenario: measured reply 292 B -> 14,181 B with 200 stand-ins (48x). Per machine: 20 MB/day at the 60 s idle cadence, 242 MB/day at the 5 s active cadence (reporter `dashboard_report_interval_active`); plus a JSON parse of it on the companion every tick. Today's stand-in count on the live NAS is unknown (not read, by rule), so the daily figures scale linearly from 200.
- Evidence: probe_report2.py (reply size with 200 seeded rows).
- Ledger: related to wire-3 (bug-hunt-2026-09-18b, a correctness finding about the same list; this is its size)
- Suggested change: add `standins_known.sig` (hash of the list) and let the companion echo the last sig it applied in the report; send `rels` only when the sigs differ. Keep the three states exactly: absent = "this dashboard does not know", empty list = "none" - a matching sig means "unchanged since what you hold", which an old companion never sends, so it keeps getting the full list.
- Effort / risk: M effort (both sides, dashboard first); low risk

### dash-api-4 - Two to three SQLite opens per companion request where one is needed
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: api.py:10918 (`auth.read_identity_token_ex(settings, identity)` without `conn=`), also 2991, 3056, 5607, 11957, 12452; api.py:2623+2629 (`identity_bar`: one open in identity_status, a second for account_bar_reason, per mounted b-roll/music/ytdl companion call); api.py:11720 (`music_cancel_requested` opens music.db read-only on every report, even with no ingest batch anywhere)
- What: auth._identity_revoked opens its own `db.connect` (4 PRAGMAs, including `journal_mode=WAL`) whenever no connection is passed, although every one of these routes already holds one from get_conn.
- Cost / failure scenario: measured 3 `sqlite3.connect` per report (2 dashboard + 1 music) vs 1 needed; 0.155 ms each on local SSD, more on ZFS where each open also maps the -shm. At 20 machines x 5 s that is 8 opens/s of pure overhead, plus one per heartbeat of every fleet job / ingest batch. Small, but free to remove.
- Evidence: probe_report2.py call-site counter: `200 connect <- _identity_revoked <- identity_status`, `200 music_cancel_requested`.
- Ledger: new
- Suggested change: pass `conn=conn` at the six call sites; have identity_bar open one connection and pass it to both halves; skip the music/b-roll lookup unless an in-process "a cancel was requested since boot" flag (set by the cancel route, cleared when the batch ends) or a cheap TTL says there could be one - the heartbeat 410 stays the authoritative path.
- Effort / risk: S effort; low risk (revocation still fails open on a read error)

### dash-api-5 - Each light report writes about 28 KB of WAL, much of it re-stamping unchanged state
- Category: idle
- Severity: low
- Confidence: PLAUSIBLE (WAL volume measured; the avoidable share estimated)
- Where: api.py:10984-11015 (clear_report_refused, record_known_editor, record_report_auth, touch_editor_report_token), api.py:11169-11218 (store_blocked_state / store_upgrade_state / store_resolve_health / store_resolve_health_detail / store_loopback_state: unconditional `SET ...=NULL` UPDATEs on machine_state every report), api.py:11352 (replace_active_transfers: DELETE + INSERT every report)
- What: a report with nothing new still executes 12 UPDATE, 8 INSERT and 5 DELETE statements; UPDATEs without an `IS NOT` guard rewrite their page even when the values are identical.
- Cost / failure scenario: measured 275 WAL frames for 40 reports (~7 pages, 28 KB each). Today's 4 machines: 160 MB/day idle (60 s), 1.9 GB/day while syncing (5 s); 20 machines syncing: about 9.7 GB/day of WAL plus the checkpoint copy into dashboard.db, on the ZFS dataset that hourly snapshots retain.
- Evidence: probe_report4.py (`PRAGMA wal_checkpoint(PASSIVE)` -> (0, 275, 275) after 40 reports from a truncated WAL); probe_report5.py statement list.
- Ledger: new
- Suggested change: add `AND (col IS NOT ? OR ...)` guards to the store_* NULL-setters and to report_auth/known-editor/token stamps (or coarsen those stamps to once a minute); skip replace_active_transfers when the set is empty and the table holds none for that machine. Must not change: received_at as the liveness signal, and the "a section that says nothing deletes the row" latch rule.
- Effort / risk: M effort; low risk

## What is already good
- The report route is lean where it counts: 63 statements, ONE commit for the fleet state, per-project commits for the big media replaces, bulk inserts as one json_each statement (CR-351), ~6 ms per report at 20 machines. The companion already omits unchanged local_manifest/media_tree (ops-efficiency-1). Leave this shape alone.
- build_editors_view's owed-files cache keyed on a fingerprint (_OWED_CACHE) works: 220 ms cold -> 6 ms warm at 20 machines x 500 projects x 400k media rows; the fingerprint itself is 3.5 ms.
- Package upload streams to a per-request .part through the threadpool with a running size cap; downloads are FileResponse (streamed). Nothing reads a whole package into memory.
- Every module-level dict in the territory is bounded: netclass `_cache` (256, expiry first), `_IGNORED_SECTION_LOGGED` (cleared past 500), `_UNREGISTERED_CACHE` (one key per projects_dir/depth), `_OWED_CACHE` (one key per DB file).
- locate.py answers from nas_media through the (size, mtime_ns) index with no filesystem call.

## Coverage note
api.py has ~356 routes and functions; I covered the report route end to end, selection read/tick, packages, the editors view and locate. Not examined: file-move routes beyond the proxy-sibling helper, the admin/setup/ai-provider routes, users/tokens, diagnostics storage growth, ytdl/jobs routes' own costs, and the partial/htmx routes (ui.py, not this territory). android.py, published_docs.py, project_groups.py, links.py were skimmed for per-request I/O only. Not raised as a finding: locate.py:192 `_as_of` is a full scan of nas_media (`MAX(refreshed_at)`, no index), but it runs only on a no-match locate, which a lane B pass reaches rarely.

## OUT OF TERRITORY
- companion/src/ccsync_companion/selection.py:364: the write-on-change compare includes `generated_at` (the companion half of dash-api-1).
- companion/src/ccsync_companion/reporter.py:623: the 5 s active report cadence is what multiplies every per-report cost above by 12; a 10-15 s active cadence would halve or third dash-api-3/-5 with no server change.
