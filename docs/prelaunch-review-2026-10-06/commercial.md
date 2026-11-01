# Pre-launch review 2026-10-06: commercial launch pass

This review covers the working tree at HEAD `08b40eb` (dashboard 0.7.73, companion 0.9.85) plus the uncommitted changes: alerts selection, the companion fixes for CR-356/357/358, and `docs/ZERO_DOWNTIME_DEPLOY.md`. The owner is about to sell CC Sync to other organisations. He asked for "every single thing that should be looked at or changed before going live commercially". This document is the commercial-launch pass of that review. It judges the product as something a small vendor with liability sells to other organisations, from the point of view of a buyer, a lawyer, a security reviewer, a support desk and a finance person. The starting point was `docs/COMMERCIAL_READINESS.md` (2026-08-17): what is really done in code and what is only claimed.

**How the pass ran.** Twelve Opus hunters ran at once, each on one lens:

| Hunter | Lens |
|---|---|
| `com-legal` | EULA, privacy, telemetry, IP, forum |
| `com-oss` | open-source licence compliance |
| `com-thirdparty-tos` | Anthropic, YouTube, Tailscale, Cloudflare, Blackmagic, TrueNAS |
| `com-security` | buyer security review |
| `com-tenancy` | first-studio identity baked into the product |
| `com-release` | signing, feed, image, keys |
| `com-licensing-billing` | entitlement and commercial paperwork |
| `com-product-surface` | what v1 is |
| `com-customer-experience` | support, install, uninstall, brand |
| `com-ops-at-scale` | the vendor operating N customers |
| `com-privacy-telemetry` | |
| `com-quality-gates` | |

Each hunter checked KNOWN_BUGS and earlier hunts first. Every critical and high was then given to one adversarial verifier who was told to refute it. Everything was read-only. The only probes were scratch scripts against repo code: no NAS, no live dashboard, no GitHub, no Resolve. Raw reports are in `docs/prelaunch-review-2026-10-06/commercial/hunters/`, and the merged, deduplicated list is in `commercial/results.json`.

**Tally: 159 raw findings (3 critical, 65 high, 69 medium, 22 low).** The hunters lenses overlapped heavily: the unsigned binaries, the IP chain of title and the stale customer channel were each reported by three to seven hunters. After merging duplicates there are **96 distinct items: 0 stop-ship, 15 high, 70 medium, 11 low.**

| Hunter | Raw | Critical | High | Medium | Low |
|---|---|---|---|---|---|
| com-legal | 18 | 0 | 8 | 10 | 0 |
| com-oss | 10 | 0 | 4 | 3 | 3 |
| com-thirdparty-tos | 15 | 1 | 3 | 8 | 3 |
| com-security | 14 | 0 | 6 | 6 | 2 |
| com-tenancy | 11 | 0 | 3 | 5 | 3 |
| com-release | 13 | 1 | 6 | 4 | 2 |
| com-licensing-billing | 10 | 0 | 5 | 4 | 1 |
| com-product-surface | 12 | 0 | 8 | 3 | 1 |
| com-customer-experience | 13 | 0 | 3 | 7 | 3 |
| com-ops-at-scale | 15 | 0 | 8 | 6 | 1 |
| com-privacy-telemetry | 12 | 0 | 4 | 5 | 3 |
| com-quality-gates | 16 | 1 | 7 | 8 | 0 |
| **Total** | **159** | **3** | **65** | **69** | **22** |

**Verifier outcome on the 68 critical and high findings: 23 CONFIRMED as rated, 45 DOWNGRADED, 0 refuted.** Of the 45 downgrades:
- All three criticals became high: the Claude Code subscription relay, unsigned binaries, and the stale customer channel.
- 40 highs became medium.
- 2 highs became low: the triage agent having "no compliant mode" (Console sign-in exists), and tenant names in shipped comments.

Most downgrades had one of three causes:
- the feature is off in the vendor build;
- the gap is paperwork the owner or counsel can produce for each deal;
- the item had already been decided and documented, for example the REL-4/REL-16 overlap or D12.

Mediums and lows were not verified. After merging, the post-verification severities are 0 critical, 26 high, 109 medium and 24 low, collapsing to the 96 items below.

**Bottom line.** No verified stop-ship remains. Nothing found loses data or opens a breach on its own today, and no paying customer runs the vendor channel yet. But fifteen items must be closed before the first paying customer, and they cluster in three areas:
- **Distribution.** The customer channel is a month stale with a draft EULA. The appliance cannot get updates. INSTALL.md cuts the customer off from the vendor feed. Every binary is unsigned, and the CI path cannot produce a signed one.
- **Trust.** One plaintext release key sits on the agent-running rig. A NAS root credential is in the container by default. The image ships on a tag push with no tests. The shared fleet token is on by default.
- **Business paperwork and continuity.** There is no order form, support plan or support channel, and the vendor has a bus factor of one.

Several of the fixes need decisions or purchases from the owner, not code. Each item says who has to produce what.

## 1. Stop-ship

None after verification. The three criticals were all verified as real and downgraded to high:
- `com-thirdparty-tos-1`: the feature is off by default, it is disclosed, and a compliant route exists.
- `com-release-1`: most customers can click through the OS warning, and only managed fleets are hard-blocked.
- `com-quality-gates-1`: it is a release-state gap, and there is no customer on the feed yet.

They are H1, H6 and H8 below.

## 2. Before the first paying customer (high)

### COM-H1 - The Claude Code / Codex subscription path relays claude.ai sign-in and stores the OAuth token, which Anthropic's policy forbids third-party developers to do; the customer notice understates what it carries
- Sources: com-thirdparty-tos-1 (critical, downgraded to high), com-legal-13, com-privacy-telemetry-3, com-product-surface-5, com-thirdparty-tos-2 (downgraded to low)
- Where: `dashboard/src/ccsync_dashboard/cli_tools.py:71-86,280-285,434-446,499-501,1729-1745,2346-2361`; `ai_providers.py:85,148-152`; `cards_ai.py:17,530-550`; `triage.py:30-35,191-227`; `triage_mail.py:366`; `docs/legal/YOUTUBE_FEATURE_NOTICE.md`
- What:
  - The SET UP wizard drives `claude auth login` through a pty and relays the sign-in code.
  - Its `setup-token` fallback captures the long-lived OAuth token into `<data>/secrets/ai/` and passes it back as `CLAUDE_CODE_OAUTH_TOKEN`.
  - `cli_env` strips `ANTHROPIC_API_KEY` so the subscription pays.
  - `claude_code` is first in `PROVIDER_ORDER`, so one admin's personal subscription serves every editor's YouTube searches, Cards transcripts and edit chat, and the triage agent. Triage runs on the CLI only.
  - The notice the admin accepts names only "every YouTube search" and frames the risk as a terms-of-service matter. It does not mention Cards or triage, consumer data terms (no DPA, possible training) or the `ai_cli_auto_update` fetches.
  - Codex signed in with ChatGPT has the same problem.
  - COMMERCIAL_READINESS item 1 is stale: it says "we cannot and do not script an interactive OAuth", and the code now does.
- Verifier: the mechanism is real. It is not stop-ship because the path is off by default (`ai_cli_providers`), the admin is warned on enabling it, and the wizard's Console (API billing) sign-in and the `anthropic_api` provider are compliant routes. Triage itself can run compliantly on a Console sign-in, so "no compliant mode" (tos-2) is wrong. That part is only a copy fix.
- Scenario: a customer enables the path as the page invites. Anthropic suspends the account, and Cards, YouTube and triage go dark. The vendor shipped the claude.ai relay, so the exposure is the vendor's, and the studio's own dashboard runs this path live.
- Recommendation:
  - Engineering: remove the claude.ai login relay, the setup-token capture and the stored token from the commercial build, keeping Console login or an API key only. Let triage pass a capped `ANTHROPIC_API_KEY` to unmodified Claude Code. Treat Codex/ChatGPT the same way. Rewrite the notice per tool, naming Cards, triage, consumer data terms and auto-update. Correct COMMERCIAL_READINESS item 1.
  - Owner: accept Anthropic's Commercial Terms, get written confirmation from Anthropic sales if any CLI path stays, and turn the flag off on the studio dashboard.
- Known: no open ledger id. CR-1 and CR-2 are fixed, the path was reintroduced on 2026-08-18, and LG-9 (notice wording) is deferred.

### COM-H2 - Every TrueNAS integration uses REST API v2.0, which TrueNAS 26 removes
- Sources: com-thirdparty-tos-3 (CONFIRMED). The resilience pass reported the same thing as `res-deps-3`.
- Where: `server/common.py:4,1339`; `server/install_dashboard_app.py:143-155`; `server/install_syncthing_app.py`; `server/setup_editor_account.py`; `server/create_api_key.py:140`; `server/backends/truenas.py`; `dashboard/src/ccsync_dashboard/nas/truenas.py:10,100,113`
- What: there is no JSON-RPC (`/api/current`) client anywhere and no NAS version check. REST was deprecated in 25.04, raises a daily alert from 25.10.1, and is gone in TrueNAS 26 (now in beta). Editor login (SMB) and the sync lanes keep working on 26. These break: first install, editor provisioning, password reset and deletion, API-key creation, snapshot tasks and the dashboard's NAS-admin actions. The snapshot safety net fails with only a stderr warning.
- Scenario: a new customer on TrueNAS 26 cannot install. An existing customer who upgrades their NAS silently loses provisioning.
- Recommendation:
  - Engineering, before launch: a version gate that refuses with a named reason.
  - Engineering, promptly after: port to the JSON-RPC 2.0 WebSocket API (`auth.login_ex` with `API_KEY_PLAIN`).
  - Sales/owner: state supported TrueNAS versions in the order form and support matrix, plus a "do not upgrade to 26 yet" notice to customers.
- Known: none.

### COM-H3 - psycopg2 (LGPL-3.0+) is frozen into the one-file companion: the LGPL-3.0 text is missing and the "replaceable" premise counsel cleared is untrue
- Sources: com-oss-3 (CONFIRMED)
- Where: `companion/build.spec:24-39,255-303` (one-file EXE, no COLLECT); `tools/license_allowlist.toml [allow.psycopg2-binary]`; `docs/legal/licenses/companion/THIRD_PARTY_LICENSES.txt`; `docs/legal/THIRD_PARTY_NOTICES.md` ~628-641
- What:
  - psycopg2, libpq and OpenSSL are unpacked to a fresh `_MEI` temp directory on every launch, so a user cannot replace them without rebuilding the exe.
  - The same build.spec removed pystray for exactly this reason ("precisely what LGPL §4 requires").
  - The allowlist and the notices call the files "separate, replaceable", which is the premise counsel cleared (LEGAL_GAP D6).
  - The LGPL-3.0 licence text is not in the bundle. The verifier corrected two hunter claims: the GPL-3.0 text is present, and the reverse-engineering clause is EULA §3(b), which already carves out third-party components (§11).
