# CR-290 - the tenth hunt's highs, the webapps/tools half - FIXED in repo 2026-09-18 (broll/indexer, broll/web)

The 2026-09-18b hunt's high findings for `broll/`, `music/`, `ytdl/`,
`server/`, `tools/`, `installer/`, `onboarding/`, built on the same day's
first fix pass (CR-282..CR-286), not around it. Two findings fell to this
group: its own `broll-indexer-1`, and the server half of `wire-1`, owed to it
by companion-media and routed by the orchestrator mid-pass - plus `overseer-1`,
which the orchestrator found by reading the second of those against the
companion's CR-284F.

### CR-290A (broll-indexer-1) - a proxy 1 or 2 frames short passed both indexer producers - FIXED (broll/indexer/broll_index/ffmpeg_tools.py, broll/indexer/tools/make_own_proxies.py)

CR-286B bought back the second full network read of every original with a
cheap screen: skip `count_frames(src)` whenever the proxy's own packet count
sits within `FRAME_SLACK` (2) of the SOURCE's `duration * fps`. The screen
cannot see the failure it screens for. A CFR camera original's real frame
count IS its duration * fps - that is the whole population this check exists
for - so a proxy 1 or 2 frames short of it lands inside the window, the source
is never counted, and the exact comparison `frames_match` performs never runs.
An estimate carrying two frames of slack cannot decide a one-frame question.

That is the low end of the Reproductive Rights class (seven files 1-18 frames
short, Resolve refused every one, the editor reported "sync is stuck"), and it
broke the invariant `frames_match`'s own docstring states: three producers,
one rule. The companion counts both files unconditionally and compares
exactly, so the same file was refused on an editor's machine and accepted by
the indexer - in `make_own_proxies` accepted into an editor-grade
`Proxy/<stem>.mp4` that Resolve links directly, with `status: ok` in the
ledger and nothing anywhere recording why Resolve then refused it.

Fixed by the brief's second option, "always count the source once per
original": the screen is gone from both producers, the comparison is exact in
both directions again, and what survives of CR-286B's saving is
`ffmpeg_tools.count_frames_cached` - `count_frames` memoised on `(path, size,
mtime_ns)`, bounded at 512 entries. An original is therefore demuxed once per
VERSION of itself rather than once per verification pass: the libx264
fallback's second `_bad()` is free, as is a second proxy cut from the same
source in the same process. Keyed on the bytes, never the path alone, because
a re-encoded file at the same path is a different file; a file that cannot be
stat'ed is counted rather than cached, so the memo can never be the reason a
count is wrong. The source read is still skipped when the DESTINATION's count
is unknown - "both known or skip" is unchanged, and an unknowable comparison
must not pay for the expensive half of itself.

The memo remembers only a REAL count (coordinator review of this entry, same
day). `count_frames` answers None for a transient failure as readily as for an
unreadable file - an SMB blip, a NAS too busy to serve the demux - and the
first cut of this fix stored that None, which would have pinned "cannot tell"
on that original for the life of the process and sent every later proxy of it
down the "both known or skip" branch unchecked: the memo becoming the reason a
count is wrong, which is the one thing its docstring forbids. A failed count
is now simply retried, at worst costing the read it was always going to cost.

