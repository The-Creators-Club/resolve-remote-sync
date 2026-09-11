## The music tagger, 2026-09-11 (CR-246)

### CR-246 - music ingest: a filename allocation that could spin for ever, refusals nothing could retry, a rescore that cleared a marker it had not earned, a readiness probe that sampled the wrong fifty tracks, a 405 on HEAD, a traceback for a waveform, and a fleet gate that never bound a per-editor token to the identity it carried (CR-55) - FIXED 2026-09-11 (`music/web`)

**music-1 (high).** `ingest_batches.allocate_name`'s collision loop had no
ceiling, and both of its predicates answered TAKEN on error by design ("a
query that cannot run counts as TAKEN, which is the harmless direction").
That reasoning holds for a transient fault and is an infinite tight loop for
a persistent one: a music.db that stays locked or malformed, or - the
trigger the verifier found, which needs no database fault at all - a bind
mount this container's uid can stat but not traverse, because `Path.exists()`
swallows ENOENT and lets EACCES and EIO through. Every candidate came back
taken, `i` climbed without bound, and the call sat on a uvicorn threadpool
thread at 100 per cent CPU; the companion's HTTP timeout then retried the
item, so every retry of every item of every drop added another spinning
thread to the process that also serves the fleet status page. Nothing logged
anything and only a container restart cleared it. The loop now has a CEILING
(1,000 candidates for one stem is a broken library, not a drop) and, more
importantly, asks a three-valued question: `_candidate_free` returns free,
taken, or "could not tell", and the third is a 503 the caller can retry
rather than another candidate. The old `_taken_on_disk` / `_taken_by_a_track`
are gone rather than left beside the new `_disk_state` / `_track_state` with
nobody calling them - this loop was their only caller, and a predicate
nothing uses is what music-4 below is about.

**music-2 (medium).** The two refusals the server emits meaning "ask again"
were consumed as permanent failures for the track: the companion's
`_post_result` branches on `status != 200` alone, and `MAX_ITEM_ATTEMPTS` is
2 inside one `_drain` pass with no backoff, so a bind mount that blipped for
thirty seconds during an album drop failed every track in flight with the
audio still staged on the editor's machine. Worse, there was no way back:
b-roll grew a retry route and a button in BROLL-18 (2026-09-04) and music
never did, so `done with errors - 3 failed` was the end of the road unless
the editor dropped the files again by hand. The server half, here: the 503
from `share_root_ready` and from the new "could not tell" case, and the 409
`name_race`, all carry `{detail, reason, retry: true}` through one helper
(`ingest_batches.retry_detail`), so a companion that knows no reason codes
can still read the flag; and `POST /api/ingest-batches/{uid}/retry-failed`
plus a `try the failed tracks again` button on every batch card with a
failure puts the failed items back to `pending` and the batch back to
`queued`, with the same three limits b-roll's has (only `failed` items move,
`track_id`/`dest_name` stay so the slot is re-used, nothing is dispatched
from the route). The button then asks THIS computer's companion to take the
re-armed batch (`POST /music/ingest/retry` on the loopback) and believes it
has only on a **202**, which is the answer of a companion that re-armed and
CLAIMED it. A companion published before that route answers 200 and claims
nothing, leaving the batch queued with no machine, so any other success is
worded "back in the queue, open this page on the computer that staged them
and press Run" - an editor told work is running on a machine nothing claimed
it on waits for ever. The companion half - classifying 503 and 409 `name_race` as
retry-later with a backoff - is the comp-broll-music builder's, in
`music_ingest.py`, and **the two halves ship together**: without it the new
503 is read as a permanent failure exactly as before, and without the server
half the companion has nothing to classify.

**music-3 (medium).** `rescore_library` read `db.load_matrix` at the top,
spent seconds in numpy, and then deleted `scores_stale` unconditionally. The
marker is a library-wide fact but the pass only covers the snapshot it
loaded, so a `result` on another threadpool thread that wrote a track and
marked the library stale in that window had its marker erased by a rescore
that never saw its track. `routes_fleet._settle_scores` is gated on exactly
that marker, so the end-of-batch settle - the guarantee MUSIC-5 exists to
provide - was skipped, and the track sat in the library searchable by
similarity with no tags, no axes and no facet membership, while `/api/stats`
reported `scores_stale: null` so the catching-up banner did not show either.
The clear is now compare-and-clear against `_snapshot_token` - the marker AND
the highest `tracks.id`, because the marker is an ISO timestamp to the second
and two marks inside one second compare equal - and a token it cannot read
compares unequal, which costs one extra rescore and loses nothing.

