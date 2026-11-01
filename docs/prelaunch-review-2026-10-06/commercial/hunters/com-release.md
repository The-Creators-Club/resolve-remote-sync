# com-release - release, signing and distribution readiness

Pre-commercial-launch review, 2026-10-06, HEAD 08b40eb plus the uncommitted working tree. Read-only.

**Covered:** `docs/COMMERCIAL_READINESS.md` item 4 checked against the code. Also read: `docs/RELEASE.md` (code signing, release key, kind extras), `docs/RELEASE_FEED.md`, `docs/RELEASE_PATHWAYS.md`, `docs/APPLIANCE_INSTALL.md`, `installer/START_HERE.md`, all six `.github/workflows/*.yml` (signing steps, triggers, permissions, action pinning), `tools/sign_windows_binary.ps1`, `tools/release_macos.sh` and `tools/build_onboard_macos.sh` (signing and notarisation blocks), `tools/publish_latest.py`, `tools/publish_feed.py`, `tools/sign_release.py` and `tools/release_key.py`. In code: the settings for the release key, feed URL, policy and soak; the setup wizard's release-key task; `select_code_root.py`; `compose.appliance.yaml` / `compose.image.yaml`; the companion's downgrade floor; the feed's recall and freshness handling.

Also inspected: the local `feed/channel.json`, which `publish_feed.py` merges from the live channel, so it reflects what was published as of its last run on 2026-09-26. Also local git tags, the `~/.ccsync-release/` layout (file names and the backup record only, never the key), and KNOWN_BUGS (REL-1/3/4/16, CR-361, the macOS code-signing backlog item).

**Not covered:** the live GitHub release, GHCR visibility and remote tags. This was a no-live-systems rule, so "the feed is stale" is judged from local tags and the local copy of the feed. Not verified: the Android keystore/APK path, the Cards deploy path, and whether the `Q:` backup is truly offline.

---

### com-release-1 - Every binary a customer installs is unsigned: no Authenticode, no Developer ID, no notarisation
- **Severity:** critical
- **Confidence:** CONFIRMED
- **Where:** `feed/channel.json` (every one of the 12 records has `signed_binary: false`); `.github/workflows/release-macos.yml:201` (hard-coded `"signed_binary":false`); `installer/START_HERE.md` ("Click More info, then Run anyway"); `onboarding/build_onboard_macos.spec:74`; `docs/RELEASE.md` "Operator TODO"; `docs/COMMERCIAL_READINESS.md` item 4 ("BLOCKED ON PURCHASE").
- **What:** The Ed25519 release-record signing is real and works. The OS-level code signature does not exist on any artefact: the Windows companion, `onboard.exe`, the macOS companion Mach-O and the macOS wizard `.app`. Seven weeks after item 4 was marked "blocked on purchase", no certificate has been bought. Every ship has used `-AllowUnsignedBinary`.
- **Scenario:**
  - **New Windows editor:** downloads `onboard.exe` from the dashboard and gets "Windows protected your PC". Our own docs teach them to click past it, which is the advice malware gives.
  - **Windows 11 with Smart App Control on** (the default on clean installs): an unsigned exe is blocked outright, with no "Run anyway". That machine cannot be installed at all.
  - **Managed customers:** any WDAC/AppLocker publisher rule or EDR allowlist cannot whitelist the product, and an unsigned PyInstaller exe that self-replaces and spawns rclone/syncthing is classic AV-heuristic bait.
  - **New Mac editor:** macOS 15 needs Privacy & Security > Open Anyway with an admin password. The ad-hoc companion loses its TCC grants on every self-upgrade (KNOWN_BUGS backlog "macOS code-signing (was item 16)").
