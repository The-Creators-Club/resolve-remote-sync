# Pre-launch commercial review: customer experience (com-customer-experience)

Date 2026-10-06, HEAD 08b40eb plus the uncommitted working tree. Read-only.

**What this covers:** everything a paying customer sees that is not the sync engine itself. That means brand and name consistency; support contact and support artefacts; the about, licence and EULA surfaces; versioning shown to users; the documents that actually ship to a customer; uninstall cleanliness on Windows and macOS; offboarding when an editor or a whole customer leaves; accessibility; and i18n (non-English Windows, CJK paths).

**What I read:** `docs/COMMERCIAL_READINESS.md`, `LICENSE`, every file in `docs/legal/`, `published_docs.py` and `help.py`, `docs/EDITOR_SETUP.md`, `docs/INSTALL.md`, `docs/APPLIANCE_INSTALL.md`, `docs/TENANCY.md` (offboarding), both bootstraps' Apps & features and firewall sections, `installer/windows_uninstall.ps1` (whole), `macos_uninstall.sh` (rclone/Resolve parts), `companion/build.spec`, `eula.py` and the lane gate in `app.py`, the settings window's help and licence rows, the dashboard topbar, installer and help templates, the CC theme tokens (contrast computed), the locale handling in `drive_swap.py`, `paths.py`, `resolve_prefs.py` and `secretfile.py`, `tools/make_product_repo.ps1`'s tenant markers, and the KNOWN_BUGS entries for CR-6, CR-25, OPS-17 and CR-183.

**What I did not cover:** the macOS wizard UI, the b-roll, music and Cards SPAs' accessibility, a live screen-reader pass, and a real non-English Windows install.

### com-customer-experience-1 - Nothing in the product names a support channel, and the support artefacts the EULA promises do not exist
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:**
  - `docs/legal/EULA.md:128-130`
  - `docs/legal/PRIVACY.md:103-113`
  - `dashboard/templates/admin_settings.html:136`
  - `dashboard/templates/partials/health_diagnostics.html:15`
  - `dashboard/templates/partials/computer_answer.html:14`
  - `dashboard/src/ccsync_dashboard/notices.py:1456,1490,1585`
  - `dashboard/src/ccsync_dashboard/app.py:469`
- **What:** The product tells the customer's admin to "send to support" in several places: the notices, the crash-report zip ("to send to support"), the server log, and "change these only if support asks you to". No template, setting or site-manifest key holds a support address, URL or hours. The only contact anywhere is `contact@thecreatorsclub.co`, at the bottom of the legal documents. That one inbox serves privacy, security, sales and support.

  The EULA §8 says "Support and updates are provided as described in your order or support plan". There is no order form, support plan, SLA, DPA template, status page or public changelog anywhere in the repo. PRIVACY §3 offers a signed GDPR Art. 28 DPA "on request", and none is drafted.
- **Scenario:** A customer admin sees "Copy the text of this notice and send it to support" during an outage. They have no idea who support is, so they email the generic inbox or nobody. A procurement or legal reviewer asks for the support plan, SLA and DPA the EULA and privacy policy point to, and there is nothing to send.
- **Recommendation:** Code: add a vendor-level `support_url` / `support_email` constant. Make it build data, not site data, with an optional site override for a reseller. Render it on /help, in the topbar menu, next to every "send to support" line and in the companion's help rows. Non-code, owner plus counsel:
  - a support-plan document (hours, response targets, channel, what is included)
  - an order-form template the EULA can reference
  - a DPA template
  - a public status/changelog page for the vendor feed
  - a separate support address so security and privacy reports are not mixed with sales.
- **Known:** not in KNOWN_BUGS.

### com-customer-experience-2 - A new EULA version stops sync on every editor computer until each editor clicks ACCEPT
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:**
  - `companion/src/ccsync_companion/eula.py:215-249`
  - `companion/src/ccsync_companion/app.py:6445-6466`
  - `docs/legal/EULA.md:1-10` (maintainer note: "a bump sends every editor in every fleet back through acceptance")
