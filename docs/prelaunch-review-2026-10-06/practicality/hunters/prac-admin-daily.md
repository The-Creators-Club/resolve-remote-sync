# Practicality pass: the customer admin's week (prac-admin-daily)

Pre-commercial-launch review, 2026-10-06, HEAD 08b40eb plus the uncommitted
working tree. Lens: a customer studio's admin (not a developer) running the
fleet day to day, plus the vendor supporting ten such admins.

**Covered (read end to end):** home / SYNC STATUS (`templates/fleet.html`,
`partials/fleet_grid.html`, `partials/home_problems.html`, `ui_home.py`
readouts), the HUD (`partials/topbar.html`, `ui._render` counts), HEALTH
(`admin_health.html`), USERS (`admin_users.html` + partial, suspend / approve /
key routes in `ui.py`), PACKAGES (`admin_packages.html` + partial,
`admin_dashboard_update.html`, `release_feed.py` policy path,
`package_store.make_current`), JOBS page shell, ALERTS (`admin_alerts.html`
partial, `alerts.py` registry, `KIND_GROUPS`, `scan`), the settings nav
(`ui.SETTINGS_NAV_GROUPS`), the computer-answer window, the collector's
enforce brake (`collector.py` ~1480-1720), notices registry (`db.py` ~3520),
`published_docs.py`, `crash_report.py`, `triage.py` bundle, client-folder
routes and `docs/CLIENT_FOLDERS.md` section 3, compose image template.
Cross-checked against KNOWN_BUGS.md, COMMERCIAL_READINESS.md and the
2026-09-03 DUI/DCORE sweep notes.

**Not covered:** the setup wizard and first install (other lenses), the
account page beyond a skim, the SYNC PLANS grid's JS, the project page,
b-roll / music / ytdl / Cards SPAs, the companion tray. No live probing of a
rendered page; findings are from code paths read end to end.

---

### prac-admin-daily-1 - The home page's "problems" is not the server's problems: three different counts, and alerts are missing from home
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/ui_home.py:260-280` (problems readout = `notice_counts` errors only); `templates/fleet.html:67-73` (problems.log = `/partials/home-problems` = `ui._notices_context`, notices table only); `templates/partials/topbar.html:22-25,67-72` (HUD: "N problems" = notice errors, "N alerts" = alert error+warn); `alerts.py:2197` (`_check_notices` re-files every error notice as an alert); `templates/admin_health.html:20` (a third total across notices, alerts, invariants, protection)
- **What:** The admin's 10-second answer is meant to be the home page. Its PROBLEMS readout and the problems.log window read only the `notices` table. The forty-plus alert kinds (machine_silent, disk_low, lane_error, lane_stalled, engine_down, upgrade_failed, rollout_stalled, versions_behind, ...), the invariants and the protection checks never reach home; they are only counted in a small HUD "alerts" link that goes to Health, and that HUD count double-counts every error notice (once as a problem, once as an alert via `_check_notices`). Health has a third, different total. "Problems 0 - nothing needs you / All clear, N of M checks ran" can sit beside "3 alerts" in the HUD.
- **Scenario:** An editor's lane A has been in error for a day (`lane_error`, alert only) and another computer's disk is at 97% (`disk_low`). Home shows PROBLEMS 0, "nothing needs you", and problems.log "All clear". The admin who reads the big number and the green "all clear" closes the tab.
- **Recommendation:** One number everywhere: the HUD, the home readout and the home window all show Health's open total (`health_rows`), worst first, with the same rows Health lists (or the top five and a link). Drop `_check_notices` double counting from the HUD figure, or drop the separate HUD alerts link. Rename the readout "needs you" and make "all clear" mean Health is empty.
- **Known:** not recorded.

### prac-admin-daily-2 - The 3-removal blast-radius brake freezes ordinary admin actions fleet-wide, including Suspend, and only a container env change undoes it
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/settings.py:625,939` (`enforce_max_share_removals = 3`); `collector.py:1633-1662` (removals counted as (folder, device) pairs; over the limit, ALL removals skipped); `collector.py:1693-1696` (`desired = desired | actual`); `collector.py:1529-1558` (suspended editors are dropped from `desired`, so suspend IS a removal); `ui.py:3440-3447` (Suspend promises "their projects will be unshared within a minute"); `templates/partials/fleet_grid.html:54-64` ("ask whoever installed this server to raise the limit: it is a container setting")
- **What:** A share removal is one project on one computer. Anything an admin does routinely that removes more than three at once trips the brake: unticking two finished projects for an editor who has a desktop and a laptop (4), end-of-month cleanup of four wrapped projects, or SUSPENDING an editor who has four or more project-computer shares. Over the limit, no removal anywhere in the fleet is applied, every cycle, until the pending diff drops to 3 or below. The banner's fix is a container environment variable; the notice's alternative ("untick fewer at a time") does not work once the diff is already over, because the unapplied unticks stay in the diff.
- **Scenario:** An editor leaves; the admin presses SUSPEND (the button built for "stop this person" on an SMB site). They had 6 projects ticked across 2 computers = 12 removals. The page says they will be unshared within a minute; instead the brake refuses, the departing editor's Syncthing keeps receiving every project, and every other untick in the fleet is frozen too. Fixing it needs SSH / the NAS app UI and a container restart, or the vendor.
- **Recommendation:** Do not count removals the admin asked for: removals that trace to an audited action in this cycle (untick, suspend, forget, delete, archive) are pre-authorised; keep the brake for removals nobody asked for (the bad-snapshot shape it exists for). Add an "Apply these N removals" key on the refusal banner (admin-only, audit-logged, names the folders and computers). Make the limit a site setting, not an env var, and scale it with fleet size.
- **Known:** the brake and its notice are KNOWN_BUGS DASH-3 (fixed as designed); that ordinary admin actions and Suspend trip it is not recorded.

