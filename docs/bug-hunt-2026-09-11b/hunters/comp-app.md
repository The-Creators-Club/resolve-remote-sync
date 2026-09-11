# comp-app - the companion app core (app.py, config, site, identity, machine, eula, reporter, idle, ui_state/ui_copy, paths/canon/secretfile, shutdown_guard, theme)

Files read (with approximate coverage): `git diff 40f931a..HEAD` over the whole
territory in full (app.py +425 lines, config.py, eula.py, machine.py,
ui_copy.py); `companion/src/ccsync_companion/app.py` - LaneWatchdog and its
record (~lines 839-1210), `_lanes_refusal`/`_start_lanes`/`sync_now`/
`sync_now_result`, `_on_root_absent`, `_handle_non_canonical`,
`consolidate_project` + `_consolidate_summary`, `_apply_file_moves` +
`_queue_file_move_answer`, `_watcher_list`/`resolve_health`, `sync_guard`,
`retry_loopback_bind`/`_start_broll_server`/`_note_loopback_state`,
`_log_tray_state` (~40% of the file, chosen by the diff and by the data/fleet
paths); `machine.py` and `eula.py` in full; `ui_copy.py` in full;
`reporter.py` `_machine_id`/`_syncthing_device_id`; `config.py` VERSION block;
`companion/tests/test_bug_hunt_2026_09_11_comp_app.py` in full. Both sides of
the file-move wire: `dashboard/src/ccsync_dashboard/db.py`
(`pending_file_moves`, `mark_file_move_applied`, `expire_delivered_file_moves`)
and `api.py`'s report handler.

Tests run:
`cd companion; .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_comp_app.py tests/test_broll_wiring.py -q` -> 51 passed.
`cd companion; .venv\Scripts\python.exe -m pytest tests/test_app.py tests/test_machine.py tests/test_eula.py -q` -> 418 passed.
Plus a scratch simulation of `LaneWatchdog` against a permanently dead
sequencer (scratchpad, outside the repo) - output quoted below.

## Findings

### comp-app-1 - comp-sync-20's "retrying while the drive is out" does not stop the 7 day expiry it was written to stop
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:7556` (the new `_queue_file_move_answer(..., state="retrying", attempts=0)`), against `dashboard/src/ccsync_dashboard/db.py:5480` (`expire_delivered_file_moves`) and `dashboard/src/ccsync_dashboard/db.py:5556` (`mark_file_move_applied`'s retrying arm)
- What: the companion half now answers `state="retrying"` while `local_root` is
  absent, on the stated ground that the dashboard "EXPIRES it after 7 days of
  told and never answered". The dashboard does not read `state` when it
  expires: `expire_delivered_file_moves` selects on `applied_at IS NULL AND
  expired_at IS NULL AND delivered_at < cutoff`, and the `retrying` arm of
  `mark_file_move_applied` updates only `state`, `attempts`, `last_error` and
  `detail` - it never sets `applied_at` and never refreshes `delivered_at`. The
  companion side of the fix landed; the dashboard side did not.
- Failure scenario: an editor leaves for a two week shoot with the sync drive in
  their bag. Day 1 the dashboard delivers file move #7 and the companion answers
  `retrying: waiting for the sync drive (P: drive)` every report. Day 8
  `expire_delivered_file_moves` stamps `expired_at` anyway; `pending_file_moves`
  filters on `t.expired_at IS NULL`, so the command stops being offered. Day 15
  the editor plugs the drive in, lane A (which never deletes) re-uploads the
  file at the OLD path, and the move is undone on the server - the exact
  failure `docs/FILE_MOVES.md` exists to prevent.
- Evidence: read both SQL statements. `mark_file_move_applied`'s retrying branch
  is `UPDATE file_move_targets SET state=?, attempts=?, last_error=?, detail=?
  WHERE ... AND applied_at IS NULL` - no `delivered_at`, no `expired_at`.
  `expire_delivered_file_moves`'s WHERE clause does not mention `state`. No
  other call site in `api.py` touches `delivered_at` on an inbound outcome
  (`grep -n "mark_file_move_applied|delivered_at" api.py` -> one hit, line 8994).
- Ledger: CR-244/CR-247 (the file-moves half of the 2026-09-11 fix pass) does not fix comp-sync-20
- Suggested fix: either exclude `state='retrying'` rows from
  `expire_delivered_file_moves`, or have the retrying arm bump `delivered_at`
  to `now` so the 7 day clock measures silence rather than age. The first is
  safer: "the machine is still talking to us" is exactly the condition the
  expiry is meant not to fire on.

### comp-app-2 - the same answer floods the dashboard log once per move per report for as long as the drive is out
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:7556`, against `dashboard/src/ccsync_dashboard/api.py:8994`
- What: `pending_file_moves` re-offers every unanswered move on EVERY report
  (its bound is delivery, not an answer), and `mark_file_move_applied`'s
  retrying UPDATE matches every time (`applied_at IS NULL`), so it returns
  `rowcount > 0` and `api.py` writes `log.warning("%s/%s file move #%s:
  RETRYING (waiting for the sync drive ...)")` on every report. Before this
  change the drive-absent case was silent on the wire and wrote nothing.
