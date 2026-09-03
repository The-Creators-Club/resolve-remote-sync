# comp-ui — companion tray/popup/Tk-lifecycle/LUT-prefs territory

Files read (with approximate coverage):
- `companion/src/ccsync_companion/ui_dispatch.py` (100%)
- `companion/src/ccsync_companion/resolve_prefs.py` (100%)
- `companion/src/ccsync_companion/luts.py` (100%), `stills.py` (~70%)
- `companion/src/ccsync_companion/tray_native.py` (100%)
- `companion/src/ccsync_companion/settings_window.py` (~60%: docstring, `action_set_role`, whole Tk shell)
- `companion/src/ccsync_companion/tray.py` (~55%: dialog sites, lock sites, `_build_menu`, `_menu_fingerprint`, `start_tray`, action_*)
- `companion/src/ccsync_companion/popup.py` (~45%: `PopupDialog.show`/`_drop_widgets`, `ProgressWindow`, `confirm_dialog`, `licence_dialog`, `_tk_pick`, `show_popup`)
- `companion/src/ccsync_companion/theme.py` (~40%: `apply_window_icon`, `style_*`, `neon_button`)
- tests: `test_tk_release_native.py`, `test_tk_interpreter_hygiene.py`, `test_no_em_dash.py` (headers), `test_tray.py` (youtube sections)

Tests run:
`companion/.venv/Scripts/python.exe -m pytest tests/test_tray.py tests/test_tray_guard.py tests/test_tray_native_main_thread.py tests/test_ui_dispatch.py tests/test_popup.py tests/test_luts.py tests/test_resolve_prefs.py tests/test_settings_window.py tests/test_no_em_dash.py tests/test_theme.py tests/test_tk_interpreter_hygiene.py tests/test_tk_release_native.py tests/test_stills.py -q`
-> **610 passed** (clean baseline; none of the findings below are caught by it).

Plus two ad-hoc scripts from the companion venv (scratchpad, not the repo) reproducing finding 1.

## Findings