### prac-admin-daily-3 - "Send us the container log": no vendor contact exists anywhere, and the log cannot be fetched from the dashboard
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `alerts.py:1696,2028,2106,3426,3833,3911,4245,4259,4274`; `invariants.py:1200,1400`; `notices.py:1060` ("send us ..."); no `support_email`/`support_url`/vendor contact key in `dashboard/src` or `companion/src`; `crash_report.py:9-30` (logs go to stdout; a log file only with `DASH_LOG_DIR`); only download is `/admin/diagnostics/crash-reports.zip` (`ui.py:4555`)
- **What:** Sixteen user-visible fix lines tell a customer admin to "send us" a container log, diagnostics or a list. "Us" is the vendor, but the product names no vendor contact on any page, email or the weekly report. The container log is only reachable through the NAS app UI or SSH (`docker logs`), and it is lost on a recreate. Per-computer diagnostics are shown as a `<pre>` on screen, not downloadable as one file. The triage agent already builds a scrubbed evidence bundle (`triage.py:678`, `scrub(build_bundle(...))`) but nothing lets an admin download it.
- **Scenario:** `check_failed: the whole scan` fires. The fix says "Send us the container log from the NAS." The customer admin does not know who "us" is, has no SSH, and does not know where TrueNAS keeps a container's log. They email whoever sold it to them a screenshot; the vendor then has to walk them through `docker logs` over a call.
- **Recommendation:** Add `support_contact` (email/URL) to the site manifest, filled by the vendor at install, and render "send it to <contact>" instead of "us". Add one "Download support bundle" key on Health: the triage `scrub(build_bundle())` evidence, the last N hours of the `ccsync` logger (turn `DASH_LOG_DIR` on by default under `/data/logs`), versions, open Health rows, and the newest diagnostics per computer, as one zip.
- **Known:** not recorded.

