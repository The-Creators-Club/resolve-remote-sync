# Dashboard web UI: every page, template, chip, button and toast (DUI)

## Summary
This is the most carefully written UI in the repo: every dangerous control on
the fleet grid, the packages table and the users panel now carries a confirm
that names the consequence, empty states say what to do next, "not checked" is
never rendered as "OK", and the phone layer is a real design rather than a
media query. The remaining usability debt is not missing copy, it is **copy in
the wrong place**: an error always renders at the TOP of a panel whose buttons
are at the bottom, every chip's explanation lives in a `title=` that a phone
cannot show, and two one-time credentials are painted into panels that a 30 s /
60 s htmx poll erases underneath the admin. The resilience posture has one hole
that dwarfs the rest: **there is no `htmx:responseError` handler anywhere and
the only freshness stamp on the page is in the topbar, which is never
re-rendered** - so a dashboard whose API is 500ing, or whose NAS has gone, keeps
painting a green fleet with "updated 4s ago" beside it, indefinitely. The
cheapest high-value win is a six-line global htmx error handler plus moving the
`updated` stamp into a polled fragment; the second cheapest is stopping the
polls from eating the credentials.

## Findings

### DUI-1: A one-time password and a one-time fleet token are rendered into panels that a poll erases 30 s later
- **Lens:** both
- **Who:** admin / owner
- **Where:** `dashboard/src/ccsync_dashboard/ui.py:1913-1926`, `dashboard/templates/partials/admin_users.html:6`, `dashboard/templates/admin_users.html:9` (`every 30s`), `dashboard/templates/partials/admin_report_tokens.html:18-30`, `dashboard/templates/admin_users.html:23` (`every 60s`). Screen: Settings -> USERS.
- **Today:** Creating a local account with a blank password mints one and returns it through the **`error`** context key: `error = f"{username}: created with a generated password: {generated}"` (`ui.py:1926`), which the panel paints as `<div class="banner">▲ {{ error }}</div>` - the success case wears the warning triangle and shares a channel with "does not look like an OpenSSH public key". The report-token panel does better copy ("copy it now, it is shown once and never stored in a readable form") but sits inside `<div hx-get="/partials/admin/report-tokens" hx-trigger="load, every 60s ...">`, and the users panel inside a 30 s twin. The next poll swaps the wrapper's innerHTML and the credential is gone for good; there is no [ COPY ] button, and no other value the admin must transcribe (sha256, device id, token) has one either. Recovery for the password is "set a new one"; for the token it is "mint another and revoke the first".
- **Proposed:** (a) render a minted secret in a `<div id="minted-secret" hx-preserve="true">` so htmx carries it across the swap, or suppress the poll while it is on screen (`hx-trigger="every 60s [!document.getElementById('minted-secret')]"`); (b) give it its own `notice` slot, not `error`, with a green chip and no ▲; (c) add a `[ COPY ]` button (`navigator.clipboard.writeText`, falling back to select-on-click) beside every one-shot value; (d) copy: `[ NEW PASSWORD FOR JSMITH ] Copy it now. It is shown once and this panel refreshes by itself.`
- **Effort:** S   **Value:** critical   **Confidence:** high
- **Related:** none in 08-28; UX-22 covered revocation, not minting.

