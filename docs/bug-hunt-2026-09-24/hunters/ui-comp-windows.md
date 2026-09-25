# ui-comp-windows - companion Tk + native UI (popup, Settings, tray menu/tooltip/balloons, licence dialog, sign-in windows)
Files read (approximate coverage): companion/src/ccsync_companion/settings_window.py (all), ui_copy.py (all), eula.py (all), theme.py (all), popup.py (PopupDialog._build, confirm_dialog, notice_dialog, show_popup, licence_dialog; progress windows skimmed), tray.py (_build_menu, _tooltip_text and suffixes, _blocked_line, halt/resume/grade-swap/remove confirm bodies, _build_sign_in_dialog, _youtube_sign_in), tray_native.py (toast/tooltip limits, win32 notify, macOS notify), drive_reminder.py (sentences, Unfinished), ytdl_browser_login.py (run and its Outcome copy), app.py (licence dialog caller, blocked_report/_blocked_candidate, drive_unfinished_summary, other confirm_dialog callers), assets/EULA.md head.
Tests/probes run: companion venv snippets (scratchpad only): (1) `_lane_advisories` + `rank_advisories` + `_help_first` on a `no_selection` guard; (2) `_tooltip_text`'s `[:127]` slice and `_licence_advisory` on the three licence sentences; (3) Tk font measurement in a withdrawn root (Consolas 10, 96 DPI, 1920 px screen) of the confirm_dialog bodies; (4) a withdrawn-root build of the Settings jump strip with theme.neon_button and winfo_reqwidth; (5) fixer.default_destination_dirs lengths; (6) WCAG contrast of the theme palette. No window was mapped, nothing live touched.

## Findings

### ui-comp-windows-1 - confirm_dialog never wraps its body, so the WIRED TO THE SERVER confirm is 2,280 px wide and its buttons are off-screen
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/popup.py:2419 (confirm_dialog body Label, no wraplength); same in notice_dialog popup.py:2477; callers settings_window.py:353, tray.py:2067, tray.py:2037, tray.py:1995
- What: confirm_dialog renders `body` in a tk.Label with no `wraplength`, and the button bar is packed `anchor="e"` (right edge). Every caller that writes a paragraph without `\n` gets a window as wide as the whole paragraph on one line. The typed-word confirm next to it (`_ask_typed_confirmation_locked`, tray.py:1946) wraps at 520; this one does not.
- Failure scenario: an editor clicks WIRED TO THE SERVER in Settings. The body (321 characters, one line) measures 2,247 px in Consolas 10 at 96 DPI, so the dialog is about 2,283 px wide on a 1,920 px screen; CANCEL and the OK button sit at the right edge, off-screen. Same shape on a 1,366/1,536 px laptop for the STOP ALL SYNCING confirm (a 1,582 px line) and the RESUME PROXY DOWNLOAD confirms (1,442 px). The editor sees a sentence running off the screen and no buttons; only the title-bar X (which cancels) is reachable.
- Evidence: probe (3): wired 2247 px, remote 2107, halt 1582, resume 1442; screen 1920. Code: no wraplength on popup.py:2419/2477.
- Ledger: new
- Suggested fix: give confirm_dialog and notice_dialog's body Label `wraplength=520` (the typed-confirm value), or cap it at a fraction of `winfo_screenwidth()`.

### ui-comp-windows-2 - Having nothing ticked is drawn as a RED blocking line in Settings, and it moves HELP to the top as if something were wrong
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/settings_window.py:199 (`(BLOCKING, tray_mod._blocked_line)`), settings_window.py:96 (`BLOCKING -> "warning"`), settings_window.py:1626 (`_help_first`); tray.py:170 (`_BLOCKED_INFORMATIONAL`)
- What: `_blocked_line` returns the no_selection sentence without its warning glyph because tray.py treats it as informational (live-5). But Settings gives `_blocked_line` a fixed BLOCKING severity at the producer level, so the sentence is styled "warning" (red, the tier reserved for "work is not reaching the server"). `_help_first` then sees a warning line and moves HELP above THIS COMPUTER.
- Failure scenario: a new laptop with no projects ticked opens Settings and sees "No projects are ticked for this computer" in red in SYNCING, with HELP / COPY DIAGNOSTICS pulled to the top of the window. This breaks the owner rule (2026-09-11, restated 2026-09-18) that nothing ticked is never an error or warning on any surface. The PROJECTS section below already says the same thing calmly.
- Evidence: probe (1): `_lane_advisories({"blocked":{"reason":"no_selection",...}})` -> `[('blocking', ...)]`, `rank_advisories` -> `Line(..., style='warning')`, `_help_first` -> `['HELP', 'SYNCING']`.
- Ledger: new (breaks owner rule "nothing ticked is fine")
- Suggested fix: in `_lane_advisories`, tag the blocked line INFO when `blocked.reason` is in `tray_mod._BLOCKED_INFORMATIONAL`, or suppress it there because `_projects_section` already says it.