### prac-admin-daily-4 - Fixes point the admin at documents the customer does not have, and there is no admin guide at all
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `published_docs.py:42-55` (only `HOW_IT_WORKS.md`, `EDITOR_SETUP.md`, `legal/` ship); user-visible references to unshipped docs: `alerts.py:3022,3041,3325,3625,3653`, `notices.py:799,925`, `protection.py:700,710`, `recovery.py:918,1117`, `setup_engine.py:976-977,1372,1541`, `templates/partials/admin_packages.html:28,258,474,476` (`tools\ship.cmd`, `docs/RELEASE.md`)
- **What:** Alert, notice, protection, recovery and setup fix text sends the admin to `docs/DOCKER.md`, `docs/RELEASE.md`, `docs/SECRETS.md`, `docs/BACKUP_RESTORE.md`, `docs/RESOLVE_EDIT_SAFETY.md`, `docs/INSTALL.md`, `docs/APPLIANCE_INSTALL.md`, and Packages tells them to run `tools\ship.cmd` "from your wired computer". None of these ship to a customer (by design, `published_docs.py`), and `/help` on a customer dashboard will not open them. The customer gets an editor explainer and an editor setup guide, and nothing written for the admin: what each Settings page is for, the weekly routine, how updates work, what to do when a computer goes red.
- **Scenario:** `code_not_applied` says "Restart the dashboard (docs/DOCKER.md)". The admin opens Help, finds no such page, and has to contact the vendor for a one-line instruction.
- **Recommendation:** Write a customer `ADMIN_GUIDE.md` (the week, each Settings page, updates, adding/removing an editor, "a computer is red", backups, getting help) and publish it. Replace every `docs/...` reference in user-visible strings with either a link into that guide or the instruction itself; add a scan test like the em-dash one that fails on `docs/` or `tools\` in a fix/body string. On a feed-configured site never mention `ship.cmd`.
- **Known:** the 2026-09-03 usability sweep (`docs/usability-resilience-sweep-2026-09-03/DUI.md:85`) listed developer paths in templates; the alert/notice/protection strings and the missing admin guide are not recorded.

### prac-admin-daily-5 - A new editor's SSH key waiting for approval is invisible outside the Users page, and pending devices never alert
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `api.py:4940` ("`pending_ssh_keys`, which nothing reads but the Users page"); no notice kind or alert kind for pending SSH keys (`db.py` NOTICE_KINDS ~3520-3700, `alerts.KIND_GROUPS`); `db.py:3553` + `notices.py:527-554` (`pending_device_approval` is a WARN notice); `ui_home.py:265-275` and `topbar.html:22` (HUD and readout count only error notices); `alerts.py:2197` (`_check_notices` mirrors only errors)
- **What:** Onboarding a computer needs two admin approvals: its Syncthing device and (NAS mode) its SSH key. Until the key is approved, that editor's upload (lane A) and proxy download cannot authenticate. The key request appears only as a window on Settings, Users. The device request is a warn notice: it appears in problems.log but is not in the HUD count, not in the big PROBLEMS number, and is never emailed, because only error notices become alerts.
- **Scenario:** An editor installs on Monday, starts shooting, and their footage never leaves the laptop. The admin, who has email alerts set up, gets nothing; home shows PROBLEMS 0. The editor's lane A eventually shows an error on the grid, which says "lane error", not "approve their key on Users".
- **Recommendation:** Add a `pending_ssh_key_approval` notice (error once older than an hour) with a "take me there" to `/admin/users#win-pending-keys-t`, and alert kinds for both pending approvals (default on). Better: when the device and key arrive from a companion signed in with that editor's own `cce1` credential, approve both automatically and log it; keep manual approval for the shared-token path only.
- **Known:** not recorded (KNOWN_BUGS OPS-2 / UX-14 built the approval window, not its notification).

### prac-admin-daily-6 - "Newer versions will never go up": originals that cannot upload are a grey chip, never an alert, and the dashboard offers no fix
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `templates/partials/fleet_grid.html:132` (warn chip "won't upload: N"); `ui.py:451-454` (help text: "this computer's newer versions will never go up"); `health.py:1387-1390` (a note only); no `skipped_exists` kind in `alerts.KIND_GROUPS` or the notice registry; companion side `app.py:7331`
- **What:** When a file of the same name and a different size is already on the NAS, lane A never overwrites it, so the editor's version (often the real, complete original after a partial copy) stays on one disk forever. The dashboard knows the count and samples, but only draws a warn tag inside the row's issue list. Nothing emails, nothing reaches problems.log or Health, and there is no action: no list of the files, no "keep both" / "replace the server copy" / "rename mine".
- **Scenario:** A camera card was copied twice, the first copy interrupted. The NAS holds a truncated `A004C012.mov`; the editor's full copy is skipped every pass. Three weeks later the laptop is stolen. The admin had a yellow chip among a dozen others on one row.
- **Recommendation:** Make it an alert kind ("footage only on one computer") with the file list from the samples, default on, severity error after 24 h. On the row, add an admin action that asks the companion to upload the local copy beside the server one as `<name> (from <machine>).<ext>` so nothing is overwritten and nothing is lost; say on the editor's tray which file and what to do.
- **Known:** not recorded as an admin-visibility issue (the companion-side message wording was fixed, KNOWN_BUGS ~12172).

### prac-admin-daily-7 - Home cannot answer "is any footage only on one computer": uploads and downloads are summed into one "moving" number
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `ui_home.py:124-160` (`plan_facts`: `owed_bytes` sums file transfers and queues of both directions); `ui_home.py:217-232` ("moving" readout); `ui.py:570-620` (`safe_to_close`, the upload-only answer, exists for the editor only)
- **What:** The admin's real question is "is everybody's footage safe", which means: are there originals on editors' computers that are not on the server yet, how much, and since when. The readouts are online / moving / problems / in sync. "Moving 380 GB" can be 380 GB of proxies coming down (harmless) or 380 GB of originals that exist on one laptop (the thing that matters). The per-editor `safe_to_close` logic already computes upload bytes and the "cannot tell" (capped or withheld list) case, but only for the editor's own view.
- **Scenario:** Monday morning the admin sees "in sync 11/12, moving 210 GB". They cannot tell whether a shoot from Saturday is still only on the camera op's laptop without opening Transfers and filtering by direction.
- **Recommendation:** Replace "moving" with "not on the server yet: X GB on N computers, oldest Y h" (lane A owed bytes plus `uncertain` rows counted as "cannot tell", never zero), with the per-computer list one click away. Keep downloads on the Transfers page.
- **Known:** not recorded.

