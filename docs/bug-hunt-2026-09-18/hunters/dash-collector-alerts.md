# dash-collector-alerts - the dashboard's collector, its alert/notice registry, health verdicts, protection and recovery

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/collector.py` (the whole hand-move block and
  `_record_inventory` / `_poll` in full; ~40% of the rest skimmed)
- `dashboard/src/ccsync_dashboard/notices.py` (the new "the lock" block in full,
  `record_server_error` and the registry comments around it)
- `dashboard/src/ccsync_dashboard/health.py` (whole diff since 34a3c8f: `_disk_floor_hit`,
  `_echo_words`/`_says_the_same`/`_unnest`/`_detail_clause`, `_why_first`, `_second_cause`,
  `lane_strip`, `fleet_headline`, `detail_notes`)
- `dashboard/src/ccsync_dashboard/invariants.py` (`_check_proxy_pairs` + its registry row)
- `dashboard/src/ccsync_dashboard/protection.py` (`refresh_line` in full, `run_cycle` tail)
- `dashboard/src/ccsync_dashboard/alerts.py` (`_check_code_not_applied` only)
- `dashboard/src/ccsync_dashboard/syncthing_client.py`, `mount_status.py`, `recovery.py`,
  `crash_report.py` (skimmed for resilience red flags; no finding)
- read as callees, not reported on: `db.py` (`nas_media_rows`, `replace_nas_media`,
  `file_move_recorded`, `record_file_move`, `file_move_target_machines`, `NOTICE_KINDS`,
  `notice_kinds`, `notice_href`, `mark_notice_checked`), `ui.py` (the notices panel and the
  protection ack route), `dashboard_update.version_tuple`,
  `companion/sync/lane_guard.py` (the lane B floor)
- docs: `CLAUDE.md`, `docs/HAND_MOVES_ON_THE_SERVER.md` (sections 3-7),
  `docs/FILE_MOVES.md` (skim), `KNOWN_BUGS.md` (grepped for CR-267, CR-269, CR-270, CR-278,
  hand move, proxy_pairs, db_busy, slow_write)
- tests: `test_hand_moves_detected.py` (full), `test_db_busy_2026_09_17.py`,
  `test_protection.py` (refresh_line part), `test_sweep_2026_09_04_dashboard.py`
  (the registry test)

Tests run:
`cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_hand_moves_detected.py tests/test_notices.py tests/test_health.py tests/test_protection.py tests/test_invariants.py -q`
-> 182 passed, 1 warning. Plus one ad-hoc snippet against `collector.detect_moves` from the
dashboard venv (scratchpad, outside the repo) for finding 3.

## Findings

### dash-collector-alerts-1 - a hand move BETWEEN two projects is detected only if both projects happen to fall in the same cycle's 8-project window, and the evidence is destroyed either way
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/collector.py:1663-1666` (the rotating window) and
  `:1706-1713` (`previous = db.nas_media_rows(...)` then `db.replace_nas_media(...)`), against
  `dashboard/src/ccsync_dashboard/collector.py:2277` (`_matched_pairs`, which matches only
  within the walks of ONE pass)
- What: `_record_inventory` walks at most `settings.inventory_projects_per_cycle` projects per
  cycle (default 8, `settings.py:569`) chosen by a rotating cursor, and skips any of those whose
  directory signature is unchanged. Only the projects walked in THIS pass become `InventoryWalk`
  entries, and `_matched_pairs` can only pair a vanish with an appearance inside that one list.
  A move that leaves project A for project B is a vanish in A's walk and an appearance in B's
  walk, so it is recognised only when A and B are both inside the same window. When they are
  not, the project that is walked first has its `nas_media` rows replaced by
  `replace_nas_media`, which is the only record of the pre-move state: the other half of the
  move arrives one or more cycles later with nothing left to match it against, and the move can
  never be detected again. The same permanent loss happens when one of the two projects'
  replacements is refused by the collapse brake (the `else` at `:1714`), because the refused
  project is deliberately left out of `diffs` while the other one's rows have already been
  overwritten.
