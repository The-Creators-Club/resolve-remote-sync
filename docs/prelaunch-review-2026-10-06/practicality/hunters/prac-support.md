# Pre-launch practicality pass: vendor supportability (prac-support)

Lens: can the vendor support ten customers without SSH? Covered: the companion
diagnostics channel (`build_diagnostics`, `_redact_diagnostics`, the upload
triggers, Settings > HELP), companion and dashboard crash reporting
(`crash_report.py` on both sides), the dashboard Health page ("what is running",
"what these computers said", the crash-reports zip), dashboard logging and the
compose files for all three deploy shapes, the vendor release feed
(`release_feed.py`, `publish_feed.py`, `publish_latest.py`), the setup wizard's
software / release-key tasks, the protection panel, `/help` and
`published_docs.py`, the onboarding wizard's calls to the dashboard, the EULA's
support and contact sections, and `check_deploy_drift.ps1`. Checked against
KNOWN_BUGS.md, COMMERCIAL_READINESS.md and the 2026-09-24 hunt. None of the
findings below is recorded there.

Not covered: the triage agent's mail loop (gated off in the vendor build), the
Android app, Cards-specific diagnostics.

What already works well: the companion's diagnostics bundle is thorough and
reaches the customer's dashboard on its own (button, lane error, admin ask); the
Health page's "what is running" panel answers version questions for the
customer's admin; per-machine [ UPDATE NOW ] exists. The gaps are almost all
about the step from the customer's admin to the vendor.

### prac-support-1 - Nobody can find out how to contact the vendor: no support contact anywhere in the product
- Severity: high
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/alerts.py:3316, dashboard/src/ccsync_dashboard/release_feed.py:1290, dashboard/templates/partials/admin_packages.html:162,375, dashboard/templates/partials/health_diagnostics.html:15, companion/src/ccsync_companion/assets/EULA.md:130,198-207, dashboard/src/ccsync_dashboard/published_docs.py:38-49
- What: The product tells admins to "Ask the vendor" in three places and offers a crash zip "to send to support", but no screen, tray item, help document or site manifest key says who the vendor is or how to reach them. The only address is buried in EULA section 14 (contact@thecreatorsclub.co). EULA section 8 says support is "as described in your order or support plan". No repo document is a support runbook (what to ask a customer for, in what order). The customer-facing docs (`HOW_IT_WORKS.md`, `EDITOR_SETUP.md`, legal) have no troubleshooting section for admins.
- Scenario: A customer's Health page says "the vendor's build needs a newer dashboard: ask the vendor". The admin cannot find out where to ask. They either dig through the EULA or give up, and the vendor hears nothing until the customer escalates through sales.
- Recommendation: Add `support_contact` (email/URL) to the site manifest, defaulted from the vendor build. Show it in /help, in the Health page header, beside every "ask the vendor" line, in the companion's Settings > HELP, and on the wizard's Done step. Write `docs/SUPPORT.md` for both sides: the admin's "before you email us" checklist (Health > download support bundle, the computer's diagnostics, versions) and the vendor's triage runbook.
- Known: none

