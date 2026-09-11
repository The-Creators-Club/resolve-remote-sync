# comp-resolve - the companion's Resolve half: bridge, journal, fixer/consolidate, watcher, Timeline Cards role

Files read (with approximate coverage): `git diff 40f931a..HEAD` for the whole
territory in full (consolidate.py, fixer.py, resolve_bridge.py,
resolve_journal.py, timeline_cards_role.py, watcher.py - 308 changed lines,
every hunk); then `watcher.py` (100%), `script_server.py` (100%),
`timeline_cards_bridge.py` (100%), `resolve_bridge.py` connect/launch-window
and library/sweep entry points (~40%), `resolve_journal.py` write/sweep/
allow_automatic (~60%), `fixer.py` copy_with_progress + dry-run arm (~25%),
`consolidate.py` execution half (~40%), `timeline_cards_role.py` gate/start/
watchdog/report (~70%), plus the two sides I had to follow to judge the fixes:
`app.py` `_handle_non_canonical` / `_canon_relink_loop` / the consolidate
toast, `popup.py` `run_fix_all` + `summarize_fix_results`, and
`dashboard/src/ccsync_dashboard/cards_tunnel.py`'s `machine` handling.
Not read: proxy_gen/proxy_scan/proxy_relink/proxy_history, luts, bpg,
project_setup, library.py beyond `timeline_items`, resolve_undo/resolve_prefs
(none of them changed since 40f931a).

Tests run: `companion> .venv\Scripts\python.exe -m pytest
tests/test_bug_hunt_2026_09_11_comp_resolve.py tests/test_watcher.py
tests/test_consolidate.py tests/test_fixer.py tests/test_timeline_cards_role.py
tests/test_timeline_cards_role_health.py tests/test_resolve_journal.py
tests/test_resolve_bridge_launch_window.py tests/test_script_server.py -q`
-> 343 passed in 2.61s.

## Findings