**music-4 (low).** `apply_for_track`'s docstring said "`release` passes
force=True, so a batch is always fully tagged by the time it finishes".
Nothing in production passes `force=True`; `release` settles a batch through
`_settle_scores`, which rescores only when the marker is set. The difference
is precisely music-3 - the documented design has no gate to lose and the
implemented one does - so a reviewer reconciling the two would have trusted
the docstring and not looked. The docstring now describes `_settle_scores`,
and `test_force_is_what_release_uses` is renamed for what it actually pins.

**music-5 (medium).** `config.share_root_ready` sampled `ORDER BY id LIMIT
50`: the fifty OLDEST rows, which are the rows most likely to have been
replaced or tidied away without a `--prune` - a state `db.prune_missing`
exists for. A library whose entire early set had been re-imported answered
"the library is not mounted here" for ever, on a share that was mounted and
full, closing `/api/ingest`, `_ingest_inline` and every fleet `result`, with
a message that sent the operator to look at the mount. It is `ORDER BY id
DESC` now, and a POSITIVE answer is cached for five seconds (`forget_ready_cache`
clears it): the probe was up to fifty stat()s over SMB on the request path of
every `allocate_name`, i.e. per item of every drop. Only the positive answer
is cached, so the write path reopens the instant a mount comes back.

**music-6 (low).** `HEAD /api/audio/{track_id}` answered 405. Starlette's
plain `Route` adds HEAD alongside GET; FastAPI's `APIRoute` does not, so the
one route in this app that exists to speak Range correctly refused the method
a player uses to discover `Accept-Ranges` and `Content-Length` before it
starts seeking. Registered explicitly now, with the body dropped in the route
rather than by the response class - only `FileResponse` special-cases HEAD,
so the streaming branch would have sent every byte.

**music-7 (low).** `/api/peaks`'s on-demand fallback called
`peaks_from_file` unguarded (ffmpeg raises on a truncated or undecodable
file, which is the ordinary case for a half-synced track on a base rig) and
then ran `Response(bytes(data))` even when `data` was None. Both surfaced as
a 500 with a traceback on a route the SPA calls for every track the user
clicks. A decode failure is now a 503 naming the cause, an empty decode a
404, and the log line names the track and the file.