### prac-support-2 - Customer installs have no update channel: the vendor cannot push any fix to an appliance or generically installed site
- Severity: high
- Confidence: CONFIRMED
- Where: dashboard/deploy/compose.appliance.yaml:150-175 (no DASH_RELEASE_FEED_URL, no DASH_RELEASE_PUBKEYS), dashboard/src/ccsync_dashboard/settings.py:910-919 (both env-only, default empty), dashboard/deploy/Dockerfile (no ENV defaults), docs/INSTALL.md:210-235, dashboard/src/ccsync_dashboard/setup_engine.py:1536-1541, dashboard/src/ccsync_dashboard/protection.py:699-700, dashboard/templates/partials/admin_packages.html:476, docs/APPLIANCE_INSTALL.md ("nothing publishes a companion build to this fleet from the appliance")
- What: The appliance compose says the pubkeys "appear at boot (WP D)", but nothing generates or reads them except the environment. An appliance boots with no vendor feed and no trusted key, so every publish returns 503, the feed poller never starts and dashboard OTA is impossible. The generic `INSTALL.md` step 6 tells the customer to run `release_key.py new` and `bake`, which mints THEIR OWN key and bakes it into a companion they do not build. The wizard says "the public half of your release key ... (docs/RELEASE.md)". With no feed, the Packages page tells the admin to run `tools\ship.cmd` from "your wired computer" and see `docs/RELEASE.md`. Neither ships to a customer (`published_docs.PUBLISHED_DOCS`), and neither applies to one. Nowhere customer-facing gives the vendor's feed URL or public key.
- Scenario: A new customer installs the appliance. A week later the vendor fixes a sync-safety bug and publishes it to the feed. The customer's dashboard never reads the feed. Their editors stay on whatever companion was hand-installed, and when the admin opens Packages, the instructions are for a script that only exists in the vendor's private repo.
- Recommendation: Bake the vendor's feed URL and public key(s) into the image as defaults that the environment can override, with policy `stage` or `current`. Show both read-only on the wizard's "Software for editors" step. Rewrite the three copy sites to say "the vendor's signing key" and drop `ship.cmd` / `docs/RELEASE.md` from customer-visible text. Split `INSTALL.md` step 6 into a vendor-only appendix.
- Known: none (APPLIANCE_INSTALL.md lists it as NOT YET TRUE, but nothing tracks it as a launch blocker)

### prac-support-3 - Every correctly configured customer gets a permanent red "release key not backed up" finding they cannot fix
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/protection.py:483-505 (`_check_key_backup`), 702-712
- What: The check goes quiet only when no release key is configured. A customer who sets `DASH_RELEASE_PUBKEYS` to the vendor's key (required to take vendor builds) gets "broken: nobody has confirmed that the offline release key is backed up. Lose it and no further update can ever be published". The fix text says to copy the key "off that workstation". The customer has no private key; the vendor holds it. The finding counts in the Health page's open total.
- Scenario: Every paying customer's Health page shows a red protection line from day one. The admin either clicks "I have backed it up" without having anything to back up, which trains them to dismiss red, or emails support asking for "the release key".
- Recommendation: Return not_checked ("the vendor holds this key") when the configured keys are the vendor's baked default(s), or when the site has never published a package itself. Show the line only to a site that signs its own builds.
- Known: none

### prac-support-4 - The dashboard's own log is neither kept nor reachable, and there is no server support bundle
- Severity: high
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/crash_report.py:28-30,292-310 (DASH_LOG_DIR opt-in), dashboard/deploy/compose.appliance.yaml / compose.image.yaml / compose.yaml / server/install_dashboard_app.py:2497 (DASH_CRASH_DIR set, DASH_LOG_DIR set nowhere), dashboard/templates/admin_health.html, dashboard/src/ccsync_dashboard/ui.py:4555 (only a crash zip)
- What: The dashboard logs to stdout only. In every deploy shape the json-file driver caps it at 20 MB, and it is discarded when the container is recreated, which happens on every image update or NAS app restart. No admin page shows or downloads the log. The only server-side download is crash-reports.zip, and its button appears only when a thread has actually crashed. Most server problems produce a WARNING line and no crash: feed refusals, publish refusals, a collector cycle failing quietly. Those leave nothing an admin can fetch, so diagnosing one needs `docker compose logs` on the NAS, the shell this product's sweeps assume the customer does not have.
- Scenario: A customer reports "the update never arrived". The reason is one `release feed: ... cannot be made current here` WARNING (release_feed.py:995). Getting it means walking a non-technical admin through Container Manager's log view, or SSH.
- Recommendation: Set `DASH_LOG_DIR=/data/logs` in all three compose shapes. Add [ DOWNLOAD SUPPORT BUNDLE ] to the Health page: one zip with VERSION, git sha, runtime id, schema version, the what-is-running block, open findings, the last N lines of the rotating log, crash files, the newest diagnostics bundle per computer, and settings with secrets masked. Name it in prac-support-1's checklist.
- Known: none (bug-hunt-2026-08-21 recommended DASH_LOG_DIR on by default in the appliance; it was not done)

