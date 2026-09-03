# Companion lifecycle, tray, popups, settings window, config, identity, upgrade

## Summary
The 2026-08-28 sweep's waves 1-4 landed hard here: the advisory lines it asked
for exist, they are well written, and `blocked_report()` is a genuinely good
piece of design (one ordered sentence, `reason` + `detail` + `since`, worst
answer wins). The problem is where all of it was PUT. On 2026-08-27 the tray
menu was cut to ten items (CR-88) and every advisory line moved into a
scrolling Settings window, and the sweep then wrote thirteen new warnings into
that same window. So the machine now knows a great deal about itself and says
almost none of it on the surface an editor looks at: the icon is green and the
tooltip says "up to date" while the dashboard has not accepted a report in
three days (APP-1). Compounding it, roughly a dozen "what to do next" strings
still route the reader through menu items the reduction deleted (APP-2), and
two of the safety toasts an editor most needs are silently discarded on macOS
because they contain a newline (APP-3). The biggest risk is APP-1: every wave
1-4 investment is one unopened window away from invisible. The cheapest strong
win is APP-2 - a route audit of about fifteen literal strings, no new
mechanism at all - closely followed by APP-1's two-line change to
`compute_overall_color` and `_tooltip_text` (both already receive the
snapshot that carries `sync_guard.blocked`).

## Findings

### APP-1: the icon stays green and the tooltip says "up to date" while `sync_guard.blocked` names a reason nothing is syncing
- **Lens:** both
- **Who:** editor, admin
- **Where:** `companion/src/ccsync_companion/tray.py:149-196` (`compute_overall_color`), `tray.py:2976-3013` (`_tooltip_text`), `tray.py:3419-3423` (the menu shows `_sync_line` only), `app.py:5586-5597` (`_BLOCKED_ORDER`), `settings_window.py:367-395` (thirteen advisory lines, Settings only)
- **Today:** `compute_overall_color` consults exactly five things: lane `state`, `config_problems`, `_root_absent`, identity, `is_paused`. It never sees `sync_guard`. `_tooltip_text` does not read `sync_guard` at all and ends `return ... "CCSync: up to date"`. So a machine whose reporter has been 401'd for a week (`_reporter_line`), whose clock is 40 minutes out (`_clock_skew_line`, which the docstring itself says makes lane B transfer nothing while exiting 0), which has given up installing an update, which reverted itself off a crashing build, whose watchdog is restarting the sequencer three times an hour, or which has `blocked = {reason: "folders_unfiltered"}` shows a **steady green mark** and a tooltip saying it is up to date. Only `_sync_line`, inside the right-click menu, carries `blocked['detail']` - and only if the editor right-clicks.
- **Proposed:** (a) `compute_overall_color(statuses, app, guard=None)` returns `"orange"` whenever `guard.get("blocked")` is present and no stronger colour applies, and `"red"` for the three that mean something is broken rather than merely stopped (`clock_skew`, `lane_stalled`, `syncthing_down`); `_guard_fingerprint` already makes the guard part of the render fingerprint, so no new plumbing. (b) `_tooltip_text` prefers `blocked['detail']` over `"CCSync: up to date"`, truncated to 127. (c) An advisory that is a WARNING (`⚠`) puts a single line into the menu itself, above `_sync_line` - one line, the highest-priority one, never all thirteen; the menu already renders a conditional block of exactly this shape.
- **Effort:** S   **Value:** critical   **Confidence:** high
- **Related:** CR-88 (the reduction), 08-28 APP-1/APP-6/APP-13, SYNC-15

