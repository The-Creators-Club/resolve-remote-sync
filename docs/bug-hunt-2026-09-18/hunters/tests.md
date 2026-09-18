# tests - test QUALITY across the whole tree (does the test bite, does it test its own commit, does it mock away the break)

Files read (with approximate coverage):
`git diff --stat 34a3c8f..HEAD -- '*test*'` (48 files) as the map; read in full:
`companion/tests/test_broll_standins.py`, `companion/tests/test_proxy_relink_standins.py`,
`companion/tests/test_broll_insert_tiers.py`, the new `insert`-object block of
`companion/tests/test_broll_server.py` (lines ~1029-1210),
`dashboard/tests/test_db_busy_2026_09_17.py`, `dashboard/tests/test_select_code_root.py`,
`dashboard/tests/test_locate.py` (first half), `dashboard/tests/test_hand_moves_detected.py`
(names + the migration case), `dashboard/tests/test_cards_pool.py` (names/docstrings),
`broll/web/tests/test_insert_target.py`, the migration-test diffs in
`broll/indexer/tests/test_migrate.py` / `test_schema_parity.py` / `broll/web/tests/test_migration.py`,
`companion/tests/conftest.py` (the rclone gate), `companion/tests/test_jobs_media.py` (header),
`companion/tests/test_ffmpeg_tools.py` (header/loader), `dashboard/tests/test_no_em_dash.py`,
`dashboard/tests/test_alerts.py` (the registry-coverage test),
`.github/workflows/ci.yml` / `release-macos.yml` / `release-windows.yml` (test steps).
Supporting source read: `companion/src/ccsync_companion/broll_standins.py`,
`broll_server.derive_insert_paths`/`plan_insert`, `proxy_relink.plan_relinks`,
`dashboard/src/ccsync_dashboard/notices.py` (busy/slow-write block), `app.py`'s 500 handler,
`broll/web/app/routes_api.py::_insert_object`, `broll/indexer/broll_index/migrate.py`.

Tests run:
- `companion/.venv/Scripts/python.exe -m pytest tests/test_broll_standins.py tests/test_proxy_relink_standins.py tests/test_broll_insert_tiers.py -q` -> 67 passed
- `companion/.venv/Scripts/python.exe -m pytest tests/test_broll_server.py -q -k insert_object` -> 12 passed
- `companion/.venv/Scripts/python.exe -m pytest tests/test_proxy_relink_standins.py -q -k never_refreshed` -> 1 passed
- mutation check on a SCRATCH copy of `proxy_relink.py` (guard `not is_standin()` removed from the
  refresh condition): the repo code answers `ops == []`, the mutant answers one `refresh` op, so
  `test_a_stand_in_is_never_refreshed_against_its_own_file` does bite. (Note for whoever repeats
  this: `PYTHONPATH=<scratch>` does NOT displace the companion venv's installed package when pytest
  runs - a probe script placed IN the scratch dir does.)
- ad-hoc snippets against the companion venv for findings tests-2 and tests-4 (output quoted below).

## Findings

### tests-1 - twenty media-job tests skip silently on every CI and release runner
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/tests/test_jobs_media.py:37-42` (and its 19 `@needs_ffmpeg` uses + the `clips`
  fixture's `pytest.skip` at line 67); `.github/workflows/ci.yml:399-401`,
  `.github/workflows/release-windows.yml`, `.github/workflows/release-macos.yml`
- What: `needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")))`
  has no `CCSYNC_REQUIRE_*` escape hatch, unlike the rclone fixture in `companion/tests/conftest.py:514-535`
  which exists precisely because "pytest exits 0 when tests SKIP, so a missing rclone would silently
  drop 24 lane-direction tests from a release". ffmpeg is installed by exactly one CI step, and that
  step is `if:` scoped to the **broll/indexer** job on Linux (`ci.yml:399`); neither companion job
  (windows-latest, macos-latest) nor either release workflow installs it.
