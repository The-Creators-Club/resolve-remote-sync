# server-tools - server/*.py, tools/* (minus the four feed tools), bench/

Files read (with approximate coverage):
- `git diff` over the whole territory (16 files) read hunk by hunk: `server/check_health.py`,
  `server/install_dashboard_app.py`, `server/publish_db.py`, `server/tests/test_broll_drain.py`,
  `server/tests/test_bug_hunt_2026_09_11b_server_tools.py`, `tools/gen_notices.py`,
  `tools/release.ps1`, `tools/release_macos.sh`, `tools/tests/test_gen_notices.py`,
  `tools/tests/test_release_scripts.py`, `bench/ccbench/runners/{_rclone_common,base,iperf3,syncthing}.py` (100%).
- New file `server/tests/test_bug_hunt_2026_09_18_webapps_tools.py` (100%).
- `server/publish_db.py` main()/do_apply_drain/read_live_counts/shrink_refusals (~60% of the file),
  `server/install_dashboard_app.py` docs-policy block + `_stage_docs_tree` + `git_out` (~10%),
  `tools/gen_notices.py` in full, `tools/build_dashboard_bundle.py` docs block,
  `bench/ccbench/runners/rclone_smb.py`, `bench/ccbench/selftest.py` (subprocess sites only).
- Read as the other end of a wire, not reported on: `broll/web/app/db.py`,
  `music/web/musicweb/db.py` (ensure_schema / `_check_swapped` / `con()`),
  `companion/tests/conftest.py::require_ffmpeg_or_skip`, `.github/workflows/release-macos.yml`,
  `.github/workflows/release-windows.yml`.

Tests run:
- `server$ ../dashboard/.venv/Scripts/python.exe -m pytest tests/test_broll_drain.py tests/test_bug_hunt_2026_09_11b_server_tools.py tests/test_bug_hunt_2026_09_18_webapps_tools.py -q` -> 42 passed
- `tools$ ../dashboard/.venv/Scripts/python.exe -m pytest tests -q` -> 342 passed
- ad-hoc: `gen_notices.read_lock(dashboard/deploy/requirements.lock)` -> 52 rows, psycopg2-binary 2.9.12 present

## Findings

### server-tools-1 - release_macos.sh silently cancels a CCSYNC_REQUIRE_FFMPEG the caller (and CI) set
- Severity: medium
- Confidence: CONFIRMED
- Where: `tools/release_macos.sh:509-535` (the `REQUIRE_FFMPEG=""` branch and the
  `CCSYNC_REQUIRE_FFMPEG="$REQUIRE_FFMPEG"` prefix on the pytest line), against
  `.github/workflows/release-macos.yml:145-147` (`CCSYNC_REQUIRE_FFMPEG: "1"` on the build step)
  and `tools/release.ps1:647-652` (the Windows half of the same fix)
- What: the Mac half of tests-1 computes `REQUIRE_FFMPEG` purely from `have_cmd ffmpeg` and then
  EXPORTS it unconditionally in front of pytest. When ffmpeg is not on PATH it exports the empty
  string, which overrides any value the environment already carried. The Windows half of the same
  fix only ever *sets* the variable when it finds ffmpeg and never clears it, so an inherited `1`
  survives there. Two ends of one fix, two contracts.
- Failure scenario: the macOS release runner's `brew install ffmpeg` step succeeds but the binary
  is not resolvable in the build step's shell (a keg-only/arch/PATH case, a re-ordered or removed
  install step, or a maintainer running `CCSYNC_REQUIRE_FFMPEG=1 ./tools/release_macos.sh` by
  hand to force the coverage). `conftest.require_ffmpeg_or_skip` sees an empty value, the twenty
  media-job tests SKIP, pytest exits 0, and the macOS companion is published without the only
  coverage that holds `jobs_media.py`'s three Timeline Cards recipes to `library_engine.py`'s
  ffmpeg argv - which is precisely the hole tests-1 was written to close. The run prints
  "no ffmpeg on PATH: the media-job tests will SKIP and this build is cut without them",
  i.e. the guard reports its own defeat as normal.
