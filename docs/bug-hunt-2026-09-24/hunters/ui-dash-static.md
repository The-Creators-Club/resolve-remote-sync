# ui-dash-static - dashboard/static JS + CSS + service worker + manifest (Wave 3, UI)
Files read (approximate coverage): dashboard/static/htmx_errors.js (all), confirms.js (all), pwa.js (all), sw.js (all), manifest.webmanifest (all), tab_memory.js (all), copy_value.js (all), dashboard_update.js (all), site_settings.js (~70%: AI providers, history, save/import), assignments.js (~70%: cell writes, column runs, copy-plan), setup.js (skimmed error paths), style.css (tokens, banners, focus, toasts, stale banner, chip sheet, contrast-relevant rules), mobile.css (chip sheet / coarse pointer, admin block skimmed). Templates read alongside: base.html, partials/chip_sheet.html, admin_packages.html + partial, admin_dashboard_update.html, admin_jobs.html, fleet_halt.html, notices.html (swap modes), offline.html, sidebar/project_detail toggle markup. htmx.min.js 1.9.12 read at the swap / afterSwap code path.
Tests/probes run: jsdom 24 installed in the session scratchpad (not the repo) and a node http server serving the REAL htmx.min.js 1.9.12 + htmx_errors.js + base.html's inline script: (a) a write in an outerHTML-swapped panel that answers with an `.error-banner`, (b) the same with an innerHTML swap as a control, (c) a 409 from an hx-post. WCAG contrast computed in node for the palette tokens. No repo test suites run.

## Findings

