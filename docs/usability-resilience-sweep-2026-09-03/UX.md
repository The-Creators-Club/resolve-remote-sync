# End-to-end journeys across every surface

## Summary

The individual surfaces are in much better shape than they were on 08-28: the
wizard now opens on THE LAST INSTALL DID NOT FINISH, `editor_status` has a
freshness rule, `blocked_report`/`why_not_syncing` give a machine a plain
sentence on both ends, and the tray's dangerous role switch is confirmed with
its consequence. What is NOT in good shape is the seams between them. The
2026-08-27 tray reduction moved `Copy diagnostics`, `Open log` and the whole
`Advanced` submenu into a Settings window, and roughly twenty editor-facing
sentences still send the editor to a tray menu that no longer has them - the
single most-hit dead end in the product, and the cheapest fix in this report.
Terminology has drifted in four dimensions at once (tick/plan/assignment,
machine/computer/device, wired/base/physically-connected, halt/pause/stop),
and there is now ZERO in-product help: nothing in the companion, the
dashboard or the SPAs links to a single document, so `docs/HOW_IT_WORKS.md`
(788 lines, written as the customer explainer) is unreachable by any user.
The biggest risk is journey 4: the only path for customer #2 is a hand-edited
compose file plus `docker compose exec`, from a doc that labels itself DRAFT,
and 51 dialog titles hardcode `ccsync-companion` / `CCSYNC.EXE` in a product
that otherwise brands everything from the site manifest.

## Findings

