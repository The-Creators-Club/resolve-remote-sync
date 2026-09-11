# install-onboard - installers (Windows/macOS bootstrap, upgrade, uninstall, package build) and the first-run wizard

Files read (with approximate coverage):
- `installer/windows_bootstrap.ps1` (the 097f5a3..HEAD diff in full; sections 1a, the drive-mapping/foreign-drive block, capability plumbing, companion install ~line 2200 read directly; ~40% of the whole file)
- `installer/windows_uninstall.ps1` (100%), `installer/windows_upgrade.ps1` (~70%: manifest read, swap, `.prev` rollback, relaunch confirm), `installer/drive_mapping.ps1` (`Get-DriveMapping`, `Test-IsElevated`)
- `installer/macos_bootstrap.sh` (the diff in full; arg parsing, site-value resolution, `install_uninstaller`, `retire_legacy_agent`, the companion LaunchAgent branch, config seeding; ~30% of the whole file), `installer/macos_uninstall.sh` (~80%)
- `installer/build_editor_package.ps1` (the publish/version-parity/signing block, lines 1040-1120)
- `onboarding/steps.py` (the diff in full plus EULA, breadcrumb, cleanup-plan, `ensure_config`, `run_bootstrap`, `installer_on_forbidden_drive`; ~60%), `onboarding/onboard.py` (the diff in full plus the editor worker and finish pages; ~50%)
- `onboarding/build_onboard.spec`, `onboarding/build_onboard_macos.spec` (100%), `onboarding/tests/*` (skimmed; `test_site_prefix_handoff.py` read closely)
- Cross-checks outside the territory (read only): `dashboard/src/ccsync_dashboard/api.py` `POST /api/v1/ssh-key`, `companion/src/ccsync_companion/root_guard.py`, `tools/release.ps1` manifest shape, `KNOWN_BUGS.md` CR-119.

Tests run:
- `cd onboarding; python -m pytest tests -q` -> 391 passed
- all seven `installer/tests/*.ps1` via `powershell -NoProfile -ExecutionPolicy Bypass -File` -> all pass
- `bash installer/tests/test_macos_site_values.sh` -> all pass
- ad-hoc probe from the repo (scratchpad script, `PYTHONPATH=companion/src`) proving finding 2

## Findings

