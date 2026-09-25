# Ledger, wave 2 (2026-09-25): group c-app (`app.py`, `__main__.py`)

Builder "c-app", chunk 1 of 1. All code changes are in
`companion/src/ccsync_companion/app.py`. New tests are in
`companion/tests/test_bug_hunt_2026_09_24_w2_c-app.py` (16 tests). Two existing
tests in `companion/tests/test_app.py` were edited because behaviour changed on
purpose (see bug-comp-app-2 and ui-comp-windows-3).

"Fails on HEAD" below was checked by running the new file against HEAD's
app.py in a scratch copy of the package (`-o pythonpath=<scratch>`): 13 of the
16 fail there. The 3 that pass on HEAD are a control (a clean consolidate still
uploads), a guard (one ask in flight is not started twice, which HEAD's early
stamp also held), and a wire-contract pin for bug-comp-app-4.

Tests run (companion venv, from `companion/`):
`.venv\Scripts\python.exe -m pytest tests/test_app.py tests/test_app_contract.py tests/test_self_upgrade_handoff.py tests/test_settings_window.py tests/test_sync_halt.py tests/test_selection.py tests/test_bug_hunt_2026_09_18b_companion_core.py tests/test_diagnostics_upload.py tests/test_bug_hunt_2026_09_11_comp_app.py tests/test_bug_hunt_2026_09_11b_comp_app.py tests/test_file_moves.py tests/test_lane_b_resume_requests.py tests/test_site.py tests/test_bug_hunt_2026_09_24_w2_c-app.py -q`
-> 832 passed.

## bug-comp-app-2 - Consolidate ignores the halt, the licence gate and the sign-in gate
- Status: FIXED
- Verified as: CONFIRMED medium (med-01). I re-read HEAD's `consolidate_project`. Its four gates are sync_enabled, pause, config_problems and root. It never asks `_lanes_refusal()` (the only place the halt and the EULA are checked) or `_login_gate_blocks_sync()`. `_consolidate_upload_phase` calls `_lane_a.run_once` / `_lane_b.run_once` directly.
- Fix: app.py ~3966-3985: after the existing four gates, `consolidate_project` refuses on any `_lanes_refusal()` ("Nothing was copied in or uploaded. <the gate's sentence>") and on the login gate. app.py ~4270-4330: `_consolidate_upload_phase` asks `_lanes_refusal()` again before lane A and again before lane B, because the copy can take hours and a halt can land during it. It now returns the refusal sentence or None. app.py ~4205-4215: when the upload was refused or cut short, the final toast says "Copied in (N copied in), but the upload did not run or did not finish. <reason>" instead of "Copy & upload finished".
- Regression test: test_bug_hunt_2026_09_24_w2_c-app.py::test_consolidate_refuses_during_a_fleet_halt, ::test_consolidate_refuses_behind_the_licence_gate, ::test_consolidate_refuses_when_nobody_is_signed_in, ::test_a_halt_landing_during_the_copy_skips_the_upload_and_says_so (control: ::test_a_clean_consolidate_still_uploads). They fail on HEAD because the lanes ran and the toast said "Copy & upload finished".
- Existing test changed: six consolidate tests in test_app.py (confirm_flow, refuses_a_blank_active_project, holds_the_popup_lock, shows_the_batches_queued, refuses_a_project_root_outside_local_root, stops_at_the_failure_report) now pass `require_login=False`. Their fixture defaulted to require_login=True with no signed-in identity, which is exactly the machine the new gate refuses. The behaviour each one tests is unchanged.
- Tests run: see top -> pass.
- Skew / deploy order: companion only, no wire change.
- OWED: none

