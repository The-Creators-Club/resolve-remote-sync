# verdicts - security-regression

Verified at HEAD 214869b. Everything below was read in the tree; the one probe
was run against a `create_app` TestClient in the dashboard venv from a
scratchpad script. No live process, no `~/.ccsync`, no NAS, no repo edits
outside this file.

## security-1
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `_open_path` (`app.py:145-148`) is a pure path test and
  `login_gate` (`app.py:1164+`) never reads `request.method`, so the four PWA
  carve-outs are open to every verb although all four comments say "GET only".
  `csrf_gate` does not catch the residue either: `if not
  auth.session_is_tracked(request): return await call_next(request)`
  (`app.py:1002`) means an unauthenticated POST skips CSRF as well, and
  `CardsGate` (`cards.py:353-370`) checks only `BLOCKED_PATHS` and the agent
  prefix, never a session. So under the mount the request really does reach the
  checkout's `do_POST`. Two things keep this low and I could not push it higher:
  `CardsDispatch` never BUILDS an engine, so the slug must already be open, and
  the 4 MB buffer is spent by `body_size_gate` on any unauthenticated path
  anyway.
- Evidence: reproduced the hunter's probe in the dashboard venv -
  `GET /cards/` and `POST /cards/open` -> 303 to `/login`, while
  `POST /cards/sw.js`, `POST /cards/manifest.webmanifest`,
  `DELETE /cards/icon.svg` and `POST /cards/p/ep-12345678/sw.js` all fall
  through to a 404 from the router; `POST|GET /cards/p/<slug>/api/state` 401s,
  i.e. the gate is working everywhere except the open paths.
- Fix note: the suggested `(method, path)` test is right. Include HEAD (Chrome
  HEADs a manifest on some paths) and apply it to the `_OPEN_PATTERN` branch as
  well as the three literals. No test pins the old behaviour, so nothing breaks;
  a fix should add one, since the coverage note is correct that none exists.

## security-2
- Verdict: CONFIRMED (medium)
- Duplicate of: partially overlaps dash-cards-3 (same refusal sentence, same
  "leaving frees nothing" fact); dash-cards-3 is the copy, security-2 is the
  missing capability. Not a duplicate of dash-cards-5 (thread leak on close).
- Reasoning: `cards_open` (`cards_landing.py:145-175`) has no role test;
  `cards_close` (`:179-195`) refuses any non-admin. `EnginePool.open` counts
  `state != FAILED` entries against `self.cap` and returns `_full_sentence`;
  nothing else calls `drop()`, and `occupants()`/`ACTIVE_SECONDS` only decorate
  the sentence - no idle release exists. So two mistaken opens by one
  non-admin park the whole feature until an admin acts or the container
  restarts, and the refusal names the editors holding the seats to every
  logged-in user. Medium is right: it is an availability hole any signed-in
  user can open by accident, on the surface a phone stages a cut on.
- Evidence: code as cited; `grep` finds `pool.drop` called only from
  `cards_close`; `_full_sentence` interpolates `entry.occupants()` (usernames)
  into the string rendered to the refused party.
- Fix note: the suggested self-close is right, but a fix must also touch
  `dashboard/templates/cards_landing.html` (the close control is drawn
  admin-only and `ready`-only - see dash-cards-2 for the `ready`-only half) and
  should land with dash-cards-3's sentence, or the page will promise an act the
  template still does not draw. `drop()`'s own docstring is the constraint: a
  self-close still leaks the upstream threads, so it must not be sold as free.

## security-3
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `cards_landing.py:172-174` and `remember()` at `:277-280` set
  `secure` from `request.url.scheme` / a passed-in bool, while every other
  cookie goes through `auth.cookie_secure` (`auth.py:539-555`), which honours
  `DASH_COOKIE_SECURE` and `X-Forwarded-Proto` from a trusted proxy only.
  Behind a TLS terminator the scheme is `http`, so on a `DASH_COOKIE_SECURE=1`
  site the session cookie is Secure and this one is not. The payload is a slug
  behind `httponly` + `samesite=lax`, so low is the right rating; the finding's
  value is the one-helper rule. The `remember()`-has-no-caller observation also
  checks out: `grep -rn "remember("` over `dashboard/src` finds the definition
  and a comment in `cards.py:223`, no call.