- Failure scenario: `jobs_media.py`'s three Timeline Cards recipes must "reproduce `library_engine.py`'s
  ffmpeg argv VERBATIM" (CLAUDE.md) and adopt `proxy_gen`'s `.partial`/atomic-rename rule. Break the
  argv or the rename and every companion CI run and both release runners stay green: the 20 tests that
  would have caught it report as skips in a suite whose exit code is 0, and the build is published.
- Evidence: `grep -rn "ffmpeg" .github/workflows/*.yml` returns only `ci.yml:383-401` (the indexer
  step); `grep -c needs_ffmpeg companion/tests/test_jobs_media.py` -> 20; `conftest.py:530` is the
  only `CCSYNC_REQUIRE_RCLONE`-style gate in the tree.
- Ledger: new (the rclone half is 3c7cf8e / 214869b; the ffmpeg half has never been raised)
- Suggested fix: give the ffmpeg gate the rclone treatment - a session fixture that `pytest.fail`s
  when `CCSYNC_REQUIRE_FFMPEG=1`, set by `release.ps1`/`release_macos.sh`, plus an ffmpeg install step
  in the companion CI jobs (or accept the skip explicitly and say so in the workflow).

### tests-2 - the malformed-`insert` test asserts three fields and misses the one that changes the plan
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/tests/test_broll_server.py:1160-1177`
  (`test_a_malformed_insert_object_is_ignored_never_fatal`), against
  `companion/src/ccsync_companion/broll_server.py:765-766` (`derived["from_page"] = True`) and
  `:893-899` (the `weight is None and from_page and edit_proxy_rel` rule)
- What: `derive_insert_paths` sets `from_page = True` for **any** dict, before a single field is
  validated. The test feeds it exactly the objects that fail validation (`{"preview_rel":
  "../../etc/passwd"}`, `{"geometry": "1920x1080"}`, ...), asserts that `preview_rel`,
  `edit_proxy_rel`, `original_is_edit_weight` and `geometry` all fall back to the stem convention -
  and never asserts `from_page`, nor the plan that comes out. Its sibling
  (`test_the_stem_conventions_guess_is_not_evidence_of_weight`,
  `companion/tests/test_broll_insert_tiers.py:85-90`) pins the rule "a stem-convention guess is not
  evidence of weight" only for `insert=None`, so the half of the rule that a real page exercises is
  untested.
- Failure scenario: a page or a proxying layer that sends a truncated/garbled `insert` object (an
  object with `share`/`original_rel` but no tier fields is enough) makes the companion answer
  `fetch_standin` for a clip nobody ever judged heavier than edit weight: it downloads the 1080p
  preview, writes it **at the original's canonical path**, ledgers a stand-in and imports the lie into
  Resolve, plus an upgrade owed against a `Proxy/<stem>.mov` the server never made. The whole point of
  `from_page` is "the dashboard LOOKED"; a malformed object has looked at nothing.
- Evidence (companion venv):
  `derive_insert_paths({'share':'broll','original_rel':'Creators_Club/x/clip.mov'}, 'Creators_Club/x/clip.mov')`
  -> `{... 'edit_proxy_rel': 'Creators_Club/x/Proxy/clip.mov', 'original_is_edit_weight': None,
  'from_page': True}`; `plan_insert(False, False, that, wired=False)` ->
  `{'action': 'fetch_standin', 'fetch_rel': 'Creators_Club/x/Proxy/clip.mp4', 'upgrade_rel':
  'Creators_Club/x/Proxy/clip.mov', 'why': 'the original is heavier than edit weight'}`. The same
  result for the test's own `{'preview_rel': '../../etc/passwd'}` input.
- Ledger: new (proxy tiers phase 3 / CR-281)
- Suggested fix: set `from_page` only when the object actually carried a tier field the code accepted
  (e.g. `"preview_rel" in insert or "edit_proxy_rel" in insert or isinstance(weight, bool)`), and add
  `assert tiers["from_page"] is False` plus a `plan_insert` assertion to the parametrised test.

### tests-3 - a phase-2 test still pins "the insert object changes nothing", after phase 3 shipped
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/tests/test_broll_server.py:1177-1193`
  (`test_an_insert_object_in_the_body_changes_nothing_about_the_insert`), fixture `_mode_gate_body`
  at `:1029-1036`
