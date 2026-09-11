# verdicts - webapps-ingest

Scope: comp-broll-music-1..4 (hunters/comp-broll-music.md), broll-1..3
(hunters/broll.md), music-1/2/3/5 (hunters/music.md). broll-1 and
comp-broll-music-3 are the same defect from the two ends of one wire and share
a single verdict below.

## comp-broll-music-1
- Verdict: CONFIRMED
- Reasoning: `_enqueue_uploads` (broll_ingest.py:2467-2487) declares
  `item["uploads"]` from the whole plan and then `continue`s past the
  `queue.enqueue` for any rel whose local file is gone. `_pump_uploads`
  (:2552-2578) only ever acts on a missing rel that is ALSO in
  `queue.failures()`, so a rel that was never handed over is neither landed nor
  broken and the loop `continue`s for ever: `upload_attempts` never moves,
  `_fail_item` is never reached, `_next_item` skips `uploading` by design and
  `_maybe_finish` counts the item as outstanding for ever, so `release` is never
  called and the heartbeat keeps renewing the lease. `music_ingest.py:465-496`
  has the identical shape for its one file. I tried to refute it on the
  "something else rescues it" axis and could not: there is no stall watchdog on
  an item, `MAX_ITEM_ATTEMPTS`/`MAX_UPLOAD_ATTEMPTS` are both unreachable from
  this state, and `_requeue_after_restart` calls the same `_enqueue_uploads`, so
  a tray restart re-declares and re-skips exactly the same rel.
- Evidence: reproduced against the real `BrollIngestor` with the repo's own
  `FakeQueue`/`FakeServer`, deleting the item's `local_path` between describe
  and enqueue (scratch test, not written into the repo):
  ```
  declared uploads: ['posters/4127.jpg', 'sprites/4127.jpg',
                     'creators/2026-08-18 ingest/Proxy/A001.mp4',
                     'creators/2026-08-18 ingest/A001.MP4']
  queued rels:      ['posters/4127.jpg', 'sprites/4127.jpg',
                     'creators/2026-08-18 ingest/Proxy/A001.mp4']
  after 20 pumps -> batch held: True   stage: uploading   upload_attempts: None
  released: []
  ```
  The one factual correction to the hunter: deleting the state file is NOT the
  only cure - the dashboard's CANCEL reaches the heartbeat
  (`_heartbeat_loop` -> `reply["cancel_requested"]` -> `self.cancel(...)`,
  broll_ingest.py:2763), which frees the machine at the cost of the whole
  batch. That is a manual escape hatch, not a recovery, so the severity stands.
