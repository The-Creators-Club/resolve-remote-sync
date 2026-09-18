# comp-ui - the companion's tray, popup, settings window, dispatcher, crash report and stills

Files read (with approximate coverage):
- `companion/src/ccsync_companion/tray_native.py` - the whole Windows `_WindowsIcon`
  half (100% of the diff; `run`, `_add_icon`, `_flush_pending_toasts`, `_modify`,
  `_on_message`, the three re-add-timer helpers, `_create_window`, `_teardown`),
  the macOS half skimmed.
- `companion/src/ccsync_companion/tray.py` - 100% of the diff; plus
  `compute_overall_color`, `_blocked_line`, `_sync_line`, `_tooltip`,
  `resolve_count_phrases`, `resolve_bridge_line`, `_menu_fingerprint`,
  `_guard_fingerprint`, `_report_windows_icon_failure`, `start_tray`'s hook.
- `companion/src/ccsync_companion/popup.py` - 100% of the diff; `perform_fix_all`,
  `format_file_progress`, `format_batch_progress`, `PopupDialog._render_progress`,
  `ProgressWindow` end to end.
- `companion/src/ccsync_companion/settings_window.py` - `_resolve_section` (the
  whole diff) and its neighbours.
- `companion/src/ccsync_companion/stills.py` - all of it.
- `companion/src/ccsync_companion/ui_dispatch.py`, `crash_report.py` - unchanged
  today, skimmed only (see coverage note).
- Cross-read for the wires: `app.py` (`_BLOCKED_ORDER`, `blocked_candidate`,
  `standins_owed`, `_note_stills`), `consolidate.run_consolidation`,
  `broll_server.run_proxy_upgrade`, `broll_standins.set_upgrade`, `ui_copy.count`.
- Tests: `companion/tests/test_bug_hunt_2026_09_18_companion_core.py` (the
  comp-ui-1..5 and live-5 blocks), `test_settings_window.py`, `test_stills.py`,
  `test_bug_hunt_2026_09_11_comp_ui.py`, `test_bug_hunt_2026_09_11b_comp_ui.py`.
- Ledger: `docs/bug-hunt-2026-09-18/ledger/companion-core.md` CR-283B/M/N/O/P/Q,
  `companion-media.md`'s OWED line for comp-broll-tiers-5.

Tests run:
`companion\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_18_companion_core.py tests/test_settings_window.py tests/test_stills.py -q` -> 142 passed.
Plus one ad-hoc script in the scratchpad driving `popup.perform_fix_all` under a
dry-run `fix_clip_fn` (output quoted in comp-ui-1).

## Findings

### comp-ui-1 - a rehearsal still says `Copying "...": 0 B of 12.7 GB` for its FIRST clip, and for the whole run when there is one clip
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/popup.py:643-661` (the publish precedes
  the answer that sets `rehearsing`), test at
  `companion/tests/test_bug_hunt_2026_09_18_companion_core.py:709-745`
- What: `rehearsing` is learned from the first `outcome.get("dry_run")`, but the
  progress keys for a file are published BEFORE `call_fix_clip` runs. So file 1
  of every rehearsal is published with `rehearsing` false and the real
  `file_bytes_total`/`batch_bytes_total`, which is exactly the screen CR-283P
  says it replaced: the word "Copying", a byte total that will never be reached,
  and a batch bar drawn off bytes rather than clips.
- Failure scenario: `fixer_dry_run` on, editor presses FIX ALL on one dead link
  (the common single-clip case). The dialog reads
  `Copying "A001_C012.braw": 0 B of 12.7 GB` with both bars at 0 for the whole
  run, then closes. RES-15's "a screen an admin can trust" is unchanged for that
  run. With N clips it is wrong for the first file only.
- Evidence: scratchpad script, companion venv, two dry-run rows:
  ```
  a.braw rehearsing= False file_total= 1024 batch_total= 2048
     label: Copying "a.braw": 0 B of 1.0 KB
  b.braw rehearsing= True file_total= 0 batch_total= 0
     label: Checking "b.braw"
  ```
  The regression test cannot see it: it asserts on `mid[-1]`, the LAST per-file
  publish, never `mid[0]`, and its `rows` list has two entries so the first is
  discarded.
- Ledger: CR-283P does not fix comp-ui-5 for the first file (partial fix of a
  ledgered item).
- Suggested fix: decide `rehearsing` before the loop from the same config
  `fixer.fix_clip` reads (`fixer_dry_run`), keeping the first-answer latch as
  the fallback; and change the test to assert on `mid[0]` with a single-row batch.

### comp-ui-2 - the toast queue covers the startup window but NOT the Explorer restart, which is the window the safety latches actually fall into
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray_native.py:1000-1020` (`notify`
  queues only when `_added` is false) and `:1191-1194` (`_modify` swallows a
  failed `NIM_MODIFY` at DEBUG)