- **What:** `acceptance_problem()` refuses to sync whenever the accepted version is below the bundled marker. There is no grace period, no "material change" distinction, and no acceptance by the organisation. The contracting party is the Customer (the organisation), but consent is a per-editor click, repeated on every computer. Any wording fix to the EULA therefore becomes a sync outage at every customer. When `auto_update` is on, it happens unattended.
- **Scenario:** The vendor fixes a typo in the EULA (version 1.2) and publishes companion 0.9.90 to the feed. Every customer's auto-updating companions take it overnight. Uploads (lane A) and downloads stop on every editor machine until each editor finds and accepts the modal. An unattended base rig or render node stops until someone logs in. The memory ledger already records this happening on this studio's own fleet with EULA 1.1 ("re-consent parks 0.9.82 machines").
- **Recommendation:** Keep blocking only on first install. On a version change, keep syncing and show a non-blocking notice for N days. Let the admin's acceptance on the dashboard (the org) cover the fleet, with editors only acknowledging. Give the EULA a "material change" flag, separate from typo bumps. Counsel should confirm that org-level acceptance in the setup wizard is the operative consent.
- **Known:** not recorded as a defect in KNOWN_BUGS (memory note only).

### com-customer-experience-3 - The customer is told to bypass Windows SmartScreen, and the exe carries no publisher or version metadata
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:**
  - `dashboard/templates/installer.html` (the "Windows protected your PC ... Run anyway" note)
  - `companion/build.spec:264-302` (no `version=` VSVersionInfo)
  - `onboarding/build_onboard.spec`
  - `KNOWN_BUGS.md:512-534` (CR-6)
- **What:** No Authenticode or Developer ID certificate exists. The product's own installer page tells customers to click "More info, Run anyway". macOS builds are ad-hoc signed, so Full Disk Access is lost on every self-update (`app.py:3051`). On top of that, PyInstaller is given no version resource, so the exe's Properties show no CompanyName, ProductName, FileVersion or copyright. SmartScreen and AV products show "Unknown publisher".
- **Scenario:** A customer's IT department enforces SmartScreen, AppLocker or Defender ASR, which most managed studios do. The installer cannot run at all, so a new customer cannot be installed. Where it can run, the first thing a buyer's editors are taught is to override a malware warning.
- **Recommendation:**
  - Buy an OV/EV Authenticode certificate and an Apple Developer ID plus notarisation (owner purchase; the CR-6 hooks already exist).
  - Add a VSVersionInfo resource (CompanyName = the legal entity, ProductName = the product name, FileVersion = VERSION, LegalCopyright) to both specs.
  - Remove the "Run anyway" note the day the build is signed.
- **Known:** CR-6 (OPEN for certificates).

### com-customer-experience-4 - The Windows uninstall from Apps & features leaves the fleet credential, the SSH key and the rclone remote on the machine
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `installer/windows_uninstall.ps1:316,720-806`
  - `installer/windows_bootstrap.ps1:928-934` (UninstallString has no `-Full`)
  - `installer/macos_uninstall.sh:275` (macOS does remove its rclone stanza)
- **What:** Apps & features runs the uninstaller with no switches. That is the "keep sign-in + settings" mode, so it keeps:
  - `~/.ccsync/config.toml`, with the per-editor `cce1.` fleet token and `dashboard_token`
  - `identity.json`
  - the Syncthing identity.

  Even `-Full` keeps `~/.ssh/ccsync_ed25519`, a passphrase-less key to the customer's NAS, and only prints a NOTE about it. The Windows uninstaller never touches the `[<remote>]` stanza in `%APPDATA%\rclone\rclone.conf`, which the macOS uninstaller does remove. The LUT Locations entries the companion appended to Resolve's `config.dat` are left without a word. The macOS script at least prints a line about Resolve's mapped mount.
- **Scenario:** An editor leaves, or a laptop is reassigned. IT uninstalls "CC Sync" from Settings > Apps and believes it is gone. The machine still holds a working fleet credential, a NAS SSH key and an rclone remote that reaches the project tree, until the admin separately revokes them on the server.
- **Recommendation:** Make the Apps & features entry ask, or offer a second "CC Sync (remove everything)" mode. Delete the SSH key and the Windows rclone stanza in `-Full`, as macOS already does for rclone. Print the Resolve-preferences leftovers on Windows too. Document in the customer guide that the server-side revoke on the Users page is the real offboarding step.
- **Known:** not in KNOWN_BUGS (OPS-17 and CR-183 cover registering the entry, not what it leaves).

### com-customer-experience-5 - Apps & features shows the customer as Publisher and a frozen, wrong version number
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `installer/windows_bootstrap.ps1:289,1019-1027,928-943`
  - `companion/src/ccsync_companion/config.py:156`
  - `companion/src/ccsync_companion/settings_window.py:1860-1871`
- **What:**
  - `Publisher` is set to the site's `org_name` (the customer), not the vendor.
  - `DisplayVersion` is the installer version (1.0.46), written once at install. Nothing updates it when the companion self-updates; the only writer is the bootstrap.
  - The tray shows "ccsync-companion v0.9.85", the dashboard is 0.7.73, the onboarder is 1.0.46 and the EULA is 1.1.
  - There is no HelpLink or URLInfoAbout.
  - The companion has no About entry naming the licensor, copyright or EULA, or offering to re-open the accepted EULA.
