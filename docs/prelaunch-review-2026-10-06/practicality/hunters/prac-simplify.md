# Practicality pass: prac-simplify (complexity that earns nothing)

Lens: dead code, dormant features, one-customer special cases, dev hatches,
two mechanisms for one job, docs and plans to archive, features to cut or hide
for v1. Ranked by risk removed per unit of effort.

Read: `settings.py` (auth method, shared token), `setup_api.py`,
`compose.appliance.yaml`, `Dockerfile`, `run.sh`, `api.py` (`/verify`,
credential shapes, `/jobs`, device approve), `triage.py`, `cards*.py` sizes
and mounts, `android.py` + `docs/ANDROID.md`, `published_docs.py`,
`docs/EDITOR_SETUP.md`, `docs/INSTALL.md`, `docs/DOCKER.md`,
`docs/APPLIANCE_INSTALL.md`, `docs/ZERO_DOWNTIME_DEPLOY.md`,
`docs/RELEASE_PATHWAYS.md`, `docs/PRODUCT_REPO.md` +
`tools/make_product_repo.ps1`, `site.example.toml`, `broll/web/app/config.py`,
`companion/build.spec`, `ytdl_browser_login.py`, `broll_vlm/__init__.py`,
`docs/legal/TELEMETRY.md`, KNOWN_BUGS (CR-18, WPK-*, open titles),
COMMERCIAL_READINESS items 1, 2, 10, 14. Greps for env hatches,
customer strings and duplicated modules.

Not covered: the individual SPA front-ends, the music indexer internals,
macOS installer scripts beyond what EDITOR_SETUP says, the full `server/`
script set. No probes were run (everything below was closed by reading the
code path).

### prac-simplify-1 - The appliance install cannot create its first admin: the compose file leaves auth on the legacy SMB default
- Severity: high
- Confidence: CONFIRMED
- Where: dashboard/deploy/compose.appliance.yaml:153-173; dashboard/src/ccsync_dashboard/settings.py:140, 807; dashboard/src/ccsync_dashboard/setup_api.py:38-75; dashboard/deploy/Dockerfile (no ENV for it); docs/APPLIANCE_INSTALL.md:108-115
- What: There are three login mechanisms (`smb`, `oidc`, `local`). The zero-touch appliance is designed around `local` (no NAS credential exists), but `DASH_AUTH_METHOD` is set nowhere on that path: not in the compose environment block, the Dockerfile or `run.sh`. `Settings.auth_method` therefore defaults to `smb`. Under `smb`, `POST /api/v1/setup/admin` returns 403 ("first-admin setup only applies when DASH_AUTH_METHOD=local"), `/setup/status` reports `users_exist: True`, and every other setup route needs an admin session. That session would come from an SMB probe against `DASH_SMB_HOST`/`nas_host`, and the appliance leaves both unset on purpose.
- Scenario: A new customer follows APPLIANCE_INSTALL.md, runs `docker compose up` and opens `/setup`. Step 2 "Create your admin account" is refused or never offered, and no login can succeed. They cannot get past the wizard without editing the compose file to add a variable that no customer document tells them to set.
- Recommendation: Put `DASH_AUTH_METHOD: "local"` in compose.appliance.yaml. Better still, make `local` the default whenever no NAS host is configured. Treat `smb` as the studio's legacy opt-in, set explicitly by `install_dashboard_app.py`. Add one appliance test that boots `Settings.from_env` with exactly the compose environment and asserts `/setup/admin` succeeds.
- Known: ZERO_TOUCH_PLAN WP C says "`smb` stays the default"; nothing records that the appliance compose inherits it.