### prac-support-5 - The companion's diagnostics name a crash but drop its message and traceback
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/app.py:9700-9710 (build_diagnostics crash section), companion/src/ccsync_companion/crash_report.py:243-264 (`recent_reports` returns name/when/thread/type only), app.py:9734 (40-line log tail)
- What: The bundle is the one artefact that reaches the dashboard unattended. Its crash section prints only `<when> TypeError in thread X (<file>.json)`. The message, the traceback and the 200-line breadcrumb all stay in `~/.ccsync/crashes/` on the editor's machine, with no button that opens that folder. The log tail is 40 lines. The crash module's own docstring promises to turn "send me your log" into "send me one small file", but no part of the product sends that file.
- Scenario: A lane thread dies on a remote editor's Mac. The admin presses [ ASK THIS COMPUTER WHY ] and forwards the bundle to the vendor, who sees "KeyError in thread ccsync-lane-b". The vendor must then get a non-technical editor to find a hidden folder and email a JSON file.
- Recommendation: Include the newest crash's exception message and the last ~30 traceback lines in the bundle, passed through `_redact_diagnostics` like the rest. Raise the tail to ~200 lines (still well under a few tens of KB). Add an OPEN CRASH FOLDER item next to OPEN LOG.
- Known: none

### prac-support-6 - The vendor has no view across customers: a problem is learned only when a customer emails
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/release_feed.py (the feed fetch carries no identity), dashboard/src/ccsync_dashboard/alerts.py:272-300 (sink `none` and heartbeat off in the vendor build), EULA.md:136-138 ("The Licensor has no access to your dashboard")
- What: The design deliberately has no phone-home, which is defensible for privacy. But it puts no opt-in replacement in place, so the vendor cannot answer "which customers are on the dashboard build with the bug" or "whose feed check is failing". With the alert sink `none` by default, the customer's own admin may not know either. The existing weekly report and heartbeat could carry this if the vendor were a recipient, but nothing documents or offers that.
- Scenario: A bad companion build is recalled. The vendor cannot tell which of ten customers already made it current, and has to email all ten and wait for answers.
- Recommendation: Add an opt-in "share health with the vendor" setting (off by default, named in TELEMETRY.md). It would send a small daily signed POST of versions, schema, feed-check result and open finding KINDS (no names or paths), plus a vendor-side list of sites. At minimum, until then, document adding the vendor address as an extra alerts/weekly-report recipient as part of onboarding a paying customer.
- Known: none

### prac-support-7 - No documented way to ship a fix to one customer only
- Severity: medium
- Confidence: CONFIRMED
- Where: tools/publish_latest.py:46 (`FEED_REPO` hard-coded, one channel), docs/RELEASE_FEED.md:61-62 (`channel` is display-only), docs/RELEASE_PATHWAYS.md:27, dashboard/src/ccsync_dashboard/release_feed.py:648-673
- What: There is one global feed. A path does exist: publish the hotfix STAGED (without --make-current, so the signed `current` pointer keeps every auto-policy site on the old build). The one customer's admin then presses [ PUBLISH ] on Packages and pushes it to one computer or makes it current. No runbook describes this, and RELEASE_PATHWAYS says the feed reaches "every dashboard ... per its policy". The soak gate and `--allow-behind` make the recipe non-obvious. On a feed with no `current` entry for that kind/platform, the fallback is "highest version wins", which would hand the hotfix to every auto-policy site.
- Scenario: Customer B hits a Synology-only bug. The vendor builds 0.9.83 and has to choose: put it in front of everyone (`--make-current`), or work out the staged path live on a call with B's admin.
- Recommendation: Add a "hotfix for one site" section to RELEASE_PATHWAYS.md that says staged publish, then the customer admin's two clicks, then the later promotion. Make publish_feed refuse a staged publish when the channel has no `current` pointer for that pair. Later, consider per-site channel files (`channel-<site>.json`) chosen by the feed URL.
- Known: none

### prac-support-8 - The default deploy shape cannot take a dashboard fix without SSH, the base rig and the repo
- Severity: medium
- Confidence: CONFIRMED
- Where: server/install_dashboard_app.py:1402-1407 (`DEFAULT_STACK_MODE = "bind"`), dashboard/src/ccsync_dashboard/dashboard_update.py:36-40 (bind-mount refuses every apply), docs/DOCKER.md:12-14
- What: Dashboard self-update over the feed (WP K) works only in image mode, and image mode is opt-in. A customer installed by INSTALL.md's defaults gets bind mode. Every dashboard fix then means someone runs `server/install_dashboard_app.py` over SSH from a machine holding the repo checkout and the NAS secrets. For a customer, that someone is the vendor.
- Scenario: A dashboard-side fix (most of the 2026-09 fix passes) has to be delivered to ten customers as ten SSH sessions.
- Recommendation: Make image mode the default for every new site and keep bind mode as a vendor/studio option. Have the wizard or Health page flag a bind-mode customer site as "cannot update itself".
- Known: none

