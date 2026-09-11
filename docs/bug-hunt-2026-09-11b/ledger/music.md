## The music ingest panel after its own fix pass (CR-262, 2026-09-11)

The morning's music fixes (CR-246) ported b-roll's BROLL-18 retry button, cached
the library readiness probe and taught the rescore to clear only the snapshot it
scored. The second hunt of the same day found that the port was taken from
b-roll BEFORE b-roll's own fix of the same morning, that the cache turned a
fail-closed gate into one that stays open for five seconds, and that the probe
now samples the rows least likely to be on disk.

### CR-262A (music-1) - retry-failed took a live batch away from the machine indexing it - FIXED (music/web/musicweb/routes_batches.py)
`POST /api/ingest-batches/{uid}/retry-failed` reset the batch to `queued` with
`lease_expires_at = NULL` whenever one item had failed, without asking whether a
machine was still holding it. b-roll grew the refusal for exactly this the same
morning (broll-5, CR-246) and that half was missing here: fifteen tracks in, one
failed, the batch `running` on RAZER, one click and RAZER is 410'd on its next
per-item POST - and because `claim` only refuses a second machine while the
lease is live, a second computer of the same editor could claim beside it and
both index the same tracks into the same library. The route now 409s
`reason: held` while `ingest_batches.lease_live(batch)`, and expires stale
leases first so a machine that went away hours ago is still retryable (that
orphaned batch is what the button exists for).

### CR-262B (music-2) - the retry button was drawn on running batches and on other editors' - FIXED (music/web/static/ingest.js)
The port dropped both of b-roll's conditions: the button appeared next to
`cancel` on a `claimed`/`running` batch as soon as one track failed, and in the
admin "all machines" scope over other editors' work. That click is how CR-262A
was reached in practice, and in the admin scope the dispatch half cannot help
anyway - the admin's computer has none of the audio staged. It is now drawn only
in the `mine` scope and only for a batch in `MI_TERMINAL_STATES`. The server
guard above is the contract; this is the button.

### CR-262C (music-3) - a retried batch was undispatchable after a page reload - FIXED (music/web/static/ingest.js)
`miRetryFailed` only told the companion to pick the batch up when the page still
remembered the drop (`mi.batchUid` + `mi.stagingId`, in memory, lost on every
reload), and the fallback line said "press Run" - which submits the CURRENTLY
staged selection as a brand new batch. The normal case (come back after lunch to
`done_with_errors`, press the button) therefore re-queued the items and left the
batch in `queued` with nothing anywhere that could pick it up. The dispatch is
unconditional now - the companion's `run()` accepts an empty staging id and
takes the items from the server's claim - and the SPA grew b-roll's BROLL-8
control, `take over on this computer`, on any `queued` batch in the `mine`
scope. The fallback line names that button instead of Run.

### CR-262D (music-4) - the readiness cache kept the write gate open after the mount disappeared - FIXED (music/web/musicweb/config.py)
music-5 cached the POSITIVE answer of the mount probe for five seconds to save
the per-item stat storm. `share_root_ready` is the only thing between an
unmounted bind mount and a write path that mints filenames and `tracks` rows for
audio that lands in the container's own filesystem, and caching the whole answer
meant a NAS reboot mid-album was invisible to it for five seconds: three rows and
three `uploaded` destinations pointing at a directory that is not the library.
The cache now covers only the 50-stat SAMPLE; `root.is_dir()` is one stat and
runs on every call.

### CR-262E (regression-10) - a live drop refused itself from item ~51 - FIXED (music/web/musicweb/config.py)
music-5 flipped the probe from the oldest 50 `tracks` rows to the newest 50. But
a fleet `result` writes the `tracks` row BEFORE the companion uploads the audio,
and `tracks` has no status column to exclude an unlanded row, so once a drop had
written fifty of them the newest-50 sample was entirely files that are not there
yet: item 51 of a 120-track import was answered 503 "the music library is there
but empty", which with the new retry burns six tries over twenty minutes per
track and then fails it permanently, pointing the operator at a mount that is
fine. The sample is both ends now, 25 newest and 25 oldest: one end missing is a
normal library, both ends missing is a share that is not mounted.

### CR-262F (music-5) - the "cannot tell" token raised instead - FIXED (music/web/musicweb/rescore.py, ingest_batches.py)
`_snapshot_token`'s try covered `SELECT MAX(id)` but not the `meta` read beside
it, so a locked or malformed database raised out of `rescore_library`'s first
statement rather than yielding the never-equal sentinel the docstring promises.
Worse, `write_item_result`'s own failure handler then called
`rescore.scores_stale(conn)` again from inside its except block and raised a
second time, turning a track that WAS written into an HTTP 500 - which the
companion's `_result_retry_wait` reads as terminal for that track. Both reads
are guarded now.

### CR-262G (music-6) - an editor name with a space was not an editor - FIXED (music/web/musicweb/fleet_auth.py)
`_STAMP_RE` refused an `editor:` stamp carrying whitespace or more than 64
characters; `gate_stamp` then returned `(None, None)` and the call fell through
to the SHARED token comparison, which a per-editor `cce1.` token can never
satisfy - so such an editor lost music fleet ingest entirely and was told their
`X-CCSync-Token` was missing or invalid. b-roll and ytdl accept the same name.
Music now uses b-roll's parser (prefix plus non-empty remainder) and logs a
stamp that carries no name at all.

