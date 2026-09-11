# install-onboard - the two bootstraps, the two uninstallers, the drive library and the first-run wizard

Files read (with approximate coverage):
- `git diff 40f931a..HEAD -- installer onboarding` in full (11 files, 779 insertions) - 100%
- `installer/windows_uninstall.ps1` - 100% (all six sections, both new helpers)
- `installer/windows_bootstrap.ps1` - the uninstall-entry block, `Register-UninstallEntry` / `Set-UninstallEntryIcon`, the `-CanonicalPrefix` / `-TreeName` resolution at 720-775, section 9's companion copy - ~35%
- `installer/macos_bootstrap.sh` - the label/plist block (440-470), `retire_legacy_agent` (1900-1920), the `--resolve-mapping-only` exit, section 6a in full - ~30%
- `installer/macos_uninstall.sh` - sections 3 and 6 - ~40%
- `installer/windows_upgrade.ps1` - `Test-VersionAtLeast`, the EULA gate, the rollback block - ~25%
- `onboarding/steps.py` - `site_manifest_value`, `site_canonical_prefix`, `normalise_dashboard_url`, `fetch_site`, `run_bootstrap`, `installer_on_forbidden_drive`, `forbidden_installer_message`, `_default_stat_dev` - ~40%
- `onboarding/onboard.py` - `_site`, `_drive_letter`, the sign-in worker, `_worker_editor` - ~20%
- `onboarding/tests/test_bug_hunt_2026_09_11_install_onboard.py`, `tests/test_site_prefix_handoff.py`, `installer/tests/*.ps1`, `installer/tests/test_macos_site_values.sh` - 100% of the changed parts
- `companion/src/ccsync_companion/site.py` (`normalise`, `cached_site`, `STRING_KEYS`) as the callee of the new fallback
- `KNOWN_BUGS.md` CR-248 in full, `docs/bug-hunt-2026-09-11/hunters/install-onboard.md` headings, `verdicts.txt`

Tests run:
- `cd onboarding; python -m pytest tests -q` -> 412 passed in 3.64s
- every `installer\tests\*.ps1` via `powershell -NoProfile -ExecutionPolicy Bypass -File` (7 scripts) -> all pass
- `bash installer/tests/test_macos_site_values.sh` -> all pass
- two scratch PowerShell experiments in the scratchpad (not in the repo) reproducing `Remove-Item -Recurse -Force` against a locked child and against the running script's own directory

No installer, uninstaller or upgrade script was executed against this machine.

## Findings

