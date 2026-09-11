# comp-ytdl-jobs - companion: YouTube downloads, fleet jobs, upgrades, reporting

Files read (with approximate coverage):
`companion/src/ccsync_companion/upgrade.py` (~70%, all of the diff since 097f5a3 plus
parse_version/compare_to_running/same_origin/verify/floor/UpgradeManager),
`jobs_runner.py` (~90%), `jobs_media.py` (~60%, all of the diff plus the partial/publish
discipline), `job_paths.py` (100%), `release_pubkey.py` (100%), `ed25519.py` (~60%,
verify path), `sidecar_tools.py` (~80%), `ytdlp_manager.py` (~35%, status_report + the
sidecar loop), `ytdl_executor.py` (~35%, all of the diff plus the file-naming/litter
rules, `_GUARD`/`start`/`_release`), `ytdl_cookies.py` (~70%), `ytdl_browser_login.py`
(~40%, the diff), `youtube_import.py` (~25%, the diff), `reporter.py` (~30%, payload
build), `capabilities.py` (~50%, cross-check), plus the dashboard sides I had to compare
against: `dashboard/src/ccsync_dashboard/api.py` (report reply + the four jobs routes +
`UpgradeIn`/`CapabilitiesIn`/`JobsGateIn`), `jobs.py` (policy/offers), `db.py`
(claim/heartbeat/cancel/version_tuple), `alerts.py` (grep only).

Tests run:
`companion\.venv\Scripts\python.exe -m pytest tests/test_jobs_media.py tests/test_jobs_phase4.py tests/test_jobs_resilience.py tests/test_jobs_runner.py tests/test_jobs_runner_visibility.py tests/test_ffmpeg_tools.py tests/test_sidecar_tools.py tests/test_upgrade.py tests/test_upgrade_floor_guards.py -q`
-> 421 passed.
`... -m pytest tests/test_ytdl_executor.py tests/test_ytdl_cookies.py tests/test_ytdl_browser_login.py tests/test_ytdl_server.py tests/test_ytdlp_manager.py tests/test_ytdl_feature_gate.py tests/test_ytdl_root_guard.py tests/test_youtube_import.py tests/test_reporter.py tests/test_reporter_health.py tests/test_self_upgrade_handoff.py -q`
-> 668 passed.

## Findings

### comp-ytdl-jobs-1 - `refusal()` throws away every refusal of an OLDER build, which is exactly the downgrade-floor case REL-3 was written for
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/upgrade.py:1464-1483` (`UpgradeManager.refusal`),
  read by `upgrade_report(..., refusal=...)` at `upgrade.py:456`; the dashboard side is
  `dashboard/src/ccsync_dashboard/api.py:6935` (`UpgradeIn.refused_version/_reason/_at`).
- What: `refusal()` self-clears the standing refusal when
  `compare_to_running(record["version"])` is `VERSION_SAME` **or `VERSION_OLDER`**. The
  comment justifies only the SAME case ("a machine that is now RUNNING the build it
  refused"). But a refusal produced by the downgrade floor, or by a deliberate rollback
  publish, is BY DEFINITION about a version older than the running one, so it is
  discarded on the very first read and `sync_guard.upgrade.refused_*` goes out as null.
- Failure scenario: machine runs 0.9.70 with a persisted floor of 0.9.70. An admin
  republishes 0.9.65 as a rollback (a first-class operation, per CLAUDE.md). Every
  companion refuses it at receipt with "v0.9.65 is below the downgrade floor v0.9.70 ...
  delete upgrade_floor.json on this machine". `_note_refusal` stores it, `refusal()`
  returns None, the report carries nulls, `api._store_upgrade_refusal` writes nothing,
  the `upgrade_refused` alert never fires and Packages renders the whole fleet as
  "pending" - the exact indistinguishability REL-3 exists to remove. Same for a Mac
  handed an older-versioned Windows record (the new kind/platform refusal at
  `upgrade.py:1385-1404`) whenever that record's version is at or below the running one.
- Evidence: ran from the companion venv against the real module (running VERSION 0.9.70):
  `m._note_refusal("0.9.65", "...below the downgrade floor...")` -> `m.last_refusal` is
  stored, `m.refusal()` -> `None`; the same call with `"0.10.0"` returns the record. The
  ledger (`KNOWN_BUGS.md:11773-11784`) names "a build below this machine's downgrade
  floor" as REL-3's first example and states the clear rule as "once the machine is
  running the refused version" - SAME only.
- Ledger: regression of CR / REL-3 (recorded FIXED; the companion half does not hold for
  its headline case)
- Suggested fix: clear only on `VERSION_SAME` (and on the next accepted offer, which
  `_clear_refusal` already does). If an older refused version should ever self-retire,
  retire it on age, not on ordering.

### comp-ytdl-jobs-2 - a report reply wipes a locally requested job stop, so the tray's [ STOP ] can silently do nothing
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/jobs_runner.py:330` (`note_report_reply`:
  `self._cancel = stops[:16]`) against `jobs_runner.py:427-450` (`stop_current`, which
  appends the id to that same list); dashboard side
  `dashboard/src/ccsync_dashboard/db.py:9618` (`pending_job_cancels`) and
  `api.py:8958-9000` (the `commands.jobs` block is omitted entirely when it is empty).