`FRAME_SLACK` and `expected_frames` remain, with comments saying plainly that
neither may decide a verdict any more. The ffmpeg/ffprobe argv is untouched
(the parity tests and the companion's loader pin it), and nothing about the
companion's twin changes: it was already exact, so the three producers agree
again.

Cost, stated honestly: a back-catalogue run pays one extra full read of each
original, which is what CR-286B removed. That is the price of the invariant,
and the invariant is the one that stopped seven bad proxies reaching an
editor. If the read cost has to come back down, the answer is a count carried
FORWARD from a read the pipeline already does (`stage_probe` / `_frames_source`
territory), not a tolerance on one of the three producers.

### CR-290B (wire-1, the server half owed by companion-media) - a two-stage `/uploaded` made the item terminal while the original was still going up - FIXED (broll/web/app/ingest_batches.py, routes_batches.py, routes_fleet.py, static/ingest.js, migrations/013_proxies_live.sql)

The companion stages a clip live as soon as its preview, poster and sprite are
on the NAS and posts `/uploaded` a second time when the original finishes
(CR-288D). Both posts landed on a route that wrote `live`, which is TERMINAL.
So an original whose upload then failed left: an item no retry could move
(`_check_transition` refuses to leave a terminal state, and `retry_failed`
only ever moved `failed`), a batch that called itself `done`, and a `videos`
row advertising an `original_path` the archive does not hold - with the
failure recorded nowhere at all.

The first stage now writes `proxies_live`: a new item state between
`uploading` and `live` in `ITEM_PROGRESS`, in neither `ITEM_TERMINAL` nor
`ITEM_FINISHED`. The clip stays VISIBLE throughout, which is the whole point
of the two stages - visibility is `videos.status`, which both stages set to
`indexed`, and no reader anywhere filters browse, search or the tree on the
item state (checked: the only other readers of `ITEM_TERMINAL` are `claim`,
which skips an item that already has a `video_id` anyway, and the cancel
sweep). Around that word:

  * `release` counts an item still at `proxies_live` exactly as a failure when
    it decides `done` versus `done_with_errors`. At release nothing more is
    coming, so an owed original is a permanent one. It is NOT folded into
    `n_failed` mid-run, which would flash "1 failed" at an editor while an
    upload was healthy; it is its own counter, `n_proxies_live`.
  * a CANCEL leaves it alone, as it leaves `live` alone (`_CANCEL_KEEPS`,
    from the new `ITEM_PUBLISHED`): its media is in the archive and an editor
    may already have cut with it, and its `videos` row is `indexed`, so the
    ghost-row DELETE cannot reach it either.
  * `retry_failed` moves it back to `pending` beside the failed ones. Not to
    `uploading`: that is the one state `_next_item` skips, so an item parked
    there whose local upload queue died with the old process is a dead end
    (comp-loopback-2's shape). The re-run is idempotent on this side -
    `record_result` REPLACES segments, themes and flags, and the archive slot
    is the one already allocated - so the cost is a re-describe, which is the
    price of a button that works with a companion of any age.
  * the panel says "original still owed" per clip, adds "N still to send the
    original" to the counters line, and draws the retry button for a batch
    with nothing failed and something owed ("finish the N still uploading") -
    without that last part the one way back would have been invisible.

`ingest_items.state` carries a CHECK constraint and SQLite cannot alter one,
so `013_proxies_live.sql` REBUILDS the table: every column, index and foreign
key of migration 011 with one more word in the CHECK, rows copied whole. Safe
inside the runner's single transaction because nothing references
`ingest_items` (`ingest_batches.current_item_uid` is plain TEXT). Landed in
all three migration directories, both `schema.sql` copies, `app/db.py`'s chain
(v13) and the indexer's `migrate.py` (`LATEST_VERSION = 13`), which the
existing parity tests check.

### CR-290C (overseer-1) - during the upload window the insert object said the clip HAS no original, so the preview was imported in its place for good - FIXED (broll/web/app/routes_api.py, broll/web/app/ingest_batches.py)

Found by the orchestrator reading CR-290B against the companion's CR-284F.
CR-290B's whole point is that a clip is usable while its original uploads -
and for those hours `insert_target_detail` lists the archive folder, finds no
sibling beside the preview and answers `original_rel: null`. The 0.9.75
companion reads null as "this clip has no original" and imports the PREVIEW at
the original's own path, permanently, ignoring the editing proxy; when the
real file lands hours later nothing upgrades, because nothing is watching. It
is the common case for every heavy clip, and it defeats plan item 5 ("usable
from the moment its editing proxy lands").

`_insert_object` now answers the path the original WILL land at, and says so:

  * the path is `ingest_batches.ItemFiles(archive_dir, archive_stem,
    basename(videos.rel_path), id).original` - the SAME expression
    `mark_uploaded` stores on the second post, not a reconstruction that can
    drift from it.
  * `original_pending: true` rides beside it. ADDITIVE: `original_rel` is null
    in this window today, so a 0.9.74 companion sees a non-null path and takes
    its ordinary stand-in route, which is the designed behaviour, and a
    companion that ignores the flag loses nothing. The key is ABSENT rather
    than false when nothing is owed, so nothing has to be taught to read it.
  * only when the server could LOOK. A `known: false` object judged nothing
    (proxy-tiers-3), and naming a path there would contradict it.
  * null, with no flag, for every clip genuinely without an original: no
    ingest item at all (everything the indexer archived), an item that already
    sent one, a stem-diverged row, and a batch ingested with
    `upload_originals` off.
  * a `live` item whose `original_uploaded` is 0 counts as owed too. After
    CR-290B that combination can only be a wire-1 VICTIM, written before this
    deploy: published, original never sent, and no retry can reach it.
  * a DB error degrades the insert object, never the detail page.

**And a defect of CR-290B's own, found writing this one and fixed with it:**
`upload_originals: false` is a deliberate proxies-only ingest (the companion's
`_upload_plan` omits the original), so its one `/uploaded` post carries
`original_uploaded: false` - and CR-290B as first written parked every such
item at `proxies_live` for ever, ending every proxies-only batch
`done_with_errors` and offering a retry that could never succeed.
`mark_uploaded` now reads the batch's own setting: nothing owed, so the one
post ends the item `live`.

### Verification
- `broll/indexer/tests/test_bug_hunt_2026_09_18b_webapps_tools.py::test_a_proxy_one_or_two_frames_short_is_refused[1799]` and `[1798]` -> accepted the proxy before the fix (no RuntimeError), refuse it now
- `...::test_a_proxy_longer_than_its_source_is_refused_too` -> same, the other direction of the exact rule
- `...::test_make_own_proxies_refuses_a_one_frame_short_proxy[1799]` and `[1798]` -> before the fix the `.partial` was renamed into `Proxy/A003.mp4` with `status: ok`; now `bad-output` with the counts in `detail`
- `...::test_a_good_proxy_costs_one_source_read_across_the_encoder_fallback` -> the memo, across an nvenc failure and the libx264 retry
- `...::test_a_count_the_destination_cannot_produce_costs_no_source_read` -> "both known or skip" still holds and costs nothing
- `...::test_the_source_count_memo_is_keyed_on_the_bytes` -> a re-encoded file at the same path is re-counted
- `...::test_a_count_that_failed_once_is_not_remembered` -> with the None cached (the first cut of this fix) the second proxy of that original is never frame-checked and the test does not raise; with the guard the source is re-counted and the 1799-frame proxy is refused
- `broll/indexer/tests/test_bug_hunt_2026_09_18_webapps_tools.py::test_a_source_is_demuxed_once_however_many_proxies_it_feeds` replaces `::test_a_proxy_whose_length_is_right_costs_no_second_read_of_the_source`, which pinned the defective screen; it now pins the saving that survives it
- Run: `cd broll/indexer; python -m pytest tests/test_bug_hunt_2026_09_18b_webapps_tools.py tests/test_bug_hunt_2026_09_18_webapps_tools.py -q` -> 22 passed. Neighbours of the touched files, run as a safety check: `tests/test_ffmpeg_tools.py tests/test_fix_10bit_proxies.py tests/test_proxy_integrity.py tests/test_sprite_geometry_recorded.py` -> 62 passed.

- `broll/web/tests/test_bug_hunt_2026_09_18b_webapps_tools.py::test_the_two_stages_end_live` -> before the fix the FIRST post left the item `live`; now `proxies_live`, visible and searchable, and the second post ends it `live` with `original_path` set
- `...::test_a_failed_original_leaves_a_visible_retryable_item` -> before, the batch released as `done` and `retry-failed` moved nothing; now `done_with_errors`, the clip is still browsable, and the retry re-queues it to `pending`
- `...::test_a_batch_whose_originals_all_landed_is_plain_done` and `...::test_an_older_companions_single_post_is_unchanged` -> the two directions that must NOT change (they pass on the unfixed source too, deliberately: they are the compatibility pins)
- `...::test_the_panel_is_told_what_is_owed` -> `n_proxies_live` on both browser routes
- `...::test_a_cancelled_batch_keeps_a_staged_item` -> before, a cancel relabelled a published clip `cancelled`
- `...::test_the_stepped_migration_takes_the_new_word_and_keeps_the_rows` -> a v12 database stepped to v13 keeps its item rows and accepts `proxies_live`; verified to fail with migration 013 unregistered
- `...::test_the_panel_says_original_still_owed_rather_than_the_enum` -> the page words it
- `...::test_the_insert_object_names_the_original_that_is_still_coming` -> before the fix `original_rel` was null through the whole upload window (which is what made the companion import the preview in its place); now the expected archive path plus `original_pending`, and after the second post the real path with no flag
- `...::test_a_batch_that_never_sends_originals_owes_nothing` -> a proxies-only batch: the item ends `live` on its one post, the batch releases `done`, and the insert object says null with no flag. Fails on CR-290B as first written (item stuck `proxies_live`, batch `done_with_errors`)
- `...::test_a_clip_with_no_ingest_item_is_unchanged` -> everything the indexer archived is untouched
- `broll/web/tests/test_fleet_ingest.py::test_a_cancelled_release_deletes_the_rows_that_never_got_media` was EDITED, not broken: it posted `/uploaded` with no original and expected `live`, which is now the two-stage case. It posts the original too, so it still tests what its name says.
- `broll/indexer/tests/test_migrate.py` and `tests/test_schema_parity.py` pin the literal latest version on purpose; both moved 12 -> 13.
- Runs: `cd broll/web; .venv\Scripts\python.exe -m pytest tests -q` -> 642 passed (whole suite, because a schema version touches everything). `cd broll/indexer; python -m pytest tests -q` -> 822 passed.

### Not fixed
- none.

### OWED TO ANOTHER GROUP
- companion-media (INFORMATIONAL, no code owed, but WORTH KNOWING before the companion side is finished): `insert.original_pending` is a new key a companion MAY use - it means "this path is not on the NAS yet". A companion that treats a non-null `original_rel` as "fetchable now" will simply fail the fetch and retry, exactly as it does for any original not yet synced; nothing regresses without it. If CR-284F's stand-in ledger wants to avoid writing a stand-in it will have to upgrade later, that flag is the signal to wait for the second post instead.
- companion-media (INFORMATIONAL, no code owed): a companion older than this server that posts `/uploaded` with `original_uploaded` false and then never posts again now leaves the item `proxies_live` instead of `live`. That is the intended fix and needs no companion change; the response body is unchanged apart from two ADDED keys (`state`, `original_uploaded`), and `live` keeps its meaning "the clip is published", true of both stages.
- The companion's twin (`companion/src/ccsync_companion/ffmpeg_tools.frames_match`, `broll_ingest._frames_missing`) is already exact and counts both files unconditionally, so this fix makes the indexer match IT, not the other way round. Optional and NOT required for the rule: companion-media may adopt a `count_frames_cached` of its own if the ingest's double count ever costs measurably; the verdict does not change either way.

### Deploy order
- CR-290A is indexer-only, base rig, no wire. Nothing on an editor's machine or the dashboard reads any of this, so there is no ordering constraint and no rollback hazard: an older indexer simply accepts the short proxy again.
- CR-290C: server first, same as CR-290B and in the same change; purely additive on the wire in both directions.
- CR-290B: THE SERVER DEPLOYS FIRST (the dashboard image carries `broll/web`), before any companion. It is safe alone in both directions - an older companion posting one call with its original sees exactly today's behaviour, and a newer one's first stage simply gets the new word.
- Two things to know about the schema step, both from `server/publish_db.py`'s own refusals. (1) `ensure_schema` runs at MOUNT time, so the live `broll.db` is stepped to v13 when the new dashboard boots; a `broll.db` published from this rig AFTER that must be stepped too (`broll-index migrate`), or the publish is refused as older than the live file. (2) Publishing a v13 index UNDER an older dashboard is refused the other way round, correctly: deploy first, publish second.
- A dashboard ROLLBACK to a v12 image against a v13 database: `app/db.py` refuses to run and the mount fails ABSENT, not fatal, so the dashboard still boots with `/broll` off (`ccsync_dashboard/broll.py` already recognises that exact message). The rows are not lost - `proxies_live` items simply cannot be read by the old code. Rolling forward again fixes it; there is no down migration and there should not be one.

### Owner decisions
- `retry_failed` sends an owed clip back to `pending`, i.e. it is re-proxied and re-described (a model call) rather than only re-uploaded. The alternative needs the companion to resume an upload from a state the server names, which is a companion change nobody owes this pass; say the word if the re-describe cost matters and it becomes one.
- The cheap screen versus the exact rule: the rule wins, and the back-catalogue read cost comes back. Worth knowing before the next full archive run, since CR-286B was written because that cost was felt. The memo means it is one extra read per original, not per proxy.
