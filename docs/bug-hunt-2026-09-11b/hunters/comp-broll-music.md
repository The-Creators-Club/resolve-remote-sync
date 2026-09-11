# comp-broll-music - the companion's b-roll / music loopback, ingest orchestrator, upload queue and CORS gate

Files read (with approximate coverage): `companion/src/ccsync_companion/broll_ingest.py`
(the whole 2026-09-11 diff plus `run`/`retry`/`_item_from_manifest`/`_crunch_item`/
`_enqueue_uploads`/`_resend_uploads`/`_pump_uploads`/`_maybe_finish`/`_next_item`/
`_drain`/`tick`/`prune_staging`/`_note_staging_ended`/`staging_report`/`_space_refusal`,
~60%), `music_ingest.py` (100% of the diff, ~70% of the file),
`broll_upload.py` (~80%), `broll_fetch.py` (diff + `poll_fetch`, ~40%),
`broll_server.py` (diff + the retry handler, `do_PUT`/`_stream_body_to`/
`_upload_body_ok`/`configured_port`/`start`, ~35%), `music_server.py` (diff +
`build_send_response`, ~20%), `loopback_guard.py` (docstring + constants, ~30%),
`companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py` (100%).
Second sides read outside my territory, for the wire only: `broll/web/static/ingest.js`
(the retry/run dispatches), `music/web/static/ingest.js` (`miRetryFailed`),
`music/web/musicweb/ingest_batches.py` (`retry_detail`, `allocate_name`).

Tests run: `cd companion; .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_comp_broll_music.py tests/test_broll_ingest.py tests/test_music_ingest.py tests/test_broll_upload.py tests/test_broll_fetch.py tests/test_loopback_guard.py tests/test_broll_server.py tests/test_music_server.py -q` -> 570 passed, 1 skipped.

## Findings

### comp-broll-music-1 - the b-roll RETRY FAILED button now claims the batch with no staging id, so every clip in it fails at once
- Severity: high
- Confidence: CONFIRMED
- Where: `broll/web/static/ingest.js:1718` (`ingestRetryFailedBatch`), against
  `companion/src/ccsync_companion/broll_ingest.py:1761` (`_item_from_manifest`)
  and `:2130` (`_crunch_item`'s source check)
- What: this afternoon's broll-1 fix replaced the retry dispatch with
  `POST /broll/ingest/run {batch_uid, staging_id: null}`. `run()` only looks
  up `self._staging[staging_id]`, and `_item_from_manifest(entry, None)` is
  the sole place `local_path` is ever populated, so with `staging_id: null`
  every item of the re-claimed batch is built with `local_path: ""`.
  `_crunch_item` opens with `source = item.get("local_path") or ""` and fails
  the item immediately. Before the fix that same call was only the 404
  fallback for a companion below 0.9.67; now it is the primary path on every
  build.
- Failure scenario: an editor drops 12 clips, 3 fail on a wifi blip, they
  press RETRY FAILED on the page that staged the drop. The server puts the 3
  items back to `pending` and the batch to `queued`; the loopback call claims
  the batch; `_drain` fails all 3 with "the source file is not on this
  computer any more" twice each (MAX_ITEM_ATTEMPTS), `_maybe_finish` releases
  the batch as failed. The page toasts "3 clips queued again." Pressing the
  button a second time repeats it exactly, so the drop is unrecoverable
  without re-dropping the files, even though the bytes are still in staging.
- Evidence: `_item_from_manifest` line 1765 `items = (staging or {}).get("items") or {}`;
  with `staging is None` the match loop never runs and `local_path` stays `""`.
  `run()` line 1674 only sets `staging` when `staging_id` is truthy, and
  `str(None or "")` is `""` on the server side of the loopback. The music half
  of the SAME fix pass got this right: `music/web/static/ingest.js:1296` sends
  `{batch_uid: uid, staging_id: mi.stagingId}` and guards it with
  `uid === mi.batchUid && mi.stagingId`. `broll_server.py:1814` already accepts
  the `{batch_uid, staging_id}` shape on `/broll/ingest/retry` for both kinds,
  so the companion side needs no change.
- Ledger: "CR-24x does not fix broll-1" (new finding against this afternoon's
  broll-1 fix; grep `broll-1 (2026-09-11)` in `broll/web/static/ingest.js`).
  `ingestTakeOver` (`ingest.js:1663`) has the same `staging_id: null` shape
  and is older, but it is at least about a machine that genuinely has no
  staging.
- Suggested fix: send the page's own `ing.stagingId` (guarded as music does:
  only when `uid === ing.batchUid`), or better, use the same
  `/broll/ingest/retry {batch_uid, staging_id}` route the music page uses -
  the companion handler is already shared. Belt and braces on this side:
  `run()` should refuse (409) a claim whose manifest yields zero local paths
  when the machine holds a staging entry for that batch, rather than claiming
  and failing everything.

