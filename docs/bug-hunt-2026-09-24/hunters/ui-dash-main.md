# ui-dash-main - dashboard main pages (fleet, project, transfers, installer, login, offline, setup, help, cards landing) and their partials, plus ui.py rendering

Files read (approximate coverage): templates/base.html, fleet.html, project.html, project_setup.html, transfers.html, installer.html, login.html, offline.html, setup.html, help.html, cards_landing.html (HEAD and the uncommitted working copy); partials/topbar, sidebar, chip_sheet, fleet_grid, project_detail, my_queue, queue_section, fix_root, project_roots, project_roots_browse, notices, plan_changes, transfers, bins, missing_files, editor_switcher, stamp (all fully); ui.py `_render`, `page_fleet`, `_queue_machine`, `_as_qs`, `partial_toggle`, `page_project`, `_sidebar_context`, `_switcher_context`, plan-change undo, notices, `/offline`, `/sw.js`; static/pwa.js, htmx_errors.js, confirms.js, sw.js (first half), style.css phone block; app.py csrf_gate.
Tests/probes run:
- Real htmx 1.9.12 + static/htmx_errors.js + base.html's inline scripts in headless Chromium (Playwright), served from disk with stubbed responses: (a) sidebar tick with `hx-swap="outerHTML"`, (b) an outerHTML admin panel answering with an `.error-banner`, (c) a polled `innerHTML` container holding a text input and a select.
- Rendered `/`, `/project/<slug>`, `/transfers`, `/installer`, `/help`, `/setup` from a TestClient app (dashboard venv, seeded DB, two computers on one account) and loaded them at 390 px in Chromium, measuring elements past the right edge and taking full-page screenshots.

Note: the working tree gained uncommitted edits to base.html and cards_landing.html (a new `{% block head %}`, a rewritten picker, a missing `static/cards_landing.js`) while this hunt ran. The brief says HEAD is clean, so those edits are in-flight work and nothing below is about them.

## Findings

### ui-dash-main-1 - Ticking a project in the sidebar folds the whole project tree back up, and on a phone closes the sheet
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/sidebar.html:21-22 (hx-target="closest .projects" hx-swap="outerHTML"); dashboard/templates/base.html:76-86 (the details-preserve afterSwap handler)
- What: htmx 1.9.12 sets `evt.detail.target` in `htmx:afterSwap` to the ORIGINAL target. After an outerHTML swap that element has been removed from the document, so base.html's restore handler reapplies the saved open/closed state to the removed tree and none of it reaches the new one. The response is the whole sidebar partial, so a second `[ PROJECTS ]` sheet handle is also added beside the old one each time. The new `<nav popover>` also starts closed, so on a phone the sheet shuts on every tick.
- Failure scenario: an editor opens 2026 > FF5 in the rail (on the fleet page nothing is open by default) and ticks one project. The tree snaps shut, so ticking a second project means opening the groups again. On a phone the bottom sheet closes after every tick, and the aside gains an extra handle button per tick until the 30 s refresh.
- Evidence: Playwright probe with the real htmx and base.html's script: a group opened by hand reads `open: false` after the tick, and `.sheet-handle` count is 2. The htmx source shows `u.target=c` and then `ce(e,"htmx:afterSwap",u)` fired on each new element.
- Ledger: new
- Suggested fix: in the restore handler, walk `evt.target` (the new element the event fires on) rather than `evt.detail.target`, or key the saved state on a selector and look it up in `document`. Have the sidebar toggle return only the `<nav>` (or `hx-select=".projects"`) so the handle is not duplicated.

### ui-dash-main-2 - The DUI-6 "refusal next to the button" mover does nothing on the outerHTML panels it was written for
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/static/htmx_errors.js:225-256 (loaded on every page by base.html)
- What: this is the same htmx fact as finding 1. `root = detail.target` is the removed element after an outerHTML swap, so `root.querySelector(".error-banner")` searches the old DOM, finds nothing and returns. Every panel the comment names swaps outerHTML: admin_users, admin_packages, admin_jobs, admin_report_tokens. The test that covers it runs against a hand-written harness, not htmx itself.
- Failure scenario: an admin clicks `[ SET ]` on a password row far down the Users panel and it is refused. The banner renders at the top of the panel, about 2,000 px above the viewport, and nothing appears to happen: exactly the DUI-6 symptom.
- Evidence: Playwright probe with htmx 1.9.12: after an outerHTML response carrying `.error-banner`, the banner has no `form-error` class and is not next to the form, and the page stays scrolled at 2388 px.
- Ledger: regression of DUI-6 / CR-243g / CR-259f (FIXED entries whose fix never ran against real htmx)
- Suggested fix: look up the banner in the new content: the element the event fires on (`evt.target`), or `document.querySelector` scoped by the panel's id. Pin it with a test that loads the real htmx.min.js.

