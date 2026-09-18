# verdicts - comp-music-ytdl-jobs-res-fleet

Verified: comp-music-ytdl-jobs-1, -2, -3, res-fleet-2, res-fleet-3 (MEDIUMs only).
Read-only pass; no repo edits outside this file, no live system touched.

## comp-music-ytdl-jobs-1
- Verdict: CONFIRMED
- Duplicate of: none (same CLASS as comp-music-ytdl-jobs-3 and as the FIXED MEDIA-2; one shared helper would fix all three)
- Reasoning: both sides read. `jobs_runner._run_child` (`:1271-1275`) spawns the
  whisper venv's `pipeline.py transcribe` with `creationflags=_win_creationflags()`,
  and `_win_creationflags` (`:1548`) returns CREATE_NO_WINDOW and nothing else -
  no group, no job object, no `start_new_session`. `_terminate` (`:1496`) is
  `proc.terminate()` / `proc.kill()` on that one pid, and it is the ONLY stop
  in the module (`grep` shows five call sites at `:1317-1334`: lease lost,
  cancel, fleet halt, shutdown, exception). The grandchild is real: 
  `MulticamPipeline/multicam_pipeline/transcripts/whisper_corpus.run_worker`
  (`:518-535`) `Popen`s a SECOND process which is the one that loads the model
  and holds the VRAM, with no group of its own either. TerminateProcess does
  not cascade on Windows and SIGTERM's default action does no cleanup, so a
  cancel/halt/quit returns the machine to idle with the worker still running -
  and the machine can then claim the next whisper job onto the same GPU. A fleet
  halt that does not stop the work it names is the SYNC_SAFETY shape, so medium
  is right, not low.
- Evidence: code read of `_run_child`, `_terminate`, `_win_creationflags` and
  `run_worker`; `grep -rn CREATE_NEW_PROCESS_GROUP\|start_new_session` over
  `companion/src` confirms jobs_runner is the only spawner of a spawner without
  one. `grep -an` KNOWN_BUGS.md: MEDIA-2 (`:7029`) is the DIRECT-child ingest
  ffmpeg and is FIXED; nothing covers the jobs runner. Partial mitigation the
  hunter does not mention: when `pipeline.py` dies, the worker's next JSON event
  write hits a broken stderr pipe and it will usually die then - but only at its
  next per-file event, so a long file keeps the GPU for minutes, and the file it
  is mid-way through is still written.
- Fix note: the hunter's suggested fix is right in spirit but wrong in one
  detail on Windows: `CREATE_NEW_PROCESS_GROUP` alone changes nothing, because
  `Popen.terminate()` still calls TerminateProcess on the single pid (the
  existing users of that flag - `supervisor.py:454`,
  `sync/syncthing_supervisor.py:267`, `broll_vlm/local_vlm.py:169`, `bpg.py:878`
  - pass it to DETACH a child, the opposite intent). The working shape is the
  one KNOWN_BUGS `:7579-7583` already documents for `terminate_bootstrap`:
  `taskkill /T /F /PID` on Windows, `os.killpg` elsewhere (a Job Object would be
  better still). A fix must also touch `companion/tests/test_jobs_runner.py`
  (every jobs test injects a fake runner, so a fake `proc` with no real pid must
  not make the new kill path raise) and should be shared with
  `ytdl_executor._kill_proc` (finding 3) rather than copied a fourth time.

