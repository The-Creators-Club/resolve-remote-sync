# verdicts - ytdl-wire

Verifier for `hunters/ytdl-web.md` (8 findings) and `hunters/wire.md` (4).
Read-only pass at HEAD 214869b; the only writes are this file and two scratch
scripts in the session scratchpad. Nothing live was touched.

## ytdl-web-1
- Verdict: CONFIRMED (high)
- Duplicate of: none (no other hunter reports the red suite; `tests.md` covers
  silently-skipping tests, not this)
- Reasoning: reproduced on an unmodified tree. The test pins a literal
  yt-dlp version `'2026.08.27'` and asserts `yt_dlp_stale is False`, while
  `_yt_dlp_is_stale` is `age > config.YTDLP_MAX_AGE_DAYS` with the age taken
  against `date.today()` and the limit defaulting to 21
  (`config.py:282`). 2026-09-18 minus 2026-08-27 is 22 days, so the assertion
  is false from 2026-09-17 onwards and can never pass again. The CI step
  `ytdl/web -- pytest` has no `continue-on-error` (there is no
  `continue-on-error` anywhere in `.github/workflows/ci.yml`), so `main` is
  red, and `tools/publish_latest.py` only takes the newest GREEN run on main.
- Evidence: `cd ytdl/web; ../../dashboard/.venv/Scripts/python.exe -m pytest
  tests/test_api.py -q -k yt_dlp` -> `1 failed, 2 passed`, failing at
  `tests/test_api.py:473` with `assert True is False`.
- Fix note: the suggested fix is right and is the only honest one - derive both
  versions from `date.today()` (`- timedelta(days=1)` for fresh,
  `config.YTDLP_MAX_AGE_DAYS + 1` for stale) so the test pins the rule. Touch
  nothing else; the second half of the same test (`'2026.01.01'` -> stale) is
  correct for the same reason and should be rewritten in the same edit so it
  cannot rot in the other direction if the limit is ever raised.

## ytdl-web-2
- Verdict: CONFIRMED (medium)
- Duplicate of: none
- Reasoning: read both functions in full. `_refuse_if_full`
  (`routes_api.py:1494`) calls `_forget_free_at` then
  `_refuse_if_the_tree_is_gone(job)` before raising; `_no_room_note`
  (`worker.py:1528`) reproduces the two numbers, the factor, the floor and the
  cache invalidation but has no tree guard, and its caller
  (`worker.py:1641-1650`) only logs and sets `phase='failed'`. I also grepped
  the worker for any existence test on `PROJECTS_ROOT`: `is_dir()`/`exists()`
  appear only inside `ensure_outdir`'s parent walk. So the executor path emits
  exactly the sentence CR-263a/ytdl-web-1 exist to prevent. Reachability is
  narrower than the hunter implies (it needs `YTDL_LOCAL_DOWNLOAD=1` AND a
  created-local job AND an unclaimed lease), but the harm - an admin told to
  free space on a share that is not mounted - is the one the repo already
  decided is worth a guard, so medium stands.
- Evidence: `grep -n "_refuse_if_the_tree_is_gone" ytdl/web/ytdlweb/*.py` ->
  definition at `routes_api.py:1571` and one call, at `:1528`, inside
  `_refuse_if_full`. No hit in `worker.py`.
- Fix note: the suggested fix is right in shape but must not raise
  `HTTPException` from the worker thread - `_no_room_note` returns a sentence
  that the caller writes into `set_phase(..., 'failed', note)`. Factor the
  tree test out of `_refuse_if_the_tree_is_gone` into a predicate (it already
  has one: `_named_under_the_root`) and have `_no_room_note` return the
  `tree_missing` wording instead. A fix also wants a test beside
  `ytdl/web/tests/test_bug_hunt_2026_09_11b_ytdl_web.py`, which currently
  exercises `_no_room_note` only against a full-but-present tree.

## ytdl-web-3
- Verdict: CONFIRMED (medium)
- Duplicate of: none
- Reasoning: `renderRetry` (`app.js:1401`) computes `offer = failed > 0 &&
  (phase === 'done' || phase === 'failed')`, and in the `_no_room_note` case
  `dl_failed` was just reset to 0 by `start_download`
  (`routes_api.py:1730`), `mark_pending` put every row back to `pending`, and
  `_phase_download` returns before the per-clip loop, so no row is `failed`.
  I tried to refute this with "the review grid's DOWNLOAD button is another
  way back" and could not: `poll()` at `app.js:1250` calls `loadManifest`
  only `if (job.phase !== 'failed')`, and `startDownload` has already hidden
  `#review` (`app.js:2292`), so a failed job shows neither control - on the
  live page or after a reload. `#dlnote` is gated on the same `offer`, so the
  instruction is not even repeated next to where the button would be.
