# CR-295 - a stopped child that spawned a child of its own (companion jobs + ytdl)

## CR-295 - the whisper worker and the merge ffmpeg outlive the kill that names them - FIXED in repo 2026-09-18 (companion)

### CR-295A (comp-music-ytdl-jobs-1) - a cancelled or halted whisper job left the worker on the GPU - FIXED (companion/src/ccsync_companion/jobs_runner.py, proc_tree.py)

`_run_child` spawns the whisper venv's `pipeline.py transcribe`, but that
process is not the worker: `whisper_corpus.run_worker` Popens a second process,
and that one loads the model and holds the VRAM. `_terminate` was
`proc.terminate()` / `proc.kill()` on the pipeline's pid alone, with no group
and no job object, so a cancel, a fleet halt or a tray quit reported the job
stopped within a heartbeat while the worker kept the GPU, kept writing into the
episode folder, and the machine went back to idle and could claim the next
whisper job onto the same card. The fix spawns the child at the head of its own
group (`proc_tree.spawn_kwargs`, preserving the caller's CREATE_NO_WINDOW) and
makes `_terminate` a single call to `proc_tree.kill_tree`, which is `taskkill
/T /F /PID` on Windows and `killpg(SIGTERM)` then `SIGKILL` elsewhere, always
followed by the old single-process stop. The verifier's note is honoured:
`CREATE_NEW_PROCESS_GROUP` alone changes nothing, because `Popen.terminate()`
still calls TerminateProcess on one pid. Tests:
`test_jobs_runner_terminate_goes_through_the_tree_kill` and
`test_whisper_child_is_spawned_in_its_own_group`.

### CR-295B (comp-music-ytdl-jobs-3) - killing yt-dlp did not kill the ffmpeg it spawned - FIXED (companion/src/ccsync_companion/ytdl_executor.py, proc_tree.py)

`_kill_proc` (reached from `lose_lease`, from `_register_proc` when the lease
went away during the spawn, and from the timeout path's own bare `proc.kill()`)
killed the yt-dlp pid only. Every download here is a `bestvideo+bestaudio`
merge with `--ffmpeg-location`, so the merge ffmpeg survived the kill holding
handles on the `.part` and the output, which is what `clear_partials` /
`clear_aside_originals` then failed on (MEDIA-2's symptom, one process further
out). yt-dlp now spawns in its own group through the same
`proc_tree.spawn_kwargs`, and both `_kill_proc` and the timeout path go through
`proc_tree.kill_tree`. The helper is SHARED with `jobs_runner`, not copied a
fourth time, as the verifier asked. Test:
`test_ytdl_executor_kill_proc_goes_through_the_tree_kill`, plus the helper's own
Windows/POSIX tests.

### Verification
- comp-music-ytdl-jobs-1: `companion/tests/test_proc_tree.py` (7 tests) passes; the two delegation tests fail on the pre-fix source, where `_terminate` never reaches the helper.
- comp-music-ytdl-jobs-3: same file; `_kill_proc` delegation pinned.
- Neighbours re-run green: `test_jobs_runner.py`, `test_jobs_phase4.py`, `test_jobs_runner_visibility.py`, `test_ytdl_executor.py` (275 passed with the new file).
- `py_compile` clean on `proc_tree.py`, `jobs_runner.py`, `ytdl_executor.py`.

### Not fixed
- comp-music-ytdl-jobs-2 was DOWNGRADED to low by the verifier and is not in this group's list; the "forget this sign-in" it asks for is untouched.
- A Windows Job Object (the verifier's "better still") was not built: `taskkill /T` is the shape the repo already documents and can be landed inside the box.

### OWED TO ANOTHER GROUP
- None. `sidecar_tools.py` was listed in this group's files but needed no change: it installs binaries and spawns nothing that spawns.
- Not owed, but worth recording for whoever owns the other spawners: `broll_vlm_sidecar`, `supervisor.py`, `sync/syncthing_supervisor.py` and `bpg.py` pass `CREATE_NEW_PROCESS_GROUP` to DETACH a child (the opposite intent) and were deliberately left alone.

### Deploy order
- Companion only, no wire change. A machine on an older build behaves as before; nothing on the dashboard side reads any of this.

### Owner decisions
- None needed.
