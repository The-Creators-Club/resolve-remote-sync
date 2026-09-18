# verdicts - comp-ui-comp-resolve

Scope: the nine MEDIUMs of `comp-resolve` and `comp-ui`
(comp-resolve-2..5, comp-ui-1..5). Read-only verification against the
working tree as it stood on 2026-09-18 (uncommitted fix pass over HEAD
214869b). No live Resolve, no Tk dialog, no `scriptapp()`.

## comp-resolve-2
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: the code reads exactly as reported.
  `resolve_bridge.replace_clip` only answers `ok: False` when
  `raised == max(1, tries)`; the `if refresh:` arm below it returns
  `{"ok": True, "changed": False}` without consulting `raised` at all
  (`resolve_bridge.py:2382-2394`). `proxy_relink.apply_relinks` treats
  `changed is False` as a settled verdict and calls
  `note_geometry_verdict(..., False, stat, stored_frames)`
  (`proxy_relink.py:1019-1027`), and `remembered_geometry_verdict` only
  forgets it when `_proxy_fingerprint` (mtime, size) changes - which for a
  file whose original has already arrived never happens again. So a burst
  where one or two of the three `ReplaceClip` calls raised and the
  non-raising one did not move the geometry is remembered as "settled" and
  phase 3's one mechanism is disarmed for that clip.
  I could not refute it on reachability: an all-raised burst is the only
  case the `raised` counter covers, and Resolve raising on some calls and
  not others (mid-render, script-server flap) is the ordinary shape of the
  failures this module's own comments describe elsewhere.
  Mitigating, and why this is not a high: `_GEOMETRY_VERDICTS` is a module
  dict, so the damage ends at the next companion restart, and it is one
  clip per occurrence, not the pass.
- Evidence: code read of `replace_clip`'s tail (the `raised` comparison and
  the `if refresh:` return that ignores it) and of `apply_relinks`'
  `refresh.get("changed") is False` branch; `remembered_geometry_verdict`
  at `proxy_relink.py:383-396` shows the only expiry is the file
  fingerprint.
- Fix note: the suggested fix is right and the cheaper half of it (carry
  `retryable: True` when `raised > 0` and have `apply_relinks` skip
  `note_geometry_verdict` unless the pass was clean) is preferable to
  `ok: False`, which would push the clip into `failures` /
  `REASON_NO_ANSWER` and change what the RES-3 channel reports. A fix must
  also touch `companion/tests/test_bug_hunt_2026_09_18_companion_media.py`
  (the refresh block), which currently has no case with a partial raise,
  and should not disturb the `changed is True` branch, which deliberately
  notes a verdict under the pre-call `stored_frames`.

## comp-resolve-3
- Verdict: CONFIRMED (narrowed: the plan side is the live half; the insert
  side is archive-scoped by its only caller)
- Duplicate of: none
- Reasoning: `plan_relinks` refuses a `.mp4` offer on
  `new_proxy.lower().endswith(".mp4") and original_present() and not
  is_standin()` (`proxy_relink.py:833-839`) with no `_under_archive` test,
  although `_under_archive` exists in the same module (`:250`) and is used
  six lines above for the refresh gate (`:816`). `_original_on_disk` is a
  plain existence test by either spelling, and `is_standin` is the
  per-machine ledger, so a project clip at
  `P:\Projects\...\A001.mov` with a pre-R14 `Proxy\A001.mp4` beside it and
  a working original falls in the refusal. `proxy_scan.py:59-63` states in
  capitals that existing `.mp4` proxies stay valid and are not re-made, so
  the estate this hits is real and the generator will not replace it. No
  `notes` entry is appended either, so the refusal is invisible to the
  RES-3 "why is my proxy not attached" channel.
  I tried to refute it via the insert side and partly did: the second
  reader (`resolve_bridge._attach_adjacent_proxy` + `_real_original_here`)
  has exactly one caller, `_perform_insert_locked` via `perform_insert`,
  reached only from `music_worker.act_broll_insert` (the b-roll insert),
  so it is archive-scoped by construction and is at most a latent trap.
