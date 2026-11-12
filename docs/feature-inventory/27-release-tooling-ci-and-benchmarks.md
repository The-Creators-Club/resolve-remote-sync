# Building, signing, publishing and checking releases; continuous integration; the sync benchmark

Terms used throughout:
- **Companion**: the editor-machine app (a frozen Windows `.exe` or a macOS app bundle).
- **Onboard / wizard / installer**: the first-run installer program (`onboard.exe` on Windows, a zipped app on macOS) that bundles the companion.
- **Dashboard**: the server web app that runs in a container on the NAS.
- **Base rig**: the operator's own Windows workstation, where releases are signed.
- **Upgrade channel**: the dashboard's package store that editors' companions download updates from. A build is **published** (uploaded) and either **staged** (stored, offered to nobody) or **current** (offered to every machine).
- **Vendor feed**: a signed `channel.json` plus artefacts on a GitHub Releases repository, which every customer dashboard reads to learn about new builds.
- **Release key**: an offline ed25519 private key on the base rig that signs every package record.
- **Bind mode / image mode**: two ways the dashboard container is deployed (`[stack] mode` in `site.toml`). In bind mode the code is copied onto the NAS by script; in image mode the container runs a CI-built image and takes code updates "over the air" from the vendor feed.

## The one-command ship at the operator's terminal
(source: tools/ship.cmd, tools/ship.ps1, tools/ship_gates.ps1)

