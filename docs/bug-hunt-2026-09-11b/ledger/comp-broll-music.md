## The companion's b-roll and music ingest: a retry that burned the drop, staging that could never be deleted, orphaned uploads, a false "nothing to do" (CR-253, 2026-09-11)

The 2026-09-11b hunt of that afternoon's fix pass, territory `comp-broll-music`
(`broll_ingest.py`, `music_ingest.py`, `broll_server.py`). Five of the six
findings are the neighbour a same-day fix opened; the sixth is the half of
comp-app-6 the latch did not reach.

### CR-253A (comp-broll-music-1, companion half) - a claim that names no staging id is refused, not spent (broll_ingest.py)

The page's RETRY FAILED posts `{batch_uid, staging_id: null}`. `run()` reads
`self._staging[staging_id]` and nothing else, and `_item_from_manifest` is the
only place `local_path` is ever populated, so with no staging id every item of
the re-claimed batch is built with `local_path: ""` and `_crunch_item` fails it
on its first line. Three clips that failed on a wifi blip therefore failed
again immediately, twice each (MAX_ITEM_ATTEMPTS), and `_maybe_finish` released
the batch as failed - with the bytes still sitting in staging and the button
repeating it exactly on every press. The page's half of this belongs to the
`broll` builder (send `ing.stagingId`, guarded as the music page already does).
This side is now belt and braces: after the claim, a batch whose manifest
yields ZERO local paths while this machine holds a staging entry for the very
files it lists is refused 409 `staging_id_missing` (with the id it found, so
the page can retry with it) instead of being crunched into failure. The new
`_staging_holding` matches the way `_item_from_manifest` matches, name plus
`rel_dir`, so a genuine take-over by a machine that staged nothing is
untouched and still claims. The refusal does not release the batch, for the
reason `_fits` gives a few lines above: the lease expires and the corrected
request, or another machine, takes it, whereas releasing it `failed` would
make the editor re-create it.

### CR-253B (comp-broll-music-2, also regression-9) - a drop that was never run can be deleted again, and the space refusal stops naming a button that cannot act (broll_ingest.py)

CR-238's fix replaced `prune_staging`'s `at` fallback with a bare `continue`
for any entry with no `ended_at`. That was right for the tray's CLEAR FINISHED
STAGING (`max_age_days=0`), which used to delete a drop mid-PUT, but
`ended_at` is written in exactly one place, `_note_staging_ended`, reached only
for a batch that was CLAIMED. A drop that was staged and abandoned (400 clips
dropped, tab closed) therefore has no `ended_at` at any point in its life, and
`prune_staging` is the only caller of `shutil.rmtree` in the whole ingest
stack: those bytes had become permanent, inside a dot-folder in the archive
that no editor has any UI to see, and the next drop's space refusal counted
them and sent the editor to a button that answers "There is no finished
staging to clear on this computer."

Now: the button still holds an unrun drop back (and REPORTS it, `held_unrun`),
but the ordinary retention sweep reaches it again. The clock for an unrun drop
is the later of when it was staged and when a byte last landed in it
(`_dir_newest_mtime`), so a drop whose PUTs are still arriving is never a
candidate however old its `at` is - which is the loss the CR-238 fix was
protecting against, kept. `staging_report` now splits `finished_bytes` from
`unrun_bytes`, and `_space_refusal` names CLEAR FINISHED STAGING only when
there are finished bytes for it to clear; unrun staging gets its own sentence
that points at the page and says it is cleared automatically after the
retention. CR-238's `test_the_retention_sweep_leaves_an_old_drop_that_has_not_run`
pinned the leak, so it is retitled
`test_the_retention_sweep_leaves_a_drop_still_being_written_into` and now
proves the property that is actually wanted.

### CR-253C (comp-broll-music-3) - a clip whose original vanished uploads nothing at all (broll_ingest.py)