### comp-resolve-b-1 - comp-resolve-2's fix landed in consolidate only: FIX ALL still counts a rehearsal as bytes copied
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/popup.py:648` and `popup.py:671-679`
  (second side: the fixed twin at
  `companion/src/ccsync_companion/consolidate.py:485` / `:516-527`)
- What: This afternoon's comp-resolve-2 fix taught three call sites that
  `fixer.fix_clip`'s rehearsal arm answers `{"ok": True, "dry_run": True}` and
  copied nothing - `consolidate.run_consolidation`, `consolidate.count_copied`
  and app.py's consolidate toast. `popup.run_fix_all`, the loop behind the FIX
  ALL button that every editor actually presses, was not touched: it still does
  `if outcome.get("ok"): batch_done += file_total` and
  `fixed = sum(1 for r in results if r.get("ok"))`. The FIX ALL progress window
  is driven off exactly those numbers.
- Failure scenario: an admin sets `fixer_dry_run = true` (the RES-15 rehearsal
  switch, whose entire purpose is a trustworthy screen), opens FIX ALL over 40
  clips and 800 GB. Each `fix_clip` returns instantly with ok/dry_run, so
  `batch_bytes_done` climbs to 800 GB in a second or two, the bar fills, and
  `RateEstimator`'s speed/ETA read off nonsense - the identical symptom the
  hunter described for the consolidate screen ("the bar filled at full speed,
  the ETA was nonsense"). The end-of-run summary is correct (popup.py:1385
  handles rehearsal), so the only thing that lies is the live screen.
- Evidence: read both loops side by side; `grep -n "dry_run" popup.py` shows
  the key is known to `summarize_fix_results` (:203, :249) and to the final
  dialog (:1385) but to nothing inside `run_fix_all` (:584-679).
  `consolidate.py:485` is the same line with `and not outcome.get("dry_run")`
  appended. The suite cannot catch it:
  `test_bug_hunt_2026_09_11_comp_resolve.py` exercises
  `run_consolidation` only.
- Ledger: CR-236 (comp-resolve-2) does not fix comp-resolve-2 on the FIX ALL
  path.
- Suggested fix: in `popup.run_fix_all` credit `batch_done` only when
  `not outcome.get("dry_run")` and count with `consolidate.count_copied` /
  `count_rehearsed` (they take a plain result list and are import-safe), adding
  a `rehearsal=` key to the final publish as consolidate now does.

### comp-resolve-b-2 - clips held by the auto-relink rate limiter can wait for the life of the process, because only a FAILED relink re-arms the watcher
- Severity: medium
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (frequency)
- Where: `companion/src/ccsync_companion/watcher.py:484-512`
  (`rearm_non_canonical`, comp-sync-13's new cooldown) and
  `companion/src/ccsync_companion/app.py:2959-2975` (the limiter arm of
  `_handle_non_canonical`)
- What: the watcher latches a NON_CANONICAL path in `_offered_non_canonical` at
  OFFER time, and the only thing that ever lifts the latch is
  `rearm_non_canonical`, which the app calls when a ReplaceClip has been
  ATTEMPTED and refused. When `resolve_journal.allow_automatic` refuses the
  burst, no clip is attempted, so nothing is re-armed, the clips sit in
  `_canon_relink_pending`, and `_handle_non_canonical` is never re-entered
  unless some other path is newly offered or the editor clicks SCAN WHOLE
  PROJECT. Nothing polls that queue. Before comp-sync-13 the re-offer window
  was the next 3 s poll for any re-armed path, which masked this; the 900 s
  cooldown makes the queue's only automatic drain even rarer.
- Failure scenario: a companion restarts (a self-upgrade, the 0.9.62
  supervisor's relaunch after a CR-93 abort) less than 15 minutes after an
  auto-relink pass - `allow_automatic`'s bars are persisted (RES-2), so the
  first burst of the new process is refused. Every non-canonical clip in the
  open project is now latched and queued; the log says "holding N clip(s)"
  once and nothing ever retries. The clips stay stored under the local
  spelling (the 2026-08-12 Energy Transition class) until the editor happens
  to open Tray > Settings > SCAN WHOLE PROJECT, which nothing tells them to
  do outside `companion.log`.
- Evidence: `grep -n "_canon_relink_pending" app.py` - the only writers are
  `_handle_non_canonical` and the drain loop; no timer, no report hook. The
  limiter arm at app.py:2966 returns with `_canon_relink_busy = False` and the
  pending list intact. `rearm_non_canonical` is called only from
  app.py:3091, inside the post-ReplaceClip failure branch.
- Ledger: related to CR-236/CR-245 (comp-sync-13, new); the stranding predates
  it, the 900 s cooldown widens it.
- Suggested fix: when the limiter refuses, schedule one retry at
  `AUTOMATIC_MIN_INTERVAL_SECONDS` (or have the watcher re-arm every latched
  path that is still on the pending queue), so the queue drains without the
  editor being told to click something in a log line they never read.

### comp-resolve-b-3 - `_elide` can return MORE characters than the cap it is given
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/timeline_cards_role.py:139-151`
- What: for `limit == 4`, `head = max(1, limit // 3) == 1` and the tail slice is
  `text[-(limit - head - 3):]` = `text[-0:]`, i.e. the WHOLE string. The helper
  whose contract is "cut this to `limit`" returns `text[:1] + "..." + text`.
- Failure scenario: not reachable today (the one caller's budget is
  `255 - 57 - 103 = 95`), but the budget is computed from two sentences in the
  same file: lengthen the head or the tail of the standalone-agent refusal past
  a budget of 4 and the refusal grows instead of shrinking, and the dashboard's
  `max_length=255` truncation the fix exists to pre-empt is back.
- Evidence: `.venv\Scripts\python.exe -c "from ccsync_companion import
  timeline_cards_role as r; print(len(r._elide('x'*400, 4)))"` -> `404`.
