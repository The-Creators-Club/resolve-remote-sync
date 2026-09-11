# comp-broll-music - the companion's 8899 loopback, b-roll ingest/fetch/upload, local VLM, music

Files read (with approximate coverage):
- `companion/src/ccsync_companion/broll_server.py` (100%), `loopback_guard.py` (100%),
  `ingest_kinds.py` (100%), `broll_fetch.py` (100%), `broll_upload.py` (~90%),
  `music_server.py` (100%), `broll_ingest.py` (~75%: staging/prepare/upload_slot/retry/run/gate/
  crunch/pump/finish/prune; skipped the progress-window plumbing and the report block),
  `music_ingest.py` (~50%: the overrides), `broll_vlm_sidecar.py` (~40%),
  `broll_vlm/local_vlm.py` (~60%), `broll_ingest_media.py` (~30%), `music_clap_sidecar.py` (~15%).
- The other side of every wire format: `broll/web/app/routes_fleet.py`,
  `broll/web/app/ingest_batches.py` (retry_failed), `broll/web/app/schemas.py`,
  `music/web/musicweb/routes_fleet.py`, `music/web/musicweb/schemas.py`,
  `music/web/musicweb/fleet_auth.py`, `broll/web/static/app.js`, `broll/web/static/ingest.js`,
  `music/web/static/app.js`, plus `git show 097f5a3:broll/web/static/app.js` for the older page.
- `git diff 097f5a3..HEAD` over the whole territory first, as briefed.

Tests run:
`companion> .venv\Scripts\python.exe -m pytest tests/test_broll_fetch.py tests/test_broll_ingest.py
tests/test_broll_ingest_media.py tests/test_broll_paths.py tests/test_broll_server.py
tests/test_broll_upload.py tests/test_broll_vlm_sidecar.py tests/test_broll_vlm_vendored.py
tests/test_broll_wiring.py tests/test_loopback_guard.py tests/test_music_clap_sidecar.py
tests/test_music_ingest.py tests/test_music_server.py tests/test_music_worker.py -q`
-> **772 passed, 1 skipped** in 145 s. Two scratch tests written outside the repo reproduce
findings 1 and 2 against the real classes (output quoted below).

## Findings

### comp-broll-music-1 - an artifact whose local file is gone is declared as an upload but never queued, and the item (and the whole batch, and the machine) wedges in `uploading` for ever
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_ingest.py:2467-2487` (`_enqueue_uploads`) and
  `:2552-2578` (`_pump_uploads`); same shape in
  `companion/src/ccsync_companion/music_ingest.py:465-496`
- What: `_enqueue_uploads` writes `item["uploads"] = {rel: kind for every rel in the plan}` and
  then skips the `queue.enqueue` for any rel whose local file is missing
  (`if not local or not os.path.isfile(local): continue`). `_pump_uploads` computes
  `missing = [rel for rel in rels if rel not in landed]` and only acts when a missing rel is also
  in `queue.failures()`. A rel that was never enqueued can never land and can never fail, so that
  branch `continue`s on every tick: `upload_attempts` never increments, `_fail_item` is never
  reached, the item stays `ITEM_UPLOADING`, `_next_item` skips it by design, and `_maybe_finish`
  counts it as outstanding for ever and never calls `release`.
- Failure scenario: an editor indexes a camera card in place (`source: "path"`) or stages onto an
  external drive, and the card/drive is unplugged (or the staging folder is cleaned, or a poster
  ffmpeg silently produced nothing) after `describe` and before the upload. From then on: the
  batch is never released, the heartbeat thread keeps renewing its lease so no other machine can
  take it, and every later drop on that machine gets `run()`'s 409 "this computer is already
  indexing another batch". The only cure is deleting the state file. This is the comp-loopback-3
  wedge (2026-08-21) through the one door that fix did not cover.
- Evidence: scratch pytest against the real `BrollIngestor` (FakeQueue/FakeServer from
  `tests/test_broll_ingest.py`), item with poster+proxy present and `local_path` missing:
  ```
  uploads declared: ['posters/1.jpg', 'Creators_Club/x/Proxy/A001.mp4', 'Creators_Club/x/A001.MP4']
  queue jobs:       ['posters/1.jpg', 'Creators_Club/x/Proxy/A001.mp4']
  stage after 10 pumps: uploading   upload_attempts: None
  released: []      batch still held: True
  ```
- Ledger: new (the never-ending-`uploading` symptom is what comp-loopback-3 recorded; this is a
  second, uncovered cause of it)
- Suggested fix: in both `_enqueue_uploads` implementations, put a rel into `item["uploads"]` only
  once its `queue.enqueue` actually happened; when a planned local file is missing, fail the item
  with that reason (or drop the rel and go on, if the artefact is optional). A belt-and-braces
  guard in `_pump_uploads` - a rel that is in neither `landed` nor `failures` for N ticks counts
  as a failure - would close the class.

### comp-broll-music-2 - CLEAR FINISHED STAGING deletes a drop that has been staged but NOT run, which its own docstring promises it never does
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_ingest.py:3023-3071` (`prune_staging`, the
  `ended_at` -> `at` fallback), called with `max_age_days=0` from
  `companion/src/ccsync_companion/app.py:6460-6479` (`clear_finished_ingest_staging`)
