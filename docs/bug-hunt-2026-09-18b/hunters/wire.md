# wire - every contract between two processes, both sides side by side

Files read (with approximate coverage):
- `companion/src/ccsync_companion/app.py` (the report builder `sync_guard`/
  `resolve_health` blocks, the whole report-reply fan-out, `_apply_file_moves`,
  `_note_dashboard_version` / `_dashboard_knows_state_word` /
  `_synced_project_rels`, `_queue_file_move_answer` / `_file_move_results`,
  `standins_owed`) - ~70% of the changed hunks.
- `dashboard/src/ccsync_dashboard/api.py` (`ReportIn`/`SyncGuardIn`/
  `ResolveHealthIn`/`StrayProjectsIn`/`StandinsPlacedIn`/`StandinsOwedIn`/
  `FileMoveResultIn` + its new `_unknown_state_is_no_state` validator, the
  report-reply builder, `_upgrade_info`'s `withheld`, `flatten_sync_guard`) -
  every hunk that touches a wire key.
- `dashboard/src/ccsync_dashboard/db.py` (`record_standins_placed`,
  `standins_known`, `media_rel_key`), `locate.py` (whole diff).
- `companion/src/ccsync_companion/sync/server_locate.py` (the `unreadable`
  reader), `upgrade.py` (`note_report_response` / `upgrade_none_reason`),
  `proxy_relink.py` (`note_fleet_standins`, `fleet_says_standin`,
  `_geometry_disagrees`, `plan_relinks`, `apply_relinks`),
  `broll_standins.py` (`placed_report`, `archive_rel_of`, `normalise_key`),
  `broll_server.py` (`_derive_tiers`, `plan_insert`),
  `broll_ingest.py` (`item_uploaded`, `_post_uploaded`, `_maybe_stage_live`,
  `_pump_uploads`, `_fail_item`), `sync/rclone_lane.py`
  (`_refresh_stray_projects`).
- `broll/web/app/ingest_batches.py` (`mark_uploaded`, `set_item_state`,
  `_check_transition`, `release`, `retry_failed`), `app/schemas.py`
  (`ItemUploadedIn`), `app/routes_api.py` (`insert_target_detail`,
  `_insert_object`), `app/routes_batches.py`.
- `dashboard/src/ccsync_dashboard/cards_tunnel.py` (whole diff).

Tests run:
`broll/web/.venv/Scripts/python.exe -c "from app import ingest_batches as ib;
ib._check_transition('live','failed')"` -> `HTTPException 400
{'detail': 'item is already live; it cannot become failed', 'reason':
'illegal_transition', 'state': 'live'}` (proves wire-1). No pytest suite run
(the gate runs once, centrally).

## Findings

### wire-1 - the two-stage `/uploaded` makes the item terminal, so the original's upload can never fail, be retried, or be noticed
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_ingest.py:3116-3169`
  (`_maybe_stage_live`) and `broll/web/app/ingest_batches.py:1216-1243`
  (`mark_uploaded`'s `UPDATE ingest_items SET state = 'live'`) /
  `broll/web/app/ingest_batches.py:94` (`ITEM_TERMINAL`) /
  `broll/web/app/ingest_batches.py:852-869` (`_check_transition`)
- What: `_maybe_stage_live` posts `/uploaded` with `original_uploaded=False`
  while the original is still going up. That route is not a partial-progress
  route: it writes `ingest_items.state = 'live'`, which is in `ITEM_TERMINAL`.
  Every subsequent state write for that item goes through `set_item_state` ->
  `_check_transition`, which raises `400 illegal_transition` out of any
  terminal state. The companion's `_fail_item` catches that as a plain
  `Exception` and logs it at DEBUG (`broll_ingest.py:3464-3465`), so the
  failure is swallowed on both sides.
- Failure scenario: a 6K drop. Preview + editing proxy land, `_maybe_stage_live`
  takes the clip live, the editor starts cutting. The original's rclone job
  then dies four times (`MAX_UPLOAD_ATTEMPTS`) - a dropped VPN, a full NAS
  dataset, a pulled sync drive. `_pump_uploads` calls `_fail_item`, the server
  answers 400, the companion writes `item["stage"] = "failed"` locally only.
  `release(state="done")` then recounts from the server, sees the item `live`
  and no failures, and the batch finishes as **`done`**, not
  `done_with_errors`. `videos.status` stays `indexed` with `original_path`
  NULL for ever. `retry_failed` only re-queues rows in state `failed`
  (`ingest_batches.py:571-577`), so the page's retry can never reach it, and
  `broll_upload.py:21`'s claim ("the item's `original_uploaded` stays 0 and
  the page offers a retry") is not backed by any code - `original_uploaded` is
  exposed at `ingest_batches.py:409` and read by nothing in `broll/web/static/`.
  The same swallow hides `_fail_item`'s "the upload of N file(s) never started
  on this computer" (LOST_UPLOAD_TICKS) arm.
- Evidence: the snippet above (400 refused); `grep -rn original_uploaded
  broll/web/static/` -> no hits; `grep -rn "staged_live\|_maybe_stage_live"
  companion/tests broll/web/tests` -> **no hits at all**, so nothing in either
  suite exercises the second stage or the failure after it.
- Ledger: new (opens a neighbour of proxy-tiers-5)
- Suggested fix: either give `/uploaded` an explicit two-stage shape (a
  `partial`/`proxies_live` item state that is not in `ITEM_TERMINAL`, with
  `mark_uploaded` writing `live` only on the `original_uploaded=True` post),
  or make the original's failure after staging its own reported condition: a
  route that records "this live clip's original never arrived" on the item and
  surfaces it on the batch panel, plus a retry that re-queues the original
  alone. At minimum, `_fail_item` must distinguish the 400
  `illegal_transition` answer from a transport error and say so at WARNING.

### wire-2 - the companion never forgets a dashboard version, so a rollback below 0.7.50 422s its reports for as long as a `not_synced_here` move is redelivered
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:1331-1362`
  (`_note_dashboard_version`, `_dashboard_knows_state_word`) and
  `dashboard/src/ccsync_dashboard/api.py:8796-8834` (`FileMoveResultIn.state`,
  whose `_unknown_state_is_no_state` validator explicitly "CANNOT HELP A
  DASHBOARD OLDER THAN THIS BUILD")
- What: `_note_dashboard_version` writes `app._dashboard_version` only when the
  reply carries a non-empty `dashboard_version`; an absent key leaves the
  remembered value untouched. Its own docstring states the opposite reading
  ("an ABSENT `dashboard_version` means a dashboard older than the one that
  started sending it, which is the safe reading"), and the gate that consumes
  it is latched permanently open once any 0.7.50 reply has been seen.
- Failure scenario: 0.7.50 is deployed, a machine answers a section-4b move
  with `state="not_synced_here"`, the operator rolls the dashboard back to
  0.7.49 (a first-class operation - `docs/RELEASE.md`, and the image-mode
  redeploy this fleet uses). The 0.7.49 `FileMoveResultIn` Literal has no
  `not_synced_here`, and `file_moves_applied` is not a tolerant section, so the
  **whole report** 422s - lanes, presence, alarms. The move is redelivered
  (it was never recorded applied), the companion re-answers from its ledger at
  `app.py:8092-8095` with the same word, because `_dashboard_version` is still
  "0.7.50", and every report carrying that answer 422s again. Only a tray
  restart clears it. The same shape applies to a customer whose companions
  briefly reach a second, older container.
- Evidence: `_note_dashboard_version` has no `else` clearing the attribute;
  `_dashboard_knows_state_word` reads `getattr(app, "_dashboard_version", "")`
  with no freshness bound; the 0.7.49 model at
  `git show HEAD:dashboard/src/ccsync_dashboard/api.py` line 8611 is
  `Literal["done","failed","retrying","parked"]` plus `blocked`/`applying`
  (no `not_synced_here`).
- Ledger: new (res-fleet-3 does not close its own rollback case)
- Suggested fix: make the absent key mean what the docstring says - clear
  `_dashboard_version` (or stamp it with the reply time and treat a version
  older than the last N replies as unknown) whenever a well-formed reply
  carries no `dashboard_version`. One extra probe report is the cost; the
  current cost is every report from that machine.

### wire-3 - `standins_known` is a fleet-wide, never-expiring list answered to every machine, and a `True` from it is conclusive with no probe
- Severity: medium
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (the grant-starvation size)
- Where: `dashboard/src/ccsync_dashboard/db.py:8869-8886` (`standins_known`,
  no `editor`/`machine`/rel filter and no age bound) called at
  `dashboard/src/ccsync_dashboard/api.py:9870-9872`, against
  `companion/src/ccsync_companion/proxy_relink.py:476-487` and `:560-572`
- What: the reply block is documented on both sides as "the rels **this
  machine listed**" (`api.py:9859-9862`, `proxy_relink.py:425-427`,
  `broll_standins.py:100-105`). The query does not intersect with the report's
  `standins_placed` at all: it is `SELECT archive_rel ... GROUP BY archive_rel
  ORDER BY last_seen DESC LIMIT 200` over the whole `broll_standins` table.
  `fleet_says_standin` returning `True` short-circuits `_geometry_disagrees`
  to True with **no probe and no header check**, and the caller turns that into
  a `refresh` op - a real `ReplaceClip` on the clip's own path, journalled,
  behind a SaveProject, and one of the 8 `allow_automatic` grants a day.
- Failure scenario: a remote editor stands in for
  `Creators_Club/FF5/A001_0003.mov`. The wired rig holds the genuine original
  at that archive rel and has imported it natively into a DIFFERENT project
  whose stored geometry is already correct. On the wired rig
  `_under_archive` is true, `original_present()` is true, `is_standin()` is
  false, and the fleet answer says True, so the clip is refreshed even though
  nothing about it disagrees. `_GEOMETRY_VERDICTS` is a module dict with no
  persistence, so this repeats after every companion restart and for every
  such clip in the pool; `apply_relinks` bounds it to about two ReplaceClips
  per clip per process (the `changed: False` arm remembers it under the new
  stored count), but the ops are planned before the grants are spent. A pool
  holding a dozen archive clips any editor ever stood in for therefore burns
  the day's 8 `allow_automatic` grants on no-op refreshes, which
  `apply_relinks`' own comment at `:1035-1043` names as the harm ("genuine
  proxy relinks are rate-limited out for the rest of it"). The rel is never
  retired either: `placed_report` sends "every entry, stale or not", and
  `standins_known` has no age filter, so the fact is permanent.
- Evidence: read both SQL and both readers; `record_standins_placed` and
  `standins_known` share no predicate; `fleet_says_standin` is asked before
  `header_frames_fn` at `proxy_relink.py:565`.
- Ledger: new (proxy-tiers-4 built the wire wider than its own contract)
- Suggested fix: pass the reporting machine's `standins_placed.rels` (or the
  set of archive rels it just declared) into `standins_known` and intersect,
  as both comments promise; exclude rows written by the asking
  `(editor, machine)`; and bound by `last_seen` so a stand-in replaced months
  ago stops answering. Cheapest partial fix: keep the fleet `True` as a hint
  that lets the HEADER estimate run rather than as a conclusive verdict.

### wire-4 - `standins_known` never sends the empty list both sides' contracts say it sends
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9870-9872` (`if known:`)
  against the comment two lines above it (`api.py:9864-9866`: "an empty list
  is sent for the same reason, so the two shapes cannot be confused") and
  `companion/src/ccsync_companion/proxy_relink.py:428-433` (the documented
  THREE states)
- What: the third state ("this dashboard looked and there are none") is never
  put on the wire. A fleet with zero stand-ins is indistinguishable from a
  dashboard that has never heard of the key, so `_FLEET_KNOWN` stays False and
  every archive clip falls through to the header estimate and the packet
  count - exactly the demux the feature exists to avoid, in the case where it
  would help most (a wired rig whose fleet has placed none).
- Failure scenario: today's fleet. `broll_standins` is empty on every machine
  (the feature has never shipped), so `standins_known` returns `[]`, the key is
  omitted, and the first wired-rig relink pass after the deploy demuxes the
  archive exactly as it does now. The operator reads the log line "the fleet
  knows of 0 stand-in(s)" never - it is only emitted when the key arrives.
- Evidence: `if known:` is the only guard; `note_fleet_standins` sets
  `_FLEET_KNOWN = True` for an empty `rels` list, so the companion side is
  already correct.
- Ledger: new
- Suggested fix: `result["standins_known"] = {"rels": known}` unconditionally
  inside the existing `try`.

### wire-5 - the Cards tunnel's new no-engine hold parks one threadpool worker per cards-role machine for the whole poll
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/cards_tunnel.py:179-208`
  (`_wait_for_an_engine`) and `:405-424` (`cards_agent_pending`)
- What: the fix replaces an immediate 200 with a blocking `time.sleep` loop of
  up to `MAX_WAIT_SECONDS` inside a blocking `def` route. That is correct for
  the pacing problem it names, but it converts "no episode open" from a busy
  request loop into a permanently parked AnyIO threadpool worker per agent,
  plus a `get_conn` sqlite handle held open for the same window
  (`api.py:107-112` opens one per request). The dashboard runs
  `--workers 1`, and every other blocking `def` route in the dashboard draws
  from the same 40-slot pool.
- Failure scenario: a customer with `cards_agent` on across a 30+ machine
  fleet and no episode open (a container restart, overnight). Thirty workers
  sit in `_sleep`, and the fleet page, the report route and the setup wizard
  contend for the remaining ten. On this fleet (four machines, the flag off
  everywhere) it cannot bite today.
- Evidence: read the route; `_sleep` is `time.sleep`, the route is a `def`,
  and the `conn` dependency's `finally: conn.close()` runs only after the
  hold.
- Ledger: new (neighbour of dash-cards-1)
- Suggested fix: cap the hold well below `MAX_WAIT_SECONDS` for the no-engine
  answer (a few seconds is enough to stop the spin), or make this one route
  `async def` with `anyio.sleep`, since the no-engine arm never touches the
  blocking engine.

## Coverage note
Read both ends of every wire key the brief named
(`unreadable`, `standins_placed`, `standins_known`, `dashboard_version`,
`not_synced_here`, `upgrade_none_reason`, `refreshed`, `standins_owed`, the
stray-projects `slugs`/`checked_at`, the insert object's `known` /
`original_known`, the two-stage `/uploaded`).

Clean, as far as I could read them:
- `unreadable` (locate): additive, companion logs it only
  (`server_locate.py:190-198`); a 0.9.74 companion ignoring it is strictly
  safer than before because the excluded slugs are also missing from `files`.
- `dashboard_version` itself: additive, absent-tolerant on read (the defect is
  wire-2, the stickiness, not the key).
- `upgrade_none_reason`: additive both ways; a build that cannot read it keeps
  today's behaviour exactly.
- `stray_projects.slugs`/`checked_at`: declared with the same caps the
  companion producer uses (`MAX_REPORTED_PROJECT_DIRS`), closing live-4.
- `standins_owed`: declared on `ResolveHealthIn` ahead of the companion half;
  `{}` parses to all-None; nothing stores it, which is stated.
- `standins_placed`: NFC on both sides (`archive_rel_of` vs `media_rel_key`,
  both plain `unicodedata.normalize("NFC", ...)`, neither case-folds), always
  sent including empty, bounded at 200 on both sides.
- `not_synced_here`'s dashboard half: `_unknown_state_is_no_state` is the
  right shape and would have prevented the `applying` outage.
- the insert object's `known`/`original_known`: the companion's
  `_derive_tiers` applies `known is False` after the `original_rel is None`
  arm, so the ordering is right, and `plan_insert`'s `known is False` branch
  sits after `local_path_exists` and `wired` where it belongs.
- `edit_proxy_rel` on `/uploaded`: omitted entirely when absent, so an older
  `broll/web` sees a byte-identical body.

NOT covered: the jobs offer/claim/cancel wire, `commands.*` beyond file moves
and the upgrade push, the music and ytdl fleet routes, the vendor feed vs
`release_feed.py`, and the 8899 loopback's CORS/token half. No suite covers
the two-stage `/uploaded` at all (wire-1's evidence), and none of the three
report-reply keys added today (`standins_known`, `dashboard_version`,
`upgrade_none_reason`) has a test that drives the OLD dashboard's reply
through the new companion reader - only the new-new pairing is pinned.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/broll_upload.py:21`: the docstring's claim
  that "the page offers a retry" for an unuploaded original is not true of any
  code in `broll/web/static/`.
- `broll/web/app/ingest_batches.py:1233-1235`: `mark_uploaded` writes
  `ingest_items.state` directly instead of through `set_item_state`, so it is
  the one writer that bypasses `_check_transition` - which is what lets the
  second stage work at all, and is worth a comment saying so.
