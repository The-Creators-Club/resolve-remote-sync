## Installers and the first-run wizard (CR-265, 2026-09-11)

The hunt of the 2026-09-11 fix pass found six defects in this territory: one
regression test that could not fail on the bug it was written for, one
half-landed cache fallback, and four pieces of closing copy that tell an
editor the opposite of what happened. All six are fixed.

### CR-265a (tests-1) - the macOS mount-guard regression test passed against the bug on every runner it runs on - FIXED (onboarding/tests/test_bug_hunt_2026_09_11_install_onboard.py)

CR-248's headline fix (the frozen wizard refused from Downloads, the Desktop
and /Applications, because `os.path.ismount("/Users")` is True on a volume-group
Mac) was real, and its regression test was not. The tests drive the shipped
guard with `os.stat` / `os.lstat` swapped for a firmlink simulation, which is
the right idea, but the PRE-FIX guard reached the mount table through
`os.path.ismount` - and on the Windows dev box and the Windows CI job, the only
runners this suite has, `os.path` is `ntpath`, whose `ismount` never looks at
`st_dev` and answers False for every POSIX path. The old code therefore
returned "not refused" there, so the whole file was green against the shipped
bug; reverting only `steps.py` gave 8 failed, 12 passed, and the 12 included
every test about the home folder. The canary written expressly to stop this
probed `posixpath.ismount`, not the callable the code used, so it was green
too.

The fix puts the macOS semantics back under the mechanism a revert would
restore: `_guard_under_firmlinks` now also substitutes `posixpath.ismount` for
`steps._default_is_mount` (which the shipped guard does not call at all, so
nothing under test changes), `_FakeStat` carries an `st_ino` so a real
posix ismount walk resolves, and a new
`test_the_pre_fix_walk_refuses_what_the_shipped_guard_allows` keeps the pre-fix
darwin branch verbatim in the test file and asserts the two verdicts DIFFER
under the same simulation - a regression test that cannot state the bug cannot
fail on it. The probe of the module's own `_default_is_mount` is kept as a
separate test that SAYS OUT LOUD where it cannot run: it is
`skipif(os.path is not posixpath)` with a reason naming ntpath, this suite's
Windows-only runners, and the CI gap. Reverting `steps.py` to 40f931a now
fails 19 tests including all four home-folder cases.

The second half of the finding, that the onboarding suite is the only suite
whose subject is macOS-only behaviour and the only one that never runs on the
macOS CI job, is OWED below: `.github/workflows/ci.yml` is not this
territory's.

### CR-265b (install-onboard-1) - a stale, unbounded, unidentified cache could override a manifest this run fetched - FIXED (onboarding/steps.py)

