# comp-ytdl-jobs — the companion's fleet-jobs runner, media recipes, job paths, and the whole local ytdl executor

Files read (with approximate coverage):
- `companion/src/ccsync_companion/job_paths.py` (100%)
- `companion/src/ccsync_companion/jobs_runner.py` (100%)
- `companion/src/ccsync_companion/jobs_media.py` (100%)
- `companion/src/ccsync_companion/ytdl_executor.py` (~85%: all of the fleet client, the claim/lease/heartbeat path, `_download_all`/`_download_one`, `build_argv`, the cookie inversion, `_ensure_edit_ready`/`swap_in`, the file-litter helpers, the module guard; skimmed `Deps`, `write_sidecar`)
- `companion/src/ccsync_companion/ytdlp_manager.py` (~70%: install/verify/`ensure`/version ranking/URL pinning; skimmed the daily loop)
- `companion/src/ccsync_companion/ytdl_cookies.py` (100%), `ytdl_attestation.py` (100%), `ytdl_server.py` (100%)
- `companion/src/ccsync_companion/ytdl_browser_login.py` (~80%), `youtube_import.py` (~40%: the scan/settle/name-filter half)
- `companion/src/ccsync_companion/capabilities.py` (the `idle_seconds`/cache/`job_kinds` half)
- Both sides of the wire: `dashboard/src/ccsync_dashboard/api.py` §`/jobs/*` + the report reply's `commands.jobs` block, `db.queue_depth`/`fail_job`/`job_retry_budget`
- `companion/tests/test_jobs_phase4.py`, skimmed `test_jobs_runner.py`, `test_jobs_media.py`
- `CLAUDE.md`, `KNOWN_BUGS.md` (grepped: CR-31, CR-68, CR-79, CR-80, YT-1/3/6, YTDL-3/15/17/22/23, COMP-BROLL-*)

Tests run:
`companion\.venv\Scripts\python.exe -m pytest tests/test_jobs_media.py tests/test_jobs_phase4.py tests/test_jobs_runner.py tests/test_youtube_import.py tests/test_ytdl_browser_login.py tests/test_ytdl_cookies.py tests/test_ytdl_executor.py tests/test_ytdl_feature_gate.py tests/test_ytdl_root_guard.py tests/test_ytdl_server.py tests/test_ytdlp_manager.py -q` -> **600 passed**.
Plus three ad-hoc probes from the companion venv (scratchpad, not in the repo).

Also verified clean (no finding): `ytdl_common.py` is byte-identical to `ytdl/web/ytdlweb/ytdl_common.py` below the vendoring marker; `ytdl_attestation.TEXT_VERSION` == `ytdlweb.attestation.TEXT_VERSION`; no em dashes in any user-visible string in the territory; `job_paths.resolve` correctly refuses `/abs`, `C:\abs`, `\\UNC`, and `..` (raw-value check before stripping, `resolve()`-based containment so an in-root symlink out is also refused); `_execute`'s dispatch cannot run `conform`/`resolve-edit` (unknown kind -> `retryable=False` hand-back); cookie CONTENT is never logged or posted (only a fixed `STALE_SIGNATURES` phrase reaches `mark_stale`); the yt-dlp install path is sha256-verified against the release's own `SHA2-256SUMS`, redirect-pinned to GitHub hosts, size-capped, exec-bit set only after verification, and `os.replace`d atomically; `default_run` passes `resolve_bridge.sanitized_child_env()` (the schtasks/stripped-env hang).

## Findings

