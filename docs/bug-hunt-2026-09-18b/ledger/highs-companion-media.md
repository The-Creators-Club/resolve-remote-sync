# CR-288 - the companion-media highs of the tenth hunt

## CR-288 - four highs in today's own fixes: the verdict key, the intent row, the prune and the two-stage uploaded - FIXED in repo 2026-09-18 (companion 0.9.75, unshipped)

Every one of these is about a change made EARLIER TODAY (CR-282D/E, CR-284I,
CR-284N, CR-284R), so each fix builds on that change rather than around it.
Nothing here is a wire word: the companion's requests are byte for byte what
0.9.75 already sent.

### CR-288A (comp-resolve-1 = regression-1) - the geometry verdict was written under a key nothing reads - FIXED (proxy_relink.py)

`_geometry_disagrees` keys its memory on `probe` - the spelling
`_openable_path` proved this process can OPEN, which on a machine with no `P:`
mapping is the local twin (a service, a remote shell, every macOS editor).
`apply_relinks` wrote the post-refresh verdict under `op["file_path"]`, the
clip's LINKED canonical spelling, and `_geometry_key` normalises without
translating, so the two are different dict keys wherever the twin is in play -
and the fingerprint under the canonical key was a stat of a path this process
cannot stat. Every verdict CR-282D, CR-282E and CR-284R rest on was therefore
unreadable on exactly the machines the twin exists for: the refresh was
re-planned every 120 s for ever, each pass spending one of the eight
`resolve_journal.allow_automatic` grants a day, so within about sixteen
minutes genuine proxy attachments stopped for the rest of the day on that
machine.

`plan_relinks` now carries `probe_path` on the refresh op, from the one
`_openable_path` answer, beside the `stored_frames` its own comment said was
carried "so apply_relinks can remember the verdict under the same key the
probe used"; `apply_relinks` notes both verdicts (the no-change one and the
CR-284R one) under it, falling back to `file_path` when the key is absent, so
an op built by an older caller or injected by a test behaves exactly as
before.

Test: `::test_the_geometry_verdict_is_written_where_the_next_pass_reads_it` -
canonical `P:\...` clip, only the twin exists, both `exists` and `stat`
refusing the canonical spelling, two `plan_relinks` passes with a real
`apply_relinks` in between. The second pass must plan nothing and must not
re-run the whole-file demux.

### CR-288B (proxy-tiers-1) - an intent row nothing could falsify, for a download that never started - FIXED (broll_server.py, broll_standins.py)

CR-282C moved the stand-in ledger write to BEFORE the fetch so a download
nobody polls again is still remembered. Two holes: `STATE_BUSY` returns three
branches earlier than the retirement (at the two-download cap `poll_fetch`
starts nothing and registers nothing - its own docstring), and an exception
out of the fetch skipped every branch below it. Both left a row with
`size: None`, and `_entry_is_stale` reads a non-int size as "still a stand-in"
unconditionally, so that row could be falsified by nothing at all - not even
the real 6K original arriving at that path - and `_prune_locked` would only
retire it 30 days later, which the real original prevents. `_real_original_here`
then answers False for a file that IS the original, `plan_relinks`' `.mp4`
rule inverts, and `placed_report` tells the whole fleet.

Three parts, all in the companion:

  * the `STATE_BUSY` branch retires the row (nothing was started), and the
    fetch call is wrapped so anything that leaves without an answer does the
    same before re-raising the caller's exception unchanged;
  * `record(..., pending_fetch=True)` MARKS an intent row, so it is told apart
    from an ordinary entry whose size merely could not be read;
  * `settle_intents()` answers those rows on the 120 s cycle (called from
    `resume_pending_upgrades`, which already runs there): the row is settled
    by IDENTITY (CR-288B/2 below), and a path with no file at all after
    `INTENT_EXPIRY_SECONDS` (6 h, and only while the tree is demonstrably
    present) is a download that never landed and is retired.

Tests: `::test_a_download_that_never_started_leaves_no_standin_row`,
`::test_a_fetch_that_blows_up_leaves_no_standin_row`,
`::test_an_intent_row_whose_stand_in_landed_unobserved_becomes_falsifiable`,
`::test_an_intent_row_for_a_download_that_never_landed_is_retired`.

