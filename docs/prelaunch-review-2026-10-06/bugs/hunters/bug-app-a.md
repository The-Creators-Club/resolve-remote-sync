# Pre-launch bug hunt, lens bug-app-a (2026-10-06)

Territory: `companion/src/ccsync_companion/app.py` lines 1-6100 (single-instance guard,
LaneWatchdog, file-move helpers, `CompanionApp.__init__`, `_on_report_response` fan-out,
`_build_lanes`, root guard pause/resume, popup plumbing, non-canonical relink, consolidate,
media-tree loop, readers). Followed the paths that this range hands off to (`_start_lanes`,
`_lanes_refusal`, `toggle_pause`, `on_signed_in`, `halt_all_sync`/`release_halt`,
`_apply_fleet_halt`, `_apply_pushed_update`/`_maybe_auto_update`, `_apply_file_moves`,
`_apply_resolve_undo`, `_apply_diagnostics_request`, `_show_licence_dialog`, `start()`), plus
`sequencer.start/pause/resume/stop/thread_died`, `lane_guard.HaltState`, `upgrade.apply`,
`reporter.post_once/_build_payload` and the dashboard's command assembly in `api.py`.
Working tree as it stands (uncommitted CR-356/CR-358 edits included). Read-only; no probes
were needed beyond reading, every CONFIRMED item is a traced code path.

Not covered: `shutdown()`, `run()` beyond the licence-watch start, `sync_guard()`,
`build_diagnostics()` sections, `removal_blockers`/`remove_project_from_machine` (lines >6100,
assumed to be another lens).

### bug-app-a-1 - Resume after a pause can leave the managed machine with no sequencer at all (sync silently dead until restart)

- Severity: high
- Confidence: CONFIRMED
- Where: app.py:10075-10127 (`toggle_pause`), app.py:6697-6721 (`_start_lanes` PAUSED gate), app.py:6896-6908 (`on_signed_in`), app.py:8150-8162 (`release_halt`), app.py:9147-9178 (`_apply_fleet_halt` release), sync/sequencer.py:695-705, 754-784
- What: In managed mode `toggle_pause()` resumes by calling `sequencer.resume()` only. `resume()` sets events; it never starts a thread. Every restart path (`on_signed_in`, `release_halt`, the fleet-halt release, the licence accept, `_root_resume_lanes`) goes through `_start_lanes()`, which RETURNS without starting anything while `_paused` is set and leaves `_lanes_started` False. When the editor later un-pauses, nothing ever calls `_start_lanes()` again. The sequencer was `stop()`ped (halt / token expiry / sign-out) or never started, so `thread_died()` is False and LaneWatchdog never restarts it either.
- Scenario: (a) Editor pauses on a hotspot. Admin sets a fleet halt (`halt_all_sync` -> `_stop_lanes` -> `sequencer.stop()`, `_lanes_started=False`), later releases it (`_start_lanes` refused: paused). Editor clicks Resume: `sequencer.resume()` on a stopped sequencer. Lanes A/B/C and lane A's watchdog stay down, tray shows Resumed, "Sync now" answers "Checking the server for changes now." (`sync_now_result` does not ask `_lanes_started`), until the tray is restarted. (b) The same through an expired token: `_identity_watch_loop` stops the lanes, the editor (paused) signs in, `on_signed_in` is refused by the pause, Resume does nothing. (c) Local halt while paused, release, resume.
- Recommendation: In `toggle_pause` managed branch, on resume call `_start_lanes()` when `not self._lanes_started` (it already re-checks every gate), else `sequencer.resume()`. Make `sync_now_result` refuse (or start) when the managed lanes were never started.
- Known: not in KNOWN_BUGS.md.

### bug-app-a-2 - Accepting the licence, or clearing a local halt, starts the lanes with nobody signed in

