# comp-ytdl-jobs - companion: YouTube downloads, fleet jobs, sidecar tools, upgrades

Files read (with approximate coverage): the full `git diff 40f931a..HEAD` for
`companion/src/ccsync_companion/{jobs_media,jobs_runner,sidecar_tools,upgrade,ytdl_executor,ytdlp_manager}.py`
and `companion/tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py` (100%), then
`jobs_runner.py` (~85%: `note_report_reply`, `stop_current`, `_gate`, `tick`,
`_cancel_requested`, `_post_result`, `_run_child`'s stop wiring),
`sidecar_tools.py` (~85%: `install_tool`, `_note_cause/_note_pass`,
`ensure_ffmpeg_pair`, `ensure`), `ytdlp_manager.py` (~45%: `status_report`,
`sidecar_report`, `sidecar_warning_line`, `status()`, `_publish_sidecar`, the
sidecar loop), `upgrade.py` (~50%: `_write_json`, `note_version_start`,
`_accept_offer`, `_note_refusal`, `refusal`, `note_report_response`,
`upgrade_report`), `jobs_media._read_pcm`/`_kill` (100%), `ytdl_executor.py`
(~30%: `FleetClient`, `_this_machine_id`, claim/heartbeat/manifest/clip_status),
plus the other sides I had to compare against: `ytdl/web/ytdlweb/routes_fleet.py`
(`_machine_of`, `_leaseholder_or_410`, claim/heartbeat/manifest/clip_status),
`ytdl/web/ytdlweb/db.py` (`lease_held_by`, `is_leaseholder`, `claim_download`,
`heartbeat_download`), `dashboard/src/ccsync_dashboard/api.py`
(`_upgrade_info`, `_store_upgrade_refusal`, `_store_ytdlp_state`, `YtdlpIn` /
`YtdlpSidecarIn` / `_BoundedSectionIn`, and the 40f931a version of the last),
`dashboard/src/ccsync_dashboard/alerts.py` (`_check_upgrade_refused`, grep for
sidecar), `companion/src/ccsync_companion/{tray.py:1405-1460,machine.py}` (the
two seams that feed my files).

Tests run:
`companion\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py tests/test_jobs_runner.py tests/test_jobs_media.py tests/test_sidecar_tools.py tests/test_upgrade.py tests/test_ytdlp_manager.py tests/test_jobs_phase4.py tests/test_jobs_resilience.py tests/test_jobs_runner_visibility.py -q`
-> 469 passed.
`... -m pytest tests/test_ytdl_executor.py tests/test_ytdl_server.py tests/test_ytdl_cookies.py tests/test_youtube_import.py tests/test_upgrade_floor_guards.py -q`
-> 358 passed.
Two ad-hoc snippets from the companion venv (quoted in the findings below).

## Findings

### comp-ytdl-jobs-1 - the refusal is now sticky FOR EVER: a rollback the admin abandons leaves every machine permanently alarmed, and nothing can clear it
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/upgrade.py:1494-1520` (`refusal`), with
  `upgrade.py:1525-1560` (`note_report_response`) and the other side at
  `dashboard/src/ccsync_dashboard/api.py:5666` (`_upgrade_info`: `running ==
  current["version"]` -> no offer) and `alerts.py:2440-2469`
  (`_check_upgrade_refused`).
- What: CR-237's fix for last hunt's comp-ytdl-jobs-1 narrowed the self-clear
  from `SAME or OLDER` to `SAME` only. That closes the reported bug, but it
  leaves `last_refusal` with only ONE remaining retirement path -
  `_accept_offer` succeeding on a later offer - and the dashboard stops making
  offers entirely once the machine is running the current build. The fix's own
  comment says "If an old refusal should ever self-retire, retire it on AGE",
  and no age retirement was written.
- Failure scenario: admin republishes 0.9.65 as a rollback; every 0.9.71
  companion refuses it at the downgrade floor and reports
  `refused_version=0.9.65` (this is the fix working). The admin gives up and
  makes 0.9.71 current again. `_upgrade_info` now returns None for every
  machine (running == current), so `_accept_offer` is never called again,
  `refusal()` keeps returning the stale record on every report,
  `_store_upgrade_refusal` keeps latching it, and `[ REFUSING 0.9.65 ]` plus the
  `upgrade_refused` alert stay lit on the whole fleet until each companion is
  restarted - while the alert's own action text says "publish a build that
  computer will accept", which the admin has already done. The dashboard's
  latch cannot help: the companion never spells "I am not refusing anything now".
- Evidence: from the companion venv -
  `m._note_refusal('0.9.65','below the downgrade floor')`, then five
  `m.note_report_response({'ok': True})` (a well-formed reply with no `upgrade`
  key, which is what a fleet on the current build receives) ->
  `m.refusal()` still returns the record and
  `upgrade_report({},1,m.refusal())` still carries
  `refused_version='0.9.65'`. Read `_upgrade_info` to confirm no offer is made
  when `running == current["version"]`.
- Ledger: new (introduced by the CR-237 fix for `bug-hunt-2026-09-11`
  comp-ytdl-jobs-1; related to REL-3)
- Suggested fix: clear `last_refusal` in `note_report_response` when a
  well-formed reply carries NO offer (nothing is being refused right now - a
  still-current refused build is re-offered and re-noted on every report, so
  nothing true is lost), and/or retire on age as the comment intends.

### comp-ytdl-jobs-2 - the sidecar cause/counter never reaches the report on a YouTube-enabled machine's two commonest failures, so the new tray line can never appear there
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sidecar_tools.py:585-604` (`ensure`: the
  `no_room` return, and the deno-only `failed` return), against
  `sidecar_tools.py:466-500` (`ensure_ffmpeg_pair`, which is the only place
  `_note_pass` is called) and `ytdlp_manager.py:1238-1253` (`_loop` calls
  `ensure()` when the downloader is ON and `ensure_ffmpeg_pair()` when it is
  off) / `ytdlp_manager.sidecar_warning_line` (needs
  `consecutive_failures >= 2`).
- What: CR-237's comp-ytdl-jobs-3 fix attaches `cause` and
  `consecutive_failures` to the dicts returned by `ensure_ffmpeg_pair`, but
  `ensure()` - the wrapper the sidecar thread uses on every machine where
  `youtube_download` is on - has two returns that were not updated. The
  `no_room` return carries no `failed`, no `cause` and no
  `consecutive_failures` at all; the deno-only `failed` return reports
  `consecutive_failures()` after `ensure_ffmpeg_pair` has already called
  `_note_pass(False)` and reset the global to 0.
- Failure scenario: an editor's machine with the downloader on and a full disk
  (or no writable tools dir) fails the daily pass for a week. The log does warn
  from pass two (the counter itself is maintained inside
  `ensure_ffmpeg_pair`), but `_publish_sidecar` stores
  `{action: failed, consecutive_failures: 0, cause: None}`, so
  `sidecar_warning_line` returns "" for ever and `sync_guard.ytdlp.sidecar`
  tells the dashboard nothing. The machine quietly stops being offered
  `proxy-480p` / `audio-extract` / `peaks` with no sentence anywhere a person
  looks - which is exactly the state the finding was raised about.
- Evidence: from the companion venv, with `ensure_tools_dir` stubbed to None and
  `youtube_enabled` true, three `ensure({})` passes ->
  log: "ffmpeg, ffprobe could not be installed on 3 consecutive passes";
  returned dict: `{'ok': False, 'action': 'failed', 'message': 'sidecar tools
  could not be installed (tools dir or free space) ...'}`;
  `sidecar_tools.consecutive_failures()` -> 3;
  `sidecar_warning_line({'sidecar': sidecar_report(st)})` -> `''`.
- Ledger: CR-237 does not fix `bug-hunt-2026-09-11` comp-ytdl-jobs-3 on the
  `ensure()` path
- Suggested fix: give `ensure()`'s `no_room` and `failed` returns the same
  `failed` / `cause` / `consecutive_failures` keys, and call `_note_pass(True,
  failed)` there (or move the pass accounting to the single point where the
  loop publishes a status) so one pass is counted once whichever entry point ran.

### comp-ytdl-jobs-3 - the new `sync_guard.ytdlp.sidecar` block is stored by the dashboard and read by nobody, so the admin half of the finding is still open
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/ytdlp_manager.py:392-421` (`sidecar_report`)
  -> `dashboard/src/ccsync_dashboard/api.py:7397-7411` (`YtdlpSidecarIn`) ->
  `api.py:7801-7832` (`_store_ytdlp_state`, a meta blob) and then nothing:
  `grep -rn sidecar dashboard/src/ccsync_dashboard/alerts.py
  dashboard/src/ccsync_dashboard/ui.py dashboard/templates/*.html` returns only
  the unrelated PO-token and Tailscale sidecars.
- What: both sides of the wire were built (good: an older 0.7.34..0.7.42
  dashboard has `extra="ignore"` on `_BoundedSectionIn`, checked at 40f931a, so
  the new key is dropped and never 422s), and the editor gets a tray/Settings
  line. But the hunter's stated consequence was the ADMIN one - "`GET
  /jobs/{id}/why` says `no_capable_machine`, with no way to tell why" - and no
  alert kind, notice or grid chip reads the stored verdict.
- Failure scenario: the Mac with no CA bundle reports
  `sidecar.cause="certificate verify failed"` every 30 s for a month. The blob
  sits in `meta` under `ytdlp:<editor>/<machine>`; PROBLEMS THE SERVER FOUND
  says nothing, and the admin still cannot tell "never set up" from "cannot
  reach GitHub" without asking that editor to open their tray.
- Evidence: the greps above; `alerts.ALERT_KINDS` has `ytdlp_stale` and
  `ytdlp_failed` (CYT-7's pair) and no sidecar kind.
- Ledger: CR-237 partially fixes `bug-hunt-2026-09-11` comp-ytdl-jobs-3 (editor
  half done, fleet half not)
- Suggested fix: one registry row in `alerts.ALERT_KINDS` reading the stored
  `ytdlp.sidecar` (action == failed and `consecutive_failures >= 2`), naming
  the machine and the cause - adding a check is adding a row, per CLAUDE.md.

### comp-ytdl-jobs-4 - the new drain-liveness check fires on stderr too, and it runs BEFORE the real-failure check, so it can replace ffmpeg's own error with a generic one
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/jobs_media.py:676-692` (`_read_pcm`)
- What: the fix joins BOTH drain threads and then fails the job if EITHER is
  still alive, with a message about the decode output. The stderr drain carries
  no audio; a stderr thread that has not reached EOF cannot truncate the peaks.
  Worse, the new `raise` sits ahead of `if failure:`, so when the PCM drain
  recorded a genuine read error AND a thread is still alive, the specific
  message (`the decode failed: ...`) is thrown away in favour of "the decode
  output could not be read to the end". Both joins also still cost
  `DRAIN_JOIN_SECONDS` each in series (60 s worst case), unchanged.
- Failure scenario: a job whose stderr pipe is held open by an inherited handle
  completes with a full, correct PCM buffer and is now failed and retried on
  another machine - a fleet-wide retry loop for a job that was fine. Rarer, but
  the diagnosis path matters more: a real decode failure on a stalled share is
  now reported to the editor and the dashboard as the generic sentence.
- Evidence: read `_read_pcm` at HEAD; the regression test
  (`test_a_pcm_drain_that_never_reaches_eof_fails_the_job`) stalls BOTH streams
  with the same `_StuckStream`, so it cannot tell the two cases apart and would
  pass either way.
- Ledger: new (follows CR-237's fix for `bug-hunt-2026-09-11` comp-ytdl-jobs-4)
- Suggested fix: test only the PCM drain thread for liveness, and move the test
  below `if failure:` so a recorded read error keeps its own message.

### comp-ytdl-jobs-5 - the one fix in this territory with no regression test is the one that changed fleet-visible behaviour
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/tests/test_bug_hunt_2026_09_11_comp_ytdl_jobs.py:1-20`
  (the file's own docstring lists 2, 3, 4, 5, ytdl-web-3 and res-companion-4)
  against `companion/src/ccsync_companion/upgrade.py:1505` (the
  comp-ytdl-jobs-1 hunk).
- What: the header claims "Every test here fails at 40f931a and passes after the
  fix beside it", and comp-ytdl-jobs-1 has no test at all - neither the new file
  nor `test_upgrade.py` / `test_upgrade_floor_guards.py` asserts that a refusal
  of an OLDER version survives `refusal()` (grep for `last_refusal` /
  `refusal()` in `companion/tests` finds nothing pinning the SAME-vs-OLDER
  rule). Nothing would catch the fix being reverted, and nothing pinned the
  state it created (finding 1 above).
- Failure scenario: the next person reading `refusal()`'s docstring - which
  still says only "a machine that is now RUNNING the build it refused" - reverts
  to the tolerant compare and the suite stays green.
- Evidence: read the test file in full; `grep -rn "last_refusal|\.refusal()"
  companion/tests` finds only `test_app.py:7387-7503`, which SET
  `upgrade.last_refusal` directly and exercise the auto-update back-off - none
  of them calls `UpgradeManager.refusal()`, so the SAME-vs-OLDER compare is
  unasserted anywhere in the 827 tests I ran.
- Ledger: new
- Suggested fix: one test asserting `refusal()` keeps a record for a version
  BELOW the running one and drops it for the running one - and, with finding 1,
  one asserting an offer-free reply clears it.

### comp-ytdl-jobs-6 - `_local_cancel` has no ceiling and is merged ahead of the admin's list, so 16 stale local stops would crowd out a fleet cancel
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/jobs_runner.py:275, 341-346, 465-469, 772-775`
- What: `_cancel` keeps its 16-entry cap, but the merge puts every id in
  `_local_cancel` first; ids only leave that set in `_post_result`. A job that
  ends without a posted result (the process killed between the kill and the
  post, `stop()` racing `_execute`) leaves its id there for the life of the
  process.
- Failure scenario: on a long-running tray where the editor has stopped jobs
  repeatedly and some ended without a result, `sorted(self._local_cancel)`
  fills the sixteen slots and an admin's `commands.jobs.cancel` for the job
  actually running is truncated away - the fleet cancel button then does
  nothing on that machine, silently.
- Evidence: read the merge; `_local_cancel` is a `set` with no bound and no
  pruning other than `_post_result`. I did not construct the 16-stale-id state,
  hence PLAUSIBLE.
- Ledger: new (introduced by the CR-237 fix for comp-ytdl-jobs-2)
- Suggested fix: bound `_local_cancel` (drop the oldest, or prune any id that is
  neither the current job nor in the last N finished), and merge the admin's
  stops FIRST so a fleet cancel can never be the entry that is truncated.

## Coverage note
I verified the ytdl-web-3 wire on both sides in full (`_machine_of`,
`lease_held_by`, `is_leaseholder`, `claim_download`, `heartbeat_download`): it
is correctly optional in both directions, `''` is normalised to NULL at the
claim so the two tolerant checks agree, and the 0.9.65/0.9.70 companions in the
field (which claim with `machine_id` and heartbeat without) keep the per-editor
answer rather than getting 410s. comp-app-5's new `machine.machine_id()`
returning `""` for an unreadable-but-present file also composes safely with
every fleet call in this territory. Not reached: `ytdl_attestation.py`,
`ytdl_browser_login.py`, `ytdl_cookies.py`, `ytdl_server.py`, `job_paths.py`,
`release_pubkey.py`, `ed25519.py` and `youtube_import.py` beyond a grep (all
unchanged since 40f931a, and covered by last hunt), and the whisper half of
`jobs_runner._execute`. The suite does not cover: any `ensure()` (as opposed to
`ensure_ffmpeg_pair()`) failure path, the refusal compare against an older
version, or a stderr-only stalled drain.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/alerts.py:2440` (`_check_upgrade_refused`): the
  action text tells the admin to publish a build the machine will accept, which
  is precisely the move that cannot clear the state described in finding 1;
  whoever owns dash-collector-alerts may want a staleness bound on that row.