- Failure scenario: a fleet with more than 8 active projects (this studio has well over 8:
  FF3, FF4, FF5 and its episodes, Creator Profiles, Repro Rights, CIA_City, Base Drone, ...).
  An admin moves the Gold Card Meetup shoot from `Creator Profiles` to `FF5 Talent Gap` in
  Explorer on the NAS - the exact incident in `docs/HAND_MOVES_ON_THE_SERVER.md` that this
  feature was built for. If the two projects' indices are not in the same rotating block, the
  collector walks `Creator Profiles`, replaces its inventory, records nothing, and on a later
  cycle walks `FF5 Talent Gap` and sees only new files. No `file_moves` row is written, no
  machine follows, every machine that holds the clips re-uploads them to the old path on its
  next lane A pass, lane B sees them as deletions, and CR-267a's two-day trail of warnings and
  parked breakers happens again - with the dashboard now reporting the check as having run
  (`db.mark_notice_checked("file_move_detected")` is stamped unconditionally at `:1746`).
- Evidence: `selected = [active[(start + i) % n] for i in range(min(window, n))]` at `:1666`,
  with `window = self.settings.inventory_projects_per_cycle` (`settings.py:569`
  `inventory_projects_per_cycle: int = 8`). `diffs` is built only from `walked`, and
  `_record_detected_moves(conn, diffs, now)` is the only caller of `detect_moves`. The suite
  does not catch this: `test_a_move_between_two_projects_is_matched_across_the_pass`
  (`dashboard/tests/test_hand_moves_detected.py:71`) calls `detect_moves([walkA, walkB])`
  directly with both walks already in one list, which is precisely the precondition the
  collector does not guarantee; the end-to-end test
  (`test_a_hand_move_between_two_walks_becomes_a_detected_row_the_fleet_follows`, `:189`) uses a
  two-project fixture, i.e. fewer projects than the window.
- Ledger: new (CR-267a is the incident this feature answers; it is FIXED in the ledger, and
  this is the case in which the fix does not fire)
- Suggested fix: make the cross-project matcher independent of the window - either force a
  pass that detects a vanish to walk every active project before replacing any inventory, or
  persist the unmatched vanishes/appearances of a pass (a small `nas_media_pending_moves`
  table, aged out after a cycle or two) so the halves can be paired across consecutive cycles.
  At minimum, refuse to consume a vanish whose project's partner was not walked, and log it.

### dash-collector-alerts-2 - the 500-move cap drops the rest of a pass permanently, while its log line promises they will be picked up later
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/collector.py:1750-1756` (`moves = moves[:DETECTED_MOVE_LIMIT]`)
- What: when a pass finds more than `DETECTED_MOVE_LIMIT` (500) moves, the surplus is sliced
  off with a warning that says the rest "are picked up on later cycles". They are not: the
  `nas_media` rows that were the only evidence of their old paths were already replaced by
  `replace_nas_media` in the same function, several lines earlier. A later cycle sees the files
  at their new paths as ordinary inventory.
- Failure scenario: an admin reorganises a 700-clip archive on the NAS in one afternoon. The
  next inventory pass detects 700 moves, records the first 500 (alphabetically by
  `(from_slug, from_rel)`) and silently discards 200. Those 200 files are deletions as far as
  every machine is concerned: lane A re-uploads them to the old paths, lane B's breaker sees
  200 vanished files and parks proxy download on every machine that held them, and the operator
  is told nothing except one `log.warning` in a container log that a recreate throws away.
- Evidence: the slice at `:1756` runs after the `for ... in walked:` loop at `:1706-1713` has
  already called `db.replace_nas_media`. `detect_moves` sorts before returning
  (`sorted(moves, key=lambda m: (m.from_slug, m.from_rel))`), so the truncation is alphabetical,
  not by importance. Nothing writes a notice for the discarded remainder.
- Ledger: new
- Suggested fix: when the cap is hit, do not replace the inventory for the projects whose moves
  were dropped (so the next pass can still see them), or file an `error` notice naming the
  count so the operator can use the MOVE button for the rest. A log line that states an untruth
  is worse than the cap itself.

### dash-collector-alerts-3 - a folder RENAMED in place becomes one detected row per file, not one folder row
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/collector.py:2322-2334` (`_folder_move`: `for depth in
  range(shared, 1, -1)`), against `docs/HAND_MOVES_ON_THE_SERVER.md` section 7 phase 1
  ("batch a folder move into one row per folder")
- What: `_folder_move` counts how many trailing path components the old and new paths share and
  then only considers folder depths `>= 2`. For a rename of the leaf folder itself
  (`B-roll/A001.braw` -> `Broll/A001.braw`) only the basename is shared, `shared == 1`, and
  `range(1, 1, -1)` is empty, so the function returns None and every file falls through to the
  per-file loop. Only a folder MOVED under a different parent (which shares the folder name as
  well as the basename) is batched.