#### CR-288B/2 - and settled by IDENTITY, never by presence - FIXED (broll_standins.py, broll_fetch.py, broll_server.py)

The first cut of `settle_intents` measured whatever was at the path. That
reaches proxy-tiers-1's own outcome through the settlement: after a fetch that
failed unobserved, lane B or the editor's own copy can put the REAL ORIGINAL
at that path, and measuring it records the original's size as the stand-in's -
permanently, because the size then never changes again. `is_standin` answers
True for the real 6K file, `_entry_is_stale` never fires, the preview is
attached as its proxy and the rel is broadcast to the fleet. "Under-trusting a
file is the safe direction" is not true of a real original.

A stand-in IS the preview's bytes, so the file's own header decides. The row
already carries `geometry`, which is read with `ffmpeg_tools.probe_video` (one
open, never `-count_packets`) through a seam `broll_server._standin_probe`
resolves from this machine's configured ffmpeg.

**Note the polarity, which is the opposite of the one the fix was asked for
in.** That `geometry` is the ORIGINAL's, not the preview's: it comes from the
`videos` row (`routes_api._insert_object`), which the indexer probed from the
SOURCE clip, and the plan's own example is `6064x3424`
(docs/BROLL_PROXY_TIERS_PLAN.md line 294). So a header that MATCHES the row is
the real original and RETIRES the row with a line saying so; a header that
DIFFERS is the 1080p preview under the original's name, i.e. the stand-in, and
the row is measured. Reading it the other way round would retire exactly the
rows that must stand.

When the row has no usable geometry, or the header cannot be read, the
fallback is `broll_fetch`'s own job record for that destination - new
`broll_fetch.job_state(dest)`, which reads `_JOBS` under the lock and NEITHER
STARTS a job (as `poll_fetch` would when there is none) NOR POPS a terminal
one: DONE measures, FAILED retires, and anything else, including the "no such
job" that a restart makes of every job there ever was, LEAVES THE ROW PENDING.
A row that cannot be settled is not guessed at; it stays a stand-in, which is
the safe reading of a file that has not been identified.

Tests: `::test_the_real_original_arriving_at_a_pending_path_retires_the_row`,
`::test_a_row_nothing_can_identify_is_left_pending`,
`::test_a_fetch_the_registry_calls_failed_retires_the_row`,
`::test_the_job_registry_is_read_without_starting_or_popping_anything`.

### CR-288C (comp-broll-tiers-1) - a tree absent for one poll erased the ledger - FIXED (broll_standins.py)

CR-284N's 30-day prune dropped every entry whose file could not be stat'ed.
"Cannot be stat'ed" is not "has been deleted": an external sync drive pulled
(CR-92), a share not yet mapped at companion start, an SMB blip or a NAS
reboot makes every entry unstattable AT ONCE, so one poll dropped every old
row and the next write of any kind persisted it. When the drive came back
`is_standin` answered False for those paths and a 1080p H.264 lie read as the
real original - the one failure the module says it exists to prevent.

The prune now needs the TREE to be there: `_archive_root_of` walks the entry's
own path up to the `Assets/B-roll Archive` pair (the ledger holds no
local_root) and `_isdir` answers whether it is present, cached per root per
pass. A path whose archive root cannot be derived, or whose root is not there,
is skipped entirely. A prune that cannot tell does nothing.

Test: `::test_a_tree_that_is_absent_for_one_poll_does_not_erase_the_ledger`.
CR-284N's own test moved its two files under the archive, which is the only
place a stand-in can be.

### CR-288D (wire-1) - a clip could go live and its original fail in silence - FIXED (broll_ingest.py)

CR-284I's first `/uploaded` post (`original_uploaded: false`) is not a
partial-progress call on the server: `mark_uploaded` writes
`ingest_items.state = 'live'`, which is in the server's `ITEM_TERMINAL`, so
every later state write is refused with `400 illegal_transition`. The
companion's `_fail_item` posted `failed` into that refusal, kept the failure
locally only, and the batch then finished as plain `done` with
`videos.original_path` NULL for ever and no retry able to reach it.