- Ledger: new (inside CR-236's comp-resolve-3 fix).
- Suggested fix: clamp the tail width, e.g.
  `tail = max(0, limit - head - 3)` and return `text[:head] + "..." + (text[-tail:] if tail else "")`.

### comp-resolve-b-4 - an UNKNOWN probe closes the launch window with the "Resolve registered" line
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/resolve_bridge.py:383`
- What: comp-resolve-6 split the close of the launch window into READY and
  ABSENT, but the fall-through at line 383 (`_note_starting(None)`) is taken for
  UNKNOWN too - the fail-open answer that means "the TCP table could not be read
  / the port is held by something that is not fuscript". That logs
  "script server has its host now - connecting", which is a positive claim the
  probe did not make, into the one line CR-68 diagnoses are read out of.
- Failure scenario: on a machine where `GetExtendedTcpTable` fails (a locked-down
  endpoint agent) or a non-Fusion service holds 1144, every launch window ends
  with "Resolve has registered" in the bundle, and the next reader concludes
  scripting was healthy while the probe was actually blind and the call went
  through unguarded.
- Evidence: `script_server.classify` returns UNKNOWN for "port held by X, not
  Fusion's script server" and `_probe_uncached` returns UNKNOWN on any
  exception; `connect()` treats everything that is not STARTING/ABSENT the same.
- Ledger: CR-236 (comp-resolve-6) does not cover the UNKNOWN arm.
- Suggested fix: pass the phase through, e.g.
  `_note_starting(None, ready=(phase == script_server.READY))`, and give UNKNOWN
  its own sentence ("the probe could not tell; connecting anyway").

### comp-resolve-b-5 - the res-companion-2 regression test passes on a half-reverted fix
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/tests/test_bug_hunt_2026_09_11_comp_resolve.py:265`
  (`test_a_start_that_fails_after_engine_start_stops_that_engine`)
- What: the assertion is
  `assert engine.stopped is True or engine.started is False`. The fix has two
  independent halves - reordering so the client is built before
  `engine.start()`, and `_release_engine` on the failure path - and the
  disjunction is satisfied by EITHER. Revert `_release_engine` alone (or any
  future change that starts the engine first again but keeps the release) and
  the test still passes, so it does not pin the property its own docstring
  claims ("stops that engine").
- Failure scenario: a later edit that moves `engine.start()` back above
  `make_tunnel_client` and drops the release leaves a Timeline Cards engine
  driving Resolve with nothing holding it - the two-clients-on-one-machine
  breach the module exists to prevent - with a green suite.
- Evidence: read the test against `timeline_cards_role._start` (:657-680); with
  the shipped order `engine.started` is False on the client-raises path, so the
  second disjunct alone carries it.
- Ledger: new (test quality, CR-236).
- Suggested fix: assert both properties separately, with a second case that
  makes `engine.start()` itself raise after a successful client build.

## Coverage note
Not reached: `proxy_gen.py` (2 403 lines, rule 2 / `.partial` handling),
`proxy_scan/relink/history`, `luts.py`, `bpg.py`, `project_setup.py`,
`resolve_undo.py`, `resolve_prefs.py`, and the bulk of `library.py` and
`resolve_bridge.py` (the media-pool write path, `replace_clip` /
`link_proxy_media`) - none of them changed in this diff, but they are the
largest unexamined surface in the territory. The suite does not cover
`popup.run_fix_all` in rehearsal mode at all (finding 1), nor any Timeline
Cards path against a real engine object from the other repo: every engine in
the tests is a `FakeEngine` whose `stop()` exists, which is precisely the
attribute `_release_engine` was written to tolerate being absent.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/popup.py`: finding 1 lives here (comp-ui's
  file) but is the missing half of this territory's own comp-resolve-2 fix.
- `companion/src/ccsync_companion/app.py:2959`: finding 2's other side (the
  limiter arm that leaves `_canon_relink_pending` with no automatic drain) is
  comp-app's file.