- What: the test asserts the worker call is identical with and without the `insert` object, with the
  docstring "Phase 3 is gated on the phase 0 spike: today the object is parsed, derived and logged".
  Phase 3 shipped on 2026-09-17 and the object now decides which file is fetched and imported. The
  test still passes only because `_mode_gate_body` writes the clip to disk, so both runs take the
  `import_original` row of the table - i.e. it is vacuous for the one thing it is named after.
- Failure scenario: no live defect. The hazard is the next change: this test goes red the moment the
  object is allowed to matter for a present original (e.g. the stand-in-already-placed row), and its
  docstring invites "fix" by narrowing phase 3 rather than by deleting a stale pin.
- Evidence: `pytest tests/test_broll_server.py -k insert_object` -> 12 passed; `_mode_gate_body`
  writes `clip.mov` before the call, and `plan_insert(True, False, ...)` is `import_original` for both
  bodies.
- Ledger: new
- Suggested fix: delete it or rewrite it as "an absent original + an insert object changes the fetch",
  and drop the phase-gating docstring.

### tests-4 - the "a write that cannot land is not an exception" test monkeypatches away the thing that raises
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/tests/test_broll_standins.py:118-128`, against
  `companion/src/ccsync_companion/broll_standins.py:180-196` (`_persist_locked`) and `:398-400`
  (module-level `record`)
- What: the test replaces `StandinLedger._persist_locked` with `lambda self: False`, which is the
  exact function whose failure it claims to cover, so it proves only that a `False` return is
  tolerated. `_persist_locked` catches `OSError` only, and `json.dumps(payload)` sits inside that
  try; `record()` has no try/except of its own, and the module-level `record()` wrapper is the ONE
  public wrapper in the file without the `try/except -> log.debug` that `is_standin`, `is_stale`,
  `all`, `set_upgrade` and `pending_upgrades` all have. The module docstring says "no method here
  raises".
- Failure scenario: any value in `geometry` that json cannot encode makes `broll_standins.record()`
  raise inside the insert path, i.e. the ledger entry that must be written BEFORE the import is lost
  and (depending on the caller's own guard) the insert fails. The geometry reaching it today is
  JSON-parsed from the page's body, so this is a latent gap rather than a live break - which is
  exactly why the test should be the thing that holds the line.
- Evidence (companion venv): `bs.record(path, geometry={'fps': object()})` ->
  `RAISED TypeError Object of type object is not JSON serializable`, and the ledger file was never
  created.
- Ledger: new
- Suggested fix: make the test raise a real `OSError` from `Path.write_text`/`os.replace` (and a
  `TypeError` from `json.dumps`) instead of stubbing `_persist_locked`; wrap the module-level
  `record()` like its five siblings.

### tests-5 - the "every new kind is in the registry" test is a hand-written list, so it cannot fail for a new kind
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/tests/test_alerts.py:1312-1328`
- What: the test loops over sixteen kind names typed into the test file and asserts each is in
  `alerts.ALERT_KINDS`. Nothing derives the expected set from the code, so a kind added tomorrow and
  forgotten is invisible to it - the test only proves that sixteen kinds somebody remembered to add
  twice are present. Its own docstring states the rule it cannot enforce ("a kind that is only a
  function is a kind nobody is told about"). The week's two new notice kinds (`notices.DB_BUSY_KIND`,
  `notices.SLOW_WRITE_KIND`, 2026-09-17) have writers and no registry row; that follows the
  `server_error` precedent so it is not itself a defect, but nothing in the suite would have said so
  either way.
- Failure scenario: a builder adds a check function and a notice writer, forgets the registry row;
  the checks panel renders `[ NOT CHECKED ]` for it (or it never reaches the weekly report and the
  alerts sink), and the suite is green.