### CR-262H (security-3) - the gate stamp was believed on an environment variable - FIXED (music/web/musicweb/config.py, DEPLOY.md)
The comment above `_LOGIN_GATED` reads "It is NOT inferred from the environment"
and the line under it was `os.environ.get('MUSIC_LOGIN_GATED') == '1'`. That flag
is what makes `fleet_auth` believe an inbound `X-CCSync-Fleet-Auth` stamp, and
the stamp SKIPS the fleet-token comparison entirely - so a standalone musicweb
with the documented hatch set, behind a proxy that did not strip the header, no
longer required `DASH_REPORT_TOKEN` on `/api/fleet/ingest/*` (the remaining
barrier was `require_identity`, which is why this is one credential lost and not
an open door). b-roll and ytdl can only be told by a call from their mount. The
flag is `False` now and only `set_login_gated(True)` turns it on; nothing in the
tree ever set the variable, and DEPLOY.md says so and points a standalone
deployment at `MUSIC_INGEST_TOKEN` instead.

### Verification
All in `music/web/tests/test_bug_hunt_2026_09_11b_music.py` unless noted; run
with `cd music\web; .venv\Scripts\python.exe -m pytest tests\test_bug_hunt_2026_09_11b_music.py -q`.
- test_a_batch_a_machine_is_still_holding_is_not_retried -> fails at f1eeb42 (200, lease nulled), passes now  (music-1)
- test_a_batch_whose_lease_has_run_out_is_still_retryable -> the guard does not close the orphaned-batch door  (music-1)
- test_the_retry_button_is_drawn_only_on_the_editors_own_finished_batches -> fails at f1eeb42, passes now  (music-2)
- test_the_retry_dispatch_does_not_depend_on_what_this_page_remembers -> fails at f1eeb42, passes now  (music-3)
- test_a_queued_batch_can_be_taken_over_on_this_computer -> fails at f1eeb42, passes now  (music-3)
- test_a_mount_that_disappears_inside_the_cache_window_closes_the_gate -> fails at f1eeb42, passes now  (music-4)
- test_a_live_drop_does_not_refuse_itself_once_fifty_rows_are_unlanded -> fails at f1eeb42, passes now  (regression-10)
- test_a_database_that_cannot_answer_yields_a_token_not_an_exception -> fails at f1eeb42 (raises), passes now  (music-5)
- test_a_result_whose_rescore_and_marker_both_fail_is_still_a_200 -> fails at f1eeb42 (500), passes now  (music-5)
- test_a_stamp_the_mount_can_produce_is_parsed[Jane Smith|80 chars|jsmith] -> fails at f1eeb42, passes now  (music-6)
- test_an_unparseable_stamp_is_still_not_a_credential[5 shapes] -> the refusal is unchanged  (music-6)
- test_an_environment_variable_does_not_make_this_app_login_gated -> fails at f1eeb42 (True in a subprocess), passes now  (security-3)
- test_bug_hunt_2026_09_11_music.py::test_the_page_only_says_running_when_the_companion_claimed_it -> its "press Run" assertion was updated to the take-over wording music-3 replaced it with; the 202 assertion is untouched.
- Re-run after the fixes: the ten music/web test files that touch these modules (fleet ingest, the two ingest gates, ingest batches, the ingest UI, the mounted prefix, em dashes, plain words, both rescore files, the UI scan) - 214 passed.

### OWED TO ANOTHER TERRITORY
- comp-broll-music: `companion/src/ccsync_companion/broll_server.py`, the `/music/ingest/retry` handler: nothing is required, but note that the browser now sends `run_mode` with that body and always sends `staging_id` (possibly `""`). Both are already read (`body.get("run_mode")`, `str(body.get("staging_id") or "")`), so an unchanged companion behaves exactly as before; no deploy order between the two.
- comp-broll-music: `companion/src/ccsync_companion/broll_server.py` / `broll_ingest.py`: the new `take over on this computer` button posts `/music/ingest/run` with `staging_id: ""`, which `run()` already accepts (the items come from the server's claim). No change owed unless that ever stops being true.
- dash-api: `api.py` (security-1): when the suspended-account predicate is made importable, music's fleet routes (`music/web/musicweb/routes_fleet.py`, via `fleet_auth.require_fleet_caller`) must ask it too, the same as b-roll and ytdl. Not built here: the predicate does not exist yet and music must not grow a second notion of "suspended". Dashboard deploys first.

Deploy order for everything above: the dashboard (which is what carries `music/web`) can deploy on its own - no companion change is needed, and a companion on 0.9.65..0.9.71 sees no difference.

### Owner decisions
- security-3: I removed the `MUSIC_LOGIN_GATED` hatch outright (the hunter's first suggestion) rather than splitting it into a second `MUSIC_TRUST_GATE_STAMP` flag. Nothing in the tree ever set it, only DEPLOY.md mentioned it, and one flag meaning two things is how it went wrong. A standalone deployment behind its own proxy now sets `MUSIC_INGEST_TOKEN` instead. Say the word and the split version is a ten-line change.
- music-2: the retry button is hidden in the admin `all machines` scope, exactly as b-roll hides it. An admin who wants to retry another editor's failed tracks has to switch to that editor's machine, which is where the audio is.
- music-6: the 64-character cap on an editor name in the stamp is gone (b-roll has none). The name is compared against the signed identity before it means anything, so its shape is not a boundary.