### ui-dash-main-3 - The project page's 10 s poll wipes what an admin is typing into MOVE and SHARE A FOLDER
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/templates/project.html:11-13 (`#project-detail`, every 10s, innerHTML); dashboard/templates/partials/project_detail.html:131-137 (share input), 154-184 (move form)
- What: both forms are inside the container the poll replaces every 10 s. The inputs have no id, no `hx-preserve`, and nothing pauses the poll while one has focus. Each refresh empties the text boxes, puts the destination `<select>` back to this project and drops focus.
- Failure scenario: an admin types `B-roll/A001_0512.braw`, picks a destination project and starts typing the folder. Within 10 s all three fields go blank and focus drops to the page body. Pressing MOVE now sends an empty path, and the server answers "type the file or folder to move". A long path pasted into SHARE A FOLDER disappears the same way.
- Evidence: Playwright probe, a polled innerHTML container with the same markup: after one poll, `value: ""`, the select is back to the first project, and focus is on BODY.
- Ledger: new
- Suggested fix: move the two forms out of the polled container. Alternatively, add a trigger filter that skips the beat while `document.activeElement` is inside `#project-detail` or a field in it is dirty.

### ui-dash-main-4 - The fix-root computer picker drops `?as=`, so an admin checking an editor's second computer lands back on their own queue
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/fix_root.html:18-21; dashboard/src/ccsync_dashboard/ui.py:620-640 (`_queue_machine`)
- What: the `[ LAST TO REPORT ]` and `[ <computer> ]` chips link to `/` and `/?machine=<m>`, without the `as=` the admin is viewing under. On the new page `_queue_editor` returns the admin. `_queue_machine` then drops the machine, because it is not one of the admin's own computers.
- Failure scenario: the owner picks leso in [ TICKING FOR ] and clicks `[ LESO-MACBOOK ]` to see where FIX ALL puts files on that laptop. The page reloads showing `[ SYNC QUEUE: ALEX ]` and the owner's own open Resolve project, with nothing saying the view changed. The per-computer view (dash-api-4's hand-off) is unreachable for anyone but the editor.
- Evidence: read the template hrefs, `_queue_editor` (it reads `as` only from the query) and `_queue_machine` (it rejects a name not in `machines_of(editor)`).
- Ledger: related to dash-api-4 (2026-09-11b hand-off)
- Suggested fix: build the hrefs with the current `as_qs` (`/?machine=..&as=..`) and keep `as` on the `[ LAST TO REPORT ]` link.

### ui-dash-main-5 - On a phone the fix-root computer chips run off the screen and cannot be reached
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/fix_root.html:16-24
- What: the chip row is a plain `div` of inline `<a class="chip">` with no wrap and no `.scroll-x`. A long hostname such as a Mac's `Leso-MacBook-Pro-2024.local` is pushed past the viewport and clipped, and the page does not scroll sideways to reveal it.
- Failure scenario: an editor with a MacBook and a desktop opens `/` on a phone. The second computer's chip ends at x=556 on a 390 px screen and cannot be tapped.
- Evidence: rendered `/` with two computers on one account, at 390 px in Chromium: `A.chip right=556 txt=[ Leso-MacBook-Pro-2024.local ]`, and the screenshot shows it cut at the edge.
- Ledger: new
- Suggested fix: give the row `display:flex; flex-wrap:wrap; gap` (or `.scroll-x`), as the other chip rows have.

### ui-dash-main-6 - The project-roots 30 s poll closes an open [ BROWSE ] folder picker and resets a changed select
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/templates/fleet.html:75 (every 30s, innerHTML); dashboard/templates/partials/project_roots.html:21-31, 35, 60
- What: this is the same mechanism as finding 3. The browse panel is swapped into `#roots-browse-mN`, inside the polled wrapper. Every 30 s the panel is emptied and every root `<select>` goes back to its stored value.
- Failure scenario: an admin clicks [ BROWSE ] and walks three folders deep under Projects/. On the next beat the browser vanishes and they start again from the top. An admin who picked a new root in the select but has not yet pressed [ SET ] sees it silently revert.
- Evidence: read the templates. The probe in finding 3 shows a polled innerHTML swap discards form state and injected content.
- Ledger: new
- Suggested fix: skip the poll while a `.roots-browse` is open or a root select has focus or a changed value. Alternatively, drop the poll and refresh after SET only.