### comp-broll-music-2 - a staged drop that was never run can now never be deleted, and CLEAR FINISHED STAGING still tells the editor to press it
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_ingest.py:3134` (`prune_staging`),
  with `:3091` (`staging_report`) and `:3013` (`_space_refusal`)
- What: this afternoon's comp-broll-music-2 fix replaced the `at` fallback with
  a bare `continue` for any staging entry with no `ended_at`. `ended_at` is
  written in exactly one place, `_note_staging_ended`, which is only reached
  from `_maybe_finish` / `_lease_lost` for a batch that was claimed. A drop
  that was staged and never run therefore has no `ended_at` at any point in
  its life, and `prune_staging` is the ONLY caller of `shutil.rmtree` in the
  whole ingest stack (`grep -n rmtree broll_ingest.py broll_server.py
  music_ingest.py` -> one hit). So those bytes are now permanent.
- Failure scenario: an editor drags 400 clips onto the page, the browser
  finishes the PUTs, they change their mind and close the tab. ~1 TB sits in
  the dot-folder inside the archive for ever. The next drop hits
  `_space_refusal`, whose message counts that drop (`staging_report` uses
  `ended_at or at` and counts every entry with a directory) and says "N GB of
  that drive is finished b-roll staging: open Settings from the tray icon and
  use CLEAR FINISHED STAGING". The editor presses it and gets "There is no
  finished staging to clear on this computer." There is no other UI, route or
  sweep that can remove it.
- Evidence: read the three functions above plus `app.py:6717`
  (`clear_finished_ingest_staging`). The new regression tests
  `test_clear_finished_staging_leaves_a_drop_that_has_not_run` and
  `test_the_retention_sweep_leaves_an_old_drop_that_has_not_run` assert
  exactly this ("staged 2020-01-01, never run -> removed == 0, directory
  exists"), so the suite pins the leak rather than catching it.
- Ledger: new; neighbour opened by this afternoon's comp-broll-music-2 fix.
- Suggested fix: keep the hold-back for `max_age_days == 0` and for drops that
  are still being written into (a `last_put_at` stamp, or "no entry in
  `waiting`/`uploading` state"), but let the normal retention sweep still
  expire an unrun drop off `at` once it is older than the retention - and make
  `_space_refusal`/`staging_report` distinguish "finished" from "held", so the
  sentence never points at a button that cannot act.

### comp-broll-music-3 - a clip whose original vanished still uploads its poster, sprite and proxy to the archive, with no row to own them
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_ingest.py:2504-2528` (`_enqueue_uploads`)
- What: the new loop enqueues each rel as it goes and only afterwards checks
  whether the ORIGINAL was among the lost. `_upload_plan` builds the dict
  poster -> sprite -> proxy -> original (lines 2469-2483) and dicts preserve
  insertion order, so by the time the missing original is noticed the other
  three jobs are already handed to `UploadQueue` and will be uploaded. The
  item is then failed and `item["uploads"]` is cleared, so nothing ever posts
  `mark_uploaded` for them.
- Failure scenario: an editor pulls the SD card between describe and upload.
  `posters/<video_id>.jpg`, `sprites/<video_id>.jpg` and
  `<archive_dir>/Proxy/<stem>.mp4` land in the b-roll archive on the NAS for a
  clip that has no `live` row; the proxy in particular is a real file in an
  editor-visible archive folder that nothing references and nothing will clean
  up.
- Evidence: read `_upload_plan` and `_enqueue_uploads`; `UploadQueue.enqueue`
  starts the worker thread immediately (`_ensure_thread`; `_wake.set()`), and
  nothing in the failure branch calls `queue.retry()` or otherwise withdraws
  the three jobs.
- Ledger: new; introduced by this afternoon's comp-broll-music-1 fix (the old
  code enqueued the same three and then wedged, so the orphans are not new,
  but the ending now makes them permanent and silent).
- Suggested fix: build `declared`/`lost` from `os.path.isfile` FIRST, decide
  whether the item can proceed, and only then enqueue - or, in the failure
  branch, `queue.retry(list(declared))` plus a withdraw for anything still in
  `_queue`.