The companion side, which works against today's server unchanged:
`_fail_item` diverts a `staged_live` item to `_note_original_failed`, which
leaves the item LIVE (which is what the server believes and what the editor is
already cutting with), records `original_failed`, says it at WARNING naming
the clip and what has to happen, and HOLDS the staged drop so the retention
clock cannot delete this machine's copy while the archive has none.
`_maybe_finish` carries `originals_failed` / `originals_owed` into the release
summary, which is the batch's own `error` text on the dashboard - the one
surface this side can still write to once the item is terminal.

The item state the server should grow (a non-terminal `proxies_live`) and a
retry that re-queues the original alone are OWED to webapps-tools; neither is
needed for this half to be honest.

Test: `test_broll_ingest.py::test_an_original_that_fails_after_the_clip_went_live_is_reported`,
with the server fake answering the real `400` to a state write on a terminal
item.

### CR-288E (overseer-1) - an original that is still uploading is a KNOWN original - FIXED (broll_server.py)

The two-stage `/uploaded` (CR-284I) opened a window nothing downstream knew
about: a clip is live on its proxies while a multi-GB original is still going
up. In that window `insert_target_detail` answered `original_rel: null`, which
CR-284F reads as "the archive holds no original for this clip" - a genuine,
first-class state - and `plan_insert` therefore returns `PLAN_PREVIEW_ONLY`:
the preview imported at the PREVIEW's own path. For a clip whose 6K original
is minutes away that is the wrong File Path on every machine the project
travels to.

The server now answers that window with the original's EXPECTED archive path
plus `original_pending: true` (webapps-tools, SERVER FIRST). The companion
half: `derive_insert_paths` carries `original_pending` on the derived object,
`original_known` stays True for it, and `plan_insert` therefore takes the
ordinary stand-in path - the preview fetched to the original's own path,
ledgered, the editing proxy as the background upgrade. Three rules hold the
edges, and each has a test:

  * `original_known = False` is still for an EXPLICIT NULL only. A null that
    arrives with `original_pending: true` is a server contradicting itself,
    and the null wins: refusing to invent an original is the safe half.
  * proxy-tiers-3's `known: false` ("the server could not look") clears it,
    like every other field in the object: a server that judged nothing has
    not judged this either.
  * ABSENT means today's behaviour exactly. Every deployed dashboard is in
    that state, and silence is not `false`.