- Failure scenario: an admin fixes a typo in a shoot folder's name on the NAS - a 300-clip
  `Interviews` -> `Interviews 2026` rename. Instead of one `file_moves` row for the folder,
  the collector writes 300 rows, sends 300 `commands.file_moves` entries to every holding
  machine, floods the project page's MOVES history with 300 events, and comes within a third of
  finding 2's 500-row cap in a single pass. A rename of 600 files crosses it and loses the tail.
- Evidence: ad-hoc snippet from the dashboard venv against `collector.detect_moves` with
  `old=[B-roll/A001.braw, B-roll/A002.braw, B-roll/Proxy/A001.mov]`,
  `new=[Broll/...]` returned two `DetectedMove`s with `is_dir=False`
  (`from_rel='B-roll/A001.braw'` and `from_rel='B-roll/A002.braw'`), not one row with
  `is_dir=True`. `test_a_whole_folder_is_one_row_not_one_per_file`
  (`dashboard/tests/test_hand_moves_detected.py:59`) only covers the moved-under-a-new-parent
  shape (`B-roll` -> `Archive/B-roll`), so the rename case is untested.
- Ledger: new
- Suggested fix: derive the candidate folder from the longest common PREFIX of the two paths as
  well as the common suffix (the parent of the first differing component), and let
  `_folder_members` do the proving as it already does; the safety bar it applies is unchanged.

### dash-collector-alerts-4 - the new "slow write" notice blames the collector for holding a write lock the collector deliberately does not hold
- Severity: medium
- Confidence: CONFIRMED (mechanism); PLAUSIBLE that it fires on this fleet every cycle
- Where: `dashboard/src/ccsync_dashboard/collector.py:488-500` and
  `dashboard/src/ccsync_dashboard/notices.py:1152-1180` (`record_slow_write`)
- What: `_poll` measures the WALL TIME of a whole poll (`time.monotonic()` around `fn(conn)`)
  and, whenever it exceeds `db.BUSY_TIMEOUT_MS / 1000.0` (5 s), files a warn notice whose body
  asserts that the poll "held the database's write lock for longer than a request waits". The
  inventory poll's own docstring at `:1634-1638` says the opposite and by design: "Every
  filesystem walk happens BEFORE the first write: an os.walk of a ZFS/NFS tree inside an open
  SQLite write transaction is what made editors' POST /api/v1/report 500". The same is true of
  the syncthing poll, which spends its time on HTTP calls. Elapsed poll time is not lock-hold
  time, and the notice states it as fact.
- Failure scenario: the NAS walk of a large project tree takes 40 s (entirely outside any
  transaction). The home page grows a permanent `slow_write` warn card reading "N time(s)
  collector poll inventory held the database's write lock for longer than a request waits", N
  climbing every fifteen minutes, whose fix text tells the operator to "untick the projects it
  does not need" or "send Diagnostics to support". Meanwhile the notice that WOULD be the real
  culprit of a `db_busy` (a genuinely long write) is indistinguishable from this noise, so the
  cross-reference the `db_busy` fix text promises ("look for a slow write from the same minute")
  points at an innocent pass. Nothing ever clears these notices, so one slow walk leaves a card
  an admin has to dismiss by hand.
- Evidence: `if elapsed > db.BUSY_TIMEOUT_MS / 1000.0` at `:494` with `elapsed` computed at
  `:487` from `clock_started` set at `:471`, i.e. the whole of `fn(conn)`;
  `db.BUSY_TIMEOUT_MS = 5000` (`db.py:686`); `SLOW_POLL_SECONDS = 1.0` (`collector.py:117`).
  `notices.record_slow_write`'s body string is the claim. `dashboard/tests/test_db_busy_2026_09_17.py`
  exercises `record_slow_write` directly with a made-up duration and never asserts that the
  writer named actually held a lock.
- Ledger: new (the writer half of the 4aaca6a "contention, not a server error" rework)
- Suggested fix: measure the write burst, not the poll - time from the first write to the
  commit (or pass the burst duration in from `_record_inventory`) - and only record a slow write
  when that exceeds the busy timeout. If the whole-poll timing is wanted too, give it its own
  wording ("took N s" / "one pass took longer than a cycle"), not a lock claim.