### install-onboard-1 - the macOS "installer is on a mounted volume" guard refuses every frozen wizard run from the home folder (`/Users` is a mount boundary on APFS volume groups)
- Severity: high
- Confidence: PLAUSIBLE (cannot execute on macOS from here; the Mac at 100.66.62.41 did not answer SSH this session)
- Where: `onboarding/steps.py:3305-3325` (`installer_on_forbidden_drive`, darwin branch) with `_default_is_mount` at `onboarding/steps.py:2128`; caller `onboarding/onboard.py:1137`; test that hides it `onboarding/tests/test_site_prefix_handoff.py:216-219`
- What: the darwin branch walks from `posixpath.dirname(sys.executable)` up to `/` and returns True at the first directory `os.path.ismount()` calls a mount point. On macOS 10.15+ the user's data lives on a separate APFS volume reached through firmlinks, so `/Users` has a different `st_dev` from `/` - which is exactly `posixpath.ismount`'s test. Every path under `/Users/...` therefore hits a "mount point" two or three steps up, and the guard fires for a wizard run from anywhere in the home folder.
- Failure scenario: a Mac editor downloads `CCSync Onboarding.app` to `~/Downloads` (or Desktop), accepts the EULA, signs in, clicks BEGIN INSTALL. `_worker_editor` refuses at its first line and logs the Windows-worded refusal ("this installer is running from P: or a network share ... Copy onboard.exe to your Desktop and run it from there") and renders the failed-install page. Copying it to the Desktop does not help, because the Desktop is under `/Users` too. There is no way to complete a macOS wizard install short of running the unfrozen source.
- Evidence: code read. `posixpath.ismount` compares `st_dev` of the path with `st_dev` of `realpath(path/..)`; on a volume-group Mac `df /Users` reports `/System/Volumes/Data` while `/` is the (separate) System volume, so the two differ. The three darwin tests all inject `is_mount=lambda p: False` or a single hand-picked path, so the default `os.path.ismount` is never exercised - `test_the_boot_volume_is_fine` mocks away precisely the thing that breaks (brief rule 7). Compare `companion/src/ccsync_companion/root_guard.py:376-390`, which only ever calls `ismount` on `/Volumes/<name>` entries and never walks up a path.
- Ledger: new; a defect introduced by CR-119's install-onboard-4 fix ("`installer_on_forbidden_drive` refuses under `/Volumes/` on macOS", KNOWN_BUGS.md:10492).
- Suggested fix: drop the walk-up and keep only the `startswith("/Volumes/")` test (plus, if an external SSD elsewhere is really wanted, compare `os.stat(exe).st_dev` against `os.stat("/System/Volumes/Data").st_dev` / the home directory's device rather than "any mount boundary"). Also give the darwin refusal its own message: it names a drive letter and `onboard.exe`, neither of which exists on a Mac.

### install-onboard-2 - `run_bootstrap` still cannot pass `canonical_prefix` / `tree_name` when the manifest fetch failed, which is the only case CR-119 was written for
- Severity: medium
- Confidence: CONFIRMED
- Where: `onboarding/steps.py:1424-1425` and `:1471-1474` / `:1505-1511` (`run_bootstrap`), against `onboarding/steps.py:3046-3062` (`ensure_config`, which uses `site_canonical_prefix(site or None)`); caller `onboarding/onboard.py:1190`; `onboarding/onboard.py:541-545` (`_site()` returns None on a failed fetch)
- What: `ensure_config` resolves the prefix through the CACHED manifest when `site is None`, but `run_bootstrap` does `site = site or {}` and then reads `site.get("canonical_prefix")` off that dict only. With `site=None` it therefore passes no `-CanonicalPrefix` / `-TreeName` (Windows) and sets no `CCSYNC_CANONICAL_PREFIX` / `CCSYNC_TREE_NAME` (macOS), so the bootstrap re-fetches; a fetch that also fails there is explicitly non-fatal and falls back to `P:\` / `CCSync`. That is the exact wizard-vs-bootstrap disagreement CR-119 says it fixed - the flags only help in the case where the fetch succeeded and nothing was ever wrong.
- Failure scenario: a Q:\ site, second wizard run, dashboard briefly unreachable (or the token rejected) so `fetch_site` returns `{}`. config.toml gets `canonical_prefix = "Q:\"` (from the cache) and the machine gets P: mapped, share `CCSync_P`, logon task `CCSync-SubstP`. The companion, the uninstaller and every Resolve clip path then address Q:, which does not exist.
- Evidence: probe run from `onboarding/` with `steps.site_mod.cached_site` stubbed to `{"canonical_prefix": "Q:\\", "tree_name": "Pool"}` and `site=None`:
  ```
  WIN passes -CanonicalPrefix: False | -TreeName: False
  MAC env CCSYNC_CANONICAL_PREFIX: None
  ensure_config -> ['local_root = "C:\\\\Pool"', 'canonical_prefix = "Q:\\\\"']
  ```
  `onboarding/tests/test_site_prefix_handoff.py:187-192` pins the incomplete behaviour by asserting the source literally contains `site.get("canonical_prefix")`.
- Ledger: regression of CR-119 (install-onboard-2) - recorded FIXED, only half fixed.
- Suggested fix: in `run_bootstrap`, resolve both values the way `ensure_config` does (`site_canonical_prefix(site or None)` / the tree-name sibling, i.e. through `cached_site()`), and change the test to assert the cache fallback rather than the raw `.get`.

### install-onboard-3 - the Windows uninstaller announces "removed program binaries" whether or not anything was removed, after it has already deleted the Apps & features entry
- Severity: medium
- Confidence: CONFIRMED
- Where: `installer/windows_uninstall.ps1:422-433` (entry removed first) and `:434-441` (`Remove-Item -Recurse -Force -ErrorAction SilentlyContinue` followed by an unconditional `Write-Step "removed program binaries: $BinDir"`)
- What: the deletion is silenced with `-ErrorAction SilentlyContinue` and its result is never re-read, so a locked file (the companion exe whose `Stop-Process` has not finished releasing the image, an AV scan, the running `windows_uninstall.ps1` itself now that OPS-17 installs it into `$BinDir`) leaves the binaries in place while the script prints success. Every other removal in this file was deliberately rewritten to re-read the machine afterwards (`$unmapSettled`, `Test-SmbShareGone`); this one was not.
- Failure scenario: an editor uninstalls while the companion is mid-write. `ccsync-companion.exe` survives; the uninstall entry has already been deleted (it is removed first, by design), the autostart entries are gone and the run ends with "CCSync uninstall complete". The machine now has the app on disk, nothing in Apps & features to retry with, and a report that says it was removed. A re-run is the only cure and nothing suggests one.
- Evidence: code read; `Test-UninstallEntry.ps1` exercises `Unregister-UninstallEntry` in isolation and asserts nothing about the binaries, so the suite cannot catch it.
- Suggested fix: re-read `Test-Path $BinDir` (excluding `$PSCommandPath` and `drive_mapping.ps1`) after the delete and warn with the exact leftover path when files remain; consider deleting the Apps & features entry only after the binaries are actually gone, or re-registering it when they are not.

### install-onboard-4 - the Apps & features entry gets no icon on a first install, because it is registered ~1250 lines before the companion exe exists
- Severity: low
- Confidence: CONFIRMED
- Where: `installer/windows_bootstrap.ps1:949` (`-IconPath $CompanionExePath`) and the guard `if ($IconPath -and (Test-Path -LiteralPath $IconPath))` at `:889-891`; the exe is copied at `installer/windows_bootstrap.ps1:2221`
- What: section 1a runs before Tailscale, rclone, Syncthing, the drive mapping and the companion install. On a fresh machine `%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe` does not exist yet, so `DisplayIcon` is skipped - permanently, since a re-run overwrites the same key only if the bootstrap is run a second time.
- Failure scenario: every first-time editor sees a blank-icon "CC Sync" row in Settings > Apps > Installed apps, which is the shape an unwanted/unsigned program has.
- Evidence: line numbers above; `Register-UninstallEntry` returns `$true` regardless, so the run reports success.
- Ledger: new (OPS-17 follow-up).
- Suggested fix: write the `DisplayIcon` value from the companion-install section (section 9) once the exe is in place, or register the entry there instead.

### install-onboard-5 - `normalise_dashboard_url` guesses `http://` for any explicit port that is not 443, and that guess is written into the field and into config.toml
- Severity: low
- Confidence: CONFIRMED
- Where: `onboarding/steps.py:900-925` (`normalise_dashboard_url`), used by `onboard.py:586-603` (`_normalise_dashboard_url_field`, which `set()`s the rewritten value back into `dashboard_url_var`, the same variable `_write_config_and_identity` passes to `ensure_config`)
- What: `if port and port != "443": scheme = "http"`. Tailscale Serve/Funnel on this deployment publishes TLS on 8443 as well (the client-share port), and an admin who hands an editor `nas.tail26290e.ts.net:8443` gets `http://nas...:8443`, which will not connect. The wrong guess is then persisted: the field is overwritten, so the value that reaches `config.toml`'s `dashboard_url` (and the companion's loopback origin allow-list, `loopback_guard.py`) is the unusable one.
- Failure scenario: editor types a hostname with a TLS port, sees "refused the connection: ... nothing is serving the dashboard on that port", and the amber note only tells them the scheme was added - not that it was the wrong one for their port.
- Evidence: code read; `_dashboard_url_note` shows the rewrite but the editor must guess which half is wrong.
- Ledger: new (OPS-6 follow-up).
- Suggested fix: treat 443 and 8443 (and any port whose host is a `.ts.net` name) as https, or probe https first and fall back to http on a connection error rather than deciding from the port alone.

