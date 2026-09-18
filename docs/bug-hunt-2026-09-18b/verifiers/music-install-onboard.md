# verdicts - music-install-onboard

Scope: the nine MEDIUMs of `install-onboard` (1-6) and `music` (1-3). Read-only
verification; neither uninstaller was executed. Windows evidence comes from
`Get-UninstallClosingAdvice` sliced out of `installer/windows_uninstall.ps1`
(lines 234-288) into the scratchpad and dot-sourced.

## install-onboard-1
- Verdict: CONFIRMED
- Duplicate of: none (shares a root - the closing paragraph - with install-onboard-4)
- Reasoning: the self-path arm at `windows_uninstall.ps1:278-285` is keyed on
  `$LeftoverCount -gt 0` alone, while the new "NOT complete" branch at :271 is
  keyed on `$identityCount`. On that branch `$LeftoverCount` is 0, so the
  function emits the "delete that file, and the folder it is in, whenever you
  like" arm in the same paragraph as "run this uninstaller again with -Full".
  It is also worse than the hunter says it is likely to be: `Get-BinDirLeftovers`
  deliberately EXCLUDES `$SelfPath`, `windows_uninstall.ps1` and
  `drive_mapping.ps1` (:198-201), so `$binLeftovers.Count` can be 0 with the
  script still in `bin\` - and `bin\` is then a surviving child of
  `%LOCALAPPDATA%\ccsync`, i.e. `Get-FullRemovalLeftovers` reports it and the
  identity branch fires. Any -Full run where PS 5.1 could not delete the running
  script's own directory lands here.
- Evidence: dot-sourced the extracted function and called
  `Get-UninstallClosingAdvice -LeftoverCount 0 -BinDir C:\x\ccsync\bin -SelfPath
  C:\x\ccsync\bin\windows_uninstall.ps1 -IdentityLeftovers @("C:\x\ccsync\bin")`
  ->
  `[warn] ... NOT complete: 1 item(s) of your sign-in and Syncthing identity ...
  run this uninstaller again with -Full.` followed by
  `[step] this uninstaller is still on disk at ... Delete that file, and the
  folder it is in, whenever you like.`
- Fix note: the hunter's fix is right - gate the self-path arm on
  `($LeftoverCount -gt 0 -or $identityCount -gt 0)`. The LEAVE wording must stop
  saying "the program files listed above" on the identity branch (nothing was
  listed there). `installer/tests/Test-BinDirLeftovers.ps1` asserts only the
  "NOT complete" substring today (see install-onboard-7), so no test pins the
  old wording and none will catch the fix either unless a whole-paragraph case
  is added.

## install-onboard-2
- Verdict: DOWNGRADED to low
- Duplicate of: none
- Reasoning: the control flow is as reported - section 4's `elseif
  (Unregister-UninstallEntry ...)` at :602 runs before `if ($Full)` at :662, so
  a -Full run whose tree delete fails ends with the Apps & features entry
  already gone. But the harm the finding rests on does not follow. The entry's
  `UninstallString` is minted by `windows_bootstrap.ps1:888` as
  `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<script>"` with NO
  `-Full`, so that button could never have carried out the closing line's "run
  this uninstaller again with -Full" - keeping the entry would not have given
  the editor the retry path they are told to use. What is genuinely left behind
  on this path is DATA (syncthing-config, config.toml), not program files, so
  install-onboard-3's (2026-09-11) "an entry removed before a delete that did
  not happen" invariant is only grazed: the binaries really are gone whenever
  the entry is removed, because `$binLeftovers.Count -eq 0` is its gate.
- Evidence: `windows_bootstrap.ps1:884-890` (the command string has no -Full);
  `windows_uninstall.ps1:597-607` vs `:662`.
- Fix note: do not move the entry removal below section 5 - that would keep an
  entry pointing at a script that a successful -Full run has just deleted, which
  is the OPS-17 dangling-button failure. The right fix is the one in
  install-onboard-1/-4: have the identity branch print the exact hand-delete
  command (`Remove-Item -LiteralPath <CcsyncLocal> -Recurse -Force`) and the
  path, since no registered button can ever run -Full.

