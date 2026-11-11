# dash-collector - the dashboard's collector cycle, self-diagnosis (notices / alerts / invariants / protection), triage and their clients

Files read (approximate coverage): collector.py (loop, run_cycle, _timed, provision, config, enforce skim, inventory + move detection head, completion, remoteneed, prune, invariants, alerts runners: ~70%), notices.py (run_checks and every _check_*: ~85%), alerts.py (Ctx, scan, run_cycle, _is_open/_open_subjects: ~25%), invariants.py (proxy_pairs, run_cycle: ~25%), db.py (notice / clear_notice / clear_notices_of_kind / _mark_notice_checked / meta helpers / record_poll_run / prune / replace_missing_files / upsert_completion / collector_health), syncthing_client.py (100%), syncthing_gui_guard.py (100%), mount_status.py (100%), tailscale_local.py (100%), triage.py (scheduler + poller ~25%), triage_mail.py (poll ~30%), recovery.py (walks + route callers ~15%), app.CollectorWatchdog, settings.py intervals, docs/SELF_DIAGNOSIS.md.
Probes run (all in scratchpad\dash-collector\, dashboard venv, temp DBs built with db.migrate):
- `probe_notices.py`: 20 steady-state `notices.run_checks` passes, SQL traced, WAL measured with autocheckpoint off.
- `probe_cycle.py`: 20 real `Collector.run_cycle(conn, ["connections"])` calls with a stub Syncthing client, SQL / commits / WAL / HTTP calls counted, once with a frozen clock and once with a 15 s production-like clock.
- `sim_loop.py`: `_loop`'s scheduling rules simulated for 24 h with the default intervals (cycles per day).
- `probe_remoteneed.py`: the remoteneed write phase with an unchanged 500-row missing list, 1 and 10 pairs.
- `probe_proxy_pairs.py`: `invariants._check_proxy_pairs` over a synthetic nas_media of 200k and 1M rows.

## Findings

