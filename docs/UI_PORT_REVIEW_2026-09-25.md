# UI port review, 2026-09-25

One adversarial wave (the small-medium workflow) over the CC Terminal UI port,
merged as dashboard 0.7.62 (commit `107f9b0`; plan `UI_REDESIGN_PORT_PLAN.md`,
ledgers `UI_PORT_LEDGER/`). Five hunters, each followed by an independent
verifier: the look-switching mechanism, home and project, settings, the
everyday pages and the SPAs, and accessibility and copy. Browser checks ran
against the seeded dev server (`DASH_DEV_INSECURE=1`, `tools/mobile_sweep_seed.py`)
in headless Chrome at 1440, 768 and 390 px with the terminal groups on.

This is a REVIEW. Nothing was fixed and nothing was committed (a hunt is not a
fix wave). Severity below is the verifier's, which in several cases is lower
than the hunter's; both are shown.

## Tally

38 findings survived verification (37 confirmed, 1 plausible). None were refuted.

| Severity | Count |
|---|---|
| High | 3 |
| Medium | 17 |
| Low | 18 |

| Area | High | Medium | Low | Total |
|---|---|---|---|---|
| Mechanism (look switching, X-CC-UI, cookies) | 0 | 2 | 2 | 4 |
| Home and project pages | 2 | 5 | 4 | 11 |
| Settings pages | 1 | 1 | 4 | 6 |
| Everyday pages, HUD and SPAs | 0 | 4 | 2 | 6 |
| Accessibility and copy | 0 | 5 | 6 | 11 |
| **Total** | **3** | **17** | **18** | **38** |

Themes worth naming before the list:

- **Blind toggles.** `partial_toggle` flips whatever the server holds, so any
  stale control on a page with two views of the same plan (home tree plus
  queue, account computers plus person queue) performs the opposite of what it
  says (home-project-2, everyday-apps-1). The 409 after a committed write
  (mechanism-1) is the same shape from the other side.
- **The HUD at widths between phone and wide desktop.** The meta row cannot
  shrink and two hiding rules lose the cascade (everyday-apps-2, -3,
  home-project-9).
- **The mobile sweep can pass a page that scrolls sideways**, because mobile
  emulation grows the layout viewport to the content (settings-3).
- **Accessible names carry the decorative glyphs** added by `::before`
  (a11y-copy-1, -5).

## High

### home-project-1: tr.drawer rows use the global off-canvas .drawer class: hidden on desktop, and a full-screen opaque overlay on phones that blanks the project page

- **Severity:** high (hunter: high)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/templates/cc/partials/project_roots.html:35,58` and
  `cc/partials/project_detail.html:129` (`tr class="drawer"`), colliding with
  `dashboard/static/cc/components.css:450-456` (`.drawer { position: fixed; inset: 0; z-index: 71; display: none }`)
  and `static/cc/phone.css:21` (`.tbl.stack-sm tr { display: grid }`).
- **Scenario:** At 1440, an admin presses Browse in project_roots (or Missing
  files in the project's computers window). The answer loads into
  `#roots-browse-uN` / `#missing-<device>`, but the row is `display:none`, so
  nothing appears. At 390, on any project page with at least one unmapped or
  mapped root row, the phone rule overrides `display:none`: each `tr.drawer`
  becomes a fixed 390x844 opaque box at z-index 71, and the whole page below
  the HUD is black.
- **Evidence:** Seeded server, every group on, headless Chrome. At 1440,
  `/project/2026-ff5-elections` has three `tr.drawer` in `#win-roots` with
  computed `display=none`, `position=fixed`. After Browse, `#roots-browse-u1`
  held 690 bytes of answer but measured 0x0. At 390 the same rows computed
  `display=grid`, `position=fixed`, z-index 71, background `rgb(11,6,5)`,
  rect 0,0,390,844; `elementFromPoint(100,200)` returns that TD although the
  h1 is at top 70. The 390 screenshot is blank between the HUD and the dock.
  Verifier: no rule anywhere sets display on `tr.drawer`; on phones
  `.tbl.stack-sm tr` (0,2,1) beats `.drawer`. Verified from the stylesheets.
- **Suggested fix:** Rename the row class (`tr.xdrawer` / `.row-drawer`) in
  both templates and in the rules that style it (components.css:1061-1062,
  1099, home.css:128-129), or scope the off-canvas `.drawer` rules to a
  non-`tr` selector. Add a CSS-fact test that no `tr` carries a class the fixed
  drawer rule matches, and a 390 render check on the project page.

### home-project-2: A stale tree row after a queue untick turns a confirmed "This removes X" into a tick

- **Severity:** high (hunter: high)
- **Verdict:** CONFIRMED
- **Where:** `cc/partials/home_queue.html` (untick answers only `.queue-box`),
  `cc/partials/projects_tree.html` (blind toggle hx-post, confirm text chosen
  from the stale `on` state), `ui.partial_toggle` (toggles on server state).
- **Scenario:** jsmith on `/?machine=JSMITH-STUDIO` unticks Elections in
  sync_queue and confirms. The queue says "Nothing ticked", but the projects
  tree on the same page still shows Elections ticked for up to 30 s. Clicking
  that tree row to untick it shows "This removes 2026/FF5/Elections from
  JSMITH-STUDIO...", and OK sends a toggle that ADDS the project back. The
  same happens with the project page's sync_plan keys for 10 s after a tree
  tick.
- **Evidence:** Browser run as jsmith. Before: selections had
  (JSMITH-STUDIO, elections). Queue untick confirmed, queue answered "Nothing
  ticked", tree row still `checked=true`. Tree click: the dialog read "This
  removes 2026/FF5/Elections from JSMITH-STUDIO. Its copies stay on disk...".
  After OK, sqlite showed `('jsmith','JSMITH-STUDIO','2026-ff5-elections')`
  re-created, and the tree read "1 of 2 ticked". Verifier: `partial_toggle`
  (ui.py:1566-1573) sends no intended state; `ui_home.toggle_answer`
  re-renders only `.queue-box` with no HX-Trigger or oob swap; the tree polls
  every 30 s. A removal-worded confirm performs an addition.
- **Suggested fix:** Make tree and queue controls explicit sets, not toggles:
  send the intended state (for example `?want=off`) and have `partial_toggle`
  refuse or no-op when the server already matches. Also refresh the sibling
  window after each answer (an HX-Trigger that fires the tree body's and queue
  body's hx-get, or an oob swap of the other window).

### settings-1: Alerts Save always fails with "Refused: malformed form body". No alert channel can be saved from Settings, Alerts

- **Severity:** high (hunter: high)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/templates/cc/partials/admin_alerts.html` (`#alerts-form`,
  17 fields) and the classic `partials/admin_alerts.html`;
  `dashboard/src/ccsync_dashboard/ui.py` `_form()` (`MAX_FORM_FIELDS = 16`,
  line 963) used by `partial_admin_alerts_save` (line 2559).
- **Scenario:** An admin opens `/admin/alerts`, sets mail or a webhook (or
  changes nothing) and presses Save. The body carries 17 fields: the 13
  channel/mail/webhook keys plus the four server-check keys added 2026-09-24
  (`alerts_triage`, `_hours`, `_reply_to`, `alerts_imap_host`).
  `parse_qs(max_num_fields=16)` raises ValueError, `_form` turns it into HTTP
  400 "malformed form body", and nothing is saved. The only other way to set a
  channel is the Setup wizard's step, which cannot set SMTP host, port or user.
