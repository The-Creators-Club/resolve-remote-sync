# dash-db - the dashboard's data layer: db.py, links.py, assignments.py, runtime_id.py, schema.sql, v47..v54 migration, the busy-database rework

Files read (with approximate coverage):
- `git diff -- dashboard/src/ccsync_dashboard/db.py` (534 changed lines, every hunk, 100%)
- `dashboard/src/ccsync_dashboard/db.py`: migration block v47..v54 + `migrate`/`_split_statements`/`_already_applied` (100%), `connect`/busy timeouts (100%),
  `age_seconds`/`parse_iso` and every other `parse_iso` arithmetic site in the file (100%),
  the file-move / resolve-undo command layer (`file_move_target_machines`, `command_machine_names`,
  `pending_file_moves`, `mark_file_move_applied`, `pending_resolve_undos`, `mark_resolve_undo_applied`,
  `adopt_renamed_machine`, `forget_machine`, `_MACHINE_STATE_TABLES`) (100%),
  the new pending-move-halves and stand-in ledger sections + `prune` (100%),
  `collector_stale_bound`/`configured_stale_bound`/`fetch_collector_status` (100%),
  `upsert_machine_state`/`fetch_sync_guard_map` for the two v54 columns (100%)
- `dashboard/src/ccsync_dashboard/assignments.py` (diff + `_machine_options`, 100%)
- `dashboard/src/ccsync_dashboard/schema.sql` (100% - unchanged, still the v1 base; correct)
- other sides of the wires I read to verify: `api.py` (`_by_target_machine`, `api_report`'s
  file-move/undo/stand-in blocks, `_register_machine`'s SYS-18a branch, the admin move route ~2850),
  `collector.py` (`run_cycle`'s Syncthing-free gate, `_settle_halves`), `notices.py` (`is_db_busy`,
  `record_db_busy`, `record_slow_write`, `record_slow_poll`), `app.py`'s 503/500 handler
- tests: `test_bug_hunt_2026_09_18_dashboard_lows.py` (res-fleet-4 section),
  `test_bug_hunt_2026_09_18_dashboard_mediums.py` (index + dash-db-4/-5 tests), `test_db_busy_2026_09_17.py`,
  `test_db_write_locks.py`, `test_db.py`

Tests run:
- `dashboard\.venv\Scripts\python.exe -m pytest tests/test_db.py tests/test_bug_hunt_2026_09_18_dashboard_lows.py tests/test_db_busy_2026_09_17.py tests/test_db_write_locks.py -q` -> **99 passed**
- scratch migration harness (scratchpad, outside the repo): built databases at v47, v52, v53 with
  the truncated step list, then ran `migrate()` TWICE against each, plus a fresh database twice,
  plus a hand-made "interrupted mid-v54" database (table created and one of the two `ADD COLUMN`s
  applied, `user_version` still 53) -> **every case reaches user_version=54, `PRAGMA integrity_check` ok,
  both new tables and both new columns present, no duplicate-column error on replay.** The v54 step is
  clean and replayable; no finding there.
- scratch reproduction of dash-db-1 below (offer/answer asymmetry) -> reproduced exactly.

## Findings

### dash-db-1 - res-fleet-4 landed its OFFER half only: the machine's ANSWER is still keyed on the reporting hostname, so a command offered under a former name can never be retired
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:5923` (`mark_file_move_applied`) and
  `dashboard/src/ccsync_dashboard/db.py:6168` (`mark_resolve_undo_applied`), against
  `dashboard/src/ccsync_dashboard/db.py:5779` (`command_machine_names`) /
  `:5806` (`pending_file_moves`) / `:6133` (`pending_resolve_undos`);
  caller side `dashboard/src/ccsync_dashboard/api.py:9475` and `:9492`
- What: res-fleet-4 made the OFFER and the DELIVERY STAMP look under every hostname sharing this
  computer's `machine_id` (`command_machine_names`, `_by_target_machine`), but the two functions that
  record the machine's ANSWER still match `WHERE ... AND machine=?` with the REPORTING hostname, and
  `api_report` passes the reporting `machine` into both. A command filed under the former hostname is
  therefore offered, delivered and executed, and its answer updates zero rows.
- Failure scenario: an editor renames OLD-PC to NEW-PC while a file move is outstanding. SYS-18a
  defers the adoption (a rename and a cloned disk look identical), so for the deferral window the row
  stays under `machine='OLD-PC'`. NEW-PC is offered the move, moves the file, and answers
  `file_moves_applied`. `mark_file_move_applied(..., machine='NEW-PC')` matches nothing, returns
  False: the target row keeps `applied_at IS NULL`, so the SAME move is re-offered on the next report
  and on every report after it, every 30 s. The second attempt finds nothing at the old path, and the
  companion's answer is dropped again. Meanwhile `_file_move_answer(conn, id, editor, machine)` (the
  comp-app-2 log de-dupe) also reads under the reporting hostname and always returns None, so the
  exact WARNING flood comp-app-2 was written to stop is back, once per move per report. If the
  adoption is never confirmed - the new name has acquired a plan of its own, which
  `adopt_renamed_machine` refuses by design, or the twin keeps reporting - this is PERMANENT: the row
  ages into `expired_at`, raises the warn alert naming a computer the registry does not have, and the
  project page shows the move as never applied on a machine that applied it twice. The same applies to
  `resolve_undo_requests`.
- Evidence: scratch database at v54, two `machines` rows (`OLD-PC`, `NEW-PC`) sharing `machine_id='mid-1'`,
  one `file_move_targets` row under OLD-PC and one `resolve_undo_requests` row under OLD-PC:
  ```
  offered to NEW-PC: [(1, 'OLD-PC')]
  answer recorded under reporting hostname NEW-PC -> False
  row now: {'machine': 'OLD-PC', 'delivered_at': None, 'applied_at': None, 'state': None}
  undos offered to NEW-PC: [(1, 'OLD-PC')]
  undo answer under NEW-PC -> False
  ```
  (`delivered_at` is None in the snippet only because I called `pending_file_moves` directly rather than
  through `api_report`; in the product `_by_target_machine` stamps it correctly under OLD-PC - which is
  precisely the asymmetry.) The new test
  `tests/test_bug_hunt_2026_09_18_dashboard_lows.py::test_a_command_under_a_former_hostname_is_still_offered`
  asserts the offer and `target_machine`, and never calls `mark_file_move_applied` at all, which is why
  the gate is green on a half-landed fix.
- Ledger: new (CR-285/res-fleet-4 does not fix res-fleet-4's own scenario end to end)
- Suggested fix: carry the row's key through the answer. Pass `machine_id` into
  `mark_file_move_applied` / `mark_resolve_undo_applied` and widen their WHERE to
  `machine IN (command_machine_names(...))`, or have `api_report` look the outstanding row's
  `target_machine` up by id (it already has the id) and stamp that. Add a regression test that answers
  an offer made under a former hostname.

### dash-db-2 - `command_machine_names` has no liveness test, so two live computers on one `machine_id` (the cloned disk SYS-18a deliberately keeps) are each offered the other's move and Resolve-undo commands
- Severity: high
- Confidence: CONFIRMED (db behaviour proven; the downstream Resolve effect follows the companion's
  documented handling of a command it is given)
- Where: `dashboard/src/ccsync_dashboard/db.py:5779-5804` (`command_machine_names`) via
  `dashboard/src/ccsync_dashboard/db.py:4858` (`machines_by_machine_id`), reached from
  `pending_file_moves` and `pending_resolve_undos`; the state that makes it reachable is
  `dashboard/src/ccsync_dashboard/api.py:7050-7070` (`_register_machine`'s `if live:` branch)
- What: `command_machine_names` returns every registry row carrying the same `machine_id`, with no
  check on whether that row is still LIVE. Its own docstring says "IDENTITY ONLY, never the editor's
  other computers: a machine that never held the file must not be told to move it". But SYS-18a's
  clone refusal exists precisely to leave TWO live rows on one `machine_id` indefinitely ("Refusing the
  adoption: no plan is moved and no row is deleted"), so on a copied disk the predicate does exactly
  what the docstring forbids - it hands each twin the other's commands. Only the quiet former name is
  wanted, and nothing here tests for quiet.
- Failure scenario: an editor images creator-1's disk onto a second box. Both report every 30 s with
  `machine_id='mid-1'`, and `_register_machine` refuses the adoption forever, by design. An admin then
  clicks `[ MOVE ON THE SERVER AND ON EVERY MACHINE ]`, targeting creator-1; or clicks an admin-side
  Resolve undo for creator-1's journal. The reply to the CLONE's next report carries that command.
  For a move the clone moves its own copy of the file (it has one - it is a disk copy) and, per
  dash-db-1 above, the answer is discarded, so creator-1 is still commanded too. For a Resolve undo
  the clone replays a journal against whatever project its Resolve has open, i.e. an editor's Resolve
  project is mutated by a command addressed to a different computer - the one class of damage the
  severity guide calls high.
- Evidence: `machines_by_machine_id` (db.py:4858) is a plain `SELECT * FROM machines WHERE
  editor_username=? AND machine_id=?` with no freshness predicate; `command_machine_names` filters
  nothing out of it. `api.py:7055` (`live = [r for r in others if _previous_row_is_live(r, now)]`)
  shows the dashboard already owns the liveness predicate this needed and does not use it here. The
  new test asserts only the negative case for a DIFFERENT `machine_id` (`OTHER-PC`/`mid-2`); the
  same-`machine_id`-both-live case is untested.
- Ledger: new (opened by res-fleet-4's fix)
- Suggested fix: in `command_machine_names`, keep only rows that are NOT live -
  `[r for r in machines_by_machine_id(...) if not _previous_row_is_live(r, now)]`, moving
  `_previous_row_is_live`/`CLONE_ADOPTION_WINDOW_SECONDS` into `db.py` (api imports db, not the
  reverse). A former name is by definition quiet; a twin is by definition not.

### dash-db-3 - dash-db-4's LIKE escaping was applied to the db helper and not to the identical query the admin's MOVE button actually runs
- Severity: medium
- Confidence: CONFIRMED
- Where: fixed at `dashboard/src/ccsync_dashboard/db.py:5656-5662`
  (`file_move_target_machines`, `_like_prefix` + `ESCAPE '\'`); UNFIXED duplicate at
  `dashboard/src/ccsync_dashboard/api.py:2850-2855`
- What: `api.py`'s move route builds its own target set rather than calling
  `db.file_move_target_machines`, with a byte-for-byte copy of the same
  `rel_path=? OR rel_path LIKE ?` query and the same unescaped `media_key + "/%"` prefix. The db
  helper is reached only from `collector.py:1883` (the DETECTED hand-move path). So the fix landed on
  the path CR-267a added and missed the path CR-267a was reported against - the admin clicking the
  button.
- Failure scenario: an admin moves the folder `Gold_Card_Meetup`. The pattern
  `Gold_Card_Meetup/%` matches `Gold-Card-Meetup/...`, `GoldXCardXMeetup/...` and every other
  same-length sibling differing only where the underscores sit, so machines holding only the SIBLING
  folder are added to `file_move_targets`, are sent a `commands.file_moves` entry for a file they do
  not hold, and appear as waiting/failed rows on the project page's per-computer progress for a move
  that has nothing to do with them.
- Evidence: `sqlite3` in the dashboard venv:
  `select 'Gold-Card-Meetup/A001.mp4' LIKE 'Gold_Card_Meetup/%'` -> `1`;
  with the escaped prefix and `ESCAPE '\'` -> `0`. The new test
  `test_a_move_of_an_underscored_folder_does_not_claim_its_siblings` exercises
  `db.file_move_target_machines` only, so it passes while the route still over-matches.
- Ledger: CR-285/dash-db-4 does not fix dash-db-4 on the admin route
- Suggested fix: make `api.py`'s move route call `db.file_move_target_machines` (it already computes
  the same `media_key`) instead of keeping a second copy of the query, and extend the regression test
  to go through `POST` on the route.

