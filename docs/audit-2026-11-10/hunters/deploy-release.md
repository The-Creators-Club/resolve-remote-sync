# deploy-release - the companion / package release flow (ship.cmd, release.ps1, CI release workflows, publish_latest/publish_feed, release_customers)

Files read (approximate coverage): `.github/workflows/release-windows.yml` (all), `release-macos.yml` (all), `ci.yml` (all), `release-dashboard.yml` (trigger block); `tools/ship.ps1` (header, gates 330-660, steps 0-3 in full); `tools/release.ps1` (steps 2-5 in full, parity/install by grep); `tools/publish_latest.py` (1-130, 240-808); `tools/publish_feed.py` (structure by grep); `tools/release_customers.py` (structure by grep); `tools/select_suites.py` (docstring, run on four real commit ranges); `installer/build_editor_package.ps1` (by grep); `companion/build.spec` (grep for bundled tools); `docs/RELEASE_PATHWAYS.md` (all), `docs/RELEASE.md` ("Where versions live"), `docs/CI.md` (grep); `dashboard/.../release_feed.py` (poll interval, same-version-different-bytes 409); owner memory notes `studio-package-direct-put.md`, `ship-2026-09-25.md`; KNOWN_BUGS / prelaunch review grepped for overlap.
Probes run: `gh run list` (60 runs) and `gh run view --json jobs` step timings for CI 42776015071 / 42837667812, release-windows 42847901698 (push, skip-tests) and 42750267485 (dispatch, tests), release-macos 42847901441 / 42750271542; `gh api .../artifacts` (artifact sizes); `python tools/select_suites.py --base A --head B` on 6b5c0c6..5aee6ff, 57eb0b2..6b5c0c6, 5aee6ff..d20af6a, ffdf9f2..1b7d03f (0.21-0.31 s each). No release, publish, sign or ship script was run.

## The two pathways as they run today (2026-11-10, after the "release speed" change)

Measured numbers are from the runs named above; "est." marks an estimate.

### Pathway A - `tools\ship.cmd` (Alex at the terminal; studio is IMAGE mode)

| # | Step | Wall clock | Manual / prompt |
|---|---|---|---|
| pre | bump companion VERSION in 2 files; installer version in 4 files (forced on every ship, SHIP-4, ship.ps1:475-507) | human, est. 2-4 min | 6 hand edits, commit |
| pre | `. .\tools\load_secrets.ps1` | ~1 s | 1 command |
| 0 | secrets/URL/dirty/version-free probes, Authenticode prediction, live-dashboard gates | ~5 s | `-AllowUnsignedBinary` typed every ship |
| 0 | release key passphrase (ship.ps1:634) | human | **prompt 1** |
| 0 | server suite through Git bash | ~70 s (CI linux: 68-71 s) | |
| 0b | onboarding suite (system python) | 12-49 s (CI) | |
| 0c | **dashboard suite, SERIAL** (ship.ps1:773, no `-n`) | **~19 min** (CLAUDE.md, "Fast runs") | |
| 1 | image mode: nothing deployed; one health read | ~3-10 s | |
| 2a | release.ps1: lock install + editable + PyInstaller pin | est. 20-30 s | |
| 2a | companion suite `-n auto` | ~1 min (CLAUDE.md) | |
| 2a | **dashboard suite again**, `-n auto --dist loadfile` | **~2.5 min** | |
| 2a | PyInstaller, scan_frozen, `--self-test`, signtool, manifest | est. 1.5-2 min (CI: 54 s for the PyInstaller part) | |
| 2b | build_editor_package: onboard.exe PyInstaller | 14-21 s (CI) | |
| 2b | dashboard admin password (build_editor_package.ps1:366) | human | **prompt 2** |
| 2b | PUT exe + onboard (1-2 s), make-current - or exit 3 (soak refusal) | ~2 s | on exit 3: push the staged build to one machine in Settings > Packages, wait the soak (30 min last time), `ship.cmd -Resume` |
| 2b2 | vendor feed: NOT published unless `-PublishFeed` | - | prints a command to copy |
| 2c | macOS advisory: tells you to run `release_macos.sh` ON A MAC | ~1 s | stale advice (finding 9) |
| 3 | windows_upgrade.ps1, check_deploy_drift.ps1 | est. 20-30 s | |