- What: `stop_current()` deliberately reuses the admin's `_cancel` list, but
  `note_report_reply` REPLACES that list wholesale with whatever the dashboard sent.
  The dashboard is never told about a local stop (there is no release/cancel call - see
  `_post_result`'s docstring and `stop_current`'s), so `pending_job_cancels` can never
  contain that id, and the next report reply - including the very common reply that
  carries no `jobs` block at all, in which case `stops` is `[]` - erases it.
- Failure scenario: an editor clicks the tray's stop while a whisper job runs.
  `stop_current` returns True and logs "the person at this machine stopped job #N", so
  the tray reports success. `_run_child` only polls `_cancel_requested` once per
  `proc.wait(timeout=5)` slice, i.e. every ~5 s; the reporter interval is 5-60 s. If a
  report reply lands inside that 5 s window the id is gone, the child is never
  terminated, the heartbeat keeps renewing the lease, and the job runs to completion on
  a machine whose owner asked for it back. The same race applies to the media recipes
  (0.5 s poll, so a narrower window) and to `ytdl` is unaffected (different path).
- Evidence: read both sides. `note_report_reply` has no merge; `_cancel` has no other
  persistence; `api_report` builds `block` and only sets `result["commands"]["jobs"]`
  `if block`, so an idle fleet sends no `cancel` key and `stops` is `[]`.
  `test_jobs_runner_visibility.py` tests `stop_current` in isolation and never calls
  `note_report_reply` after it, so the suite cannot catch this.
- Ledger: new (the `stop_current` design note at `KNOWN_BUGS.md:12614` states the reuse
  but not this consequence)
- Suggested fix: keep locally requested ids in their own set that `note_report_reply`
  unions into `_cancel` rather than overwriting (prune an id once its result has been
  posted).