### ui-dash-static-1 - the "refusal moves next to its button" handler never fires for the five panels that swap outerHTML
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/static/htmx_errors.js:219-243 (`root = detail.target`); the same assumption in the chip `focusable()` pass at htmx_errors.js:167-170
- What: in htmx 1.9.12 `htmx:afterSwap`'s `detail.target` is the ORIGINAL target, and an outerHTML swap has already removed that node from the document (swapOuterHTML ends with `parent.removeChild(target)`; afterSwap is fired on the new elements with the old responseInfo). The mover searches the detached old panel for `.error-banner`, finds nothing (or moves a banner inside the detached tree and scrolls a detached node), and the new panel's refusal stays at the top. Every DUI-6 panel except the fleet grid swaps outerHTML: admin_jobs, admin_packages, admin_report_tokens, admin_users, fleet_halt (and notices' [ DISMISS ]). The existing node tests (tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py:408-411, tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py:463-465) fabricate `detail.target` as the NEW panel, which htmx never sends for outerHTML, so they pass against a handler that does not work in a browser. The same stale-target bug means chips swapped in by an outerHTML panel never get `tabindex="0"`, so keyboard users cannot reach their explanation sheet.
- Failure scenario: admin clicks [ DELETE ] on the fortieth row of Packages (or [ SET ] on a user's password, or a jobs [ CANCEL ]); the server answers 200 with "▲ refused: ..." in `.error-banner`; the banner renders two screens above the viewport and the admin sees nothing happen, which is exactly the DUI-6 symptom the file exists to fix.
- Evidence: jsdom probe with real htmx 1.9.12: outerHTML case printed `afterSwap detail.target connected= false evt.target connected= true`, `banner moved beside form: false`, `chip tabindex after swap: null`; innerHTML control printed `banner moved beside form: true`.
- Ledger: regression of CR-150 (DUI-6), CR-243g and CR-259f (each fix and its test built on the same wrong assumption)
- Suggested fix: resolve the live root as `evt.target` (the settled new element) or `detail.elt`/`document.getElementById(oldTarget.id)` when `detail.target.isConnected` is false, and change the two node tests to drive a real htmx outerHTML swap (jsdom) instead of a hand-built detail.

### ui-dash-static-2 - every 4xx refusal is reported as "THIS PAGE HAS STOPPED UPDATING", the server's reason is thrown away, and a signed-in 403 is called an ended session
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/static/htmx_errors.js:62-79 (and the checkbox left flipped: templates/partials/sidebar.html:21, templates/partials/project_detail.html:53-99)
- What: htmx 1.9 does not swap a >=400 response, and the only handler treats any responseError as an outage: it paints the red fixed "Nothing below is current ... The server answered 409. Reload the page to try again." banner and never reads `xhr.responseText`, which for these routes is a FastAPI `{"detail": ...}` carrying the actual next action. 401 and 403 both say "Your session has ended", but the routes answer `403 if user else 401`, i.e. 403 means SIGNED IN but not allowed. The banner is then removed by the next successful poll anywhere on the page (`htmx:afterRequest` -> clear()), so the misleading message also vanishes within 15-60 s, and the control stays in the state the browser flipped it to.
- Failure scenario: a stale tab ticks a project for a wired machine: `POST /partials/selection/.../toggle` answers 409 "every computer on this account is wired to the server ... projects cannot be ticked for them". The editor sees the checkbox ticked, a red bar claiming the dashboard is unreachable and telling them to reload, and 30 s later the bar disappears while the checkbox still shows ticked until the sidebar poll repaints it. The real reason is shown nowhere. Same for a non-admin whose click earns a 403: told their session ended, they sign in again and get the same result.
- Evidence: jsdom probe: a 409 hx-post produced banner text "THIS PAGE HAS STOPPED UPDATING (last update 1 seconds ago). Nothing below is current. The server answered 409. Reload the page to try again." ui.py:1370-1412 (403/404/409 with detail on the toggle route).
- Ledger: new (DUI-2 in CR-150 added the handler; no hunt has recorded the 4xx case)
- Suggested fix: split 4xx from 5xx/sendError: for 400-499 (not 401) show the parsed `detail` as a refusal beside the element (`detail.elt`) rather than the stale banner, and word 403 as "you are not allowed to do that"; re-sync the triggering checkbox (`elt.checked = !elt.checked`) or re-fetch its panel.

### ui-dash-static-3 - Settings [ UNDO ] names yesterday's change after an in-page save, then undoes the save just made
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/static/site_settings.js:737-771 (loadSiteHistory runs once at DOMContentLoaded) and :790-797 (the save handler never reloads the history); server: dashboard/src/ccsync_dashboard/setup_routes.py:418-443
- What: the history list and the undo button's `latest` are captured once at page load. A save (and the CLI-provider checkbox, which writes through the same PUT /api/v1/admin/site) adds a newer history entry without the page refetching, so the undo confirm keeps quoting the old entry while `undo-last-change` always reverts `entries[0]`, the newest one. The "saved" line is also never cleared, so after a later failed save the page shows "saved" and "▲ could not save" together.
- Failure scenario: Alex opens Settings, sees "save by alex at 2026-09-20 ... (1 setting)", changes the drive letter, clicks SAVE ("saved"), notices the old entry and clicks [ UNDO ] meaning to revert the 09-20 change. The confirm asks "Put back the 1 setting changed by alex at 2026-09-20 ...?"; OK reverts the drive letter he just saved, and the 09-20 change is untouched.
- Evidence: read both sides; setup_routes.py:431-435 takes `entries[0]`, the JS confirm uses the closure's `latest` from the page-load fetch.
- Ledger: new
- Suggested fix: call `loadSiteHistory()` after every successful save / flag change, clear `settings-saved` on input and on error, and send the history entry id the admin confirmed so the server refuses if it is no longer the newest.

### ui-dash-static-4 - a refused dashboard update or rollback flashes its reason and then erases it
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/static/dashboard_update.js:157-160 (runUpdate catch) and :62-83 (reloadPanel replaces the whole panel, `#dashupd-progress` included)
- What: when `POST .../apply` is refused (409 "an update is in progress", a signature or runtime refusal), the catch writes the reason into `#dashupd-progress` and immediately calls `reloadPanel()`, which fetches `/partials/admin/dashboard-update` with no error and replaces the panel's outerHTML. The freshly rendered progress line only knows `last_error` from a RUN, not a refusal of the request, so the message is gone within one round trip. The [ UPDATE NOW ] button is also never disabled, so a double click posts twice and the second refusal wipes the first run's progress line.
- Failure scenario: the owner clicks [ UPDATE NOW ] while a second admin's update is still running; the confirm is accepted, "an update is in progress (step: ...)" appears for a fraction of a second and the panel repaints looking exactly as before. Nothing says why nothing happened.
- Evidence: read; the partial (templates/partials/admin_dashboard_update.html) renders only `error` (never passed by reloadPanel), `in_progress` and `last_error` into that region.
- Ledger: new
- Suggested fix: after reloadPanel resolves, re-apply the refusal text (or pass it as `?error=` which the partial already renders), and disable the clicked button until the promise settles.

### ui-dash-static-5 - muted explanatory text is below AA contrast, and the phone drawer's close button is 1.8:1
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/static/style.css:12 (`--muted: #6f6f7a`), :441, :90, :488, :718; :184 (`.drawer-close { color: var(--red-dim) }`), :2005 (`.help-file-note`)
- What: `--muted` on `--bg` is 3.98:1, on `--panel` 3.82:1 and on `--field` 3.63:1, used at 11-12 px for the sentences that carry the next action (why-lines, stamps, row-detail labels, login labels). `--red-dim` (#7c1322) is 1.86:1 on the page background and is the text colour of the nav drawer's close control (both the header and the phone-only foot button) and of help-file notes.
- Failure scenario: on a phone outdoors the "close" of the nav drawer and the grey guidance lines are effectively unreadable; WCAG AA needs 4.5:1 for text this small.
- Evidence: node WCAG calculation: #6f6f7a/#0a0a0d 3.98, /#101014 3.82, /#16161c 3.63; #7c1322/#0a0a0d 1.86, /#101014 1.78. topbar.html:76 and :173 use `.drawer-close`.
- Ledger: new
- Suggested fix: raise `--muted` to about #8a8a96 (>= 4.6:1 on --panel) and give `.drawer-close` / `.help-file-note` `--muted` or `--red` instead of `--red-dim` (keep `--red-dim` for borders and decorative separators).

### ui-dash-static-6 - the offline page's [ RETRY ] throws away the page the reader was trying to open
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/templates/offline.html:15 with dashboard/static/sw.js:93-104
- What: the worker answers a failed navigation with the cached /offline document AT THE ORIGINAL URL, but its retry is `href="/"`, so retrying from /admin/packages or /projects/<slug> lands on the fleet page instead of re-requesting the page that failed.
- Failure scenario: an editor on a phone opens a project link from a notice email while the wifi drops; the offline page appears; they tap [ RETRY ] once the network is back and get the home page, with the link they followed gone from the address bar.
- Evidence: read; `respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)))` keeps the request URL.
- Ledger: new
- Suggested fix: make the retry `href=""` (reloads the current URL) or `onclick="location.reload()"` with the plain link as fallback.

### ui-dash-static-7 - the stale banner hides error toasts and the bottom of the page, and sits under the iPhone home indicator
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/static/style.css:1878-1887 (`.stale-banner`, z-index 60, no safe-area padding) vs :1163-1170 (`.toast-host` z-index 50, bottom 1rem)
- What: the fixed-bottom stale banner covers the bottom-right toast stack (the assignments page's persistent error toasts, which only go away when clicked) and the last ~2 lines of any page, and the body is given no bottom padding to compensate. Unlike `.chip-sheet` it does not add `var(--safe-b)`, so in the installed PWA with viewport-fit=cover its text runs under the gesture bar.
- Failure scenario: during a flaky connection on /admin/assignments a "could not tick X" error toast appears under the red banner and cannot be read or clicked away; on an iPhone the end of the banner sentence is under the home indicator.
- Evidence: read CSS stacking values; base.html sets viewport-fit=cover.
- Ledger: new
- Suggested fix: `padding-bottom: calc(0.5rem + var(--safe-b))`, lift `.toast-host` above it (or offset it by the banner height when `body[data-stale]`), and add `body[data-stale] { padding-bottom: 3rem }`.

### ui-dash-static-8 - [ COPY ] can stick on "[ COPIED ]" and gives no feedback when the clipboard API is absent
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/static/copy_value.js:29-33 and :44-50
- What: `flash()` saves `btn.textContent` as the label to restore; a second click inside the 2 s window saves "[ COPIED ]" as the original, so the button reads "[ COPIED ]" for good. On a non-secure origin (plain-http LAN access; pwa.js notes the dashboard can be http) `navigator.clipboard` is undefined, the value is only selected, and the button text does not change, so the admin cannot tell whether the one-time password was copied.
- Failure scenario: admin double-clicks [ COPY ] on a freshly minted password, then later sees "[ COPIED ]" still showing and trusts it; over http nothing visibly happens and the one-time secret panel is closed believing it was copied.
- Evidence: read.
- Ledger: new
- Suggested fix: store the idle label once in a data attribute, and on the fallback path flash "[ SELECTED - PRESS CTRL+C ]" (or try `document.execCommand("copy")` first).

### ui-dash-static-9 - the AI provider pin and the CLI-provider checkbox keep showing a choice the server refused
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/static/site_settings.js:117-126 (`ai-preference` change) and :131-145 (`ai-cli-enabled` change)
- What: both controls change on screen first and, on a failed PUT, only print an error line; neither puts the control back (contrast confirms.js, which restores the policy select, and assignments.js, which rolls a cell back). The select keeps displaying a pin that is not in force until the next full reload.
- Failure scenario: admin pins "OpenAI API", the PUT 422s ("no key saved"), the select still reads "4. OpenAI API" while "YouTube downloader will use: Claude Code" sits above it: two contradictory answers on one screen.
- Evidence: read; `renderAiProviders` would reset `pref.value` but is only called on success.
- Ledger: new
- Suggested fix: in each catch, call `loadAiProviders()` (which resets both controls from the server) after showing the error.

## Coverage note
Not covered: the rest of setup.js (first-run wizard flows), the bottom third of site_settings.js (import preview wording), mobile.css admin/fleet rules at 390 px beyond a skim (no rendered page was inspected in a browser), icons, cards_landing (WIP, see below). base.html's inline details-state keeper and the DUI-7 deep-link scroll use the same `evt.detail.target` as finding 1, but every current consumer (bins, sidebar, transfers, fleet grid, notices, fleet-halt load) swaps innerHTML, so they are latent, not live, today; any future outerHTML panel with `details[data-key]` or a deep-link target will inherit the finding-1 failure. pwa.js's visible-refresh (`target: el`) was checked against every polled element: none carries hx-target/hx-select, so it is correct today.

## OUT OF TERRITORY
- dashboard/templates/cards_landing.html (uncommitted working-tree change, not HEAD): references `/static/cards_landing.js`, which does not exist in dashboard/static; a 404 on /cards if shipped as is.
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py:408-411 and test_bug_hunt_2026_09_11b_dash_mounts_ui.py:463-465: the node harness hands afterSwap the new panel as `detail.target`, which real htmx 1.9.12 does not do for outerHTML; tests pass over a broken handler (see finding 1).