- What: `_added` is set false only inside the `TaskbarCreated` handler. Between
  Explorer dying and that broadcast arriving, `_added` is still true, so
  `notify()` takes the normal path into `_modify`, `Shell_NotifyIcon(NIM_MODIFY)`
  fails against a notification area that no longer exists, and the sentence is
  dropped with a `log.debug` and no queue entry. CR-283M's deque only ever sees
  the pre-first-registration window.
- Failure scenario: Explorer crashes; two seconds later the lane B breaker trips
  (or a fleet halt arrives, or the drive is pulled). The toast is lost at DEBUG.
  A second later `TaskbarCreated` arrives, the icon comes back, the deque is
  empty and nothing ever tells the editor sync stopped itself - the precise
  failure CR-283M's own rationale describes ("four of the things that arrive here
  are SAFETY LATCHES").
- Evidence: read both call sites; `_modify` ignores its return value beyond a
  `log.debug`, and no code path clears `_added` except `_remove_icon` and the
  broadcast handler.
- Ledger: CR-283M does not fix comp-ui-1 for the Explorer-restart window.
- Suggested fix: in `_modify`, when the call carries `NIF_INFO` and
  `Shell_NotifyIconW` returns 0, append `(message, title)` to `_pending_toasts`
  (and consider setting `_added = False`, which is what the failure means); the
  existing flush on the next successful `_add_icon` then delivers it.

### comp-ui-3 - CR-283O frees neither the window nor the window class it says it frees; the test asserts an attribute, not a handle
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray_native.py:911-921` (the new
  `_teardown()` call) and `:1473-1490` (`_teardown` itself); test at
  `companion/tests/test_bug_hunt_2026_09_18_companion_core.py:317-346`
- What: `_teardown()` removes the icon, destroys the cached HICONs and assigns
  `self._hwnd = None`. It never calls `DestroyWindow`, and `UnregisterClassW`
  appears NOWHERE in the file (`grep -n "UnregisterClass\|DestroyWindow"` gives
  only the two `DestroyWindow` calls inside `_on_message`, i.e. the pump path).
  So in the arm CR-283O added, the HWND created by `_create_window` stays alive
  for the life of the process with `self._hwnd` nulled, meaning nothing can ever
  destroy it; and the per-instance class `CCSyncTray_<id(self):x}` is leaked in
  EVERY path, happy one included, contrary to the ledger entry and the comment.
- Failure scenario: first registration fails (the 105 s backoff exhausted on a
  slow login). `run()` announces, tears down, returns. The window remains
  registered with USER32 and its `WNDPROC` is `self._wndproc_ref`. If that
  `_WindowsIcon` is ever dropped and collected (tray restarted in-process, or a
  fallback backend selected), the ctypes callback is freed while USER32 still
  holds the pointer - the crash-inside-USER32-with-no-traceback that the comment
  at `_create_window` warns about. A second Icon that lands on a recycled `id()`
  gets `ERROR_CLASS_ALREADY_EXISTS`, which the code tolerates, and then creates a
  window on the STALE class, i.e. the dead callback.
- Evidence: `grep -n "UnregisterClass\|DestroyWindow" tray_native.py` ->
  `656`, `657` (the argtypes) and `1256`, `1262` (both inside `_on_message`).
  The regression test's `_User32` double defines no `DestroyWindow` and no
  `UnregisterClassW` at all, and asserts `icon._hwnd is None` - which the plain
  assignment satisfies. It would pass just as well if `_teardown` were a no-op
  plus `self._hwnd = None`.
- Ledger: CR-283O does not fix comp-ui-4 as described (leak persists; the class
  half is untouched everywhere).
- Suggested fix: have `_teardown` call `DestroyWindow(self._hwnd)` when the
  handle is live and the pump is not running, then `UnregisterClassW(class_name,
  hinstance)`; keep the class name on `self` so teardown can name it. Add
  `DestroyWindow`/`UnregisterClassW` to the test double and assert they were
  called with `4242` / the class name.

### comp-ui-4 - CR-283P's twin: the CONSOLIDATE progress window still draws "Copying ... 0 B of 800 GB" for a whole rehearsal
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/popup.py:1858-1868`
  (`ProgressWindow._tick` calls `format_file_progress` with no `rehearsal`
  argument and draws its batch bar off bytes) with the publisher at
  `companion/src/ccsync_companion/consolidate.py:443-485`