`site_manifest_value` fell back to `site_mod.cached_site()` whenever the value
in the passed manifest was empty, not only when the fetch had failed. Since
`site.normalise` fills every absent string key with `""`, a manifest this run
fetched successfully from a dashboard that publishes no `tree_name` silently
took the tree name out of a cache written by some earlier - possibly
different - deployment while `canonical_prefix` came from this run: a mixed
pair from two sources, put on argv as `-CanonicalPrefix` / `-TreeName`, where
`windows_bootstrap.ps1` only calls `Get-SiteValue` when the flag is empty. The
cache therefore beat the script's own live fetch, which happens later in the
install once Tailscale is up and is exactly the fetch most likely to succeed
when the wizard's did not. The cache itself is a single unkeyed
`~/.ccsync/state/site.json`, was read with `max_age_seconds=None` (any age),
and was never checked against the `dashboard_url` it carries - so a machine
re-onboarded from deployment A (`Q:\`) to deployment B (`P:\`) with one timed
out `GET /api/v1/site` got A's letter, A's tree name, a `CCSync-SubstQ` logon
task and a `CCSync_Q` share, none of it correctable except by hand.

Now: the cache answers for a MISSING MANIFEST, never for a missing key; the
read is bounded by `SITE_CACHE_MAX_AGE_SECONDS` (30 days); and a cached
manifest whose `dashboard_url` host differs from the URL this run signed in to
is ignored. Only a PROVEN mismatch refuses - a dashboard that predates the key
publishes no `dashboard_url`, and refusing there would undo install-onboard-2,
whose whole point is that the cache answers when the fetch failed.
`run_bootstrap` passes the `dashboard_url` it was given.

### CR-265c (install-onboard-5) - "8443 means TLS" was one deployment's Funnel port applied to every customer's hostname - FIXED (onboarding/steps.py)

CR-248 correctly stopped guessing `http://` for `.ts.net` names, but it also
promoted ANY non-numeric, non-local hostname on port 8443 to `https://`,
because 8443 is this studio's client-share Funnel port. That is a property of
one operator's Tailscale Serve configuration, not of the number, and the
wizard is vendor software: an admin typing `dash.studio.internal:8443` for a
plain-HTTP container port behind their own proxy got `https://` written into
the field, into config.toml and into the companion's loopback origin
allow-list - the identical failure the finding described, pointing the other
way. 443 stays https everywhere and a bare name stays https; 8443 now implies
TLS only where Serve terminates it, which is a `.ts.net` name. The CR-248
parametrised case that pinned `("dash.example.com:8443", "https://...")` as
intended behaviour is inverted with the reason beside it.

### CR-265d (install-onboard-2) - the closing advice on a failed uninstall contradicted itself - FIXED (installer/windows_uninstall.ps1)

On the leftovers path the uninstaller printed "CCSync uninstall NOT complete:
... run this uninstaller again from Apps & features" and then, four lines
later and unconditionally, "this uninstaller is still on disk at <path> (it
was running). Delete that file, and the folder it is in, whenever you like."
Following the second line deletes the only retry path the first one just
named, and "the folder it is in" is `$BinDir`, which still holds the program
files - the OPS-17 "a button that fails" shape CR-248 was written to avoid.
The leftovers case is not rare: PowerShell 5.1's `Remove-Item -Recurse`
deletes NOTHING AT ALL when one child is locked, so a partial failure leaves
the entire bin dir, not one file. The whole closing paragraph is now
`Get-UninstallClosingAdvice`, which returns Kind/Text lines the body prints:
on the leftovers path the self-on-disk notice becomes "LEAVE this uninstaller
where it is ... it is what Apps & features runs when you retry", and the
healthy path keeps the OPS-17 wording unchanged.

### CR-265e (install-onboard-3) - the macOS uninstaller claimed "removed" and "complete" over a removal that did not happen - FIXED (installer/macos_uninstall.sh)

install-onboard-3 was fixed on Windows only. `rm -rf "$CCSYNC_LOCAL"` was
followed unconditionally by `step "removed ... (binaries and the Syncthing
identity)"` and the run ended `CCSync uninstall complete`, while nine lines
later the same script already knew better (`if [ -d "$BIN_DIR" ]; then warn`).
On a Mac where part of `~/.local/ccsync` is root-owned (a sudo-run install, a
`--companion-file` copied with sudo) both sentences print in the same run, the
reassuring one first, and the editor reinstalls on top of a half-removed tree
whose old Syncthing identity then fights the new device ID on lane C. The
removal is `remove_local_tree` now: it re-tests the directory after the `rm
-rf`, says "removed" only when it is gone and "could NOT remove ... sudo rm -rf"
when it is not, and its exit status sets `REMOVAL_INCOMPLETE`, which the
`$BIN_DIR` warn also sets and which `closing_verdict` gates the closing line
on. The Syncthing-identity warning is only printed when the removal really
took it.

### CR-265f (install-onboard-4) - a failed Mac run can leave no companion autostart at all, and the warning block did not say so - FIXED (installer/macos_bootstrap.sh)