### prac-support-9 - A failed editor install is invisible to the admin and the vendor
- Severity: medium
- Confidence: CONFIRMED
- Where: onboarding/onboard.py:1302-1336 (COPY LOG only), onboarding/steps.py:929-1382 (calls only /verify, /ssh-key, /health, /site)
- What: Once sign-in succeeds, the wizard holds a credential and the dashboard URL. But it never tells the dashboard whether the install finished, failed, or at which step. A failure exists only in the wizard window and its local log file. The editor has to press COPY LOG and paste it to someone.
- Scenario: A new editor's install fails at the Syncthing step at 10 pm. The admin's dashboard shows nothing, not even "tried to install", and the morning starts with a screenshot hunt.
- Recommendation: After /verify succeeds, POST the outcome (step reached, error line, last ~100 log lines, wizard and companion versions) to `/api/v1/diagnostics` with trigger `install`, and render it under "what these computers said".
- Known: none

### prac-support-10 - No way to mark a release as urgent, and the default policy is manual
- Severity: medium
- Confidence: CONFIRMED
- Where: tools/publish_feed.py:1037-1134 (no urgency/security field), dashboard/src/ccsync_dashboard/settings.py:918 (`release_feed_policy` defaults to `manual`), dashboard/src/ccsync_dashboard/alerts.py:2548-2571
- What: A feed record carries only free-text `notes`, which is unsigned. A data-safety or security fix looks exactly like a cosmetic one on the customer's Packages page and in the "behind the vendor" alert. With the policy `manual` and the alert sink `none` by default, it waits until an admin happens to open the dashboard.
- Scenario: The vendor ships a fix for a lane-B delete edge. Nine of ten customers are still on the old build a month later because nothing told their admin this one mattered.
- Recommendation: Add a signed `severity` field (`routine` / `recommended` / `urgent`). Show an urgent record as a banner for all admins and as an alert kind that bypasses the digest. Consider `stage` as the default policy for new sites.
- Known: none

### prac-support-11 - Stored diagnostics are hard to forward, and the companion bundle does not identify the site
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/health_diagnostics.html:18-24, companion/src/ccsync_companion/app.py:9507-9548
- What: A bundle on the Health page is a `<pre>` inside a fold, with no copy or download button. The bundle itself carries the dashboard URL but not the org name or the dashboard version, so a pasted bundle in the vendor's inbox does not say which customer it is from or what server it talked to.
- Scenario: An admin forwards three bundles from different computers. The vendor has to work out from tailnet hostnames which customer sent them and what server version they ran.
- Recommendation: Add [ COPY ] and [ DOWNLOAD .TXT ] to each bundle. Put `site: <org_name>` and the dashboard version from the last report reply in the bundle header.
- Known: none

### prac-support-12 - Crash-report "opt-in sending" is dead configuration in every shipped build
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/config.py:356-363, companion/src/ccsync_companion/crash_report.py:357-402, dashboard/src/ccsync_dashboard/crash_report.py:24-27, docs/CONFIG.md:937, docs/legal/PRIVACY.md:149
- What: `crash_reporting` / `crash_dsn` (companion) and `DASH_SENTRY_DSN` (dashboard) need `sentry_sdk`, which neither the frozen companion nor the image includes, and the code says a customer would have to "compile their own". So it is a documented feature, a PRIVACY.md row and two config keys that no paying customer can switch on.
- Scenario: A customer's IT reads CONFIG.md, sets `crash_reporting = true` plus a DSN, and gets nothing except an INFO line in a log nobody reads.
- Recommendation: Either remove the keys and the PRIVACY.md row, or replace them with what the product can actually do: prac-support-4's bundle and prac-support-6's opt-in vendor report. Do not leave a switch that cannot work.
- Known: none
