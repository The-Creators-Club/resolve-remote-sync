# verdicts - indexer-tests

Scope: every finding in `hunters/broll-indexer.md` (6) and `hunters/tests.md` (6).
Read-only on the repo; all mutation work was done through a scratch pytest plugin
on `PYTHONPATH` (scratchpad), never by editing the tree.

## broll-indexer-1
- Verdict: CONFIRMED
- Duplicate of: none (the companion-side twin, `proxy_gen.py`, is the hunter's own
  OUT OF TERRITORY note for comp-resolve and is not reported by anyone)
- Reasoning: read both `_bad()` bodies. `broll/indexer/broll_index/ffmpeg_tools.py:462-488`
  has the three-mode check (decode errors, frame count, 97% duration);
  `broll/indexer/tools/make_own_proxies.py:273-289` has only decode errors and the
  97% duration comparison, and `grep -n count_frames broll/indexer/tools/make_own_proxies.py`
  is empty. The output is an editor-grade `Proxy/<stem>.mp4` from the companion's
  `own_proxy_cmd` (imported at `make_own_proxies.py:52`), i.e. a file Resolve links
  directly, so it is squarely in the class the 2026-09-17 check exists for. I checked
  the one refutation that would matter - a frame-rate change between source and proxy
  would make an equality comparison wrong - and `own_proxy_cmd` sets no `-r`, so the
  counts are comparable exactly as in `build_proxy`.
- Evidence: side-by-side read of the two `_bad()`s; `own_proxy_cmd` argv (no rate
  change, `-map 0:v:0`).