### DUI-2: Nothing handles an htmx error, and the one freshness indicator is in the never-refreshed topbar
- **Lens:** resilience
- **Who:** editor / admin
- **Where:** `dashboard/templates/base.html:78-83` (topbar included once, no `hx-trigger`), `dashboard/templates/partials/topbar.html:191` (`updated {{ view.generated_at | ago }}`), `dashboard/static/pwa.js` (no error listener), `dashboard/static/confirms.js` (none either), every polled fragment in `fleet.html:22-71`.
- **Today:** htmx 1.9.12 does not swap on a non-2xx and there is no `htmx:responseError` / `htmx:sendError` listener in the repo, so a partial that 500s (`app.py`'s handler answers `{"detail":"internal error"}`), a container restart, a NAS reboot or a wifi drop simply leaves the last good render on screen for ever. The topbar is a plain `{% include %}` rendered once per full page load, so `updated 4s ago` is frozen at load time and never contradicts it. An admin who left the fleet page open sees green dots, live-looking lane chips and "updated 4s ago" while the dashboard has been unreachable for an hour. `▲ SYNCTHING UNREACHABLE` (`topbar.html:182`) is inside the same frozen include.
- **Proposed:** one small script in `base.html`: on `htmx:responseError`/`htmx:sendError`/`htmx:timeout`, stamp `document.body.dataset.stale = Date.now()` and paint a fixed banner `▲ THIS PAGE HAS STOPPED UPDATING (last update 4 minutes ago). Nothing below is current.`; clear it on the next `htmx:afterSwap`. Separately, move the stamp+`SYNCTHING UNREACHABLE` pair into a small `/partials/stamp` fragment polled on the page's own cadence, or have each polled partial emit `HX-Trigger: {"ccsync:fresh": "<iso>"}` and let the script rewrite the stamp client-side.
- **Effort:** S   **Value:** critical   **Confidence:** high
- **Related:** `sw.js` is correct here (pass-through for `/partials/`); this is purely the client's silence.

### DUI-3: Every chip explains itself only in `title=`, which a phone cannot show, and up to ~30 can stack in one cell
- **Lens:** usability
- **Who:** admin / owner
- **Where:** `dashboard/templates/partials/fleet_grid.html:171-319` (40 `class="chip` occurrences in the LANES cell alone), `dashboard/static/mobile.css` (no `[title]` rule anywhere), `dashboard/templates/partials/fleet_grid.html:136-140` (comment: "'is anything red' is the whole reason to open this page on a phone").
- **Today:** the fleet grid's LANES cell can render, in one row: `[ RELAYED: 2 ]  [ ORPHANS: 3 ]  [ PROXY DOWNLOAD STOPPED ]  [ SYNC ENGINE DOWN 2d ago, 4 RESTARTS FAILED ]  [ CLOCK 3m AHEAD ]  [ CRASHES: 2 ]  [ UPDATE FAILED x8 ]  [ UNFILTERED FOLDERS: 1 ]  [ CONFLICTS: 4 ]  [ 12 CLIPS OUTSIDE THE TREE ]  [ 3 STRAY PROJECT DIRS ]  [ DISK 94% ]  [ STALLED B, KILLED ]  [ WON'T UPLOAD: 40 ]  [ TRASH: 8.2 GB ]  [ GPU 24G ]  [ WHISPER ]  [ 91 NEED PROXIES ]` - eighteen labels, each of whose cause and next action is only in the tooltip. On a touch device there is no hover, so the entire explanatory layer of the product's most important page is unreachable; the same is true of every `title` on the dots, the SYNCED column head, and the assignments grid. There is also no legend anywhere for the green/amber/red dot, and no ordering rule the reader can see (the `why-line` at the top is the one thing that is prose).
- **Proposed:** (a) make a chip tappable on a coarse pointer: `.chip[title]` gets `cursor:pointer` and a delegated click handler that renders its `title` into a small `.chip-detail` line below the cell (no library, ~15 lines, and it also serves keyboard users); (b) cap the cell at the five highest-severity chips with `[ +7 MORE ]` expanding the rest, ordering red > amber > neutral (the template's own comment already claims the safety latches "outrank every transport diagnostic beside them" but nothing enforces it when both are present); (c) one collapsed `WHAT THESE MEAN` legend under the grid, in the shape `notice_checks.html` already uses.
- **Effort:** M   **Value:** high   **Confidence:** high

### DUI-4: No loading feedback on any htmx control, including one that blocks for two minutes
- **Lens:** both
- **Who:** admin / owner
- **Where:** no `hx-indicator` and no `.htmx-request` rule exist in `dashboard/templates/` or `dashboard/static/style.css` (grepped); `ui.py:1879-1885` (`_create_or_update_editor_sync` docstring: "blocks on time.sleep() for up to ~2 minutes"); also `/partials/admin/alerts/test` (SMTP), `/partials/admin/feed/publish`, `/partials/project/{slug}/move`, `/partials/admin/recovery/restore`.
- **Today:** the admin clicks [ CREATE ] on Settings -> USERS and the page does nothing at all for up to two minutes: no spinner, no disabled button, no text. htmx adds `.htmx-request` to the element but no stylesheet reacts to it. The predictable user response is to click again, or reload, or conclude it is broken. `assignments.js` and `setup.js` do disable their own buttons; the ~40 htmx forms do not.
- **Proposed:** three CSS rules in `style.css` (`.htmx-request .btn, .btn.htmx-request { opacity:.5; pointer-events:none }`, plus a `::after` ellipsis that animates), and `hx-disabled-elt="this"` on the slow forms. For the two known multi-minute actions add explicit copy in the button's own slot: `[ CREATE ]` -> while running, `[ CREATING THE ACCOUNT ON THE NAS... ]` with the note "this can take up to two minutes".
- **Effort:** S   **Value:** high   **Confidence:** high

### DUI-5: [ NONE ] clears a whole computer's plan with no confirmation, no progress and no per-project failure report
- **Lens:** usability
- **Who:** admin / owner
- **Where:** `dashboard/static/assignments.js:197-258` (`runColumn`), `dashboard/templates/admin_assignments.html:74-75`; screen: Settings -> ASSIGNMENTS.
- **Today:** `confirmCapacity` is called only when `wanted` is true, so `[ NONE ]` fires straight into a sequential loop of DELETEs over every ticked project for that computer, while unticking **one** project in the sidebar demands "This removes X from jsmith's 2 computers (DESKTOP, LAPTOP). Their copies stay on disk...". During the run there is no progress at all (only individual checkbox pulses inside a sideways-scrolling grid); navigating away mid-run leaves the column half applied. On failure the toast is `"3 of 40 change(s) failed for jsmith on DESKTOP"` - it never names which three, and both it and `'could not update "jsmith": ' + err.message` (which names the editor, not the project) auto-dismiss after 4000 ms (`assignments.js:27-29`). The copy-plan success path toasts and then immediately `window.location.reload()`s, so that toast is never read either.
- **Proposed:** (a) `[ NONE ]` gets a confirm on the same pattern: `Untick all 40 projects for jsmith on DESKTOP? Their copies stay on disk; nothing new comes down and proxy sync stops for all of them.`; (b) while a column runs, replace the button label with `[ 12 / 40 ... ]` and offer `[ STOP ]` (set a cancelled flag the `next()` loop checks); (c) errors do not auto-dismiss - keep an error toast until dismissed, and list the failed project labels; (d) `toast()` messages name the project, not the editor.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** UX-1 (08-28) added the capacity confirm to `[ ALL ]` only.

### DUI-6: The error always renders at the top of the panel; the button that caused it is at the bottom
- **Lens:** usability
- **Who:** admin / owner
- **Where:** `partials/admin_users.html:6`, `partials/admin_packages.html:6`, `partials/admin_jobs.html:15`, `partials/fleet_halt.html:17`, `partials/admin_report_tokens.html:15`, `partials/fleet_grid.html:12`, `templates/setup.html:14` + `static/setup.js:39-45`.
- **Today:** every htmx panel returns its whole self with `error` painted in a banner at the top and swaps `outerHTML` on the panel, which preserves scroll position. So an admin who clicks [ DELETE ] on the fortieth package row, or [ SET ] on the last user's password, gets their refusal roughly two thousand pixels above the viewport and sees nothing happen. The setup wizard is worse: `showError()` writes into `#setup-error` at the very top of a page whose checklist is at the bottom, and **it is never cleared** - `showError(null)` has no call site, so a transient failure stays on screen through every subsequent success.
- **Proposed:** render the panel's `error` **beside the form that produced it** where the partial can tell (the project page already does this with `move_error` / `link_error` inline), or, cheaply and generically, add `hx-on::after-swap="this.querySelector('.banner')?.scrollIntoView({block:'center'})"` on the panels. In `setup.js`, call `showError(null)` at the top of every successful `.then`, and scroll the banner into view when it is set.
- **Effort:** S   **Value:** high   **Confidence:** high

