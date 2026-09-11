# res-companion - what an editor's machine does when things go wrong, traced across files

Files read (with approximate coverage): `git diff 40f931a..HEAD -- companion/`
in full for `app.py`, `supervisor.py`, `crash_report.py`, `file_moves.py`,
`sync/lane_guard.py`, `sync/rclone_lane.py`, `sync/sequencer.py`,
`sync/repath.py`, `drive_reminder.py`, `upgrade.py`, `resolve_bridge.py`
(~100% of the diff hunks in those files); the surrounding source at every call
site I judged (`app._apply_file_moves` / `_queue_file_move_answer` /
`_relink_pending_moves` / `_lanes_refusal` / `_start_lanes`,
`FileMoveLedger` whole, `LaneBBreaker` whole, `RcloneLane.run_once`'s early
returns and `_account_pass`, `sequencer._run_project_turn`'s lane B join,
`RepathLedger`); the dashboard's other side of the file-move wire
(`api.py` FileMoveResultIn + ingest, `db.mark_file_move_applied`); the prior
hunt's own `docs/bug-hunt-2026-09-11/hunters/res-companion.md` for res-companion-1/4/5.

Tests run: `companion\.venv\Scripts\python.exe -c "<snippet>"` against
`file_moves.FileMoveLedger` (record_intent -> state/retry_due/recent_excludes)
-> printed `state applying ok False retry_due False`. No pytest file run (the
two relevant regression tests are quoted below and neither exercises the path).

## Findings

### res-companion-1 - the crash-resume for an interrupted file move is unreachable, and the crash now ends as a PERMANENT failed move instead of a retired one
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:7522-7523` (the ledger gate in
  `_apply_file_moves`) against
  `companion/src/ccsync_companion/file_moves.py:243-262` (`apply_move`'s new
  resume arm) and `file_moves.py:518-530` (`record_intent`); dashboard side
  `dashboard/src/ccsync_dashboard/db.py:5555-5572`
  (`mark_file_move_applied`: any non-`retrying` answer sets `applied_at`).
- What: this afternoon's fix writes an `applying` intent row before the first
  filesystem call and teaches `apply_move` to finish the job when a
  redelivered command finds `src` gone, `dest` present and OUR `applying` row.
  But `_apply_file_moves` never calls `apply_move` again for that move: it
  short-circuits on `done is not None and not self.file_moves.retry_due(done)`,
  and `retry_due()` is False for every state except `retryable`. `applying` is
  neither `retryable` nor `blocked`, so the redelivery takes the
  already-answered branch and replies `ok=False`, `detail="applying it on this
  machine"`, **`state=None`** - which on the dashboard means "an old companion
  answered, a failure is an answer": `applied_at` is stamped and the command is
  retired for ever. The resume arm is dead code in production.
- Failure scenario: the companion is killed (CR-93 abort, power cut, a
  `Stop-Process` during the proxy loop) between `src.replace(dest)` and
  `record()`. On the next start the redelivered `commands.file_moves` gets
  `ok=False` with a nonsense detail; the project page shows that machine as
  FAILED for ever; the ledger keeps an `applying` row whose `state` is in
  `recent_excludes`'s `unresolved` set, so that path is excluded from lane A
  *permanently* (proved: `excludes ['A001.mov']` with no window). The worse
  variant is a kill BEFORE the rename (intent written, file still at the old
  path): the move is then never applied on that machine at all, the dashboard
  is told it failed and stops asking, lane A is muzzled on the path for ever,
  and the editor's copy silently diverges from the server's with nothing on
  either side that can clear it.
  Secondary: the `applying` row carries `relink_pending=True`, so
  `_relink_pending_moves` (watcher thread) may queue a *contradicting*
  `ok=True` answer for the same id; whichever lands second wins locally, and
  the dashboard ignores the second one because `applied_at IS NULL` no longer
  holds.
- Evidence: snippet above (`state applying ok False retry_due False`,
  `excludes ['A001.mov']`). `file_moves.retry_due`:
  `if entry.get("state") != STATE_RETRYABLE: return False`. The two regression
  tests do not cover the path:
  `companion/tests/test_bug_hunt_2026_09_11_comp_sync.py:437` calls
  `file_moves.apply_move(...)` directly, bypassing `_apply_file_moves`'s gate,
  and `companion/tests/test_bug_hunt_2026_09_11_comp_app.py:752`
  monkeypatches `apply_move` away, asserting only that the ledger is passed.
- Ledger: new; "CR-248-era fix res-companion-1 does not fix res-companion-1"
  (the intent row lands, the resume never runs).
- Suggested fix: in `_apply_file_moves`, treat `STATE_APPLYING` like
  `retry_due` (fall through to `apply_move`), or make `retry_due()` return True
  for it; and until it resolves answer `state="retrying"` rather than a bare
  `ok=False`, so the dashboard does not retire the command. Add a test that
  drives `_apply_file_moves` twice across a simulated kill.