- **Recommendation:** These are not code artefacts. **The owner** must:
  1. Settle the legal entity first: OV/EV certificates and an Apple Developer *organisation* enrolment both need a registered entity and a D-U-N-S number. The EULA licensor is still a placeholder (com-licensing-billing-9).
  2. Buy an Authenticode certificate (cloud-HSM signing such as Azure Trusted Signing, DigiCert KeyLocker or SSL.com eSigner fits the "CI builds, rig signs" model better than a USB token).
  3. Enrol in the Apple Developer Program, create a Developer ID Application certificate and an app-specific password for notarytool.

  Then, once com-release-2 is fixed, ship one signed build end to end. Rewrite `START_HERE.md` so it never tells a customer to bypass SmartScreen.
- **Known:** COMMERCIAL_READINESS item 4 (open, blocked on purchase); KNOWN_BUGS backlog "macOS code-signing (was item 16)" (open).

### com-release-2 - Even with certificates bought, the pathway every customer receives builds through cannot produce a signed build
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:**
  - `tools/publish_latest.py`: no signtool/codesign step, and no `signed_binary` gate anywhere in the file.
  - `.github/workflows/release-windows.yml:72,199-220`: PFX-in-secrets route.
  - `.github/workflows/release-macos.yml:146-150`: only `CCSYNC_APPLE_DEV_ID` is passed. There is no keychain import, no `CCSYNC_NOTARY_PROFILE`, and the onboard step gets no identity at all.
  - `docs/RELEASE.md` "Where the Authenticode key should live" (release-pipeline-11, "not reconciled").
- **What:** Pathway B (CI build, then `publish_latest.py`, then the public feed) is the only route to feed customers. `ship.cmd`'s refusal to make an unsigned binary current exists only on pathway A, which publishes to this studio's dashboard alone. On pathway B:
  - `publish_latest` signs the release record over whatever CI produced and has no unsigned refusal.
  - **Windows CI** can only sign from a base64 PFX secret. Since the June 2023 CA/B rule, no OV/EV code-signing key can be exported to a PFX, so that route cannot work with any certificate on sale today.
  - **macOS CI** never imports a certificate into a keychain, so a set `CCSYNC_APPLE_DEV_ID` makes `codesign` fail and the build abort.
  - Notarisation credentials are never supplied.
  - The wizard step never sees the identity, and its manifest says `signed_binary:false` whatever happens.
  - The documented alternative, "sign on the rig", has no implementation: nothing re-signs a downloaded CI artefact before its record is signed.
- **Scenario:** The owner buys both certificates and sets the env vars as `RELEASE.md` says. Every feed release still goes out unsigned (Windows), or fails to build (macOS with `CCSYNC_APPLE_DEV_ID` set as a secret). Nothing in pathway B refuses or warns loudly enough to stop a `--make-current`.
- **Recommendation:**
  1. Decide where signing happens. A cloud HSM with OIDC (Azure Trusted Signing) in an approval-gated GitHub environment, or a rig re-sign step inside `publish_latest.py`.
  2. Implement it for all four artefacts, including keychain import, notarytool API-key credentials and stapling for the wizard on macOS CI.
  3. Give `publish_latest.py --make-current` the same unsigned-binary refusal and `--allow-unsigned-binary` override that `ship.ps1` has.
  4. Have the rig check the Authenticode/codesign status itself, rather than trusting the CI manifest's `signed_binary` claim.
- **Known:** release-pipeline-11 (documented as an unreconciled decision, no ledger id).

### com-release-3 - The customer distribution channel is a month behind what the vendor runs: feed dashboard 0.7.44 and image `:1` = v0.7.44, repo at 0.7.73
- **Severity:** high
- **Confidence:** CONFIRMED (local tags plus the local copy of the live feed; the remote is not queried)
- **Where:**
  - `feed/channel.json`: `current["dashboard/linux"] = "0.7.44"` (published 2026-09-11), `dashboard_image.tag = "0.7.24"`. The newest `feed/linux/*.tar.gz` is 0.7.44.
  - `git tag -l "v*"`: newest is `v0.7.44`, and `image.yml` moves `:1` only on a `v*` tag.
  - `dashboard/src/ccsync_dashboard/__init__.py:31`: `VERSION = "0.7.73"`.
  - `server/install_dashboard_app.py:1415-1428,1621-1627`: the studio runs `:edge` or a sha digest, not `:1`.