- Evidence: the two call sites and `cookie_secure` read side by side; the grep
  above.
- Fix note: correct as suggested. `remember()` takes `secure` as an argument,
  so wiring it into `CardsDispatch._note` means giving the dispatcher the
  Settings object (`request.app.state.settings` is not in an ASGI-level
  dispatcher's hand) - that is the one non-trivial part of the fix, and
  deleting the helper is the cheaper honest option.

## security-4
- Verdict: DOWNGRADED to low-as-parse-cost only (severity stays low; the
  cross-project half is REFUTED as a defect)
- Duplicate of: none (dash-api-1 and dash-api-3 are about the inventory
  locate answers FROM, not its scope)
- Reasoning: the wide scope is not a defect - `api_locate_files`' own docstring
  states it ("this reads the whole tree's inventory across every active
  project, which is more than any one editor's pages show them") and the route
  is behind the full fleet gate, so it is a documented design choice, not an
  oversight; a hunter finding may not re-rate a decision on the strength of
  restating it. The unbounded model is real: `LocateIn.files` has no
  `max_length`, `MAX_LOCATE_FILES` (2000, `locate.py:50`) is tested inside the
  handler at `api.py:10757`, and `_BODY_LIMITS` has no entry for the path, so a
  4 MB body is buffered and fully parsed into `LocateFileIn` models before the
  413. That is a cheap DoS on a single-worker container by an authenticated
  fleet caller - low.
- Evidence: the SQL at `locate.py:87-90` (`WHERE p.active=1` only); the cap
  after `_require_fleet_caller`; no `/api/v1/files/locate` key in `_BODY_LIMITS`.
- Fix note: `Field(max_length=2000)` on the list is right and cheap, but it
  changes the refusal from a 413 with the route's careful sentence to a
  pydantic 422 - and that sentence exists precisely so a caller does not read a
  truncated answer as "not on the server". Keep the 413 by adding a
  `_BODY_LIMITS` entry (a declared-length refusal before any buffering) rather
  than by moving the check into validation, and check
  `companion/src/ccsync_companion/sync/server_locate.py` (the caller) for what
  it does with a 422 it has never seen.

## regression-1
- Verdict: CONFIRMED (medium)
- Duplicate of: overlaps music-2 (this hunt) on the messaging half only;
  regression-1 is the deeper claim (the dispatch cannot be made at all)
- Reasoning: I read both halves and the wire between them.
  `broll_server.py:2281-2305` routes `/music/ingest/retry` into
  `ingestor.retry(body)` and then, when the body carries a `batch_uid`, into
  `ingestor.run(batch_uid, staging_id, run_mode)`. `run` holds CR-253A
  (`broll_ingest.py:1791-1806`): no staging id + no item with a `local_path` +
  `_staging_holding(items)` non-empty -> 409 `staging_id_missing`.
  `_staging_holding` (`:1852-1871`) matches on (name, rel_dir) against
  `self._staging`, which is in-process and persisted (`_save`/`:863`) and is
  only cleared by the retention sweep at `:3515-3540` - a page reload clears
  none of it. `music/web/static/ingest.js:1353-1358` posts `staging_id: ''`
  after a reload (`mi.batchUid` is empty) and swallows the answer in a bare
  `catch`, and `miTakeOver` (`:1291-1300`) posts the same empty id and reports
  every 409 as "Another of your computers is still working on this batch". So
  both exits from the reload state are refused, on the machine that holds the
  files.
- Evidence: the four call sites above, read at HEAD; `_item_from_manifest`
  (`:1873+`) confirms every item gets `local_path: ""` when `staging` is None,
  which is the guard's own trigger condition.
- Fix note: the suggested `takeover: true` flag is right in shape but it must
  be added on THREE sides, not two: `music/web/static/ingest.js` (both
  buttons), `companion/src/ccsync_companion/broll_server.py` (the `/run` body
  allow-list at `:2308` is explicitly "`batch_uid`, `staging_id` and `run_mode`
  and NOTHING ELSE", so the plan doc and that comment change with it), and
  `broll_ingest.run`. Do not simply drop CR-253A's guard - it is what stops a
  retry burning MAX_ITEM_ATTEMPTS on every clip. The honest cheap fix is to
  have the page send the staging id the companion just named back to it: the
  409 body already carries `"staging_id": held`.

## regression-2
- Verdict: REFUTED
- Duplicate of: none
- Reasoning: the mechanism is real (the lanes are shared objects,
  `_child_progress_at` is a plain instance attribute stamped by any
  `express=False` run, and `consolidate_project` calls `run_once` on its own
  thread), but the stated failure scenario cannot happen, because the watchdog
  is ALREADY stood down for the whole of a consolidate. `CollectorWatchdog.check`
  (`app.py:984-987`) begins with `blocked = self._must_not_restart()` and
  returns `[]` on any blocker, and `_must_not_restart` (`:1023-1092`) reads
  `app._standing_down_would_kill_work()`, which returns `"consolidate"` while
  `_consolidate_active` is True (`:6312`) - set around the whole of
  `_consolidate_project_inner` (`:3697-3700`), i.e. across both lane runs. So
  during a consolidate the sequencer is never restarted whatever
  `seconds_since_heartbeat` returns, and CR-279 adds no new harm on that path.
  I also checked there is no second non-express caller: in managed mode
  `_start_lanes` (`:6150-6163`) starts lane C, the sequencer and lane A
  `start_watchdog_only()` - no periodic loop, no lane B loop - and the express
  path is explicitly excluded from the stamp (`rclone_lane.py:4454`), while
  `_child_progress_at` is reset to None in the `finally` at `:4459`. The tray
  claim in the finding is also wrong: nothing but `app.py:1106` reads
  `seconds_since_heartbeat`.
- Evidence: the three code paths above; `grep -rn "run_once("` over
  `companion/src` shows the only non-sequencer, non-express callers are
  consolidate and the unmanaged `sync_now` path (where `self.sequencer is
  None`, so there is no heartbeat to corrupt).
- Fix note: no fix needed for the reported scenario. If the owner still wants
  the hygiene (a token minted per turn), note that it would be inert today and
  that `_must_not_restart` is the load-bearing guard a future refactor must not
  drop; a fix that removed the stand-down while relying on the heartbeat would
  create exactly the bug reported here.

## regression-3
- Verdict: DOWNGRADED to low
- Duplicate of: none (dash-mounts-ui-1 covers `retired_from` having no reader)
- Reasoning: the code reads as the hunter says - the CR-270 retire branch
  (`select_code_root.py:424-451`) returns `image_pythonpath()` before the
  `already_failed >= MAX_BOOT_ATTEMPTS` block at `:467` that calls
  `revert_refusal`, and it rewrites `current.json` as a fresh five-key dict,
  dropping `revert_refused_reason`/`revert_refused_from` that `alerts.py`
  looks for. The test-coverage claim is also exact: `_world` in
  `test_bug_hunt_2026_09_11b_dash_mounts_ui.py:47-80` never patches `APP_ROOT`,
  and the CR-270 test had to monkeypatch `image_version` to `"0.7.42"` to keep
  the older test reachable. What does not hold is the failure scenario: the
  branch fires only when `installed <= image`, so "the operator rolls the image
  BACKWARDS" moves the tree to NEWER than the image and the branch is skipped.
  Reaching the danger needs an image whose VERSION is not lower but whose
  SCHEMA is - a build the release process does not produce. That makes this a
  latent invariant dependency plus a test gap, not a live crash-loop path.
- Evidence: `parse_version(version) <= parse_version(image_version())` at
  `:439`; the five-key `write_json` at `:441-448`; the test world read at HEAD.
- Fix note: asking `revert_refusal("")` before retiring is cheap and correct
  and nothing else reads the branch, so it breaks nothing; carrying
  `revert_refused_*` through the retire write additionally touches
  `alerts.py:2664`'s expectations (it must still clear when the tree is gone,
  or the banner outlives its cause - the `already_failed == 0` clearing branch
  at `:453-462` is the precedent to follow).

## regression-4
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `tree_schema_version`'s three-way contract ("None is NOT zero and
  must never read as safe") is genuinely collapsed by the writer:
  `dashboard_update.py:1373` and `:1394` both write
  `int(checks.get("schema_version") or 0)`, and the stage-verify subprocess
  already defaults to `0` in its own `except` (`:861-867`), so a probe that
  could not answer is recorded as a tree that claims schema v0 - and
  `0 >= live` is false for every live schema, i.e. a permanent refusal with a
  sentence that names a number the tree never claimed. I checked the one
  plausible refutation: `checks` is the WHOLE parsed subprocess dict (`checks =
  stage_verify(...)` at `:1355`), not the inner list, so the key really is
  read from where it is written. Low is right: the only way in is a tree that
  passes every other stage-verify check while failing to import
  `ccsync_dashboard.db`, which is narrow.
- Evidence: the two writer lines, the subprocess `except` arm, and
  `select_code_root.tree_schema_version` / `revert_refusal` read together.
- Fix note: the suggested conditional write is right. It must be made in BOTH
  places (`staged_manifest` at `:1373` and `current.json` at `:1394`), and
  anything reading `current.json["schema_version"]` unconditionally must take
  the same `None` (grep before landing); `live_schema_versions` beside it is a
  separate key and is unaffected.

## regression-5
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `collector_stale_bound` returns the caller's floor whenever no
  kind has started twice (`db.py:8995-8996`), and every caller -
  `api.py:410/451/1369`, `db.py:3912`, `ui.py:927` - takes the default
  `stale_after_seconds`, i.e. `COLLECTOR_STALE_SECONDS` = 180 s. On a
  Syncthing-less deployment the fastest SYNCTHING_FREE kind is `alerts` at
  600 s, so between about t+3 min and the second alerts cycle the stored flag
  and `/api/v1/health` report a healthy collector as stale while the alert,
  the notice and the chip stay correctly silent. That is exactly the residue
  the hunter names, and `collector_stale_bound`'s own docstring admits it.
  Low: it is a first-boot window minutes wide, self-clearing, and the fix
  pass's stated goal (the permanent false STOPPED) really is closed.
- Evidence: the call sites above; `SYNCTHING_FREE_KINDS` intervals quoted in
  the docstring; the `if shortest is None: return floor` branch.
- Fix note: the suggested floor is right; the number lives in
  `alerts._stale_after_seconds`, which is in `alerts.py`, and `db.py` must not
  import `alerts` (cycle). Pass it down from the callers or move the interval
  table into `db.py` beside `SYNCTHING_FREE_KINDS` - that is the design
  question CR-256o was declined on, so the decline should be revisited
  explicitly rather than worked around.

## regression-6
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `grep -n "or True"` over the four test trees at HEAD returns
  exactly two assertions: `companion/tests/test_app.py:6914` and the new
  `dashboard/tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py:329`.
  `grep -an "tests-3" KNOWN_BUGS.md` returns only CR-255k at line 21329, whose
  heading names `dashboard/tests/test_selection_api.py` and nothing else, so
  the companion half is unfixed and unledgered and the pass did add a third.
  Low, and honestly so: the companion line as written would be WRONG if
  enabled (it bans every hyphen, and a hyphen with spaces is the owner's own
  recommended replacement for an em dash), which is probably why it was
  neutered instead of deleted.
- Evidence: the greps and both lines read at HEAD; line 6915 is the real
  `—` assertion beside it.
- Fix note: delete both lines rather than "fix" the companion one - making
  `"-" not in detail` live would fail on correct copy. Nothing else reads
  them, so no other file is involved.

## regression-7
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `tests-4` is id 142 in `docs/bug-hunt-2026-09-11b/tally.txt` and
  is assigned at `ASSIGNMENTS.md:153`, yet the string appears nowhere in
  `KNOWN_BUGS.md`, in any of the 25 ledger files, or anywhere in the tree
  outside the two 09-11b documents themselves. The test
  (`music/web/tests/test_bug_hunt_2026_09_11_music.py:308-320`) is byte
  identical to what the hunter reported and still `pytest.skip()`s when a
  production `force=True` caller appears. So it was dropped silently, which is
  the finding. Low, and the ledger value (the six deliberate declines are
  named so a later hunt cites rather than re-finds them) is the useful half.
- Evidence: `grep -rn "tests-4"` over the repo returns two hits, both in
  `docs/bug-hunt-2026-09-11b/`; `grep -an "tests-4" KNOWN_BUGS.md
  docs/bug-hunt-2026-09-11b/ledger/*.md` returns nothing.
- Fix note: the suggested fix is right and touches one file. Note the test
  lives in the 09-11 file, not the 09-11b one, so a builder looking in the
  fix-pass suite will not find it.
