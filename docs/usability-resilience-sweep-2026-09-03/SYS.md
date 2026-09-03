# The whole system as a product and as a distributed system (SYS)

## Summary

The 08-28 sweep's five waves are all in the repo and the code is markedly
better for them: 42 alert kinds, 10 invariants, 8 protection lines, a notices
panel, a recovery page, 28 chaos tests. **None of it has ever told anyone
anything.** Two independent reasons, both cheap to fix: the alert sink
defaults to `none` and nothing anywhere says so (`alerts.py:150`,
`_check_weekly_send` is deliberately silent on that case), and the studio's
own dashboard is behind the repo, so the panels are running nowhere that
matters. Since 2026-08-29 the ledger's discoverers are: the owner (12
entries), CI (4 defects in CR-94), the new chaos suites (2, SYS-18a/b), and
the self-diagnosis layer (0). The two machine discoverers are the ones nobody
planned to lean on.

The recurring shape of the last thirty entries is not a bug class, it is a
**delivery** class. 170 ledger headings say "unshipped"/"NOT YET SHIPPED".
CR-98's whole investigation ended in "already fixed in the repo the owner hit
it in"; CR-94's own lesson is "push before the pile gets to seven commits".
The second-largest shape is new and the 08-28 sweep did not have it:
**the client hides a capability the server allows** (CR-95, CR-96, CR-99 in
one night; a fourth instance is still live at `sidebar.html:14`).