### ui-comp-windows-3 - The licence dialog shows raw EULA.md, including the internal "DRAFT FOR COUNSEL / TODO(legal)" authoring comment
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/app.py:6200-6240 (`_show_licence_dialog` passes `eula_mod.bundled_text()` verbatim), popup.py:2617-2627 (inserted into the Text widget as is); content at companion/src/ccsync_companion/assets/EULA.md:1-15
- What: the licence dialog inserts the bundled Markdown file as-is. That file starts with an HTML comment written for the lawyer, not the reader: "DRAFT FOR COUNSEL, NOT LEGAL ADVICE, NOT YET EXECUTABLE ... has NOT been reviewed by a qualified legal professional. TODO(legal): replace "Cablewrap Creative" ... almost certainly NOT the correct contracting entity". The `<!-- EULA-VERSION: 1.0 -->` marker and the Markdown syntax (`#`, `**`) come after it. The dialog shows all of this in a disabled Text widget.
- Failure scenario: a customer's editor on a fresh machine gets the NOT SYNCING licence modal. The first thing on screen is an engineer's note saying the agreement is not executable, is unreviewed and names what is probably the wrong company (and a brand the owner has retired). The editor must click ACCEPT beneath that to sync at all.
- Evidence: `head assets/EULA.md`; app.py:6233 passes `document` unchanged; popup.py:2627 `text.insert("1.0", document)`.
- Ledger: new
- Suggested fix: strip HTML comments (and optionally Markdown markup) for display in `_show_licence_dialog`, keeping the full text for the hash and version parse. The wizard's copy probably wants the same treatment.

### ui-comp-windows-4 - The Settings jump strip is wider than the window: ADVANCED is cut and HELP is invisible at the default size
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/settings_window.py:1769-1823 (strip Frame packed `side="left"` with no wrap), settings_window.py:1761-1762 (`720x640`, `minsize(560, 420)`), settings_window.py:1830 (`wraplength=660`)
- What: one neon_button per section goes in a single non-wrapping row. At the fixed 720 px geometry, pack clips whatever does not fit. Separately, every Line is given a fixed `wraplength=660` whatever the window width. When the window is dragged down to its 560 px minsize (about 505 px of usable canvas), each advisory is cut on the right rather than reflowed.
- Failure scenario: a healthy machine (THIS COMPUTER, SYNCING, PROJECTS ON THIS COMPUTER, RESOLVE, FLEET JOBS, ADVANCED, HELP). The buttons end at x=746 (ADVANCED) and x=815 (HELP) against a 720 px window, so HELP, the section APP-17 built the strip to reach, cannot be seen or clicked. A YOUTUBE section cuts off more. An editor who narrows the window loses the ends of the red advisories, which is where the action is named.
- Evidence: probe (4): withdrawn-root build, reqwidths give ADVANCED 657-746, HELP 754-815, frame 841 > 720.
- Ledger: related to APP-17 (sweep 2026-09-03, built)
- Suggested fix: lay the strip out with `grid` over several rows (or shorter labels, e.g. PROJECTS), and bind the canvas `<Configure>` to set each Line's wraplength to the canvas width minus padding.

### ui-comp-windows-5 - Settings says "Your drive was disconnected ... plug it back in" about a drive that is plugged in but not answering, or mounted in the wrong place
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/settings_window.py:1356-1361; compare tray.py:2478-2488 and tray.py:501 (`drive_absent_phrase`), drive_reminder.py:181 (`wedged_reminder`)
- What: `root_unfinished` is non-empty whenever `_root_absent` is set, which covers the ROOT_NOT_ANSWERING and ROOT_MISPLACED states as well as a pulled drive. The tray line, tooltip and balloon all go through `drive_absent_phrase(root_state)` (SYNC-2/SYNC-105) or `wedged_reminder`. This Settings line hard-codes "disconnected" and "plug it back in", and says "Your drive" rather than `site.drive_phrase()`.
- Failure scenario: an external SSD is wedged (plugged in, not answering) with 2 uploads owed. The tray line says "the drive is not answering" and the balloon says "Reconnect it or restart this computer", while the Settings window says "Your drive was disconnected ... plug it back in". SYNC-120 recorded that this sends the editor to check a cable that is fine.
- Evidence: app.py:2594-2601 (`drive_unfinished_summary` gated only on `_root_absent`); tray.py:2479-2484 comment on the not-answering/misplaced cases.
- Ledger: related to SYNC-2 / SYNC-105 / SYNC-120 (Settings surface missed)
- Suggested fix: build the sentence from `tray_mod.drive_absent_phrase(snap.get("root_state"))` and the site drive phrase, as `_sync_line` does.