## comp-music-ytdl-jobs-2
- Verdict: DOWNGRADED to low
- Duplicate of: none
- Reasoning: the code half is exactly as reported - `ytdl_browser_login`
  `:517-524` does `profile.mkdir` + `os.chmod(profile, 0o700)` and nothing else,
  `secretfile.harden` is never called on this path (`grep` finds `profile_dir`
  defined at `:192` and used once at `:517`), and there is no sign-out anywhere.
  But the stated failure - "any other local account can copy the profile and get
  a signed-in Google session" - does not work on the platform the finding names.
  Two things stand in the way: a default `%USERPROFILE%` already grants only
  SYSTEM, Administrators and the owner, so a second standard user cannot read
  `~/.ccsync` regardless of the chmod; and Chromium on Windows encrypts the
  cookie store with a key wrapped by DPAPI in the USER's scope, so a wholesale
  copy by another account is undecryptable. Against the same-account threat
  (malware running as the editor) an owner-only ACL buys nothing either - it
  grants that same owner - so the ACL half of the fix is close to ornamental,
  unlike `cookies.txt`, which is plaintext. The hunter is also wrong that the
  profile outlives an uninstall in general: `installer/windows_uninstall.ps1:698-712`
  deletes everything under `%USERPROFILE%\.ccsync` except `state\` on `-Full`
  (the hunter's `:22` citation is the help text about `state`), and
  `macos_uninstall.sh --full` removes `~/.ccsync`. What survives is the DEFAULT
  run, which is true and is the part worth fixing.
- Evidence: reads of `ytdl_browser_login.py:190-194, 500-525`, `secretfile.py`
  header and `_harden_windows`, `installer/windows_uninstall.ps1:661-720`,
  `installer/macos_uninstall.sh:1-30`; `grep -rn "profile_dir|yt-login-profile"`
  over `companion/src` and `installer/`.
- Fix note: keep the useful half only. A "forget this sign-in" that deletes
  `cookies.txt` AND the profile, wired where `ytdl_cookies.mark_stale` and the
  tray's YouTube menu already reach, is the fix; the `(OI)(CI)` icacls variant
  the hunter proposes is defensible hygiene but do not size the work by the
  stated scenario. Note that any such variant must go in `secretfile.py` beside
  `_harden_windows` (a second icacls call site in `ytdl_browser_login` would be
  the thing COMMERCIAL_READINESS item 15 consolidated), and the default
  uninstall's copy ("your sign-in and settings are kept") would need to keep
  saying what is kept.

## comp-music-ytdl-jobs-3
- Verdict: CONFIRMED
- Duplicate of: none (shares its fix with comp-music-ytdl-jobs-1)
- Reasoning: `ytdl_executor._kill_proc` (`:2012-2021`) is `proc.kill()` under the
  lock on the yt-dlp pid alone, reached from `lose_lease`, from `_register_proc`
  when the lease went away during the spawn, and the timeout path at `:511` does
  its own bare `proc.kill()`. The spawn at `:476-484` passes
  `ytdlp_manager._win_creationflags()`, CREATE_NO_WINDOW only. yt-dlp really
  does have an ffmpeg child here: the module passes `--ffmpeg-location`
  (`_ffmpeg_location`, gate at `:957`) and uses the `bestvideo+bestaudio` merge
  selector (`:121`, `:369`), so essentially every DASH download ends in an
  ffmpeg merge. Killing the parent leaves that merge running with its handles
  on the `.part`/output, which is precisely MEDIA-2's recorded Windows symptom
  ("holding a handle on the staged file ... blocks any later staging cleanup")
  one process further out, and `clear_partials` / `clear_aside_originals`
  (`:1362`, `:1384`) are the cleanups that then fail and log.
- Evidence: reads of `:470-525`, `:1995-2030`, `:1350-1400`; `grep -n ffmpeg
  ytdl_executor.py` shows the only ffmpeg we spawn ourselves is the edit-ready
  conversion (a direct child, correctly killed). Mitigation worth recording:
  yt-dlp reads ffmpeg's pipes, so the orphan often dies on its next write to a
  broken pipe - but ffmpeg writes progress sparsely and a 4K merge can run a
  long way before it does.
- Fix note: right fix, same correction as finding 1 - on Windows the group flag
  alone does not make `kill()` reach the child, so `taskkill /T /F /PID`
  (`os.killpg` elsewhere) is what is needed. One shared helper for
  `jobs_runner`, `ytdl_executor` and `ytdlp_manager._win_creationflags` is the
  right shape; `companion/tests/test_ytdl_executor.py`'s fake `proc` doubles
  (they expose `kill` and often no real `pid`) are the tests a fix must not
  break.

## res-fleet-2
- Verdict: CONFIRMED
- Duplicate of: dash-db-5 (same two functions, same mechanism, rated low there);
  overlaps dash-collector-alerts-3 (the first-walk variant of the same write)
- Reasoning: verified in the code. `db.record_pending_move_halves` (`:8766`)
  inserts whatever `_settle_halves` hands it with no cap, `_settle_halves`
  (`collector.py:2654`) passes `plan.persist` whole, and `unpaired_halves`
  (`:2554`) filters only ambiguity and `Proxy/` - so an upload of N new clips
  into a walked project, or a first walk of a project (`walk.old` empty), yields
  N `appeared` halves in one executemany. The read, `db.pending_move_halves`
  (`:8789`), is `WHERE seen_at >= cutoff ORDER BY seen_at, rowid LIMIT 4000`, and
  `pair_across_cycles` only ever sees `carried` from that read: once the live
  two-day window holds more than 4000 rows, the oldest 4000 (by construction the
  ones that will never pair) crowd out every fresh half and cross-cycle
  detection is off, silently, until `prune`'s two-day age-out drains it. The
  `DETECTED_MOVE_LIMIT = 500` cap at `collector.py:1847` bounds the MOVES a pass
  reports, not the halves it persists - and `_settle_halves` deliberately puts
  capped moves' halves BACK, so the cap makes the table bigger, not smaller.
  Medium is defensible (the feature disables itself with no notice); dash-db-5
  rated the identical mechanism low, so the two verdicts should be reconciled
  when it is triaged - I would keep medium.
- Evidence: reads of `db.py:8743-8825` and `:8531-8536` (the only bound: a
  two-day `prune`), `collector.py:2554-2690` and `:1840-1880`.
- Reasoning on the write path: the executemany runs inside the inventory pass's
  write transaction, which is the same lock hold `dash-collector-alerts-3` and
  `test_db_write_locks.py` care about - so a fix that only reads newest-first
  leaves that half open.
- Fix note: both halves of the suggested fix are right and they are independent.
  Reading `ORDER BY seen_at DESC` is the cheap one, but note it changes which
  rows `pair_across_cycles` sees and therefore which moves are detected, so
  `dashboard/tests/test_collector_moves.py` (and whatever pins oldest-first in
  `test_db_*`) must be re-read, and the docstring "oldest first" at `db.py:8794`
  is part of the change. Bounding the write wants the `file_moves_dropped`
  notice dash-db-5 names, not a silent drop, and should skip a walk whose `old`
  is empty (dash-collector-alerts-3's half) so a new project never writes halves
  at all.

## res-fleet-3
- Verdict: CONFIRMED
- Duplicate of: dash-release-jobs-1 (which covers the same two unguarded
  `_set_state` calls AND the deeper in-memory-intent hole, with a reproduction);
  res-fleet-3 is a strict subset
- Reasoning: the mechanism holds. `apply`'s tail runs `_set_state(settings,
  step="restarting", ...)` at `:1471` with no `best_effort`, i.e. through
  `_write_json`, immediately AFTER `staging.rename(final)` and after
  `current.json` has been rewritten to name the new version, and immediately
  BEFORE `request_restart`. An OSError there propagates out of `apply`, the
  worker's `except` in `start_apply._run` calls `_fail_state` (now best effort,
  so it records `step="failed"`), and no restart is ever requested: the panel
  says FAILED while the swapped tree is what the next unrelated restart boots.
  `rollback` has the identical shape at `:1558`. Two corrections to the
  write-up: `request_restart`'s OWN write is already `best_effort=True`
  (`:1288`), so the hunter's second location is wrong - `:1558` is rollback's
  call, not request_restart's - and the residual hole inside `request_restart`
  is that the swallowed write loses the `restart_requested` flag entirely, which
  is dash-release-jobs-1's point, not this one's.
- Evidence: `grep -n "_set_state(" dashboard_update.py` -> best_effort at 590,
  1288, 1303; plain at 1353, 1369, 1375, 1386, 1418, 1471, 1558, 1580. Reads of
  `_set_state` (`:551`), `_write_json` (`:219`, no try), `_write_json_best_effort`
  (`:228`, swallows OSError), `apply`'s tail (`:1440-1478`: the only `finally` is
  the archive unlink) and `rollback` (`:1550-1562`).
- Fix note: `best_effort=True` on `:1471` and `:1558` is correct and cannot
  break anything - `_set_state` returns the decided state either way and neither
  caller reads the return. It is NOT sufficient on its own, though: without
  dash-release-jobs-1's in-memory restart flag the process still exits 0 when
  the guarded write is swallowed, so fix the two together. Tests to touch:
  `dashboard/tests/test_dashboard_update.py`'s
  `test_a_restart_is_signalled_even_when_the_note_about_it_cannot_land` and its
  sibling (which pre-writes `restart_requested: True` to a healthy disk and so
  passes vacuously) - the new case should break `_write_json` BEFORE `apply`'s
  tail and assert `_signal_restart` fired.