## bug-comp-app-3 - An admin's "ask this machine why" is marked answered before the upload
- Status: FIXED
- Verified as: CONFIRMED medium (med-01). On HEAD, `_apply_diagnostics_request` wrote `applied_request` and then started a thread that threw away `_upload_diagnostics`' boolean. The dashboard clears the ask only when the bundle arrives, so every redelivery was refused.
- Fix: app.py. `_apply_diagnostics_request` (~9140) no longer writes the stamp. Under a new `_diagnostics_lock` it refuses while an ask is in flight, and within `DIAGNOSTICS_REQUEST_RETRY_SECONDS` (300 s, ~1479) after a failed attempt, then marks the ask in flight. `_upload_diagnostics` (split into a wrapper plus `_upload_diagnostics_once`) calls the new `_settle_diagnostics_request(ok)` (~9167) for the `admin_request` trigger. On success that writes `applied_request`. On failure it arms the retry floor. The lane-error path's read-modify-write of the same state file now runs under the same lock (`_note_lane_error_states`, ~9061), so neither writer can revert the other's field.
- Regression test: ::test_a_failed_upload_is_retried_by_the_standing_ask (fails on HEAD: the stamp is written after a failed POST and the retry never happens), ::test_a_signed_out_machine_does_not_burn_the_ask (fails on HEAD: stamped with no upload), ::test_one_ask_in_flight_is_not_started_twice (guard, also holds on HEAD).
- Tests run: test_diagnostics_upload.py unchanged and green, plus the new file.
- Skew / deploy order: companion only. The dashboard contract (the command stands until the bundle lands) is unchanged. reporter.py's docstring ("a failure is try again later") is now true of this trigger.
- OWED: none

## bug-comp-core-3 - The site manifest is refreshed once per process start
- Status: FIXED
- Verified as: CONFIRMED medium (med-04). `site_mod.refresh_site` had one caller, a one-shot thread in `start()`. Every `feature_enabled()` reader (auto_update in app.py, youtube_download / youtube_unblock in ytdl_server.py and ytdlp_manager.py) reads the cache per call, so refreshing the cache file is enough for those flags to land.
- Fix: app.py. The start-time thread now runs `_site_refresh_loop` (~6383): `fetch_site`, then `save_site` on success, then `_stop_event.wait(SITE_REFRESH_SECONDS=900)`. After a failed fetch it waits `SITE_REFRESH_RETRY_SECONDS=120` instead, so a laptop that started before its tailnet catches up in about two minutes. It never raises and exits on shutdown. Constants are at ~1486.
- Residual, by design: keys that config.py merges into the config at LOAD (smb_unc -> server_p_unc, the SFTP tuning) still take effect at the next start. config.py's `_apply_site_manifest` contract is cache-at-load on the offline-safe path. They are now at least correct on the next start of a machine that booted offline, which was not true before. Hot re-applying them would be a c-core design change (a config reload), not a fix, so it is not OWED.
- Regression test: ::test_the_site_manifest_is_refreshed_for_the_life_of_the_process, ::test_a_refresh_that_raises_keeps_the_loop_alive. Both fail on HEAD, which has no loop.
- Tests run: test_site.py and the new file -> pass.
- Skew / deploy order: companion only. It is one extra GET /api/v1/site per machine every 15 min against an existing route. A dashboard without the route answers 404, which is already handled as "keep the cache".
- OWED: none

