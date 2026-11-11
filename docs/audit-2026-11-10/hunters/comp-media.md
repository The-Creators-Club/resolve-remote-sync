# comp-media - companion media stack: b-roll/music ingest, loopback server, proxy generation, sidecars
Files read (approximate coverage): broll_server.py (handler, server class, status/insert/upload paths, ~40%), broll_ingest.py (gate, tick, drain, crunch, frames, save, staging prune, uploads plan, ~55%), broll_ingest_media.py (run_ffmpeg, frame argv, ~30%), broll_upload.py (~80%), broll_fetch.py (~60%), proxy_gen.py (spawn/kill/drain, gate, tick, scan, partial sweep, ~35%), ffmpeg_tools.py (resolver, probe caches, probe_video, ~25%), music_server.py (call, probe cache, ~50%), music_worker.py (actions), music_clap_sidecar.py (session, decode, embed, hash, ~45%), broll_vlm_sidecar.py (caches, status, ~40%), broll_vlm/local_vlm.py (server lifecycle), loopback_guard.py (token), broll_standins.py (ledger shape only), startguard.py/launcher.py (worker re-entry). Grep-level only: bpg.py, sidecar_tools.py, music_ingest.py, music_clap/, ingest_kinds.py, lgpl_libs.py.
Probes run (all under scratchpad\comp-media\):
- `tasklist /FI "IMAGENAME eq Resolve.exe"` timed: 0.16 s per call (10 calls), 0.235 s per call under load (23 calls).
- Frame extraction on a synthetic 90 s 1080p h264 clip (GOP 50): 23 one-frame seek spawns 1.96 s; one `select` pass 0.64 s; 23 tasklist spawns 5.40 s.
- `json.dumps(..., indent=2)` on a synthetic ingest state shaped like `_save`'s snapshot: 400 items 15.7 ms / 1.35 MB, 2,000 items 84 ms / 6.75 MB; compact separators 2.3 ms / 0.93 MB and 13.5 ms / 4.65 MB.
- `os.walk` of a synthetic 50k-file tree, the two startup walk shapes: 0.09-0.11 s each (local NTFS, warm).
- `python -X importtime -c "import ccsync_companion.app"` (HOME pointed at scratch): 0.16 s, so the worker child's cost is the onefile extraction, not the imports.

## Findings