- Fix note: the suggested two-liner is right in shape but must NOT be a bare equality.
  comp-broll-tiers-3 reports that the same exact-equality rule on the companion's ingest
  path fails whole items on VFR sources ("the proxy has 5391 frames, the original has
  5388"); whatever tolerance that finding settles on has to be applied here and in
  `build_proxy._bad` at the same time, or the three producers diverge again. Also note
  the cost: `count_frames(src)` on a backup tree over SMB is broll-indexer-3's second
  network read, so the two findings' fixes interact. A fix should come with the first
  test `make_own_proxies.encode_one` has ever had.

## broll-indexer-2
- Verdict: DOWNGRADED to low
- Duplicate of: proxy-tiers-7 (same line, `ffmpeg_tools.py:253`, same "nb_frames is what
  this module calls a lie" argument; proxy-tiers-7 rates it low and adds that the column
  is write-only)
- Reasoning: the INCONSISTENCY is real and reproduces on the page - `probe_video` fills
  `frames` from the container field fifty lines above the docstring that says the field is
  "absent or a lie in exactly the cases that matter". But the failure scenario the medium
  rating rests on (an offline media-pool clip of the wrong length on every remote machine)
  cannot happen today: nothing writes an interchange file. I traced the column end to end -
  `routes_api._insert_object` -> `broll_server.derive_insert_paths` (`geometry` kept for
  five keys) -> `broll_standins.record`'s ledger entry, and that is where it stops. No
  reader anywhere decides a length, a plan or a relink from `frames` (grep over
  `companion/src`: the only other `frames` uses are `count_frames` and the contact-sheet
  code). So this is a latent data-quality defect on a write-only column, which is low.
- Evidence: `grep -rn "\bframes\b" companion/src/ccsync_companion/*.py`;
  `broll_standins.py:220-247` stores geometry verbatim and nothing reads it back.
- Fix note: the hunter's "record it only when a packet count confirms it" is the safe half,
  but the cheap half is better: `nb_frames` vs `round(duration_s*fps)` needs no extra
  ffprobe at all, and `probe_video` already has both. Do NOT add an unconditional
  `count_frames(path)` to `probe_video` - that is broll-indexer-3's cost on the probe stage
  as well. Any fix must touch the companion twin (`ccsync_companion/ffmpeg_tools.py:567`)
  in the same change, or the two pipelines stop agreeing on a wire field.

## broll-indexer-3
- Verdict: CONFIRMED
- Duplicate of: none (comp-resolve-2 is the same *mechanism* - a whole-file
  `-count_packets` demux used as a cheap check - on the companion's relink pass; different
  file, different caller, and it is rated high there)
- Reasoning: `_bad()` calls `count_frames(src)` unconditionally, before the cheap
  metadata comparison, and `count_frames_cmd` passes `-count_packets` with no
  `-read_intervals`, which demuxes the whole file. `stage_proxy` and `_frames_source`
  both carry comments saying the design is "one network read per file instead of three"
  because "with source media on a 46 MB/s network share those reads dominate the whole
  run" - so the new check lands on precisely the budget those two comments protect. I
  checked the ordering for a cheap refutation (if the duration check ran first, most
  clips would never reach the count) and it does not: the count is second, the probes
  third. The hunter's "roughly doubles" is right for network I/O (1 read -> 2) and
  overstated for wall clock, since a demux is cheaper per byte than the encode's
  decode+encode; on an I/O-bound share the two converge.
- Evidence: read `count_frames_cmd` (no interval flags) and `_bad()`'s statement order;
  `pipeline.py:168-175` and `:190-201` comments.
- Fix note: the suggested fix is right and is the cheap one: `build_proxy` already ran
  `run_ffprobe(src)` for the timecode and rate, so `duration_s * fps` is in hand for free
  and the expensive source count need only run when the PROXY's own packet count
  disagrees with it. Any fix must keep "a count neither side can produce is not a
  mismatch" (both-known-or-skip) and must not change `build_proxy`'s argv, which
  `broll/indexer/tests/test_ffmpeg_tools.py` and the companion parity loader pin.

## broll-indexer-4
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: reproduced all three crashes against the real module. `probe_video` yields
  `duration_s = None` whenever neither `format.duration` nor the video stream's duration
  is present, and `stage_probe` gates only on `codec`, so such a row is stored as
  `probed` and `stage_proxy` passes the None into `build_sprite`/`build_poster`
  (`stage_frames` into `fill_gaps`). Low is the right severity: the clip fails either way,
  the failure is per-clip and recorded, and the loss is only diagnosis quality.
- Evidence (broll/indexer, system python):
  `build_sprite TypeError unsupported operand type(s) for //: 'NoneType' and 'float'`;
  `build_poster TypeError unsupported operand type(s) for *: 'NoneType' and 'float'`;
  `fill_gaps TypeError '<=' not supported between instances of 'NoneType' and 'int'`
  (the hunter did not cite the `fill_gaps` one; it is real).
- Fix note: parking the row at `skipped` in `stage_probe` is right and matches the two
  existing parks, but `skipped_for_length()` tells the two existing "skipped" kinds apart
  structurally (codec present + duration present) - a third kind with a codec and NO
  duration must not be misread by it. Check `skipped_for_length`, `build_archive.py`'s
  eligibility rules and `test_build_archive_eligibility.py` in the same change.

## broll-indexer-5
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: `remux()` asserts `if not ffmpeg_tools.read_timecode(tmp)` - truthiness, not
  the value - while `plan()` one function above compares `read_timecode(preview) == wanted`.
  Since audit F6 the VALUE (colon vs semicolon at the same numbers) is the whole point of
  the tool, so the post-condition is weaker than the precondition it is meant to close. I
  looked for the refutation that the round trip cannot differ in practice: KNOWN_BUGS R17
  records the 2026-08-12 sweep as "799 previews fixed, 0 failed", so empirically ffmpeg
  did round-trip the form then - but that run predates the F6 change that made the
  semicolon form conditional on the tmcd flag, and the mp4 tmcd box stores a drop-frame
  FLAG rather than the separator, which is exactly the place a normalisation can happen
  silently. The "forever re-fixing, exit 0 each time" consequence follows from `plan()`
  re-deciding `fix` on the next run. Low is right: worst case is wasted remuxes and a
  repair that silently does nothing.
- Evidence: `fix_proxy_timecode.py:98` (`plan`'s `==`) vs `:117` (`remux`'s truthiness).
- Fix note: the one-line fix is right; report the value written, and make sure the error
  string stays distinguishable from "remux dropped the timecode" so the sweep's summary
  still tells the two apart. No test pins the current wording (`grep` finds no test file
  for this tool at all), so nothing breaks - which is itself worth a line in the fix.

## broll-indexer-6
- Verdict: REFUTED (as a live defect; the non-atomic write is real, the stated failure
  path is unreachable)
- Duplicate of: none
- Reasoning: `build_proxy` does write straight to `dest` and leaves a truncated (or
  verified-bad) file there on a kill or a raise - that half is correct, and stronger than
  the hunter said, since the `raise RuntimeError("proxy unusable after libx264 fallback")`
  path also leaves the bad file behind. But the consequence cannot occur: the frames stage
  is gated by `STAGE_PREREQ_STATUS = {..., "frames": "proxied"}` (`pipeline.py:59`,
  enforced at `:561`, and again by hand in `parallel_local.py:80-86`), and a row only
  reaches `proxied` at the END of `stage_proxy`, i.e. after `build_proxy` returned
  verified. A killed encode leaves the row at `probed`, where `--stages frames` declines
  it and `--stages proxy` re-encodes over the truncated file with `-y`. There is no
  id-picked entry point that bypasses the status gate (`run_pipeline` is the only caller of
  `_process_video`, and it selects by status). So the truncated proxy is always overwritten
  before it can be a frames source.
- Evidence: `pipeline.py:59`, `:555-562`, `parallel_local.py:80-86`; `stage_proxy`'s
  `update_video(status="proxied")` is its last statement.
- Fix note: the suggested `.partial` + `os.replace` is still worth doing for tidiness and
  for the disk-full case (`fix_10bit_proxies.py:140-141` already uses exactly that pattern
  in this tree), but it is a hardening, not a bug fix, and `-f mp4` would have to be added
  with it - that flag is argv, and `tests/test_ffmpeg_tools.py`'s argv assertions plus the
  companion parity loader would need updating in the same change.

## tests-1
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: `test_jobs_media.py:37-42` gates 20 tests on `shutil.which` with no
  `CCSYNC_REQUIRE_*` escape, and the module-scoped `clips` fixture skips as well, so the
  whole file can vanish at exit code 0. A tree-wide grep shows `CCSYNC_REQUIRE_FFMPEG`
  exists ONLY in `broll/indexer/tests/conftest.py`, and no workflow or release script sets
  it; `CCSYNC_REQUIRE_RCLONE=1` is set by `tools/release.ps1:634` and
  `tools/release_macos.sh:506`, which is the precedent the hunter cites and it holds.
  ffmpeg is installed by exactly one CI step, `if:`-scoped to the Linux broll/indexer job
  (`ci.yml:399-401`), and that step's own comment says a bare runner image has neither
  binary on PATH. One honest caveat I could not close from here: that measurement was on
  `ubuntu-latest`, and I cannot prove from the repo that `windows-latest` / `macos-latest`
  ship no ffmpeg. If they do, this is a fragility rather than a live gap - but the gate
  is missing either way and the CI comment already frames the rclone treatment as the
  house pattern.
- Evidence: `grep -rn "CCSYNC_REQUIRE_FFMPEG\|require_ffmpeg"` (indexer only);
  `grep -rn ffmpeg .github/workflows/*.yml` (ci.yml 383-401 only);
  `grep -c needs_ffmpeg companion/tests/test_jobs_media.py` -> 20.
- Fix note: the suggested fix is right, but put the fixture in `companion/tests/conftest.py`
  beside `rclone_binary` (so a future ffmpeg-dependent companion test inherits it) and set
  the variable in BOTH release scripts, not just `release.ps1` - a Mac-only regression in
  the three Timeline Cards recipes is exactly the shape that gets published from
  `release_macos.sh`. Adding an ffmpeg install step to the two companion CI jobs is the
  other half; without it, turning the skip into a failure turns CI red rather than honest.

## tests-2
- Verdict: DOWNGRADED to low
- Duplicate of: none (the underlying `from_page = True` behaviour is the hunter's own
  OUT OF TERRITORY note for comp-broll-tiers, and comp-broll-tiers did not report it)
- Reasoning: the test gap is exactly as described and I reproduced the hunter's evidence
  verbatim in the companion venv: a dict with no tier fields yields `from_page: True` and
  `plan_insert` answers `fetch_standin` with a stem-convention `fetch_rel`, while
  `insert=None` on the same path answers `fetch_original`. The parametrised test asserts
  four fields and never `from_page` or the plan, so it cannot see the difference. What
  pulls the severity down is reachability: every shipped producer of the object is
  `routes_api._insert_object`, which ALWAYS emits `preview_rel`, `edit_proxy_rel`,
  `original_is_edit_weight` and `geometry` (nulls included, and an explicit null is handled
  correctly - `edit_proxy_rel: None` makes `heavy` false and the plan `fetch_original`).
  So the stand-in-nobody-judged outcome needs a hypothetical truncated client, and the
  live value of the finding is test hardening rather than a defect in the field.
- Evidence: companion venv - `derive_insert_paths({'share':..,'original_rel':..}, ..)` ->
  `from_page: True`, `plan_insert(False, False, t, wired=False)` -> `fetch_standin`,
  identical for `{'preview_rel': '../../etc/passwd'}`; `insert=None` -> `fetch_original`.
- Fix note: the suggested fix is safe. I ran it as a mutation (a scratch pytest plugin
  wrapping `derive_insert_paths` to set `from_page` only for a carried tier field) across
  `tests/test_broll_server.py` + `tests/test_broll_insert_tiers.py`: 223 passed, so nothing
  currently pins the old semantics. Note the parametrisation includes non-dict inputs
  ("not a dict", 42, []) - `assert tiers["from_page"] is False` is correct for all eight
  cases only AFTER the fix. If the rule changes, `broll/web/app/routes_api.py::_insert_object`
  is the other side of the wire and must keep sending at least one tier field for the
  phase-3 behaviour to survive.

## tests-3
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: `_mode_gate_body` writes `clip.mov` before the call, so
  `local_path_exists` is True and `plan_insert` returns `import_original` for both bodies
  regardless of the object - the test is vacuous for the thing its name claims, and its
  docstring ("Phase 3 is gated on the phase 0 spike") has been false since 2026-09-17. I
  proved the vacuity rather than arguing it: with a scratch plugin that makes the companion
  IGNORE the insert object entirely, this test still passes (only its sibling
  `test_an_insert_object_is_used_as_given` goes red). Low is right - no live defect, only
  a stale pin that will mislead the next change.
- Evidence: `PYTHONPATH=<scratch> .venv/Scripts/python -m pytest tests/test_broll_server.py
  -p mutant -k insert_object` -> `1 failed, 11 passed`, and the failure is the sibling, not
  this test.
- Fix note: rewriting it as "an ABSENT original plus an insert object changes the fetch" is
  the right replacement and would have caught the mutation above. Deleting it outright is
  also acceptable, since `test_broll_insert_tiers.py` already owns the decision table.

## tests-4
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: the test stubs `StandinLedger._persist_locked` with `lambda self: False`,
  i.e. it replaces the exact function whose failure it claims to cover, so it proves only
  that a False return is tolerated. `_persist_locked` catches `OSError` only and
  `json.dumps(payload)` is inside that try, and the module-level `record()` is the one
  public wrapper without the `try/except -> log.debug` its five siblings have, against a
  docstring that says "Never raises". I reproduced the raise and then found it is WORSE
  than reported: the bad entry is inserted into `self._entries` before the persist, so the
  in-memory ledger is poisoned and every SUBSEQUENT `record()` in that process raises too,
  with the ledger file never created. Low stands only because the value is unreachable
  today: `geometry` is JSON-parsed from the page body, so it can hold nothing json cannot
  re-encode.
- Evidence: companion venv - first `record(geometry={'fps': object()})` -> TypeError;
  second, clean `record()` on the same ledger -> TypeError; `is_standin` on the second path
  answers True from the poisoned in-memory dict; the state file never exists.
- Fix note: both halves of the suggested fix are right, and the wrapper should also roll
  the entry back (or validate before inserting) so a failed persist cannot poison the
  process. A test that raises a real `OSError` from `os.replace` belongs beside it; nothing
  in `tests/test_broll_standins.py` pins the current stub, so there is no old behaviour to
  break.

## tests-5
- Verdict: CONFIRMED
- Duplicate of: none (dash-collector-alerts-5 and dash-db-2 report the missing
  `db_busy`/`slow_write` registry rows themselves; this is the test that cannot see them)
- Reasoning: `test_every_new_kind_is_in_the_registry_and_the_weekly_list` loops over
  sixteen string literals typed into the test file and asserts membership in
  `alerts.ALERT_KINDS`; nothing derives the expected set from `src/`, so the test can only
  fail if someone deletes a kind, never if someone forgets to add one - the opposite of
  what its docstring claims to enforce. I checked whether another test covers it from the
  other direction: `grep -rn "ALERT_KINDS\|NOTICE_CHECKS_META" dashboard/tests` finds only
  monkeypatch uses and two count assertions (`test_protection.py:553`,
  `test_alerts.py:342`), and those count assertions are themselves derived from
  `len(ALERT_KINDS)`, so they cannot bite either. Low is right: it is a hole in a net, not
  a break.
- Evidence: `dashboard/tests/test_alerts.py:1312-1328`; the grep above.
- Fix note: the suggested derived test is right but must be written against the SOURCE
  text (every `kind=` literal passed to `db.notice(...)` under `src/`), with the allow-list
  commented - and the allow-list has to name `server_error`, `db_busy` and `slow_write` on
  day one, or the new test lands red on the two kinds dash-collector-alerts-5 and dash-db-2
  are separately arguing about. Whoever fixes those two findings changes this test's
  expected set, so the two changes should be sequenced.

## tests-6
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: there is no cross-copy comparison anywhere - `test_schema_parity.py` compares
  a FRESH `schema.sql` against a MIGRATED chain within one copy, not one copy against
  another, and no `filecmp`/hash test exists in either suite. Two things sharpen the
  finding rather than refute it. First, the copies are not in fact byte-identical:
  `diff -r broll/web/migrations broll/indexer/broll_index/migrations` shows every file
  differing by the five-line "Bundled copy: ... kept in sync here" header, so a naive hash
  test fails on day one. Second, both `broll_index/migrate.py` (`_find_migration_file`,
  repo-root first at `:44-62`) and `broll/web/app/db.py` (`find_migration_path`,
  "repo-root-first, then bundled") resolve to the REPO-ROOT copy when the repo is checked
  out - which is what every test run is - so the bundled copies are exercised by no test
  at all, and drift shows up only in a deployed container or an installed package. Low is
  right for a copy that is identical today.
- Evidence: `diff -r broll/migrations broll/web/migrations` -> identical;
  `diff broll/schema.sql broll/web/schema.sql` -> identical;
  `diff -r broll/web/migrations broll/indexer/broll_index/migrations` -> header-only
  differences in all eleven files.
- Fix note: the suggested hash test must normalise (strip the bundled-copy header block,
  or compare only the non-comment SQL) or it cannot pass as written. Better still, have it
  assert on the statements rather than the bytes, and cover `schema.sql`'s two copies in the
  same test. Put it in the indexer suite, which is the one that already keeps a literal
  `LATEST_VERSION == 12` anchor; the web side's relaxation to `== CURRENT_SCHEMA_VERSION`
  (`broll/web/tests/test_migration.py:284-290`) is the other half worth restoring.
