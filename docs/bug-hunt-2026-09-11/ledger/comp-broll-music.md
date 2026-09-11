## The companion's b-roll and music ingest, 2026-09-11 (CR-238)

### CR-238 - an ingest item whose file was gone, a CLEAR FINISHED STAGING that deleted a drop still being uploaded, a "busy" answer an old page printed as success, port 0, a download that never started and an upload worker with no supervisor - FIXED 2026-09-11 (bug hunt 2026-09-11, territory comp-broll-music)

**comp-broll-music-1 (high) - a declared upload that was never queued wedged
the item, the batch and the whole machine.** `_enqueue_uploads` wrote
`item["uploads"] = {every rel in the plan}` and then skipped the
`queue.enqueue` for any rel whose local file was missing. `_pump_uploads`
only ever acts on a missing rel that is ALSO in `queue.failures()`, so a rel
that was never handed over could neither land nor fail: `upload_attempts`
never moved, `_fail_item` was never reached, `_next_item` skips `uploading`
by design and `_maybe_finish` counted the item as outstanding for ever, so
the batch was never released, the heartbeat kept renewing the lease and every
later drop on that machine got run()'s 409 "this computer is already indexing
another batch". A camera card unplugged (or an external staging drive pulled)
between `describe` and the upload is the live case; `music_ingest.py` had the
identical shape for its one audio file. Now a rel enters `item["uploads"]`
only once the queue has taken it, a missing ORIGINAL (or music's one file)
ends the clip with a sentence that names why, and `original_uploaded` is
derived from what was really queued rather than from the plan. Two belts
either side of it: an `uploading` item with nothing declared is failed rather
than waited on (that is what an older build's state file looks like), and a
rel that is neither landed, nor failed, nor known to the queue for
`LOST_UPLOAD_TICKS` pumps is failed too - the new `UploadQueue.tracks()` is
what answers that, and a queue that cannot answer counts everything as
tracked, because "I could not tell" must never end an upload that is running.

**comp-broll-music-2 (medium) - CLEAR FINISHED STAGING deleted a drop that had
not run.** `prune_staging` fell back from `ended_at` to `at` (when the drop
was staged) for an entry with no ending. At `max_age_days=0`, which is the
tray's CLEAR FINISHED STAGING button, the cutoff is now and every past `at` is
older than it, so a drop the browser was still PUTting into was `rmtree`'d and
popped: the bytes already uploaded were gone and every remaining `PUT
/broll/ingest/upload/...` answered 404 "no such upload slot - prepare first".
The function's own docstring, `_iso_epoch`'s docstring and KNOWN_BUGS MEDIA-3
all promise the opposite. An entry with no `ended_at` is now skipped at every
retention value, not only at 0: at the default seven days the same fallback
silently deleted a drop staged eight days ago that nobody had run.

**comp-broll-music-4 (low, downgraded) - "this computer is already downloading"
was an `ok: true` an older page toasted GREEN.** CMEDIA-7 turned the fetch cap
into `200 {"ok": true, "state": "busy"}` and the comment beside it claimed
"the older pages that only understand ok:false/true see a success with nothing
inserted yet and poll on". They do not: the pre-2026-09-04 `app.js` loop
continues only on `state === "downloading"`, so that body falls through to
`toast(body.message || "Sent to Resolve.", "success")` and returns. The colour
cannot be fixed from the companion; the sentence can, so `BUSY_MESSAGE` now
opens "not sent yet: ..." and keeps "already downloading" in it, which is what
the current page's `busyOld` branch matches on. The two comments asserting the
old page polls on are corrected in `broll_server.py` and `music_server.py`.

**comp-broll-music-5 (low) - `broll_server_port = 0` bound an ephemeral port.**
The range check was `0 <= port <= 65535` and `0` means "any free port" to
`bind()`, so the loopback came up somewhere nothing can reach it (every web UI
hardcodes 127.0.0.1:8899) while the tray and the log reported the ephemeral
number as if all were well: Send to Resolve, "+ Resolve", reveal, the ytdl
dispatch and both ingest route groups dead on that machine. The floor is 1 now,
and the existing warning sends the operator back to 8899;
`broll_server_enabled = false` is how the feature is switched off.

**comp-broll-music-6 (low) - a download whose thread never started stayed
`downloading` for ever.** `poll_fetch` registered the job in `_JOBS` before
`Thread(...).start()`, so a spawn that raised left an entry that could never
become terminal: every later poll for that clip answered "downloading, 0 %"
for the life of the process and one of the two `MAX_CONCURRENT_FETCHES` slots
was gone with it. The start is inside a try now: the key is popped and the
caller gets `failed`, which the page retries.

**comp-broll-music-7 (low) - one escaped exception killed the upload queue for
good.** `UploadQueue._loop`'s body was unguarded. `run_upload`/`verify_upload`
are written never to raise, but `build_upload_command` (`RcloneTuning.from_cfg`
on a hand-edited config) and `_finish` are not, and a thread that died there
left `self._active` set: `_next_job` refuses while `_active is not None`, so
`_ensure_thread` cheerfully restarted a thread that could only spin and nothing
on the machine uploaded again - finding 1's wedge, for every item. The per-job
body is now supervised: the job is failed with the exception's text (an
exception here repeats, and a failure is what the orchestrator's retry ledger
is for) and the queue goes on.

**music-2, the companion half (medium) - a retryable refusal of `result` killed
the track permanently.** `MusicIngestor._post_result` branched on `status != 200`
alone, so the two statuses the SERVER emits meaning "try again" - a 409
`name_race`, and the 503 `allocate_name` raises when the library's bind mount
is not there - both cleared `embedded` and called `_fail_item`. A thirty-second
mount blip during a fifteen-track album drop failed every track in flight, the
batch released `done_with_errors`, and unlike b-roll there is no retry-failed
route anywhere in `music/web` to get them back. The classification is on the
server's own `reason` now, not the status: 429/502/503/504 and a 409 that says
retry leave the item where it is with a backoff (`RESULT_RETRY_BACKOFF_S`, 5 s
to 5 min, `MAX_RESULT_RETRIES` = 6, about twenty minutes in all) and are
re-POSTed on a later drain pass; 409 `model_mismatch` and 422 stay terminal,
because those refusals repeat. The retry re-POSTs the analysis this process
already has (`_deferred_analysis`, in memory only - the vectors are deliberately
not in the state file, so a companion restarted mid-wait re-embeds) rather than
re-entering the embedding, and `MAX_ITEM_ATTEMPTS` is untouched: it was written
for crunch failures. `_next_item` skips an item whose `result_retry_at` is in
the future, so the drain does not spin on a NAS that is rebooting, and the item
stays outstanding, so the batch and its lease are kept. The budget ENDS: a
library that never comes back fails the track with the server's own words, and
the batch releases.

**music-2, the loopback half (owed by the music web builder).** The music page
gains a "try the failed tracks again" button on the server's new `POST
/api/ingest-batches/{uid}/retry-failed`, and it then asks this machine to run
the batch again from the audio still staged here, with the b-roll body shape
`{batch_uid, staging_id}` on `POST /music/ingest/retry`. That route already
existed - the ingest dispatcher is kind-generic, so there is no second
listener on 8899 and the same origin/token/Host rules apply - but it only
re-armed the STAGING ledger (BROLL-5's meaning), which would have left the
batch `queued` with no machine holding it: comp-broll-music-3's mistake
exactly. A body carrying a `batch_uid` now re-arms the ledger AND claims the
batch (`ingestor.run`, the tested take-over path), answering the claim's
status with `retried` carried alongside; a body without one behaves exactly as
it did, so the b-roll page's existing call is untouched. `run_mode` /
`start_now` are read the same way `/run` reads them. `_post_result`'s
classification takes the server's own `retry: true` flag as the first word -
read both at the top level and inside `detail`, since FastAPI wraps a raised
HTTPException's payload and a returned body is not wrapped - ahead of the
status-based half that was already there.

**comp-app-6, the logging half (owed by the comp-app builder).** The app
retries the loopback bind with a backoff now, and `start()`'s `except OSError`
said the same six-line WARNING - the one that tells the editor to quit the old
standalone BRoll Companion - on every attempt, which is how the log an editor
is asked to send stops being readable. It is latched on the error TEXT rather
than on a counter, reusing `_LAST_BIND_ERROR`, which already existed for
CMEDIA-3's tray line: WARNING the first time, DEBUG for an identical repeat,
WARNING again when the text changes ("address already in use" becoming
"permission denied" is a different fault and a different remedy) and after a
successful bind, which clears `_LAST_BIND_ERROR` as it always has.

### Verification
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_a_clip_whose_file_vanished_ends_instead_of_wedging_the_machine -> fails at 40f931a, passes now  (comp-broll-music-1)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_only_what_the_queue_took_is_declared_as_an_upload -> fails at 40f931a, passes now  (comp-broll-music-1)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_a_rel_the_queue_forgot_does_not_hold_the_item_for_ever -> fails at 40f931a, passes now  (comp-broll-music-1, belt and braces)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_a_track_whose_file_vanished_ends_instead_of_wedging_the_machine -> fails at 40f931a, passes now  (comp-broll-music-1, music)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_clear_finished_staging_leaves_a_drop_that_has_not_run -> fails at 40f931a, passes now  (comp-broll-music-2)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_the_retention_sweep_leaves_an_old_drop_that_has_not_run -> fails at 40f931a, passes now  (comp-broll-music-2)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_the_busy_message_cannot_be_read_as_sent -> fails at 40f931a, passes now  (comp-broll-music-4)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_both_busy_routes_carry_that_sentence -> fails at 40f931a, passes now  (comp-broll-music-4, the comment)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_port_zero_is_not_a_port -> fails at 40f931a, passes now  (comp-broll-music-5)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_a_download_whose_thread_will_not_start_is_not_downloading_for_ever -> fails at 40f931a, passes now  (comp-broll-music-6)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_the_upload_worker_survives_an_escaped_exception -> fails at 40f931a, passes now  (comp-broll-music-7)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_a_503_on_result_waits_for_the_mount_instead_of_killing_the_track -> fails at 40f931a, passes now  (music-2, companion half)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_a_name_race_is_retried_and_a_model_mismatch_is_not -> fails at 40f931a, passes now  (music-2, companion half)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_a_library_that_never_comes_back_still_ends_the_batch -> fails at 40f931a, passes now  (music-2, companion half)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_a_retry_that_names_a_batch_runs_it_again_on_this_machine -> fails at 40f931a, passes now  (music-2, the loopback the music page calls)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_the_servers_own_retry_flag_is_what_decides -> fails at 40f931a, passes now  (music-2, the server's `retry: true`)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_the_bind_warning_is_said_once_per_distinct_failure -> fails at 40f931a, passes now  (comp-app-6)
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_a_bind_that_works_makes_the_next_failure_loud_again -> fails at 40f931a, passes now  (comp-app-6, the reset)

Also re-run green with the fixes in: `tests/test_broll_ingest.py`,
`tests/test_music_ingest.py`, `tests/test_broll_upload.py`,
`tests/test_broll_fetch.py`, `tests/test_broll_server.py`,
`tests/test_music_server.py`, `tests/test_loopback_guard.py`,
`tests/test_broll_wiring.py`, `tests/test_music_worker.py` - and the four
suites nearest this territory re-run once more after the loopback route
landed: `test_broll_server.py`, `test_music_server.py`, `test_music_ingest.py`,
`test_broll_ingest.py`, 390 passed.

### OWED TO ANOTHER TERRITORY
- `broll/web/static/ingest.js` (+ the comment in `broll/web/app/ingest_batches.py`
  and the body assertion in `broll/web/tests/test_ingest_retry_and_takeover.py`):
  comp-broll-music-3 / broll-1. Per the verdict the fix is on the web side -
  `ingestRetryFailedBatch` should dispatch the take-over
  (`POST /broll/ingest/run`) instead of calling `/broll/ingest/retry` with
  server item uids. Nothing was changed in the companion's `retry()`: it still
  answers `200 {"retried": 0}` for an id set it does not know, so if the web
  builder KEEPS the loopback call it must be made 404/409 here first, or the
  page's `run` fallback stays dead.
- `music/web/musicweb/ingest_batches.py` and `music/web/static/app.js`:
  music-1's explicit 503, the `retry: true` flag on it and on 409 `name_race`,
  and the page's "try the failed tracks again" button are the music builder's
  half. The companion side is safe without any of them: a 503 from any fleet
  route is retryable whatever it carries, and `POST /music/ingest/retry`
  ignores a `batch_uid` nobody sends. The page must send `{batch_uid,
  staging_id}` (b-roll's shape) for the take-over to happen; an OLDER
  companion answers that body 200 with `retried` only and does not claim, so
  the page should treat a non-202 as "ask the editor to press RUN".
- `music/web/musicweb/fleet_auth.py`: the hunter's out-of-territory note stands
  (the music fleet gate never binds a `cce1.` token to the signed identity the
  way `require_fleet_caller` does).

### Owner decisions
- A staging entry with NO `ended_at` is now never pruned, at any retention.
  That is the safe direction (it cannot delete a drop nobody has run), but it
  means an entry written before `ended_at` existed (before MEDIA-3,
  2026-08-28) is never cleaned up automatically. If any machine still carries
  one, it needs a hand.
- A missing ORIGINAL fails the clip; a missing poster, sprite or proxy only
  drops that artefact and the clip still goes live without it. The alternative
  (fail the clip for a missing poster too) would cost an editor a re-index for
  a 100 KB still.
- `MAX_RESULT_RETRIES` = 6 with a 5 s..5 min backoff is about twenty minutes of
  waiting for a library that is not mounted. Longer would cover a NAS that is
  down for a proper reboot; it also holds the machine's ingest lease that much
  longer, which is why it is not longer.
