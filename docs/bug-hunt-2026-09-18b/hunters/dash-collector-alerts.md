# dash-collector-alerts - the collector cycle, the notices/alerts registries, and the server's own self-diagnosis

Files read (with approximate coverage): `git diff` of
`dashboard/src/ccsync_dashboard/collector.py` (100% of the hunks, plus
`_record_inventory`, `_timed`, `_matched_pairs`, `_folder_move` in full),
`notices.py` (100% of the hunks + `run_checks`, the record_* writers),
`alerts.py` (100% of the hunks + `_check_notices`, `_check_nas_tree`, `Ctx`),
`health.py` (100% of the hunks + `_why_get`, `_why_first`, `_second_cause`,
`detail_notes`), `mount_status.py` (whole file), `db.py` (NOTICE_KINDS,
`mark_notice_checked`, `notice`, SCHEMA_V54, `record/pending/delete_pending_move_halves`,
`prune`, machines/file_move* schema), `api.py` (the sync_guard ingest of
`disk_floor_bytes` / `stalled_at`), `broll.py` (`record_root`),
`broll/web/app/routes_api.py` (`insert_target_detail`), companion
`sync/rclone_lane.py` (stall record + `stall_report`), `sync/lane_guard.py`
(`DiskFloorLatch.report`). `invariants.py`, `protection.py`, `recovery.py`,
`crash_report.py`, `syncthing_client.py` are unchanged by this pass and got a
skim only.

Tests run:
`dashboard/.venv/Scripts/python.exe -m pytest tests/test_notices.py tests/test_bug_hunt_2026_09_18_dashboard_mediums.py -q` -> 56 passed.
Two ad-hoc snippets against `collector.unpaired_halves` / `pair_across_cycles`
from the dashboard venv (output quoted below).

## Findings

### dash-collector-alerts-1 - cross-cycle move pairing invents a fleet-wide file move from an unrelated delete and arrival two days apart
- Severity: high
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (frequency)
- Where: `dashboard/src/ccsync_dashboard/collector.py:2564` (`unpaired_halves`), `:2626` (`pair_across_cycles`), consumed at `:1909` (`_moves_including_carried_halves`) and acted on at `:1876-1906` (`_record_detected_moves`)
- What: the within-pass matcher had an implicit proof that two halves belong to
  ONE act: both were observed in a single atomic before/after picture of the
  same projects in the same window. `pair_across_cycles` drops that proof and
  keeps pairing on `(basename, size, mtime_ns)` alone, across up to
  `PENDING_MOVE_HALF_MAX_AGE_DAYS` = 2 days and across every project in the
  fleet. The result is not a suggestion: `_record_detected_moves` writes a
  `file_moves` row with `requested_by=DETECTED_MOVE_ACTOR` and
  `state=FILE_MOVE_DONE` and targets every machine holding the source file, so
  each of those companions MOVES its own copy and relinks Resolve, unattended,
  with no admin confirmation anywhere in the path.
- Failure scenario: an editor copies `A001_C003.mov` from project A into
  project B on their machine and lane A uploads it into B (a first-time
  ARRIVAL there - the copy preserves size and mtime). Some hours or a day
  later the copy in project A is deleted on the NAS (by hand, or by a lane C
  delete propagating). The two events land in different inventory passes; the
  carried half pairs them and the server tells every machine that still holds
  A's copy to move its file into project B's path and relink Resolve - a
  project many of those machines have no tick for. Reproduced:
  ```
  pass1 halves: [_Half(half='vanished', base='a.mov', size=100, mtime_ns=111, slug='A', rel_path='Old/a.mov', ...)]
  moves: [('A', 'Old/a.mov', 'B', 'Footage/a.mov', False, 1)]
  ```
  (two separate `unpaired_halves` calls, exactly as two cycles would produce
  them, then `pair_across_cycles`).