- **Evidence:** Seeded server, every group on. The real Save key posted
  `POST /partials/admin/alerts/save` with 17 pairs; response 400, banner
  "Refused: malformed form body" (1440 and 390). The same click in the classic
  look also gave 400, so the port did not cause this; it predates it and
  affects both looks. A browser count of every settings form found only two
  over 12 fields: `#settings-form` (24, sent as JSON, not affected) and
  `#alerts-form` (17). Verifier: 17 keys returned 400, 16 keys got past
  parsing; the only existing test posts just `alerts_sink`.
- **Suggested fix:** Raise `MAX_FORM_FIELDS` for `_form`, or give
  `partial_admin_alerts_save` its own limit (`len(alerts.SETTING_KEYS)` plus a
  margin). Add a test that posts the full rendered `#alerts-form` in both
  looks and expects 200 and "saved.".

## Medium

### mechanism-1: An htmx write that gets the 409 "cannot serve" answer has already been committed, and the classic error handler then undoes the checkbox on screen

- **Severity:** medium (hunter: high)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/ui_variant.py:859-876` (`render`:
  `if res.conflict: return HTMLResponse('', 409)`), called from `ui._render`
  at the end of every route; the 409 cases come from `resolve()` at lines
  776-806. The on-screen revert is `dashboard/static/htmx_errors.js` `refuse()`
  (~113-131).
- **Scenario:** (a) A tab loaded before the 0.7.62 deploy sends no X-CC-UI
  header, and an admin then turns on chrome,home. (b) An image rollback lands
  on a build that lacks one of the page's groups. The editor ticks or unticks a
  project. `partial_toggle` writes and commits, then calls `_render`;
  `resolve()` returns conflict, and the client gets 409 with an empty body.
  `refuse()` flips the checkbox back and shows "Refused: the server answered
  409 and gave no reason". The plan has changed, the page shows the opposite,
  and clicking again toggles it a second time.
- **Evidence:** Seeded 0.7.62 server, `ui_terminal_groups=chrome,home`. A POST
  to `/partials/selection/tchen/2026-ff5-animals/toggle?machine=TCHEN-RIG`
  with a signature that does not verify returned `409 {'x-cc-ui-want': '1'} ''`
  and the selection row was deleted. The same POST with no X-CC-UI header
  returned the same 409 and the row came back. R23 assumes the 409 refuses the
  write, but the check runs after the handler committed. Verifier reproduced
  both with TestClient; `test_a_forged_header_on_a_write_is_409_with_want`
  checks only the status code, never the DB. Downgraded: needs a stale state,
  a reload shows the truth, the effect is one tick or untick, nothing deleted.
- **Suggested fix:** Decide the look before the route runs (a dependency or
  middleware that refuses htmx writes with 409 before the handler touches the
  DB), or, where a write already happened, answer HX-Refresh instead of 409.
  Add a test asserting the selection is unchanged after a 409.

### mechanism-2: HEADER_FLOOR names a version that does not parse X-CC-UI (0.7.61), and nothing enforces it anyway

- **Severity:** medium (hunter: high)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/ui_variant.py:199-202`
  (`HEADER_FLOOR = "0.7.61"`). No other reference in `dashboard/src` or
  `tools`; `validate_groups_value`, `/ui/preview` and the `dashboard_update`
  preflight have no image-version check.
- **Scenario:** An admin turns on chrome,home (or uses the preview cookie).
  The Packages one-click rollback, the watchdog auto-revert or
  `select_code_root`'s "boot the image" fallback then lands on 0.7.61 or older.
  Every open terminal page keeps polling; the old build ignores X-CC-UI and
  returns classic fragments with no HX-Refresh, swapped into terminal windows.
  This is exactly what R23's header floor exists to prevent. The docstring
  promises enabling a group "is refused where that can be checked"; it never
  is. And 0.7.61 is the build just before the port (4c1b52f, no
  `ui_variant.py`); the first build that parses the header is 0.7.62.
- **Evidence:** `git show 4c1b52f:dashboard/src/ccsync_dashboard/ui_variant.py`
  does not exist and that commit's VERSION is 0.7.61. `grep -rn HEADER_FLOOR`
  finds only the definition. The P0 ledger says "(constant only)". A live
  0.7.61 server answered `GET /partials/fleet` with X-CC-UI=chrome,home plus
  Gen/Sig/HX-Current-URL with 200, no HX-Refresh, no X-CC-UI-Want and a
  classic `fleet-grid` body. Downgraded: needs an image rollback below 0.7.62
  while a group is on, which is rare.
- **Suggested fix:** Set `HEADER_FLOOR = "0.7.62"`. Implement the R23
  refusals: `validate_groups_value` and `/ui/preview?variant=cc` return
  422/403 while `dashboard_update.image_version()` is below the floor in image
  mode, with the same message on the groups form. Add
  `min_image_version = HEADER_FLOOR` to later feed records and enforce it in
  preflight. Refuse or warn on a one-click rollback below the floor while any
  group is on.

### home-project-3: Cancelling a tree confirm leaves the checkbox flipped