### install-onboard-6 - a macOS run with no companion binary removes OUR LaunchAgent but leaves the legacy `com.creatorsclub.*` companion agent loaded
- Severity: low
- Confidence: CONFIRMED
- Where: `installer/macos_bootstrap.sh:2443-2481` (the `COMPANION_MISSING = 1` branch removes only `$COMPANION_PLIST`) vs `:2482-2486` (the else branch calls `retire_legacy_agent "$COMPANION_PLIST_LEGACY"`)
- What: the legacy-label retirement is inside the else branch only. On the path where the companion could not be installed (no `DASHBOARD_TOKEN`, no `--companion-file`, a failed download) the script deletes the correctly-labelled agent and leaves the pre-2026-08-17 one running an old companion - the very process that holds loopback 8899 against the new one when a later run succeeds. CLAUDE.md's rule ("any installer that writes the new label must boot out and delete the legacy pair") is satisfied only on the happy path.
- Failure scenario: a Mac upgraded from a 2026-08 build re-runs the bootstrap without a token; the run ends with the big "THE SYNC APP IS NOT INSTALLED" banner while an old companion keeps running and reporting under the legacy label.
- Evidence: line numbers above; `installer/tests/test_macos_site_values.sh` does not cover this branch.
- Suggested fix: hoist `retire_legacy_agent "$COMPANION_PLIST_LEGACY" "$COMPANION_LABEL_LEGACY"` above the `if`, beside the unconditional Syncthing one at `:1918`.

## Coverage note
- The three `INSTALLER_VERSION` copies plus `build_onboard_macos.spec`'s `CFBundleShortVersionString` all read 1.0.41 and agree; `build_editor_package.ps1` gates on the first three (the spec only by the pytest parity test).
- Em-dash scan of every `.ps1` / `.sh` / `.py` / `.spec` in the territory: one hit, in a comment in `windows_upgrade.ps1` (exempt). No user-visible em dashes.
- No secret reaches the new OPS-5 install log: the fleet token travels by env var to both bootstraps and neither echoes it; root logging is at INFO and `identity.py` logs no token values.
- EULA asset is byte-identical across `docs/legal/`, `onboarding/assets/` and the companion, at version 1.0.
- `POST /api/v1/ssh-key` matches the wizard's payload and header exactly, and is non-fatal on an older dashboard as documented.
- NOT covered: I did not read `windows_bootstrap.ps1` sections 2-7 (rclone/Syncthing pinned downloads, rclone.conf, Syncthing folder wiring) or the bulk of `macos_bootstrap.sh` outside the diff; I did not test the OPS-4 streaming path against a real PowerShell child (only read `_stream_child`); the `.prev` rollback was read but not exercised beyond `Test-PrevRollback.ps1`; nothing here was tested on an actual Mac (finding 1 is unverified for that reason). The installer suites mock or slice every path that touches a real drive, share or launchd, so none of findings 1-6 could have been caught by them.

## OUT OF TERRITORY
- `installer/windows_upgrade.ps1` rollback leaves `ccsync-release.json` describing the build that failed to start (the script says so out loud); `tools/check_deploy_drift.ps1` will report that machine as running a version it is not.
