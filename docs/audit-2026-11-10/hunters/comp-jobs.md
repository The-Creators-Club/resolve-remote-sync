# comp-jobs - companion fleet job runner, media recipes, YouTube executor and its sidecar manager

Files read (approximate coverage): `companion/src/ccsync_companion/jobs_runner.py` (all), `jobs_media.py` (all), `proc_tree.py` (all), `ytdl_executor.py` (~70%: http/run seams, Deps, capabilities, DownloadJob end to end, build_argv, edit-ready conversion; skimmed the module tail and the dedupe helpers), `ytdlp_manager.py` (constants, ensure, loop; ~40%), `ytdl_server.py` / `ytdl_browser_login.py` / `ytdl_cookies.py` / `ytdl_attestation.py` / `ytdl_common.py` / `job_paths.py` (outline + spawn/pipe sites only). Context: `capabilities.py` `_build` and `_resolve_block`, `resolve_prefs.resolve_process_state`, `app.py` job-runner wiring, report-reply hand-off and shutdown order, `sidecar_tools.ensure_ffmpeg_pair`, `proxy_gen.sweep_stale_partials`, `broll_ingest.default_request`, `docs/API.md` 6c, ccsync `CLAUDE.md` jobs paragraphs.

Probes run (all under the scratch folder `comp-jobs\`, companion venv, nothing live touched):
- `tl.py` / `tl2.py`: 10 x the exact `tasklist /FI "IMAGENAME eq Resolve.exe" /NH` spawn `resolve_process_state` makes: median 0.164 s wall (0.133-0.196), 0.016 s CPU in tasklist itself (the rest is process start and the enumeration it asks for).
- `count.py`: real `JobRunner.tick()` with counting seams: capabilities() calls and Resolve process probes per tick in three gate states.
- `stale.py`: real `JobRunner` with a transport-failing `request_fn` and one stale offer: 10 ticks -> 10 claim attempts, 10 tracebacks, offer never cleared, state stays `ready`.
- `peaks.py`: `jobs_media.peaks_bytes` over synthetic s16le PCM delivered in the drain's 1 MiB chunks, under tracemalloc, against a streaming binner: 1 h clip +288 MB transient, 3 h clip +864 MB transient (on top of the PCM chunks themselves); the streaming version produces byte-identical output with ~10 MB extra.

## Findings

### comp-jobs-1 - The peaks recipe holds the whole decoded audio in RAM, then makes five more copies of it
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/jobs_media.py:717 (`b"".join(chunks)`), :340-343 (`peaks_bytes`), :721-736 (`_drain_binary` appends every 1 MiB block to a list)
- What: `_read_pcm` keeps every PCM block the drain reads in `chunks`, joins them into one bytes object (2x), and `peaks_bytes` then does `astype("int32")` (4x more) and `np.abs` (another 4x) before reducing to one byte per 40 samples. Peak transient is about 6x the PCM size, inside the companion process, on an editor's machine.
- Cost / failure scenario: 8 kHz mono s16 is 57.6 MB per hour of audio. Measured transient on top of the chunk list: 288 MB for a 1 h clip, 864 MB for a 3 h interview recording (plus the 173 MB chunk list = ~1.04 GB resident for one job). Runs once per `peaks` job, one per clip a Cards lane touches; interviews of 2-3 h are the normal input. The companion runs for weeks beside Resolve; a 1 GB spike can push a 16 GB machine into paging while Resolve is open (the idle gate does not require Resolve closed when `jobs_skip_while_resolve_running` is off, and the base rig, which is the preferred machine for this kind, routinely has Resolve open). Python returns most of that to the OS afterwards, but the high-water mark is what pages.
- Evidence: `peaks.py` probe: `1.0h: pcm 58 MB in chunks; join+peaks peak extra 288 MB`; `3.0h: pcm 173 MB in chunks; join+peaks peak extra 864 MB`; streaming binner `identical=True`.
- Ledger: new (comp-ytdl-jobs-4 / CR-237 fixed the drain's truncation, not its size)
- Suggested change: bin in the drain thread as blocks arrive (carry the remainder of each block to a multiple of 80 bytes; numpy per block), so the job holds ~2 MB of peaks instead of the PCM. Output is byte-identical (proved by the probe), so the verbatim pin against `library_engine._peaks_make` (which pins BYTES, not the algorithm) still holds. Must keep: the `pcm_thread.is_alive()` truncation check and `failure` hand-back of comp-ytdl-jobs-4.
- Effort / risk: S effort; low risk

### comp-jobs-2 - Every job-runner tick spawns `tasklist` 1-4 times, even when nothing can be claimed
- Category: idle
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/jobs_runner.py:729 (`runnable_kinds()` in `_gate`), :682 (`_capabilities()`), :758 (`_resolve_running()`), :817-818 (`_claim` calls `_capabilities()` and `runnable_kinds()` again), :1218 (`_execute_media` again for `nvenc`); capabilities.py:318 (the cached path still calls `resolve_running_fn` every time); resolve_prefs.py:158 (`tasklist` spawn)
- What: `_gate` asks `runnable_kinds()` to learn whether this machine has ffmpeg/whisper at all, and that goes through `app.job_capabilities` -> `capabilities.build`, whose 60 s cache deliberately re-evaluates the Resolve block on every call, i.e. spawns `tasklist`. The gate then spawns it again for its own Resolve check, and a claim spawns it twice more. The hardware answer `runnable_kinds` needs is already cached; only the Resolve probe is not.
- Cost / failure scenario: measured per tick: editor present 1 spawn; machine idle 2; idle with an offer 4 (+1 per media job). Cadence: 20 s (`jobs_poll_seconds`) whenever the dashboard's queue is non-empty, even with jobs this machine cannot run (a whisper backlog on a fleet of laptops); 80 s when it is empty. So 45-360 `tasklist` spawns an hour per machine from this thread alone, each ~0.16 s wall and a full process enumeration, around the clock, on every editor machine for weeks, beside Resolve. The reporter's capabilities section adds one more per report (out of territory, same root). At 20 machines the fleet is doing ~7,000 process enumerations an hour to answer "is Resolve open" for a gate whose answer changes a few times a day.
- Evidence: `count.py`: "editor at keyboard, empty queue: capabilities() calls 1, Resolve process probes (tasklist) 1"; "machine idle, empty queue: ... 2"; "machine idle, offer present: capabilities() calls 3, Resolve process probes 4, next wait 20.0 s". `tl.py`: tasklist median 0.164 s.
- Ledger: new
- Suggested change: (a) in the runner, read capabilities ONCE per tick and pass the dict to `runnable_kinds`/`_claim`/`_execute_media`; (b) answer "which kinds can I run" from the cached hardware fields only (a `capabilities.hardware()` accessor that skips the live Resolve/idle/cards blocks); (c) put a short shared TTL (5-10 s) on `resolve_process_state`, keeping fail-closed on `None`. The gate still checks Resolve fresh enough for the claim, and the claim body still carries a live Resolve block.
- Effort / risk: S effort; low risk

### comp-jobs-3 - A stale offer plus an unreachable dashboard: a claim attempt and a full traceback every 20 s, and the gate says "ready"
- Category: bug
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/jobs_runner.py:826 (`_claim` lets the transport exception from `default_request` escape), :1033-1038 (`_offered` is cleared only when `_claim` RETURNS None), :1011 (`log.exception("jobs: the runner tick failed")`), :592-593 (`wait_seconds` stays at the 20 s base while anything is offered); app.py:2651-2655 (offers are only replaced by a SUCCESSFUL report reply)
- What: `broll_ingest.default_request` raises on a refused connection, DNS failure or timeout. `_claim` does not catch it (`_heartbeat` does, since comp-ytdl-jobs-1), so the tick raises out, `_offered` is never cleared, and the state stays `ready`. Nothing else clears the offer while the dashboard is unreachable, because only a delivered report reply replaces it.
- Cost / failure scenario: a laptop is offered a job, then the editor takes it off the tailnet (or the dashboard is mid-redeploy, or its image pull takes minutes). From then on, every 20 s: one claim attempt (up to `HTTP_TIMEOUT_SECONDS` = 20 s blocked on a black-holed address), 1-4 `tasklist` spawns (comp-jobs-2), and a multi-line traceback in the companion log, for as long as it stays offline. That is 180 tracebacks an hour (~0.2-0.5 MB/hour, ~5-10 MB a day), which the rotating log handler spends by evicting the history the diagnostics bundle needs. Meanwhile Settings -> JOBS and the report's `jobs_gate` say "This computer is ready for fleet work".
- Evidence: `stale.py`: "claims attempted 10 offered still [5] state ready wait 20.0"; "log bytes for 10 ticks 11930 traceback lines 10" (short synthetic traceback; a real urllib one is longer).
- Ledger: new (the heartbeat half was comp-ytdl-jobs-1; this is the claim half of the same shape)
- Suggested change: catch transport failures in `_claim` like `_heartbeat` does: log one INFO line, clear `_offered` (the offer is an invitation and the next report reply re-issues it), return None, so the tick lands in `nothing_offered` and the backoff applies. Must not treat a 401/403 differently from today (wire-5).
- Effort / risk: S effort; low risk

### comp-jobs-4 - Two machines can write the same `.partial` in the shared vault after a lease expiry, and the loser deletes the winner's file
- Category: concurrency
- Severity: low
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/jobs_media.py:979 (`partial = <final>.partial`, the same name on every machine), :366-381 (`claim_partial` is an in-process set), :428-435 (`discard`); jobs_runner.py:851-875 (a heartbeat transport failure keeps the job running past its lease)
- What: rule 2 ("never two writers on one output") is enforced per process. The output is in the vault every machine shares, and the fleet lease is the only cross-machine guard. `_heartbeat` deliberately keeps working through transport failures, so a dashboard outage longer than the 300 s lease lets the scheduler re-offer the job while machine A is still encoding.
- Cost / failure scenario: dashboard unreachable for more than 300 s (a redeploy whose health check stalls, a NAS reboot) while A encodes a long 480p proxy. B claims the requeued job and starts ffmpeg `-y` on the same `.partial`, truncating A's. When A's next heartbeat gets 410 it kills its ffmpeg and `discard()`s the `.partial`, which is now B's in-progress file. B's `os.replace` then fails ("could not put the finished file in place") and the job fails retryable after minutes of encode on two machines. If the timing is the other way round, a file stitched from two writers can be published.
- Evidence: code reading of the three sites above, plus the lease/heartbeat contract in `docs/API.md` 6c. Not reproduced; it needs a real lease expiry.
- Ledger: new
- Suggested change: make the partial name per machine and per job (`<final>.<job id>.partial`). It still ends in `.partial`, so every lane filter excludes it, and `discard` can then only ever remove its own bytes. `_publish`'s re-check stays the arbiter of who wins.
- Effort / risk: S effort; low risk

### comp-jobs-5 - Media recipes spawn one more ffprobe than they need
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/jobs_media.py:894-897 (`proxy-480p`: `probe_video` then `probe_audio`, two ffprobe runs over the same source), :939 (`peaks`: `probe_audio` before every decode, used only for the realtime figure and the no-audio verdict on FAILURE)
- What: the proxy recipe opens the source twice to read the first video and the first audio stream. The peaks recipe probes up front for a duration that only feeds the `realtime` metric and a verdict needed only when the decode fails.
- Cost / failure scenario: one extra ffprobe spawn per proxy job and per peaks job (estimated 0.1-0.3 s each, longer on an SMB vault, with a PROBE_TIMEOUT of 120 s each on a wedged share). Cards touches every clip of an episode, so this is hundreds of spawns per episode on whichever machines take the work.
- Evidence: code reading. Not timed (no media in scratch).
- Ledger: new
- Suggested change: one ffprobe with `-show_entries stream=codec_type,codec_name,duration,width,height,avg_frame_rate,r_frame_rate` for the proxy; for peaks, probe only after a non-zero exit, and take the realtime figure from the PCM length (`len(raw) / 16000` s). Neither touches an argv the page reads, so the verbatim pin is unaffected.
- Effort / risk: S effort; low risk

## What is already good
- The ytdl executor makes no idle calls at all: it runs only when a page dispatches a job through 8899, and its capabilities answer is cache-only by design. Its heartbeat, retry budget (elapsed-time, 60 s with 2-15 s backoff), lease-loss and tree kill (`proc_tree.kill_tree` with taskkill /T) are sound.
- `jobs_runner` already backs off to 80 s on an empty queue, and `_wake` makes the backoff free for a new offer. `_recent` (10), `_local_cancel` (16) and the whisper output tail (2,000 lines, 4,000 chars sent) are all bounded.
- Every ffmpeg/yt-dlp pipe is drained on its own thread with a bounded sink; `stdin=DEVNULL` everywhere; below-normal priority for the media recipes.
- `ytdlp_manager`'s daily `--update-to nightly` is throttled by a persisted 20 h stamp, a failed pass backs off exponentially to a day, and the disabled-feature 15 min pass does only stat()s (`sidecar_tools.ensure_ffmpeg_pair`).

## Coverage note
Did not read `card_copy.py`, `ledger_scan.py`, `sorter_cards.py` (the card-ingest/drive-copy/ledger-scan kinds dispatched from this runner) or the rest of `ytdl_executor.py` (dedupe/id-bearing file helpers, the module-level `start`/`snapshot`/`progress` mirror). `ytdl_browser_login.py` and `ytdl_cookies.py` were only checked for spawn and pipe handling. I did not measure whisper VRAM. It runs as a subprocess that exits per job, and the runner will not claim while Resolve is running (`jobs_skip_while_resolve_running`, default on), so model load/unload is the pipeline's own business.

## OUT OF TERRITORY
- companion/src/ccsync_companion/capabilities.py:318 + reporter: every report (5-60 s) spawns `tasklist` through the same uncached Resolve block. Fix it with the shared TTL in comp-jobs-2.
- %LOCALAPPDATA%\Temp: two 119 MB `_MEI*` dirs dated 2026-11-05 21:52 sit beside today's live 125 MB pair (15:21), plus about 36 small 1 MB `_MEI*` dirs from 09-17..10-03. Those look like PyInstaller one-file extractions left by companion runs that were killed instead of exiting (supervisor relaunch / Stop-Process / upgrade). Nothing prunes them: about 240 MB here.