- **Launcher**: `tools\ship.cmd` runs `ship.ps1` through `powershell -NoProfile -ExecutionPolicy Bypass`, passing every argument through unchanged.
- **What a full ship does, in order**: step 0 gates, step 0a live-dashboard gates, step 0 / 0b / 0c test suites, step 1 dashboard deploy and health poll, step 2a tested companion build, step 2b package + publish + make current, step 2b2 optional vendor-feed publish, step 2c advisory macOS check, step 3 upgrade this machine + drift doctor, then a rollout line.
- Every line it prints is prefixed `[ship] `; failures print `[ship] FAILED: <reason>` in red; warnings are yellow.
- **Flags**:
  - `-DashboardUrl <url>`: required (or environment variable `CCSYNC_DASHBOARD_URL`); trailing `/` stripped. No default.
  - `-AdminUser <name>`: required unless `-DashboardOnly` (or `CCSYNC_ADMIN_USER`). The dashboard admin the package publish logs in as; its password is prompted for once by the packaging script.
  - `-DashboardOnly`: stop after step 1. Also skips the dirty-tree check, the version-collision probes, the signing check, the live-dashboard gates and the release-key passphrase prompt.
  - `-Recreate`: passes `--recreate` to `server\install_dashboard_app.py` (delete and re-create the dashboard app so container-level changes take effect). In image mode it forces the deploy script to run anyway.
  - `-SkipLocalUpgrade`: do steps 1 and 2, leave this machine's companion alone; ends with "done (-SkipLocalUpgrade). Editors get the tray offer; this machine stays as-is."
  - `-SkipTests`: skip the server, onboarding and dashboard suites of step 0 (prints "server + onboarding + dashboard tests skipped (-SkipTests)"). Does NOT skip the companion and dashboard suites run inside `release.ps1` in step 2a.
  - `-AllowDirty`: publish from a working tree with uncommitted changes; the build is stamped `+dirty`. Passed through to `release.ps1`.
  - `-IReallyMeanDirtyCurrent`: allow a dirty build to be made current. Without it a dirty ship prints that the build "will be published STAGED, not made current". Passed to the packaging script.
  - `-AllowKeyRotation`: passed to the packaging script; publish although this rig's key did not sign the fleet's current build.
  - `-EmitKindExtras`: sign the extra fields `requires_dashboard` and `arch` into the record. Gated (see step 0a). Passed to the packaging script.
  - `-AllowBehind`: publish although the live dashboard is older than this companion's `REQUIRES_DASHBOARD`; prints a warning that it will be "STAGED there, never offered".
  - `-Resume`: continue a stopped ship from the journal file.
  - `-AllowUnsignedBinary`: allow an exe without a valid Authenticode (Windows code-signing) signature to be made current; passed to the packaging script.
  - `-PublishFeed`: also publish to the vendor feed (step 2b2). Off by default.
  - `-FeedRepo <owner/repo>`: default `The-Creators-Club/ccsync-releases`; read only with `-PublishFeed`.
  - `-Notes "<text>"`: one line of "what changed"; whitespace collapsed to single spaces and exported as `CCSYNC_RELEASE_NOTES`, which the signing tool reads (unsigned advisory text shown in the editor's update dialog).
- **Step 0, secrets gate**: refuses (exit 1) when any of `TRUENAS_PW`, `DASH_REPORT_TOKEN`, `DASH_SESSION_SECRET`, `SYNCTHING_API_KEY` is missing from the session environment; prints "missing environment variable(s): ..." and tells the operator to run `. .\tools\load_secrets.ps1` (or `-Save` the first time), and "Do NOT use setx".
- **Step 0, target gate**: refuses when the dashboard URL (or, unless `-DashboardOnly`, the admin user) is missing; prints "this repo no longer has a dashboard address or an admin account compiled in". Then prints "shipping to: <url> (admin: <user or n/a>)".
- **Step 0, dirty-tree gate** (not with `-DashboardOnly`): `git status --porcelain` non-empty without `-AllowDirty` refuses, listing each dirty line: "working tree is dirty -- a +dirty build must not reach the fleet".
- Reads the dashboard version from `dashboard/src/ccsync_dashboard/__init__.py` and the companion version from `companion/src/ccsync_companion/config.py` and prints both.
- **Ship journal** (`tools\.ship-state.json`, gitignored): rewritten after each step with `step`, `version`, `installer_version`, UTC `timestamp`, `made_current` list and `dashboard_url`. Steps in order: `gates`, `dashboard`, `build`, `publish`, `current`, `local`. A journal write failure only warns ("-Resume will not work for this run").
  - `-Resume` with no journal refuses: "-Resume, but there is no journal ... run the ship normally".
  - `-Resume` with a journal for another companion version refuses: "that is a new ship, not a resumption".
  - Otherwise every step at or before the recorded step is skipped, and it prints how far the last run got and what was already made current.
  - The checked-in copy records step `gates`, companion 0.9.62, 2026-08-30, dashboard `http://100.71.216.3:8480` (a leftover file in the tree).
- **Version-collision probes** (not with `-DashboardOnly`): asks the dashboard `GET /api/v1/companion/package/windows/<companion version>` and `GET .../windows/<installer version>?kind=onboard` for just the first byte (range `0-0`, 20 s timeout), sending the fleet token `X-CCSync-Token` through curl's standard input, never on its command line.
  - A 200 or 206 for the companion refuses: "companion v<x> is ALREADY published on the server." with instructions to bump `VERSION` in `config.py` and `pyproject.toml`.
  - A 200 or 206 for the installer refuses: "installer v<x> is ALREADY published ... its bytes WILL differ and the upload will 409", naming the four places the installer version lives.
  - An unparseable `$InstallerVersion` in `installer\windows_bootstrap.ps1` refuses.
  - Both probes are skipped when resuming past `publish` with the same installer version the journal recorded; a different installer version is probed as a new ship.
- **Code-signing pre-check**: without `-AllowUnsignedBinary`, refuses when neither `CCSYNC_SIGN_THUMBPRINT` nor `CCSYNC_SIGN_PFX` is set ("no code-signing identity is configured, so step 2b WILL refuse"); otherwise prints "code signing: identity configured".
- **Step 0a, live dashboard gates** (not with `-DashboardOnly`): reads `GET /api/v1/health` (20 s) with the fleet token.
  - With `-EmitKindExtras`: refuses when the health answer is missing, has no `rollout` block, has an EMPTY rollout block, or lacks `rollout_platforms` ("Do not guess this one"). Refuses when any channel offers a version below 0.9.55, any channel has computers `behind`, any platform has an unreadable count, or a platform has computers but no current build; lists each straggler and points to `check_deploy_drift.ps1 -AdminUser`. A platform reported empty or `unknown` is counted as `windows`. Passing prints "every reporting computer is on 0.9.55 or newer".
  - Minimum dashboard: reads `REQUIRES_DASHBOARD` from `config.py`; when the live version is below it, refuses ("Deploy the dashboard first") unless `-AllowBehind`. When the live version cannot be read, prints a NOTE that the order is not checked.
  - Version comparison is numeric per dotted part; any non-numeric part answers "not at least".
- **Release-key passphrase** (not with `-DashboardOnly`): key path `%USERPROFILE%\.ccsync-release\release.key` or `CCSYNC_RELEASE_KEY`. If `release_key.py status` says `encrypted` and `CCSYNC_RELEASE_KEY_PASSPHRASE` is unset, prompts once "Release key passphrase (asked once for this ship)" (hidden input), exports it for child processes, then runs `release_key.py check`; a wrong passphrase refuses before anything is deployed. A `plaintext` key prints a warning to encrypt it. The passphrase variable is removed at the very end of a successful ship.
- **Key backup note**: when `%USERPROFILE%\.ccsync-release\backup.json` is absent, prints (never refuses) "this computer's release key has no recorded backup ... python tools\release_key.py backup --to <a USB stick>".
- **Step 0 test suites** (unless `-SkipTests` or resumed past `gates`):
  - Server suite with the dashboard virtual environment's Python, run inside Git's own bash (found from `git.exe`'s location, two candidate paths) so the shell-executing tests run. No Git bash: runs from PowerShell with a warning that those tests "will SKIP, not pass". No dashboard venv: NOTE "server tests SKIPPED, not passed" (not a refusal). Non-zero exit refuses.
  - Step 0b onboarding suite with system `python`; no `python` on PATH refuses; non-zero refuses.
  - Step 0c dashboard suite with the dashboard venv; a missing venv refuses; non-zero refuses.
- **Deploy shape**: reads `[stack] mode` from the site file (`CCSYNC_SITE` or repo `site.toml`), default `bind`, and prints it.
- **Step 1, dashboard**:
  - Image mode without `-Recreate`: does nothing ("nothing to deploy from here").
  - Otherwise runs `python server\install_dashboard_app.py [--recreate]`; non-zero exit refuses.
  - Then polls `/api/v1/health` every 3 s until it reports the repo's dashboard version, up to 90 s (10 s in image mode or when resumed), printing "waiting for the dashboard to come back up (up to 90s)..." once.
  - Image mode passes when live is equal or newer ("ahead of this checkout, fine"); live older refuses with the over-the-air recipe (`build_dashboard_bundle.py`, `publish_feed.py ... --kind dashboard`, then Settings > Packages > APPLY, or roll back with `--mode bind`).
  - Bind mode with a mismatch after 90 s refuses: "investigate before continuing".
  - `-DashboardOnly` ends here: "done (-DashboardOnly)".
- **Step 2a, tested build**: runs `tools\release.ps1 -DashboardUrl <url> [-AllowDirty]`; non-zero refuses ("nothing has been published; the dashboard deploy in step 1 stands"). Skipped when resumed past `build`.
- **Step 2b, Authenticode gate and publish**:
  - Checks `companion\dist\ccsync-companion.exe` with Windows' signature check; anything other than `Valid` refuses without `-AllowUnsignedBinary`, or warns "every fresh install meets SmartScreen" with it.
  - Runs `installer\build_editor_package.ps1 -RebuildOnboard -Publish -MakeCurrent -DashboardUrl -AdminUser` plus the pass-through flags. Never `-RebuildExe`.
  - On resume past publish, reuses the existing `onboarding\dist\onboard.exe` (omits `-RebuildOnboard`) only when it is newer than the companion exe, `installer\windows_bootstrap.ps1` and every `onboarding\*.py`.
  - Exit 0: journal `publish` then `current`. Exit 3: journal `publish`, then exits 3 saying both builds are "published and STAGED", the dashboard refused only the flip to current, and to push to one machine, soak, then MAKE CURRENT or `ship.cmd -Resume`. Any other non-zero refuses.
- **Step 2b2, vendor feed** (`-PublishFeed` only): runs `publish_feed.py --make-current --github-upload` for the companion (with its manifest `companion\dist\ccsync-release.json`) and for onboard (platform windows, installer version, current `git rev-parse HEAD`, and dirty flag), passing `--notes` when set. A missing artefact or non-zero exit only warns. Without the flag, prints a NOTE that feed customers do not have the build and the exact mirroring command.
- **Step 2c, macOS advisory**: reads the headers of `GET /api/v1/companion/package/macos/current` (first byte, 15 s). Same version: "level with this repo". Different: warning with the Mac-side commands. 404: NOTE "no macos companion package published yet". Unreadable: "not checked". Never changes the exit code.
- **Step 3, local upgrade**: runs `installer\windows_upgrade.ps1 -CompanionExe companion\dist\ccsync-companion.exe`; failure refuses with "PUBLISHED and CURRENT for the fleet but is NOT installed here". Then runs `check_deploy_drift.ps1 -DashboardUrl` and echoes it; any DRIFT line about the installed version, no running process, the running process, or a newer exe on disk fails the ship (exit 1). Other drift lines are advisory.
- **Rollout line**: re-reads health and prints, per channel, "rollout: N of M computers on <version> (<platform>)", plus "K behind" and "K REFUSING it"; if unreadable, a NOTE that older dashboards do not report it. Ends by suggesting `check_deploy_drift.ps1 -AdminUser <user> -Watch`.
- **Exit codes**: 0 success, 1 any refusal or failure, 3 published-but-staged.
- **Cards deploy verdict helper** (in `ship_gates.ps1`, used by the drift doctor): given the Cards deploy record, the Timeline Cards repo head, its count of uncommitted files and whether the site has Timeline Cards, answers one of:
  - skip: "this site has no Timeline Cards ... nothing to check";
  - unknown: no record ("NOT CHECKED, not OK"), record with no commit (shipped as a DIRECTORY), or head unreadable;
  - drift: head moved ("<ref> is now <sha> (N commits), ahead of the shipped <short>") or uncommitted files ("THEY ARE NOT ON THE NAS. Commit them and re-ship.");
  - ok: shipped commit is still head and checkout clean.

## The tested Windows companion build
(source: tools/release.ps1)

- **Purpose**: builds the Windows companion exe from this checkout, after checks and tests, and writes a provenance manifest beside it. It never publishes or installs; it prints the next commands instead. It never runs a git write command.
- Lines are prefixed `[release] `; warnings `[release] WARNING:`; failures `[release] FAILED:`.
- **Flags**:
  - `-SkipTests`: skip both test suites; recorded as `tests_run=false`.
  - `-TestsGate ci`: only meaningful with `-SkipTests`; recorded as `tests_gate: "ci"` meaning "CI's test run vouches for this commit". Only `""` and `ci` are accepted.
  - `-AllowDirty`: shrinks the multi-line dirty-tree banner to one line; the manifest is stamped `+dirty` either way.
  - `-DryRun`: prints every step and exact command, builds and writes nothing; ends "dry run complete -- nothing was built, written, published, or installed".
  - `-DashboardUrl`: only used to print the publish command; falls back to `CCSYNC_DASHBOARD_URL`, then the placeholder `<your-dashboard-url>`.
- **Environment variables read**: `CCSYNC_SIGN_THUMBPRINT`, `CCSYNC_SIGN_PFX` (decide whether signing was intended), `CCSYNC_RELEASE_KEY` (signing key path, default `%USERPROFILE%\.ccsync-release\release.key`), `PROCESSOR_ARCHITECTURE` / `PROCESSOR_ARCHITEW6432` (build architecture: `arm64` if either is `ARM64`, else `x86_64`). It sets `CCSYNC_REQUIRE_RCLONE=1` for the suites and, when `ffmpeg` is on PATH, `CCSYNC_REQUIRE_FFMPEG=1`, restoring both afterwards.
- **Step 1/5, version parity**:
  - Reads the companion `VERSION` from `config.py` (refuses if unparseable), the `version` from `companion/pyproject.toml`, and the installer version from three places: `installer/windows_bootstrap.ps1`, `onboarding/steps.py`, `installer/macos_bootstrap.sh`. Prints all five.
  - Refuses, listing every mismatch, when pyproject differs from config, any installer copy is unparseable, or the Windows installer version differs from either other copy.
  - Refuses when the companion version is not exactly three dot-separated numbers ("does not look like 1.2.3 -- the dashboard refuses to publish anything else").
- **Vendored-file parity**: eleven source/copy pairs must be byte-identical (the copy may carry a header ending in the line `# --- vendored content below, byte-identical ---`, everything below which must equal the source; one pair must match whole-file). Pairs: ytdl `ytdl_common.py` into the companion; five b-roll local-model files (`local_models.py`, `local_runtime.py`, `local_vlm.py`, `compact_format.py`, `contract.py`) into the companion's `broll_vlm`; the indexing prompt `index_clip_v7_compact.md` (whole file); `normalize.py` from the b-roll indexer into `broll/web`; `identity.py` from ytdl into `broll/web` and into `music/web`; `music_models.py` and `mel_numpy.py` from the music indexer into the companion's `music_clap`.
  - A missing or unreadable file, a missing marker, or a marker appearing twice is a refusal, never a skip. A drift report gives byte counts and the first differing byte offset and approximate source line, names the source to edit, and how to recopy.
- **Release-key parity**:
  - Refuses when no public key (a base64 string of 40+ characters) is baked into `companion/src/ccsync_companion/release_pubkey.py`: "A companion built like this refuses EVERY update, permanently", with `release_key.py new` then `bake`.
  - Prints the number of baked keys and each key's id (first 16 hex digits of SHA-256 of the raw key).
  - If the signing key file exists, asks `release_key.py pubkey --quiet` and refuses when that public key is not among the baked ones ("Every editor would refuse the build you are about to publish"), suggesting `bake` or `bake --add`. If the key file is absent, only warns that publishing will fail.
- Reads optional `REQUIRES_DASHBOARD` from `config.py` and the dashboard `VERSION` (reported only, never enforced).
- **Dirty tree**: does not block. With `-AllowDirty` a one-line warning; otherwise a boxed banner, plus up to 12 uncommitted `companion/src` paths ("these WILL be baked into the exe") and "... and N more".
- **Step 2/5, install from the lock** (runs even with `-SkipTests`): creates `companion\.venv` with `python -m venv` if missing (refuses if that fails); installs `requirements.lock` with `--require-hashes` (refuses on failure, "regenerate the lock ... never edit it by hand"); installs the companion itself editable with `--no-deps` (refuses on failure, hinting a byte-order mark in pyproject); installs `pyinstaller==6.21.0` (refuses on failure).
- **Step 2/5, tests** (unless `-SkipTests`): companion then dashboard suites with each project's venv Python (falls back to `python` on PATH with a warning). Adds `-n auto --dist loadfile` (parallel) when the `xdist` plugin imports. Prints whether ffmpeg is a hard requirement or that media-job tests "will SKIP". A failing suite refuses ("NOT building").
- **Step 3/5, build**: `python -m PyInstaller build.spec --noconfirm` in `companion`; non-zero or no `companion\dist\ccsync-companion.exe` refuses.
- **Step 3a, frozen-content scan**: runs `tools/scan_frozen.py --component companion --workpath companion\build\build`; non-zero refuses before signing.
- **Step 3a2, launch test**: starts the built exe hidden with `--self-test --self-test-out companion\build\self-test.txt`, waits up to 180 s (kills and refuses on timeout), refuses on a non-zero exit quoting the result file, otherwise prints "self-test: <result>".
- **Step 3b, Authenticode signing**: always runs `tools\sign_windows_binary.ps1 -Path <exe>`; a non-zero exit refuses. Then reads the signature: `Valid` prints the signer subject; anything else prints a boxed "UNSIGNED BUILD" warning (SmartScreen, antivirus quarantine, buy a certificate, ship will refuse without `-AllowUnsignedBinary`).
- **Step 4/5, manifest** `companion\dist\ccsync-release.json` (UTF-8 without byte-order mark): `version`, `version_stamp` (version or version`+dirty`), `platform` `windows`, `artifact` `ccsync-companion.exe`, `sha256`, `size_bytes`, `built_at`, `artifact_mtime`, `git_commit` (short), `git_describe`, `git_dirty`, `tests_run`, `tests_gate`, `baked_pubkey_ids`, `requires_dashboard`, `arch`, `signed_binary`, `built_by` (`user@computer`), `built_with` `tools/release.ps1`. Warns when any companion source file is newer than the exe ("re-run"). Refuses if no exe exists (outside dry run).
- **Step 5/5, next steps** printed: A. publish with `installer\build_editor_package.ps1 -Publish -MakeCurrent` (showing the underlying `PUT /api/v1/admin/packages/windows/<v>?sha256=..&make_current=1` and `POST .../current`; a 409 means bump the version; extra warning for a dirty build); B. install locally with `installer\windows_upgrade.ps1 -CompanionExe <exe>`; then verify with `tools\check_deploy_drift.ps1`.
- Exits 0 explicitly on success.

## The macOS companion build and publish
(source: tools/release_macos.sh)

- **Purpose**: the Mac twin of the Windows build: parity checks, tests, PyInstaller, signature checks, manifest, and optionally a publish straight to one dashboard's upgrade channel. Runs only on macOS. Never runs a git write command.
- **Flags** (unknown flag prints usage and exits 1; `-h`/`--help` prints usage):
  - `--skip-tests`: skip the companion suite (`tests_run=false`).
  - `--tests-gate ci`: with `--skip-tests`, records that CI vouches; any value other than `ci` or empty refuses.
  - `--allow-dirty`: shrink the dirty banner to one line.
  - `--dry-run`: print steps, change nothing.
  - `--publish`: upload to the dashboard (prompts for the password).
  - `--make-current`: with `--publish`, ask that the build be offered at once.
  - `--dashboard-url <url>` (or `CCSYNC_DASHBOARD_URL`) and `--admin-user <name>` (or `CCSYNC_ADMIN_USER`): both required with `--publish`, refused before the build if missing.
- **Environment variables**: `CCSYNC_DASHBOARD_URL`, `CCSYNC_ADMIN_USER`, `CCSYNC_REQUIRE_FFMPEG` (if set by the caller it wins: a missing ffmpeg then fails the tests on purpose), `CCSYNC_APPLE_DEV_ID` (Developer ID signing identity), `CCSYNC_NOTARY_PROFILE` (stored notarisation credential profile), `CCSYNC_MIN_VERSION` (minimum version floor for the signed record; empty means the floor file), `CCSYNC_RELEASE_KEY` (via the signing tool).
- **Step 1/6, platform guard**: on macOS prints the machine architecture and OS version. On any other OS: with `--dry-run` continues in "INSPECTION MODE" (parity and provenance only, then exits 0 with "steps 3-6 ... are macOS-only"); without it refuses ("only runs on a Mac ... PyInstaller does not cross-compile").
- **Step 2/6, version parity**: refuses when `config.py` VERSION is unparseable, differs from pyproject, or is not `N.N.N`. Installer version drift among its three copies is only a warning here ("not this script's artifact").
- **Vendored-file parity**: ten pairs, refused on drift the same way as Windows (the ytdl file, the five `broll_vlm` files, the prompt whole-file, ytdl identity into music/web, the two music files). It does not check the two `broll/web` copies that the Windows build checks.
- **Dirty tree**: same banner behaviour as Windows, up to 12 uncommitted `companion/src` paths.
- **Step 3/6, environment and tests**: reuses or creates `companion/.venv` with `python3 -m venv` (refuses if no `python3`: "install the Command Line Tools (xcode-select --install) or python.org 3.12"); installs the lock with hashes, the companion with `--no-deps`, then `pyinstaller==6.21.0` (refuses on failure). Runs the companion suite with `CCSYNC_REQUIRE_RCLONE=1` and the ffmpeg rule; a failure refuses ("A missing rclone now FAILS rather than skipping").
- **Step 4/6, build**: PyInstaller `build.spec`; output `companion/dist/ccsync-companion` (a single binary), made executable. Refuses if PyInstaller fails or the file is absent. Then:
  - `tools/scan_frozen.py --component companion` (refuses on failure, before any signing).
  - Launch test `--self-test --self-test-out companion/build/self-test.txt` (refuses on non-zero exit). No timeout.
  - With `CCSYNC_APPLE_DEV_ID`: signs with `codesign --force --options runtime --timestamp` (refuses on failure or if `codesign` is missing). With `CCSYNC_NOTARY_PROFILE` too: zips with `ditto`, submits with `xcrun notarytool submit --wait` (refuses on failure), then tries to staple the ticket (a failure only warns, because a bare binary cannot hold one). Without the profile: warns "Developer ID SIGNED but NOT NOTARISED" with the one-time credential command.
  - Without a Developer ID: boxed "UNSIGNED BUILD (ad-hoc only)" warning about Gatekeeper's "cannot be opened because the developer cannot be verified".
  - Checks `codesign -dv`: a non-zero result refuses ("An unsigned binary is killed on launch on Apple silicon", with the re-sign command). `Signature=adhoc` forces the recorded `signed_binary` to false. No `codesign` only warns.
  - Reads the architecture with `file` (arm64, x86_64 or unknown; falls back to `uname -m`) and warns when not arm64.
- **Step 5/6, manifest** `companion/dist/ccsync-release.json`: same fields as Windows plus `platform` `macos`, `artifact` `ccsync-companion`, `arch`; `baked_pubkey_ids` is a comma-separated string here (an array on Windows); `built_with` `tools/release_macos.sh`. Warns when a source file is newer than the binary.
- **Step 6/6, publish**:
  - Without `--publish`: prints "NOTHING IS PUBLISHED YET" and the login + `PUT /api/v1/admin/packages/macos/<v>?kind=companion&sha256=..&make_current=1` it would do; exit 0.
  - With `--dry-run`: prints the login and PUT it would do; exit 0.
  - Refuses with no `curl` or no hash.
  - Signs the release record first with `tools/sign_release.py --artifact --kind companion --platform macos --version` plus `--signed-binary`, `--min-version`, `--requires-dashboard`, `--arch` (only x86_64, arm64 or universal2), `--git-sha`, `--git-dirty 0|1`. Refuses if signing fails ("The offline release key is missing on this Mac ... Nothing was uploaded"), if no query suffix comes back, or if the signed hash differs from the binary.
  - Warns when publishing a dirty build.
  - Uses a private temporary folder (mode 700, deleted on exit) for the cookie jar and response.
  - Pre-flight: reads `dashboard_token` from `~/.ccsync/config.toml`; if present asks for the first byte of `GET /api/v1/companion/package/macos/<v>` (20 s). 200/206 refuses ("ALREADY published for macos"); 404 prints "not on the server yet"; other codes warn and continue. With no token prints a NOTE and skips.
  - Password prompt "dashboard password for <user>@<url>: " (not echoed). Strips terminal bracketed-paste wrappers anywhere in the value. Refuses an empty password, and refuses a username or password with any control byte, naming its hex value and position ("retype it rather than pasting").
  - `POST /api/v1/login` with a JSON body built byte-safely (30 s); non-200 refuses showing the response; a response without `"is_admin": true` refuses ("is not a dashboard admin").
  - `PUT` the raw binary (600 s timeout) with `make_current=0|1` plus the signature query; prints up to 2000 characters of the response. 409 refuses ("already published ... Bump VERSION"); other non-200 refuses.
  - If the response carries a `note` (the dashboard published but would not make current), prints it and "push it to one Mac from Settings > Packages, leave it running, then [ MAKE CURRENT ] there"; otherwise prints "made it CURRENT" or "STAGED, not current".
  - Ends with "WHAT NEXT": confirm with `check_deploy_drift.ps1 -AdminUser`, Mac editors are offered (not pushed) the update on their next report, and this Mac keeps running `~/.local/ccsync/bin/ccsync-companion` until it takes the offer.

## The macOS first-run wizard build and publish
(source: tools/build_onboard_macos.sh)

- **Purpose**: builds `onboarding/dist/CCSync Onboarding.app` (bundling the already-built macOS companion), zips it, and optionally publishes it as the macOS `kind=onboard` package, which is what a Mac's INSTALLER download serves. Runs only on macOS (with `--dry-run` it inspects anywhere).
- Lines are prefixed `[onboard-build] `.
- **Flags**: `--dry-run`, `--publish`, `--make-current`, `--dashboard-url` (or `CCSYNC_DASHBOARD_URL`), `--admin-user` (or `CCSYNC_ADMIN_USER`); `-h`/`--help` and unknown flags print usage and exit 1. URL and user are required with `--publish` and refused before anything runs.
- **Environment**: `CCSYNC_APPLE_DEV_ID`, `CCSYNC_NOTARY_PROFILE`, `CCSYNC_MIN_VERSION`, `CCSYNC_RELEASE_KEY` (via the signer).
- **Platform guard**: off macOS without `--dry-run` refuses ("onboard.exe comes from installer/build_editor_package.ps1 on the base rig").
- **Version parity**: reads the installer version from `onboarding/steps.py` (refuses if absent), `installer/windows_bootstrap.ps1`, `installer/macos_bootstrap.sh`, and the bundle version `CFBundleShortVersionString` in `onboarding/build_onboard_macos.spec`. Refuses if the three installer copies differ, or if the bundle version is present and differs.
- **Bundled companion**: refuses when `companion/dist/ccsync-companion` is missing ("build it first: ./tools/release_macos.sh"; in dry run only notes it). If the companion manifest exists, refuses when its hash differs from the binary ("sha256 drift"), warns when the manifest stamp contains `+dirty` ("do not hand this wizard to an editor"). No manifest only warns.
- **Already-published pre-flight** (with `--publish`, before building): needs `curl`; reads `dashboard_token` from `~/.ccsync/config.toml`; asks for one byte of `GET /api/v1/companion/package/macos/<v>?kind=onboard` (20 s). 200/206 refuses, listing all four places to bump; 404 prints "not on the macos channel yet"; other codes warn and continue; no token prints a NOTE and skips.
- **Dry run** prints the PyInstaller, signature-verify, zip and round-trip steps (and the publish steps when `--publish`), then exits 0.
- **Build**: refuses when `companion/.venv/bin/python` is missing or cannot import PyInstaller ("run ./tools/release_macos.sh first"). Runs PyInstaller on `build_onboard_macos.spec`; refuses on failure or when the bundle folder is missing. Runs `scan_frozen.py --component onboarding --workpath onboarding/build/build_onboard_macos`; refuses on failure.
- **Signing**: with `CCSYNC_APPLE_DEV_ID`, signs the whole bundle deeply with hardened runtime and timestamp (refuses on failure or with no `codesign`); with `CCSYNC_NOTARY_PROFILE` also notarises (zip, submit and wait) and staples the ticket into the bundle; here a staple failure REFUSES (unlike the companion). Without a notary profile: warning "SIGNED but NOT NOTARISED". Without a Developer ID: boxed "UNSIGNED WIZARD (ad-hoc only)" warning.
- **Signature verification**: `codesign -dv` non-zero refuses; `codesign --verify --all-architectures --deep --strict` non-zero refuses ("A nested binary inside Contents/Frameworks is unsigned or modified ... Do NOT publish it"). No `codesign` only warns.
- **Zip**: `onboarding/dist/ccsync-onboard-macos-<version>.zip` made with `ditto`; prints its SHA-256. When `codesign` exists, unzips into a temporary folder and re-verifies deeply; any failure refuses ("the ZIP is what broke it ... Do NOT publish this zip").
- **Without `--publish`**: prints "BUILT, NOT PUBLISHED", the publish command, and hand-over advice (USB/AirDrop/scp; a quarantined copy needs System Settings > Privacy & Security > "Open Anyway"); exit 0.
- **Publish**: signs the record with `sign_release.py --kind onboard --platform macos` (optional `--signed-binary`, `--min-version`); refuses if signing fails, returns no query, or the signed hash differs from the zip. Same password prompt and login checks as the companion script. `PUT /api/v1/admin/packages/macos/<v>?kind=onboard&sha256=..&make_current=0|1` (600 s).
  - On 409, asks the server's stored hash via the `X-CCSync-Sha256` response header of a one-byte download with the admin cookie. Identical: "already published and is BYTE-IDENTICAL ... nothing to upload" (exit 0), with a NOTE that `--make-current` was not applied. Different: refuses, naming both hashes.
  - Other non-200 refuses. A `note` in the response is printed with "flip [ MAKE CURRENT ] ... when you are ready"; otherwise "made it CURRENT -- a Mac's [ INSTALLER ] click now downloads ccsync-onboard-<v>.zip" or "STAGED, not current". Always ends noting the Terminal route (`macos_bootstrap.sh`) still exists in the editor package.

## Signing one package record
(source: tools/sign_release.py, tools/release_floor.json)

- **Purpose**: produces the ed25519 signature over one package's record, just before an upload. Prints a JSON object (sorted keys, indented) with the record fields plus `signature`, `pubkey_id`, `query` (a ready-made, URL-encoded `&signature=..&pubkey_id=..&min_version=..&published_at=..&signed_binary=0|1` suffix plus any signed optional fields and any non-empty unsigned provenance), `git_sha`, `git_dirty`, `notes`.
- **The signed record** contains: `kind`, `platform`, `version`, `filename` (derived, see below), `sha256`, `size_bytes`, `min_version` (the downgrade floor), `published_at`, `signed_binary`; plus `runtime_id` for kind `dashboard`; plus `requires_dashboard` and `arch` only when given, non-empty and allowed.
- **Filename rule** (must match the dashboard's): dashboard kind `ccsync-dashboard-<v>.tar.gz`; Windows onboard `ccsync-onboard-<v>.exe`; macOS or Linux onboard `ccsync-onboard-<v>.zip` if the file starts with `PK`, else `.sh`; companion `ccsync-companion-<v>.exe` on Windows, no extension otherwise.
- **Flags**:
  - `--artifact <file>` (required; refuses if not a file; refuses an empty file, "nothing to sign").
  - `--kind companion|onboard|dashboard` (required).
  - `--platform windows|macos|linux` (required).
  - `--version` (required).
  - `--min-version`: default is the tracked floor for that kind and platform from `tools/release_floor.json` (or the file named by `CCSYNC_RELEASE_FLOOR_FILE`), else `0.0.0`. Printed to standard error as "min_version (downgrade floor) stamped".
  - `--allow-no-floor`: permit a companion or onboard record with floor `0.0.0` (refused otherwise: "NO downgrade floor ... any older signed build could then be made current by a replayed channel or a compromised admin session").
  - `--published-at`: default now (UTC, whole seconds).
  - `--signed-binary`: the artefact carries a real Authenticode or Developer ID signature.
  - `--runtime-id`: required for kind `dashboard` (refused without it).
  - `--requires-dashboard`: oldest dashboard version this build works with; must be dotted-numeric.
  - `--emit-kind-extras` (or environment `CCSYNC_EMIT_KIND_EXTRAS=1`): actually sign `requires_dashboard` and `arch`. Without it, any given values are dropped with a NOTE that they were not signed ("older builds refuse a record that carries them").
  - `--arch` one of `x86_64`, `arm64`, `universal2` or empty.
  - `--git-sha`, `--git-dirty 0|1`: unsigned provenance.
  - `--notes`: unsigned one-line note (falls back to `CCSYNC_RELEASE_NOTES`), whitespace collapsed, cut to 300 characters.
  - `--key <file>`: release key (default as in the key tool).
  - `--out <file>`: also write the JSON there.
- **Refusals**: floor not dotted-numeric; floor ABOVE the version (explains that companions raise their floor on sight, so the record would refuse itself and every corrected republish); `--requires-dashboard` given while the record type does not cover it; the record definition naming a mandatory field this signer cannot fill; a signature that does not verify locally.
- `--arch` given for a record type that does not cover it is dropped with a NOTE (build offered to every machine of the platform).
- After signing, NOTEs on standard error: when the floor is `0.0.0` ("this release sets NO downgrade floor"); when `signed_binary` is false ("SmartScreen/Gatekeeper are not satisfied").
- **Tracked floor file** `tools/release_floor.json`: companion windows 0.9.75, macos 0.9.75; onboard windows 1.0.44, macos 1.0.44. Its comment says to keep it at or below the current build, trailing by a release, and that the owner must pick launch values before the beta.

## The offline release key
(source: tools/release_key.py)

- **Purpose**: create, protect, back up and read the release signing key, and bake its public half into the companion source.
- **Key file**: default `~/.ccsync-release/release.key` (Windows: `%USERPROFILE%\.ccsync-release\release.key`), or `CCSYNC_RELEASE_KEY`, or the global `--path` flag. Lines beginning `#` are comments. Two formats:
  - v1 plaintext: `ccsync-release-key-v1 <base64 of the 32-byte seed>` (a bare base64 seed line is also accepted).
  - v2 encrypted: `ccsync-release-key-v2 <base64 JSON envelope>` holding the public key in the clear, a scrypt salt and cost (N = 2^17, r = 8, p = 1, about 128 MiB of memory), a nonce, the encrypted seed and an HMAC-SHA256 tag. A file declaring a cost above N 2^22, r 32 or p 8 is refused ("implausible scrypt cost").
- **Passphrase**: from `CCSYNC_RELEASE_KEY_PASSPHRASE` if set, else asked once per process on the terminal ("release key passphrase for <file>: "), never echoed. With no interactive console it refuses ("there is no terminal to ask on"). Minimum 12 characters when encrypting. Unicode-normalised before use.
- Loading a plaintext key for signing prints, once per process, "WARNING: the release key <path> is UNENCRYPTED ... Protect it now: python tools/release_key.py encrypt". A wrong passphrase or altered file: "cannot unlock <path>: wrong passphrase, or the key file was altered". A damaged encrypted line: "looks like an encrypted release key but is damaged -- restore it from your offline backup". A missing file: "no release key at <path> ... Generate one: python tools/release_key.py new".
- **Subcommands**:
  - `new [--force]`: generates a random 32-byte seed and writes a plaintext v1 file with owner-only permissions, never overwriting by accident. If a key exists, refuses without `--force` ("Overwriting it orphans every build the fleet was ever offered"); with `--force` moves the old one to `release.key.superseded` first. Prints the public key and id. If `--force` replaced the key every signer reads, prints "THE NEW KEY NOW SIGNS EVERYTHING ... wrong order" for rotations. If written at a side path while the signing key exists, prints the rotation recipe (`--path <side> bake --add`). Otherwise prints "Next: ... bake". Always ends with "THEN PROTECT IT" (encrypt) and "BACK IT UP NOW" instructions.
  - `pubkey [--quiet]`: prints the public key and its id (first 16 hex digits of SHA-256 of the raw key) and a note that the dashboard verifies against `DASH_RELEASE_PUBKEYS`; `--quiet` prints only the key. Never asks for the passphrase of an encrypted key.
  - `trusted [--quiet]`: lists the signing key plus `release-next.key` and `release.key.superseded` if present beside it (rotation neighbours), without duplicates, one per line as `<id> <file> <key>`, then the comma-joined value for `DASH_RELEASE_PUBKEYS`. `--quiet` prints only the comma-joined list. An unreadable neighbour refuses.
  - `bake [--add] [--target <file>]`: rewrites the `RELEASE_PUBKEYS` list in `companion/src/ccsync_companion/release_pubkey.py` (or the target). Without `--add` the list becomes just this key; with `--add` this key first, then the existing ones. Already identical: "nothing to do". List not found: "edit it by hand" (exit 1). Replacing keys prints "EVERY MACHINE ON THE CURRENT BUILD WILL REFUSE THIS BUILD" and the rotation advice. Always reminds to rebuild.
  - `backup --to <file or folder> [--force]` or `backup --print`: one of `--to` / `--print` is required. Plaintext key: `--print` prints the key line under "THIS LINE IS THE PRIVATE KEY"; `--to` writes a copy (refuses to overwrite without `--force`) and says the file IS the key. Encrypted key: copies or prints the encrypted line as it is (no passphrase needed) and says to keep the passphrase elsewhere. Either way records `backed_up_at`, `where` and `pubkey_id` in `backup.json` beside the signing key (any other key file gets `<name>.backup.json`), and tells the operator to click SETTINGS > PROTECTION > [ I HAVE BACKED IT UP ] on the dashboard.
  - `status`: prints `encrypted`, `plaintext`, or `missing` (exit 1). Never asks for the passphrase.
  - `check`: decrypts once (asking, or from the environment); prints `ok` (exit 0), or `missing` or the error (exit 1).
  - `encrypt`: already encrypted prints "nothing to do". Otherwise asks the passphrase twice ("type it again: "; a mismatch refuses), refuses one shorter than 12 characters, writes the encrypted file under a temporary name, verifies it decrypts to the same seed and public key (else "the plaintext key is UNTOUCHED"), swaps it in, overwrites the old plaintext copy with random bytes and deletes it. Prints next steps: two offline copies, write the passphrase down elsewhere, destroy older plaintext copies, and encrypt any rotation neighbour files too.

## The vendor release feed: build, sign, publish, recall
(source: tools/publish_feed.py)

- **Purpose**: maintains the vendor feed every customer dashboard reads: a local feed folder holding `channel.json` (the signed manifest), `channel.json.sig` (a detached ed25519 signature over it), `<platform>/<file>` artefacts, and flat non-package files; optionally uploads it to a GitHub release with the `gh` command-line tool. Nothing leaves the machine without `--github-upload`.
- Lines are prefixed `[publish-feed] `; failures print `[publish-feed] FAILED: <reason>` to standard error.
- **Channel document**: `schema` 1, `channel` name (default `stable`), `generated_at`, `pubkey_id`, `dashboard_image` (`tag`, `digest`, optional `sftp_digest`), `packages` (signed records each with `signature`, `pubkey_id`, `url`, `notes`, optional unsigned `git_sha`, `git_dirty`, `baked_pubkey_ids`), optional `artefacts` (non-package files: kind, version, filename, sha256, size_bytes, url), optional `current` map (`"<kind>/<platform>": "<version>"`), optional `retracted` recall list (kind, platform, version, reason, at). The whole document is signed with a `ccsync-channel-v1` prefix.
- **Exit codes**: 0 OK; 2 usage or any refusal; 3 the build manifest condemns the build; 4 self-verification failed (also `--verify` failure); 5 upload failed or the live channel could not be read.
- **Flags**:
  - `--artifact <file>`, `--manifest <ccsync-release.json>` (fills version, platform, artefact path, signed flag, requires-dashboard, arch, git sha and dirty flag, baked key ids).
  - `--kind companion|onboard|dashboard` (default companion), `--platform windows|macos|linux`, `--version`.
  - `--min-version` (default: the tracked floor file), `--allow-no-floor`, `--allow-floor-above-current`, `--allow-floor-drop`.
  - `--published-at`, `--runtime-id` (dashboard bundles), `--signed-binary`, `--notes`.
  - `--feed-dir` (required unless `--verify`), `--base-url`, `--github-repo OWNER/REPO`, `--github-tag` (default `ccsync-releases-v1`), `--github-upload`, `--channel` (default `stable`).
  - `--asset <file>` (repeatable), `--asset-kind` (only `music-clap-audio`), `--asset-version`.
  - `--make-current`, `--set-current KIND/PLATFORM/VERSION`, `--retract KIND/PLATFORM/VERSION`, `--reason`, `--allow-no-current`.
  - `--requires-dashboard`, `--arch`, `--git-sha`, `--git-dirty`, `--baked-pubkey-ids`.
  - `--allow-key-rotation`, `--allow-shrink`, `--allow-replace`, `--allow-red-ci`, `--allow-dirty`, `--allow-untested`.
  - `--set-image tag@digest`, `--set-sftp-digest sha256:...`.
  - `--verify <feed dir>`, `--key <file>`, `--dry-run`.
- **`--verify`**: checks the channel signature and every package record's signature against the public keys baked into this checkout's companion; for each record whose artefact is present locally, checks its SHA-256; for each non-package file present, checks hash and size. Prints one line per check ("artifact not present locally (fine if already uploaded)" when absent) and "VERIFY OK" or "VERIFY FAILED".
- **GitHub repository and URL**: `--github-upload` without `--github-repo` refuses. The repository must be `OWNER/REPO`. The base URL is derived as `https://github.com/<repo>/releases/download/<tag>`; a different `--base-url` refuses. Record URLs are flat (`<base>/<filename>`) for GitHub and `<base>/<platform>/<filename>` for other hosts.
- **Manifest gate**: a manifest with `git_dirty` true refuses (exit 3) without `--allow-dirty`. `tests_run` false refuses (exit 3) without `--allow-untested` unless CI vouches for that commit (see the CI vouching rule in the next section). A manifest platform is lower-cased; one not in windows/macos/linux refuses. A manifest arch is normalised (`amd64`/`x64` to x86_64, `aarch64` to arm64, `universal` to universal2); anything else is dropped with a NOTE.
- **Live channel as the base** (with `--github-upload`): first runs `gh auth status` (missing `gh` or not signed in refuses, exit 5, "The feed directory is already written and signed; nothing was uploaded"). Downloads the live `channel.json` and `.sig` from the release. If absent ("no assets match", "release not found", "not found"), treats it as the first publish. Any other failure refuses to upload (it cannot tell empty from unreachable). A live channel that does not verify against this checkout's baked keys refuses ("Either the feed was tampered with, or it was signed by a key this checkout does not know"). Otherwise prints the record and artefact counts and merges this machine's local feed on top: local records replace same-key records, nothing published is dropped, the image and `current` entries overlay, recalls are only ever added. These upload refusals are raised only after the local feed folder has been written and signed.
- **`--retract`**: needs `KIND/PLATFORM/VERSION` and a non-empty `--reason` (refused otherwise: "every customer dashboard shows it beside the withdrawn build"). Adds or replaces a signed recall entry with the reason and time, removes the record and any `current` pointer at it (the asset stays on the release), prints "RETRACTED ..." or a NOTE that the record was not on the channel but the recall is published anyway. If it removed the current pointer and nothing else in the run sets one, it refuses unless `--allow-no-current`, explaining that dashboards would take the highest remaining version (possibly a newer staged one) and suggesting the newest version below the withdrawn one.
- **`--set-current`**: needs three parts. Refuses if the channel carries no such record (lists the versions it does carry), if the build is on the recall list, or if the record's signing key is not among the keys baked into the build currently pointed at (unless `--allow-key-rotation`). Refuses when combined with `--make-current` for the same kind and platform. Moves the pointer only ("pointer only, no artifact uploaded").
- **Publishing an artefact** (`--artifact` or via manifest):
  - Requires platform, version and a base URL; refuses if the file is missing.
  - For dashboard bundles, reads the bundle's own `manifest.json` for `runtime_id`, git commit and dirty flag; a `--runtime-id` that disagrees with the bundle refuses.
  - **CI gate** (only for `--github-upload` with `--make-current`, unless `--allow-red-ci`): refuses when the build names no git sha or is dirty; expands a short sha to the full commit (unresolvable refuses); refuses when the commit has no successful `ci.yml` run or GitHub cannot be asked; refuses when the commit is not an ancestor of the remote release branch (`main`). Message prefix "REFUSED (GL-25):".
  - Signs the record in-process with the same signer as `sign_release.py`.
  - **Key-rotation check**: when the currently pointed build records its baked key ids and this record's key is not among them, refuses (without `--allow-key-rotation`) with a long explanation: every machine on the current build will refuse it; if this build bakes both keys it is the overlap release and must be signed with the OLD key; the flag "does not perform a rotation". With the flag, warns. When the current record carries no key ids, NOTE that the check could not run.
  - Refuses re-publishing a recalled version (unless retracted in this same run).
  - Refuses the same kind/platform/version with different bytes (shows both hashes) without `--allow-replace`.
  - Refuses a floor below the highest floor already published for that kind and platform without `--allow-floor-drop`.
  - For companion and onboard, refuses a floor above the currently pointed version without `--allow-floor-above-current`.
  - Adds or replaces the record; with `--make-current` sets the pointer; copies the artefact into `<feed-dir>/<platform>/<filename>` (not in dry run).
- **`--asset`**: needs a base URL and `--asset-version` (refused otherwise) and an existing file; records kind, version, filename, hash, size and flat URL; prints its size and hash prefix and a reminder that the companion checks this hash against the one baked into its own build; copies it into the feed folder root.
- **`--set-image`**: must contain `@`; sets `dashboard_image` tag and digest (plus `sftp_digest` if given).
- With none of artefact, asset, set-current, set-image or retract: refuses "nothing to do".
- **`--dry-run`**: prints the full channel it would write and stops (nothing written or uploaded).
- **Shrink guard**: when a live channel was read, refuses (without `--allow-shrink`) any upload that would remove a published package or artefact other than one deliberately retracted, listing each.
- **Timestamp**: `generated_at` is now, or one second after the newest timestamp already published if the clock is behind; if the published one is more than 60 s ahead, prints a WARNING to fix that clock.
- **Writing**: signs the channel with the release key, verifies the signature immediately (exit 4 if not), writes `channel.json` (indented) and `channel.json.sig`, prints the count.
- **Upload** (`--github-upload`): refuses if any record or artefact's signed URL is not `<base>/<filename>`, or two share a filename. Creates the release if missing (title "CC Sync release feed (<tag>)"; "already exists" counts as success). Lists the release's existing assets (name, size, state, digest) and skips any file whose size matches, whose state is `uploaded`, and (when GitHub reports one) whose SHA-256 digest matches; always uploads the channel, its signature and the package signed in this run. Prints how many were skipped. Uploads with `gh release upload --clobber`; failure exits 5 ("may now be PARTIALLY updated; re-run"). Prints the count and "feed URL for DASH_RELEASE_FEED_URL: <base>/channel.json". Notes any package file not in the local folder ("assuming the release already carries it").
- Without upload: prints "built only -- add --github-upload" (when a repo was given), or that nothing was uploaded with an `rclone sync <feed-dir> remote:ccsync-releases --checksum` example.

## Publishing the newest green CI build to the vendor feed
(source: tools/publish_latest.py)

- **Purpose**: on the base rig, takes the newest successful CI release build of each companion and installer artefact from GitHub Actions, verifies it, and publishes it to the vendor feed through `publish_feed.py`. It must not run in CI (the key never leaves the rig). Lines are prefixed `[publish-latest] `; failures `[publish-latest] FAILED: ...` with exit 1.
- **Fixed settings**: feed folder `<repo>/feed`; feed repository `The-Creators-Club/ccsync-releases`; release branch `main`; CI workflow `ci.yml`.
- **Sources** (four): Windows companion and Windows installer from `release-windows.yml`; macOS companion and macOS installer from `release-macos.yml`; manifests `ccsync-release.json` (companion) and `ccsync-onboard.json` (installer). The dashboard is deliberately not included.
- **Flags**:
  - `--kind companion|onboard`, `--platform windows|macos`: narrow the sources (no match refuses).
  - `--dry-run`: download and verify, print the `publish_feed.py` command, sign and upload nothing.
  - `--force`: publish even if that version is already on the feed.
  - `--make-current`: also move the `current` pointer.
  - `--allow-older`: publish a CI build older than the newest on the channel.
  - `--min-version`: floor passed through.
  - `--notes`: one-line note (whitespace collapsed, 300 characters).
  - `--allow-behind`: publish a companion needing a newer dashboard than any bundle on the channel.
  - `--allow-red-ci`: publish despite no green `ci.yml` run (passed through to `publish_feed.py` too).
  - `--sha <full sha>`: only builds from this commit; a missing run for it is a refusal, not a skip.
  - `--allow-no-floor`, `--allow-floor-above-current`, `--allow-key-rotation`: passed through.
- **Environment**: `CCSYNC_EMIT_KIND_EXTRAS` (decides whether the dashboard-ordering check applies); `CCSYNC_RELEASE_KEY_PASSPHRASE` (set for child processes by the unlock).
- **Preflight**: refuses with no `gh` on PATH, with `gh` not authenticated, or with no key at `~/.ccsync-release/release.key` (this path only; "Do NOT run `release_key.py new`"). Unlocks an encrypted key once (prompting) before anything is downloaded.
- **Release branch tip**: asks the remote (`git ls-remote origin refs/heads/main`), fetches if this clone lacks that commit, refuses if the remote cannot be read ("refusing to sign against a possibly stale local ref"). Prints "origin/main is at <sha>".
- **Live channel**: downloads and verifies the published channel; a channel that cannot be read or does not verify refuses; absent means empty.
- **Per source**:
  - Finds the newest successful run of the workflow on `main` (optionally for `--sha`). None: "no successful <wf> run yet -- skipping".
  - Refuses if the run's commit is not an ancestor of the remote tip ("A force-push can remove a commit CI went green on").
  - Refuses if that commit has no successful `ci.yml` run (once per commit), unless `--allow-red-ci` (then a WARNING).
  - Downloads the run's artefacts once per run (`gh run download`); a failure (usually expired artefacts) skips that source.
  - Finds the manifest; missing skips. Verifies the artefact beside it hashes and sizes as the manifest says (refuses a mismatch: "refusing to sign a mismatch").
  - Refuses when the manifest platform differs from the expected one, when the build is dirty, or when tests were skipped and CI does not vouch for it (the CI vouching rule: `tests_run` false is acceptable only with `tests_gate` `ci`, a clean tree, a resolvable commit, and a successful `ci.yml` run on that exact commit; prints "tests: skipped in the build, vouched for by a green ci.yml run").
  - Dashboard ordering: if the manifest names `requires_dashboard` but kind extras are not being signed, prints a NOTE that customers get no ordering check; if the channel has no dashboard bundle, a NOTE; if the required dashboard is newer than the newest dashboard bundle on the channel, refuses without `--allow-behind`.
  - Already on the channel (without `--force`): without `--make-current` or when already current, "nothing to do"; when older than the current version, does not move the pointer back (points to `publish_feed.py --set-current` for a rollback); when the channel holds different bytes for that version, prints the exact `--set-current` command to make the staged record current instead; otherwise moves the pointer only (NOTE that `--min-version` / `--notes` are not applied to an existing record).
  - Refuses a version older than the newest on the channel without `--allow-older`.
  - Otherwise runs `publish_feed.py --manifest --artifact --kind --feed-dir --github-repo [extras] --github-upload` and shows its output.
  - UNREACHABLE: a WARNING about moving the dashboard pointer exists for kind `dashboard`, but no source and no `--kind` value can be `dashboard`.
- **Summary**: the tip compared against, each published and skipped item. After a real publish: with `--make-current`, explains that sites on `policy = current` take it on their next check (daily by default; 10 s after a container restart) subject to their own soak gate, sites on `manual` need Settings > Packages > "Check now" > "Publish", and the first dashboard bundle with the CLI lock must go through `install_dashboard_app.py`; without it, "published and STAGED". Prints a ready-to-run recall command per published record (`--retract`, with `--set-current <previous>` or `--allow-no-current` when it was made current).
- A per-job CI check helper exists here (which `ci.yml` jobs did not succeed on a commit) and is used by the customer release tool.

## The customer release: one gated event from one green commit
(source: tools/release_customers.py)

- **Purpose**: releases dashboard, companion and installers to customers together, from one commit on `main`. Lines are prefixed `[release-customers] `; any refusal prints `[release-customers] REFUSED: <reason>` and exits 1.
- **Flags**:
  - `--sha <40-char commit>`: default the remote `main` tip; anything not 40 characters refuses.
  - `--dry-run`: verify and print the plan; tags, publishes and edits nothing (still runs `publish_latest.py --dry-run`).
  - `--image-timeout <s>`: default 3600; how long to wait for the image build.
  - `--poll <s>`: default 30.
  - `--no-compose-pin`: do not rewrite the appliance compose file.
  - `--soak-hours <h>`: default 24.
  - `--allow-unrun-ci-jobs`: release although the CI `linux` job did not run to success.
  - `--allow-no-soak`: skip the studio soak (prints a WARNING).
  - Any other flag is passed through unchanged to `publish_latest.py`.
- **Environment**: `CCSYNC_STUDIO_URL` and `DASH_REPORT_TOKEN` (studio dashboard and fleet token for the soak check), `CCSYNC_SOAK_LEDGER` (soak ledger path, default `~/.ccsync/release_soak.json`).
- **Steps and refusals, in order**:
  1. Preflight as in `publish_latest.py` (gh present and signed in, key present and unlocked); remote tip readable.
  2. Reads and verifies the live channel.
  3. Refuses when the commit is not an ancestor of remote `main`; when it has no successful `ci.yml` run; when the CI run's `linux` job (and every leg of it) did not succeed or could not be read ("a skipped job leaves the run green ... nothing has tested this dashboard"), unless `--allow-unrun-ci-jobs` (then a WARNING); when the dashboard `VERSION` at that commit cannot be read; when that version is older than the newest dashboard bundle on the channel ("That is a rollback, not a release"); when any of `release-dashboard.yml`, `release-windows.yml`, `release-macos.yml` has no successful run for that commit (with the `gh workflow run` command to dispatch it).
  4. Tag `v<dashboard version>`: asks the remote; a tag on a different commit refuses ("An immutable tag is never moved").
  5. The GitHub environment `customer-release` must exist and have required reviewers; otherwise refuses (it explains that GitHub would auto-create it unprotected and promote with no approval). Not being able to ask refuses.
  6. **Studio soak** (unless `--allow-no-soak`): needs the two environment variables (refuses without them). Reads the studio dashboard's `/api/v1/health` with the fleet token, following no redirect. Refuses when the studio runs a different dashboard version, or reports a different or unknown commit. The first time it sees `<version>@<commit>` it records the time in the ledger and refuses ("soak clock ... starts now; re-run in 24 h"); later runs refuse until the configured hours have passed, saying how many remain. A dry run does not write the ledger.
  7. Prints commit, version and tag state, and what was verified.
  8. Downloads the `ccsync-dashboard-bundle` artefact of the dashboard release run; refuses if it cannot (expired), has no `ccsync-dashboard-*.tar.gz`, has no readable `manifest.json`, was built dirty, from another commit, or carries another version.
  9. Refuses when that version is on the channel's recall list, or already on the channel with different bytes ("The studio soak must use the exact CI artefact").
  10. Dry run stops here after printing the plan and running `publish_latest.py --sha --make-current --dry-run`.
  11. If the tag is absent, creates an annotated tag "Customer release <version>" and pushes it (failure refuses); "image.yml is building and will wait for approval".
  12. Polls the `image.yml` run for that tag and commit every poll interval until completed; a non-success conclusion refuses; past the timeout refuses ("It may be waiting for the `customer-release` environment approval ... the tag is already pushed"). Downloads the `image-digests` artefact's `digests.json`; refuses if missing, if any of `version`, `image`, `digest`, `sftp_digest` is empty, or if a digest is malformed.
  13. Publishes the dashboard bundle with `publish_feed.py --kind dashboard --platform linux --make-current --git-sha --set-image <version>@<digest> --set-sftp-digest <digest> --github-upload`; failure refuses ("the companion and installers were NOT published").
  14. Runs `publish_latest.py --sha <commit> --make-current` plus pass-through flags; failure refuses, noting the dashboard half is already published and how to re-run the client half.
  15. Unless `--no-compose-pin`, rewrites the appliance compose file to the version and both digests and prints "COMMIT IT".
  16. Ends: "done. Next: a fresh appliance install against the vendor feed ... and `python tools/check_feed_freshness.py`."

## Pinning the appliance compose file to image digests
(source: tools/pin_compose_images.py)

- **Purpose**: rewrites `dashboard/deploy/compose.appliance.yaml` so the two vendor images (the lines whose image comes from `CCSYNC_IMAGE` and `CCSYNC_SFTP_IMAGE`) read `repo:<version>@sha256:<digest>`. Other images are left alone.
- **Flags**: `--compose <file>` (default the appliance compose file), `--version`, `--dashboard-digest`, `--sftp-digest`, `--check`.
- `--check`: lists every vendor image reference that carries no digest ("vendor images NOT pinned by digest: ...", exit 1) or prints "every vendor image is pinned by digest" (exit 0).
- Pinning refuses (exit 2, `[pin-compose] FAILED:`) when the version is not `N.N.N`, a digest is not `sha256:` plus 64 hex characters, or no matching image line exists. Writes only when the text changed, keeping line endings; prints "pinned to <version> (<digest prefix>...)".

## Checking the customer channel is not stale
(source: tools/check_feed_freshness.py)

- **Purpose**: reads the published vendor channel (signature verified with this checkout's baked keys) and fails when it trails `main`.
- **Flags**: `--repo` (default `The-Creators-Club/ccsync-releases`), `--max-behind` (default 3), `--max-age-days` (default 45).
- **Exit codes**: 0 fresh ("fresh: channel dashboard X vs main Y"); 1 stale (lists each problem under "STALE (main dashboard <v>):"); 3 "NOT CHECKED" when the channel cannot be read or does not verify (an absent channel also counts as not checked).
- **Problems it reports**:
  - no current `dashboard/linux` at all;
  - the current dashboard is more than the allowed number of patch releases behind this tree's dashboard `VERSION` (a different major.minor always counts as far behind), "run tools/release_customers.py";
  - a current dashboard with no `dashboard_image` digest starting `sha256:`;
  - a current companion or onboard record whose `requires_dashboard` is newer than the current dashboard;
  - the channel generated more than the allowed days ago while the tree's dashboard is newer.

## Publishing one prebuilt package to one dashboard
(source: tools/publish_package.py)

- **Purpose**: uploads one already-built file (companion, onboard or dashboard kind) to one dashboard's upgrade channel, without building. Lines prefixed `[publish] `; failures `[publish] FAILED: ...`.
- **Flags**: `--artifact`, `--manifest` (fills version, platform, artefact, hash, signed flag), `--kind` (default companion), `--platform`, `--version`, `--min-version` (default: the tracked floor file), `--allow-no-floor`, `--signed-binary`, `--make-current`, `--dashboard-url` (or `CCSYNC_DASHBOARD_URL`), `--admin-user` (or `CCSYNC_ADMIN_USER`), `--key`, `--password-stdin`, `--allow-dirty`, `--allow-untested`, `--dry-run`.
- **Exit codes**: 0 OK, 2 usage, 3 already published, 4 login, 5 publish or unreachable dashboard.
- **Steps and refusals**:
  - Manifest: refuses a dirty build without `--allow-dirty`; refuses `tests_run` false without `--allow-untested` unless CI vouches for the commit (same rule as `publish_latest.py`).
  - Refuses when artefact, platform, version, URL or admin user is missing; when the URL is not `http://` or `https://`; when the file is missing; when its hash differs from the manifest's.
  - Signs the record first (a missing or unreadable key refuses, "Nothing was uploaded"); refuses if the signed hash differs. Prints kind, platform, version, size, hash prefix, key id, floor and signed flag.
  - `--dry-run`: prints the PUT and login it would do, and stops.
  - Pre-flight (only when `DASH_REPORT_TOKEN` is set): one-byte download of the package with the fleet token (20 s); existing refuses (exit 3); otherwise prints the state (`absent`, `unknown:<code>`, `unknown:no-token`).
  - Password: from the terminal (hidden), or one line of standard input with `--password-stdin`; with no terminal and no flag refuses ("never argv, never the environment"). An empty password or one with a control character below 0x20 refuses.
  - `POST /api/v1/login` (30 s); non-200 or a non-admin account refuses (exit 4).
  - `PUT /api/v1/admin/packages/<platform>/<version>?kind=..&sha256=..&make_current=0|1&<signed query>` (600 s). 409 refuses (exit 3); other non-200 refuses (exit 5). Prints "CURRENT" or "STAGED (not current -- flip [ MAKE CURRENT ] on the admin page)".
  - Reads back `GET /api/v1/admin/packages` and prints the matching row (first 400 characters), or a NOTE to check the admin page.
  - Never follows a redirect; an unreachable dashboard refuses with "Check it is up, then re-run".

## The deploy drift doctor
(source: tools/check_deploy_drift.ps1, tools/ship_gates.ps1)

- **Purpose**: a read-only Windows report answering "which build is actually running here and being offered to the fleet?". Changes no file, registry entry, process or git state; network use is GETs plus one login POST with `-AdminUser`. Always exits 0 (drift is shown in the report, never in the exit code).
- **Flags**: `-DashboardUrl` (default `dashboard_url` from `~/.ccsync/config.toml`, then `CCSYNC_DASHBOARD_URL`), `-AdminUser` (log in for admin-only facts; prompts "dashboard password for '<user>'", hidden), `-Quiet` (drop the footer "Nothing was changed by this check. Runbook: docs\RELEASE.md"), `-Watch` (follow the rollout).
- **Environment**: `CCSYNC_SITE` (site file, default repo `site.toml`), `CCSYNC_DASHBOARD_URL`, `CCSYNC_CARDS_RECORD` (Cards deploy record, default `~/.ccsync/state/cards_deployed.json`).
- Line markers: `OK` (green), `DRIFT` (yellow), `?` (grey, "not checked").
- **REPO section**: companion `VERSION`, pyproject version, three installer version copies, dashboard `VERSION`, `[stack] mode` (default `bind`) and, in image mode, `[stack] image` (default `ghcr.io/the-creators-club/ccsync:1`) with a `?` when it is pinned by tag not digest; `git describe`. OK or DRIFT for companion version parity and installer version parity.
- **BUILT section** (`companion\dist\ccsync-companion.exe`): path, build time and age, size, SHA-256; manifest version, commit and build time. DRIFT when the manifest hash differs from the exe ("rebuilt without tools/release.ps1?"); DRIFT when built with tests skipped, except when `tests_gate` is `ci` (then "left to ci.yml"); `?` when there is no manifest; DRIFT "STALE" when any companion source file is newer than the exe, else OK. `?` when there is no built exe.
- **INSTALLED section** (`%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe`): path, time, size, hash. Installed version is taken from, in order: byte-identity with the built exe; the `ccsync-release.json` beside the installed exe (if its hash matches; a mismatching one is reported and ignored); `~/.ccsync/state/last_version.txt`; the last "ccsync-companion vX.Y.Z starting" line in `~/.ccsync/companion.log`; hash equality with the build. The row names which source was used, or `?` if none.
  - Process: running with process id and start time, or DRIFT "no ccsync-companion process is running on this machine"; DRIFT "the running process is <path> -- NOT the exe inspected above"; DRIFT "the exe on disk is NEWER than the running process".
  - Autostart: the `CCSyncCompanion` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`; DRIFT when missing or pointing elsewhere.
- **DASHBOARD section**: `?` when there is no URL. Reads `/api/v1/site` (8 s) for `nas_kind` and site name and prints the expected container name (`ix-ccsync-dashboard-1` on TrueNAS, else `ccsync-dashboard-1`). Reads `/api/v1/health` (8 s) for the live version and, if present, `syncthing_reachable` and `collector_stale`. OK when live equals repo; otherwise DRIFT with the bind-mode remedy ("docker compose up -d --build") or the image-mode remedy (new image or signed bundle; "Re-shipping the host code trees would change nothing"). In image mode prints that the host code trees are unused and are the rollback.
- **With `-AdminUser`** (after a successful admin login; a non-admin gives `?`):
  - Authenticated health `code` block: live code source, running and image versions, runtime id. DRIFT when image mode runs a developer checkout, when bind mode carries an image runtime id, or when image mode has no runtime id. `?` for an older dashboard.
  - Packages: current Windows package and all published Windows versions (current marked `*`); OK or DRIFT against the repo version. For the current Windows companion: its release signature (key id and floor) OK, or DRIFT "UNSIGNED -- companions that verify will REFUSE it"; Authenticode OK or DRIFT. Current Windows installer: version and Authenticode OK/DRIFT, or `?` when none is published.
  - macOS: current package, published companion and onboard versions; advisory OK/DRIFT against the repo ("run tools/release_macos.sh on the Mac (advisory)").
  - ROLLOUT section: per channel "<platform>: N of M on <version>", who is behind (editor, machine, version, how long since last seen), revert and failed-attempt counts, how long it has been current, and each refusing machine with its reason. OK when every machine is on it and none refuses, else DRIFT, plus a hint to use `-Watch`. `?` for a dashboard with no rollout numbers, or when nothing is current.
  - PACKAGE CHANNEL: one DRIFT line per outdated machine.
- **TIMELINE CARDS section**: shown when a deploy record exists, is unreadable, or the site has `[timeline_cards] src` or `enabled` (not "false"), or the record variable is set. Prints the deployed commit, subject, source repo and shipped time (or the directory override). If the Cards repo exists locally, compares the deployed commit with the head of its ref (default `main`), counts commits ahead and uncommitted files (restricted to the record's subtree), and prints the verdict from the shared helper; a drift adds the re-ship command. `?` when the repo is not on this machine.
- **VERDICT**: OK when the installed version (ignoring `+dirty`) equals the repo version, with a further DRIFT if the bytes differ from the build; otherwise DRIFT with "anything you 'verified' against this repo has NOT been tested on this machine" plus build and install commands; `?` when undeterminable.
- **`-Watch`**: needs the admin session (`?` otherwise). Every 60 s re-reads the packages view and prints one timestamped line per channel, until every channel is complete ("every computer that reports is on its platform's current build"). A 401/403 ends it ("your admin session expired"); other errors are retried up to 5 times in a row, then it gives up. Stops if the dashboard reports no rollout numbers.

## Operator secrets for a release session
(source: tools/load_secrets.ps1)

- **Purpose**: keeps the operator's secrets in a file encrypted with Windows DPAPI (decryptable only by this Windows account on this machine) and loads them into the current PowerShell window only, instead of permanent user environment variables.
- **Secrets handled**: `TRUENAS_PW`, `SYNCTHING_API_KEY`, `DASH_REPORT_TOKEN`, `DASH_SESSION_SECRET`, `BROLL_INGEST_TOKEN` (optional; a blank value is never written).
- **Store**: default `%LOCALAPPDATA%\ccsync\secrets\operator.xml` (`-Path` overrides). Its folder and the file have inheritance removed and access granted only to the current user and SYSTEM.
- **Modes**:
  - `-Save`: prompts for each secret with hidden input; an existing value is shown as "(set -- Enter keeps it)" and kept on an empty answer; writes the store; prints "load it into a window with: . .\tools\load_secrets.ps1".
  - `-Clear`: deletes the store and removes the five variables from this window.
  - No flag (must be dot-sourced to affect the window): decrypts each stored secret into the window's environment. No store: warning "run: .\tools\load_secrets.ps1 -Save". An empty store: warning "decrypted but held nothing".
- **Derived public keys**: if `%USERPROFILE%\.ccsync-release\release.key` exists, sets `DASH_RELEASE_PUBKEYS` from `release_key.py trusted --quiet` (all keys of a rotation in progress); reports "(derived)" or "(derived, N keys: a key rotation is under way)". A failure or missing key file warns that "ship step 1 will refuse".
- Prints only the names it loaded, never values.

## Authenticode signing of one Windows binary
(source: tools/sign_windows_binary.ps1)

- **Purpose**: the single place that runs Microsoft's `signtool` to code-sign a Windows exe (the companion, the installer, and CI builds).
- **Parameters**: `-Path <file>` (required), `-Quiet` (hide progress lines; failures still print).
- **Environment**: `CCSYNC_SIGN_THUMBPRINT` (certificate in the user's certificate store, by SHA-1 thumbprint) or `CCSYNC_SIGN_PFX` plus `CCSYNC_SIGN_PFX_PASSWORD` (a certificate file); `CCSYNC_SIGN_TIMESTAMP_URL` (default `http://timestamp.digicert.com`).
- **Behaviour**:
  - Missing file: "[sign] FAILED: no file at ..." exit 1.
  - No identity configured: prints "not signing <file>: no CCSYNC_SIGN_THUMBPRINT and no CCSYNC_SIGN_PFX in the environment", exit 0 (never fatal).
  - Finds `signtool.exe` on PATH or the newest x64 copy under the Windows 10 SDK folders; not found: warning "install the Windows 10/11 SDK 'Signing Tools' feature", exit 0.
  - Signs with SHA-256 file digest and an RFC 3161 SHA-256 timestamp, using the thumbprint if set, else the certificate file (and password). Output of signtool is discarded.
  - A signtool failure: "the binary is NOT signed. Fix the certificate (or unset CCSYNC_SIGN_* to build unsigned deliberately)", exit 1.
  - Callers judge the result by reading the file's signature status, not this exit code.

## Windows version information inside the frozen exes
(source: tools/winversion.py)

- **Purpose**: a helper the PyInstaller build specifications import to embed a Windows version resource, so Explorer's Details tab and SmartScreen show a file description, product and company.
- Writes a version-information text file with: company name and copyright "Copyright (c) 2026 <entity>", file description, internal name, original filename, product name `CC Sync`, file and product version (numeric four-part form, non-numeric parts count as 0), US English.
- **Environment**: `CCSYNC_LEGAL_ENTITY` overrides the company name, default `Cablewrap Creative Ltd`.
- Also reads a version string assigned in a source file without importing it (default `0.0.0` when absent).

## Running every test suite on the operator's machine
(source: tools/run_all_tests.ps1)

- **Purpose**: runs all 13 test suites, each with the interpreter it needs, and prints a summary table. Every suite runs even after a failure. The exit code is the number of failed suites.
- **Suites and interpreters**:
  - companion (its own venv, parallel `-n auto` when the parallel-test plugin `xdist` is importable, else serial with a note);
  - dashboard (its own venv, parallel `-n auto --dist loadfile`);
  - server (dashboard venv, run inside Git's own bash; with no Git bash it runs from PowerShell, warns, and reports "PASS* (no Git bash: the remote-script tests SKIPPED, not passed)");
  - onboarding (system `python`);
  - bench (its own venv);
  - broll/web (its own venv, falling back to the dashboard venv with a note);
  - broll/indexer (system python); music/web (its own venv); music/indexer (system python); ytdl/web (dashboard venv); tools (dashboard venv);
  - installer: every `installer\tests\Test-*.ps1`, each in a fresh PowerShell; none found is a failure; the first non-zero exit is reported;
  - installer/macos: every `installer\tests\test_*.sh` in Git bash; none found is a failure; no Git bash gives "SKIP (no bash)" (which counts as a failed suite in the total).
- A missing interpreter gives "NO INTERPRETER (...)" for that suite (counted as failed).
- When a passing suite skipped tests, its row shows "[N skipped]" and a closing NOTE says "a skip is not a pass. Re-run that suite with -rs".
- **`-Changed`** (with optional repeatable `-Base <commit>`): asks `select_suites.py` for a plan (printed), runs only the selected suites or test files, then the plan's extra checks (`check_licenses.py`, `gen_notices.py --check`) from the repo root under the dashboard venv. Prints the gate tier and reason and which suites were not selected. If the selector fails, runs everything ("running EVERY suite").
- `-Base` without `-Changed` refuses (exit 2).

## Choosing which tests a change needs
(source: tools/select_suites.py, tools/test_map.toml)

- **Purpose**: given the files changed since a base commit, prints a "gate plan": one of four tiers (smallest to largest):
  - `neutral`: only the smoke set (plus the area's own listed tests);
  - `scoped`: the changed area's suites and test files plus smoke;
  - `dashboard-wide`: dashboard, broll/web, music/web, ytdl/web, tools and server suites, plus the area's own, plus smoke;
  - `full`: all 13 suites plus the licence check and `gen_notices.py --check`.
- **Flags**: `--base <ref>` (repeatable; the merge base of all of them with the head is used, i.e. the older), `--head <ref>` (diff base..head, ignoring the working tree), `--files <paths...>` (classify these instead of asking git), `--json` (machine-readable plan), `--json-out <file>` (readable plan printed and JSON written), `--audit`, hidden `--map <file>`.
- **Fail-closed rules**: no base selects full ("no base given"); a base not in this clone selects full; git failing selects full; any changed file no area claims selects full ("UNMAPPED: add it to an area"); `--files` without `--base` cannot treat a version bump as neutral.
- The diff is base to working tree, including uncommitted and untracked files (or base..head with `--head`).
- **Version bump rule**: a change to `dashboard/src/ccsync_dashboard/__init__.py`, `dashboard/pyproject.toml`, `companion/src/ccsync_companion/config.py` or `companion/pyproject.toml` is neutral only when the only changed lines are `VERSION = "..."` / `version = "..."` / `__version__ = "..."`.
- **Map** (`tools/test_map.toml`, first matching area wins): 
  - full tier: the gate itself (the map, selector, test runner, `tools/ship*`, `.github/**`, every `conftest.py`, `.gitattributes`); dependencies (every requirements lock/txt/in and pyproject); shipped legal paperwork and EULA copies and `LICENSE`; the dashboard database code and schema; dashboard boot, settings, site store, secrets boot, mount status, `dashboard/deploy/**`, the ytdl nightly updater, `.dockerignore`; auth (login, sessions, local users, OIDC, the companion loopback origin guard); the shell templates, styles and service worker; AI provider resolution, CLI tools and `site.example.toml`.
  - neutral tier: docs (with named tests that read docs), `KNOWN_BUGS.md`, `SPEC.md`, `CLAUDE.md`, READMEs, every `.gitignore`.
  - scoped tier: companion, onboarding, installer (both installer suites), server, bench, b-roll indexer, music indexer, tools, b-roll web (also the b-roll indexer suite), music web, ytdl web, the Timeline Cards integration files; each lists extra test files in other suites that read its files.
  - dashboard-wide: everything else under `dashboard/`.
  - The smoke set: dashboard boot and mount tests, the three sub-apps' mounted-prefix tests, fleet-credential tests, every suite's em-dash scan, the docs index test and the map's own test.
- **Output**: "gate plan: <TIER> (<reason>)", the diff range, each changed file with its area and tier, what runs (whole suite or listed files), the extra checks, and "not run: ...".
- **`--audit`**: parses every test file's imports and path-like string literals, resolves them to repository files, and prints for every test a change would NOT select the row to fix (`area "<name>": add "<test>" to tests (it reads <file>)`, or for a conftest, add the whole suite). Ends with "N missing selection(s)" (exit 1) or "the map covers every import and path literal the tests have" (exit 0).
- A map that cannot be read exits 2.

## Refusing a build that froze something unlisted
(source: tools/scan_frozen.py)

- **Purpose**: after PyInstaller runs, reads the build's table-of-contents files to find every third-party package actually frozen into the binary, and fails the release if any is not allowed.
- **Flags**: `--component companion|onboarding` (required), `--workpath <dir>` (default `companion/build/build` or `onboarding/build/build_onboard`).
- **Components**: companion is judged against `companion/requirements.lock`; the onboarding wizard against `onboarding/requirements.lock` (it is frozen from the companion's environment, so any third-party package in it is a leak). The first-party package `ccsync-companion` and the freezer itself (`pyinstaller`, `pyinstaller-hooks-contrib`, noted as "Bootloader exception, not judged") are exempt.
- **Fails (exit 1)**, one `[scan_frozen] FAIL:` line each, then "this build must not be released":
  - a frozen package the component's lock does not name (platform markers ignored);
  - a frozen package whose own metadata licence reads LGPL, GPL, AGPL or SSPL without an entry in `tools/license_allowlist.toml` that has a `reason` and whose `targets` include this component (or no targets);
  - a file under `site-packages` that no installed package's file list claims (compiled-cache files are ignored);
  - a judged package with no committed `docs/legal/licenses/<component>/<name>-<version>.txt` at the frozen version;
  - a judged package missing from the "Contents:" list of the `THIRD_PARTY_LICENSES.txt` the build froze; a build that froze no such file; for the wizard, a bundle that does not list every entry of the companion's bundle (or the companion's bundle missing).
- **Cannot scan (exit 2)**, "[scan_frozen] CANNOT SCAN: ...": no workpath or no table-of-contents files, or one that does not parse (constructor calls such as the embedded version resource are tolerated).
- Prints the count and each judged package with version, notes (allowlisted copyleft, licence not declared), and on success "OK: every frozen distribution is in the lock and its licence text travels with the binary."

## The licence gate
(source: tools/check_licenses.py, tools/license_allowlist.toml)

- **Purpose**: judges the licences of every package in the locks of what is conveyed to customers; exits 1 on unexcused copyleft or unknown licences.
- **Targets**:
  - `companion`: `companion/requirements.lock` for Windows and macOS, licence data from `companion/.venv`.
  - `dashboard-container`: `dashboard/deploy/requirements.lock` for Linux, licence data from the dashboard, music/web, ytdl/web and broll/web environments.
  - `dashboard-container-unblock`: `dashboard/deploy/requirements-unblock.lock` for Linux (the optional YouTube-unblock add-on), from the dashboard environment.
- Packages per target come from its lock, with platform markers evaluated for that target's platforms (all marked packages included if the `packaging` library is missing). Licence strings come from `pip-licenses` run inside each environment (shared helper with the notices generator; installed on demand).
- **Verdicts** (case-insensitive substring, in this order): AGPL ("AGPL", "AFFERO"), SSPL ("SSPL", "SERVER SIDE PUBLIC"), LGPL ("LGPL", "LESSER GENERAL PUBLIC", "LIBRARY GENERAL PUBLIC"), GPL ("GPL", "GENERAL PUBLIC LICENSE/LICENCE"); empty, "UNKNOWN" or "NONE" is UNKNOWN.
- **Statuses**: FAIL (copyleft or unknown with no applicable allowlist entry; or an allowlisted copyleft entry with no `reason`; or, under `--strict`, a package not installed in any scanned environment), ALLOWED, UNSCANNED (not installed; a warning without `--strict`), XFAIL (allowlisted but marked `expect_removed`). An allowlist entry marked `expect_removed` whose package is no longer copyleft produces a STALE warning.
- **Flags**: `--strict`, `--json` (findings, warnings, failure count), `--only <target>` (repeatable), `--platform win32|darwin|linux` (repeatable; asks only for that slice of each target's platforms; a target with none of them gets a warning "nothing checked").
- **Report**: per target its purpose, lock, platforms and package count, then each finding sorted by status; warnings (missing lock, missing environment, pip-licenses failure); ends "FAILED: N licence problem(s) in a conveyed artefact." or "OK: no unexcused copyleft or unknown licence in the shipped set." Output is ASCII only.
- **Allowlist entries** (`license`, `reason`, optional `targets`, optional `expect_removed`):
  - `paramiko` (LGPL-2.1), dashboard container only.
  - `psycopg2-binary` (LGPL with linking exception), dashboard container and companion; the reason states that in the companion it is shipped as plain replaceable files outside the one-file archive, with the user's own `~/.ccsync/lib` copy taking precedence.
  - `bgutil-ytdlp-pot-provider` (GPL-3.0), only the unblock target.

## Third-party notices and the licence texts each binary carries
(source: tools/gen_notices.py, tools/notices_extra/)

- **Purpose**: generates `docs/legal/THIRD_PARTY_NOTICES.md` (the customer-facing inventory of third-party components) and, separately, the per-binary licence text files and bundles.
- **Flags**: `--check` (exit 1 when the file is missing or differs from what would be generated; writes nothing), `--out <path>` (default the notices file; `-` prints to standard output as UTF-8), `--write-texts`, `--venv LABEL=PATH` (repeatable; scan another environment for a component; malformed values are a usage error), `--rescan` (ignore licences already stated in the committed file).
- **Generated notices document** (deterministic, no run date):
  - A maintainer comment, a title "CC Sync: third-party notices", "**Issued 2026-09-25 by Cablewrap Creative Ltd.**", a statement that CC Sync is proprietary under the EULA and that each component's own licence prevails, and how to read the verification column.
  - "LICENCES NEEDING ATTENTION": every package whose licence string contains GPL, AGPL, LGPL, SSPL, MPL, EUPL, CDDL, EPL or "CC BY-SA", with where it appears and whether its licence text is on disk ("metadata" or "metadata+text"); or a paragraph saying none was found in pip metadata (ffmpeg and Syncthing live in the hand-written part).
  - "Scan warnings": packages whose licence could not be resolved.
  - "Python dependencies by component": tables for companion, dashboard, music/web and broll/web, each built from that component's `requirements.lock` (all platforms).
  - A `dashboard-container` table from `dashboard/deploy/requirements.lock`, with the licence borrowed from whichever environment has the package and a column saying where it was read ("not installed anywhere on this machine" otherwise).
  - "All pip dependencies (merged)": unique (package, version) rows with the components and whether a licence text is on disk.
  - "Binaries the installer fetches": read from code by symbol name (rclone and Syncthing versions, asset and SHA-256 from `installer/windows_bootstrap.ps1` and `installer/macos_bootstrap.sh` for Windows x64 and macOS arm64/x64; ffmpeg, ffprobe and deno from the companion's pinned-asset table; the NAS-side ffmpeg URL and hash from `server/install_dashboard_app.py`). A pin that cannot be found aborts with exit 2 and writes nothing.
  - The hand-maintained block between the lines `<!-- BEGIN HAND-MAINTAINED -->` and `<!-- END HAND-MAINTAINED -->`, copied back verbatim (a placeholder section if the file has none). A file with the begin line but no end line refuses to regenerate.
- **Licence resolution order** for each locked package: the committed file's own row for that exact version; an installed environment at that exact version (via `pip-licenses`, installed on demand into that environment; output read as UTF-8); `tools/notices_extra/lock_only.json`; the committed per-binary licence file; else UNKNOWN with a warning naming the component to regenerate on.
- No component lock readable: exit 2. Machine-specific warnings go only to standard error.
- Writes with LF line endings.
- **`--write-texts`**: for the companion (runtime closure of its pyproject dependencies plus the `tray` extra, walked through the lock's "via" comments; a root missing from the lock aborts: "relock") and the onboarding wizard (no packages of its own, but it embeds the companion):
  - writes `docs/legal/licenses/<component>/<name>-<version>.txt` for each package (title, declared licence, file names, then every licence-like file from the installed package; a wheel with none uses `tools/notices_extra/dists/<name>.txt`);
  - keeps an existing text when the package is not installed here at that version (warning), deletes stale texts;
  - writes `THIRD_PARTY_LICENSES.txt` per component: an introduction, a "Contents:" list, then the non-pip texts (PyInstaller bootloader, CPython, Tcl/Tk, OpenSSL, libpq, LGPL-3.0) followed by every package section (the wizard's also includes every companion section);
  - if any package has no text, writes NOTHING for that component and exits 1 ("NO TEXT ... re-run with --venv").
- **`tools/notices_extra/`** (data): verbatim licence texts with a header saying what they cover and where they were copied from: `cpython.txt` (CPython 3.12), `tcl-tk.txt` (8.6), `openssl.txt` (OpenSSL 3, Apache-2.0), `libpq.txt` (PostgreSQL client library in psycopg2-binary, companion only), `lgpl-3.0.txt`, `pyinstaller-bootloader.txt` (GPL with the bootloader exception); fallbacks `dists/flatbuffers.txt` and `dists/pyobjc-core.txt` for wheels that ship no licence file; `lock_only.json` (uvloop 0.22.1: Apache/MIT); `music_text_encoder/NOTICE` and `LICENSE` (Apache-2.0 notice and modification statement for the exported music text model; nothing in my part of the code reads them); a README table of when to refresh each.

## Building the dashboard code bundle (over-the-air update)
(source: tools/build_dashboard_bundle.py)

- **Purpose**: packs the dashboard's code (not its runtime) into `ccsync-dashboard-<version>.tar.gz`, which `publish_feed.py --kind dashboard` signs into the vendor feed and customer dashboards apply to themselves.
- **Flags**: `--out <dir>` (required unless `--verify`: "--out is required"), `--repo-root` (default this checkout), `--version` (default the dashboard's own `VERSION`), `--allow-dirty`, `--verify <bundle>`.
- **Exit codes**: 0 OK; 2 usage, missing tree, or verify failure; 3 dirty tree.
- **Refusals**: a checkout with uncommitted changes or no git at all ("DIRTY ... Commit, or pass --allow-dirty"); a missing source tree ("a bundle without it would boot a dashboard whose ... root is empty"); a missing required published guide file ("a dashboard whose /help page says it is not installed").
- **Contents**: `manifest.json` first (kind `dashboard`, version, git commit, dirty flag, `runtime_id` derived from `dashboard/deploy/requirements.lock` and `dashboard/deploy/Dockerfile`, build time, SHA-256 of every file), then `src/`, `templates/`, `static/`, `deploy/` (from `dashboard/`), `broll-app/` (`broll/web`), `music-app/` (`music/web`), `ytdl-app/` (`ytdl/web`), plus the customer-facing documents the dashboard's published-documents list names (for documentation trees only `.md` files, plus licence texts under `docs/legal/licenses/`); optional documents are included when present.
- **Always excluded**: folders `.venv`, `venv`, `tests`, `__pycache__`, `.pytest_cache`, `node_modules`, `.git`, `data`, `dist`, `build`, `.ruff_cache`, `.mypy_cache`; files ending `.pyc`, `.pyo`, `.map`, `.log`, `.db`, `.db-wal`, `.db-shm`, `.sqlite`, `.sqlite3`; symbolic links.
- Deterministic archive: sorted members, every file mode 0644, owner 0, time 0; written to a `.part` file then renamed.
- Prints path, size, file count, version, commit (with "+dirty"), runtime id, SHA-256, and the `publish_feed.py` command to publish it.
- **`--verify`**: checks the manifest exists, every member is a regular file listed in the manifest with a matching hash, and nothing listed is missing; prints one line per problem and "VERIFY OK" or "VERIFY FAILED".

## Fleet jobs from the command line
(source: tools/jobs.py)

- **Purpose**: an operator's command-line client for the dashboard's fleet job queue (work such as transcription or proxies that the dashboard hands to editor machines).
- **Global flags**: `--dashboard-url` (default `CCSYNC_DASHBOARD_URL`), `--admin-user` (default `CCSYNC_ADMIN_USER`), `--password-stdin`. Both URL and user are required ("error: ... is required", exit 2).
- **Login**: password from a hidden terminal prompt "password for <user>: " or one line of standard input; with no terminal and no flag refuses ("never argv, never the environment"); empty refuses. `POST /api/v1/login`; non-200 or non-admin refuses ("a job is work on somebody else's computer"), exit 4. Every later call sends the session's CSRF token as `X-CSRF-Token`. No redirect is followed; an unreachable dashboard refuses with a sentence. Any non-200 answer: "<METHOD> <path> answered HTTP <code>: <detail>", exit 5.
- **Exit codes**: 0 OK, 2 usage, 4 login, 5 call failed, 6 the watched job failed or was abandoned.
- **Path rule**: every path is a root name plus a relative path. Roots: `tree`, `vault`, `media`. A path starting `/` or with a drive letter is refused ("must be RELATIVE to its root ... name the root with --root"); a path containing `..` is refused; an empty one is refused.
- **`submit`** (`POST /api/v1/jobs`):
  - `--kind whisper|proxy-480p|audio-extract|peaks` (default whisper). `conform` and `resolve-edit` cannot be submitted.
  - `--root` (default vault), `--rel` (required), `--priority` (default 0), `--watch`, `--timeout` (default 3600 s).
  - Whisper: `--episode` (relative; default on the server: the folder's parent), `--speakers` (also identify speakers), `--vram` (GB of GPU memory required, default 6.0); the job requires a whisper-capable machine with that root mounted and that much GPU memory.
  - Media kinds: `--out-root` (default vault), `--out-rel` (required, refused with an explanation of where Timeline Cards caches go), `--out-stem` (the name the page knows the clip by).
  - `--now`: sends `force` (offered to every capable machine at once, skipping the idle wait, cooldown and ranking grace). `--on <machine>`: only that machine.
  - Receipt: "job #N queued (kind)", root:path, "forced: every capable machine is asked at once", "for <machine> only", the scheduler's summary and a yes/no line per machine with the reason.
- **`list`** (`GET /api/v1/jobs?state=&limit=`): `--state` (default `open`; also queued, running, done, failed, abandoned), `--limit` (default 50). One line per job: id, kind, state, attempts, holder, path; and the last error (first 160 characters). "no jobs" when empty.
- **`why <id>`** (`GET /api/v1/jobs/<id>/why`): summary, reason code (with "(transient: the fleet will get to it)"), and per-machine yes/no with reason.
- **`cancel <id>`** (`POST /api/v1/jobs/<id>/cancel`): "job #N is over (<error>)" for a job that ends at once, otherwise "will stop on <machine>'s next report; it is not retried anywhere".
- **`retry <id>`** (`POST /api/v1/jobs/<id>/retry`): "is on the queue again as #M", path and summary; `--watch`, `--timeout`.
- **`queue`** (`GET /api/v1/jobs/queue`): queued, running and pinned counts and the oldest wait; per kind "running/cap" with "AT THE LIMIT"; whether this dashboard's own worker takes jobs the fleet gives up on, or why not.
- **`watch <id>`** (`--timeout`, default 3600 s): polls `GET /api/v1/jobs/<id>` every 5 s, printing a line whenever state, holding machine or progress percentage changes. Done: duration, speed relative to real time, files written (up to 20 listed) or "nothing to do, it was already made". Failed or abandoned: the error, exit 6. Pinned keeps watching. Timeout: "still <state> after N s" with the `why` hint, exit 0.

## The Android app build (Trusted Web Activity)
(source: tools/android/build_apk.sh, tools/android/twa_manifest.py, tools/android/check_assetlinks.py, tools/android/fixture/)

- **What it is**: the Android app is a Trusted Web Activity: a thin Android shell (built with Google's Bubblewrap tool) that opens one dashboard origin full-screen in Chrome.
- **`build_apk.sh <https-origin> [package-id] [outdir]`** (outdir default `build/twa`; no origin prints usage, exit 2):
  - Signing from `CCSYNC_ANDROID_KEYSTORE`, `CCSYNC_ANDROID_KEYSTORE_PASSWORD`, `CCSYNC_ANDROID_KEY_ALIAS` (default `android`), `CCSYNC_ANDROID_KEY_PASSWORD`. A keystore path that does not exist refuses; a keystore without both passwords refuses. With no keystore, generates (once) a throwaway RSA 2048 debug key `debug.keystore` in the output folder (alias `ccsync-debug`, password `ccsync-debug`, valid 10,000 days) and warns "Do not ship this APK: its fingerprint changes on every build, and an app signed with a new key cannot update an installed one."
  - Exports the passwords as `BUBBLEWRAP_KEYSTORE_PASSWORD` / `BUBBLEWRAP_KEY_PASSWORD`.
  - If `~/.bubblewrap/config.json` is missing, writes it from `JAVA_HOME` and `ANDROID_HOME` (or `ANDROID_SDK_ROOT`), converting backslashes; if either is missing refuses ("Run 'npx @bubblewrap/cli doctor' once interactively ...").
  - Creates a stub `tools/source.properties` (`Pkg.Revision=26.1.1`) inside the Android SDK if absent (using sudo if needed), because Bubblewrap's SDK check looks for it.
  - Runs `twa_manifest.py` (passing `CCSYNC_ANDROID_WEB_MANIFEST` as `--manifest` when set), then `bubblewrap update --skipVersionUpgrade` and `bubblewrap build --skipPwaValidation` (Bubblewrap command from `BUBBLEWRAP`, default `npx --yes @bubblewrap/cli@latest`; Python from `PYTHON`, default `python3`).
  - Prints the signing kind, the package id and the certificate SHA-256 fingerprint, tells the operator to paste both into the dashboard's Settings > ANDROID and verify with `check_assetlinks.py`, and lists `app-release-signed.apk` and `app-release-bundle.aab`.
- **`twa_manifest.py`**: writes `twa-manifest.json` for Bubblewrap from the live web app manifest.
  - Flags: `--origin` (required), `--package` (default: the origin's host labels reversed plus `.ccsync`, each label lower-cased, non-alphanumerics turned to `_`, a label not starting with a letter prefixed `n`), `--out` (required), `--manifest` (URL or file, default `<origin>/manifest.webmanifest`, 30 s), `--keystore` (default `./android.keystore`), `--key-alias` (default `android`), `--version-name` (default 1.0.0), `--version-code` (default 1).
  - Takes name, short name, theme and background colours (default `#0a0a0d`), display (default standalone), start URL, scope, orientation, and the largest normal and maskable icons. A manifest with no normal icon refuses. Fixed values: no notifications, Custom Tabs fallback, minimum Android SDK 21, splash fade 300 ms, site-settings shortcut on, no shortcuts.
  - An unreadable manifest: "FAIL could not read the web app manifest", exit 2. Prints the package id, host, start URL and icon URL.
- **`check_assetlinks.py <origin> <fingerprint>`**: reads `<origin>/.well-known/assetlinks.json` (15 s) and reports whether an `android_app` statement with relation `delegate_permission/common.handle_all_urls` carries that SHA-256 fingerprint (case-insensitive, optional `SHA256:` prefix). Exit 0 "OK <package> is declared with this fingerprint"; exit 1 for not a JSON array, an empty statement ("the site has no Android package configured"), no matching statement, or a different fingerprint (lists the ones declared); exit 2 when the site cannot be read.
- **Fixture** (for CI builds without a real dashboard): a `manifest.webmanifest` named "CC Sync" with colours `#0a0a0d` and three icons, and `make_fixture_icons.py`, which writes flat `#0a0a0d` PNGs `icon-192.png`, `icon-512.png`, `icon-512-maskable.png`.

## Offline test of the installed Timeline Cards app
(source: tools/cards_offline/run.js, tools/cards_offline/serve.py, tools/cards_offline/stale_worker.js)

- **Purpose** (DEV ONLY, a manual test harness): proves that the installed Timeline Cards web app opens with no network, in a real headless Chrome driven over the DevTools protocol (no npm dependencies; needs Node with built-in fetch and WebSocket).
- **`run.js` flags**: `--python` (default `python`), `--page-src` (the Timeline Cards checkout's `multicam_pipeline/cards`, or `CARDS_PAGE_SRC`), `--shots <dir>` (save screenshots `hole.png`, `refused.png`, `picker-with-download.png`), `--port` (default 8491), `--proxy` (default 8492), `--debug-port` (default 9333), `--chrome` (default `C:/Program Files/Google/Chrome/Application/chrome.exe`), `--work` (default `<temp>/cards_offline_run`).
- Starts `serve.py`, waits up to about 30 s for it (`/cards/icon.svg`), and routes Chrome through its own proxy, which can pass traffic, "hang" (accept and never answer) or "refuse". Phone-sized viewport 412 x 915 at 2x. Uses a session cookie the server minted.
- **Checks** (each printed PASS/FAIL; exit 1 if any fails, 2 on a crash; ends "all passed" or "N FAILED"):
  - first: the service worker registers at scope `/cards/`, and the landing page plus its CSS and JS are saved in cache `cards-landing` on the first visit;
  - hole: with the server a black hole, the saved picker is served, first paint under 10 s, and the episode list has rows;
  - hard: with the connection refused, and with the browser in offline mode, it draws in under 2 s;
  - start: `/cards/?source=pwa` and `/cards/?utm_source=x&a=1` find the saved page in under 2 s;
  - upgrade: with an older worker (`stale_worker.js`, which caches nothing) installed first, one online visit after the update saves the page, and the next black-hole launch shows the offline picker;
  - episode: opening an episode makes its own worker save its page (cache name starting `cards-shell-`); after a downloaded cut list is recorded in the browser's `cards-offline` database, the offline picker lists it, the row is wider than 100 px, and tapping it opens the episode offline under its own worker.
- **`serve.py`** (`--worktree`, `--port` default 8491, `--work` required, `--page-src` or `CARDS_PAGE_SRC`, refused if it has no `page.py`): builds a local dashboard with Timeline Cards mounted on a stub engine (empty state) but the real Cards page files, a fake vault with three episodes (Civil Defence, Framing Formosa, Pangolins under `FF5`, each with a `Script Docs/main.cut.md`), admin user `owen`, sets `DASH_DEV_INSECURE=1`, writes `cookie.txt` and `cookie_name.txt`, and serves on 127.0.0.1.

## The mobile layout sweep
(source: tools/mobile_sweep.js, tools/mobile_sweep_seed.py)

- **Purpose** (DEV ONLY): photographs and measures every dashboard page at phone and tablet width.
- **`mobile_sweep_seed.py`**: starts a real dashboard on a throwaway database with invented data so every page has its hard case.
  - Flags: `--port` (default a free port), `--host` (default 127.0.0.1), `--admin` (default `owen`), `--password` (default `sweep-` plus random), `--data <dir>` (keep this data folder; default a temporary folder deleted on exit).
  - Seed: editors `jsmith`, `mrivera`, `tchen`; five machines (one healthy, one with the lane B breaker tripped plus conflicts and crashes, one halted by the operator, one running a b-roll ingest at 37 percent, one out of date with all lanes erroring, stalled lane, Syncthing supervisor errors and low disk); two projects; NAS media with a deliberately long clip name; Resolve bin trees; selections (one upload-only); twelve live transfers and history; four queued jobs and one running at 37 percent; four notices and one sent alert; two published companion versions per platform with 0.9.54 current. Admin and editor accounts are local accounts; sign-in method `local`.
  - Prints the URL, user, password, data folder and the matching `mobile_sweep.js` command; runs until Ctrl+C.
- **`mobile_sweep.js`** (Node, no npm dependencies, Chrome over DevTools):
  - Flags: `--url` (default `http://127.0.0.1:8499`), `--user` (default `owen`), `--password` (required, exit 2 without), `--out` (default `docs/mobile`), `--json` (report path, default `<out>/report.json`), `--chrome` (default the Windows Chrome path), `--debug-port` (default 9358), `--resolve-project` (default `FF5 Elections E2`), `--widths` (default `390,768`; 390 is 844 high at 3x, 768 is 1024 high at 2x, any other width 1024 high at 2x).
  - Signs in through the real login form (reads the CSRF token off the page); refuses if no `ccsync_session` cookie comes back.
  - Pages: login (signed out), home, transfers, the first project found on the home page, project setup for the given Resolve project, installer, and admin users, assignments, jobs, packages, settings, audit, alerts, invariants, protection, recovery (16 pages).
  - For each page and width: waits for the page's dynamic partials to settle (up to 1.5 s), saves `docs/mobile/<width>/<page>.png`, and measures.
  - FAIL when: the page landed on `/login` (other than the login page); the whole page scrolls sideways; any element outside a `.scroll-x` wrapper (form fields exempt) scrolls sideways, naming the element that reaches furthest past the edge, its width, how far past, and whether it refuses to wrap.
  - WARN when the smallest visible button/link chip/input/select is under 44 px on either axis, when there is no tap target at all, or when the smallest rendered text is under 12 px.
  - Prints a per-page line and a summary table, writes the JSON report (time, URL, user, widths, thresholds, totals, findings), and exits 1 if any page failed.

## Checking an origin a phone can install from
(source: tools/check_mobile_origin.py)

- **Purpose**: tells an administrator, one line per check, whether a dashboard address will let a phone install the dashboard as an app. Anonymous requests (no session), system trust store, redirects followed, 15 s timeout, user agent `ccsync-check-mobile-origin/1`.
- **Usage**: `check_mobile_origin.py <url> [--json]`; the URL is reduced to scheme and host:port (a missing scheme is taken as https).
- **Checks, in order, stopping at the first FAIL** (lines "OK", "FAIL" or "SKIP", name, detail):
  - `https`: the origin's scheme is https, else "no secure context: no service worker, no install prompt, no TWA".
  - `certificate`: a request to `/api/v1/health` completes the TLS handshake ("TLS refused: ..." or "could not connect: ...").
  - `manifest`: `/manifest.webmanifest` answers 200 signed out, is JSON, and has `start_url` and a non-empty `icons` ("Chrome will not offer to install it").
  - `service worker`: `/sw.js` answers 200 with a `Service-Worker-Allowed` header.
  - `asset links`: `/.well-known/assetlinks.json` answers 200 with JSON; an empty list passes ("no Android package configured yet").
  - `health`: `/api/v1/health` answers 200 JSON with a `version` ("whatever is behind this origin, it is not the dashboard").
  - `cookie secure`: every cookie set by `/login` carries `Secure`, else FAIL naming them with the fix (`DASH_COOKIE_SECURE=1` or add the proxy to `DASH_TRUSTED_PROXIES`); no cookie at all is SKIP.
- Ends with "STOPPED at <check>. Fix that and run this again." on failure. `--json` prints origin, overall ok and each check. Exit 1 if any check failed.

## Redrawing the product icons
(source: tools/gen_icons.py, tools/make_icons.js)

- **`gen_icons.py [--check] [--mark PATH]`** (needs Pillow; the companion environment has it): redraws every raster icon from one source, the white-on-transparent brand mark `companion/src/ccsync_companion/assets/cc_mark_white.png` (refuses a mark with no visible pixels).
  - Brand red is RGB (255, 33, 64). The mark is centred at 92 percent of the width on a transparent square; drawn at 4x and downscaled; at 32 px and below the mark's opacity is boosted by 1.35x so thin strokes stay visible.
  - Writes: `companion/.../assets/icon.ico` (16, 24, 32, 48, 64, 128, 256 px, each drawn separately), `companion/.../assets/icon.png` (512), `dashboard/static/favicon.png` (512), `dashboard/static/favicon.ico` (16, 32, 48), `broll/web/static/favicon.png` (512), `dashboard/static/icons/icon-192.png` and `icon-512.png` (transparent), and `icon-192-maskable.png` / `icon-512-maskable.png` (white mark at 60 percent on an opaque brand-red square).
  - `--check`: renders in memory and lists each file that differs ("STALE"), ending "icons are current" (exit 0) or "icons are stale: N" (exit 1).
- **`make_icons.js [--check]`** (Node plus Chrome at the fixed Windows path, debug port 9358): renders only `dashboard/static/icons/icon-180.png` (the iOS home-screen icon) from the two paths in `dashboard/static/icons/icon.svg`: the mark at 74 percent inside a rounded dark panel (`#0a0a0d`, 96 px corner radius, 10 px `#7c1322` border). Refuses if `icon.svg` does not hold exactly two path elements. `--check` renders into a temporary folder and compares only the PNG size header ("MISSING", "WRONG SIZE", "stale icons: N" exit 1, or "icons are current"). A "maskable" drawing mode exists in the code but nothing uses it (UNREACHABLE: no target asks for it).

## Live checks of the Resolve project-library walk
(source: tools/library_walk_check.py, tools/library_walk_timing.py)

- **What the "library walk" is**: the companion can read a Resolve project's clips and timelines directly from Resolve's project database instead of through Resolve's slow scripting interface. These two DEV ONLY tools are run by hand on a machine with Resolve running and a project open, with the companion's Python. Both are read-only (no playhead move, no project or timeline opened or closed, nothing written) and connect to Resolve only after the script-server readiness check passes (state READY or UNKNOWN).
- **`library_walk_check.py`** (no flags): compares the database's answers with Resolve's own API.
  - Exit 2 with a sentence when Resolve does not answer ("Resolve is not answering the scripting API; nothing to compare."), no project is open, no timeline is open, or the project's library cannot be located.
  - Reports: session (project, timeline and its id, library description); timeline items (API items walked, distinct pool clips, clips with a path, library items, items with a path, multicam angles, both walk times, speed-up); media pool (clip counts, walk times, speed-up).
  - Compares, over clips both sides saw, timeline file paths, pool file paths and pool bin paths; prints counts (from API, from library, compared, agree, disagree, API only, library only) and up to 10 disagreements with both values ("... and N more").
  - Fails (exit 1) on any disagreement, when the library returns no timeline items while the API walked some, no media paths at all, no pool clips while the API has some, or recognises none of the clips the API reported. Ends "DISAGREEMENTS: N", "FAILED: ..." lines, or "all compared paths agree."
- **`library_walk_timing.py`** (no flags): times the companion's own entry points with the real configuration (`~/.ccsync/config.toml` if it exists, never creating it; defaults otherwise). Prints the `library_walk` and `library_db_host` settings, then three runs of the timeline poll and one media-pool walk, each line showing ok, which walk answered, item count, items with a path, wall time and how long the companion's Resolve lock was held (with per-call breakdown), and any error message; finally the library status. No Resolve: "no Resolve to talk to -- nothing measured", exit 1.

## The GPU indexer container
(source: tools/Dockerfile.indexer-gpu, tools/compose.indexer-gpu.yaml, tools/indexer-entrypoint.sh)

- **Purpose**: one container image that runs the b-roll and music indexers (the heavy GPU work that fills the search databases) on a machine with an NVIDIA card. Not part of the dashboard deployment.
- **Image** (`ccsync/indexer-gpu:1`): base `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04`; Ubuntu's Python 3.11, ffmpeg (from the distribution, not vendored), libsndfile; a virtual environment at `/opt/venv`; pinned packages: torch 2.6.0 and torchaudio 2.6.0 (CUDA 12.4 build), numpy 2.1.3, transformers 4.46.3, librosa 0.11.0, pyloudnorm 0.1.1, soundfile 0.13.1, onnx 1.17.0, onnxruntime 1.20.1, anthropic 0.92.0, faster-whisper 1.1.1, ctranslate2 4.5.0, fastembed 0.8.2, xxhash 3.5.0, pyyaml 6.0.2, requests 2.32.3, jieba 0.42.1, opencc-python-reimplemented 0.1.7. Copies and installs (editable) `broll/indexer`, `music/indexer`, plus `music/web`. Runs as user 3000, group 3001 (`ccsync`, same ids as the dashboard container).
- **Volumes**: `/data`, `/index`, `/models` (declared); `/library` and `/config` mounted by the operator.
- **Preset environment**: `BROLL_DATA_ROOT=/data/broll`, `BROLL_DB_PATH=/index/broll.db`, `BROLL_MODEL_CACHE=/models/fastembed`, `CCSYNC_WHISPER_PYTHON=/opt/venv/bin/python`, `CCSYNC_WHISPER_SCRIPT=/app/broll/indexer/tools/whisper_transcribe.py`, `CCSYNC_WHISPER_MODEL_DIR=/models/whisper`, `MUSIC_DATA_ROOT=/data/music`, `MUSIC_DB_PATH=/index/music.db`, `MUSIC_MODEL_CACHE=/models/hf`, `HF_HOME=/models/hf`.
- **Entrypoint verbs** (default `help`, which prints usage and exits 0, so a bare start never begins spending):
  - `index [args]`: `broll-index --config <config> run ...` (the whole b-roll pipeline; costs model-call money);
  - `transcribe [args]`: `python batch_transcribe.py --config <config> ...` (speech transcription, model loaded once);
  - `music-embed [args]`: `python index_music.py ...`;
  - `drain [args]`: `python index_music.py --queue ...` (process the music upload queue);
  - `shell`: an interactive shell;
  - `help`, `-h`, `--help`: usage;
  - anything else: "unknown command", usage, exit 2.
  - `index` and `transcribe` refuse (exit 2) when the b-roll config file is missing ("Mount one at /config/config.yaml ... or set BROLL_CONFIG").
  - Environment: `BROLL_INDEXER_DIR` (default `/app/broll/indexer`), `MUSIC_INDEXER_DIR` (default `/app/music/indexer`), `BROLL_CONFIG` (default `/config/config.yaml`).
- **Compose file** (run with `docker compose ... run --rm <service>`): services `broll-index` (`index`), `broll-transcribe` (`transcribe`), `music-index` (`music-embed`), `music-drain` (`drain --export-drain /index/drain.db`, the only one with the library writable). Each needs `ANTHROPIC_API_KEY` and `CCSYNC_LIBRARY` (refused if unset); `CCSYNC_DATA` (default `./indexer-data`), `CCSYNC_INDEX` (default `./indexer-index`), `CCSYNC_CONFIG` (default `./indexer-config`, read-only); a named `indexer-models` volume; one NVIDIA GPU reserved.

## Continuous integration: the test workflow
(source: .github/workflows/ci.yml)

- **Triggers**: every push to any branch, every pull request, manual dispatch, and nightly at 03:17 UTC. A newer run on the same ref cancels the older one. Token permission: read-only repository contents. Python 3.12; `PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1`. Every job has a 30-minute limit. Steps after the first carry "run unless cancelled", so one failing suite does not stop the others.
- Actions are pinned by commit (checkout v4, setup-python v5 with pip caching keyed on the locks, upload-artifact v4).
- **`windows` job** (windows-latest):
  - Puts Git's own bash (`C:\Program Files\Git\bin`) ahead of the WSL launcher on PATH.
  - Companion environment from `companion/requirements.lock` with hashes.
  - Installs rclone v1.75.0 for Windows from downloads.rclone.org, falling back to the GitHub release, verifying SHA-256 `203581f0...89ac0` before extracting to `companion/.tools/rclone.exe` (300 s per download; any failure fails the step).
  - Installs ffmpeg with Chocolatey if not on PATH (allowed to fail).
  - Companion suite in parallel (`-n auto`), JUnit report.
  - Licence gate: `check_licenses.py --strict --only companion --platform win32`.
  - Onboarding environment and suite; bench environment and suite.
  - Every `installer/tests/*.ps1` in a fresh PowerShell; none found or any non-zero exit fails, naming each failure.
  - Uploads `junit-*.xml` as artifact `junit-windows`.
- **`linux` job**: DORMANT, switched off with `if: false` since 2026-11-10 (a skipped job leaves the run green). When on (ubuntu-latest):
  - CRLF gate: fails if any tracked `*.sh`, `*.bash`, `dashboard/deploy/run.sh`, either Dockerfile, `dashboard/deploy/*.yaml` or workflow file contains a carriage return; and fails if git's index records any of them as not LF (with the fix command).
  - Dashboard suite (parallel, `--dist loadfile`, `PYTHONPATH=src`); server suite through bash on the dashboard environment; broll/web, music/web and ytdl/web each in their own locked environment; broll/indexer with its lock plus `numpy==2.5.2` and `pillow==12.3.0`, after installing ffmpeg with apt (8-minute cap, 3 retries, 30 s timeouts); music/indexer and tools suites on the dashboard environment; every `installer/tests/test_*.sh` through bash (none found fails).
  - Licence gate `--strict --only dashboard-container --platform linux`; `gen_notices.py --check`.
  - Uploads `junit-linux`.
- **`macos` job** (macos-latest, Apple silicon):
  - Companion environment from the lock; rclone v1.75.0 `osx-arm64` from the same two sources, SHA-256 `35e8f2a6...cba6f8`, to `companion/.tools/rclone`; ffmpeg with Homebrew if missing (allowed to fail).
  - Companion suite in parallel; licence gate `--only companion --platform darwin`; onboarding environment and suite.
  - `tools/release_macos.sh --dry-run --skip-tests --allow-dirty` as a smoke test (builds and publishes nothing).
  - Uploads `junit-macos`.
- **Not covered by CI while the linux job is off**: the dashboard, server, b-roll, music, ytdl and tools suites, the CRLF gate, the dashboard licence gate and the notices check. The customer release tool refuses a dashboard release when that job did not run (see above).

## Continuous integration: the Windows release build
(source: .github/workflows/release-windows.yml)

- **Triggers**: every push to `main`, and manual dispatch with inputs `run_tests` (boolean, default false: also run the companion, dashboard and onboarding suites here) and `allow_dirty` (boolean, default false). Read-only token. windows-latest, 80-minute limit. Never publishes.
- **Job environment**: `PFX_B64` from secret `CCSYNC_SIGN_PFX_BASE64`; `CCSYNC_REQUIRE_FFMPEG=1`.
- **Steps**:
  - Full-history checkout (so the manifest names the right commit); Git's bash first on PATH; Python 3.12 with pip cache.
  - Companion environment from the lock with hashes plus `pyinstaller==6.21.0`; dashboard environment from `dashboard/requirements.lock` (the build script runs its suite when tests are on).
  - Pinned rclone v1.75.0 (same two sources and checksum as CI); ffmpeg via Chocolatey if absent (a failed install fails the run).
  - Signing certificate: if the secret is empty, writes "signing: no CCSYNC_SIGN_PFX_BASE64 secret -- this build will be UNSIGNED ..." to the run summary; otherwise decodes it to `<runner temp>/ccsync-sign.pfx`, exports `CCSYNC_SIGN_PFX`, and notes it in the summary.
  - Build: `tools/release.ps1` with `-SkipTests -TestsGate ci` unless `run_tests` is true, `-AllowDirty` if asked; secrets `CCSYNC_SIGN_THUMBPRINT`, `CCSYNC_SIGN_PFX_PASSWORD`, `CCSYNC_SIGN_TIMESTAMP_URL` are passed in.
  - Wizard (`onboard.exe`): skipped with a summary note when no companion exe exists; PyInstaller `onboarding/build_onboard.spec` from the companion environment (failure noted, run continues); `scan_frozen.py --component onboarding` (failure deletes `onboard.exe` and notes "REFUSED"); signs it with `sign_windows_binary.ps1` (failure noted "the installer artefact is unsigned"); with `run_tests`, runs the onboarding suite. Writes `onboarding/dist/ccsync-onboard.json`: version (from `onboarding/steps.py`), platform windows, artefact `onboard.exe`, SHA-256, size, build time, full git commit, dirty flag, `tests_run`, `tests_gate` (`ci` when tests were not run, empty when they were), `signed_binary` (Windows signature status Valid), built by `github-actions/release-windows`. Prints a summary line.
  - Writes the companion manifest (or "no manifest ... the build did not complete") into the run summary.
  - Uploads artifact `ccsync-companion-windows` with `ccsync-companion.exe`, `ccsync-release.json`, `onboard.exe`, `ccsync-onboard.json`; fails if no file is found.

## Continuous integration: the macOS release build
(source: .github/workflows/release-macos.yml)

- **Triggers**: every push to `main`, and manual dispatch with `run_tests` and `allow_dirty` (both default false). Read-only token. macos-latest, 45-minute limit. Never publishes.
- **Steps**: full-history checkout; Python 3.12; companion environment from the lock plus `pyinstaller==6.21.0`; pinned rclone v1.75.0 for Apple silicon; ffmpeg via Homebrew if absent.
- **Build**: `tools/release_macos.sh` with `--skip-tests --tests-gate ci` unless `run_tests`, `--allow-dirty` if asked; environment `CCSYNC_REQUIRE_FFMPEG=1` and `CCSYNC_APPLE_DEV_ID` from a secret (when set, the script signs with Developer ID; no notarisation profile is passed, so it is not notarised).
- **Wizard**: if `tools/build_onboard_macos.sh` is executable, runs it (no publish); a failure is noted and the run continues. If `onboarding/dist/ccsync-onboard-macos-<version>.zip` exists (version from `installer/macos_bootstrap.sh`), writes `onboarding/dist/ccsync-onboard.json` with version, platform macos, artefact name, SHA-256, size, build time, commit, dirty flag, `tests_run` / `tests_gate` (onboarding suite run only with `run_tests`), and `signed_binary` always `false`.
- **Upload**: artifact `ccsync-companion-macos` with `companion/dist/ccsync-companion`, its manifest, the wizard zip and its manifest; fails if no file is found.

## Continuous integration: the dashboard code bundle
(source: .github/workflows/release-dashboard.yml)

- **Trigger**: manual dispatch only, input `allow_dirty` (boolean, default false). Read-only token. ubuntu-latest, 15-minute limit, full-history checkout, Python 3.12, no packages installed. Never publishes.
- **Steps**: `tools/build_dashboard_bundle.py --out dist [--allow-dirty]` (output appended to the run summary); `--verify` on every produced bundle; a run-summary note "This artifact is NOT published" with the `publish_feed.py` command; uploads artifact `ccsync-dashboard-bundle` (`dist/ccsync-dashboard-*.tar.gz`; fails if none). The customer release tool requires a green run of this workflow on the release commit.

## Continuous integration: the container images
(source: .github/workflows/image.yml)

- **Triggers**: push to `main`, push of a tag starting `v`, manual dispatch. A newer run on the same ref cancels the older one. Permissions: read contents, write packages (to push to GitHub's container registry, GHCR), and an identity token (for keyless signing).
- **Images**: the dashboard (`dashboard/deploy/Dockerfile`) and the SFTP sidecar (`dashboard/deploy/sftp/Dockerfile`), both built from the repository root. Names from repository variables `CCSYNC_IMAGE` / `CCSYNC_SFTP_IMAGE`, default `ghcr.io/<owner lower-cased>/ccsync` and `.../ccsync-sftp`. Version read from `dashboard/src/ccsync_dashboard/__init__.py` (not from the tag); missing version fails.
- **`gate` job** (does work only for a tag): refuses unless the tag equals `v<VERSION>`, the commit is an ancestor of `origin/main`, the tag is the newest `v*` tag, and `ci.yml` has a successful run on that commit. Each refusal is an error annotation.
- **`build` job** (after the gate, 30-minute limit):
  - CRLF gate over the Dockerfiles, `run.sh`, the sidecar's scripts and `sshd_config`, `dashboard/deploy/*.yaml` and this workflow file.
  - Tags pushed: `:<short sha>` always; `:edge` too only when the ref is `main`.
  - For a tag build, refuses if `:<VERSION>` already exists for either image ("a released version is never rebuilt. Bump VERSION.").
  - Builds and pushes the dashboard image with build argument `CCSYNC_GIT_SHA=<full commit>`, an SBOM, and GitHub Actions layer caching.
  - Boot smoke test: runs the pushed digest with an empty data folder, random secrets, `DASH_AUTH_METHOD=local`, `DASH_VENDOR_DEFAULTS=1`, port 8480 mapped to 127.0.0.1:18480; polls `/api/v1/health` every 2 s up to 60 times; requires `version` equal to VERSION and an `ok` field; requires `/setup` to answer 200; prints the container log on failure.
  - Signs the dashboard digest with cosign keyless signing; builds, pushes and signs the SFTP image the same way (no smoke test).
  - Run summary: both digests, the tags pushed, and the exact `cosign verify` command for this workflow's identity.
- **`promote` job** (tags only, behind the GitHub environment `customer-release`, which waits for a required reviewer's approval): adds `:<VERSION>` and `:1` to both verified digests, writes `digests.json` (version, image, digest, sftp_image, sftp_digest), and uploads it as artifact `image-digests` (read by the customer release tool).

## Continuous integration: the Android app
(source: .github/workflows/android.yml)

- **Trigger**: manual dispatch only, inputs `origin` (required, default `http://127.0.0.1:8765`), `package_name` (blank: derived from the host), `serve_fixture` (default `true`). Inputs are passed through environment variables, never written into shell lines. Newer run cancels older. Read-only token. ubuntu-latest, 45-minute limit.
- **Steps**: Python 3.12, Node 20, Temurin Java 17; prints the toolchain; if secret `CCSYNC_ANDROID_KEYSTORE_BASE64` is set, decodes it to a temporary keystore (summary: "release keystore materialised"), else summary warns of a THROWAWAY DEBUG KEY; unless `serve_fixture` is `false`, serves `tools/android/fixture/` on 127.0.0.1:8765 and points the build at its manifest; runs `tools/android/build_apk.sh <origin> <package> build/twa` with the keystore secrets; always writes the package and fingerprint to the run summary ("Paste both into the dashboard's Settings -> ANDROID") or a note that the build did not get that far; lists outputs; uploads artifact `ccsync-android` (APK, AAB, `twa-manifest.json`; warns if none); stops the fixture server.

## Continuous integration: feed freshness and action pins
(source: .github/workflows/feed-freshness.yml, .github/dependabot.yml)

- **feed-freshness**: daily at 06:41 UTC and on manual dispatch; ubuntu-latest, 10-minute limit; runs `tools/check_feed_freshness.py` with `GH_TOKEN` from secret `FEED_READ_TOKEN` (falling back to the workflow's own token, which cannot read a private feed repository, giving "NOT CHECKED" and a red run).
- **Dependabot**: opens at most 5 pull requests a week to move the pinned GitHub Actions versions forward.

## The sync benchmark: what it is and its commands
(source: bench/pyproject.toml, bench/ccbench/__init__.py, bench/ccbench/cli.py, bench/ccbench/config.py, bench/bench.toml.example, bench/requirements.lock, bench/.gitignore)

- **Purpose** (DEV ONLY tool, package `ccbench` 0.1.0, Python 3.12+, no runtime dependencies; pytest is its only locked package, for development): measures how fast each candidate transfer engine moves data between this machine and the NAS over Tailscale for each of the three sync lanes (lane A video up, lane B proxies down, lane C everything else both ways), and checks whether the Tailscale path to a peer is direct or relayed.
- **Command** `ccbench` with subcommands:
  - `dataset`: generate a synthetic dataset.
  - `run --config <bench.toml>`: run the benchmark matrix.
  - `report`: render the results into Markdown.
  - `selftest`: run the matrix against local folders as a smoke test.
  - `tailscale-check --peer <host, DNS name, node key or Tailscale IP>`: prints `peer=<name> path=<direct or relayed ...> cur_addr=<address or (none)> relay=<region or (none)>`; exit 0 when direct, 2 when relayed, 1 when the peer is not found in `tailscale status --json` (with the reason).
- **Config file** (TOML; relative paths resolved against the config file's folder; unknown sections kept). Sections and defaults:
  - `[general]`: `results_file` (default `results/results.jsonl`), `repeats` (default 2; the example uses 3), `keep_remote_data` (default false: clean the NAS scratch data once after the matrix), `verify` (default true), `work_dir` (default `work`), `allow_destructive_endpoint` (default false).
  - `[datasets]`: name to folder (example: `large = "data/large"`, `small = "data/small"`).
  - `[lanes.<letter>]`: `dataset` (a key of `[datasets]`; an unknown key raises "lane references dataset ... but it is not defined"), `direction` `up`, `down` or `both` (both runs each direction separately; default `up`). Example: A large up, B large down, C small both.
  - `[engines] include`: default `rclone_sftp`, `rclone_smb`, `robocopy_smb`, `syncthing`, `iperf3`.
  - `[endpoints.sftp]`: `host`, `user`, `key_file`, `port` (default 22), `remote_path` (must contain `_bench`; default `ccbench`, which does not, so cleanup would be refused), optional `local_test_dir`.
  - `[endpoints.smb]`: `host`, `share`, `user`, `password_env` (the NAME of an environment variable holding the password; example `CCBENCH_SMB_PASSWORD`), optional `domain`, `remote_subpath` (default `ccbench`), `unc_path` (both delete targets must contain `_bench`), optional `local_test_dir`.
  - `[endpoints.syncthing]`: `binary` (default `syncthing`).
  - `[endpoints.iperf3]`: `host`, `port` (default 5201).
  - `[params.rclone]`: `transfers` (default 4; example 1, 4, 8, 16, 32), `multi_thread_streams` (default 0; example 0, 4, 8), `sftp_chunk_size_kib` (default 255; example 32, 128, 255). The old key `sftp_chunk_size_mb` is rejected with an error.
  - `[params.robocopy]`: `mt` (default and example 1, 8, 16, 32).
  - `[params.iperf3]`: `parallel` (example 1, 4, 8), `duration_s` (example 10).
  - `[tailscale] peer_hint`: not read by any code (the peer comes from `--peer`).
- `bench/.gitignore` ignores `data/` and `work/` but deliberately keeps `results/` trackable.

## The sync benchmark: synthetic datasets
(source: bench/ccbench/dataset.py)

- `ccbench dataset --out <dir>` with `--profile large|small|both` (default both), `--seed` (default 1337), `--large-count` (default 3), `--large-size-gib` (default 4.0), `--small-count` (default 400), `--small-min-kib` (default 50), `--small-max-mib` (default 20).
- **Large profile**: files `large/clip_0000.braw`, `clip_0001.mov`, ... (extensions alternate .braw and .mov), each the full size, filled with seeded pseudo-random (incompressible) bytes.
- **Small profile**: files `small/<Audio|GFX|Docs|Stills>/<Music|SFX|Titles|Graphics|Client|Archive>/<v1|v2|final|draft|misc>/asset_NNNN.<wav|png|aep|srt|psd>`, sizes spread log-uniformly between the minimum and maximum.
- Deterministic for a given seed and parameters; written in 64 MiB chunks.
- Writes `manifest.json` in the output folder: profile, seed, generation time, root, file count, total bytes, and per file its path, size, SHA-256 and profile. Prints "wrote N files (X MiB) -> <manifest>". An unknown profile raises an error.

## The sync benchmark: the matrix run and safety guard
(source: bench/ccbench/matrix.py, bench/ccbench/guard.py, bench/ccbench/result.py, bench/ccbench/runners/__init__.py, bench/ccbench/runners/base.py)

- **`ccbench run`** flags: `--config` (required), `--rerun` (re-run combinations that already produced a measurement; skipped or failed ones are always retried), `--engines e1,e2` (allowlist within the config's list), `--lanes A,B,C` (allowlist; iperf3 belongs to the synthetic lane `net` and is filtered by it too), `--allow-destructive-endpoint`.
- **What runs**: for each configured lane, each included file engine (rclone_sftp, rclone_smb, robocopy_smb, syncthing), each direction, each parameter combination, each repeat (0 to repeats minus 1). Then iperf3 up and down for each of its combinations and repeats, unless excluded.
  - Already-measured combinations (same engine, lane, dataset, direction, parameters and repeat, with ok and not skipped) print `[skip-measured] ...` and are not re-run without `--rerun`.
  - Each run prints `[run] lane=X engine direction {params} rep=N ...` and then `-> skipped: <reason>`, `-> FAILED: <reason>`, or `-> <MB/s> MB/s in <s>s verified=<bool> (<method>) [<bytes source>]`.
  - A download destination is `work/_bench_down/<engine>/<dataset>/<repeat>`, removed after each run.
  - A runner crash is recorded as a failed row ("runner crashed: ...", last 2000 characters of the traceback) and the matrix continues; so is a bad parameter section ("FAILED to expand params").
  - Remote scratch data is cleaned once at the end, unless `keep_remote_data`; cleanup refusals and failures are printed, never fatal.
  - Ends "N/M runs completed ok. Results: <file>". Always exits 0.
- **Results file** (`results.jsonl`, append-only, one JSON object per line): engine, dataset, direction, params, seconds, num_bytes, `MB_s` (decimal megabytes per second), verified, ok, skipped, reason, lane, endpoint, timestamp, repeat_index, `stderr_tail` (last 2000 characters, credentials redacted), `bytes_source`, `verify_method`, `loopback` (both ends on this machine; not comparable with network rows), `timing_resolution_s`.
- **Shared rules for all runners**: a missing tool is a skipped row, never an error; a timed run that moved less than 99 percent of the dataset's bytes is a failed row ("the destination was already partly warm, timing is meaningless"; 0 bytes: "nothing was moved"); spot-check verification re-hashes up to 3 randomly chosen files at the destination (size, then SHA-256); a failed verification leaves the row ok with `verified=false` and the reason.
- **Safety guard**: every delete the harness makes (rclone purge of the remote scratch folder, removal of the robocopy target, emptying a download destination) is refused unless some component of the target path contains `_bench` ("refusing to <action> ...: no '_bench' component in the path ... or re-run with --allow-destructive-endpoint"). Paths are read from local paths, named rclone remotes (`remote:path`) and inline rclone connection strings (`:backend,params:path`). A refused delete fails that run. With the override (flag or `allow_destructive_endpoint = true`) the run prints "WARNING: --allow-destructive-endpoint is set -- purge/rmtree targets are NOT restricted to '_bench' scratch paths for this run."
- Emptying a destination that still holds files after the delete fails the run ("Timing a transfer into a warm destination measures nothing.").
- Inline credentials (`pass`, `password`, `pass2`, `key_pem`, `api_key`, `token`, `secret_access_key`, `client_secret`) are replaced with `***` in every message and in stored error output.

## The sync benchmark: rclone over SFTP and SMB
(source: bench/ccbench/runners/_rclone_common.py, bench/ccbench/runners/rclone_sftp.py, bench/ccbench/runners/rclone_smb.py)

- Needs `rclone` on PATH (else skipped "'rclone' not found on PATH"). No rclone configuration file is used: each run builds an inline connection string.
- **SFTP target**: `:sftp,host=<host>,user=<user>,key_file=<key>,port=<port>:<remote_path>/<dataset>/<direction>`.
- **SMB target**: `:smb,host=<host>,user=<user>,pass=<obscured>,domain=<domain>:<share>/<remote_subpath>/<dataset>/<direction>`; the password is read from the environment variable named by `password_env` and obscured with `rclone obscure` (15 s; falls back to the plain value if that fails).
- **Self-test mode**: with `local_test_dir` set, the target is the local folder `<local_test_dir>/_bench_sftp|_bench_smb/<dataset>/<direction>` and rows are marked loopback.
- **Parameter combinations**: every combination of `transfers` and `multi_thread_streams` (plus `sftp_chunk_size_kib` for SFTP), without duplicates. On "up", SFTP pins multi-thread streams to 0 (SFTP cannot multi-thread uploads); SMB sweeps them both ways.
- **Flags passed**: `--transfers N --multi-thread-streams N [--sftp-chunk-size <N>Ki]` plus statistics flags `--use-json-log --stats 10s --stats-log-level NOTICE -v`.
- **Up**: untimed purge of the target (guarded, 120 s; a timeout or failure to start fails the run as "pre-clean failed"; a non-zero exit is tolerated), then timed `rclone copy <dataset> <target>` (3600 s limit).
- **Down**: untimed seed `rclone copy <dataset> <target> --transfers 8` (1800 s; a failure or timeout fails the run "seed failed"), empty the local destination (guarded), then timed `rclone copy <target> <destination>` (3600 s).
- **Results**: non-zero exit fails ("rclone exit N", with redacted error output); a timeout fails ("timeout after N s"); moved bytes come from rclone's JSON statistics (or its "Transferred:" line) with `bytes_source` `rclone-stats`, else the dataset total with `manifest-fallback`. Verification: downloads are spot-checked; uploads compare an `rclone lsjson -R --files-only` listing (300 s) with every manifest file's size (`remote-size-listing`), or `exit-code-only` with "NOT verified" when the listing is unavailable.
- **End-of-matrix cleanup**: `rclone purge` of each target that was used (guarded).

## The sync benchmark: robocopy over SMB
(source: bench/ccbench/runners/robocopy_smb.py)

- Windows only (elsewhere skipped "robocopy is Windows-only"); needs `robocopy` on PATH. Target `<unc_path>/<dataset>/<direction>` (or `<local_test_dir>/_bench_robocopy/<dataset>/<direction>`, loopback); with neither configured the run crashes with "robocopy_smb endpoint needs 'unc_path' (or 'local_test_dir' for selftest)".
- Parameter: `mt` threads (default sweep 1, 8, 16, 32). Command `robocopy <src> <dst> /E /MT:<mt> /R:1 /W:1 /NFL /NDL /NP /NJH`. Exit codes 0 to 7 count as success, 8 or more as failure.
- **Up**: guarded pre-clean of the target (fails if files survive), then the timed copy (3600 s). **Down**: untimed seed into the target (1800 s; exit 8+ fails "seed failed"), empty the destination (guarded), then the timed copy back.
- Bytes come from robocopy's "Bytes :" summary line (second column, k/m/g treated as binary) with `bytes_source` `robocopy-summary`, else `manifest-fallback`. Short transfers fail as above. Verification: downloads spot-checked; uploads compared by listing sizes on the target (`remote-size-listing`).
- End-of-matrix cleanup removes each target (guarded).

## The sync benchmark: Syncthing pair
(source: bench/ccbench/runners/syncthing.py)

- Needs the `syncthing` binary (or the `[endpoints.syncthing] binary` path); missing gives a skipped row ("configured syncthing binary not found: ..." or "'syncthing' not found on PATH"). One parameter combination per direction (nothing to tune).
- `direction = "bidirectional"` is a skipped row ("syncthing runner cannot measure a true bidirectional sync ... Use direction = \"both\""); anything other than up or down is skipped too.
- Probes `syncthing --version` once per binary (30 s); supports major versions 1 and 2 with their different command shapes (v2: `generate --config --data --no-port-probing`, `device-id`, `serve ... --no-browser --no-restart --no-upgrade --no-port-probing`; v1: `generate --no-default-folder`, `--device-id`, daemon with `--no-browser --no-restart --no-default-folder`). An unreadable or other major version is a skipped row.
- **Each run**: creates a temporary workspace `ccbench-_bench-syncthing-*`; copies the dataset into the sending side's folder ("editor" sends for up, "nas" sends for down); generates two configs, starts two daemons on free localhost ports (GUI ready within 20 s, else the run fails); disables global and local discovery, relays and NAT traversal and declines usage reporting; sets listen addresses on 127.0.0.1; restarts if required; pairs the two devices (auto-accept folders) and shares folder `ccbench-bench` (send-receive, rescan every 5 s, file watcher on, permissions ignored).
- Waits untimed up to 60 s (polling every 0.05 s) for the receiver to connect; no connection fails the run ("peers never connected within 60s -- nothing was measured").
- Timed wait for completion (default limit 1800 s): complete only when the receiver's global index holds at least the seeded byte count, it needs 0 bytes and is idle. Polls every 0.05 s for the first 10 s, then every 0.5 s. Timeout fails ("sync did not complete within ...", saying whether the index ever arrived).
- Bytes moved are the size of what landed (dot-files excluded), `bytes_source` `destination-listing`; short transfers fail; downloads spot-checked. Every row is `loopback=true` and `endpoint` `localhost-pair`; `timing_resolution_s` is 0.05 plus the poll interval at completion.
- Always stops both daemons (REST shutdown, then terminate, then kill, 10 s each) and removes the workspace unless `keep_remote_data`.
- UNREACHABLE: the docstring says `remote_address` can point the pair at a real host; no code reads such a key.

## The sync benchmark: network ceiling and Tailscale path
(source: bench/ccbench/runners/iperf3.py)

- Needs `iperf3` on PATH and `[endpoints.iperf3] host` (else skipped "no iperf3 host configured"); port default 5201.
- Combinations: each `parallel` value (default 1, 4, 8) with `duration_s` (default 10). Command `iperf3 -c <host> -p <port> -P <parallel> -t <seconds> -J`, plus `-R` for "down" (server sends); 120 s limit.
- Non-zero exit, unparseable output or an error in the JSON fails ("iperf3 exit N: ..."). Otherwise bytes and seconds come from the receiver's summary (`bytes_source` `iperf3-sum-received`, `verify_method` `iperf3-goodput`, always `verified`). A host of 127.0.0.1, ::1 or localhost marks the row loopback.
- **Tailscale check**: runs `tailscale status --json` (15 s; local query only), finds the peer by host name, DNS name, node key, or an IP containing the given text; the path is direct when the peer has a current address (`CurAddr`), relayed otherwise. A relayed path prints "WARNING: Tailscale path to ... is RELAYED via DERP (<region>) -- CurAddr is empty ... Check UDP 41641 forwarding / NAT traversal before trusting any transfer benchmark numbers." Description strings: "DIRECT via <address> (home DERP <region>)" or "RELAYED via DERP <region> (no direct CurAddr)".

## The sync benchmark: the report
(source: bench/ccbench/report.py)

- `ccbench report` flags: `--results` (default `results/results.jsonl`), `--out` (default `results/report.md`), `--baseline-mbps` (default 60.0), `--since` (an ISO date or date-time in local time, or `<N>h` / `<N>d`; unreadable values print an explanation and exit 1).
- No results: "no results found at ...", exit 1. With `--since`: "--since X: N of M rows kept"; none kept: "nothing was recorded in that window -- widen --since or drop it", exit 1.
- Writes the Markdown file, prints "wrote report -> <path>" and the whole report.
- **Content**:
  - Title "# ccbench results", and when `--since` was used a line saying only runs at or after it are included.
  - Per lane (A video originals up, B proxies down, C everything else, `net` raw network ceiling, `?` unclassified; lane taken from the row, or for old rows guessed from dataset name and direction): a table sorted by median MB/s with engine, direction, dataset, params, median, min, max, n (ok/total), verified (and how), where bytes came from, loopback ("YES -- not comparable"), and notes (skipped or FAILED reason; "BLENDED: these N repeats span X -- the median mixes separate sittings; re-render with --since" when repeats span more than 6 hours; "clock +/-X s on a Y s run (Z% instrument error, polled not bracketed)" when the clock resolution is at least 2 percent of the run).
  - "Recommended per-lane config" for A, B and C: the winner is the highest median among successful combinations, preferring non-loopback, then verified; with caveats (not verified, loopback in bold, manifest byte fallback, the two measurement notes). Gives the exact flags: for rclone every swept flag including zeros (`--transfers N --multi-thread-streams N --sftp-chunk-size NKi`; old megabyte rows flagged as invalid), for robocopy `/E /MT:N /R:1 /W:1`, for Syncthing "use it as configured". No data: "No successful runs recorded for this lane yet."
  - "Did we beat Resolve Cloud?" marked "INTERNAL ONLY -- do not reproduce in customer-facing material", reading the baseline both as megabits per second (divided by 8) and as megabytes per second, and for each lane the winner and whether it "beats both readings", "beats the Mbps reading only" or "does NOT beat either reading" (with a loopback note).

## The sync benchmark: self-test
(source: bench/ccbench/selftest.py)

- `ccbench selftest [--workspace DIR] [--keep]`: runs a miniature matrix entirely on this machine with no network endpoint. Workspace defaults to a temporary folder; a given workspace is always kept.
- Generates tiny datasets (2 large files of 2 MiB; 20 small files of 10 to 200 KiB, seed 1), then runs lanes A (large up), B (large down), C (small both) with 1 repeat, verification on, rclone SFTP and SMB against local folders (`transfers` 1 and 4, `multi_thread_streams` 0 and 4, chunk 255 KiB), robocopy (`mt` 1 and 4) to a local folder, the Syncthing pair, and, when `iperf3` exists, a local iperf3 server on a free port with a 2 s, 1-stream test (otherwise prints that iperf3 checks will show as skipped). Always re-runs everything.
- Writes `results.jsonl` and `report.md` in the workspace, prints the report, removes the generated data and work folders unless kept, and ends "selftest artifacts: <results>, <report>". Exit 0.

## Top-level repository files a release depends on
(source: Build Command.txt, .gitattributes, .gitignore, feed/)

- **`Build Command.txt`**: one saved command line for the operator: load the secrets, set `CCSYNC_MIN_VERSION` to `0.7.0`, and run `tools\ship.cmd -DashboardUrl "http://100.71.216.3:8480" -AdminUser alex -AllowUnsignedBinary`. (Nothing in `ship.ps1` reads `CCSYNC_MIN_VERSION`; only the macOS scripts pass it to the signer.)
- **`.gitattributes`** (line endings): every file is normalised (`text=auto`); LF is forced for `*.sh`, `*.bash`, `dashboard/deploy/run.sh`, `dashboard/deploy/select_code_root.py`, `installer/macos_bootstrap.sh`, `installer/macos_uninstall.sh`, `tools/release_macos.sh`, `tools/build_onboard_macos.sh`, every `Dockerfile`, `Dockerfile.*` and `*.dockerfile`, workflow YAML, `dashboard/deploy/*.yaml`, `dashboard/deploy/sftp/sshd_config`, the vendored-copy pairs the build compares byte for byte (b-roll indexer files, the companion's `broll_vlm` and `music_clap`, ytdl and identity copies, music indexer files), every `*.lock` and `requirements*.txt`; CRLF for `*.ps1`; `*.exe`, `*.png`, `*.ico` are binary.
- **`.gitignore`** rules a release depends on: `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/`, `.tools/`, `.cache/` (the fetched ffmpeg tarball), `dist/`, `build/`; the real `site.toml` (but not the server test fixture); secrets and personal data (`.env*`, `*.pem`, `*.key`, cookie files, `identity.json`, `rclone.conf`, `*.db` and its WAL/SHM files); `private/`; the local vendor-feed folder `feed/`; the ship journal `tools/.ship-state.json`; b-roll indexer run outputs; CI JUnit reports `/junit-*.xml`.
- **`feed/`** (untracked, the local working copy of the vendor feed that `publish_feed.py --feed-dir .\feed` writes): `channel.json` and `channel.json.sig`; `windows/` (companion 0.9.0 to 0.9.91 exes and onboard 1.0.36 to 1.0.47 exes), `macos/` (companion binaries and onboard zips), `linux/` (dashboard bundles 0.6.2 to 0.7.76); and the music audio model `music-clap-audio-1.onnx` (about 280 MB) with `music-clap-audio-1.params.json` (feature-extractor parameters for the `laion/larger_clap_music_and_speech` export: 48 kHz, 10 s, 64 mel bands, opset 17, fp32). The local channel (generated 2026-11-10) has 22 package records, `current` companion 0.9.91 on both platforms, dashboard 0.7.76, onboard 1.0.44 (macOS) and 1.0.46 (Windows), and a `dashboard_image` still naming tag 0.7.24.

## Looks redundant or overlapping

- Four different routes publish a companion or installer into one dashboard's upgrade channel: `installer/build_editor_package.ps1` (via `ship.cmd`), `release_macos.sh --publish`, `build_onboard_macos.sh --publish`, and `publish_package.py`. The two shell scripts each carry their own curl login, upload and password-handling code (the password block is copied byte for byte between them).
- Four routes reach the vendor feed: `ship.cmd -PublishFeed`, `publish_latest.py`, `release_customers.py`, and `publish_feed.py` by hand. Only `publish_feed.py` holds the CI gate for all of them, while `publish_latest.py` and `release_customers.py` also run their own CI checks first.
- The CI-vouching rule for untested builds is implemented once (`publish_latest.tests_vouched_by_ci`) but called from three places (`publish_feed`, `publish_package`, `publish_latest`).
- Version comparison is written separately in `ship.ps1` twice (`Compare-Version` and `Test-VersionAtLeast` in `ship_gates.ps1`), in `sign_release.py`, `publish_latest.py`, `check_feed_freshness.py`, `select_suites.py` (a different, regex-only form) and `check_deploy_drift.ps1`.
- Vendored-file parity is checked by `release.ps1` (11 pairs) and `release_macos.sh` (10 pairs) with different lists.
- Developer ID signing and notarisation logic is duplicated between `release_macos.sh` and `build_onboard_macos.sh`, with different behaviour on a staple failure.
- The site-file `[stack]` reader (`Get-SiteScalar`) is copied in `ship.ps1` and `check_deploy_drift.ps1`.
- Git-bash discovery for the server suite is copied in `ship.ps1` and `run_all_tests.ps1`.
- The pinned rclone download step (two sources, one checksum) is copied four times across `ci.yml` (Windows and macOS jobs), `release-windows.yml` and `release-macos.yml`.
- The CRLF gate exists in `ci.yml` (switched off with the linux job) and in `image.yml` (narrower file list).
- The rollout numbers appear in three places: `ship.ps1`'s closing rollout line (from health), `check_deploy_drift.ps1`'s ROLLOUT section and its `-Watch` loop (from the admin packages view).
- Two icon generators split the icon files between them (`gen_icons.py` with Pillow, `make_icons.js` with Chrome); `make_icons.js` keeps a maskable drawing path nothing uses.
- `ship.ps1` steps 0 and 0c run the dashboard suite, and step 2a (`release.ps1`) runs it again in the same ship.
- The Android build, the Cards offline test and the mobile sweep each drive Chrome over DevTools with their own copy of the connection code.

## Claims the code does not back

- `tools/release_key.py`, `backup` docstring: says there is deliberately NO passphrase wrap because a scrypt-plus-XOR construction would be homemade cryptography; the same file's `encrypt` subcommand implements exactly a scrypt-derived HMAC keystream with an HMAC tag.
- `tools/publish_package.py` docstring: "min_version is whatever you pass, default 0.0.0"; the default is the tracked floor file, and a floorless companion or onboard record is refused.
- `tools/load_secrets.ps1` docstring: says it handles "optionally ... the code-signing secrets" and that `-Clear` removes "the four variables"; the code stores only the five listed names (no signing secrets) and clears five.
- `tools/run_all_tests.ps1` docstring: says broll/web "still borrows the venv of the old standalone broll-platform checkout (the in-repo copy has none yet)"; the code uses `broll\web\.venv` with a dashboard-venv fallback.
- `tools/ship.ps1` image-mode refusal prints `python tools\build_dashboard_bundle.py` as the first step of the recipe; that command without `--out` is refused by the bundle tool ("--out is required").
- `tools/ship.ps1` synopsis lists the step-0 suites as server and onboarding; the code also runs the dashboard suite there (step 0c).
- `.github/workflows/release-windows.yml` header: "MANUAL ONLY (workflow_dispatch)"; it also runs on every push to `main`. Its comment that `release.ps1` "does NOT install PyInstaller" is stale: `release.ps1` installs `pyinstaller==6.21.0` itself.
- `.github/workflows/release-macos.yml` header: "MANUAL ONLY" and "The script currently AD-HOC signs ... release_macos.sh ignores [CCSYNC_APPLE_DEV_ID] today"; the workflow also runs on push to `main`, and `release_macos.sh` does sign with Developer ID when that variable is set. The wizard manifest it writes always says `signed_binary: false` regardless.
- `.github/workflows/release-dashboard.yml` comment: "same posture as release-windows.yml: a release is a decision, not a consequence of a push"; release-windows now builds on every push.
- `tools/release_macos.sh` success line says "(N pairs: ytdl_common.py + the broll_vlm set)"; it also checks the music and identity pairs, and it does not check the two `broll/web` copies that `release.ps1` checks.
- `tools/check_licenses.py` docstring: names python-xlib as "pystray's Linux backend ... in the companion lock"; the allowlist file states pystray was removed from the companion lock.
- `tools/mobile_sweep.js` header: "--json writes the same findings to a file"; the JSON report is always written (default `docs/mobile/report.json`), and the comment's "seventeen" pages are sixteen in the list.
- `tools/Dockerfile.indexer-gpu` comment: whisper's environment script "is invoked with --cpu inside a container"; nothing in the image invokes it.
- `bench/README.md`: download spot checks are "seeded, so the same 3 files are checked across an A/B comparison"; `spot_check` is called with no seed, so the sample is random each run. It also says to "point `--results` at a fresh file" for `ccbench run`, which has no `--results` flag (the matrix's own `--rerun` help repeats this).
- `bench/ccbench/runners/iperf3.py` module docstring: direct versus relayed is "`Peer[*].Relay` empty vs set"; the code (correctly, per its own function docstring) decides on `CurAddr`.
- `bench/ccbench/runners/syncthing.py` docstring: the pair can be pointed at a real host via the endpoint's `remote_address`; no code reads that key.
- `bench/bench.toml.example` `[tailscale] peer_hint` is described as used by `tailscale-check`; the command only reads `--peer`.

## Could not determine

- Whether `CCSYNC_MIN_VERSION=0.7.0` in `Build Command.txt` reaches anything: `ship.ps1` does not read it, and `installer/build_editor_package.ps1` (outside this part) was not read. If it does reach the signer it is below the tracked floor (0.9.75) and `publish_feed.py` would refuse a floor drop.
- `publish_latest.py` preflight checks only `~/.ccsync-release/release.key` and ignores `CCSYNC_RELEASE_KEY`, while the signer honours it; whether anyone relies on a non-default key path was not determinable.
- What `installer/build_editor_package.ps1` does in step 2b of the ship (exit code 3 meaning, the onboard Authenticode refusal, the password prompt) is described only from `ship.ps1`'s side; that script is outside this part.
- The dashboard routes the tools call (`/api/v1/health` rollout fields, `/api/v1/admin/packages`, `/api/v1/jobs/*`, `/api/v1/companion/package/*`) are described from the caller's side only.
- Whether the local `feed/` folder is still the source of anything published (it is gitignored and `publish_feed.py` merges the live channel over it), and why its `dashboard_image` names tag 0.7.24 while its current dashboard bundle is 0.7.76.
- The licence text files under `tools/notices_extra/` (`cpython.txt`, `openssl.txt`, `lgpl-3.0.txt`, `pyinstaller-bootloader.txt`, `tcl-tk.txt`, `libpq.txt`, `dists/*.txt`, `music_text_encoder/LICENSE`) were read only to their headers (title, coverage and source lines); the verbatim licence bodies were not read line by line, as they carry no behaviour.
- The `tools/android/fixture/*.png` files and the `feed/` binaries were not opened (binary data); `.pytest_cache` contents and `bench/ccbench.egg-info` (build metadata) were not inventoried beyond the console entry point `ccbench = ccbench.cli:main`.