### comp-ui-1 — Two tray dialogs build a `tk.Tk()` root outside `ui_dispatch`, orphaning a Tcl interpreter per click (and touching Tk-Aqua off the main thread on macOS)
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray.py:977` (`_install_youtube_cookies`) and `companion/src/ccsync_companion/tray.py:1088` (`_show_youtube_terms_dialog`). Contrast the correct pattern at `companion/src/ccsync_companion/popup.py:2225-2248` (`_tk_pick`) and `companion/src/ccsync_companion/app.py:7245-7262`.
- What: both functions run on a tray worker thread (`action_youtube_cookies_file` / `action_youtube_terms` -> `_spawn`) and call `tk.Tk()` **directly**, then `root.destroy()`. They are the only two `tk.Tk()` sites in the package not wrapped in `ui_dispatch.dispatch(...)`, and neither calls `ui_dispatch.release_root()`. Three consequences:
  1. **CR-93 machinery is defeated.** `install_tk_guard` pins every interpreter at birth; `_try_free()` only ever runs from `dispatch()`'s `finally` (`reclaim_mine`) or `release_root()`. Neither happens here, the `_spawn` worker thread then exits, and the record becomes an **orphan that can never be freed for the life of the process** (~1.8 MB each; `PINNED_WARN_AT = 8` then logs an ERROR). This is exactly the state `_report_orphans()` calls out as "the bug".
  2. **On macOS this builds a Tk-Aqua root on a worker thread**, which is the whole reason `ui_dispatch` exists ("neither AppKit nor Tk-Aqua may be touched off the main thread"). No dispatcher hop, no hidden-root serialisation.
  3. The docstring's own justification is wrong: `_install_youtube_cookies` says *"No popup lock: askopenfilename is a native modal, **not one of this process's Tk roots**"* — but the code six lines below creates one. So the AUDIT_2 CORE-H8 sibling-Tk-root hazard the lock exists for is live: the fixer popup or Settings can be open while this second root is created.
- Failure scenario: editor clicks Settings -> YouTube -> "use an exported cookies.txt", cancels, repeats. On Windows every click permanently pins one Tcl interpreter; after 8 the log carries the "something keeps a widget or a closure for the life of the process" ERROR with no actual holder (`held by: <none>`). On a Mac the same click builds Tk-Aqua off the main thread beside `ui_dispatch.serve()`'s hidden root.
- Evidence: reproduced with the companion venv. Replicating `tray.py:977` verbatim on a worker thread that then exits:
  ```
  pinned after worker exited: 1
    - a Tk root (built by thread 'ccsync-tray-action' at worker_like_tray_py:7):
      thread EXITED, window gone, 2 refs (baseline 3), pinned=True, held by: <none>
  ```
  The same body wrapped in `ui_dispatch.dispatch(...)` + `release_root(root, ...)`:
  ```
  pinned after fixed worker: 0
  ```
  The suite cannot see it: **every** test of these two functions passes the `picker=` / `confirm=` seam (`tests/test_tray.py:2399, 2413, 2429`; `tests/test_ytdl_browser_login.py:317`), which mocks away the exact `tk.Tk()` branch. `tests/test_tk_release_native.py` proves the mechanism but scans no source, and `tests/test_tk_interpreter_hygiene.py` only scans `StringVar`/`Style` masters — nothing pins "a `tk.Tk()` must be inside `ui_dispatch.dispatch`".
- Ledger: new (regression-in-spirit of CR-93; the 0.9.55 sweep missed these two sites).
- Suggested fix: wrap each body in `def _ask(): root = tk.Tk(); try: ... finally: ui_dispatch.release_root(root, "<label>")` and call it through `ui_dispatch.dispatch(_ask)`, exactly as `popup._tk_pick` does; take `_popup_active_lock` too, and correct the docstrings. Add an AST guard to `test_tk_interpreter_hygiene.py`: every `tk.Tk()` call in the package must be lexically inside a function that is passed to `ui_dispatch.dispatch` (or be `ui_dispatch`'s own `_make_root`).

### comp-ui-2 — User-visible copy still directs editors to tray menu items that the 2026-08-27 menu reduction deleted
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray.py:463, 478, 484, 490, 496, 951, 1160, 1408, 1648, 1770` (and the same strings in `app.py`, `fixer.py`, `identity.py`, `resolve_journal.py` — see OUT OF TERRITORY)
- What: `_build_menu` (tray.py:3244) renders exactly ten rows: identity, optional Sign in, the conditional block, state lines, Sync now, volunteer, Pause/Resume, Open my sync drive, Open dashboard, `Settings…`, Quit. `Copy diagnostics`, `Open log`, `Scan whole project` and the whole `Advanced` submenu moved into `settings_window.py` (buttons `COPY DIAGNOSTICS FOR YOUR ADMIN`, `OPEN LOG`, `SCAN WHOLE PROJECT` at settings_window.py:591, 593, 542). The error copy was not updated with them: nine strings in tray.py alone still say `"Tray → Copy diagnostics for your admin."`, one says `"use Advanced → Remove a project from this machine"` (tray.py:484) and one `"Advanced → YouTube: use an exported cookies.txt…"` (tray.py:951). Two sites *were* updated (`popup.py:1263`, `settings_window.py:237-238, 254` say `"Tray > Settings > COPY DIAGNOSTICS FOR YOUR ADMIN."`), which is what makes this a missed sweep rather than a deliberate shorthand.
- Failure scenario: a lane fails; the balloon says "Something went wrong. Tray → Copy diagnostics for your admin." The editor right-clicks the tray, finds no such item anywhere in the ten rows, and the admin never gets the diagnostics bundle — on precisely the machine that needed it. Same for "Advanced → Remove a project from this machine": there is no Advanced submenu, and removal is now a per-project `REMOVE '<name>'` button inside Settings (settings_window.py:581-586).
- Evidence: read `_build_menu` in full (tray.py:3244-3444) — no Copy-diagnostics / Open-log / Advanced item exists. `grep -n 'Button("' settings_window.py` confirms where they went. `grep -rn "Tray →" src/ccsync_companion` lists the stale strings.
- Ledger: new.
- Suggested fix: rewrite the ten tray.py strings (and the sibling files) to the already-agreed wording `Tray > Settings > COPY DIAGNOSTICS FOR YOUR ADMIN`, `Tray > Settings > OPEN LOG`, `Tray > Settings > SCAN WHOLE PROJECT`, `Tray > Settings > REMOVE '<project>'`. Worth a scan test in the companion suite (the same shape as `test_no_em_dash.py`) that fails on `"Tray → Advanced"` / `"Tray → Copy diagnostics"` / `"Tray → Open log"`, so the next menu move cannot leave the copy behind again.

### comp-ui-3 — `LutLinkManager._report` warns once per PROCESS, not once per streak, so a recurring LUT-link failure is silent after the first time
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/luts.py:397-400` and `:486-491`
- What: `self._warned` is a `set[str]` of *statuses*, and `_report` adds a status the first time it carries a message and never removes it except in the single `self._warned.clear()` on a successful add (luts.py:471). The comment says "Warn once per streak, not once per check", but nothing detects the end of a streak.
- Failure scenario: the library is briefly absent at boot -> one `no-library` warning. Hours later P: drops for real and the library is gone for a day: `check()` reports `no-library` every cycle, `_report` suppresses the log line forever, and `companion.log` holds nothing about the LUT library being unreachable for that whole period. Also: `add_lut_location` returning `FORMAT_UNRECOGNISED` after a Resolve upgrade rewrote the prefs logs once and never again.
- Evidence: read; `_warned` is only mutated at luts.py:471 (`clear()` on OK) and luts.py:489 (`add`). No time or streak component.
- Ledger: new.
- Suggested fix: clear `self._warned` whenever `status` differs from `self._last_status`, or key the set on `(status, message)` with a re-warn interval (e.g. once an hour), so a persistent failure keeps saying so.

### comp-ui-4 — `copy_into_library` joins an unvalidated `dest_rel`, so a `..` segment writes outside the LUT library
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/luts.py:339-364` (`dest = library.joinpath(*[p for p in rel.split("/") if p])`)
- What: the filter drops empty segments but not `..` or an absolute/drive-qualified segment. Today `dest_rel` only ever comes from `_dest_rel()` (a `Path.relative_to` result, so never `..`), which is why this is low and PLAUSIBLE rather than CONFIRMED — it is a missing fail-closed on the one function in this module that writes files, and `adopt(entries)` takes whatever list it is handed.
- Failure scenario: any future caller (or a widened stray scan that follows a symlink and produces a `../` relative path) writes a copied LUT outside `<root>/Assets/Luts` — i.e. into a Syncthing-shared tree at an unintended path.
- Evidence: read; `_dest_rel` is the only current producer, `copy_into_library` does no containment check on `dest`.
- Ledger: new.
- Suggested fix: after building `dest`, refuse unless `_is_under(_resolved(dest), _resolved(library))` — the helper is already in this file for the stray scan.