## bug-comp-app-4 - The pending-relink "done" answer can never land
- Status: ALREADY_FIXED (by d-db's bug-wire-1 in this same wave, uncommitted: db.py `mark_file_move_applied`, second arm ~6300-6313)
- Verified as: duplicate of bug-wire-1 (med-08, CONFIRMED medium; it also records that "nothing renders it" is wrong, because project_detail.html:250 does). The defect is entirely on the dashboard side. The companion's second answer from `_relink_pending_moves` is `ok=True` with no `state` and no `relink_pending`. The d-db arm matches exactly that shape (`ok and not relink_pending and state in (None, "", "done")`) against `applied_at IS NOT NULL AND ok=1 AND relink_pending=1`.
- Fix: none in app.py. The companion half was already correct.
- Regression test: ::test_the_relink_done_answer_is_a_plain_success pins the companion half of the wire contract that d-db's arm relies on (passes on HEAD; it is a contract pin, not a regression test).
- Tests run: new file -> pass.
- Skew / deploy order: dashboard-only fix. Every companion since RES-10 already sends the shape.
- OWED: none (d-db owns and has it)

## bug-comp-app-5 - An off-cycle report runs `_on_report_response` concurrently with the reporter thread's own
- Status: FIXED
- Verified as: real. `resume_lane_b` is reached from inside `_on_report_response` (via `_apply_resume_lane_b`). It calls `_report_off_cycle`, which runs `reporter.post_once` on a new thread, and post_once calls `on_report_response` with no lock anywhere. The consumers (`_apply_diagnostics_request`, `_apply_file_moves`, `_apply_resolve_undo`) are check-then-act on unlocked state.
- Fix: app.py ~2390. `_on_report_response` is now a wrapper that takes a re-entrant `_report_response_lock` (~1457) around the old body (`_on_report_response_locked`). The off-cycle thread waits its turn. Its only job, carrying sync_guard up, is already done by the time it gets there. The lock is re-entrant so a consumer that ever posts inline on the same thread cannot deadlock itself.
- Regression test: ::test_an_off_cycle_reply_waits_for_the_one_being_applied. It fails on HEAD because two fan-outs overlap (max concurrency 2).
- Tests run: see top -> pass (test_lane_b_resume_requests.py and test_sync_halt.py included).
- Skew / deploy order: companion only.
- OWED: none

## bug-comp-app-6 - `_queue_file_move_answer` appends outside the lock res-companion-5 added
- Status: FIXED
- Verified as: real (read at HEAD). The `with` block ended after the filter-assign and the append ran unlocked, so a swap between the attribute load and the append orphaned the answer.
- Fix: app.py ~8645-8660. The answer is built first, then the filter and the append run inside one `with _file_move_answers_lock(self):`.
- Regression test: ::test_an_answer_queued_while_the_reporter_drains_is_not_lost. A property seam starts the reporter's drain between the append's attribute load and the append itself. It fails on HEAD (the answer is lost) and passes now (the drain waits on the lock and sees it). The existing res-companion-5 test (test_bug_hunt_2026_09_11b_comp_app.py::test_an_answer_already_reported_is_not_resurrected) is still green.
- Tests run: see top -> pass.
- Skew / deploy order: companion only.
- OWED: none

## bug-wire-6 - `_queue_file_move_answer` appends outside the lock it was given
- Status: FIXED (duplicate of bug-comp-app-6; one fix, one test)
- Verified as: same code, same race as bug-comp-app-6.
- Fix: as bug-comp-app-6.
- Regression test: ::test_an_answer_queued_while_the_reporter_drains_is_not_lost.
- Tests run: see top -> pass.
- Skew / deploy order: companion only.
- OWED: none

## bug-comp-app-7 - The posix single-instance pid file never checks that the live pid is a companion
- Status: FIXED
- Verified as: real on posix. `_acquire_lock_file` treats any live pid in `~/.ccsync/companion.pid` as a running companion (`os.kill(pid, 0)` only), and nothing removes the file. After a reboot the LaunchAgent starts at low pids, where the old number can belong to a daemon. This is plausible and not measured, as the hunter says. The cost is a Mac with no companion and a false "already running" alert. On Windows the named mutex is the guard and the pid file is only its fallback.
- Fix: app.py ~440-510. New `_ps_command(pid)` (`ps -p <pid> -o command=`, 5 s timeout, never raises) and `_pid_looks_like_companion(pid, platform, ps_fn)`: False only when ps positively names a command without "ccsync" (the frozen bundle is `ccsync-companion`, source is `-m ccsync_companion`). It is True when ps cannot answer, and always True on win32. `_pid_holds_the_slot` = alive AND looks like a companion, and is now the default liveness test in `_acquire_lock_file`. The self-upgrade predecessor wait is unchanged: the predecessor is a companion. I did not add an unlink at shutdown. Removing the file during a multi-second teardown would let a double-click start a second instance beside a still-stopping one, and the identity check already closes the reboot case. A switch to fcntl.flock was considered and not done because it is a redesign of the guard that the existing hand-off tests are built around.
- Regression test: ::test_a_live_pid_that_is_not_a_companion_is_not_a_holder, ::test_a_reused_pid_after_a_reboot_does_not_lock_the_mac_out (sys.platform patched to darwin, `_pid_is_alive` True, ps names syslogd -> acquired; ps names ccsync-companion -> refused). Both fail on HEAD (no such function, and HEAD refuses).
- Tests run: test_app.py single-instance/predecessor tests and test_self_upgrade_handoff.py -> pass.
- Skew / deploy order: companion only. It matters on macOS, so it needs a Mac build (`tools/release_macos.sh`).
- OWED: none
- Review round (2026-09-25): the reviewer was right. The "ccsync" token check alone failed open for a supported install: `installer/macos_bootstrap.sh:151-152` accepts `--companion-path <path>`, and a path like `/Applications/Sync Tools/companion` has no "ccsync" in it. On that Mac a live companion's pid read as "not a companion", and a second instance started beside it. Fix, app.py ~465-535: new `_own_executables()` (frozen only: `sys.executable` and `sys.argv[0]`, each as given and as realpath) and `_command_runs(command, exe)` (full-path match, or the basename as a whole path component followed by the end of the line or an argument, so `companion` does not match `/usr/libexec/companiond` and a directory with spaces still matches). `_pid_looks_like_companion` returns True when ps names one of our own executables, and keeps "ccsync" as a second accepted token. From source `_own_executables()` is empty on purpose: `sys.executable` is a bare python, which would match every python on the machine, and `-m ccsync_companion` already carries the token. The one over-match left (an interpreter running a script whose basename equals ours) errs toward refusing a start, which is the fail-safe direction. New tests: ::test_a_companion_at_an_owner_chosen_path_still_holds_the_slot (seam cases plus end to end through `_acquire_lock_file` with `sys.frozen`/`sys.executable` patched; it fails when the own-executable match is removed, checked by stubbing `owns = []`) and ::test_from_source_a_bare_python_is_not_our_executable. Tests run: the new file, test_app.py and test_self_upgrade_handoff.py -> 417 passed.

## ui-comp-windows-3 - The licence dialog shows raw EULA.md, including the "DRAFT FOR COUNSEL / TODO(legal)" authoring comment
- Status: FIXED (the display half, at the verifier's downgraded LOW scope). The document's own content needs an owner decision (see below).
- Verified as: DOWNGRADE to low (med-17). `_show_licence_dialog` passed `eula_mod.bundled_text()` verbatim. The verifier's point stands: the VISIBLE body itself says "DRAFT FOR COUNSEL", names "Cablewrap Creative" (a retired brand) and carries inline `TODO(legal)` markers. Stripping the comment cannot fix those.
- Fix: app.py ~1493-1516. New `_licence_display_text(document)` removes HTML comments (the counsel note and the EULA-VERSION marker), `#` heading markers and `**bold**` markup. It turns U+2014 into " - " (the owner's no-em-dash rule for visible text) and collapses blank runs. `_show_licence_dialog` passes that to `popup.licence_dialog`. It is display only: `eula.bundled_text()`, the acceptance hash and the version parse read the untouched bytes.
- Owner decision needed (not a code fix, not OWED to a builder): the EULA text itself (companion/src/ccsync_companion/assets/EULA.md and onboarding/assets/EULA.md) still says "DRAFT FOR COUNSEL" in its visible heading line, names Cablewrap Creative as licensor, and leaves `[TODO(legal): jurisdiction]` inline. That is counsel's and the owner's to settle (CLAUDE.md: docs/legal is DRAFT FOR COUNSEL; memory: cablewrapcreative.com is retired). Bumping EULA-VERSION when it changes pushes every editor back through acceptance.
- Regression test: ::test_the_licence_dialog_shows_no_authoring_comment_or_markup. It fails on HEAD because the comment, "NOT YET EXECUTABLE", `**` and `#` are shown.
- Existing test changed: test_app.py::test_the_dialog_shows_the_document_this_build_bundles asserted `document == eula_mod.BUNDLED_TEXT`. It now asserts the whole document as displayed (`_licence_display_text(BUNDLED_TEXT)`) and that a late clause is present. It is still the full text, not a summary, which is what that test protects.
- Tests run: test_app.py -k licence -> 9 passed. New file -> pass.
- Skew / deploy order: companion only. The wizard's copy of the same defect is ui-onboarding-2 (group onboarding).
- OWED: none


# Owed round (2026-09-25)

Items other groups fixed on their side and left for `app.py`. Tests: `companion/tests/test_bug_hunt_2026_09_24_w2_c-app.py`, section "owed round". Regression check: the five regression tests were run in a scratch copy of `companion/` with HEAD's `app.py` swapped in. All 5 fail there. The 2 guard tests (`..._still_clears`, `..._keeps_no_reply_...`) pass on both, as intended.

Tests run: `companion\.venv\Scripts\python.exe -m pytest tests/test_app.py tests/test_bug_hunt_2026_09_24_w2_c-app.py tests/test_bug_hunt_2026_09_11b_comp_app.py tests/test_bug_hunt_2026_09_11_comp_app.py tests/test_bug_hunt_2026_09_24_w2_c-ui.py tests/test_bug_hunt_2026_09_24_w2_c-core.py tests/test_bug_hunt_2026_09_18_companion_media.py tests/test_bug_hunt_2026_09_18b_companion_media.py tests/test_upgrade.py -q` -> 779 passed.

## bug-comp-core-4 (owed by c-core) - sign_in rebuilt the verify reply and dropped `upgrade_none_reason`
- Status: FIXED
- Verified as: HEAD `sign_in` passed `{"upgrade": last_upgrade_info}` to `note_report_response`. That dict cannot carry a reason, so the clear rule in upgrade.py (~1665) wiped a standing refusal on every sign-in. c-core's `identity.py` now keeps `last_upgrade_reply = {"upgrade", "upgrade_none_reason"}` on a successful sign-in (identity.py ~557).
- Fix: app.py `sign_in` (~6770) passes `getattr(self.identity, "last_upgrade_reply", None) or {"upgrade": self.identity.last_upgrade_info}`. The fallback covers an identity double that keeps no reply.
- Regression test: ::test_a_sign_in_whose_verify_names_a_reason_keeps_a_standing_refusal (real UpgradeManager with a refusal noted; it fails on HEAD because the refusal is cleared). Guards: ::test_a_sign_in_with_no_offer_and_no_reason_still_clears (keeps the comp-ytdl-jobs-1 rule) and ::test_a_sign_in_with_an_identity_that_keeps_no_reply_still_works.
- Tests run: see top.
- Skew / deploy order: companion only on this side, and it reads no new wire key beyond c-core's. Against a dashboard older than 0.7.58, /verify sends no reason, so HEAD's behaviour stands there. The fix takes effect once d-api's `api_verify` half (bug-wire-4) is live, so deploy the dashboard first. Neither order breaks anything.
- OWED: none

## bug-wire-4 (owed by d-api) - sign_in adopted the /verify offer as if it were a report reply
- Status: FIXED (same change as bug-comp-core-4)
- Verified as: d-api offered two options. This takes the first: pass the whole verify result's upgrade keys. The second option was to skip the call when the reply has no `upgrade` key. I did not take it because it would drop the existing "an absent value clears a stale offer" behaviour at sign-in, which is the rollback case: an offer the admin has withdrawn would stay clickable for up to a report interval. With the reason now forwarded, the comp-app-3 case (a withheld build that is never re-offered) keeps its refusal. A machine-targeted CR-191 offer that /verify cannot name is cleared at sign-in and restored by the first report reply, a few seconds later, as it was at HEAD.
- Fix / Regression test / Tests run: as bug-comp-core-4.
- Skew / deploy order: dashboard first (d-api's `api_verify` reason), then companion. Either order is harmless.
- OWED: none

## bug-comp-media-5 (owed by c-media) - the no-ffmpeg sentence now also covers a missing ffprobe
- Status: FIXED
- Verified as: c-media's `proxy_gen._check_ffmpeg` now returns STATE_NO_FFMPEG when ffprobe is missing. `_proxy_state_note` (app.py ~919), which is the progress window's sentence, still said "ffmpeg is not installed here", and that is untrue on a machine that has ffmpeg. The tray's own proxy line does not name the tool, so it did not need a change.
- Fix: app.py ~919-922: "waiting: ffmpeg or ffprobe is not installed here" (no em dash).
- Regression test: ::test_the_no_ffmpeg_sentence_names_ffprobe_too. It fails on HEAD because the sentence has no "ffprobe".
- Skew / deploy order: companion only.
- OWED: none

## bug-comp-resolve-2 (owed by c-resolve) - the automatic-pass rate limiters read the 20 s cached project name
- Status: FIXED
- Verified as: `_handle_non_canonical` (~3435 at HEAD) and `_relink_proxies_once` (~4881) passed `current_project_name()`, the 20 s cache, to `resolve_journal.allow_automatic`. Just after a switch from A to B, B's first unprompted burst was charged to A. The same stale read fed `undo_last_fix`'s "undone" summary (~3597). `resolve_bridge.undo_last_relink` picks the project open NOW, so the notice could describe the other project's pass. That site was not in the OWED list, but it is the same defect in this file, so it is fixed here too.
- Fix: app.py, the canon-relink limiter, the proxy-relink limiter and `undo_last_fix` all read `current_project_name(max_age=0.0)`. That is one GetCurrentProject+GetName per burst, pass or click. `undo_last_fix_summary` (a label read, possibly on every menu build) keeps the cache on purpose.
- Regression test: ::test_the_canon_relink_limiter_charges_the_project_open_now and ::test_the_proxy_relink_limiter_charges_the_project_open_now. A double answers "A" from the cache and "B" only for max_age=0. Both fail on HEAD, which charges A.
- Existing test changed: test_bug_hunt_2026_09_11b_comp_app.py::test_the_rate_limiters_hold_off_is_logged_once_per_cooldown stubbed `current_project_name` as `lambda: "P"`, which cannot take the new keyword. It is now `lambda *a, **k: "P"`, and its assertion is unchanged.
- Skew / deploy order: companion only.
- OWED: none

## bug-comp-ui-1 (owed by c-ui) - register the app's popup lock with the ingest picker
- Status: FIXED
- Verified as: c-ui's `popup.set_picker_popup_lock` exists, and nothing called it. So `pick_media_sources` ran with `_picker_popup_lock = None`, which applies only the one-picker rule.
- Fix: app.py `CompanionApp.__init__`, right after `self._popup_active_lock = threading.Lock()`: `popup.set_picker_popup_lock(self._popup_active_lock)`.
- Regression test: ::test_the_ingest_picker_is_handed_the_apps_popup_lock. It fails on HEAD because the global stays None.
- Test hygiene note: each CompanionApp built in the suite now re-registers its own lock as the process global. The only real picker calls in the suite are in test_bug_hunt_2026_09_24_w2_c-ui.py, whose `_fresh_picker` fixture resets it, and every other picker use stubs `pick_media_sources`. So a lock left held by a test_app.py test cannot reach a picker test.
- Skew / deploy order: companion only.
- OWED: none

# Owed round 2 (2026-09-25)

## bug-comp-media-5 again (owed by c-media) - the STATE_NO_FFMPEG sentence names ffprobe
- Status: ALREADY_FIXED (by this group's first owed round, above; uncommitted working tree)
- Verified as: app.py ~921 `_proxy_state_note` already maps `proxy_gen_mod.STATE_NO_FFMPEG` to "waiting: ffmpeg or ffprobe is not installed here", the exact wording asked for, with no em dash. `grep -rn "ffmpeg is not installed here" companion/` finds no test or source still pinning the old words, so no existing test needed a change.
- Fix: none needed this round.
- Regression test: ::test_the_no_ffmpeg_sentence_names_ffprobe_too (from round 1; fails on HEAD, whose sentence has no "ffprobe").
- Tests run: `companion/.venv python -m pytest tests/test_bug_hunt_2026_09_24_w2_c-app.py -k ffprobe` - 1 passed.
- Skew / deploy order: companion only.
- OWED: none


# Owed round 3 (2026-09-25)

## ui-copy (owed from c-ui's widened scan) - "both sync lanes are failing" on the tray, Settings and the machine row
- Status: FIXED
- Verified as: `_blocked_candidate("transport_offline")` returned "This computer cannot reach the server: both sync lanes are failing" when the last error was empty. It returned "both sync lanes are failing" as the fallback when `classify_lane_error` raised. The widened `_WORD_RE` (plurals) in `test_sweep_2026_09_04_copy.py` failed on app.py for both.
- Fix: app.py (~7827/~7834): both places now say "upload and proxy download are both failing". The two rclone lanes are A and B, which the vocabulary table calls upload and proxy download.
- Regression test: `companion/tests/test_bug_hunt_2026_09_24_w2_c-app.py::test_the_transport_offline_sentence_says_upload_and_proxy_download[None|rclone...]` drives `_blocked_candidate` with two erroring fake lanes and fails on HEAD with the old sentence. `test_sweep_2026_09_04_copy.py::test_no_retired_word_in_a_sentence_an_editor_reads[app.py]` failed before and passes now.
- Tests run: `companion\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_c-app.py tests/test_sweep_2026_09_04_copy.py tests/test_tray.py tests/test_bug_hunt_2026_09_18_companion_core.py -q` -> 614 passed.
- Skew / deploy order: the dashboard renders the detail verbatim and nothing parses it.
- OWED: none