- **What:** A feed or appliance customer gets dashboard 0.7.44 through both the code bundle and the image, and the feed's image hint still names 0.7.24. Meanwhile the companion pointer is at 0.9.84.
  - **Missing from what customers get:** everything since 2026-09-11. That includes the 09-18 and 09-24 bug-hunt highs, LG-1 (the per-site telemetry switches the legal docs promise) and LG-4 (the cleartext-to-public refusal), the account page, schema v55-v58, and CR-361.
  - **Not dogfooded:** the vendor's own dashboard comes from `:edge`/digests, so the `:1` + feed path a customer depends on is never exercised by anyone.
  - **Ordering:** `CLAUDE.md` says repeatedly "deploy the dashboard before the companions". A feed customer is offered companion 0.9.84 beside dashboard 0.7.44, the exact ordering those rules forbid (see com-release-5 for why nothing enforces it).
- **Scenario:** A first customer installs the appliance on launch day. They run code missing a month of security and legal fixes, with companions newer than their dashboard expects (for example, "an old dashboard banners the new report section on every report"). The vendor's own fleet looks fine, because it runs a different build.
- **Recommendation:**
  1. Make the customer channel the vendor's channel. Cut a `v0.7.7x` tag so `:1` moves, publish the matching dashboard bundle to the feed, and update `dashboard_image` with `--set-image`.
  2. Switch the studio itself to `:1` or a feed-published digest, so every customer release has been run by the vendor first.
  3. Add a drift check (`check_deploy_drift.ps1` or a `publish_latest` preflight) that fails when the feed's dashboard or image is behind the companion's real dashboard requirement.
- **Known:** none.

### com-release-4 - A new appliance customer has no vendor key and no feed URL: no installer, no companion, no updates
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:**
  - `dashboard/deploy/compose.appliance.yaml:35-42,168-174`: claims `DASH_RELEASE_PUBKEYS` is "generated into data/secrets on first boot". A public key the vendor holds cannot be generated, and nothing reads one from secrets.
  - `dashboard/src/ccsync_dashboard/settings.py:429,438`: both default empty.
  - `dashboard/deploy/Dockerfile`: no baked key or feed URL.
  - `dashboard/src/ccsync_dashboard/setup_engine.py:1527-1541`: tells the operator to put "the public half of **your** release key" there and redeploy.
  - `server/install_dashboard_app.py:1660`: the "Fix" is `python tools/release_key.py pubkey`, which a customer cannot run.
  - `docs/APPLIANCE_INSTALL.md` (DRAFT, "nothing publishes a companion build to this fleet from the appliance").
- **What:** On the zero-touch path, which is the one meant for customers, the dashboard boots with `release_pubkeys=()` and `release_feed_url=""`. With no key, every publish is a 503. `select_code_root` can never apply an over-the-air code update ("the image always wins"). With no feed URL, no package ever arrives, so `[ INSTALLER ]` has nothing to serve and no editor machine can be installed. The compose file also says "none of it should be edited", and the wizard's wording sends the customer looking for a key they do not have.
- **Scenario:** A customer pastes `compose.appliance.yaml`, completes the wizard and has no way to install their first editor without emailing the vendor for two values and editing a file they were told not to touch.
- **Recommendation:** The vendor's public key(s) and the feed URL are public values, so bake both into the image as defaults (for example `ENV` in the Dockerfile, or constants in settings), with the environment still able to override. Rewrite the wizard task so it says "the vendor's signing key" and never names `release_key.py` to a customer. Then have someone other than the author run `APPLIANCE_INSTALL.md` end to end and remove its DRAFT label.
- **Known:** partially in `APPLIANCE_INSTALL.md` "NOT YET TRUE"; no ledger id.

