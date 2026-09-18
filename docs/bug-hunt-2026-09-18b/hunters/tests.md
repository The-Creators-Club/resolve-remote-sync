# tests - test QUALITY across the whole tree: do today's regression tests fail without the fix, do they test the scenario their ledger section names, do they mock away the thing that breaks

Files read (with approximate coverage):
- All thirteen new `test_bug_hunt_2026_09_18_*.py` files, in full (5,506 lines):
  `companion/tests/test_bug_hunt_2026_09_18_companion.py`,
  `..._companion_core.py`, `..._companion_media.py`,
  `dashboard/tests/test_bug_hunt_2026_09_18_dashboard.py`, `..._dashboard_lows.py`,
  `..._dashboard_mediums.py`,
  `broll/web/tests/`, `broll/indexer/tests/`, `music/web/tests/`,
  `music/indexer/tests/`, `onboarding/tests/`, `server/tests/`, `ytdl/web/tests/`
  `test_bug_hunt_2026_09_18_webapps_tools.py`.
- `git diff -- '*tests*'` in full for the 44 edited test files (every removed
  line reviewed; `dashboard/tests/test_cards_pool.py` read hunk by hunk).
- Cross-checks in the sources the tests pin:
  `dashboard/src/ccsync_dashboard/dashboard_update.py` (apply, ~1420-1445),
  `companion/src/ccsync_companion/sync/rclone_lane.py::_move_out_of_trash`,
  `companion/src/ccsync_companion/proxy_relink.py` (plat handling),
  `companion/src/ccsync_companion/app.py::_note_proxy_attach` at HEAD,
  `.github/workflows/ci.yml`, `release-windows.yml`, `release-macos.yml`,
  `tools/release.ps1`, `docs/bug-hunt-2026-09-18/hunters/regression.md`.

Tests run:
`cd companion; .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_18_companion.py tests/test_bug_hunt_2026_09_18_companion_core.py tests/test_bug_hunt_2026_09_18_companion_media.py -q` -> 94 passed in 1.67s.

Overall the pass is unusually good on this lens: the great majority of the new
tests drive the real seam, feed the producer's real payload shape, and carry a
named guard test for the neighbouring case. `regression-6`'s two `or True`
assertions were both really deleted (verified: `grep -rn "assert .* or True"`
over the tree now returns nothing but explanatory comments), the `needs_ffmpeg`
bare skipif really was replaced by `require_ffmpeg_or_skip`, and the two
CR-90 literals in `test_a_mac_spelling_of_one_name_is_one_key` are genuinely
NFD and NFC (checked byte by byte - a decomposed `̌` is present). The
findings below are the residue.

## Findings

### tests-1 - the only test for dash-release-jobs-5 re-implements the fixed expression and cannot fail on the unfixed code
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_mediums.py:485-501`
  (the fix it claims to pin: `dashboard/src/ccsync_dashboard/dashboard_update.py:1423-1436`)
- What: `test_reapplying_the_running_version_keeps_the_rollback_target` never
  calls `dashboard_update.apply`, nor any helper of it. It writes a
  `current.json`, reads it back, and then evaluates the corrected expression
  **in the test body** (`carried = previous if previous and previous != version
  else str(held.get("previous") or "")`), asserting on its own arithmetic. The
  only product functions it touches are `_write_json` / `_read_json`, which the
  fix did not change. Reverting the `apply` hunk to
  `previous if previous != version else ""` leaves this test green.
- Failure scenario: a later edit (or a revert, or a rebase that drops the hunk)
  puts the blanking arithmetic back in `apply`; `current.json` is written with
  `previous: ""` whenever a version is re-applied; `""` means "the image" to
  both `rollback` and `select_code_root`, so a rollback that should return to
  the previous TREE silently returns to the image instead. Nothing in the
  13-suite gate goes red.
- Evidence: read the test and the fix side by side; `grep -rn
  "dash-release-jobs-5"` shows the 2026-09-18 id cited at exactly one code site
  (`dashboard_update.py:1424`) and exactly one test site (this one) - every
  other hit is the same id reused for unrelated 2026-09-03 and 2026-09-11b
  findings in `release_feed.py`. The comment in the test itself concedes it:
  "The exact expression `apply` uses, exercised through a helper rather than a
  whole bundle".
- Ledger: "CR-285 does not fix dash-release-jobs-5" (the code fix is right; the
  regression test does not guard it).
- Suggested fix: lift the two lines into a named helper on
  `dashboard_update` (e.g. `_carry_previous(held, version)`) and have both
  `apply` and the test call it; or drive `apply` far enough with a stub bundle
  to read the `current.json` it writes.

### tests-2 - a whole section of companion_core is pasted twice, so one test is silently dropped at collection
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/tests/test_bug_hunt_2026_09_18_companion_core.py:847-886`
- What: the header comment `# -- comp-sync-5: the CR-90 worked example, in the
  right bytes ---` and the whole of
  `test_no_companion_source_file_carries_latin1_mojibake` appear twice, back to
  back. Python rebinds the name, so pytest collects one function, not two. The
  bodies are identical today, so nothing is lost in substance - but the file
  reports one fewer test than it contains, and the same paste in a file where
  the two copies had drifted would run only the second.
