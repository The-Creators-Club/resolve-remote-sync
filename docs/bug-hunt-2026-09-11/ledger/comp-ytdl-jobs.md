## Companion: downloads, fleet jobs, upgrades, reporting, 2026-09-11 (CR-237)

### comp-ytdl-jobs-1 - the one refusal REL-3 was written for was the one refusal it threw away - FIXED (companion, `upgrade.py`)

`UpgradeManager.refusal()` self-cleared the standing refusal whenever the
refused version compared `VERSION_SAME` **or `VERSION_OLDER`** against the
running build, while its own docstring justified only the SAME case ("a
machine that is now RUNNING the build it refused"). Every refusal the
downgrade floor produces is by construction about a version at or below the
running one, and so is a Mac handed an older-versioned Windows record. So an
admin republishing 0.9.65 as a rollback - a first-class operation, per
`docs/RELEASE.md` - got the whole fleet rendered as "pending" on the Packages
page: each companion refused the offer at receipt, `_note_refusal` stored the
verdict, `refusal()` discarded it on the first read, the report carried nulls,
`_store_upgrade_refusal` wrote nothing and the `upgraded_refused` alert never
fired. The reason (delete `upgrade_floor.json` on that machine) existed only
in one `log.error` in that editor's `companion.log`.

Fixed: clear on `VERSION_SAME` only. A refusal that should ever self-retire
retires on age, not on ordering. The pinning test was the giveaway and is
rewritten: `test_a_build_below_the_floor_is_a_refusal_too` refused **9.9.8**,
which is NEWER than every shipped VERSION, so it asserted the property using
the one case that could not break; it now refuses a version below
`config.VERSION`, and a second test reads the refusal twice, because the
report re-reads it every heavy tick and the old self-clear retired it on the
first read.

### comp-ytdl-jobs-2 - a report reply wiped the tray's [ STOP ], so the job ran to completion on a machine whose owner had asked for it back - FIXED (`jobs_runner.py`)

`stop_current()` deliberately reuses the admin's `_cancel` list, and
`note_report_reply` REPLACED that list wholesale with whatever the dashboard
sent. The dashboard is never told about a local stop (nothing posts one, and
`db.pending_job_cancels` is fed only by an admin cancel), so that id could
never come back - and the commonest reply of all carries no `jobs` block at
all, in which case the list was replaced with `[]`. `_cancel_requested` is
polled once per `proc.wait` slice, so a reply landing inside that window erased
the stop before the job thread ever read it: the child was never terminated,
the heartbeat kept renewing the lease, and the job finished normally after the
tray had said it was stopped.

Fixed: the ids the person at this machine asked to stop live in their own set,
which `note_report_reply` UNIONS into `_cancel` instead of overwriting, and
which `_post_result` prunes - so a job number the dashboard reuses after a
rebuild is not cancelled by a stop somebody asked for last week.

### comp-ytdl-jobs-3 - a sidecar ffmpeg that could not install reached nobody, and the machine simply disappeared from every media job kind - FIXED (`sidecar_tools.py`, `ytdlp_manager.py`)

`install_tool` swallowed every download failure into one `log.info` and
returned False; `ensure_ffmpeg_pair` turned that into "could not install
ffmpeg, ffprobe" with the cause dropped; `ytdlp_manager._loop` logged that
string at INFO when the downloader was on and **DEBUG when it was off** - the
vendor default - so at the shipped log level there was literally nothing. The
only fleet-visible consequence was `capabilities.ffmpeg=false`, which makes the
machine silently ineligible for `proxy-480p`, `audio-extract` and `peaks`: it
reads as "this machine was never set up" rather than "this machine cannot
verify GitHub's certificate", which is a live field problem on macOS. CYT-7
fixed exactly this shape for yt-dlp and left the sidecar behind.

Fixed on CYT-7's pattern: the exception text is kept per tool and rides the
returned `message` and a new `cause` key; consecutive failed passes are counted
and a REPEAT is logged at WARNING regardless of the feature flag (the ffmpeg
pair stopped being a YouTube entitlement in comp-ytdl-2), and the loop no longer
demotes a failed pass to DEBUG. The verdict is published as an OPTIONAL
`sidecar` key inside the `sync_guard.ytdlp` block that already exists
(`ytdlp_manager.status_report`), so nothing new had to be plumbed through
`app.py` and a dashboard that does not read it is unchanged.
`ytdlp_manager.sidecar_warning_line()` is the Settings line, quiet on the first
failed pass and worded for the consequence an editor can see; wiring it into
`tray.py` is OWED below.

### comp-ytdl-jobs-4 - `_read_pcm` built the peaks out of a buffer its drain thread was still writing to - FIXED (`jobs_media.py`)

After the child exits, the two drain threads are joined with a timeout and the
code then read `chunks` and returned, with no liveness test - so a drain that
had not reached EOF within 30 s (a stalled share still holding the read end
open) produced peaks from a partial buffer while the reader thread was still
appending to the same list. That is the silent truncation the 2026-09-03
rewrite's own comment says the join exists to prevent, and the job reported
success: `_publish` renamed it under the final name and Timeline Cards cached it
as current, because its mtime beats the source's, so it was never remade. Fixed:
an expired join kills the child and raises `MediaJobError("the decode output
could not be read to the end")` - retryable, which a truncated peaks file is
not. The timeout is now the named `DRAIN_JOIN_SECONDS`, so the test can prove it
without sitting out half a minute.

### comp-ytdl-jobs-5 - the gate sentence glued two explanations together, one of them no longer true - FIXED (`jobs_runner.py`)

`_gate_note` was set for `no_capability` and `local_work` and cleared only on
the path that reached the bottom of `_gate()`. `STATE_DISABLED`,
`STATE_NO_DASHBOARD`, `STATE_HALTED` and `STATE_RUNNING` all return before any
assignment, so the previous tick's note was still appended by `status()` and
rode `capabilities.jobs_gate.detail` to the dashboard: a machine indexing b-roll
and then halted read "Your admin has stopped syncing for the whole fleet, so
this computer is not taking work of any kind. Indexing b-roll". Fixed by
clearing the note once at the top of `_gate()`.

### ytdl-web-3 (companion half) - the fleet calls above the claim did not say WHICH computer was making them - FIXED (`ytdl_executor.py`)

CR-66 narrowed the download lease to `(editor, machine_id)` at the CLAIM door
only; the heartbeat, the download manifest and the per-clip status all went
through `is_leaseholder(job, editor)`, which answers for a PERSON. A laptop that
stalled past the lease, lost the job to the same editor's desktop and then woke
up kept re-extending a lease that belonged to the other machine, kept fetching
the manifest and kept posting `done` against it - two trees, two copies of every
clip, lane A carrying both up. Neither companion was ever told 410, so neither
stopped. The companion half: the heartbeat and clip-status bodies now carry
`machine_id` (the value `machine.py` mints into `~/.ccsync/machine.json`, the
same id the claim already sends), and the manifest GET carries it as a query
parameter. It is OPTIONAL on the wire in both directions: absent means today's
per-editor answer, a server that does not read it sees a field and a query
parameter it ignores, and a companion that cannot read `machine.json` sends
nothing and behaves exactly as it does today. The server-side check is the
`ytdl-web` builder's half. **Deploy the dashboard before the companions is not
required here** - either order is safe - but the behaviour only changes once
both sides are in.

### res-companion-4 (the `upgrade._write_json` half) - a crash-loop counter that could not be written said nothing - FIXED (`upgrade.py`)

`_write_json` returned False and logged at DEBUG, and its caller
`note_version_start` did not look at the return - so an unwritable `~/.ccsync`
(a full disk, an AV lock) turned every start into "we know nothing", which means
a build that is not staying up is never reverted by APP-5's guard and keeps
coming back for ever, with nothing at the shipped log level to say why. Fixed:
the swallowed write is a WARNING that names the path and counts itself in
process (`upgrade.write_failures()`, in memory because the thing that cannot be
done is writing to disk), and `note_version_start` says out loud that this start
was not recorded. The supervisor half of the same finding belongs to `comp-ui`.

### Verification
- `tests/test_upgrade.py::test_a_build_below_the_floor_is_a_refusal_too` -> fails at 40f931a, passes now (comp-ytdl-jobs-1)
- `tests/test_upgrade.py::test_a_rollback_below_the_floor_keeps_being_reported` -> fails at 40f931a, passes now (comp-ytdl-jobs-1)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_a_report_reply_with_no_jobs_block_does_not_wipe_a_local_stop` -> fails at 40f931a, passes now (comp-ytdl-jobs-2)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_a_report_reply_carrying_other_cancels_keeps_the_local_one` -> fails at 40f931a, passes now (comp-ytdl-jobs-2)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_the_local_stop_retires_once_the_result_is_posted` -> guard on the prune half (passes at 40f931a for the wrong reason: the reply had already erased the id)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_a_failed_sidecar_install_carries_its_cause` -> fails at 40f931a, passes now (comp-ytdl-jobs-3)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_a_repeated_sidecar_failure_is_a_warning_whatever_the_flag_says` -> fails at 40f931a, passes now (comp-ytdl-jobs-3)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_the_sidecar_verdict_rides_the_report_block_that_already_exists` -> fails at 40f931a, passes now (comp-ytdl-jobs-3)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_the_sidecar_warning_line_waits_for_a_second_failed_pass` -> fails at 40f931a, passes now (comp-ytdl-jobs-3)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_a_pcm_drain_that_never_reaches_eof_fails_the_job` -> fails at 40f931a, passes now (comp-ytdl-jobs-4)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_a_halt_does_not_inherit_the_previous_ticks_gate_note` -> fails at 40f931a, passes now (comp-ytdl-jobs-5)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_the_heartbeat_names_the_machine` -> fails at 40f931a, passes now (ytdl-web-3)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_the_manifest_fetch_names_the_machine` -> fails at 40f931a, passes now (ytdl-web-3)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_a_clip_status_names_the_machine` -> fails at 40f931a, passes now (ytdl-web-3)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_a_machine_with_no_id_sends_no_field` -> guard: absent must keep meaning today's per-editor answer
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_a_swallowed_state_write_is_a_warning_and_a_count` -> fails at 40f931a, passes now (res-companion-4)
- `tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py::test_note_version_start_says_so_when_it_could_not_record_the_start` -> fails at 40f931a, passes now (res-companion-4)

Also run green after the change: `test_jobs_runner.py`,
`test_jobs_runner_visibility.py`, `test_jobs_media.py`, `test_sidecar_tools.py`,
`test_ytdlp_manager.py`, `test_ytdl_executor.py`, `test_jobs_phase4.py`,
`test_jobs_resilience.py`, `test_upgrade.py`, `test_upgrade_floor_guards.py`,
`test_crash_loop_revert.py`, `test_self_upgrade_handoff.py`, `test_reporter.py`,
`test_no_em_dash.py` (569 + 169 + 100 tests, 0 failures).

### OWED TO ANOTHER TERRITORY
- `companion/src/ccsync_companion/tray.py` (comp-ui/comp-app): the sidecar
  sentence needs one caller. `tray._ytdlp_status()` already holds the dict that
  now carries the optional `sidecar` key, so the whole wiring is to append
  `ytdlp_manager.sidecar_warning_line(snap.get("ytdlp_status"))` beside the
  existing `ytdlp_warning_line(...)` line in `settings_window.py:1359`. Without
  it the cause still reaches the report and the log at WARNING, which is the
  half that matters most (an admin, not the editor, is who can fix a CA bundle).
- `dashboard/src/ccsync_dashboard/` (dash-api-jobs / dash-alerts): nothing is
  REQUIRED - the block is optional and ignorable - but to finish CYT-7's shape
  for the sidecar the dashboard would need `sync_guard.ytdlp.sidecar` accepted
  on `_BoundedSectionIn`, a column, and an `alerts.ALERT_KINDS` row registered
  WITH its writer ("this machine cannot install ffmpeg: <cause>"). Not done here
  and not owed by this fix: the companion side is complete without it.
- `ytdl/web/ytdlweb/` (ytdl-web): the server half of ytdl-web-3 - read
  `machine_id` off `HeartbeatIn` / `ClipStatusIn` / the manifest query, pass it
  into `is_leaseholder`, and 410 a machine that is not the recorded holder.

### Owner decisions
- The sidecar warning waits for the SECOND consecutive failed pass before it
  says anything (one GitHub blip is not news; a machine that has silently
  stopped taking media work is). The WARNING log line has the same threshold.
  An owner who wants the first failure to speak should say so.
- `sync_guard.ytdlp.sidecar` was nested inside the existing yt-dlp block rather
  than added as a new top-level `sync_guard.sidecar` section, because the block
  is assembled in `app.py` (out of this territory) and nesting needs no change
  there. If the dashboard would rather have a sibling section, that is a
  one-line move in `app.ytdlp_report`.
