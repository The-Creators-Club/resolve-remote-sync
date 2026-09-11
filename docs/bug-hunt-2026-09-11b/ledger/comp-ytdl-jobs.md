## Companion: the upgrade refusal, the sidecar tools and the fleet job runner (CR-254, 2026-09-11)

Seven findings from the 2026-09-11b hunt, six of them about the state the same
morning's CR-237 pass created: a refusal with no way out, a cause and a counter
that reached only one of the two entry points, a liveness check on the wrong
thread, an unbounded list of local stops, and a fleet-visible change with no
test. The seventh is the companion half of wire-5 / dash-api-4: dash-api-6's
account bar answers 403 on the job heartbeat and the result, and nothing in the
runner read that as "stop".

### CR-254a (comp-ytdl-jobs-1) - a refusal an admin cannot clear - FIXED (companion/src/ccsync_companion/upgrade.py)

CR-237 narrowed `refusal()`'s self-clear from SAME-or-OLDER to SAME only, which
is right: a refusal produced by the downgrade floor is by construction about a
build at or below the running one, and retiring OLDER threw away the one
refusal REL-3 exists to surface. What it left behind was a record with exactly
one remaining retirement path - `_accept_offer` succeeding on a later offer -
and a dashboard that stops offering anything at all once the machine is running
the current build (`api._upgrade_info` returns None when `running ==
current["version"]`). So the abandoned rollback is permanent: the admin
publishes 0.9.65, every 0.9.71 companion refuses it at the floor and reports
`refused_version=0.9.65`, the admin gives up and makes 0.9.71 current again,
and `[ REFUSING 0.9.65 ]` plus the `upgrade_refused` alert stay lit on the whole
fleet until each tray is restarted - while the alert's own action text tells
the admin to publish a build that computer will accept, which is what they just
did. The fix is the second way out the fix's own comment asked for, and it is
not an age bound: `note_report_response` clears the record when a well-formed
reply carries NO offer at all. Nothing true is lost, because a rollback that is
still current is re-offered and re-refused on the very next report. An
`upgrade` key that could not be parsed is deliberately not this case.

### CR-254b (comp-ytdl-jobs-5) - the SAME-vs-OLDER compare had no test - FIXED (companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py)

The one CR-237 fix in this territory that changed fleet-visible behaviour was
the one with no regression test: nothing in the 827 companion tests called
`UpgradeManager.refusal()` at all, so a revert to the tolerant compare would
have stayed green, and `refusal()`'s docstring still described only the
running-version case. Two tests now pin both directions, and the docstring
names both ways a refusal retires.

### CR-254c (comp-ytdl-jobs-2) - the sidecar cause and counter never reached a YouTube machine's report - FIXED (companion/src/ccsync_companion/sidecar_tools.py)

