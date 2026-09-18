# verdicts - music-install

Group: `music` (music-1..4) and `install-onboard` (install-onboard-1..5).
Method: read the cited code plus its callers/callees, re-ran the hunters'
reproductions from the component venvs (music/web `.venv`, onboarding system
python) and a scratch shell simulation of `macos_uninstall.sh` sections 3 and
6. `grep -an` over KNOWN_BUGS.md for each symptom; cross-read
`docs/bug-hunt-2026-09-18/tally.txt` and the neighbouring hunter reports for
duplicates. No installer, upgrader or uninstaller was run for real.

## music-1
- Verdict: CONFIRMED (medium)
- Duplicate of: none (same SHAPE as the hunter's own OUT OF TERRITORY note on
  `broll/web/app/routes_batches.py:187`, which no other hunter reported)
- Reasoning: `routes_batches.cancel` is the only batch route that does not call
  `ingest_batches.expire_stale_leases(conn)` first (the others do at
  routes_batches.py:124, :159, :228, and `claim` at ingest_batches.py:689), and
  its finalise test reads the raw column (`not batch['lease_expires_at']`)
  rather than `lease_live(batch)`. The row it leaves behind - `state='running'`,
  `lease_expires_at IS NULL`, `cancel_requested=1` - is excluded by
  `expire_stale_leases`'s own `lease_expires_at IS NOT NULL` predicate, so no
  later sweep can move it, and `claim` 410s every attempt to re-take it
  (`cancel_requested` + not terminal), so the companion cannot rescue it
  either. Nothing else in the module drives a batch terminal from `running`.
- Evidence: reproduced from `music/web/.venv` (scratchpad `m1.py`): create ->
  claim as RIG -> force `state='running'`, `lease_expires_at=2026-01-01` ->
  `cancel -> {'ok': True, 'state': 'running', 'cancel_requested': True}`, row is
  `state running lease None cancel_req 1`, `expire_stale_leases` sweeps `0`, and
  after the sweep the row is unchanged. Severity medium is right, not high: a
  second click on `cancel` does finalise it (the branch then reads
  `not lease_expires_at` -> True) and no audio or library row is lost.
- Fix note: the hunter's fix is correct and minimal. Two things it must carry:
  `lease_live` is imported/used as `ingest_batches.lease_live`, and the
  `queued`-or-dead test must stay an OR so a genuinely held batch keeps the
  request-not-kill path. A fix should add the missing test (there is none that
  cancels a batch with a past `lease_expires_at`) in
  `music/web/tests/`, and the identical shape in
  `broll/web/app/routes_batches.py:187` should be fixed in the same change or
  the two panels will disagree.

## music-2
- Verdict: CONFIRMED (medium)
- Duplicate of: none
- Reasoning: verified both halves of the wire. `broll_ingest.run()` returns 409
  for three unrelated causes - "this computer is already indexing another
  batch" (:1727), "those tracks are no longer staged - drop them again" (:1743),
  and the `staging_id_missing` refusal added by comp-broll-music-1 (:1802,
  which explicitly tells the editor to reload the page) - plus it forwards the
  dashboard claim's own 409 verbatim (:1758-1762). `miTakeOver`
  (`music/web/static/ingest.js:1289-1300`) sends `staging_id: ''`
  unconditionally and branches on `e.status === 409` alone, so all four become
  "Another of your computers is still working on this batch." The take-over
  path is exactly the one that trips `staging_id_missing`: `_staging_holding`
  (broll_ingest.py:1852) matches on name + rel_dir against the companion's
  in-memory staging map, which survives the page reload that lost
  `mi.stagingId`. `miRetryFailed`'s `catch { }` (:1358) discards it entirely.
- Evidence: source read of both sides; no runtime repro attempted (it needs a
  live companion, which the brief forbids touching). The 09-11b JS tests assert
  on the source text of `ingest.js` with regexes, so nothing pins the message.
- Fix note: the suggested fix is right, but the page must read the JSON body,
  not `e.message` alone - check how `miLoopback` surfaces the body before
  writing the branch, and key off `reason` (`staging_id_missing`,
  `tier_unfit`), not off the prose. Keep the "another of your computers"
  wording only for the claim's 409, which is the one carrying a `machine`
  field. `broll/web/static/ingest.js:ingestTakeOver` has the same blind branch
  and should move with it.

## music-3
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `precheck` (ingest_batches.py:476-497) calls `allocate_name(...,
  reserved=set())` seeded only per request, while the real allocation in
  `write_item_result` (:925-928) passes `reserved=reserved_names(conn)` - every
  `dest_name` on an item not in `('cancelled','failed','skipped','duplicate')`.
  `reserved_names` has exactly one caller, so the preview genuinely sees a
  strict subset. The docstring's property ("reserves NOTHING") is not harmed by
  reading the ledger, so the fix is compatible with the design.
- Evidence: read of both call sites and of `reserved_names`; grep shows
  `reserved_names` used only at :927. Low is the right severity, and if
  anything the visible symptom is milder than the hunter says: `ingest.js:878`
  only prints "will be saved as X" when `final_name !== name`, so in the
  hunter's own scenario the panel says nothing at all and the surprise is a
  silent `Theme (2).mp3` rather than a contradicted label.