- Evidence: read the test; `grep -rn "db_busy\|slow_write" dashboard/src` shows writers in
  `app.py:1350-1364`, `api.py:9405`, `collector.py:497` and no `ALERT_KINDS` entry.
- Ledger: new
- Suggested fix: derive the expectation - assert every `kind=` literal passed to `db.notice(...)`
  under `src/` is either in `ALERT_KINDS` or in an explicit, commented allow-list (`server_error`,
  `db_busy`, `slow_write`), which turns "adding a check is adding a registry row" into a test.

### tests-6 - three copies of the b-roll schema and migrations, no test that they are the same
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/migrations/`, `broll/web/migrations/`, `broll/indexer/broll_index/migrations/`;
  `broll/schema.sql` vs `broll/web/schema.sql`; `broll/web/tests/test_migration.py:284-290`
- What: the twelve migration scripts and `schema.sql` exist in three (schema: two) byte-identical
  copies, each suite testing only its own copy. No test compares them. In the same commit the web
  suite's version assertion was relaxed from the literal `== 11` to `== CURRENT_SCHEMA_VERSION`,
  removing that side's only anchor - the indexer side kept its literal deliberately (`== LATEST_VERSION
  == 12`, with a comment saying why), so the two halves now disagree about how they guard the number.
- Failure scenario: a fix applied to one copy of `011_ingest_batches.sql` or `012_geometry.sql` (or a
  column added to one `schema.sql`) leaves the indexer writing a database the web app migrates
  differently; both suites stay green because each reads its own copy.
- Evidence: `diff -r broll/migrations broll/web/migrations` -> identical today;
  `diff broll/schema.sql broll/web/schema.sql` -> identical today; no `filecmp`/hash comparison
  anywhere in `broll/*/tests`.
- Ledger: new
- Suggested fix: one test (either suite) that hashes each migration file and `schema.sql` in all
  copies and asserts equality, naming the file that drifted.

## Coverage note
Read as diffs/names rather than line by line: `dashboard/tests/test_cards_pool.py` (469 new lines -
the docstrings describe the right scenarios and the seams look real, but I did not verify that the
fake engine exercises the refuse-not-evict thread accounting), `test_fleet_grid_declutter_2026_09_11.py`,
`test_admin_assignments.py`, `test_packages.py`, `test_health*.py`, `test_protection.py`,
`test_release_feed.py`, `tools/tests/test_publish_feed.py`, `companion/tests/test_rclone_lane.py`
(+274, names only), `test_watcher_broll_archive.py`, `test_broll_ingest*.py`, `test_ffmpeg_tools.py`
(+289, the indexer-parity loader only), `installer/tests/Test-BinDirLeftovers.ps1`. I ran no dashboard,
broll/web or indexer test file (time-box; the ones I would have run are the migration ones).
The "is there a THIRD release-runner platform break" question is answered only for external binaries
(tests-1) and the `broll/indexer` loaders; I did not audit the ~40 older companion test files that
embed `X:\` literals for the `os.path.abspath`-on-POSIX shape 214869b fixed - a sweep for
`r"[A-Z]:\\"` feeding a function that calls `os.path.abspath`/`Path.resolve` is still owed, and it is
the cheapest way to pre-empt the next red macOS release run.
What the suites do not cover at all, tree-wide: nothing measures whether a test fails without its fix
(no mutation gate), and `run_all_tests.ps1`'s exit code counts failed SUITES, so a suite that skips
its way to zero (tests-1) is indistinguishable from one that passed.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/broll_server.py:765`: `from_page = True` for any dict, before
  validation - the behaviour behind tests-2, comp-broll-tiers' to report.
- `companion/src/ccsync_companion/broll_standins.py:398`: module-level `record()` is the only public
  wrapper in the file with no try/except, and it can raise `TypeError` (tests-4).
- `dashboard/src/ccsync_dashboard/notices.py:1115-1127`: `_seen_before` takes "the first digit token
  of the body" as the count, so any future body whose first token contains a digit silently resets
  the counter to 1 - dash-collector-alerts'.