### comp-ui-5 — `_DarwinIcon.stop()` calls AppKit from whatever thread requested shutdown
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/tray_native.py:1364-1374`
- What: every other AppKit touch in `_DarwinIcon` goes through `self._to_main` (`_darwin_on_main_thread`) — precisely the comp-app-core-2 fix of 2026-08-21 — but `stop()` calls `NSStatusBar.systemStatusBar().removeStatusItem_(...)` inline. `stop()` is reachable from the Quit menu item (main thread, fine) *and* from `app.shutdown()` on a non-main thread, where it is a Main-Thread-Checker violation of the same class the rest of the class was fixed for.
- Failure scenario: a SIGTERM/self-upgrade shutdown on a Mac removes the status item off the main thread: intermittent menu-bar corruption or an AppKit crash with no Python traceback, at the exact moment the process is trying to hand over to a new build. Cannot be verified from Windows.
- Evidence: read; `_apply_title`, `_apply_image`, `_apply_menu` all hop, `stop()` does not.
- Ledger: new (related to comp-app-core-2).
- Suggested fix: `self._to_main(self._remove_status_item)` with `self._stopped.set()` left on the calling thread, so shutdown never blocks on the runloop.

## Coverage note
- Not reached: most of `popup.py` (`PopupDialog` row building, `perform_fix_all`, `WorkProgressWindow`, the ingest picker's timeout path), `stills.py` past line ~660, `theme.py`'s branding/registry half, `tray.py`'s snapshot/advisory-line builders (`_sync_line`, `_ingest_lines`, `_proxy_*`), and the whole `tray_native` `_darwin_helper_classes` runtime behaviour.
- What the suite does not cover, and should: (a) no scan that a `tk.Tk()` is built inside `ui_dispatch.dispatch` (finding 1); (b) no test that a tray-copy string names an item the tray menu actually has (finding 2); (c) `_install_youtube_cookies` / `_show_youtube_terms_dialog` are only ever exercised through their `picker=`/`confirm=` seams, so the Tk half of both is entirely untested; (d) nothing exercises `_WindowsIcon._teardown` concurrently with the refresh/pulse threads (`_hicon_cache` is iterated in `_teardown` while `_icon_handle` may still insert into it from a loop that has not yet noticed `_ccsync_stop` — a `RuntimeError: dictionary changed size during iteration` inside `run()`'s `finally` would leave `_stopped` unset and make every `stop()` wait its full 5 s; narrow, unverified, not reported as a finding).
- Verified clean: `_check_struct_sizes()` returns `[]` on this rig (NOTIFYICONDATAW 976, MENUITEMINFOW 80); `_queue_latency_ms` wrap arithmetic; `_clamp_menu_anchor`'s alignment-mask rewrite; `resolve_prefs.PrefFile.save`'s tempfile+`os.replace`+`copymode` atomicity, line-ending and `surrogateescape` handling; `ensure_media_storage`'s descending shift loops; the em-dash rule (`test_no_em_dash.py` walks the AST over the whole package and passes).

## OUT OF TERRITORY
- `companion/src/ccsync_companion/app.py:2694, 2791, 2817, 3055, 3197, 3288, 3313, 3386, 4725, 5087, 8374, 8873`: same stale `Tray → Copy diagnostics` / `Tray → Advanced → Scan whole project` / `Tray → Open log` copy as comp-ui-2, in balloon text an editor reads.
- `companion/src/ccsync_companion/fixer.py:1187`, `identity.py:538`, `resolve_journal.py:296`, `loopback_guard.py:112`: likewise.
- `companion/src/ccsync_companion/app.py` `prompt_licence_acceptance`: `popup.licence_dialog` takes no `_popup_active_lock` of its own (by design, per its docstring) — whether the caller holds it across the dialog is an app.py question and worth a second pair of eyes given the "licence dialog always loses the popup lock" history.