- What: a staging entry that has never run has no `ended_at`, so the sweep falls back to `at` (when
  it was staged). With `max_age_days=0` the cutoff is `now`, and every past `at` is older than it,
  so the directory is `rmtree`'d and the entry popped. Only the RUNNING batch's staging id is
  excluded (`_staging_entries`), and a staged-not-yet-run drop has no batch.
- Failure scenario: an editor drops 40 clips, the browser is still PUTting them, and someone (the
  same editor, or an admin talking them through a "clear some space" step) clicks the tray's
  CLEAR FINISHED STAGING. The bytes already uploaded are deleted, the ledger entry is forgotten,
  and every remaining `PUT /broll/ingest/upload/...` gets 404 "no such upload slot - prepare
  first". The button's name and the function's own docstring both say only finished batches are
  touched.
- Evidence: scratch pytest - `prepare()` one item, write the staged file, then `prune_staging(0)`:
  ```
  prune -> {'removed': 1, 'bytes': 10, 'held': 0, 'held_names': []}
  dir still there: False   entry still known: False
  upload_slot now: (404, {'ok': False, 'message': 'no such upload slot -- prepare first'})
  ```
- Ledger: new (related to MEDIA-3, which added the button, and CMEDIA-4, which added the
  `held_for_base_rig` carve-out to the same loop)
