# install-onboard — installer/, onboarding/, bench/, companion packaging surface

Files read (with approximate coverage):
- `installer/drive_mapping.ps1` (100%), `installer/windows_uninstall.ps1` (100%),
  `installer/windows_upgrade.ps1` (~90%: params, prev-rollback, config migration,
  relaunch/SHIP-2, licence gate, exit codes), `installer/windows_bootstrap.ps1`
  (~35%: OPS-7 console user, site-manifest/canonical_prefix resolution, shim
  writers, the whole drive-mapping + loopback-share + Explorer-label section,
  config seeding), `installer/build_editor_package.ps1` (~30%: CR-52 preflight,
  Connect-Dashboard, version helpers, the package file list, the LF guard),
  `installer/macos_bootstrap.sh` (~15%: header/`set -u`, site_value +
  canonical_prefix_letter, LaunchAgent write/retire/reload, companion install),
  `installer/macos_uninstall.sh` (100%).
- `onboarding/steps.py` (~45%: site helpers, EULA block, run_bootstrap,
  install_companion, merge_config_text/ensure_config, forbidden-drive),
  `onboarding/onboard.py` (~15%: the editor worker + `_site()`/`_drive_letter()`),
  both `.spec` files (100%), `onboarding/tests/*` (skim).
- `bench/ccbench/result.py`, `runners/base.py` (100%), rest skimmed.
- `companion/build.spec` (100%), `companion/launcher.py`,
  `companion/src/ccsync_companion/__main__.py`, `supervisor.py` docstring +
  `decide` contract, `config.py` DEFAULT_TOML_TEXT (checked for `[sections]`).
- `CLAUDE.md`, `KNOWN_BUGS.md` (grepped: R11, OPS-7/8, INST-*, CR-52, CR-68).

Tests run:
- `onboarding: python -m pytest tests -q` -> **336 passed**
- `bench: .venv\Scripts\python.exe -m pytest tests -q` -> **175 passed, 1 skipped**
- `bash installer/tests/test_macos_site_values.sh` -> **all pass**
- `Test-DriveMapParser.ps1` / `Test-LicenceGate.ps1` / `Test-PrevRollback.ps1` /
  `Test-ConsoleUser.ps1` -> **all pass**
- ad-hoc repro script (scratchpad `t.py`) for finding 1.

## Findings

### install-onboard-1 — the wizard writes `canonical_prefix = "P:\"` even on a Q: site, whenever the manifest fetch failed
- Severity: medium (high on any non-`P:` site)
- Confidence: CONFIRMED (reproduced)
- Where: `onboarding/steps.py:2614` (`ensure_config`, editor branch:
  `forced["canonical_prefix"] = _toml_string(site.get("canonical_prefix") or "P:\\")`);
  contrast `onboarding/steps.py:203` `site_drive_letter` and
  `onboarding/steps.py:164` `site_tree_name`, and the caller
  `onboarding/onboard.py:739` (`self.site = site or {}`).
- What: every other site-derived value in the wizard falls back to the CACHED
  manifest (`site_mod.cached_site()`) when the caller passes no manifest --
  `site_tree_name`, `site_drive_letter`, `default_local_root`,
  `default_base_local_root` all do. `ensure_config` is the single exception: it
  does `site = site or {}` and then reads `canonical_prefix` off that dict with a
  hardcoded `"P:\\"` fallback, never consulting the cache. `onboard.py` sets
  `self.site = site or {}` and passes it straight in, so a `fetch_site` that
  returned `{}` (a 404, a timeout, a transient tailnet blip -- `fetch_site`
  swallows every exception and returns `{}` by contract) makes the wizard write
  `P:\` into config.toml while the same process's `_drive_letter()` and the
  bootstrap it is about to launch both resolve `Q`.
- Failure scenario: site manifest publishes `canonical_prefix = "Q:\"`. The
  wizard's `fetch_site` fails once (dashboard restarting after a deploy is the
  documented case in `build_editor_package.ps1`'s own OPS-12 note). The wizard
  cleans up `CCSync-SubstQ` / `\\localhost\CCSync_Q`, prefills `C:\Creators_Club`
  from the cache, writes `canonical_prefix = "P:\"`, then runs
  `windows_bootstrap.ps1`, whose own fetch succeeds and maps `Q:`. The install
  reports success. The companion now rewrites every Resolve clip path against a
  drive letter nothing on the machine mounts.