- Scenario: a customer asks for the means to relink psycopg2 under LGPL §4. The vendor cannot provide either a replaceable library or the Minimal Corresponding Source.
- Recommendation:
  - Engineering, now: add the LGPL-3.0 text to `tools/notices_extra` and regenerate.
  - Engineering, then one of: load psycopg2 from a user-replaceable override directory first; ship it outside the exe; or offer the §4(d)(0) application archive plus a build recipe. Also inspect the macOS `psycopg2/.dylibs`.
  - Counsel: re-review with the one-file fact.
- Known: LEGAL_GAP D6 (cleared on an incorrect premise).

### COM-H4 - One plaintext Ed25519 release key, on the studio's everyday agent-running workstation, signs code every customer runs, with no compromise or revocation plan
- Sources: com-security-1, com-release-7, com-ops-at-scale-7 (all CONFIRMED)
- Where: `tools/release_key.py:1-27,95-106,225-245`; `%USERPROFILE%\.ccsync-release\release.key`; `companion/src/ccsync_companion/release_pubkey.py:40-42`; `dashboard/src/ccsync_dashboard/dashboard_update.py`; `release_feed.py:1002,1089-1098`; `docs/RELEASE.md` (rotation only); `docs/RELEASE_PATHWAYS.md` ("Claude included")
- What:
  - The seed is base64 with no passphrase, by design.
  - It signs the companion, onboarding and dashboard OTA bundles for the vendor feed.
  - Exactly one public key is baked in. There is no offline recovery key, no revocation and no compromise runbook. Rotation only works through a build signed by the old key, so a thief can rotate too.
  - The rig edits footage, runs indexers and runs autonomous Claude Code sessions as the same user.
  - A backup exists (`backup.json`, 2026-09-26, to Q:).
  - `release_pubkey.py` itself says to move the key to a hardware token before the first customer ship.
- Scenario: a malicious dependency or a prompt-injected agent copies the file. Combined with the gh login on the same rig, the attacker signs a build that every policy=current site stages or auto-applies, and that build drops the vendor key. Recovery means reinstalling every machine at every customer.
- Recommendation:
  - Owner: buy a hardware token, HSM or cloud KMS, or set up a dedicated offline signer that runs no agents. Escrow the seed twice. Record a key ceremony.
  - Engineering: generate a new key there and retire the 2026-08-17 key in an overlap release. Bake a second, cold recovery public key. Consider a root key plus a revocable signing subkey. Write a key-compromise runbook.
  - Decide this together with the Authenticode custody question (COM-H7).
- Known: CR-6 (keep/rotate undecided), COMMERCIAL_READINESS item 4.

### COM-H5 - The container holds a NAS root-equivalent credential by default, and the dashboard admin is by default the NAS admin
- Sources: com-security-6 (CONFIRMED)
- Where: `server/install_dashboard_app.py:2627-2648,5269,5306-5335`; `docs/INSTALL.md:32-34`; `dashboard/src/ccsync_dashboard/ai_providers.py:611,1176-1205`
- What:
  - `compose_nas_pw = "" if nas_api_key else truenas_pw`: unless the operator mints a scoped key, the NAS admin password goes into the container env. The only guard is a stderr NOTE.
  - `TRUENAS_VERIFY_SSL` defaults to 0.
  - DSM has no API-key option, and the install requires 2FA off on the DSM admin.
  - `DASH_ADMIN_USERS` defaults to the NAS admin, who signs in to the dashboard with the NAS admin password over the LAN's plain HTTP.
  - The admin-settable CLI path is exec'd. That path is weaker than the hunter claimed, since it requires an existing file, but the escalation does not depend on it.
  - COMMERCIAL_READINESS item 6 is marked DONE, but only the option was added; it was never made mandatory.
- Scenario: a phished or sniffed admin login, or any remote code execution in the dashboard, b-roll, music or ytdl code, yields the NAS root-equivalent credential, and with it the customer's whole NAS.
- Recommendation:
  - Engineering: make `TRUENAS_API_KEY` mandatory on TrueNAS and use the password only for deploy-time SSH. Separate the dashboard admin from the NAS admin. Pin the NAS certificate fingerprint at install. Restrict CLI paths to `<data>/tools` and audit changes.
  - Engineering, DSM: use a non-admin service account where possible, and document the residual risk.
  - Docs: state that dashboard admin is a NAS-privileged role.
- Known: COMMERCIAL_READINESS item 6 / CR-9 (optional, never made mandatory).

### COM-H6 - Every binary a customer installs is unsigned at the OS level; the installer page teaches users to click "Run anyway"
- Sources: com-release-1 (critical, downgraded to high), com-product-surface-9, com-customer-experience-3, com-quality-gates-6 (CONFIRMED); com-thirdparty-tos-11, com-ops-at-scale-15 (medium); com-licensing-billing-10 (low)
- Where: `feed/channel.json` (12 of 12 records have `signed_binary: false`); `dashboard/templates/installer.html:37`; `installer/START_HERE.md:20-22`; `companion/build.spec:257-303` (no VSVersionInfo, `codesign_identity` None); `onboarding/build_onboard_macos.spec:249`; `.github/workflows/release-macos.yml:201`; `tools/release_macos.sh:594-651`
- What:
  - No Authenticode signature on Windows, and no Developer ID or notarisation on macOS (ad-hoc only).
  - Every ship uses `-AllowUnsignedBinary`.
  - The exes have no version resource (CompanyName, ProductName, LegalCopyright), so they show as "Unknown publisher".
  - The Ed25519 record signing protects only the update channel.
  - Ad-hoc Mac bundles lose their TCC / Full Disk Access grant on every self-update. The repo documents this, but the verifier did not reproduce it.
- Verifier: high, not critical. SmartScreen and Gatekeeper can be clicked through on unmanaged machines. Smart App Control, WDAC/AppLocker, EDR allow-listing and MDM fleets are hard-blocked.
- Scenario: a managed customer cannot run `onboard.exe` at all. Elsewhere, editors are taught on day one to override a malware warning.
- Recommendation:
  - Owner (the legal entity): settle the entity and get a D-U-N-S number. Buy an OV/EV Authenticode certificate, preferably cloud-HSM or Azure Trusted Signing. Enrol in the Apple Developer Program for a Developer ID plus notarytool credentials. Start now: lead time is weeks.
  - Engineering: add a VSVersionInfo built from `config.VERSION` with the legal entity to both specs. Remove the "Run anyway" text the day a signed build ships. Requires COM-H7.
- Known: CR-6 (OPEN), COMMERCIAL_READINESS item 4, KNOWN_BUGS macOS code-signing backlog (item 16).