- Evidence: `grep -n "_under_archive" proxy_relink.py` -> `250`, `255`,
  `816` only; `grep -rn "_attach_adjacent_proxy" companion/src` -> one
  definition, one call site; `grep -rn "perform_insert(" companion/src`
  -> `music_worker.py:473` only.
- Fix note: gating the plan side on `_under_archive(file_path, local_root,
  canonical_prefix)` is right and free (it is already computed for the
  refresh gate a few lines above - hoist it into a local rather than
  calling twice). Adding the `notes` entry is the more valuable half. A fix
  must also touch the proxy-tiers tests that pin the refusal
  (`companion/tests/test_bug_hunt_2026_09_18_companion_media.py`'s audit-F1
  cases and `test_proxy_relink.py`): several of those build their clip on a
  `tmp_path` that is not under any archive, so a naive `_under_archive`
  gate turns them green-for-the-wrong-reason or red.

## comp-resolve-4
- Verdict: CONFIRMED
- Duplicate of: wire-3 (same defect, same two ends, also medium); partly
  overlaps regression-3 (low, the "fleet-global top-200 was not the
  per-machine answer the hand-off asked for" half) and comp-resolve-8 /
  dash-api-5 / res-companion-5 / res-fleet-4 / wire-4 on the neighbouring
  empty-list contract.
- Reasoning: `db.standins_known(conn, limit=200)` has no editor, machine or
  rel filter - it is `GROUP BY archive_rel ORDER BY last_seen DESC LIMIT ?`
  over the whole `broll_standins` table - while both sides' comments
  (`api.py:9858`, `app.py:2293`) describe a per-machine answer about the
  list the reporting machine just sent. In `_geometry_disagrees`
  (`proxy_relink.py:565-573`) a hit is conclusive: it notes the verdict
  True and returns True before either probe, so a forced `ReplaceClip` is
  planned for a clip in THIS machine's pool purely because some other
  machine once placed a stand-in at that archive rel. On the wired rig -
  the machine proxy-tiers-4 was written for - the original was always
  present and the clip was never born from a stand-in, so every such hit is
  a false positive.
  Harm is real but bounded: the refresh is a re-import of a good clip
  (proxy attachment at risk, mitigated best-effort by the comp-resolve-6
  re-attach), and the `False` verdict `apply_relinks` writes afterwards
  stops the repeat - on a machine where the canonical spelling is openable,
  i.e. not where comp-resolve-1 (high, being fixed) bites, and only until
  the process restarts.
- Evidence: `db.py:8868-8886` (no WHERE clause, fleet-wide LIMIT 200);
  `api.py:9866-9872`; `proxy_relink.py:565-573` (`if fleet is True: ...
  return True`, before the header estimate and the exact count).
- Fix note: the suggested fix is right in shape - demote the hint from a
  conclusion to a reason to run the cheap header estimate, which answers
  "nowhere near" correctly for a real original at the cost of one open.
  Filtering `standins_known` to the rels the request listed is the other
  half and it must be done on the dashboard (`db.standins_known` signature
  + `api.py`'s call, and `dashboard/tests` pin the current shape); note
  that a fix here interacts with proxy-tiers-2/dash-api-5 (the
  never-sent empty list) and with dash-db-4/proxy-tiers-4
  (`record_standins_placed` rewriting `first_seen`), so all three should be
  landed together rather than one at a time.

## comp-resolve-5
- Verdict: DOWNGRADED to low
- Duplicate of: proxy-tiers-6 (same two code sites, same argument, filed
  low and PLAUSIBLE there)
- Reasoning: the two code sites are as reported (`resolve_bridge.py:2333`
  `project_name = "" if refresh else ...`, `:2364` `if journal and not
  refresh`), and the tension with comp-resolve-6's premise is real. But the
  journal half is close to meaningless for a refresh: `KIND_REPLACE_CLIP`
  records `old_path`/`new_path`, which are the same string here, so the
  "inverse edit" it would name is this same call again - the docstring's
  reasoning is sound for the journal. Only the save point is arguable, and
  the harm named (the refresh drops the proxy, the re-attach cannot run,
  nothing records it) rests entirely on the unmeasured premise that
  `ReplaceClip` clears the attachment; no one has run this against a live
  Resolve. That is a low, not a medium.
  One point of the finding does stand and is worth recording: the
  docstring justifies the omission with "a SaveProject + ExportProject on
  every 120 s pass", which overstates the cost - `_before_mutation` only
  exports when `resolve_journal.save_point_due` claims the interval slot
  (`resolve_journal.py:476-493`), so a save point for the refresh burst is
  at most one per `SAVE_POINT_INTERVAL_SECONDS` per project, not one per
  pass.
- Evidence: code read of `_before_mutation` (`resolve_bridge.py:2223-2248`)
  and `save_point_due`; the refresh return path writes no journal entry and
  the re-attach at `proxy_relink.py:1052-1070` is explicitly best effort.
- Fix note: keeping the save point (and only the save point) for a forced
  refresh is the right shape and costs nothing extra thanks to the interval
  claim; journaling the refresh as `KIND_REPLACE_CLIP` would be wrong -
  if anything is journalled it is the re-attach, which already goes through
  `link_proxy_media`'s own `KIND_LINK_PROXY`. Any fix must update the
  `force` docstring (it is the stated contract three other findings quote)
  and check `companion/tests/test_bug_hunt_2026_09_18_companion_media.py`,
  whose refresh tests assert no save point is taken.

## comp-ui-1
- Verdict: CONFIRMED
- Duplicate of: none (comp-ui-4 is its consolidate twin, a different
  surface)
- Reasoning: `rehearsing = False` is initialised before the loop
  (`popup.py:583`) and only set from `outcome.get("dry_run")` AFTER
  `call_fix_clip` returns (`:668-671`), while the progress publish that
  zeroes the byte totals runs BEFORE the call (`:650-656`). So file 1 of
  every rehearsal publishes `file_bytes_total=file_total`,
  `batch_bytes_total=batch_total` and `rehearsing=False`, and
  `PopupDialog._render_progress` (`:1374-1384`) therefore draws the exact
  "Copying ...: 0 B of N" screen CR-283P was written to remove. With one
  row that is the whole run. Nothing upstream pre-seeds `rehearsing`:
  `fixer_dry_run` is read only inside `fixer.py` (`:1140-1164`), and
  `perform_fix_all` never asks.
  I could not refute it on reachability: `fixer_dry_run` is a config key an
  admin turns on precisely to watch this screen (RES-15), and the
  single-dead-link FIX ALL is the common case.
- Evidence: code read of `popup.perform_fix_all` lines 583, 650-656,
  668-671 and `_render_progress` 1374-1384; the hunter's scratchpad
  transcript matches the code exactly, so I did not re-run it.
- Fix note: the suggested fix is right, and reading the same cached answer
  `fixer.fix_clip` uses is the correct source - `fixer` exposes the cached
  `fixer_dry_run` resolution at `fixer.py:1140-1164`, so call that rather
  than re-reading config (a second read could disagree with the run after a
  config reload). Keep the first-answer latch as the fallback for callers
  that inject their own `fix_clip_fn`, as the hunter says, or injected
  dry-run doubles will regress. A fix must also touch
  `companion/tests/test_bug_hunt_2026_09_18_companion_core.py:709-745`,
  which asserts on `mid[-1]` and so passes on the unfixed code.

## comp-ui-2
- Verdict: DOWNGRADED to low
- Duplicate of: none (comp-ui-7, low, is the neighbouring flush-rate
  question)
- Reasoning: the mechanism is exactly as described and I could not refute
  it. `notify` queues only when `not self._added`
  (`tray_native.py:1000-1020`); `_added` is cleared only in `_remove_icon`
  and in the `TaskbarCreated` handler (`:1263-1268`), so between Explorer
  dying and the broadcast arriving `notify` goes to `_modify`, whose
  `Shell_NotifyIconW(NIM_MODIFY)` failure is swallowed at DEBUG
  (`:1191-1194`) with no queue entry. A safety-latch sentence raised in
  that window is lost.
  The downgrade is about reachability, not correctness: the window is the
  few seconds between an Explorer crash and its restart broadcast, and it
  must coincide with one of the handful of toasts the companion raises in a
  day. That is a rare-times-rare, and the ledgered bug CR-283M was aimed at
  the startup window, which it does fix - so "CR-283M does not fix
  comp-ui-1" overstates it; this is a neighbour, not a partial fix.
- Evidence: `grep -n "_added = " tray_native.py` shows the only clears are
  `_remove_icon` and the `TaskbarCreated` arm; `_modify` ignores its return
  beyond `log.debug`.
- Fix note: the suggested fix is right and small - on a failed
  `Shell_NotifyIconW` that carried `NIF_INFO`, append to
  `_pending_toasts`; the existing `_flush_pending_toasts` on the next
  successful `_add_icon` then delivers it. Do NOT also set
  `_added = False` from `_modify` as the hunter floats: `_modify` is called
  from the tooltip and icon setters on the refresh loop, so a single
  transient failure there would flip the icon into the not-registered state
  and arm the re-add machinery on a healthy icon. A fix should land with
  comp-ui-7's drain rate (five queued balloons delivered back to back is
  one balloon on screen) or the extra entries buy nothing.

## comp-ui-3
- Verdict: DOWNGRADED to low
- Duplicate of: none
- Reasoning: the factual claims all hold. `_teardown`
  (`tray_native.py:1473-1490`) cancels the re-add timer, removes the icon,
  destroys the cached HICONs and assigns `self._hwnd = None`; it calls
  neither `DestroyWindow` nor `UnregisterClassW`, and `UnregisterClassW`
  does not appear anywhere in the file (the only `DestroyWindow` calls are
  at `:1256` and `:1262`, inside `_on_message`, i.e. the pump path). So
  run()'s comment ("the happy path frees the window, its per-instance class
  and every cached HICON in _pump's finally") is wrong twice: the happy
  path frees the window in the PUMP, not in `_teardown`, and the class is
  never freed on any path. The CR-283O arm therefore leaks one HWND with
  its handle nulled, plus the per-instance class, and the regression test
  at `:317-346` asserts `icon._hwnd is None` and the destroyed HICONs only
  - it would pass against a `_teardown` that did nothing but null the
  attribute.
  Downgraded because the harm is one window and one class per process, in
  a terminal arm that only runs when startup registration has already
  failed, and the dangling-WNDPROC crash needs the `_WindowsIcon` to be
  collected while USER32 still holds its class - the instance is held for
  the life of the tray in every shipping path. This is an inaccurate ledger
  entry and a small leak, not a medium-severity defect.
- Evidence: `grep -n "UnregisterClass\|DestroyWindow" tray_native.py` ->
  `656`, `657` (argtypes), `1256`, `1262` (pump only); read of `_teardown`
  and of the test's `_User32` double, which defines neither call.
- Fix note: the suggested fix is right, with one caution - `DestroyWindow`
  must be called on the thread that created the window (USER32 refuses it
  cross-thread), and in the CR-283O arm that is the pump thread, which is
  the caller, so it is safe THERE; `_teardown` is also reached from the
  `finally` after `_pump()`, where the window is usually already destroyed,
  so the call needs an `IsWindow`-style guard or must tolerate a false
  return. Store the class name on `self` in `_create_window` so teardown
  can unregister it, and extend the test double with `DestroyWindow` /
  `UnregisterClassW` or the fix stays unpinned.

## comp-ui-4
- Verdict: CONFIRMED
- Duplicate of: none (comp-ui-1 is the FIX ALL surface of the same shape)
- Reasoning: verified both ends. `consolidate.run_consolidation` publishes
  `file_bytes_total=size` and `batch_bytes_total=batch_total` before each
  file (`consolidate.py:470-473`) and never publishes a `rehearsing` key -
  `grep -n "rehears" consolidate.py` matches only `count_rehearsed` and its
  docstring. Its renderer is `popup.ProgressWindow._tick`
  (`popup.py:1858-1868`), which calls `format_file_progress` with no
  `rehearsal=` argument and draws the batch bar off bytes, where
  `PopupDialog._render_progress` (`:1374-1384`) now passes
  `rehearsal=rehearsing`. The 2026-09-11 fix (comp-resolve-2) stopped
  `run_consolidation` crediting bytes for a `dry_run` outcome but left the
  totals, which is precisely the "0 B of 800 GB with the word Copying"
  screen CR-283P calls untrustworthy. The ledger entry names popup.py as
  the fix site, so this genuinely reads as covered and is not.
- Evidence: the two code sites above; `grep -n "rehears\|dry_run"
  consolidate.py` (no `rehearsing` publish); there is no test anywhere for
  `ProgressWindow._tick`.
- Fix note: the suggested fix is right and is the same two changes twice.
  Note `run_consolidation` cannot latch on the first answer alone any more
  cheaply than `perform_fix_all` can, so give both the same source (the
  cached `fixer_dry_run` answer) in one change rather than two different
  mechanisms. Files a fix must touch: `consolidate.py` (the per-file
  publish and, for consistency, the final publish's totals), `popup.py`
  (`ProgressWindow._tick`), and a new test - the suite has none driving
  `_tick`, and one must follow the conftest pattern that keeps real Tk out
  of the process.

## comp-ui-5
- Verdict: DOWNGRADED to low
- Duplicate of: none
- Reasoning: the mechanism is right but the stated failure scenario is
  refuted. `_report_windows_icon_failure(..., fatal=False)` has exactly one
  producer: the Explorer-restart re-add failure at
  `tray_native.py:1288-1290`. A startup registration failure - the
  hunter's "a machine where NIM_ADD fails for a durable reason" - goes
  through `run()`'s `_announce_failure(str(exc))` with the default
  `fatal=True`, which still writes the `TrayIconUnavailable` crash report
  and so still reaches `sync_guard.crashes` and the dashboard. What remains
  is narrower: a machine whose icon registered once, lost it to an Explorer
  restart, and whose re-add then fails durably, gets one `log.warning` and
  then silent per-minute DEBUG retries with no off-machine surface. That is
  a real rule-5 gap, and `registered` still has no reader in the repo
  (grep over `companion/src` and `dashboard/src` finds only the pycache
  binary), but it is not the "no surface at all" the finding claims.
- Evidence: `grep -n "fatal" tray.py` -> the hook at `:5064-5070` defaults
  `fatal=True`; `_announce_failure`'s only `fatal=False` call site is
  `tray_native.py:1288`; `run()`'s error arm calls `_announce_failure` with
  one argument.
- Fix note: the suggested fix (one `TrayIconUnavailable` report per process
  once the retry has failed N ticks, latched on `self`) is right and
  respects CR-283N's actual concern, which was one crash file per broadcast
  evicting real reports through `crash_report._prune`'s 20-file ceiling.
  Giving `registered` a reader in `build_diagnostics` is the better half -
  it puts the condition on the dashboard without touching the crash-report
  budget at all - and that change also touches
  `dashboard/src/ccsync_dashboard` (whatever renders the machine's
  diagnostics) plus the report schema's tests.
