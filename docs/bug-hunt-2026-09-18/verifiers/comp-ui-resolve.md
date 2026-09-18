# verdicts - comp-ui-resolve

Verifier for `hunters/comp-ui.md` and `hunters/comp-resolve.md` (13 findings).
Read-only pass; the only evidence produced was one scratchpad snippet run from
`companion\.venv` with no Resolve connection (no `scriptapp()`, no live
process touched, no Tk root built).

## comp-ui-1
- Verdict: DOWNGRADED to low
- Duplicate of: none
- Reasoning: every fact is right - `_nim_add_delays(12, base=0.5, cap=15.0)` is
  `[0.5, 1, 2, 4, 8, 15 x 7]`, `_add_icon` sleeps all but the last (105.5 s),
  `run()` reaches `self._pump()` only afterwards, `notify()` at
  `tray_native.py:956` drops with a WARNING and `grep` finds no queue, no
  replay and no reader of "DROPPED" anywhere. What I cannot accept is the
  framing "widened the window from 2.5 s to 105 s". Before comp-ui-1 the 2.5 s
  schedule did not END the drop window, it ended the ICON: `_add_icon` raised,
  `run()` announced the failure and returned, and every toast for the rest of
  the session was dropped. So in every case where Explorer is late the new
  schedule delivers strictly more toasts, not fewer. The genuine regression is
  narrow: Explorer becoming ready in roughly the 1.5-3.0 s band, where the old
  flat schedule would have registered by 2.5 s and the new sparse one does not
  retry until 3.5 s - which is exactly where `app.py`'s fixed 3.0 s
  `threading.Timer` toasts land. That is a real, unnoticed coupling worth
  fixing, but it is one narrow band and two informational toasts, not a
  medium. The "four safety latches" half is a pre-existing gap (no toast queue
  has ever existed), not something this fix pass introduced.
- Evidence: `tray_native.py:312-330` (the schedule and its comment),
  `:861-880` (`run()` order), `:956-966` (the drop), `app.py:10664-10696` (the
  two 3.0 s timers), `app.py:3324-3332` (`_notify_tray` has no fallback path
  at all - if the icon refuses, the sentence is gone).
- Fix note: the suggested bounded pending deque flushed by `_add_icon`'s
  success path is the right shape and touches only `tray_native.py`. The
  alternative (scheduling off `icon.registered`) is weaker: `registered` is
  read exactly once, via `getattr`, at `app.py:10504`, so app.py would need a
  new wait primitive. Whoever fixes it should revisit `app.py:10670-10696`'s
  two timers in the same change, and `tests/test_bug_hunt_2026_09_11_comp_ui.py:113`
  asserts the "DROPPED" wording, so a queue must keep logging when it evicts.

## comp-ui-2
- Verdict: CONFIRMED (medium)
- Duplicate of: none
- Reasoning: I re-ran the greps and they hold. `_add_icon` has exactly two call
  sites (`tray_native.py:868` in `run()`, `:1196` in the `TaskbarCreated`
  branch); there is no `SetTimer`, no `_WM_TIMER` handler and no other write to
  `_added` except `:1078` (success), `:1127` (`_remove_icon`) and `:1190` (the
  broadcast). So after one failed re-add the only recovery in the process is
  another Explorer restart, which the code's own comment says "may be never".
  `notify()`, `_modify()` and the tip/icon setters all gate on `_added`, so the
  session is silent as well as invisible, and Quit is only reachable by killing
  the process - note that since 0.9.62 `supervisor.py` deliberately does NOT
  relaunch after a `Stop-Process`, so the editor's Task Manager kill is at least
  final rather than a loop. Medium is right: sync keeps working, and the
  trigger needs a failed re-add inside 2.5 s plus no later broadcast.