### dash-db-4 - `record_standins_placed` deletes the machine's rows before inserting, so `first_seen` is rewritten on every report and the `ON CONFLICT ... DO UPDATE` arm is unreachable
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:8880-8908` (`record_standins_placed`)
- What: the docstring states "`first_seen` survives a re-report of the same rel, because 'how long has
  this clip been standing in' is the question an operator asks". The body runs
  `DELETE FROM broll_standins WHERE editor_username=? AND machine=?` and only then the
  `INSERT ... ON CONFLICT(archive_rel, editor_username, machine) DO UPDATE SET last_seen=...`. After
  the delete nothing can conflict, so every insert writes `first_seen=now`: the stored age of every
  stand-in is at most one report cycle, and the conflict arm is dead code.
- Failure scenario: a stand-in placed on 2026-09-01 that is still not upgraded on 2026-09-18 reads as
  "first seen 30 seconds ago" for any future panel or alert built on this column - which is the whole
  reason the column exists. Nothing renders it yet, which is the only reason this is low.
- Evidence: read of the function; `grep -rn broll_standins dashboard/src dashboard/tests` shows no
  reader of `first_seen` today, and no test asserts it.
- Ledger: new (proxy-tiers-4's dashboard half)
- Suggested fix: drop the blanket DELETE and replace it with a delete of the rels NOT in the new set
  (`DELETE ... AND archive_rel NOT IN (...)`, chunked), leaving the upsert to keep `first_seen`; or
  keep the delete and re-read the old `first_seen` values first. Add a test that reports the same rel
  twice with two different `now` values and asserts `first_seen` did not move.

### dash-db-5 - `PENDING_MOVE_HALF_LIMIT` bounds the READ only; nothing bounds the table on the way in, so one unmounted share can bury the pairing window for two days
- Severity: low
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (that a real site hits it)
- Where: `dashboard/src/ccsync_dashboard/db.py:8757-8795`
  (`PENDING_MOVE_HALF_LIMIT`, `record_pending_move_halves`, `pending_move_halves`);
  caller `dashboard/src/ccsync_dashboard/collector.py:2654-2682` (`_settle_halves`, `persist` uncapped)
- What: the constant is named as a table limit but is only the `LIMIT` of the oldest-first read.
  `record_pending_move_halves` inserts every half it is given, and `_settle_halves` passes the whole
  `persist` list. The only bound is `prune`'s two-day age-out.
- Failure scenario: a project's share is unmounted (or a large delete happens) while the inventory
  walk runs: every file in it becomes a `vanished` half, tens of thousands of rows in one pass. From
  then on `pending_move_halves(limit=4000)` returns the oldest 4000 of those rows on every cycle, so
  a genuine hand move made the next day has its half written but never read, and hand-move detection
  is silently off for two days - the failure mode dash-collector-alerts-1 was written to end. Nothing
  tells anybody.
- Evidence: read of both functions and of `_settle_halves`; `PENDING_MOVE_HALF_LIMIT` appears only in
  the `pending_move_halves` signature (`grep -n PENDING_MOVE_HALF db.py collector.py`).
- Ledger: new
- Suggested fix: cap at the write - refuse to persist more than `PENDING_MOVE_HALF_LIMIT` halves per
  slug per pass (the walk that produced them already knows the count), and raise the existing
  `file_moves_dropped` notice when halves are dropped for the cap, so the blind window is visible.

## Coverage note
- The v54 migration is clean: exercised on scratch v47/v52/v53 databases, twice each, plus a fresh
  database twice and a hand-made interrupted-mid-step database. `schema.sql` is deliberately still the
  v1 base and needs no change. `_already_applied` covers both new `ALTER TABLE`s and both new tables
  use `IF NOT EXISTS`. Every reader of the two new columns (`fetch_sync_guard_map`,
  `upsert_machine_state`'s COALESCE/CASE arms) survives NULL for every machine on deploy day - I read
  both and they are correct, including the deliberate difference between `disk_floor_bytes` (COALESCE,
  a setting) and `skipped_exists_subpath` (CASE on `skipped_exists`, a scope that must travel with its
  count).
- `collector_stale_bound`'s new database heuristic checks out: `collector.run_cycle` (collector.py:408)
  skips non-`SYNCTHING_FREE_KINDS` before any `poll_runs` row is written when `syncthing_url` is
  unset, so "a poll_runs row outside the free kinds" really is evidence of a Syncthing-backed site.
  The one residual is a site that HAD Syncthing and lost it: its historic rows keep the tight 180 s
  bound until they age out of `poll_runs`. Too narrow to report.
- I did NOT audit `links.py` or `runtime_id.py` line by line - neither is touched by this fix pass
  (`git diff` empty for both) and the time went into the file-move command layer instead.
- The suite does not cover: the ANSWER side of res-fleet-4 (dash-db-1), the two-live-rows case of
  `command_machine_names` (dash-db-2), the admin ROUTE for dash-db-4's escaping (dash-db-3),
  `first_seen` on `broll_standins` (dash-db-4), and any bound on `nas_media_pending_moves` growth
  (dash-db-5). All five gaps are in tests written this afternoon.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/app.py:1460-1472`: a busy database now answers **503 with a JSON
  body on every route, including HTML page routes** (a browser gets `{"detail": ...}` instead of a
  page) and, more importantly, on `POST /api/v1/report`. Whether the companion (0.9.65..0.9.74 in the
  field) treats a 503 as a retryable skip or as a refusal is a wire question I did not chase.
- `dashboard/src/ccsync_dashboard/notices.py:1215`: `is_db_busy` matches only the literal
  `"database is locked"`; SQLITE_LOCKED's `"database table is locked"` would still be filed as a
  server error with the "send to support" fix line.
- `dashboard/src/ccsync_dashboard/api.py:9870`: `standins_known` (up to 200 paths) is added to EVERY
  report reply of EVERY machine every 30 s, whether or not that machine has any use for it; the reply
  is not gated on the companion having asked for it.