### dash-collector-1 - The self-diagnosis pass runs on every 15 s cycle and costs 18 write transactions and ~83 KB of WAL when nothing has changed
- Category: idle
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/collector.py:460-494 (run_cycle's tail), notices.py:134-220 (run_checks), db.py:3962-3973 (_mark_notice_checked), db.py:3999-4087 (notice / clear_notice / clear_notices_of_kind)
- What: `notices.run_checks` runs at the end of EVERY collector cycle, and a cycle happens whenever any kind is due, so the 15 s `connections` kind drives it. Each pass commits once per check (17 checks) and, in steady state, re-asserts every open notice (`UPDATE ... last_seen`, then a `SELECT id` nobody uses) and calls `_mark_notice_checked` for every kind it touches, which reads, re-parses and re-writes the whole `notice_last_checked` JSON meta row (1.3 KB, ~28 rewrites per pass) with fresh timestamps.
- Cost / failure scenario: `sim_loop.py` with the default intervals gives ~7,900 cycles/day. Measured per connections-only cycle with a production-like clock: 18 BEGIN/COMMIT pairs, 29 INSERT/upserts, 8 UPDATE, 80 SELECT, 83 KB of WAL (vs ~8 KB for the poll_runs row and set_connections the cycle actually needs). Per day: ~140,000 write-lock acquisitions and ~650 MB of WAL written to the ZFS `/data` dataset (which has hourly + daily snapshot tasks, CR-227), plus a checkpoint fsync roughly every 12 minutes, on a fleet where nothing is wrong. Every one of those 18 commits is a write lock a companion's `POST /api/v1/report` can queue behind - the exact contention `test_db_write_locks.py` and the 2026-09-03 "database is locked" incident are about. Scales with cycles, not fleet size, so it is the same at 4 or 20 machines; the number of re-asserted notices adds rows on top.
- Evidence: probe_notices.py: 17 commits / 28 INSERT / 95 KB WAL per pass; probe_cycle.py: 18 commits / 83,020 WAL bytes per cycle with a 15 s clock (12 KB with a frozen clock, i.e. the bytes are the timestamp rewrites). `ui.py:1912` is the only reader of `notice_last_checked` and uses only the key set, so the per-pass timestamp rewrite is never read.
- Ledger: new (related to dash-db-1/dash-db-2 2026-09-18, which removed the same per-poll write from `_timed` for this reason)
- Suggested change: (a) run `notices.run_checks` only when a kind other than `connections` ran, or at most once per 60 s (every condition it reports is measured in minutes to days); (b) keep the check-evidence stamps in a per-process dict and write the meta row only when the SET of checked kinds changes (or at most every 15 min - see finding 2 for the freshness it should carry); (c) in `db.notice`, skip the UPDATE when severity/body/fix are unchanged and `last_seen` is younger than ~10 min (RESOLVE_RULES quiet windows are hours). Must not break: a check that raises still leaves its notices alone; one commit per check stays (syscalls outside the write txn); `[ DISMISS ]` reopening on re-assert must still happen within one pass.
- Effort / risk: S effort; low risk

### dash-collector-2 - "[ OK ]" on WHAT THE SERVER CHECKS needs only that a kind was evaluated once, ever: a check that now raises every cycle, or a pass that has gone blind, still reads OK
- Category: bug
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:3990-3996 (notice_check_times), ui.py:1911-1913, notices.py:192-197 (run_checks swallows a raising check), collector.py:1957-1971 (the blind-pass comment)
- What: the evidence row is a persisted `{kind: last_checked}` map, but the panel only asks whether the key is present (`set(db.notice_check_times(conn))`). The map survives restarts and image updates, so once a kind has been stamped it is `[ OK ]` for the life of the database. The timestamps that would show a stalled check are written ~7,900 times a day (finding 1) and read by nothing.
- Cost / failure scenario: (1) `_check_broll_archive`, `_check_ai_cli_update` or any other check starts raising (an import error after an update, a bad row): `run_checks` logs the traceback to a container log and moves on, the check's kind keeps its old stamp, and the panel shows `[ OK ]` beside it indefinitely - exactly the "unverified check is NOT CHECKED" rule SELF_DIAGNOSIS section 1 states, broken silently. Unlike alerts (which raise `check_failed`) nothing tells anyone a notice check is failing. (2) `collector._record_detected_moves` deliberately skips the `file_move_detected` stamp on a blind pass so that "the LAST honest stamp ... the panel renders as a time going stale" (collector.py:1962-1965); no code renders the time, so a permanently blind inventory still reads `[ OK ]` for hand-move detection, the check whose silence turns moves into deletions (CR-267a).
- Evidence: read the only consumer (ui.py:1912) and grepped every reference to `NOTICE_CHECKS_META` / `notice_last_checked` (db.py and a comment in protection.py only).
- Ledger: new (regression of the intent of resilience sweep 2026-08-28 fix pass finding 1 and dash-collector-alerts-1 2026-09-18)
- Suggested change: treat a stamp older than a per-kind bound (e.g. 3x the writer's cadence, floor 1 h; 2x interval_inventory for `file_move_detected`) as `[ NOT CHECKED ]`, rendered with its age; and have `run_checks` file a `notice_check_failed` (or reuse `check_failed` on the alert side) when a check raises, with the check name as subject. Pairs naturally with finding 1(b): stamps kept in memory, flushed every 15 min, judged stale at read.
- Effort / risk: S effort; low risk

### dash-collector-3 - remoteneed deletes and re-inserts every unchanged missing-files list every minute
- Category: disk-growth
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/collector.py:2367-2399 (_run_remoteneed), db.py:3460-3476 (replace_missing_files)
- What: for every (folder, device) pair below 100 % complete, every 60 s, the pass fetches up to 3 pages of `/rest/db/remoteneed` and then `DELETE`s that pair's rows and bulk-inserts up to 500 again with a new `refreshed_at`, whether or not the list changed. An editor several hours into a proxy backlog has a list that changes slowly; the write is the same rows every minute.
- Cost / failure scenario: measured 0.12 MB of WAL and 2 ms per pair per pass with an unchanged 500-row list; 10 incomplete pairs = 1.09 MB/min = ~1.6 GB/day of WAL (plus primary-key index churn) for as long as those backlogs last, on the snapshotted `/data` dataset. Each pair also costs 1-3 `remoteneed` calls a minute, each of which makes Syncthing walk that folder's index for the device (estimated, tens of ms on a 20k-file folder on the NAS). Today: 4 machines x the projects each is behind on (plausibly 5-20 pairs); at 20 machines x 500 projects the pair count and the churn scale together. `_run_remoteneed` also has no wall-clock budget, unlike completion.
- Evidence: probe_remoteneed.py: "1 pair: 2 ms, 0.12 MB WAL per 60 s pass"; "10 pairs: 17 ms, 1.09 MB WAL per 60 s pass". `refreshed_at` is read only by `fetch_missing` (shown) and the 7-day-scale prune (db.py:10733).
- Ledger: new
- Suggested change: skip the HTTP and the rewrite for a pair whose `need_items` from this minute's completion pass equals the value it had at the last remoteneed fetch (keep `{pair: need_items_at_fetch}` beside `_incomplete`), forcing a refresh every ~15 min; when fetched, compare with the stored `(name, size)` list and write only on difference, bumping `refreshed_at` with one UPDATE when unchanged. Must not break: pairs that drop out of `_incomplete` still get cleared by `clear_missing_files`; the poll-then-write ordering stays.
- Effort / risk: S effort; low risk

### dash-collector-4 - The inventory skip-signature is directory mtimes only, so a file caught mid-copy keeps its partial size and mtime until something else in that project changes
- Category: bug
- Severity: medium
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/collector.py:2098-2109 (_dir_signature), 1884-1887 (the skip)
- What: a directory's mtime changes when an entry is created, removed or renamed, not when an existing file grows or is rewritten in place. A walk that runs while a file is being written straight to its final name (an Explorer/Finder copy of a card onto `P:\`, an SMB copy, anything not using temp-then-rename) records the partial `size` and `mtime_ns`; when the copy finishes no directory mtime moves, the signature matches, and the walk is skipped until some OTHER entry in that project's tree changes. For the last folder of an ingest, that can be never.
- Cost / failure scenario: `nas_media.size/mtime_ns` is the identity key for hand-move detection (`_move_key`, `ix_nas_media_identity`) and the `(basename, size)` the companion's lane-B "found elsewhere" test relies on. If an admin later moves that file by hand, the vanish half carries the stale size and the appearance half the real one, the pair never matches, and every machine holding the clip treats it as a deletion - CR-267a's re-upload + parked lane-B breaker. The project page's byte totals are also short by the unfinished part. Likelihood per ingest is the chance a walk (every ~3 h per project at 100 projects, finding 5) overlaps a 10-30 minute card copy: small per copy, but it happens on every busy shoot day.
- Evidence: read `_dir_signature` (os.walk + `os.stat(dirpath).st_mtime_ns` per directory, no file entries) and the skip; POSIX/ZFS directory mtime semantics. Not reproduced on the NAS (read-only rule). CR-297A already notes "`_dir_signature` is directory mtimes only" for a different consequence.
- Ledger: new (related to CR-297A, fixed)
- Suggested change: after a walk, if any recorded file has `mtime_ns` within the last ~30 min of `walked_at` (the walk saw something still settling), store a NULL/"unsettled" signature so the next visit walks the files again; one extra walk per busy project, nothing in steady state. Must not break: the steady-state no-write skip for unchanged projects, and CR-297A's one-forced-re-walk behaviour.
- Effort / risk: S effort; low risk

### dash-collector-5 - The 8-projects-per-cycle inventory window is spent on unchanged projects too, so "is it on the server" lags 3 h today and ~16 h at 500 projects
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/collector.py:1861-1887 (_run_inventory), settings.py:692-693 (interval_inventory 900 s, inventory_projects_per_cycle 8)
- What: the rotating cursor picks 8 projects per 15-minute pass and only THEN compares each one's cheap directory signature; an unchanged project consumes a slot exactly like a changed one. The cap exists to bound the expensive per-file walk, but it bounds the cheap signature check as well.
- Cost / failure scenario: a project is looked at once every ceil(n/8) passes: 100 active projects -> every 13 passes = 3.1 h worst case (1.6 h average) before footage uploaded to the server appears in `nas_media` (project page MEDIA PRESENCE, `locate`, hand-move pairing, proxy_pairs). At 500 projects: every 63 passes = 15.6 h worst case. The pending-move-halves table and its 2-day prune were sized assuming a pass reaches every project well inside that window. No other code path refreshes `nas_media` (grep: `replace_nas_media` has the one caller).
- Evidence: read; arithmetic from the defaults. The signature walk is a dirs-only `os.walk` (it still lists every entry, so it is not free on NFS, but it stats only directories).
- Ledger: new (related to CR-285AL, which added the cross-cycle carry because of this window)
- Suggested change: compute signatures for all active projects (or a much larger window, time-budgeted like completion) each pass and spend the 8-project cap only on the ones whose signature changed, oldest-changed first. Optionally nudge `inventory` for one project when a lane-A upload report names it. Must not break: all walks before the first write; the unmounted-tree canary; the per-pass DETECTED_MOVE_LIMIT and half-carry limits.
- Effort / risk: M effort; low risk

### dash-collector-6 - Invariant 10 (proxy_pairs) re-reads every nas_media row of every project every 15 minutes even when no inventory changed
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/invariants.py:736-823 (_check_proxy_pairs)
- What: every invariants pass (900 s) loads all rows of `nas_media` per active project into Python and rebuilds the original/proxy sets, although the answer can only change for a project whose inventory was replaced since the last pass (at most 8 per 15 min, usually 0).
- Cost / failure scenario: measured 2.4 s for 200k rows and 1.58 s for 1M rows (1.6 s/M, desktop CPU; the NAS CPU is slower) on the collector's single thread, every 15 min. Today (~100 projects x a few thousand media rows) about 0.3-1 s per pass; at 500 projects x 10k files (5M rows) ~8 s+ per pass, during which connections/enforce wait.
- Evidence: probe_proxy_pairs.py: "100 projects x 10000 files = 1000000 rows: 1.58 s".
- Ledger: new
- Suggested change: cache each project's verdict keyed on `nas_inventory_state.walked_at` (or `tree_sig`) in memory and recompute only projects whose key changed; a fresh process recomputes everything once. Must not break: the per-folder subject shape, the `found` list that lets run_cycle close vanished subjects (CR-266c).
- Effort / risk: S effort; low risk

### dash-collector-7 - Syncthing's pending-devices list is fetched on every cycle (~7,900 GETs a day) for a check whose threshold is 24 hours
- Category: idle
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/collector.py:478-483, notices.py:531-558 (PENDING_DEVICE_HOURS = 24)
- What: run_cycle calls `self.client.pending_devices()` before every self-diagnosis pass, i.e. on every 15 s connections cycle, and the only consumer ignores any device pending for less than 24 h.
- Cost / failure scenario: ~7,900 REST calls a day to the NAS's Syncthing (one per cycle, measured in probe_cycle.py), each a small JSON response; plus, when Syncthing is down, a 10 s client timeout added to every 15 s cycle (the default `SyncthingClient.timeout`), stretching the connections cadence while it is down.
- Evidence: probe_cycle.py: "syncthing pending_devices: 1.0" per connections-only cycle.
- Ledger: new
- Suggested change: fetch it only when the `config` kind ran in this cycle (120 s) or at most every 10 min, caching the last answer; keep "could not ask -> None -> nothing cleared". Folds into finding 1(a) if the notices pass itself moves to a slower cadence.
- Effort / risk: S effort; low risk

## What is already good
- `alerts.Ctx` gathers the fleet view and every table once per scan; the sixty-odd alert kinds share that snapshot and do not query per machine. Leave it.
- Completion polls then writes, has a 30 s wall-clock budget with a rotating cursor and a 3 s per-call timeout; `completion_history` is thinned by `should_snapshot`. Inventory walks before writing and skips the per-file walk on an unchanged signature (no writes in steady state).
- `_timed` writes the slow-poll card only on a change (dash-db-1), `poll_runs` is capped at 2,000 rows, the Syncthing client reuses one `requests.Session`, and every guard tick (`syncthing_gui_guard`, tailnet) is rate limited and never raises.
- `mount_status.recheck` probes with no lock held; `tailscale_local` checks the socket exists before any connect; the triage reply poller is one thread, every 120 s, only while replies are switched on.

## Coverage note
Not read in depth: `_run_enforce` beyond its call sites (it fetches `/rest/config` and `system_status` itself every 60 s while `config` and `provision` fetch the same config at 120 s / 300 s - one shared read per cycle would save 1-2 full-config GETs a minute, not measured), `_provision_slug` / `_run_links`, most of alerts.py's individual checks and `deliver` (its recovery pass is two indexed queries per distinct (kind, subject) in 120 days of alert_log, every 600 s - small today), `compose_weekly`, protection.py and recovery.py beyond their filesystem calls, health.py (pure functions), triage.py's run itself, triage_actions.py. `_ingest_item_finished` (collector.py:2314-2365) makes 2 event-stream calls per completion pass and one SELECT per ItemFinished event plus one per sharing device - small, not a finding. No probe against live Syncthing, TrueNAS or IMAP (rule 2).

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/ui.py:2108-2160 and api.py:12186: every Alerts-page POST (5 routes) and GET re-runs the full `alerts.scan()` (fleet view + all checks) synchronously; fine at today's scale, worth caching from the last collector scan at 20 machines.
