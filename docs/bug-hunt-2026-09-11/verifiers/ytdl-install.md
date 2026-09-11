# verdicts - ytdl-install

Verified at HEAD 40f931a. Read-only apart from this file. Probes run from the
dashboard venv (`ytdl/web`) and by reading `onboarding/`, `installer/`.

## ytdl-web-1
- Verdict: CONFIRMED (medium)
- Reasoning: `free_bytes_at` walks up to the first ancestor `shutil.disk_usage`
  answers for and never checks that the answering path is the destination's
  filesystem, so the ONLY "cannot tell" answer is an exception. A bind mount
  that has gone away leaves its mount-point directory behind on the container's
  own filesystem, which is exactly the case where `disk_usage` succeeds with the
  wrong number - so the fail-open path the docstring advertises ("a vanished
  mount ... FAILS OPEN") is unreachable for a vanished mount. I tried to refute
  it by looking for a tree-presence check ahead of the gate in `start_download`
  or anywhere in `ytdlweb`: there is none (`PROJECTS_ROOT` is referenced in five
  places, all of them `safe_join` for a path, none of them a liveness test), so
  nothing else in this service would name the real fault either. The harm is the
  message, not the refusal: it sends the editor to delete footage, and a second
  press repeats it.
- Evidence: probe from the dashboard venv against a path whose last three
  segments do not exist -> `free_bytes_at('.../nope/deeper/still')` returned
  493215760384 (the answering ancestor's free space) and cached it under the
  FULL non-existent path. Confirms both the walk-up and that no comparison is
  made between the path asked about and the path answered for.
- Fix note: the suggested `st_dev` comparison against `PROJECTS_ROOT` does NOT
  work on its own - when the mount is the one that vanished, `PROJECTS_ROOT`
  itself is the leftover directory on the overlay, so both sides match and the
  refusal still fires. The cheap correct guard is "refuse only if the
  destination's own project folder exists" (with the tree mounted it does; with
  the tree gone the walk-up is what happens, and that is precisely the case to
  fail open on), or record the answering path and fail open whenever it is an
  ancestor of `PROJECTS_ROOT`. Any fix must also touch
  `ytdl/web/tests/test_says_what_it_knows.py:203`, which pins the walk-up as
  intended, and the `free_bytes_at` docstring, which currently claims the
  behaviour the fix removes.

## ytdl-web-2
- Verdict: DOWNGRADED to low
- Reasoning: the mechanism is real and reproducible - the cache key is the
  destination path, the entry is written on every call including the refusing
  one, nothing clears it, and there is no way for the editor to force a re-stat.
  But the damage is bounded at 60 s, self-heals with no intervention, and the
  quoted number is never more than a minute stale; the editor who presses twice
  presses a third time. That is an annoyance in the same class as the hunter's
  own low-rated findings (-4, -6), not a medium beside -1, whose failure mode is
  an editor deleting footage for a reason that is not true. Recorded as real,
  not refuted.
- Evidence: probe - `free_bytes_at(p)` returned a planted cached value 123 on
  the second call and the real number again only at `now + 61`. `_refuse_if_full`
  calls it with no `now` and never touches `_free_cache`.
- Fix note: "cache only passes, never refusals" is the right half of the
  suggestion and is a one-line change inside `free_bytes_at`'s caller; deleting
  the key from `_refuse_if_full` reaches into the cache from outside and would
  race the lock. Note that fixing -1 the way I describe changes what is cached,
  so -1 and -2 should be fixed together in one edit rather than twice.

## ytdl-web-3
- Verdict: CONFIRMED (medium)
- Reasoning: the wire claim checks out on both sides. `is_leaseholder` always
  calls `lease_held_by(job, editor)` with `machine=None`, and `lease_held_by`
  returns True for any machine when the caller does not say which; the companion
  sends `{"editor": ...}` only on the heartbeat (`ytdl_executor.py:1150`) and a
  body with no machine field on clip status (`:1160-1188`), while the claim body
  does carry `machine_id` (`:1130`). `heartbeat_download`'s WHERE is
  `claimed_by=? AND lease_expires_at>?` - a person, not a computer - so the
  stale executor re-extends the new holder's lease and is never told 410, and
  `clip_status` writes `download_host = job['claimed_by']`, which is now the
  other machine. I tried to refute it on reachability: `start_download` 409s
  while the phase is `downloading`, so B cannot claim during A's run, and the
  worker's reclaim is one-way (`mode_lock='server'`). The reachable sequence is
  the ordinary one: A stalls, the lease expires, the worker reclaims and the job
  ends `done`/`failed`, the editor presses DOWNLOAD on desktop B (which clears
  the pin and the rest of the executor state, by CR-37's design), B claims, and
  A - which stops on nothing but a 410 - wakes into a lease it is allowed to
  keep renewing. Two trees, two sets of clips, lane A carrying both up.
- Evidence: code read on both sides plus `db.claim_download`'s CAS (an expired
  lease is claimable by another machine of the same editor) and
  `db.reclaim_download` (one-way). `grep -an` over KNOWN_BUGS.md finds no open
  entry for the residual: CR-66's deferral list does not carry it, and
  `data-model-7` is listed among the eight items "closed after all", so this is
  new rather than a known deferral.
- Fix note: the suggested fix is right and is the only shape that works - the
  field must be OPTIONAL on both bodies (absent = today's per-editor answer) or
  every companion below the fix version starts getting 410s mid-download. Files:
  `ytdl/web/ytdlweb/routes_fleet.py` (`HeartbeatIn`, `ClipStatusIn`,
  `_leaseholder_or_410`'s signature, and the manifest route),
  `ytdl/web/ytdlweb/db.py` (`is_leaseholder` gains a `machine` parameter;
  `heartbeat_download` needs `claimed_machine` in its WHERE or the CAS still
  extends), `companion/src/ccsync_companion/ytdl_executor.py` (both bodies), and
  `ytdl/web/tests/` - `is_leaseholder`'s docstring states the per-editor rule as
  deliberate, so it and any test asserting it must be rewritten.

## ytdl-web-5
- Verdict: DOWNGRADED to low
- Reasoning: half of this is not a defect. `NewJob.local` is client-supplied ON
  PURPOSE - CR-96 half 1 (KNOWN_BUGS.md:2980ff) widens `ticked_projects` and
  `resolve_project` to every active project whenever the download will run on
  the server, on the stated reasoning that no machine's sync plan is then a
  constraint, and it was threaded end to end exactly as the hunter describes
  (`GET /api/projects?local=`, `NewJob.local` default True). With the fleet flag
  off, `local:false` from the SPA is TRUE, not a lie, and the destination really
  is unconstrained by design; CR-117 then made `start_download` re-validate under
  the job's stored pair rather than the request's, which is the second door
  working as intended. So "any signed-in editor can put clips in any active
  project" is an accepted property of this deployment, not a new hole, and the
  module docstring is the thing that is wrong. What survives as a real seam is
  narrower and worth fixing: nothing ties `local` to `config.LOCAL_DOWNLOAD` or
  to the claim, so with `YTDL_LOCAL_DOWNLOAD=1` a client can post `local:false`
  to widen its destinations and then still hand the job id to its own companion
  on 127.0.0.1:8899 - `db.claim_download`'s WHERE clause never consults
  `created_local` - which lands 40 clips on a machine in a project it does not
  sync, the one outcome CR-96's argument excluded. That is low: it needs a
  hand-edited request, the actor is an authenticated editor of the same fleet,
  and nothing crosses a tenancy boundary.
- Evidence: `ytdlweb/projects.py:196-201` (`if (not local) or _wired(...) or
  _base_only(...)`), `static/app.js:2397` (`if (!state.localDownload) return
  false;`) and `:2157` (`local: localWanted()`) - the SPA does post `local:false`
  by default with the flag off, as reported. `db.claim_download` (db.py:1073ff)
  and `db.claim_next_job` were read in full: neither reads `created_local`.
- Fix note: "correct the docstrings" is the right answer for the widening
  itself - `routes_api.py:14-19`, `schema.sql` and `migrations/013`'s comment all
  assert an invariant CR-96 deliberately removed, and an owner reading them today
  would be misled. Do NOT "derive `local` server-side from `config.LOCAL_DOWNLOAD`":
  that breaks the legitimate case CR-96 exists for (the flag on, the editor
  unticking "on this machine"). The seam is better closed at the claim door -
  refuse a claim for a job whose `created_local` is 0, since the widening was
  granted on the promise that no machine would claim it - which touches
  `ytdl/web/ytdlweb/db.py` (`claim_download`) and `routes_fleet.claim`'s refusal
  wording only, with no companion-side change.

## install-onboard-1
- Verdict: CONFIRMED (high)
- Reasoning: I could not refute it, and everything checkable from here supports
  it. `posixpath.ismount` is an `st_dev` comparison between the path and its
  parent; on macOS 10.15+ the user's data is on a separate APFS Data volume
  (`/System/Volumes/Data`, its own entry in `mount`, its own device) reached
  through firmlinks, and `/Users` is one of the firmlinked paths, so
  `lstat('/Users').st_dev` is the Data volume's while `lstat('/Users/..').st_dev`
  is the sealed System volume's - different devices, so `ismount('/Users')` is
  True. The darwin branch walks up from `dirname(sys.executable)` and stops at
  the FIRST such hit, so any frozen wizard under `/Users/...` (Downloads,
  Desktop, and `/Applications`, which is firmlinked too) refuses before the
  `path != "/"` loop can end. The refusal is terminal: `_worker_editor` logs and
  calls `_install_failed()` at its first line. The mitigating fact is field
  exposure, not correctness - Mac editors here have been installed by
  `macos_bootstrap.sh` over SSH (see the memory note on installing the macOS
  companion from the channel) - but the frozen wizard is a shipped artefact
  (`build_onboard_macos.spec`, installer 1.0.17+), so on the path it is shipped
  for it cannot succeed.
- Evidence: `onboarding/steps.py:3305-3325` read in full; `_is_mac` falls back to
  `sys.platform`, so the production call at `onboarding/onboard.py:1137`
  (`installer_on_forbidden_drive(self._site())`) takes the darwin branch with the
  real `os.path.ismount`. The three darwin tests
  (`tests/test_site_prefix_handoff.py:204-224`) inject `is_mount=lambda p: False`
  or a single hand-picked path; `test_the_boot_volume_is_fine` asserts False for
  `/Users/leso/Desktop/onboard` with the mount test stubbed to always-False,
  which is the exact call that would be True in production. THE LIVE CHECK THAT
  SETTLES IT, one line on any Catalina-or-later Mac:
  `python3 -c "import os;print(os.path.ismount('/Users'), os.stat('/').st_dev,
  os.stat('/Users').st_dev)"` - two different st_dev values and True is the bug;
  `stat -f '%d %N' / /Users /Applications` and `mount | grep Volumes/Data`
  corroborate. If those come back equal, this finding is refuted outright.
- Fix note: the suggested fix is right in direction but over-broad in one
  respect and under-specified in another. Keeping only `startswith("/Volumes/")`
  restores the CR-119 behaviour and is safe; if the external-SSD case is still
  wanted, compare `os.stat(exe).st_dev` against the HOME directory's st_dev (not
  `/`, and not "any mount boundary") so the Data volume is never itself the
  refusal. The darwin refusal message must also be its own: the text at
  `onboard.py:1138-1142` names a drive letter, "network share" and
  `onboard.exe`, none of which exist on a Mac. A fix must update
  `tests/test_site_prefix_handoff.py::TestForbiddenDriveOnMacOS` -
  `test_any_other_mount_point_is_refused_too` pins the walk-up and would have to
  go or be rewritten around the home-device rule.

## install-onboard-2
- Verdict: CONFIRMED (medium)
- Reasoning: read both sides. `run_bootstrap` does `site = site or {}` at
  `steps.py:1405` and then `site.get("canonical_prefix")` / `site.get("tree_name")`
  at `:1433-1434`, so with `site=None` (which `onboard.py:_site()` returns on any
  failed fetch, deliberately) neither `-CanonicalPrefix`/`-TreeName` nor
  `CCSYNC_CANONICAL_PREFIX`/`CCSYNC_TREE_NAME` is passed - both are guarded by
  `if canonical_prefix:` / `if tree_name:`. `ensure_config` at `:3062` resolves
  the same key through `site_canonical_prefix(site or None)`, i.e. the CACHED
  manifest. So the two halves of one wizard run resolve the same site value from
  two different sources in exactly the state CR-119 was written for. The two
  fetch failures the scenario needs are correlated, not independent - the
  wizard's fetch failing is usually the dashboard being unreachable, which is
  what the bootstrap's own fetch will hit seconds later - so this is not a
  contrived compound failure.
- Evidence: `steps.py:1405`, `:1433-1434`, `:1471-1474` (Windows flags),
  `:1505-1511` (macOS env vars), `:3046-3062`; `onboard.py:541-545`, `:1190`.
  `tests/test_site_prefix_handoff.py:186-192` asserts the run_bootstrap SOURCE
  literally contains `canonical_prefix = str(site.get("canonical_prefix")`, which
  pins the half-fixed behaviour.
- Fix note: the suggested fix is right, with one caveat the existing comment
  already flags: the macOS env vars are set only when the wizard "actually has a
  manifest value", precisely so the wizard's own fallback does not beat the
  script's fetch. Resolving through `cached_site()` keeps that property only if
  the cache-miss case still yields an empty string rather than the `P:\` default
  that `site_canonical_prefix` hands back unconditionally - so `run_bootstrap`
  needs the raw cached key, not `site_canonical_prefix`'s normalised default, or
  a wizard on a machine with no cache will start forcing `P:\` onto a Q: site's
  bootstrap, which is the same bug pointing the other way. Files:
  `onboarding/steps.py` and `onboarding/tests/test_site_prefix_handoff.py:186-192`.

## install-onboard-3
- Verdict: CONFIRMED (medium)
- Reasoning: `windows_uninstall.ps1:434-441` deletes `$BinDir` with
  `-ErrorAction SilentlyContinue`, never re-reads it, and prints "removed program
  binaries: $BinDir" unconditionally - while the Apps & features entry has
  already been removed thirteen lines earlier, by design (OPS-17: the entry
  points at a script inside `$BinDir`). The lock is not hypothetical: step 1 uses
  `Stop-Process -Force` with `SilentlyContinue` and does not wait for the image
  handle to be released, and since OPS-17 the running `windows_uninstall.ps1`
  and `drive_mapping.ps1` live in the directory being deleted
  (`windows_bootstrap.ps1:912-930`). The file's own house style is against it:
  every other removal here re-reads the machine (`$unmapSettled`,
  `Test-SmbShareGone`, and each registry removal uses `-ErrorAction Stop` inside
  a try/catch with a `Write-Warn2`). This one is the only silenced-and-unchecked
  deletion in the script.
- Evidence: `installer/windows_uninstall.ps1:96` ($BinDir), `:154-165`
  (Stop-Process), `:421-433` (entry first, with a warning on failure), `:434-441`
  (the unchecked delete), `:253-363` (the re-read pattern it departs from);
  `installer/windows_bootstrap.ps1:912-930` (the uninstaller's own copy inside
  $BinDir). `Test-UninstallEntry.ps1` covers `Unregister-UninstallEntry` only.
- Fix note: the suggested fix is right, but "excluding $PSCommandPath and
  drive_mapping.ps1" is the load-bearing detail - those two are expected
  leftovers on every successful run (PowerShell may or may not hold the .ps1
  open, and a self-deleting script must not report its own corpse as a failure),
  so a naive `Test-Path $BinDir` would warn on every healthy uninstall and teach
  editors to ignore it. Re-registering the Apps & features entry when binaries
  remain is the better half of the suggestion; if that is taken,
  `Register-UninstallEntry`'s guard in `windows_bootstrap.ps1:889-891` is the
  other file touched, and `installer/tests/Test-UninstallEntry.ps1` is where the
  new behaviour would be pinned.