- Evidence: the three code paths above read directly; `db.mark_pending`
  (`db.py:1612`) sets `pending` for `('none','failed','skipped','pending')`.
- Fix note: of the hunter's two options, the SECOND (have the no-room failure
  mark the pending rows `failed` with the note) is the riskier one: the
  server's own retry predicate counts unfinished rows and the breaker path
  deliberately leaves them `pending` (KNOWN_BUGS CR-263b). Prefer widening
  `renderRetry`'s `offer` to "phase === 'failed' and the manifest has pending
  rows". A fix touches `ytdl/web/static/app.js` only, plus a static-app test
  (the suite already drives `renderRetry`).

## ytdl-web-4
- Verdict: CONFIRMED (medium)
- Duplicate of: none
- Reasoning: confirmed both halves myself. `grep -n "_refuse_if_full"` over
  `ytdl/web/ytdlweb/` returns the definition and exactly one call site, inside
  `start_download`; `create_url_job` (`routes_api.py:954-1045`) resolves the
  project, dedupes against the ledger and calls `db.create_url_job` with no
  measurement of anything. The worker's backstop is gated on
  `config.LOCAL_DOWNLOAD and db.created_widening_of(job)[1]`, and
  `LOCAL_DOWNLOAD` is `os.environ.get('YTDL_LOCAL_DOWNLOAD') == '1'`
  (`config.py:214`), so with the flag off the backstop never runs for any job
  and the paste door has no check at all on either executor.
- Evidence: `config.py:214`; the single call site at `routes_api.py:1705`;
  `worker.py:1543`.
- Fix note: calling `_refuse_if_full` from `create_url_job` is correct but it
  raises a 409 whose detail says "press DOWNLOAD again" - the paste page's
  button is GET LINKS, so the sentence needs a caller-supplied verb or the
  refusal reads as an instruction to press a button that is not there (the
  same class of defect as ytdl-web-3). Relaxing `_no_room_note` is the smaller
  change but leaves the flag-off fleet uncovered, so do both.

