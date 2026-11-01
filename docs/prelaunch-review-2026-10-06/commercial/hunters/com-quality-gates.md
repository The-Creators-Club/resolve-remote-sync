# Pre-launch commercial review 2026-10-06: engineering quality gates (`com-quality-gates`)

Lens: the engineering gates a commercial launch needs. HEAD `08b40eb` plus the
uncommitted working tree (30 modified files, 2 untracked).

**Read:** `.github/workflows/{ci,image,release-windows,release-macos,release-dashboard}.yml`,
`tools/{ship.ps1,publish_latest.py,publish_feed.py,build_dashboard_bundle.py,release_macos.sh}`
(the gate and refusal paths), the local vendor feed `feed/channel.json` (what a
feed customer is offered today), `docs/{COMMERCIAL_READINESS,RELEASE,CI,MODULAR_UPDATES,APPLIANCE_INSTALL}.md`,
`installer/MACOS_FIRST_RUN.md`, the bug-hunt tallies from 2026-09-03 to 2026-09-24,
and the whole `KNOWN_BUGS.md` structure: every `##`/`###` heading, every
OPEN/PARTLY/DEFERRED/OWED entry, plus the CR-66 deferred list and the Carryover.
I also read the uncommitted diff (companion 0.9.85, alert-kind muting, the b-roll
tree depth).

**Probed (read-only):** I counted tests, skip sites and sleeps per suite (about 15,800
test functions). I ran the new or touched non-UI test files of the working tree
(`dashboard/tests/test_alert_kind_selection.py` 13 passed; companion
`test_fixer/test_resolve_bridge/test_telemetry_disclosure` 257 passed;
`broll/web/tests/test_collection_filter.py` 37 passed;
`tools/tests/test_test_map.py` 46 passed). I parsed the feed's package records
and checked git tags against them.

**Not done:** No full suite runs (forbidden). No GitHub state: CI run history,
branch protection and secrets were not checked. Nothing live. I did not run the
Tk-touching companion tests (popup, settings_window, tray). I did not review the
Timeline Cards repo beyond checking whether it has CI.

---

### com-quality-gates-1 - What a new customer gets today is the 11 September release: a draft EULA, no server-side privacy switches, and a companion newer than its dashboard
- **Severity:** critical
- **Confidence:** CONFIRMED
- **Where:** `feed/channel.json` (`current`), `dashboard/deploy/compose.appliance.yaml:88,147,291` (`:1`), `.github/workflows/image.yml` (tag trigger), `git tag` (last `v0.7.44`), `git show v0.7.44:docs/legal/EULA.md`
- **What:** The signed vendor channel's `current` set is `dashboard/linux 0.7.44` (published 2026-09-11), `companion 0.9.82` (0.9.83 and 0.9.84 are published but staged), `onboard/windows 1.0.46` and `onboard/macos 1.0.44`. Its `dashboard_image` pin is tag `0.7.24`. The appliance compose pulls `ghcr.io/the-creators-club/ccsync:1`, and image.yml only moves `:1` on a `v*` tag. The newest tag is `v0.7.44`. Meanwhile the studio runs dashboard 0.7.73. Everything from CR-282 to CR-361 is missing on the customer path. That includes the legal-gap features (dashboard 0.7.61, schema v59), the final EULA 1.1 (`b9503c9`, 2026-09-25) and the CC Terminal UI. At v0.7.44, `docs/legal/EULA.md` opens with `DRAFT FOR COUNSEL — NOT LEGAL ADVICE, NOT YET EXECUTABLE`. That file is what `setup_engine._find_eula` serves from the image and the bundle.
- **Scenario:** A first customer follows APPLIANCE_INSTALL today. Their setup wizard shows editors a EULA marked as a draft for counsel. Their dashboard (0.7.44) cannot strip the LG-1 withheld report fields. Their editors receive companion 0.9.82, which includes the 0.9.80 and 0.9.81 report sections. CLAUDE.md says both of those need the dashboard first ("an old dashboard banners the new report section on every report"). So every machine raises the SYS-3 "REPORT SECTION(S) IGNORED" banner on the first day.
- **Recommendation:** Treat a customer release as its own gated event, separate from the studio's OTA flow. Pick a release candidate commit and tag it `vX.Y.Z` so image.yml builds `:VERSION` and `:1`. Publish the dashboard bundle to the feed first, then the companion and both installers from the same commit, then move `current` on all of them. Before any sale, check the result with a fresh install on a clean NAS (see com-quality-gates-7). The owner has to decide whether `:1` keeps following each tag or whether customers pin exact versions.
- **Known:** Partly, as CR-66 `release-pipeline-9` (the mutable `:1` tag, "tagged exactly once", needs a tagging policy), which is still OPEN. The feed lag itself is not recorded anywhere.