CR-248 hoisted `retire_legacy_agent "$COMPANION_PLIST_LEGACY"` above the
`COMPANION_MISSING` branch, which is right - the legacy agent holding loopback
8899 is what breaks the next successful install - but it means the retirement
now also runs on the failure path, and that path then removes our own plist
too. A Mac whose legacy agent was starting a working companion at some other
path (`--companion-path` can move it) ends a failed run with both agents gone,
stops syncing at the next logon, and the unmissable warning block explains
only that the sync app is not installed. `retire_legacy_agent` now records
whether it actually deleted anything (`LEGACY_AGENT_RETIRED`), and the
`COMPANION_MISSING` block says, when it did, that this Mac will not start the
sync app at logon at all until an install succeeds - not even the older copy
it used to start. The delete stays unconditional: the alternative (skip when
the legacy plist names a program that exists) re-opens the port-8899 fight.

### Verification
- `onboarding/tests/test_bug_hunt_2026_09_11_install_onboard.py::test_the_pre_fix_walk_refuses_what_the_shipped_guard_allows` -> new; with `steps.py` reverted to 40f931a the file now fails 8 of 8 mount-guard cases (was: all 8 green against the bug), passes now  (tests-1)
- `onboarding/tests/test_bug_hunt_2026_09_11b_install_onboard.py::test_a_fetched_manifest_is_never_completed_from_the_cache` (and `test_a_cache_from_another_dashboard_is_ignored`, `test_a_cache_from_the_same_dashboard_is_still_used`, `test_a_cache_that_names_no_dashboard_is_still_used`, `test_the_cache_read_is_bounded`, `test_run_bootstrap_passes_the_url_it_signed_in_to`, `test_an_unreadable_cache_is_still_not_fatal`) -> fail at f1eeb42, pass now  (install-onboard-1)
- `onboarding/tests/test_bug_hunt_2026_09_11b_install_onboard.py::test_8443_means_tls_only_where_this_fleet_publishes_it[dash.studio.internal:8443-http://dash.studio.internal:8443]` -> fails at f1eeb42, passes now  (install-onboard-5)
- `installer/tests/Test-BinDirLeftovers.ps1` ("the leftovers path does not tell the editor to delete its own retry path", plus the AST check that the notice is not printed outside `Get-UninstallClosingAdvice`) -> fails at f1eeb42 naming the line, passes now  (install-onboard-2)
- `installer/tests/test_macos_site_values.sh` ("a removal that did not happen says so", "an incomplete uninstall does not end complete", and the scan for `rm -rf` followed by `step "removed`) -> fails at f1eeb42, passes now  (install-onboard-3)
- `installer/tests/test_macos_site_values.sh` ("retiring a legacy plist deletes it and sets the flag", "the COMPANION_MISSING warning block says when the old autostart was removed too") -> fails at f1eeb42, passes now  (install-onboard-4)

Run: `cd onboarding; python -m pytest tests/test_bug_hunt_2026_09_11b_install_onboard.py tests/test_bug_hunt_2026_09_11_install_onboard.py tests/test_site_prefix_handoff.py -q` -> 58 passed, 1 skipped (the skip is the POSIX-only canary, with its reason printed).
`powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-BinDirLeftovers.ps1` and `...\Test-UninstallEntry.ps1` -> pass.
`bash installer/tests/test_macos_site_values.sh` -> pass. No installer, uninstaller or upgrade script was executed against this machine.

### OWED TO ANOTHER TERRITORY
- server-tools: `.github/workflows/ci.yml`: the `macos` job (lines ~464-537, which today runs the COMPANION suite only): add the onboarding suite (`cd onboarding && python -m pytest tests -q`). It is the only suite whose subject is macOS-only behaviour and the only one that never runs on a Mac; the skipped canary in `test_bug_hunt_2026_09_11_install_onboard.py` names this gap in its skip reason and would then run. No deploy ordering.
- server-tools: `tools/run_all_tests.ps1`: the installer row (lines ~161-203) still names seven scripts and `ls installer/tests/*.ps1` is eight - this is tests-2, already assigned there. `Test-BinDirLeftovers.ps1` now carries the install-onboard-2 cases as well, so the local gate misses those too until that row enumerates the directory.