- Evidence: `grep -rn "_add_icon(" companion/src` -> two hits;
  `grep -n "SetTimer\|WM_TIMER\|_added" tray_native.py` -> no timer of any
  kind; `tests/test_bug_hunt_2026_09_11b_comp_ui.py` asserts only that the
  loops survive.
- Fix note: the `SetTimer` retry is sound and stays on the pump thread, which
  is the premise `fatal=False` already relies on. It must land with comp-ui-3:
  a once-a-minute retry that keeps calling `_announce_failure` would write one
  `TrayIconUnavailable` crash file per minute. The re-add must also keep using
  the FLAT default schedule (`cap=_NIM_ADD_RETRY_DELAY`) inside the WM_TIMER
  handler, for the same reason `_add_icon`'s `cap` argument exists.

## comp-ui-3
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `tray.py:1022` (`log.error`, ending "Sign out and back in, or
  restart CCSync, to get it back") and the `crash_report.write_report({... 
  "type": "TrayIconUnavailable"})` block at `:1032` are both outside the
  `if fatal:` guard at `:1029`, so a failure the same fix pass declared
  self-recovering still prints the terminal remedy and still spends one of the
  20 crash-file slots. `crash_report._prune` keeps the newest
  `MAX_CRASH_FILES = 20` and `crash_summary()` is read by `sync_guard` on every
  report tick, so the dashboard and Settings both see the count rise. The
  function's own docstring still argues for the unconditional crash report,
  which is evidence the `fatal` split was bolted on without revisiting it.
- Evidence: read `tray.py:995-1050` and `crash_report.py:68-80,135-141`.
- Fix note: the suggested split is right. A caller-side wording change is not
  enough - `_report_windows_icon_failure` is called from both sites, so the
  fix belongs in that function, and the non-fatal wording must stop promising
  a restart is needed. Nothing pins the current ERROR text: no test in
  `companion/tests` asserts on "Sign out and back in".

## comp-ui-4
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `run()`'s `except Exception` arm (`tray_native.py:869-874`)
  announces, sets `_stopped` and returns; `_teardown()` is reachable only from
  the `finally` around `_pump()`, which that arm never enters. After an
  exhausted `_add_icon` the process keeps the HWND, the per-instance window
  class and the WNDPROC reference for its lifetime. The severity is right: it
  is a leak in a process that is already headless, not a hang -
  `stop()`'s `_stopped.wait(5)` returns immediately because `_stopped` is
  already set.
- Evidence: read `run()` at `:861-880` and `_teardown` at `:1338-1351`.
- Fix note: calling `self._teardown()` in the except arm is safe - it is
  written defensively throughout and `_create_window` may not even have run
  (`_hwnd` is None, every step no-ops). One caveat the hunter did not name:
  `_teardown` must run BEFORE `self._stopped.set()`, or a `stop()` waiter can
  return while the window is still alive.

## comp-ui-5
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: the code reading is exact - `batch_done` is only advanced on
  `ok and not dry_run` (`popup.py:643-645`) while `batch_bytes_total` stays
  `batch_total_bytes(rows)` at both publish sites, so `_render_progress`
  computes `1000 * 0 / batch_total` and `RateEstimator` never sees a moving
  sample; `format_file_progress` still leads with `Copying "..."`. I do want to
  deflate the failure scenario: `fixer.fix_clip`'s dry-run arm returns at
  `fixer.py:1294` before any I/O, so a 40-clip rehearsal's progress phase is
  over in well under a second - the editor sees a flash, not a screen they sit
  and watch, and the answer they came for is in `_fix_done`'s rehearsal block
  a moment later. Low is correct and generous.
- Evidence: `popup.py:626-695`, `:1338-1355`, `:87-110`; `fixer.py:1292-1318`.
- Fix note: the suggested fix is right but must not break the summary: the
  final `publish(...)` at `popup.py:687-695` carries `rehearsal=`, `fixed=`,
  `skipped=` keys that `_fix_done`/`summarize_fix_results` read, so publishing
  `batch_bytes_total=0` has to stay confined to the progress keys.
  `format_file_progress` is also called on the real copy path and by
  `tests/test_popup.py`, so a wording switch needs a flag, not an edit to the
  one string.

## comp-ui-6
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `stills.py:148` is literally `f"gallery moved to {root}\\{GALLERY_FOLDER}"`
  and `desired_entry(..., windows=False)` returns `str(stills_dir(local_root))`
  as `root` - a POSIX path - with the canonical `P:\Assets\Stills` in
  `mapped_root`. On Windows `root` IS the canonical `P:\...` spelling, so the
  backslash is correct there and only a Mac sees the hybrid. The line reaches
  the Settings window through `app._note_stills` -> `stills_state()["instruction"]`.
  Cosmetic, once per successful move, and it is the one line telling the
  editor where their gallery went.
- Evidence: read `stills.py:54-76,140-152`; `grep` shows no test asserts on
  the message text.
- Fix note: `os.path.join(root, GALLERY_FOLDER)` is wrong on Windows when the
  companion runs frozen on a Mac path... in practice the manager already
  carries `self._windows`, so gate the separator on that (the module's own
  convention - `canonical_stills_path` hard-codes `\\` on purpose because that
  string must match between machines, and must NOT be changed).

## comp-resolve-1
- Verdict: CONFIRMED (high)
- Duplicate of: none (proxy-tiers-4 builds on it and cites it by id; res-companion-5 and comp-resolve-3 are downstream of it)
- Reasoning: I reproduced it independently from the companion venv with no
  Resolve: `replace_clip(item, <the path the item reports>)` returns
  `{'ok': True, 'message': 'Already linked to ...'}` and never calls
  `ReplaceClip` - my fake raises `AssertionError` from `ReplaceClip` and the
  assertion never fires. It also short-circuits for a differently-spelled but
  equivalent path (`p:/...` vs `P:\...`), since both sides go through
  `_norm_path`. The refresh op's `file_path` really is the clip's own stored
  path: `library.py:1006,1113` fill it from `paths`, which
  `resolve_bridge:1512,1625` read straight out of `GetClipProperty()["File Path"]`,
  and `plan_relinks` copies it unchanged into the op. So phase 3's one
  mechanism cannot fire, while `refreshed += 1` and the INFO line claim it
  did - and the op is re-planned every pass, spending an
  `allow_automatic` grant per 900 s against `AUTOMATIC_MAX_PER_DAY`. Nothing
  in `KNOWN_BUGS.md` covers it; CR-281 (line 24411) asserts the opposite
  ("after one ReplaceClip the relink pass runs").
- Evidence: scratch snippet output pasted above in reasoning;
  `resolve_bridge.py:2280-2285`; `proxy_relink.py:704`.
- Fix note: the `force=` parameter is right and must default to False -
  `fixer.py`/`popup.py` relink paths depend on the short-circuit to avoid a
  needless save point. Two things the hunter's fix must not miss: with `force`
  the `took` test (`after == norm_new`) is vacuously true, so a forced call
  would report success for a `ReplaceClip` that raised every time - gate the
  success on `raised < tries` at minimum, better on the `Frames` re-read; and
  `resolve_journal.record` would then write a KIND_REPLACE_CLIP entry whose
  old_path == new_path, i.e. an undo entry that undoes nothing, so the journal
  call needs a decision too. Other files a fix touches:
  `companion/tests/test_proxy_relink_standins.py` (see comp-resolve-4) and
  `KNOWN_BUGS.md` CR-281's claim.

## comp-resolve-2
- Verdict: CONFIRMED (high)
- Duplicate of: res-companion-3 (same defect, same lines; that hunter rated it medium)
- Reasoning: `_geometry_disagrees` calls `count_frames_fn(probe)` before it can
  know the counts agree, and `count_frames` is
  `ffprobe -v error -count_packets -select_streams v:0` with no
  `-read_intervals` - a full demux - at `PROBE_TIMEOUT_SECONDS = 60` per file.
  `frame_counter`'s cache is per pass by design, and `app.py:4443` builds a
  fresh one on every call, so nothing is remembered between passes. The scope
  is genuinely every archive clip and not more: `stored_frames` needs
  `item["frames"]`, which `_enrich_proxy_keys` sets only under
  `_under_broll_archive` (`resolve_bridge.py:1843-1852`) - but on the wired rig
  the archive IS the pool, and `original_present()` is true there, so the
  narrowing does not help the machine that pays. I keep the hunter's HIGH over
  res-companion-3's medium: reading the whole archive off SMB every two
  minutes competes with lanes A/B for the same link, and the cost is paid
  before `allow_automatic` is consulted (app.py checks the rate limit only
  after `if not ops: return`), so the existing rate limiter cannot bound it.
  The watchdog half is plausible, not proven: `_media_tree_heartbeat` is
  stamped only at `app.py:4481`, the top of the loop, against
  `LANE_WATCHDOG_WEDGED_SECONDS = 30 min`.
- Evidence: `ffmpeg_tools.py:905-962`; `proxy_relink.py:285-345,544-550`;
  `app.py:4431-4444,1135-1148,4479-4481`.
- Fix note: the suggested persistent (path, size, mtime) verdict is right and
  is the cheap falsifier. The "only probe a clip the ledger calls stale" half
  is NOT sufficient on its own - proxy-tiers-4 shows the ledger is per-machine
  state about an event that happened on another machine, so the wired rig's
  ledger is empty for exactly these clips. Fix comp-resolve-1 and the cheap
  signal together, or the pass gets cheaper and still does nothing.

## comp-resolve-3
- Verdict: DOWNGRADED to low
- Duplicate of: res-companion-5 (same defect, rated low/PLAUSIBLE there)
- Reasoning: the code reading is right - the refresh branch records neither a
  success nor a failure, `plan_relinks` consults only live geometry, and
  `note_refusal`'s (mtime, size) memory covers the proxy half only. But the
  harm as stated is almost entirely comp-resolve-1's: today no `ReplaceClip`
  happens at all, so there is no repeated save point and no journal growth,
  and once comp-resolve-1 is fixed the repetition is bounded by
  `allow_automatic` (one grant per 900 s, `AUTOMATIC_MAX_PER_DAY = 8`) rather
  than being unbounded. What is left is a slow leak of save points and journal
  entries for a handful of non-converging clips, which is what the other
  hunter called low. Counting it medium double-counts comp-resolve-1.
- Evidence: `proxy_relink.py:395-420` (`note_refusal`) vs `:701-722`;
  `resolve_journal.allow_automatic` bars read at `app.py:4456-4462`.
- Fix note: the (path, size, mtime, stored_frames) memory is right, and it
  should live in the same state file `note_refusal` already writes so there is
  one thing to clear. It MUST be keyed on `stored_frames` too, or a clip that
  genuinely refreshes on the second attempt is never retried.

## comp-resolve-4
- Verdict: CONFIRMED (medium)
- Duplicate of: none
- Reasoning: all three refresh tests inject `replace_fn`
  (`test_proxy_relink_standins.py:171,188,208`), and `grep` over the whole
  `companion/tests` tree finds no call of `apply_relinks` that exercises the
  default, nor any direct test of `replace_clip` on its own path - no test
  anywhere even contains the string "Already linked". So the suite's 52 green
  tests pin the shape of the refresh and mock away the only part that is
  broken. Medium is defensible because this is the specific reason a high
  shipped as "built and verified" in CR-281.
- Evidence: `grep -n replace_fn tests/test_proxy_relink_standins.py`;
  `grep -rn "Already linked" companion/tests` -> nothing.
- Fix note: the minimum version (a direct `replace_clip(item, <item's own
  path>)` test asserting `ReplaceClip` IS called under `force=True`) is the
  right one to add, and it needs no Resolve - my scratch snippet is already
  that test. It belongs in `tests/test_resolve_bridge*.py` rather than the
  relink file, and the `_no_live_resolve` conftest fixture must stay in force
  because `replace_clip`'s journal path calls `_before_mutation` ->
  `connect()`; pass `journal=False` or stub it.

## comp-resolve-5
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `message` is built only `if relinked or failures`
  (`proxy_relink.py:775-780`), so a pass that refreshed 40 clips and linked
  none produces `""` and `app.py:4475` logs "proxy relink: nothing to do".
  `_note_proxy_attach` (`app.py:4941-4962`) reads `relinked`, `failed`,
  `failures` and never `refreshed`, so the tray/report value is
  `attached: 0`. `grep -rn '"refreshed"' companion/src` confirms one producer
  and no consumer. Low is right - it is an observability gap - but it is the
  gap that hid comp-resolve-1, so it should be fixed in the same change.
- Evidence: the two functions plus the grep above.
- Fix note: correct, and additive. `_note_proxy_attach`'s dict is read by the
  report/tray surface, so adding a `refreshed` key is safe on the same "ADDED
  keys, never replacing" rule the module already states; the wire side needs
  no change.

## comp-resolve-6
- Verdict: NOT VERIFIED
- Duplicate of: none
- Reasoning: the code half is exactly as described - `plan_relinks` computes
  `new_proxy` only under `if not proxy_is_working(state)`, and
  `apply_relinks`'s refresh branch does `if not op.get("new_proxy"): continue`
  after the replace - so a refresh on a clip with a working proxy carries no
  re-attach. The claim that matters, though, is what `ReplaceClip` does to an
  attached proxy, and that cannot be answered without a live Resolve, which
  the brief forbids. The plan's spike notes do not say. I will not confirm a
  finding whose whole harm rests on an untested API behaviour, and I cannot
  refute it either. Note it is also moot until comp-resolve-1 is fixed - today
  no ReplaceClip happens on this path at all.
- Evidence: `proxy_relink.py:524-545,701-722`; no spike data in
  `docs/BROLL_PROXY_TIERS_PLAN.md` section 3 on proxy survival.
- Fix note: "read `proxy_path` back after the refresh and re-link if it went
  blank" is the cheaper and safer of the two suggestions - it costs one
  property read per refresh and needs no change to `plan_relinks`' careful
  `.mp4` rule (which audit F1 exists to protect). Whoever answers this should
  do it as a live check on the wired rig, which is already on CR-281's "still
  owed" list.

## comp-resolve-7
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `exempt_cache` is created inside the poll (`watcher.py:317`) and
  the watcher polls every `poll_interval` (default 3.0,
  `watcher.py:100,700-717`), so the verdict is recomputed for every distinct
  MISSING archive path on every poll. The cheap string test
  (`is_under_archive`) comes first, so only archive clips pay, but for those
  it is a ledger stat plus a media stat (`is_standin`) plus up to four
  `find_proxy_on_disk` existence probes - and a proxy-only b-roll timeline on
  a remote rig is the designed steady state in which every one of them is
  MISSING every poll. Low is right: it is filesystem probes on a local sync
  drive for a diagnostic count, not a correctness bug.
- Evidence: `watcher.py:308-320,405-420,503-536`; `app.py:2122-2142`
  constructs the watcher with no `archive_exempt_fn`.
- Fix note: a per-path TTL cache is right and matches `_warned_missing`'s
  existing latch. It must be invalidated (or kept short) on the arriving-file
  side: the exemption flips to "not exempt" when a proxy is deleted and to
  "exempt" when one lands, and a long TTL would keep a genuinely missing clip
  out of the count. The same `_archive_exempt_fn` injection point that the
  tests use stays the seam, so `tests/test_watcher*.py` need no rework.
