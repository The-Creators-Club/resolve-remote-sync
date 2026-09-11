# res-companion - cross-cutting resilience lens: what an editor's machine does when things go wrong

Files read (with approximate coverage): traced whole paths rather than whole
files. `companion/src/ccsync_companion/supervisor.py` (100%),
`crash_report.py` (marker/clean-exit half), `upgrade.py` (`_apply_inner`,
`_rollback`, `_write_json`, `note_version_start`, `read/write_version_state`),
`file_moves.py` (100%), `app.py` (`_on_report_response`, `_apply_file_moves`,
`_apply_fleet_halt`, `shutdown`, `run` startup block, `LaneWatchdog` /
`_SupervisedThread`, the stale-tmp/partial sweeps, the P: grade-swap
accessors), `reporter.py` (`_report_loop`, `_run_cycle`, `post_once`,
`_note_failure`/`_note_success`, state persistence), `root_guard.py`
(`_loop`, `probe_once`, `_sample`, `_filesystem_answers`, `_fire`, `probe_root`),
`manifest.py` (`refresh_once`/`_loop`), `drive_reminder.py` (`_loop`, record),
`proxy_gen.py` (`_loop`, notify state, `sweep_stale_partials`, `_publish`),
`jobs_runner.py` (`_loop`, `note_report_reply`, `wait_seconds`),
`timeline_cards_role.py` (start/supervise/health/report_block),
`selection.py` (cache write + `load_cached`), `sync/lane_guard.py`
(`LaneBBreaker`), `sync/rclone_lane.py` (the pass result chain,
`_account_pass`, `check_remote_root`), `sync/syncthing_supervisor.py`
(state), `resolve_bridge.replace_clip`, `config.py` (`set_key` + backup),
`drive_swap.py` (header + classification), `tray.py` (`credential_rejected`,
`_reporter_line`, `p_mode`), plus `git diff --stat 097f5a3..HEAD` over the
package.

Tests run: none (read-only trace; no scenario needed a runtime repro that a
test could produce without a real Resolve/NAS).

## Findings

### res-companion-1 - a companion killed mid file-move applies the move and then never relinks Resolve, and reports it as fully applied
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/file_moves.py:193` (`apply_move`, the
  `if not src.exists(): return True, "nothing at the old path on this
  machine", None` arm) -> `file_moves.py:172` (`move_proxy_siblings`, the wide
  part of the window) -> `companion/src/ccsync_companion/app.py:7289-7311`
  (`_apply_file_moves`: `apply_move` -> `_relink_moved_result` ->
  `self.file_moves.record(...)`) -> `file_moves.py:319` (`record`, which only
  stores `old_local`/`new_local` when `paths` is truthy) ->
  `file_moves.py:397` (`moved_to`, which skips every entry without both).
- What: the on-disk ledger entry is written only AFTER the filesystem move and
  the relink. The move itself (`src.replace(dest)` plus a proxy-sibling loop
  that can touch many files) is therefore not crash-atomic with the record of
  it. If the process dies in that window the file has moved, nothing recorded
  it, and the redelivered command takes the "nothing at the old path" arm,
  which returns `paths=None` - so `_relink_moved_result` is never called, the
  entry is recorded with no `old_local`, and `relink_pending` is False.