- What: comp-ui-5 was fixed in `PopupDialog._render_progress` only.
  `consolidate.run_consolidation` has the identical shape - it stopped crediting
  bytes for a `dry_run` outcome (comp-resolve-2, 2026-09-11) and still publishes
  the real `file_bytes_total`/`batch_bytes_total` and no `rehearsing` key - and
  its renderer is `ProgressWindow`, in popup.py, which was not touched. The
  ledger entry names popup.py as the fix site, so this reads as covered and is
  not.
- Failure scenario: `fixer_dry_run` on, editor uses COPY THIS PROJECT'S MEDIA IN
  over an 800 GB project. The window sits at `File 7 of 412: 0 B of 800 GB done`
  with both bars at zero and the word "Copying" beside each clip name, for the
  whole rehearsal - the exact screen CR-283P calls untrustworthy.
- Evidence: read both; `run_consolidation`'s per-file publish (popup.py's twin)
  has no `rehearsing` key and `ProgressWindow._tick` has no `rehearsal=`
  argument. `grep -n "rehearsing" consolidate.py` -> no matches.
- Ledger: CR-283P fixes one of the two surfaces it shares a bug with (related to
  comp-resolve-2, closed 2026-09-11).
- Suggested fix: apply the comp-ui-5 pattern to `run_consolidation` (latch on the
  first `dry_run`, zero the byte totals, publish `rehearsing`) and give
  `ProgressWindow._tick` the same two lines `PopupDialog._render_progress` got.

### comp-ui-5 - after CR-283N a tray icon that never comes back has no surface at all outside the local log
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray.py:1040-1046` (the new non-fatal
  early return) with `tray_native.py:1454-1472` (`_retry_readd` logs at
  DEBUG/INFO and deliberately never announces)
- What: CR-283N is right that an Explorer crash-loop must not write one crash
  report per broadcast. But the crash report was the ONLY channel that left the
  machine: it rides `sync_guard.crashes` and `build_diagnostics` to the
  dashboard. The non-fatal path now writes one `log.warning` per broadcast and
  nothing else, and the once-a-minute retry (CR-283B) logs at DEBUG when it
  fails. `_WindowsIcon.registered`, added by comp-ui-1 on 2026-09-11 precisely so
  callers could ask, has NO reader in the repo
  (`grep -rn "\.registered\b" companion/src` -> nothing).
- Failure scenario: a machine where `NIM_ADD` fails for a durable reason (a
  policy-locked notification area, a wedged shell). Every minute the retry fails
  silently. The editor has no icon, no menu, no Settings, no Quit and every toast
  held in a five-deep deque that never drains, while the dashboard shows the
  machine perfectly healthy and no notice, alert or crash count ever fires. Rule
  5's "a failure logged but never surfaced to the person who must act".
- Evidence: read the three functions and grepped for every reader of
  `registered` / `_register_error`; the only consumer of `_register_error` is the
  DROPPED-toast log line in `notify`.
- Ledger: CR-283N does not fix comp-ui-3 without opening its neighbour (new).
- Suggested fix: write ONE `TrayIconUnavailable` crash report per process for a
  non-fatal failure that the retry has not cleared after, say, five ticks (a
  latch on `self`), so the condition still reaches `sync_guard.crashes` exactly
  once; or give `registered` a reader in the report so the dashboard can say it.

### comp-ui-6 - live-5 makes `no_selection` hide the RED reasons that sit below it in the one-reason report
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray.py:163-170` and `:239-243`, against
  `companion/src/ccsync_companion/app.py:7271-7282` (`_BLOCKED_ORDER`)