### com-quality-gates-2 - The feed's version-ordering and CPU-architecture checks are switched off, and the companion's minimum dashboard version is stale
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/config.py:174` (`REQUIRES_DASHBOARD = "0.7.23"`); `tools/publish_latest.py:505-525`; `tools/sign_release.py` (`--emit-kind-extras` opt-in); `docs/RELEASE.md` "The overlap cost of the two signed fields"; `tools/release_macos.sh:683-698` (arm64 only); `companion/src/ccsync_companion/upgrade.py:1518` (arch deliberately not checked client-side); `feed/channel.json` (no record carries `requires_dashboard`/`arch`; every `min_version` is `0.0.0`)
- **What:** The signed `requires_dashboard` and `arch` fields are dropped unless `CCSYNC_EMIT_KIND_EXTRAS=1`. No record in the feed carries either one. The value they would carry is also wrong: `REQUIRES_DASHBOARD` is 0.7.23, while CLAUDE.md lists companion features since then that need a newer dashboard deployed first (account page 0.7.60, legal-gap 0.7.61, the 0.9.54 upload-only tick). The Mac build is arm64-only, and the arch field is the only thing that would stop an Intel Mac being offered it. The downgrade floor is 0.0.0 on every record (CR-66 `release-pipeline-8`).
- **Scenario:** A customer's dashboard is older than the companion it publishes. It offers that companion anyway, and the "deploy the dashboard first" rules in CLAUDE.md go unenforced for customers. A customer editor on an Intel MacBook is offered an arm64 binary. It cannot execute, and the editor gets REL-8 `exec-failed` on every attempt. There is also no floor stopping a re-offer of a build with a known data-loss bug.
- **Recommendation:** The whole fleet has been on 0.9.74 or newer since 2026-09-17, so the overlap precondition ("every machine 0.9.55 or newer") is met. Turn on `CCSYNC_EMIT_KIND_EXTRAS=1` in the publishing environment. Add a test that fails when a companion change carries a "deploy the dashboard first" note but `REQUIRES_DASHBOARD` was not raised, or simply raise it to the dashboard the release ships with. Either state "Apple silicon only" in INSTALL.md and the EULA's system requirements, or build `universal2`. Make `min_version` a tracked constant that is raised whenever a data-loss fix ships.
- **Known:** CR-66 `release-pipeline-8` (OPEN). REL-4/REL-16 shipped the mechanism and it is still inert. CR-280 / CR-283U cover the Mac CA bundle separately.

### com-quality-gates-3 - Dashboard releases need no green test run: the OTA bundle and the `:1` image publish without one, and 0.7.71-0.7.73 shipped while CI was red
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `tools/build_dashboard_bundle.py:279-294` (the manifest has no `tests_run` or `gate`); `tools/publish_feed.py:965-975` (refuses only `tests_run is False`, and a missing key is not False); `.github/workflows/release-dashboard.yml` (builds without running pytest); `.github/workflows/image.yml` (push and tag triggers, no `needs:`, no dependency on CI, no `docker run` boot check); `docs/MODULAR_UPDATES.md` section 1 ("The full gate is red on `main` right now"), section A.7 (planned, not built); `ci.yml` (no `schedule:`); `tools/ship.ps1` header (step 1 deploys the dashboard before step 2a runs the dashboard suite)
- **What:** The companion path is gated: `publish_latest` takes only a successful release workflow on `main`, which runs the suites with `CCSYNC_REQUIRE_RCLONE`/`FFMPEG`. The dashboard path is not. A bundle built from any clean commit publishes to every customer with no evidence that a test ran. Pushing a `v*` tag pushes `:VERSION` and the floating `:1` to GHCR in parallel with CI and regardless of its result. The image is never started before it is signed and pushed. MODULAR_UPDATES records that the Linux CI job failed two dashboard tests from 0.7.72 to 0.7.73 while both were live. Its own mitigations ("a nightly full gate", "`build_dashboard_bundle.py` refuses a commit with no full-green run") are design text only. In bind-mount mode, `ship.cmd` deploys the dashboard (step 1) before `release.ps1` runs the dashboard suite (step 2a).
- **Scenario:** A dashboard regression that the Linux suite would catch is bundled, published with `--make-current`, and taken unattended by every site on `[releases] policy = current`. A broken `run.sh` or Dockerfile change is pushed as `:1` and pulled by the next appliance update, and nothing ever started that container.
- **Recommendation:** Build A.7 before launch. Have `ci.yml` emit a signed or recorded `gate: full` for the commit. Make `build_dashboard_bundle.py --feed` and `publish_feed.py --kind dashboard` refuse a commit without a full-green CI run on `main`, as `publish_latest` already does for the companion. Make image.yml's tag path `needs:` a CI run on the same SHA and add a `docker run` + `/api/v1/health` smoke before push. Add the nightly `schedule:`. Reorder `ship.ps1` so no deploy happens before the suite that guards it.
- **Known:** CR-66 `release-pipeline-2` (reconciling the two publish paths, deferred). MODULAR_UPDATES M0/A.7 is not recorded as a defect.

### com-quality-gates-4 - Each bug hunt keeps finding 9-17 high-severity defects, and the largest changes since the last hunt have not been hunted
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `docs/bug-hunt-2026-09-03.md` (9 high), `-09-11.md` (14 raw high), `-09-11b.md` (14 high in the fix pass itself), `-09-18.md` (17 raw / 10 distinct), `-09-18b.md` (14 raw / 12 distinct, again in the fix pass), `-09-24.md` (16 raw, 11 confirmed); commits since 2026-09-25: `8b349d4` "CC Terminal UI port ... built fast, no adversarial stage yet", `a1a54da`, `4c1b52f` (legal-gap features), CR-346..CR-361
- **What:** Every weekly hunt since 2026-09-03 has confirmed about 10 or more highs. The two hunts aimed at the previous fix pass each found 12-14 highs in the fixes themselves, so the fix passes introduce defects at roughly the rate they remove them. Since the 2026-09-24 hunt, three big changes landed and none has been through a hunt: the whole UI was replaced (CLAUDE.md: "phase 8 built early by the owner's decision, no soak"), the legal-gap features added schema v58/v59, and twelve CR fixes followed. Nothing defines a release exit criterion.
- **Scenario:** The first paying customer gets a build whose expected count of undiscovered high-severity defects, going by the last six measurements, is about ten. Some of the highs found so far were data-loss shapes: CR-282 "a deletion that came back", CR-287/288 file-move corrections, `bug-ops-1` publish_db rollback renaming a WAL over the live index.
- **Recommendation:** Freeze a release candidate (feature freeze on the RC branch, fixes only). Set written exit criteria. For example: one full hunt on the frozen RC confirms zero highs; the hunt of the RC's own fix pass confirms zero highs; the RC soaks for N days on the studio fleet with no new CR of medium or worse in sync, delete or upgrade paths. Track the high-severity discovery rate per hunt as a launch metric.
- **Known:** Not recorded as a gate. The individual hunts are archived.

### com-quality-gates-5 - No code review or change approval: every commit goes straight to `main` from one account, with an AI co-author on every one
- **Severity:** high
- **Confidence:** CONFIRMED (branch protection itself not checked: no live GitHub calls)
- **Where:** `git log --since=2026-09-01`: 116 commits, all authored by one account, all carrying a `Co-Authored-By: Claude …` trailer, 2 merge commits, no PR flow; `tools/publish_latest.py` (the go/no-go is the operator alone); memory note "Alex is non-technical"
- **What:** The code that `[releases] policy = current` and `auto_update` push unattended into customer fleets is written by AI agents and committed directly to `main`. No second human reviews it, there is no PR record, and no required-check gate is visible in the repo. Supplier security questionnaires (SOC 2 CC8.1, ISO 27001 A.8.32, typical enterprise vendor questionnaires) ask for exactly this: change approval, segregation of duties, and evidence that tests passed before release.
- **Scenario:** A buyer's security reviewer asks "who reviews and approves a change before it reaches our fleet, and show me the record". Today the honest answer is "nobody but the author, and no record". One bad commit to the lane-B delete path or `upgrade.py` reaches every customer on `policy = current` within a day.
- **Recommendation:** Protect `main`: require a PR, required status checks (all three CI jobs), and no direct pushes. Require a named human approver for changes under the sync delete, upgrade/signing and auth paths (a CODEOWNERS file). The owner should decide who that reviewer is, perhaps a contracted engineer if the owner cannot review code. Write a one-page SDLC statement for questionnaires.
- **Known:** Not recorded.

### com-quality-gates-6 - Every published binary is unsigned, and Mac builds are not notarized
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `feed/channel.json`: every record has `signed_binary: false`; `.github/workflows/release-macos.yml:20-26` (ad-hoc signing; `CCSYNC_APPLE_DEV_ID` reserved but unused); `docs/RELEASE.md` "Code signing", "Operator TODO"; KNOWN_BUGS Carryover "macOS code-signing (was item 16)"
- **What:** No companion, onboard or dashboard artefact on the feed is Authenticode-signed or Developer ID signed and notarized. Ship runs with `-AllowUnsignedBinary`. The release signature (Ed25519) protects the update channel but not the first download or OS trust.
- **Scenario:** A new customer's editor downloads `ccsync-onboard-1.0.46.exe`. SmartScreen shows "Windows protected your PC", and corporate AppLocker or Defender for Endpoint policies commonly block it outright. On macOS 15 an un-notarized app downloaded in a browser cannot be opened without going through System Settings > Privacy & Security. Every Mac self-upgrade resets the TCC / Full Disk Access grant (Carryover item 16), so a Mac editor's sync silently loses access after each update.
- **Recommendation:** The owner (as the legal entity Cablewrap Creative Ltd.) buys an OV or EV Authenticode certificate and an Apple Developer Program membership with a Developer ID Application certificate. Set the env vars and secrets RELEASE.md names. Make `-AllowUnsignedBinary` and unsigned publishes refuse for the vendor feed, and keep the override for the studio only.
- **Known:** CR-6 ("certificates NOT bought", OPEN), COMMERCIAL_READINESS item 4, Carryover item 16.

### com-quality-gates-7 - A new-customer install has never been run end to end, and there is no staging site: the studio's own fleet is the only integration test
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `docs/APPLIANCE_INSTALL.md:1-17` ("DRAFT ... until somebody who is not the author has run this end to end", WP B Serve "NOT YET TRUE", the wizard "CHECKS ... does not yet DO"); KNOWN_BUGS WPK-3 ("no `docker build`, no `docker run`, and no NAS" for the OTA code path); `docs/CI.md` "What CI cannot cover"; `dashboard/tests/test_smoke_boot.py` (TestClient, not the container)
- **What:** Nothing automated or recorded shows a clean NAS going from nothing to a working fleet with the vendor artefacts: compose, image, setup wizard, editor onboard on Windows and Mac, first sync both ways, first OTA, first rollback. CI never starts the container or the sftp/Syncthing sidecars. Each fix is integration-tested only by deploying it to the studio's production fleet.
- **Scenario:** The first customer is also the first appliance install, on a NAS model or DSM/SCALE version nobody has tried. A failure in the wizard, the bind-mount ownership step, Serve, or the first lane B pass happens at the customer, with the vendor diagnosing over email.
- **Recommendation:** Build a staging reference site, ideally one TrueNAS SCALE and one Synology DSM with a Windows and a Mac editor VM, used only for release candidates. Script an install acceptance run (a checklist, or automated where possible) and record its result per RC. Add a CI job that runs `docker compose -f compose.appliance.yaml up` with the built image, waits for health, completes `/setup` headless, and runs one report from a stub companion.
- **Known:** WPK-3 (OPEN), APPLIANCE_INSTALL "NOT YET TRUE" sections, COMMERCIAL_READINESS item 16.

### com-quality-gates-8 - The rollout soak is 30 minutes on one machine and counts only crashes; customers have no staged rollout
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/db.py:4691` (`DEFAULT_SOAK_MINUTES = 30`); `dashboard/src/ccsync_dashboard/package_store.py:163-169`; `docs/RELEASE.md:929-940`; `tools/publish_latest.py:640-655` and RELEASE_PATHWAYS ("always --make-current")
- **What:** The only soak evidence is one machine reporting the version for 30 minutes with `crashes.count == 0`. It ignores lane errors, the breaker, stalled lanes, refused reports and alerts. On the vendor side, the go/no-go is "a green release workflow". Nothing stages a build through rings (studio for N days, then opt-in early customers, then everyone). For a sync product most damaging defects (CR-91 wedged lanes, CR-282 resurrected deletions, CR-347 one big upload starving the rest) show up only after hours, or on a specific shape of tree.
- **Scenario:** A build that does not crash but stops lane B on a common tree shape soaks for 30 minutes on the vendor's canary, is moved to `current`, and reaches every customer on `policy = current` within a day.
- **Recommendation:** The vendor feed needs its own canary policy: a minimum of days on the studio fleet, with soak criteria that include `lane_error`, `lane_stalled`, `breaker_tripped`, `report_refused`, `upgrade_reverted` and the crash count, across at least one Windows and one Mac machine. Add an "early" channel customers can opt into. Raise the default soak for customer sites. Publish release notes and a known-issues list with each `current` move.
- **Known:** REL-1 built the mechanism. The weakness of its criteria is not recorded.