### prac-admin-daily-8 - Updates are a per-release, per-platform, per-customer chore, and policy "current" does not actually make anything current
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `release_feed.py:1026-1066` (policy current calls `package_store.make_current`, which refuses for the soak; logs a WARNING and continues); `package_store.py:98-110` (soak applies to the feed by owner decision); `package_store.py:357-360` (STAGED_SENTENCE: "push it to one computer, let it soak, then MAKE CURRENT"); no automatic canary push anywhere; `alerts._check_soak` (fires only on canary crashes/reverts) and `_check_rollout_stalled` (needs a build to BE current); `templates/partials/admin_packages.html:330-336` (policy label "current: auto-publish and make current"), `:419-421` (staged builds are in a folded "other versions held"); `templates/admin_packages.html:12-13` and `fleet.html:16-17` (UPDATE ALL and Check now not built)
- **What:** On a site set to "current", a new companion build is downloaded and staged, then stays staged forever: nothing pushes it to a canary, so the soak can never pass, and the only trace is a container log line. No alert covers "a staged build is waiting for a canary". To actually ship a release an admin must, per platform: open Packages, unfold "other versions held", pick a computer, push to one, wait 30 minutes, come back, press make current, then press "update now" on each computer that has not taken it (there is no update-all). The vendor repeats this conversation with each of ten customers for every release.
- **Scenario:** The vendor ships a fix for a data-safety bug. A customer set to "current" believes they get fixes automatically. Two weeks later their fleet is still on the old build; Health shows a small "vendor: newer" tag, nothing alerts.
- **Recommendation:** On policy current, pick the canary automatically (the base rig or the most recently active computer per platform, recorded in the audit log), push to it, and promote after the soak; on manual, raise a notice "build X is staged and waiting for you to try it on one computer" with the push key inline. Add "update every computer that is behind". Rename the policy option to what it does.
- **Known:** REL-1 (soak on the feed) is a deliberate owner decision; the missing auto-canary and the silent stall are not recorded.

### prac-admin-daily-9 - Settings a customer admin is told to change but can only change through the container (SSH, NAS app UI, or the vendor)
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `templates/partials/admin_packages.html:325` (`DASH_RELEASE_FEED_URL`, "a container setting, not something this page can change"); `templates/partials/fleet_grid.html:58-62` (`DASH_ENFORCE_MAX_REMOVALS`); `templates/partials/admin_report_tokens.html:18` (`DASH_SHARED_REPORT_TOKEN_ENABLED`); `templates/partials/fleet_grid.html:77-81` (remove `DASH_SESSION_SECRET_PREVIOUS`); `templates/partials/project_setup_panel.html:45` (projects mount); `templates/partials/admin_users.html:293-295` (`DASH_NAS_PW`); `alerts.py:3653` and `notices.py:799,925` ("restart the ccsync container"); `recovery.py:900-920` (root-shell restore commands); `templates/partials/admin_dashboard_update.html` (bind mode: "Ask whoever installed this server")
- **What:** At least seven things the dashboard asks the admin to do are environment variables or container operations. On a sold appliance the customer admin cannot do any of them without SSH or the NAS's app editor, so each becomes a vendor ticket. Several are routine rather than disaster-only: retiring the shared report token after onboarding, clearing the previous session secret after a rotation, raising the removal brake (see -2), restarting after a mount fix.
- **Scenario:** The Users page tells the admin, once onboarding is done, to "ask whoever installed this server to switch the shared token off". That is the vendor. Multiply by ten customers.
- **Recommendation:** Move the routine ones into `site_settings` with a Settings control (shared-token switch, removal limit, previous-secret retirement once the drain count is zero, done automatically), add a "Restart the dashboard" key on Health (the process can re-exec itself, as the OTA path already does), and reword the rest as "contact <support_contact>" with the exact value to quote. The feed URL should be baked into the vendor image as the default, not left blank.
- **Known:** DUI sweep 2026-09-03 (`DUI.md:85`) listed the developer paths in these templates; making them settable is not recorded.

