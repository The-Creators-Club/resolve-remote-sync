# dash-db - the dashboard's database layer: db.py, links.py, assignments.py, runtime_id.py, schema.sql, migrations v47..v53, the busy-database rework

Files read (with approximate coverage):
`dashboard/src/ccsync_dashboard/db.py` (the diff 34a3c8f..HEAD in full, plus
connect/migrate/_already_applied/_split_statements, the whole NOTICE_KINDS +
notice/clear_notice/notice_check_times block, the file_moves block, the
selections/fetch_machine_selections/selections_for_machine block, the
`_schema_predates` readers, `nas_media_rows`/`replace_nas_media`,
`record_ignored_report_sections` - call it 35% of 10,503 lines, chosen by the
diff and by what the week's features touch);
`links.py` (100%); `assignments.py` (100%); `runtime_id.py` (100%);
`schema.sql` (skim, 100% of its 101 lines);
plus, as the other end of my wires and cited only:
`notices.py`'s new "the lock" block, `app.py`'s exception handler,
`api.py:api_report`'s slow branch, `collector.py:_timed` and the
`file_move_detected` writer, `ui.py`'s notice panel/health-rows readers,
`dashboard/templates/admin_assignments.html`.
Tests read: `test_db_busy_2026_09_17.py` (100%), `test_admin_assignments.py`
(the picker block + fixtures), `test_db_write_locks.py`, `test_links.py`,
the NOTICE_KINDS assertions in `test_sweep_2026_09_04_dashboard.py` and
`test_health_page.py`.

Tests run:
- `dashboard/.venv/Scripts/python.exe -m pytest tests/test_db_busy_2026_09_17.py tests/test_admin_assignments.py tests/test_links.py tests/test_db.py tests/test_db_write_locks.py -q`
  -> first run `1 failed, 112 passed, 1 skipped`
  (`test_db_write_locks.py::test_no_alert_is_sent_with_the_write_lock_held`),
  four subsequent runs of the identical command `113 passed, 1 skipped`. See
  dash-db-6.
- Three scratch scripts in the scratchpad (never in the repo):
  a v47- and v52-shaped database migrated to v53 and replayed; an AST sweep of
  every `db.notice(...)` kind literal against `db.NOTICE_KINDS`; a live
  `Collector._timed` call with a six-second poll that writes nothing.

## Findings

### dash-db-1 - a collector poll that held no write lock at all is recorded as the writer that held it, for ever
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/collector.py:493` (the trigger),
  `dashboard/src/ccsync_dashboard/notices.py:1153` (`record_slow_write`, the
  body it writes), `dashboard/src/ccsync_dashboard/db.py:3424` (`notice`,
  which is why it cannot be dismissed)
- What: `_timed` measures `elapsed` around the WHOLE runner - `_run_inventory`
  is an SSH walk of the NAS tree, `_run_enforce` and `_run_connections` are
  Syncthing API round trips - and then treats any `elapsed > BUSY_TIMEOUT_MS /
  1000` (5 s) as evidence that the poll "held the database's write lock for
  longer than a request waits". Almost none of that time is inside a write
  transaction; the poll's own writes are `record_poll_run` plus whatever the
  runner committed. So the one durable record the 2026-09-17 rework added to
  name the culprit of a contention event names, on most fleets, a pass that
  was waiting on the network.
- Failure scenario: a site whose inventory walk over SSH takes 20 s (normal
  for a tree of any size - `SLOW_POLL_SECONDS` is 1.0, so the authors already
  expect polls well past a second). Every collector cycle upserts
  `notices(kind='slow_write', subject='collector poll inventory')` with the
  count incremented, so the home page permanently carries "N time(s)
  collector poll inventory held the database's write lock for longer than a
  request waits (5 s)" with N climbing by one per cycle, and a fix line that
  tells the admin to untick projects or send Diagnostics to support. Because
  `db.notice` sets `cleared_at=NULL` on every re-assert by design, dismissing
  it lasts until the next cycle: the admin cannot clear it, and it competes
  for the 25 rows of `NOTICE_PANEL_LIMIT` with real findings.
- Evidence: scratch script against a fresh migrated database - a
  `Collector._timed(conn, "inventory", fn)` where `fn` only `time.sleep(6.0)`
  and touches nothing produced exactly one row:
  `{'kind': 'slow_write', 'severity': 'warn', 'subject': 'collector poll
  inventory', 'body': "1 time(s) collector poll inventory held the database's
  write lock for longer than a request waits (5 s); the last time took 6.0
  s. ..."}`. No test covers this path: the two `record_slow_write` tests in
  `test_db_busy_2026_09_17.py` call the function directly, and
  `test_db_write_locks.py::test_a_slow_poll_says_so_in_the_log` drives
  `_timed` with a zero-cost runner and a monkeypatched `SLOW_POLL_SECONDS`,
  so it never reaches the new branch.
- Ledger: new (the commit is 4aaca6a, unledgered; CR-240i's note is the
  ancestor)
- Suggested fix: measure the lock, not the pass - time only the committing
  section (or `record_poll_run` + the runner's own commits) and pass that to
  `record_slow_write`; or give the poll branch its own threshold and its own
  wording ("the pass took N s", not "held the write lock"). Whichever, give
  `slow_write` a clearing writer so a fleet that has stopped being slow stops
  being told it is.

### dash-db-2 - the two notice kinds the busy rework writes are not in the registry, so the panel that exists to say what the server checks never mentions them
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:3165-3325` (`NOTICE_KINDS`, no
  `db_busy`, no `slow_write`), written at
  `dashboard/src/ccsync_dashboard/notices.py:1141` and `:1164`
- What: `NOTICE_KINDS` is the registry every rendered property of a notice is
  looked up in - `notice_kinds()` builds the WHAT THE SERVER CHECKS panel,
  `notice_href()` builds the [ TAKE ME THERE ] button, and `ui.py:1848`'s
  health rows take the row's TITLE from it. 4aaca6a added two writers and no
  registry rows, which is the mirror image of the 2026-08-28 finding 1 the
  registry was built for: not a false [ OK ], but a condition the server does
  check and never lists, rendered with a raw key for a title and no
  destination button.
- Failure scenario: a fleet under contention. The home page shows a row whose
  title is the literal string `db_busy` (ui.py falls back to
  `n.get("kind")`), with no [ TAKE ME THERE ], and the checks panel - the
  place an owner goes to learn what this server watches for - has no line for
  database contention at all, so "is it even looking?" has no answer.
- Evidence: AST sweep of every `notice(conn, <kind>, ...)` call in
  `ccsync_dashboard/*.py` against `db.NOTICE_KINDS`:
  `written but NOT registered: db_busy ['notices.py'], slow_write
  ['notices.py']` and `registered but no literal writer found: <none>`.
  `test_sweep_2026_09_04_dashboard.py::test_the_registered_kinds_all_have_a_writer_in_this_wave`
  pins the discipline for that wave's kinds only, so nothing failed.
- Ledger: new
- Suggested fix: add both kinds to `NOTICE_KINDS` (`db_busy`: warn, href
  `/fleet#fleet-diagnostics`; `slow_write`: warn, same) and make the
  registration test generic - assert that every kind any writer passes to
  `db.notice` is in the registry, which the AST sweep above shows is a
  three-line check.

### dash-db-3 - the busy handler answers contention by adding another writer to it
- Severity: medium
- Confidence: CONFIRMED (by reading both sides; the pile-up is PLAUSIBLE in
  degree, not in kind)
- Where: `dashboard/src/ccsync_dashboard/app.py:1354-1364`, calling
  `notices.record_db_busy` -> `db.notice` + `conn.commit()`
  (`dashboard/src/ccsync_dashboard/notices.py:1130`), over a fresh
  `db.connect(settings.db_path)` at the default `BUSY_TIMEOUT_MS`
- What: the request reached this handler precisely because it waited 5 s for
  the write lock and did not get it. The handler's response to that is to
  open a second connection and take the write lock (an upsert into `notices`
  plus a commit) with the same 5 s timeout. So the answer to "the database is
  busy" is one more waiter on the busy database, and the client's worst case
  becomes ~10 s rather than 5 - on the one route (`/api/v1/report`) the whole
  rework was written for, where every companion in the fleet is knocking.
  `record_server_error` has the same shape but fires on a defect, not on a
  condition defined by lock saturation.
- Failure scenario: four companions and the collector all reporting into a
  slow ZFS pool. Companion A waits 5 s, gets nothing, enters the handler,
  waits up to another 5 s for the notice write (which itself may raise
  `database is locked`, be swallowed by the `except Exception` and logged, so
  the contention is not even recorded), and only then gets its 503. During
  those extra seconds it is holding a connection and a lock request that the
  next companion is waiting behind. The record the feature exists to produce
  is the first thing lock saturation destroys.
- Evidence: read of both functions; `record_db_busy` ends in `conn.commit()`
  and is called synchronously inside the exception handler before the
  `JSONResponse` is constructed. `test_the_handler_answers_a_locked_database_503_with_retry_after`
  raises the error from a hand-registered route on an idle database, so the
  contended case is never exercised.
- Suggested fix: record the busy event with a SHORT busy timeout
  (`db.connect(..., busy_ms=250)`) and return the 503 regardless, or hand the
  event to a queue the collector drains - the 503 must not be able to wait on
  the same lock that caused it.
- Ledger: new

### dash-db-4 - the "who holds this file" query is a LIKE with the path's own wildcards unescaped
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:5494-5500`
  (`file_move_target_machines`)
- What: the manifest half of the target list matches
  `rel_path=? OR rel_path LIKE ?` with the pattern built as
  `media_rel_key(from_rel) + "/%"` and no `ESCAPE` clause. `_` is a
  single-character wildcard in SQL LIKE and is in almost every folder name
  this product handles (`Gold_Card_Meetup`, `A_001`), and `%` is legal in a
  filename too. The value is not attacker-controlled through SQL (it is a
  bound parameter), but it is pattern-controlled: the prefix matches more
  paths than the one being moved.
- Failure scenario: a directory move of `Gold_Card_Meetup`. A machine that
  holds `Gold-Card-Meetup/...` (or any sibling agreeing in length and
  differing only where an underscore sits) is added to the move's target
  list, is sent `commands.file_moves` for a file it does not have at that
  path, and answers not-applied. Harmless on the wire today because the
  companion's "already where the server has it" / not-found arms are
  forgiving, but it makes the move's per-machine progress row on the project
  page wrong, and the same predicate is the natural one to reuse for a
  refusal.
- Evidence: read of the statement; no `ESCAPE` anywhere in db.py (the only
  other LIKE on a path, `db.py:9445`, documents itself as a prefilter that a
  later exact check re-decides - this one has no such second pass).
- Ledger: new (the function itself is the 2026-09-11 dash-db-1 fix)
- Suggested fix: escape `%`, `_` and the escape character in `media_key`
  before appending `/%`, and add `ESCAPE '\'`.

### dash-db-5 - the assignments picker offers a computer whose grid can never have a column
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/assignments.py:171-184`
  (`_machine_options`) against `:95-108` (the column loop)
- What: `_machine_options` appends the "no computer yet (ticks no computer has
  claimed)" option, value `db.ANY_MACHINE` (`""`), whenever the person has
  bucket rows - including when they also have registered machines. The column
  loop only ever emits a `machine=""` column for a person with NO machines
  (`if not machines: ... continue`). Choosing that option therefore filters
  the columns to `machine == ""` and leaves none.
- Failure scenario: `editor1` has `EDIT-1` registered and a legacy
  `machine=''` selections row (the pre-WP5 shape, or a tick written before
  the companion first reported). The picker offers the bucket; choosing it
  renders a page with no grid and no cells, so the rows the option exists to
  expose are exactly the rows it cannot show.
- Evidence: scratch script driving the real app: with one machine and one
  bucket selection row, `/admin/assignments?editor=editor1` offers
  `('', 'no computer yet (ticks no computer has claimed)')`, and
  `/admin/assignments?editor=editor1&machine=` gives
  `grid present: False`, `machines in grid: set()`.
  `test_an_editor_with_no_computer_yet_gets_the_unassigned_bucket` covers only
  the no-machines case, so the suite is green.
- Ledger: new
- Suggested fix: either emit the bucket column whenever bucket rows exist for
  the chosen person (the honest fix - it is a real plan row), or offer the
  option only when the person has no registered machine, matching the column
  loop.

### dash-db-6 - a write-lock test in my territory failed once and will not reproduce
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/tests/test_db_write_locks.py:255`
  (`test_no_alert_is_sent_with_the_write_lock_held`)
- What: the first run of my five-file selection failed on this test; four
  identical re-runs passed. Its assertions are
  `len(opener.in_transaction) >= 2` and `not any(opener.in_transaction)`,
  both of which depend on how many subjects the fixture's own boot left open
  and on whether the shared `conn` happens to be mid-transaction when the
  webhook opener is called - state a neighbouring test file can influence. A
  test that pins "no network call under the write lock" and is order- or
  timing-sensitive is worth pinning down: the next time it goes red in the
  central gate nobody will know whether the invariant broke.
- Failure scenario: the full `run_all_tests.ps1` gate goes red on a
  reordering, or (worse) stays green while the invariant it guards has
  regressed, because the assertion is `>= 2` over a count nothing controls.
- Evidence: `1 failed, 112 passed, 1 skipped` on the first run of
  `pytest tests/test_db_busy_2026_09_17.py tests/test_admin_assignments.py
  tests/test_links.py tests/test_db.py tests/test_db_write_locks.py -q`,
  `113 passed` on four repeats of the same command. I did not capture the
  assertion text before it stopped reproducing.
- Ledger: new
- Suggested fix: have the test record the transaction state for a KNOWN set
  of subjects (clear the fixture's open alerts first) so the count is exact,
  and assert on that set rather than on `>= 2`.

## Coverage note

What I verified and found clean, so nobody need redo it:
- **Migrations v47..v53.** Built a v47-shaped and a v52-shaped database by
  running `db.migrate` with the step list truncated, then migrated each to
  HEAD: both reach `user_version=53`, `PRAGMA integrity_check` = ok,
  `PRAGMA foreign_key_check` = empty, and a second `migrate()` on the same
  connection is a no-op. Every step from v45 on is `ALTER TABLE ... ADD
  COLUMN` or `CREATE ... IF NOT EXISTS`, so the mid-step interrupt replay
  (`_already_applied`) covers all of them; `SCHEMA_V53`'s `NOT NULL DEFAULT
  'admin'` is a legal ADD COLUMN and matches the regex `_ADD_COLUMN_RE`
  parses. No backfill UPDATE anywhere in the range, so nothing is
  double-applied.
- **CR-240 / dash-db-2's `_schema_predates` readers** compose correctly with
  the busy rework: they re-raise `database is locked` (only "no such column"
  / "no such table" is swallowed), so a lock there now becomes a 503 rather
  than a silent fail-open. `assignments._assignments_view`'s
  `archived_unreadable` flag and its banner are the correct shape.
- `links.py` (including the 09-11 dash-db-3 entry cap and the sorted-prefix
  dedupe, whose `d + "/"` sort key is right), `runtime_id.py`, and
  `record_ignored_report_sections` / `forget_ignored_report_sections_of_older_build`
  (the writer does pass `dashboard_version=VERSION`, and the boot caller is
  `app.py:673`).
- `file_move_target_machines` sending a wired base rig a move off its
  manifest is NOT a defect: `companion/file_moves.py:364` answers "already
  where the server has it" when the destination exists and the source does
  not.

What I did not get to: the rest of db.py by volume - `prune`/retention
(whether `notices`, `file_moves` and `file_move_targets` are bounded, and
what a v53 `source` column means for the history query), `jobs`'s ranking
SQL, the `editor_media` / `media_tree_clips` write paths under the
non-atomic report, and the b-roll geometry columns (migration 012, which is
the `broll` territory's schema, not this one's). I also did not measure a
real contended database (two processes writing), which is what dash-db-3
needs to move from "confirmed shape" to "measured cost"; and I did not read
`schema.sql` line by line against the 53 steps for drift, only the tables the
week's diff touches.

What the suite does not cover: no test drives `Collector._timed` through the
new `record_slow_write` branch (dash-db-1); no test asserts that a written
notice kind is registered (dash-db-2); no test exercises the busy handler on
a database that is actually busy (dash-db-3); `test_admin_assignments.py`
has no case for a person who has both machines and bucket rows (dash-db-5).

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/app.py:1363`: `Retry-After: 30` is sent and
  nothing on the companion side reads it (`reporter.py` / `app.py` have no
  `Retry-After` handling at all) - the wire lens should judge whether the
  header is load-bearing or decorative.
- `dashboard/src/ccsync_dashboard/notices.py:1110` (`is_db_busy`): matches
  only the exact substring "database is locked". SQLite also emits "database
  table is locked" (and busy-on-commit variants); if any of those reach the
  handler they are still recorded as `server_error` with a "send to support"
  fix line.