### ui-comp-windows-6 - The local-stop release is "Clear the sync stop on this computer" in the tray but "START SYNCING AGAIN" in Settings, the label UX-19 retired
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/settings_window.py:1410-1412; tray.py:3130-3138 (`halt_release_label`), tray.py:2069-2073 (halt confirm body quotes the tray label)
- What: UX-19 renamed the tray row after its cause because "Start syncing again" is false while a pause is also set: clicking it leaves the computer not syncing. The Settings button that calls the same `action_release_halt` still carries the old effect-named label, and ui_copy has no route constant for it.
- Failure scenario: a computer with both a local stop and a pause. The editor presses START SYNCING AGAIN in Settings and nothing starts syncing (the pause still holds). The STOP ALL SYNCING confirm told them to look for "Clear the sync stop on this computer", which is not what Settings calls it.
- Evidence: code read, both labels quoted above.
- Ledger: related to UX-19 (sweep 2026-09-03; the tray half was fixed)
- Suggested fix: use `tray_mod.halt_release_label(guard)` (minus the arrow) for the Settings button, and add it to ui_copy's ROUTE_ROWS.

### ui-comp-windows-7 - The licence refusal in the tooltip is cut before its action, and inside Settings it tells the reader to open Settings
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/tray.py:4234 (`f"CCSync: {blocked['detail']}"[:127]`); settings_window.py:218-234 (`_licence_advisory`); eula.py:425-434
- What: (a) The tooltip takes the head of the blocked sentence with a hard slice, which is the pattern APP-4 removed from balloons (fit_toast keeps the tail). The licence sentences are 129 and 149 characters, so the "updated" variant loses the whole route. (b) `_licence_advisory` exists to strip the old "setup wizard" sentence. Since APP-9/comp-app-3 no eula sentence contains that phrase, so the Settings line now reads "... Open Tray > Settings > READ AND ACCEPT THE LICENCE. Nothing syncs until it is accepted." directly above that button, inside that window.
- Failure scenario: after a EULA bump the tooltip reads "CCSync: The CC Sync licence agreement has been updated (version 1.1; this computer accepted 1.0). Open Tray > Settings > READ A". In Settings the editor is sent to the window they are already in.
- Evidence: probe (2): lengths 129 and 149 and the sliced strings; `_licence_advisory` output quoted above.
- Ledger: new
- Suggested fix: run tooltip text through a tail-keeping fit (tray_native.fit_toast with limit 127). In `_licence_advisory`, drop the sentence that starts "Open " instead of the dead "setup wizard" filter.

### ui-comp-windows-8 - The fixer popup's destination combobox is 52 characters wide, so it hides the default destination's last folder
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/popup.py:1160-1161 (`ttk.Combobox(..., width=52)`); fixer.py:454 (`list_destination_dirs` returns project-prefixed relative paths)
- What: every option is prefixed with the project path, and the ttk popdown list is the combobox's width. So both the field and the dropdown show only about the first 52 characters, and the distinguishing tail is cut off.
- Failure scenario: for project "Projects/2026/FF5/Civil Defence", the default video destination is "Projects/2026/FF5/Civil Defence/B-roll/Editor Added/ruskin" (58 characters), which shows as ".../Editor Added/" with the editor's own folder cut. Deeper existing folders (".../Footage/Interviews/Day 3/A-cam") all look alike in the dropdown. The editor picks a folder by guesswork and FIX ALL files the media there.
- Evidence: probe (5): 58/45/43-character defaults for a real-shaped prefix.
- Ledger: new
- Suggested fix: show paths relative to the row's `effective_prefix` (the prefix is the same for every option), or widen the combobox to the longest option up to a screen-width cap.