### dash-collector-alerts-5 - `db_busy` and `slow_write` are notice kinds with a writer but no registry row
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/notices.py:1106-1107` (the kinds) vs
  `dashboard/src/ccsync_dashboard/db.py:3165-3325` (`NOTICE_KINDS`, which has no entry for
  either); rendered at `dashboard/src/ccsync_dashboard/ui.py:1848-1852`
- What: both new kinds are written but not registered. `db.notice_kinds()` is the WHAT THE
  SERVER CHECKS panel and the source of each row's sentence; an unregistered kind is absent
  from the panel (so the operator cannot tell "never happened" from "not a check this build
  has") and, on the health diagnostics rows, `kind_what.get(...)` misses and the title falls
  back to the raw key - a card headed `db_busy`. `db.notice_href` also returns `("", "")`, so
  the row gets no [ TAKE ME THERE ] button. Its sibling in the same module, `server_error`, IS
  registered (`db.py:3300`), which is the precedent, and CLAUDE.md states the registry rule
  ("Register a notice kind WITH its writer").
- Failure scenario: a fleet under contention shows an operator a problem card titled
  `slow_write` with no link and no registry line, and the checks panel silently omits the two
  kinds the 2026-09-17 rework added.
- Evidence: `grep -n '"db_busy"\|"slow_write"' dashboard/src/ccsync_dashboard/db.py` -> no
  match; `grep -n "server_error" ...db.py` -> `3300: "server_error": {"severity": "error", ...`.
  `test_sweep_2026_09_04_dashboard.py:163` pins exactly this rule for the kinds ITS wave added,
  so the convention is established and these two were missed.
- Ledger: new
- Suggested fix: add both to `NOTICE_KINDS` (severity `warn`, an operator-readable `what`, and
  an `href` to `/fleet#fleet-diagnostics`), and stamp `mark_notice_checked` for them from the
  poll so they do not read [ NOT CHECKED ] for ever on a healthy server.

### dash-collector-alerts-6 - the dashboard's stand-in for the companion's disk floor is hard-coded, so a machine with a configured floor is described wrongly
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/health.py:284-297` (`_disk_floor_hit`, compares against
  the constant `DISK_RED_FREE_BYTES`) vs
  `companion/src/ccsync_companion/sync/lane_guard.py:954`
  (`cfg_int(cfg, "lane_b_min_free_bytes", DEFAULT_LANE_B_MIN_FREE_BYTES)`)
- What: CR-269 correctly replaced the 5% chip with "the companion's floor", but the companion's
  floor is a per-machine config key with 20 GB only as its DEFAULT. The dashboard asserts the
  default for every machine.
- Failure scenario: an editor on a small SSD sets `lane_b_min_free_bytes` to 60 GB. The
  companion parks lane B at 55 GB free; a dashboard talking to a build too old to report
  `blocked_reason == "disk_full"` says nothing at all, because 55 GB is above the hard-coded
  20 GB. The inverse (a floor lowered to 5 GB) puts "proxy download stopped itself" on a row
  for a machine that is still downloading - the same class of false sentence CR-269 fixed.
- Evidence: the two lines above; the companion reports no floor value in its report payload, so
  the dashboard has nothing to read (grep of `reporter.py` for `lane_b_min_free` -> no match).
- Ledger: related to CR-269 (fixed) - CR-269 does not fix the configured-floor case
- Suggested fix: have the companion report its effective floor (one integer on the guard block)
  and read it here with the 20 GB constant as the fallback; this branch is only for builds too
  old to send `blocked_reason` anyway, so the fallback stays correct for them.

## Coverage note
- Read but not exhaustively hunted: `recovery.py` (1110 lines, the wizard's generated
  commands), `alerts.py` beyond `_check_code_not_applied` (~4400 lines, forty alert kinds -
  only the changed hunk was read with care), `crash_report.py`, `mount_status.py` and
  `syncthing_client.py` (skimmed; timeouts are set on every Syncthing call and nothing there
  retries without a ceiling, but I did not trace their callers).
- Not covered by the suite, and not covered here either: the collector's behaviour with more
  active projects than `inventory_projects_per_cycle` (finding 1) - no test in
  `dashboard/tests` constructs that fleet shape at all; and the interaction between hand-move
  detection and a project whose replacement is refused by the collapse brake in the SAME pass.
- I did not measure a real inventory poll's duration (read-only rule, live dashboard off
  limits), so finding 4's "fires every cycle on this fleet" is inference from the walk's own
  docstring, not measurement.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/api.py:9402-9408`: the other `record_slow_write` caller - the
  same wall-clock-vs-lock-hold question applies to `api_report` and should be checked by dash-api.
- `dashboard/src/ccsync_dashboard/ui.py:1848-1852`: an unregistered notice kind renders its raw
  key as a card title with no link; a `kind_what` miss could fall back to something friendlier.
