## Server scripts and release tooling, 2026-09-11 (CR-247)

### CR-247 - the -EmitKindExtras gate passed a fleet it had not looked at, a snapshot mount the container cannot read through, a deploy aborted by a file that moved under it, and two tools that answered an unreachable dashboard with a traceback - FIXED 2026-09-11 (`tools/`, `server/`)

**server-tools-1 (high) - "every reporting computer is on 0.9.55 or newer",
having examined nothing.** `-EmitKindExtras` signs `requires_dashboard` and
`arch` into the release record, and a companion below 0.9.55 does not know
those field names: its signature check fails on the WHOLE record, it refuses
the build silently and for ever, and the only recovery is a reinstall at that
desk. The gate that was supposed to make that impossible (REL-4) guarded with
`if ($null -eq $health -or $null -eq $health.rollout)`, and in PowerShell
`$null -eq @()` is `$false` - it catches a MISSING property, never an empty
array. `api._rollout_block` returns `[]` on ANY exception with HTTP 200 (a
locked database, a column an older schema lacks, a collector mid-migration),
so a dashboard-side fault the operator cannot see walked straight past the
refusal: the `foreach` ran zero times, `$stragglers.Count` was 0, and the ship
printed the all-clear. A second hole in the same block: it iterated CHANNELS,
and `db.rollout_status` builds one channel per (kind, platform) that has a
CURRENT build, so a platform with real computers and no current package - a
fresh site, or a macOS channel nobody has pointed current - contributed no
channel and its machines were invisible even when the array was non-empty.
That is the leso-Mac-on-0.9.2 shape exactly. The verdict half of the gate now
lives in `tools/ship_gates.ps1` (`Get-KindExtrasVerdict`), where it can be run
against real health bodies instead of read: an absent, null or EMPTY rollout
is UNREADABLE, which is a refusal; the count that decides is machines per
platform, from an optional `rollout_platforms` block on `/api/v1/health`; and
a dashboard too old to report that block is unreadable too, not clear.
ship.ps1 keeps every message and every exit, and prints the verdict's reason
line. `Test-VersionAtLeast` moved into the same file, unchanged, so there is
one definition.

**server-tools-3 (medium, mechanism confirmed, NOT verified live) - the
recovery page's snapshot mount very likely carries nothing.**
`<mountpoint>/.zfs/snapshot` is ZFS's control directory: listing it shows the
snapshot NAMES, but each name is an AUTOMOUNT the kernel performs in the
HOST's mount namespace on first traversal, and unmounts again after
inactivity. A docker bind is `rprivate` by default, so a mount that appears
under the source after the container started does not propagate into it: the
container keeps seeing an empty trigger directory, and Settings -> RECOVERY
answers `RecoveryError` 404 - "the snapshot holds no folder for <project>" -
blaming a rename that never happened. It is intermittent, because a snapshot
already mounted when the container started IS visible, which is the worst
shape there is for an operator mid-incident. The mount is written by
`snapshot_volumes` in `install_dashboard_app.py` and now carries `ro,rslave`
(short-syntax comma options, so the hand-rolled compose renderer and every
`:`-splitting reader of `volumes` are untouched). rslave is only our half:
the HOST mount must carry `shared` propagation, which is a change to the
NAS's own mount namespace a deploy may not make silently, so
`snapshot_propagation_note()` prints the `findmnt -no PROPAGATION`, the
`mount --make-rshared` and the `docker exec ... ls /snapshots/<snapshot>/`
that proves it end to end, on every deploy that mounts snapshots.

**server-tools-4 (low) - a finished upload aborted because a file moved under
the source.** `install_tree` did `expected = upload_tree(...)`, which walks
`iter_local_files(source, excludes)` and SFTPs it, and then walked the same
tree AGAIN with `local_manifest(...)` - so the deploy verified the uploaded
copy against a manifest of a tree it had not uploaded. Anything creating or
removing a file under `dashboard/` (or `broll/web`, `music/web`, `ytdl/web`)
mid-transfer - an editor saving, a build, a stray tool - either aborted the
whole SFTP with "internal manifest mismatch" or shifted `expected_bytes` so
the staged-tree check failed instead. Both refusals are in the safe direction
(nothing is swapped), so this was a wasted transfer explained by a message
about an internal disagreement. The suite found it before an operator did:
two `test_music_deploy` tests failed with "(297 vs 296)" on one run of the
full server suite and passed on the next. There is one walk now, taken before
the upload and sent verbatim; `upload_tree` reports back what it actually
sent, with the byte total the SFTP server confirmed per file rather than a
local stat from some other moment; and the internal count check is kept as
what it always was, an assertion on one list.

**server-tools-5 (low) - an unreachable dashboard came back as a urllib
traceback.** `Http.send` in `tools/jobs.py` and `tools/publish_package.py`
caught `urllib.error.HTTPError` only, so `URLError` (connection refused, DNS
failure, TLS failure) and a socket timeout escaped unhandled - past `main`'s
`JobsError`/`PublishError` handler - on the commonest failure either tool
has: the NAS rebooting, or a dashboard restarting mid-deploy while
`ship.cmd` publishes. Every other failure in both scripts is a sentence
naming the next action. Both now raise their own error naming the URL and the
reason, and publish_package's says that nothing was published.

