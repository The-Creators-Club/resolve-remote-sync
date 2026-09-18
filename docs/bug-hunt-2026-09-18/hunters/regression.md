# regression - did the 09-11b fix pass (CR-249..CR-266) actually close its findings, and did the 30 commits since undo any of them

Files read (with approximate coverage):
- `docs/bug-hunt-2026-09-11b/tally.txt` (all 154 ids), `docs/bug-hunt-2026-09-11b.md`,
  `docs/bug-hunt-2026-09-11b/ASSIGNMENTS.md`, and all 25 ledger files in
  `docs/bug-hunt-2026-09-11b/ledger/` (headings + every entry cited below in full).
- `KNOWN_BUGS.md` CR-249..CR-281 (grep -a, the fix-pass and post-pass entries).
- Verified in the code at HEAD, both sides where the finding was two-sided:
  `companion/src/ccsync_companion/{app.py,file_moves.py,tray.py,tray_native.py,broll_ingest.py,supervisor.py,machine.py}`,
  `companion/src/ccsync_companion/sync/{sequencer.py,rclone_lane.py,lane_guard.py,syncthing_admin.py,syncthing_lane.py}`,
  `dashboard/src/ccsync_dashboard/{api.py,db.py,ui.py,app.py,alerts.py,notices.py,collector.py,package_store.py,release_feed.py,dashboard_update.py,assignments.py}`,
  `dashboard/deploy/select_code_root.py`, `dashboard/templates/partials/admin_packages.html`,
  `music/web/musicweb/routes_batches.py`, `music/web/static/ingest.js`,
  `broll/web/app/{routes_fleet.py,routes_ingest.py,client_folders.py}`, `broll/web/static/{app.js,ingest.js}`,
  `onboarding/steps.py`, `installer/macos_bootstrap.sh`, `.github/workflows/ci.yml`.
- `git diff 34a3c8f..HEAD` over every file the fix pass touched (the 46-file
  intersection), plus `git show` of 4aaca6a, f266225, 579e9fa, 924b5c2, c9303bd,
  142e2cf, 7008e65, 11b81e1, c70cbe4.

Tests run:
- `dashboard/.venv/Scripts/python.exe -m pytest tests/test_bug_hunt_2026_09_11b_dash_{api,db,core,collector_alerts,mounts_ui,release_jobs}.py -q -rs` -> **102 passed**, 0 skipped.
- `companion/.venv/Scripts/python.exe -m pytest tests/test_bug_hunt_2026_09_11b_comp_{sync,app,ui,resolve,broll_music,ytdl_jobs}.py -q -rs` -> **149 passed**, 0 skipped.
- Mutation runs (scratch copies OUTSIDE the repo, source read from the repo):
  the pre-fix `expire_delivered_file_moves` predicate, the pre-fix
  `_note_lane_b_abandoned`, and `git show 40f931a:onboarding/steps.py` against
  the HEAD onboarding test file. All three make the corresponding regression
  test fail, as the ledger claims.

Method: for each 09-11b finding I read the hunter's original failure scenario,
the builder's ledger entry, the code at HEAD, and `git log -p 34a3c8f..HEAD`
over the fixed file. All 14 highs were verified individually; the mediums were
verified where a later commit touched the same file; the lows were sampled
(six full, plus a mechanical "is this id cited anywhere in the tree" pass over
all 154).

## Headline verdict

**No fix from CR-249..CR-266 was reverted or bypassed by the 30 commits since.**
Of the fourteen highs, eleven are CLOSED end to end with the regression test
proven to fail without the fix (comp-app-1/regression-18, res-companion-1/wire-1,
comp-sync-b-1/res-companion-2/regression-15, comp-ui-1/regression-7/regression-16,
comp-broll-music-1, dash-api-1, dash-db-1/res-fleet-1, wire-2, res-fleet-2,
tests-1, music-1). The three findings below are where a fix does not close the
whole of its hunter's scenario, and two more are post-pass work (CR-270, CR-279)
that landed on top of a 09-11b fix without inheriting its constraints.

## Findings

### regression-1 - CR-262C does not close music-3: the retry it made unconditional is refused by CR-253A from the SAME fix pass, and the batch cannot be dispatched by any button on the page
- Severity: medium
- Confidence: CONFIRMED
- Where: `music/web/static/ingest.js:1291-1300` and `:1353-1358` (CR-262C) against
  `companion/src/ccsync_companion/broll_ingest.py:1784-1806` (CR-253A)