### ui-dash-main-7 - [ UNDO ] on a TICKED row takes a project off computers with no confirm, unlike every other untick
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/plan_changes.html:47-50; dashboard/src/ccsync_dashboard/ui.py:1697-1760
- What: undoing a tick removes each placement the tick added. For a person-level tick that is every computer the person owns. The button has no `hx-confirm` and the row names only the slug (folder id). DASH-8 added a confirm naming the computers to every other untick in the product, because CR-49 was a mis-click untick.
- Failure scenario: two plan changes sit next to each other in the last hour. The owner means to undo the UNTICKED row and clicks the TICKED row's [ UNDO ] one line up. The project is unshared from all of that editor's computers in one click, with nothing asked and the confirmation banner naming only a folder id ("removed 2026-ff5-elections again for leso").
- Evidence: read the template (no hx-confirm) and `partial_plan_change_undo` (remove_selection for each `after` machine not in `before`).
- Ledger: related to DASH-8 / CR-49
- Suggested fix: add an `hx-confirm` on the undo of a `plan.tick` row naming the project label and the computers it comes off. Show `project.label` rather than the slug in the table and in the notice.

### ui-dash-main-8 - The sidebar's projects sheet shuts under a phone user every 30 s
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/templates/fleet.html:6-7 (and every page's `<aside hx-get="/partials/sidebar" every 30s innerHTML>`); dashboard/templates/partials/sidebar.html:74-76
- What: below 600 px the project rail is a `popover` sheet inside the aside, and the aside's innerHTML is replaced every 30 s. `pwa.js` only slows 2 s and 5 s polls, not this one. The replacement `<nav popover>` is a new closed element, and nothing records or restores the popover's open state or scroll position.
- Failure scenario: an editor on a phone opens [ PROJECTS ], scrolls to find a project and is reading the list. At the next 30 s beat the sheet vanishes and the page is back underneath. Scrolling a hundred-project tree to the right row can take longer than 30 s.
- Evidence: nothing in static/*.js or ui.py mentions `projects-sheet`, `popover` or `showPopover`. By the popover spec, removing an open popover hides it, and the element inserted in its place is closed. The finding-1 probe shows the swapped-in nav is a new element.
- Ledger: new
- Suggested fix: skip the sidebar poll while the sheet is open (trigger filter `[!document.querySelector('#projects-sheet:popover-open')]`), or reopen it after the swap in a document-level `htmx:afterSettle` listener.

### ui-dash-main-9 - [ UNTICK ] in the sync queue re-renders the panel as the person's view and drops the "safe to close" line
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/ui.py:1457-1459; dashboard/templates/partials/my_queue.html:43-48
- What: the queue's untick posts with no `?machine=`. `partial_toggle` then renders `my_queue.html` with `build_queue_view(conn, editor, machine=None)` and no `safe_to_close` in the context.
- Failure scenario: an editor viewing `/?machine=MacBook` unticks a project. For up to 10 s the panel shows the person-wide queue instead of that computer's, and the "Not yet: 3 files still uploading..." sentence disappears, which reads as "safe to close" until the next poll puts it back.
- Evidence: read `partial_toggle`'s last return and the template.
- Ledger: new
- Suggested fix: send `machine=` from the panel (as the poll does), and pass `safe_to_close` and `queue_machine` into the untick render.

### ui-dash-main-10 - "(s)" plurals survive on the fleet and transfers pages, against UX-10's own rule
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/fleet_grid.html:78, 80, 239, 271; dashboard/templates/partials/transfers.html:47, 65; dashboard/templates/partials/bins.html:4
- What: the comment at fleet_grid.html:43-45 records the rule that "(s)" is not a word and the count is known. The enforce-refusal banner ("SHARE REMOVAL(S) REFUSED", "folder(s)"), the sync-engine and moved-folder chip titles, the transfers queue ("N file(s)") and the bins header ("original(s)", "proxy file(s)") still use it.
- Failure scenario: cosmetic. The alarm banner an admin most needs to read carries the wording the rule was written to remove.
- Evidence: grep of the templates.
- Ledger: related to UX-10 (2026-09-03)
- Suggested fix: use the same `{{ "s" if n != 1 }}` pattern as the surrounding lines.

## Coverage note
Not covered: the new cards landing picker (uncommitted, in flight), notice_checks.html and collector_health.html beyond their render on `/`, setup.js and the wizard flows, dark/light theme contrast (the product is dark-only), desktop layouts wider than 390 px beyond reading the CSS, and keyboard focus order in the drawer. No em dashes were found in any template in the territory or in ui.py strings. `missing-{{ loop.index }}` with `hx-preserve` (project_detail.html:317) keys a preserved list by row position. If the editor order ever changes between polls, the list will sit under the wrong row. I did not verify the order is unstable, so it is not reported.

## OUT OF TERRITORY
- dashboard/templates/cards_landing.html (HEAD) line 116-119: the footer says "Closing one is an admin act", while `[ CLOSE ]` is drawn for non-admins by `ep.may_close`. The in-flight rewrite changes this text.
- dashboard/templates/cards_landing.html (working copy) line 5: references `/static/cards_landing.js`, which does not exist in the tree yet. The search box, order and year chips are dead until it lands.
- dashboard/templates/cards_landing.html: the forms send `csrf_token`, but `auth.CSRF_FIELD` is `csrf`. That is harmless only because `/cards/` is origin-checked, not token-checked.