- Fix note: the hunter's fix is right and is the minimal one - add the rel to
  `item["uploads"]` only after `queue.enqueue` returned, and fail the item when
  a REQUIRED local file (the original, or music's single audio file) is gone.
  Two knock-ons to check: `_pump_uploads` derives `original_uploaded` from
  `rels.values()`, so dropping a missing original correctly reports
  `original_uploaded: False` rather than lying to `mark_uploaded`; and
  `_requeue_after_restart` (broll_ingest.py:1902-1923) depends on
  `_enqueue_uploads` being callable twice, which the change preserves. Both
  `companion/src/ccsync_companion/broll_ingest.py` and `music_ingest.py` must
  change together, with cases in `companion/tests/test_broll_ingest.py` and
  `tests/test_music_ingest.py` (today `FakeQueue` models the failure ledger but
  not "it was never handed over at all"). The belt-and-braces counter in
  `_pump_uploads` is worth having as well, since it closes the same class for
  comp-broll-music-7's dead-worker shape.

## comp-broll-music-2
- Verdict: CONFIRMED
- Reasoning: `prune_staging` excludes only the RUNNING batch's staging id
  (`_staging_entries`) and the `held_for_base_rig` entries (CMEDIA-4). A drop
  staged but never run has no `ended_at`, so the code falls back to `at`, and
  with `max_age_days=0` the cutoff is `now`, which every past `at` is older
  than: `rmtree` plus `self._staging.pop`. Both the function's own docstring
  ("neither is a drop that has been staged but not yet run - an editor who
  staged 40 clips and went to lunch has not lost them"), `_iso_epoch`'s
  docstring ("the pruner never touches ... a drop that has not been run") and
  KNOWN_BUGS MEDIA-3 (line ~7104) assert the invariant the code breaks, so this
  is not a documented trade-off.
- Evidence: read at broll_ingest.py:3023-3071 and app.py:6460-6479; the
  `ended_at` fallback is unconditional and the only `continue`s above it are the
  base-rig hold and a missing `at`. KNOWN_BUGS records the invariant as
  delivered, so the finding is new, not an open ledger entry.
- Fix note: the suggested fix is right but should be the stronger form - skip
  any entry with no `ended_at` at ALL retention values, not only at 0. At the
  default 7 days the same fallback silently deletes a drop staged eight days ago
  that was never run, which is the identical loss on a slower clock. Touch
  `broll_ingest.prune_staging` only; `app.clear_finished_ingest_staging`'s
  "There is no finished staging to clear" wording already covers the
  nothing-removed case. Add a companion test for a staged-but-never-run entry
  under `max_age_days=0` and under the default.

## broll-1 + comp-broll-music-3 (one defect, two reports)
- Verdict: CONFIRMED (medium). The fix belongs on the WEB side
  (`broll/web/static/ingest.js`, plus the misleading comment in
  `broll/web/app/ingest_batches.py`), not in the companion.
- Reasoning: `retry_failed` returns `items = [ingest_items.uid, ...]` (32-hex,
  minted by `new_uid`) and its comment claims "that is the body the companion's
  `/broll/ingest/retry` takes". It is not. `Ingestor.retry`
  (broll_ingest.py:1510-1564) matches `wanted` against the keys of
  `self._staging[sid]["items"]`, which are browser-minted local ids
  (`ingest.js:388`, `i${Date.now().toString(36)}...`, capped by
  `_clean_local_id`), and `ingest_items` has no `local_id` column at all
  (`grep -n local_id broll/web/app/ingest_batches.py` -> only the precheck echo
  at :489). The namespaces cannot intersect, so `retried` is 0 and the answer is
  `200 {"ok": true, "retried": 0}` - which means the page's `e.status === 404`
  fallback to `/broll/ingest/run` (the path that would actually claim the batch)
  never fires, and the toast still says "12 clips queued again". The two routes
  are also about different failures: the companion's `/ingest/retry` is BROLL-5,
  the browser->companion STAGING upload ledger; the server's `retry-failed` is
  BROLL-18, batch items that failed to INDEX. Even a perfect id mapping would
  make the companion rewrite the wrong ledger, which is why the fix is not "also
  accept uids".
- Evidence: both ends read in full; `ingest.js:1708-1712` sends
  `{ items: answer.items || [] }`; `ingest_batches.py:563-590` fills `item_uids`
  from `SELECT uid ... WHERE state = 'failed'`;
  `broll_ingest.py:1539` is `if wanted and str(local_id) not in wanted: continue`.
  Partial mitigation the hunters did not name: after the retry the batch is
  `queued` with `n_failed == 0`, so the panel's next `ingestLoadBatches()`
  re-renders it with `[ take over on this computer ]` (ingest.js:1612-1618) -
  the editor has a visible, working way out on the same card, they are just not
  told they need it.
- Fix note: in `ingestRetryFailedBatch`, drop the `{items: ...}` call and go
  straight to the take-over dispatch (`POST /broll/ingest/run` with
  `{batch_uid, staging_id: null, ...}`) - that is the already-tested path,
  needs no companion change, and works on every build in the fleet including the
  pre-0.9.67 ones. Also delete the "that is the body the companion's
  /broll/ingest/retry takes" comment in `retry_failed`, and assert on the BODY
  in `broll/web/tests/test_ingest_retry_and_takeover.py:257-269`, which today
  only greps the function for the string `"/broll/ingest/retry"` - the exact gap
  the defect lives in. If instead you keep the loopback call, the companion's
  `retry()` must answer 404/409 on an unmatched id set rather than 200, or the
  fallback stays dead.

## comp-broll-music-4
- Verdict: DOWNGRADED to low
- Reasoning: the mechanism is real - `git show 097f5a3:broll/web/static/app.js`
  continues its poll loop only on `state === "downloading"`, so a
  `200 {"ok": true, "state": "busy"}` falls through to
  `toast(body.message || "Sent to Resolve.", "success")` and returns, and the
  in-tree comment at broll_server.py:765-770 ("the older pages ... see a success
  with nothing inserted yet and poll on") is simply wrong. But the harm is much
  smaller than a green "Sent to Resolve": `message` is always populated
  (`broll_fetch.BUSY_MESSAGE` = "this computer is already downloading as much as
  it will at once. This one starts as soon as a slot is free"), so the editor
  reads an accurate statement that the clip has not gone in yet. What is
  genuinely wrong is the colour and the unkept promise - on an old page nothing
  resumes when a slot frees, because `STATE_BUSY` refuses rather than queues.
  Reachability is also narrower than stated: the deployed dashboard is 0.7.42,
  so this needs a browser holding a cached pre-2026-09-04 `app.js`.
- Evidence: the two app.js revisions read side by side; no branch in the old
  loop tests `state === "busy"`; the current page's `busyNow`/`busyOld` pair is
  at app.js:1754-1757.
- Fix note: the hunter's wording fix is the right one and is cheap - keep
  `state: "busy"` and `ok: true` for the current page if you like, but the
  message must not be printable as a success; or simply correct the comment,
  which is wrong either way. If you flip `ok` to `false`, check
  `broll/web/tests/test_send_busy_is_a_queue.py` and the `busyOld` regex at
  app.js:1755 (it matches `/already downloading/i`, which the current sentence
  also contains), and `music_server.py:497-505` carries the same shape.

## broll-2
- Verdict: CONFIRMED (high)
- Reasoning: I built a real v1 `client_shares.db` and drove the real module at
  it. CPython's sqlite3 runs DDL in autocommit, so `ALTER TABLE ... ADD COLUMN
  hash` is durable the instant it executes while `PRAGMA user_version` is only
  written after `_backfill_hashes()`. Anything that re-enters `ensure_schema`
  in that window - or after a process death inside it - re-runs the ALTER and
  raises `OperationalError: duplicate column name: hash`, which nothing catches:
  it escapes `get_shares_db` (a per-request dependency) as a 500 on every
  client-folder route and every public `/broll/share/<token>/...` link, and at
  boot it sends the whole mount DEGRADED. Nothing self-heals. I did knock down
  the hunter's primary trigger: `mount_broll` calls
  `client_folders.ensure_schema()` at boot (broll.py:552) BEFORE any request is
  served, so the normal upgrade path is serialised and two concurrent first
  requests do not usually race. What is left is still enough: a container
  killed, OOM-ed or restarted during the backfill (which broll-6 shows is one
  unindexed UPDATE per `videos` row, i.e. seconds on a real archive), a
  deployment whose `_init_broll_storage` raised earlier so the boot call never
  ran, or the bare `broll/web` app run without the dashboard shim. The
  consequence - the public client links, the one thing CLAUDE.md says must never
  be at risk - is permanent and needs hand-editing `PRAGMA user_version` on the
  NAS.
- Evidence: from the b-roll venv, against a hand-built v1 ledger with the ALTER
  already applied:
  ```
  start user_version: 1
  in_transaction after ALTER: False
  second connection sees column: [... 'added_at', 'hash']
  user_version still: 1
  ensure_schema RAISED: OperationalError duplicate column name: hash
  ```
  The existing test that looks like it covers this,
  `broll/web/tests/test_a_v1_ledger_gains_the_hash_column_and_is_backfilled`
  (test_client_folders.py:349-374), drops the column and resets `user_version`
  in the same commit, so it never constructs the half-migrated file.
- Fix note: the suggested fix is right. Make the step idempotent by asking
  `PRAGMA table_info(client_folder_items)` for the column rather than trusting
  `user_version` alone, and wrap the whole version==1 branch in
  `BEGIN IMMEDIATE` so two threads cannot both enter it. Catching
  `OperationalError` on the message text is the weaker second choice (the
  message is not API). A `try/except` around `ensure_schema()` inside
  `get_shares_db` is worth adding on its own merits - one bad ledger should not
  take the public share door out - but it must not swallow the "newer
  user_version" RuntimeError, which is deliberately fatal. Files: only
  `broll/web/app/client_folders.py`; add a test that runs `ensure_schema` twice
  over a v1 file whose ALTER already landed.

## broll-3
- Verdict: DOWNGRADED to low
- Reasoning: the factual half is right - `FleetClient` issues no GET at all
  (`_url` is used by claim/heartbeat/status/result/uploaded/release only, and
  `grep -rn "fleet/ingest" companion/src/` finds just the prefix constant in
  `ingest_kinds.py:198`), so `GET /api/fleet/ingest/batches` has no caller and
  the `_broll_fleet_list_re` carve-out in the dashboard's login gate exists for
  nobody. But the failure scenario is refuted by the feature's OWN ledger entry
  and by the page: KNOWN_BUGS BROLL-8 (line ~12950) names the panel's
  `[ take over on this computer ]` button as the affordance, and
  `ingest.js:1612-1618` renders it for every `queued` batch in the editor's
  `mine` scope, dispatching the uid to THIS machine's loopback. A rebuilt EDIT-03
  opening the ingest panel - the thing its editor does in order to drop more
  clips - sees the orphaned batch and can take it. So "picked up by NOTHING"
  is not the current state; what remains is a dead route plus an unused gate
  carve-out (a small, GET-only, credential-still-required piece of attack
  surface) and a docstring that misdescribes it.
- Evidence: greps above; routes_fleet.py:120-157 read in full;
  dashboard/app.py:1067 + :1166-1170 for the carve-out; ingest.js:1600-1618 for
  the button and its `batch.state === "queued" && ing.scope === "mine"` guard.
- Fix note: do not build the companion poller on the strength of this finding -
  a companion that discovers and claims batches on its own would change who
  decides what a machine works on, and the plan's rule is that possession is
  won by a claim the PAGE dispatches. The honest fixes are either to say plainly
  in the ledger that the discovery route shipped without a client, or to delete
  the route and the `_broll_fleet_list_re` carve-out together. Either way fix
  the NOTE in `routes_fleet.discover`'s docstring (that is broll-4, and it
  claims the gate still needs widening when it was widened in the same commit).

## music-1
- Verdict: CONFIRMED (high)
- Reasoning: `allocate_name`'s `while` (ingest_batches.py:236-242) has no
  ceiling and both of its predicates answer TAKEN on error, so any PERSISTENT
  error is an infinite tight loop on a uvicorn threadpool thread. I attacked the
  hunter's own scenario successfully - with a wholly unreadable music.db the
  route never reaches `allocate_name`, because `_leaseholder_or_410` and
  `_item_or_404` query the same connection first and 500 (routes_fleet.py:216-218)
  - and then found a much better trigger that needs no database fault at all.
  `pathlib.Path.exists()` swallows only ENOENT/ENOTDIR/EBADF, so an EACCES or
  EIO from `stat()` PROPAGATES, and `_taken_on_disk`'s `except ... OSError:
  return True` turns it into "taken" for every candidate. A music library root
  that the container's uid can stat but not traverse - exactly the bind-mount
  ownership failure the b-roll mount calls "overwhelmingly" the cause of a
  degraded mount - passes `share_root_ready` whenever the index has no `tracks`
  rows yet (`if not rows: return True, ''`, config.py:479-480), i.e. on a fresh
  customer deployment, and then spins for ever inside `allocate_name`.
- Evidence: reproduced from `music/web/.venv` (scratchpad), `safe_join` raising
  EACCES and an index with no tracks:
  ```
  gate: (True, '')
  _taken_on_disk('theme.mp3'): True
  allocate_name still running after 4 s: True {}
  ```
  and the DB-flavoured variant the hunter reported also reproduces in isolation
  (`share_root_ready -> (True, '')`, `allocate_name` alive after 4 s) - it is
  only the ROUTE-level reachability of that one I refuted. `pathlib._IGNORED_ERRNOS`
  on this interpreter is `['ENOENT', 'ENOTDIR', 'EBADF', 'WSAELOOP']`.
- Fix note: the suggested fix is right and both halves are needed. Cap the loop
  and 503 on fall-through, and separate "taken" from "could not tell" - but note
  that flipping `_taken_on_disk`/`_taken_by_a_track` to RAISE on error changes
  the contract their docstrings pin (bug-hunt-2026-09-03 music-3), so the
  safest shape is to keep them returning True and let the cap produce the 503.
  Whatever the server does here must be landed WITH music-2's companion-side
  classification, or the new 503 is consumed as a permanent track failure by
  every companion in the fleet. Files: `music/web/musicweb/ingest_batches.py`,
  a test with a failing connection and one with a failing filesystem, and the
  companion's `music_ingest._post_result`.

## music-2
- Verdict: DOWNGRADED to medium
- Reasoning: the shape is real - `_post_result` (music_ingest.py:414-424)
  branches on `status != 200` alone, clears `embedded`, calls `_fail_item` and
  returns False, and only 410 is special-cased upstream in `IngestClient._call`.
  So the server's two "try again" statuses (409 `name_race`, and the new 503
  from `share_root_ready` via `allocate_name`) are handled as refusals. But the
  hunter's central claim - "`_fail_item` is terminal ... with no attempts budget
  and no re-queue" - is wrong, and that is the reason for the downgrade.
  `_next_item` (broll_ingest.py:2084-2096) deliberately returns a FAILED item
  whose `attempts < MAX_ITEM_ATTEMPTS` (2), `_drain` loops immediately, and
  music's `_crunch_item` re-embeds because `_post_result` cleared `embedded`
  (the comment at music_ingest.py:335-337 says exactly that). So a 409
  `name_race` IS retried once and does re-allocate around the collision, which
  is what the server's comment promises. What survives is still a defect: only
  two attempts, both inside the same `_drain` pass with no backoff at all, so
  any outage longer than one re-embed burns the budget and kills the track - and
  unlike b-roll there is no `retry-failed` route or button anywhere in
  `music/web`, so a failed music item is dead until the editor re-drops the file
  by hand.
- Evidence: `_drain` at broll_ingest.py:2058-2082 re-selects the same item;
  `MAX_ITEM_ATTEMPTS = 2` at :119; `_crunch_item`'s `if not item.get("embedded")`
  gate at music_ingest.py:308; `grep -n retry music/web/musicweb/routes_batches.py`
  returns nothing, so there is no music equivalent of BROLL-18.
- Fix note: the suggested fix (branch on `reason`, not on the status) is right,
  and the server already names it. Two things a fix must not break: 409
  `model_mismatch` and 422 must stay terminal, and whatever budget you add has
  to leave `MAX_ITEM_ATTEMPTS` alone for the crunch failures it was written for -
  a retry that re-embeds the track is expensive, so the retry for a 503 should
  re-POST the existing analysis rather than re-enter `_crunch_item`. Land it
  together with music-1's server-side 503, and add the cross-tree test the
  suites lack (nothing anywhere asserts what `_post_result` does with a 409 or a
  503). Files: `companion/src/ccsync_companion/music_ingest.py`, and
  `broll_ingest.py` if the classification is hoisted into `IngestClient._call`.

## music-3
- Verdict: CONFIRMED (medium)
- Reasoning: `rescore_library` takes `ids, mat = db.load_matrix(con)` first,
  spends seconds in numpy, and then unconditionally
  `DELETE FROM meta WHERE key = 'scores_stale'` (rescore.py:340-362). The marker
  is a library-wide fact but the pass only covers the snapshot, so a
  `mark_scores_stale` written by another threadpool thread during the numpy
  window is erased by a rescore that never saw that track. `_settle_scores`
  (routes_fleet.py:145-147) is gated on exactly that marker, so the end-of-batch
  settle - the guarantee MUSIC-5 exists to provide - is skipped and the track
  ends up in the library with no tags, no axes and no facet membership, while
  `/api/stats` reports `scores_stale: null` so the SPA's catching-up banner does
  not show either. I could not refute the interleaving: the container runs one
  uvicorn worker but these are sync routes dispatched to a threadpool, and
  SQLite serialises the writes, not the numpy pass between them. The window is
  bounded in practice - it only bites the LAST track(s) of the second batch,
  because any later non-deferred `result` in that batch rescores the library
  including it - which is why medium, not high, is right.
- Evidence: rescore.py:355-360 (the DELETE inside the same `with con:` as
  `tagged_at`, compared against nothing), :390-394 (the defer branch's
  `mark_scores_stale`), routes_fleet.py:130-152. `test_rescore_transaction.py`
  is single-threaded throughout, so it cannot see this.
- Fix note: the "capture the marker before `load_matrix` and only DELETE if
  unchanged" fix is correct and is the smaller change; note the marker's value
  is an ISO timestamp from `_now()`, so two marks inside the same second would
  compare equal - prefer comparing `max(tracks.id)` (or both) over the string.
  The alternative the hunter offers, having `release` call
  `apply_for_track(..., force=True)`, also fixes music-4's docstring drift but
  changes `_settle_scores` from best-effort-after-release into a per-track call,
  so check the "raising here would make the companion retry a release that
  already happened" contract still holds. Files: `music/web/musicweb/rescore.py`
  and possibly `routes_fleet.py`; a test would need two threads or an injected
  seam in `rescore_library`.

## music-5
- Verdict: CONFIRMED (medium)
- Reasoning: the probe really is `SELECT rel_path FROM tracks WHERE rel_path IS
  NOT NULL ORDER BY id LIMIT 50` (config.py:476-477, `_READY_SAMPLE = 50`), i.e.
  the fifty OLDEST rows, and the only escapes are "no rows at all" and "one of
  these fifty exists". A negative answer closes the whole write path -
  `/music/api/ingest`, `_ingest_inline` and every fleet `result` via
  `allocate_name` - with a message that blames the mount, and there is no
  override. I looked for a reason this cannot happen and did not find one: the
  library is FLAT (rel_path IS the filename), `db.prune_missing` exists
  precisely because rows outlive files, and `_taken_by_a_track`'s own docstring
  cites "a row's file was removed by hand without a --prune" as a normal state.
  The realistic trigger is smaller than the hunter's 400-track reorganisation:
  any library whose entire indexed set is old enough to have been replaced -
  a small or early library cleared out and re-imported without `--prune` - is
  permanently 503. I kept it at medium rather than raising it because it does
  need ALL fifty sampled files to be gone at once.
- Evidence: query and loop read; `_READY_SAMPLE` grepped; the same helper is the
  503 in `allocate_name` (ingest_batches.py:230-232), so one bad sample closes
  the fleet path too.
- Fix note: `ORDER BY id DESC` is the right change (the newest rows are the ones
  most likely to still exist) and is one word; a random sample is better still
  but costs an ORDER BY RANDOM() on every call. Cache the POSITIVE answer for a
  few seconds while you are there - the secondary cost the hunter names is real,
  up to 50 stat()s over SMB/NFS per `allocate_name`, i.e. per item of every
  drop. Do not make the negative answer overridable by config without also
  keeping the `_taken_by_a_track` third member of the collision set, which is
  what stops a name being handed out over an indexed track when the share is
  actually absent. Files: `music/web/musicweb/config.py`; check
  `music/web/tests` for anything pinning the current ordering before changing
  it.