### comp-ytdl-jobs-1 — one failed heartbeat HTTP call destroys a running whisper job
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/jobs_runner.py:869` (inside `_run_child`'s `try:` whose `except Exception` at :885 terminates the child), reached through `_heartbeat`:523 -> `_call`:484 -> `broll_ingest.default_request`:191 (which raises on any transport failure, by design)
- What: `JobRunner._heartbeat` has no transport-failure tolerance at all. A `URLError`/`ConnectionRefusedError` from one heartbeat POST propagates out of `_heartbeat`, is caught by `_run_child`'s catch-all, and that handler's response is `_terminate(proc)` + `return False, tail, str(exc)`. The module docstring's own claim — "Beat every 30 so a machine has to miss ten in a row before it is treated as gone" (:97-99) — is not implemented: the tolerance is zero.
- Failure scenario: an editor's machine is 18 minutes into a GPU whisper pass. The dashboard container restarts (stage-verify-swap, ~3 s; the exact event of CR-31). The next 30 s beat raises `ConnectionRefusedError`; the child is terminated, the job is posted failed with `retryable=True` and error text `"[Errno 111] Connection refused"`. `db.fail_job` re-queues it, counts an attempt, and — because `retryable` is True — puts a 120 s `set_machine_job_cooldown` on the machine that just did the work. Every machine running a job across that restart does this at once; three such events and the job is `abandoned` (`JOB_RETRY_BUDGET_DEFAULT = 3`). Minutes-to-hours of GPU work per machine, thrown away by an outage nobody saw.
- Evidence: ad-hoc probe with a `request_fn` that raises `OSError` only on `/heartbeat`:
  ```
  jobs: the transcription child failed
  Traceback ... OSError: tailnet blip
  ok=False err='tailnet blip'  proc.returncode=-15  http calls=1
  ```
  One raised call, child terminated (`-15`), job failed. Compare `ytdl_executor.FleetClient._call` (:1024), which retries exactly this for `CALL_RETRY_BUDGET_SECONDS`, and `DownloadJob._heartbeat_loop` (:1953-1961), which explicitly swallows a non-410 heartbeat failure with the comment "A blip, not a verdict".
- Ledger: new — but it is **CR-31's shape reproduced in a module written after CR-31 was fixed**. The ytdl executor learned this lesson; `jobs_runner` did not inherit it.
- Suggested fix: wrap the `self._call` in `JobRunner._heartbeat` so a raised transport failure returns `True` (keep going) and only a real `410` returns `False`, exactly as `_heartbeat_loop` does; optionally count consecutive failures and only give up after the lease could plausibly have lapsed.

### comp-ytdl-jobs-2 — a raising heartbeat silently kills the media beater thread, and the encode runs on with an expired lease
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/jobs_runner.py:703-711` (`_execute_media`'s `beat()`)
- What: `beat()` calls `self._heartbeat(...)` with no `try`. The same transport failure as finding 1 raises out of the thread target, so the daemon thread dies permanently after the first blip. Nothing sets `lease_lost`, so `should_stop()` never learns; the ffmpeg keeps running to completion with no further heartbeats. In a frozen windowed build the `threading.excepthook` traceback goes to a stderr that does not exist, so this is completely silent.
- Failure scenario: a `proxy-480p` job is 4 minutes into a libx264 encode when the dashboard blips. The beater dies. At 300 s (`db.JOB_LEASE_SECONDS`) `expire_leases` re-queues the job and offers it to a second machine, which starts the same encode. The first machine finishes, `_publish`'s re-check discards its own output (rule 2 saves the *file*), and its `_post_result` 410s and is swallowed. Net result: the encode is done twice, the "one job at a time / possession expires" contract is honoured only by accident, and no log line anywhere says a heartbeat stopped.
- Evidence: source inspection — `beat()` is `while not finished.wait(HEARTBEAT_SECONDS): if not self._heartbeat(...): lease_lost.set(); return`, with no exception handling anywhere in the closure or on the thread. Same root cause as finding 1 (`_heartbeat` raises), different and quieter consequence. `_run_child`'s equivalent at least fails loudly.
- Ledger: new (same root cause as comp-ytdl-jobs-1).
- Suggested fix: fixing `_heartbeat` to swallow transport failures (finding 1) fixes this too; regardless, `beat()` should have its own `try/except Exception: log.debug(...)` so no exception can ever kill the beater.

### comp-ytdl-jobs-3 — the queue-depth backoff never fires, and its test pins a shape the wire never carries
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/jobs_runner.py:318-325` (`wait_seconds`) against `dashboard/src/ccsync_dashboard/api.py:7780-7781` (`if depth["queued"] or depth["running"] or depth["pinned"]: block["queue"] = depth`)
- What: the dashboard **omits** the `queue` block entirely when the queue is empty. The companion's `wait_seconds` returns the base interval when `not depth`. So the exact state phase 4's backpressure was written for — "a dashboard that says the queue is EMPTY is a dashboard that will have nothing for a while" — is the one state in which the depth signal is absent and the backoff cannot engage. The backoff is reachable only when `pinned > 0` and both `queued` and `running` are 0, a rare corner.
- Failure scenario: eight idle editor machines with an empty fleet queue keep waking every `jobs_poll_seconds` (20 s) for ever; the documented "back off to 80 s" never happens on any real deployment.
- Evidence: both sides read directly. Also `companion/tests/test_jobs_phase4.py:46-50` (`test_an_empty_queue_makes_this_machine_ask_less_often`) feeds `{"queued": 0, "running": 0, "pinned": 0, "oldest_age_s": None}` — a block the dashboard never sends — while `:74-78` (`test_a_dashboard_too_old_to_send_a_depth_keeps_the_old_cadence`) pins the *no-backoff* answer for an absent block, which is what a live empty-queue reply actually looks like. The suite therefore green-lights the broken behaviour under a name that says the opposite.
- Ledger: new.
- Suggested fix: either always send `block["queue"] = depth` from the dashboard (the block is present whenever there is anything to say, and "nothing to say" is itself the signal), or treat an absent-but-jobs-block-present depth as empty on the companion side. Whichever is chosen, the phase-4 test must feed the shape the dashboard really emits.

### comp-ytdl-jobs-4 — a stalled ffmpeg makes a `peaks` job ignore cancel, halt, shutdown and its own ceiling for ever
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/jobs_media.py:646` (`_read_pcm`'s `block = proc.stdout.read(1 << 20)`)
- What: `proc.stdout` is a `BufferedReader` (binary, no `TEXT_UTF8`), so `read(1 MiB)` blocks until a full megabyte or EOF. `should_stop()` and the `ceiling` are only consulted *after* a block returns. An ffmpeg that produces nothing further — a source on a share that went away mid-decode, a device in an uninterruptible wait — parks the job thread indefinitely. Every other stop path in this module (`_run_ffmpeg`) polls on a 0.5 s timer precisely to avoid this; `_read_pcm`'s docstring claims the chunking is what makes a stop "honoured within a chunk instead of within half an hour", but a chunk that never completes is unbounded.
- Failure scenario: an admin clicks `[ CANCEL ]` or a fleet halt lands during a peaks job on a clip whose SMB share has dropped. Nothing stops. The beater keeps renewing the lease every 30 s, so the dashboard sees a healthy running job for ever and `expire_leases` never reclaims it; the companion's own "one job at a time" guard means that machine takes no further work until the tray is restarted.
- Evidence: `_popen(cmd, binary_stdout=True)` (:428-458) skips `ffmpeg_tools.TEXT_UTF8`, leaving a binary buffered pipe; Python's `BufferedReader.read(n)` returns short only at EOF. Contrast `_run_ffmpeg`:560-569, which is a `poll()` + `time.sleep(POLL_SECONDS)` loop with both the stop check and the ceiling inside it. Not reproduced against a real hung ffmpeg, hence PLAUSIBLE.
- Ledger: new.
- Suggested fix: read with a small non-blocking/`selectors`-based loop, or drain stdout on its own thread (as `_run_ffmpeg` already does for the progress pipe) and keep the stop/ceiling check on a `POLL_SECONDS` timer in the caller.

### comp-ytdl-jobs-5 — a cancelled or halted AAC copy leaves its `.partial` behind
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/jobs_media.py:787-806` (`MediaJob._attempt_copy`)
- What: `_attempt_copy`'s `try/finally` releases the in-process claim but never discards the file. `_run_ffmpeg` raises `MediaJobError` for a stop (cancel, fleet halt, shutdown, lost lease), a timeout, or a failed spawn, and on that path the `<stem>.m4a.partial` stays on disk. Its sibling `_with_partial` (:894-904) does `discard(partial)` on exactly these exceptions — the two writers in one module disagree about their own rule 2.
- Failure scenario: an operator cancels a batch of `audio-extract` jobs mid-flight; every cancelled clip leaves a partial (up to full track size) in `<episode>/Script Docs/remote_audio/source/`, and nothing on any machine ever removes it (no age sweep exists for these). Contained (`.partial` is excluded from every lane), so it costs disk, not correctness.
- Evidence: source read; the only `discard(partial)` in `_attempt_copy` is on the "copy is not usable" success path (:803), inside the `try`, after `_run_ffmpeg` has returned normally.
- Ledger: new.
- Suggested fix: give `_attempt_copy` the same `except MediaJobError: discard(partial); raise` that `_with_partial` has (or route it through `_with_partial`).

### comp-ytdl-jobs-6 — the "could not put the finished file in place" message names a file the very next line deletes
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/jobs_media.py:407-409` (`_publish`) and `:896-899` (`_with_partial`)
- What: `_publish` raises `MediaJobError("could not put the finished file in place ({exc}) -- it is still there as {partial.name}")`; `_with_partial` calls `_publish` inside a `try` whose `except MediaJobError:` immediately does `discard(partial)` and re-raises. The sentence is the job row's `last_error`, so an admin is told to go and look at a file that has already been removed.
- Failure scenario: an `os.replace` fails (a Windows share holding the target open, a permissions change on the vault). The job row reads "it is still there as `<clip>.m4a.partial`"; the admin looks, finds nothing, and concludes the vault path in the message is wrong.
- Evidence: source read, both call sites.
- Ledger: new.
- Suggested fix: either have `_with_partial` not discard on a publish failure (which is what the message promises and is the safer choice — the encode is finished work), or reword the message to say the finished file was discarded.

## Coverage note
- `youtube_import.py` was read only for the scan/settle/name-filter half; `_import_batch`, `_canonical_spelling` and `_pool_path_alias` (the Resolve media-pool side) were not audited.
- `ytdlp_manager`'s daily loop (`start`/`_loop`/`_enforce_max_age`) and `fetch_client_config` were skimmed, not traced.
- I did not exercise the ytdl executor end to end against a live dashboard; every ytdl finding-candidate I chased there turned out to be already defended (the CR-80 anonymous-first inversion, the CR-79 conversion + `swap_in` fallbacks, the YT-6 `.converted`/`.original` naming, `disown_output`/`clear_partials` id-scoping, `_label_is_ours`, `destination_for`'s canon+`normalized_safe_rel`, `url_is_youtube`, the three feature gates — `youtube_download` for the whole `/ytdl` surface including `reveal`/`fetch`, `ytdl_local_downloads` for execution, `youtube_unblock` for the cookie jar, all failing closed).
- The suite does not cover: any transport failure on the jobs-runner heartbeat path (findings 1 and 2 — every jobs test's `request_fn` returns a status, never raises); a `_read_pcm` whose child stops producing output; the `.partial` left by a stopped `_attempt_copy`.
- `JobRunner.wait_seconds()` is called from `_loop` **outside** the `try` that guards `tick()`, and it does bare `int()`/`float()` on values from the report reply and from config. A non-numeric `queue.queued` or `jobs_poll_seconds` would raise there and kill the jobs thread for the rest of the session, silently. Not reachable from the current dashboard (it sends ints), so I have not written it up as a finding, but the guard is one line and the loop is a daemon thread nobody watches.
- The browser sign-in's DevTools port is an unauthenticated local API over a live Google session for the minutes the flow lasts; this is explicitly reasoned about in the module docstring and accepted, so I have not filed it. `free_port()` is a bind-then-close TOCTOU (a lost race shows up as the harmless "never became reachable" refusal). `netscape_text` filters `\t` in the name and `\t`/`\n` in the value but not `\n` in the name or anything in `domain`/`path` — theoretical only, since CDP cookie names cannot contain newlines.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/api.py:7780` — the `commands.jobs.queue` block is omitted on an empty queue, which is the dashboard half of comp-ytdl-jobs-3; whichever side is fixed, the two must be decided together.