### ui-comp-windows-9 - The fixer popup's width is unbounded: file paths never wrap, and the right-aligned FIX ALL bar goes off-screen for a long path
- Severity: low
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/popup.py:1148-1152 (path Labels without wraplength), popup.py:1003 (`btn_bar ... sticky="e"`), popup.py:1170-1186 (height capped at 80% of the screen; width set to reqwidth with no cap)
- What: the build caps the window's height and not its width. Each row's clip name (bold 10pt) and full path (8pt) are unwrapped Labels, so the widest path sets the window width, and the button bar is pinned to the right edge of that width.
- Failure scenario: a clip on a deeply nested card dump (about 200+ characters of path) on a 1,366 px laptop. The dialog opens wider than the screen and FIX ALL / SKIP / LEAVE THIS FOLDER ALONE are past the right edge. The header text wraps at 620 px, so the screen looks normal apart from the missing buttons.
- Evidence: code read; not measured with a real long path.
- Ledger: new
- Suggested fix: cap the width at a fraction of `winfo_screenwidth()` like the height, and give the path Label a wraplength (or middle-ellipsise it).

### ui-comp-windows-10 - Fleet-jobs toggles: re-enabling omits "takes effect at the next start", and the kind sentence is ungrammatical
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/settings_window.py:1099-1106, settings_window.py:1196-1200
- What: the section's own comment says every jobs_* key needs a restart. Unticking says so, but ticking "Let the fleet use this computer" back on says only "This computer will take work for the fleet again." The per-kind balloon interpolates `_kind_label(kind).lower()` into "This computer will no longer take transcribe audio (uses the graphics card) for the fleet".
- Failure scenario: an editor re-enables fleet work and expects it now. It starts only after a restart, and nothing on screen says so apart from the generic "settings above were changed" line.
- Evidence: code read.
- Ledger: new
- Suggested fix: append "Takes effect the next time CCSync starts." to the re-enable sentence, and word the kind balloon as "no longer do this for the fleet: <label>".

### ui-comp-windows-11 - Muted text fails contrast, and no themed button shows keyboard focus
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/theme.py:23 (MUTED #6f6f7a), theme.py:19 (RED_DIM), theme.py:430-452 (`neon_button`: `bd=0, highlightthickness=0`); popup.py:2393-2453 (confirm_dialog: no Return/Escape binding, no initial focus)
- What: MUTED on BG is 3.98:1, below the 4.5:1 AA floor for small text. It carries the 8pt file paths in the fixer popup, every secondary Settings line, the jump strip and every non-primary button (CANCEL, SKIP FOR NOW). RED_DIM, used for the popup's "dest:" label, is 1.86:1. Every neon_button turns off the focus highlight, so Tab moves focus invisibly. confirm_dialog and notice_dialog bind neither Return nor Escape and focus nothing, so a keyboard user cannot answer them at all. The sign-in dialog and the typed confirm do bind keys.
- Failure scenario: on a bright office screen the file path (the one fact that tells the editor which clip is outside the tree) is dim grey 8pt on near-black. A keyboard-only user cannot tell which button Space will press.
- Evidence: probe (6) contrast ratios; code read.
- Ledger: new
- Suggested fix: lift MUTED to about #8a8a96 (at least 4.5:1), give neon_button `highlightthickness=1, highlightcolor=RED`, and bind `<Escape>` to cancel on confirm/notice (leave Return unbound on the destructive ones).

## Coverage note
The progress windows in popup.py (ProgressWindow, WorkProgressWindow) and the macOS tray_native menu delegate were only skimmed. bug-comp-ui covers the lock/lifecycle side of those. DPI: nothing in the companion calls SetProcessDpiAwareness, so on a scaled Windows display Tk windows and the tray icon are probably bitmap-stretched (blurry) rather than clipped. Not verified in a frozen build. The sign-in dialog's 15 s freeze and raw urllib error are still present in code but are recorded as sweep APP-11 (2026-09-03), so they are not re-reported. On macOS, notifications go through osascript without fit_toast, so a long safety-latch balloon is truncated at its head by Notification Center rather than keeping the action tail (APP-4). Plausible, not checked on a Mac.

## OUT OF TERRITORY
- companion/src/ccsync_companion/app.py:7420: the folders_unfiltered blocked sentence reads "1 project are not sharing yet"; the verb does not agree after the count() plural fix. The tray line, Settings and the dashboard grid all show it.
- companion/src/ccsync_companion/app.py:3938, 10142, 10196, 10297: confirm_dialog titles are raw strings ("STOP INDEXING THIS MUSIC BATCH", "Share these LUTs with the team?") rather than site_mod.notify_title, so those windows lack the brand prefix UX-4 gave every other dialog.
- companion/src/ccsync_companion/ytdl_browser_login.py:560-600: Outcome failure messages are lower-case fragments ("the browser was closed before the sign-in finished - nothing saved") that tray._youtube_sign_in shows verbatim as a balloon, with no next action for the closed-window case.