- Suggested fix: skip any entry with no `ended_at` when `max_age_days == 0` (better: skip whenever
  the drop's items are not all in a finished state). "Staged but never run" is not "finished",
  which is the word on the button.

### comp-broll-music-3 - the retry-failed handshake passes SERVER item uids to a companion route that matches STAGING local ids, so it always retries nothing while the page says it worked
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_ingest.py:1510-1564` (`retry`), against
  `broll/web/static/ingest.js:1694-1712` and `broll/web/app/ingest_batches.py:562-590`
  (`retry_failed`, which returns `items = [ingest_items.uid, ...]`)
- What: the dashboard's `retry-failed` answers with the 32-hex **batch item uids** that moved back
  to `pending`; the page hands that list straight to `POST /broll/ingest/retry` (with no
  `staging_id`); the companion matches those strings against the keys of
  `self._staging[sid]["items"]`, which are browser-minted **local ids**
  (`i<base36 time><random>`, capped by `_clean_local_id`). The two namespaces never intersect, so
  `wanted` filters everything out and the route answers `200 {"ok": true, "retried": 0}`.
  Separately, `retry()` only rewrites the staging ledger - it never re-claims or re-queues the
  batch - so even a matching id would not make this machine "start within the second" as the
  page's comment states. Because the answer is 200 rather than 404, the page's `run` fallback (the
  path that would actually reach the claim) is never taken.
- Failure scenario: a batch ends `done_with_errors` with 12 failed clips. The editor clicks the
  retry button; the server re-queues them; the companion does nothing; the page toasts
  "12 clips queued again", sets `ing.running = true` and polls a batch no machine holds. The clips
  sit `queued` until somebody works out the batch must be run again by hand.
- Evidence: both ends read. Server: `"items": item_uids` from
  `SELECT uid FROM ingest_items ... state = 'failed'`. Page: `{ items: answer.items || [] }`.
  Companion: `if wanted and str(local_id) not in wanted: continue`, where `local_id` comes from
  `_clean_local_id(raw.get("local_id"), index)` and the page mints
  `local_id: i${Date.now().toString(36)}${Math.random()...}` (`ingest.js:388`).
- Ledger: new (BROLL-5 and BROLL-18, both 2026-09-04, are two halves built against different
  vocabularies)
- Suggested fix: settle on one vocabulary - have `/retry` also accept batch item uids (the batch's
  items carry both ids, so the mapping exists), and make it re-claim the batch, or return
  409/404 so the page's existing `run` fallback fires. A test that drives server answer -> page
  body -> `retry()` would have caught it; today's `retry` tests hand it local ids directly.

### comp-broll-music-4 - "this computer is already downloading" is now `ok: true`, which an older dashboard's page reports to the editor as SUCCESS
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_server.py:759-770` (same shape in
  `music_server.py:497-505`), against `git show 097f5a3:broll/web/static/app.js:1566-1581`
- What: CMEDIA-7 turned the fetch cap into `200 {"ok": true, "state": "busy", ...}`. The in-tree
  comment claims "the older pages that only understand ok:false/true see a success with nothing
  inserted yet and poll on". They do not: the pre-CMEDIA-7 loop continues only on
  `state === "downloading"`, and `body.ok === true` falls through to
  `toast(body.message || "Sent to Resolve.", "success")` and `return`. The older music page breaks
  out of its loop the same way and renders `r.ok ? (r.note || 'done') : ...`.
- Failure scenario: dashboard 0.7.34 (or any browser holding a cached pre-2026-09-04 `app.js`)
  with companion 0.9.70 - a fleet state the brief names. An editor clicks Send to Resolve on a
  third clip while two are downloading, gets a GREEN toast and stops, believing the clip is in the
  timeline. Before CMEDIA-7 the same case was a red toast that at least said to try again.
- Evidence: the two `app.js` revisions read side by side; no path in the old loop tests
  `state === "busy"`.
- Ledger: new (introduced by CMEDIA-7, 2026-09-04)
- Suggested fix: keep `state: "busy"` but send `ok: false` with wording that reads as a wait, or
  make the message one an old page can print without claiming success ("not sent yet - this
  computer is busy downloading"). Deploying the dashboard before the companions mitigates but does
  not cover a cached page, and the comment asserting otherwise should go either way.

### comp-broll-music-5 - `broll_server_port = 0` binds an ephemeral port instead of being refused
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_server.py:2169-2185` (`configured_port`)
- What: the range check is `0 <= port <= 65535`, so `0` is accepted and handed to `bind()`, where
  it means "any free port". The listener comes up somewhere nothing can find it: every web UI
  hardcodes `http://127.0.0.1:8899`, while the tray and the log report the ephemeral number as if
  all were well. An operator typing `0` to switch the feature off (the key is deliberately absent
  from `DEFAULTS` and from `validate_config`, so nothing corrects them) gets a silent half-on
  server.
- Failure scenario: `broll_server_port = 0` in `~/.ccsync/config.toml` -> Send to Resolve,
  "+ Resolve", reveal, the ytdl download dispatch and both ingest route groups are all dead on
  that machine, with a healthy-looking log line.
- Evidence: `port = int(raw)`; `if not (0 <= port <= 65535)` accepts 0;
  `make_server((host, 0), ...)`.
- Ledger: new
- Suggested fix: require `1 <= port <= 65535` and fall back to 8899 with the existing warning;
  `broll_server_enabled = false` is the way to switch it off.

### comp-broll-music-6 - a download whose thread never starts stays `downloading` for ever and eats a fetch slot
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/broll_fetch.py:395-411` (`poll_fetch`)
- What: the job is inserted into `_JOBS` before `threading.Thread(...).start()`. If the spawn
  raises (a machine out of threads, or an injected `runner` that throws) the exception propagates
  out of `poll_fetch`, leaving a registry entry permanently in `STATE_DOWNLOADING`. Terminal
  states are popped on read, but this one never becomes terminal: every later poll for that clip
  answers "downloading, 0 %" for the life of the process, and it permanently consumes one of the
  two `MAX_CONCURRENT_FETCHES` slots.
- Failure scenario: rare, but invisible when it happens - a clip that syncs at 0 % for ever and a
  download cap silently one lower from then on.
- Evidence: read; not reproduced (the spawn failure is hard to force).
- Ledger: new
- Suggested fix: register the job only after the runner has started, or wrap the start and pop the
  key (answering `failed`) if it raises.

### comp-broll-music-7 - the upload queue worker has no supervisor: one escaped exception pins `_active` and no upload ever runs again
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/broll_upload.py:424-472` (`UploadQueue._loop`)
- What: the loop body is unguarded. `run_upload`/`verify_upload` are written never to raise, but
  `build_upload_command` (`RcloneTuning.from_cfg`, `_transport_flags`) and `_finish` are not
  covered. If anything escapes, the thread dies with `self._active` still set: `_next_job` then
  returns `None` for ever (it refuses while `_active is not None`), `_ensure_thread` cheerfully
  restarts a thread that can only spin, and `_pump_uploads` sees rels that are neither landed nor
  failed - finding 1's wedge, for every item on that machine.
- Evidence: read. `_loop` has no try/except; the package's other long-lived loops do.
- Ledger: new
- Suggested fix: wrap the per-job body in try/except, `_finish(job, False, str(exc))` on escape,
  and log it.

## Coverage note
Not got to: `music_clap_sidecar.py` beyond its capability/refusal surface and the ONNX session
lifetime; `broll_vlm/local_runtime.py`'s download/checksum path; `broll_ingest_media.py`'s argv
parity with the indexer (its test loads the indexer by path and passes); the progress-window and
report halves of `broll_ingest.py`; `music_worker.py`. Two things I looked at but could not
settle: `local_vlm.get_server` holds `_servers_lock` across `start_server` (minutes) and
`_health_retried` (18 s), so a `stop_server()` from another thread blocks for that long - harmless
today because the only caller is the tick thread itself, but one refactor from a hang; and
`atexit.register(handle.stop)` runs per start with no unregister, accumulating dead handles in a
tray that stays up for weeks.

What the suite does not cover: nothing in `companion/tests` drives a real server answer through
the page's body shape into a companion route (finding 3 would have been caught); `prune_staging`
has no test for a staged-but-never-run drop under `max_age_days=0` (finding 2); and
`_pump_uploads` has no test for a declared rel that was never enqueued (finding 1) - `FakeQueue`
models the failure ledger and the one-way stop latch, but not "it was never handed over at all".
The loopback guard itself (origins, Host, token, share/rel_path traversal, the PUT's content-type
and containment rules) I read closely and found nothing wrong: the traversal and containment
checks are unconditional and the 2026-08-21 blank-mount hole is properly closed.

## OUT OF TERRITORY
- `music/web/musicweb/fleet_auth.py:64-118`: unlike b-roll's `require_fleet_caller` (CR-55), the
  music fleet gate never compares the editor a `cce1.` token is BOUND to against the signed
  `X-CCSync-Identity` - `stamp_ok` is shape-only and the two dependencies are declared separately
  on every route in `routes_fleet.py`. Editor A's per-editor token plus editor B's identity token
  passes here and is refused by b-roll.
- `broll/web/static/app.js:1754-1757`: the `busyOld` fallback matches the OLD companion's wording
  with `/already downloading/i`, and the CURRENT sentence contains that phrase too, so the two
  branches overlap - harmless today, brittle the next time the sentence is reworded.