## ytdl-web-5
- Verdict: CONFIRMED (medium)
- Duplicate of: none (proxy-tiers-3 is the same SHAPE - "the container loses
  the share and nothing says so" - on the b-roll archive, not the same code)
- Reasoning: `_refuse_if_full` returns None at `routes_api.py:1500` whenever
  `free >= need`, and the tree guard is below that return; its own docstring
  says the omission is deliberate ("a download that fits is a download that
  fits"). `ensure_outdir` (`worker.py:849`) then `os.makedirs(..., exist_ok=
  True)` with no precondition, and nothing between the claim and the ledger
  write asks whether the destination is the mount. So on a host with room, a
  vanished bind mount ends as `phase='done'` with ledger rows pointing at
  files on the overlay - and those rows are what later searches and pastes
  skip as "the fleet already has that video". The mount-point-on-the-overlay
  premise is not the hunter's invention: it is the repo's own, stated in the
  comment block at `routes_api.py:1508-1512`.
- Evidence: the two functions above, plus `grep -n "is_dir()\|exists()\|
  PROJECTS_ROOT" ytdl/web/ytdlweb/worker.py` -> no existence test anywhere in
  the download path.
- Fix note: the suggested fix (check the tree unconditionally at the top of
  `_phase_download`) is right, but it must fail OPEN on anything it cannot
  measure and must reuse `_named_under_the_root` for CR-90, or a Mac-reported
  NFD label starts refusing downloads that would have worked. Same caveat as
  ytdl-web-2: the worker cannot raise `HTTPException`.

## ytdl-web-6
- Verdict: CONFIRMED (low)
- Duplicate of: none (related in shape to security-4, "a fleet credential
  answers across every editor's data" on `/api/v1/files/locate")
- Reasoning: read `claim` end to end (`routes_fleet.py:398-545`). It verifies
  the token/identity, the attestation, the phase, the cancel flag,
  `created_local`, the mode lock, the template/sidecar versions, the quality
  scope and the yt-dlp floor - and never once compares `editor` with
  `job['created_by']`. `_job_or_404` documents that it is deliberately not
  `db.get_job_for`, and `db.claim_download`'s WHERE clause (`db.py:1081`)
  tests phase, mode lock, `COALESCE(created_local,1)=1`, the cancel flag and
  lease freedom - not ownership. So the first claim on any created-local job
  is authorised by a valid `cce1.` token alone. Low is right: it needs a
  fleet-credentialled editor to aim at another editor's job id deliberately
  (the SPA only ever hands a companion its own), and the consequence is
  misplaced clips and a wrong `download_host`, not disclosure beyond a
  fleet that already shares the archive.
- Evidence: the route body and the CAS SQL as read above; the only use of the
  verified name is `db.claim_download(c, job_id, editor, ...)`, which WRITES
  `claimed_by`.
- Fix note: the suggested 410 is right and belongs beside the other 410s, but
  put it AFTER the phase/cancel checks so the most actionable sentence still
  comes first, and make sure it is not raised for a row with a NULL
  `created_by` (pre-migration rows), or an old job becomes permanently
  unclaimable. `heartbeat`, `clip_status` and `_record_done` already ride on
  the lease, so no other route needs the same test.

## ytdl-web-7
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: two module-level `def _column(row, key)` at `db.py:206` and
  `db.py:976`; the second wins for every caller in the module. They are
  behaviourally identical today (the first's `except TypeError` covers
  `row is None`, which the second handles explicitly), so nothing is broken -
  this is a maintenance trap, correctly rated low.
- Evidence: `grep -n "^def _column" ytdl/web/ytdlweb/db.py` -> 206, 976; both
  bodies read.
- Fix note: delete the line-206 definition and keep the 976 one - but the
  fourteen readers ABOVE 976 then depend on a name defined below them, which
  is fine at call time and confusing to read; moving the survivor up to 206 is
  the cleaner edit and is behaviour-identical either way.

## ytdl-web-8
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: the sentence is real and says "this search" for all three
  callers. But the hunter's own failure scenario ("an editor pastes eight
  links with the box unticked") is nearly unreachable as written:
  `dispatchLocal` returns at `if (!localWanted()) return false;` BEFORE the
  `createdLocal === false` branch, and `runUrls` computes `payload.local =
  localWanted()` microseconds earlier, so an unticked paste never reaches the
  note. The reachable path is the one the hunter did not name: a paste
  submitted unticked, the box ticked afterwards, then RETRY FAILED
  (`app.js:1436`) or the review-grid DOWNLOAD (`app.js:2288`), both of which
  pass `state.manifest.job.created_local` - and `db.job_dict` sets that field
  for url jobs too (`db.py:1906`). Confirmed on the wording, with the
  scenario corrected; still low.
- Evidence: `app.js:2519-2537` (the early return above the branch),
  `app.js:2241`, `app.js:1436`, `app.js:2288`, `db.py:1906`.
- Fix note: the suggested wording is right and carries no em dash, so the
  per-suite scan test stays green. The same file is the only one a fix
  touches; if a test is added, note that the static-app tests assert on the
  literal string.

## wire-1
- Verdict: CONFIRMED (high)
- Duplicate of: none
- Reasoning: I read both sides. `_pump_uploads`
  (`broll_ingest.py:2976-3013`) branches on 200 and 409 and its `else` is a
  bare `self.log.warning`; the item keeps `stage == ITEM_UPLOADING` and every
  rel stays in `landed`, so the next pump recomputes `missing = []` and posts
  the identical body. `upload_attempts` is incremented only in the 409 branch
  and `upload_lost_ticks` only in the "rels the queue never heard of" branch,
  neither of which this path reaches - so there is no ceiling and no other
  stall guard in the file (`grep` for `_fail_item(` shows every caller; none
  covers it). The server side now has two non-409 refusals of that exact
  route: `400 wrong_edit_proxy` and `400 outside_root`
  (`broll/web/app/ingest_batches.py:1141` and `:1157`), both with comments
  saying no retry can help. A 5xx wedges the same way, which is why this
  compounds wire-2. High is right.
- Evidence: the two branches quoted above; `IngestClient._call`
  (`broll_ingest.py:390`) raises only on 410, returning every other status
  verbatim; `grep -rn "wrong_edit_proxy"` hits only the server and
  `broll/web/tests/test_fleet_ingest.py` - no companion-side reader.
- Fix note: the suggested split (4xx-not-409 terminal, 5xx a counted attempt)
  is right. A fix touches `companion/src/ccsync_companion/broll_ingest.py`
  only for the logic, but the music path shares this pump through
  `_post_uploaded`'s override, so check `music` item states too: `_fail_item`
  there must not skip the `queued_for_base_rig` ending (`_final_state`).
  Add the companion-side test the hunter says is missing.

## wire-2
- Verdict: CONFIRMED (medium)
- Duplicate of: none for the MOUNT gap (dash-api-2 / dash-core-2 / dash-db-2 /
  dash-db-3 are about the busy handler's own extra write, a different defect
  in the same rework)
- Reasoning: I proved the mechanism rather than reasoning about it. A
  `@app.exception_handler(Exception)` on the parent FastAPI app is installed
  as the parent's `ServerErrorMiddleware` handler; a mounted sub-app has its
  own error middleware, which answers `500 Internal Server Error` itself
  before re-raising, so the parent's 503 branch never runs for `/broll`,
  `/music`, `/ytdl` or `/cards`. `broll/web/app/db.py:249` opens connections
  with sqlite3's default 5 s busy timeout and there is no busy translation
  anywhere in `broll/web/app/` (only `search.py`'s FTS catches). The reader
  side is as quoted: any non-200 from `/items/{uid}/result` clears
  `item["described"]` and calls `_fail_item`, discarding the local VLM work.
- Evidence: scratch script with a parent app carrying the 503 handler and a
  mounted sub-app raising `sqlite3.OperationalError("database is locked")`,
  run on `dashboard\.venv`: `parent route: 503`, `mounted route: 500
  'Internal Server Error'`. Plus `grep -rn "exception_handler\|
  OperationalError" broll/web/app/*.py` -> four hits, all in `search.py`.
- Fix note: registering the handler on each sub-app is correct, but do it
  through a shared installer that the sub-app can also use standalone
  (`broll/web` runs on its own in dev), and be careful that the handler's
  `notices.record_db_busy` writes to the DASHBOARD db, not the mounted app's -
  the sub-apps have no `settings.db_path`. Do not fix this without wire-1: a
  503 that the companion still treats as terminal only moves the loss.

## wire-3
- Verdict: CONFIRMED (medium)
- Duplicate of: dash-cards-8 ("a discarded agent push reads as a healthy cards
  role") - the same defect seen from the dashboard side; dash-cards-1 is the
  neighbouring hot-loop consequence of the same `_no_engine` answer
- Reasoning: `_no_engine` (`cards_tunnel.py:137`) returns `{"error": ...}`
  with FastAPI's default 200, and `_routed` hands it back as the route's
  body. `TunnelClient.call` (`timeline_cards_role.py:911-921`) raises only on
  `status != 200`; on 200 it calls `_note_call(200, "")`, which CLEARS
  `_last_error` and moves `_last_poll_at`, then `_note_traffic`, which reads
  `timeline`/`project` off the REQUEST body - so the tray, the role's health
  and the fleet grid all report a healthy agent pushing timeline X while
  every push is discarded. I checked the real far end in the other repo:
  `multicam_pipeline/cards/agent.py` `push_loop` ignores the answer entirely
  for a full-state push (line 2049) and reads only `ans.get("resend")` for the
  playhead ping (line 2074), so the sentence reaches nothing there either.
- Evidence: the four code sites above, read in both repos.
- Fix note: the suggested fix is right and the hunter's caveat is important -
  do NOT change `/agent/pending`'s 200 `{}` shape, because `pull_loop`'s
  `if got.get("id") is None: continue` depends on it. Treating a 200 carrying
  `error` as NOT-ATTACHED in `TunnelClient.call` is the one-sided change, and
  it must not raise (a raise would put the role into a retry/backoff state and
  reintroduce dash-cards-1's hot loop from the other end).

## wire-4
- Verdict: CONFIRMED (low)
- Duplicate of: broll-1 (rated medium by that hunter) and comp-broll-tiers-4;
  this is the same defect reported from three sides
- Reasoning: confirmed the collapse exactly. `insert_target_detail`
  (`routes_api.py:76-136`) returns `original_rel=None` with `rel_path` falling
  back to the preview for a clip with no unique sibling, and its docstring
  spends a paragraph saying the null is an answer; `derive_insert_paths`
  (`broll_server.py:768-773`) applies "absent is not null" to `preview_rel`
  and `edit_proxy_rel` but keeps `original_rel = rel_path` for an explicit
  null. `plan_insert` then reads `posixpath.splitext(original_rel)` - the
  PREVIEW's `.mp4` - so `PLAN_PREVIEW_ONLY` cannot fire and the clip takes
  `PLAN_FETCH_STANDIN` with `fetch_rel == the preview's own path`. Low is the
  right rating and I would not raise it: the population is the four
  stem-diverged archive task #23 clips named in `_insert_target`'s own
  docstring, the file that lands is the same file either way, and the harm is
  a permanent ledger row plus the suppressed relink guards - real, but
  bounded.
- Evidence: the three functions read side by side; `_insert_object`
  (`routes_api.py:139`) forwards `original_is_edit_weight = _is_edit_weight(
  video)`, which is what makes `heavy` true for such a row and puts it on the
  stand-in branch.
- Fix note: the `original_known` third state is the right shape, but the fix
  must be made on BOTH sides of the wire in one change: `derive_insert_paths`
  and `plan_insert` in `companion/src/ccsync_companion/broll_server.py`, and
  the tests that pin today's reading -
  `companion/tests/test_broll_insert_tiers.py` (which, per the tests hunter,
  only uses objects whose `original_rel` is a real path) and the malformed-
  `insert` test tests-2 names. Nothing on the server side needs to change: it
  is already answering correctly.