### com-quality-gates-9 - The Mac side lags Windows: an older installer, unverified fixes, an unrun acceptance checklist, and no stated supported macOS versions
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `feed/channel.json` (`onboard/macos` current 1.0.44; 1.0.45/1.0.46 never published for macOS; `git diff 99b6d7c 35cb10c -- onboarding/` adds the "4b. Privacy" LG-1 page and +3,200 lines); KNOWN_BUGS CR-280 / CR-283U ("FIXED in repo, UNVERIFIED"; `certifi` still not in `companion/requirements.lock`); Carryover "macOS runtime validation backlog" (`installer/MACOS_FIRST_RUN.md` §A7–H unrun, MAC-12 wedged FSEvents); `tools/release_macos.sh:683-698` (arm64 only); no `LSMinimumSystemVersion` / `MACOSX_DEPLOYMENT_TARGET` anywhere; builds on the floating `macos-latest`/`windows-latest` images
- **What:** A Mac editor onboarded today gets the 1.0.44 wizard, which has no privacy page for the four reporting switches the legal documents describe. The macOS HTTPS CA-bundle fix has never run in a frozen Mac build. `MACOS_FIRST_RUN.md` has no recorded pass. The studio has one Mac (leso), so Mac soak and verification wait on one person. Nothing states a minimum macOS or Windows version. The build host image floats, so the binary's real minimum OS can change between releases without anyone noticing.
- **Scenario:** A customer whose editors are mostly on Macs (common in video) onboards with a wizard that skips the privacy choices their contract promises. Local YouTube downloads and sidecar installs fail certificate verification (CR-280) on every Mac. Editors on macOS 13 find the new build will not launch after a runner image bump.
- **Recommendation:** Publish onboard/macos 1.0.46 or later from the same RC. Add `certifi` to the companion lock (CR-283U's owed item) and verify CR-280 on a frozen build. Run and record `MACOS_FIRST_RUN.md` against the RC. Pin the build runner images (`macos-14`, `windows-2022`) and set `LSMinimumSystemVersion` and the deployment target. Publish a supported-platforms matrix (macOS and Windows versions, Apple silicon only or not, Resolve Studio versions) in INSTALL.md and the EULA order form.
- **Known:** CR-280/CR-283U (fix unverified), Carryover macOS backlog (OPEN). The onboard/macos lag and the OS matrix are not recorded.

### com-quality-gates-10 - The Linux CI job runs about 25 of its 30 allowed minutes, and no test has its own timeout
- **Severity:** medium
- **Confidence:** CONFIRMED (timings from `docs/MODULAR_UPDATES.md` section 1)
- **Where:** `.github/workflows/ci.yml` (`linux: timeout-minutes: 30` runs dashboard, server, broll/web, music/web, ytdl/web, broll/indexer, music/indexer, tools and the two gates serially; the windows and macos jobs also allow 30); MODULAR_UPDATES ("dashboard suite alone is 5,973 tests in 20 min ... whole CI run is about 25 min"); no `pytest-timeout` in any lock or config; companion tests carry 109 `time.sleep(` and 78 thread spawns, the dashboard 29 and 12
- **What:** The suites grow by hundreds of tests per fix pass, so the Linux job will exceed its timeout. A timed-out job reads as cancelled or failed, the same as a hang. Without per-test timeouts, one wedged thread or stray Tk dialog (the macOS job comment says "a stray dialog HANGS") burns the whole budget and names no test. The last red run on `main` was a wall-clock race (`test_a_cancelled_job_does_not_come_back_when_the_lease_expires`), the flakiness family that sleeps and real threads produce.
- **Scenario:** In a release week the Linux job starts timing out at 30 minutes. The operator re-runs until it is green, or ships from a red gate as happened with 0.7.72 and 0.7.73.
- **Recommendation:** Add `pytest-timeout` (for example `--timeout=120 --timeout-method=thread`) to every suite. Split the Linux job into a matrix by suite. Record `--durations` in CI and fail on a budget. Quarantine wall-clock tests behind a fake clock.
- **Known:** Not recorded (M0 measured it but set no budget for the full gate).

### com-quality-gates-11 - Tests that skip when a tool is missing still leave CI green: the CLAP gate runs on one machine, and CI does not insist on rclone or ffmpeg
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `.github/workflows/ci.yml` (ffmpeg steps are `continue-on-error: true`; neither `CCSYNC_REQUIRE_RCLONE` nor `CCSYNC_REQUIRE_FFMPEG` is set in `ci.yml`, though both release workflows set them); `music/web/tests/test_text_encoder.py:74-79` (skips without the artefact or torch); `music/web/tests/*` and `broll/web` (`node`-dependent tests skip); KNOWN_BUGS CR-65 ("The CLAP artefact gate itself still runs on exactly one machine in the world"); about 330 skip sites across the suites
- **What:** pytest exits 0 on a skip, and `ci.yml` neither forces the binaries nor sets a skip budget. In `ci.yml`, a failed ffmpeg install silently turns the media-job argv tests, which pin Timeline Cards' recipes, into skips. The CLAP text-encoder and search-quality gate, which decides whether music search works, never runs in CI. `run_all_tests.ps1` prints a skip footer, but CI does not.
- **Scenario:** A change breaks the CLAP query embedding or the proxy-480p argv. CI is green because those tests skipped, and `publish_latest` treats the commit as releasable.
- **Recommendation:** Set `CCSYNC_REQUIRE_RCLONE=1` and `CCSYNC_REQUIRE_FFMPEG=1` in `ci.yml`, and require `node`. Record the skip count per suite in the junit artefacts and fail on growth over a committed baseline. Make a decision on the CLAP artefact: either check in a small fixture artefact, or run the gate on a scheduled self-hosted job with recorded results.
- **Known:** CR-65 (PARTLY FIXED; the CLAP gate is OPEN).

### com-quality-gates-12 - `KNOWN_BUGS.md` cannot tell a buyer or support desk what is actually open
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `KNOWN_BUGS.md` (31,993 lines; 194 `##`/`###` headings still say unshipped, unbuilt, not deployed or next ship; 515 mentions of "owed"; 22 "UNVERIFIED"); examples of stale status: WPK-3 (image mode has been live since 0.6.1), CR-10 "NOT YET APPLIED to either NAS", CR-95 "NOT YET SHIPPED", Carryover "Mac builds owed"; entries out of order (CR-357/CR-358 filed after CR-359 and the Carryover in the working tree)
- **What:** The file says it is "the ledger of what is STILL open", but its status lives in free-text headings that are never updated after a ship. There is no severity, no fixed-in version, no shipped-in version, no "verified live" field, and no index. The only way to answer "is CR-x fixed in what customers run" is to read the entry and cross-check commits and the feed. Combined with com-quality-gates-1, the honest answer is often "fixed in repo, not in the feed".
- **Scenario:** A customer reports a symptom. Support cannot tell whether it is a known defect, whether a fix exists, and which version carries it. A due-diligence reviewer asks for the open-defect list by severity and gets a 32k-line narrative.
- **Recommendation:** Move to a structured tracker (GitHub Issues with severity, component and status labels plus milestones per release) or add a generated table (id, severity, status, fixed-in, shipped-in feed version, verified-live) that CI checks against the narrative. Before launch, run a one-time triage that closes or re-states every entry still marked "unshipped". Publish customer-facing release notes and a known-issues page per `current` move.
- **Known:** Not recorded.

### com-quality-gates-13 - Ledger items still OPEN that matter for launch
- **Severity:** high
- **Confidence:** CONFIRMED (each re-checked in code where it is code)
- **Where:** `KNOWN_BUGS.md` CR-66, CR-86, CR-91/CR-279, CR-333, CR-62, CR-65, CR-280, CR-137, CR-234, CR-294, CR-299C, CR-70, R16, Carryover; `dashboard/src/ccsync_dashboard/settings.py:806` (shared fleet token on by default); `dashboard/src/ccsync_dashboard/nas/truenas.py:54-60` (NAS REST TLS verify defaults False); `companion/src/ccsync_companion/` (no `known_hosts` anywhere, so the editor lanes verify no SFTP host key)
- **What:** These are still open after reading the whole ledger:
  - **Sync safety and data:**
    - `sync-safety-1`: lane A has no upload ledger, so a hand-moved file comes back. Only the dashboard's move button avoids this (CR-87).
    - CR-279 queueing half and CR-91: one long lane A pass holds every other project behind it. This is a design decision, still open.
    - CR-333: a blocked move's target recreated by another writer leaves the project blocked for good.
    - Carryover: the proxy generator's live-attach proof is "still the SHIP-BLOCKER for the editor proxy rollout".
    - Carryover: a one-time AppleDouble sweep is owed.
    - CR-234: the de-dupe in `app.py` is OWED.
    - CR-294: the b-roll insert during a container outage is PARTLY fixed.
  - **Trust:**
    - `trust-model-1` + CR-86: identity tokens never expire and cannot be revoked. `DASH_SHARED_REPORT_TOKEN_ENABLED` defaults ON, so a departed editor's credential never ages out.
    - `trust-model-4`: editor rclone lanes pin no NAS host key.
    - `trust-model-8`: dashboard to TrueNAS REST uses `verify=False` by default.
    - `trust-model-6`: one secret underwrites six trust relationships.
    - `trust-model-9`: no CSP.
    - CR-299C: the Cards idle release is PARTLY fixed.
  - **Release:**
    - `release-pipeline-8`: the downgrade floor is never raised.
    - `release-pipeline-9`: the mutable `:1` tag.
    - `release-pipeline-2`: two publish paths.
    - WPK-4: the dashboard has no downgrade floor.
  - **Data model:** `data-model-8`: `canonical_prefix`/`tree_name` can be edited live but are install-time constants, so an edit breaks the fleet.
  - **Platform:**
    - CR-280: unverified on a Mac.
    - CR-65: the CLAP gate.
    - CR-137: three Timeline Cards suites red; Cards has no CI at all (see com-quality-gates-15).
    - MAC-12: FSEvents wedge.
  - **UX:**
    - CR-70: tray menu opens late.
    - CR-283G: "CCSync"/"CC Sync" spelling, an owner decision.
    - R16: eight deliberately unfixed 08-14 findings.
- **Scenario:** Each item is a support ticket or an incident shape a first customer can hit. The trust items are what a security review flags first. `data-model-8` is a fleet-wide outage caused by one admin edit.
- **Recommendation:** For each item, the owner records a launch decision: fix before launch, document as a known limitation in customer docs, or accept with a reason. Minimum before the first sale: turn the shared fleet token off by default for new sites and build revocable identity tokens (`trust-model-1`); pin NAS host keys on the editor lanes (`trust-model-4`); default `DASH_NAS_VERIFY_SSL` to verify with a fingerprint option (`trust-model-8`); make `canonical_prefix`/`tree_name` read-only once a machine exists (`data-model-8`); run the proxy live-attach proof or disable editor proxy generation in the vendor build.
- **Known:** All of the listed ids. All are OPEN or PARTLY FIXED as of the working tree.

### com-quality-gates-14 - About 1,050 lines of live-incident fixes have sat uncommitted for six days, with the version numbers out of step
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `git status` (30 modified, 2 untracked); `companion/src/ccsync_companion/config.py:156` and `companion/pyproject.toml` bumped to 0.9.85; `dashboard/src/ccsync_dashboard/{alerts,api,ui}.py` + `templates/partials/admin_alerts.html` changed with `dashboard/__init__.py` still `VERSION = "0.7.73"` (the live version); `KNOWN_BUGS.md` CR-356/357/358 "(unbuilt)"; untracked `dashboard/tests/test_alert_kind_selection.py`, `docs/ZERO_DOWNTIME_DEPLOY.md`
- **What:** The fixes for three incidents from 2026-09-30 (CR-356: ruskin's licensed music never reached the server; CR-357; CR-358: FIX ALL copying the wrong project's music) exist only in this working copy. The dashboard alert-muting feature changes shipped code without a version bump, so a bundle built from it would carry live 0.7.73's number with different bytes. `publish_feed` refuses that, which costs a re-roll but means nothing slips through. No record shows the gate ran on this tree. My targeted runs of the touched non-UI files passed: 13 + 257 + 37 + 46.
- **Scenario:** The base rig's disk fails, or someone runs a `git checkout --` (CLAUDE.md recommends one for CRLF repair), and the CR-356 fix is lost while ruskin's 30 tracks are still offline. Or the tree is committed as one blob and released without the full gate.
- **Recommendation:** Commit now in separate reviewable units: companion 0.9.85 (CR-356/357/358), the dashboard alert-muting feature with a VERSION bump, the b-roll depth change. Run the full gate once centrally. Put KNOWN_BUGS entries in numeric order. As a launch rule: nothing ships from, or stays more than a day in, an uncommitted tree.
- **Known:** CR-356/357/358 (FIXED in repo, unbuilt). The uncommitted state itself is not recorded.

### com-quality-gates-15 - No decision on whether Timeline Cards is part of the product, and it is outside every gate (no CI, no versioned release, handshake never run live)
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `E:\Projects\Editing\Resolve\MulticamPipeline` has no `.github/workflows`; CLAUDE.md "The release/reload handshake has still NEVER RUN LIVE"; KNOWN_BUGS CR-137 ("three Timeline Cards suites are red"), memory "Cards iteration = `run_all.py --fast`, never the full gate"; `dashboard/src/ccsync_dashboard/cards*.py`, `companion/src/ccsync_companion/timeline_cards_role.py`, `jobs_media.py` (reproduces the other repo's ffmpeg argv verbatim)
- **What:** Timeline Cards is mounted in-process in the dashboard, schedules fleet media jobs, and has a companion role. Its code comes from another repo that is deployed by snapshot, with no CI, no signed release, and a test gate that is routinely run in `--fast` mode. For customers it is dormant (no `DASH_CARDS_SRC`, `cards_agent` off). But nothing in the licensing docs, INSTALL.md or the feature flags says whether it is sold, and the dashboard and companion carry its seams either way.
- **Scenario:** Sales demos /cards from the studio. A customer asks for it. Either it is enabled from an ungated repo, or the customer finds that a demonstrated feature is not in the product.
- **Recommendation:** The owner decides whether Cards is in v1. If not, list it as excluded in the product description and EULA order form and keep the mount behind a vendor-off feature flag. If yes, it needs its own CI, a versioned and signed artefact in the feed, the handshake run live, and CR-137 cleared.
- **Known:** CR-137 (OPEN). The scope decision is not recorded.

### com-quality-gates-16 - No one-page release checklist, no coverage measurement, and no test across companion and dashboard versions
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/RELEASE.md` (1,574 lines, two pathways in `RELEASE_PATHWAYS.md`); no `pytest-cov`/`coverage` in any lock or workflow; `dashboard/tests` has ad-hoc "older companion" tests (11 named) but no stored per-version report corpus; `docs/ARCHITECTURE.md`/`INSTALL.md` carry no supported-skew policy
- **What:** A release that reaches customers takes four to six commands across two machines (Windows rig plus Mac or the CI artefacts), spread over 1,500 lines of rationale. Nowhere is there a go/no-go list that someone else could run. The completeness of test coverage on the critical paths (lane B trash, upgrade/rollback, auth) is claimed but not measured. Version skew between a customer's dashboard and their mixed-version companions is the normal state (machines upgrade at different times). It is tested only where a past incident left a test behind.
- **Scenario:** The owner is unavailable on release day and nobody else can run or verify a release. Or a companion N+1 report field breaks a customer's dashboard N, because no test replays an N+1 report against N.
- **Recommendation:** Write `docs/RELEASE_CHECKLIST.md`, one page, generated from the gates that exist: RC commit and tag; CI full-green on all three OSes; dashboard bundle, image tag and feed; companion Windows + Mac; onboard Windows + Mac; fresh-install acceptance; soak criteria; notes and known issues; recall command written down. Add `pytest-cov` reporting on the companion and dashboard, with a floor on the sync, upgrade and auth modules. Keep a corpus of recorded `/report` and `/verify` payloads from each published companion version, replay it against the current dashboard in CI, and publish a supported-skew policy (for example dashboard N supports companions N-3 and newer).
- **Known:** Not recorded.