### Owner decisions
- `SITE_CACHE_MAX_AGE_SECONDS` is 30 days. The cache is rewritten by whoever last talked to the dashboard, so on a machine being re-onboarded it is normally hours old; a month is generous and only affects a wizard whose own fetch failed. Shorter is safer, longer is friendlier to a machine that has been off for a season.
- install-onboard-5: `dash.example.com:8443` now normalises to `http://`, reversing a case CR-248 pinned as intended. 8443 is a conventional TLS port in the wider world, so this is a judgement call: the argument for it is that this fleet's 8443 is a Funnel port, every other deployment's is whatever their proxy does, and a typed `https://` prefix is always honoured. If you would rather guess https there, the one-line change is in `normalise_dashboard_url` and the case is in both test files.
- The macOS uninstaller / bootstrap behaviour tests were added to `installer/tests/test_macos_site_values.sh` rather than a new file, because a new `.sh` would be run by neither the local gate nor CI (both enumerate `*.ps1` only and name that one bash file). Its closing line now says "macos_bootstrap.sh / macos_uninstall.sh"; renaming the file would need the two gate references changed and was left alone.

### Hand-off wave

#### CR-265g (tests-5) - the leftover report was tested as a computation, never as a report - FIXED (`installer/tests/Test-BinDirLeftovers.ps1`)

tests-5 named this file as the clearest case of the pass's test shape: it
extracts `Get-BinDirLeftovers` with the PowerShell parser, tests it
thoroughly, and checks the delete/unregister ORDER with a line-number regex
over the script text - so a refactor that keeps the function, keeps the call
and stops PRINTING the answer leaves every case green while the uninstaller
silently reports success over a bin dir full of program files. That is the
install-onboard-3 defect exactly, re-arriving through the door the tests do
not watch.

Two cases now execute the uninstaller's OWN statements. They are taken from
its AST (the `if` that deletes the bin dir and re-reads it, and the `foreach`
that prints `Get-UninstallClosingAdvice`), so they cannot drift from what
runs, and they run in a child scope where `Write-Step`/`Write-Skip`/
`Write-Warn2` are captured and `Remove-Item` is a no-op - which is PowerShell
5.1's real leftovers case, one locked child and the whole recursive delete
does nothing. The assertions are on what an editor would see: the locked
exe's full path, the "run this uninstaller again from Apps & features" retry
line, no "removed program binaries" claim, and the closing "NOT complete"
line arriving as a WARNING with its count. A helper for the AST lookup
(`Get-ScriptStatement`) fails loudly if either statement stops existing,
rather than silently testing nothing.

### Verification (hand-off wave)

`powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-BinDirLeftovers.ps1`
-> 23 PASS, exit 0 (was 17 cases).

- "the leftover is PRINTED by the uninstaller's own statements, not just computed" -> FAILS when the `Write-Warn2 "    $leftover"` inside the script's own loop is replaced with a no-op while everything else stays (mutation run, measured); passes on the real script.
- "the script's own block finds the locked exe", "the printed report names the retry path", "a run with leftovers never claims the binaries were removed", "the closing advice reaches the editor as a WARNING on the leftovers path", "the closing advice names how many files are left" -> pass.
- `windows_uninstall.ps1` is NOT changed by this wave (the mutation was reverted byte for byte); the script parses.

### OWED TO ANOTHER TERRITORY (hand-off wave)

- none new. The wave-1 OWED line still stands: `tools/run_all_tests.ps1`'s
  installer row must enumerate `installer\tests\Test-*.ps1` (tests-2,
  server-tools), or the local gate runs neither these cases nor the
  install-onboard-2 ones.

### Owner decisions (hand-off wave)

- The uninstaller itself is driven statement by statement rather than end to
  end. Running `windows_uninstall.ps1` for real on the gate machine would
  stop the companion, remove the Run key, unmap the tree drive and delete
  the SMB share on the base rig; a sandboxed whole-script run would need
  parameters the script does not take. The AST lookup is the closest thing
  to the public path that is safe here, and it fails loudly rather than
  quietly if the statements move.