- Evidence: shell semantics of `VAR=value cmd` are an unconditional per-command assignment;
  `companion/tests/conftest.py:554` tests `os.environ.get("CCSYNC_REQUIRE_FFMPEG") == "1"`, so an
  empty string is "not required". `release-macos.yml:147` sets it to `"1"` on the very step that
  invokes this script. `tools/tests/test_release_scripts.py::test_the_mac_script_does_not_fail_without_ffmpeg`
  asserts only that nothing calls `fail` - it cannot see the override.
- Ledger: new (tests-1's Mac half does not honour what tests-1's CI half sets)
- Suggested fix: let the caller win, e.g. `REQUIRE_FFMPEG="${CCSYNC_REQUIRE_FFMPEG:-}"` and only
  set it to `1` when it is empty and `have_cmd ffmpeg`; when it arrives as `1` with no ffmpeg on
  PATH, say so and let the suite fail as the runner asked.

### server-tools-2 - publish_db's "older schema than the live one" refusal is false for `--which music`
- Severity: medium
- Confidence: CONFIRMED
- Where: `server/publish_db.py:328-351` (`schema_refusal`, the `source_version < live_version`
  branch) and `server/publish_db.py:795-805`; the other end is
  `music/web/musicweb/db.py:238-290` (`_check_swapped` -> `invalidate()` -> `con()` re-running
  `ensure_schema`)
- What: the new broll-2 refusal was reasoned from b-roll's mount, where `ensure_schema` runs once
  at mount time (`broll/web/app/main.py:34`, `dashboard/.../broll.py:610`) and nothing re-runs it
  after a rename-swap. Music is not built that way: `db.con()` calls `_check_swapped()` on every
  connection, a replaced inode calls `invalidate()`, which clears `_schema_ready`, and the next
  `con()` re-runs `ensure_schema` - which walks migrations by PREDICATE, not by `user_version`.
  The refusal nevertheless fires for `--which music` with b-roll's sentence.
- Failure scenario: an operator publishes a music index built from a slightly older checkout
  (`CURRENT_SCHEMA_VERSION` 3) onto a container that has stepped its own file to 4. The publish is
  REFUSED with "ensure_schema runs at mount time, so a running container never steps a file
  dropped under it: every ingest push and fleet checkpoint would 500 ... until somebody restarts
  it" - none of which is true of `/music`. The stated remedy (restart the container) is not needed,
  and the operator is pushed to `--allow-schema-skew`, a flag that also disables the direction that
  IS real (source newer than live, which `musicweb/db.py:124-128` makes fatal).
- Evidence: `music/web/musicweb/db.py:238-263` (`_check_swapped`, MUSIC-10/music-2) and
  `:272-290` (`con()` re-running `init()` under `_schema_lock` when `_schema_ready` is false);
  `_MIGRATIONS` at `:56-63` carries an "already applied" predicate per step precisely so a
  recorded version need not be trusted. `broll/web/app/db.py` has no inode/generation check
  (`grep -n "st_ino|invalidate|swapped" broll/web/app/db.py` -> nothing).
- Ledger: new (CR-286 / broll-2 does not fix broll-2 for the music half)
- Suggested fix: make `schema_refusal` take `which` into account - keep both directions for
  `broll`, and for `music` refuse only `source_version > live_version` (the direction its own
  `ensure_schema` makes fatal), or give each SPEC a "re-steps itself after a swap" flag.