### comp-ytdl-jobs-3 - a sidecar ffmpeg install that keeps failing (the known macOS SSL CA problem) reaches nobody, and the machine just disappears from every media job kind
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sidecar_tools.py:316` (the only place the cause
  is recorded, `log.info`), `sidecar_tools.py:405-417` (the returned message drops the
  cause), `ytdlp_manager.py:1142-1151` (the result is logged at INFO when the downloader
  is on and **DEBUG when it is off** - the vendor-build default).
- What: `install_tool` swallows every download exception into one INFO line and returns
  False; `ensure_ffmpeg_pair` turns that into `{"action": "failed", "message": "could
  not install ffmpeg, ffprobe"}` with no cause attached; `_loop` logs that string and
  nothing else. Unlike yt-dlp - which got `ytdlp_manager.status_report` and the
  `ytdlp_stale`/`ytdlp_failed` alerts in CYT-7 - the ffmpeg/deno sidecar has no report
  field, no tray line and no alert kind (`grep ffmpeg dashboard/.../alerts.py` -> no
  hits). The only fleet-visible consequence is `capabilities.ffmpeg=false`, which makes
  the machine silently ineligible for `proxy-480p`, `audio-extract` and `peaks`
  (`jobs_runner.runnable_kinds`), i.e. it reads as "this machine was never set up"
  rather than "this machine cannot reach GitHub".
- Failure scenario: a Mac whose Python has no CA bundle (a live, recorded field problem -
  see MEMORY "macOS sidecar downloads fail on SSL CA verify") retries the download once a
  day forever. With `youtube_download` off (the vendor default) the failure line is at
  DEBUG, so at the shipped log level there is literally nothing; the admin sees a fleet
  where one machine is never offered media work and `GET /jobs/{id}/why` says
  `no_capable_machine`, with no way to tell why.
- Evidence: read `install_tool`, `ensure_ffmpeg_pair`, `ensure`, `ytdlp_manager._loop`;
  grepped `dashboard/src/ccsync_dashboard/alerts.py` for `ffmpeg` (no matches) and
  `companion` for any reporter field carrying the sidecar verdict (only `sync_guard.ytdlp`
  exists, and it is yt-dlp's status, not the sidecar's).
- Ledger: new (CYT-7 fixed exactly this shape for yt-dlp and left the sidecar behind)
- Suggested fix: carry the exception text into the returned `message`, log a repeated
  failure at WARNING regardless of the feature flag, and publish the verdict as
  `sync_guard.sidecar` on CYT-7's pattern so an alert kind can name the machine and the
  cause.

### comp-ytdl-jobs-4 - `_read_pcm` proceeds after its drain-join timeout, which is the silent truncation the code was rewritten to prevent
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/jobs_media.py:670-681`
- What: after the child exits, the two drain threads are joined with `timeout=30.0` and
  the code then reads `chunks` and returns, with no `thread.is_alive()` check. If the PCM
  drain has not reached EOF within 30 s the peaks are built from a partial buffer while
  the reader thread is still appending to the same list - exactly the "the tail of the
  audio is silently missing from the peaks" outcome the comment two lines above says the
  join exists to prevent, and the job reports success.
- Failure scenario: a slow/stalled share holding the read end open after the child exits
  (or a very large buffered tail) -> a `.peaks` file shorter than the audio, published
  under the final name by `_publish`, cached by Timeline Cards as current (its mtime
  beats the source's), so it is never remade.
- Evidence: read `_read_pcm`; the `timed_out`/`stopped` branch raises, but the normal-exit
  branch has no post-join liveness test.
- Ledger: new (follows bug-hunt-2026-09-03 comp-ytdl-jobs-4's rewrite)
- Suggested fix: after the join, `if any(t.is_alive() for t in threads): raise
  MediaJobError("the decode output could not be read to the end")`.

### comp-ytdl-jobs-5 - the gate sentence keeps a stale `_gate_note` on the four early-return states
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/jobs_runner.py:600-630` (`_gate`) and
  `jobs_runner.py:410-416` (`status()` appends `self._gate_note` to the sentence)
- What: `_gate_note` is set for `no_capability` and `local_work` and cleared at
  `jobs_runner.py:626` only on the path that gets that far. `STATE_DISABLED`,
  `STATE_NO_DASHBOARD`, `STATE_HALTED` and `STATE_RUNNING` all return before any
  assignment, so whatever note the previous tick left is still appended by `status()` and
  rides `capabilities.jobs_gate.detail` to the dashboard.
- Failure scenario: a machine indexing b-roll reports `local_work` with detail "Indexing
  b-roll"; the admin then halts the fleet. The next tick returns `STATE_HALTED` and the
  editor's tray/Settings reads "Your admin has stopped syncing for the whole fleet, so
  this computer is not taking work of any kind. Indexing b-roll" - two different
  explanations glued together, one of them no longer true.
- Evidence: read both functions; there is no other writer of `_gate_note`.
- Ledger: new (CMEDIA-12)
- Suggested fix: set `self._gate_note = ""` once at the top of `_gate()`.

## Coverage note
Not reached: `ffmpeg_tools.py` beyond the discovery helpers (unchanged since 097f5a3),
`ytdl_server.py` and `ytdl_attestation.py` in depth (both unchanged), the bulk of
`ytdl_executor.py`'s per-clip rung/retry machinery, `reporter.py`'s scheduling half, and
`youtube_import.py`'s Resolve-side filing. I did not exercise a live dashboard, so the
jobs claim/heartbeat/result wire formats were compared by reading both sides only
(`machine`, `capabilities`, `kinds`, `ids` vs `JobClaimIn`; `machine`/`progress` vs
`JobHeartbeatIn`; `machine`/`ok`/`retryable`/`error`/`result` vs `JobResultIn` - all
agree, and `JobClaimIn.machine_id` is declared but never sent and never read, which is
harmless). `idle_seconds`'s null-is-not-idle contract holds on both sides
(`capabilities._idle_seconds`, `jobs_runner._user_is_away`, `jobs.policy_refusal`).
Version comparison handles two-digit minors correctly on both sides
(`upgrade.parse_version` tuple compare, `db.version_tuple`). `job_paths.resolve`'s
absolute/`..` refusals and `release_pubkey`/`ed25519` verification read as correct.
The suites do not cover: a local stop racing a report reply (finding 2), a refusal of an
older build being reported (finding 1), or any sidecar download failure reaching a human.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/app.py:6998` (`_maybe_auto_update`): the auto-update
  arming/back-off lives here rather than in `upgrade.py`; the "never rolls backwards"
  rule is enforced by the caller, not by `UpgradeManager`, so it is only as good as
  `app.py`'s gate. Worth a look by whoever owns app.py.
- `dashboard/src/ccsync_dashboard/api.py:8993` (`_wants_idle_queue_depth`): a `+dirty`
  companion version parses to `()` and therefore never receives the queue depth. Correct
  by the stated rule, but it means a deliberate hotfix build loses the backoff signal.