### prac-admin-daily-10 - Client folder links need SSH, sudo and a tailnet policy edit before a client can open one
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/CLIENT_FOLDERS.md` section 3 (lines 96-220: tailnet policy file `funnel` attribute, then `sudo tailscale funnel --bg --yes --https=8443 --set-path /broll/share ...` or `sudo docker exec tailscale tailscale funnel ...` over SSH on the NAS); `broll/web/app/routes_client_folders.py:116-140` (the public base URL is a separate admin setting)
- **What:** Client folders are a selling point, and any editor can create one and copy a link. The link only works outside the studio once someone has edited the tailnet policy in the Tailscale admin console, SSHed into the NAS, run a root `tailscale funnel` command (which blocks if the policy is missing) and then set the public base URL in the b-roll UI. None of that is in the dashboard or the setup wizard, and the customer admin has no shipped doc for it (CLIENT_FOLDERS.md is not published, see -4).
- **Scenario:** An editor sends a client the link; the client gets a Tailscale login page or nothing. The admin has no way to tell from the dashboard whether the public door exists.
- **Recommendation:** Make it a setup-wizard task: check the funnel state through the Tailscale local API the dashboard already talks to (`tailscale_local.py`), and either turn it on from there or print the one console link that grants it. Show "client links: reachable from the internet / tailnet only" on the client-folders screen and refuse to mint a link that cannot be opened.
- **Known:** not recorded.

### prac-admin-daily-11 - Email alerts need raw SMTP settings with no provider presets
- **Severity:** low
- **Confidence:** PLAUSIBLE
- **Where:** `templates/partials/admin_alerts.html:131-165` (host, port, user, from, to, STARTTLS, verify, password); no provider presets in `alerts.py` or the template; `setup_engine.py:1567-1668` (the wizard's alerts task takes an address, then sends the admin to the full form for the mail server)
- **What:** Without a channel the admin is told nothing unless they open the dashboard. The email channel needs SMTP host, port, user, an app password (Gmail and Microsoft 365 both need one now) and TLS choices, which a small studio's admin will not know. Webhook is the only alternative.
- **Scenario:** Setup's "Who should we tell?" takes an email, then the mail-server half is left; the site runs with `alerts_sink_none` (a warn notice) for months.
- **Recommendation:** Presets for Gmail / Google Workspace and Microsoft 365 (host, port, TLS filled, with the app-password link), and consider a vendor relay as the default channel so alerts work with just an address.
- **Known:** not recorded.

### prac-admin-daily-12 - Lane meters on the computers grid are always full or empty, so they look like progress but are not
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `templates/partials/fleet_grid.html:184` (`cc_meter(1 if lt in ('ok', 'busy') else 0, 1, 10)`)
- **What:** Each lane draws a 10-cell block meter, filled when the lane is ok or busy and empty otherwise. An upload that is 3% through a 400 GB backlog shows a full bar, the same as a lane that is caught up.
- **Scenario:** The admin reads a row of full bars as "all done" while lane A owes hundreds of gigabytes.
- **Recommendation:** Draw the meter from that lane's owed versus total bytes when known, or replace it with a word or a dot, so a bar never looks like completion.
- **Known:** not recorded.

### prac-admin-daily-13 - Settings is fourteen pages with four overlapping "is it healthy" pages; the fleet stop lives on Users
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `ui.py:257-288` (SETTINGS_NAV_GROUPS: SITE, USERS, SYNC PLANS, TRANSFERS, PACKAGES, JOBS, HISTORY, SETUP, HEALTH, INVARIANTS, PROTECTION, ALERTS, RECOVERY, HELP); `templates/fleet.html:41-45` ("Stop the fleet" links to Users); `templates/admin_jobs.html` (shown on every site, Cards or not)
- **What:** HEALTH already aggregates notices, alerts, invariants and protection, yet INVARIANTS and PROTECTION are separate nav entries with developer names, and problems.log on home is a fifth view. JOBS (Timeline Cards' work queue) shows on sites that do not use Cards. The emergency "stop syncing everywhere" is a window at the bottom of the Users page, under sessions and report tokens.
- **Scenario:** A new admin clicks through every entry trying to learn the product; half of them are diagnostic internals.
- **Recommendation:** Fold INVARIANTS and PROTECTION into tabs of HEALTH, hide JOBS unless a job kind is enabled or a job has ever run, and give the fleet stop its own control on home (the comment at `fleet.html:16-17` already says it is waiting on a ticket).
- **Known:** SYS-6 (2026-09-03 sweep) grouped the strip into three runs; the overlap remains.