CR-237 attached `cause` and `consecutive_failures` to `ensure_ffmpeg_pair`'s
returns. `ensure()` - the wrapper `ytdlp_manager._loop` uses on every machine
where `youtube_download` is ON - has two failure returns of its own, and
neither was updated. The `no_room` return (no writable tools dir, or a full
disk: the two commonest failures there) carried no `failed`, no `cause` and no
`consecutive_failures` at all, and the deno-only `failed` return read the
counter after `ensure_ffmpeg_pair` had already reset it to 0. Both published
`{action: failed, consecutive_failures: 0, cause: None}`, which makes
`sidecar_warning_line` return "" for ever and tells `sync_guard.ytdlp.sidecar`
nothing - so a machine that has quietly stopped being offered `proxy-480p` /
`audio-extract` / `peaks` had no sentence anywhere a person looks, which is the
state the original finding was raised about. Both returns now carry the three
keys, the deno no-room arm records its own cause, and the pass accounting is
counted ONCE whichever entry point ran (`pair_failed` is "the pair already took
this pass"), so the two-pass warning cannot fire on pass one. The streak itself
stays the pair's: an ffmpeg that installs cleanly resets it every pass, which
is what keeps the "cannot make proxies" line off a machine whose only missing
tool is the JS runtime.

### CR-254d (comp-ytdl-jobs-4) - the drain liveness check judged the wrong thread, and first - FIXED (companion/src/ccsync_companion/jobs_media.py)

CR-237's `_read_pcm` fix joined both drain threads and failed the job if EITHER
was still alive. The stderr drain carries the last 200 characters of ffmpeg's
log and never a sample of audio, so a stderr pipe an inherited handle is
holding open cannot truncate the peaks - but it failed a complete job, which
the fleet then retried on another machine, and so on. Worse, the new `raise`
sat AHEAD of `if failure:`, so a genuine read error on a stalled share (which
leaves the thread alive too) had its own message - the only diagnosis anyone
had - replaced by the generic "the decode output could not be read to the end".
Now only the PCM thread's liveness is a verdict, the recorded failure is raised
first, and the stderr join gets a token `STDERR_JOIN_SECONDS` (2 s) instead of
a second full `DRAIN_JOIN_SECONDS`, which was a minute in series on a job that
was already finished. CR-237's own property - truncated peaks published under
the final name are worse than no peaks - is kept and re-pinned; its test could
not tell the two streams apart because it stalled both with the same stub.

### CR-254e (comp-ytdl-jobs-6) - 16 stale local stops crowded out the fleet's cancel - FIXED (companion/src/ccsync_companion/jobs_runner.py)

CR-237 kept the person at this machine's [ STOP ] in `_local_cancel`, out of
reach of a report reply that replaces `_cancel` wholesale. Ids only leave that
set in `_post_result`, so a job that ends without a posted result (the process
killed between the kill and the post, `stop()` racing `_execute`) leaves its id
there for the life of the tray - and the merge put every local id in FRONT of
the admin's list before capping the result at sixteen. Sixteen stale local
stops therefore truncated away an admin's `commands.jobs.cancel` for the job
actually running, and the dashboard's [ CANCEL ] did nothing on that machine,
silently. `_local_cancel` is now a bounded list (newest last,
`LOCAL_CANCEL_MAX` = 16, one helper `_note_local_cancel`) and the admin's stops
are merged FIRST, so whichever end is truncated it is never the fleet's.

### CR-254f (wire-5, dash-api-4) - a 403 on the heartbeat is an account bar, not a blip - FIXED (companion/src/ccsync_companion/jobs_runner.py)

dash-api-6 put the suspended-account gate on `_require_fleet_caller`, which
gates claim, heartbeat and result alike. The runner treated ONLY 410 as "this
job is not ours"; a 403 fell through as "keep going", so a machine whose owner
was suspended mid-transcode ran the job to the end, wrote its output into the
shared vault (SMB, which no gate reaches), and then had its result refused -
while the lease it could not renew had already expired and sent the same job to
a second machine. 401 and 403 on the heartbeat now stop the job the way 410
does, and the same statuses on the claim and on the result are recorded rather
than swallowed. The editor is told: `status()["gate"]["reason"]` carries "This
computer's fleet work is not being accepted right now: ask the studio to check
this account." until a fleet call gets through again, and `credential_refused`
rides the same dict for the diagnostics bundle. The result still goes out with
its own `retryable` verdict - the WORK is retryable on another machine, and
only this machine's account is barred.

### CR-254g (res-companion-4, companion half) - "this machine cannot keep its crash-loop counter" left the machine - FIXED (companion/src/ccsync_companion/upgrade.py)

The supervisor half was closed by CR-237 (`--prior` means the relaunch ceiling
no longer needs a writable state dir); the companion half was a WARNING in the
log of the machine with the full disk and an accessor, `write_failures()`, with
no caller anywhere. A machine that cannot write `~/.ccsync/state` has a
crash-loop counter that reads "first start" on every start, so APP-5's revert
can never fire and a build that will not stay up keeps coming back - and the
dashboard sees a machine reporting normally with no hint of why.
`sync_guard.upgrade.state_write_failures` now carries the count, always sent
and normally zero, exactly as `lane_guard._PersistedLatch._persist_report`'s
`persist_failed` does for the lane latches.

### Verification
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_reply_with_no_offer_retires_the_standing_refusal -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_reply_that_still_carries_the_refused_offer_keeps_the_refusal -> guards the other direction
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_an_unreadable_reply_does_not_retire_the_refusal -> guards the parse-failure case
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_refusal_of_an_older_build_survives_and_the_running_one_does_not -> fails at f1eeb42 only if the CR-237 compare is reverted; it is the test that was missing
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_the_swallowed_state_writes_ride_the_upgrade_report -> fails at f1eeb42 (KeyError), passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_full_disk_on_a_youtube_machine_reaches_the_editor -> fails at f1eeb42 (KeyError 'failed'), passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_deno_only_failure_reports_the_streak_it_is_on -> fails at f1eeb42 (0 failures, no cause), passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_one_pass_is_counted_once_whichever_entry_point_ran -> guards the double-count the fix could have introduced
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_stalled_stderr_drain_does_not_fail_a_complete_decode -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_real_read_error_keeps_its_own_message -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_stalled_pcm_drain_still_fails_the_job -> CR-237's property, kept
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_an_admin_cancel_is_never_the_entry_that_is_truncated -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_the_newest_local_stop_is_the_one_that_is_kept -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_403_on_the_heartbeat_stops_the_job -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_410_on_the_heartbeat_is_still_not_a_credential_problem -> guards the wording split
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_500_on_the_heartbeat_is_still_a_blip -> guards CR-31's shape
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_refused_result_is_recorded_rather_than_swallowed -> fails at f1eeb42, passes now
- companion/tests/test_upgrade.py::test_upgrade_report_is_always_a_full_shape -> edited for the new always-sent key

Also run (unchanged, all green): test_bug_hunt_2026_09_11_comp_ytdl_jobs.py,
test_jobs_runner.py, test_jobs_media.py, test_sidecar_tools.py,
test_ytdlp_manager.py, test_jobs_phase4.py, test_jobs_resilience.py,
test_jobs_runner_visibility.py, test_upgrade_floor_guards.py - 473 passed,
plus the 17 new ones.

### OWED TO ANOTHER TERRITORY
- dash-api: `dashboard/src/ccsync_dashboard/api.py`: `UpgradeIn`: declare
  `state_write_failures: int | None = Field(default=None, ge=0)` (and store it
  beside the other upgrade fields if dash-db adds a column). Without it
  `undeclared_report_sections` names `sync_guard.upgrade.state_write_failures`
  in the daily log line and on the SYS-3 banner - a true warning about a key
  nothing reads, but noise until it is declared. DEPLOY THE DASHBOARD FIRST;
  the companion side is harmless either way (an older dashboard ignores it,
  `_BoundedSectionIn` is `extra="ignore"`).
- dash-collector-alerts: `dashboard/src/ccsync_dashboard/alerts.py`: one
  `ALERT_KINDS` row reading the stored `ytdlp.sidecar` block (action ==
  `failed` and `consecutive_failures >= 2`), naming the machine and the cause
  (comp-ytdl-jobs-3, regression-11). The companion half is built and, with
  CR-254c, now populated on the `ensure()` path too; nothing on the dashboard
  reads it, so the admin still cannot tell "never set up" from "cannot reach
  GitHub". Dashboard-only change, no ordering constraint.
- dash-collector-alerts: `alerts.py` `_check_upgrade_refused`: with CR-254a the
  refusal retires on the next offer-free report, so the row now clears by
  itself on a fleet running 0.9.72+. A staleness bound on that row would also
  cover the machines still on 0.9.65..0.9.71, where the refusal is still
  sticky for the life of the process. Dashboard-only.
- dash-api: `api.py` `_require_fleet_caller`: answering 410 rather than 403 on
  `/jobs/{id}/heartbeat` and `/jobs/{id}/result` when the refusal is an account
  bar would also reach the companions already in the field (0.9.65..0.9.71),
  which stop only for 410. CR-254f fixes 0.9.72 onwards; the dashboard half is
  what covers the fleet today. Either side may deploy first.
- comp-ui: `companion/src/ccsync_companion/supervisor.py`: regression-12
  (res-companion-3, claimed fixed with no fix in the tree) is listed under
  comp-ui and `supervisor.py` is not in this territory's file list - untouched
  here.

### Owner decisions
- A reply with no offer clears the refusal; an age bound was not added. An age
  bound alone would have kept a truly stuck machine's chip lit for a day or a
  week after the cause was gone, and would still have needed a number nobody
  can pick. If you would rather have both, the hook is `_clear_refusal`.
- A 403 on the RESULT does not change the job's `retryable` verdict. The work
  itself is fine and another machine should do it; only this machine's account
  is barred. The alternative (marking it not retryable) would strand a job on a
  403 that turned out to be a dashboard misconfiguration.
- The credential-refused sentence is appended to the jobs gate reason, which
  Settings and the tray already render, rather than a new tray line: no tray.py
  change (not this territory) and nothing new to plumb.

### Hand-off wave

Two OWED lines routed back to this territory: ytdl-web's third machine door,
and the half of CR-254f that wave 1's ledger claimed was already rendered.

#### CR-254h (ytdl-web-3, hand-off) - the fleet calls named this computer in the body only - FIXED (companion/src/ccsync_companion/ytdl_executor.py)

`routes_fleet._machine_of` reads three doors on purpose - a body field on the
two POSTs, a query parameter on the manifest GET, and `X-CCSync-Machine` as the
shape-independent fallback - and the companion filled only the first two. The
header is the one that does not depend on the call's shape: a route that grows
a second POST, or a body something between the two ends rewrites, loses the id
and the lease silently goes back to answering per EDITOR, which is exactly the
stale-laptop bug ytdl-web-3 was raised for (a machine that lost the job to its
owner's desktop and woke up re-extending the other computer's lease). `_headers`
now carries it on every fleet call - claim, heartbeat, manifest and clip status
alike. Optional both ways: an older server sees an unknown header, and
`_machine_of` prefers the body/query spelling, so the two can never disagree.
An id that cannot be an HTTP header is not sent at all (`_header_safe`):
machine.json is a plain file an editor can replace by hand, `http.client` raises
on a newline or a non-ASCII value, and a claim that dies in the transport is
strictly worse than one the server answers per editor.

#### CR-254i (wire-5, surfacing half) - "Taking fleet work" while nothing this machine does is accepted - FIXED (companion/src/ccsync_companion/jobs_runner.py)

CR-254f put the refusal sentence on `status()["gate"]["reason"]` and the ledger
said Settings and the tray already render it. Settings does - but only when the
gate is CLOSED: `settings_window._jobs_section` prints "Taking fleet work" and
drops the reason when `taking_work` is true, and this runner's resting state is
`STATE_NOTHING_OFFERED`, whose verdict is true. So in the commonest case - a
suspended account, nothing running - the one sentence a person at that machine
could act on was rendered nowhere at all. A door that answers 401/403 to claim,
heartbeat and result alike is not a machine that is taking work, so the verdict
now says so: `taking_work` is false while a refusal stands, an already-closed
state keeps its own words and gains the note (somebody at the keyboard is still
why nothing is running), and an open one is replaced by it, because "ready for
fleet work" beside "not being accepted" is two answers to one question. It
clears on the next fleet call that gets through, so an un-suspended account does
not need a tray restart. `app.jobs_gate()` rides the same verdict, so
`GET /api/v1/jobs/<id>/why` stops printing a machine as willing when its own
credential is being refused.

Also confirmed, not changed: `_heartbeat` already treats 401/403 as terminal for
the current job (`CREDENTIAL_REFUSED_STATUSES`), both callers terminate the
child on a false answer rather than killing it from the beat thread, and
`_post_result` records a refused result instead of swallowing it. Tests for all
three are in wave 1's section above.

### Verification (hand-off wave)
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_every_ytdl_fleet_call_carries_the_machine_header -> fails before the fix (no header), passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_machine_with_no_id_sends_no_machine_header -> guards the optional-on-the-wire property
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_machine_id_that_is_not_header_safe_is_left_out -> guards the transport raise the fix could have introduced
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_refused_credential_closes_the_gate_it_contradicts -> fails before the fix (taking_work True), passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_call_that_gets_through_reopens_the_gate -> fails before the fix, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py::test_a_closed_gate_keeps_its_own_reason_and_gains_the_note -> guards the wording split

Run green: test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py (23), plus
test_bug_hunt_2026_09_11_comp_ytdl_jobs.py, test_ytdl_executor.py,
test_jobs_runner.py, test_jobs_runner_visibility.py, test_jobs_phase4.py,
test_jobs_resilience.py, test_ytdl_server.py, test_ytdl_feature_gate.py - 392
passed. py_compile on both touched source files.

### OWED TO ANOTHER TERRITORY (hand-off wave)
- comp-ui (OPTIONAL, low): `companion/src/ccsync_companion/tray.py` renders
  only `jobs_forced_line`, never the jobs gate reason, so the credential
  refusal reaches the editor through Settings -> JOBS and not the tray menu. A
  one-line `jobs_credential_line(snap["jobs_status"])` beside it, shown only
  while `credential_refused` is set, would put it where an editor looks first.
  Companion-only, no ordering constraint.
- ytdl-web: nothing. `routes_fleet` already accepts `X-CCSync-Machine` on the
  heartbeat, the manifest and the status post; either side may deploy first.

### Owner decisions (hand-off wave)
- The header goes on EVERY ytdl fleet call, not only the heartbeat the OWED
  line named. One header on one call would have left the same gap on the next
  route that grows a body, and the server prefers the body/query spelling where
  it has one, so nothing changes for a call that already carried the id.
- A refused credential closes the jobs gate rather than only annotating it.
  The alternative (leave `taking_work` true and teach Settings to print the
  reason anyway) needs a settings_window.py change, which is comp-ui's, and
  would still report this machine as willing to `/jobs/<id>/why`.
