## Installers and the first-run wizard, 2026-09-11 (CR-248)

**install-onboard-1 (high): on a Mac the wizard refused to install from
anywhere.** `installer_on_forbidden_drive`'s darwin branch, added by CR-119 so
the Mac had the guard Windows has, walked up from `sys.executable` and refused
at the first `os.path.ismount()` hit. On macOS 10.15+ that is `/Users` itself:
a volume group puts everything a person can write on a separate APFS Data
volume reached through firmlinks, so `lstat("/Users").st_dev` is the Data
volume's while its parent's is the sealed System volume's, which is exactly
what `ismount` compares. Every frozen `CCSync Onboarding.app` run from
Downloads, the Desktop or `/Applications` was therefore refused at
`_worker_editor`'s first line, with the Windows wording ("running from P: or a
network share ... copy onboard.exe to your Desktop") and no place left to copy
it to: the shipped macOS artefact could not complete an install at all. The
guard now asks the volume's IDENTITY rather than whether a mount boundary was
crossed: `/Volumes/<name>` (the SMB tree and every removable disk) is refused
by prefix, and past that a device that is neither half of the boot volume group
(`/`, `/System/Volumes/Data`) nor the home folder's is a foreign volume.
"Cannot tell" still never refuses. The injectable is `stat_dev` now, not
`is_mount`, and the refusal text is `steps.forbidden_installer_message`, which
has its own sentence per platform - the old one named a drive letter, a network
share and `onboard.exe`, none of which exist on a Mac, and it was the only
thing a Mac editor ever saw of the install. The old darwin tests all injected
`is_mount`, i.e. mocked away precisely the thing that was wrong; the new ones
drive the REAL default with the firmlink `st_dev` shape simulated, and assert
that `posixpath.ismount("/Users")` is True under that simulation so the test
cannot quietly stop proving anything.

**install-onboard-2: the cached prefix still did not reach the bootstrap after
a failed fetch.** CR-119 gave `run_bootstrap` `-CanonicalPrefix` / `-TreeName`
(and the macOS env pair) so one wizard run could not disagree with itself about
which drive letter the tree has, but it read them off the passed dict only.
`onboard.py::_site()` returns None on any failed fetch, so in the exact case
the flags exist for, nothing was passed and the script fell back to `P:\` /
`CCSync` while `ensure_config` wrote the CACHED `Q:\` into config.toml a minute
later. The two fetch failures are one failure: the dashboard being unreachable.
Both values now go through `steps.site_manifest_value`, which falls back to the
cached manifest - and to the RAW cached key, never `site_canonical_prefix`'s
normalised `P:\` default: a wizard with no cache must pass nothing, or it would
force our fallback onto a Q: site's bootstrap and beat the script's own fetch,
which is the same bug pointing the other way. The test that pinned the source
text of the old `.get` now pins the cache fallback and the absence of the
default.

**install-onboard-3: the uninstaller said "removed program binaries" whether or
not anything was removed.** The delete was `-ErrorAction SilentlyContinue` and
its result was never re-read, so a companion exe still locked (step 1's
`Stop-Process -Force` does not wait for the image handle to be released), an AV
scan, or anything else holding a file left the app on disk under a report that
said it was gone - and the Apps & features entry had already been removed
thirteen lines earlier, so the editor had no button left to retry with. The
order is inverted: the binaries go first, `Get-BinDirLeftovers` re-reads the
directory (excluding `$PSCommandPath` and the top-level `drive_mapping.ps1`,
which are expected to survive every healthy run since OPS-17 put them there),
and the entry is removed only when the directory is actually clear. When it is
not, the leftovers are named, the entry is deliberately left in place and both
the warning and the closing line say what to do: sign out and back in, then run
it again from Apps & features. `installer/tests/Test-BinDirLeftovers.ps1` is the
new suite; it pins the exclusion rule and the order of the two operations.

**install-onboard-4 (low): a first install got a blank icon in Apps &
features.** Section 1a registers the uninstall entry about 1250 lines before
section 9 copies the companion exe, so `Register-UninstallEntry`'s "only point
at an icon that exists" guard always skipped `DisplayIcon` on a fresh machine -
permanently, since only a second bootstrap run rewrites the key. A blank row in
Settings > Apps is the shape an unwanted or unsigned program has. A new
`Set-UninstallEntryIcon` writes the value from section 9, where the exe either
exists or never will; it creates no key and invents no icon.
`Test-UninstallEntry.ps1` covers the function and the fact that the call site is
below the copy.

**install-onboard-5 (low): a TLS port on 8443 was guessed as http://.**
`normalise_dashboard_url` read any explicit port other than 443 as plain http,
and this deployment's Tailscale Serve/Funnel publishes TLS on 8443 too (the
client-share port). An admin who said `nas.tail26290e.ts.net:8443` got
`http://` written into the field, and from there into config.toml and the
companion's loopback origin allow-list, none of which can connect. The rule
now: an address or a local name has no certificate whatever the port, a
`.ts.net` name is TLS on every port Serve fronts, and 443 and 8443 are TLS;
a bare container port on somebody else's deployment is still plain. A scheme the
editor typed is still never second-guessed.