- What: `blocked_report` returns exactly ONE reason, the first match in
  `_BLOCKED_ORDER`. `no_selection` sits at position 12, ahead of
  `project_dir_moved`, `folders_unfiltered`, `lane_stalled`, `syncthing_down` and
  `transport_offline` - and `lane_stalled` and `syncthing_down` are both in
  `_BLOCKED_RED_REASONS`. The live-5 fix skips the colour branch on the REASON
  rather than asking whether a worse one is also true, so those five can no
  longer colour the icon on a machine with nothing ticked.
- Failure scenario: an editor machine with an empty plan whose Syncthing engine
  has died. Before today the tray was red; now it is green, and the only trace is
  the plain `Sync: No projects are ticked for this computer` line. The moment the
  admin ticks a project for that machine it will not sync, and the tray said
  everything was fine right up to the tick.
- Evidence: read both lists; `_BLOCKED_RED_REASONS` at tray.py:159 contains
  `lane_stalled` and `syncthing_down`, both ordered after `no_selection`.
  `test_a_real_blockage_is_still_amber_and_still_warns` uses `transport_offline`
  with no `no_selection` present, so it cannot see the masking.
- Ledger: new (live-5 is an owner decision, so this is the neighbour it opened,
  not a re-report of the decision).
- Suggested fix: keep the informational exemption but let the reporter carry the
  runner-up: either have `blocked_report` skip `WHY_INFORMATIONAL` reasons when a
  non-informational candidate also matched, or have the tray re-ask for the next
  reason when the first is informational.

### comp-ui-7 - the held toasts are flushed back to back, so Explorer shows at most the last one
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/tray_native.py:1153-1171`
- What: `_flush_pending_toasts` loops `_modify(info=...)` with no gap. A
  notification area shows one balloon per icon at a time, and an `NIM_MODIFY`
  carrying `NIF_INFO` while a balloon of that icon is up replaces it rather than
  queuing behind it. Up to five sentences are handed over in a few microseconds.
- Failure scenario: an editor logs in, the icon registers at t+90 s, five held
  sentences (post-upgrade, crash-loop rollback, breaker tripped, halt, disk
  floor) flush and the editor sees one balloon - most likely the last, which is
  not the most important.
- Evidence: read the flush; no delay, no re-arm, no per-toast scheduling. Not
  verified against a live shell, hence PLAUSIBLE.
- Ledger: related to CR-283M (new).
- Suggested fix: drain one per `SetTimer` tick (the re-add timer machinery from
  CR-283B already exists), or collapse the held sentences into a single balloon.

### comp-ui-8 - the Settings line renders an internal upgrade note, which can be an exception string carrying a path
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/settings_window.py:952-966` (the `why`
  parenthetical), fed by `app.py:5204-5222` -> `broll_standins` `upgrade_note`,
  written at `broll_server.py:1380-1382` and `:1416-1418`