### com-release-5 - The release-ordering and architecture protections are dormant: `requires_dashboard` and `arch` are not signed into any feed record
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:**
  - `feed/channel.json`: no record carries `requires_dashboard` or `arch`.
  - `tools/publish_latest.py:179-184,506-520`: kind extras are off unless `CCSYNC_EMIT_KIND_EXTRAS=1`, and the tool only prints a NOTE.
  - `docs/RELEASE.md` "Emission is opt-in".
  - `companion/src/ccsync_companion/config.py:174`: `REQUIRES_DASHBOARD = "0.7.23"`.
  - `.github/workflows/release-macos.yml:52`: `macos-latest` builds arm64 only.
- **What:** REL-4 (dashboard ordering) and REL-16 (arch) are "FIXED" in code. But the signing tools drop both fields until someone opts in, and nobody has, so customer dashboards see neither. Even when emitted, `REQUIRES_DASHBOARD` still says 0.7.23, although companions since 0.9.80 depend on dashboard 0.7.60 (per the `CLAUDE.md` account-page and report-optouts rules). There is no x86_64 or universal2 macOS build at all, and nothing anywhere states that Intel Macs are unsupported.
- **Scenario:** A post-production house with a 2019 Intel Mac Pro (common for Resolve) cannot run the arm64-only wizard. Once installed by hand, that Mac is offered the arm64 companion: it downloads it, fails to exec, rolls back, and retries forever (the REL-16 symptom). Separately, any customer whose dashboard lags is offered companions it cannot support.
- **Recommendation:**
  1. The fleet is past 0.9.55, so turn kind extras on permanently in `publish_latest`, `publish_feed` and `ship`, making it the default rather than an opt-in.
  2. Raise `REQUIRES_DASHBOARD` to the real minimum and add a test tying it to the newest dashboard-dependent feature.
  3. Either build a universal2/x86_64 macOS companion and wizard (a `macos-13` runner or `target_arch='universal2'`), or publish "Apple Silicon only, macOS N+, Windows 10/11 x64" as a support statement in the order form and the docs.
- **Known:** REL-4 / REL-16 (marked FIXED in KNOWN_BUGS but inactive on the feed).

### com-release-6 - The dashboard image bypasses the offline release key: any `v*` tag pushes an untested `:1` to every customer, through unpinned actions
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:**
  - `.github/workflows/image.yml:61-64,149-170`: a `v*` tag pushes `:<VERSION>` and moves `:1`. There is no `needs:` on CI, no pytest, and no `environment:` approval.
  - `.github/workflows/image.yml:256-258` and `docs/DOCKER.md:562`: `cosign verify --certificate-identity-regexp '.*'`.
  - All 29 `uses:` lines across `.github/workflows/*.yml` are tag-pinned. None is pinned to a commit SHA.
  - `dashboard/deploy/compose.appliance.yaml:88,147,291`: `:1`.
  - `docs/RELEASE_PATHWAYS.md` ("CI builds, this rig signs").
- **What:** Two gaps undercut the trust model:
  - **The image path.** The trust model says nothing that runs at a customer is trusted without the offline key. That holds for companion records and dashboard code bundles, but not for the image. The image is the most privileged artefact: it holds every site secret, the tree, the Syncthing and TrueNAS API keys, and it is the verifier `select_code_root` trusts. It is built and published by CI on a tag push, with no tests and no human signature, under a floating tag. The NAS's "Update" click pulls `:1` with no verification. The documented cosign check accepts any GitHub Actions identity, so it proves nothing.
  - **Companion builds.** The rig signs whatever a CI run produced, with tag-pinned third-party actions and no reproducible-build check. A compromised action or GitHub account therefore gets a rig-signed record too.