Total: **~27-29 min**, of which ~21.5 min is the dashboard suite run twice; 2 typed secrets, 1 typed flag, 6 hand edits; frequently 2 invocations (soak). Produces a LOCAL Windows binary that is not the one CI built for the same commit, and no macOS artefact.

### Pathway B - CI + `tools/publish_latest.py`

| # | Step | Wall clock | Manual / prompt |
|---|---|---|---|
| pre | bump 2 files (companion) or 6 (with installer); commit; push | human, est. 1-3 min | hand edits |
| 1 | release-windows.yml (now on every push, `tests_gate=ci`) | **2 m 52 s** (run 42847901698; was 39-51 min with tests) | none (docs still say dispatch it, finding 9) |
| 1 | release-macos.yml | **2 m 30 s** (42847901441; was 10-12 min) | |
| 1 | ci.yml windows / macos (linux OFF since today) | **5 m 52 s / 4 m 31 s** (42776015071); linux was 11 m 41 s | |
| 2 | wait for all three green on the sha | ~6 min after push | `gh run watch <id>` per run (ids copied by hand) |
| 3 | `publish_latest.py --make-current`: passphrase | human | **prompt 1** |
| 3 | download 2 artifacts (125.5 MB + 118.4 MB), verify, sign, 4 x publish_feed (channel download + asset upload) | est. 2-5 min | if a version is staged with other bytes: copy the printed `publish_feed --set-current` line |
| 4 | studio picks it up: poller is DAILY (release_feed.py:1639) or a container restart | **up to 24 h** | a `docker restart` of the live dashboard to hurry it |
| 4 | NAS downloads each artefact from GitHub's release CDN | **~14 min per 50 MB** (owner note 2026-09-26; "past 15 min" 09-17); direct PUT of the same bytes: **1.2 s** | the fast path is a scratchpad helper with run id, sha and version copied by hand |
| 5 | studio soak (REL-1) then current; companions self-upgrade on next report | 30 min soak last time | |

Total from push to "on the vendor feed": **~9-12 min**, 1 prompt. From push to "the studio has the bytes": 9 min + (0 to 24 h) + ~14-40 min, or 9 min + 1 s with the off-repo PUT helper.

### Side by side - what is duplicated

| Work | A | B | Duplicate? |
|---|---|---|---|
| Companion + dashboard suites on the commit | local (dashboard twice) | ci.yml (dashboard NOT any more: linux off) | A re-runs what CI runs (companion); B no longer runs the dashboard at all |
| Windows PyInstaller build of the commit | local | release-windows.yml on every push | yes: two builds, two different byte sets under one version (finding 3) |
| macOS build | none (advisory) | release-macos.yml | B only |
| onboard.exe | local | CI | yes |
| record signing (release key) | build_editor_package -> sign_release | publish_feed -> sign_release | same code, both fine |
| destination | studio dashboard only (PUT) | vendor feed only | the studio is on `policy = current` reading the feed, so A's make-current is undone on the next poll (RELEASE_PATHWAYS step 3) |
| dirty / version-reuse / Authenticode / min_version / CI-green / on-main refusals | ship.ps1 + build_editor_package + the dashboard | publish_latest + publish_feed | both enforce; B's set is the superset (CI green on exact sha, ancestry of the REMOTE main) |

A can be B's wrapper: everything A does that B does not (live-dashboard order gates, local upgrade, drift check, the studio PUT) is cheap and can be layered on top of B's verified CI artefact. See the proposal at the end.

## Findings