- What: music-3 was "a retried batch is undispatchable after a page reload:
  music has no take-over path". CR-262C fixed it by making the dispatch
  unconditional and sending `staging_id: ''` whenever the page no longer
  remembers the drop. CR-253A, landed in the same pass, added the opposite rule
  to the SHARED companion ingestor: a claim that names no staging id, whose
  items carry no `local_path`, is refused `409 staging_id_missing` when
  `_staging_holding(items)` finds a staging entry for those files on this
  machine. `self._staging` is in-process, so a page reload does not clear it -
  which is exactly the state CR-262C's fix is for. The two fixes are mutually
  exclusive on the one path both were written for.
- Failure scenario: an editor drops 15 tracks, one fails, the batch ends
  `done_with_errors`; they reload the page and press "try the failed tracks
  again". `mi.batchUid` is empty, `staging_id: ''` goes out, the companion is
  still holding the staging entry, and the loopback answers 409 with "reload the
  page and try again" - the action that caused it. `miRetryFailed` swallows the
  body in a bare `catch { }` (`ingest.js:1358`) and toasts that the tracks are
  queued. `take over on this computer` is drawn (the batch is `queued`), posts
  the same empty `staging_id`, hits the same guard, and `miTakeOver`'s blind 409
  branch reports "Another of your computers is still working on this batch." The
  editor's other machine is idle. The only exits are cancel-and-re-drop or a
  companion restart.
- Evidence: read both halves at HEAD; `broll/web/static/ingest.js:1738-1745`
  shows the same collision degrading honestly (it prints the companion's own
  sentence), which is what music was supposed to have been ported from. The
  09-11b ledger records CR-262C and CR-253A as independently FIXED with no note
  that they meet.
- Ledger: "CR-262C does not fix music-3". The editor-facing copy half of this is
  already reported as `music-2` in this hunt (`hunters/music.md`) - cite that for
  the wording; this entry is about the dispatch itself being impossible, not
  only mis-described.
- Suggested fix: teach music's page the reload hint (music-2's fix), and make
  the take-over path carry a `takeover: true` flag that `broll_ingest.run` honours
  as "the staging entry you are holding is stale, adopt it" rather than refusing.