- **Scenario:** A stolen GitHub token, a compromised third-party action, or a careless tag push (for example on a branch) moves `:1`. Every customer who clicks Update in the NAS UI, or runs an auto-updater, then executes it with full dashboard privileges, and no offline key was ever involved.
- **Recommendation:**
  1. Gate `image.yml`'s tag path on green CI and on a GitHub environment with required reviewers.
  2. Pin every action to a commit SHA, with Dependabot keeping the pins updated.
  3. Have the vendor publish image *digests* in the signed channel (the `dashboard_image` field already exists: make the page compare the running digest to it), and tell customers to pin by digest.
  4. Fix the cosign example to the exact workflow identity (`--certificate-identity https://github.com/<org>/<repo>/.github/workflows/image.yml@refs/tags/v...`).
  5. Longer term, make `select_code_root`/run.sh refuse an image whose digest no signed channel names, and adopt reproducible PyInstaller builds (`SOURCE_DATE_EPOCH`) so the rig can rebuild and compare before signing.
- **Known:** none (server-tools-3 tightened workflow permissions but not this).

### com-release-7 - The release key that controls every customer is a plaintext seed on the daily-driver workstation, with no compromise plan
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:**
  - `tools/release_key.py:21-27` ("There is no passphrase").
  - `~/.ccsync-release/release.key`: a plaintext 32-byte seed on this rig, beside `android.keystore`.
  - `~/.ccsync-release/backup.json`: backup to `Q:\ccsync-release-key\release.key`, a medium not documented as offline.
  - `docs/RELEASE_PATHWAYS.md`: "anyone/anything on the base rig - Claude included".
  - `docs/RELEASE.md` rotation section (rotation only; no compromise or revocation procedure).
- **What:** One Ed25519 key signs every companion for every customer and every dashboard code bundle that customer dashboards execute. Its holder can run code on every editor machine and inside every customer's dashboard. It is not on hardware or an offline machine: it sits unencrypted on the base rig, which browses, syncs, and routinely runs AI agent sessions with bypass permissions. There is no revocation mechanism. A companion trusts its baked keys until it installs a build that drops one, and an attacker holding the key can sign builds that never drop it. No incident runbook exists for "the key leaked".
- **Scenario:** Malware, a malicious dependency in any repo opened on the rig, or a misdirected agent reads `release.key`. From then on the attacker can sign a companion that every customer's dashboard and every editor accepts. The vendor's only recovery is a hand reinstall of every machine at every customer, with no contractual or technical plan for it.
- **Recommendation:**
  1. Move the signing key to hardware: a YubiKey/HSM-backed Ed25519 key, or a dedicated offline signing laptop that only signs and is never used for anything else.
  2. At minimum, DPAPI- or age-encrypt it at rest, and keep agent sessions off the rig while it is mounted.
  3. Write a key-compromise runbook (rotate, recall, customer notification wording, reinstall path) and a key ceremony record covering who holds copies and where.
  4. Consider a second, cold "revocation/rotation" key baked into companions now, so a compromise can be answered over the air.
  5. Document the `Q:` backup medium in `docs/SECRETS.md`.
- **Known:** COMMERCIAL_READINESS item 4 said "decide keep/rotate before the first customer ship and BACK IT UP OFFLINE". The backup is recorded; the keep/rotate decision and custody are not.

### com-release-8 - No downgrade floor has ever been set, and the feed has no freshness check: any signed build, however old, can be made current fleet-wide
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `feed/channel.json` (all 12 records `min_version: "0.0.0"`); `tools/release_macos.sh:838` and `tools/build_onboard_macos.sh:507` (`CCSYNC_MIN_VERSION:-0.0.0`); `companion/src/ccsync_companion/upgrade.py:42-46,726` (floor only from records; "different, not newer"); `dashboard/src/ccsync_dashboard/release_feed.py:874` (`generated_at` stored, never compared).
- **What:** The monotonic floor exists in code, but the field floor is 0.0.0 on every machine because no record has ever asserted one. Any signed record still in a dashboard's packages table can be made current and pushed to every machine. That includes builds from before the loopback guard, LG-4 and the bug-hunt security fixes. The channel also carries no expiry or monotonic counter, so a replayed older (validly signed) channel is accepted. Recalls are persisted, which limits but does not remove this.
- **Scenario:** A customer admin, a stolen admin session, or a confused support call does "roll back to 0.9.0". Every editor reinstalls a build with since-fixed security bugs, with no warning that the target is below the vendor's security baseline.
- **Recommendation:**
  1. Before launch, publish a release with `--min-version` at the first build that contains the security fixes you rely on, and raise it with every security-relevant release.
  2. Default `CCSYNC_MIN_VERSION` in the CI workflows to the previous security baseline rather than 0.0.0.
  3. Make the dashboard refuse a channel whose `generated_at` is older than the last one it accepted (TUF-style freshness), and optionally add `expires`.
