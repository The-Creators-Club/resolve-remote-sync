# proxy-tiers - the b-roll proxy-tiers path read end to end, against the plan and the audit

Files read (with approximate coverage):
`docs/BROLL_PROXY_TIERS_PLAN.md` (all), `docs/BROLL_PROXY_TIERS_PLAN_AUDIT.md` (all),
`companion/src/ccsync_companion/broll_server.py` (the whole diff + `derive_insert_paths`,
`plan_insert`, `build_insert_response`, the upgrade lane: ~90%),
`companion/src/ccsync_companion/broll_standins.py` (whole file),
`companion/src/ccsync_companion/broll_ingest.py` (the diff + `_pump_uploads`,
`_maybe_stage_live`, `_post_uploaded`, `_mirror_locally`, `_encode_verified`),
`companion/src/ccsync_companion/proxy_relink.py` (`_geometry_disagrees`, the fleet
memory, `plan_relinks`, `apply_relinks`: ~70%),
`companion/src/ccsync_companion/ffmpeg_tools.py` + `broll/indexer/broll_index/ffmpeg_tools.py`
(the `frames_match` / `_plausible_frames` twins, `build_proxy`'s frame check),
`companion/src/ccsync_companion/resolve_bridge.py` (`replace_clip`, `_real_original_here`,
`_attach_adjacent_proxy`), `companion/src/ccsync_companion/watcher.py` (the diff),
`companion/src/ccsync_companion/app.py` (the report section, the relink pass, the
report-reply fan-out), `broll/web/app/routes_api.py` (`insert_target_detail`,
`_insert_object`, `_is_edit_weight`), `broll/web/app/ingest_batches.py` (`mark_uploaded`),
`broll/web/static/app.js` (the POST body only),
`dashboard/src/ccsync_dashboard/api.py` (`StandinsPlacedIn`, the report writer, the
reply), `dashboard/src/ccsync_dashboard/db.py` (`broll_standins` table,
`record_standins_placed`, `standins_known`, `prune`, `media_rel_key`),
`dashboard/tests/test_bug_hunt_2026_09_18_dashboard_lows.py` and
`companion/tests/test_bug_hunt_2026_09_18_companion_media.py` (the proxy-tiers cells).

Tests run: none from the suites (owner rule: the gate runs once, centrally). One ad-hoc
script in the scratchpad against `companion/.venv` that drives
`broll_server.build_insert_response` with a stub fetcher - output quoted in
proxy-tiers-1.

## Findings

### proxy-tiers-1 - a `busy` (or unobserved failed) fetch leaves a stand-in ledger row that nothing can ever falsify, and it makes the companion treat the REAL original as a lie
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_server.py:1176-1215` (the intent row is
  written before the fetch; the `STATE_BUSY` branch at `:1205-1211` returns BEFORE the
  `forget()` added at `:1217-1219`), with
  `companion/src/ccsync_companion/broll_standins.py:484-495` (`_entry_is_stale`) and the
  three readers it poisons: `resolve_bridge.py:2958-2976` (`_real_original_here`),
  `proxy_relink.py:804-836` (the `.mp4` rule and the refresh gate),
  `broll_standins.placed_report` -> `sync_guard.standins_placed`.
- What: comp-broll-tiers-1 moved the ledger write to BEFORE the fetch, with `size=None`
  because "a non-int size reads as still a stand-in, which is the conservative
  direction", and retires the row on `state != DONE`. But `STATE_BUSY` returns three
  branches earlier, and `poll_fetch`'s own docstring says busy means "nothing started,
  nothing registered". So an insert that hits the 2-download cap records a stand-in for
  a file no download was ever started for. Because `size` is `None`,
  `_entry_is_stale` returns False unconditionally - the row has no falsifier at all, not
  even the real original arriving at that path - and `_prune_locked` only drops it after
  30 days AND the file being absent, which the real original prevents. The same hole is
  open for the scenario the fix was written for: a download that FAILS and is never
  polled again (page closed, laptop asleep) leaves the identical row, because only a
  later poll observing `failed` calls `forget`.
- Failure scenario: an editor with two archive clips already downloading clicks Send to
  Resolve on a third heavy clip. The answer is `busy`; nothing is downloaded. The ledger
  now permanently claims `<local_root>/Assets/B-roll Archive/CIA_City/cam-1-001.mov` is a
  stand-in. Weeks later the real 6K original is on that machine (a wired session, a hand
  copy, the follow-up real-original fetch). Now: `_real_original_here` answers False, so
  `_attach_adjacent_proxy` attaches the 1080p browser PREVIEW as the proxy of a clip whose
  real original is on disk; `plan_relinks`' `.mp4` rule (audit F1, the finding phase 3
  exists to close) is inverted for the same reason and keeps re-offering it every 120 s;
  the geometry refresh is suppressed for that clip for ever (`not is_standin()`); and
  `placed_report` ships the rel to the dashboard, which tells EVERY machine in the fleet
  - including the wired rig - to force one `ReplaceClip` on a clip that never needed one.
  The editor cuts at preview quality with nothing on screen to say so, which is the exact
  harm audit F1 names.
- Evidence: ad-hoc run against `companion/.venv` (stub fetcher returning
  `{"state": "busy"}`, nothing else mocked):

  ```
  HTTP 200 {'ok': True, 'state': 'busy', 'retry_after': 1.5, 'message': 'busy'}
  ledger entries: [{... 'rel_path': 'CIA_City/cam-1-001.mov', 'size': None, 'upgrade': None ...}]
  is_standin(original path) -> True
  after the real original arrives, is_standin -> True
  is_stale -> False
  placed_report -> {'rels': ['CIA_City/cam-1-001.mov'], ...}
  ```

  `broll_fetch.py:109-111` ("At the cap: nothing was started, nothing was registered")
  and `:418-426` confirm the busy branch starts no job.
- Ledger: new (CR-284/comp-broll-tiers-1 does not fix its own scenario on the `busy` and
  never-polled-again paths)
- Suggested fix: call `broll_standins.forget(insert_path)` on the `STATE_BUSY` branch too
  (and wrap the fetch so an exception does the same), and give `_entry_is_stale` a second
  falsifier for a size-less row - e.g. record the preview's EXPECTED size from the insert
  object, or treat "size is None AND the file exists" as stale rather than as a stand-in,
  since the intent row is only ever written while the file is absent.

### proxy-tiers-2 - the dashboard never sends the empty `standins_known`, so a companion cannot be told the fleet has none left
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9860-9874` (`if known:`), against
  `companion/src/ccsync_companion/proxy_relink.py:426-470` (`note_fleet_standins`) and
  `companion/src/ccsync_companion/broll_standins.py:165-186` (`placed_report`).
- What: both sides write down a THREE-state contract - a reply carrying the key is
  knowledge, a rel in it means somebody placed a stand-in, an absent key means "this
  dashboard does not know" and must change nothing. api.py's own comment says "an empty
  list is sent for the same reason, so the two shapes cannot be confused". The code does
  the opposite: `if known:` omits the key whenever the fleet set is empty, collapsing
  "the fleet knows of none" into "the dashboard does not know". `note_fleet_standins`
  deliberately KEEPS the previous set on an absent key, so a positive set can never be
  cleared inside a running companion.
- Failure scenario: the one machine that had ledger rows forgets them (proxy-tiers-1's
  fix, a 30-day prune, a machine retired past `MACHINE_STATE_MAX_AGE_DAYS`).
  `standins_known` returns `[]`, the key is omitted, and every companion keeps answering
  `fleet_says_standin -> True` for those rels until its process restarts, forcing a
  `ReplaceClip` refresh per clip per process on clips that are fine. In the other
  direction, a fleet that has never had a stand-in can never move a companion out of
  "ask the probe", which is the behaviour the whole section exists to avoid.
- Evidence: read both sides; the only route-level test
  (`dashboard/tests/test_bug_hunt_2026_09_18_dashboard_lows.py:297-306`) asserts the
  key is present for a NON-empty set, and the empty case is only asserted at the db
  layer (`:334`), so nothing pins the wire shape the comments promise.
- Ledger: new
- Suggested fix: `result["standins_known"] = {"rels": known}` unconditionally (the
  try/except already makes it best effort), and add the empty-reply cell to the route
  test.

### proxy-tiers-3 - the `known: false` outage guard protects only 0.9.75, and the deploy order guarantees the fleet runs the unprotected build first
- Severity: medium
- Confidence: CONFIRMED
- Where: `broll/web/app/routes_api.py:114-190` (`insert_target_detail` /
  `_insert_object`), against `companion/src/ccsync_companion/broll_server.py:821-836`
  (the `known` reader, new in 0.9.75) and `broll/web/app/routes_api.py:68-76`
  (`_is_edit_weight`, a pure DB read).
- What: proxy-tiers-3's whole point is that ten minutes of an unreadable archive folder
  turned every Send to Resolve into a ledgered stand-in "and the damage outlived the
  outage for ever". The fix is a NEW key that only a 0.9.75 companion understands, while
  the object it rides still carries `preview_rel` (present) and
  `original_is_edit_weight` (computed from the `videos` row, entirely independent of the
  failed listing, so it is `false` for every heavy clip). Plan section 7 and CLAUDE.md
  both say dashboard FIRST, so for hours-to-days after the deploy - and today, on all
  four machines at 0.9.74 - the outage produces exactly the pre-fix outcome: `heavy` is
  true, `preview_rel` is present, the companion plans `fetch_standin` and writes a ledger
  row for a clip whose original is sitting on the NAS.
- Failure scenario: `BROLL_DATA_ROOT` is wrong after an image update (the example the
  comment itself gives). Every insert from any 0.9.74 machine in that window places a
  stand-in over its heavy originals and ledgers it; the rows then travel to the fleet
  through proxy-tiers-4 and force refreshes everywhere.
- Evidence: `_is_edit_weight` reads `height`/`bitrate`/`codec` off the row and is called
  unconditionally in `_insert_object`; 0.9.74's `derive_insert_paths` (`git show
  HEAD:companion/src/ccsync_companion/broll_server.py`) has no `known` branch and reaches
  the `heavy` test with `weight is False`.
- Ledger: new (CR-284G closes the new-companion half only)
- Suggested fix: on the `known=false` path also answer `original_is_edit_weight: true`
  (and `edit_proxy_rel: null`), which is the one field every build in the field already
  reads and which forces `PLAN_FETCH_ORIGINAL` on 0.9.65..0.9.74 as well as on 0.9.75.

### proxy-tiers-4 - `record_standins_placed` resets `first_seen` on every report; its ON CONFLICT arm is unreachable
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:8830-8868`
- What: the docstring promises "`first_seen` survives a re-report of the same rel,
  because 'how long has this clip been standing in' is the question an operator asks",
  but the function DELETEs every row for `(editor, machine)` before the `INSERT ... ON
  CONFLICT(archive_rel, editor_username, machine) DO UPDATE` - so the conflict can never
  fire for that machine's own rows and `first_seen` is rewritten to `now` on every
  report, i.e. every report interval.
- Failure scenario: nothing reads the column today (grepped: no reader in
  `dashboard/src`, `dashboard/templates` or `tools/`), so the cost is a false docstring
  and a column that will silently answer "a few seconds" the first time anyone builds
  the operator view the docstring describes.
- Evidence: the DELETE and the INSERT are in the same function, and the only selective
  reader (`standins_known`) takes `MAX(last_seen)`.
- Ledger: new
- Suggested fix: keep the replace-the-set semantics but preserve `first_seen` - read the
  existing rows before the DELETE, or replace the DELETE with a delete-of-the-difference
  and let the ON CONFLICT arm do its job.

### proxy-tiers-5 - the one log line that announces a stand-in is emitted before any bytes are placed, and even when none ever are
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_standins.py:412-425` (the `log.warning`
  at the end of `record`), reached from `broll_server.py:1176` (the pre-fetch intent row).
- What: `record()` unconditionally logs "`<path>` now holds the PREVIEW's bytes, not the
  original. Resolve will read its geometry from that file, and a render on this computer
  would render it". Since comp-broll-tiers-1 that call happens BEFORE the download, so
  the sentence is false at the moment it is written, and on the `busy` path
  (proxy-tiers-1) it is never made true. The plan names this line as the v1 render
  warning ("v1 only logs it"), so it is the line an operator greps.
- Failure scenario: an operator reading `companion.log` after a render dispute sees a
  stand-in announced for a path that holds the real original and was never touched.
- Evidence: the ad-hoc run in proxy-tiers-1 printed that warning with `state: busy` and
  no file on disk.
- Ledger: new
- Suggested fix: log at the point the bytes land (the second `record` call, which has
  the real size) and log the intent row at INFO with wording that says "about to".

### proxy-tiers-6 - the forced refresh writes the media pool with no save point and no undo journal, against CLAUDE.md's standing rule
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/resolve_bridge.py:2269-2290` (`force` skips the
  save point and the journal entry), used by
  `companion/src/ccsync_companion/proxy_relink.py:1007`.
- What: CLAUDE.md: "Every media-pool write goes through `resolve_bridge.replace_clip` /
  `link_proxy_media`, which take a `SaveProject`+export save point and write an undo
  journal". The forced refresh opts out on the grounds that "old_path == new_path, so
  the journal's inverse edit is this same call again". But the call is not a no-op on
  project state: it changes the clip's stored geometry (that is its purpose) and,
  per comp-resolve-6 three hundred lines away, it "may drop the clip's proxy
  attachment" - which the code then repairs by hand. A pass over hundreds of archive
  clips therefore rewrites the pool with no save point in front of it.
- Failure scenario: Resolve or the companion dies part-way through a refresh pass on a
  big archive timeline; the project has no save point from before the pass and no
  journal entry naming what was touched, so `resolve_undo` has nothing to replay.
- Evidence: read both functions; `resolve_journal.allow_automatic` is claimed once per
  PASS in `app.py:4654`, not per op, so nothing else bounds the number of unjournalled
  writes in one pass.
- Ledger: related to CR-284R (open, the repeat-suppression half)
- Suggested fix: keep the journal entry (it can record "refresh, same path" for the
  audit trail) and take ONE save point per refresh pass rather than per call, which
  costs one `SaveProject` and answers the rule.

### proxy-tiers-7 - a clip goes LIVE early even when its original's upload has already failed
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/broll_ingest.py:2989-3014` -
  `_maybe_stage_live` is called before the `broken` (rclone failed) branch.
- What: proxy-tiers-5's two-stage `/uploaded` stages the clip live as soon as
  "everything but the original" has landed, and the only thing it checks about the
  original is that it is still in `missing` - not whether it is in `failures`. So an
  original whose upload has already failed hard still takes the clip live, and the item
  is then failed on the next two lines.
- Failure scenario: the link drops mid-original. The clip appears in search and Send to
  Resolve (preview-only, correctly), while the ingest panel shows the item FAILED and
  the editor believes nothing landed. If they clear the batch rather than retry, the
  archive keeps a live clip whose original will never arrive, with no failed item left
  to say so.
- Evidence: read the call order; `_maybe_stage_live` filters only
  `[rel for rel in missing if rel not in originals]`.
- Ledger: new
- Suggested fix: pass `failures` in and return early when any of the item's rels is in
  it, so the clip goes live only while the original is genuinely still in flight.

## Coverage note

Judged against the plan section by section; what I could NOT close in the time box:

- **Section 7's manual live checks are still owed and the plan's status line is now
  wrong.** It still reads "UNSHIPPED: no version bump, no KNOWN_BUGS entry yet", both
  untrue since `8f74d5e` (0.9.74 / 0.7.49, CR-281). The three live checks it lists - a
  stand-in-born clip opened on a wired rig, the preview-to-editing-proxy swap on a clip
  already in a timeline, and the spike's third machine (leso's Mac) - have still never
  run, and every mechanism in proxy-tiers-4 (`Frames` enrichment, the forced
  `ReplaceClip`, the re-attach) is only reachable there.
- **Two 200-caps that are not the same bound.** `FLEET_REPORT_MAX` is 200 rels PER
  MACHINE and `db.standins_known`'s limit is 200 rels for the WHOLE fleet, ordered by
  `last_seen DESC` - and every row from one report shares one `last_seen`, so with two
  busy remote editors the answer is effectively "the most recent reporter's set" and the
  other machine's stand-ins silently fall out of the fleet answer. Not a defect on
  today's volumes (a handful of rows); it will become one on a Johnny-Harris-sized
  ingest, and the comment on both sides claims a single shared bound.
- The plan's "the render warning names them" (section 6, third reader of the ledger) has
  no implementation beyond `record()`'s log line - which proxy-tiers-5 shows is written
  at the wrong moment. Consistent with the same section's "v1 only logs it", so I did not
  raise it as a finding, but the ledger has two readers in code, not three.
- I did not read `broll/indexer/broll_index/pipeline.py`'s migration-012 writers, the
  `edit_weight.py` rule itself, or `broll_upload.UploadQueue`'s ordering in detail;
  broll-indexer and comp-broll-tiers own those and neither had filed a report when I
  started (only `comp-ui`, `dash-core`, `dash-db`, `install-onboard`, `music`,
  `res-companion`, `ytdl-web` existed).
- Not covered by any suite I could find: the `busy`-leaves-a-row cell (proxy-tiers-1),
  the empty-reply wire shape (proxy-tiers-2), and any 0.9.74-against-0.7.50 cell for the
  `known` key (proxy-tiers-3).

## OUT OF TERRITORY

- `companion/src/ccsync_companion/broll_ingest.py:3151`: `_maybe_stage_live` posts
  `/uploaded` on every pump tick until it succeeds, with no attempt counter of its own -
  bounded only by the original's upload time, but a 409 `no_result` (the description has
  not been posted yet) makes it a per-tick POST for the life of the upload.
- `broll/web/app/ingest_batches.py:1137-1143`: `wrong_edit_proxy` is a 400 the companion
  now treats as terminal (wire-1), while `mark_uploaded` is also the route the two-stage
  post hits twice - the second post re-declares the same `edit_proxy_rel`, so the two
  changes are fine together, but nothing tests the pair.