### res-companion-2 - the new "lane B abandoned" latch can be set on a thread that has just finished, and then nothing ever clears it: proxy download is dead until the tray restarts
- Severity: medium
- Confidence: CONFIRMED (a race; the window is small but is exactly the likely timing)
- Where: `companion/src/ccsync_companion/sync/sequencer.py:2082-2095` (the
  `thread.join(LANE_B_ABORT_JOIN_SECONDS)` / `if thread.is_alive():` /
  `self._lane_b_abandoned = subpath` sequence) against `sequencer.py:2028-2033`
  (`_b()`'s `finally: self._clear_lane_b_abandoned()`) and `sequencer.py:1998-2008`
  (the latch forces `run_b = False` on every later turn).
- What: comp-sync-7 added a latch that stops a new lane B thread being started
  while an abandoned one is still running, and documents that ONLY the
  abandoned thread's own `finally` may clear it. The set and the clear are not
  ordered: the rotation checks `thread.is_alive()`, then takes `self._lock` and
  sets the latch. If the lane B thread finishes in between - which is precisely
  what a thread that just missed a short join after its rclone child was killed
  is about to do - its `_clear_lane_b_abandoned()` runs against a latch that is
  still None, and the main thread then sets a latch nobody is left to clear.
  Because the latch also forces `run_b = False`, no further `_b()` ever runs,
  so no further `finally` ever clears it.
- Failure scenario: a wedged SMB mapping makes one lane B pass overrun the
  bounded join; `abort_run` kills the child; the thread exits ~50 ms after
  `LANE_B_ABORT_JOIN_SECONDS` expires. From then on every project turn logs
  "not starting lane B ... an earlier pass on X was abandoned and is still
  running" and the tray/grid detail says "stalled on X: waiting for an earlier
  pass to end" about a thread that ended hours ago. No proxies download; no
  breaker trips (this is not the breaker); the only cure is restarting the
  tray, and nothing tells the editor that.
- Evidence: read the whole `_run_project_turn` tail; the clear has exactly one
  call site, inside `_b`'s `finally`, and `run_b` is forced False while the
  latch is set, so the clear is unreachable once it is wrongly set. The
  regression test
  `companion/tests/test_bug_hunt_2026_09_11_comp_sync.py:248` assigns
  `seq._lane_b_abandoned` by hand and calls `_clear_lane_b_abandoned()`
  directly - it never exercises the set path or the ordering.
- Ledger: new (comp-sync-7, this afternoon).
- Suggested fix: set `_lane_b_abandoned = subpath` BEFORE the short
  `thread.join(LANE_B_ABORT_JOIN_SECONDS)` and let the thread's own `finally`
  clear it (the clear then always wins); or gate the set on the thread object
  (`if thread.is_alive(): latch = thread`) and have `_lane_b_turn` clear the
  latch when the recorded thread is no longer alive.

### res-companion-3 - an in-flight deletion credit that is never reconciled makes the NEXT lane B pass's deletions invisible to the breaker
- Severity: low
- Confidence: CONFIRMED (by reading; the trigger path is an exception, not the happy path)
- Where: `companion/src/ccsync_companion/sync/lane_guard.py:671-703`
  (`note_deletes_in_flight`, `_in_flight_credited`) and `lane_guard.py:727-733`
  (`note_pass`'s `max(0, deleted - credited)`), against
  `companion/src/ccsync_companion/sync/rclone_lane.py:3502-3546` (the two
  `except Exception as exc: ... return self.status()` arms that return BEFORE
  `_account_pass`).
- What: `_in_flight_credited` is reset only by `note_pass()` and `resume()`. A
  run that dies on an exception between the first `--stats` tick and
  `_account_pass` (a read error on the child's stdout, a MemoryError, anything
  `_run_popen` lets escape) leaves the counter set to that pass's total. The
  next pass's running total starts from zero, so `delta = total - credited` is
  negative and nothing is credited in flight, and its `note_pass` then computes
  `max(0, deleted - credited)` = 0 for real deletions.
- Failure scenario: pass 1 trashes 400 proxies, then `_run_popen` raises; pass
  2 trashes 400 more; the breaker's cumulative account grows by 0 for pass 2,
  so a flapping NAS can walk past the cumulative trigger the breaker exists
  for. The per-pass `--max-delete` cap keeps this bounded, which is why it is
  low - it is still the wrong direction for a safety device.
- Evidence: `_in_flight_credited` has exactly three writers (`__init__`,
  `resume`, `note_pass`) and no reset at the start of a run;
  `_credit_deletes_in_flight` is called from the stats parser, which runs
  before every early return listed above.
- Ledger: new (res-companion-5's fix, this afternoon).
- Suggested fix: reset `_in_flight_credited` when a run STARTS (a
  `note_pass_started(scope)` on the breaker, called from `run_once` next to
  `_set_periodic_scope`), or treat a smaller `deleted_so_far` than
  `_in_flight_credited` as a new run and re-baseline to 0 inside
  `note_deletes_in_flight`.

### res-companion-4 - "this machine cannot keep its crash-loop counter" is a log line and an accessor nobody calls
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/upgrade.py:196-216`
  (`_WRITE_FAILURES`, `write_failures()`), `upgrade.py:294-306`
  (`note_version_start`'s new WARNING).
- What: the supervisor half of res-companion-4 was properly closed (the
  `--prior` argv chain means the relaunch ceiling no longer depends on a
  writable state dir). The companion half was not: `write_failures()` has no
  caller anywhere in `companion/src` or `dashboard/src` - its only reference is
  the test that asserts the counter increments - and the failure is surfaced
  only as a WARNING in the log of a machine whose disk is full. Compare
  `lane_guard._PersistedLatch._persist_report()`, landed the same afternoon,
  which puts `persist_failed` on the report so the fleet grid can say it. So
  APP-5's crash-loop revert is still silently disabled on exactly the machine
  that needs it, and the admin is told nothing.
- Failure scenario: `C:` fills; `note_version_start` cannot write; every start
  looks like the first; the bad build is never reverted; the dashboard shows a
  machine reporting normally (or not at all) with no hint of why.
- Evidence: `grep -rn "write_failures" companion/src dashboard/src` -> only the
  definition and its own comment.
- Ledger: "the res-companion-4 fix closes the supervisor half only".
- Suggested fix: fold `upgrade.write_failures()` into the report's
  `sync_guard` block the way `persist_failed` is folded into the latch reports,
  and into `crash_report`'s startup warning line, so it reaches a human.

### res-companion-5 - `_file_move_answers` is rebuilt from two threads with no lock, so an answer can be lost or an already-sent one resurrected
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/app.py:7641` / `:7654`
  (`_queue_file_move_answer`) and `app.py:7658` (`_file_move_results`'s swap).
- What: `_queue_file_move_answer` does a read-filter-assign followed by an
  append, with no lock. It is called from the report-reply path
  (`_apply_file_moves`) and from the watcher thread
  (`_relink_pending_moves` / `_show_moved_clip_dialog`), while the reporter
  swaps the list out. A swap landing between the filter-assign and the append
  re-publishes answers that have already been sent, or drops the one being
  queued. comp-sync-20 made this hotter by queueing an answer on EVERY report
  while the drive is out.
- Failure scenario: duplicate `retrying` answers (harmless) or a lost `blocked`
  answer, which costs one report interval - small, but it is the same list the
  finding above turns into contradictory verdicts.
- Evidence: read all four call sites; no lock is taken anywhere around
  `_file_move_answers`.
- Ledger: new (pre-existing shape, widened this afternoon).
- Suggested fix: guard the three accesses with an existing lock (or a small
  dedicated one) and make the queue a dict keyed by move id.

## Coverage note
Traced end to end: kill-mid-file-move, kill-mid-lane-B-pass, drive pulled and
returning in a different state (comp-sync-8/9 - these read correct; the
`resume_remembered(state)` record delete is right), the supervisor relaunch
chain across an unwritable state dir (correct after the `--prior` fix), the
loopback rebind backoff (correct), the repath blocked/unblocked cycle
(correct), and the Resolve launch-window logging (correct). NOT covered for
want of time: `consolidate.py` / `fixer.py` under a mid-copy kill, the ytdl and
jobs executors' failure paths, `music_ingest`/`broll_ingest` staging under a
full disk, and `tray_native`'s registration-retry path (comp-ui-1 logs the
failure but I did not verify that any toast reaches the editor when the icon
never registers - worth a look by comp-ui). The companion suite still has no
test that kills a process between two writes; every crash-consistency property
above is asserted only by reading, which is how finding 1 got through.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/app.py:5620` (`_lanes_refusal`): its blanket
  `except Exception` returns None, i.e. "no gate in the way", so an exception
  while reading the halt or config gates now starts the lanes on a halted
  machine - the old code let it propagate out of `_start_lanes`.
- `companion/src/ccsync_companion/sync/sequencer.py:2011`: `_lane_b_subpath` is
  set to None whenever `run_b` is False, so comp-sync-7's
  `subpath_still_current` check answers "still current" for every queued pass
  while the rotation is idle or lane B is off - the abandoned latch is doing
  all the work.
- `companion/src/ccsync_companion/sync/repath.py:498-505`: the new 5 minute
  `RELINK_RETRY_MIN_SECONDS` throttle is monotonic and per-process, so a
  machine that restarts often retries on every start; harmless, noted only
  because the pairing test is `force=True`.