### prac-simplify-2 - Two fleet credentials, and the weak one is the default: /verify hands every editor the shared fleet secret, while per-editor tokens are a manual side path
- Severity: high
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/api.py:2434-2456 (`api_verify`), 160-200 (credential shapes); settings.py:135, 805-806 (`shared_report_token_enabled` default True); onboarding/steps.py:993-1060
- What: `/verify` checks a username and password, then returns `settings.report_token`. That is the ONE shared fleet secret, and it "proves only somebody in this fleet". The bound, revocable `cce1.` token is minted by an admin on Users > REPORT TOKENS, copied, and passed out of band to the editor, who pastes it into the wizard. The documented reason is that /verify is "unauthenticated" and must never mint a token (CR-18). But /verify does authenticate (password check, throttle, fleet-membership check), and it already hands out the more dangerous secret. So the product has two credential systems, two code paths in every fleet route, and a boot log that names machines still on the shared token, all to support a default that a new customer never needs.
- Scenario: A new studio onboards 8 editors through the wizard. All 8 receive the same shared token. One laptop is stolen. Revoking that one person means rotating `DASH_REPORT_TOKEN` and re-onboarding all 8 machines, because none of them ever got a per-editor token: that path needed four manual steps per editor.
- Recommendation: For new sites, have /verify mint a bound per-machine `cce1.` token after the password check, and default `DASH_SHARED_REPORT_TOKEN_ENABLED` to off when the deployment has no machines that predate it. Keep the shared-token branch only as the studio's migration path, and plan to delete it.
- Known: CR-18 (FIXED, design "manual by design"); this is a challenge to that decision, not a re-report.

### prac-simplify-3 - Four install routes and two container modes, and every doc names the one nobody runs as the default
- Severity: high
- Confidence: CONFIRMED
- Where: docs/DOCKER.md:9-24 ("Bind-mount mode is the default and every live site uses it"); site.example.toml `[stack] mode` comment ("bind ... what every deployment runs today"); server/install_dashboard_app.py:9, 1402-1403, 1551, 4907 (`DEFAULT_STACK_MODE = "bind"`); docs/INSTALL.md:25-80 (needs a Windows base rig, Python, git, PyInstaller and a Mac); docs/ZERO_DOWNTIME_DEPLOY.md:13-15, 285 ("every live site is in image mode and bind-mount is the legacy path"); docs/SYNOLOGY_EASY_INSTALL.md ("nothing here exists yet"); docs/APPLIANCE_INSTALL.md (DRAFT)
- What: A new customer finds INSTALL.md + SERVER.md (operator SSHes from a base rig and runs install_dashboard_app.py, bind mode, pip at first boot), SERVER-SYNOLOGY.md (the same script with `--nas-kind synology`), APPLIANCE_INSTALL.md (compose + wizard, marked DRAFT) and SYNOLOGY_EASY_INSTALL.md (a design that is not built). The studio itself moved to image mode on 2026-08-18. ZERO_DOWNTIME_DEPLOY calls bind "legacy sites only", but the deploy script, the example manifest and DOCKER.md still make bind the default and say every site runs it. INSTALL.md still lists "for releases: PyInstaller and a Mac" as a customer prerequisite, which contradicts ZERO_TOUCH_PLAN's "only we build".
- Scenario: A customer's contractor follows INSTALL.md as written. They get bind mode: code shipped over SFTP from a Windows box, a venv pip-installed from PyPI at boot, and no OTA self-update (the handover cannot see new code in bind mode, ZERO_DOWNTIME §3.6). That puts the customer on the one path no live site runs and the vendor cannot update remotely.
- Recommendation: Choose one customer path for v1: the image or appliance route, with the wizard. Make `image` the default in install_dashboard_app.py and site.example.toml, and mark bind "studio legacy / dev only". Rewrite INSTALL.md's prerequisites with no base rig, no PyInstaller and no Mac. Move SYNOLOGY_EASY_INSTALL.md to an archive. Fix the DOCKER.md table.
- Known: none (WPK-2..5 are open on the image/OTA path and are related).