### regression-2 - CR-279's heartbeat relaxation counts an rclone child CONSOLIDATE spawned, so a wedged sequencer is never restarted while a consolidate transfer keeps moving bytes
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/sequencer.py:647-665`
  (`seconds_since_heartbeat`), `companion/src/ccsync_companion/sync/rclone_lane.py:4453-4473`
  (`_child_progress_at`, `seconds_since_child_progress`),
  `companion/src/ccsync_companion/app.py:3966-3984` (`consolidate_project`)
- What: CR-279 (c70cbe4) relaxed the sequencer watchdog by taking
  `min(silence_since_the_last_turn_stamp, age_of_the_lane_child's_last_progress)`,
  on the reasoning that "a lane child that is still moving bytes is the loop
  making progress". That inference only holds if the child belongs to the
  sequencer's own turn. It does not: CONSOLIDATE calls `self._lane_a.run_once()`
  and `self._lane_b.run_once()` on its own thread, on the SAME lane instances
  the Sequencer was constructed with (`app.py:1712-1713`), and those calls take
  the non-express `_wait_with_watchdog` path that stamps `_child_progress_at`.
  The express path is correctly excluded; the consolidate path is not.
- Failure scenario: an editor presses FIX ALL / CONSOLIDATE (which is refused
  while syncing is paused, so the sequencer is necessarily running). Consolidate
  starts a multi-hour lane A upload that keeps ticking `--stats`. In the same
  window the sequencer thread wedges - a Syncthing call that never returns, the
  CR-93 shape, anything the watchdog exists for. `seconds_since_heartbeat()`
  returns the consolidate child's progress age, a few seconds, for the whole
  transfer. The watchdog never fires, the tray shows the sequencer as alive, and
  nothing syncs on its schedule until the consolidate finishes. The same shape
  applies to the FIX ALL proxy pull through lane B.
- Evidence: `app.py:3966` (`self._lane_a.run_once(subpath)`) and `:3982`
  (`self._lane_b.run_once(subpath)`) run on the consolidate thread; `app.py:1712`
  passes `self._lane_a, self._lane_b` to `Sequencer(...)`, and
  `sequencer.py:283-284` stores those same objects as `self.lane_a`/`self.lane_b`,
  which `:656` iterates. `rclone_lane.py:4454` stamps
  `self._child_progress_at` for any `express=False` run, with no notion of which
  thread asked. The 09-11b finding regression-4 already established that the
  lane object is shared with CONSOLIDATE; CR-279 was written without it.
- Ledger: new (CR-279 is a post-pass commit, not in the 09-11b ledger). Closely
  related to 09-11b regression-4 ("comp-sync-7: the new stale-subpath gate is on
  the shared lane object, so CONSOLIDATE's proxy pull is silently dropped") -
  the same shared-object assumption, made twice.
- Suggested fix: stamp the child progress with the thread (or a token the
  sequencer mints per turn) and let `seconds_since_heartbeat` count only a child
  its own turn spawned; or have consolidate run through a lane clone.

### regression-3 - CR-270's retire branch is asked before CR-259a's schema guard, is not schema-aware, and no test can reach it
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/deploy/select_code_root.py:424-451` (the retire branch,
  f266225) against `:279-340` and `:467-487` (CR-259a's `revert_refusal` /
  `live_schema_version`); test world at
  `dashboard/tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py:47-80`
- What: CR-259a (res-fleet-2) made the automatic crash-loop revert refuse to go
  back past a migration the live database has already taken. CR-270 then added,
  ahead of everything, a branch that RETIRES an applied tree whose version is
  not newer than the image's: `current.json` is rewritten with an empty version,
  `boot_attempts.json` is cleared, and the image boots. That branch asks the
  version question only. It is safe under `check_tree` rule 5's invariant ("an
  OTA tree is always newer than the image", so image-version >= tree-version
  implies image-schema >= tree-schema), but nothing enforces that invariant at
  this point and the branch is what decides whether the schema guard is ever
  consulted.
- Failure scenario: the operator rolls the container IMAGE backwards past a
  migration the live database already took (a bad image, `docker compose` on an
  older tag, the image-mode revert). The applied OTA tree - the one tree that
  could still run this schema - is now "not newer than the image", so it is
  retired, `current.json` is cleared, and the image boots into a `migrate()`
  that fails on a v53 database. CR-259a's guard is never reached, and its
  recorded escape hatch (`revert_refused_reason` / `revert_refused_from`, which
  `alerts.py:2664` looks for) is dropped by the same write, because the retire
  branch writes a fresh five-key dict.
- Evidence: the retire branch at `:437-451` returns `image_pythonpath()` before
  the `already_failed >= MAX_BOOT_ATTEMPTS` block at `:467` that calls
  `revert_refusal`. The res-fleet-2 tests cannot see it: `_world()` never
  monkeypatches `APP_ROOT`, so `image_version()` reads a non-existent `/app` and
  returns `""`, `parse_version("")` is falsy, and the branch never fires in any
  test - the one CR-270 test that exercises it
  (`test_the_image_is_judged_by_its_own_migration_list`) had to monkeypatch
  `image_version` to `"0.7.42"` to keep the OLD test reachable (git diff 34a3c8f..HEAD over that
  test file shows exactly that edit).
- Ledger: new; "CR-270 narrows CR-259a". Note this is a correction, not a
  revert: the case CR-270 removes from the counted set used to revert to an
  equally stale record, which was worse. `dash-mounts-ui-1` in this hunt covers
  the separate problem that `retired_from` is written where no surface reads it.
- Suggested fix: ask `revert_refusal("")` (is the IMAGE safe for this database)
  before retiring, and keep `revert_refused_*` when the retire branch rewrites
  `current.json`; add one test whose world has a real `APP_ROOT`.

### regression-4 - CR-259a's guard treats "the staged tree could not say what schema it knows" as schema v0, and permanently refuses the rollback it exists to protect
- Severity: low
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (reachability)
- Where: `dashboard/src/ccsync_dashboard/dashboard_update.py:1373` and `:1394`
  (`int(checks.get("schema_version") or 0)`) against
  `dashboard/deploy/select_code_root.py:279-300` (`tree_schema_version`) and
  `:302-312` (`revert_refusal`)
- What: `tree_schema_version`'s own docstring says "None is NOT zero and must
  never read as safe", and `revert_refusal` is built on the three-way answer
  (`None` = cannot judge = allow, a number = compare). The writer collapses the
  third state: a stage-verify whose `schema_version` key is missing or zero is
  written into the manifest as the integer `0`, which reads back as a real
  number, and `0 >= live` is false for any live schema. The escape hatch is then
  refused for ever, with the sentence "<version> knows database schema v0 and
  this database is on v53".
- Failure scenario: a tree whose stage-verify JSON lost the key (a partially
  parsed subprocess answer, a tree applied by a build that predates REL-10's
  `schema_version`, a `0` written by the `except` arm at
  `dashboard_update.py:866`) is applied. It later crash-loops. The automatic
  revert refuses, permanently, naming a schema the tree does not claim, and the
  admin is told to restore a backup rather than being allowed the rollback the
  guard would have permitted had the value been absent.
- Evidence: read both sides; `dashboard_update.py:861-868` shows the subprocess
  defaults `schema_version` to `0` in its own `except`, and `:1373`/`:1394` apply
  `or 0` again on top. `select_code_root.tree_schema_version` returns `None` only
  for a MISSING or unparseable key, which `or 0` guarantees never happens.
- Ledger: "CR-259a does not fully fix res-fleet-2" (the guard's own
  "cannot tell" state is unreachable from the writer).
- Suggested fix: write the key only when the probe answered
  (`if checks.get("schema_version"): staged_manifest["schema_version"] = ...`),
  so a tree that could not say reads back as `None`.

### regression-5 - CR-258B does not close dash-collector-alerts-1 for a deployment whose collector has not yet run any kind twice
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:8955-8999` (`collector_stale_bound`),
  `:9058-9064` (`fetch_collector_status`), read by `api.py:1414`, `db.py:3926`
  and `dashboard/templates/partials/collector_health.html:19-21`
- What: dash-collector-alerts-1 was "a Syncthing-less deployment now reports its
  own healthy collector as STOPPED, for ever". CR-256b fixed the ALERT by
  re-asking against the CONFIGURED intervals (`alerts._stale_after_seconds`, 1200 s
  by default with no `syncthing_url`), and CR-258B fixed the STORED flag by
  deriving the bound from the OBSERVED rhythm. The observed bound needs a kind
  to have started twice; with none, it returns the 180 s floor, which is the
  original bug's premise. CR-256o - the hand-off that would have given db.py the
  same configured-interval fallback - is recorded NOT DONE in
  `ledger/dash-collector-alerts.md:280-295`, on the reasoning that it "cannot
  change the first verdict", which is true of the alert and not of this flag.
- Failure scenario: a brand new zero-touch or vendor deployment with no
  `syncthing_url`. Between roughly t+3 min and the second `alerts` cycle at
  t+10 min, the home page shows "the last collector cycle finished too long ago:
  everything below is ... not the state now" and `/api/v1/health` reports the
  collector stale, on a collector that is perfectly healthy. The first
  impression of the product is a red banner. The alert, the notice, the topbar
  chip and the mail are all correctly silent, so the visible half is exactly the
  half CR-258B was written for.
- Evidence: `collector_stale_bound`'s own docstring states the residue ("a kind
  that has run only once tells us nothing about cadence, so a container with no
  repeat yet keeps the floor"); `POLL_RUNS_KEEP = 2000` means this is a fresh
  DATABASE, not a fresh container, so the window is narrow but it is the
  first-boot window.
- Ledger: "CR-258B does not fully fix dash-collector-alerts-1"; related to
  CR-256o (declined).
- Suggested fix: floor the bound at the shortest CONFIGURED interval for the
  kinds this deployment actually runs when no observed gap exists yet - the
  number `alerts._stale_after_seconds` already computes.

### regression-6 - CR-255k fixed one of tests-3's two neutered assertions; the companion one is untouched and unledgered, and the fix pass added a third
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/tests/test_app.py:6914`
  (`assert "-" not in blocked["detail"].replace("CCSync", "") or True`); the new
  one at `dashboard/tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py:329`
  (`assert not hasattr(settings, "release_feed_sig_url") or True`)
- What: tests-3 named two `or True` assertions. CR-255k's KNOWN_BUGS entry and
  its ledger both describe only the dashboard one
  (`dashboard/tests/test_selection_api.py`), and the finding is recorded FIXED.
  The companion half survives verbatim, and the fix pass then wrote a new
  can-never-fail assertion into one of its own regression test files.
- Failure scenario: the hunter's own scenario for the companion half - the
  `project_dir_moved` detail acquires a hyphen-joined phrase the owner's copy
  rule bans, and the line meant to catch it passes; only the `(em dash)` assert on
  the next line has any force, and it does not cover the case the neutered line
  names.
- Evidence: `grep -n "or True"` over the test trees at HEAD; `sed -n '6914p'` of
  the companion file is unchanged since before the fix pass;
  `grep -an "tests-3" KNOWN_BUGS.md` returns only CR-255k, which names one file.
- Ledger: "CR-255k does not fix tests-3" (half of it).
- Suggested fix: delete the companion line (the `(em dash)` assert beside it is the
  real check) and the new dashboard one.

### regression-7 - tests-4 was dropped from the fix pass with no fix, no decline and no ledger entry anywhere
- Severity: low
- Confidence: CONFIRMED
- Where: `music/web/tests/test_bug_hunt_2026_09_11_music.py:307-315`
- What: tests-4 ("a regression test that skips itself when the thing it guards
  appears") is one of the 154 tally ids and is assigned in
  `docs/bug-hunt-2026-09-11b/ASSIGNMENTS.md`, but the string `tests-4` appears
  nowhere in `KNOWN_BUGS.md`, in any of the 25 ledger files, or in the tree. The
  test is byte-identical to what the hunter reported: it greps the package for a
  production `apply_for_track(..., force=True)` caller and `pytest.skip()`s if
  one exists.
- Failure scenario: exactly the hunter's - a `force=True` caller lands, the test
  skips silently for the rest of the repo's life, and the docstring it guards is
  never revisited. A skip in a suite of 25 is invisible.
- Evidence: `git log --oneline 34a3c8f..HEAD -- music/web/tests/test_bug_hunt_2026_09_11_music.py`
  is empty; `grep -an "tests-4" KNOWN_BUGS.md docs/bug-hunt-2026-09-11b/ledger/*.md`
  returns nothing while tests-1/2/3/5 all have entries. Of the 154 ids this is
  the only one with neither a fix nor a recorded decline.
- Ledger: new ("tests-4 was never actioned"). Distinct from the six entries the
  pass did decline on purpose (CR-256i NOT A BUG, CR-256o NOT DONE, CR-258F
  DOCUMENTED/OWED, CR-264h MITIGATED, CR-264i PARTLY FIXED, and dash-api's
  DECLINED first-class `applying` state), all of which are cited, not re-found.
- Suggested fix: make the caller case an explicit assertion about what the
  docstring must then say, or delete the test and keep the docstring fix.

## Coverage note

What I verified to CONFIRMED depth: all 14 highs from `tally.txt`, both sides of
each two-sided one, with the regression test mutation-checked for five of them.
The mediums were verified where a later commit touched the fixed file (which is
how regression-2 and regression-3 were found); the ones in files with no commits
since 34a3c8f were read but not mutation-tested. Of the lows I read six in full
(broll-6, comp-app-8, security-4, regression-12, install-onboard-4, res-fleet-4 -
all CLOSED) and ran a mechanical citation pass over all 154 ids, which is how
tests-4 surfaced; the remaining ~50 lows are unsampled.

Post-pass work (CR-267..CR-281) was judged against its KNOWN_BUGS text rather
than a hunter's failure scenario, since there was none. CR-267a/b/c, CR-268a/b,
CR-269 and CR-271..CR-275 I read and found consistent with their ledger claims;
CR-270 and CR-279 are regression-3 and regression-2 above. CR-276, CR-277,
CR-280 and CR-281 I did not reach - `dash-cards.md`, `dash-release-jobs.md` and
the proxy-tiers hunters cover their territory.

What the suites do not cover, relevant to this lens:
- Both fix-pass regression suites are entirely green at HEAD (102 + 149, zero
  skips), so nothing here was caught by a red test. Every finding above is in
  the gap between what a test asserts and what its hunter's scenario was.
- No test anywhere reaches `select_code_root.py`'s retire branch with a real
  `APP_ROOT` (regression-3), and no test runs `seconds_since_heartbeat` with a
  lane child a second thread spawned (regression-2).
- The brief says the 09-11b summary lists findings "deliberately NOT fixed" in a
  "Not fixed" section. It does not - `docs/bug-hunt-2026-09-11b.md` was written
  before the fix pass and says "STATUS: UNFIXED, by rule" of everything. The
  deliberate non-fixes are in the ledger headings; the six of them are listed in
  regression-7's Ledger line so the next hunt can cite rather than re-find them.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/collector.py:487-498`: `record_slow_write("collector poll <kind>", elapsed)` measures the poll's WALL time, not lock-hold time, so a poll that is slow because the NAS is slow publishes a notice blaming it for holding the write lock. Already reported as `dash-collector-alerts-4`.
- `dashboard/src/ccsync_dashboard/app.py:1352-1361`: the busy-database handler opens a second connection and COMMITS a notice while the database is under contention, adding a writer per contention event; neither `db_busy` nor `slow_write` is ever cleared. Already reported as `dash-api-2`, `dash-db-3` and `dash-core-2`.
- `broll/web/static/ingest.js:ingestTakeOver`: the same blind `409` branch music-2 reports, in b-roll's page.
- `dashboard/src/ccsync_dashboard/collector.py` (`_run_enforce`): CR-258F is recorded as DOCUMENTED with the one-line `for_enforce=True` call-site change still owed to dash-collector-alerts; it has not landed.