- **Scenario:** A customer's IT asset inventory lists "CC Sync (Acme Studios), publisher Acme Studios, 1.0.46" on every machine for ever. Meanwhile the support desk asks "which version are you on?" and gets three different answers.
- **Recommendation:**
  - Publisher = the legal entity.
  - Refresh DisplayVersion from the companion after every upgrade (HKCU, so no elevation is needed).
  - Add HelpLink/URLInfoAbout pointing at the support URL from finding 1.
  - Add an About row in the settings window: product, version, licensor, copyright, and links to the EULA, privacy policy and licences.
  - Decide one customer-facing product version (see finding 11).
- **Known:** not in KNOWN_BUGS.

### com-customer-experience-6 - The brand is unresolved: four names, two spellings, and the export tooling treats the vendor as a tenant
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `tools/make_product_repo.ps1:202-206`
  - `docs/legal/EULA.md:16,200-207`
  - `docs/COMMERCIAL_READINESS.md` item 10 follow-ups (CR-25)
  - `companion/src/ccsync_companion/*.py` (218 "CCSync" strings vs 22 "CC Sync")
  - `onboarding/steps.py` (62 vs 2)
- **What:** A customer meets:
  - the product as "CC Sync" (dashboard, legal) and as "CCSync" (every tray toast, wizard step and installer line)
  - the Creators Club "CC" mark (CR-25: "branded Creators Club software")
  - the licensor Cablewrap Creative Ltd.
  - the contact domain thecreatorsclub.co, which also names a production studio, possibly the buyer's competitor.

  `make_product_repo.ps1` still lists "Cablewrap", "Creators Club" and "creatorsclub" as tenant markers that refuse an export. Those strings now appear by design in the final EULA, PRIVACY, THIRD_PARTY_NOTICES and the contact email (`contact@thecreatorsclub.co` matches `creatorsclub`, case-insensitive). The tool and the CR-25 ruling contradict each other about who the vendor is. No trademark clearance for "CC Sync" or the mark is recorded.