### comp-broll-music-4 - a music track waiting out a result retry publishes "nothing to do" and tears the model down every 15 s
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/broll_ingest.py:2093` (`_next_item`'s
  new `result_retry_at` skip) and `:1948-1957` (`tick`)
- What: `_next_item` skipping every remaining item makes `_drain` return
  `STATE_NOTHING_TO_DO` early (line 2072), which in `tick` means
  `state != STATE_RUNNING` -> `_stop_model_server()` and
  `_publish_state(STATE_NOTHING_TO_DO)`, while the batch and its heartbeat are
  deliberately retained. The longest backoff is 300 s, i.e. twenty ticks.
- Failure scenario: the NAS bind mount blips, the last track of a drop enters
  the 300 s backoff. For five minutes the tray and the page say this machine
  has nothing to do while it is in fact holding a lease on a live batch, and
  the model server is stopped and (once the wait expires) started again. An
  editor watching the page reads "nothing to do" and re-drops the album.
- Evidence: read `_drain`, `tick` and `_publish_state`; the new
  `test_a_503_on_result_waits_for_the_mount_instead_of_killing_the_track`
  asserts only `item["stage"] != ITEM_FAILED` and `ing._batch is not None`, so
  it does not notice the published state. Not measured against a live music
  sidecar, hence PLAUSIBLE on the model-server half.
- Ledger: new; neighbour opened by this afternoon's music-2 fix.
- Suggested fix: give `_drain` a third answer (or have `_next_item` report
  "waiting") so `tick` publishes a `waiting`/`running` state and skips
  `_stop_model_server()` while any item has a live `result_retry_at`.

### comp-broll-music-5 - the deferred CLAP analysis is never dropped when a batch is cancelled or its lease is lost
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/music_ingest.py:104` (`_deferred_analysis`)
- What: entries are popped only in `_post_result` (on success and on a
  terminal refusal). `cancel()`, `_lease_lost()` and a gate that closes
  mid-wait all drop the batch without touching the dict, so the embedding,
  the waveform peaks and the axes of every track that was mid-retry stay in
  memory for the life of the tray process. `item["result_retries"]` is also
  never reset after a successful POST, so a rel that recovered on try 5 starts
  its next refusal one away from the ceiling.
- Failure scenario: an editor cancels three album drops during a long NAS
  outage; the companion carries ~25 kB per mid-retry track for ever. Small,
  but it is memory an editor cannot free without restarting the tray.
- Evidence: `grep -n _deferred_analysis music_ingest.py` -> the constructor,
  the `_crunch_item` read, and two pops, both inside `_post_result`.
- Ledger: new; introduced by this afternoon's music-2 fix.
- Suggested fix: clear `_deferred_analysis` in `_lease_lost`/`cancel`/
  `_maybe_finish` (or key it by batch uid and drop the batch's whole map), and
  reset `result_retries` alongside `result_retry_at` on a 200.

### comp-broll-music-6 - a non-OSError failure to start the loopback server is neither latched nor recorded
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_server.py:2271-2273`
- What: the comp-app-6 fix latched the `OSError` branch on `_LAST_BIND_ERROR`
  but left the `except Exception` branch below it untouched: it logs a full
  WARNING with traceback on every retry of the new backoff loop (the exact
  log-flooding the latch was added to stop) and never writes
  `_LAST_BIND_ERROR`, so a stale message from an earlier OSError is what any
  reader of that global sees.
- Failure scenario: `make_server` raises something that is not an OSError (a
  bad `mounts` value, a resolver failure inside `resolve_mounts`); the app
  retries with backoff and the log fills with identical tracebacks, while the
  diagnostic string still says "OSError: address already in use" from the
  previous fault.
- Evidence: read `start()` lines 2244-2296; `_LAST_BIND_ERROR = ""` is set
  only on the success path at line 2288.
- Ledger: "CR-24x does not fully fix comp-app-6".
- Suggested fix: set `_LAST_BIND_ERROR` and apply the same repeat test in the
  generic branch.

## Coverage note
Not reached: `broll_ingest_media.py`, `broll_vlm_sidecar.py`, `music_worker.py`,
`music_clap_sidecar.py`, `ingest_kinds.py` and `ffmpeg_tools.py` beyond a grep -
none of them changed since 40f931a, and the diff plus its blast radius took the
time-box. `loopback_guard.py`'s matching logic (`origins_for_url`,
`verify_token`, the Host/DNS-rebind check) was read only as far as the module
docstring; the `security` lens should cover it properly. I did not bind 8899 or
exercise any route over the network (the live tray holds the port), so every
HTTP-shaped claim here is read from the handler, not observed. The suite does
not cover: the retry -> run dispatch end to end from either page (the new
`test_a_retry_that_names_a_batch_runs_it_again_on_this_machine` stubs
`ingestor.run`, so it cannot see finding 1), staging that is purgeable by any
route at all, or what `_publish_state` says during a result-retry wait.

## OUT OF TERRITORY
- `broll/web/static/ingest.js:1663` (`ingestTakeOver`): sends `staging_id: null`
  too, so a take-over by the machine that actually staged the drop loses every
  local path the same way finding 1 does. Older than this hunt.
- `music/web/musicweb/ingest_batches.py:223` (`retry_detail`): emits
  `{detail, reason, retry}` as the BODY of a raised `HTTPException`, so a
  companion below 0.9.71 sees only FastAPI's `detail` wrapper and still ends
  the track; the server has no way to tell which companion it is answering.
