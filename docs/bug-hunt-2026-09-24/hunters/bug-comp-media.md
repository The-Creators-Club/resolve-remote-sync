# bug-comp-media - companion media stack: fleet job runner + media recipes, proxy generator/scan/history, ffmpeg tools, BPG, sidecar tools, proc_tree, music loopback/ingest/worker/CLAP sidecar

Files read (approximate coverage): jobs_runner.py (all), jobs_media.py (all), job_paths.py (all), proc_tree.py (all), music_server.py (all), music_worker.py (all), proxy_scan.py (all), proxy_gen.py (~60%: popen/kill/drain/progress, gate, tick, scan_once, encode_once/_encode_clip/_verify/_publish, failure cap, drain workers), ffmpeg_tools.py (binary discovery, probe, timecode, encoders; argv builders skimmed), bpg.py (~85%), sidecar_tools.py (install/ensure half), music_ingest.py (per-item pipeline, result/upload), music_clap_sidecar.py (session, audio decode/peaks/windows/embed, probe/transcode). Not read: music_clap/mel_numpy.py, music_models.py, proxy_history.py beyond its lock structure. Cross-checked the dashboard side for jobs: dashboard/src/ccsync_dashboard/jobs.py (idle floor, eligibility), api.py JobIn/`POST /jobs`, cards_exec.py `_paths`, db.py cooldown.
Tests/probes run (companion venv, scratchpad only):
- `probe_managed.py`: PATH stripped of ffmpeg, `sidecar_tools.managed_path` pointed at a real ffmpeg/ffprobe pair -> `ffmpeg_available("ffmpeg")` is True, `ffprobe_for` resolves, and all three `MediaJob.run` kinds fail with `could not start ffmpeg: [WinError 2]`.
- `probe_stem.py`: `JobRunner._media_paths` with `out_stem` = `C:/Windows/Temp/evil` resolves the output to `C:\Windows\Temp\evil.peaks`; `Interview 1/2` lands in a subdirectory; a NUL in rel_path raises a plain ValueError, not JobPathError.
- ffmpeg 7 run of the exact `peaks_cmd` on a video-only mp4: "Output file does not contain any stream", non-zero exit.

## Findings

### bug-comp-media-1 - Media jobs and proxy generation spawn the BARE name "ffmpeg", so a machine whose only ffmpeg is the managed sidecar copy advertises the capability and then fails every encode
- Severity: high
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/jobs_media.py:251-312 (argv[0] = `str(ffmpeg_path)`), :469 (`subprocess.Popen(cmd)`); jobs_runner.py:1167 (`ffmpeg_path=str(self.cfg.get("ffmpeg_path", "ffmpeg"))`); proxy_gen.py:558, :326 (`_default_popen`), :1726/:1989/:1994 (verify + encode argvs); vs ffmpeg_tools.py:128-139/:187-224 (managed fallback)
- What: `ffmpeg_tools._resolve_binary`/`ffmpeg_available` fall back to the sidecar-installed ffmpeg when the bare default `ffmpeg` is not on PATH (KNOWN_BUGS CR-53 / R18 fix 1), and capabilities.py reports `ffmpeg`/`ffprobe` true from exactly that probe. But the argv builders in jobs_media and ffmpeg_tools put the UNRESOLVED config value (`"ffmpeg"`) in argv[0], and `subprocess.Popen` looks only on PATH. ffprobe works (ffprobe_for resolves), ffmpeg itself never does. music_clap_sidecar (`:778`, `:810`) and ytdl_executor (`:1742`) resolve with `_resolve_binary` first; these two callers do not.
- Failure scenario: an editor laptop with no ffmpeg of its own (the normal case; the vendor build installs the pinned pair into the tools dir) reports `ffmpeg: true, ffprobe: true`, so the dashboard offers it proxy-480p / audio-extract / peaks jobs. It claims one, fails in about a second with "could not start ffmpeg: [WinError 2]" as a RETRYABLE failure, earns the 120 s per-machine cooldown (db.JOB_COOLDOWN_SECONDS), and the job tours the fleet. On the same machine proxy_gen's gate reads RUNNING (ffmpeg_available is True), every clip's encode fails with the same spawn error, three attempts cap each clip, and the history ledger fills with "could not start ffmpeg" rows while remote editors never get the proxies.
- Evidence: scratchpad `probe_managed.py` (output above): `which ffmpeg: None`, `ffmpeg_available: (True, ...\ffmpeg.exe)`, then `peaks/audio-extract/proxy-480p FAILED: could not start ffmpeg: [WinError 2] ... retryable= True`. No `PATH` prepend exists anywhere in the package (grep for PATH mutations: none).
- Ledger: new (related to CR-53, whose managed-ffmpeg fallback these two spawners never use)
- Suggested fix: resolve once where the path is chosen (`ffmpeg_tools._resolve_binary(cfg ffmpeg_path) or ffmpeg_path`) in `ProxyGenerator.__init__`/per tick and in `JobRunner._execute_media`, the way music_clap_sidecar and ytdl_executor already do; add a test that runs with PATH stripped and a managed binary.