### comp-media-1 - Ingest asks `tasklist` before every extracted frame: the Resolve probe costs 2.7x the frames it guards
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/broll_ingest.py:2746-2751 (`_extract` calls `_should_stop()` per frame), :2287-2293 (`_should_stop` re-runs `_gate()`), :1110-1115 (idle mode + away + `skip_while_resolve` -> `_resolve_running()`), :1004-1014 (uncached); resolve_prefs.py:158 (`tasklist` spawn)
- What: `_should_stop()` re-runs the full gate between every stage, and `_make_frames` calls it before EVERY one-frame seek. In the default run mode (`idle`) with the editor away - exactly when crunching happens - the gate reaches `_resolve_running()`, which is `resolve_prefs.resolve_is_running()`: a `tasklist` process spawn, uncached here (proxy_gen caches the same probe for 60 s, proxy_gen.py:126-134, 702-722, precisely because it is a spawn). `broll_ingest_skip_while_resolve` defaults to True (config.py:546). Music inherits the same `_should_stop`.
- Cost / failure scenario: frames are every <= 4 s of clip (`MAX_GAP_S`, broll_ingest_media.py:77) plus scene cuts, so a 90 s clip makes ~23 frame seeks plus ~6 stage checks = ~29 tasklist spawns. Measured: 23 tasklist calls 5.4 s vs the 23 frame seeks themselves 1.96 s. A 400-clip card of 60 s clips is ~8,000 tasklist spawns (~30 min of wall time at 0.16-0.235 s each, run twice in parallel at the default `max_concurrent_ffmpeg = 2`); a 2,000-clip batch (the server's MAX_BATCH_ITEMS) ~40,000 spawns, 1.8-2.6 h. Each spawn is a full process snapshot on a machine the editor may return to at any moment.
- Evidence: code read above; timings in the probes list.
- Ledger: new (proxy_gen's MED-9 2026-08-11 fixed the same pattern in proxy_gen only)
- Suggested change: give the ingestor the proxy_gen shape - a TTL-cached Resolve probe (5-15 s) for the between-stage/between-frame `_should_stop`, keeping the fresh probe for the tick's `_gate()` and keeping fail-closed (an exception still reads as "running"). Secondary, measured: on short clips one `select=` ffmpeg pass over the 1080p proxy beat 23 seeks 0.64 s vs 1.96 s; worth it only below a duration threshold, because a single pass decodes the whole proxy.
- Effort / risk: S effort; low risk

### comp-media-2 - The ingest state file is re-serialised whole, pretty-printed, at every stage of every item: O(n^2) bytes written per batch
- Category: perf
- Severity: medium
- Confidence: CONFIRMED (per-save cost measured; saves-per-item counted from the code, total estimated)
- Where: companion/src/ccsync_companion/broll_ingest.py:885-929 (`_save`: `_snapshot` deep copy of `_batch` + every `_staging` drop, `json.dumps(..., indent=2)`, tmp + `os.replace`); called from 28 sites, including `_stage` :3567 and after each crunch step :2405-2453, `note_upload` :1663 (per PUT), `_pump_uploads` :3206 (per tick)
- What: every checkpoint rewrites the WHOLE batch plus every retained staging drop (kept 7 days, `DEFAULT_STAGING_RETENTION_DAYS`), with the pure-Python indent encoder, under the GIL. One item passes ~12 saves (5 `_stage` checkpoints, 5 post-step saves, the upload stage, its staging PUT), so total bytes = ~12 n x (size proportional to n).
- Cost / failure scenario: measured per save: 400 items 15.7 ms / 1.35 MB; 2,000 items 84 ms / 6.75 MB. A 400-clip card: ~4,800 saves = ~6.5 GB written to the editor's SSD and ~75 s of GIL-held CPU. A 2,000-clip card (the server's limit, broll/web/app/schemas.py:127): ~24,000 saves = ~160 GB written and ~34 min CPU (estimated from the measured per-save figures). Music (500-item cap) pays the same shape at a quarter of the scale.
- Evidence: save_probe.py in scratch (numbers above); compact separators measured 6.2-6.8x faster and 31% smaller.
- Ledger: new (comp-broll-music-1 2026-09-03 fixed this function's thread safety, not its cost)
- Suggested change: (a) `separators=(",", ":")` - a one-line 6x win; (b) coalesce: mark dirty and flush at most every 2-5 s from the tick, writing synchronously only at the transitions a restart cannot rediscover (claim, lease change, held-for-base-rig, batch end). Each crunch step already re-derives "done" from its artifact on disk (`outputs.get("proxy")` + `isfile`), so losing the last few seconds of checkpoints costs at most a re-run stage, never a wrong one. Keep the per-thread tmp name and `_save_lock`.
- Effort / risk: S for (a), M for (b); low risk for (a), medium for (b)

### comp-media-3 - The music page's 30 s Resolve-status poll re-launches the onefile companion exe every time, even with Resolve closed and the tab hidden
- Category: idle
- Severity: medium
- Confidence: CONFIRMED (mechanism read); cost estimated
- Where: music/web/static/app.js:1032 (`setInterval(refreshResolveStatus, 30000)`, no `document.hidden` check); companion music_server.py:296-304 -> :155-208 (`call` = `subprocess.run` of `worker_command`, which in a frozen build is the companion exe re-entered with `--music-resolve-worker`, :133-152); `PROBE_TTL_S = 3.0` (:221) cannot coalesce a 30 s cadence; build.spec:333 (onefile EXE)
- What: every `/music/status` is a fresh copy of the 48+ MB onefile exe: bootloader extraction to `%TEMP%\_MEI*`, interpreter start, `resolve_bridge.connect()` (a new fuscript client), then deletion. Nothing checks whether Resolve's script server is even up before spawning, so a machine with Resolve closed pays the same. `/status`, every b-roll Send to Resolve and every music send pay one extraction each too (seconds of added latency per click, estimated).
- Cost / failure scenario: 120 spawns per hour per open music tab, all day if the tab stays open. PRAC-77 measured 116 MB written per extraction, so ~14 GB/hour of %TEMP% churn and ~120 interpreter boots/hour (estimated), plus 120 fuscript connects/hour whose only purpose is a status dot. At 20 machines it is per editor.
- Evidence: code read; `import ccsync_companion.app` measured at 0.16 s, so the spawn cost is the extraction (PRAC-77's figure), not Python.
- Ledger: related to PRAC-77 (open: onefile in general) and comp-broll-music-3 (2026-09-03: fixed the burst, not the cadence)
- Suggested change: in the parent, answer without a child when `script_server.state()` (TCP table, no connection, CR-68-safe) says the server is not ready - "Resolve is not running" needs no worker. On the page, skip the tick while `document.hidden` and back off to 60-120 s. Keep the killable child for real Resolve calls (MED-3); onedir (PRAC-77) is what removes the per-call extraction.
- Effort / risk: S effort; low risk

### comp-media-4 - Ingest uploads spawn two rclone processes (copyto + lsjson verify) per artifact, five artifacts per clip, strictly one at a time
- Category: perf
- Severity: medium
- Confidence: PLAUSIBLE (the spawn count is read from the code; the per-spawn handshake cost against the NAS could not be measured under the rules)
- Where: companion/src/ccsync_companion/broll_ingest.py:2890-2927 (`_upload_plan`: poster, sprite, preview proxy, edit proxy, original); broll_upload.py:504-582 (`run_upload`, one `rclone copyto` per job), :585-623 (`verify_upload`, one `rclone lsjson` per job), :447-500 (single active job)
- What: each artifact is its own rclone process and its own SFTP session, followed by a second process and session that lists the file to compare its size. rclone `copyto` already fails a transfer whose size differs ("corrupted on transfer: sizes differ"), and the server stats every file before flipping the row live (broll_upload.py:196-203 says so), so the lsjson is a third size check that costs a full process + SSH handshake each time.
- Cost / failure scenario: 10 rclone spawns and 10 SSH handshakes per clip, serial. 400 clips = 4,000; 2,000 clips = 20,000. At an estimated 0.5-1 s per spawn+handshake over the tailnet that is ~0.5-1 h (400) or ~3-5.5 h (2,000) of pure overhead before any bytes move, and three of the five files per clip are sub-MB JPEG/sprite files where the handshake IS the cost.
- Evidence: code read; no NAS probe (forbidden).
- Ledger: new
- Suggested change: drop `verify_upload`'s lsjson (rclone's own post-transfer size check plus the server's stat remain); send poster + sprite in one `rclone copy --files-from` call (their names are server-allocated `posters/<id>.jpg` / `sprites/<id>.jpg`, so stage them under that layout). Must keep: original enqueued first (comp-broll-music-3), `copyto` for server-chosen names, the `.partial`-on-the-far-side behaviour.
- Effort / risk: S (drop lsjson) / M (batch stills); low / medium risk

### comp-media-5 - Startup walks the whole tree twice for two leftover-file sweeps that were meant to share one walk
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/proxy_gen.py:429-479 (`sweep_stale_partials`, its own `os.walk(local_root)`); app.py:11827-11879 (called right after `fixer.walk_ccsync_tmp_files`, whose docstring at fixer.py:784-790 says it was split out so the sweeps "share ONE walk of the tree at startup instead of two", COMP-GUARD-1)
- What: the `.partial` sweep was added after COMP-GUARD-1 and re-walks the same tree with the same hidden-dir pruning, looking for a second suffix. Not gated on mode, so on the base rig it walks `P:\` over SMB.
- Cost / failure scenario: once per companion start; PRAC-77 counted 24 of 55 starts as restarts on Resolve exit, so several per day. Measured 0.1 s per walk for 50k local files; on the base rig's SMB tree (tens of thousands of files x ~100 projects) estimated tens of seconds of NAS metadata traffic per start, doubled for nothing.
- Evidence: code read; walk_probe.py.
- Ledger: related to COMP-GUARD-1 (fixed 2026-08-14)
- Suggested change: have `walk_ccsync_tmp_files` also collect `Proxy/*.partial` (same loop, second suffix) and pass the list to `sweep_stale_partials`, as `tmp_files` is passed to the reservation sweep.
- Effort / risk: S effort; low risk

### comp-media-6 - llama-server's log is appended for the life of the install
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED (growth); size estimated
- Where: companion/src/ccsync_companion/broll_vlm/local_vlm.py:167-170 (`open(log_path, "a")` per server start); broll_vlm_sidecar.py:127-132 (`~/.ccsync/state/broll_vlm_server.log`); nothing in the package truncates or rotates it
- What: every server start appends a banner, the model-load output and every request line. The server is stopped whenever the gate closes (editor back, broll_ingest.py:2177-2182) and restarted on the next idle window, so starts are frequent on a working machine.
- Cost / failure scenario: estimated ~20-50 KB per start plus ~1-2 KB per described clip; a few MB per thousand clips, never reclaimed. Small, but it is the one file in `state/` with no bound, and its path is named in the failure message editors are told to read.
- Evidence: code read.
- Ledger: new
- Suggested change: at `start_server`, if the log exceeds ~5 MB, rename it to `.1` (one generation) before opening; the failure message still names a current file.
- Effort / risk: S effort; low risk

## What is already good
- The 8899 loopback: HTTP/1.0 close-per-request, `daemon_threads` (no `_threads` accumulation), bodies read in bounded chunks with a byte limit enforced on bytes READ, `.partial` + rename for PUTs, origin allow-list rebuilt at most every 30 s by one thread, status probes coalesced behind one in-flight slot with a capped slot dict.
- Child hygiene: proxy_gen drains stderr into a 200-line deque and `-progress` on its own thread, kills with a bounded wait, below-normal priority; `run_ffmpeg`/`_run` publish the Popen so stop/cancel can kill it and drain after a timeout kill; rclone readers kill on reader failure.
- Model memory: llama-server (4-12 GB VRAM) and the ONNX session (~300 MB) are both released the moment the gate closes; GPU/readiness probes are TTL-cached and `status()` is zero-I/O.
- `ffmpeg -version` successes cached 300 s, encoder list cached for the binary's life; `content_hash` streams 1 MiB blocks; upload queues are per batch and dropped at batch end; fetch registry popped on read and by `reap_finished`.

## Coverage note
Not read in depth: bpg.py, sidecar_tools.py (download/verify), music_ingest.py beyond its hash wiring, music_clap/mel_numpy.py, broll_vlm/local_runtime.py, compact_format/contract, lgpl_libs.py, the edit-proxy decision path and stand-in upgrade worker in broll_server.py. Known and not re-reported: bug-comp-media-7 (music decode holds the whole track's PCM, partly fixed), PRAC-76 (onnxruntime import commits ~740 MB), PRAC-77 (onefile exe). Minor, not filed: with `max_concurrent_ffmpeg = 2` the two frame threads overwrite one `_child` slot, so stop() can miss one short frame ffmpeg (<1-2 s).

## OUT OF TERRITORY
- companion/src/ccsync_companion/app.py:7749 / :8069: `ingest_staging_report` walks every retained staging drop on every report; small locally, but it is a per-report tree walk with no cache.
- companion/src/ccsync_companion/resolve_prefs.py:143-171: `tasklist` is the process probe for every Resolve gate in the companion; a ctypes `EnumProcesses`/`CreateToolhelp32Snapshot` check would avoid a 0.16-0.24 s process spawn (measured) for every caller (jobs_runner, proxy_gen, ingest).