- Evidence: with `steps.site_mod.cached_site` returning
  `{'tree_name':'Creators_Club','canonical_prefix':'Q:\\'}` and `site={}`:

  ```
  'local_root = "C:\\\\Creators_Club"'      <- from the CACHE
  'canonical_prefix = "P:\\\\"'             <- ignores the cache
  site_drive_letter (no site) -> Q
  site_tree_name  (no site) -> Creators_Club
  ```

  i.e. one call to `ensure_config` produces two site values resolved from two
  different sources. Directly violates CLAUDE.md's item-11 invariant ("both
  installers, both uninstallers and the companion read the same two keys").
- Ledger: new (extends installer-onboard-tools-3, 2026-08-21, which fixed
  `site_drive_letter` in the wizard but not this call site).
- Suggested fix: give `ensure_config` a `site_canonical_prefix(site)` helper with
  the same `cached_site()` fallback the siblings use (and reuse
  `_CANONICAL_PREFIX_RE` so a junk prefix degrades the same way), instead of
  `site.get(...) or "P:\\"`.

### install-onboard-2 — the drive letter is fetched twice, and nothing carries the wizard's answer to the bootstrap
- Severity: medium
- Confidence: CONFIRMED (by absence: the parameter does not exist)
- Where: `onboarding/steps.py:1091` (`run_bootstrap`, the Windows `cmd` list) and
  `installer/windows_bootstrap.ps1:64` (`param(...)`, no `-CanonicalPrefix`),
  `installer/windows_bootstrap.ps1:709-721`.
- What: `run_bootstrap` explicitly passes through the manifest values the
  bootstrap has flags for -- `-RemoteRoot`, `-NasSyncthingId`, `-SftpPort`,
  `-LocalRoot` -- with the comment "keeps ONE fetch per install". There is no
  flag for `canonical_prefix` (nor for `tree_name`), so the bootstrap makes its
  own `Invoke-RestMethod .../api/v1/site -TimeoutSec 8`. That fetch failing is
  explicitly NOT fatal (`Write-Warn2 "no site manifest ... using the values
  passed on the command line"`), and the fallback is the literal `"P:\"`. The
  wizard has already written config.toml (ensure_config runs before
  run_bootstrap, `onboard.py:1015` then `:1032`), and the bootstrap skips its own
  config seeding when the file exists (`windows_bootstrap.ps1:1922`), so the two
  halves can disagree with nothing to reconcile them.