**install-onboard-6 (low): a Mac run with no companion binary left the legacy
LaunchAgent loaded.** `retire_legacy_agent "$COMPANION_PLIST_LEGACY"` was
inside the else branch, so on the path where the companion could not be
installed (no `DASHBOARD_TOKEN`, no `--companion-file`, a failed download) the
script deleted our correctly-labelled agent and left the pre-2026-08-17
`com.creatorsclub.*` one running an old companion - the very process that holds
loopback 8899 against the new one when a later run succeeds. It is hoisted
above the branch now, beside the unconditional Syncthing one, so CLAUDE.md's
rule holds on every path and not just the happy one.

### Verification
- onboarding/tests/test_bug_hunt_2026_09_11_install_onboard.py::test_the_home_folder_and_applications_are_fine -> fails at 40f931a, passes now (install-onboard-1)
- onboarding/tests/test_bug_hunt_2026_09_11_install_onboard.py::test_the_refusal_wording_is_the_platforms_own -> fails at 40f931a, passes now (install-onboard-1)
- onboarding/tests/test_bug_hunt_2026_09_11_install_onboard.py::test_windows_bootstrap_gets_the_cached_prefix_after_a_failed_fetch -> fails at 40f931a, passes now (install-onboard-2)
- onboarding/tests/test_site_prefix_handoff.py::TestTheBootstrapIsToldTheLetterTheWizardUsed::test_the_cache_answers_when_this_runs_fetch_failed -> fails at 40f931a, passes now (install-onboard-2)
- installer/tests/Test-BinDirLeftovers.ps1 -> fails at 40f931a (no Get-BinDirLeftovers, entry removed first), passes now (install-onboard-3)
- installer/tests/Test-UninstallEntry.ps1 ("the icon is written once the exe exists", "the icon is set after the companion exe is installed") -> fails at 40f931a, passes now (install-onboard-4)
- onboarding/tests/test_bug_hunt_2026_09_11_install_onboard.py::test_normalise_dashboard_url_does_not_force_http_on_a_tls_port -> fails at 40f931a, passes now (install-onboard-5)
- installer/tests/test_macos_site_values.sh ("the legacy companion agent is retired on every path") -> fails at 40f931a, passes now (install-onboard-6)

### OWED TO ANOTHER TERRITORY
- none

### Owner decisions
- install-onboard-1: an external SSD mounted OUTSIDE /Volumes is still refused
  (its device is neither the boot volume group's nor the home folder's). If a
  Mac editor deliberately keeps their tree on such a disk, that refusal is
  wrong for them; the alternative is to refuse only under /Volumes, which is
  CR-119's original behaviour.
- install-onboard-3: when files survive the delete, CC Sync is LEFT in Apps &
  features on purpose, so the editor has a button to retry with. Anyone who
  reads "still listed" as "uninstall failed" is reading it correctly, but it
  does mean a machine can sit with an entry until the editor re-runs it.
- install-onboard-5: a name with any other explicit port (say 9443) is still
  guessed as http. Probing https first and falling back was the other option
  and adds a network call to a page that must stay instant.