Biggest risk: `release_feed._auto_publish` swallows a `requires_dashboard`
refusal into a `log.warning` (`release_feed.py:690-693`) while
`_check_versions_behind` measures the fleet against what *this* dashboard
published (`alerts.py:1196-1200) - so a customer whose dashboard is one
version too old stops receiving companion updates permanently, and every
surface in the product reports the fleet as current. Best cheap win: a 13th
setup task and a 9th protection line, "who do we tell when something breaks".

## Findings

### SYS-1: 42 checks, 10 invariants and a weekly report, delivered to nobody by default
- **Lens:** both
- **Who:** owner, admin
- **Where:** `dashboard/src/ccsync_dashboard/alerts.py:150` (`"alerts_sink": SINK_NONE`), `alerts.py:1287-1290`, `protection.py:602-686` (8 lines, none about alerting), `setup_engine.py:307-1192` (12 setup tasks, none about alerting)
- **Today:** the vendor default is no sink. `_check_weekly_send`'s docstring: *"Silent on a site whose sink is `none`: `run_cycle` records THAT case `ok=1` ("generated, not sent")"*. That is right for the check and wrong for the product: a customer who never opens Settings -> ALERTS has every detector in this system running into an empty room, and the one panel whose stated principle is "a safety mechanism this server cannot positively verify renders as MISSING, never as silence" (SYS-14, built) does not carry a line for the mechanism that delivers all the others. The setup wizard has a "Protect your data" task for snapshots and nothing for "who do we tell".
- **Proposed:** (a) a 9th `ProtectionLine("alerts_sink", "somebody is told when this server finds a problem", …)`, `error` severity, green only on a configured sink whose last send succeeded; consequence copy: *"This server checks 42 things every few minutes. With nobody to tell, the first anyone hears of a stopped sync is an editor asking."* (b) a 13th setup task, `id="alerts"`, title `Who should we tell?`, one address or webhook plus `[ SEND A TEST ]`, skippable but recorded as skipped. (c) while the sink is `none`, the home page's PROBLEMS panel carries a standing amber line: `[ NOBODY IS BEING TOLD - SET AN ADDRESS ]` linking to Settings -> ALERTS.
- **Effort:** S   **Value:** critical   **Confidence:** high
- **Related:** SYS-8/SYS-14 (both built); `docs/SELF_DIAGNOSIS.md`

### SYS-2: A dashboard one version too old silently stops the whole fleet updating, forever
- **Lens:** resilience
- **Who:** owner, admin
- **Where:** `dashboard/src/ccsync_dashboard/release_feed.py:690-693`, `package_store.py:33-52`, `companion/src/ccsync_companion/config.py:173` (`REQUIRES_DASHBOARD = "0.7.23"`), `alerts.py:1190-1220`
- **Today:** REL-4/SYS-13's refusal is correct and lands in the right place. Its *output* is `log.warning("release feed auto-publish of %s/%s %s failed: %s") ; continue`. On a `policy = "current"` site (the zero-touch default, `site.toml:49`) nobody clicks anything, so nobody ever sees the 409. Worse, the derived alert cannot see it either: `_check_versions_behind` counts rows in `companion_packages` - what *this* dashboard published - so with the feed refused, `published` is stale, every machine is "0 releases behind", and the fleet grid, the weekly report and the Packages page all agree that everything is current. The asymmetry that makes this reachable is structural: pathway B publishes companions autonomously with no password, and *"What B deliberately does not sweep: the dashboard bundle"* (`docs/RELEASE_PATHWAYS.md:96-99`), which is an admin click.
- **Proposed:** three small pieces. (1) An alert kind + notice `feed_publish_refused`: *"A new CC Sync build (0.9.64) is available but cannot be installed here: it needs dashboard 0.7.23 and this one is 0.7.15. Update the dashboard first: Settings -> PACKAGES -> DASHBOARD."* Written from the `PackageStoreError` already in hand at `:691`. (2) An alert kind `dashboard_behind` fed by `dashboard_update.status()`'s `code_updates`, which already computes it (`dashboard_update.py:1455-1489`) and renders it on exactly one page. (3) `_check_versions_behind` compares against the newest *offered* feed record, not only the published one, so "the fleet is behind the vendor" survives a dashboard that refuses to publish.
- **Effort:** S   **Value:** critical   **Confidence:** high
- **Related:** REL-4/SYS-13 (built), REL-11 (feed unreachable - this is the feed reachable and refused)

### SYS-3: The client disables what the server allows - three times in one night, and a fourth is still live
- **Lens:** both
- **Who:** admin, owner
- **Where:** live: `dashboard/templates/partials/sidebar.html:12-16`; fixed siblings: `admin_assignments.html:120-123` (CR-95), `ytdl/web` picker (CR-96), `admin_settings.html` readonly (CR-99). Server side: `ui.py:869-880` (`partial_toggle` refuses only the TICK branch), `api.py:2232-2241` vs `api_untick` at `:2290` (no base-only refusal at all)
- **Today:** CR-95 fixed the assignments grid: *"a wired cell is `disabled` only when it is NOT already ticked"*. The project sidebar - the other place a tick is rendered - still does `{% if toggle_editor_base %}disabled` unconditionally, ticked or not, and `partial_toggle`'s own comment says out loud *"the checkbox is rendered disabled for a base rig, and this is the path a stale [tick uses]"*. So a base-rig account with a stale tick cannot clear it from the sidebar, exactly as CR-95 described for the grid. Three of the owner's five reports on 2026-08-30 and 2026-09-02 were this one shape (a capability the API allows, hidden by the page that renders it), and it is invisible to every runtime check because nothing is wrong with the state.
- **Proposed:** (a) fix `sidebar.html` on CR-95's rule (disabled only when not ticked; title explains the untick). (b) Adopt a house rule and pin it: **a control is never pre-emptively disabled for a reason the server also enforces** - render it live, let the route refuse, show the refusal `detail`, which is already written in editor English at `api.py:2238-2240`. (c) A dashboard test that walks `templates/` for `disabled`/`readonly` (11 + 1 occurrences today, small enough to enumerate) and asserts each is either cosmetic or has a named counterpart predicate in the route it guards - the same parity discipline `server/tests/test_cross_component.py` already applies to duplicated truths.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** CR-95, CR-96, CR-99

### SYS-4: GOTCHAS §15 hands other Resolve clients a guard weaker than the rule it documents
- **Lens:** resilience
- **Who:** developer
- **Where:** `docs/GOTCHAS.md:980-985` vs `companion/src/ccsync_companion/script_server.py:323-337`, `resolve_bridge.py:343-352`
- **Today:** §15's copy-pasteable block for *"any other Resolve client on the same machine (the MCP server, the MulticamPipeline tools)"* is `from script_server import is_starting; if is_starting(): return None`. `is_starting()` covers STARTING only. `ready_to_connect()`'s own docstring says why that is not enough: *"STARTING and ABSENT both say no: in the first a connection kills the server, in the second scriptapp() sits in a multi-second retry loop that becomes the first case the moment the server appears"* - and `connect()` returns None for both (`:343-345`, `:346-352`, "the 0.9.45 failure"). The user-level rule this repo exported to every Resolve project names `ready_to_connect()` and says explicitly "not on 'no listener'". So the document that exists to spread the fix spreads half of it. Compounding: CR-68's own "not done" list still reads *"The Resolve MCP server's copy is in its working tree, uncommitted"* (`KNOWN_BUGS.md:2873-2876`), thirteen days on, and that MCP server's tools "automatically launch Resolve if it is not running".
- **Proposed:** replace the snippet with `ready_to_connect()`, one line, and add the sentence about ABSENT. Then close CR-68(b): commit the MCP server's copy and record the version in the ledger, because one unguarded client is enough to break scripting for all of them.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** CR-68; global rule in `~/.claude/CLAUDE.md`

### SYS-5: The one document you hand a customer describes a product that has not shipped for a fortnight
- **Lens:** usability
- **Who:** owner, editor
- **Where:** `docs/HOW_IT_WORKS.md:377-389` vs `companion/src/ccsync_companion/tray.py:3426-3444`
- **Today:** §6.6 "The rest of the tray menu" lists nine items. The real menu is *Sync now / [⚡ Take fleet jobs now] / Pause syncing / Open my sync drive / Open dashboard / Settings… / Quit*. Five of the doc's rows ("Open my project folder", "Grade from server originals", "Copy diagnostics for your admin", "Open log", "Advanced") stopped being menu items at CR-88 and live in the Settings window, which the document does not mention at all. Also absent from the customer explainer: upload-only ticks (CR-85 - the phrase does not occur), fleet jobs and whisper, and PROBLEMS THE SERVER FOUND, i.e. the panel that answers the document's own troubleshooting table.
- **Proposed:** rewrite §6.6 from `tray.py:3426-3444` and add three short sections: "The Settings window" (five sections, `settings_window.py:353-601`), "Sending originals up without bringing the project down" (upload-only), and "What the server tells you it has found". Add a doc test in the dashboard suite pinning the menu labels in HOW_IT_WORKS against `tray.py`'s literals, the way the copy-rule scan tests already work - a customer-facing document is exactly the kind of truth that drifts silently.
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** CR-88, CR-85

### SYS-6: Four pages answer "is my fleet all right", and the Settings strip is twelve flat entries
- **Lens:** usability
- **Who:** owner, admin
- **Where:** `dashboard/templates/partials/settings_nav.html:18-31`, `templates/fleet.html:16` (notices), `admin_alerts.html`, `admin_invariants.html`, `admin_protection.html`
- **Today:** the strip has grown from the owner's 2026-08-18 five ("users, assignments, transfers, setup, the installer") to twelve in twelve days, six of them diagnostic surfaces from one sweep: TIMELINE, ALERTS, JOBS, INVARIANTS, PROTECTION, RECOVERY. The template's own comment concedes the shape: *"twelve entries wrapped onto four rows would push the page they belong to off the bottom of a phone"*. Each page is well built; nothing composes them, so "is everything OK?" is four pages plus the home notices panel plus the fleet grid's chips, and an owner who is not an engineer has no way to know which one is authoritative.
- **Proposed:** (a) one `[ HEALTH ]` page that renders, in one ranked list, the open notices, the RED/AMBER alert findings, broken invariants and missing protection lines, each row carrying the existing `diagnosis` + `fix` strings verbatim and linking to its detail page - no new data, one template. Make it the SETTINGS landing. (b) Group the strip into three labelled runs: *Run the fleet* (SITE, USERS, ASSIGNMENTS, TRANSFERS, PACKAGES, JOBS), *Is it healthy* (HEALTH, ALERTS, INVARIANTS, PROTECTION), *When it breaks* (RECOVERY, TIMELINE, SETUP). (c) The topbar's alert chip should point at HEALTH, not at ALERTS.
- **Effort:** M   **Value:** high   **Confidence:** high

### SYS-7: 170 headings say "unshipped" and nothing in the product measures the gap
- **Lens:** both
- **Who:** owner, developer
- **Where:** `KNOWN_BUGS.md` (170 of 182 `###` headings mentioning ship state say unshipped / NOT YET SHIPPED / NOT YET DEPLOYED / NOT YET APPLIED); `tools/check_deploy_drift.ps1`; `CLAUDE.md:319`
- **Today:** the drift doctor is a PowerShell script on the base rig, run by hand, comparing repo vs built vs installed vs live. A second customer has no base rig and no repo, so for them it does not exist. In-product, the dashboard knows its own `VERSION`, every machine's `companion_version`, the published packages and the feed's records - four of the five numbers - and shows them on three different pages with no verdict. CR-98 is what this costs at human scale: a fault reported, investigated, and closed with *"already fixed in the repo the owner hit it in - what was missing was deployment"*. CR-94's own lesson is the developer half: seven commits sat unpushed and the first CI run found four defects, two of them latent races this hardware kept winning.
- **Proposed:** (a) a `[ WHAT IS RUNNING ]` box on the HEALTH page: dashboard version vs newest feed dashboard record; current companion vs newest feed companion record; how many machines are on each build, with the date each was published. One sentence when they disagree, using SYS-2's wording. (b) A ship-time gate mirroring CR-94's lesson: `ship.cmd` and `publish_latest.py` refuse (with `-AllowBehind`) when `git rev-list --count origin/main..HEAD` exceeds 3 or the newest green CI run predates the tip - the pile is what makes the failures interact.
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** CR-94, CR-98; ledger class B

### SYS-8: The newest per-machine settings are reachable only by hand-editing a TOML file on the editor's PC
- **Lens:** usability
- **Who:** admin, editor
- **Where:** `docs/CONFIG.md:672-735` (`jobs_enabled`, `jobs_kinds`, `jobs_volunteer_minutes`, `cards_agent`), `companion/src/ccsync_companion/settings_window.py:353-601` (sections THIS COMPUTER, SYNC LANES, YOUTUBE, ADVANCED, HELP - no jobs, no cards)
- **Today:** CONFIG.md says it plainly: *"A comma string works too, because config.toml is edited by hand"*. To keep one laptop out of `whisper`, or to turn the Timeline Cards role on (which must be on exactly one computer in the fleet), somebody remotes into that machine and edits `~/.ccsync/config.toml`. Every other per-computer decision got a window at CR-88 precisely because "the role belongs to the computer" and the person at that computer is the one who decides. The dashboard, which schedules the jobs and knows which machines are capable, cannot change any of it.
- **Proposed:** (a) a sixth Settings section, `FLEET JOBS`: `[ ] Let the fleet use this computer` (jobs_enabled), a checkbox per kind (`capabilities.py:64`'s list, `conform`/`resolve-edit` never offered), and the volunteer minutes - the tray item that lends the machine already exists, so this is the standing version of a control editors already meet. (b) `cards_agent` as a dashboard-side per-machine switch delivered on the command channel, with the "exactly one computer" rule enforced server-side rather than by prose, since the server is the only party that can see all of them.
- **Effort:** M   **Value:** high   **Confidence:** high

### SYS-21: The usability debt, counted: one settable setting, 122 documented keys, ~127 balloon texts
- **Lens:** usability
- **Who:** editor, admin
- **Where:** `companion/src/ccsync_companion/settings_window.py:194` (the only `config_mod.set_value` in the whole window), `docs/CONFIG.md` (122 documented `| \`key\` |` rows), `tray.py:1810-1884` (13 `Sync:` states), `tray.py:2976-3013` (8 tooltip states), `dashboard/templates/partials/settings_nav.html:18-31` (12 admin tabs)
- **Today:** an editor's surface is 10 tray items (18 possible), 5 Settings sections, ~32 distinct dialog kinds, roughly 127 distinct balloon texts over 160 call sites and ~75 distinct status-line strings, three icon colours with no legend anywhere in the product, plus four browser SPAs. **The Settings window can change exactly one setting** - `mode`, wired vs remote - and everything else in `CONFIG.md`'s 122 keys is a hand-edited TOML file on a machine where a bad write took the companion to ALL DEFAULTS once already (APP-4). By comparison a competing product (Resolve's own Project Server, Dropbox/Frame.io style sync) asks an editor to learn: sign in, pick a project, and a status icon. The debt is not that there are many strings - most are well written - it is that **the number of *concepts* an editor must hold is unbounded and undefined**: lanes A/B/C, ticks, upload-only, wired vs remote, machine vs person, halt, breaker, EULA gate, jobs, LUT link, ingest, Send to Resolve. None of them has a "what is this?" anywhere in the product; `HOW_IT_WORKS.md` explains most and is not linked from the tray, the Settings window or the dashboard.
- **Proposed:** two cheap moves, no new mechanism. (a) A `[ WHAT DO THESE MEAN? ]` entry in the Settings window's HELP section and a `?` in the dashboard topbar, both opening the deployed `HOW_IT_WORKS.md` (it is already customer-facing prose; serve it from the dashboard at `/help` and deep-link the glossary anchors from the four places the words appear: the sync line, the lane lines, the fleet chips, the tick modes). (b) Promote the ten config keys an editor or admin plausibly changes into the Settings window as real controls - `drive_reminder_minutes`, `proxy_gen_enabled`, `jobs_*` (SYS-8), `project_rotation_seconds`, `poll_interval` - and mark the rest of `CONFIG.md` explicitly "support only, edited with the tray closed". Today the split between "a control" and "edit a file" is not a judgement about who needs it; it is the order things were built in.
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** SYS-5, SYS-8, APP-4

### SYS-9: A safety document is wrong about a safety mechanism
- **Lens:** resilience
- **Who:** admin, owner
- **Where:** `docs/BACKUP_RESTORE.md:359-360` and `:524-525` vs `companion/src/ccsync_companion/sync/lane_guard.py:73-74`, `config.py:240-241`
- **Today:** BACKUP_RESTORE says `.ccsync-trash` *"is never pruned … an open defect"* and lists it among four things that "grow forever". It has been pruned at 14 days / 50 GB since the CR-48 era, and `SYNC_SAFETY.md:100-106` documents that correctly. An admin reading the backup runbook to answer "can I get that file back" is told the wrong retention in the wrong direction: they will look for a copy that was pruned a fortnight ago.
- **Proposed:** correct both lines and cite `lane_guard.DEFAULT_TRASH_MAX_AGE_DAYS`. Then close the reverse gap the invariant registry already admits: `versioning_agrees` (invariant 8) is permanently `NOT CHECKED` because editor-side `.stversions` is 30 d (`syncthing_admin.py:163-164`) and NAS-side is 365 d (`provision.py:247-248`). Pick one number, report the companion's, and the invariant becomes checkable.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** R5 (open since the 08-11 pass)

### SYS-10: The two non-human discoverers this system has are the two it invested in least
- **Lens:** resilience
- **Who:** developer
- **Where:** `.github/workflows/ci.yml` (`workflow_dispatch`/push, per `docs/CI.md`), `companion/tests/chaos/test_fault_injection.py` (14 tests), `dashboard/tests/chaos/test_fault_injection.py` (14 tests)
- **Today:** since the sweep, CI found four defects in one run (CR-94) and the chaos suites found two the five build packages had missed (SYS-18a, SYS-18b) - *"both were found by fault injection rather than by a person noticing, which was the point of the exercise"*. Everything else in the last thirty entries was found by the owner using the product. Against ~10,600 test functions in 421 files, 28 are fault injections, and three of the four CR-94 failures existed only because the base rig is one Windows box.
- **Proposed:** parameterise the two chaos modules over the shapes of the last thirty entries rather than the last sweep's: a dashboard N versions behind a companion record (SYS-2, assert a notice, not a log line); a mounted app's manifest fetched with no session (CR-100); a template rendering a control the route would allow (SYS-3, assert no `disabled` without a matching predicate); a page whose cached list is nulled by a context switch while a throttle is still running (CR-101); a Tk dialog whose closure cycle is collected on a worker thread (CR-93, on Windows where it can run). Nine more tests, each closing a shape the ledger has now paid for twice.
- **Effort:** M   **Value:** high   **Confidence:** high

### SYS-11: An outer gate can shadow a mounted app's open assets, and the checker checks the wrong copy
- **Lens:** resilience
- **Who:** admin, developer
- **Where:** `tools/check_mobile_origin.py:191-209` (`check_manifest` fetches `origin + "/manifest.webmanifest"` only), `dashboard/src/ccsync_dashboard/app.py:48-...` (`_OPEN_EXACT`)
- **Today:** CR-100 is fixed by adding two literal paths to `_OPEN_EXACT`, and `dashboard/tests/test_pwa.py` pins them. The *class* is not closed: the origin checker still asks only the dashboard's own manifest, which has been open since M4, so it will pass again for the next mount that ships a PWA (cards was the second; b-roll's client-share prefix is a third candidate). The generalisation is the same one REL-7 already learned once - a parity check that compares a thing against itself.
- **Proposed:** make `check_mobile_origin.py` take the mount list from `GET /api/v1/health` (or a constant it shares with `app.py`) and run `check_manifest` per mount, and make `test_pwa.py` enumerate mounts rather than name paths: for every mounted app that serves a `manifest.webmanifest`, assert the outer gate does not 303 it.
- **Effort:** S   **Value:** med   **Confidence:** high
- **Related:** CR-100, REL-7

### SYS-12: `docs/README.md` promises a complete index and is missing ten documents, two of them load-bearing
- **Lens:** usability
- **Who:** developer, owner
- **Where:** `docs/README.md:3` ("Every document in `docs/`, one line each"), `:6` ("Index written 2026-08-17")
- **Today:** unlisted: `ANDROID.md`, `FILE_MOVES.md`, `LIBRARY_WALK_PLAN.md`, `MOBILE.md`, `MOBILE_PLAN.md`, `RELEASE_PATHWAYS.md`, `TIMELINE-CARDS-INTO-CCSYNC.md`, `TRAY_MENU_LATENCY.md`, `UPLOAD_ONLY_TICK.md`, `YTDL_TERMS_AND_QUEUE.md`. `CLAUDE.md` names `FILE_MOVES.md` and `UPLOAD_ONLY_TICK.md` as the documents you must read before touching those paths, and `RELEASE_PATHWAYS.md` exists *because* a session could not find the right release route. Nothing about jobs, cards, mobile or android appears anywhere in the index.
- **Proposed:** add the ten rows, and add a `tools/` test (that suite is stdlib-only and already runs) asserting every `docs/*.md` appears in `docs/README.md` - the index's promise is machine-checkable and this is the third document in this report whose only defect is that nothing checks it.
- **Effort:** S   **Value:** med   **Confidence:** high

### SYS-13: `ARCHITECTURE.md` contradicts itself in the same paragraph and omits the last two weeks
- **Lens:** usability
- **Who:** developer, owner
- **Where:** `docs/ARCHITECTURE.md:122` ("up to **three** mounted sub-applications") vs `:131-134` (four in the diagram), `:150-171` (four described), `:172` ("all **four**")
- **Today:** besides the count, the 660-line system overview has zero mentions of `notices`/`alerts` self-diagnosis, `supervisor.py`, the mobile port or android, and "Further reading" omits `SELF_DIAGNOSIS.md`. The jobs and cards sections are current and good, so the file is being maintained per-feature and never re-read whole.
- **Proposed:** fix `:122`; add a short "The server diagnoses itself" section pointing at `SELF_DIAGNOSIS.md`, and one line each for the supervisor and the phone port. Add the 08-28 SYS-19 blast-radius table while in there - it is still the one thing an operator needs first and is still only inferable from code.
- **Effort:** S   **Value:** med   **Confidence:** high

### SYS-14: `CLAUDE.md` still says there is one ship command; the repo learned otherwise on 2026-08-31
- **Lens:** usability
- **Who:** developer
- **Where:** `CLAUDE.md:319-327` ("**There is one command. It is `tools\ship.cmd`.**") vs `docs/RELEASE_PATHWAYS.md:10-24, 36`
- **Today:** RELEASE_PATHWAYS exists because that framing cost a session half an hour reconstructing a ship it could not run (the password is `Read-Host` by design). Pathway B is *"the autonomous one"*, it publishes all four artefacts (pathway A publishes two), and it is how 0.9.61 actually reached the fleet. CLAUDE.md mentions `publish_latest.py` further down but subordinates it, and CLAUDE.md is the file every session reads first.
- **Proposed:** replace the "one command" paragraph with two sentences and a pointer: *"Two pathways, and which one applies depends on who is running it: `docs/RELEASE_PATHWAYS.md`. At Alex's terminal, `tools\ship.cmd`. Anything unattended, CI + `tools/publish_latest.py`."*
- **Effort:** S   **Value:** med   **Confidence:** high

### SYS-15: The ledger's ids are the system's vocabulary and two of them are ambiguous
- **Lens:** usability
- **Who:** developer
- **Where:** `KNOWN_BUGS.md:8288` and `:8445` (both "CR-91"), `:3254` and `:3350` (both "CR-93"), `:2903`/`:2918` (CR-71 before CR-70)
- **Today:** the 08-28 sweep flagged the CR-91 collision and it is unchanged. 60 citations of `CR-91` exist outside the ledger - `sync/base.py:45`, `rclone_lane.py:173`, `reporter.py:249`, `drive_reminder.py:30,124`, `shutdown_guard.py:401` - and all of them mean the lane-stall entry, while the ledger's first CR-91 is the phantom-editor one. A reader who greps the ledger for CR-91 lands on the wrong entry.
- **Proposed:** rename the older one CR-91a in its heading (nothing cites it), and CR-93's continuation to CR-93b; add a one-line rule at the top of the ledger - *ids are never reused; a follow-up gets its own number and links back* - since CR-95/CR-96 already follow it correctly.
- **Effort:** S   **Value:** med   **Confidence:** high

### SYS-16: A fix narrower than the rule it came from is this system's most reliable repeat offender
- **Lens:** resilience
- **Who:** developer
- **Where:** CR-27 -> CR-27a; CR-28 -> CR-95 (-> SYS-3's sidebar, still open); CR-72 -> CR-96; CR-93 -> CR-93 continued; SYNC-3/SYNC-11/MEDIA-21 (CR-90's lesson, applied at three further sites weeks later)
- **Today:** four of the last fifteen entries are follow-ups whose text says the earlier fix was right and reached one of N places. The 08-28 synthesis named this as theme 3 ("the guard exists, but only in one of the N places it belongs") and the pattern survived the sweep that named it, because nothing in the process asks the question.
- **Proposed:** a required line in the ledger entry template, filled in at fix time and grep-able: **`Other sites of this shape:`** - the answer being either a list with commit refs or the word `none, and here is why`. Cheap, procedural, and it is the only one of these findings that needs no code. Pair it with the mechanical half where one exists: for a predicate duplicated between a route and a template (SYS-3) or between components, a parity test.
- **Effort:** S   **Value:** med   **Confidence:** med

### SYS-17: The shortest invariant list that would have caught the most of the last thirty
- **Lens:** resilience
- **Who:** developer, admin
- **Where:** `dashboard/src/ccsync_dashboard/invariants.py:652-746` (10 built)
- **Today:** the ten built cover state that has gone wrong *inside* one deployment. Every one of the last thirty entries that a machine could have caught is about the relationship between **what is written, what is deployed, and what is rendered** - and none of the ten looks there.
- **Proposed:** five more, all computable from data the dashboard already holds. **11 `fleet_current_with_vendor`** - the newest companion record the feed offers is published here and is current (SYS-2). **12 `dashboard_meets_requirements`** - this dashboard's VERSION is at or above the `requires_dashboard` of every record in the channel. **13 `mount_assets_open`** - every mounted app's manifest and icon answer 200 with no session (CR-100). **14 `cards_tree_matches_source`** - a hash of the served `cards-web` tree against the checkout it was shipped from (CR-101 was hand-deployed with a `.bak`, and the next `install_dashboard_app.py` run is the only thing that reconciles it). **15 `alerts_deliverable`** - a sink is configured and its last send succeeded (SYS-1). Add them one at a time; the registry is data and each is a function.
- **Effort:** M   **Value:** high   **Confidence:** med

### SYS-18: What the second customer hits, in order
- **Lens:** usability
- **Who:** owner
- **Where:** `docs/ZERO_TOUCH_PLAN.md:282` (WP C not built), `KNOWN_BUGS.md:10095` (CR-99: WP B/C exist on nobody's deployment), `docs/COMMERCIAL_READINESS.md:210` (CR-10 never applied to either NAS), `protection.py:448-456`, `alerts.py:150`
- **Today**, walking the first day of a second site with the current code: (1) they need a NAS admin account with a known password, because `DASH_AUTH_METHOD=local` exists but `smb` is still the default; (2) `DASH_RELEASE_PUBKEYS` must be set by hand or every publish 503s - the protection panel says so, but only after they find the panel; (3) no snapshot task exists (CR-10 has never been applied on either of the vendor's own two NASes, which is the strongest possible evidence that it will not happen at a customer's); (4) `alerts_sink` is `none`, so nothing they set up will tell them anything (SYS-1); (5) the dashboard is the one component with no unattended update path, and going one version stale silently freezes the fleet's companion updates (SYS-2); (6) `HOW_IT_WORKS.md`, the document they hand their editors, describes a tray menu no shipped build has (SYS-5); (7) their first support question - "why is nothing syncing" - now has a real answer on the fleet page, which is the sweep's biggest win and the one thing on this list that is already right.
- **Proposed:** treat items 2-4 as a single **first-boot completeness gate**: the setup wizard does not report "Done" while a release key, a snapshot task and an alert destination are absent; each is a task with a `[ SKIP - I understand ]` that records the skip and leaves the protection line red. The wizard already has this shape (`setup_engine.py`'s snapshots task); it needs two more tasks and a refusal to say Done.
- **Effort:** M   **Value:** high   **Confidence:** high

### SYS-19: `MULTI_BASE_RIG_PLAN.md` and `COMMERCIAL_READINESS.md` are frozen snapshots written in the present tense
- **Lens:** usability
- **Who:** developer
- **Where:** `docs/MULTI_BASE_RIG_PLAN.md:48-49` ("`effective_mode()` answers `base` when **either source says so**") vs `:32-38` and `companion/src/ccsync_companion/app.py:4011-4032` ("CONFIG ONLY since 2026-08-27"); `docs/COMMERCIAL_READINESS.md:309` ("`install_dashboard_app.py` still deploys bind-mount mode only") vs `server/install_dashboard_app.py:672` (`STACK_MODES = ("bind", "image")`)
- **Today:** the plan contradicts itself three sections apart and contradicts the code; its WP2 claims schema v26, which is the lane B breaker resume. COMMERCIAL_READINESS's items 1, 5, 9, 10, 11, 15 all still read "DONE in repo, unshipped" although several shipped weeks ago. Both are read as status by anyone new.
- **Proposed:** date-stamp the header of each ("**Status as at 2026-08-17; not maintained - check the ledger**") or bring the status lines current. For COMMERCIAL_READINESS specifically, replace the per-item "unshipped" with a link to the ledger id, which is the thing that is maintained.
- **Effort:** S   **Value:** med   **Confidence:** high

### SYS-20: `projects_dir` is still half-wired, exactly as the 08-19 audit found
- **Lens:** resilience
- **Who:** owner
- **Where:** `server/common.py:199` (the only reader of the site key), absent from `site_store.py` entirely; hard-coded `"Projects"` survives at `sync/lane_guard.py:70`, `manifest.py:87,156`, `proxy_scan.py:527`, `broll_fetch.py:78`, `fixer.py:391`, `file_moves.py:166`, `sync/borrowed_folders.py:47`, `sync/rclone_lane.py:2148,2266-2269,3180`, `app.py:4557-4558`
- **Today:** setting `[tree] projects_dir` still changes the server's behaviour and nothing else's, and the manifest never carries it, so a customer who sets it gets a fleet that silently syncs nothing - a silent breakage, not a refusal. Unchanged since `TREE_LAYOUT_AGNOSTICISM.md` documented it on 2026-08-19.
- **Proposed:** until TREE_LAYOUT_PLAN lands, make it a refusal: `settings`/`site_store` boot check rejects a `projects_dir` other than `Projects` with *"this build only supports a tree whose projects live in `Projects`"*. A key that cannot work should not be settable.
- **Effort:** S   **Value:** med   **Confidence:** high

## Still open from 08-28

- **CR-10** - snapshot schedule never applied to either NAS. Not built (the panel that names its absence is built; the schedule is not).
- **R5** - `.stversions` 365 d NAS-side vs 30 d editor-side. Not reconciled; invariant 8 is registered as permanently NOT CHECKED because of it.
- **CR-68(b)** - the Resolve MCP server's copy of the guard is still uncommitted in that repo's working tree.
- **SYS-9** - built, all ten invariants; the five in SYS-17 above are the next layer, not a re-report.
- **SYS-6 / SYS-13 (canary, `requires_dashboard`)** - built; SYS-2 above is the hole in the second one's *output*, not in the guard.

## Cross-cutting notes

- **For the dashboard agent:** `release_feed._auto_publish` (`release_feed.py:690-693`) is the single highest-value line in that file - a refusal with a well-written reason, thrown into a log on the one path designed to run with nobody watching.
- **For the companion agent:** the tray's one-line "why" (`tray.py:1810-1852`) is genuinely excellent and is the model for the dashboard's HEALTH page in SYS-6 - one sentence, priority-ordered, always non-empty.
- **For the docs agent:** `BACKUP_RESTORE.md:359-360` (SYS-9) is the one doc error with a safety consequence; everything else in SYS-12/13/14/19 is hygiene.
- **For the release agent:** the dashboard is the only component with no unattended update path, and it gates every companion update through `requires_dashboard`. Whatever pathway B becomes for the dashboard bundle, it should land before the next customer.
- **Observed pattern, restated for this sweep:** the 08-28 report's closing line was "the gap is applying an existing pattern to the second and third place it belongs". Twelve of the twenty findings above are that same sentence with the pattern being one the sweep itself built: a notice instead of a log line (SYS-2), a protection line for an unverifiable mechanism (SYS-1), a parity test for a duplicated truth (SYS-3, SYS-11, SYS-12), an invariant for a fact that must stay true (SYS-17).