### deploy-release-1 - ship.cmd runs the whole dashboard suite twice, the first time serially (~21.5 min per ship), and in image mode the first run guards a deploy that does not happen
- Category: deploy
- Severity: medium
- Confidence: CONFIRMED
- Where: tools/ship.ps1:768-784 (step 0c, `& $dashPy -m pytest tests -q`, no `-n`); tools/release.ps1:673-727 (step 2a, the same suite again with `-n auto --dist loadfile`); tools/ship.ps1:831-848 (image mode decided AFTER 0c, and step 1 then deploys nothing)
- What: GL-25 moved a dashboard suite run BEFORE step 1 so a red suite cannot follow a bind-mode deploy, but release.ps1 still runs it again in step 2a, and step 0c never got the `-n auto --dist loadfile` that release.ps1 and CI use. On the live studio (image mode) step 1 deploys nothing, so 0c's reason does not apply at all.
- Cost / failure scenario: every pathway-A ship (three companion versions were cut today: 0.9.89, 0.9.90, 0.9.91) x ~19 min serial + ~2.5 min parallel = ~21.5 min of dashboard tests, ~19 min of it pure waste. With `select_suites.py` the two companion releases cut today were SCOPED (companion + 20 dashboard test files): the dashboard share would be seconds.
- Evidence: the two invocations read above; CLAUDE.md "Fast runs": dashboard ~19 min serial vs ~2.5 min `-n auto --dist loadfile`; `select_suites.py --base 6b5c0c6 --head 5aee6ff` -> "SCOPED ... dashboard 20 file(s)" in 0.31 s (same for 57eb0b2..6b5c0c6).
- Ledger: related to GL-25 / CR-371 (which added 0c); new
- Suggested change: run the dashboard suite once, in 0c, with `-n auto --dist loadfile`, and pass release.ps1 a `-SkipDashboardSuite` (companion suite still runs) so 2a does not repeat it; better, let 0c run `select_suites.py --base <live code.commit>` (fail-closed to FULL). Must keep: a red dashboard suite stops the ship before any bind-mode deploy.
- Effort / risk: S effort; low risk