- **Severity:** medium (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `cc/partials/projects_tree.html` (hx-post plus hx-confirm on a
  checkbox, triggered by change); `static/cc/cc.js` htmx:confirm handler
  (dialog close does not restore the input).
- **Scenario:** An admin acting as jsmith clicks a ticked project in the tree
  and presses Cancel in the "This removes ..." dialog. Nothing is sent, but the
  browser has already unchecked the box, so the row shows unticked until the
  next 30 s beat. The reverse happens for the capacity-warning confirm on a
  tick.
- **Evidence:** `/?as=jsmith`, Animals `checked=true`, label clicked; the
  cc-confirm opened with "This removes 2026/FF5/Animals from jsmith's 2
  computers...". After Cancel the states read `[[Animals,false],[Elections,true]]`;
  nothing was posted and the server still had both ticks. Verifier: the close
  handler (cc.js:305-310) clears `pending` only. Display error, no data loss.
- **Suggested fix:** On dialog close without OK (and on htmx's own confirm
  false), restore `elt.checked = !elt.checked` for a checkbox source, or
  preventDefault the click and set checked only from the server's answer.

### home-project-4: "online" readout: nothing-ticked computers are counted, and silent computers with a fault headline count as online

- **Severity:** medium (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/ui_home.py` `home_readouts`
  (`counted = why.reason != 'no_selection'`;
  `silent = headline.reason == 'not_reporting'`).
- **Scenario:** `why_not_syncing` returns only the first reason, and
  disk_full, halt, breaker, not_signed_in and companion-reported reasons rank
  above no_selection, so a nothing-ticked computer is counted whenever it has
  any other why. `health.fleet_headline` returns a non-informational fault
  before the silence check, so a computer silent for hours with a breaker or
  disk fault is never in `silent` and is reported online.
- **Evidence:** (a) JSMITH-MBP and JSMITH-STUDIO aged 8 h: the readout said
  "online 4/5, JSMITH-STUDIO not heard from" while JSMITH-MBP's row said "Last
  report 8h ago" and was counted online (headline = breaker fault). (b) tchen
  with every selection deleted: "online 1/1, every computer with a project
  ticked has reported", although TCHEN-RIG has nothing ticked
  (why = not_signed_in). Verifier traced health.py ~858-898 and 1216/1223.
- **Suggested fix:** Count by the row's plan (`e.get('plan',{}).get('count')`
  and mode not base), and decide silence with the headline's own freshness
  test (`health._silence(row)` or the "no report since" prefix), not
  `headline.reason`. Add tests for a silent faulted row and a nothing-ticked
  row with a non-selection why.

### home-project-5: "moving" and "in sync" readouts read only Syncthing folder completion, so they contradict the page

- **Severity:** medium (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `ui_home.home_readouts`: `moving = sum(need_bytes_total)` and
  `ticked` = projects with `p.editors`, both built from
  `db.fetch_project_editors` (completion_current joined to shared Syncthing
  devices).
- **Scenario:** Lanes A and B (what the transfers window shows) and
  upload-only ticks are never in that source. With Syncthing unreachable, not
  yet shared, or upload-only, the home page says "moving 0 B, nothing waiting"
  beside a transfers window full of moving files, and "in sync 0/0, no project
  is ticked anywhere" while selections exist.
- **Evidence:** Seeded server (5 selections, no completion rows): "moving 0 B,
  nothing waiting" and "in sync 0/0, no project is ticked anywhere", while the
  same screenshot's transfers window lists 15 files at 40 MB/s and the queue
  says "Not yet: 26 files still uploading ... (290.6 GB)". Verifier:
  `api.build_projects_view:437` builds from `fetch_project_editors`
  (db.py:10899), lane C alone; the readout's own tip claims all footage.
- **Suggested fix:** Take "moving" from `build_transfers_view` /
  `safe_to_close` (bytes in flight plus queued), or label it folder sync only.
  Take "ticked" from the selections (`fetch_all_selections`) and never print
  "no project is ticked anywhere" while selections exist.

### home-project-6: On phones and at 768 the projects tree and ticking_for are the last things on the page, about 10,000 px down

- **Severity:** medium (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `static/cc/terminal.css:406` (`.side { position: static; order: 2 }`)
  with `cc/fleet.html`'s `aside.side`; nothing replaces the classic
  `#projects-sheet`.
- **Scenario:** An editor on a phone wants to tick a project. The dock's
  "sync" link (D17's "one tap reaches the tree") opens `/`, where the tree
  sits under the readouts, problems.log, every computer card, transfers, plan
  changes and the queue. The queue's empty state says "Tick a project in the
  projects list" with no link to it.
- **Evidence:** Home as admin at 390: `#win-ro-online` top 358,
  `#win-computers` 7267, `#win-queue` 9534, `#win-ticking-for` 9832,
  `#win-projects` 10016 (page height 10358). At 768, `#win-projects` at 6650
  of 6948. Project page at 390: tree at 3741. Verifier confirmed the layout
  rule (only `.side.docs-first` gets order 0, fleet.html does not use it) but
  did not re-measure.
- **Suggested fix:** Put the side column first on narrow screens, or give it a
  sticky "projects" sheet as classic did. At least add an in-page "projects"
  jump in the head and link the queue's empty state to `#win-projects`. Add
  D17's phone-sweep assert that the tree is one tap away.

### home-project-7: Each computer's headline sentence is clipped to one line, and its tooltip gives the reason code instead of the sentence

- **Severity:** medium (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `cc/partials/fleet_grid.html:174`
  (`<div class="hl" title="reason code: {{ hl.reason }}">`) and
  `static/cc/home.css:13` (`.pc .hl` nowrap, overflow hidden, ellipsis).
- **Scenario:** The headline is the row's answer to "what is wrong and what to
  do", for example "Not syncing: this computer is not signed in. Also: Proxy
  download has probably stopped itself: ...". It is cut at about 40
  characters at every width, and hovering shows "reason code: not_signed_in".
  The full text survives only in the 10 px LED's title; on a phone it cannot
  be read.
- **Evidence:** At 1440, `.home-pc .hl` client/scroll widths 348/665, 348/1451,
  348/1508 for JSMITH-MBP, RIVERA-TOWER, TCHEN-RIG with titles "reason code:
  breaker_tripped" / "disk_full" / "not_signed_in". At 390: 298/1508. The
  coarse/phone block at home.css:30 relaxes `.issues` and `.lanes-wrap` but not
  `.hl`.
- **Suggested fix:** Let `.hl` wrap (clamp to 2-3 lines with the full text in
  the row expander), or put `hl.text` in the title / data-tip so cc.js's tip
  and hint sheet carry it. Keep the reason code out of user copy.

### settings-3: On a phone, Sync plans, Packages and Setup make the whole page scroll sideways (Sync plans by about 240 px)

- **Severity:** medium (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/static/cc/settings_people.css:6`
  (`.sp-stack { display: grid; ... }`) and `settings_fleet.css:5`
  (`.sf-stack`), implicit auto column with no `minmax(0,1fr)`; with the nowrap
  `.bar` in `terminal.css:115`, a `.win` cannot shrink below its bar's
  one-line width.
- **Scenario:** At 390, Sync plans' whose_plan window has the nowrap bar meta
  "the choice is in the address, so a link lands here too", making the bar
  568 px; the grid track grows to 613 px, the picker selects to 577 px and the
  document to 627 px. The topbar and nav are cut off and the page pans
  sideways. Packages (42 px) and Setup (30 px) do the same on a smaller scale.
- **Evidence:** Headless Chrome at 390 without mobile layout-viewport
  expansion: `/admin/assignments` scrollWidth 627 against innerWidth 390, width
  chain select 577 < label.pick 579 < form 579 < .win 613 < div.sp-stack
  (352 wide, gridTemplateColumns 613.234px). `/admin/packages` scrollWidth 432,
  `/setup` 420. With mobile emulation the layout viewport grows to the content
  (innerWidth 584/627 while visualViewport.width is 390), so
  `tools/mobile_sweep.js`, which compares scrollWidth with innerWidth, reported
  all three "ok". Verifier reproduced (584 vs 390, 570 px track, two 568 px
  bars; packages 403/432; setup 420). phone.css's
  `.bar .meta{min-width:0;overflow:hidden}` does not stop the bar sizing the
  track. Also seen on every settings page: the HUD dock's "...more" reaches
  401 px at 390.
- **Suggested fix:** Give both stacks `grid-template-columns: minmax(0, 1fr)`
  (or `min-width: 0` on their children). Let `.bar .meta` shrink with ellipsis
  at phone width. Make the mobile sweep compare against
  `visualViewport.width` (or run with mobile:false) so layout-viewport
  expansion cannot hide overflow.

### everyday-apps-1: In the account page's new sync queue window, Untick is not reflected in the computer windows, and their Untick key then ticks the project again

- **Severity:** medium (hunter: high)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/templates/cc/partials/person_queue.html` (Untick:
  `hx-target=#person-queue-body`, fires no account-refresh) and
  `cc/partials/account_computer.html` (Untick is a plain
  `toggle?view=none&machine=...`); `ui.py partial_toggle` ~1565-1612.
- **Scenario:** jsmith on `/account` presses Untick on 2026/FF5/Animals in the
  sync queue and confirms. The queue empties, but the JSMITH-MBP window still
  lists Animals with "Upload only" and "Untick" until its 30 s poll. Pressing
  that Untick sends a toggle with no mode, and since the project is no longer
  ticked, the server ticks it again. The stale "Upload only" / "Sync fully"
  keys re-tick it too, because a mode makes the toggle a set.
- **Evidence:** Headless Chrome, seeded server (390/1440). Queue Untick plus OK
  took the queue rows from [Animals] to []; 15 s later the computer window
  still showed the keys for `2026-ff5-animals@JSMITH-MBP`. Clicking that stale
  Untick plus OK, a fresh `GET /account` showed Animals ticked again on
  JSMITH-MBP. Verifier confirmed from code: `ui_everyday.toggle_answer`
  returns only person_queue.html with no oob bodies and no trigger; a slug not
  ticked with no mode goes to `add_selection`. Downgraded: the computer window
  refreshes after its own request and shows the tick, so one more Untick
  reverses it; only proxy sync resumes, nothing deleted.
- **Suggested fix:** After a queue untick, refresh every computer window
  (`hx-on:htmx:after-request` triggering `account-refresh` on each
  `.account-pc`, or oob bodies from the route). Better, make the computer
  window's Untick an explicit remove (`?mode=off` or a DELETE) so a stale key
  can never tick.

### everyday-apps-2: The HUD overflows the page sideways at desktop and tablet widths while Syncthing is unreachable, pushing the account menu off-screen and hiding the brand

- **Severity:** medium (hunter: high)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/static/cc/hud.css` hud-common (`.hud-nav flex:none`,
  `.hud-meta flex:none` plus `white-space:nowrap`; only `.hud-name` can
  shrink), copied into broll/music/ytdl `style.css`;
  `cc/partials/stamp.html` (the full "syncthing unreachable, data may be
  stale" sentence at every width above 600 px).
- **Scenario:** Syncthing is unreachable, or there are problems and alerts. An
  admin at 1440, or an editor at 1024 or 768, opens any page (transfers,
  installer, help, account, project setup, `/cards`, `/broll/`, `/music/`,
  `/ytdl/`). The bar is wider than the window, the page scrolls sideways, the
  "menu" key (sign out, look switch, help, installer) sits past the right
  edge, and the brand shrinks to 0 px.
- **Evidence:** Hunter: admin 1440 -> scrollWidth 1464-1549 on every page and
  all three SPAs, 1024 -> 1549, 768 -> 1274-1351; editor 1024 -> 1202, 768 ->
  1009. `div.hud-meta` 866-921 px; "menu" at x 1495-1549; `.hud-name` 0 px at
  1440/1100/800. Verifier: 1024 -> 1390 with the menu's right edge at 1390,
  768 -> 1281; at 1440 the page did NOT overflow in the verifier's run (1430 vs
  1440), but `.hud-name` was 0 px on /transfers and /account. Downgraded: needs
  Syncthing down plus several meta items; the menu is reachable by scrolling.
  (Cosmetic: the flex gap renders "stale : syncthing".)
- **Suggested fix:** `.hud-meta { flex: 0 1 auto; min-width: 0 }` with the
  stale sentence and "updated N ago" giving way (ellipsis). Hide the stale
  sentence (keep the LED, "stale" and the tip) below about 1600 px, not only
  at 600. Give the brand a min-width. Copy the hud-common block to all four
  sheets.

### everyday-apps-3: The HUD's hud-hide-sm and hud-more-btn hiding rules lose the cascade, so the phone bar shows items it should hide and a desktop bar shows the tablet-only "more" key

- **Severity:** medium (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/static/cc/hud.css` hud-common (and the three SPA
  copies): `.hud-meta a { display:inline-flex }` (0,1,1) beats
  `.hud-hide-sm { display:none }` (0,1,0); `.hud-key { display:inline-flex }`
  (line 144) is declared after `.hud-more-btn { display:none }` (line 135) at
  equal specificity.
- **Scenario:** (a) At 390 the alert count and the "owen @admin" account link,
  both `hud-hide-sm`, stay in the bar; for an admin the bar is 401 px, so every
  page and SPA is wider than the phone and mobile Chrome zooms out. (b) Above
  900 px the "more" button meant for 601-900 px shows in the nav; pressing it
  opens the phone sheet as a full-width slab across the lower page.
- **Evidence:** At 390: `hud-count hud-hide-sm|flex`, `hud-user hud-hide-sm|flex`,
  `hud-key hud-hide-sm|none`; innerWidth 401 on /transfers, /account, /cards/,
  /broll/, /music/ for owen. At 1920/1440/1100, `.hud-more-btn` display flex;
  clicking opened `#hud-more` at [0,334,1910,566]. Verifier re-measured the
  390 case and the visible "more" at 1440 and 1024; did not re-check the sheet
  position.
- **Suggested fix:** Raise the hiding rules' specificity inside hud-common
  (`.hud .hud-hide-sm, .hud-meta .hud-hide-sm { display:none }` in the 600 px
  block; `.hud-nav .hud-more-btn { display:none }` at base with the 601-900
  block re-showing it). Add a test that computes these elements' display, not
  only the rule text.

### everyday-apps-5: Help in the terminal look: a code block widens the whole page on phones (pre has no overflow), up to 3.5x the screen

- **Severity:** medium (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/static/cc/components.css` `.doc` rules (no `.doc pre`
  rule) and `cc/everyday.css` `.ev-help .help-doc` (only overflow-wrap); the
  classic sheet had `.help-doc pre { overflow-x: auto }` (`static/style.css:2074`).
- **Scenario:** An editor opens `/help/EDITOR_SETUP.md` (or API.md, GOTCHAS.md,
  or the default HOW_IT_WORKS.md tree diagram) on a phone. The PowerShell and
  bash snippets are `white-space:pre` with no scroll container, the column
  grows to the longest line, and the page zooms out to unreadable text.
- **Evidence:** At 390 with mobile emulation, innerWidth /help 531,
  /help/API.md 1182, /help/EDITOR_SETUP.md 1397, /help/GOTCHAS.md 868. Widest
  leaf: a 1366 px `CODE` ("powershell -ExecutionPolicy Bypass -File
  .\windows_bootstrap...") in a `PRE` with overflow visible. Verifier
  reproduced the same widths.
- **Suggested fix:** Add `.doc pre { overflow-x: auto; max-width: 100%; }` and
  `min-width: 0` on the doc column (or a `minmax(0,1fr)` track). Give
  `.doc table` a scroll wrapper or overflow-x auto as classic's help-table
  rules did.

### a11y-copy-1: CSS glyphs become part of control names: "▸ DISMISS", "◉ none", ">site"

- **Severity:** medium (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/static/cc/terminal.css:166` (`.key.quiet::before "\25B8"`);
  `components.css:47-51` (`.check` / `.radio .g::before` glyphs), 188, 784,
  1123; `hud.css:280` (`.snav a::before ">"`); broll/music/ytdl `style.css`
  (`html.cc .text-btn::before "\25B8"`, ytdl `.ptoggle ::before`).
- **Scenario:** A screen-reader user tabs through terminal pages. Every quiet
  key, fold summary and settings-nav link has a decorative `::before` glyph
  with no alt-text form, so NVDA/VoiceOver read "black right-pointing small
  triangle dismiss" or "greater-than site". A radio is named after its painted
  state glyph: an unchecked option reads "white circle mail (smtp)".
- **Evidence:** CDP `Accessibility.getFullAXTree` at 1440. Home: 17x button
  "▸ DISMISS", link "▸ WHAT TO DO". /admin/users: "▸ DELETE" x4, "▸ REMOVE" x5,
  "▸ ERASE HISTORY" x4. /admin/health: "▸ NOTICES" x17, "▸ ALERTS" x22.
  /admin/alerts: radios "◉ none", "○ mail (smtp)", "○ webhook". Every settings
  page: links ">site", ">users", ">sync plans" ... ">help". Transfers
  direction cells named "⇡"/"⇣" (literal glyphs, cc/partials/transfers.html:46,
  122). The HUD's own ">" is correctly aria-hidden. Verifier: settings
  checkboxes render `<span class="g"></span>` without aria-hidden
  (admin_settings.html:168-170); only admin_assignments marks it.
- **Suggested fix:** Give every decorative `content:` an empty alternative
  (`content: "\25B8" / "";`), including the `.g` glyphs and `.snav a::before`
  in all four hud-common copies. Render the transfers direction as a visually
  hidden word with the arrow aria-hidden. Add a CSS-fact test that every
  visible-glyph `content:` in static/cc and the SPA cc blocks carries the
  `/ ""` alt text.

### a11y-copy-2: The confirm dialogs never announce the question they ask

- **Severity:** medium (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/templates/cc/shell.html:147`
  (`<dialog id="cc-confirm" aria-labelledby="cc-confirm-t">`, no
  aria-describedby); broll/music/ytdl `static/cc_spa.js:246-272` (confirmBox
  builds a dialog with no name and no description).
- **Scenario:** An admin using a screen reader presses "disable" on a user.
  Focus moves to Cancel and the reader says "are you sure, dialog, Cancel,
  button", never the question ("Stop jsmith signing in? ..."). The same on
  every destructive confirm (delete, forget, stop the fleet, make an unsigned
  build current). In the SPAs the dialog has an empty name.
- **Evidence:** CDP on /admin/users: AX dialog name "are you sure", no
  description, `aria-describedby=null`. SPA: `ccSpa.confirm('Delete this clip
  from the archive?')` gave AX dialog name "" and no description. Verifier:
  `<p data-cc-confirm-q>` has no id; cc_spa.js is byte-identical across the
  three SPAs.
- **Suggested fix:** Give the question paragraph an id and point
  aria-describedby at it on `#cc-confirm`. In cc_spa.js give the dialog
  aria-label or aria-labelledby plus aria-describedby at `.cc-spa-q`. Add an AX
  assertion to the confirm tests.

### a11y-copy-3: SPA tips remove the title for good, and keyboard users never see them

- **Severity:** medium (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `broll/web/static/cc_spa.js:186-229` (byte-identical in
  `music/web` and `ytdl/web`).
- **Scenario:** In the terminal look of b-roll, music and YouTube,
  `showTip()` moves a title into `data-cc-tip` and removes it without setting
  aria-description (unlike dashboard cc.js adoptTips). After one mouse pass a
  control's only explanation is gone for a screen reader until the look is
  switched off. There is no focusin handler, so keyboard users never see a
  tip, and on touch controls are excluded.
- **Evidence:** b-roll index.html with html.cc and cc_spa.js: before hover the
  Visuals button had description "Visuals: what is seen on screen..."; after
  `focus()` no `.cc-spa-tip.show`; after one mouseMoved over and away, no
  description, `title=null`, text in `data-cc-tip`. Verifier: listeners are
  mouseover, click (coarse, non-controls) and Escape only; `restoreTitles`
  runs only when the look is turned off.
- **Suggested fix:** Set aria-description when adopting, as cc.js does (or keep
  the title and suppress only the native bubble). Add focusin/focusout that
  shows the tip, and a `.tip-btn` or tap path for controls on coarse pointers.

### a11y-copy-4: Control explanations cannot be reached on touch or by keyboard focus (plan 3.2 / finding 126 not built)

- **Severity:** medium (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/static/cc/cc.js:103-105` (`TIP_SELECTOR` has no
  `.key` / `[role=tab]` / `.hud-nav a`), cc.js:197-209 (`.tip-btn` handler);
  `templates/cc/**` (no `.tip-btn` anywhere; `window.ccsyncOpenHint` never
  defined).
- **Scenario:** On a phone the explanations on keys, tabs, links and fields
  cannot be read: "Send a test", the Site tabs, "Update now", "Suspend" (the
  reversible way to stop somebody), "Delete". Touch browsers never show title
  and the hint sheet deliberately ignores controls. On desktop, tabbing onto a
  key shows nothing. The plan accepted a `.tip-btn` beside explained controls
  and floating tips on keys and tabs; neither was built, and the "?" handler
  is dead code.
- **Evidence:** At 390 with a coarse pointer, visible controls with a title and
  no reachable tip: home 34, /admin/settings 39, /admin/users 37,
  /admin/alerts 17, /account 24, /project 33, /admin/packages 19; tipBtns=0
  everywhere. At 1440 on /admin/alerts, "Send a test" focused, no
  `.cc-tip.show` after 1.3 s. Verifier: `ccsyncOpenHint` referenced only at
  cc.js:204; htmx_errors.js:249/283 skips CONTROLS for the hint sheet.
- **Suggested fix:** Build the planned Jinja macro rendering
  `<button type="button" class="tip-btn" data-tip-for=...>` beside explained
  controls, shown under `(pointer: coarse)`. Define `window.ccsyncOpenHint` or
  open `#chip-sheet` directly. Extend `TIP_SELECTOR` (or give keys a data-tip)
  so focus shows the floating tip. Add the planned 390 sweep check.

### a11y-copy-5: Heading names are glyph soup: "> TRANSFERS", "// YOUR COMPUTERS", "## 2. The pieces", "this_dashboard"

- **Severity:** medium (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `templates/cc/*.html` h1 (`<span class="prompt">&gt;</span>`, 20
  pages, 3 aria-hidden); `components.css:19,185,462,834`,
  `everyday.css:17,83` (`"\2f\2f"` ::before); `components.css:957,959`
  (`.doc h2/h3` "## " / "### "); snake_case window titles in
  `cc/admin_packages.html:35`, `partials/admin_packages.html:25`,
  `cc/admin_settings.html`, `cc/admin_health.html:48`, `cc/admin_alerts.html`,
  protection, recovery.
- **Scenario:** Screen-reader users move by headings. Every terminal page
  title reads "greater-than transfers"; section heads read "slash slash your
  computers"; all 45 /help headings read "number number 1. The problem it
  solves"; window titles read "this underscore dashboard". Home (`cc_title`
  filter) and assignments/audit (underscores aria-hidden plus a `.vh` space)
  already solve this.
- **Evidence:** CDP AX headings: /transfers "> TRANSFERS"; /account "// YOUR
  COMPUTERS"; /help "## 1. The problem it solves" ... "### 8.7 Keeping the
  engines alive"; /admin/packages "currently_served", "from_the_vendor",
  "other_versions_held", "out_of_date_computers", "this_dashboard";
  /admin/settings "your_studio", "the_tree", "how_editors_connect",
  "nas_and_folders"; /admin/health "what_is_running"; /admin/recovery
  "protected_right_now", "put_files_back"; /admin/alerts "server_check";
  /admin/protection "what_only_you_can_confirm".
- **Suggested fix:** aria-hide the h1 `.prompt` span. Give the ::before
  prefixes empty alt text (`content: "\2f\2f" / ""`). Render every window title
  through the underscore-splitting markup of `cc/admin_assignments.html:21` or
  through `cc_title`.

## Low

### mechanism-3: X-CC-UI-Want is never shown on base.html pages, so classic-bodied pages (including chrome-only ones) never learn that the look changed

- **Severity:** low (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/templates/base.html` (loads htmx_errors.js, not
  cc/cc.js); the only X-CC-UI-Want handlers are `static/cc/cc.js:473-485`
  (showReloadLine) and `cc/dashboard_update.js`; `htmx_errors.js` has none.
- **Scenario:** With chrome on, `/admin/users` is drawn by base.html with the
  terminal HUD over a classic body. An admin turns on settings-fleet, or rolls
  chrome off with `tools/ui_variant.py off`. Every poll now carries
  X-CC-UI-Want: 1 but nothing reads it, so the page keeps its old look (on a
  wall display, forever). R23 says htmx_errors.js shows a quiet "the dashboard
  look changed, reload" line. Same gap for fully classic pages when a group is
  first turned on.
- **Evidence:** CDP on /admin/users with chrome,home: no cc/cc.js script. After
  flipping to chrome,home,settings-fleet and triggering the stamp poll, the
  response had X-CC-UI-Want 1, no `.cc-reload`, no "look changed" text. Over
  httpx, after `none` a page drawn with chrome,home kept getting terminal
  partials with Want: 1 only. Downgraded: partials follow the page's signed
  set, so the page stays self-consistent; cannot-serve cases still get
  HX-Refresh.
- **Suggested fix:** Move the htmx:afterRequest Want listener (and the 409 plus
  Want line) into htmx_errors.js, which both shells load, or load a small
  shared script from base.html. Add the R23 test: classic body with chrome on,
  page group flipped, line shown.

### mechanism-4: SPA first paint trusts a stale ccsync_ui_effective cookie after a rollback, and html.cc is never cleared if the topbar fetch fails

- **Severity:** low (hunter: low)
- **Verdict:** CONFIRMED
- **Where:** `broll/web/static/index.html` (and music/ytdl) head script adding
  `html.cc` from the cookie; `broll/web/static/app.js` `loadDashboardTopbar()`
  finally branch (~318-334) removes `cc-chrome` but never `cc`.
- **Scenario:** With apps on, a browser gets `ccsync_ui_effective=chrome.apps`
  (180 days). The admin turns every group off. The editor opens `/broll/`
  (or music, ytdl) directly. The head script paints the terminal body; if
  `../partials/topbar` then fails (503, redirect, network error), `html.cc`
  stays set for the page's life. When the fetch succeeds, the first paint still
  flashes the terminal look.
- **Evidence:** Code trace of app.js's finally block (app.js:331-332) and
  index.html's head script. Only a dashboard full-page render or a successful
  topbar rewrites the cookie.
- **Suggested fix:** In the finally branch remove `cc` as well as `cc-chrome`
  when no topbar arrived (fail classic), and rewrite the cookie to empty.

### home-project-8: With ?as=<editor>, the first 15 s beat swaps the grid, readouts and meta to the whole fleet while the header still names the editor's computers

- **Severity:** low (hunter: low)
- **Verdict:** CONFIRMED
- **Where:** `cc/fleet.html:70` (`.fleet-grid-wrap hx-get="/partials/fleet"`,
  no as=) and the oob `#home-readouts` / `#computers-meta` in
  `fleet_grid.html:22-25`; `/partials/home-transfers` likewise.
- **Scenario:** `/?as=jsmith` first paints jsmith's 2 computers. Fifteen
  seconds later the grid shows 5 rows, meta "5 computers", online 5/5, while
  the head still says "2 computers · 2 projects". Classic lacked as= on this
  poll too, but the new oob readouts now visibly disagree with the header.
- **Evidence:** t0 {sub "2 computers · 2 projects", meta "2 computers", rows 2,
  online 2/2}; t+16 s {sub unchanged, meta "5 computers · collector 8m ago",
  rows 5, online 5/5}. Admin-only, cosmetic.
- **Suggested fix:** Carry the page's as= (`tree.as_qs`) on the
  `/partials/fleet` and `/partials/home-transfers` polls, or draw the head's
  counts from the same oob answer.

### home-project-9: Home at 768 scrolls sideways (page 1282 px wide)

- **Severity:** low (hunter: low)
- **Verdict:** PLAUSIBLE
- **Where:** `cc/partials/topbar.html` HUD (`.hud-meta` / `.hud-stamp` /
  `.hud-stale` not hidden at 601-900 px); home and project pages.
- **Scenario:** At 768 the HUD meta row does not wrap or hide, so home and
  project have a 1282 px scroll width and the stale warning is cut off. Chrome
  group markup, but it breaks both home-group pages. Overlaps everyday-apps-2.
- **Evidence:** At 768 on / and /project/2026-ff5-elections:
  scrollWidth 1282 vs clientWidth 768; widest `DIV.hud-meta` (right edge 1281,
  width 921), `SPAN.hud-stamp`, `SPAN.hud-stale` (405). Verifier: hud.css:137
  `.hud-meta` flex none, nowrap; 299-310 hides only `.hud-lowpri`; did not
  re-measure, depends on the stale state.
- **Suggested fix:** Hide or wrap `.hud-stamp` / `.hud-stale` in the 601-900
  band, and add the 768 overflow assert to the sweep.

### home-project-10: Phone tap targets on home are below 44 px: tree ticks, project links, row "details", fold buttons, admin keys

- **Severity:** low (hunter: low)
- **Verdict:** CONFIRMED
- **Where:** `static/cc/home.css` / `terminal.css` under `(pointer: coarse)`,
  `(max-width: 760px)`.
- **Scenario:** At 390 on touch, the only way to reach Resume / Ask this
  computer why / Read the answer is a 20 px "details" summary; the tick square
  is 28x29, the project link 23 px tall, fold buttons 11 px wide, row keys
  28 px. The ledger lists "44 px tree rows" as not yet checked.
- **Evidence:** LABEL.tick 28x29, A.nm 50x23, details.more > summary 136x20,
  BUTTON.fold 11x44, .row-actions .key 143x28 / 191x28. Verifier: the only
  `--cc-tap` rules are hud.css:375-378 (HUD and snav).
- **Suggested fix:** Under the coarse/phone query give `.row.proj label.tick`,
  `a.nm`, `details.more > summary`, `button.fold` and `.key.sm` a min size of
  `var(--cc-tap)`, and add them to the sweep's tap assert.

### home-project-11: "Read the answer" lands more than a screen away with no scroll or focus

- **Severity:** low (hunter: low)
- **Verdict:** CONFIRMED
- **Where:** `cc/partials/fleet_grid.html:241` (`hx-target="#fleet-diagnostics"`)
  and the what_computers_said window after the whole computers window in
  `cc/fleet.html`.
- **Scenario:** On a phone, pressing Read the answer swaps the bundle below
  the last computer card; nothing on screen changes. cc.js unfolds the window
  but does not scroll to it.
- **Evidence:** At 390, button top 412, answer top 1652 (innerHeight 868),
  scrollY unchanged. At 1440: button 469, answer 1227, viewport 900. Verifier:
  cc.js's only scrollIntoView is in openHash (424).
- **Suggested fix:** After a non-poll swap into `#fleet-diagnostics`,
  scrollIntoView the window (or focus its first summary), or render the answer
  inline in the row expander.

### settings-2: "roll back" on a served row puts its refusal on another row, inside the folded "other versions held" list, or shows it nowhere

- **Severity:** low (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/templates/cc/partials/admin_packages.html` (rollback
  form 65-77, `refusal()` 45-50, held rows inside
  `<details class="fold pkg-other">` 406-416, banner rule "error and not
  error_for" 229); `ui.py partial_admin_package_current`
  (`error_for=f"{kind}/{platform}/{version}"`, 4325).
- **Scenario:** The rollback select posts the chosen older version, so a
  refusal is keyed to that version's row, which sits in the closed
  other_versions_held details. If that row is gone (deleted by another admin
  between poll and click), the refusal matches no row and the top banner is
  suppressed too, so nothing shows. cc.js's unfold-on-refusal rule reads
  `evt.detail.target`, the detached old box for this outerHTML swap, and its
  selector lacks `.row-refusal`.
- **Evidence:** Seeded windows 0.9.53 row signed, ever_current, on disk. (a)
  Build recalled after render, rollback pressed and confirmed: the only
  refusal node was in the folded 0.9.53 row (open=false). (b) Row deleted
  after render: `.row-refusal, .error-banner` returned []. Downgraded:
  `pkg_rollback_choices` already filters to acceptable targets, so this needs
  a race.
- **Suggested fix:** Key the rollback refusal to the pressed row (an
  `error_row` field, or render on the current row for any make-current from a
  `form.rb`). Fall back to the top banner when error_for matches no row. Open
  the pkg-other details when a refusal lands inside. Use `liveRoot(evt)` in
  cc.js's afterSwap and add `.row-refusal` to its selector.

### settings-4: The Alerts "sent.log" table scrolls sideways at 768 px inside a .scroll-y that is not a .scroll-x

- **Severity:** low (hunter: low)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/templates/cc/partials/admin_alerts.html:181`
  (`<div class="scroll-y hl-list">` holding `table.tbl.stack-sm`); health.css
  `.hl-list`.
- **Scenario:** At tablet width the table is not stacked yet; overflow-y auto
  forces overflow-x auto, so the table becomes a sideways scroller outside a
  `.scroll-x`, against the port's own section 3.2 rule, with the "result"
  column past the edge.
- **Evidence:** `tools/mobile_sweep.js` at 768: "admin-alerts FAIL content
  scrolls sideways by 111 px", the only FAIL across 12 settings pages at 390
  and 768. Verifier: scrollWidth 825 vs clientWidth 694.
- **Suggested fix:** Wrap the table in `.scroll-x` inside the `.scroll-y` (as
  admin_audit.html does), or stack it at 768 too.

### settings-5: Site settings: the "AI providers" link on the features tab stops working after the first use

- **Severity:** low (hunter: low)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/templates/cc/admin_settings.html:172`
  (`<a class="hi" href="#ai-providers">`); `static/cc/cc.js` openHash bound
  only to hashchange (426); a tab click does not clear `location.hash`.
- **Scenario:** Clicking "AI providers" on the features tab switches tabs.
  Back on features, clicking it again does nothing (the hash is unchanged, no
  hashchange). Same after landing via `/go/ai-providers`, and for the
  "notices" link (`#server-notices`) in Health's open findings.
- **Evidence:** First click: {hash '#ai-providers', ai true, feat false}. After
  the features tab and a second click: {hash '#ai-providers', ai false, feat
  true}.
- **Suggested fix:** Handle clicks on in-page anchors whose target is in a
  tabpanel (call openHash or activate the tab), or clear/replace the hash when
  a tab is activated by click.

### settings-6: Health: dismissing a notice leaves it counted and listed under "open findings"

- **Severity:** low (hunter: low)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/templates/cc/admin_health.html` (open findings tab
  rendered once); `ui_health.py` `POST /partials/health-notices/{id}/dismiss`
  (86-98) re-renders only `#health-notices-body`.
- **Scenario:** Dismissing a problem on "problems the server found" drops it
  there, but the first tab still says "open findings (53)" and lists it until
  reload.
- **Evidence:** Notices tab went from 16 to 15 rows after dismiss; the
  htab-open label read "open findings (53)" before and after, `#hpanel-open`
  still had 53 entries.
- **Suggested fix:** Have the dismiss response also refresh the open-findings
  panel and its count (an oob fragment, or an HX-Trigger that re-fetches it).

### everyday-apps-4: Going into b-roll, music or YouTube downgrades the ccsync_ui_effective cookie to a session cookie, and /ui/preview never updates it, so the SPA's first paint is often the wrong look (CLS ~0.69)

- **Severity:** low (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `broll/web/static/app.js` syncDashboardLook (~311), same code in
  `music/web/static/app.js` ~915 and `ytdl/web/static/app.js` ~3181 (cookie
  written with no max-age); `ui_variant.set_effective_cookie` (skips an equal
  value); `ui_variant.ui_preview` (writes only `ccsync_ui`).
- **Scenario:** (1) Any SPA visit rewrites the 180-day cookie as a session
  cookie; the dashboard never restores the expiry. After a browser restart a
  bookmarked SPA paints classic then flips to terminal. (2) Picking "classic
  look on this browser" or "follow the site setting" from inside an SPA
  redirects back with the old effective cookie, so the first paint is the look
  just left.
- **Evidence:** Network.getCookies: after /transfers the cookie expired in
  180 d; after /broll/ it was "session" and stayed so. Fresh browser straight
  to /broll/: class ''->'cc-chrome cc' at 50 ms, layout shift 0.686.
  `/ui/preview?variant=site&next=/music/`: shift 0.663. Verifier confirmed
  from code (the seed mounts no /broll/). Downgraded: a one-time flash, not a
  functional fault.
- **Suggested fix:** In syncDashboardLook write the cookie with the server's
  max-age (or skip when equal). In /ui/preview set or delete
  `ccsync_ui_effective` on the redirect. Make `set_effective_cookie` refresh a
  cookie that has lost its expiry.

### everyday-apps-6: The 44 px tap rule for tip tags keys on [title], which cc.js removes, so polled rows jump 24 px and the tags end up under 44 px

- **Severity:** low (hunter: low)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/static/cc/phone.css:276`
  (`.tag[title], .led[title] { min-height: var(--tap) }` under pointer:coarse)
  against `static/cc/cc.js` adoptTips (title -> data-tip, then removeAttribute).
- **Scenario:** On a phone, /transfers re-swaps queued rows every 2 s; each
  swap arrives with title= on the tags, the summary row grows 64 -> 88 px, then
  cc.js strips the title and it snaps back. Once stripped, the upload/download
  tags are well under 44 px.
- **Evidence:** Hunter: layout shift 0.0095 every ~10 s from DETAILS.fgroup and
  SPAN.tag; a 20 ms sampler caught 64.28 -> 88.14 -> 64.28. Verifier: 5 ms
  sampler logged 64 -> 88 at 10086 ms and back at 10108 ms; adopted tags 19 px
  tall; no layout-shift entries in its run, so the CLS figure did not
  reproduce.
- **Suggested fix:** Key the tap rule on the surviving attribute
  (`.tag[data-tip], .led[data-tip], .tag[aria-description]`), or run adoptTips
  on the incoming fragment in htmx:beforeSwap.

### a11y-copy-6: Repeated controls with no context: six "fold" buttons, four identical "delete" buttons, 16 "take me there" links

- **Severity:** low (hunter: medium)
- **Verdict:** CONFIRMED
- **Where:** `templates/cc/admin_settings.html:27`, `cc/admin_packages.html:35`,
  `cc/partials/admin_packages.html:25`, `cc/cards_landing.html:27` (fold named
  by `<span class="vh">fold</span>`); `cc/partials/admin_users.html:118-125`
  and the remove/erase-history forms; `cc/partials/home_problems.html` and
  health_notices ("Take me there", "dismiss").
- **Scenario:** Listing buttons on Packages gives "fold, expanded" six times.
  Home, account and health name folds via aria-labelledby, these four do not.
  On Users, "delete", "remove", "erase history" repeat without naming the
  person or computer. Home repeats "take me there" and "dismiss".
- **Evidence:** /admin/packages 6x "fold"; /admin/settings 4x; /admin/users 4x
  "▸ DELETE", 5x "▸ REMOVE", 4x "▸ ERASE HISTORY"; home 16x "TAKE ME THERE",
  17x "▸ DISMISS"; /admin/health 71 "Take me there". Downgraded: the Users and
  Health keys sit in rows next to their subject, so in-context naming passes;
  only the bare folds are truly contextless.
- **Suggested fix:** aria-labelledby the window title id on every fold (as
  `ev_macros.win` / `home_macros.win` do). Add a visually hidden object to
  repeated keys (`<span class="vh"> jsmith</span>` or aria-describedby at the
  row's name cell).

### a11y-copy-7: The 12 px phone floor is overridden by page sheets (11 px at 390)

- **Severity:** low (hunter: low)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/static/cc/home.css:44,83,115` (`.home-page h3.sec`,
  `.tree-count`, `.field > span` at 11px); `settings_fleet.css:40,47`
  (`.sf-pkg .sha`, `.sf-pkg .grp-row td`); `settings_people.css:12`
  (`.sp-caps`); `phone.css:225-270` floor list (bare single-class selectors).
- **Scenario:** Page sheets set 11 px with two-class selectors that beat
  phone.css's 12 px floor, so the tick counter, "move" field labels, Packages
  hashes and group rows, and "mint a token" stay at 11 px at 390, below
  MOBILE_PLAN goal 1.
- **Evidence:** At 390 with mobile and touch emulation: / `div.tree-count`
  11px, `h3.sec` 11px; /project `label.field > span` 11px x3;
  /admin/packages `td span.sha` x4, `tr.grp-row td` x6 at 11px; /admin/users
  `b.sp-caps` 11px. Every other page clean.
- **Suggested fix:** Put the floor for these selectors in each page sheet's
  phone query, or raise phone.css's selectors to match. Extend the CSS-fact
  floor assert to every static/cc/*.css inside max-width 760px and add the
  computed check to mobile_sweep.js.

### a11y-copy-8: D8 slips: confirms name keys in capitals, and Packages says "Press check now there" unquoted

- **Severity:** low (hunter: low)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/templates/cc/partials/admin_suspend_button.html:8`
  ("...and RESUME puts it back."); `cc/partials/admin_users.html:121`
  ("...DISABLE only stops logins."); `cc/partials/admin_packages.html:254,364,472`.
- **Scenario:** D8 names a control by its label in sentence case in double
  quotes. Two new confirms shout RESUME and DISABLE (rendered labels "resume",
  "disable"). The Packages ledes run "check now" into the sentence unquoted
  and name a window by its snake_case id, so "Press check now there to fetch
  them" reads as broken English.
- **Evidence:** Rendered /admin/users hx-confirm values: "Pause syncing for
  jsmith? Their sync plan is kept and RESUME puts it back." and "Delete jsmith,
  their computers and their sync plans? DISABLE only stops logins."
- **Suggested fix:** ...and "Resume" puts it back. / "Disable" only stops
  logins. / Press "Check now" in the From the vendor window to fetch them.
  Extend the vocabulary scan to flag ALL-CAPS words in hx-confirm equal to a
  key label on the page.

### a11y-copy-9: Retired word "machine" in visible Site copy, which the vocabulary scan cannot see

- **Severity:** low (hunter: low)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/templates/cc/admin_settings.html:46` (FIELD help JSON:
  `"sftp_host": "... Usually the same machine as this dashboard ..."`).
- **Scenario:** The SFTP host hint renders as visible text and title with the
  retired word "machine". It lives in a JSON block that site_settings.js
  paints, and `test_sweep_2026_09_04_copy._visible_strings` blanks script
  bodies, so `test_no_retired_word_in_rendered_copy` never sees it. Inherited
  from the classic twin.
- **Evidence:** Rendered /admin/settings at 1440: title "The address uploads
  and proxy downloads connect to. Usually the same machine as this dashboard.
  Example: nas.example.ts.net". Verifier: `_INLINE_CODE_BLOCK`
  (test_sweep_2026_09_04_copy.py:516,538).
- **Suggested fix:** "Usually the same server as this dashboard." Make the
  vocabulary scan read the JSON help maps (or the rendered page).

### a11y-copy-10: The weekly email and alerts say "since never"

- **Severity:** low (hunter: low)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/alerts.py:968-978` (`_age_words`
  returns "never"), used at alerts.py:2095 (feed_stale) and 4436 (builds line).
- **Scenario:** On a fresh site the alert and Monday report say "...has not
  been able to check for new CC Sync builds since never", and the BUILDS
  section "mrivera/RIVERA-LAPTOP has been on 0.9.53 since never". With a stamp
  it reads "since 8 minutes ago", also ungrammatical.
- **Evidence:** `GET /admin/alerts/preview` on the seeded server printed those
  lines, plus "tchen/TCHEN-RIG has been on 0.9.49 since never".
- **Suggested fix:** Branch on a missing stamp ("has never been able to
  check...", "is on 0.9.53 (since when is not known)") and use "for N hours" or
  "since <date>" with an age.

### a11y-copy-11: A customer's show name ships as a placeholder in the new project page

- **Severity:** low (hunter: low)
- **Verdict:** CONFIRMED
- **Where:** `dashboard/templates/cc/partials/project_detail.html:171`
  (`placeholder="a folder from another project, e.g. 2026/FF5/Elections/Interviewees/..."`).
- **Scenario:** Every customer's terminal project page shows the owner
  studio's own series and episode as the example path, against the "no
  customer name in code" rule. Copied from the classic template, but the cc
  template is new in this port.
- **Evidence:** `git show 8b349d4` adds the placeholder (new file, +276); the
  classic `partials/project_detail.html:148` has the same text.
- **Suggested fix:** A neutral example such as
  "e.g. 2026/Show/Episode/Interviews/..." in the cc template, and in the
  classic one when phase 8 lands.

## Refuted

None. Every finding the hunters reported survived verification. Eight were
downgraded by the verifier (mechanism-1, mechanism-2, mechanism-3, settings-2,
everyday-apps-1, everyday-apps-2, everyday-apps-4, a11y-copy-6), and
home-project-9 is PLAUSIBLE rather than confirmed.
