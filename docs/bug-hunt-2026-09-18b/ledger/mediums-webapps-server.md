# CR-301 - webapps-server mediums (server/, tools/, bench/) - FIXED in repo 2026-09-18 (2026-09-18b mediums wave)

Three confirmed mediums, all three fixed: the macOS release script cancelling
the ffmpeg gate CI sets, publish_db's false "older schema" refusal for music,
and gen_notices decoding pip-licenses by the console codec.

### CR-301A (server-tools-1) - release_macos.sh silently cancelled a CCSYNC_REQUIRE_FFMPEG the caller set - FIXED (tools/release_macos.sh)

The Mac half of tests-1 computed `REQUIRE_FFMPEG` from `have_cmd ffmpeg`
alone and then passed `CCSYNC_REQUIRE_FFMPEG="$REQUIRE_FFMPEG"` as a
per-command assignment on the pytest line, so an empty value overrode whatever
the environment carried. `.github/workflows/release-macos.yml:147` sets
`CCSYNC_REQUIRE_FFMPEG: "1"` on exactly that step to turn a missing binary
into a failed release, and `conftest.require_ffmpeg_or_skip` tests `== "1"`:
brew succeeding with ffmpeg off the step's PATH published a macOS companion
whose twenty media-job tests had skipped with exit 0. The caller now wins -
`REQUIRE_FFMPEG="${CCSYNC_REQUIRE_FFMPEG:-}"`, with the `have_cmd` probe only
filling a blank - and the "asked for, but no ffmpeg" case says so out loud in
both the real and the `--dry-run` branch, with the suite's own refusal left to
happen as the caller asked. An absent ffmpeg nobody asked about still only
warns; this script also runs on somebody's Mac. Tested by extracting the real
block from the script and running it under bash with `have_cmd` stubbed, which
fails on the unfixed script for the CI case and passes for both probe cases.

### CR-301B (server-tools-2) - publish_db's "older schema than the live one" refusal was false for --which music - FIXED (server/publish_db.py)

broll-2's new refusal was reasoned from b-roll's mount, where `ensure_schema`
runs once at mount time and nothing re-runs it, so a file dropped under a
running container is never stepped. /music is built the other way round:
`musicweb.db.con()` checks the inode on every connection (MUSIC-10),
invalidates its cached schema state when the file was swapped, and re-runs
`ensure_schema`, which walks its migrations by an "already applied" PREDICATE
rather than by `user_version`. The refusal fired anyway, with b-roll's
sentence and a remedy ("restart the container") that music does not need, and
pushed the operator to `--allow-schema-skew`, the same flag that disables the
direction which IS fatal for music. The property belongs to the web app, so it
is now a per-SPEC `resteps_after_swap` flag that `schema_refusal` consults for
the older-than-live direction only; the newer-than-live refusal is unchanged
for both. Tested with music cases added beside the existing broll ones.

### CR-301C (server-tools-3) - gen_notices decoded pip-licenses by the console codec - FIXED (tools/gen_notices.py, tools/publish_latest.py)

The same pass added `encoding="utf-8", errors="replace"` to
`server/check_health.py` and the four bench runners but left the three
`subprocess.run` calls in `run_piplicenses` decoding by
`locale.getpreferredencoding(False)` - cp1252 here, whose 0x81/0x8D/0x8F/0x90/
0x9D are undefined and are ordinary UTF-8 continuation bytes - while
`--with-license-file` pulls whole licence TEXTS through that pipe. The
resulting `UnicodeDecodeError` is a `ValueError` but neither a `RuntimeError`
nor a `json.JSONDecodeError`, so `collect()`'s except let it escape `main()`
and the one document that must exist before a build is conveyed could not be
regenerated. All three calls now decode UTF-8 with `errors="replace"`, the
except is widened to `ValueError` (which subsumes `json.JSONDecodeError`), and
`publish_latest.run()` - documented as never raising, over git and gh output -
got the same treatment. A scan test over `tools/*.py` replaces the
hand-written file list that let this survive the first pass.

### Verification
- server-tools-1: `tools/tests/test_bug_hunt_2026_09_18b_webapps_server.py` - the caller-wins case and the text pin both fail on the reverted script, pass after; the probe cases pass either way by design.
- server-tools-2: `server/tests/test_bug_hunt_2026_09_18_webapps_tools.py` - the music older-than-live case fails on the reverted `schema_refusal`, passes after.
- server-tools-3: `tools/tests/test_bug_hunt_2026_09_18b_webapps_server.py` - the CJK decode and the escaped-ValueError cases both fail on the reverted `gen_notices.py`, pass after.
- Suites run: tools `test_bug_hunt_2026_09_18b_webapps_server.py`, `test_release_scripts.py`, `test_gen_notices.py`, `test_publish_latest.py`, `test_publish_feed.py` (187 passed); server `test_bug_hunt_2026_09_18_webapps_tools.py` (18 passed). `py_compile` on every touched .py, `bash -n` on the script, `git ls-files --eol` confirms release_macos.sh is still LF.

### Not fixed
- Nothing from this group's list. The downgraded-to-low items were not reached.

### OWED TO ANOTHER GROUP
- None. All three fixes are inside `server/` and `tools/`.

### Deploy order
- None of the three is a wire change. `release_macos.sh` and `gen_notices.py`
  are base-rig/CI tooling only; `publish_db.py` runs from the base rig against
  the NAS and needs no dashboard or companion change (the music behaviour it
  now allows is what the deployed /music already does).

### Owner decisions
- None needed.