- **Known:** CR-52 (related; floor-above-version only).

### com-release-9 - Release continuity rests on one person, one rig and one GitHub login, with no security contact or supported-versions policy
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `docs/RELEASE_PATHWAYS.md`: pathway A is "Alex, at the terminal"; pathway B needs this rig's `gh auth` and the key file.
  - The dashboard bundle is a two-step on the rig only (`release-dashboard.yml` header).
  - No `SECURITY.md` anywhere in the repo.
  - `docs/legal/EULA.md:128-130`: "as described in your order or support plan", a document that does not exist.
- **What:** If the owner's rig dies, or the owner is unavailable, no one can ship a security fix to any customer: there is no second signer, no written disaster-recovery procedure, and no escrow. Buyers will also ask for:
  - a vulnerability-disclosure contact and process;
  - how long a release is supported and how fast critical fixes ship;
  - what happens to their updates if the vendor stops trading (source and key escrow).
- **Scenario:** A critical CVE in a bundled dependency (yt-dlp, rclone, FastAPI) lands while the owner is away. Customers have no channel to report it and no patch arrives. An enterprise buyer's security questionnaire fails on "vulnerability disclosure policy" and "business continuity".
- **Recommendation:** **The owner and counsel** to produce:
  - a `SECURITY.md` / security@ address and disclosure policy;
  - a support and maintenance schedule (supported versions, critical-fix SLA) referenced by the order form;
  - a written release DR runbook covering a second trusted person, sealed key copy and rebuilding the rig from scratch;
  - optionally, a source and key escrow agreement for larger customers.
- **Known:** overlaps com-licensing-billing-5 (support terms), which covers the paperwork side; this finding covers the release mechanics.

### com-release-10 - No managed-deployment path: per-user self-replacing exe, PowerShell `-ExecutionPolicy Bypass`, no MSI/pkg, no silent install
- **Severity:** medium
- **Confidence:** CONFIRMED (the absence); PLAUSIBLE (the AppLocker/WDAC impact at a given customer)
- **Where:** `installer/windows_bootstrap.ps1:929-932`; `docs/EDITOR_SETUP.md:64` (`powershell -ExecutionPolicy Bypass -File .\windows_bootstrap.ps1 ...`); the companion installs to `%LOCALAPPDATA%\ccsync\bin` and self-replaces; there is no `.msi`/`.pkg`/MDM/Intune/Jamf reference anywhere in `installer/`, `onboarding/` or `docs/`.
- **What:** Studios with IT (the buyers most likely to pay) deploy software through Intune, Jamf or GPO. They need a signed MSI/pkg with silent switches, a per-machine install location, and a way to pre-seed the site URL and token. AppLocker/WDAC default rules block executables in user-writable paths, and a self-replacing unsigned exe there is exactly what those rules exist to stop.
- **Scenario:** A 20-seat customer's IT department refuses to let editors run `onboard.exe` or a Bypass PowerShell command, and has nothing it can push centrally. The sale stalls or turns into per-machine hand installs by the vendor.
- **Recommendation:** Decide (owner) whether managed IT customers are a launch target. If they are, produce a signed MSI (WiX) and a notarised `.pkg` with silent and unattended parameters (site URL, enrolment token) and a documented per-machine mode. If not, state "unmanaged machines only" in the order form.
- **Known:** none.