### DUI-7: Both of the product's own deep links point at anchors that do not exist when the browser looks for them
- **Lens:** usability
- **Who:** admin / owner
- **Where:** `partials/topbar.html:46,85` (`href="/#server-notices"`), `partials/fleet_halt_banner.html:15` (`href="/admin/users#admin-fleet-halt"`); targets are `partials/notices.html:13` and `partials/fleet_halt.html:11`, both rendered only by `hx-trigger="load"` divs (`fleet.html:22`, `admin_users.html:27-28`).
- **Today:** clicking `[ 3 PROBLEMS ]` in the topbar navigates to `/`, where `#server-notices` does not exist at parse time - it arrives a few hundred milliseconds later from the load-triggered fetch, and browsers do not retry the fragment scroll. The admin lands at the top of the fleet page and has to find the panel. Same for the standing halt banner's "Start syncing again on Settings, Users.", which drops the admin at the top of a Users page with four panels above the halt control - the one moment the product most needs to hand them a button.
- **Proposed:** on `htmx:afterSwap`, if `location.hash` names an element that has just appeared and has not been scrolled to yet, `scrollIntoView()` it (five lines in `base.html`'s existing inline script, beside the `details` preserver). Alternatively render the halt panel server-side into `admin_users.html` rather than load-triggering it.
- **Effort:** S   **Value:** med   **Confidence:** high

### DUI-8: Fifteen places where the dashboard's answer to a non-technical owner is "edit an env var and redeploy" or "run this script from the repo"
- **Lens:** usability
- **Who:** owner (second customer, who has no repo checkout)
- **Where:** `partials/project_detail.html:232` ("device not named after a TrueNAS username. Run accept_device.py --device-name"), `:270` ("No editor devices share this folder yet. Share it with accept_device.py."), `partials/fleet_grid.html:218` ("Set dashboard_url in each editor's ~/.ccsync/config.toml"), `:60` (DASH_ENFORCE_MAX_REMOVALS), `partials/project_setup_panel.html:46-47` ("Ask your admin to create/link the folder with server/setup_tree.py"), `partials/admin_dashboard_update.html:24-25` (`server/install_dashboard_app.py`, `docs/DOCKER.md`), `partials/admin_packages.html:219-221` (`DASH_RELEASE_FEED_URL`, `docs/RELEASE_FEED.md`), `partials/admin_report_tokens.html:24-27,29,34` (`~/.ccsync/config.toml`, `DASH_SHARED_REPORT_TOKEN_ENABLED=0`), `partials/android_settings.html:18` (`docs/ANDROID.md`).
- **Today:** two of these are also **stale**: device approval moved into the Users panel's [ DEVICES AWAITING APPROVAL ] table long ago, yet the project page still tells an admin to run `server/accept_device.py`, a script that only exists on a base rig with a git checkout and NAS SSH. Queuing a fleet job is CLI-only in the same way (`tools/jobs.py queue`; Settings -> JOBS can only cancel).
- **Proposed:** for each line, either point at the page that now does it (`Approve it on Settings, USERS.`) or say plainly who can do it (`Ask whoever installed this server: it is a container setting, not something this page can change.`). Never name a repo path in copy an appliance customer reads. `accept_device.py` should be replaced in both places today; `~/.ccsync/config.toml` in the report-token panel should become "paste this into the tray's Sign in box" if that path exists, and otherwise say which editor to send it to.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** COMMERCIAL_READINESS item 11; docs/TENANCY.md.

### DUI-9: The package trash is a guard with no UI, and the confirm says recovery is impossible
- **Lens:** both
- **Who:** admin
- **Where:** `partials/admin_packages.html:127-131` (confirm), `ui.py:2933-2946` (`_trash_package_file`), `api.py:4589-4625` (`.trash` + `_prune_package_trash`); screen: Settings -> PACKAGES.
- **Today:** the confirm reads "Once it is gone you cannot put the fleet back on it without rebuilding and republishing." That has been untrue since the trash landed: the bytes sit in `<data>/packages/.trash/<platform>/` for 30 days. But nothing in the UI lists the trash, says how long it keeps things, or restores from it - the only recovery is a shell on the NAS, which is exactly the audience this product is trying to stop needing. So the copy is wrong AND the safety net is unreachable.
- **Proposed:** confirm copy: `Delete companion 0.9.62 for windows? These are the bytes a rollback needs. It is kept for 30 days and can be put back from [ DELETED PACKAGES ] below; after that it is gone.` Add a collapsed `[ DELETED PACKAGES ]` details block listing trashed files with their remaining days and a `[ PUT BACK ]` button (re-insert the row from the file's own metadata).
- **Effort:** M   **Value:** med   **Confidence:** high
- **Related:** UX-9 / C-5 (08-28) created the trash.

### DUI-10: If htmx does not load, the two things that explain why nothing is syncing are the only content that never appears
- **Lens:** resilience
- **Who:** editor / admin
- **Where:** `base.html:40` (htmx `defer`), `base.html:100-102` (halt banner, `hx-trigger="load"` with no server-side include), `fleet.html:22` (notices), `fleet.html:36` (plan changes), `project.html:17` (media presence).
- **Today:** the design is otherwise robust - the sidebar, fleet grid and transfers panel are all server-rendered into their first paint, so a dead `htmx.min.js` (a cached truncated file, an aggressive proxy, a locked-down browser) still shows a usable, if static, page. But the fleet halt banner - deliberately put on every page because "a Friday halt was a fleet that could not work all weekend with nothing on screen saying why" - and PROBLEMS THE SERVER FOUND are `load`-triggered with no server-rendered fallback. The one failure mode the banner exists for is exactly the one it does not survive.
- **Proposed:** server-render the halt banner into `base.html` (the read is one `meta` row and `_halt_banner_context` already exists) and keep the poll for updates; same for `partials/notices.html` on the fleet page. Optionally add `<noscript>` copy naming `/admin/users` as the place the halt lives.
- **Effort:** S   **Value:** med   **Confidence:** high

### DUI-11: SITE SETTINGS is sixteen jargon fields with one hint, in a mechanism built for hints
- **Lens:** usability
- **Who:** owner
- **Where:** `dashboard/templates/admin_settings.html:20-22` (`FIELD_HINTS` holds exactly one key), `:29-44` (the 16 fields).
- **Today:** the owner's configuration page is a flat list: ORG NAME, SHORT NAME, PRODUCT NAME, TRAY LOGO, TREE NAME, DRIVE LETTER, REMOTE ROOT, SMB UNC, DASHBOARD URL, SFTP HOST, SFTP PORT, SFTP CHUNK SIZE, SFTP CONCURRENCY, SFTP SHELL TYPE, RCLONE REMOTE, NAS SYNCTHING ID. Only `brand_logo` has a `title`. Nothing says which of these an editor's machine will refuse to sync without (`dashboard_url` mis-set 403s every Send-to-Resolve call - see CLAUDE.md's loopback note), which are advanced, or what a safe value looks like. A first-time customer meets this immediately after the wizard.
- **Proposed:** fill `FIELD_HINTS` for all sixteen (one sentence each, plus an example), and split the loop into three headed groups: `[ YOUR STUDIO ]` (org/product/logo), `[ THE TREE ]` (tree name, drive letter, remote root, SMB UNC, dashboard URL), `[ HOW EDITORS CONNECT - ADVANCED ]` (the sftp/rclone/syncthing six) collapsed by default. Flag `dashboard_url` specially: `This must be exactly the address editors type in their browser. If it does not match, Send to Resolve stops working for everyone.`
- **Effort:** S   **Value:** high   **Confidence:** high

### DUI-12: The audit log is called TIMELINE, in a product for people whose job is timelines and which mounts Timeline Cards
- **Lens:** usability
- **Who:** owner / editor
- **Where:** `partials/settings_nav.html:26` (`("audit", "TIMELINE", "/admin/audit", true)`), `templates/admin_audit.html:185,192`, and `partials/topbar.html:121` (`[ CARDS ]` -> Timeline Cards), `partials/plan_changes.html:58` ("the <a href="/admin/audit">fleet timeline</a>").
- **Today:** three different things in one navigation now use the word: a Resolve timeline (what the whole product is about, and what the CARDS chip in the fleet grid names: `[ CARDS: <timeline> ]`), Timeline Cards at `/cards/`, and the fleet audit log at `/admin/audit`. An owner told "check the timeline" has three places to look.
- **Proposed:** rename the settings entry and the page heading to `[ HISTORY ]` (or `[ WHAT CHANGED ]`, which is literally the page's own first sentence: "What changed in this fleet, and who changed it"), and change plan_changes.html's link text to "the full history". Leave the route.
- **Effort:** S   **Value:** med   **Confidence:** high

### DUI-13: Nothing on this UI is bounded: 400 projects and 40 machines are rendered whole, every poll
- **Lens:** resilience
- **Who:** admin / editor
- **Where:** `api.py:286-321` (`build_projects_view`, no LIMIT), `partials/sidebar.html:74-85` (whole tree, no filter box), `partials/fleet_grid.html:15-26` (a card per project), `admin_assignments.html:94-146` (projects x computers checkboxes), `partials/admin_jobs.html:88-99` (a per-machine "why" line for every job, always expanded).
- **Today:** the sidebar re-renders every 30 s and the fleet grid every 15 s, both unbounded; the assignments grid is O(projects x machines) checkboxes each carrying five data attributes (400 x 40 = 16,000, several MB of HTML per page load); the jobs page prints one prose line per machine per job with no `<details>`, so 20 queued jobs on a 40-machine fleet is 800 sentences re-fetched every 15 s. The assignments page has a client-side filter box; the sidebar, which is on every page and is the primary way to find a project, has none.
- **Proposed:** (a) add the same `filter projects...` input to the sidebar (client-side, on the already-rendered tree); (b) cap the fleet page's project cards at the N not-green ones plus `[ SHOW ALL 400 ]`; (c) wrap the jobs page's per-machine block in `<details><summary>why not here (40 machines)</summary>`; (d) paginate the assignments grid by project (it already has the filter, so page size 50 with the filter searching the server would be enough).
- **Effort:** M   **Value:** med   **Confidence:** med

### DUI-14: The em-dash rule is enforced for the glyph and not for its ASCII stand-in, which is in 14 places of visible copy
- **Lens:** usability
- **Who:** owner (the rule's author)
- **Where:** `dashboard/tests/test_no_em_dash.py:35` (`FORMS = ("—", "&mdash;", "&#8212;", "\\u2014")`), and in rendered copy: `setup.html:11,42`, `admin_assignments.html:29`, `admin_settings.html:21,69,179`, `partials/admin_users.html:204,267`, `partials/admin_packages.html:60,61`, `partials/fleet_grid.html:181,319,324`, `partials/topbar.html:156`.
- **Today:** e.g. `First-run wizard -- every step here can be re-run later from Settings.` and `device list unavailable -- {{ error }}` and `optional -- falls back to org name`. The house rule (CLAUDE.md, 2026-08-18) is "Use a hyphen with spaces, a colon, or two sentences"; ` -- ` is none of those, it is a typewriter em dash, and it renders as one to a reader. The test that exists to hold this line does not see it.
- **Proposed:** add `" -- "` to the scan (templates and the DOM-writing JS only, never comments - the test already strips `{# #}`, `<!-- -->` and `//`), and fix the 14 sites with a colon or a full stop. `First-run wizard: every step here can be re-run later from Settings.`
- **Effort:** S   **Value:** med   **Confidence:** high

### DUI-15: This customer's tailnet is a placeholder in the vendor build
- **Lens:** usability
- **Who:** owner (second customer)
- **Where:** `partials/android_settings.html:36` (`placeholder="net.ts.tail26290e.truenas.ccsync"`).
- **Today:** the Android panel's PACKAGE NAME field suggests a value derived from this studio's actual Tailscale tailnet id. CLAUDE.md's rule is "No customer's name in code", and a tailnet identifier is stronger identification than a name.
- **Proposed:** `placeholder="net.ts.<your-tailnet>.<host>.ccsync"`, or derive it from the live `dashboard_url` the same way the panel already derives `android_check.google_url`.
- **Effort:** S   **Value:** low   **Confidence:** high

### DUI-16: The first-run wizard has no sense of progress, no order, and injects task text as HTML
- **Lens:** both
- **Who:** owner (first-time customer)
- **Where:** `dashboard/static/setup.js:147-169` (`renderTasks`, `tr.innerHTML = '<td>' + task.title + ...` and `task.detail`), `:171-182` (`actionButton`), `templates/setup.html:54-61`.
- **Today:** steps 1-3 are numbered cards; below them the checklist is an unnumbered table where every row offers [ CHECK ], sometimes [ DO IT ], sometimes [ SKIP ], with no statement of how many are done, which are prerequisites of which, or when the wizard is finished. `[ DO IT ]` disables its button for the duration and says nothing else, for tasks that provision NAS accounts and trees. And `task.title` / `task.detail` are concatenated into `innerHTML`: a detail carrying a path with `<` in it, or a NAS error message containing markup, renders as broken HTML rather than text.
- **Proposed:** (a) header line `[ CHECKLIST ] 4 of 9 done, 2 optional` computed from the same payload; (b) number the rows and grey out ones whose prerequisite is not `ok`; (c) `[ DO IT ]` -> `[ WORKING... ]` while in flight, with the task's `detail` updated from the poll; (d) build the row with `document.createElement` + `textContent`, as `assignments.js` does for its toasts.
- **Effort:** M   **Value:** med   **Confidence:** high

### DUI-17: A machine whose clock is ahead reads as the freshest in the fleet
- **Lens:** resilience
- **Who:** admin
- **Where:** `dashboard/src/ccsync_dashboard/ui.py:88` (`seconds = max(int(delta.total_seconds()), 0)`), used by every LAST REPORT / LAST SEEN / published cell.
- **Today:** the clamp turns any future timestamp into `0s ago`. A machine whose clock is a day fast (the same condition the grid has a `[ CLOCK n AHEAD ]` chip for) therefore shows `0s ago` in LAST REPORT permanently, even after it has been switched off for a week - it sorts and reads as the healthiest row on the page. The clamp exists to avoid negative strings, which is right; saying nothing about the cause is not.
- **Proposed:** return `"clock ahead"` (with the delta in the title) when `delta` is more than ~120 s negative, and leave `0s ago` for ordinary jitter. One line, and it makes the existing skew chip's story consistent.
- **Effort:** S   **Value:** med   **Confidence:** high

### DUI-18: [ DISABLE ], [ REVOKE ] on an SSH key and [ SET ] on a password fire on one click, in the panel where [ DELETE ] asks twice
- **Lens:** usability
- **Who:** admin
- **Where:** `partials/admin_users.html:38-43` (key revoke), `:57-62` (set password), `:65-70` (disable/enable).
- **Today:** the panel is careful where it matters (DELETE names what survives; the sessions panel distinguishes "you") but three unconfirmed one-click writes sit in the same rows: revoking an editor's SSH key breaks their SFTP immediately and cannot be undone without the key text; setting a password locks them out of the dashboard until told the new one; DISABLE is at least reversible but its consequence ("they can no longer sign in anywhere, their computers keep syncing") is nowhere on screen. All three are adjacent to a `[ DELETE ]` that does ask, so a user learns "this panel confirms dangerous things" and is wrong three times per row.
- **Proposed:** confirms in the house style: `Revoke this SSH key for jsmith? Their SFTP access stops now and the key text cannot be recovered from here.` / `Stop jsmith signing in? Their computers keep syncing; this only blocks the dashboard and SFTP.` A password [ SET ] needs no confirm but does need a result line: `Password set for jsmith. Tell them: it is not shown again.`
- **Effort:** S   **Value:** med   **Confidence:** high
- **Related:** UX-22 (08-28) covered token/session revocation only.

### DUI-19: An editor's own page has no answer to "am I safe to close my laptop"
- **Lens:** usability
- **Who:** editor
- **Where:** `partials/my_queue.html:27-34`, `partials/transfers.html:33-38`, `fleet.html:58-69`.
- **Today:** the editor lens on `/` is good at what is moving (LIVE TRANSFERS, SYNC QUEUE with ETA) but never composes the one sentence the editor came for. They must read a percentage bar, a "12 files · 4.2 GB · ETA 26m" line, and a `[ GETTING READY ]` chip and do the synthesis themselves; and the fleet grid's `why_not_syncing` sentence (the exact mechanism for this) is rendered per machine in the admin table, not at the top of the editor's own page.
- **Proposed:** one line above the queue, from state already computed: `EVERYTHING OF YOURS IS ON THE SERVER.` / `4.2 GB still to upload from this computer, about 26 minutes. Leave it running.` / `Nothing is syncing on this computer: <why sentence>.` Reuse `health.why_not_syncing` and the queue view's totals; no new data.
- **Effort:** S   **Value:** high   **Confidence:** med

### DUI-20: A wired ("base rig") computer's cells are disabled with no route to the setting that made them so
- **Lens:** usability
- **Who:** admin
- **Where:** `admin_assignments.html:63-65,123-129`, `partials/sidebar.html:14-15`.
- **Today:** the column head prints `wired` and every checkbox is disabled with the tooltip "this computer works directly off the NAS tree, so it syncs nothing". True, and per CR-88 the setting lives on **that computer's** tray (Settings -> THIS COMPUTER), which the tooltip never says. An admin who wants that laptop to sync has a greyed-out grid and no next step. Worse on a phone, where the tooltip does not exist at all (see DUI-3).
- **Proposed:** append to both strings: `Change it on that computer: tray, Settings, THIS COMPUTER.` and make the `wired` label itself carry it as visible muted text in the column head rather than a title.
- **Effort:** S   **Value:** med   **Confidence:** high

## Still open from 08-28
- UX-8: HALT ALL SYNCING - built (confirm, expiry, banner, history). Closed.
- UX-9: release controls - partly built (unsigned/soak override needs a typed version); `[ MAKE CURRENT ]` on a signed, soaked build is still one unconfirmed fleet-wide click.
- UX-11: MOVE confirm and undo - built (`hx-on::confirm` composes the sentence; [ UNDO THIS MOVE ] exists).
- UX-12 / DASH-8: person-level tick naming and the undo panel - built.
- UX-20: [ RESUME ] acting on nothing - built (`error` banner in the grid).
- UX-22: revoking a session/token unconfirmed - built for sessions; SSH keys and report tokens still unconfirmed (see DUI-18).
- DASH-7: free space where the database lives - built (`admin_packages.html:14-27`), but it is on the PACKAGES page only, not on the fleet page an owner actually opens.

## Cross-cutting notes
- For the companion agent: the fleet grid's `[ RESUME ]`, `[ ASK THIS MACHINE WHY ]` and `commands.upgrade` all promise "on its next report". Nothing on the dashboard says what that interval is, so the admin cannot tell "it did not work" from "it has not happened yet". A `(usually within a minute)` in the chip copy would need the companion's report cadence surfaced in the report payload.
- For the release/OPS agent: `partials/admin_packages.html:60` tells the admin to "republish through tools\ship.cmd" - a Windows path to a script on the vendor's base rig, in a customer-facing panel. Same class as DUI-8.
- For the mobile/PWA reviewer: `sw.js` precaches `/offline` and `/static/*` keyed on the dashboard VERSION; a hotfix that edits `style.css` without bumping VERSION ships to installed phones as the old stylesheet with the new HTML.
- For whoever owns `docs/HOW_IT_WORKS.md`: there is no in-product legend for the green/amber/red dot, and no page linking to that document from the UI.