### install-onboard-1 - `site_manifest_value` lets a stale, unbounded, unidentified cache override a manifest this run actually fetched, and beat the bootstrap's own live fetch
- Severity: medium
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (field frequency)
- Where: `onboarding/steps.py:230-252` (`site_manifest_value`) and `onboarding/steps.py:1475-1476` (`run_bootstrap`), against `installer/windows_bootstrap.ps1:737-741` and `installer/macos_bootstrap.sh` (`CCSYNC_CANONICAL_PREFIX` read flag-first)
- What: `site_manifest_value` falls back to `site_mod.cached_site()` whenever the value in the passed manifest is empty - not only when the fetch failed. `site.normalise` fills every absent `STRING_KEYS` entry with `""`, so a manifest this run fetched successfully from a dashboard that publishes no `tree_name` (or publishes it blank) silently takes `tree_name` from a cache written by some earlier, possibly different deployment, while `canonical_prefix` comes from this run: a mixed pair from two sources. Separately, `cached_site()` is called with `max_age_seconds=None` (any age) and the cache is a single unkeyed `~/.ccsync/state/site.json` with no check against `dashboard_url`, which the manifest does carry. The value then goes on argv as `-CanonicalPrefix`, and `windows_bootstrap.ps1:740` only calls `Get-SiteValue "canonical_prefix"` when the flag is empty - so the cache beats the script's own live fetch, which happens later in the install, after Tailscale is up, and is exactly the fetch most likely to succeed when the wizard's did not.
- Failure scenario: an editor whose machine was previously onboarded to deployment A (`canonical_prefix = "Q:\"`, cached) is re-onboarded to deployment B (`P:\`). Sign-in to B succeeds; `steps.fetch_site` then hits its 5 s timeout on `GET /api/v1/site` (it returns `{}` on ANY exception), so `onboard.py::_site()` returns None. `run_bootstrap` reads `Q:\` out of the stale cache and passes `-CanonicalPrefix Q:\`; the bootstrap skips its own fetch, maps Q:, writes `canonical_prefix = "Q:\"` into config.toml, names the logon task `CCSync-SubstQ` and the loopback share `CCSync_Q` - all disagreeing with deployment B, and none of it correctable except by a hand re-run. The narrower case needs no second deployment at all: any site that changes `tree_name` or its letter, plus one timed-out fetch, gets the old answer.
- Evidence: `companion/src/ccsync_companion/site.py:156-158` (every missing string key becomes `""`), `:255-275` (`cached_site` has no default max age, no site identity), `:74` (`dashboard_url` is in `STRING_KEYS`, so the cache *could* be checked and is not); `onboarding/steps.py:1070-1073` (`fetch_site` returns `{}` on any exception, including a timeout after a successful sign-in); `installer/windows_bootstrap.ps1:740` (`if (-not $CanonicalPrefix) { ... Get-SiteValue ... }` - the flag wins). The new tests only drive `cached_site` through a monkeypatched lambda, so none of them can see staleness or provenance.
- Ledger: CR-248 does not fully fix install-onboard-2 (new sub-case of the same wire)
- Suggested fix: only consult the cache when `site` is falsy (the failed-fetch case the flags exist for), not per-key; pass a `max_age_seconds` bound; and ignore a cached manifest whose `dashboard_url` host does not match the URL this run signed in to.

### install-onboard-2 - the closing advice on a failed uninstall contradicts itself: "run this uninstaller again" and then "delete that file, and the folder it is in"
- Severity: low
- Confidence: CONFIRMED
- Where: `installer/windows_uninstall.ps1:613-616` and `:622-627`
- What: when `$binLeftovers.Count -gt 0` the script prints `CCSync uninstall NOT complete: ... Sign out and back in, then run this uninstaller again from Apps & features.` Four lines later, unconditionally, it prints `this uninstaller is still on disk at <path> (it was running). Delete that file, and the folder it is in, whenever you like.` Following the second line deletes the only retry path the first line just told the editor to use - and "the folder it is in" is `$BinDir`, the directory that still holds the program files. The self-on-disk notice is only meant for the healthy run where everything else went; it is not gated on `$binLeftovers`.
- Failure scenario: an editor whose companion exe was locked reads the last paragraph (the one on screen), deletes the bin dir by hand or gives up, and is left with the Apps & features entry the fix deliberately preserved now pointing at a script that is gone - the OPS-17 "button that fails" shape this change was written to avoid.
- Evidence: read both blocks; the second has no `$binLeftovers` guard. The leftovers case is non-theoretical: I reproduced `Remove-Item -LiteralPath <dir> -Recurse -Force -ErrorAction SilentlyContinue` in a scratch dir where one child was held with `FileShare.None`, and PowerShell 5.1 deleted **nothing at all** - the running script, `drive_mapping.ps1` and every binary all survived (REMAINS: all four files). So on any partial failure the leftovers list is the entire bin dir, not one file.
- Ledger: CR-248 does not fully fix install-onboard-3
- Suggested fix: wrap the "still on disk ... delete it whenever you like" notice in `if ($binLeftovers.Count -eq 0)`, or reword it to "leave it where it is until the uninstall finishes" on the leftovers path.

### install-onboard-3 - the macOS uninstaller still claims "removed" and "complete" over a removal that did not happen
- Severity: low
- Confidence: CONFIRMED
- Where: `installer/macos_uninstall.sh:186-196` and `:276`
- What: install-onboard-3 was fixed on Windows only. `rm -rf "$CCSYNC_LOCAL"` is followed unconditionally by `step "removed $CCSYNC_LOCAL (binaries and the Syncthing identity)"`, and the closing banner prints `CCSync uninstall complete` regardless - even though the script itself, nine lines later, already knows better (`if [ -d "$BIN_DIR" ]; then warn "$BIN_DIR still exists"`). The two statements can both be printed in the same run, the reassuring one first and the loud one never repeated in the summary.
- Failure scenario: a Mac where part of `~/.local/ccsync` is root-owned (a `sudo`-run install, an `--companion-file` copied with sudo) or sits on a volume with restrictive ACLs: `rm -rf` fails on those entries, the transcript says "removed ... (binaries and the Syncthing identity)" and ends "CCSync uninstall complete", and the editor reinstalls on top of a half-removed tree with the old Syncthing identity still present - which then fights the new device ID on lane C.
- Evidence: read the section; `rm -rf` result is never tested and `$?` is never consulted. Parallel to the Windows text CR-248 changed.
- Ledger: CR-248 does not fix install-onboard-3 on macOS
- Suggested fix: mirror the Windows shape - re-test `-d "$CCSYNC_LOCAL"` after the `rm -rf`, print "removed" only when it is gone, and gate the closing "complete" line on the same test (the `$BIN_DIR` warn already computes half of it).

### install-onboard-4 - the hoisted legacy-agent retirement can leave a Mac with no companion autostart at all, and the big warning block does not say so
- Severity: low
- Confidence: PLAUSIBLE
- Where: `installer/macos_bootstrap.sh:2452` (the hoisted `retire_legacy_agent`) together with `:2481-2491` (removing our own plist when `COMPANION_MISSING=1`)
- What: the fix moved `retire_legacy_agent "$COMPANION_PLIST_LEGACY"` above the `COMPANION_MISSING` branch, so it now runs on the failure path too - and that path then also removes `com.ccsync.companion.plist`. `retire_legacy_agent` deletes the plist without ever asking what program it runs (`plist_program` exists and is not used here), so a Mac whose legacy agent pointed at a *working* companion binary at a path other than this run's `$COMPANION_PATH` (which `--companion-path` can move) ends a failed run with both agents gone. The unmissable warning block that follows explains that the sync app is not installed, but never mentions that the autostart that was working until a minute ago was just removed.
- Failure scenario: an admin re-runs `macos_bootstrap.sh` with no `DASHBOARD_TOKEN` and a `--companion-path` pointing somewhere the binary is not (or with a download that 404s) on a pre-2026-08-17 Mac. Both LaunchAgents are deleted; the Mac stops syncing at the next logon, and nothing in the transcript attributes it to the retirement.
- Evidence: read `retire_legacy_agent` (installer/macos_bootstrap.sh:1904-1917 - it takes only a path and a label, never a program) and the `COMPANION_MISSING` branch. `COMPANION_PATH` is overridable at `:152`. When the legacy agent ran the default path the point is moot, because `COMPANION_MISSING=1` means that binary is already absent - hence PLAUSIBLE, not CONFIRMED.
- Ledger: related to CR-248 (install-onboard-6)
- Suggested fix: retire the legacy agent unconditionally as now, but on the `COMPANION_MISSING` path say so in the warning block ("the old autostart entry was removed too, so this Mac will not start the sync app at logon until the install succeeds"), or skip the delete when `plist_program "$COMPANION_PLIST_LEGACY"` names a file that exists.

### install-onboard-5 - `normalise_dashboard_url`'s new 8443 rule is a deployment-specific guess applied to every customer's hostname
- Severity: low
- Confidence: CONFIRMED
- Where: `onboarding/steps.py:946-953`
- What: the fix correctly stops guessing `http://` for `.ts.net` names, but it also promotes **any** non-numeric, non-local hostname on port 8443 to `https://`, because 8443 is *this* studio's client-share Funnel port. That is a property of one deployment's Tailscale Serve configuration, not of the port number, and the wizard is now vendor software. For a customer who publishes the dashboard container's own port as 8443 behind their own reverse proxy or on a LAN name that is not `.local`, the wizard writes an `https://` URL that cannot connect, into the field, into config.toml and into the companion's loopback origin allow-list - the identical failure the finding described, pointing the other way.
- Failure scenario: an admin types `dash.studio.internal:8443` for a plain-HTTP container port. Before: `http://` (worked). After: `https://` (every request fails, and `loopback_guard`'s origin allow-list holds a scheme the browser never sends).
- Evidence: read the branch; `tailnet` is computed but `port in ("443", "8443")` is ORed with it rather than gated by it, and the new parametrised test pins `("dash.example.com:8443", "https://...")` as intended behaviour. Nothing in `dashboard/deploy/*` binds 8443, so the guess is drawn from the operator's Funnel setup only.
- Ledger: CR-248 does not fully fix install-onboard-5
- Suggested fix: make 8443 imply TLS only for `.ts.net` hosts (`tailnet and port in ("443","8443")`, plus `not port` for a bare name), or probe both schemes once with `dashboard_reachable` and keep the one that answers rather than guessing at all.

## Coverage note

Not reached: `installer/drive_mapping.ps1` beyond the two parser functions its own suite covers; the bulk of `windows_bootstrap.ps1` (sections 2-8: Tailscale, rclone, Syncthing, the SMB share and firewall rule, the subst task) and of `macos_bootstrap.sh` (Homebrew, the SSD/volume handling, the Resolve Mapped Mount); `installer/build_editor_package.ps1` and the `-Publish` path; most of `windows_upgrade.ps1`'s staging/rollback; the wizard's Tk pages other than the sign-in and install workers; `installer/*.md`.

What the suite does not cover: nothing in either uninstaller's *behaviour* is executed by any test - `Test-BinDirLeftovers.ps1` and `Test-UninstallEntry.ps1` extract single functions with the PowerShell parser and otherwise assert on **line numbers in the source text**, which proves order but not effect (and neither test would notice that PS 5.1's `Remove-Item -Recurse` deletes nothing at all when one child is locked, which is what actually happens). No test on any platform exercises `macos_bootstrap.sh` or `macos_uninstall.sh` as scripts - `test_macos_site_values.sh` is a grep over the source. The onboarding suite never runs a real bootstrap; `run` is injected everywhere, so every argv/env contract with the two scripts is pinned only by string matching on the other file.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/site.py:255-275`: `cached_site()` has no default staleness bound and the cache is not keyed to the dashboard that wrote it, although the manifest carries `dashboard_url`; every offline reader inherits that (finding install-onboard-1 is one consumer).