**server-tools-6 (low) - `check_deploy_drift.ps1 -Watch` retried an expired
session for ever.** The watch loop caught every failure of the admin
`packages` GET, printed one line, slept 60 s and continued, with no ceiling
and no way to tell a dashboard restarting (the case it was written for) from
a session cookie that has expired - which is guaranteed on a long rollout,
because the session is minted once, before the report. It printed the same
line once a minute until the operator gave up, and never reached the
completion line it exists to print. A 401/403 now ends the watch naming the
expired session, anything else is retried five times and then gives up with
the same re-run line.

### Verification
- server/tests/test_bug_hunt_2026_09_11_server_tools.py::test_a_file_appearing_under_the_source_does_not_abort_a_finished_upload -> fails at 40f931a, passes now  (server-tools-4)
- server/tests/test_bug_hunt_2026_09_11_server_tools.py::test_a_file_removed_under_the_source_does_not_abort_it_either -> fails at 40f931a, passes now  (server-tools-4)
- server/tests/test_bug_hunt_2026_09_11_server_tools.py::test_the_byte_total_is_what_the_nas_confirmed_not_a_later_local_stat -> fails at 40f931a, passes now  (server-tools-4)
- server/tests/test_bug_hunt_2026_09_11_server_tools.py::test_upload_tree_reports_what_it_sent -> fails at 40f931a, passes now  (server-tools-4)
- server/tests/test_bug_hunt_2026_09_11_server_tools.py::test_the_snapshot_mount_follows_the_hosts_automounts -> fails at 40f931a, passes now  (server-tools-3)
- server/tests/test_bug_hunt_2026_09_11_server_tools.py::test_the_compose_body_carries_the_propagation_option -> fails at 40f931a, passes now  (server-tools-3)
- server/tests/test_bug_hunt_2026_09_11_server_tools.py::test_the_deploy_names_the_host_side_half_of_it -> fails at 40f931a, passes now  (server-tools-3)
- tools/tests/test_bug_hunt_2026_09_11_server_tools.py::TestEmitKindExtrasFailsClosed::test_an_empty_rollout_is_refused_not_waved_through -> fails at 40f931a, passes now  (server-tools-1)
- tools/tests/test_bug_hunt_2026_09_11_server_tools.py::TestEmitKindExtrasFailsClosed::test_a_platform_with_computers_and_no_current_build_is_counted -> fails at 40f931a, passes now  (server-tools-1)
- tools/tests/test_bug_hunt_2026_09_11_server_tools.py::TestUnreachableDashboardIsASentence (3 tests) -> fails at 40f931a, passes now  (server-tools-5)
- tools/tests/test_bug_hunt_2026_09_11_server_tools.py::TestTheWatchLoopGivesUp (2 tests) -> fails at 40f931a, passes now  (server-tools-6)
- Also updated and green: server/tests/test_snapshot_mount.py (the mount string), server/tests/test_deploy_resilience.py::test_install_tree_records_the_tree_it_renamed_aside (it stubbed the second walk that no longer happens).

### OWED TO ANOTHER TERRITORY
- `dashboard/src/ccsync_dashboard/api.py::_rollout_block`: two things, both
  read by the fixed gate. (1) it returns `[]` both for "nothing is current"
  and for "the computation raised" - one wire representation for two facts;
  it should return `null` (JSON) on the exception path, which ship.ps1 already
  treats as unreadable. (2) `/api/v1/health` needs a sibling block
  `"rollout_platforms": {"windows": 7, "macos": 2}` - the MACHINE count per
  platform from `machine_state`, independent of which platforms have a current
  package - so the gate can see a platform with computers and no channel.
  Until that ships, `-EmitKindExtras` REFUSES on every dashboard (it is
  unreadable by the rule above), which is the safe direction and the reason
  the refusal names `ship.cmd -DashboardOnly`. Counts only, no names: the
  fleet credential reads this route. Deploy the dashboard first.
- `dashboard/src/ccsync_dashboard/recovery.py`: an empty snapshot directory is
  reported as "the snapshot holds no folder for <label> ... or its folder has
  been renamed since", which after server-tools-3 is the wrong explanation.
  Worth a second sentence naming mount propagation once the live check below
  has been done.

### Owner decisions
- server-tools-1: `-EmitKindExtras` is now REFUSED whenever the fleet cannot
  be assessed, which includes every dashboard deployed before the
  `rollout_platforms` block above exists. The flag is rare and the refusal
  names the fix, but it does mean the dashboard must be deployed before a ship
  that uses it. The alternative (fall back to counting channels when the block
  is absent) is the fail-open this finding is about.
- server-tools-3: the mount option is shipped unverified, because it cannot be
  verified from here. It is inert if the mechanism is not the problem: `ro` is
  unchanged and `rslave` on an rprivate host mount is a no-op. THE LIVE CHECK
  IS STILL OWED, and the deploy now prints it: `docker exec <container> ls
  /snapshots/<snapshot>/` on a snapshot nobody has touched for an hour. If it
  comes back empty even after `mount --make-rshared`, the fallback is to have
  the recovery page read snapshots over SSH, which needs nothing from the
  host's mount namespace.
- `tools/ship_gates.ps1` is a new file that `tools/ship.ps1` dot-sources. It
  exists because the defect was in the PowerShell semantics of one comparison,
  and while the gate was inline the only thing any test could assert about
  it was its source text.