**CR-55 in music, raised out of territory by the comp-broll-music hunter and
CONFIRMED here.** `fleet_auth` accepted the mount's `X-CCSync-Fleet-Auth:
editor:<name>` stamp as proof that "a fleet machine is calling" and then
believed whatever `X-CCSync-Identity` the same request carried, without ever
comparing the two. ytdl bound them on 2026-08-21 and b-roll's
`require_fleet_caller` mirrors it (CR-55); music, which got the stamp in the
same wave, never did. So a machine whose only verified credential was the
`cce1.` token BOUND to one editor could act under another editor's name on
that editor's batches: claim one, fail its tracks, take it from the machine
already crunching it. Measured at 40f931a, that claim answered 200. The two
dependencies are now one - `require_fleet_caller`, the machine credential
first and then the identity, exactly b-roll's order - and a bound token whose
editor differs from the identity is a 403 `identity_mismatch`. The shared
migration token is bound to nobody and keeps today's behaviour exactly:
`require_fleet_token` returns None for it and there is nothing to compare, so
the batch-ownership check is still what refuses another editor's batch.
`stamp_ok` became `gate_stamp` (kind and editor, unparseable is no opening)
rather than leaving a shape-only predicate beside the one that binds.

### Verification
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_a_database_that_cannot_answer_is_a_503_not_a_loop -> hangs at 40f931a (the deadline fails it), passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_a_share_that_faults_on_stat_is_a_503_not_a_loop -> hangs at 40f931a, passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_the_collision_loop_has_a_ceiling -> hangs at 40f931a, passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_a_healthy_library_still_steps_around_a_collision -> passes before and after (the answer this must not change)
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_the_share_not_ready_503_says_retry -> fails at 40f931a (the detail was a bare string), passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_a_failed_track_can_be_put_back_in_the_queue -> fails at 40f931a (405, no such route), passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_retrying_a_batch_with_nothing_failed_is_answered_not_refused -> fails at 40f931a, passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_the_page_only_says_running_when_the_companion_claimed_it -> fails at 40f931a (no such call), passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_another_editors_batch_cannot_be_retried -> fails at 40f931a, passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_a_track_written_during_the_pass_keeps_its_stale_marker -> fails at 40f931a (verified by re-pinning `_snapshot_token` to a constant, which is the pre-fix unconditional clear), passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_a_rescore_that_covers_everything_still_clears_the_marker -> passes before and after (the behaviour the fix must not lose)
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_the_force_docstring_describes_what_actually_settles_a_batch -> fails at 40f931a, passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_a_library_whose_oldest_files_were_tidied_away_is_still_ready -> fails at 40f931a, passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_a_share_with_none_of_the_newest_tracks_is_still_refused -> passes before and after (the refusal the probe exists for)
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_a_positive_answer_is_not_re_probed_per_item -> fails at 40f931a (no such cache), passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_head_on_audio_answers_the_headers_a_player_probes_with -> fails at 40f931a (405), passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_head_with_a_range_answers_206_and_no_body -> fails at 40f931a (405), passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_head_on_an_unknown_track_is_still_a_404 -> fails at 40f931a (405), passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_get_is_untouched_by_the_head_registration -> passes before and after
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_a_file_ffmpeg_cannot_decode_is_named_not_a_traceback -> fails at 40f931a (500), passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_an_empty_decode_is_a_404_not_bytes_of_none -> fails at 40f931a (TypeError, 500), passes now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_a_waveform_that_builds_is_stored_and_served -> passes before and after
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_a_bound_token_may_not_carry_another_editors_name -> at 40f931a the claim answers 200 (verified by re-pinning the gate to its pre-fix "learns nothing" answer), 403 identity_mismatch now
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_a_bound_token_carrying_its_own_editor_still_works -> passes before and after (the migrated editor whose ingest CR-55 turned back on)
- music/web/tests/test_bug_hunt_2026_09_11_music.py::test_the_shared_migration_token_keeps_todays_behaviour -> passes before and after
- Also re-run green after the change: test_share_gate.py, test_media_range.py, test_rescore_transaction.py, test_ingest_batches.py, test_fleet_ingest.py, test_no_em_dashes.py, test_ingest_ui.py, test_plain_words.py, test_ui_says_what_it_knows.py, and test_fleet_ingest.py again after the CR-55 change (48 of its tests cover the fleet gate).

### OWED TO ANOTHER TERRITORY
- `companion/src/ccsync_companion/music_ingest.py` (comp-broll-music builder):
  `_post_result` must classify a 503, and a 409 whose `reason` is
  `name_race`, as retry-later with a backoff, and re-POST the analysis it
  already has rather than re-entering `_crunch_item`. 409 `model_mismatch`
  and 422 stay terminal. The server now sends `{detail, reason, retry}` on
  all three; `retry: true` is the field to read if branching on `reason` is
  not wanted. Ship the two halves together.
- `companion/src/ccsync_companion/music_server.py`: `POST
  /music/ingest/retry` `{batch_uid, staging_id}` is BEING BUILT by the
  comp-broll-music builder and answers 202 once it has re-armed and claimed
  the batch. This page is already written against it and degrades on any
  other success, so the two can land in either order: against a companion
  without the route (404) or an older one (200) the editor is told the batch
  is queued and where to press Run.

### Owner decisions
- The retry button is offered on any batch with a failure, terminal or not,
  and is worded "try the failed tracks again". b-roll's equivalent is only
  reachable on a terminal batch through the same route; if you would rather
  it were hidden until the batch has finished, that is one condition.
- The positive readiness cache is five seconds. Longer is fewer stat()s per
  drop and a longer window in which a share that has just gone away is still
  written to (nothing is ever written OUTSIDE the root, so the cost is a
  refusal arriving a few seconds late, not a misplaced file).