The pending original landing at that path later needs nothing new: it is the
identity settlement of CR-288B/2 (the file stops being the preview's geometry
and becomes the original's), after which the fleet fact and the refresh path
take over.

Tests: `::test_an_original_still_uploading_gets_a_stand_in_not_the_preview`,
`::test_an_explicit_null_original_is_still_preview_only`,
`::test_a_null_original_that_also_claims_to_be_pending_is_still_no_original`,
`::test_a_dashboard_that_never_mentions_pending_behaves_exactly_as_today`,
`::test_a_server_that_could_not_look_is_never_pending`.

### Verification
- `companion/tests/test_bug_hunt_2026_09_18b_companion_media.py::test_the_geometry_verdict_is_written_where_the_next_pass_reads_it` -> fails before the fix, passes now
- `companion/tests/test_bug_hunt_2026_09_18b_companion_media.py::test_a_download_that_never_started_leaves_no_standin_row` -> fails before, passes now
- `companion/tests/test_bug_hunt_2026_09_18b_companion_media.py::test_a_fetch_that_blows_up_leaves_no_standin_row` -> fails before, passes now
- `companion/tests/test_bug_hunt_2026_09_18b_companion_media.py::test_an_intent_row_whose_stand_in_landed_unobserved_becomes_falsifiable` -> fails before, passes now
- `companion/tests/test_bug_hunt_2026_09_18b_companion_media.py::test_the_real_original_arriving_at_a_pending_path_retires_the_row` -> fails before (watched, with the settlement forced back to presence-only), passes now
- `companion/tests/test_bug_hunt_2026_09_18b_companion_media.py::test_a_row_nothing_can_identify_is_left_pending` -> fails before (same), passes now
- `companion/tests/test_bug_hunt_2026_09_18b_companion_media.py::test_a_fetch_the_registry_calls_failed_retires_the_row` -> fails before (same), passes now
- `companion/tests/test_bug_hunt_2026_09_18b_companion_media.py::test_the_job_registry_is_read_without_starting_or_popping_anything` -> pins `job_state`'s read-only contract
- `companion/tests/test_bug_hunt_2026_09_18b_companion_media.py::test_an_intent_row_for_a_download_that_never_landed_is_retired` -> fails before, passes now
- `companion/tests/test_bug_hunt_2026_09_18b_companion_media.py::test_a_tree_that_is_absent_for_one_poll_does_not_erase_the_ledger` -> fails before, passes now
- `companion/tests/test_broll_ingest.py::test_an_original_that_fails_after_the_clip_went_live_is_reported` -> fails before (watched, with the divert disabled: the summary has no `originals_failed` and the server logs the refused `failed` write), passes now
- `companion/tests/test_bug_hunt_2026_09_18b_companion_media.py::test_an_original_still_uploading_gets_a_stand_in_not_the_preview` -> fails before the fix (watched, with the field's parse disabled), passes now; the other four overseer-1 tests pin the edges that must NOT change
- Adjacent suites run green as a check on the blast radius: `test_broll_standins.py`, `test_broll_insert_tiers.py`, `test_proxy_relink.py`, `test_proxy_relink_standins.py`, `test_broll_server.py`, `test_broll_proxy_upgrade.py`, `test_watcher_broll_archive.py`, `test_library_walk.py`, `test_broll_ingest*.py`, `test_music_ingest.py`, `test_bug_hunt_2026_09_18_companion*.py` (all pass).

### Not fixed
- wire-1's server half: a `/uploaded` first stage still makes the ITEM terminal on the server. The companion no longer loses the failure, but the server cannot yet be told "this live clip's original never arrived", and the page's retry still cannot re-queue the original alone. OWED below.

### OWED TO ANOTHER GROUP
- webapps-tools: `broll/web/app/ingest_batches.py`: `mark_uploaded` / `ITEM_TERMINAL` / `retry_failed`: give the two-stage `/uploaded` an explicit non-terminal item state (`proxies_live`, NOT in `ITEM_TERMINAL`), written when `original_uploaded` is false, with `live` written only on the second post; `retry_failed` re-queues an item whose `original_uploaded` is 0 (the original alone); the batch panel shows "original still owed" for such a row, and `release`'s recount counts one as an error so a batch ends `done_with_errors`. SERVER DEPLOYS FIRST, and it is safe alone in both directions: the companion posts exactly the body it posts today, an older companion against the new server simply never posts the second stage for a clip it never staged, and a newer companion against the old server behaves as this fix leaves it (live item, WARNING, release summary).
- companion-core: none.

### Deploy order
- CR-288A, CR-288B, CR-288C are companion-only and need no dashboard change. Any order.
- CR-288D: dashboard/b-roll web BEFORE companions if webapps-tools lands the owed half; the companion half here is safe against either server.
- CR-288E: SERVER FIRST (that is where `original_pending` is minted), and it is safe in both directions on its own. A new server against an old companion is exactly today: the old companion ignores the field, and the non-null `original_rel` it now sees already routes it to the stand-in plan - the field is what stops a FUTURE reader treating "pending" as "absent". A new companion against an old server sees no field and behaves as today.

### Owner decisions
- `INTENT_EXPIRY_SECONDS` is 6 hours. It only ever retires a row whose file NEVER appeared and only while the tree is demonstrably present, so a slow link cannot trip it; shorten it only with that in mind.
- `settle_intents` identifies the file by its header geometry against the ORIGINAL's geometry on the row, because the preview's expected size is not on the insert object and its geometry is not either. One header read per intent row whose file has appeared, once, on the 120 s cycle.
- A row with no geometry and no live job record stays PENDING for ever rather than being guessed at. It still reads as a stand-in, which is the conservative direction, and the six-hour expiry cannot retire it while a file sits at that path. If that ever needs an ending, the honest one is an operator-visible notice, not a guess.