## install-onboard-3
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: the `$doomed` loop at :704-712 deletes with `-ErrorAction
  SilentlyContinue` and never re-reads `$CcsyncProfile`; the `Write-Step` at
  :713 reports `$doomed.Count`, the count it INTENDED to delete, outside any
  leftovers test. `Get-FullRemovalLeftovers` is handed `$CcsyncLocal` only
  (:677), so `%USERPROFILE%\.ccsync` is outside the closing verdict's reach and
  a run that removed nothing there still ends "CCSync uninstall complete". The
  contents are exactly what the finding says: `config.py:337/1039` puts
  `companion.log` in `~/.ccsync` (held open by the companion section 1 killed
  without waiting - see install-onboard-5), and `config.py:358-364` puts
  `dashboard_token` and the per-editor `report_token` in `config.toml` beside
  it. This is the same "LOOK before claiming" rule today's fix wrote into the
  block immediately above.
- Evidence: source read of :677 and :704-714; `grep -n "Wait-Process"
  installer/windows_uninstall.ps1` is empty, so the log-handle case is live;
  `config.py` lines as cited.
- Fix note: the suggested fix is right and cheap. It must keep `state\`
  excluded from the survivors (the KEPT paragraph at :715 depends on it), and
  the survivors have to be folded into a source the closing advice can see - if
  they are appended to `$fullLeftovers` they inherit install-onboard-4's
  mis-wording ("items of your sign-in and Syncthing identity" for a `~\.ccsync`
  file is at least true there), so fix -4 first or in the same change.
  `Test-BinDirLeftovers.ps1` has no case over this block at all.

## install-onboard-4
- Verdict: CONFIRMED
- Duplicate of: none (same function as install-onboard-1, different defect)
- Reasoning: the two predicates really are different inputs. Section 5's
  identity paragraph (:727-733) asks `Test-Path $SyncthingHome`; the closing
  verdict asks `Get-FullRemovalLeftovers`, which returns every surviving
  top-level child of `%LOCALAPPDATA%\ccsync` (:219-228) - `bin`, a stray
  `Temp`, anything - and the :271 line calls all of them "item(s) of your
  sign-in and Syncthing identity". The split outcome is not exotic: `bin\`
  surviving while `syncthing-config\` went is the ordinary shape when the
  uninstaller is launched from Apps & features out of `bin\`, and it produces
  "your ... device identity are gone. A reinstall generates a NEW device ID"
  immediately followed by "NOT complete: 1 item(s) of your sign-in and
  Syncthing identity are still on this machine". That is the admin-facing
  question (re-approve or not) answered both ways in one paragraph.
- Evidence: the scratchpad call under install-onboard-1 produced the second
  sentence verbatim for a leftover of `...\ccsync\bin`.
- Fix note: the suggested fix is the right shape - pass the identity verdict in
  as its own flag and word the leftovers line as "item(s) of the CC Sync app
  folder", naming the identity only when `syncthing-config` is among them. Any
  fix here also has to touch section 5's paragraph so the two are computed
  once, and `Test-BinDirLeftovers.ps1` needs a case that asserts the whole
  paragraph rather than the "NOT complete" substring.

## install-onboard-5
- Verdict: DOWNGRADED to low
- Duplicate of: none
- Reasoning: the first half stands - there is no `Wait-Process` or
  `WaitForExit` anywhere in the script (verified by grep), `Stop-Process -Force`
  returns before the handles are released, and that is exactly the mechanism
  today's comment at :668 names. The second half, the supervisor race, is
  REFUTED by design: `supervisor.DELIBERATE_EXIT_CODES` contains `0xFFFFFFFF`,
  which is what `Stop-Process`/`Process.Kill()` sets, so `decide()` returns
  "not fighting it" whatever the run marker says; and the supervisor is the
  same exe re-entered, so `Get-Process ccsync-companion | Stop-Process -Force`
  kills it in the same call. Both are stated as guarantees in the module
  docstring (`supervisor.py:26-34`) and in KNOWN_BUGS.md line 3413. With the
  race gone, what remains is a robustness improvement to a condition the fix
  already reports accurately, not a defect the fix introduced.
- Evidence: `grep -n "Wait-Process\|WaitForExit" installer/windows_uninstall.ps1`
  -> no hits; `supervisor.py:104` (`DELIBERATE_EXIT_CODES = frozenset({0, 1,
  0xFFFFFFFF, 0xC000013A})`) and `:146-149`.
- Fix note: the `Wait-Process -Name ccsync-companion, syncthing -Timeout 10`
  half is worth doing and is safe. Do NOT delete
  `~/.ccsync/crash/running.marker` before the kill as suggested: the marker is
  `crash_report`'s UncleanExit evidence and is already irrelevant here (the
  exit code stands the supervisor down), and removing it from an installer
  would make a genuine crash during an aborted uninstall invisible. Note the
  pythonw source-mode kill at :306-315 needs the same wait.

## install-onboard-6
- Verdict: DOWNGRADED to low
- Duplicate of: none
- Reasoning: the behaviour is exactly as described - `SYNCTHING_HOME` is
  `$CCSYNC_LOCAL/syncthing-config` (:65) and `remove_local_tree "$CCSYNC_LOCAL"`
  at :214 is outside any `FULL` test, so a plain `macos_uninstall.sh` destroys
  the device identity while Windows keeps it. What the hunter missed is that
  the script SAYS SO, in the same breath and unconditionally: on success line
  216 warns "that included the Syncthing identity in $SYNCTHING_HOME. A
  reinstall generates a NEW device ID, so the admin has to approve this Mac
  again on the dashboard before lane C syncs", and the dry run says the same in
  the conditional (:212). So the stuck-lane-C scenario - an admin who does not
  expect a new device ID - requires the editor to ignore a warning printed at
  them, not a silent divergence. What is left is a genuine cross-platform
  inconsistency plus a mode line ("keep your sign-in and settings in
  $CCSYNC_PROFILE") that is true about the profile and silent about the
  identity.
- Evidence: `installer/macos_uninstall.sh:63-65`, `:194-219` (the warn at 216),
  `:263` (where `FULL` first branches), against
  `installer/windows_uninstall.ps1:662` and `:740-741`.
- Fix note: prefer the hunter's second option (say it in the mode line) over
  the first. Changing the macOS scope so `syncthing-config/` survives a plain
  run would change what `REMOVAL_INCOMPLETE` means (`:229-232` sets it from
  `[ -d "$BIN_DIR" ]` only, but `remove_local_tree` deletes the whole tree and
  reports on it), and `installer/tests/test_macos_site_values.sh` slices these
  sections - any scope change needs its harness updated in the same commit.

## music-1
- Verdict: CONFIRMED
- Duplicate of: none (the b-roll twin at `broll/web/app/routes_batches.py:193`
  is the same defect in another territory; the hunter flagged it as out of
  territory rather than as a second id)
- Reasoning: the else path at `routes_batches.py:206` calls
  `ingest_batches.cancel()`, whose UPDATE (`ingest_batches.py:614-619`) sets
  `lease_expires_at = NULL` and leaves `state`. `expire_stale_leases`'s
  predicate is `state IN ('claimed','running') AND lease_expires_at IS NOT NULL
  AND lease_expires_at < ?`, so the row is outside every sweep for good, and
  `_leaseholder_or_410` (`routes_fleet.py:78-82`) 410s any companion that comes
  back - the cancel flag is checked FIRST and unconditionally. I checked every
  other writer: `claim`, `heartbeat`, `release` and `retry_failed` all need a
  companion that is still alive, so a companion that dies between the cancel
  and its next heartbeat leaves the row terminal-looking to nobody. The
  downstream cost the hunter names is real too: `reserved_names`
  (`ingest_batches.py:360-365`) excludes only cancelled/failed/skipped/
  duplicate items, so a wedged batch holds every `dest_name` for ever.
- Evidence: source reading of the four functions above; the new test
  `test_a_cancel_never_leaves_a_row_no_sweep_can_reach` calls
  `_running_with_a_dead_lease` first, so it only ever drives the finalise
  branch. Mitigation the finding understates: a SECOND cancel click does clear
  it - the route sweeps, sees `lease_live` false, and finalises - so this is
  recoverable by an editor who guesses, not permanent.
- Fix note: the first suggested fix (leave the expiry in place on the
  request-not-kill branch) is the right one and closes music-2 with it; the
  410-on-next-call effect is already delivered by `cancel_requested`, which
  `_leaseholder_or_410` checks ahead of the lease. It does not break the new
  test `test_a_cancel_on_a_live_lease_still_only_asks`, which asserts only
  `state`, `cancel_requested` and the absence of `finalised` - verified by
  reading it. The same change is owed to `broll/web/app/ingest_batches.py`'s
  `cancel`, and any fix must keep the YTDL-WEB-1 property that the next fleet
  call 410s even if a heartbeat lands first (it does, via `cancel_requested`).

## music-2
- Verdict: DOWNGRADED to low
- Duplicate of: none (same root cause as music-1)
- Reasoning: the mechanism is real and I could not break it - `cancel()` nulls
  `lease_expires_at` under a live leaseholder, `lease_live()` reads that column
  and nothing else (`ingest_batches.py:156-160`), so the retry-failed guard at
  `routes_batches.py:239` passes immediately after a cancel, and
  `retry_failed`'s UPDATE sets `cancel_requested = 0, cancel_by = NULL, state =
  'queued'`, i.e. the still-running companion is never told to stop. But the
  stated failure scenario cannot happen from one page: the button is drawn only
  when `MI_TERMINAL_STATES.includes(batch.state)` (`ingest.js:1262-1263`), and
  after a cancel on a live lease the row is still `running`, so the card that
  would offer the button is never rendered. Reaching it needs a stale second
  tab (one tab cancels, another still showing `done_with_errors` retries) or a
  direct API call - narrow enough that the consequence, though serious, is not
  a medium. The route-is-the-contract argument in the docstring is fair, which
  is why this is a low rather than a refutation.
- Evidence: `ingest_batches.py:156-160` (`lease_live`), `:600-619` (`cancel`),
  `retry_failed`'s UPDATE, `routes_batches.py:237-246`,
  `music/web/static/ingest.js:1262-1267`. Confirmed by reading that no test in
  `tests/test_ingest_batches.py` or the new suite cancels before retrying.
- Fix note: fix music-1 (leave the lease alone) and this closes with it; that
  is preferable to the alternative of re-keying the guard on
  `state in ('claimed','running') and not finished_at`, which would newly
  refuse the orphaned-batch case the route exists for whenever the sweep has
  not run. If the guard IS re-keyed, `expire_stale_leases` must stay the call
  before it, or an orphan becomes unretriable.

## music-3
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: `miRetryFailed`'s new catch sets `refused = miRefusalText(e)` for
  every exception (`ingest.js:1404-1411`), and `miRefusalText` returns
  `e.message` whenever the throw is not a 409 carrying a body. `miLoopback`
  builds `e.message` as the parsed message/detail or the app's own generic
  `the CC Sync tray returned HTTP <n>` (`:412-418`), and a rejected fetch never
  reaches it at all (no `.status`, message "Failed to fetch"). Both of the
  commonest dispatch failures - no tray, and a companion too old for
  `/music/ingest/*` - therefore print as the companion's reason, and because
  `refused` is truthy the third arm of the toast (the only sentence that tells
  the editor to open the page on the machine holding the audio) is
  unreachable on this path. The page's own convention elsewhere is the proof:
  `:438` and `:472` both map `e.status === 404` to `MI_TOO_OLD`, and this path
  does not.
- Evidence: source reading of `miLoopback`, `miRefusalText` and `miRetryFailed`
  as cited; the new node-driven test in the music web suite only drives 409s
  with bodies, so it cannot see this.
- Fix note: the suggested fix is right - set `refused` only when the companion
  actually spoke (`e.body && (e.body.reason || e.body.message)`), keep the
  fallback sentence otherwise, and special-case 404 to `MI_TOO_OLD`. Note
  `miTakeOver` (`:1338-1348`) has the mirror shape (it routes non-409s to
  `miSetNotice` with a raw `e.message`) and should be changed in the same pass;
  the b-roll twin `broll/web/static/ingest.js` carries the same helper. Watch
  the no-em-dash scan test in the music web suite when rewording.

## Note on the group
install-onboard-1, -2 and -4 are three faces of one paragraph
(`Get-UninstallClosingAdvice` plus section 5's identity block) and should be
fixed as one change with one whole-paragraph test; music-1 and music-2 are two
faces of `cancel()` nulling the lease and close together.