- Severity: medium
- Confidence: CONFIRMED
- Where: app.py:6638-6646 (`_show_licence_dialog` -> `_start_lanes`), app.py:8150-8162 (`release_halt`), app.py:6666-6695 (`_lanes_refusal` has no login gate), app.py:11862-11879 (licence watch started regardless of sign-in), app.py:10155-10168 (`start()` login gate lives outside `_start_lanes`)
- What: The require_login gate is applied only by `start()`, `on_signed_in`, `_root_resume_lanes` and `toggle_pause`; it is not in `_lanes_refusal()`, which the code calls "the ONE door every start path goes through". `_show_licence_dialog` (after ACCEPT) and `release_halt` call `_start_lanes()` directly.
- Scenario: An upgrade crosses an EULA version bump (EULA 1.1 re-consent) on a machine whose identity token has expired. `run()` starts `_licence_watch`, the dialog appears, the editor clicks ACCEPT, `_start_lanes()` passes every gate and starts the sequencer, lane C and lane A's watchdog. The selection fetch 401s and falls back to the cached `selection.json`, so the machine uploads/downloads/shares on a stale plan while `editor_identity()` is None and the reporter skips every cycle: it syncs while invisible on the fleet grid. Same via the tray's clear-halt after a sign-out.
- Recommendation: Put the login gate into `_lanes_refusal()` (after config, before EULA), with `_mark_lanes_pending_login` as its action in `_start_lanes`.
- Known: not recorded.

### bug-app-a-3 - A fleet halt release also erases the editor's own local halt

- Severity: medium
- Confidence: CONFIRMED
- Where: sync/lane_guard.py:1421-1490 (`HaltState.engage`/`note_fleet_flag`/`release`), app.py:9147-9178
- What: HaltState is one slot. A fleet engage over an active LOCAL halt overwrites its scope and reason ("upgraded"), and the fleet release then clears the slot entirely and `_apply_fleet_halt` calls `_release_lane_c_folders()` and `_start_lanes()`.
- Scenario: An editor presses STOP ALL SYNC because their project folder is in a bad state. Later the admin halts the fleet for an unrelated NAS issue and releases it an hour later. The editor's machine restarts lanes A/B and unpauses its Syncthing folders, toasting "Your administrator started syncing again", although the editor never released their stop.
- Recommendation: Track the local halt separately (e.g. `local_active` beside the fleet flag) and on fleet release fall back to the local halt if one was set before.
- Known: not recorded.

### bug-app-a-4 - Consolidate pulls proxies (lane B `rclone sync`) for a project ticked upload-only on this machine

- Severity: medium
- Confidence: PLAUSIBLE (path confirmed; whether the owner wants upload-only to bind consolidate is the open question)
- Where: app.py:4407-4418 (`_consolidate_upload_phase`), consolidate.py (no sync_mode check anywhere)
- What: CLAUDE.md: upload-only is "lane A alone for that project on that machine" and "Every reader of `selections` that decides what comes DOWN must ask for sync_modes=(full,)". The consolidate path runs `self._lane_b.run_once(subpath)` for the open project whenever `lane_b_enabled` and the dry run saw no deletions, without consulting the tick's `sync_mode`.
- Scenario: A laptop editor ticks a big project upload-only to save disk, opens it in Resolve and runs COPY THIS PROJECT'S MEDIA IN. After the upload, lane B downloads the whole project's proxy tree onto the laptop (and moves any local-only files into `.ccsync-trash`), exactly what upload-only was chosen to avoid.
- Recommendation: Resolve the open project's tick through the selection and skip the lane B pull (and say so in the report) when it is upload-only.
- Known: not recorded.

### bug-app-a-5 - Dashboard file moves are applied on disk during a halt

- Severity: low
- Confidence: PLAUSIBLE
- Where: app.py:8680-8895 (`_apply_file_moves`), app.py:2541-2566 (fan-out order), dashboard api.py:10990-11010 (no halt gate)
- What: The halt's contract is "stop touching the files"; the fan-out applies `_apply_fleet_halt` and then `_apply_file_moves` on the same reply with no halt check, and the dashboard sends `commands.file_moves` regardless of the fleet halt. `apply_move` renames local files, may move a folder into `.ccsync-trash` (section 4b), lists the server with rclone, and repoints Resolve.
- Scenario: An admin halts the fleet because a mass rename is going wrong, then (or already queued) file moves are outstanding; every halted machine still performs the renames/trashing and the Resolve relinks on its next report.
- Recommendation: Answer pending moves `retrying` ("waiting: syncing is stopped") while `self.halt.active`, the same shape as the drive-out wait.
- Known: not recorded.