CR-238's `_enqueue_uploads` enqueued each rel as it went and only afterwards
asked whether the ORIGINAL was among the lost. `_upload_plan` is poster ->
sprite -> proxy -> original and dicts keep insertion order, so by the time the
missing original was noticed the other three were already handed to
`UploadQueue`, whose worker thread starts on `enqueue`. The item was then
failed and `item["uploads"]` cleared, so nothing ever posted `mark_uploaded`
for them: a poster, a sprite and a proxy in an editor-visible archive folder
for a clip with no `live` row, referenced by nothing and cleaned up by nothing.
The card being pulled between describe and upload is the live case. The whole
plan is now stat'ed before anything is handed over, and the decision to fail is
taken first. The original is also enqueued FIRST of what survives, which costs
nothing (`UploadQueue` sorts by `UploadJob.order`, not insertion order) and
means an `enqueue` that raises cannot orphan the stills either.

### CR-253D (comp-broll-music-4) - a track waiting out a result retry is not "nothing to do" (broll_ingest.py)

music-2's `result_retry_at` skip in `_next_item` makes `_drain` find no
crunchable item, and `_drain` answered `STATE_NOTHING_TO_DO`. In `tick` that
means stop the model server and publish "nothing to do" - for up to 300 s, i.e.
twenty ticks, while this machine holds a lease on a live batch and its
heartbeat keeps renewing it. The page and the tray said the machine was idle
during a NAS mount blip, which is exactly when an editor re-drops the album,
and the 4-12 GB model was torn down and rebuilt around the wait. `_drain` now
asks `_waiting_on_retry()` and answers `STATE_RUNNING` while any item of the
batch is inside its backoff, so the gate note stays empty, the model stays up
and the state matches what the machine is actually doing.

### CR-253E (comp-broll-music-5) - the deferred CLAP analysis is dropped with its batch, and a landed result resets the budget (music_ingest.py)

`_deferred_analysis` (music-2's in-memory parking for a mid-retry track's
embedding, peaks and windows, about 25 kB a track) was popped only inside
`_post_result`. `cancel()`, `_lease_lost()` and a `_maybe_finish` that gave up
on the item all dropped the batch without touching it, so three cancelled album
drops during a long NAS outage left that memory held for the life of the tray
process, unfreeable without restarting it. The base orchestrator now has a
`_forget_batch_scratch(batch)` hook beside `_note_staging_ended`, called from
all three places a batch is dropped; it is a no-op for b-roll, which keeps
nothing off the item, and clears the map for music. Separately,
`item["result_retries"]` was never reset after a POST that landed, so a rel
that recovered on try 5 started its next refusal one away from
MAX_RESULT_RETRIES and was failed for good by a blip the first one survived; a
200 now clears it alongside `result_retry_at`.

### CR-253F (comp-broll-music-6) - a non-OSError failure to start the loopback is latched too (broll_server.py)

CR-24x's comp-app-6 fix latched the `OSError` branch of `broll_server.start()`
on `_LAST_BIND_ERROR` and left the `except Exception` branch below it
untouched: it logged a full WARNING with traceback on every attempt of the new
backoff loop, which is the exact log flooding the latch was added to stop, and
never wrote `_LAST_BIND_ERROR`, so any reader of that global saw a stale
message from an earlier bind fault. A failure that is not a bind error (a bad
`mounts` table, a resolver that raises inside `resolve_mounts`) now takes the
same latch, on the same rule: loud once per distinct fault, DEBUG on a repeat,
cleared by a successful start.