### com-release-11 - yt-dlp nightly is fetched and executed at runtime, outside the vendor's release and signing process
- **Severity:** medium
- **Confidence:** CONFIRMED (design); gated by the `youtube_download` feature, off in the vendor build
- **Where:** `dashboard/deploy/run.sh:353-405` (`ytdlweb.ytdlp_nightly install` at boot, default on when ytdl is on); KNOWN_BUGS CR-361 (`github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest`, verified only against that release's own `SHA2-256SUMS`; companion side too).
- **What:** For sites with YouTube download enabled, a third-party nightly build changes daily and is installed onto customer dashboards and editor machines. It is checked only against a checksum file from the same host: integrity, not authenticity, and yt-dlp's GPG-signed `SHA2-256SUMS.sig` is not checked. The vendor has not reviewed or tested that code, and it never passes through the offline key.
- **Scenario:** A compromised yt-dlp nightly-builds release, or simply a broken nightly, runs on every opted-in customer's server and editor machines within a day, and the vendor's support desk inherits the outage. A security reviewer will flag it as "auto-updating unsigned code from the internet".
- **Recommendation:** Verify yt-dlp's published GPG signature on `SHA2-256SUMS` against a pinned yt-dlp public key. Alternatively, have the vendor re-publish a vetted yt-dlp on the signed feed as an `artefacts` entry. Document in the YouTube feature notice that this component updates itself from a third party.
- **Known:** CR-361 (BUILT in repo, unshipped, owner decision 2026-10-05).

### com-release-12 - Vendor-side rollout has one `stable` channel and no customer cohorts; the image `:1` moves for everyone at once
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `docs/RELEASE_FEED.md` §2.1 (`channel` "not consulted for anything"); `image.yml` `:1`; `release_feed.py` policy `manual|stage|current` per site.
- **What:** Per-site rollout tooling exists: policy, the soak gate, recalls and a per-machine push. But the vendor cannot stage a release to "customer A first, others next week", there is no beta channel for a design-partner customer, and every `v*` tag moves `:1` for all customers at once.
- **Scenario:** A release that only breaks Synology reaches every Synology customer on `policy=current`, or every customer who clicks Update in their NAS UI the same day.
- **Recommendation:** Add a `beta` channel URL (a second tag on the release repo) and per-customer guidance on which policy to run. Pin customers to `:<version>` or a digest named in the signed channel instead of `:1` (see com-release-6).
- **Known:** REL-1 (site soak, fixed); vendor-level cohorts not tracked.

### com-release-13 - The Mac install path has never been signed off, and the Mac wizard lags the Windows one
- **Severity:** low
- **Confidence:** PLAUSIBLE
- **Where:** `installer/MACOS_FIRST_RUN.md` (every box A7-H unchecked; file untouched since 2026-08-17); KNOWN_BUGS backlog "macOS runtime validation backlog"; `feed/channel.json` (`onboard/macos` 1.0.44 vs `onboard/windows` 1.0.46).
- **What:** Mac editors exist in the fleet, so parts of this have run informally. But the scripted first-run drill (install, Resolve mapping, SSD, self-upgrade, uninstall) has no recorded pass, and the Mac wizard on the feed is two installer versions behind Windows.
- **Scenario:** A first Mac-only customer hits an install-time defect the Windows path no longer has, with no recorded baseline for support to compare against.
- **Recommendation:** Run and record `MACOS_FIRST_RUN.md` on a clean Mac against the signed, notarised build (after com-release-1/2). Publish `onboard/macos` at parity before launch.
- **Known:** KNOWN_BUGS backlog "macOS runtime validation backlog" (open).

### Note (not a separate finding)
`docs/RELEASE.md` "What to buy" says EV "starts with SmartScreen reputation from day one". Microsoft removed that EV fast-path in 2024, so EV and OV now earn reputation the same way. The purchase decision should rest on key custody and CI fit (com-release-2), not on reputation. Correct the doc when the certificate decision is made.