- Evidence: the snippet above, run from `dashboard/.venv`; plus
  `_record_detected_moves`'s unconditional `db.record_file_move(...,
  targets=targets, state=db.FILE_MOVE_DONE)`. There is NO test anywhere in
  `dashboard/tests` for `unpaired_halves`, `pair_across_cycles`,
  `_settle_halves` or `nas_media_pending_moves`
  (`grep -rn "pair_across_cycles\|unpaired_halves" dashboard/tests` -> nothing),
  so the largest new mechanism in this territory - a new table plus an
  inference that moves files on editors' machines - ships unpinned.
- Ledger: new (the fix is the new half of CR-285/`dash-collector-alerts-1`;
  this is the neighbour it opens)
- Suggested fix: require more than a byte-identity match across cycles before
  ACTING: either cut the window hard (one or two cycles, not two days), or
  record a cross-cycle pair as a `file_move_detected` notice for a human to
  confirm on the project page instead of an auto-issued `FILE_MOVE_DONE`, or
  refuse a pair whose destination project had no prior inventory (see
  dash-collector-alerts-3). At minimum add the pairing tests.

### dash-collector-alerts-2 - the new b-roll archive check cannot fire on the failure it was written for, and its test pins the wrong answer
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/notices.py:786-815` (`_check_broll_archive`), the same code in `dashboard/src/ccsync_dashboard/alerts.py:1998-2038`, test at `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_mediums.py:409-428`
- What: both copies probe `mount_status.root_of("broll")[0]` - the RECORDED
  ROOT - and treat "scandir succeeded" as healthy. `mount_status.record_root`'s
  own docstring says why that cannot work: "A bind mount that goes away LEAVES
  ITS MOUNT POINT BEHIND, so probing the root is probing a directory that is
  there either way", which is the entire reason the `witness` argument exists
  and the reason `broll.py:600` records `get_proxies_dir()` as b-roll's
  witness. The check ignores the witness. An unmounted dataset leaves an empty
  (or stale) mount point that scandirs fine, so the check answers OK in
  precisely the outage it exists for. Note also that the rest of this codebase
  treats ZERO ENTRIES as the canary (`collector._record_inventory`'s
  NOT-MOUNTED CANARY, `alerts._check_nas_tree`'s "is there but completely
  empty"); here an empty root is silently healthy.
- Failure scenario: the b-roll dataset unmounts under a running container.
  `insert_target_detail` starts answering `known: false` for every clip, every
  Send to Resolve degrades to a preview-only insert, and neither the PROBLEMS
  panel nor the alert mail says a word - the exact silence proxy-tiers-3 was
  written to end.
- Evidence: `mount_status.py:74-93` (record_root docstring), `broll.py:592-601`
  (root vs witness), and the test itself, which creates a root that does not
  exist (ENOENT) to raise the card and then asserts the card CLEARS when the
  directory is created EMPTY - i.e. it pins "an empty mount point is fine".
  `except StopIteration` in both copies is dead code: `next(it, None)` never
  raises.
- Ledger: "CR-285R / proxy-tiers-3's dashboard half does not fix the reported scenario"
- Suggested fix: probe the recorded WITNESS (`root_of()[1]`, the `proxies`
  directory) and treat an empty root as unreadable, the way `_check_nas_tree`
  and the inventory canary already do; update the test to cover the
  empty-mount-point case instead of asserting it is healthy.

### dash-collector-alerts-3 - a project's FIRST inventory writes one pending half per file, inside the collector's write burst
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/collector.py:2564` (`unpaired_halves`), written by `_settle_halves` at `:2685` via `db.record_pending_move_halves`
- What: `InventoryWalk.old` is `db.nas_media_rows(conn, pid)`, which is EMPTY
  for a project the collector has never walked, so every media file in a newly
  activated project counts as an "appeared" half and is persisted. There is no
  cap on the write side (`PENDING_MOVE_HALF_LIMIT` = 4000 bounds the READ
  only), so the executemany runs inside phase 2's "one short write burst" -
  the write transaction `_record_inventory`'s own docstring is built to keep
  short, because holding it is what made editors' `POST /api/v1/report` 500
  with "database is locked".
- Failure scenario: a new episode project with 5,000-50,000 media files is
  activated. The first walk inserts that many rows in one executemany on the
  collector's connection, and for two days every one of them is live evidence
  that a file "arrived" there - candidate matches for any genuine deletion
  elsewhere in the fleet (see finding 1).
- Evidence: snippet from `dashboard/.venv`:
  `unpaired_halves([InventoryWalk(slug='B', old=[], new=[2 files])])` ->
  `halves from a first walk: 2 appeared`. `db.record_pending_move_halves` has
  no limit; `db.pending_move_halves` has one.
- Ledger: new
- Suggested fix: skip walks whose `old` is empty (a project's first inventory
  is not evidence that anything arrived), and cap the halves persisted per
  pass the same way the read is capped.

### dash-collector-alerts-4 - one permanently unreadable project directory makes the hand-move check read [ NOT CHECKED ] for ever on a small fleet
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/collector.py:1821-1843` (`_record_detected_moves`, the `if blind:` branch), called from `:1796-1800`
- What: the stamp `db.mark_notice_checked("file_move_detected", now)` is now
  skipped whenever ANY project in the window was unreadable or refused. The
  window is `inventory_projects_per_cycle` (8) selected by a rotating cursor,
  so on a fleet with 8 or fewer active projects EVERY pass contains the bad
  project and the kind is never stamped at all - which the WHAT THE SERVER
  CHECKS panel renders as [ NOT CHECKED ], not as "a time going stale" as the
  comment claims. Meanwhile detection has in fact run over the seven readable
  projects and may have issued fleet-wide moves from them.
- Failure scenario: a small studio has 6 projects and one of them was renamed
  on the NAS, so `record_inventory_error(pid, "project dir missing on NAS")`
  fires every cycle. From that day the panel says the server does not check
  for hand moves, for ever, while it does - and the one honest reading of
  [ NOT CHECKED ] ("no writer in this build") is now indistinguishable from
  "one folder is missing".
- Evidence: `blind=len(errors) + refused` is fleet-window-wide, not per
  project; `errors` is appended for a missing project dir and for a dir with
  no `.stfolder`, both of which are durable states. `db.mark_notice_checked`
  is the only writer of the stamp for this kind.
- Ledger: new (neighbour opened by `dash-collector-alerts-1`'s own blind-pass fix)
- Suggested fix: stamp per pass but carry the blindness in the evidence (e.g.
  stamp when at least one project was fully read, and record the unread count
  on the panel), or scope the skip to the projects that were blind rather than
  to the whole kind.

### dash-collector-alerts-5 - a machine that switched its disk floor OFF is told its proxy download "has probably stopped itself"
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/health.py:296-311` (`machine_disk_floor`), used at `:321-336` (`_disk_floor_hit`), `:686-720` (`_why_sentence`) and `alerts.py:1390-1396`
- What: `machine_disk_floor` returns `floor if floor > 0 else None`, and None
  means "fall back to the 20 GB default". But zero is a documented VALUE on the
  companion, not an absence: `lane_guard.DiskFloorLatch.enabled` says "A floor
  of 0 turns the whole device off, like every other knob here", and that value
  now reaches the dashboard on `disk_floor_bytes`. So the one machine that has
  positively said "I never park for disk space" is the one this server
  compares against its own 20 GB.
- Failure scenario: an editor with the floor disabled drops to 15 GB free. The
  grid's why sentence becomes "Proxy download has probably stopped itself...",
  `_why_first` ranks the row as `disk_full`, and `_check_disk_low` mails a RED
  disk alert - about a machine that is still downloading normally.
- Evidence: `companion/src/ccsync_companion/sync/lane_guard.py:966-969`
  (`enabled`), `:990` (`floor_bytes` is `self.min_free_bytes`, sent verbatim),
  `health.py:311`.
- Ledger: new (`dash-collector-alerts-6` of the fix pass does not cover floor = 0)
- Suggested fix: distinguish absent from zero - return 0 as a real answer and
  have `_disk_floor_hit` answer False for it, keeping the default only for
  `None`.

### dash-collector-alerts-6 - the unreadable b-roll archive is mailed twice
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/alerts.py:1970-1996` (`_check_notices`) vs the new `broll_archive_unreadable` row at `:3387-3392`
- What: `_check_notices` turns EVERY open notice of severity `error` into a
  finding, and `notices._check_broll_archive` writes exactly such a notice. The
  new dedicated alert kind re-does the same scandir, so one unreadable archive
  produces two findings, two mails and two recovery mails, with two different
  subjects (`notice kind=broll_archive_unreadable` and `path=<root>`) so the
  dedup cannot collapse them.
- Failure scenario: the dataset unmounts (once finding 2 is fixed so the check
  can fire at all): the owner gets the same problem twice a day from two kinds.
- Evidence: `_check_notices`' SQL is `WHERE cleared_at IS NULL AND
  severity='error'` with no kind exclusion; `notices.BROLL_ARCHIVE_KIND` is
  written at severity `"error"`.
- Ledger: new
- Suggested fix: either drop the notice writer and keep the alert row, or
  exclude kinds that have their own `AlertKind` from `_check_notices`.

### dash-collector-alerts-7 - `_slow_poll_open` gives up for the life of the process on one failed read, and two modules now own `SLOW_POLL_SECONDS`
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/collector.py:543-566` and `:117` vs `notices.py:1290`
- What: `_slow_poll_open` adds the kind to `_slow_polls_asked` BEFORE the
  SELECT and returns False on any exception, so a single transient failure
  (a locked database - the very condition this release is about) means the
  process never asks again, and a `slow_poll` card that survived a container
  restart then stays open until the next restart. Separately,
  `collector.SLOW_POLL_SECONDS` is 1.0 (the log line) and
  `notices.SLOW_POLL_SECONDS` is 60.0 (the card); two module constants with
  one name and two meanings, read six lines apart, is how the next edit picks
  the wrong one.
- Failure scenario: the inventory pass overruns once, a card opens, the
  container restarts, the first `_slow_poll_open` hits a busy database, and the
  card stays on the home page for ever although every pass since has been fast.
- Evidence: `self._slow_polls_asked.add(kind)` precedes the `try`; the
  `except` returns False without discarding it.
- Ledger: new (`dash-db-1` / `dash-collector-alerts-4` of the fix pass)
- Suggested fix: only mark the kind as asked when the SELECT actually answered.

## Coverage note
Not got to: `invariants.py`, `protection.py`, `recovery.py`,
`crash_report.py`, `syncthing_client.py` beyond a skim - none is touched by
this pass. I did not exercise `_folder_move`'s new "rename in place"
candidate against real path data beyond reading it (it looks right for
`A/B/f` -> `A/B2/f`, and `_folder_members` still does the proving), and I did
not test `_settle_halves`' persistence against a real database. The suite
does not cover `unpaired_halves`, `pair_across_cycles`, `_settle_halves`,
`nas_media_pending_moves` retention, the `blind` skip, or the b-roll archive
check's empty-mount-point case.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/health.py` `detail_notes` (dash-mounts-ui-4's additions) reads `guard["trash_bytes"]` against a 5 GB threshold hard-coded to match the TEMPLATE's: two copies of one number, in two files, with a comment saying they must agree.
- `broll/web/app/routes_api.py:131` `os.listdir(top_dir_fs)` is the only listing behind `known`; a b-roll data root that is present but EMPTY (unmounted bind mount whose mount point survives) raises ENOENT on the subfolder, so that side is correct - it is only the dashboard's check that is blind.