### Verification
- companion/tests/test_bug_hunt_2026_09_11b_comp_broll_music.py::test_a_claim_with_no_staging_id_is_refused_when_this_machine_staged_it -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_broll_music.py::test_a_take_over_by_a_machine_that_staged_nothing_still_works -> guards the guard (passes both)
- companion/tests/test_bug_hunt_2026_09_11b_comp_broll_music.py::test_the_retention_sweep_expires_a_drop_that_was_never_run -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_broll_music.py::test_a_drop_still_being_written_into_survives_the_sweep -> pins what the CR-238 fix protected (passes both)
- companion/tests/test_bug_hunt_2026_09_11b_comp_broll_music.py::test_clear_finished_staging_still_leaves_an_unrun_drop_and_says_so -> fails at f1eeb42 (no `held_unrun`), passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_broll_music.py::test_the_space_refusal_does_not_name_a_button_that_cannot_act -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_broll_music.py::test_the_space_refusal_still_names_the_button_for_finished_staging -> the other direction (passes both)
- companion/tests/test_bug_hunt_2026_09_11b_comp_broll_music.py::test_nothing_is_uploaded_for_a_clip_whose_original_vanished -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_broll_music.py::test_a_track_waiting_out_a_result_retry_is_not_nothing_to_do -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_broll_music.py::test_a_cancel_drops_the_deferred_analysis -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_broll_music.py::test_a_result_that_lands_resets_the_retry_budget -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_broll_music.py::test_a_non_oserror_start_failure_is_latched_and_recorded -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11_comp_broll_music.py::test_the_retention_sweep_leaves_a_drop_still_being_written_into -> retitled from ...leaves_an_old_drop_that_has_not_run, which pinned the CR-253B leak

Run: `cd companion; .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11b_comp_broll_music.py -q` -> 12 passed. The
territory's older files (`test_broll_ingest.py`, `test_music_ingest.py`,
`test_broll_server.py`, `test_broll_upload.py`, `test_music_server.py`,
`test_loopback_guard.py`, `test_bug_hunt_2026_09_11_comp_broll_music.py`) -> 537
passed, 1 skipped, 1 failed, and the failure is NOT this territory's:
`test_music_server.py::test_the_frozen_flag_is_the_one_app_run_answers` reads
`inspect.getsource(app.run)` and `app.py` is being edited by the comp-app
builder while this ran.

### OWED TO ANOTHER TERRITORY
- broll: `broll/web/static/ingest.js`: `ingestRetryFailedBatch` (and
  `ingestTakeOver`, older): send the page's own `ing.stagingId` guarded by
  `uid === ing.batchUid` rather than `staging_id: null`, or dispatch to
  `POST /broll/ingest/retry {batch_uid, staging_id}` the way
  `music/web/static/ingest.js:1296` already does (the companion handler at
  `broll_server.py:1814` is shared and needs no change). With the companion
  half alone, a 0.9.72 machine answers 409 `staging_id_missing` instead of
  failing the drop: recoverable, but the button still does not work until the
  page is fixed. The PAGE is served by the dashboard, so the dashboard deploys
  first; a page that sends a staging id to a companion below 0.9.72 works
  exactly as it always did, so the two halves are independent.
- comp-app: `companion/src/ccsync_companion/app.py`:
  `clear_finished_ingest_staging`: `prune_staging` now returns `held_unrun`
  (how many staged-but-never-run drops it deliberately kept). When `removed`
  is 0 and `held_unrun` is not, the sentence "There is no finished staging to
  clear on this computer." should say instead that the staging on this
  computer is drops that were never indexed, and that they clear themselves
  after the retention. Companion-only, no deploy order.

### Owner decisions
- CR-253A refuses the claim rather than resolving the staging id itself.
  Auto-resolving (matching the manifest to a staging entry and using its local
  paths) would make RETRY FAILED work with no page change at all, but it
  guesses which drop the editor meant when two drops hold files with the same
  names in the same `rel_dir`, and a wrong guess indexes the wrong bytes. The
  hunter suggested the refusal; if the owner prefers the button to work without
  waiting on the page fix, `_staging_holding` already returns the id that would
  be used.
- CR-253B lets the retention sweep delete an abandoned drop after the
  configured window (7 days by default). That is what the docs promised from
  the day the feature shipped, but it is a deletion of an editor's staged
  originals that no one confirms. The two guards are that the drop must have had
  no byte written into it for the whole window, and that `max_age_days=0` (the
  button) never takes it.
- CR-253D publishes `running` during a result-retry wait rather than adding a
  new `waiting-result` state. A new state string would render as its raw
  spelling in both SPAs (`ingGateLabel` falls back to `String(gate)`) until the
  b-roll and music pages learned it, which is a two-sided change for a
  cosmetic gain.