### prac-simplify-4 - The YouTube anti-bot and cookie sign-in code still ships in every companion exe and dashboard image, dormant
- Severity: high
- Confidence: CONFIRMED (the code ships); PLAUSIBLE (the legal weight, which is counsel's to judge)
- Where: companion/src/ccsync_companion/ytdl_browser_login.py, ytdl_cookies.py, ytdl_attestation.py, ytdl_executor.py, ytdl_server.py, ytdlp_manager.py, youtube_import.py (about 8,000 lines); companion/build.spec:248 (excludes only setuptools); ytdl/web (about 12,800 lines); dashboard ytdl.py; dashboard/deploy/requirements-unblock.*
- What: COMMERCIAL_READINESS item 2's fix said "remove the circumvention components from the vendor build". What landed is a feature flag. The flag turns the feature off, but the code is still compiled into every editor's exe and baked into the image: the DevTools-driven Google session cookie exporter, the PO-token and n-challenge plumbing, and the ytdl web app. About 22k lines that a customer with the flag off can never use still need maintenance, tests, licence review, and an answer if a customer's counsel asks "what does this binary contain?".
- Scenario: An organisation's IT or legal review unpacks the companion exe and finds a module whose stated purpose is driving a real browser to lift Google session cookies so downloads look like a logged-in browser. The feature being off does not change what was distributed.
- Recommendation: For v1, build the vendor companion and image WITHOUT the ytdl and unblock modules: exclude them in build.spec and do not COPY `ytdl/web` into the image. Keep the code in the studio's own build until counsel signs off. If that is too much work for launch, at least drop `ytdl_browser_login.py`, the cookie path and the unblock requirements from the vendor artefacts.
- Known: COMMERCIAL_READINESS item 2 ("DONE in repo, counsel owed"); CR-29..CR-39 cover functional defects in the same stack.

### prac-simplify-5 - The AI CLI door (Claude Code / Codex driven by a personal subscription) and the email triage agent that depends on it should be cut from v1
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cli_tools.py (2,593 lines: download wizard, pty sign-in, auto-update); ai_providers.py; triage.py:31-35, 190-204 (`cli_gate`: triage runs ONLY through the Claude Code CLI); triage_mail.py, triage_actions.py (2,183 lines with triage.py); site.example.toml `[features] ai_cli_providers`, `ai_cli_auto_update`
- What: The CLI providers exist so the studio can power Timeline Cards and the triage agent from a personal Claude subscription. The site manifest itself warns that this "may breach that subscription's terms". The triage agent cannot use an API key ("the Anthropic API provider is deliberately NOT a fallback"). So for a customer who follows the supported path (API keys), the triage agent is dead weight. It is also the most security-sensitive surface in the dashboard: an IMAP inbox whose replies trigger actions, gated on DKIM/DMARC parsing. CR-26 says the setup wizard was never verified on a container.
- Scenario: A customer turns on `alerts_triage`. Every scheduled run sends a "fallback" email saying Claude Code is switched off, because the only way to make it work is the ToS-questionable door. Alternatively, a customer turns the door on and the vendor is now the party that told them how to run a consumer subscription as a service.
- Recommendation: For v1, remove the CLI door from the customer feature set. Hide the Settings > AI providers CLI rows, the SET UP wizard and the `alerts_triage` setting unless a vendor-only flag is on. Either port triage to the SDK path (with tool use over the evidence) or ship it later.
- Known: CR-26 (OPEN, unverified on a container); COMMERCIAL_READINESS item 1.

### prac-simplify-6 - The fleet job scheduler runs on every customer's machines, and only Timeline Cards ever creates a job
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/api.py:11843 (`POST /api/v1/jobs`, admin only; the sole producers are Cards and `tools/jobs.py`); dashboard jobs.py (1,363 lines); companion jobs_runner.py (1,583), jobs_media.py (1,023); companion config.py:833 (`jobs_enabled: True`); docs/legal/TELEMETRY.md:274-275 (input_idle is sent while jobs_enabled); ui.py:267 (JOBS in every admin's Settings nav)
- What: Nothing in this repo queues a whisper, proxy-480p, audio-extract or peaks job except Timeline Cards, which lives in another repo and is never present on a customer's dashboard (prac-simplify-7). Even so, `jobs_enabled` defaults to true on every editor's computer. The companion then probes capabilities, polls offers, and reports `idle_seconds` (a personal-data telemetry category, LG-1) for a scheduler that will never have work. Admins see a JOBS page that is permanently empty.
- Scenario: A customer's privacy officer reads TELEMETRY.md and asks why keyboard and mouse idle time is collected from every editor. The honest answer is "for a feature you do not have".
- Recommendation: Tie the job stack to the Cards feature. `jobs_enabled` should default to false unless the site publishes a jobs-capable feature, the JOBS nav entry should hide when no job kind can be produced, and `input_idle` should not be collected in that state.
- Known: none.

### prac-simplify-7 - About 9,400 lines of Timeline Cards integration that a customer can never use
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cards.py, cards_ai.py, cards_catalog.py, cards_exec.py, cards_landing.py, cards_pool.py, cards_tunnel.py, cards_wsgi.py; companion timeline_cards_role.py, timeline_cards_bridge.py; dashboard/deploy/compose.image.yaml:191, 333 (`/cards-app` mount from a host checkout); server/install_dashboard_app.py:517-566; dashboard/templates/shell.html:33
- What: Cards' code is "another repo's checkout", never in the image or an OTA bundle, and is deployed by the studio's own snapshot recipe. A customer dashboard therefore always has an absent `/cards`, but still carries the mount logic, the engine pool, the `/cards/agent/*` tunnel on the fleet credential, the `sw.js` kill switch, the a2wsgi bridge and the pinned executor. The companion carries the agent role. Every one of these runs through the fail-absent machinery on every boot, and every bug hunt reviews it.
- Scenario: The vendor supports ten customers and none of them has Cards. Every dashboard release still has to be regression-tested against the Cards mount contract, the engine-pool refusal rules and the tunnel routing, for the studio alone.
- Recommendation: Put the whole Cards integration behind a vendor-only site feature (`timeline_cards`, off in the vendor build, as `youtube_download` is). When it is off, skip the mount, the routes, the tunnel and the companion role. Longer term, ship Cards as its own package.
- Known: none.

### prac-simplify-8 - The Android TWA needs a per-customer APK build, a signing keystore and a fingerprint paste: cut it for v1 and ship the PWA
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/android.py; dashboard/templates/partials/android_settings.html and admin_settings.html:271-277 (ANDROID panel); docs/ANDROID.md §1-§3; tools/android/build_apk.sh, twa_manifest.py; `.github/workflows/android.yml`
- What: The app is bound to ONE origin "baked in at build time". Every customer therefore needs their own APK, built with a JDK and the Android SDK or a CI dispatch, signed with a keystore that must never be lost ("losing it means every editor uninstalls and reinstalls"), plus the fingerprint pasted into Settings. ANDROID.md exists mostly to diagnose the silent failure (a URL bar). The PWA already does the same job without any of this.
- Scenario: The vendor has ten customers and therefore ten keystores, ten APKs and ten rebuilds whenever a customer changes port or hostname. One lost keystore forces every editor at that customer to reinstall.
- Recommendation: Remove the ANDROID settings panel from customer builds and document "install from Chrome" (the PWA) as the phone path for v1. Keep the TWA tooling vendor-side only, until a single vendor-published app (one package and key, with the origin configured at runtime) is designed.
- Known: none.

### prac-simplify-9 - The published editor guide describes the pre-wizard install, two ways of doing everything the wizard and dashboard now do
- Severity: medium
- Confidence: CONFIRMED
- Where: docs/EDITOR_SETUP.md:18-25, 56-70, 83-102, 159-166, 244 (published to every customer: dashboard/src/ccsync_dashboard/published_docs.py:42-45, REQUIRED_DOCS); dashboard api.py:6069 (`POST /admin/devices/approve`); onboarding/README.md
- What: EDITOR_SETUP.md is one of only two documents every customer's editors can read in /help. It tells them:
  - to run `windows_bootstrap.ps1 ... -DashboardToken <token-from-admin>` by hand, although the `onboard.exe` wizard exists and wraps that script;
  - on a Mac, to `chmod +x` and `xattr -d` a `.sh` in Terminal, although onboarding/README.md says the Terminal-only route caused "the worst support incidents";
  - that the admin approves the device by running `server/accept_device.py`, although the dashboard has an approve button;
  - to ask for "your TrueNAS username (they set this up with `server/setup_editor_account.py`)", which does not exist on a local-auth appliance.
- Scenario: An editor at a new customer reads /help, asks the admin for a "TrueNAS username" and a token, and the admin, who installed the appliance and has no base rig, cannot run `accept_device.py`.
- Recommendation: Rewrite EDITOR_SETUP.md around the one supported path: the admin invites, the editor runs the wizard and signs in, and the admin presses Approve on the dashboard. Move the manual bootstrap and the Terminal route to an "if the wizard cannot run" appendix in admin-only docs.
- Known: none.

### prac-simplify-10 - Two companion release pathways, and the one the studio uses most bypasses the feed every customer is on
- Severity: medium
- Confidence: CONFIRMED
- Where: docs/RELEASE_PATHWAYS.md (table and "Pathway A, when to prefer it"); tools/ship.cmd / ship.ps1; installer/build_editor_package.ps1 -Publish
- What: Pathway A builds the companion on the base rig and PUTs it straight into the studio's own dashboard, with an interactive password and `-AllowUnsignedBinary` on every ship so far. Pathway B builds on CI, signs locally and publishes to the vendor feed that every customer's dashboard reads. Once customers exist, any A ship puts the studio on bytes that no customer has, and the soak signal the studio provides ("it ran on our fleet first") is for a different artefact.
- Scenario: A Pathway-A 0.9.x soaks happily at the studio and is then rebuilt by CI for the feed with a different toolchain or dependency resolution. Customers get bytes the studio never ran, and the version-number rule makes the mismatch invisible.
- Recommendation: Once the first customer exists, retire A as a publishing route. The studio should take releases from the feed like any customer (`policy = stage`, then make current), and A stays only as a local dev build plus `windows_upgrade.ps1` on one machine.
- Known: COMMERCIAL_READINESS item 4 (Authenticode still absent).

### prac-simplify-11 - The "product repo" export is a denylist that has gone stale; make it an allowlist or drop it for v1
- Severity: medium
- Confidence: CONFIRMED
- Where: tools/make_product_repo.ps1:141-185 (TenantFiles, TenantGlobs), 331 (refusal text says "pystray is LGPLv3 and is frozen into" the exe, which is no longer true), 347-351 (`:(exclude,glob)`, where `*` does not cross `/`); docs/PRODUCT_REPO.md
- What: The export withholds a hand-kept list of files plus `docs/bug-hunt-*.md`. Because the pathspec glob does not cross a directory separator, every ledger directory written since the list was made would ship: `docs/bug-hunt-2026-09-03/` ... `-09-24/`, `docs/resilience-sweep-2026-08-28/`, `docs/usability-resilience-sweep-2026-09-03/`, `docs/UI_PORT_LEDGER/`, `*_LEDGER/`, this `prelaunch-review-2026-10-06/` tree, `docs/PROJECTS_CLEANUP_PLAN.md` (about the owner's personal `E:\Projects` tree), and every plan doc. The tenant-marker gate is the only backstop. `published_docs.py` already proves an allowlist works for the same problem.
- Scenario: Someone runs the export for a contractor or an auditor. If the markers pass, the contractor receives the dated bug-hunt directories: the same "map for an attacker" the script was written to withhold.
- Recommendation: Either decide that no customer gets source in v1 (the appliance ships images) and archive the tool, or turn the export into an allowlist of product trees plus the published docs.
- Known: COMMERCIAL_READINESS item 10.

### prac-simplify-12 - KNOWN_BUGS.md (31,993 lines, 1,151 entries) cannot answer "what is open?"
- Severity: medium
- Confidence: CONFIRMED
- Where: KNOWN_BUGS.md (e.g. :745 CR-18 still titled "FIXED in repo 2026-08-17, unshipped" although it is long shipped; WPK-2..5, CR-26, CR-29..45, R-series open titles mixed among 1,100 closed ones)
- What: The live defect ledger is an append-only narrative. Status lives in free-text titles that are not updated when a fix ships. Only about 49 headings lack a closed word, and several of those are actually closed. A vendor supporting customers needs a short list of open items with platform and severity, and this file cannot produce one without a person reading 32k lines. The file also has mixed CRLF/LF line endings (a memory note warns against sed on it).
- Scenario: A customer reports a symptom. Support cannot tell in minutes whether it is a known open defect, a fixed-but-unshipped one, or new.
- Recommendation: Split the ledger. KNOWN_BUGS.md becomes the open items only (one line each: id, status, versions, link). Closed entries move to dated `docs/archive/known-bugs-2026-*.md`. Normalise line endings while doing it.
- Known: none.

### prac-simplify-13 - The studio's own name is still the default a new customer gets: the tree, the share and the archive's own-footage folder
- Severity: low
- Confidence: CONFIRMED
- Where: site.example.toml:76 (`tree_name = "Creators_Club"`), :111-112 (`share_name`, `smb_unc`), :297-301 (archive_creators_dir); broll/web/app/config.py:191-206 (default "Creators_Club"); broll/indexer/build_archive.py:54 (`CREATORS = "Creators_Club"` literal); broll/web/app/config.py:135 (legacy `creators_club` collection alias); site.example.toml:433-446 (`ghcr.io/the-creators-club/...`); site.example.toml:89 + docs/CONFIG.md (`projects_dir`, a "setting" that is refused unless it is "Projects")
- What: The rule is "no customer's name in code", but the example manifest a new customer copies names their tree and SMB share "Creators_Club", and every customer's b-roll own-footage folder is literally `Creators_Club/` unless they find an optional key. `projects_dir` is documented as a key while refusing any value but its default.
- Scenario: A second studio copies site.example.toml, changes the host and pool, and ends up with `P:\` mapped to a share called Creators_Club and an archive folder named after another company.
- Recommendation: Use neutral example values (`tree_name = "Studio"`) and a neutral default archive folder (`Own_Footage`). Set the studio's real names in its own git-ignored site.toml, which already overrides them. Delete the `projects_dir` key from the example and CONFIG.md (or mark it "not configurable").
- Known: COMMERCIAL_READINESS items 10/11 (marked done; these defaults are the residue).

### prac-simplify-14 - Four admin pages answer "is it healthy" (HEALTH, INVARIANTS, PROTECTION, ALERTS), plus the home problems panel
- Severity: low
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/ui.py:274-279; invariants.py docstring ("the ledger, the admin page, the notices, the alert kind and the weekly report all pick it up"); ui_health.py
- What: Invariants already feed notices, which already feed HEALTH and the home page, and they also become alert kinds. INVARIANTS is therefore a second rendering of findings the admin already sees, under a word a studio owner does not use. The same holds partly for PROTECTION, whose findings are notices too.
- Scenario: A customer admin sees a red item on Home, opens Settings, and has to try four pages to find the one that explains it.
- Recommendation: Make HEALTH the single page. Show invariants and protection as tabs or rows in it, and keep ALERTS only for delivery settings and history.
- Known: none.

### prac-simplify-15 - Two b-roll indexing pipelines (base-rig CLI and companion drag-and-drop), kept in step by vendored copies
- Severity: low
- Confidence: CONFIRMED
- Where: broll/indexer/broll_index/{local_vlm,local_runtime,local_models,compact_format,contract}.py vs companion/src/ccsync_companion/broll_vlm/ (vendored, drift-checked by release.ps1 and server/tests/test_cross_component.py); docs/INDEXERS.md table; docs/INSTALL.md "B-roll search: an Anthropic API key on the base rig" (stale: the local backend is now the default)
- What: A zero-touch customer has no base rig, so for them the companion ingest is the only indexing path. The base-rig CLI is the vendor's back-catalogue tool. Both stay maintained as product, with a byte-identical copy rule between them, and INSTALL.md still tells customers b-roll needs an Anthropic key on a base rig.
- Scenario: A customer reads INSTALL.md, concludes b-roll search needs an API key and a GPU workstation, and turns it off.
- Recommendation: Document the companion ingest as the customer path and the base-rig indexer as vendor-assisted back-catalogue onboarding. Fix INSTALL.md's optional-features table.
- Known: COMMERCIAL_READINESS item 14.

### prac-simplify-16 - 97 docs at the top of docs/, many of them finished plans or one-session logs
- Severity: low
- Confidence: CONFIRMED
- Where: docs/ (e.g. SHARED_FOLDERS_PLAN.md, MULTI_MACHINE_PLAN.md, UI_REDESIGN_PORT_PLAN.md, UI_PORT_REVIEW_2026-09-25.md, SYNOLOGY_PORT_PLAN.md, SYNOLOGY_EASY_INSTALL.md, BROLL_PROXY_TIERS_PLAN(_AUDIT).md, LIBRARY_WALK_PLAN.md, TRAY_MENU_LATENCY.md, macos-first-run-2026-08-0*.md, macos-onboarding-handoff.md, youtube_dlp_bugs.md, PROJECTS_CLEANUP_PLAN.md, five dated bug-hunt .md files and their directories)
- What: The docs that a customer admin or a new engineer actually needs (INSTALL, SERVER, CONFIG, RELEASE, GOTCHAS, SYNC_SAFETY, BACKUP_RESTORE, API) sit among about 60 historical plans, sweeps and session logs with similar names. PROJECTS_CLEANUP_PLAN.md is about the owner's personal folder tree and does not belong in this repo at all.
- Scenario: A support engineer hired for launch opens docs/ and cannot tell the current runbook from a superseded plan (for example SYNOLOGY_EASY_INSTALL.md vs APPLIANCE_INSTALL.md vs INSTALL.md).
- Recommendation: Create `docs/archive/` for finished plans, sweeps and session logs. Keep the docs/README.md index to the current documents. Move PROJECTS_CLEANUP_PLAN.md to the `E:\Projects` README area (the top-level CLAUDE.md points at it, so update that pointer too).
- Known: none.