### server-tools-3 - gen_notices still decodes pip-licenses by the console codec, in the very pass that fixed five other sites
- Severity: medium
- Confidence: CONFIRMED
- Where: `tools/gen_notices.py:160`, `:163-166`, `:170` (`run_piplicenses`) and
  `:196-198` (`collect`'s `except (RuntimeError, json.JSONDecodeError)`)
- What: server-tools-3/-4 of the fix pass added `encoding="utf-8"` to every `subprocess.run` in
  `server/check_health.py` and the four bench runners, but the three calls inside
  `tools/gen_notices.py` - a file the same pass edited heavily - were left decoding with
  `locale.getpreferredencoding(False)`. That is cp1252 on this rig, whose undefined bytes
  0x81/0x8D/0x8F/0x90/0x9D are ordinary UTF-8 continuation bytes, so any package metadata (author,
  URL, licence string; `--with-license-file` pulls whole licence TEXTS through this pipe) holding a
  CJK character raises `UnicodeDecodeError`. `UnicodeDecodeError` is a `ValueError`, not a
  `RuntimeError` and not a `json.JSONDecodeError`, so `collect()`'s except does not catch it and it
  escapes `main()`.
- Failure scenario: a dependency whose metadata contains a CJK name (or any character whose UTF-8
  encoding includes 0x8D - the fleet's own `母` is E6 AF 8D) enters any scanned venv.
  `python tools/gen_notices.py` dies with a traceback instead of regenerating
  `docs/legal/THIRD_PARTY_NOTICES.md`, and the legal document whose purpose is finding copyleft
  before a build is conveyed to a customer cannot be produced. On a Traditional-Chinese Windows
  install (cp950) the same happens for ordinary accented Latin text.
- Evidence: read `run_piplicenses` and `collect`; `python -c "import locale;
  print(locale.getpreferredencoding(False))"` -> `cp1252`. `subprocess.run(text=True)` decodes
  strictly. The generated notices file shows no mojibake today
  (`grep -c` for the cp1252 mojibake markers -> 0) only because no scanned package has a
  non-ASCII field - the exposure is unguarded, not absent.
- Ledger: new (server-tools-4 does not fix the same class in `tools/`)
- Suggested fix: add `encoding="utf-8", errors="replace"` to all three `subprocess.run` calls in
  `run_piplicenses`, and widen `collect`'s except to `ValueError` (which covers both
  `json.JSONDecodeError` and a decode failure).

### server-tools-4 - the new "every bench subprocess read declares utf8" test hand-lists four of the five files
- Severity: low
- Confidence: CONFIRMED
- Where: `server/tests/test_bug_hunt_2026_09_18_webapps_tools.py:135-148` (the `parametrize` list)
  and the file it omits, `bench/ccbench/runners/rclone_smb.py:43-46`
- What: the regression test for server-tools-4 is named "every bench subprocess read declares
  utf8" but enumerates four paths by hand. `bench/ccbench/runners/rclone_smb.py` also calls
  `subprocess.run(..., capture_output=True, text=True)` with no encoding and is not in the list,
  so the test is green while a fifth bench subprocess read still decodes by locale. CLAUDE.md
  already records this exact pattern for `run_all_tests.ps1` ("a hand-written list here was wrong
  three times"); a new file added to `bench/ccbench/runners/` will not be covered either.
- Failure scenario: `rclone obscure` writes a diagnostic containing a non-cp1252 byte; the decode
  raises inside `_obscure`, whose bare `except Exception: pass` then returns the RAW password as
  the "obscured" value, which goes straight into the remote spec - while the docstring above it
  promises the credential only ever leaves through `guard.redact()`.
- Evidence: `grep -rn "capture_output=True" bench/ | sed | sort -u` lists five files; the
  parametrize list names four. The test passes today.
- Ledger: new
- Suggested fix: walk `bench/ccbench/runners/*.py` with a glob in the test instead of a literal
  list, and add the encoding to `rclone_smb.py::_obscure`.

### server-tools-5 - bind-mode deploy now ships a doc set the image build and the OTA bundle both refuse, and the policy comment now says the opposite of the code
- Severity: low
- Confidence: CONFIRMED
- Where: `server/install_dashboard_app.py:4466-4487` (the new split refusal) against
  `server/install_dashboard_app.py:301-307` (the comment that still explains the old rule) and
  `tools/build_dashboard_bundle.py:118-128` (`FILES` = `published_sources(required_only=True)`,
  i.e. EDITOR_SETUP.md is REFUSED in a bundle)
- What: server-tools-5 correctly stopped an absent guide from withholding `docs/legal/`, but it
  also demoted EDITOR_SETUP.md from required to best-effort for BIND MODE only. The image's
  Dockerfile `COPY` of an absent file still fails the build and `build_dashboard_bundle.FILES`
  still refuses the checkout, so the three routes that the code's own comments insist "cannot
  disagree about what leaves this repository" now disagree. The comment at :301-307 still reads
  "the bind-mode deploy refuses the same absence rather than shipping a thinner /help without
  saying so", which is now exactly what it does.
- Failure scenario: a hand-trimmed bind-mode checkout deploys green, `/help` offers no editor
  guide, and the only trace is one stderr line early in a long deploy. The same checkout cannot
  produce an image or an OTA bundle at all, so the two deployment modes of one release disagree
  about whether the tree is publishable.
- Evidence: read all three sites; `tools/tests` and `server/tests` both pass, and neither pins the
  three-route agreement for the required set.
- Ledger: new (CR-286 / server-tools-5 opens a neighbour)
- Suggested fix: update the :301-307 comment to state the new split, and either raise a `notices`
  row / non-zero deploy summary line for a missing required doc, or make the bundle/image halves
  best-effort for it too so the three routes agree again.

### server-tools-6 - the new refusal and the new exit code exist in no runbook
- Severity: low
- Confidence: CONFIRMED
- Where: `server/publish_db.py:701-703` (`--allow-schema-skew`) and `:668,939`
  (`RC_DRAIN_UNMERGED = 3`), against `docs/BACKUP_RESTORE.md:460-500` and
  `docs/BACKCATALOGUE_INGEST.md:376-390`
- What: a publish can now stop with a new FAILED message naming a flag that appears nowhere in the
  procedure the operator is following, and can now exit 3 on a path that previously exited 0. The
  two documents that are the runbook for `publish_db.py` were not updated in the same change.
- Failure scenario: mid back-catalogue ingest the operator hits "FAILED: the index you are
  publishing is schema v11 and the live one is v12 ... Pass --allow-schema-skew if you know what
  you are doing", opens BACKUP_RESTORE.md, and finds neither the flag nor the condition. Separately,
  a wrapper that treats any non-zero as "nothing was published" now mis-reads exit 3, whose whole
  point is that the swap DID happen.
- Evidence: `grep -rn "allow-schema-skew|RC_DRAIN_UNMERGED" docs/` finds nothing outside the hunt
  directories; no caller in the repo inspects `publish_db`'s exit code, so the new code is
  currently only a signal to a human.
- Ledger: new
- Suggested fix: one paragraph in `docs/BACKUP_RESTORE.md` section 6 listing the exit codes
  (0 published, 1 nothing sent, 3 published but drain unmerged) and the schema-skew refusal with
  its two directions.

## Coverage note
- `tools/ship.ps1`, `tools/ship_gates.ps1`, `tools/run_all_tests.ps1`, `tools/check_deploy_drift.ps1`,
  `tools/publish_package.py`, `tools/check_licenses.py`, `tools/build_dashboard_bundle.py`,
  `tools/jobs.py`, `tools/android/*` and `tools/load_secrets.ps1` are unchanged by today's pass and
  I only spot-read them where a changed file pointed at them; none got a full read.
- `server/install_dashboard_app.py` is ~4,600 lines and I read roughly a tenth of it (the docs
  policy, the git helper, the swap-script builder used by publish_db). The deploy's
  stage-verify-swap core was not re-read.
- I did not run the `server/` suite from Git Bash in full (18 tests that stub `sudo`/`chown` behave
  differently by launcher, and the owner rule is that the full gate runs once, centrally); I ran the
  three server test files my territory touches and they pass.
- No suite anywhere exercises `publish_db.main()` end to end against a real container, so the
  schema-skew branch is covered only by the unit test of `schema_refusal` - which pins b-roll's
  reasoning for both `which` values (finding server-tools-2).
- `bench/` has no pytest suite at all; every bench finding here is by reading.
- Checked and found CLEAN: `read_lock` against the real `dashboard/deploy/requirements.lock`
  (52 rows, hash continuations and `# via` lines handled); the container-lock rows do reach the
  attention table and `docs/legal/THIRD_PARTY_NOTICES.md` WAS regenerated with the psycopg2-binary
  2.9.12 row, so server-tools-1 of the fix pass is complete; `CCSYNC_REQUIRE_FFMPEG` exists on both
  ends (release scripts and `companion/tests/conftest.py`); `live.pop("__user_version")` happens
  before `shrink_refusals`, so the new key cannot be read as a table count; `read_live_counts` has
  no second caller; `RC_DRAIN_UNMERGED` has no scripted consumer that would mis-handle it.

## OUT OF TERRITORY
- `tools/publish_latest.py:82`: `subprocess.run(cmd, capture_output=True, text=True, **kw)` still decodes git output by the console codec - the same class as e050413's `git_out` fix, on a rig whose commit subjects carry Chinese clip names (dash-release-jobs).
- `.github/workflows/release-macos.yml:137-143`: the `brew install ffmpeg` step is what makes server-tools-1 reachable or not, and it does not re-verify that ffmpeg is on PATH afterwards (dash-mounts-ui).
