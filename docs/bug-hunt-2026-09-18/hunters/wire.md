# wire - every contract between two processes, both sides side by side

Files read (with approximate coverage):
- locate wire, both sides, in full: `dashboard/src/ccsync_dashboard/locate.py`,
  `dashboard/src/ccsync_dashboard/api.py` (`LocateFileIn`/`api_locate_files`,
  the report reply's `commands` block, the slow-write record),
  `companion/src/ccsync_companion/sync/server_locate.py`,
  `sync/rclone_lane.py` (`_relocate_trashed`, `_local_destination`,
  `_move_out_of_trash`, `_trashed_this_pass`), `app.py`'s wiring of both.
- proxy-tiers wires, both sides: `broll/web/app/routes_api.py`
  (`insert_target_detail`, `_insert_object`), `broll/web/app/schemas.py`,
  `broll/web/app/routes_fleet.py`, `broll/web/app/ingest_batches.py`
  (`ItemFiles`, `mark_uploaded`, `_apply_probe`), `broll/web/app/edit_weight.py`,
  `broll/web/static/app.js` (`sendToResolve`) vs
  `companion/src/ccsync_companion/broll_server.py`
  (`derive_insert_paths`, `plan_insert`, `build_insert_response`),
  `broll_ingest.py` (`IngestClient._call`/`item_uploaded`/`_post_uploaded`,
  `_upload_plan`, `_enqueue_uploads`, `_pump_uploads`, `_edit_proxy_skip`),
  `broll_upload.py`, `ffmpeg_tools.is_edit_weight`, `proxy_relink.py` (the
  stand-in seam only).
- Cards tunnel, both sides: `dashboard/src/ccsync_dashboard/cards_tunnel.py`,
  `cards_pool.py` (`engine_for`/`note_visit`), `app.py`'s gate additions, and
  `companion/src/ccsync_companion/timeline_cards_role.py` (`TunnelClient.call`,
  `_note_call`, `_note_traffic`, health), plus the OTHER repo's agent loops
  (`E:\Projects\Editing\Resolve\MulticamPipeline\multicam_pipeline\cards\agent.py`
  `push_loop`/`pull_loop`) as the real far end.
- busy-database rework: `dashboard/src/ccsync_dashboard/app.py`
  (`unhandled_error`), `notices.is_db_busy`/`record_db_busy`/
  `record_slow_write`, `broll/web/app/db.py`.
- feed: `release_feed.py` (`_feed_flag`, `repair_provenance`,
  `publish_from_feed`), `tools/publish_feed.py` (`github_upload`,
  `published_assets`), `tools/publish_latest.py`.
- reporter/report reply: `companion/src/ccsync_companion/reporter.py`
  (`post_once`, `_note_failure`, `_fit_payload`), `api.api_report`'s reply.
- docs as contract: `docs/API.md` sections 2/6a, `docs/LOOPBACK_API.md`,
  `docs/HAND_MOVES_ON_THE_SERVER.md` (phase 2), the proxy-tiers plan and audit
  (sections 5/6), `docs/CARDS_TWO_PROJECTS.md` (phase 1a).

Tests run: none (read-only tracing; a lens owns no suite, and the territory
owners run theirs). Verification was by reading both ends of each wire and,
for the Cards case, the other repo's client loops.

## Findings

### wire-1 - a non-409 refusal of `/items/{uid}/uploaded` wedges the item in `uploading` for ever
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_ingest.py:3014` (the `else:`
  branch of `_pump_uploads`), against
  `broll/web/app/ingest_batches.py:1141` (the new `400 wrong_edit_proxy`) and
  `broll/web/app/routes_fleet.py:219`.
- What: `_pump_uploads` handles exactly two answers from `/uploaded`: 200 (go
  live) and 409 (re-queue, count an attempt, fail at `MAX_UPLOAD_ATTEMPTS`).
  Every other status is a `log.warning` and nothing else. The item stays at
  `ITEM_UPLOADING` with all its rels already in `landed`, so the next pump
  recomputes `missing = []` and POSTs the identical body again - for ever,
  with no attempt counter, no `item["error"]`, no failure, and the batch lease
  heartbeated the whole time. This week's change added the first refusal of
  that route that is NOT a 409: `edit_rel != slots.edit_proxy` raises
  `HTTPException(400, {... "reason": "wrong_edit_proxy"})`, and its own comment
  says "Not a 409: no retry can make this right" - but the only side that
  could stop retrying does not know the code exists. A 500 or a 503 (wire-2)
  wedges identically.
- Failure scenario: an item whose `archive_stem` the server re-allocated
  between the claim the companion cached and the `uploaded` call (a re-claim
  after a lost lease, the `_2`/`_3` dedup path), or any 5xx out of the mounted
  b-roll app: the companion posts `edit_proxy_rel = "<dir>/Proxy/<oldstem>.mov"`,
  gets 400 for ever, the clip never goes live, the batch never releases, the
  lease never expires (the heartbeat renews it), and every later drop on that
  machine meets the "another of your machines has it" 409. The editor sees a
  clip stuck at 100% uploading with no error.
- Evidence: `_pump_uploads`'s `if status == 200 ... elif status == 409 ...
  else: self.log.warning("the server would not mark %s live (HTTP %s)")`; the
  `missing`/`landed` recomputation at the top of the same loop body; the server
  side's 400 in `ingest_batches.mark_uploaded`. `grep -an "wrong_edit_proxy"`
  across the tree hits only `broll/web/tests/test_fleet_ingest.py:822` - the new
  status has a test on the server side and no reader on the companion side.
- Ledger: new. Shape-identical to comp-loopback-1/comp-loopback-3 and
  comp-broll-music-1 ("uploading for ever, lease held"), which were fixed for
  the rclone-failure and never-queued cases and not for this one.
- Suggested fix: give the `else` branch the 409 branch's accounting -
  increment `upload_attempts`, put the server's `detail` on the item, and
  `_fail_item` at the ceiling; treat a 4xx that is not 409 as immediately
  terminal (it is what the server means) and a 5xx as a retryable attempt.

### wire-2 - "a busy database is contention, not an error" stops at the dashboard's own routes; the mounted apps still 500, and the companion treats that as terminal
- Severity: medium
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (field frequency)
- Where: `dashboard/src/ccsync_dashboard/app.py:1317`
  (`@app.exception_handler(Exception)`, the `notices.is_db_busy` -> 503 +
  `Retry-After: 30` branch) vs `broll/web/app/db.py:249` (`open_connection`,
  default 5 s busy timeout, no busy translation anywhere in `broll/web/app/`),
  and the reader `companion/src/ccsync_companion/broll_ingest.py:2693`.
- What: 4aaca6a made `sqlite3.OperationalError: database is locked` a 503 with
  a retry hint - but it installed that on the DASHBOARD app's exception
  handler. `/broll`, `/music`, `/ytdl` and `/cards` are real ASGI mounts with
  their own exception middleware and their own databases, so a busy timeout
  inside the fleet ingest routes is still an unhandled 500. On the companion
  side any non-200 from `/items/{uid}/result` is terminal: it clears
  `described` and calls `_fail_item("the archive would not take this clip's
  description: ...")`. So the one contention answer the rework exists to make
  survivable is, on the busiest fleet route of the week, still a clip failed
  and a VLM description thrown away.
- Failure scenario: two editors' companions and the collector write `broll.db`
  while a `publish_db.py` swap or the indexer holds a write: one `/result` POST
  exhausts its 5 s busy timeout -> 500 -> the item is failed, `described` is
  reset, and the minutes of local VLM work are discarded; the clip must be
  re-indexed. Nothing records a `db_busy` notice for it either, so the home
  page's PROBLEMS panel cannot see that the archive DB is the contended one.
- Evidence: the 503 branch is registered with `app.exception_handler` on the
  parent FastAPI app only; `grep -rn "exception_handler\|OperationalError"
  broll/web/app/*.py` returns only `search.py`'s local FTS catches. The
  companion's terminal branch is quoted above.
- Ledger: new (extends CR-240i / the 4aaca6a rework rather than regressing it).
- Suggested fix: register the same `is_db_busy` -> 503 handler on each mounted
  sub-app (or a shared installer), and teach the ingest client that 5xx is
  retryable while 4xx is not - the same change wire-1 needs.

### wire-3 - an agent whose editor has no episode open is told so in a body nobody reads, and reports itself healthy
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_tunnel.py:137` (`_no_engine`)
  and its returns in `cards_agent_state` / `cards_agent_result`, vs
  `companion/src/ccsync_companion/timeline_cards_role.py:911`
  (`call()`: `if status != 200: raise`; otherwise `_note_call(200, "")`).
- What: phase 1a answers a push from an editor who is in no episode with HTTP
  200 and `{"error": "<editor> is not in a Timeline Cards episode..."}`. The
  companion's tunnel client keys health on the STATUS only: a 200 moves
  `_last_poll_at`, clears `_last_error` and leaves the role running, and
  `_note_traffic` then records the pushed `timeline` and `project` off the
  REQUEST body, not the answer. The far end (the other repo's `push_loop`)
  also ignores the body unless it carries `resend`. So the sentence reaches no
  log line, no tray line and no fleet page: the companion, the dashboard's
  agent panel and the editor all show a connected, pushing Cards agent while
  every state push is being dropped.
- Failure scenario: the container is recreated (the pool's `_where` is
  in-memory only) or the editor closes the episode tab. The agent keeps
  pushing; `/cards` shows no agent state; the companion says the Cards role is
  running with timeline X; nobody is told that the fix is "open an episode at
  /cards/". This is rule 5's "green while dead" plus "a failure logged but
  never surfaced".
- Evidence: `_routed` returns `(None, answer)`; `cards_agent_state` returns
  that dict with the default 200. `timeline_cards_role.call` inspects only
  `status`. `multicam_pipeline/cards/agent.py` `push_loop` reads only
  `ans.get("resend")`; `pull_loop`'s `if got.get("id") is None: continue`
  correctly ignores the `{"note": ...}` poll answer, so that half is sound.
- Ledger: new; related to CR-226 (the role) and the phase 1a pool.
- Suggested fix: have `TunnelClient.call` treat a 200 whose body carries
  `error` (or `note`) as a NOT-ATTACHED condition - keep the transport healthy
  but put that sentence in the role's detail so it reaches the log, the tray
  and the fleet page. Answering 409 from `_no_engine` for `state`/`result`
  would work too; the poll must keep its 200 `{}`-shaped answer.

### wire-4 - `insert.original_rel: null` means "there is no original"; the companion reads it as "the path you posted is the original"
- Severity: low
- Confidence: CONFIRMED (the collapse), PLAUSIBLE (the downstream harm)
- Where: `broll/web/app/routes_api.py:96` (`insert_target_detail`'s docstring:
  "`original_rel` is None when there was no unique sibling and the preview
  itself is what gets inserted... A caller must not read 'no original' as 'use
  the preview and pretend'") vs
  `companion/src/ccsync_companion/broll_server.py:770`
  (`cleaned_original = _clean_rel(insert.get("original_rel")); if
  cleaned_original: derived["original_rel"] = cleaned_original` - an explicit
  null falls back to the posted `rel_path`, which for this clip IS the
  preview).
- What: the server distinguishes three states for the top slot (a unique
  original, no original at all, un-archived) and spends a paragraph saying the
  null is an ANSWER. `derive_insert_paths` applies its "absent is not null"
  rule to `preview_rel` and `edit_proxy_rel` but deliberately not to
  `original_rel`, so `plan_insert` sees `original_rel == preview_rel` and, for
  a clip the `videos` row calls heavy, returns `PLAN_FETCH_STANDIN`: it
  downloads the preview to the preview's own path and then calls
  `broll_standins.record()` on it. That file is not a stand-in for anything -
  it is the only file the archive holds for that clip - and no original will
  ever arrive to retire the row.
- Failure scenario: an archive task #23 clip (preview published, original never
  archived) with `videos.bitrate` present and above edit weight: the editor
  gets a WARNING in the companion log saying a render would render the preview
  (permanently true, not a transient stand-in), a permanent row in
  `~/.ccsync/state/broll_standins.json`, and `proxy_relink`'s `is_standin()`
  then suppresses the geometry refresh and the "do not attach a `.mp4` preview
  as a proxy" guard (audit F1) for that path for ever.
- Evidence: both functions read side by side, plus `plan_insert`'s extension
  test (`posixpath.splitext(original_rel)`) which in this case examines the
  PREVIEW's `.mp4` rather than the real original's extension, so the
  `PLAN_PREVIEW_ONLY` branch can never fire for such a clip.
- Ledger: new (proxy-tiers phase 3 / audit F2).
- Suggested fix: carry a third state in `derived` - `original_known` - set
  False when the object is present and `original_rel` is explicitly null, and
  have `plan_insert` answer `PLAN_PREVIEW_ONLY` (fetch the preview to its own
  path, no ledger row) in that case.

## Coverage note
Traced in full and found sound: the locate wire (companion `nfc` vs
`db.media_rel_key` are both plain NFC, basenames on both sides,
`nas_media.rel_path` is project-relative so `_local_destination`'s join is
right, the 413 ceiling matches `MAX_LOCATE_FILES` on both sides, an older
dashboard's 404 degrades to "cannot tell", and the CSRF/login-gate carve-outs
are exact rather than prefixes); the editing-proxy declaration and upload order
(`EDIT_PROXY_EXT == ".mov"` matches `PROXY_DIR` + `.mov`, `UPLOAD_ORDER` puts
it between preview and original, a new companion against an old b-roll web is
silently ignored, an old companion against a new one sends nothing and nothing
is required); `edit_weight.py`'s two copies are identical in rule, constants
and the None case; `_feed_flag` fixes both `git_dirty` and `signed_binary`
string reads.

NOT covered: the jobs offer/claim/cancel wire (unchanged this week; read only
at the report-reply end), `commands.file_moves` / `resolve_undo` two-phase
replies, the music and ytdl fleet routes beyond the shared ingest client, the
upgrade offer and its signed record, and the ytdl/music loopback bodies. The
suites do not cover any of the four findings: there is no companion-side test
for a non-200/non-409 answer to `/uploaded`, no test that a mounted sub-app
translates a busy database, no test that the companion surfaces a 200 carrying
`error` from the Cards tunnel, and `test_broll_insert_tiers.py` pins
`plan_insert` only for objects whose `original_rel` is a real path.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/api.py:9396`: the slow-write notice is
  written and committed from inside the report path that was just measured as
  holding the write lock too long - one more write on the contended database,
  at the worst moment. (dash-api / dash-db)
- `dashboard/src/ccsync_dashboard/notices.py:1105`: `DB_BUSY_MARK = "database
  is locked"` does not match SQLITE_LOCKED's "database table is locked", so
  that one still records as a server error. (dash-collector-alerts)
- `tools/publish_feed.py:830`: an asset is skipped when the release already
  holds the same NAME and SIZE; a rebuild of a package this run did not sign
  that happens to match its old size is left stale on the feed.
  (dash-release-jobs)