### bug-comp-media-2 - The companion's job gate ignores the dashboard's per-kind idle floor and the base-rig exemption, so the cheap kinds wait 300 s and the base rig never claims while anybody is at it
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/jobs_runner.py:262 (`jobs_idle_seconds`, one value for every kind), :591-594 (`_user_is_away`), :729-747 (`_gate`); vs dashboard/src/ccsync_dashboard/jobs.py:53-59 (`JOB_IDLE_FLOOR_SECONDS`: audio-extract/peaks 60 s) and :867-885 (base mode exempt from the floor)
- What: the scheduler offers audio-extract and peaks to a machine idle for 60 s, and offers ANY kind to a base-mode machine regardless of idle, and ranks the base rig first for the two cheap kinds. The claimant then applies its own flat `jobs_idle_seconds` (300) to every kind and has no base-mode exemption at all, so it sits at STATE_USER_ACTIVE and never claims. Two sides of one rule disagree; CLAUDE.md states the floor is per kind and the base rig is exempt.
- Failure scenario: Alex is at the base rig (or it has no console session, where idle.py answers None = not idle). The dashboard offers it a peaks job and `GET /jobs/<id>/why` calls it eligible and first in rank; the companion refuses for as long as anybody touches the keyboard (for ever when idle is None), the 60 s grace expires, and the page's lane waits on another machine. On an editor laptop idle for 2 minutes the same happens between 60 s and 300 s, so the "60 s for the cheap kinds" decision never takes effect.
- Evidence: read both gates; no code in jobs_runner consults the job kind or the machine's mode before `_user_is_away`. The claim body carries `kinds`, but the offer ids arrive without a kind, so the gate cannot choose a floor even in principle.
- Ledger: new
- Suggested fix: let the offer block carry each id's idle floor (or the kind), and gate each id on it; exempt `effective_mode() == "base"` the way jobs.py does. Alternatively make the dashboard read `jobs_idle_seconds` from capabilities, but one of the two must own the rule.