- Failure scenario: one editor away for a week with three pending moves and a
  30 s report interval produces 3 x 2 x 60 x 24 x 7 = about 60,000 identical
  WARNING lines in the dashboard log - the log an admin opens to find out why
  something else went wrong that week.
- Evidence: `api.py:8993-9002` (`(log.info if outcome.ok else log.warning)`,
  unconditional on the rowcount being true), `db.py:5556-5564` (the retrying
  UPDATE cannot become a no-op), `db.py:5466-5476` (`pending_file_moves` bounds
  by delivery only, so the command rides every reply).
- Ledger: new (side effect of comp-sync-20's fix)
- Suggested fix: log the retrying answer only when `state` or `detail` changed
  for that target (the row already holds the previous `detail`), or have the
  companion queue the drive-absent answer once per outage rather than once per
  report.

### comp-app-3 - the watchdog's hourly ceiling is unreachable: the constants make it dead code, and the two tests that assert it pass on the backoff instead
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:1002` (`_restart_held_off`), constants at `app.py:873-879`; tests `companion/tests/test_bug_hunt_2026_09_11_comp_app.py:416` and `:430`
- What: the wait before attempt N+1 is `60 * 2**len(recent)` seconds, so the
  earliest six restarts fall at t = 0, 120, 360, 840, 1800 and 3720 s. By the
  time a sixth could happen the first has aged out of the one hour window, and
  `len(recent)` never reaches `LANE_WATCHDOG_MAX_RESTARTS_PER_HOUR = 6`. The
  branch that says "this needs a human, not another restart" can never run, so
  a permanently dead sequencer is restarted for ever - 97 times in 24 hours -
  which is the behaviour comp-app-7 says it removed.
- Failure scenario: a sequencer whose `start()` succeeds but whose loop dies
  immediately (a selection client that is gone, the shape the fix names).
  Expected: six restarts and then a stop that makes the fault visible.
  Actual: an indefinite restart every ~15 minutes for the life of the process.
- Evidence: scratch simulation against the real `LaneWatchdog` with a
  `thread_died() -> True` sequencer and an injected clock, 24 h of ticks:
  `restarts over 24h: 97`,
  `first 10 restart offsets (s): [0.0, 120.0, 360.0, 840.0, 1800.0, 3600.0, 4080.0, 4560.0, 5460.0, 6420.0]`,
  `ceiling branch ever hit: False (MAX = 6 )`.
  `test_the_watchdog_stops_trying_after_the_hourly_ceiling` asserts
  `starts <= 6` over 3600 s, which the backoff alone satisfies (5 restarts);
  `test_the_ceiling_lifts_once_the_hour_has_passed` likewise only proves the
  backoff decayed. Neither would fail if the ceiling were deleted.
- Ledger: CR-233 (comp-app-7) does not fix comp-app-7's own stated scenario
- Suggested fix: count the ceiling over a window longer than the backoff can
  span (24 h, which is already what `_record` keeps), or cap the backoff below
  `3600 / MAX`. Then assert the ceiling by counting restarts over many hours,
  not one.

### comp-app-4 - the clock-skew tolerance comp-app-7 added is missing from the one place the fix says reads those events
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:1015` (`recent = [t for t in events if 0 <= now - t <= _WATCHDOG_HOUR_SECONDS]`), vs the fix at `app.py:1215-1220` (`_load_record`) and the constant `_WATCHDOG_CLOCK_SKEW_SECONDS` at `app.py:885`
- What: the fix widened `_load_record`'s filter to tolerate an event stamped in
  the future (`-3600 <= now - t`), with the comment "and the ceiling above
  reads these events". The ceiling and the backoff themselves still filter
  `0 <= now - t`, so a clock that steps BACKWARDS discards the whole in-memory
  ledger for the policy, exactly as `_load_record` used to on disk. The
  regression test only exercises `report()`/`_load_record`.
- Failure scenario: a sequencer is restarted; two minutes later NTP corrects the
  clock back by 10 minutes (an NTP step, a VM resume, a dual-boot RTC - the
  three cases the fix's own comment names). For those 10 minutes every stored
  event is "in the future", `recent` is empty, and the watchdog restarts the
  dead thread on every 60 s tick with no backoff and no ceiling.
- Evidence: same scratch script:
  `after one restart, held off: 'restarted 0s ago and the wait after 1 attempt(s) is 120s'`;
  after `now -= 600`: `after a 10-min backward clock step, held off: ''` and
  `restarts in the 10 min after the step: 3` (expected 0).
- Ledger: CR-233 (comp-app-7) does not fix comp-app-7's clock-skew half
- Suggested fix: use `-_WATCHDOG_CLOCK_SKEW_SECONDS <= now - t` in
  `_restart_held_off` too (and clamp `max(recent)` to `<= now` when computing
  `since`), and add a test that steps the clock back between two `check()`
  calls.

### comp-app-5 - the hold-off writes a WARNING every tick, so the per-tick spam comp-app-7 removed comes straight back in the same log
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:991-995`
- What: when a restart is held off, `check()` logs
  `log.warning("thread watchdog: NOT restarting the %s -- %s (%s)")` on every
  tick, i.e. once a minute for as long as the thread stays down. The JSON write
  per tick is genuinely gone; the log line per tick is not, it is only at a
  different level.
- Failure scenario: a dead sequencer for 24 h produces 1,350 WARNING lines plus
  97 ERROR lines, against 1,440 ERROR lines before the fix. The 5 MB rotating
  log still loses the day's other evidence.
- Evidence: `grep -c "NOT restarting"` over the 24 h simulation output -> 1350.
- Ledger: new (side effect of CR-233 / comp-app-7)
- Suggested fix: log the hold-off once per change of reason (or at DEBUG), and
  keep the WARNING for the transition into the ceiling.

### comp-app-6 - "Sync now" runs lane B on a machine where lane B is disabled by config, and names it in the toast
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:8567-8572` (`sync_now`'s unmanaged arm) and `app.py:8812` (`lanes` in the verdict), against `app.py:5936-5946` (`_start_lanes` skips `self._lane_b` when `not self._lane_b_enabled`)
- What: comp-app-1 unified the REFUSALS behind `_lanes_refusal()` but left the
  ACCEPTED path iterating `self.lanes` unfiltered. `_start_lanes` deliberately
  never starts lane B when `lane_b_enabled=false` (direct NAS access) and
  writes "disabled: direct NAS access" on its status line; `sync_now` then
  calls `self._lane_b.run_once()` anyway. `rclone_lane.run_once` has no
  `lane_b_enabled` guard - its early returns are root-missing, `_stop_event`
  (never set on a lane that was never started), the breaker and the disk floor
  - so a full `rclone sync` DOWN pass runs. The verdict's `lanes` list has the
  same fault and toasts `lane_b_proxy_down` at the editor.
- Failure scenario: an on-site machine configured `lane_b_enabled=false`. The
  editor clicks "Sync now" and the proxy tree is synced down from the NAS onto
  a machine whose whole configuration says it reads proxies off the share -
  and the status line it overwrites says lane B is disabled.
- Evidence: `sync/base.py:96` (`run_once` default), `sync/rclone_lane.py:3341-3412`
  (every early return read; none consults an app-level enable flag),
  `app.py:5936` (`if lane is self._lane_b and not self._lane_b_enabled: continue`
  exists only in `_start_lanes`). `grep -an lane_b_enabled KNOWN_BUGS.md` -> no hits.
- Ledger: new
- Suggested fix: filter `self.lanes` through the same predicate `_start_lanes`
  uses, in both the `lanes` list and the run loop - ideally a
  `self._runnable_lanes()` helper so the third caller cannot miss it either.

### comp-app-7 - the consolidate success toast still hides the copied count on the path where nothing was skipped
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:3740-3743`
- What: the line comp-resolve-2 edited is
  `f"Copy & upload finished ({copied} copied in{skipped_part})." if skipped else "Copy & upload finished."`.
  The conditional governs the WHOLE f-string, so the count is shown only when
  at least one file was skipped by the user - the common, everything-worked
  case says "Copy & upload finished." with no number. The fix corrected the
  arithmetic in an expression the editor usually never sees.
- Failure scenario: a clean 40 clip consolidate toasts "Copy & upload
  finished." The editor has no count to compare against the 40 they expected,
  which is the number the rehearsal and failure branches both do print.
- Evidence: read the expression; Python binds the conditional over the entire
  f-string (the `if skipped` is not inside the braces). The new test
  `test_a_real_consolidate_still_copies_uploads_and_says_so` only asserts the
  substring "Copy & upload finished", so it does not notice.
- Ledger: new (touched by CR-233's comp-resolve-2 hunk)
- Suggested fix: always include `({copied} copied in{skipped_part})`.

### comp-app-8 - a corrupt machine.json is now permanent, silent and unrepairable
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/machine.py:71-113`
- What: comp-app-5 correctly stopped re-minting over an unreadable file, but
  gave the condition no exit. `machine_id()` returns "" for ever, the only
  trace is one `log.warning` per process (reporter.py caches the empty answer
  for the process lifetime, by design), nothing writes a notice, nothing
  appears in the report, and no tray or dashboard affordance offers to re-mint
  after the admin has been told. The machine keeps its hostname key, so the
  loss is invisible until someone tries to rename it.
- Failure scenario: a power loss truncates `~/.ccsync/machine.json` to 0 bytes.
  From then on this computer has no id in every report, for ever, and nobody
  is ever told - including the admin who later finds the rename affordance
  missing on that one machine.
- Evidence: `machine.py:105-116` (the `not readable` early return, with no
  repair path anywhere in the module), `reporter.py:704-717` (the empty answer
  is cached), `grep -rn "machine_id(" src/ccsync_companion` -> only reporter.py
  and ytdl_executor.py, neither of which reports the failure.
- Ledger: new (incomplete half of CR-233 / comp-app-5)
- Suggested fix: surface it - a `machine_id_unreadable` flag on the report (or
  a config problem / tray line) plus a single deliberate "re-mint this
  computer's id" action, so the safe default is not also a dead end.

## Coverage note
Not covered: `site.py`, `identity.py`, `paths.py`, `canon.py`,
`secretfile.py`, `capabilities.py`, `ui_state.py`, `idle.py`,
`shutdown_guard.py` and `theme.py` beyond a skim - none of them changed since
40f931a, and the time box went to the diff and to the two wires it crosses.
About 60% of `app.py` (the popup/ingest/ytdl orchestration halves) was not
read line by line. The suite has no test at all for `sync_now`'s ACCEPTED
path against `lane_b_enabled=false` (comp-app-6), none for
`_restart_held_off` under a backward clock step (comp-app-4), and its two
ceiling tests cannot distinguish the ceiling from the backoff (comp-app-3).
The file-move wire was verified by reading both sides, not by running the
dashboard suite (another territory).

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/db.py:5480`: `expire_delivered_file_moves` ignores `state`, which is the dashboard half of comp-app-1 and comp-app-2 above.
- `dashboard/src/ccsync_dashboard/api.py:8994`: the file-move outcome log has no "unchanged since last report" suppression, which is what turns comp-app-2 into volume.