### bug-app-a-6 - A watchdog restart of a dead sequencer silently undoes Pause and the drive-out pause

- Severity: low
- Confidence: CONFIRMED
- Where: app.py:1235-1255 (`restart=seq.start`), app.py:1206-1229 (`_must_not_restart` ignores pause/root/halt), sync/sequencer.py:652-655 (`start()` sets `_resume_event`)
- What: `Sequencer.start()` unconditionally `_resume_event.set()`. Pause (tray) and the root-absent pause are both `sequencer.pause()` = `_resume_event.clear()`. If the sequencer thread has died (not stopped), the editor (or the root guard) pauses within the watchdog interval/backoff, and the watchdog's `restart` then runs `start()`, rotation resumes while `_paused` is True and the tray says paused. `_must_not_restart` only checks shutdown and the popup/consolidate stand-down.
- Scenario: Sequencer dies on an OSError; editor presses Pause (hotspot) before the next watchdog tick (up to 60 s, or up to 10 min under backoff). The watchdog restarts it and lanes A/B rotate over the hotspot.
- Recommendation: After a watchdog restart, re-apply `sequencer.pause()` when `self._paused` or `self._root_absent`, or skip the restart while either holds.
- Known: not recorded.

### bug-app-a-7 - Lane completion events are drained before the POST and lost when it fails

- Severity: low
- Confidence: CONFIRMED
- Where: app.py:5099-5112 (`_pop_lane_completions`), reporter.py:941-947, 1384-1389
- What: `_build_payload` drains every lane's completions; `post_once` raises on any HTTP/network failure and nothing re-queues them (the file-move answers are explicitly redelivery-safe, completions are not).
- Scenario: A laptop on a flaky uplink finishes 40 uploads while a report times out; those 40 rows never reach the dashboard's transfer history, so the history (which admins use to confirm "did it arrive") under-reports exactly on the machines with network trouble.
- Recommendation: Keep the drained list in the reporter and prepend it to the next payload until a post succeeds (bounded by the existing cap).
- Known: not recorded.

### bug-app-a-8 - Pushed update and auto-update on the same reply race; the loser records a false "Update failed"

- Severity: low
- Confidence: CONFIRMED
- Where: app.py:2547 + 2575 (both run per reply), app.py:8382-8460, 8462-8571, upgrade.py:1901-1918
- What: With `auto_update` on and an admin push for the same version, one reply spawns both `ccsync-pushed-upgrade` and `ccsync-auto-upgrade`. `UpgradeManager.apply()` returns False to the second caller (`_applying`), which `apply_upgrade` reports as "failed": an "Update failed. You're still on vX" balloon and `_note_upgrade_failure` (REL-8 counter, persisted) for the build that is being installed.
- Scenario: Admin presses UPDATE NOW on a site with auto_update on; the editor sees "Installing" then "Update failed" seconds before the tray restarts on the new build. If the winner then fails too, the attempt is counted twice towards the give-up cap.
- Recommendation: Have `apply()` distinguish "already applying" (return a distinct outcome) and treat it as a stand-down, not a failure.
- Known: not recorded.

### bug-app-a-9 - Media-pool (bin-only) non-canonical clips are latched once per process even when the relink fails

- Severity: low
- Confidence: CONFIRMED
- Where: app.py:4888-4891 (`_pool_offered_non_canonical`), app.py:3626-3644 (`_note_non_canonical_result` re-arms only the watcher), app.py:3445-3449 (unreachable items dropped after latching)
- What: RES-19 made a failed relink re-offerable, but only for the watcher's own latch. The media-pool classifier keeps its own set, adds a path before the relink is attempted, and nothing removes it on refusal or when `media_pool_item_is_reachable` drops it.
- Scenario: Resolve is busy during the first media-tree pass and refuses ReplaceClip for 30 bin-only clips stored under `F:\...`. They are never offered again for the life of the process, so they stay Media Offline for every other editor until this tray restarts or the editor finds SCAN WHOLE PROJECT.
- Recommendation: Discard the key from `_pool_offered_non_canonical` in `_note_non_canonical_result(ok=False)` (and for items filtered as unreachable).
- Known: RES-19 fixed the watcher half only.