### COM-H7 - Even with certificates, the customer pathway (CI plus publish_latest plus feed) cannot produce a signed build
- Sources: com-release-2 (CONFIRMED)
- Where: `tools/publish_latest.py` (no unsigned refusal); `tools/publish_feed.py:1001-1002` (copies CI's `signed_binary` claim); `.github/workflows/release-windows.yml:72,199-220` (PFX only); `release-macos.yml:146-150,201`; `tools/release_macos.sh:611-615`; `docs/RELEASE.md:1299-1324`
- What:
  - The unsigned-binary gate exists only in `ship.ps1` (pathway A, this studio only).
  - Windows CI signs only from a PFX. No OV/EV key can be exported to a PFX since June 2023, and no cloud-signing route is implemented.
  - macOS CI never imports a certificate into a keychain or gets notary credentials. Setting `CCSYNC_APPLE_DEV_ID` would make `codesign` abort the build.
  - The wizard manifest hard-codes `signed_binary:false`.
  - The recommended "re-sign on the rig" step does not exist.
- Scenario: the owner buys both certificates and sets the variables as RELEASE.md says. Feed releases still ship unsigned on Windows, and macOS builds fail.
- Recommendation:
  - Engineering: decide where signing happens (an approval-gated CI environment with cloud HSM and OIDC, or a re-sign step on the rig in `publish_latest`). Implement it for all four artefacts, including keychain import, notarytool API-key credentials and stapling. Add an unsigned refusal with an override to `publish_latest --make-current`. Have the rig verify signatures itself rather than trust CI's claim.
- Known: release-pipeline-11 (unreconciled decision).

### COM-H8 - The customer channel is a month stale: feed dashboard 0.7.44, image `:1` at v0.7.44, a draft EULA served to the first admin, companion newer than its dashboard
- Sources: com-release-3, com-ops-at-scale-3 (CONFIRMED); com-quality-gates-1 (critical, downgraded to high)
- Where: local `feed/channel.json` (generated 2026-09-26: dashboard/linux current 0.7.44, `dashboard_image` tag 0.7.24, companion 0.9.82); git tags (newest v0.7.44); `.github/workflows/image.yml` (`:1` moves only on a `v*` tag); `dashboard/deploy/compose.appliance.yaml:88,147,291`; `dashboard/src/ccsync_dashboard/__init__.py:31` (0.7.73); `companion/src/ccsync_companion/config.py:174`; `tools/publish_latest.py:506-534`; `docs/RELEASE_PATHWAYS.md:81-83`
- What:
  - Customer server code ships through three manual acts that `publish_latest` does not run: the dashboard bundle plus its feed record, a `v*` tag that moves `:1`, and the channel's `dashboard_image`.
  - The studio deploys by digest and snapshot and bypasses all three, so the customer path is not dogfooded.
  - Customers are missing CR-282..CR-361, the 09-18 and 09-24 security fixes, LG-1 site-side stripping, LG-4, the account page and EULA 1.1.
  - At v0.7.44 the EULA opens "DRAFT FOR COUNSEL - NOT LEGAL ADVICE, NOT YET EXECUTABLE", and the setup wizard serves it at `GET /setup/eula`.
  - `requires_dashboard` is not signed in (see COM-M51), so nothing enforces "dashboard first".
  - Evidence is the gitignored local feed copy plus the tag list. The live feed was not queried.
- Scenario: a launch-day customer installs the appliance. Their admin accepts a draft-marked EULA 1.0 while editors accept 1.1. The dashboard cannot honour the privacy switches. Every machine banners "REPORT SECTION(S) IGNORED".
- Recommendation:
  - Engineering: make a customer release one gated event. Pick a release-candidate commit, tag `v*`, publish the dashboard bundle first, then the companion and both installers from the same commit, and move `current` together. Verify with a fresh appliance install. Provide one "release to customers" command that does bundle, tag and `dashboard_image` from the same green run. Add a CI check that fails when the feed's dashboard trails main by N versions. Move the studio onto the customer channel.
  - Owner: decide the `:1` tag policy.
- Known: CR-66 release-pipeline-9 (mutable `:1`). The feed lag itself is not recorded anywhere.

### COM-H9 - A new appliance customer has no vendor public key and no feed URL: no installer, no companion, no OTA, no recalls
- Sources: com-release-4, com-ops-at-scale-1 (CONFIRMED)
- Where: `dashboard/deploy/compose.appliance.yaml:35-42,160-174`; `dashboard/src/ccsync_dashboard/settings.py:429,438,910-916`; `setup_engine.py:1476-1545`; `app.py:866`; `api.py:6941`; `release_trust.py:146`
- What:
  - Both values come only from the environment. Neither the image nor the appliance compose sets them.
  - The compose claims `DASH_RELEASE_PUBKEYS` is "generated on first boot". That is false and impossible, because it must be the vendor's key.
  - With the URL empty, the feed thread never starts. With no keys, every publish returns 503 and every record fails verification.
  - Both wizard tasks are optional, and they tell the customer to set "your release key" while citing internal docs.
- Scenario: a customer follows APPLIANCE_INSTALL.md, finishes the wizard, and cannot install a single editor without emailing the vendor and editing a file marked do-not-edit.
- Recommendation:
  - Engineering: bake the vendor feed URL and public key(s) into the image as defaults, with the environment as an override. Fix the compose comment and the wizard copy ("the vendor's signing key"). Add a test that the appliance boots with a configured feed.
  - Owner: have a non-author run APPLIANCE_INSTALL end to end (see COM-H14).
- Known: APPLIANCE_INSTALL "NOT YET TRUE" covers it in part. Not recorded as a defect.

### COM-H10 - The dashboard image and OTA bundle publish with no test gate, through tag-pinned third-party actions, with a cosign check that accepts any identity
- Sources: com-release-6, com-quality-gates-3 (CONFIRMED); com-security-2 (downgraded to medium)
- Where: `.github/workflows/image.yml:61-64,149-170,256-258` (no `needs:`, no tests, no `environment:`, never runs the container); `docs/DOCKER.md:562` (`--certificate-identity-regexp '.*'`); all 29 `uses:` are tag-pinned; `tools/build_dashboard_bundle.py:279-294` (no `tests_run`); `tools/publish_feed.py:965-975`; `.github/workflows/release-dashboard.yml` (no tests); `ci.yml` (no schedule); `tools/ship.ps1` (dashboard deploys in step 1, before its suite in step 2a); `docs/MODULAR_UPDATES.md` s1 / A.7
- What:
  - Any `v*` tag push builds and pushes `:VERSION` and `:1` for the dashboard and sftp images, signed only by the workflow's own OIDC, with no tests, no human approval and no boot smoke test.
  - Bundles always pass `publish_feed`'s test check.
  - 0.7.71-0.7.73 were live while the Linux CI job was red. M0 made main green again, but the gate is still missing.
  - `publish_latest` signs whatever CI produced, with no provenance attestation. There is no CVE scanning of the locks, and no SBOM for the client binaries (the image does get one).
  - The boot watchdog only reverts an OTA bundle that crashes on boot.
- Scenario: a stolen GitHub token, a repointed action tag, or a stray tag push moves `:1`. Every appliance site runs it with full dashboard privileges on its next update, and the offline key is never involved. Alternatively, a dashboard logic regression is taken unattended by every policy=current site.
- Recommendation:
  - Engineering: make tag builds depend on green CI plus a required-reviewer environment. Pin every action to a commit SHA. Add a `docker run` plus health and headless `/setup` smoke test. Have bundle and feed publish refuse a commit without a full-green CI run on main (A.7), and add the nightly schedule. Reorder `ship.ps1` so no deploy precedes its suite. Fix the cosign identity to the exact workflow ref. Publish image digests in the signed channel and have customers pin by digest. Add `attest-build-provenance` and verify it before signing. Add weekly pip-audit/osv-scanner and Dependabot. Produce a CycloneDX SBOM for the companion and wizard.
- Known: CR-66 release-pipeline-2 (deferred). Nothing else recorded.

### COM-H11 - The documented customer install makes the customer mint and bake their own release key, which cuts them off from the vendor feed; no tested vendor-build install exists
- Sources: com-ops-at-scale-2, com-product-surface-7 (CONFIRMED)
- Where: `docs/INSTALL.md:46-60,89-93,210-236`; `site.example.toml:244-261`; `dashboard/src/ccsync_dashboard/release_trust.py:18`; `setup_engine._check_release_key` (~1539); `docs/APPLIANCE_INSTALL.md:1-17`; `docs/PRODUCT_REPO.md`; `docs/ZERO_TOUCH_PLAN.md:284` (WP E)
- What:
  - INSTALL.md is the "generic" guide, and it requires a Windows rig, git, PyInstaller, a Mac and a `git clone` of the private engineering repo. The product repo has never been cut.
  - Step 6 runs `release_key.py new/pubkey/bake` and sets `DASH_RELEASE_PUBKEYS` to the customer's own key. Every vendor feed record is then rejected, and vendor-built companions refuse the customer's own signatures.
  - INSTALL.md never mentions the vendor feed.
  - WP E ("retire customer-side key generation") was not done.
  - The appliance alternative is a DRAFT never run by a non-author.
- Scenario: customer 2 follows INSTALL.md and ends up on a self-signed fork. Taking vendor fixes means rebuilding at their site or reinstalling every editor.
- Recommendation:
  - Owner: decide that v1 means vendor builds through the vendor feed, with the customer running a container.
  - Engineering/docs: rewrite Step 6 as "pin the vendor key", with the key and its id published. Move key generation into vendor-only RELEASE.md. Use the same text in APPLIANCE_INSTALL and the wizard. Move self-build to a partner appendix or delete it. Cut the product repo.
- Known: COMMERCIAL_READINESS items 10 and 16; ZERO_TOUCH WP E owed.

### COM-H12 - The EULA defers scope, fees, support and updates to an "order" and "support plan" that do not exist; no support channel anywhere in the product
- Sources: com-licensing-billing-5, com-customer-experience-1 (CONFIRMED); com-legal-9 (downgraded to medium); com-ops-at-scale-8 (support half)
- Where: `docs/legal/EULA.md` §1-2 (40-43), §8 (130), §10 (159), §13 (192); `docs/legal/PRIVACY.md:103-113` (DPA "on request"); `dashboard/src/ccsync_dashboard/notices.py:1456,1490,1585`; `app.py:469`; `dashboard/templates/partials/health_diagnostics.html:15`; `computer_answer.html:14`
- What:
  - EULA 1.1 is final and cleared. It ties the licence to "the number of workstations and servers covered by your order", and support and updates to "your order or support plan". It says EULA plus order is "the entire agreement".
  - `docs/legal/` has no order form, quote template, price list, support policy, SLA or DPA template.
  - The product tells admins to "send to support" in several places, but no setting, page or manifest key holds a support address. The only contact is `contact@thecreatorsclub.co` at the foot of the legal docs, which also serves privacy, security and sales.
  - No status page or public changelog exists.
  - legal-9's verifier noted that a breach clause exists (§12, 30 days) and that indemnity, confidentiality and audit terms are negotiable. The liability cap is unanchored, not void.
- Scenario: the first buyer's procurement asks for a quote, a per-seat price, payment and renewal terms, a support SLA and a signed DPA, and the vendor has none. During an outage the admin reads "send to support" with no idea who that is.
- Recommendation:
  - Owner with counsel: a price list and unit (suggested: per editing computer plus a per-site base). An order form template (licence id, seats, term, updates-until, features, fees, payment, renewal, refunds). Subscription and support terms (hours, channel, response targets, what updates include, security-fix policy). The Art. 28 DPA (see COM-M4). A separate support address.
  - Accountant: Taiwan uniform invoice (統一發票) for domestic sales, cross-border VAT and withholding, and currency.
  - Engineering: a vendor-level `support_url`/`support_email`, with an optional reseller override, shown on /help, in the topbar, beside every "send to support" line and in the companion help rows.
- Known: LG-19 (deferred).

### COM-H13 - Bus factor of one: signing, feed, image, secrets and the vendor's GitHub org sit with one person on one rig, under a studio-named org, with no continuity plan
- Sources: com-ops-at-scale-8 (CONFIRMED); com-release-9, com-ops-at-scale-10 (medium); com-product-surface-10 (downgraded to medium)
- Where: `tools/ship.ps1` (interactive password); `tools/load_secrets.ps1` and `docs/SECRETS.md` ~87 (DPAPI, "does not help a second operator"); `tools/publish_latest.py:46` (gh login on this rig); `.github/workflows/release-dashboard.yml` (rig-only two-step); `dashboard/deploy/compose.appliance.yaml:88,147,291`; `server/install_dashboard_app.py:1428`; `docs/BACKUP_RESTORE.md:74-75`; `tools/gen_notices.py:523`
- What:
  - Every release and incident action needs the release key, the gh login to The-Creators-Club org (feed, GHCR and CI), the DPAPI secrets and the interactive password, all on one Windows account.
  - The owner is non-technical, and engineering is done by AI sessions.
  - There is no named second operator, no "vendor unavailable" or rig-rebuild runbook, no escrow, no SECURITY.md and no supported-versions or critical-fix SLA.
  - The org and registry belong to the studio brand while the licensor is Cablewrap Creative Ltd. The image path and feed URL are baked into every customer's compose, so a later move breaks every site's updates.
  - The key backup exists, which mitigates a dead disk (product-10's verifier).
- Scenario: the rig dies or Alex is away during a customer data-loss incident. Nobody can sign a fix, move the channel or reach the customer. Or the org is suspended, and every customer's update path dies with nothing left to tell them.
- Recommendation:
  - Owner with counsel: a named second operator with a tested route to the key backup and org access. Escrow terms for larger customers. Transfer the GitHub org, GHCR packages and releases repo to the contracting entity, with two owners. Put the feed behind a vendor-owned, redirectable domain and a vendor-owned registry namespace, and bake those into the defaults before customer 1.
  - Engineering: a rig rebuild drill from the docs on a clean box. A vendor continuity document.
- Known: OPS-8 (backup advice only), CR-6.

### COM-H14 - No new-customer install has ever been run end to end, and there is no staging site: the studio's production fleet is the only integration test
- Sources: com-quality-gates-7 (CONFIRMED); com-ops-at-scale-13 (medium)
- Where: `docs/APPLIANCE_INSTALL.md:1-17` (DRAFT; WP B Serve "NOT YET TRUE"; the wizard checks but does not act); KNOWN_BUGS WPK-3 (update and rollback never run under docker or on a NAS); `docs/CI.md` "What CI cannot cover"; `dashboard/tests/test_smoke_boot.py` (TestClient only)
- What: nothing takes a clean NAS through compose, image, wizard, Windows and Mac onboarding, first sync, first OTA and first rollback. CI never starts the container or its sidecars. The studio dashboard does run the CI image, so the image itself boots. The fresh-install path does not have that evidence.
- Scenario: the first customer is also the first appliance install, on an untried NAS or DSM/SCALE version. Wizard, bind-mount ownership, Serve or first lane B pass failures all happen at the customer.
- Recommendation:
  - Owner: buy or reserve vendor-owned TrueNAS SCALE and DSM boxes or VMs plus Windows and Mac editor VMs.
  - Engineering: a scripted install-acceptance run for each release candidate (fresh install, upgrade from the oldest supported version, one editor per OS) before any `--make-current`. A CI job that runs `compose up` with the built image, checks health, completes `/setup` headless and sends a stub-companion report.
- Known: WPK-3 (OPEN), COMMERCIAL_READINESS item 16.

### COM-H15 - Open trust-model items and insecure defaults a new customer inherits: shared fleet token on with non-revocable identity tokens, no NAS host-key pinning on editor lanes, NAS TLS verify off, Postgres "DaVinci" on all interfaces
- Sources: com-quality-gates-13 (CONFIRMED); com-security-12 (medium)
- Where: `dashboard/src/ccsync_dashboard/settings.py:135,804-806` (`shared_report_token_enabled` default on); `auth.py` (identity tokens: 100-year TTL, no server row); `dashboard/src/ccsync_dashboard/nas/truenas.py:54-60` (verify False); `companion/src` and `installer` (no known_hosts); `docs/SERVER.md:228`; `docs/CONFIG.md:185` (`project_acl=shared`); `server/install_dashboard_app.py:5325`; `dashboard/deploy/compose.yaml:751-776` (optional Postgres profile, password DaVinci, published on all interfaces); KNOWN_BUGS CR-66 trust-model-1/4/6/8/9, data-model-8, release-pipeline-2/8/9, WPK-4, CR-86, CR-91/279, CR-333, CR-294, CR-299C, CR-280, CR-65, CR-137, CR-234, CR-70, R16, MAC-12, the Carryover backlog
- What:
  - Many CR-66 items were deferred on purpose and never re-decided for a commercial launch.
  - The core security trade: on a default site, a departed editor's machine keeps reporting with an identity token that cannot be revoked (CR-86's recorded trade).
  - Editor lanes trust any NAS host key, and NAS REST TLS is unverified.
  - `project_acl=shared` lets any editor delete any project.
  - There is no tailnet ACL template, although Tailscale is called the perimeter.
  - data-model-8: `canonical_prefix` and `tree_name` can be edited live but are install-time constants. The verifier rates this medium fragility, not an outage.
- Scenario: a buyer's security review lists each of these. A scan finds Postgres accepting postgres/DaVinci, and any tailnet device, such as an intern's laptop, reaches the admin dashboard.
- Recommendation:
  - Owner: record a decision per open id (fix, document as a limitation, or accept with a reason).
  - Engineering, minimum before the first sale: for new sites, turn the shared token off and add per-user revocation of identity tokens (a generation counter); pin NAS host keys on editor lanes; verify NAS TLS by default with a fingerprint option; make `canonical_prefix`/`tree_name` read-only once machines exist; use a per-project ACL; generate a random Postgres password bound to LAN and tailnet only; ship a `TAILNET_POLICY.md` grants template.
  - Engineering: run the proxy live-attach proof (the open SHIP-BLOCKER), or disable editor proxy generation in the vendor build.
  - Keep the studio's legacy values in its own `site.toml`.
- Known: all the ids listed; COMMERCIAL_READINESS items 6 and 7.

## 3. Soon after launch (medium)

Each item lists its sources, where it is, what is wrong, the scenario and the recommendation. "Verifier" marks an item that a verifier downgraded from high. Items without that note were rated medium by the hunter and not verified.

### Legal, contract and IP

**COM-M1 - TELEMETRY.md no longer matches the wire it certifies.** Sources: com-legal-1, com-privacy-telemetry-8.
- Where: `docs/legal/TELEMETRY.md:109-110,262,352-354`; `reporter.py:1072-1120`; `eula.py:263-287`; `api.py:9483-9527`.
- What:
  - It says no EULA record is sent, but an `eula` section (version, accepted_at, sha) is sent.
  - `eula`, `machine_settings`, `report_optouts` and `capabilities.jobs_gate` are missing from the field table.
  - The idle_seconds and jobs rows contradict the D4 build.
  - Point 6 says the categories "cannot currently be switched off", which contradicts the switches section above it.
  - "Still sent" omits `lanes[].last_error/detail` (rclone stderr with file paths).
- Scenario: a DPO compares a capture against the Art. 13 notice and finds false statements.
- Recommendation: fix the statements and add the rows. Make `test_telemetry_disclosure.py` require every pinned key to appear in the document. Send the changes to counsel with COM-M2.

**COM-M2 - The "cleared" legal documents were edited after clearance, with an open counsel list and no version bump.** Source: com-legal-2 (verifier: medium).
- Where: git `b9503c9..HEAD -- docs/legal`; LEGAL_GAP 8.7 and D12; ledger G9, G6 and FABLE_REVIEW; `PRIVACY.md:287`; `THIRD_PARTY_NOTICES.md:426-427,634`; CR-5.
- What:
  - About 135 lines of PRIVACY and TELEMETRY were changed after clearance and sent to counsel "as information" (owner decision D12).
  - Three lines are factually wrong: PRIVACY's objection paragraph, NOTICES saying rclone and Syncthing are "resolved at install time" (they are pinned), and psycopg2 "unmodified".
  - PRIVACY and TELEMETRY still say 1.0. CR-5 still reads "awaiting counsel". There is no record of which jurisdictions counsel covered.
  - Most of the errors over-disclose.
- Recommendation: counsel gives a dated written sign-off on the diff plus the 8.7/G9 list, naming jurisdictions. Bump to 1.1 with a change log. Fix the three lines. Update CR-5.

**COM-M3 - The root LICENSE is still a draft with a placeholder licensor; no IP assignment; the yt-credit-downloader grant is still owed.** Sources: com-legal-3, com-legal-6, com-oss-4, com-tenancy-8 (all verifier: medium), com-thirdparty-tos-8, com-licensing-billing-9, com-customer-experience-12 (low).
- Where: `LICENSE:1-22`; `ytdl/web/ytdlweb/vendor/PROVENANCE.md:3-7`; `tools/make_product_repo.ps1:202-206,311-336,666-668`; `dashboard/deploy/Dockerfile:70-73`; git authorship.
- What:
  - LICENSE says "DRAFT FOR COUNSEL ... NOT YET EXECUTABLE" and names "Cablewrap Creative" without "Ltd.", contradicting the cleared EULA. It is not shipped in builds.
  - No assignment exists from Alex (the individual author) to Cablewrap Creative Ltd. for ccsync, MulticamPipeline, the vendored downloader or the CC mark.
  - PROVENANCE still says the grant is OWED. The feature is off by default.
  - The 8 commits under the "leso" identity are most likely the owner committing on the Mac (verifier), but a one-line confirmation is cheap.
  - make_product_repo treats "Cablewrap" and "Creators Club" as tenant markers and requires a root NOTICE.
  - The image labels say `source=example.invalid` and `licenses=NOASSERTION`.
  - Most of the code is AI-written, which raises a copyright question (speculative).
- Scenario: due diligence asks who owns the code, and the only copyright notice disclaims itself.
- Recommendation:
  - Counsel drafts and Alex signs a confirmatory IP assignment to the Ltd. covering code, the vendored upstream and the marks.
  - Alex adds MIT or Apache-2.0 upstream and re-vendors (closes PROVENANCE and CR-2).
  - Finalise LICENSE with the EULA's entity block.
  - Remove the licensor and brand from the tenant markers, and accept `docs/legal/THIRD_PARTY_NOTICES.md` as the NOTICE.
  - Fix the OCI labels.

**COM-M4 - No DPA template, no international-transfer mechanism, no sub-processor list, and the "no sub-processor" claim is untrue in practice.** Sources: com-legal-4, com-privacy-telemetry-4 (both verifier: medium).
- Where: `PRIVACY.md` §3, §9, §11; `docs/legal/` (no DPA).
- What:
  - The Taiwan licensor becomes a processor whenever a customer sends a bundle or log or grants remote access, and PRIVACY promises an Art. 28 DPA "on request".
  - Taiwan has no EU or UK adequacy decision, so SCC Module 2 or the UK IDTA/Addendum is needed.
  - Support mail lands in a Google-hosted mailbox, which is a sub-processor.
- Scenario: the first EU or UK customer's DPO asks for the DPA and SCCs before signing. This is high for that specific deal.
- Recommendation:
  - Counsel: a DPA template with SCC and UK annexes, Annex I/II drawn from TELEMETRY, a Taiwan transfer note and a sub-processor list.
  - Owner: a one-page procedure for support data and remote access, including whether AI tools may touch customer support data.
  - Correct PRIVACY §3 and §9 and add a Transfers paragraph.

**COM-M5 - No vulnerability disclosure process, security contact, pen test or incident/breach procedure; EU Cyber Resilience Act Art. 14 reporting is live for EU sales.** Sources: com-legal-5 (verifier: medium), com-security-10.
- Where: no SECURITY.md or security.txt; `EULA.md:206-207`; `PRIVACY.md:103-110`; `image.yml:210,234` (SBOM for the image only); `db.py:4665` (`package.retract`, no advisory channel).
- What:
  - Security reports go to the generic contact address. There is no disclosure SLA, no customer advisory channel, no external pen test, no threat model and no IR or breach-notification procedure.
  - The CRA's 24 h ENISA reporting duty has applied since 2026-09-11 for products on the EU market. The full requirements arrive in Dec 2027.
  - The vendor is Taiwanese with a Taiwan forum, so this matters only if the product is sold in the EU.
- Recommendation:
  - Counsel: confirm the CRA classification and decide on the EU market.
  - Owner: SECURITY.md and security.txt with a monitored security@ address, a support period per version, an IR/breach and ENISA runbook with an owner and a deputy, a security overview PDF, and a budget for a pen test (dashboard plus loopback) before the first enterprise sale.
  - Engineering: an advisory field in the signed feed.

**COM-M6 - The product relies on reverse-engineered Resolve internals with no record that Blackmagic's licence was reviewed.** Sources: com-legal-7 (verifier: medium), com-thirdparty-tos-7.
- Where: `library.py:1-81,224-230,436-442` (postgres/DaVinci, undocumented Sm2* tables, zstd blobs, `library_walk` on by default); `resolve_prefs.py`; `bpg.py:13-39` (UIAutomation); `EULA.md` §5.
- What:
  - The access is read-only, against the customer's own database, and disclosed (verifier).
  - The schema is unsupported, so a Resolve point release can silently break the library walk at every customer at once.
  - The verifier notes that the hunter's LG-6 citation is wrong (LG-6 is Studio-edition detection).
- Recommendation:
  - Counsel: read the Resolve Studio licence against the database reads, the preference-file edits and the UI automation, as part of the counsel review already owed.
  - Engineering: a supported-Resolve-versions gate that falls back to the API walk on unknown builds (see COM-M52). Consider Blackmagic developer relations.

**COM-M7 - YouTube downloader legal exposure: yt-dlp ships in every image, the unblock glue ships dormant, and the challenge solver runs without the unblock flag.** Sources: com-legal-8, com-thirdparty-tos-4, com-product-surface-3 (all verifier: medium), com-thirdparty-tos-12 (low).
- Where: `dashboard/deploy/requirements.lock:1199`; `ytdl/web/ytdlweb/vendor/downloader.py:228-231`; `vendor/ytsearch.py:43-45`; `dashboard/deploy/run.sh:157-200,353-407`; `YOUTUBE_FEATURE_NOTICE.md`.
- What:
  - The verifier found the actual circumvention components gated. The bgutil plugin and deno are installed only when `youtube_unblock` is on, and the whole stack is off in the vendor build.
  - But every server yt-dlp call passes `js_runtimes {deno,node}` and `remote_components ['ejs:github']` whatever the unblock setting, which contradicts the notice.
  - US DMCA 1201 trafficking and EU InfoSoc Art. 6(2) readings are an open question (Hamburg youtube-dl ruling).
  - The vendor runs continuous anti-bot engineering (CR-39/73/80/83/361).
- Scenario: a rights holder names the public org, image and feed.
- Recommendation:
  - Counsel: a written US, DE and Taiwan opinion covering yt-dlp distribution and the dormant glue.
  - Owner: decide whether the commercial SKU carries the downloader at all, and state that YouTube breakage is best-effort and outside the SLA.
  - Engineering: build the solver options from `unblock_enabled()` and pin that with a test.
- Known: CR-2 (counsel owed), LG-8 and LG-10 deferred, CR-361.

**COM-M8 - EULA formation and forum.** Source: com-legal-10.
- What:
  - Each employee who clicks ACCEPT becomes "the Customer", the indemnitor (§6) and the GDPR controller (§7).
  - There is no business-use-only clause, so the AS IS terms and the cap fail against EU/UK consumers, and UK B2B terms must pass UCTA.
  - The forum is exclusively the New Taipei District Court, and Taiwan judgments have uncertain recognition abroad.
- Recommendation (counsel, in one EULA 1.2): separate an end-user acknowledgement from the organisation contract, with the order form as the binding acceptance. Add a B2B-only clause. Consider arbitration seated outside Taiwan for foreign customers.

**COM-M9 - The organisation's EULA acceptance records no person, organisation or text digest.** Source: com-legal-11.
- Where: `setup_engine.py:433-490`; `setup_routes.py:11-16,214-231`.
- What: the acceptance is made in the anonymous setup window and stores only "accepted v1.1" with a timestamp.
- Recommendation: record the text's sha256, `org_name`, the confirming admin and the source address. Re-prompt on a sha change. Or make the signed order form the binding acceptance.

**COM-M10 - A new EULA version stops sync on every editor computer until each editor clicks ACCEPT.** Source: com-customer-experience-2 (verifier: medium).
- Where: `eula.py:215-249`; `app.py:6445-6466,6684,6754`.
- What:
  - There is no grace period, no material-change flag and no organisation-level acceptance.
  - This is a documented trade-off (CR-5, D11/H7), and the tray offers one-click acceptance, so sync resumes without a restart.
  - Unattended base rigs and render nodes stay parked until someone clicks.
- Recommendation:
  - Engineering: block only at first install. After that, show a non-blocking notice for N days, plus a material-change flag.
  - Counsel: confirm that admin acceptance on the dashboard binds the organisation.

**COM-M11 - Brand and trademark: no clearance search, four names, two spellings, and the brand owner is not the licensor.** Sources: com-legal-18, com-thirdparty-tos-9, com-customer-experience-6.
- Where: CR-25; `EULA.md:16,200-207`; 218 strings spell "CCSync" against 22 for "CC Sync" in `companion/src`; `onboarding/steps.py` (62 vs 2); the GitHub org; thecreatorsclub.co.
- What: "Creators Club" is crowded (adidas used it), and "CC" invites comparison with Adobe CC. There is no record of a search or a filing.
- Recommendation:
  - Owner: decide the product name and its one spelling, the vendor brand versus the legal entity, and the support domain. Commission a clearance search and file (TW, EU, UK, US; classes 9 and 42) in the entity's name, with a trademark licence if the mark's owner is not the licensor.
  - Counsel: add a marks clause to the EULA.
  - Engineering: sweep the strings to the chosen spelling, with a scan test.

**COM-M12 - Monitoring and privacy guidance is EU-only.** Source: com-legal-15.
- What: nothing covers Taiwan PDPA (including the vendor's own support processing), the UK ICO, the US employee-monitoring notice laws (NY Civil Rights Law 52-c, CT 31-48d, DE 19 Del. C. 705) or CCPA employee notice. There is no staff notice template and no DPIA template.
- Recommendation (counsel or local counsel): a per-jurisdiction annex, a one-page staff notice and a DPIA starter built from TELEMETRY's tables.

### Privacy and telemetry

**COM-M13 - The idle-time switch does not stop the at-the-keyboard signal.** Source: com-privacy-telemetry-1 (verifier: medium).
- Where: `capabilities.py:264-283,321-368`; `jobs_runner.py:729-749`; `telemetry_fields.py:78-80`; `db.py` (`cap_jobs_gate_reason`).
- What:
  - With `input_idle` withheld, `jobs_gate.reason` still flips between `user_active` and `nothing_offered` at the 300 s threshold, because `_user_is_away()` runs before the "offered?" check.
  - Neither field table lists the field, so neither side strips it.
  - The value is current state only, shown to admins and on the user's own /account page.
- Recommendation: map `user_active` to a neutral value when `input_idle` is withheld, on both the companion and the server. Add `jobs_gate` and the ingest gates to `input_idle` in both tables. Add a test that no report field varies with the idle probe.

**COM-M14 - The triage agent sends the whole fleet's monitoring data to the AI provider, scrubbed only of secrets.** Source: com-privacy-telemetry-2 (verifier: medium).
- Where: `triage.py:273-375`.
- What:
  - A probe showed a green machine's open project ("Client X Embargoed"), its idle seconds and `user_active` all reaching `evidence.json`.
  - PRIVACY §5 describes this as "open problems".
  - It is off twice in the vendor build.
- Recommendation: build the bundle from an allow-list (only non-green machines, notices and alerts; no idle, project or Cards fields; capped transfer names; optional per-run pseudonyms). Correct PRIVACY §5.

**COM-M15 - Interview transcripts go to AI providers and are stored indefinitely in AI conversation stores, outside PRIVACY and export/erase.** Sources: com-legal-14, com-privacy-telemetry-5.
- Where: `cards_ai.py:631-672,922,1209-1214`; the CLI `--session-id/--resume` store under `<data>/tools/claude_code/home/.claude`; `triage.py:211`; `triage_mail.py:366`; `broll_index/claude_client.py`; `PRIVACY.md` §2, §4, §5, §7.
- What:
  - Interviewees are third parties, and their speech is often special-category data.
  - The privacy policy's list of flows needing a written decision covers only relays and b-roll frames.
  - `cards_sessions/*.json` and the CLI session store are never pruned.
  - There is no per-site switch to keep Cards transcripts local.
- Recommendation:
  - Engineering: prune `cards_sessions` (for example 14 days idle). Pass `--no-session-persistence` on one-shot calls. Set a short `cleanupPeriodDays`. Add a per-site Cards-AI flag.
  - Counsel: add transcripts-to-AI as a third written-decision item and qualify §2.
  - Docs: list both stores in PRIVACY and in the export's `not_included`.

**COM-M16 - Several stores keep personal data forever, and retention cannot be shortened per customer.** Sources: com-legal-16, com-privacy-telemetry-7, com-privacy-telemetry-9.
- Where: `ytdl/web/ytdlweb/db.py` (no time-based delete); `db.py:39,598,605,5521,7292` (retention constants); `config.py:833,894-897` (every `report_*` setting and `jobs_enabled` default on).
- What:
  - YouTube attestations, search terms and download ledgers, `known_editors`, project mappings and the machine registry have no expiry.
  - Search terms survive erasure, both in rows and in folder names.
  - The defaults are the most invasive settings.
- Recommendation:
  - Engineering: build LG-10 and LG-18 as Settings values. Add site-level retention overrides that can only shorten. Consider `input_idle` off unless fleet jobs are used.
  - Owner and counsel: set the retention periods. Counsel approves the PRIVACY §6/§7 update.

**COM-M17 - IP addresses are collected and kept but not listed in PRIVACY.** Source: com-privacy-telemetry-6.
- Where: `devices.address` (an editor's home IP, kept until the device is forgotten); `auth_sessions.client`; `login_attempts`; login log lines.
- Recommendation: list them per store, with retention, in PRIVACY §2 and §7. Clear `devices.address` after 30 days disconnected.

**COM-M18 - Syncthing public relays and global discovery are on by default for customer footage.** Sources: com-legal-17, com-thirdparty-tos-15 (low).
- Where: `PRIVACY.md` §5; `server/accept_device.py`; `companion app.py:7195`.
- What: encrypted footage can transit volunteer-run relays, and there is no supported off switch (LG-7 deferred).
- Recommendation: owner decides the commercial default. Engineering builds LG-7 private mode (relays and global discovery off for new sites) to its lane C prerequisites.

**COM-M19 - Uninstalling leaves a working fleet credential, an SSH key, the rclone remote and a live Google session on the machine.** Sources: com-customer-experience-4, com-privacy-telemetry-12 (low).
- Where: `installer/windows_uninstall.ps1:15-36,316,720-806`; `windows_bootstrap.ps1:928-934`; `macos_uninstall.sh:13-16,275`; `ytdl_browser_login.py:110,192`.
- What:
  - Apps & features runs the uninstaller with no switches and keeps `config.toml` (cce1 token), `identity.json`, the Syncthing identity, `youtube-cookies.txt` and `yt-login-profile`.
  - Even `-Full` keeps `~/.ssh/ccsync_ed25519` (no passphrase) and `state\` (Resolve project names).
  - The Windows uninstaller never removes the rclone stanza, though the macOS one does.
- Recommendation: by default, remove credentials and sessions. `-Full` deletes the SSH key and the rclone stanza. Print the Resolve-preference leftovers. Document in the leaver runbook that the server-side revoke is the real offboarding step.

### Open-source and notices

**COM-M20 - The vendor-published container images carry GPL OS packages with no notice and no source offer, and the dashboard image has no aggregated licence-text bundle.** Sources: com-oss-1 (verifier: medium), com-oss-9 (low).
- Where: `image.yml`; `dashboard/deploy/Dockerfile:41,69-73` (Debian python:3.12.7-slim); `sftp/Dockerfile:29,55` (alpine with BusyBox, GPL-2.0-only); `THIRD_PARTY_NOTICES.md` (no base-image section); `docs/legal/licenses/` (companion and onboarding only).
- Recommendation:
  - Engineering: generate a per-digest OS-package notice from the SBOM. Add a "Container images" section. Keep the corresponding source per published digest (snapshot.debian.org, aports at the tag). Set real OCI labels. Extend `--write-texts` to the dashboard target and serve it on /help.
  - Counsel: approve the written offer.

**COM-M21 - The CLAP audio tower ships on the vendor feed with no licence, NOTICE or inventory row.** Source: com-oss-2 (verifier: medium).
- Where: `docs/RELEASE.md:166-170`; `music_models.py:34-40` ("CC0-1.0 weights"); `music/web/data/audio_encoder/` (no LICENSE); `text_encoder/NOTICE` ("audio tower was not exported").
- Recommendation: publish LICENSE and NOTICE assets beside the model, store them next to it, add an inventory row, give one licence string and fix the text tower NOTICE. Counsel: does the model card's licence cover commercial use given the training corpus?

**COM-M22 - The editor-side yt-dlp.exe is a GPL-3.0+ combined binary from the nightly repo, but the notices call it Unlicense from stable.** Source: com-oss-5.
- Where: `ytdlp_manager.py:66,80-84`. A byte scan found mutagen, Cryptodome and curl_cffi bundled.
- Recommendation: correct the row (GPL-3.0+ combined binary, nightly, refreshed daily, mode B) and note the auto-updating posture in the YouTube notice.

**COM-M23 - llama.cpp, Qwen3-VL and NVIDIA's CUDA runtime are installed on editor machines, though the notices say they never leave the indexing machine.** Source: com-oss-6.
- Where: `broll_vlm_sidecar.py:69-84`; `broll_vlm/local_models.py:214`; `broll_ingest.py:57`.
- Recommendation: rewrite the row as mode B on editor machines, add an NVIDIA CUDA EULA row, and have counsel confirm the end-user download of the NVIDIA redistributables.

**COM-M24 - Timeline Cards code ships to customer NASes outside every licence document, with unattributed OpenCC data and a runtime Google Fonts fetch.** Source: com-oss-7.
- Where: `install_dashboard_app.py:542,566-626,950-969`; MulticamPipeline `zh_fold_table.py` (4,112 OpenCC pairs, Apache-2.0); `cards/page/10-look.js:23-31`.
- What: the Google Fonts fetch is undisclosed in PRIVACY (LG München I 2022 awarded damages for exactly this). The EULA's "Software" definition omits Cards.
- Recommendation: see COM-M48 for the scope decision. If Cards ships: NOTICE with the OpenCC attribution, self-hosted fonts, a Cards notices row, and a EULA definition update.

### Security

**COM-M25 - No MFA for anyone, and OIDC is unproven and refuses the default claim on Entra and Google.** Source: com-security-3 (verifier: medium).
- Where: `auth.py:142-180`; `oidc.py:12-15,280-312` (refuses "@" and requires a leading letter, so Entra UPNs fail and Google cannot sign in at all); `api.py:2405-2433` (the companion `/verify` is an SMB probe).
- Mitigation: tailnet-only reachability puts an IdP login with MFA in front of the dashboard.
- Recommendation: TOTP for local and SMB admins, with recovery codes. Under OIDC, defer MFA to the IdP. Test against real Entra, Okta and Google and document a claim mapping for each. Key users on `sub`. Add a browser or device-code sign-in for the companion.
- Known: COMMERCIAL_READINESS item 12.

**COM-M26 - Offboarding: removing a person at the NAS or the IdP does not stop their computer.** Source: com-security-4 (verifier: medium).
- Where: `api.py:182-272,2433-2450`; `auth.py:74,375-391`; `settings.py:135`.
- What: `_account_refusal` in smb/oidc mode refuses only a dashboard suspension. The complete control already exists (`delete_user_everywhere`, CR-76, and SUSPEND), but the leaver runbook (`SERVER.md:372-379`, `TENANCY.md`) points at `setup_editor_account.py --revoke-key`, and nothing reconciles against the NAS or IdP.
- Recommendation: a written leaver procedure built on DELETE/SUSPEND. An alert when a fleet editor is missing from the NAS or IdP (or SCIM). Shared token off and identity tokens revocable (see COM-H15).
- Known: CR-18, CR-86.

**COM-M27 - Plain HTTP on the LAN by default for LAN-only sites.** Source: com-security-5 (verifier: medium).
- Where: `install_dashboard_app.py:2090,2401`; `compose.yaml:493-506`; `auth.py:105-139,562-584`.
- What:
  - On Serve-published (https) sites, cookies are Secure and `/login` refuses plaintext.
  - But the LAN listener is always bound, and the companion's `/verify` password check is not gated.
  - A documented LAN-only site sends SMB passwords and tokens in clear.
- Recommendation: owner decides whether a LAN-only SKU is supported. Engineering: TLS by default on the LAN (Serve-only, or Caddy with an internal CA), and refuse `/verify` and `/login` from non-TLS, non-tailnet peers unless the site opts in.

**COM-M28 - Admin and plan-changing routes skip both the CSRF token and the Origin check.** Source: com-security-7.
- Where: `app.py:222-235,1079-1085`; `api.py:7091,7281,2848,2938`.
- What: `_CSRF_EXEMPT_PREFIXES` return before `_origin_mismatch` even when a session cookie is present. `.../current` and `roll-fleet-back` are query-only session-admin POSTs. SameSite=Lax does not stop same-site origins (other apps on the NAS IP, or the ts.net domain).
- Recommendation: exemption should follow the credential, not the path. Apply the Origin and token checks whenever a tracked session is present.

**COM-M29 - No security response headers anywhere, including the public share viewer.** Source: com-security-8.
- Recommendation: one middleware that sets nosniff, frame-ancestors/XFO, Referrer-Policy, HSTS when on https, and a report-only CSP, with the strictest set on `/broll/share`.

**COM-M30 - The audit trail misses the security events a buyer asks for, is mutable and cannot be exported; admin views of another person's data are not logged.** Sources: com-security-9, com-privacy-telemetry-10 (low).
- What: `fleet_audit` has no rows for login success or failure, user and role creation, token mint/revoke, AI key or CLI-path changes, or OIDC admin-by-claim. It has no retention, export or SIEM forwarding, and the access log is off by default. There is a single admin tier.
- Recommendation: audit all of these, plus admin views of `?as=`, bins and diagnostics. Add an export and an optional syslog or https sink. Publish a retention default. Consider an operator role without monitoring fields.

**COM-M31 - The public share link is served by the same process that runs the fleet, with no rate limit.** Source: com-security-11 (PLAUSIBLE).
- Where: `CLIENT_FOLDERS.md:96-170`; `app.py:1309-1316`; `routes_share.py`.
- Recommendation: a separate read-only process or container for `/broll/share`, or at minimum per-IP and per-token limits and a cap on concurrent streams.

**COM-M32 - yt-dlp nightly is fetched and executed at runtime inside the dashboard process and on editor machines, verified for integrity only.** Sources: com-thirdparty-tos-13, com-release-11.
- Where: `run.sh:353-407,488-490`; `ytdlp_nightly.py`; `ytdlp_manager.py:68-92,689-704`.
- What: `pip --pre` with no pin runs inside the process that holds the fleet tokens, AI keys and NAS credential. The checksums come from the same host, and the GPG signature is not checked.
- Recommendation: for the commercial build, track stable with a vendor-reviewed pin, or isolate the downloader in a container with no secrets. Verify `SHA2-256SUMS.sig` against a pinned key. Make nightly a disclosed opt-in.
- Known: CR-361 (owner decision 2026-10-05).

**COM-M33 - No downgrade floor has ever been set and there is no channel freshness check.** Source: com-release-8.
- Where: every `feed/channel.json` record has `min_version` 0.0.0; `release_macos.sh:838`; `build_onboard_macos.sh:507`; `upgrade.py:42-46,726`; `release_feed.py:874` (`generated_at` is never compared).
- Scenario: a stolen admin session or a confused support call makes 0.9.0 current fleet-wide.
- Recommendation: publish with `--min-version` at a security baseline before launch and raise it with every security release. Refuse a channel older than the last one accepted.
- Known: CR-52.

### Licensing, distribution and cost

**COM-M34 - No licence, seat count, entitlement, trial, expiry, install identity or update entitlement exists anywhere.** Sources: com-licensing-billing-1, -3, -4 (all verifier: medium), com-ops-at-scale-11.
- Where: whole tree; `EULA.md` §2, §12; `release_feed.py` `_apply_policy`; `settings.py:109`; `LEGAL_GAP_FEATURES_PLAN.md:960,1229`.
- What: every install is unlimited and perpetual, a copied stack is indistinguishable from the original, and a lapsed customer receives every release. The contract is still enforceable, and D7 and LG-19 are deliberate deferrals.
- Recommendation:
  - Owner and finance: choose the licensing model (per seat or per site, trial terms, what happens when payment stops).
  - Engineering: an offline signed `licence.json` (licence_id, org, not_after, updates_until, seats, features, kind, bound_to host) under a separate offline key. A random `install_id` minted at first boot and shown in health. A LICENCE panel. A soft gate only at enrolment (banner, then refuse new computers after a grace period, never stop sync). `updates_until` filtering in `_apply_policy`, with security releases always allowed through.

**COM-M35 - The whole product is publicly downloadable with no credential, including the full Python source, under a LICENSE that says "confidential".** Sources: com-licensing-billing-2 (verifier: medium), com-legal-12, com-thirdparty-tos-10.
- Where: `DOCKER.md:474-480`; `RELEASE_FEED.md:404-406`; `release_feed.py` (no credential); `compose.appliance.yaml`; `EULA.md` §8.
- What:
  - This is a deliberate zero-touch choice, and every self-hosted customer gets readable source anyway.
  - EULA §8 overstates verification: an image pulled by tag is not checked against the licensor's key.
  - Source, feed, image and the YouTube integration all sit in one org, which is a single takedown point.
- Recommendation:
  - Owner and counsel: either declare the product source-available and drop "CONFIDENTIAL", or move to per-customer registry and feed tokens (`release_feed` sends a bearer token). Add an audit right.
  - Counsel: narrow EULA §8's wording or cover image pulls with cosign verification (see COM-H10).
  - Owner: keep an off-GitHub mirror.

**COM-M36 - The feature flags are customer-controlled switches, not vendor entitlements.** Source: com-licensing-billing-6.
- Where: `site_store.py:81-100,834-868`.
- Recommendation: owner decides whether to sell tiers. If so, `licence.features` becomes an AND-term in `feature_enabled` and the mount functions. If not, decide on a single SKU explicitly.

**COM-M37 - No seat or usage statement the vendor can invoice from.** Source: com-licensing-billing-7.
- Where: `db.py:5108,9358-9390`.
- Recommendation: define a seat as a computer active in the last N days. Add a LICENCE panel count and a downloadable usage statement signed by a per-install key, which keeps the no-phone-home promise. Alert at 90% and 100% of seats.

**COM-M38 - AI spend is uncapped, unmetered and unattributed.** Source: com-licensing-billing-8.
- Where: `cards_ai.py:113,429-469`; `ai_providers.py` (first-available fallback); `ai_backend.py:469,569`.
- What: any Cards user can pick Opus, and adding a key can silently move spend to another provider.
- Recommendation:
  - Engineering: an `ai_usage` table, "this month" with estimated cost on Settings > AI providers, a per-site soft cap, and an admin model allow-list.
  - Owner and counsel: the order form states that AI usage is billed to the customer by the provider.

**COM-M39 - The install guide says Tailscale's free tier is enough, but it is for non-commercial use only, and Funnel is a bandwidth-capped beta.** Source: com-thirdparty-tos-5.
- Where: `APPLIANCE_INSTALL.md:35`; `CLIENT_FOLDERS.md:96-215`.
- What: businesses need Standard ($8 per user per month) or higher.
- Recommendation: fix the doc. Put "Tailscale Standard+ per user" in the pricing and order form. Label Funnel delivery as beta and capped, and document a reverse-proxy alternative. Finance must include Tailscale in TCO quotes.

**COM-M40 - The documented Cloudflare-tunnel route for proxy downloads probably breaches Cloudflare's CDN terms for video.** Source: com-thirdparty-tos-6 (PLAUSIBLE).
- Where: `CONFIG.md:585-660`; `rclone_lane.py:631-650`.
- Recommendation: mark it studio-only or unsupported until Cloudflare confirms in writing (or use R2 or Enterprise). Never quote 52 MB/s to buyers.

### Tenancy (first-studio assumptions)

**COM-M41 - The project tree layout is the first studio's, and nothing makes it site data.** Source: com-tenancy-1 (verifier: medium).
- Where: `settings.py:78-94` (`SUPPORTED_PROJECTS_DIR`); `lane_guard.py:70,303`; `fixer.py:253-269,401`; `ytdl db.py:1810`; `TREE_LAYOUT_PLAN.md` ("Nothing built").
- What: a wrong layout is refused loudly at boot, not silently.
- Recommendation: before selling, a written layout requirement plus a pre-sale qualification question and an onboarding checklist item (owner or sales). WP1-WP5 (about 12 days, after decisions D1-D6) is roadmap work.

**COM-M42 - The product-repo export can no longer produce a clean repo.** Source: com-tenancy-3.
- Where: `make_product_repo.ps1:145-218,347-351`.
- What:
  - Outside its exclusions there are thousands of marker hits (ruskin 889, leso 323, tail26290e 46, ...).
  - The `bug-hunt-*` glob misses the directories, and the ledger, sweep, mobile and prelaunch directories are never pruned.
  - Escaped `C:\\Users\\alex` paths slip through.
  - Markers are missing for FF5, Creator_1, Razer, mofa and interviewee names.
- Recommendation: prune `docs/` by allow-list, add the missing markers and an escaped-path regex, and run the scan in CI.

**COM-M43 - Real interviewee names and the studio's catalogue sit in tracked fixtures and eval data.** Source: com-tenancy-4.
- Where: `broll/eval/local_vlm/clips.json`; `broll/docs/prototypes/local-vlm/*.json`; indexer tools; `test_sequencer.py`; `test_provision.py`; `test_unicode_paths.py`.
- Recommendation: use invented decomposable Latin and CJK names in the fixtures. Move the eval and preset data to the git-ignored `private/`.

**COM-M44 - The own-footage archive folder is "Creators_Club" for every customer.** Source: com-tenancy-5.
- Where: `broll/web/app/config.py:191-206`; `ingest_batches.py:264-266`; `broll/indexer/build_archive.py:54,179` (a literal); no appliance variable.
- Recommendation: a neutral default for new sites, a `site_store` key and wizard field, and `build_archive` reading the same value.

**COM-M45 - TrueNAS deploys run the container as 3000:3001 without checking the live box.** Source: com-tenancy-6.
- Where: `install_dashboard_app.py:1500-1501,5358-5419`; `backends/truenas.py:748-753`; `compose.appliance.yaml:71-79`.
- What: TrueNAS gives uid 3000 to the first local user, so the container can write as the wrong account or be unable to write into the 2770 tree.
- Recommendation: resolve the ids through the API as the Synology branch does, refuse a mismatch, have the wizard write `APP_UID`/`APP_GID`, and remove the "already right" claim.

**COM-M46 - YouTube search expands every term into Taiwan Traditional Chinese by default.** Sources: com-tenancy-7, com-product-surface-3 (part).
- Where: `claude_cli.py:566-628` (`DEFAULT_TERM_SCOPE = SCOPE_BOTH`).
- Recommendation: make the expansion languages a site setting (a BCP-47 list) defaulting to the site language or English only. Owner decides the default.

### Product scope and platform

**COM-M47 - There is no defined v1 and no preview labelling.** Source: com-product-surface-1 (verifier: medium).
- What: risky features are off by default, and navigation hides unmounted apps. But nothing lists what v1 includes and nothing marks music, jobs or triage as preview.
- Recommendation: owner publishes a v1 feature sheet. The hunter proposes:
  - sync core and admin READY (macOS beta);
  - b-roll READY;
  - client folders HIDE;
  - music BETA;
  - ytdl CUT;
  - Cards, cards agent and fleet jobs CUT;
  - triage HIDE;
  - PWA READY;
  - Android HIDE;
  - OIDC, Synology and appliance BETA.
  Mark preview features in the EULA and UI, and hard-disable CUT features.

**COM-M48 - Timeline Cards, the cards agent and whisper jobs depend on a second repository outside every gate, while the JOBS page and the tray's volunteer item show on every install.** Sources: com-product-surface-2 (verifier: medium), com-ops-at-scale-12, com-quality-gates-15, com-tenancy-10 (low).
- Where: `cards.py` (`DASH_CARDS_SRC`); `CARDS_DEPLOY.md`; `config.py:833-873`; `ui.py:267`; `tray.py:3070-3084`; MulticamPipeline has no CI.
- What:
  - Only whisper needs the checkout; the three media job kinds need only ffmpeg (verifier).
  - The release/reload handshake has never run live.
  - CR-137 (three Cards suites red) is OPEN.
- Recommendation: owner decides whether Cards is in v1. If not, exclude it in the product description and order form, and hide JOBS and the volunteer item unless jobs are configured. If so, it needs CI, a versioned signed feed artefact, a live handshake run, CR-137 cleared, and the COM-M24 notices.

**COM-M49 - Client folders let any editor publish any archive clip, including YouTube-downloaded shares, to a public link offered "to licence".** Source: com-product-surface-4 (verifier: medium).
- Where: `routes_client_folders.py:98-113,215-231` (`require_user` only); `client_folders.py:84,590-626`.
- What: links reach the internet only through a deliberate Funnel publish, and EULA §6 puts the rights on the customer.
- Recommendation: an admin marks the collections that may be shared (YouTube and originals shares refused by default), each clip's collection is shown on the add path, links expire by default, and the EULA wording is widened to "publish to third parties".

**COM-M50 - The Android app is a per-customer build that the customer must make, sign and sideload.** Source: com-product-surface-6.
- Recommendation: sell only the PWA in v1 and hide Settings > ANDROID. Later, one vendor-signed app that reads its origin at runtime.

**COM-M51 - The feed's version-ordering and CPU-architecture checks are switched off, and the companion's minimum dashboard version is stale.** Sources: com-release-5, com-quality-gates-2 (both verifier: medium).
- Where: `sign_release.py:369-389`; `publish_latest.py:179-184,505-525`; `config.py:174` (`REQUIRES_DASHBOARD` 0.7.23); `upgrade.py:1518`; `release-macos.yml:52` (arm64 only).
- What: this is the deliberate REL-4/REL-16 overlap policy, but its premise (the fleet below 0.9.55) has expired. The claim that 0.9.80+ needs about 0.7.60 is not proven.
- Recommendation: turn on `CCSYNC_EMIT_KIND_EXTRAS=1` for the vendor feed. Raise `REQUIRES_DASHBOARD` to the real minimum, with a test tying it to dashboard-first changes. Use retraction (not `min_version`) for bad builds, plus a floor (see COM-M33).

**COM-M52 - No platform support matrix, no runtime version checks, Windows 10 (end of life) listed, Mac side lagging Windows.** Sources: com-product-surface-8 (verifier: medium), com-quality-gates-9, com-release-13 (low).
- Where:
  - `INSTALL.md:30,55,65`;
  - `resolve_prefs.py:28-30` (keys read off Resolve 20);
  - no GetVersion or edition check anywhere;
  - `release_macos.sh:683-697` (arm64 only), no `LSMinimumSystemVersion`, floating `macos-latest`/`windows-latest` runners;
  - onboard/macos current is 1.0.44 against 1.0.46 on Windows, and it lacks the LG-1 privacy page;
  - MACOS_FIRST_RUN A7-H has never been run;
  - CR-280/CR-283U have not been verified on a frozen Mac build (certifi is not in the lock).
- Recommendation:
  - Docs/owner: a SUPPORTED_PLATFORMS page referenced from the EULA and order form (Resolve Studio versions, Apple silicon only or universal2, Windows 11 x64, macOS minimum, browsers, Tailscale plan, TrueNAS/DSM versions).
  - Engineering: log or check GetVersion/GetProductName after `connect()` and refuse preference writes for unknown majors. Refuse x86_64 Macs in the installer. Publish onboard/macos at parity. Add certifi to the lock and verify CR-280. Run and record MACOS_FIRST_RUN. Pin the runner images.

**COM-M53 - No release candidate to sell: version 0.x, four unrelated version streams, one-line release notes, no changelog or compatibility table.** Sources: com-product-surface-11, com-customer-experience-11 (low), com-ops-at-scale-14 (low).
- Where: `config.py:156`; `dashboard __init__.py:31`; `onboarding/steps.py:148`; `sign_release.py:443`; `RELEASE.md:1396-1416`.
- Recommendation: freeze a v1 RC (commit, full gate, build, sign, soak, publish). Decide a customer-facing release identity that maps to the component versions, and revisit the "never 1.0" rule. Publish curated per-version notes with a compatibility table and security advisories.

**COM-M54 - No managed-deployment path.** Source: com-release-10.
- What: the companion is a per-user, self-replacing exe under `%LOCALAPPDATA%`, the instructions use ExecutionPolicy Bypass, and there is no MSI, pkg or silent install. AppLocker and WDAC default rules block executables in user-writable paths.
- Recommendation: owner decides whether managed-IT customers are a launch target. If yes, build a signed WiX MSI and a notarised pkg with unattended parameters. If no, state "unmanaged machines only" in the order form.

**COM-M55 - The documents shipped to customers are internal runbooks, and there is no admin guide.** Source: com-customer-experience-7.
- Where: `published_docs.py:41-53`; `EDITOR_SETUP.md` (raw PowerShell bootstrap, server scripts, "studio base rig"); `INSTALL.md`; `APPLIANCE_INSTALL.md` (DRAFT).
- Recommendation: an editor quick start built around the wizard; an admin guide covering install, people, computers, backup and restore, updates and decommission; a troubleshooting FAQ. Strip internal references, and add a test that no published doc links to an unpublished one.

**COM-M56 - The normal install blocks every inbound SMB share on the editor's PC, with no disclosure or opt-out in the wizard.** Source: com-customer-experience-8.
- Where: `windows_bootstrap.ps1:1406-1430,1648-1657`.
- Recommendation: scope the rule so it leaves the PC's other shares alone. Otherwise add a wizard step that says so plainly, with an opt-out mapped to `-KeepRemoteSmbOpen`, and document it.

**COM-M57 - There is no offboarding path for a customer that leaves.** Source: com-customer-experience-9.
- Where: `EULA.md:179-184` ("remove it from your systems"); no teardown script.
- Recommendation: a "Leaving CC Sync" admin page (export, fleet-wide uninstall, NAS teardown including client-share links, what stays). A `server/decommission.py` with a dry run. Counsel aligns EULA §12 with what is actually supported at exit.

**COM-M58 - net share / net use output is decoded as UTF-8, but net.exe writes in the OEM codepage.** Source: com-customer-experience-10 (PLAUSIBLE).
- Where: `paths.py:134-178`; `drive_swap.py:102-115,309-340`.
- What: a non-ASCII local root mis-resolves on Chinese or European Windows.
- Recommendation: decode with `GetOEMCP()`, or call `NetShareGetInfo`/`WNetGetConnectionW` (UTF-16). Add a cp950 table test.

**COM-M59 - Apps & features shows the customer as Publisher and a frozen, wrong version; the companion has no About.** Source: com-customer-experience-5.
- Where: `windows_bootstrap.ps1:289,928-943,1019-1027`.
- Recommendation: set Publisher to the legal entity, refresh DisplayVersion after each upgrade, add HelpLink and URLInfoAbout, and add an About row (product, version, licensor, copyright, EULA, privacy, licences).

### Vendor operations at scale

**COM-M60 - Under the default soak gate, each release needs a manual canary at each customer, and the soak counts only crashes on one machine for 30 minutes; there are no rollout rings or beta channel.** Sources: com-ops-at-scale-4 (verifier: medium), com-quality-gates-8, com-release-12 (low).
- Where: `release_feed.py:1000-1090`; `package_store.py:79-118,163-350`; `db.py:4691`; `image.yml` (`:1`).
- What: `soak_minutes = 0` restores unattended `current` for a site. `versions_behind` raises an alert only at 3 builds behind.
- Recommendation: a signed vendor-soak attestation, or a "current-after-vendor-soak" policy. A vendor canary of days across Windows and Mac, with criteria covering lane_error, stall, breaker, report_refused, upgrade_reverted and crashes. An opt-in early channel. Documentation in the customer docs.

**COM-M61 - In practice installs are vendor-performed, holding the customer's NAS admin credentials.** Source: com-ops-at-scale-5 (verifier: medium).
- Where: `APPLIANCE_INSTALL.md`; `INSTALL.md:26-95`; `ZERO_TOUCH_PLAN.md:280-289`.
- What: TrueNAS has a scoped-key path. DSM does not.
- Recommendation: either finish WP B, F and G, or commit in writing to vendor-performed installs, with pricing and a credential-custody policy (scoped keys, deleted after install, a real vault).

**COM-M62 - The vendor has no view of its install base.** Source: com-ops-at-scale-6 (verifier: medium).
- Where: `release_feed.py:160-250`; `RELEASE.md:966-985`.
- What: release-compatibility actions (kind extras, the floor, key rotation) are judged from the studio's own fleet. "No phone-home" is a deliberate privacy promise.
- Recommendation: a written release-compatibility policy (no floor or extras change without written confirmation from each customer). A vendor-side customer registry. Later, WP G or an opt-in heartbeat disclosed in PRIVACY and TELEMETRY.

**COM-M63 - A recall reaches customers in up to a day and does not stop the bad build running.** Source: com-ops-at-scale-9.
- Where: `release_feed.py:499-523`; `settings.py:463` (86,400 s poll); `alerts.py:2711-2723`.
- Recommendation: poll hourly, auto-roll back to an earlier ever-current build on recall, add a signed `advisories[]` field shown as a banner and alert, and keep a vendor contact list.

### Engineering process and quality gates

**COM-M64 - Each bug hunt keeps finding about ten highs, and there are no release exit criteria.** Source: com-quality-gates-4 (verifier: medium).
- What: this pre-launch review is itself the broad hunt of the recent unhunted changes. The process gap remains.
- Recommendation: freeze an RC with written exit criteria: zero confirmed highs in a hunt of the RC and in a hunt of its fix pass, plus an N-day studio soak with no new medium-or-worse in the sync, delete or upgrade paths. Track the high-discovery rate.

**COM-M65 - No code review or change approval: every commit goes straight to main from one account, all AI co-authored.** Source: com-quality-gates-5 (verifier: medium).
- What: `publish_latest` does gate on a green run and ancestry, and `auto_update` is off in the vendor build.
- Recommendation: protect main with required checks. Add CODEOWNERS with a contracted human reviewer for the sync-delete, upgrade/signing and auth paths. Write a one-page SDLC statement for questionnaires (SOC 2 CC8.1, ISO A.8.32).

**COM-M66 - The Linux CI job runs about 25 of its 30 minutes, and no test has its own timeout.** Source: com-quality-gates-10.
- Recommendation: pytest-timeout in every suite, a per-suite matrix, a `--durations` budget, and fake clocks.

**COM-M67 - Tests that skip when a tool is missing still leave CI green.** Source: com-quality-gates-11.
- Where: `ci.yml` (ffmpeg steps `continue-on-error`, `CCSYNC_REQUIRE_RCLONE`/`FFMPEG` unset); `test_text_encoder.py:74-79`.
- What: the CLAP gate runs on one machine only.
- Recommendation: set the require variables, require node, keep a committed skip baseline, and decide on a CLAP fixture or a scheduled self-hosted gate.
- Known: CR-65.

**COM-M68 - KNOWN_BUGS.md cannot tell a buyer or a support desk what is actually open.** Source: com-quality-gates-12.
- What: 32k lines, 194 headings still marked "unshipped", 515 "owed", and no severity, fixed-in or shipped-in fields.
- Recommendation: a structured tracker (or a generated status table checked in CI), a one-time triage of "unshipped" entries, and customer release notes and known issues.

**COM-M69 - About 1,050 lines of live-incident fixes have sat uncommitted for six days.** Source: com-quality-gates-14.
- What: the CR-356/357/358 fixes plus the alert muting. The dashboard is still VERSION 0.7.73 although its bytes changed, so `publish_feed` would refuse it.
- Recommendation: commit in reviewable units with the version bumps, run the full gate once, and adopt a launch rule that nothing ships from (or sits for more than a day in) an uncommitted tree.

**COM-M70 - No one-page release checklist, no coverage measurement, and no test of mixed companion and dashboard versions.** Source: com-quality-gates-16.
- Recommendation: a `RELEASE_CHECKLIST.md` (RC tag through the recall command), pytest-cov floors on the sync, upgrade and auth modules, a replay corpus of per-version `/report` and `/verify` payloads in CI, and a published version-skew policy.

## 4. Polish (low)

- **COM-L1** (com-tenancy-2, verifier: low from high): the shipped images and the companion carry staff names, machine names, the tailnet name and the NAS's CGNAT IP in comments and docstrings, all of it the vendor's own identity. Fix: a CI tenant-marker scan over the build outputs, role words in place of names, and `optimize=2`.
- **COM-L2** (com-oss-8): the notices inventory has drifted (rclone and Syncthing pins, no Claude Code or Codex CLI rows, no third-party compose image rows). Fix: correct the rows and add a test that reads each pin and asserts NOTICES names it.
- **COM-L3** (com-oss-10): the Android TWA APK has no licence or notice coverage (androidx and android-browser-helper are Apache-2.0). Fix: an APK row and a licences link.
- **COM-L4** (com-thirdparty-tos-14): DeepSeek is offered with no PRC jurisdiction note. Fix: a note on the row and a vendor-build switch to hide it.
- **COM-L5** (com-security-13): the local password policy is length-only. Fix: a check against an offline common or breached password list (NIST 800-63B).
- **COM-L6** (com-security-14): emailed triage replies are a second admin door authorised by email authentication alone. Fix: keep it off in the vendor build, document it, limit it to reversible actions, and audit each action with its message-id.
- **COM-L7** (com-tenancy-9): `site.example.toml`, `config.example.toml` and the /help docs use the live fleet's IPs, names and FF5 paths. Fix: neutral placeholders (RFC 5737 addresses, Studio_Projects).
- **COM-L8** (com-tenancy-11): the TrueNAS client falls back to `/mnt/tank/TheCreatorsPool/homes`. Fix: refuse, naming the missing setting.
- **COM-L9** (com-customer-experience-13): no accessibility statement, and the companion's Tk dialogs (including the licence) are invisible to screen readers. Fix: a statement, a dashboard route to every modal, and a VPAT on request.
- **COM-L10** (com-privacy-telemetry-11): Syncthing crash reporting, Claude Code CLI telemetry and the Cloudflare tunnel route are missing from PRIVACY §5. Fix: disable them (`crashReportingEnabled=false`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`) or disclose them.
- **COM-L11** (com-product-surface-12): music search is tuned and measured on one 376-track library. Fix: label it beta, run the eval on a second library, and fix MUSIC-ING-1 (companion-ingested tracks have no BPM or key) first.

## 5. Refuted

None. No critical or high was refuted outright. Several individual claims inside findings were corrected by verifiers, and those corrections are folded into the items above:
- **COM-H1:** triage does have a compliant mode (Console sign-in).
- **COM-H3:** the GPL-3.0 text is present. The EULA clause is §3(b), and §11 already carves out third-party components.
- **COM-M3:** the second contributor is most likely the owner's own Mac identity.
- **COM-M6:** LG-6 is mis-cited.
- **COM-M7:** the unblock components are gated. Only the solver options are not.
- **COM-H12:** EULA §12 does have a breach clause.
- **COM-M27:** Secure cookies and the plaintext login refusal are on for Serve sites.
- **COM-M48:** only whisper needs the MulticamPipeline checkout.

## Coverage gaps

What the hunters said they did not get to:
- **Live state:** the live GitHub feed, GHCR visibility and tags, and branch protection were not queried. The stale-channel evidence (COM-H8) rests on the local `feed/channel.json` copy of 2026-09-26 plus the git tags. Re-check against the live feed before acting.
- **macOS:** no macOS build was inspected (psycopg2 dylibs, evermeet ffmpeg flags, the real TCC behaviour). There is no Developer ID signature to test. The Mac wizard UI, MACOS_FIRST_RUN and CR-280 are unverified.
- **Images:** no Docker image was built or scanned with syft or trivy.
- **Upstream licences and terms:** the yt-dlp combined-binary GPL statement and the CLAP training-data terms come from the hunters' knowledge, not a fresh check. The Blackmagic, Google/YouTube, OpenAI, DeepSeek and Synology DSM terms were not read in full.
- **Timeline Cards:** the MulticamPipeline repo was not reviewed beyond its licence-relevant files and the absence of CI.
- **Security internals:** the companion loopback (CR-7), the SPAs' route-level authorisation, the Cards sub-app, Funnel path normalisation and the NAS-side account scripts were not covered.
- **Telemetry and privacy:** not every `sync_guard` sub-key was checked against TELEMETRY. Export and erase coverage was not probed at runtime. Logging inside the music and b-roll indexers, and what the Claude Code CLI and Syncthing send by default, were not probed.
- **Accessibility and locale:** the b-roll, music and Cards SPAs were not reviewed for accessibility, nothing was run on a live screen reader, and there was no real non-English Windows install (COM-M58 stays PLAUSIBLE).
- **Unconfirmed facts:** pricing figures (no dollar measurement of AI cost), whether contact@thecreatorsclub.co is monitored, whether the Q: key backup is truly offline, and P:\ collisions at customer sites.
- **Test suites:** the full suites were not run. Only targeted test files passed (dashboard alert selection 13, companion fixer, resolve_bridge and telemetry 257, broll collection filter 37, tools test_map 46).