- What: `standins_owed["why"]` is `upgrade_note[:300]`, and one writer sets it to
  `str(exc)` for a `PathTraversalError` / `MountNotConfiguredError` - messages
  built from a share name and a relative path. That string is now pasted
  verbatim into an editor-facing sentence, inside brackets, with no vocabulary
  pass and no em-dash scan behind it (the scan tests read source literals, not
  runtime values).
- Failure scenario: a mis-configured mount produces
  `2 clips still on the preview copy: the editing proxy did not arrive
  ("P:\Assets\B-roll Archive\.." escapes the share). Send them to Resolve again
  to ask for it.` - a sentence an editor cannot act on, in the window whose job
  is to tell them what to do.
- Evidence: traced the four `set_upgrade(..., FAILED, <note>)` call sites in
  `broll_server.py`; two pass an exception string, two pass an editor-safe
  sentence.
- Ledger: related to CR-283X / comp-broll-tiers-5 (new).
- Suggested fix: keep a separate editor-facing `why` on the ledger row (one of a
  small fixed set of sentences) and leave the exception text to the log, or drop
  the parenthetical when the note did not come from the editor-safe set.

### comp-ui-9 - the new stand-in phrase is appended last, so on a machine with any other Resolve count it never reaches the menu line
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray.py:2655-2666` with `:2701-2706`
  (`resolve_bridge_line` renders `phrases[:2]`)
- What: `resolve_count_phrases` appends "N clips still on a preview copy" after
  `out_of_tree`, `missing`, `bad_prefix` and `proxy_attach.failed`. The tray LINE
  carries the first two only; the rest go to the tooltip suffix. A machine with
  dead links - the machine most likely to have stand-ins - pushes the new phrase
  off the line.
- Failure scenario: an editor with 3 clips outside the tree and 2 missing sees
  `Resolve: connected - 3 clips outside the tree, 2 missing` and no mention of
  the preview copies anywhere they will look.
- Evidence: read both functions; the slice is `[:2]` and the append is last.
- Ledger: related to CR-283X (new).
- Suggested fix: insert the stand-in phrase ahead of the attach-failure phrase,
  or ahead of the whole list - "you are cutting on a 1080p preview" outranks a
  count of dead links, which have their own popup.

## Coverage note

- `ui_dispatch.py` and `crash_report.py` are in my territory but have no hunks in
  today's diff, and I gave them only a skim. The CR-93 pinning contract and
  `crash_report._prune`'s 20-file ceiling (which CR-283N reasons about) were read
  for the argument in comp-ui-5 but not audited.
- `tray_native.py`'s macOS half (`_DarwinIcon`, the NSMenu delegate) is unchanged
  today and was not read closely; the comp-ui-1/2/3/4 fixes are Windows-only by
  construction, so the mac side has no pending-toast queue and no re-add retry -
  I did not establish whether it needs one.
- I could not exercise any of the Windows tray fixes against a real Explorer:
  everything here is read plus the existing doubles, and the balloon-replacement
  claim in comp-ui-7 is the one finding that needs a live shell to settle.
- The suite has no test at all for `ProgressWindow._tick` (comp-ui-4) and none
  that drives `perform_fix_all` with a single row (comp-ui-1).

## OUT OF TERRITORY

- `companion/src/ccsync_companion/consolidate.py:443-485`: the publisher half of
  comp-ui-4 - `run_consolidation` needs the same `rehearsing` latch
  `perform_fix_all` got (comp-resolve).
- `companion/src/ccsync_companion/broll_server.py:668` publishes `standins_owed`
  as a LIST on `GET /status` while `app.py:5081` publishes a DICT under the same
  key in `resolve_health`; both readers guard with `isinstance`, but one key name
  with two shapes is a trap for the next reader (comp-broll-tiers).
- `companion/src/ccsync_companion/app.py:7271-7282`: `_BLOCKED_ORDER` returns one
  reason only, which is what makes comp-ui-6 possible; the ordering question is
  comp-app's.