### APP-2: about fifteen user-visible strings send the reader to tray menu items that no longer exist
- **Lens:** usability
- **Who:** editor
- **Where:** `app.py:3055`, `3197`, `3288`, `3313`, `3386`, `4725`, `5087`, `8374`, `8873` (all "Tray → Copy diagnostics for your admin"); `app.py:2817` ("Tray → Open log"); `app.py:2694` ("Tray → Advanced → Scan whole project"); `tray.py:463`, `tray.py:496` (same, in `classify_lane_error`); `tray.py:484` ("use Advanced → Remove a project from this machine"); `tray.py:2391` ("Sign in again from this menu"); `resolve_bridge.py:457` ("tray → Exit, then relaunch"); `tray.py:1578` ("start them again from this menu")
- **Today:** the tray menu is the ten items at `tray.py:3424-3443`. It contains no "Copy diagnostics", no "Open log", no "Advanced", no "Exit", and no "Scan whole project". Those all live in the Settings window (`settings_window.py:591-594`, `565-571`). Only two strings were updated to the correct form: `app.py:2612` and `app.py:4214` say "Tray > Settings > REPAIR P: NOW" / "Tray > Settings > COPY DIAGNOSTICS FOR YOUR ADMIN". Worse, `classify_lane_error`'s output is now rendered ONLY inside the Settings window (`settings_window.py:355-361`), so it tells a reader who is already looking at the `[ COPY DIAGNOSTICS FOR YOUR ADMIN ]` button to go and find it in the tray. The `⚠ ... Sign in again from this menu` line has the same problem plus APP-8's.
- **Proposed:** one route vocabulary, used everywhere: `Settings > COPY DIAGNOSTICS FOR YOUR ADMIN` (the button's own label, verbatim, in caps because that is what is on screen), `Settings > OPEN LOG`, `Settings > SCAN WHOLE PROJECT`, `Settings > REMOVE '<name>' FROM THIS MACHINE`, `the tray's Quit`. Also settle on one arrow: `>` for a navigation path (as `_ignored_line` at `tray.py:2447` already does), never `→`. Add a scan test in `companion/tests/` in the shape of the existing em-dash scan: a user-visible string containing `Tray →` or `Advanced →` fails.
- **Effort:** S   **Value:** high   **Confidence:** high

### APP-3: four safety toasts contain a newline, and a newline makes the macOS notification silently fail
- **Lens:** both
- **Who:** editor (Mac)
- **Where:** `tray_native.py:1390-1398` (`_quote` escapes `\\` and `"` only; the message is interpolated into an AppleScript string literal), and the four callers `app.py:2493-2497` (files moved to `.ccsync-trash`), `app.py:2507-2512` (lane B breaker tripped), `app.py:2523-2527` (free-space park), `app.py:5927-5931` (SYNCING IS STOPPED)
- **Today:** `script = f'display notification "{_quote(message)}" with title "..."'`. An AppleScript string literal cannot span lines, so `osascript` exits with a syntax error; `subprocess.run(..., check=False, capture_output=True)` discards it and `except Exception` never fires. The four notifications that go silent are precisely the four that tell a Mac editor a safety latch has engaged - the ones CLAUDE.md says only a human may clear. Nothing else on the machine raises them again: the breaker line lives in the Settings window (APP-1).
- **Proposed:** in `notify`, `message = " ".join(str(message).split())` before quoting (newline, tab and CR all collapse to a single space), and escape any remaining control characters. Log at DEBUG when a message was reflowed. Additionally, check `osascript`'s returncode and `log.debug` the stderr rather than discarding it - a notification backend that has silently done nothing for months is exactly the class of failure this repo keeps writing guards for.
- **Effort:** S   **Value:** high   **Confidence:** high

### APP-4: the Windows toast truncates at 250 characters and the truncation eats the instruction
- **Lens:** usability
- **Who:** editor (Windows)
- **Where:** `tray_native.py:829-838` (`self._modify(info=(str(message)[:250], ...))`), callers `app.py:2493-2497`, `2507-2512`, `2609-2613`, `3383-3387`, `6398-6402`, `6404-6408`
- **Today:** the cut is a hard slice at the END, and this codebase's toast convention is "what happened, then what to do next" - so the half that survives is the diagnosis and the half that is thrown away is the action. `app.py:2507` is `"CCSync STOPPED downloading proxies as a safety measure:\n" + reason + "\nYour uploads are still running ... use the tray's \"Resume proxy download\""`: the fixed text is ~200 chars, so any breaker `reason` longer than about 45 characters silently deletes the sentence naming the fix. `app.py:2493`'s trash notice loses "Copy anything you still need back out of there" as soon as `trash_dir` is a real project path. `app.py:6398` interpolates a free-form `detail` in the middle for the same effect.
- **Proposed:** a `_fit_toast(fixed_head, variable, fixed_tail, limit=250)` helper that shortens the VARIABLE middle (ellipsised) and never the tail, and logs the full text at INFO whenever it shortens. Cite the limit at the one call site that knows it, not at nine authoring sites.
- **Effort:** S   **Value:** high   **Confidence:** high

### APP-5: the sentence that names the broken setting is written into the lane detail and then thrown away by the renderer
- **Lens:** usability
- **Who:** editor, admin
- **Where:** `app.py:4598-4602` (`_lane_config_problem_detail` = `"NOT SYNCING: this machine isn't fully set up -- " + config_problems[0]`), `tray.py:543-546` (`if problems: return f"{label}: NOT SYNCING (this machine isn't set up yet)"` - returns BEFORE `detail` is read), `tray.py:2004` (the snapshot reduces `config_problems` to a bool), `settings_window.py:355-361` (Settings renders the same reduced line)
- **Today:** `validate_config` (`config.py:1857-1940`) writes genuinely good sentences - "remote_root is blank -- rclone would target the remote's default directory ... Set the absolute NAS path your admin gave you, e.g. /mnt/<pool>/<share>/<tree> (TrueNAS) or /volume1/<share>/<tree> (Synology)". Not one of them reaches any surface on the machine. The tray says "NOT SET UP: nothing will sync (Copy diagnostics for your admin)", all three lane lines say "NOT SYNCING (this machine isn't set up yet)", and the Settings window - the place a person goes to look - repeats the same nine words three times and never names the key. The only route is a diagnostics blob mailed to an admin.
- **Proposed:** carry the list, not the bool: `_tray_snapshot` gains `problem_details = list(app.config_problems)[:3]`, and `build_settings_model`'s THIS COMPUTER section renders each as a `Line(..., style="warning")` under a "WHAT IS NOT SET UP" heading, followed by `Line(f"  in {config_mod.CONFIG_PATH}", style="muted")`. Half of these an admin can fix over the shoulder in ten seconds once they know which key it is.
- **Effort:** S   **Value:** high   **Confidence:** high

### APP-6: "Sync now" - the most-clicked item in the menu - acknowledges nothing, and on some machines does nothing
- **Lens:** usability
- **Who:** editor
- **Where:** `app.py:7313-7327` (`sync_now`), `tray.py:3029-3031` (`action_sync_now`), `tray.py:3433`
- **Today:** `sync_now()` raises no toast on any path. On a wired machine (`sync_enabled=false`) it logs `"sync_now ignored"` and returns - the item is still in the menu and still clickable. In managed mode it calls `sequencer.trigger_pass_now()` and returns; whether a pass actually started, was already running, or was refused for want of a selection is invisible. The editor's mental model after clicking is "did that do anything?", and the answer arrives, if at all, as a lane line change some seconds later inside a different window.
- **Proposed:** `sync_now()` returns `(ok, message)` and `action_sync_now` toasts it: "Checking the server for changes now." / "Nothing is ticked for this computer, so there is nothing to sync." / "This computer works straight off the server, so there is nothing to sync." (the last also greys the item out via a `snap["sync_enabled"]` flag rather than offering a no-op). A trigger that is already running says "A sync pass is already running."
- **Effort:** S   **Value:** high   **Confidence:** high

### APP-7: in the Settings window, "STOP ALL SYNCING ON THIS MACHINE" looks exactly like "OPEN LOG"
- **Lens:** usability
- **Who:** editor
- **Where:** `settings_window.py:723-726` (every `Button` renders through `theme.neon_button(...)` with the default `primary=True`), `settings_window.py:575-586` (`STOP ALL SYNCING ON THIS MACHINE…`, `REMOVE '<name>' FROM THIS MACHINE…`), `settings_window.py:322-337` (the two role buttons), `theme.py:430-452` (the button has exactly two looks: brand red and muted grey)
- **Today:** one uniform red `[ LABEL ]`. In the ADVANCED section, `[ SCAN WHOLE PROJECT ]`, `[ GRADE FROM SERVER ORIGINALS (SWAP P:)… ]`, `[ STOP ALL SYNCING ON THIS MACHINE… ]` and `[ REMOVE 'Client Job' FROM THIS MACHINE… ]` are visually identical rows in one vertical stack. The last of those deletes a project's local copy; it is guarded by a confirm dialog (`tray.py:1346-1412`, good) but nothing before the click says "this one is different". Every other dialog in the package already distinguishes weight (`popup.py:820-835` renders STOP / SKIP as `primary=False` beside a red CANCEL ALL).
- **Proposed:** add `Button.tone: str = "normal" | "danger"` to the dataclass and a `danger=True` branch in `theme.neon_button` (grey-on-normal, red only on hover, plus a leading `!`), and mark the four irreversible-or-fleet-visible actions: STOP ALL SYNCING, REMOVE ... FROM THIS MACHINE, the two role switches. Sort ADVANCED so the danger group is last under its own `[ CAREFUL ]` rule line.
- **Effort:** S   **Value:** high   **Confidence:** high

### APP-8: when the dashboard rejects this machine's credential, the only button offered is SIGN OUT
- **Lens:** usability
- **Who:** editor
- **Where:** `tray.py:2388-2391` (`"⚠ The dashboard is refusing this computer's reports: your CCSync sign-in was rejected. Sign in again from this menu"`), `settings_window.py:340-344` (`if snap.get("signed_in"): Button("SIGN OUT") else: Button("SIGN IN…")`)
- **Today:** `identity.valid()` is a purely LOCAL check - the token parses and has not expired - so a token the server has revoked still reads as signed in. The advisory line therefore renders beside a `[ SIGN OUT ]` button, in a window (not a menu), with no `[ SIGN IN ]` anywhere. The editor's only correct move is to sign out and then sign in, and nothing says so. This is the exact state APP-1 of the previous sweep was built to expose, so the exposure exists and the remedy does not.
- **Proposed:** when `sync_guard.reporter.last_status` is `HTTP 401`/`HTTP 403`, the THIS COMPUTER section renders the warning Line plus `Button("SIGN IN AGAIN…", action_sign_in)` ABOVE `[ SIGN OUT ]` (`action_sign_in` already works while signed in - it just overwrites the identity). Reword the line to "⚠ The server rejected this computer's sign-in, so your admin cannot see whether you are syncing. Use SIGN IN AGAIN below."
- **Effort:** S   **Value:** high   **Confidence:** high

### APP-9: the licence refusal tells the editor to re-run the setup wizard; the tray has a one-click accept
- **Lens:** usability
- **Who:** editor
- **Where:** `eula.py:225-236` (three sentences, all ending "Re-run the CCSync setup wizard to read and accept it."), consumed by `app.eula_problem()` -> `blocked_report`'s `licence_pending` (`app.py:5648-5652`) -> `_blocked_line` -> `settings_window.py:394`, and by the startup toast `app.py:8882` (`f"NOT SYNCING: {eula_problem}"`); contrast `tray.py:3427-3428` / `app.py:4655-4676` (`► Accept the licence agreement to start syncing…`, `force=True`)
- **Today:** the machine offers a modal that accepts the agreement in one click and starts syncing without a restart (`app.py:4789-4796`), and simultaneously tells the editor in two places to go and re-run an installer wizard. CR-27's whole lesson was that a parked editor needs the smallest possible action; this copy names the largest one available.
- **Proposed:** `acceptance_problem` returns the state only ("The CC Sync licence agreement has not been accepted on this computer.", "... has been updated (version X; this computer accepted Y).") and the ACTION comes from the surface: the toast appends "Right-click the CCSync icon and choose Accept the licence agreement." and the Settings line is followed by `Button("ACCEPT THE LICENCE AGREEMENT…", action_accept_licence)`. Keep the wizard sentence only for the "acceptance record is unreadable" branch, where the tray path genuinely may not help.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** CR-27, CR-22

### APP-10: two dialogs ask an editor for their "TrueNAS username and password"
- **Lens:** usability
- **Who:** editor, owner
- **Where:** `tray.py:843` ("Enter your TrueNAS username and password to verify this machine."), `tray.py:1700-1703` ("Windows needs your server login to stream originals. Enter the same TrueNAS username and password you sign in with.")
- **Today:** these are the only two places in the tray copy that name a storage vendor. It is wrong on the Synology target (`docs/TENANCY.md`, the 2026-08-17 port), it is a word no video editor has any reason to know, and it is the same class of leak as a customer's name in code - the product's own convention is that brand strings come from `site.org_short()`/`site.product_name()` (`site.py:359-393`), both already imported by the modules next door.
- **Proposed:** "Enter the username and password you use to sign in to the CCSync dashboard." (sign-in dialog) and "Windows needs your server login to stream originals. Use the same username and password you sign in to CCSync with. It is saved on this computer, so you will only be asked once." (credentials dialog). Add a muted third line to the sign-in dialog: "Ask your admin if you do not have one." - a first-run editor has no other source for this.
- **Effort:** S   **Value:** high   **Confidence:** high

### APP-11: the sign-in dialog freezes for up to 15 seconds and can show a raw urllib error
- **Lens:** both
- **Who:** editor
- **Where:** `tray.py:884-905` (`_submit` calls `app.sign_in` inline on the Tk thread), `identity.py:305-336` (`timeout: float = 15`; the generic branch returns `{"ok": False, "error": str(exc)}`), `app.py:4954-4972`
- **Today:** clicking SIGN IN (or pressing Return) runs a blocking HTTP POST on the Tk event thread. For up to 15 s the window does not repaint, the button does not change, and on Windows the title bar gains "(Not Responding)"; keystrokes and further Return presses queue and fire another sign-in after the first returns. If the dashboard is unreachable, `error_label` shows `str(exc)` verbatim - `<urlopen error [Errno 11001] getaddrinfo failed>` for a DNS failure with Tailscale down, `timed out` for a sleeping NAS. `classify_lane_error` exists precisely to stop rclone's stderr reaching an editor; the sign-in path has no equivalent.
- **Proposed:** (a) disable both buttons and set `error_label` to "Signing in…" before the call, and run `app.sign_in` on a worker with the result marshalled back through `root.after` - the pattern `PopupDialog._safe_after` (`popup.py:1229-1245`) already establishes. (b) A `classify_sign_in_error(exc_or_message)` mapping: name resolution / connection refused / timeout -> "Can't reach the server. Check the Tailscale icon says Connected, then try again."; HTTP 401 -> "That username or password was not accepted."; HTTP 429 -> "Too many tries. Wait a minute and try again."; everything else -> "Sign-in failed. Settings > COPY DIAGNOSTICS FOR YOUR ADMIN." Raw text to the log only.
- **Effort:** M   **Value:** high   **Confidence:** high

### APP-12: CR-93's crash safety net does not exist on macOS, and launchd deliberately will not restart the companion
- **Lens:** resilience
- **Who:** editor (Mac), admin
- **Where:** `supervisor.py:325` (`if not (sys.platform ...) == "win32": return None`), `supervisor.py:231-294` (`wait_for_exit_win32` / `pid_is_alive_win32` are the only implementations), `installer/macos_bootstrap.sh:2366-2392` ("NO KeepAlive, deliberately ... RunAtLoad" only)
- **Today:** the whole justification in `supervisor.py`'s docstring - "a native abort takes every thread in the same instruction ... the only thing that can bring it back is something OUTSIDE the process" - applies identically on macOS, where Tk runs on the main thread and CR-93's `Tcl_AsyncDelete` shape is the same. But `spawn_for` returns None there, and the LaunchAgent has no `KeepAlive` (correctly: it would fight the self-upgrade re-exec). So a Mac companion that aborts is gone until the editor logs out and back in; nobody is told, and the machine simply stops reporting. leso's Mac already has a history of going quiet (memory: "a machine below 0.9.3 cannot be pushed to").
- **Proposed:** the supervisor's design is platform-neutral except for two functions. Add `wait_for_exit_posix(pid)` (poll `os.kill(pid, 0)` every 2 s - a supervisor sleeping 2 s costs nothing) and treat SIGTERM/SIGKILL exits (`-15`, `-9`) as `DELIBERATE_EXIT_CODES` alongside 0 and 1, so `launchctl bootout` and the installer's own kill are respected exactly as `Stop-Process` is on Windows. Drop the `win32` gate to `win32 or darwin`. The relaunch path (`_detached_popen` + `child_env`) is already `subprocess`-only. Everything else - the run marker, the three-in-an-hour ceiling, the relaunch note - is portable as written.
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** CR-93, `docs/GOTCHAS.md` §18

### APP-13: there is no way to restart CCSync, and Quit's label promises the wrong way back
- **Lens:** usability
- **Who:** editor
- **Where:** `tray.py:3443` (`"Quit CCSync (stops syncing until you next sign in)"`), `settings_window.py:345-347` (`[ RESTART CCSYNC NOW ]` appears ONLY inside `if _mode_needs_restart(app)`), `resolve_bridge.py:454-458` ("also restart the companion (tray → Exit, then relaunch)"), `settings_window.py:207-223` (`action_restart_now` is unconditional in its own right)
- **Today:** three separate pieces of copy tell an editor to restart the companion (`NO_SCRIPTING_MESSAGE`; the role-switch toast; the two "Restart CCSync and try again" strings at `tray.py:828`/`1683`) and the button that does it is hidden behind a role change nobody has made. The Quit label additionally says syncing stops "until you next sign in", which is false - `identity.json` persists (`identity.py:362-370`), and a restarted companion syncs without any sign-in. A first-time editor reads that as "Quit will log me out" and, conversely, an editor told to restart has no idea how; the exe is at `%LOCALAPPDATA%\ccsync\bin` and is not on the Start menu path they know.
- **Proposed:** (a) `[ RESTART CCSYNC ]` becomes an unconditional row in the HELP section, with the "takes effect on restart" warning line still driving the extra copy of it in THIS COMPUTER. (b) Quit becomes `"Quit CCSync (nothing syncs until you start it again)"`. (c) `NO_SCRIPTING_MESSAGE` becomes "... also restart CCSync (Settings > RESTART CCSYNC) before reopening Resolve."
- **Effort:** S   **Value:** high   **Confidence:** high

### APP-14: "Open my sync drive" silently does nothing exactly when the editor most needs an answer
- **Lens:** usability
- **Who:** editor
- **Where:** `tray.py:3194-3197` (`action_open_sync_drive` -> `_open_log(local_root)`), `tray.py:581-600` (`_open_log`: blank path -> one WARNING log line; any failure -> `log.exception`, no toast)
- **Today:** the item is in the ten-item menu, so it is one of the few things an editor can do at all. With a blank `local_root` (the ALL-DEFAULTS config path) it logs "nothing to open (no path configured)" and returns. With the external SSD unplugged, `os.startfile` raises and is swallowed. Either way the menu closes and nothing happens - which is the single most confidence-destroying outcome a tray item can have, and it happens in precisely the two states where the editor is already suspicious.
- **Proposed:** `action_open_sync_drive` checks first and toasts: `"P: is disconnected, so there is nothing to open. Plug the drive back in."` (reusing `site_mod.drive_phrase`) / `"CCSync does not know where your sync folder is. Settings > COPY DIAGNOSTICS FOR YOUR ADMIN."`, and on an exception `"Windows would not open <path>."`. Same treatment for `[ OPEN LOG ]`, which has the identical failure shape.
- **Effort:** S   **Value:** med   **Confidence:** high

### APP-15: the current role is a live button that re-runs a typed-word confirmation to change nothing
- **Lens:** usability
- **Who:** editor
- **Where:** `settings_window.py:322-337` (`Button("REMOTE EDITOR" + ("  (current)" if current_role != "base" else ""), ...)` - note the suffix logic labels the OTHER one), `settings_window.py:113-206` (`action_set_role`)
- **Today:** both roles are always clickable. Clicking the one you are already on runs the full gate: `[ REMOTE EDITOR ]` on a remote machine opens the typed-word dialog demanding the editor type `REMOTE` and warning that lane B "will start DELETING files" - a genuinely alarming dialog, for a no-op. And the `(current)` suffix is attached to the button whose role is NOT current (`"REMOTE EDITOR" + " (current)" if current_role != "base"` is right only because `!= "base"` means editor - correct today, but it reads as inverted and will invert for real the moment a third mode exists).
- **Proposed:** render the current role as a `Line("Current role: WIRED TO THE SERVER")` (already there at line 320) and offer only the OTHER role as a Button, labelled `SWITCH TO REMOTE EDITOR…`. One control, one meaning, and the frightening dialog only ever appears for a real change.
- **Effort:** S   **Value:** med   **Confidence:** high
- **Related:** CR-88

### APP-16: the update offer is a version number and nothing else
- **Lens:** usability
- **Who:** editor, admin
- **Where:** `upgrade.py:1122-1143` (`offer_label` -> `"Update available → v0.9.65 (install)"`, `offer_toast`), `upgrade.py:1146+` (`offer_dialog_text`); nothing in `upgrade.py` or the package record reads a `notes`/`summary` key
- **Today:** an editor is asked to interrupt their work to install a build identified only by a number they have no way to interpret. There is no "what changed", so the rational move is to ignore it - which is exactly the fleet behaviour the [ UPDATE NOW ] push and `auto_update` were added to work around. The one case where the copy IS informative is the downgrade ("That is OLDER than the v0.9.64 you are running. Only install it if your admin asked you to."), which shows the shape works when there is something to say.
- **Proposed:** an optional `summary` string on the package record (one line, set by `publish_latest.py` / `build_editor_package.ps1` from the release notes' first line), carried through the offer dict, shown as the second line of `offer_dialog_text`'s body and appended to the toast when it fits. Absent -> today's wording exactly, so no deployed dashboard is broken by it.
- **Effort:** M   **Value:** med   **Confidence:** high

### APP-17: the Settings window is one unbounded scroll with the most-referenced button at the bottom
- **Lens:** usability
- **Who:** editor
- **Where:** `settings_window.py:350-533` (SYNC LANES accumulates 3 lane lines + 2 state lines + up to 16 advisory lines + up to 5 moved-project pairs + stray/staging lines + ytdl + up to 6 proxy rows + up to 8 ingest rows), `settings_window.py:590-598` (HELP, last), `settings_window.py:668` (`root.geometry("720x640")`)
- **Today:** a machine with anything wrong renders a SYNC LANES section far taller than the 640 px window, and the `[ COPY DIAGNOSTICS FOR YOUR ADMIN ]` button - which eight of the advisory lines instruct the reader to press - is below ADVANCED, itself below YOUTUBE. There is no section navigation, no collapse, and the mouse wheel is bound but there is no keyboard paging. `_render` destroys and repacks every widget on a signature change (guarded, `settings_window.py:735-742`) and restores the scroll fraction, so a growing section shifts what is under the cursor.
- **Proposed:** two cheap moves, no new framework. (1) Put HELP FIRST when any warning-styled line was produced this render - "the thing every warning tells you to press" should be the first thing on screen when there is a warning. (2) Render each `[ SECTION ]` header as a clickable jump strip across the top (`[ THIS COMPUTER ] [ SYNC LANES ] [ ADVANCED ] [ HELP ]`, `canvas.yview_moveto` to the header's y) - about fifteen lines against the existing model, and it makes a long window navigable without changing a single string.
- **Effort:** M   **Value:** med   **Confidence:** med

### APP-18: the out-of-tree popup is all-or-nothing, and the third answer is a folder rule
- **Lens:** usability
- **Who:** editor
- **Where:** `popup.py:689-760` (rows are name + path + destination combobox; no per-row selection), `popup.py:754-772` (`SKIP FOR NOW (this session)`, `_folder_button_label`, `FIX ALL`), `popup.py:820-835` (SKIP THIS FILE exists only DURING a run)
- **Today:** with 65 rows on screen the editor's choices are: copy all 65 in, skip all 65 for this session, or set a folder rule. Copying in "these 12 from today's card and not those 53 stock clips" is only possible by starting FIX ALL and pressing SKIP THIS FILE 53 times, one per file, as each begins. RES-12's folder rule covers the recurring case well but not the mixed one, and the mixed one is what produces repeat SKIPs.
- **Proposed:** a checkbox per row, all ticked by default (so today's FIX ALL behaviour is one click away and unchanged), plus `[ NONE ]` / `[ ALL ]` in the header; `FIX ALL` becomes `FIX SELECTED (n)` when the selection is partial. `perform_fix_all` already takes a `rows` list, and `_on_retry_failed` already demonstrates passing a subset (`popup.py:954-963`), so the plumbing exists.
- **Effort:** M   **Value:** med   **Confidence:** med

### APP-19: two copy conventions collide inside one window
- **Lens:** usability
- **Who:** editor
- **Where:** `settings_window.py:514-539` (YOUTUBE: `"Accept YouTube Terms…"`, `"YouTube: signed in ✓ (sign in again…)"`, `"Use an exported cookies.txt…"`) against every other section (`"SCAN WHOLE PROJECT"`, `"RESUME PROXY DOWNLOAD"`, `"COPY DIAGNOSTICS FOR YOUR ADMIN"`), plus `settings_window.py:341` (`"SIGN IN…"`) vs `tray.py:3312` (menu `"► Sign in… (nothing syncs until you do)"`)
- **Today:** the YOUTUBE section kept the tray menu's sentence case when it was moved into the window, so one screen shows `[ Accept YouTube Terms… ]` directly above `[ SCAN WHOLE PROJECT ]`. The advisory lines that reference buttons quote them in caps (`tray.py:2447`, `app.py:4214`), which only matches three quarters of the window.
- **Proposed:** the window is `[ CAPS ]`, the menu is Sentence case, and every cross-reference quotes the label of the surface it points at. Rewrite the five YOUTUBE labels accordingly (`ACCEPT YOUTUBE TERMS…`, `SIGN IN TO YOUTUBE AGAIN (SESSION EXPIRED)…`, `USE AN EXPORTED COOKIES.TXT…`). Cheap and it makes APP-2's route audit checkable by machine.
- **Effort:** S   **Value:** low   **Confidence:** high

### APP-20: "Check the Tailscale tray icon" is the only transport-specific instruction in the product's copy
- **Lens:** usability
- **Who:** editor, owner
- **Where:** `tray.py:492-493` (`"Can't reach the server. Check the Tailscale tray icon is connected."`)
- **Today:** correct for this studio and for the tailnet-only decision (memory, 2026-08-17), but it is a bare product name in editor-facing copy with no manifest key behind it, in a file whose neighbours all route brand strings through `site.py`. A customer on a plain LAN, or one whose VPN is anything else, gets an instruction naming software they do not have.
- **Proposed:** a `[net] vpn_name` key in the site manifest (default `"Tailscale"`, published on `/api/v1/site` beside `org_name`), read through a `site.vpn_phrase()` helper; blank -> "Can't reach the server. Check your network connection." One key, one helper, one string.
- **Effort:** S   **Value:** low   **Confidence:** high

## Still open from 08-28
- APP-7 (a slow logon leaves the companion permanently headless): **not built** - `tray_native.py:784-800` still does `_create_window()` + `_add_icon()` in one try and returns without pumping, so the `TaskbarCreated` repair at `1035-1044` remains unreachable in that case.
- APP-8 (tray Pause is invisible to the dashboard and forgotten on restart): **partly built** - `blocked_report`'s `paused` reason (`app.py:5689-5692`) now reaches the fleet grid and the tray line, but `self._paused = False` at `app.py:1164` is still never read from disk, so a pause does not survive a restart or an auto-update.
- APP-9 (one un-dismissed window blocks every update path, invisibly): **not built** - no `_popup_opened_at`, no `blocked_by` in `sync_guard`, no age reminder.
- APP-10 (a cloned disk gives two computers one identity): **not built** - `machine.py:80-107` still records no `minted_on` hostname and nothing in `installer/`/`onboarding/` clears `machine.json`/`identity.json`.
- APP-12 (a machine installed and never signed in is completely invisible): **not built** - `reporter.post_once` still returns before any request when there is no editor name.
- APP-14 (the licence watcher never arms on a machine that also has a config error): **not built** - `app.py:8870-8896` still starts `_licence_watch` only in the `else` branch.
- APP-15 (the single-instance guard fails open silently on ENOSPC): **not built** - `app.py:373-413` still `except Exception: return True` with a DEBUG line.

## Cross-cutting notes
- **Dashboard/API agent:** APP-1's fix is client-side, but the same blindness likely exists on the fleet grid - `sync_guard.blocked` is a single ordered sentence per machine and is the right thing to put in the row, ahead of the lane chips. Worth checking whether a machine with `blocked.reason = "clock_skew"` renders green there too. Also: APP-16 needs a `summary` field accepted (and ignored when absent) on the package record and echoed in the upgrade offer.
- **Installer/onboarding agent:** APP-12 above (macOS supervisor) touches `installer/macos_bootstrap.sh` only to the extent of NOT adding `KeepAlive` - the comment at line 2366 is correct and should stay; the fix belongs in `supervisor.py`. Separately, the 08-28 APP-10 clone hazard is still entirely in your territory: nothing deletes `machine.json`/`identity.json` on install or uninstall.
- **Resolve/fixer agent:** `resolve_bridge.NO_SCRIPTING_MESSAGE` (`resolve_bridge.py:454-458`) is one of APP-2's stale routes ("tray → Exit") and APP-13's ("restart the companion" with no control to do it).
- **Docs agent:** `docs/EDITOR_SETUP.md` and `docs/HOW_IT_WORKS.md` should be checked against the ten-item menu; any screenshot or step that names "Advanced" or "Copy diagnostics" as tray items has the APP-2 problem in a place an editor is more likely to be reading carefully.