### bug-comp-media-3 - `out_stem` is used as a filename with no validation, so it can write outside the output directory (anywhere, when absolute) and a multicam name with `/` or `:` lands in the wrong place
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/jobs_runner.py:1226 (`stem = inputs.out_stem or source.stem`), consumed at jobs_media.py:814/824/828/884/924 (`out_dir / f"{stem}{ext}"`); twin at dashboard/src/ccsync_dashboard/cards_exec.py:384
- What: `job_paths.resolve` goes out of its way to refuse absolute and climbing paths ("a path from the network that a background service opens ... should never be assembled without one"), but the stem is appended afterwards without any check. `Path(out_dir) / "C:/x"` discards out_dir; `../../..` climbs; `/` creates a subdirectory the recipe never mkdirs; on Windows a `:` makes an NTFS alternate data stream.
- Failure scenario: a job with `out_stem: "C:/Windows/Temp/evil"` writes `C:\Windows\Temp\evil.peaks` on the claimant (any file the tray's user can write, via `os.replace`). Less contrived: the page's multicam name `Interview 1/2` puts the proxy under `remote_audio\Interview 1\2.480p.mp4`, where the `.partial` open fails (directory not created) as a RETRYABLE failure that tours the fleet with cooldowns; `Q&A: Ruskin` on a Windows claimant writes into an ADS of a file called `Q&A`, invisible to the page.
- Evidence: scratchpad `probe_stem.py`: `'C:/Windows/Temp/evil' -> C:\Windows\Temp\evil.peaks inside vault: False`; `'Interview 1/2' -> ...\remote_audio\Interview 1\2.peaks`.
- Ledger: new
- Suggested fix: refuse (JobPathError, not retryable) a stem that is absolute, contains a separator, `..`, `:`, a control character or NUL, or does not equal `Path(stem).name`; apply the same rule in cards_exec._paths so both executors agree.

### bug-comp-media-4 - A peaks job on a clip with no audio is a RETRYABLE failure, so it tours the whole fleet cooling every machine down before it pins
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/jobs_media.py:916-939 (`_peaks`), vs :817-821 (`_audio` probes and raises `retryable=False`)
- What: `_audio` probes first and calls a missing audio track a fault in the INPUT (not retryable). `_peaks` probes too (`_codec, duration = probe_audio(...)`) but ignores the codec, runs ffmpeg, and ffmpeg refuses an output with no stream (non-zero exit). The `code != 0` branch raises `MediaJobError(err)` with the default `retryable=True`; the non-retryable "there is no audio to draw" branch is only reached on exit 0.
- Failure scenario: Timeline Cards queues peaks for a video-only angle (a drone or a second camera recorded without sound). Machine A fails it retryably and is put on the 120 s job cooldown (db.py:10685), machine B the same, and so on until the retry budget is spent and the job pins onto the dashboard's own engine, which fails it again. Every machine it visited was unavailable for real work for two minutes, and the dashboard's failure count blames the machines.
- Evidence: ran the exact `peaks_cmd` argv against a video-only mp4 with ffmpeg 7: `Output file does not contain any stream`, non-zero exit; read `_peaks` - `_codec` is discarded.
- Ledger: new
- Suggested fix: in `_peaks`, `if not _codec: raise MediaJobError("no audio track", retryable=False)` before the decode, matching `_audio`.

### bug-comp-media-5 - The proxy generator's gate checks for ffmpeg but not ffprobe, so a machine with ffmpeg and no ffprobe fails and caps every clip while reporting itself as running
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/proxy_gen.py:949-970 (`_check_ffmpeg`), :1000 (gate), :2082-2098 (probe failure -> `_record_failure`); ffmpeg_tools.py:144-165 (`ffprobe_for` falls back to bare `ffprobe`), sidecar_tools.py:727-750 (an own ffmpeg on PATH suppresses installing the managed pair, ffprobe included)
- What: capabilities.py treats ffprobe as its own capability for exactly this reason ("reported ffmpeg alone would claim the work and then guess"), but proxy_gen's gate asks only `ffmpeg_available`. When ffprobe is absent, `probe_video` raises UnreadableMediaError("ffprobe could not be run") for every clip, which is recorded as a failure OF THE CLIP.
- Failure scenario: an editor has a lone `ffmpeg.exe` on PATH (so the sidecar does not install the managed pair). The gate says RUNNING, every queued clip fails three times and is capped until restart, the history ledger records hundreds of "ffprobe could not be run" failures, and the tray shows the generator as working with the gap never closing. Nothing says "install ffprobe".
- Evidence: read the gate, `_check_ffmpeg`, `probe_video`'s OSError branch and `_record_failure`; `_editor_has_own_ffmpeg` checks only ffmpeg.
- Ledger: new
- Suggested fix: gate on `ffmpeg_available(ffprobe_for(ffmpeg_path))` too (STATE_NO_FFMPEG with an ffprobe sentence), and do not count a missing-tool probe failure against the clip.

### bug-comp-media-6 - Music "insert at playhead" cannot ripple a clip that straddles the playhead: it is moved whole into the cue it just placed, so the insert fails and rolls back
- Severity: medium
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/music_worker.py:361-412 (`act_insert`)
- What: `affected` is every item on the track with `GetEnd() > rec`, which includes a clip that STARTS before the playhead and runs past it. The snapshot re-appends each at `start + shift`; for the straddler `start + shift < rec + shift`, i.e. inside the new cue's span `[rec, rec+shift)`. `place()`'s own docstring says Resolve does not place onto an occupied span, so the verify at :409 raises "ripple failed" and the whole insert rolls back. (If Resolve instead overwrote, the new cue's tail would be destroyed.) The docstring promises "everything at or after the playhead shifts later", which a straddling clip is neither.
- Failure scenario: an editor has a music bed on A2 and parks the playhead in the middle of it (the common case: "drop a sting here") and presses insert on A2. The page reports "insert failed; rolled back N/N clip(s) on A2" every time; the only way through is to razor the bed by hand first, which the message does not say. The rollback also re-appends every rippled clip fresh, dropping its clip volume, fades and effects.
- Evidence: read the snapshot/re-append arithmetic; Resolve's overlap behaviour is taken from this module's own `place()` note, not measured live (no Resolve calls allowed in this hunt).
- Ledger: new
- Suggested fix: refuse up front with a sentence ("the playhead is inside a clip on A2 - move it to a cut or use place underneath") when any item has `GetStart() < rec < GetEnd()`, or split the straddler into its head and tail before rippling.

### bug-comp-media-7 - Music ingest decodes the whole track into the tray process at three times its PCM size, and a track over two hours gets a false duration
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/music_clap_sidecar.py:796-822 (`decode`), :946-969 (`embed_file`), :72 (`MAX_DECODE_SECONDS = 7200`)
- What: `_run(...).communicate()` holds the full f32 stdout as one bytes object (N), `np.nan_to_num` allocates a second copy (N) and `.copy()` a third (N) before the first two are freed: at 48 kHz mono float32 that is ~690 MB per hour of audio, ~2 GB peak for a one-hour mix and ~4 GB for a two-hour one, inside the companion that runs sync. Separately, `-t 7200` truncates the decode and `duration` is computed from the decoded sample count, so any track longer than two hours is recorded as exactly 7200 s, and the "re-encode duplicate defence" that `embed_file`'s docstring says matches on duration is then comparing against a wrong number.
- Failure scenario: an editor drops a 90-minute ambient mix on an 8 GB laptop: the tray allocates ~3 GB during the decode (MemoryError fails the track at best; at worst the machine pages while Resolve is open). A 2 h 30 min DJ set is stored as a 2:00:00 track.
- Evidence: arithmetic on the three allocations in `decode`; `duration = samples.size / sample_rate` after `-t 7200`.
- Ledger: new
- Suggested fix: `np.nan_to_num(samples, copy=True, ...)` alone (no extra `.copy()`), or decode at the 48 kHz rate only the windows actually used; take `duration` from the probe when the decode hit the cap.

### bug-comp-media-8 - A job input that `Path` rejects (NUL byte) escapes `_execute_media`/`_execute_whisper` uncaught, so no result is ever posted and every machine silently drops the job
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/jobs_runner.py:1102-1109 and :1053-1060 (catch only `job_paths.JobPathError`); job_paths.py:112-113 (`Path.resolve()` raises ValueError on NUL)
- What: `JobPathError` subclasses ValueError, but the handlers catch the subclass only; a plain ValueError from `Path.resolve`/`stat` ("embedded null character") propagates out of `tick()` to `_loop`'s log line. Nothing posts a result.
- Failure scenario: a submitted rel_path containing a NUL (hand-written JSON, a buggy submitter) is claimed, dropped without a result, re-offered when the 300 s lease expires, and claimed and dropped by the next machine, each time looking like a machine that "went quiet mid-job" (which also earns it the lease-expiry cooldown at db.py:10744).
- Evidence: scratchpad `probe_stem.py`: `NOT JobPathError: ValueError stat: embedded null character in path`.
- Ledger: new
- Suggested fix: catch `(job_paths.JobPathError, ValueError, OSError)` around `_media_paths` / `_whisper_command` and post a non-retryable failure; or have `job_paths.resolve` convert them to JobPathError.

## Coverage note
Did not read music_clap/mel_numpy.py or music_models.py, proxy_history.py beyond confirming every write is under its lock, bpg.py's `_START_SCRIPT` PowerShell body, or proxy_gen's notifier/coverage/gap methods. Did not run the companion test files for these modules (read-only hunt; the probes above were enough to confirm). The Timeline Cards side of `out_stem` (what names the page actually sends) was not read; finding 3 stands on the claimant alone. bpg.ensure_watch_folders' handling of a CRLF settings file was looked at: the watch-list rewrite works; only the no-key case would prepend a second `[General]` section, which Qt merges, so it is not reported.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/cards_exec.py:384: the pinned executor takes `out_stem` unvalidated too (same defect as bug-comp-media-3, on the dashboard's own filesystem).
- companion/src/ccsync_companion/broll_ingest.py:750: `self.ffmpeg_path` is the bare config value too; worth checking whether broll_ingest_media spawns it unresolved (the same shape as bug-comp-media-1).
