# Verifier med-17 (2026-09-25)

Judged against HEAD (63d4290) via `git show HEAD:<path>` / `git archive HEAD`.

## ui-music-ytdl-web-1 - DOWNGRADE (low)

Real: `.search-bar` in HEAD `ytdl/web/static/style.css:395` is `display:flex` with no `flex-wrap`, and the stylesheet has no `@media` rule at all, so on a phone the row (six non-shrinking controls) runs past the viewport. But /ytdl/ is a desktop research tool: an editor picks a project, quality and on-this-computer download switch for footage that lands in their editing tree. The row fits at any desktop or half-screen width (hunter's own measurement: 847 px). Nothing breaks, nothing is lost, and the controls are reachable by scrolling sideways. Layout polish, low.

Evidence: HEAD style.css (grep `@media` -> none; `.search-bar` block), HEAD index.html:81-119.

## ui-music-ytdl-web-2 - CONFIRMED (medium)

HEAD `ytdl/web/static/app.js` `card()`: the checkbox has `e.stopPropagation()`, the title `<a target=_blank>` has no handler, and `n.onclick = () => { if (!v.duplicate) toggle(v, !v.selected); }`. A click on the title bubbles to the card and POSTs `select` with the opposite state. `toggle` is optimistic and persisted server-side, and DOWNLOAD takes what the database says, so previewing a clip silently changes what gets downloaded. Medium is right: it quietly corrupts the editor's selection during exactly the review workflow the page exists for.

Evidence: HEAD app.js ~2011-2019 and `toggle()` right below.

## ui-music-ytdl-web-3 - DOWNGRADE (low)

The mechanism holds: `init` awaits `loadAttestation()` (which disables #go/#golinks when not accepted), then `loadProjects()` unconditionally sets both `disabled = false` when any project exists; `setAttested(true)` re-enables them over the "no projects" disable; and `el.dataset.title` is never set, so the tooltip is stale after accepting. But the SERVER is the gate (the code says so in `loadAttestation`), the attestation notice stays on screen (`#attest` is not hidden while unaccepted), and the outcome of pressing SEARCH is a refusal toast that carries its reason. No download happens that should not, nothing is lost. The no-projects path ends in a refusal too (the placeholder option's text becomes the slug). A client-side lock that leaks into an explained server refusal is low.

Evidence: HEAD app.js 747-753 (loadProjects), 3080-3108 (loadAttestation/setAttested), 3173-3181 (init order), 2148/2222 (runSearch disable/finally).

## ui-music-ytdl-web-4 - CONFIRMED (medium)

HEAD `music/web/static/style.css:707-714`: `.pane { overflow:hidden; height:0 }`, `.pane.open { height:150px }`, with a comment assuming fixed content. `openPane` (HEAD app.js 206-281) builds wave (64) + bar (8+28) + padding (20) + borders, then adds a `.wavenote` caption (every fleet-ingested track without peaks, a two-line sentence) and the `.rmsg` Resolve status/error line, and `.pacts` has `flex-wrap: wrap`. That sum passes 150 px on desktop with a caption and an error, so the one line explaining why Resolve did not answer is clipped with no scroll; on the 900 px layout the wrapped buttons are clipped too. Medium: an error message and action buttons are invisible.

Evidence: HEAD style.css 700-760, 544 (`.wavenote` 11px + margin); HEAD app.js 206-281 and 360-370.

## ui-music-ytdl-web-5 - CONFIRMED (medium)

HEAD music app.js: axis `onchange`, `#sort`, `#includeUnknown`, `#applyRange`, and the `[ include them ]` button that `noteUnknownHidden` adds after a search all call `loadTracks()` (the browse route) and never consult `#q`; only `selectFacet` and `#clear` empty `#q`. `runSearch` itself calls `noteUnknownHidden`, so the "include them" offer on a search result replaces the ranked results with an unranked browse list under "All tracks" while the box still shows the query. MUSIC-4 (KNOWN_BUGS ~12864) fixed only the search-carries-filters direction. Medium: the page's primary action is silently undone.

Evidence: HEAD app.js 546-587 (loadTracks/runSearch), 611-625 (noteUnknownHidden), 694-700, 905-931.

## ui-comp-windows-1 - DOWNGRADE (low)

Partly refuted. The body Label in `confirm_dialog`/`notice_dialog` (HEAD popup.py ~2419/2477) has no `wraplength`, and the WIRED TO THE SERVER body (settings_window.py ~353) is one 330-character line. But the claim that the buttons end up off-screen does not hold: Tk clamps a toplevel to `wm maxsize`, which defaults to the screen size. Probe (scratch tkprobe.py, a replica of the dialog with system Tk): requested width 2289, actual window width 516 = maxsize, the OK button's right edge at 506 inside the window; the Label is what gets clipped. So the real defect is a screen-wide dialog whose sentence is cut off before its end (on the wired confirm, "this is not the setting you want" is lost), with CANCEL and OK reachable. Worth a `wraplength`, but low.

Evidence: HEAD popup.py 2393-2455, 2456-2485; HEAD settings_window.py 345-365; probe output `screen 512 maxsize (516, 1029) reqw 2289 w 516`, `label req 2253 label w 480 b2 rootx 374 b2 w 132`.

## ui-comp-windows-2 - CONFIRMED (medium)

HEAD settings_window.py tags `(BLOCKING, tray_mod._blocked_line)` at the producer level, and `_SEVERITY_STYLE[BLOCKING] = "warning"`. `tray._blocked_line` returns the no_selection detail (without the warning glyph, live-5), and `app.blocked_report` does produce reason `no_selection` with "No projects are ticked for this computer". Probe from the companion venv against HEAD source: `_lane_advisories({'blocked':{'reason':'no_selection',...}})` -> `[('blocking', 'No projects are ticked for this computer')]`, `rank_advisories` -> `Line(..., style='warning')`, and `_help_first` then moves HELP to the top. This breaks the owner rule that nothing ticked is never an error or warning on any surface. Medium stands (owner rule, every new computer sees it).

Evidence: HEAD settings_window.py 90-96, 163-215, 1617-1632; HEAD tray.py 170, 3070-3092; HEAD app.py 7281-7400; probe run with PYTHONPATH at `git archive HEAD companion/src`.

## ui-comp-windows-3 - DOWNGRADE (low)

Real that `_show_licence_dialog` (HEAD app.py 6199-6240) passes `eula_mod.bundled_text()` verbatim and `popup.licence_dialog` inserts it into the Text widget, so the leading HTML comment and raw Markdown are shown. But the finding's harm is not the comment: the VISIBLE body of HEAD assets/EULA.md itself says "**Version 1.0 - draft of 2026-08-17. DRAFT FOR COUNSEL.**" (line 19), names **Cablewrap Creative** as the party (line 21, 196) and carries inline `TODO(legal)` markers (185, 196). Stripping comments, the suggested fix, would leave all of that on screen. The EULA being a draft for counsel is a documented, owner-known state (CLAUDE.md, "Legal paperwork lives in docs/legal/ and is DRAFT FOR COUNSEL"), not a rendering defect. What remains specific to this finding is cosmetic (raw Markdown and one comment block). Note for the owner, separately: the body names Cablewrap Creative, a brand the owner has retired; that is a content fix to the EULA, not to the dialog.

Evidence: HEAD assets/EULA.md lines 1-21, 185, 196; HEAD eula.py 100-111; HEAD popup.py 2569-2627.