- Failure scenario: same as finding 1 but with the failure on the other side --
  wizard fetch OK (`Q`), bootstrap fetch times out -> config.toml says `Q:\`,
  the machine gets `P:` mapped, share `CCSync_P`, logon task `CCSync-SubstP`. The
  wizard's cleanup list and the uninstaller (which read the letter from
  config.toml) will then never find them.
- Evidence: `awk '/^param\(/,/^\)/' installer/windows_bootstrap.ps1` shows the
  full parameter list; `-DriveLabel` exists, no prefix/letter parameter does.
  `grep -n 'env:CCSYNC' installer/windows_bootstrap.ps1` shows only
  `CCSYNC_DASHBOARD_TOKEN`, `CCSYNC_DASHBOARD_URL`, `CCSYNC_NAS_SYNCTHING_ID`.
- Ledger: new (same family as installer-onboard-tools-3 / COMMERCIAL_READINESS 11).
- Suggested fix: add `-CanonicalPrefix` (and `-TreeName`) to
  `windows_bootstrap.ps1`, resolved flag-first exactly like `-RemoteRoot`, and
  have `run_bootstrap` pass `site["canonical_prefix"]` when it has one. Same for
  `macos_bootstrap.sh` via `CCSYNC_CANONICAL_PREFIX`.

### install-onboard-3 — the uninstaller drops the SMB block rule while the share it scopes is still published
- Severity: medium (security: exposes the whole project tree over SMB)
- Confidence: CONFIRMED (logic; the trigger is a failed `Remove-SmbShare`)
- Where: `installer/windows_uninstall.ps1:266-283` (share removal) and
  `installer/windows_uninstall.ps1:292-296` (firewall rule gate).
- What: `$share` is captured BEFORE the removal attempt. The keep-the-rule guard
  is `if ($smbRule -and $share -and -not $unmapSettled)`, i.e. it only keeps the
  rule when the share was kept *because the unmap did not settle*. When the drive
  unmapped cleanly (`$unmapSettled = $true`) but `Remove-SmbShare` throws -- the
  `catch` calls it a "harmless leftover" and continues -- control falls into the
  `elseif ($smbRule)` branch and `Remove-NetFirewallRule` runs. The share
  `CCSync_<letter>` (path = the editor's whole local tree, per
  `New-SmbShare -Path $CCRoot`) survives with inbound TCP 139/445 no longer
  blocked. This is precisely the exposure `Set-SmbLoopbackFirewallRule` and
  COMMERCIAL_READINESS item 15 exist to close, and the comment above the block
  states the intended rule ("It also STAYS when the share stays").
- Failure scenario: an editor runs `windows_uninstall.ps1` from an elevated
  PowerShell; `Remove-SmbShare` fails (share in use / a handle open on the tree).
  Warning printed, uninstall reports complete, and the machine now serves its
  entire project tree to every network it joins, permanently.
- Evidence: read of the two adjacent blocks; `$share` is never re-read after the
  removal attempt (`grep -n 'Get-SmbShare' installer/windows_uninstall.ps1` shows
  exactly one call, at line 265).
- Ledger: new (regression risk against OPS-8's own stated rule, 2026-08-28).
- Suggested fix: re-read `Get-SmbShare -Name $ShareName` after the removal
  attempt and gate the firewall-rule removal on the share actually being gone,
  not on `$unmapSettled`.

### install-onboard-4 — `installer_on_forbidden_drive` is Windows-shaped and never fires on macOS
- Severity: low
- Confidence: CONFIRMED
- Where: `onboarding/steps.py:2841-2857`.
- What: the guard tests `sys.executable.upper().startswith("<letter>:")` or
  `startswith("\\\\")`. On macOS the tree is mounted at `/Volumes/<share>` (see
  `default_base_local_root`'s own note), which matches neither test, so a Mac
  editor who double-clicks the wizard out of the mounted NAS share gets no
  refusal -- the exact "pinned the package folder all day" failure the docstring
  cites, on the platform where the tree is normally a network mount.
- Failure scenario: Mac editor opens `onboard` from `/Volumes/TheCreatorsPool/...`;
  the wizard holds the file open server-side for the whole install and any
  unmount/remount step behaves unpredictably.
- Evidence: code read; no `/Volumes` or `os.path.ismount` check in the function
  (`_default_is_mount` exists at `steps.py:1693` but is only used by
  `_validate_local_root_macos`).
- Ledger: new.
- Suggested fix: on darwin, also refuse when `sys.executable` resolves under
  `/Volumes/` or under a mount point that is not `/` (reuse `_default_is_mount`).

## Coverage note

- **Not reached**: ~65% of `windows_bootstrap.ps1` (Tailscale/winget install,
  rclone remote + `rclone.conf` stanza rewrite, the Syncthing config/REST
  seeding, the Resolve prefs step, the final summary), ~85% of
  `macos_bootstrap.sh` (downloads/checksums beyond what the .sh test covers, the
  SMB mount, the Resolve Mapped Mount, the config seeding), ~70% of
  `build_editor_package.ps1` (the signing/publish/upload half, `-MakeCurrent`
  semantics against the dashboard API), `installer/*.md` and `docs/RELEASE.md`
  /`CONFIG.md`/`TREE_LAYOUT_AGNOSTICISM.md` were not audited for staleness.
- **Verified-and-cleared** (worth recording so nobody re-checks): the four copies
  of `INSTALLER_VERSION` (`windows_bootstrap.ps1:261`, `steps.py:125`,
  `macos_bootstrap.sh:56`, `build_onboard_macos.spec:229`) agree at 1.0.38 and
  `onboarding/tests/test_macos_steps.py:770-774` pins all four -- the fb276c7
  trap is covered. All three `EULA.md` copies are byte-identical and pinned by
  tests on both sides. `git ls-files --eol` is correct for every `.sh`.
  `Test-VersionAtLeast` / `eula_version_tuple` both compare numerically, so
  two-digit minors (`1.10` vs `1.9`, `0.10.0` vs `0.9.64`) are safe.
  `Get-DottedVersionParts` + `Test-MinVersionAboveVersion` (CR-52) are correct.
  `windows_bootstrap.ps1`/`windows_uninstall.ps1` read config.toml with
  `Select-String`, which I suspected of the INST-3 cp1252 bug -- **measured on
  this machine (ACP 1252) it decodes BOM-less UTF-8 correctly**, so it is not a
  finding. The `.spec` datas match what the code loads at runtime
  (`drive_mapping.ps1` beside the bootstrap, `assets/EULA.md`, the marks,
  `install_companion`'s posix chmod for the exec bit PyInstaller drops).
  The Stop-Process-vs-supervisor interaction in `windows_upgrade.ps1` step 1 is
  safe: `0xFFFFFFFF` is in `supervisor.DELIBERATE_EXIT_CODES` and
  `RELAUNCH_DELAY_SECONDS` is 10.
- **What the suites do not cover**: there is NO em-dash scan for any `.ps1` or
  `.sh` user-visible copy (only `test_macos_site_values.sh` checks one function,
  `low_space_message`); a byte scan found the installer scripts currently clean,
  but nothing keeps them that way. There is no test that
  `windows_bootstrap.ps1`'s parameter surface covers every manifest key
  `run_bootstrap` holds (finding 2 would have been caught by one). Nothing tests
  `merge_config_text`/`ensure_config` against a manifest-fetch failure (finding
  1). `installer/tests` has no coverage of the SMB share / firewall-rule
  lifecycle (finding 3). No test exercises the `.prev` rollback's effect on
  `ccsync-release.json` (the upgrade script says out loud that the version record
  is left WRONG after a roll-back; `check_deploy_drift.ps1` sha-verifies, so it
  degrades to "unknown" rather than lying -- acceptable, but undocumented in
  `docs/RELEASE.md`).
- bench: read `result.py` and `runners/base.py` end to end -- the accounting is
  honest (`bytes_source`, `verify_method`, `timing_resolution_s`,
  `SHORT_TRANSFER_RATIO`, `existing_keys(measured_only=True)` for SHIP-6/7) and
  175 tests pass. I did not audit the four transport runners' parsing of tool
  output, which is where a "measures what it claims" bug would most likely live.

## OUT OF TERRITORY
- `installer/build_editor_package.ps1:362-364`: the plaintext password from
  `SecureStringToBSTR` is never zeroed/freed (`ZeroFreeBSTR`) -- hygiene only, it
  is never logged or echoed; noted rather than filed.
- `companion/src/ccsync_companion/config.py`: `ensure_config`/`merge_config_text`
  and `windows_upgrade.ps1`'s `Test-Key` both do line-oriented TOML edits that a
  hand-added `[section]` would defeat; harmless today only because
  `DEFAULT_TOML_TEXT` is entirely flat (verified). If a `[section]` is ever added
  to the companion config, both editors break silently.