- Failure scenario: a later edit to the first copy (the one a reader finds by
  scrolling to the section header) is a silent no-op. This is the same class as
  ytdl-web-7 ("two definitions of `_column`: an edit to one is a silent no-op"),
  which this very pass fixed and wrote a test for
  (`ytdl/web/tests/...::test_the_db_module_defines_column_once`).
- Evidence: `grep -n "def test_" <file> | awk '{print $2}' | sort | uniq -d`
  over the thirteen new files returns exactly this one name; the two bodies at
  :850-865 and :871-886 are byte-identical.
- Ledger: new.
- Suggested fix: delete the second copy. Consider extending ytdl-web-7's
  one-definition scan to the test trees, where a duplicate name is invisible.

### tests-3 - the CR-283W hand-off is half-tested: the test imports the Settings window, deletes the import, and asserts nothing about it
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/tests/test_bug_hunt_2026_09_18_companion_core.py:892-910`
- What: `test_a_refresh_only_pass_is_not_nothing_to_do` is the companion-core
  half of comp-resolve-5 (CR-283W/X). It imports `settings_window`, asserts
  `_note_proxy_attach` keeps `refreshed`, then says in a comment "...and the
  Settings window says so instead of drawing nothing" and executes
  `del settings_window`. No assertion about `settings_window` is made. The
  surface the finding was about - a refresh-only pass that the Settings window
  drew as nothing - is untested.
- Failure scenario: `settings_window`'s proxy-attach block is changed to read
  only `relinked`/`failed` again; `_proxy_attach["refreshed"]` is stored, the
  test stays green, and the window goes back to drawing "nothing to do" after a
  pass that re-read forty clips.
- Evidence: read the test; `git diff -- companion/tests/test_settings_window.py`
  (+23 lines) does not add a `refreshed` case either.
- Ledger: "CR-283W does not fix comp-resolve-5" (the Settings-window half).
- Suggested fix: assert on the string the Settings window renders for a summary
  carrying `refreshed` only, through whichever `settings_window` helper formats
  it, and drop the `del`.

### tests-4 - nine of the new regression tests pin their fix by grepping the SOURCE text, so a reformat re-opens the bug green (or reds the suite for no defect)
- Severity: low
- Confidence: CONFIRMED
- Where (the nine):
  `companion/tests/..._companion_core.py:488-491` (`"os.replace(tmp, path)" in body`),
  `dashboard/tests/..._dashboard_mediums.py:504-516` (`inspect.getsource(apply)`),
  `..._dashboard_mediums.py:378-388` (`"lane.reported" in text and "unknown" in text`),
  `dashboard/tests/test_cards_pool.py` (new, `"await caches.keys()) await caches.delete(k)" not in body`),
  `music/indexer/tests/...:44-59` (`make_proxies.py` source slice),
  `server/tests/...:60-72` (`read_live_counts` body, `body.count("container_exec") == 1`),
  `server/tests/...:124-137` (`check_health.py` argv slice),
  `server/tests/...:140-155` (four `bench/` files split on `capture_output=True`),
  `server/tests/...:156-164` (`remove_listing`'s `except (` tuple).
- What: each asserts that a particular substring is present in, or absent from,
  a slice of a source file. They all do fail on `git show HEAD:<source>` (so
  they are not vacuous), but they pin SPELLING, not behaviour. `assert "unknown"
  in text` over a whole Jinja partial is the weakest of them: `unknown` occurs
  in that template for reasons unrelated to lanes.
- Failure scenario: two ways round. (a) `os.replace(tmp, path)` is rewritten as
  `os.replace(str(tmp), str(path))` or moved into a shared `atomic_write`
  helper - behaviour unchanged and correct, test red, and the next hand
  "fixes" it by deleting the assertion. (b) the sw.js sweep is reformatted to
  `for (const k of await caches.keys()) { await caches.delete(k); }` - byte
  string absent, test green, the dashboard PWA's own precache and `cards-media`
  are wiped again exactly as dash-cards-4 describes.
- Evidence: read each; none of the nine calls the function it is about. Two of
  them (`_sql_only` in `broll/indexer/...:tests-6`, and
  `test_the_dry_run_parks_an_undecodable_file_as_the_run_does`) say in their own
  docstrings that this was the deliberate choice, which is fair for a schema
  comparison and for a branch that needs a database, a config and argv - the
  other seven have a callable seam available.
- Ledger: new.
- Suggested fix: where the function is callable with a seam (the sw.js sweep,
  `read_live_counts`, `remux`/`check_health`'s subprocess call, `write_history`),
  drive it and assert on the effect; keep the source scan only where nothing
  can be driven, and there scan for the DEFECT's shape rather than the FIX's.

### tests-5 - comp-sync-3's regression test proves nothing on Windows, and the fallback that still has the bug is untested everywhere
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/tests/test_bug_hunt_2026_09_18_companion_core.py:750-783`;
  the code `companion/src/ccsync_companion/sync/rclone_lane.py:4256-4290`
- What: two things. (1) `test_a_destination_that_appeared_mid_move_is_a_refusal_not_a_loss`
  puts its verdict assertions behind `if os_mod.name != "nt":`, and the one
  assertion outside that guard (`dest.read_bytes() == b"the fresh download"`)
  is true on Windows whether or not the fix is present, because Windows
  `os.rename` already refuses an existing destination. So on the base rig and
  on the Windows CI job this test cannot fail; only the macOS job exercises the
  fix. That is defensible (the bug is POSIX-only) but it is worth knowing that
  the suite Alex runs before a ship does not cover it at all. (2) The fix's own
  fallback - `except OSError:` when `os.link` is refused, then plain
  `os.rename` - is the ORIGINAL defect, and it is the branch a Mac editor whose
  `local_root` is an SMB mount or an exFAT drive takes every time. No test
  reaches it: the test's `os.link` always succeeds under `tmp_path`.
- Failure scenario: a Mac editor syncing to an external exFAT drive; lane B
  follows a hand move, `os.link` fails with EPERM/EXDEV, the code falls through
  to `os.rename`, and the fresh copy that landed in the window is destroyed by
  the trashed one - the exact loss comp-sync-3 was written about, on the exact
  platform it was written for.
- Evidence: read both. The code comment states the fallback keeps the race
  ("the race is back, and that is still better than leaving the file in the
  trash for ever") - a deliberate trade, but one no test records, so the next
  hand cannot tell it from an oversight.
- Ledger: "CR-283 does not fix comp-sync-3" (for a filesystem without hard
  links).
- Suggested fix: add a case that monkeypatches `os.link` to raise `OSError` and
  asserts the documented, weaker outcome, so the trade is pinned; and drop the
  `if os_mod.name != "nt"` guard in favour of asserting the outcome that is
  true on both (`dest` untouched, and on POSIX `src` still in the trash).

### tests-6 - two tests assert only inside an `if`, so they can pass having checked nothing
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/tests/test_bug_hunt_2026_09_18_webapps_tools.py:110-127`;
  `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_mediums.py:322-332`
- What: (a) `test_a_preview_with_bytes_still_goes_live` ends
  `if r.status_code != 200: assert r.json()["detail"]["reason"] != "not_uploaded"`.
  On a 200 it asserts nothing at all; on a 500 (where `detail` is a string)
  it raises `TypeError` rather than reporting a clear failure. (b)
  `test_a_renamed_proxy_folder_is_still_refused_as_a_folder_move` asserts
  `[m.is_dir for m in moves] in ([], [False])` and then `not any(m.is_dir ...)`
  - the first is subsumed by the second, and both accept "no move detected at
  all", so the test cannot distinguish "refused as a FOLDER move, still
  detected per file" (the behaviour its docstring claims) from "detected
  nothing".
- Failure scenario: `detect_moves` stops detecting the renamed-Proxy case
  entirely - a real regression of dash-collector-alerts-3's per-file path - and
  the guard test stays green.
- Evidence: read both.
- Ledger: new.
- Suggested fix: assert the expected status explicitly in (a); in (b) assert
  the number of per-file moves as well as `is_dir is False`.

### tests-7 - the companion CI jobs install ffmpeg with continue-on-error and never set the flag tests-1 added, so the "twenty tests vanish, job green" shape survives on CI
- Severity: low
- Confidence: CONFIRMED
- Where: `.github/workflows/ci.yml:165-178` (windows job) and `:570-587`
  (macOS job); the flag exists at `companion/tests/conftest.py:551-558`
- What: CR-284K/tests-1 added `CCSYNC_REQUIRE_FFMPEG=1` to turn a silent skip
  into a hard failure, and the two RELEASE workflows set it
  (`release-windows.yml:80`, `release-macos.yml:147`). The two CI companion
  jobs install ffmpeg instead, with `continue-on-error: true`, and do not set
  the flag - the step's own comment says "the tests fall back to skipping,
  which is exactly where they were before". So a broken chocolatey/brew feed
  restores the pre-fix state on CI with no signal anywhere.
- Failure scenario: `choco install ffmpeg` fails on a Tuesday; the twenty
  media-job tests skip; `jobs_media.py`'s argv has drifted from
  `library_engine.py`'s; CI is green and the drift is only caught later, at the
  release runner, or by a Timeline Cards page that cannot read the files the
  fleet produced.
- Evidence: `grep -rn "CCSYNC_REQUIRE_FFMPEG"` - ci.yml carries the string only
  inside a comment at :416; the two release workflows set it as a real `env`.
  Publishing IS covered, which is why this is low rather than medium.
- Ledger: "CR-284K does not fix tests-1" (on CI; it does on the release
  runners).
- Suggested fix: set `CCSYNC_REQUIRE_FFMPEG: "1"` on the companion pytest steps
  in ci.yml too, and let the install step keep `continue-on-error` - a failed
  install then reds the pytest step with a sentence naming the cause, instead
  of hiding twenty tests.

## Coverage note

- I read every new test file in full and every removed line of the 44 edited
  ones, but only spot-read the added hunks of the larger edited files
  (`test_rclone_lane.py` +152, `test_alerts.py` +104, `test_publish_feed.py`
  +124, `test_cards_pool.py` +176 read in full).
- I did not attempt a mechanical "revert each hunk on a scratch copy and re-run"
  sweep across all ~150 fixes: at ~12,000 changed lines that is not a 45-minute
  job. Where I claim a test would or would not fail on `git show HEAD:<source>`
  I say which, and tests-1 is the one I traced end to end.
- Not covered by any suite, and outside what I could close here: the
  interaction between the three module-global `cards_exec._note_running` /
  `mount_status` resets in `test_bug_hunt_2026_09_18_dashboard.py` and the rest
  of the dashboard suite under `-p xdist` or a reordered run - the state is
  process-global and restored in `finally`, but the first test asserts
  `cards_exec.is_running() is False` after its client closes, which is an
  assertion about a global no other test may hold at that moment.
- The PowerShell (`installer/tests/Test-BinDirLeftovers.ps1`, +77) and shell
  (`installer/tests/test_macos_site_values.sh`, +47) additions I read but did
  not run; nothing in them looked vacuous.

## OUT OF TERRITORY

- `companion/src/ccsync_companion/sync/rclone_lane.py:4278-4284`: the
  `except OSError` fallback in `_move_out_of_trash` re-opens comp-sync-3 on any
  POSIX filesystem that refuses hard links (an SMB or exFAT `local_root` on a
  Mac). Documented as a deliberate trade in the code comment; comp-sync's call.
- `dashboard/templates/partials/fleet_grid.html`: `unknown` is used for more
  than the unreported-lane style, which is why the test that greps for it is
  weak; dash-mounts-ui may want a distinct class name.