### deploy-release-2 - With the linux CI job off, "ci.yml green on the exact commit" no longer covers the dashboard, server, tools, web suites, CRLF gate, dashboard licence gate or notices check, yet release_customers.py publishes a dashboard bundle to every customer on that gate
- Category: deploy
- Severity: high
- Confidence: CONFIRMED
- Where: .github/workflows/ci.yml:259-264 (`linux: if: false`); tools/publish_latest.py:264-284 (`ci_green_for` reads the RUN conclusion); tools/release_customers.py:71 and :422 (REQUIRED_RUNS, "verified: ci.yml green"); tools/publish_latest.py:574-579 (refusal text still claims the CRLF gate, licence and notices checks ran)
- What: A job skipped with `if: false` leaves the run `success`, and every gate in the release flow checks only the run conclusion. Since d20af6a the whole linux half (dashboard 415-460 s, server 68 s, broll/music/ytdl web, broll indexer, tools - which tests publish_latest itself - the CRLF gate that once crash-looped the dashboard, the dashboard-container licence gate and `gen_notices --check`) runs nowhere automatically, while `release_customers.py` publishes `--kind dashboard --make-current` to the vendor channel on "ci.yml green".
- Cost / failure scenario: the next customer release whose dashboard has a regression (the linux job was failing a different pair of dashboard tests on each run when it was switched off) passes every automated gate; only the 24 h studio soak stands between it and every customer dashboard. The tools suite that pins publish_latest/publish_feed's own refusals also no longer gates a change to those scripts.
- Evidence: ci.yml:259-264; CI run 42837667812 linux job red on "dashboard -- pytest" (460 s) while the run would now read green; release_customers.py has no job-level check (grep for `jobs`/`linux` finds only the platform string).
- Ledger: new (the switch-off is today's owner decision; its effect on the release gates is not recorded)
- Suggested change: keep the owner's goal (companion releases not held by flaky dashboard tests) without emptying the gate: move the linux job to its own workflow (`ci-linux.yml`) or check JOB conclusions, and require `windows`+`macos` jobs for companion/onboard kinds but the linux job `success` (not `skipped`) for `--kind dashboard` and for `release_customers.py`. Fix the refusal text so it does not claim checks that did not run. Must keep: fail closed when the job cannot be read.
- Effort / risk: S-M effort; low risk

### deploy-release-3 - Pathway A builds a second, different binary of a commit CI already built; the studio then soaks bytes no customer gets, and one version number names two binaries
- Category: deploy
- Severity: medium
- Confidence: CONFIRMED
- Where: tools/ship.ps1:921-946 (step 2a builds locally through release.ps1); installer/build_editor_package.ps1:1263 (PUT of the local exe); .github/workflows/release-windows.yml:38-44 (CI now builds every push to main); dashboard/src/ccsync_dashboard/release_feed.py:1408-1416 (409 "the feed offers DIFFERENT bytes for that same version")
- What: Since 2026-11-10 the Windows exe for every main commit is ready ~3 min after the push and is vouched for by `tests_gate=ci`. Pathway A still runs PyInstaller locally and PUTs that build to the studio, while the vendor feed gets the CI build; PyInstaller output is not byte-reproducible (`built_at` alone differs), so the same version is two binaries.
- Cost / failure scenario: per ship, ~2 min of local PyInstaller/self-test plus ~3.5 min of local suites that CI already ran, and: the studio (on `policy = current`, reading the feed) later meets the feed's record for a version it already holds with other bytes and refuses it with a 409 notice; the studio soak (`release_customers.py`, REL-1) then vouches for bytes customers never receive.
- Evidence: the steps read above; RELEASE_PATHWAYS.md step 3 already records that A's make-current is undone by the feed poll on `policy = current`; KNOWN_BUGS line ~33279 records the same "two builds of one commit differ in bytes" mechanism for the dashboard bundle.
- Ledger: related to release-pipeline-6 (fixed: the 409 now names the conflict); new for the companion path
- Suggested change: make step 2a fetch the CI artefact for HEAD (`gh run list --workflow release-windows.yml --commit <sha>`, `gh run download`, verify sha256/size/`git_commit`/`git_dirty` exactly as publish_latest.verify does) and require `ci_green_for(sha)` instead of building; keep the local build only behind an explicit `-BuildLocally` for an offline hotfix. Must keep: clean-tree, version-free and Authenticode refusals.
- Effort / risk: M effort; low risk

### deploy-release-4 - The studio gets a feed release after up to a day plus ~14 min per 50 MB from GitHub's CDN; the 1.2 s direct PUT exists only as an off-repo scratchpad helper
- Category: deploy
- Severity: medium
- Confidence: CONFIRMED (timings from the owner's notes, mechanism read)
- Where: tools/publish_latest.py:416-435 (publishes to the feed only); dashboard/src/ccsync_dashboard/release_feed.py:1638-1706 (poll every 86400 s); installer/build_editor_package.ps1:1263 (the PUT route that already exists)
- What: Pathway B ends at the GitHub release. The studio learns of it on its daily poll (or a deliberate restart of the live dashboard) and then downloads every artefact through the NAS's ~60 KB/s path to GitHub's CDN. The owner's fast path (PUT the identical, already-signed bytes from this rig over the tailnet) is a helper in a session scratchpad with the run id, sha and version retyped.
- Cost / failure scenario: per release, ~14 min per 50 MB artefact (companion exe 50 MB, mac binary ~50 MB, mac wizard zip ~63 MB) once the poll fires - `feed/check` "runs past 15 min" - versus 1.2 s for 54 MB by PUT; or up to 24 h of the studio not having the build at all. Three releases today.
- Evidence: memory `studio-package-direct-put.md` (2026-09-26: 14 min for 50 MB via feed, 1.2 s by PUT); `ship-2026-09-25.md` ("macos via feed/publish, 14 min; windows via direct PUT, 1.2 s"); poll default read in release_feed.py:1639.
- Ledger: new
- Suggested change: add `--studio <url>` to publish_latest: after a successful feed publish, PUT the verified artefact with the exact signed record publish_feed just wrote (signature, pubkey_id, min_version, published_at, git fields) to `/api/v1/admin/packages/...` using build_editor_package's admin login (one password prompt, opt-in, so pathway B stays password-free by default). The bytes are then identical to the feed's, so the studio's later poll sees "already published, same bytes". Must keep: the dashboard's own signature check and REL-1 soak; never put the password on argv.
- Effort / risk: M effort; low risk

### deploy-release-5 - A companion ship means six hand edits of version strings (two companion copies, four installer copies forced by SHIP-4)
- Category: streamline
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/config.py + companion/pyproject.toml; installer/windows_bootstrap.ps1, onboarding/steps.py, installer/macos_bootstrap.sh, onboarding/build_onboard_macos.spec (docs/RELEASE.md:58-79); tools/ship.ps1:475-507 (installer bump required on EVERY ship)
- What: The companion version is duplicated in pyproject.toml although setuptools can read it from config.py (`dynamic = ["version"]`, `[tool.setuptools.dynamic] version = {attr = "ccsync_companion.config.VERSION"}`, evaluated statically from the AST). The installer number has four copies, one (the .spec) checked only by a test. No tool writes them.
- Cost / failure scenario: 6 edits per pathway-A ship (3 ships' worth of companion bumps today), each a chance of a parity refusal after a build has started (the .spec copy is caught only by the onboarding suite, 2026-08-10 incident).
- Evidence: RELEASE.md "Where versions live"; companion/pyproject.toml uses setuptools>=68 (`version = "0.9.91"` literal); `git log` shows 0.9.89/0.9.90/0.9.91 bump commits on 2026-11-10.
- Ledger: new
- Suggested change: `tools/bump_version.py companion 0.9.92 [--installer 1.0.x]` that rewrites every copy and runs the existing parity checks; make pyproject's version dynamic so the companion has one source. Must keep: release.ps1's parity refusal (it then guards the tool, not the human).
- Effort / risk: S effort; low risk

### deploy-release-6 - publish_latest fails, and recommends `--allow-red-ci`, when CI on the newest build's commit is merely still running - the normal state for ~3 min after every push now
- Category: deploy
- Severity: low
- Confidence: CONFIRMED
- Where: tools/publish_latest.py:243-258 (newest green release run), :264-284 (`ci_green_for` asks only for `--status success`), :569-579 (refusal text)
- What: Release builds now finish in ~2.5-3 min and ci.yml in ~5-6 min (12 with linux), so for several minutes after each push the newest green release run sits on a commit whose CI is in progress. publish_latest cannot tell "in progress" from "red", refuses, and suggests the hotfix override; it has no wait and no fallback to the newest commit where both are green.
- Cost / failure scenario: an operator who runs it when the build notification arrives gets a refusal and an override hint; the honest path is to find run ids and `gh run watch` by hand, then re-run (passphrase prompt again). Not unsafe (tests_vouched_by_ci still refuses after the override) but it trains the habit the flag's help text warns against.
- Evidence: run timings above (release-windows 15:46:48->15:49:40, CI windows 07:32:43->07:38:35 on another push); refusal text at :574-579.
- Ledger: new
- Suggested change: query `gh run list --workflow ci.yml --commit <sha> --json status,conclusion`; if a run is queued/in progress say so and, with a new `--wait`, `gh run watch` it (and the release runs for that sha) before continuing. Must keep: red or unreadable = refuse.
- Effort / risk: S effort; low risk

### deploy-release-7 - The push-triggered release builds still install the dashboard venv, ffmpeg and rclone for a test run they skip
- Category: deploy
- Severity: low
- Confidence: CONFIRMED
- Where: .github/workflows/release-windows.yml:132-202; .github/workflows/release-macos.yml:91-148
- What: Those steps exist only for the suites (`CCSYNC_REQUIRE_RCLONE`/`FFMPEG`, release.ps1's dashboard suite). With `run_tests` empty on push, release.ps1/release_macos.sh run with `-SkipTests`, and build.spec bundles neither rclone nor ffmpeg (grep finds no reference).
- Cost / failure scenario: every push to main x (dashboard venv 23 s + ffmpeg 30 s + rclone 2 s) = ~55 s of a 172 s Windows build (32%); ffmpeg 31 s + rclone 2 s = ~33 s of a 150 s macOS build (22%). It is on the critical path only when CI is faster than the build, so the saving is mostly runner time and flake surface (two third-party downloads per push).
- Evidence: step timings of runs 42847901698 and 42847901441.
- Ledger: new
- Suggested change: `if: inputs.run_tests == true` on the three steps in both workflows. Must keep: a dispatched `run_tests` build still gets real rclone/ffmpeg.
- Effort / risk: S effort; low risk

### deploy-release-8 - CI runs twice per commit when a feature branch and main point at the same sha, and the publish gate accepts whichever run went green
- Category: deploy
- Severity: low
- Confidence: CONFIRMED
- Where: .github/workflows/ci.yml:30-47 (`push: branches: ["**"]`, concurrency group per ref); tools/publish_latest.py:275-284 (`any` green run for the sha)
- What: Pushing main and a branch at one commit starts two full matrices that the per-ref concurrency group cannot dedupe. With a flaky suite the two can disagree, and `ci_green_for` passes if either is green.
- Cost / failure scenario: on 2026-11-10 alone fabee82, 43a9e59, ffdf9f2 and 57eb0b2 each ran twice (4 duplicate matrices, 20-29 min each at the time); 57eb0b2 was green on `release-speed` and red on `main`, and the green one vouches for main's publish. Minutes are free (public repo); the cost is a second queue of runners and a gate that "re-run until green" satisfies.
- Evidence: `gh run list --workflow ci.yml` with headBranch (table in the probe output).
- Ledger: new
- Suggested change: concurrency `group: ci-${{ github.sha }}` for push events (or push only on main + pull_request). Whether a red run on the same sha should veto a green one is the owner's call; at least print it.
- Effort / risk: S effort; low risk

### deploy-release-9 - The release docs and advisories still describe dispatch-only 36-minute builds and Mac-side publishing
- Category: streamline
- Severity: low
- Confidence: CONFIRMED
- Where: docs/RELEASE_PATHWAYS.md:41-47 ("Dispatch the builds ... ~36 min / ~7 min") and :73-79 (the "trap" about stale runs); docs/RELEASE.md:521 and :600; .github/workflows/release-windows.yml:4-8 and release-macos.yml:10-19 ("MANUAL ONLY"); tools/ship.ps1:1148 and :1152 (advisory: "ON THE MAC: git pull && ./tools/release_macos.sh --publish"); CLAUDE.md "Building & shipping" (the Mac half)
- What: The workflows run on every push since 2026-11-10 and finish in ~3 min; docs/CI.md was updated, the pathway doc - the one written so an agent finds the autonomous route in one screen - was not. The macOS companion has come from CI + publish_latest since August; ship.ps1 still tells the operator to go to a Mac.
- Cost / failure scenario: a session following RELEASE_PATHWAYS dispatches two redundant builds (new bytes for the same commit) and budgets 36 min of waiting; ship's advisory sends the owner to a Mac for something `publish_latest.py --platform macos` does in minutes.
- Evidence: the lines cited; docs/CI.md:232 already says "Both run on every push to `main`".
- Ledger: new (related POLISH notes on RELEASE_PATHWAYS in KNOWN_BUGS ~33296)
- Suggested change: rewrite pathway B steps 2-3 as "push; wait for the three runs on that sha" and drop the timing and the trap paragraph; workflow headers to "push + dispatch"; ship.ps1 2c advisory to name `python tools/publish_latest.py --platform macos`.
- Effort / risk: S effort; low risk

### deploy-release-10 - release-dashboard.yml is still dispatch-only while release_customers.py requires it green on the release sha
- Category: deploy
- Severity: low
- Confidence: CONFIRMED
- Where: .github/workflows/release-dashboard.yml:4-5, :29-30; tools/release_customers.py:71
- What: The other two release workflows moved to push-on-main today; the dashboard bundle (16 s build) did not, so a customer release still needs a hand dispatch on the right commit, and the "which bundle did the studio soak" ambiguity KNOWN_BUGS records (two builds of one commit differ in bytes) is created by those dispatches.
- Cost / failure scenario: one manual dispatch + run-id lookup per customer release; a re-dispatch after the studio applied a bundle breaks the byte match release_customers checks.
- Evidence: `gh run list --workflow release-dashboard.yml` - five runs, all `workflow_dispatch`, 13-17 s each.
- Ledger: related to KNOWN_BUGS ~33270 (GL-24 route a, fixed by naming the artefact)
- Suggested change: add `push: branches: [main]` like the other two, so each commit has exactly one bundle and release_customers/route a pick "the run for this sha". Must keep: it never publishes.
- Effort / risk: S effort; low risk

## What a one-command release could look like

`python tools/release.py companion 0.9.92 [--installer 1.0.47] [--studio] [--current]`, run on the base rig, built from pieces that already exist:

1. **Bump** (new, finding 5): rewrite every version copy, run the parity checks release.ps1 runs, `git commit`. Refuse on a dirty tree first (the ship.ps1 rule). Saves 6 hand edits.
2. **Push and wait** (finding 6): `git push`, then wait on ci.yml + release-windows + release-macos for exactly that sha (`gh run watch`), refusing on red or skipped-required-job (finding 2). No run ids typed. ~6 min (12 with linux back), all CI.
3. **Publish** (existing): `publish_latest.publish(... --sha <sha> --make-current)`: passphrase once (prompt 1), every existing refusal unchanged - on-main ancestry against the remote head, CI green on the exact sha, `tests_gate=ci`, git_dirty, version older/same-bytes rules, release_floor.json min_version and its floor-above-current refusal, key rotation, signed channel. ~2-5 min.
4. **Studio** (finding 4, opt-in `--studio`): PUT the same verified bytes with the signed record to the studio dashboard (password prompt 2), so the studio has the customer's exact bytes in ~1 s instead of 0-24 h + 14+ min. The dashboard's own signature check and REL-1 soak gate still decide "current".
5. **This machine** (from ship.ps1 step 3): `windows_upgrade.ps1 -CompanionExe <the downloaded CI exe>` + `check_deploy_drift.ps1`, gated as today.

`ship.cmd` then becomes a thin wrapper (gates that read the live dashboard + steps 2-5), and pathway A's local suites and local PyInstaller disappear (findings 1 and 3). Estimated saving per companion release: wall clock ~27-29 min (A) -> ~10-13 min, nearly all of it CI that runs anyway; human actions ~12 (6 edits, commit, 2 prompts, flag, Mac advisory, drift read) -> 3 (one command, passphrase, optional password); studio latency 0-24 h + 14-40 min -> ~1 s; one binary per version everywhere. Prerequisite: the dashboard suite must run somewhere before (2) can vouch for a dashboard-touching commit (finding 2).

## What is already good
- `tests_gate=ci` + `tests_vouched_by_ci` (publish_latest.py:301-326): dropping the 46 min of duplicated tests from release-windows while refusing any untested build without a green ci.yml on the exact sha is the right shape; release builds went 39-51 min -> ~3 min.
- One artifact download per run (publish_latest.py:583-602) and the macOS artifact trimmed to its four deliverables (release-macos.yml:220-231): already cut the publish download in half.
- The early refusals in ship.ps1 (version already published, installer version, Authenticode prediction) cost ~1 byte each via `-r 0-0` and are placed before any build; leave them.
- `select_suites.py` answers in 0.2-0.3 s and fails closed; it is the right engine for findings 1 and 10-style scoping, just unwired.
- pip caching keyed on the locks is already on in every workflow (companion venv 10-20 s); PyInstaller itself is ~1 min, so a PyInstaller work-dir cache would save little.

## Coverage note
Did not read release_macos.sh / build_onboard_macos.sh beyond grep, check_deploy_drift.ps1, load_secrets.ps1, gen_notices.py, check_licenses.py or release_key.py in full; did not time a real publish_latest upload (forbidden to run) - its 2-5 min is an estimate. The local dashboard-suite times are CLAUDE.md's, not re-measured (whole-suite runs are out of bounds). publish_feed's four sequential channel download/upload rounds per publish_latest run (a brief window where the channel holds half a release) was noticed but not measured, so not reported.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/release_feed.py:1638-1706: the feed poll is daily and `feed/check` downloads every artefact through a ~60 KB/s NAS path (deploy-nas / dash territory; finding 4 is the release-side half).
- .github/workflows/ci.yml:259-264: the three flaky dashboard tests that got the linux job switched off (test_smoke_boot /music, test_cards_edit relay, test_cli_tools) - tests-ci.
- .github/workflows/image.yml: runs on every push to every branch (1-3 min) - deploy-nas.