- Failure scenario: admin moves `Projects/FF5/A/A001.braw` on the NAS; the
  companion moves the local copy and is killed (power loss, `Stop-Process`,
  or the self-upgrade's own teardown landing on it) before `record()`. Next
  report: the companion answers `ok: true, relink_pending: false`, the
  dashboard marks the move applied on this machine, and the editor's Resolve
  project still points at the old path. Both recovery routes are closed by the
  same missing field: `pending_relinks()` requires `relink_pending` and
  `old_local`, and the watcher's "this clip was moved, one click to relink"
  offer (`app.py:1926` `moved_lookup=self.file_moves.moved_to`) requires
  `old_local`/`new_local`. The clip is a plain MISSING clip; the fixer's
  answer to a missing in-tree clip is to copy the file back to the OLD path
  (memory note "FIX ALL is copy-only"), which re-creates exactly the path the
  admin cleared, and the 24 h lane A exclusion expires a day later - so the
  file can re-upload itself to the old server path, which is the class of
  failure `docs/FILE_MOVES.md` exists to prevent (that last hop is PLAUSIBLE,
  not confirmed).
- Evidence: `apply_move` returns `(True, "nothing at the old path on this
  machine", None)` when `src` is gone; `app.py:7303` gates the relink on
  `if ok and paths is not None`; `record` at `file_moves.py:334` writes
  `old_local` only `if paths:` (the `elif previous.get("old_local")` arm needs
  a previous entry, which is exactly what the crash prevented).
- Ledger: new (related to RES-1 / RES-10 / SYNC-108, all FIXED, none of which
  covers the no-entry crash window).
- Suggested fix: write an "intent" ledger entry (state `applying`, with
  `old_local`/`new_local` precomputed) BEFORE the first filesystem call, and
  have the redelivery path resume from it - if an `applying` entry exists and
  `src` is gone but `dest` exists, finish the proxy siblings and run the
  relink instead of answering "nothing at the old path".

### res-companion-2 - a Timeline Cards role that fails AFTER `engine.start()` leaks a live engine, and the RES-7 watchdog starts a fresh one every 60 s
- Severity: medium
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (trigger frequency)
- Where: `companion/src/ccsync_companion/timeline_cards_role.py:597-612`
  (`_start`: `engine = engine_cls(...)`, `engine.start()`, then
  `client = make_tunnel_client(...)`, and only then the `with self._lock`
  that stores `_engine`/`_client`/`_threads`) -> `:549` (`_start_guarded`,
  which swallows the exception and sets STATE_NO_ENGINE) -> `:659`
  (`_supervise`, re-asking every `PROBE_CACHE_SECONDS` = 60 s) -> `:676`
  (`supervise_now`, whose only "already up" test is `if self._threads`, still
  empty after a failed start) -> `:335` (`make_tunnel_client`, which calls
  another repo's `AgentClient(url, "", engine, machine)` positionally).
- What: the engine is constructed and STARTED before anything that can fail is
  done, but it is only recorded in `self._engine` at the end. Any exception
  between `engine.start()` and the lock leaves a running engine that this
  object no longer has a reference to - nothing can stop it - and the RES-7
  watchdog, seeing `_threads` empty, calls `_start()` again a minute later and
  starts another one. Nothing bounds the retries.
- Failure scenario: the Timeline Cards checkout at `DASH_CARDS_SRC` is updated
  and its `AgentClient.__init__` signature changes (the mount is deliberately
  "another repo's checkout", and `check_contract`/`engine_class` validate the
  ENGINE, not `AgentClient`). `make_tunnel_client` raises TypeError after
  `engine.start()` has already taken Resolve. One hour later the process holds
  60 started engines, each with the other repo's background threads sweeping
  the media pool through `CardsBridge`, which is a direct breach of the
  "one machine, one Resolve client" invariant this module's own docstring
  states - and `report_block()` renders `refused`, so the fleet grid shows a
  machine that is doing nothing while it hammers Resolve.
- Evidence: read `_start` in full; `self._engine = engine` is inside the
  `with self._lock:` block that follows `make_tunnel_client`, and `stop()`
  (`:685`) only clears the reference, it never calls `engine.stop()`. The
  "a role whose loops have died is never restarted" decision in KNOWN_BUGS
  CR-170's RES-7 notes covers a role that STARTED; it does not cover a start
  that half-succeeded.
- Ledger: new (adjacent to RES-7, whose watchdog is the retry driver here).
- Suggested fix: build the client BEFORE `engine.start()`, or wrap the tail of
  `_start` in a try/except that calls `engine.stop()` (best effort) and
  re-raises; and give `_start_guarded` a consecutive-failure ceiling so the
  watchdog stops re-entering a start that has failed the same way N times.

### res-companion-3 - a kill in the upgrade's rename window leaves no companion exe at all, and the supervisor deliberately stands down
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/upgrade.py:1753-1768` (`_apply_inner`:
  `self._replace(exe, old)` then `self._replace(new, exe)`) ->
  `companion/src/ccsync_companion/supervisor.py:136-137` (`decide`:
  `if not exe_exists: return Decision(False, "the companion exe is no longer
  on disk: nothing to relaunch")`) -> `supervisor.py:399` (the only caller,
  passing `exe_exists=exe.is_file()`) -> `app.py:10229-10238` (the next start
  is the only thing that would run `cleanup_old_exe`, and it cannot run).
- What: between the two renames the install has `ccsync-companion.exe.old` and
  `ccsync-companion.exe.new` (or `.new` already consumed) and NO
  `ccsync-companion.exe`. Every recovery this system has - `cleanup_old_exe`,
  `revert_to_previous_build`, `note_version_start`'s crash-loop revert - runs
  INSIDE a companion that has started, and the logon Run key points at the
  missing name. The one process that is outside and awake, the supervisor, is
  explicitly coded to give up in exactly this state, and it says so only in
  `supervisor.log` beside the crash reports.
- Failure scenario: power loss (or an AV product killing the process mid-swap;
  `_rollback` exists precisely because that rename pair is known to fail) at
  an editor's machine during a one-click update. The machine never runs a
  companion again: no tray, no lanes, no reports. The editor sees nothing at
  all, and the admin sees only a machine that has gone quiet on the fleet grid
  - the same symptom as a switched-off PC.
- Evidence: read both hops; `decide()` has no branch that restores `.old`, and
  nothing outside a running companion references `_OLD_SUFFIX`
  (`grep -rn "cleanup_old_exe\|revert_to_previous_build"` -> app startup only).
- Ledger: new.
- Suggested fix: in `supervisor.main`, when the marker names our pid and `exe`
  is missing but `<exe>.old` (or `.new`) exists, `os.replace` it back into
  place and relaunch - it is the one recovery only an outside process can
  perform, and it is strictly safer than leaving the install with no binary.

### res-companion-4 - both crash-loop ceilings are silently disabled by a full or unwritable `~/.ccsync`, turning a crash into an unbounded relaunch loop
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/supervisor.py:167-181`
  (`read_history` returns `[]` on ANY exception, `write_history` swallows ANY
  exception) -> `supervisor.py:138-142` (`decide`'s
  `len(recent) >= MAX_RELAUNCHES` ceiling, whose only input is that history)
  -> `companion/src/ccsync_companion/upgrade.py:181-194` (`_write_json`
  returns False and logs at DEBUG) -> `upgrade.py:219` (`note_version_start`,
  whose `starts`/`crash_loop` counter is the OTHER half of the ceiling, per
  its own docstring and APP-5) -> `app.py:9888-9897` (the crash-loop revert
  that never fires).
- What: the relaunch ceiling ("three relaunches in an hour and the supervisor
  stands down") is evidence-based, and its evidence file is in the same state
  directory that a disk-full condition makes unwritable. Both the supervisor's
  history and the companion's own start counter degrade to "we know nothing",
  and for `decide()` "we know nothing" means relaunch. This is the
  in-memory-safety-latch failure mode one level out: the latch is on disk, but
  a failed write is indistinguishable from a fresh machine.
- Failure scenario: `C:` fills (the companion's own log rotates at 5 MB, ytdl
  and proxy work stage into the profile). A build that then aborts - CR-93's
  shape, or simply out-of-disk during startup - is relaunched every
  ~10 s + startup time, for ever: each relaunched companion spawns a fresh
  supervisor, the history write fails again, and the crash-loop revert that
  would have restored the previous build never counts to three either.
  Nothing reaches the tray (there is none) or the dashboard (no reports).
- Evidence: `read_history` -> `except Exception: return []`;
  `write_history` -> `except Exception: pass`; `decide` computes `recent`
  purely from that list. `note_version_start` calls `_write_json`, which
  returns False on ENOSPC and is not checked by its caller.
- Ledger: new (the supervisor is CR-93's safety net; this is its own latch).
- Suggested fix: when `write_history` fails, fall back to a conservative
  in-process count (the supervisor lives for exactly one companion, so pass
  the previous attempt count on the child's command line) - and refuse to
  relaunch when the state directory cannot be written at all, which is itself
  a machine that needs a human.

### res-companion-5 - a hard kill mid lane-B pass erases that pass's deletions from the breaker's cumulative account
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/rclone_lane.py:3533`
  (`tripped = self._account_pass(result, subpath, local_proxies)`, reached only
  after the rclone child has exited and its output has been parsed) ->
  `rclone_lane.py:3983` (`_account_pass`) ->
  `companion/src/ccsync_companion/sync/lane_guard.py:572` (`note_pass`, which
  is the only writer of `_deletes`/`_bytes` and the only caller of
  `_persist_locked` for them).
- What: lane B's cumulative deletion account is credited once per pass, from
  the parsed result, after the process has finished. A SIGKILL or power loss
  mid-pass loses every deletion that pass had already made - the files are in
  `.ccsync-trash` on disk, but the counter that would have tripped the breaker
  on the next pass never saw them. (The deliberate stop path is covered:
  `_account_pass` is explicitly ahead of the stop-mid-transfer return, per the
  comment at `:3529`.)
- Failure scenario: a NAS reorganisation empties a scope; lane B starts
  trashing local proxies; the editor's laptop loses power halfway. On the next
  start the breaker's cumulative counter is back at its last persisted value
  and the second pass gets a full fresh budget before it can trip. The per-pass
  `--max-delete` cap is what actually bounds the damage, which is why this is
  low and not medium.
- Evidence: read the call site and `note_pass`; `_persist_locked` for
  `_deletes` is reached only from inside `note_pass`.
- Ledger: new (related to item 9 / CR-44 / CR-45, all FIXED).
- Suggested fix: credit deletions incrementally from the `--stats` parse the
  lane already consumes during the run, rather than only from the final
  result.

## Coverage note
Traced but found already defended (worth recording so the next hunt does not
re-walk them): the run-marker / supervisor decision chain against Quit,
`Stop-Process`, self-upgrade hand-off and the crash-loop revert
(`mark_clean_exit` is pid-checked, the single-instance mutex closes the
marker race); every JSON state reader in the package (`grep` of all
`json.loads`/`json.load` sites: every one catches ValueError/Exception, so
scenario 5's "truncated JSON crashes the next boot" does not exist here, and
`selection.py`'s cache is explicitly tmp+replace with a comment naming the
zero-byte incident); `root_guard.probe_once` (`probe_root` never raises,
`_fire` is guarded, the out-of-process probe fails open); `manifest.refresh_once`
(never raises, and skips rather than reporting an empty tree when the root is
gone); `LaneBBreaker.check_remote` (a FAILED listing is deliberately not a
trip, so a 10-minute NAS outage does not latch); the lane result chain (a
failed pass is STATE_ERROR and does NOT stamp `last_sync`; a stopped pass
stands down instead of going red); the reporter (401/403 is a per-process
toast plus an hourly WARNING, and `tray.credential_rejected` /
`_reporter_line` stop the tray claiming "signed in" on a revoked token);
`jobs_runner.note_report_reply` and `wait_seconds` (an absent `commands.jobs`
block from a 0.7.34 dashboard reads as "no offers" and as the BASE cadence,
not as a two-minute backoff); `config.set_key` (tmp + harden + replace, with a
`.backup` fallback); the P: grade-swap state, which is derived from the live
mapping rather than remembered, so a crash in grade mode is self-describing.

NOT covered: I did not trace the 8899 loopback server, b-roll/music ingest or
the ytdl executor's own crash/resume paths in any depth (large, and each has
an owning hunter); I did not exercise anything at runtime; scenario 7
(sleep / clock jump) was only spot-checked - `supervisor.decide` uses
wall-clock timestamps, so a backwards NTP correction makes `now - t` negative
and quietly forgives recent relaunches, which I judged too small to file
separately but is the same family as res-companion-4. The companion suite has
no test that kills a process between two writes; every crash-consistency
property above is asserted only by reading.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/app.py:9501-9509`: the `except` arm of the
  stale `.partial` sweep does `return`, so a failure there also skips
  `self._recheck_orphan_reservations(local_root, tmp_files)` on the line below
  - the second look at 0-byte reservations is lost for that start.
- `companion/src/ccsync_companion/reporter.py:1338`: the report loop has no
  failure backoff at all - a dashboard that has been down for a day is still
  polled every `dashboard_report_interval`. Harmless today (60 s, one small
  POST), noted only because "retry with no backoff" is on the brief's list.
