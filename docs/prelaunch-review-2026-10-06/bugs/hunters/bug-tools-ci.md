# bug-tools-ci - pre-launch bug hunt: tools/, CI and release workflows, bench, lockfiles, line endings

Lens `bug-tools-ci`, 2026-10-06, HEAD 08b40eb plus the uncommitted working tree.

**What I read:**

- **tools/:** `run_all_tests.ps1`, `select_suites.py` + `test_map.toml` (the new M1 selector), `check_licenses.py`, `gen_notices.py` (lock reading, the licence-resolution order, `--check`, `run_piplicenses`), `jobs.py` end to end (against the dashboard's `/api/v1/login`, CSRF gate and `/jobs/{id}/cancel`), the network and credential half of `check_deploy_drift.ps1`, `publish_latest.py`, the scan_frozen docstring and the companion-install half of `release.ps1`.
- **Workflows:** all of `.github/workflows/`: `ci.yml`, `release-windows.yml`, `release-macos.yml`, `release-dashboard.yml`, `image.yml`, `android.yml`.
- **Also:** `bench/ccbench/guard.py`, every `requirements*.lock` header, and `.gitattributes`.

**Probes I ran:** all from the scratchpad, against repo code, read-only.

- Ran `select_suites.py --audit`: the map covers every import and path literal.
- Ran a plan of the working tree against HEAD: FULL, correctly.
- Found no unmapped tracked file.
- Checked `git ls-files --eol` for every `eol=lf` path: index and working tree are both LF.
- Scanned every tracked `.ps1` for non-ASCII bytes without a BOM: only comments have any.
- Compared the container lock's versions with those of the venvs it is licence-scanned from.
- Probed `check_licenses.verdict()` with non-GPL restrictive licences.
- Probed the bench scratch-path guard.

**What I did not cover:** the bodies of `ship.ps1`, `ship_gates.ps1`, `publish_feed.py`, `publish_package.py`, `sign_release.py`, `release_key.py`, `build_dashboard_bundle.py` and `release_macos.sh`. These belong to the release path, which the release lens covers. I also did not cover the bench runners beyond the guard, or `android/`. I did not run any test suite.

**Already in the ledger:** none of the items below is in KNOWN_BUGS.md as open. REL-14 (the stale origin/main ref) and the CR-353 notices rework are fixed and are not re-reported.

---

### bug-tools-ci-1 - image.yml re-points the customer-facing `:1` image tag from ANY `v*` tag push: no CI gate, no main-ancestry check, no version-order check

- Severity: high
- Confidence: CONFIRMED (read the workflow end to end; ci.yml's triggers checked)
- Where: `.github/workflows/image.yml` (`on: push: tags: ["v*"]`, the "compute tags" step, `docker/build-push-action ... push: true`); `dashboard/deploy/compose.appliance.yaml:88,147,291` (`...ccsync:1`, `...ccsync-sftp:1`); `docs/DOCKER.md:548-556`.
- What: every appliance customer runs `ghcr.io/the-creators-club/ccsync:1`, and "updating" for them is `docker compose pull && up -d` (DOCKER.md). image.yml rebuilds and pushes `:1` and `:<VERSION>` on any `v*` tag. The job has:
  - no `needs:` on tests;
  - no check that the tagged commit is on `main`. publish_latest.py has exactly this check for the companion (release-pipeline-7 / REL-14), but there is no equivalent here;
  - no check that VERSION is newer than what `:1` already points at;
  - no check that the tag name matches VERSION.

  ci.yml only triggers on `push: branches: ["**"]`, so a tag push runs no tests at all. The same holds for `:edge`, which `server/install_dashboard_app.py:1419-1627` tells operators to deploy: a `workflow_dispatch` of image.yml from a feature branch overwrites it with that branch's build.
- Scenario:
  - (a) Someone tags a commit on a feature branch, or a `main` commit whose ci.yml run is red, as `v0.7.74`. On their next pull, every customer appliance gets untested code.
  - (b) Someone re-tags an older commit to hotfix it (`v0.7.50b` on the 0.7.50 line). `:1` moves backwards, and every appliance that pulls runs 0.7.50 code against a schema-v58 database it has never seen.
  - (c) Two tags carry the same VERSION. `:0.7.73` is silently re-pointed, which breaks anyone who pinned it.
- Recommendation:
  - Gate the push on the tagged commit being an ancestor of `origin/main`, and on ci.yml having concluded `success` for that sha (`gh api` or `workflow_run`).
  - Refuse when the tag name is not `v$VERSION`, and when `$VERSION` is not newer than the version label on the image `:1` currently points at.
  - Refuse to overwrite an existing `:<VERSION>`.
  - Restrict `:edge` to `refs/heads/main`.
- Known: no

### bug-tools-ci-2 - The documented cosign verification accepts a signature from ANY GitHub Actions workflow, and nothing in the product verifies at all

- Severity: medium
- Confidence: CONFIRMED (read)
- Where: `docs/DOCKER.md:560-565`; image.yml's step-summary block (`cosign verify --certificate-identity-regexp '.*' --certificate-oidc-issuer https://token.actions.githubusercontent.com ...`); no `cosign verify` call anywhere in server/, dashboard/ or tools/ (grep).
- What: under keyless signing, the certificate identity is the only thing that ties a signature to *our* workflow. `'.*'` with the GitHub OIDC issuer matches any repository's workflow on github.com.
- Scenario: an attacker who can get an image in front of a customer (a typo-squatted registry path, a compromised `CCSYNC_IMAGE` override, or a mirror) signs it keylessly from their own GitHub repo. The verification recipe we hand customers and auditors then passes. A security questionnaire answered "images are cosign-signed and verifiable" would be true in name only.
- Recommendation:
  - Publish the exact identity: `--certificate-identity-regexp '^https://github.com/The-Creators-Club/ccsync/.github/workflows/image.yml@refs/(heads/main|tags/v.*)$'`.
  - Put the same recipe in the step summary.
  - Consider having `install_dashboard_app.py --mode image` verify before it deploys.
- Known: no

### bug-tools-ci-3 - publish_latest signs and ships a release build without asking whether ci.yml was green for that commit; the release workflows run only a fraction of the gate

- Severity: medium
- Confidence: CONFIRMED (read; grep finds no reference to ci.yml in publish_latest.py)
- Where: `tools/publish_latest.py:236-246` (`latest_green_run`: the newest successful run of `release-windows.yml` / `release-macos.yml` on main); `.github/workflows/release-windows.yml` (release.ps1 runs the companion and dashboard suites; the onboarding suite runs only for the wizard); `release-macos.yml` (companion suite, plus the onboarding suite for the wizard); CLAUDE.md and docs/RELEASE_PATHWAYS.md ("takes the newest GREEN CI run on `main`").
- What: "green" here means the release workflow succeeded. That workflow does not run:
  - the installer suites (`installer/tests/Test-*.ps1`, `test_*.sh`), which hold `windows_bootstrap.ps1` / `macos_bootstrap.sh`. The onboard wizard conveys and executes those;
  - the CRLF gate;
  - `check_licenses.py --strict`;
  - `gen_notices.py --check`;
  - the server, broll, music and ytdl suites;
  - the macOS job's onboarding-on-a-Mac checks for the Windows artefact.

  A commit whose ci.yml run is red can therefore be signed into the vendor feed, as long as the release workflow for that commit was dispatched and passed.
- Scenario: a change to `windows_bootstrap.ps1` breaks `Test-DriveMapParser.ps1`, and ci.yml goes red. The release lead dispatches release-windows on the same main commit to get a companion fix out. It succeeds, because no installer test runs there. `publish_latest.py --make-current` then signs the companion and the onboard.exe from that run. A new customer's first install executes the broken bootstrap.
- Recommendation: in `publish_latest.main()`, after `commit_is_on_main`, query `gh run list --workflow ci.yml --commit <headSha> --json conclusion`. Refuse unless one run concluded `success` for that exact sha, with an explicit `--allow-red-ci` override. Make the documentation match.
- Known: no

### bug-tools-ci-4 - The licence gate is a denylist of GPL-family strings: non-commercial, source-available, proprietary, EUPL and OSL licences all pass silently, in check_licenses.py AND in scan_frozen.py

- Severity: medium
- Confidence: CONFIRMED (probed `verdict()`)
- Where: `tools/check_licenses.py:78-108` (DENY, `verdict()`); `tools/scan_frozen.py:77` (imports the same `verdict`).
- What: `verdict()` flags only AGPL, SSPL, LGPL, GPL and UNKNOWN/empty. The probe returned `''`, meaning clean and shippable, for every one of these:
  - `EUPL-1.2` and `European Union Public Licence 1.2`
  - `CC-BY-NC-4.0` and `Creative Commons Attribution-NonCommercial 4.0`
  - `OSL-3.0` and `CDDL-1.0`
  - `BUSL-1.1` and `Business Source License 1.1`
  - `Elastic License 2.0` and `Commons Clause`
  - `Proprietary`, `Other/Proprietary License` and `LicenseRef-Proprietary`

  gen_notices' own `ATTENTION_TOKENS` already knows EUPL, CDDL, EPL, MPL and CC BY-SA, so the inventory and the gate disagree about what needs a human.
- Scenario: a new dependency, or a transitive bump (ML-adjacent packages and model wrappers are where NC and source-available licences live), arrives with `CC-BY-NC-4.0` or `BUSL-1.1` metadata. CI's strict gate and scan_frozen both pass, and the binary sold to a paying customer conveys a package whose licence forbids commercial use. This is exactly the "new restrictive dependency arriving unnoticed" job the gate claims (its own docstring).
- Recommendation: invert the gate to an allowlist of known-permissive licences: MIT, BSD-*, Apache-2.0, ISC, PSF-2.0, Unlicense, Zlib, HPND, MPL-2.0 with a note, and SPDX expressions of these. Anything else needs an allowlist entry with a reason, just as GPL-family licences do now. At minimum, add NC, "NonCommercial", BUSL, "Business Source", "Elastic", "Commons Clause", "Proprietary", EUPL, OSL and CDDL to the deny side.
- Known: no

### bug-tools-ci-5 - CI tests the installer's PowerShell under PowerShell 7, but every editor runs it under Windows PowerShell 5.1

- Severity: medium
- Confidence: CONFIRMED (read). No concrete 5.1-only break was found in the current tree.
- Where: `.github/workflows/ci.yml` "installer -- powershell suites" step (`shell: pwsh`, `pwsh -NoProfile -ExecutionPolicy Bypass -File ...`). Compare `installer/windows_bootstrap.ps1:1`, `windows_upgrade.ps1:1` and `windows_uninstall.ps1:1` (`#requires -Version 5.1`), and `onboarding/steps.py:1831,2681,3079,3170` (the wizard launches `powershell`, which is 5.1). `tools/run_all_tests.ps1` runs them under `powershell` (5.1), so the local gate and the CI gate test different editions.
- What: the Test-*.ps1 scripts slice helpers out of the installer scripts and run them in the current host. On CI that host is pwsh 7, which accepts several things 5.1 does not:
  - `&&` / `||`, the ternary operator, `??` and `?.`;
  - `ConvertFrom-Json -AsHashtable`;
  - `Join-Path` with more than two arguments;
  - UTF-8-without-BOM source decoding, and different `Set-Content` default encodings;
  - `Get-Content -AsByteStream`.

  CI green is what publish_latest and the owner trust, and it says nothing about the edition the installer actually runs in.
- Scenario: a builder writes `$cfg = Get-Content $p | ConvertFrom-Json -AsHashtable` in a windows_bootstrap.ps1 helper and adds a table test. CI is green on pwsh 7. On a new customer's PC, onboard.exe runs `powershell -File windows_bootstrap.ps1` and the step dies with "A parameter cannot be found that matches parameter name 'AsHashtable'". The customer cannot install.
- Recommendation: use `shell: powershell` for that step and invoke `powershell -NoProfile -ExecutionPolicy Bypass -File` (windows-latest ships 5.1). Optionally run the suite under both editions.
- Known: no

### bug-tools-ci-6 - The tools that judge licences install an unpinned, unhashed `pip-licenses` into the venv they judge, on CI and on the release-signing rig; the shipped freezer is pinned but unhashed

- Severity: low
- Confidence: CONFIRMED (read)
- Where:
  - `tools/gen_notices.py:177-211` (`run_piplicenses`: on first failure, `python -m pip install --quiet pip-licenses`, latest from PyPI, into the scanned venv). check_licenses.py goes through it too. CI runs it inside `companion/.venv` (ci.yml "licence gate (companion, win32/darwin)").
  - `tools/release.ps1` (`$PyInstallerPin`), and both release workflows, run `pip install "pyinstaller==6.21.0"` with no `--require-hashes`.
- What:
  - The licence strings both gates judge come from whatever pip-licenses version PyPI serves that day, so a pip-licenses release that reads `License-Expression` differently changes verdicts with no commit.
  - The install also mutates the venv under judgement: pip-licenses pulls prettytable and wcwidth, and can move a locked dependency.
  - On the base rig, that venv is the one `release.ps1` freezes from, on the machine that holds `~/.ccsync-release/release.key`.
  - The PyInstaller bootloader is conveyed inside every exe. A version pin without a hash still accepts any wheel file newly uploaded for that version.
- Scenario: someone runs `gen_notices.py` on the base rig before a ship. pip-licenses X.Y (new that morning) installs into `companion/.venv`, upgrades `wcwidth` past the lock, and executes there. The next `release.ps1` then fails in scan_frozen with a version mismatch, which is the good outcome, or runs code from an unreviewed PyPI release on the signing rig.
- Recommendation:
  - Put pip-licenses (with hashes) in a dedicated `tools/requirements-licence.lock`, and run it in a throwaway venv that only reads the target venv's site-packages (`pip-licenses --python <target>`).
  - Hash-pin PyInstaller (and pyinstaller-hooks-contrib) in a `tools/requirements-build.lock`.
- Known: no

### bug-tools-ci-7 - Third-party actions are pinned to mutable tags in a job that holds `packages: write` and `id-token: write`

- Severity: low
- Confidence: CONFIRMED (read)
- Where: `.github/workflows/image.yml` (`docker/setup-buildx-action@v3`, `docker/login-action@v3`, `docker/build-push-action@v7`, `sigstore/cosign-installer@v3`; workflow-level `permissions: packages: write, id-token: write`).
- What: a moved or compromised tag on any of these actions runs with a GITHUB_TOKEN that can push any tag to `ghcr.io/the-creators-club/ccsync`, including `:1`. It can also mint an OIDC identity that the bug-tools-ci-2 recipe would accept. This happens on every push to main, not only on releases.
- Scenario: a supply-chain compromise of a popular action tag (it has happened to widely used actions) re-points `:1` to a backdoored image. Every appliance pulls it on its next update.
- Recommendation: pin every third-party action to a full commit SHA, with the tag in a comment, and let Dependabot keep the pins current. Scope `packages: write` / `id-token: write` to the build job only (it is the only job, but say so), and consider a separate tag-only job for `:1`.
- Known: no

### bug-tools-ci-8 - check_deploy_drift.ps1 POSTs the admin password through a call that follows redirects and has no cleartext guard

- Severity: low
- Confidence: PLAUSIBLE. That redirects are followed is CONFIRMED (no `-MaximumRedirection 0`). Whether PS 5.1 re-sends the body on a 307/308 is not verified.
- Where: `tools/check_deploy_drift.ps1:567-573` (the login `Invoke-RestMethod -Method Post ... -Body (password)`), and the GETs at `:507`, `:525`, `:584`, `:611` and `:854`.
- What: CLAUDE.md and GOTCHAS §12 say "No dashboard call follows a redirect", and jobs.py and publish_package.py carry `_NoRedirect` for exactly this reason. This doctor's login does not. It also accepts any `dashboard_url`, including plain http to a public name, whereas the companion's LG-4 CleartextGuard refuses that.
- Scenario: the operator's `config.toml` has an old `http://` dashboard URL that now 307s to an https host, or a URL behind a captive or redirecting proxy. The admin password is POSTed in cleartext, and may be replayed to the redirect target.
- Recommendation: add `-MaximumRedirection 0` to every call and treat 3xx as "refusing to follow". Refuse `http://` to a non-private host, the same way the companion does.
- Known: no

### bug-tools-ci-9 - The selector's scoped tier never runs the two "full checks", so a change to the licence allowlist or the notices inputs passes the local scoped gate and fails only in CI

- Severity: low
- Confidence: CONFIRMED (read)
- Where:
  - `tools/select_suites.py:312-314` (`plan.checks` is set only in `_full`); `tools/test_map.toml` (`[[area]] "tools"`, scoped, owns `tools/license_allowlist.toml` and `tools/notices_extra/**`).
  - `tools/run_all_tests.ps1:296-310` (checks run only when the plan carries them).
- What: `tools/license_allowlist.toml` decides check_licenses' verdicts. `tools/notices_extra/lock_only.json` and the `*.txt` files feed the rendered THIRD_PARTY_NOTICES.md. A change to either runs only the tools suite. Neither `check_licenses.py` nor `gen_notices.py --check` runs, and the scoped green says nothing about them.
- Scenario: someone deletes an allowlist entry, or edits `lock_only.json`. `run_all_tests.ps1 -Changed` reports green on the tools tier. The committed notices are now stale (CI fails `gen_notices.py --check` later), or the licence verdict changed unseen.
- Recommendation: give the `tools` area's licence and notices files their own row with tier `full`, or add a `checks = [...]` key to `[[area]]` so a row can name the full-check it needs.
- Known: no

### bug-tools-ci-10 - check_licenses judges the dashboard container's packages from other venvs, at other versions

- Severity: low
- Confidence: CONFIRMED (probe: `psycopg2-binary` is 2.9.12 in `dashboard/deploy/requirements.lock` and 2.9.13 in `dashboard/requirements.lock`, the first venv scanned)
- Where: `tools/check_licenses.py:140-155` (the `dashboard-container` target scans dashboard, music/web, ytdl/web and broll/web venvs) and `:216-231` (`rows.setdefault`, keyed by name only).
- What: the container closure is judged by name only. The licence string comes from whichever developer venv holds that name first, at whatever version that venv has. gen_notices already records this as "a venv's 2.9.13", but the gate neither checks nor says it. A package that changed licence between the two versions is judged on the wrong one.
- Scenario: the container lock pins `foo==1.4` (Apache). The dashboard dev venv has `foo==2.0`, relicensed to AGPL, so CI FAILS on a container that does not ship AGPL. The reverse case passes when it should fail.
- Recommendation: build a venv from `dashboard/deploy/requirements.lock` in the CI linux job (it is a `pip install --require-hashes` away) and scan that, or at least match on (name, version) and report a version mismatch as UNSCANNED.
- Known: no

### bug-tools-ci-11 - The opt-in YouTube-unblock dependency set (GPLv3) is in no gate at all

- Severity: low
- Confidence: CONFIRMED (read)
- Where: `tools/check_licenses.py:157-178` (target `dashboard-container-unblock`, documented as "run this target by hand"); `.github/workflows/ci.yml` (only `--only dashboard-container`).
- What: `bgutil-ytdlp-pot-provider` (GPLv3) is installed into a customer's container when `[features] youtube_unblock` is on. Its lock can gain new packages, or change licence, with nothing in CI noticing. The policy note is reasonable (this is not part of the vendor build), but "run by hand before shipping" is not enforced anywhere.
- Scenario: someone refreshes `requirements-unblock.lock` and it pulls in a new AGPL transitive dependency. A customer who enables the feature receives it, and no gate ever ran.
- Recommendation: run `--strict --only dashboard-container-unblock --platform linux` in the CI linux job as a separate, named step, so it is reported but does not affect the vendor-build verdict.
- Known: no (by design, but unenforced)

### bug-tools-ci-12 - The bench scratch-path guard accepts `..` traversal and any path component that merely contains `_bench`

- Severity: low (bench is internal and not conveyed)
- Confidence: CONFIRMED (probed)
- Where: `bench/ccbench/guard.py:126-135` (`path_components`, `is_scratch_path`).
- What: components are filtered for `""` and `"."` only. `..` survives, and the test is a substring match (`"_bench" in part`). Probe results:
  - `nas:Creators_Club/_bench/../2026/CCT` returns True (allowed to purge);
  - `nas:Creators_Club/2026/Lab_benchmarks` returns True;
  - `E:\_bench\..\Projects` returns True.
- Scenario: a `bench.toml` remote_root of `nas:Creators_Club/_bench/../2026` (for example, a hand-edited relative path) passes the guard. `rclone purge` on the NAS resolves it to the live `Creators_Club/2026` project tree.
- Recommendation: refuse any `..` component outright, and require a component EQUAL to `_bench` (case-folded), not one containing it.
- Known: no