- Fix note: `reserved = set(reserved_names(conn))` (a copy - the local set is
  mutated per item by `allocate_name`). No test pins the current behaviour;
  b-roll's `precheck` is worth checking for the same gap in the same change.

## music-4
- Verdict: CONFIRMED (low), with one leg of it weakened
- Duplicate of: none (broll-indexer-4 is a different crash in the b-roll
  indexer's probe path, not this one)
- Reasoning: the second half of the finding is solid and is the more
  interesting one: `source_info` returns `{}` for a file with no audio stream
  (proxies.py:86-90), `is_pointless({})` is False (`0 < 0` fails), so the
  `--dry-run` branch (make_proxies.py:149-160) counts it BUILT with
  `duration=0`, while the real run raises `RuntimeError('no decodable audio
  stream')` in `build_track` (:254-255) and `build_all.one`'s blanket
  `except Exception` makes it FAILED. The two modes disagree by construction.
  The first half is weaker than stated: `main()` calls `config.require_tools()`
  before anything (make_proxies.py:113-118), which checks ffprobe is on PATH or
  is an absolute file, so `FileNotFoundError` from `subprocess.run` is
  effectively pre-empted for THIS entry point. `subprocess.TimeoutExpired`
  (timeout=120, outside the `try`) and a mid-run `OSError` still escape, and
  the dry-run branch has no guard at all, so the "one bad file kills the whole
  estimate" scenario stands.
- Evidence: read of `_ffprobe`/`source_info`/`is_pointless`/`build_track`/
  `build_all` and of the whole `--dry-run` branch; `require_tools` read at
  `music/indexer/music_index/config.py:49-58`. Not reproduced against ffprobe
  (would need a deliberately truncated file and a 120 s wait).
- Fix note: the suggested fix is right; catch
  `(OSError, subprocess.SubprocessError)` around the `subprocess.run` (which
  covers both `TimeoutExpired` and `SubprocessError` subclasses) and count an
  empty `source_info` as FAILED in the dry run. Note the real run's behaviour
  would change too: with `_ffprobe` swallowing a timeout, `build_track` raises
  its `RuntimeError` instead of propagating `TimeoutExpired` - same FAILED row,
  better message, so nothing downstream breaks. `decoded_duration`
  (proxies.py:120, `timeout=900`) has the identical unguarded shape and should
  be looked at in the same change. No test covers `--dry-run` at all.

## install-onboard-1
- Verdict: CONFIRMED (medium)
- Duplicate of: none; same file and same root cause as install-onboard-5 (both
  are "DRY_RUN does not gate a post-removal statement"), but distinct lines and
  distinct wrong sentences, so they are not one finding.
- Reasoning: `BIN_DIR="$CCSYNC_LOCAL/bin"` (macos_uninstall.sh:64), so in a dry
  run - where the tree is deliberately untouched - the `if [ -d "$BIN_DIR" ]`
  block at :217 always fires, sets `REMOVAL_INCOMPLETE=1` unconditionally, and
  `closing_verdict "$REMOVAL_INCOMPLETE"` (:309) takes the warning branch. The
  `(dry run -- nothing changed)` string is unreachable whenever the app is
  installed, which is every case a dry run is run in. `git diff` shows the
  `REMOVAL_INCOMPLETE=1` and the gated verdict landed together in the 09-11b
  fix, so this is a regression of that fix, as the hunter says.
- Evidence: reproduced the three blocks verbatim in a scratch script over a
  populated fake `~/.local/ccsync/bin` with `DRY_RUN=1`: output ends
  `WARN: ... still exists -- remove it by hand` then `WARN: CCSync uninstall NOT
  complete: ...`, with no "(dry run" anywhere. Medium holds: the warning's own
  remedy is `rm -rf "$CCSYNC_LOCAL"`, i.e. an editor who ran the script
  precisely to avoid changing anything is instructed to delete the install.
- Fix note: the suggested fix is right; prefer the `[ "$DRY_RUN" = 1 ] || {...}`
  guard over passing 0 to `closing_verdict`, since the latter would also hide a
  real leftovers warning if the dry-run flag were ever set alongside a delete.
  A fix must also touch `installer/tests/test_macos_site_values.sh` - see
  install-onboard-3, which is the reason CI is green on this.

## install-onboard-2
- Verdict: CONFIRMED (medium)
- Duplicate of: none
- Reasoning: verified the asymmetry. Section 4 re-reads the directory after the
  delete (`$binLeftovers = Get-BinDirLeftovers ...`, :538) and reports
  accordingly; section 5's `-Full` branch (:620-627) does
  `Remove-Item -LiteralPath $CcsyncLocal -Recurse -Force -ErrorAction
  SilentlyContinue` followed unconditionally by `Write-Step "removed
  $CcsyncLocal"`, and the identity paragraph at :658 is outside any test. Since
  `$SyncthingHome = "$CcsyncLocal\syncthing-config"` (:97), the device identity
  is exactly what may survive. The closing advice is computed from
  `$binLeftovers` (:683), which was measured before section 5 ran. The lock
  scenario is real: section 1 calls `Stop-Process -Force` with no wait, and the
  file's own comment at :158 already concedes "Stop-Process -Force does not wait
  for the image handle". The false claim points the wrong way from the known
  stuck-lane-C / regenerated-device-ID incident, so the admin chases a device ID
  that never changes.
- Evidence: whole-file read; `$binLeftovers` is assigned only at :538;
  `grep` of `installer/tests/Test-BinDirLeftovers.ps1` finds no `-Full` and no
  `CcsyncLocal`, confirming the `-Full` path is untested. No uninstaller was
  run.
- Fix note: the suggested fix is right. It must also feed the result into
  `Get-UninstallClosingAdvice` (or the verdict still says "complete" over a
  surviving identity) and extend `Test-BinDirLeftovers.ps1`, which is the only
  test near this code. Note `Remove-Item -Recurse` on a partially locked tree
  can also delete SOME children, so the new message should name what is left
  rather than say "nothing was removed".

## install-onboard-3
- Verdict: CONFIRMED (low)
- Duplicate of: none (it is the test-side explanation of install-onboard-1, not
  a second copy of it)
- Reasoning: read `installer/tests/test_macos_site_values.sh:396-417`: the case
  evals `VERDICT_SRC` in a subshell with `DRY_RUN=0` hardcoded and calls
  `closing_verdict 0` / `closing_verdict 1` directly. It never sources section
  3, so which branch a real run reaches - the only thing the 09-11b change
  altered about the flow - is unpinned, and install-onboard-1 is green. The
  `remove_local_tree` case just above it is likewise a single extracted
  function. This is a genuine coverage hole, correctly rated low (a test gap is
  not itself a fleet defect).
- Evidence: source read; the hunter's claim that the suite passes on a tree
  containing install-onboard-1 follows directly from the hardcoded `DRY_RUN=0`.
- Fix note: the suggested fix is right and should be written as part of the
  install-onboard-1 fix, not separately. Extracting section 3 wholesale is
  awkward with the current sed/awk slicing in that harness; a cleaner pin is to
  run the whole script with `--dry-run` under a fake `HOME` and a stubbed
  `launchctl`/`brew`, which would also cover install-onboard-5.

## install-onboard-4
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `_same_dashboard` (steps.py:238-256) reduces both sides to
  `urlparse(...).hostname` and compares case-insensitively, so scheme and port
  are dropped by construction; `site_manifest_value` then returns the cached
  `canonical_prefix`/`tree_name`, which `run_bootstrap` puts on argv, and
  `windows_bootstrap.ps1` calls `Get-SiteValue` only when the flag is empty.
  The mechanism is exactly as described. Low is right: a single host fronting
  two dashboards is not the shipped shape (one dashboard per NAS, published by
  Tailscale Serve), it needs the second dashboard to be unreachable at that
  moment, and the cache must be under 30 days old.
- Evidence: ran the real helpers from `onboarding/` with the companion package
  on PYTHONPATH - `_same_dashboard('https://nas.ts.net:8480',
  'https://nas.ts.net:8481')` is `True`, and so is
  `('https://nas.ts.net:8480', 'http://nas.ts.net')`.
- Fix note: the suggested fix is right in shape but needs the blank rule
  extended to the port, or it regresses install-onboard-2's cache path: a port
  absent on either side must mean "cannot tell -> allow", and only two
  explicitly different ports may be a refusal. With that rule the four existing
  cases in `onboarding/tests/test_bug_hunt_2026_09_11b_install_onboard.py`
  (including the bare-host spelling `old-nas.tailabc.ts.net`) still pass -
  checked by hand against `normalise_dashboard_url`.

## install-onboard-5
- Verdict: CONFIRMED (low)
- Duplicate of: install-onboard-1 in ROOT CAUSE only (both are `DRY_RUN`
  ungated statements in `macos_uninstall.sh` section 3); reported separately is
  fine, and one fix should close both.
- Reasoning: the `warn "that included the Syncthing identity in
  $SYNCTHING_HOME. A reinstall generates a NEW device ID ..."` at :210-212 sits
  inside `if [ -d "$CCSYNC_LOCAL" ]` and is gated only on
  `REMOVAL_INCOMPLETE = 0`, which is still 0 at that point in a dry run (the
  `BIN_DIR` block that sets it comes seven lines later). Past tense about a
  deletion that did not happen, and the consequence named - the admin
  re-approving a device whose ID never changed - matches a failure mode this
  fleet has actually had.
- Evidence: the same scratch reproduction printed `WARN: that included the
  Syncthing identity in .../syncthing-config. A reinstall generates a NEW device
  ID...` with `DRY_RUN=1`.
- Fix note: the suggested fix is right; the tidiest version moves the sentence
  into `remove_local_tree`'s success branch (which is only reached on a real
  removal) and gives the dry-run branch its own "would also remove ..." line.
  Same test file as install-onboard-3 must gain the case, or this comes back.