- **Scenario:** A buyer's procurement team sees an invoice from Cablewrap Creative Ltd. for "CCSync" with a Creators Club logo, support at a studio's domain, and Apps & features calling the customer the publisher. They cannot tell who they are contracting with. The product-repo export refuses on the vendor's own legal documents.
- **Recommendation:** Owner decision, written down in one doc:
  - the product name and its single spelling
  - the vendor brand versus the legal entity
  - the support domain (ideally a product domain, not the studio's).

  Then run one sweep of user-visible strings to the chosen spelling, with a scan test like the em-dash one. Move the vendor's own names out of `$TenantMarkers` into an allow-list for `docs/legal/`. Commission a trademark search before selling under the name.
- **Known:** CR-25 (decision recorded; the conflicts above are not).

### com-customer-experience-7 - The documents shipped to customers are internal runbooks, and there is no customer-admin guide
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `dashboard/src/ccsync_dashboard/published_docs.py:41-53`
  - `docs/EDITOR_SETUP.md:12,19-26,55-90,161,299,473`
  - `docs/INSTALL.md:57,88,217-219`
  - `docs/APPLIANCE_INSTALL.md:1-17`
- **What:** Only `HOW_IT_WORKS.md`, `EDITOR_SETUP.md` and `legal/` ship. EDITOR_SETUP is written for a technician:
  - it opens with a PowerShell `windows_bootstrap.ps1 -TailnetHost ... -DashboardToken ...` command, not the onboard.exe wizard the dashboard serves
  - it says "Your TrueNAS username (they set this up with `server/setup_editor_account.py`)", even on Synology
  - it sends the admin to run `server/accept_device.py`
  - it mentions "the studio base rig"
  - it cites `docs/COMMERCIAL_READINESS.md` and `docs/MULTI_MACHINE_PLAN.md`, which do not ship.

  No customer-admin guide ships at all. INSTALL.md assumes a `git clone` of the proprietary repo, Python on a "base rig", and the customer minting and baking their own release key. APPLIANCE_INSTALL.md is marked DRAFT until a non-author has run it.
- **Scenario:** A new customer's admin opens /help after install. They find an editor guide that tells editors to run scripts the customer does not have, and nothing on day-2 admin tasks: adding an editor, approving a device, backups, offboarding, updates.
- **Recommendation:** Write and publish a customer-facing set:
  - an editor quick start built around the wizard
  - an admin guide (install from the appliance compose, add/remove people, approve computers, backups and restore, updates, uninstall/decommission)
  - a troubleshooting/FAQ page.

  Strip repo script names, dates and internal doc references from what ships. Add a test that a published doc does not reference an unpublished one.
- **Known:** not in KNOWN_BUGS.

### com-customer-experience-8 - The normal install blocks every inbound SMB share on the editor's computer, with no disclosure or opt-out in the wizard
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `installer/windows_bootstrap.ps1:1406-1430,1648-1657`
  - `onboarding/steps.py` (no `KeepRemoteSmbOpen` anywhere)
- **What:** To protect the loopback `CCSync_P` share, the bootstrap adds an inbound Block rule on TCP 139/445, for any remote address and any profile. That blocks every SMB share the computer serves, not just ours. The only opt-out is the `-KeepRemoteSmbOpen` switch on the raw PowerShell script. The wizard, which is the documented install path, never passes it or mentions it.
- **Scenario:** A studio editor's PC shares a "Renders" or "Exports" folder with a colleague or a print/ingest station. After installing CC Sync that share stops working from the network, and nothing tells IT why. It looks like a Windows fault, and the product gets the blame once someone finds a rule named after it.
- **Recommendation:** Scope the rule so it does not deny the machine's other shares. If that cannot be done, add a wizard step that says plainly "this blocks file sharing FROM this computer to the network", with a checkbox mapped to `-KeepRemoteSmbOpen`. Put it in the admin guide too.
- **Known:** the rule itself is documented in KNOWN_BUGS (CR-17 area, line ~732); its impact on other shares and the wizard's missing opt-out are not.

### com-customer-experience-9 - There is no offboarding path for a customer that leaves
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `docs/legal/EULA.md:179-184`
  - `docs/TENANCY.md:203-220` (per-editor only)
  - `server/` (no teardown script)
  - `docs/SERVER.md`, `docs/SERVER-SYNOLOGY.md`, `docs/APPLIANCE_INSTALL.md` (no decommission section)
- **What:** EULA §12 obliges a terminated customer to "remove it from your systems", but nothing tells them how. Per-person export and erase exist (PRIVACY §8). There is no documented or scripted way to:
  - remove the dashboard and Syncthing apps from the NAS
  - remove the editor NAS accounts and keys, the snapshot tasks, the scoped API key, the Tailscale Serve/Funnel publications (public client-share links) and the bundled tailnet node
  - uninstall the companion across the fleet (no `commands.uninstall`)
  - export the site's own records (users, audit, client folders) in one archive before teardown.
- **Scenario:** A customer cancels. Their admin has to find and remove containers, accounts, firewall and Funnel settings by hand. Public client-share links can stay reachable after the relationship ends. The vendor's support desk gets the "how do we get rid of it" ticket with no runbook.
- **Recommendation:**
  - Write a "Leaving CC Sync" admin page: export, then fleet uninstall, then NAS teardown, with what stays (the customer's media and indexes) stated explicitly.
  - Add a `server/decommission.py --dry-run` that mirrors install.
  - Consider a dashboard "uninstall from every computer" command on the report reply.
  - Have counsel align EULA §12 with what the vendor will actually support at exit.
- **Known:** not in KNOWN_BUGS.

### com-customer-experience-10 - `net share` / `net use` output is decoded as UTF-8, but net.exe writes in the OEM codepage, so non-ASCII local roots will mis-resolve
- **Severity:** medium
- **Confidence:** PLAUSIBLE
- **Where:**
  - `companion/src/ccsync_companion/paths.py:134-152` (`_local_share_target`)
  - `companion/src/ccsync_companion/paths.py:155-178` (`_delooped`)
  - `companion/src/ccsync_companion/drive_swap.py:102-115,309-340`
- **What:** Both calls run `net` with `encoding="utf-8", errors="replace"`. net.exe emits OEM-codepage bytes: cp850 on this very rig (`GetOEMCP()` = 850), and cp950 or cp936 on Chinese Windows. The label parsing is already locale-proof. The path value is not: a local root such as `D:\Vidéos\CCSync` or `D:\專案\CCSync`, or a `tree_name` with CJK in the default `C:\<tree_name>`, decodes to U+FFFD characters. `_delooped` then returns a path that matches no root, and `current_p_target` returns a UNC that never equals the server's.

  I could not create an SMB share to observe the bytes (it is a system change), which is why this is PLAUSIBLE. The codepage mismatch itself is certain.
- **Scenario:** A Taiwanese or European editor puts their sync root under a folder with a non-ASCII name. Relinked `P:\` clips read as BAD_PREFIX, or the drive classifies as "other". The result is toasts saying nothing will sync, on exactly the market the vendor is in.
- **Recommendation:** Decode with `locale.getpreferredencoding()` or the OEM codepage (`ctypes.windll.kernel32.GetOEMCP()`), or better, call `NetShareGetInfo`/`WNetGetConnectionW` through ctypes, which return UTF-16. Add a table test with a cp950-encoded `net share` output. Separately, record a decision on English-only UI: there is no i18n framework, and copy is hard-coded across five UIs.
- **Known:** CR-90 covers NFC/NFD path comparison, not this.

### com-customer-experience-11 - Customers are sold "0.x" software with four unrelated version streams and no customer changelog
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:**
  - `companion/src/ccsync_companion/config.py:156` (0.9.85)
  - `dashboard/src/ccsync_dashboard/__init__.py:31` (0.7.73)
  - `onboarding/steps.py:148` (1.0.46)
  - `tools/sign_release.py:443` (notes capped at 300 characters)
  - memory rule "companion stays below 1.0"
- **What:** Paying customers see pre-1.0 numbers, which read as beta to a buyer. The companion, dashboard, installer and EULA numbers are independent, and nothing ties them to one product release. Release notes are a single line of at most 300 characters on the package record. There is no customer-readable changelog or compatibility matrix (for example "dashboard X needs companion ≥ Y", which CLAUDE.md says matters: "deploy the dashboard first").
- **Scenario:** A customer's admin cannot tell whether "0.7.73 + 0.9.85" is a supported pair, or what changed in the update they are about to push to the fleet.
- **Recommendation:** Owner decision on a customer-facing release identity (for example "CC Sync 2026.10") that maps to component versions. Publish a changelog with a compatibility table per release. Revisit the "never 1.0" rule for the commercial launch.
- **Known:** not in KNOWN_BUGS.

### com-customer-experience-12 - The root LICENSE is still the 2026-08-17 draft and contradicts the final EULA
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:**
  - `LICENSE:1-14`
  - `docs/legal/EULA.md:16`
  - `docs/legal/PRIVACY.md` (cites `docs/SERVER-SYNOLOGY.md`, `docs/CLIENT_FOLDERS.md` and source files the customer never receives)
- **What:** LICENSE still opens "DRAFT FOR COUNSEL ... NOT YET EXECUTABLE" with `TODO(legal): replace "Cablewrap Creative" with the registered legal entity`. Meanwhile EULA 1.1 is the final text naming Cablewrap Creative Ltd., its tax ID and its address. The privacy and telemetry documents justify claims by citing repo paths and unshipped docs, which a customer cannot check.
- **Scenario:** A reviewer reads the repo or a product-repo export and finds a licence that calls itself non-executable and names a different entity from the EULA.
- **Recommendation:** Have counsel finalise LICENSE with the same entity block as the EULA. In the shipped legal docs, replace repo citations with plain descriptions, or with references to documents that ship.
- **Known:** COMMERCIAL_READINESS item 3 (the entity name was flagged; LICENSE was never updated after EULA 1.1).

### com-customer-experience-13 - No accessibility statement; the companion's Tk dialogs are invisible to screen readers
- **Severity:** low
- **Confidence:** PLAUSIBLE
- **Where:**
  - `companion/src/ccsync_companion/popup.py`, `settings_window.py`, `theme.py:377-381` (Tk)
  - `dashboard/static/cc/*.css` (ten rules at 9-10px, many at 11px)
  - `docs/COMMERCIAL_READINESS.md` item 13 ("near-zero accessibility ... untouched")
- **What:** The dashboard has reasonable ARIA (408 attributes, `lang="en"`, focus styles), and its text contrast passes: muted 5.45:1, red 5.53:1 on #070403. The companion UI, however, is Tkinter, which exposes no UI Automation or NSAccessibility tree, so its relink popup, licence dialog and settings window cannot be read by Narrator or VoiceOver. The dashboard is dark-only, has no `prefers-reduced-motion` handling on most sheets, and uses 9-11px type widely. There is no accessibility statement or VPAT.
- **Scenario:** A public-sector or large-company buyer asks for a VPAT or WCAG conformance statement during procurement. An editor using a screen reader cannot accept the licence dialog, so their machine never syncs.
- **Recommendation:** Write an honest accessibility statement listing the known gaps. Give every Tk modal a dashboard-page equivalent that it is reachable through (the licence acceptance especially). Set a minimum type size. Produce a VPAT only when a buyer asks.
- **Known:** COMMERCIAL_READINESS item 13 (recorded as untouched; no ledger id).