### UX-1: ~20 editor-facing sentences point at tray menu items that were removed on 2026-08-27
- **Lens:** usability   **Who:** editor
- **Where:** `companion/src/ccsync_companion/tray.py:3244-3250` (the menu's own docstring: "The three lane lines, every advisory line, YouTube, Advanced and its submenu all moved to settings_window.py"), `tray.py:3302-3443` (the ten items: no Copy diagnostics, no Open log, no Advanced); the strings: `tray.py:463`, `:478`, `:484`, `:490`, `:496`, `:951`, `:1160`, `:1408`, `:1648`, `:1770`, `:2395`, `:2471`, `:2503`, `:2546`, `app.py:2694`, `:2817`, `:3055`, `:3197`, `:3288`, `:3313`, `:3386`, `:4725`, `:5087`, `:8374`, `:8873`, `fixer.py:1187`, `identity.py:538`, `resolve_journal.py:296`, `loopback_guard.py:112`, `popup.py:1204`
- **Today:** The editor hits an error and reads `"Something went wrong. Tray → Copy diagnostics for your admin."` (`tray.py:463`), or `"A project folder was deleted on this machine while still ticked. Untick it on the dashboard, or use Advanced → Remove a project from this machine."` (`tray.py:484`), or `"this request was refused by the CC Sync companion -- see its log (Tray > Open log) for the reason"` (`loopback_guard.py:112`). They right-click the tray and there is no Copy diagnostics, no Open log and no Advanced. The real path is Settings… > HELP > `[ COPY DIAGNOSTICS FOR YOUR ADMIN ]` (`settings_window.py:591`) and Settings… > ADVANCED (`settings_window.py:587`).
- **Proposed:** One constant per destination in `tray.py` (`DIAG_PATH = "Settings > Help > Copy diagnostics"`, `LOG_PATH = "Settings > Help > Open log"`, `ADV = "Settings > Advanced"`) and interpolate. Copy: `"Something went wrong. Open Settings > Help > Copy diagnostics and send it to your admin."` Add a companion test that fails on the literal `"Tray →"`/`"Tray >"` followed by any label not in the ten-item menu, the way the em-dash scan tests work.
- **Effort:** S   **Value:** critical   **Confidence:** high
- **Related:** CR-88 (the ten-item layout); no 08-28 finding covers this, the menu reduction post-dates it.

### UX-2: "⚠ NOT SET UP: nothing will sync (Copy diagnostics for your admin)" is a disabled menu item
- **Lens:** usability   **Who:** editor
- **Where:** `companion/src/ccsync_companion/tray.py:3331-3334`
- **Today:** The one line a broken first-run editor sees is rendered `MenuItem("⚠ NOT SET UP: nothing will sync (Copy diagnostics for your admin)", None, enabled=False)`. The label names an action and the item is greyed out and does nothing when clicked. It is also the ONLY hint they get - the sync line beside it says only `"Sync: not set up yet"` (`tray.py:1839`) and names no problem.
- **Proposed:** Make it a live item that runs `action_copy_diagnostics`, and put the first blocking problem's own sentence in the label: `snap["problems"]` already carries them. Copy: `"⚠ NOT SET UP: <first problem>. Click to copy diagnostics for your admin"`.
- **Effort:** S   **Value:** high   **Confidence:** high

### UX-3: Nothing anywhere in the product links to any documentation
- **Lens:** usability   **Who:** editor, admin, owner
- **Where:** zero matches for `EDITOR_SETUP` / `HOW_IT_WORKS` / any doc URL across `companion/src`, `dashboard/src`, `dashboard/templates`, `dashboard/static`, `broll|music|ytdl/web/static`, `onboarding/` (the only two hits are comments: `app.py:2604`, `onboarding/steps.py:1816`); `settings_window.py:588-601` ("HELP" = Copy diagnostics, Open log, the update offer, a version line)
- **Today:** The Settings window's HELP section contains no help. The dashboard's twelve-entry settings strip (`partials/settings_nav.html`) has no help entry, the login page has no "no account? ask your admin" line, and `docs/HOW_IT_WORKS.md` (788 lines, the customer explainer) is reachable only by someone with the repo. An editor whose only next step is "ask your admin" is a support ticket by construction.
- **Proposed:** Serve `HOW_IT_WORKS.md` at `/help` on the dashboard (rendered, behind the login, brand-substituted), add `[ HELP ]` to `settings_nav.html`, and add one button to the companion's HELP section: `Button("HOW CCSYNC WORKS (opens the dashboard)", ...)` pointing at `<dashboard_url>/help`. That is one route, one nav entry and one button, and it turns a 788-line asset into a product surface.
- **Effort:** M   **Value:** high   **Confidence:** high

### UX-4: 51 editor-facing dialog and balloon titles hardcode the developer's name for the app
- **Lens:** usability   **Who:** editor (owner, for customer #2)
- **Where:** 32 sites reading `"ccsync-companion: …"` and 19 reading `"CCSYNC.EXE: …"` across `companion/src/ccsync_companion/app.py` (e.g. `:2332`, `:2497`, `:2512`, `:2614`, `:4748`, `:6589`), `drive_reminder.py:71` (`NOTIFY_TITLE = "ccsync-companion: sync unfinished"`), `settings_window.py` (`_WINDOW_TITLE = "CCSYNC.EXE: SETTINGS"`), `popup.py`; contrast `site.py:405-417` `drive_phrase()` and `ui.py:150` `brand_org`
- **Today:** Every Windows balloon and every modal an editor sees is titled with either a package name or a filename, and with TWO different ones. The product went to real trouble to brand the drive (`"your Creators Club drive"` / `"your studio drive"`) and the dashboard header, then titles the licence dialog `CCSYNC.EXE: licence agreement`.
- **Proposed:** One helper beside `drive_phrase`: `site.notify_title(suffix)` returning `f"{org_short or 'CC Sync'}: {suffix}"`. Replace all 51. Add a companion test asserting no visible string starts with `ccsync-companion:` or `CCSYNC.EXE:`.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** COMMERCIAL_READINESS item 10 ("No customer's name in code") only ever fixed the direction; this is the vendor's name where the customer's belongs.

### UX-5: Every browser tab title is hardcoded "CC SYNC", including for customer #2
- **Lens:** usability   **Who:** owner
- **Where:** `dashboard/templates/base.html:10` and 18 page templates (`fleet.html:2`, `login.html:2`, `admin_users.html:2`, `setup.html:2`, …), all `{% block title %}CC SYNC: X{% endblock %}`; vs `partials/topbar.html:40` `{{ brand_org | upper }}`
- **Today:** The header says the customer's org, the tab, the bookmark, the PWA name and the phone's app switcher say `CC SYNC: FLEET`. On the login page, before any session exists, `CC SYNC` is the only branding a customer's editor ever sees.
- **Proposed:** `{% block title %}{{ brand_org | upper }}: FLEET{% endblock %}`, with `brand_org` supplied by `_render` (it already is) and defaulted for the un-authenticated login render.
- **Effort:** S   **Value:** med   **Confidence:** high

### UX-6: PROBLEMS THE SERVER FOUND says "Every check below ran" over a panel that renders [ NOT CHECKED ]
- **Lens:** usability / resilience   **Who:** admin
- **Where:** `dashboard/templates/partials/notices.html:41` vs `partials/notice_checks.html:28-29`
- **Today:** The clean state reads `"[ PROBLEMS THE SERVER FOUND ] nothing. Every check below ran and found nothing wrong."` The panel it introduces distinguishes `[ OK ]` (evidence from `db.notice_check_times`) from `[ NOT CHECKED ]` (`title="registered but nothing in this build has ever evaluated it"`). Whenever any kind is unchecked, the headline is false, in exactly the direction wave 4 exists to prevent: an unchecked thing reading as fine.
- **Proposed:** Compute the count in the template: `"nothing. {{ checked_kinds|length }} of {{ notice_kinds|length }} checks ran and found nothing wrong."` and, when any kind is unchecked, add `" {{ n }} checks have never run on this build - open the list below."` in amber.
- **Effort:** S   **Value:** high   **Confidence:** high

### UX-7: The setup wizard sends the owner to the wrong page for the thing that blocks their fleet
- **Lens:** usability   **Who:** owner
- **Where:** `dashboard/src/ccsync_dashboard/setup_engine.py:1146-1148`; the real page is `/admin/packages` (`partials/settings_nav.html` `("packages", "PACKAGES", "/admin/packages", true)`); `admin_users.html` has no packages section
- **Today:** Setup step "Software for editors" reports `"no companion build is current for any platform: publish one on the Users page, under PUBLISHED PACKAGES"`. There is no PUBLISHED PACKAGES section on the Users page and has not been since the 2026-08-18 Settings redesign. The owner clicks USERS, finds accounts and Syncthing devices, and stops.
- **Proposed:** `"no companion build is current for any platform: publish one on Settings > Packages"`, and make the task's `run_label` link there. Sweep the sibling strings at the same time: `setup_engine.py:1104` `"no editors yet: Users page, add one"` and `recovery.py:897` `"watch the first pass on the Fleet page"` (the nav calls it `[ SYNC STATUS ]`, `partials/topbar.html:98`; the words "Fleet page" appear in no UI).
- **Effort:** S   **Value:** high   **Confidence:** high

### UX-8: The drawer loses its place on half the Settings pages, and the comment says it cannot
- **Lens:** usability   **Who:** admin
- **Where:** `dashboard/templates/partials/topbar.html:63-67` (`SETTINGS_PAGES = ["site","users","assignments","transfers","setup","packages"]`, with the comment "Same list as partials/settings_nav.html") vs `partials/settings_nav.html:16-29` (twelve entries: the six above plus `audit`, `alerts`, `jobs`, `invariants`, `protection`, `recovery`)
- **Today:** Standing on ALERTS, JOBS, INVARIANTS, PROTECTION, RECOVERY or TIMELINE, the drawer's `[ SETTINGS ]` entry is not marked current, so the phone drawer shows nothing highlighted at all. The comment asserting the two lists match has been false since the six pages were added.
- **Proposed:** Build the list once. Move `SETTINGS_NAV` into a Jinja global or `_render` context and derive `SETTINGS_PAGES` from it, so a thirteenth page cannot drift again.
- **Effort:** S   **Value:** med   **Confidence:** high

### UX-9: FIX ALL, an editor's first real decision, states no total size and never checks free space
- **Lens:** usability / resilience   **Who:** editor
- **Where:** `companion/src/ccsync_companion/popup.py:745-748` (the body), `:333-348` (`preflight_summary` covers cloud placeholders only), `:774` (`[ FIX ALL ]`, no confirm); `fixer.py:554-555` is the only space handling (`"Your disk is full. Free up space and try again."`, per file, after the copy has begun); `app.py:5527` `disk_snapshot()` already measures free space every heavy tick
- **Today:** `"{n} timeline clip(s) live outside P:\… and will NOT sync. Pick a destination. FIX ALL copies them in and relinks Resolve."` A first-day editor with a 900 GB card dump on their desktop clicks FIX ALL and finds out mid-batch, per file, that the disk is full - with part of the batch already copied and the tree now holding a mixture.
- **Proposed:** Put the total on the button row before the click: `"{n} clips, {size} in total. This computer has {free} free."` in amber when `size > free * 0.9`, and a consequence confirm above a threshold: `"Copy {size} into your sync drive? Everything copied in is also uploaded to the server. This computer has {free} free."` Refuse nothing.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** 08-28 UX-17 built the same guard for the b-roll ingest drop; this is the older, more-used surface and did not get it.

### UX-10: "Lane A" and "(s)" leak into editor sentences the rest of the product carefully translates
- **Lens:** usability   **Who:** editor, admin
- **Where:** `companion/src/ccsync_companion/app.py:5731-5733` (`f"Lane {stalled.get('lane')} stopped making progress for {minutes} minute(s) and was restarted"`), and this detail is APPENDED verbatim to the dashboard sentence (`health.py:521-528`); `_LANE_WORDS` at `health.py:387-395` exists precisely to say "upload" / "proxy download" / "folder sync". Plural-in-parentheses in visible copy: `app.py:4413`, `:4448`, `:5525`, `:5527`, `:5572`, `:5721`, `:5732`, `popup.py:745`, `:1003`, `health.py:474-476`
- **Today:** The tray can read `"Sync: Lane A stopped making progress for 3 minute(s) and was restarted"` while the dashboard, for the same machine, says `"Not syncing: upload has been busy for 47 minutes with nothing moving"`. Two vocabularies for one lane, on two screens the same person compares.
- **Proposed:** Give the companion the same `_LANE_WORDS` map (or import it in reverse) and write `"Upload stopped making progress for 3 minutes and was restarted"`. Add the pluralisation helper `health._duration_words` already models, and ban `(s)` in visible strings in the existing copy-scan test.
- **Effort:** S   **Value:** med   **Confidence:** high

### UX-11: There is no UI anywhere for the three job knobs, and the docs say there is
- **Lens:** usability   **Who:** admin, editor
- **Where:** `companion/src/ccsync_companion/config.py:797` (`jobs_enabled`), `capabilities.py:113-140` (`jobs_kinds`), `config.py:837` (`cards_agent`); `dashboard/templates/partials/admin_jobs.html` has only `[ THE QUEUE ]` and a per-job `[ CANCEL ]`; `settings_window.py` mentions jobs nowhere; `CLAUDE.md`: "`[jobs] kinds` (`jobs_kinds`) keeps an editor's laptop out of ONE kind"
- **Today:** Keeping a laptop out of whisper, or turning fleet jobs off for a machine whose editor is complaining about fan noise, means opening `~/.ccsync/config.toml` on that machine in a text editor and restarting the companion. The tray's only lever is the opposite one, "use this machine NOW" (`tray.py:3411-3419`). The admin's Settings > JOBS page can cancel a job but cannot change who is eligible for one.
- **Proposed:** Two controls. In the companion Settings window, under THIS COMPUTER: `[ LET THE FLEET USE THIS COMPUTER ]` as a checkbox plus a per-kind list. On Settings > JOBS, a machines table with the same toggles pushed through `commands` on the next report (the channel `commands.upgrade` and the halt already use). Until then, at minimum print the config path and key in the JOBS page's empty state.
- **Effort:** M   **Value:** med   **Confidence:** high

### UX-12: The music page throws away the companion's reason and tells an editor to read a log
- **Lens:** usability   **Who:** editor
- **Where:** `music/web/static/app.js:248-250` (`if (!r.ok) throw new Error('companion ' + r.status)` - the body is never read), `:296-299` (`"the companion answered but refused the request (companion 403), see its log"`), `:330-333`; `companion/src/ccsync_companion/loopback_guard.py:111-112` writes an actionable body that nothing renders
- **Today:** A misconfigured `dashboard_url` 403s every Send to Resolve for every editor, and each of them is told to open a log file. The 403 and a 404 from an older companion collapse into the same string. Compare `broll/web/static/app.js:1651-1653`, which at least names a self-test URL.
- **Proposed:** Read the JSON body and render `body.message`; on a 403 add "This computer's companion expects the dashboard at a different address. Ask your admin to check the dashboard URL." Put the allowed origin into `GET /status` (already same-origin exempt) so the b-roll status line can name both sides.
- **Effort:** S   **Value:** med   **Confidence:** high
- **Related:** 08-28 UX-18, still open on the music side.

### UX-13: The Users page names environment variables the code no longer prefers, and asks for a redeploy
- **Lens:** usability   **Who:** owner
- **Where:** `dashboard/templates/partials/admin_users.html:188-190` (`"TRUENAS_PW is not configured on the dashboard, so this section is unavailable. Set TRUENAS_HOST / TRUENAS_USER / TRUENAS_PW on the app and redeploy."`) vs `settings.py:708-710` (`first("DASH_NAS_HOST","TRUENAS_HOST")`, `first("DASH_NAS_PW","TRUENAS_PW")`) and `ui.py:1934` (`"DASH_NAS_PW is not configured on the dashboard"`)
- **Today:** The same missing credential is named `TRUENAS_PW` on the page and `DASH_NAS_PW` in the error the same page renders after a submit. The instruction is to edit the container's environment and redeploy - the one thing a non-technical owner cannot do, on the page they were sent to by the setup wizard's Editors step.
- **Proposed:** Say the new name first: `"This dashboard has no NAS password, so editor accounts cannot be created here. Set it on Settings > Setup (Connect to your NAS), or set DASH_NAS_PW in the container."` `setup_engine`'s `nas_connect` task already exists to collect it - link to it.
- **Effort:** S   **Value:** med   **Confidence:** high

### UX-14: Creating an editor account requires an SSH public key that only exists after the editor has installed
- **Lens:** usability   **Who:** owner, editor
- **Where:** `dashboard/templates/partials/admin_users.html:319` (`<textarea name="ssh_pubkey" … required>`), `ui.py:1938` (`error = "does not look like an OpenSSH public key"`); `installer/START_HERE.md:26-31` ("at the end shows you two values - your Syncthing device ID and SSH public key - to send to your admin"); `docs/EDITOR_SETUP.md:19-21` (the editor needs a username before step 2)
- **Today:** The account must exist before the wizard's sign-in page can verify it (`onboarding/onboard.py:686-761`), and the key the account form demands is generated by that same wizard. The owner's only ways out are `server/setup_editor_account.py` from a repo checkout, or generating a key themselves and mailing the private half. The refusal names no next step.
- **Proposed:** Make `ssh_pubkey` optional on the create form with the copy `"leave blank: the editor's installer sends their key up on first sign-in"`, and if that is not yet true, say so: `"Paste the editor's SSH public key. If they have not installed yet, create the account without one and use [ ADD ] on their row afterwards."` The `[ ADD ]` key control already exists (`admin_users.html:52`).
- **Effort:** M   **Value:** high   **Confidence:** med (the "key arrives automatically" half needs the reporter checked)

### UX-15: START_HERE tells the new editor to pick a role the wizard renamed and reframed
- **Lens:** usability   **Who:** editor
- **Where:** `installer/START_HERE.md:31-33` ("Follow the wizard: pick **REMOTE EDITOR** on the role page (BASE is only for the studio base rig)") vs `onboarding/onboard.py:451-490` (heading `"STEP 1: HOW IS THIS MACHINE CONNECTED?"`, options `"I'M A REMOTE EDITOR"` and `"I'M PHYSICALLY CONNECTED TO THE SERVER/NAS"`, body "Any number of machines can sit on the studio network")
- **Today:** The document handed to the editor names a button ("BASE") that is not on the screen and gives a rule ("only for the studio base rig") that the wizard's own copy deliberately abandoned on 2026-08-19. An office editor who IS wired reads START_HERE and picks REMOTE EDITOR, which then syncs a full copy of the tree onto a machine sitting next to the NAS.
- **Proposed:** Rewrite the paragraph against the live copy, and while there fix the same page's other stale promise about approving the editor by hand. Longer term: START_HERE is shipped beside the exe and goes stale silently - fold it into the wizard's welcome page, which cannot.
- **Effort:** S   **Value:** high   **Confidence:** high

### UX-16: The wizard asks "HOW IS THIS MACHINE CONNECTED?" and then says "this computer" three times
- **Lens:** usability   **Who:** editor
- **Where:** `onboarding/onboard.py:451` (heading) vs `:457-459` and `:477-489` (body); `settings_window.py:353` (`Section("THIS COMPUTER", …)`); `tray.py:1822` (`"Sync: stopped on this machine"`) vs `health.py:439-441` (`"Not syncing: syncing has been stopped on this computer"`); `admin_users.html:118-119` (`[ COMPUTERS ]`, "every computer that has reported in") vs the route/table `machine`
- **Today:** Four words for one thing across four surfaces, twice on one screen. `device` additionally means a Syncthing identity (`[ DEVICES AWAITING APPROVAL ]`) and `[ COMPANIONS ]` means the app on it.
- **Proposed:** **computer** in every editor- and admin-facing string, `machine` only in code, routes and the database, `device` only where Syncthing's own word is being quoted. Full table below.
- **Effort:** S   **Value:** med   **Confidence:** high

### UX-17: [ UP ] and [ UP ON ONE ] are four spellings of upload-only inside one dashboard
- **Lens:** usability   **Who:** admin
- **Where:** `partials/sidebar.html:33` (`[ UP ]`), `partials/project_detail.html:30` (`[ UP ]` and `[ UP ON ONE ]`), `partials/my_queue.html:22` (`[ UPLOAD ONLY ]`), `:27` ("originals up only"), `admin_assignments.html:16` ("an `up` box beside a tick makes it UPLOAD ONLY"), `project_detail.html:81/87` (`[ SWITCH TO FULL SYNC ]` / `[ SWITCH TO UPLOAD ONLY ]`)
- **Today:** The mode with the largest consequence in the product (lane A alone, no share, no proxies down) is signalled by a two-letter chip on the two pages the admin scans most, next to another chip that differs by three words.
- **Proposed:** `[ UPLOAD ONLY ]` everywhere it fits and `[ UPLOAD ONLY ON 1 OF 2 ]` for the mixed case. Both chips already carry the full sentence in `title`; the chip should not be the abbreviation of the tooltip.
- **Effort:** S   **Value:** med   **Confidence:** high

### UX-18: RECOVERY, the page an admin opens at their worst moment, prescribes repo scripts they do not have
- **Lens:** usability   **Who:** admin
- **Where:** `dashboard/src/ccsync_dashboard/recovery.py:894-897` ("re-run `server/setup_tree.py` for each project, then let the fleet resume and watch the first pass on the Fleet page"), `:688-690` ("add a periodic snapshot task for it (`server/setup_snapshots.py`)"), `:910-912` (`python publish_db.py --which broll --rollback --apply`)
- **Today:** A customer's admin has a container and a browser. These three steps require a checkout of this repo on a machine with SSH to the NAS. This is the exact class of bug CR-59 fixed for the installer 404, where an editor was told to run `build_editor_package.ps1` "from the base rig".
- **Proposed:** For each: either a button on the page that runs it through the dashboard's existing NAS client, or copy that says what the admin can do without a checkout and who to ask. `setup_engine`'s snapshots task already automates the second one - point at it rather than at the script.
- **Effort:** M   **Value:** med   **Confidence:** high

### UX-19: A local halt and a pause are two mechanisms with one word, both live in the same menu
- **Lens:** usability   **Who:** editor
- **Where:** `tray.py:3382-3384` (`"► Start syncing again"`, shown while a LOCAL halt is active), `tray.py:3435-3438` (`"⏸ Pause syncing"` / `"▶ Resume syncing (currently PAUSED)"`), `tray.py:1820-1822` (`"Sync: stopped on this machine"` vs `"Sync: paused"`), `health.py:437-441`
- **Today:** With a local halt AND a pause set, the menu carries `► Start syncing again` and `▶ Resume syncing (currently PAUSED)` four lines apart, and clicking either leaves the machine not syncing. Nothing on screen says there are two switches.
- **Proposed:** Name the halt for its cause on the item, not for its effect: `"► Clear the sync stop on this computer (set <when>)"`, and when both are set add one line to the state block: `"Two things are stopping sync on this computer: a stop and a pause."` The dashboard's `why_not_syncing` already ranks them (`health.py:548-555`); the tray should show the same second reason rather than only the first.
- **Effort:** S   **Value:** med   **Confidence:** high

### UX-20: The tray's balloon for a job it cannot finish is the drive reminder's process name
- **Lens:** usability   **Who:** editor
- **Where:** `companion/src/ccsync_companion/drive_reminder.py:71`, `:165-166`, `:171-172`
- **Today:** Every half hour, `"ccsync-companion: sync unfinished"` / `"your Creators Club drive is still disconnected and syncing is unfinished: 41 files, 62 GB still to go. Plug it back in to finish syncing."` The body is excellent and the title is a package name; the two do not look like the same product.
- **Proposed:** Covered by UX-4's `site.notify_title`. Title: `"Creators Club: sync unfinished"`. Also add the drive's letter or volume name to the first warning - `drive_phrase()` yields "your Creators Club drive", which does not tell an editor with two externals which one to plug in.
- **Effort:** S   **Value:** med   **Confidence:** high

### UX-21: The only path for customer #2 is a hand-edited compose file, from a doc that says DRAFT
- **Lens:** usability   **Who:** owner
- **Where:** `docs/APPLIANCE_INSTALL.md:1` ("the paste-and-click install (DRAFT, WP A only)"), `:36-56` (paste compose, "set `CCSYNC_TREE` by hand, before the first `docker compose up`"), `:117-137` (`docker compose exec tailscale tailscale --socket=… up`, then `docker compose logs tailscale` for the `AuthURL is …` line), `:189-196` (troubleshooting is four `docker compose` commands and a `curl`)
- **Today:** The owner is non-technical. Getting to the browser wizard needs SSH to the NAS, a text editor on a compose file, `docker compose exec` for the tailnet sign-in, and `docker compose logs` to read the sign-in URL out of a log. The setup wizard's own tailnet step (`setup_engine.py:868`) exists and is better, but the doc's step 4 does not send the owner to it.
- **Proposed:** Two things, both small against WP A's scope. (1) Reorder the doc so step 3 is "open the dashboard" and step 4 is "the wizard does the rest", with the CLI kept as the fallback under "if the bundled node cannot start". (2) Surface the tailscale `AuthURL` in the setup wizard's tailnet step, which is the one line that currently forces a terminal. Drop the DRAFT label only once a run has been done by someone who is not the author.
- **Effort:** M   **Value:** high   **Confidence:** med

### UX-22: The login page is the first thing a customer's editor sees and it explains nothing
- **Lens:** usability   **Who:** editor
- **Where:** `dashboard/templates/login.html:2` (`CC SYNC: LOGIN`), `:21` (`"Use your NAS username and password."`), no help, no org name, no failure guidance
- **Today:** A new editor is sent a URL and told to click `[ INSTALLER ]`. They land on a dark page reading `[ SIGN IN ]` and `Use your NAS username and password.` If they do not have one, or mistype, there is no route forward and nobody to ask named on the page.
- **Proposed:** Add the brand (UX-5) and one muted line: `"Your admin creates this account for you. If you do not have one yet, ask them before installing."` On the `error` branch, if the username is unknown, say so rather than a generic refusal - the account either exists in `local_users` or on the NAS and the difference is knowable.
- **Effort:** S   **Value:** med   **Confidence:** high

## Terminology drift, and the one word for each

| Concept | Words in use today (cites) | Proposed one word |
|---|---|---|
| "this project should sync here" | **tick**/**untick** (`my_queue.html:2,13`, `plan_changes.html:33-34`, tray `tray.py:484`), **selection** (route `/partials/selection/…`, table `selections`), **plan** (`sidebar.html:17` "Per-computer plans", `plan_changes.html:13` "RECENT PLAN CHANGES", `admin_users.html:78` "their sync plans"), **assignment** (page `[ ASSIGNMENTS ]`, `/admin/assignments`) | **tick** (verb), **sync plan** (the set for one computer). Rename the page `[ SYNC PLANS ]`; keep `selections` in the DB only |
| the box on the desk | **machine** (`onboard.py:451`, `tray.py:1822`, DB `machines`), **computer** (`settings_window.py:353`, `health.py:439`, `admin_users.html:119`), **device** (`[ DEVICES AWAITING APPROVAL ]`), **rig** (docs, `health.py:560`), **companion** (`fleet_grid.html:124` `[ COMPANIONS ]`) | **computer** in all UI copy; `machine` in code/routes; `device` only for a Syncthing identity |
| sync is not running | **paused** (tray, `health.py:443`), **halted** (`fleet_halt.html`, `health.py:437`), **stopped** (`tray.py:1821-1822`, `[ PROXY DOWNLOAD STOPPED ]`), **breaker** (docs, `lane_guard.py`), **parked** (`app.py:5674`) | **paused** = you did it; **stopped by your admin** = fleet halt; **stopped itself** = breaker/disk floor. Never "halted" or "parked" in UI |
| how this computer reaches the footage | **wired to the server** (`settings_window.py:93`), **physically connected to the server/NAS** (`onboard.py:477`), **base** (`config mode`, `project_detail.html:269` `[ BASE ]`), **base rig** (docs, START_HERE), **wired** lowercase (`admin_assignments.html:66`) | **wired** / **remote**. `base` stays a config value; "base rig" leaves the UI entirely |
| the three transports | **lane A/B/C** (`app.py:5732`, docs), **upload / proxy download / folder sync** (`health.py:387-395`), **uploads, proxy downloads and shared project files** (halt copy) | **upload** / **proxy download** / **folder sync**. "Lane" never appears in a user-visible string |
| upload-only mode | `[ UP ]`, `[ UP ON ONE ]`, `[ UPLOAD ONLY ]`, "originals up only", "an `up` box" | **[ UPLOAD ONLY ]** |
| the home page | `[ SYNC STATUS ]` (`topbar.html:98`), "the Fleet page" (`recovery.py:897`), `CC SYNC: FLEET` (tab title), `fleet.html` | **SYNC STATUS** |
| where the editor gets help | "Tray → Copy diagnostics", "tray → Open log", "Advanced → …", "See EDITOR_SETUP step 6" (removed) | **Settings > Help > Copy diagnostics** (one constant, UX-1) |

## Still open from 08-28

- UX-18 (loopback 403 unreadable in the SPA): partly built - b-roll names a self-test URL, `music/web/static/app.js:250` still discards the body. See UX-12.
- UX-16 (no `--bwlimit`, no "this will take 26 hours"): not built; no `bwlimit` in `sync/rclone_lane.py`.
- UX-7 (Syncthing conflict copies never surfaced): not built; still zero `sync-conflict` matches in `companion/src` or `dashboard/src`.
- UX-19 (the client's dead end on a rotated share link): not re-checked in depth; the gone page still carries no contact.

## Cross-cutting notes

- **For the companion/tray agent:** the UX-1 string sweep is mechanical and touches ~20 sites across `tray.py`, `app.py`, `fixer.py`, `identity.py`, `resolve_journal.py`, `popup.py`, `loopback_guard.py`. Worth doing as one commit with a scan test.
- **For the dashboard agent:** `partials/topbar.html:63-67` and `partials/settings_nav.html:16-29` are two hand-maintained copies of one list and have already drifted by six entries (UX-8).
- **For the docs agent:** `installer/START_HERE.md` is shipped beside `onboard.exe` and describes a role page that changed on 2026-08-19 (UX-15); `docs/APPLIANCE_INSTALL.md` is still labelled DRAFT and is the only customer-install path (UX-21).
- **For the release agent:** `setup_engine.py`'s task details are the owner's checklist and three of them name a page or a script that is wrong or unavailable (`:1104`, `:1148`, plus `recovery.py:690/897/912`). They are strings, not logic, and nothing tests them.
