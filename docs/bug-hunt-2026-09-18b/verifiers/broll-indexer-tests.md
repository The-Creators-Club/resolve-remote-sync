# verdicts - broll-indexer-tests

## broll-indexer-2
- Verdict: DOWNGRADED to low
- Duplicate of: none
- Reasoning: the mechanism is real and I reproduced it end to end with a real
  file, not arithmetic alone: `probe_video` takes `duration_s` from
  `format.duration` (the CONTAINER, i.e. the longest stream) and only falls
  back to the video stream when the container has none, so an mp4 whose audio
  outlasts its video inflates `expected` and `_plausible_frames` throws away a
  correct `nb_frames`. The twin in
  `companion/src/ccsync_companion/ffmpeg_tools.py:968` is byte-equivalent, so
  both producers drop the same value. What I could not sustain is the medium
  rating: the discard needs the audio to outrun the video by BOTH more than one
  frame and more than 1% of the clip (tolerance is `max(1.0, expected * 0.01)`),
  which in practice means clips of roughly three seconds or less at 30 fps -
  the archive's own population is minutes-long YouTube downloads, where the 1%
  arm is seconds wide. And the outcome is the column's documented "cannot tell"
  NULL, which every reader already handles as such: `routes_ingest.py:125`
  COALESCEs it so a NULL can never erase a stored value,
  `proxy_relink.stored_frames` returns None ("no refresh, never a guess"), and
  the stand-in ledger stores `geometry.frames` as None. So this is a lost
  enrichment on a narrow population, not a wrong length anywhere - the hunter's
  "a clip of the wrong length on every remote machine" is migration 012 talking
  about a WRONG count, not an absent one.
- Evidence: built two files locally with ffmpeg in the scratchpad. (a) 3 s /
  30 fps video + 3.1 s audio: ffprobe reports video `nb_frames=90`,
  `format.duration=3.100000`; `probe_video` returns
  `{'duration_s': 3.1, 'fps': 30.0, 'frames': None}` - a correct 90 discarded.
  (b) the same with 3.0 s audio: `frames: 90`, so an ordinary aac encode with
  matched durations does not trip it. `_plausible_frames(1800, 60.6, 30.0)` ->
  1800 (a 0.6 s audio overhang on a 60 s clip is inside the 1% arm), which is
  what bounds the population.
- Fix note: the suggested fix is right in direction - prefer the VIDEO stream's
  own `duration` (or `duration_ts` x `time_base`) and fall back to the
  container's - and it is cheap, because `probe_video` already holds
  `video_stream`. Two cautions. The floor must NOT be widened much: this helper
  is the confidence gate in front of a column whose whole point is that a
  confident wrong number is worse than a NULL, and `frames_match`'s exactness
  is a separate rule that must not be softened by association. And the change
  has to land in `companion/src/ccsync_companion/ffmpeg_tools.py::_plausible_frames`
  in the same commit (its docstring calls itself "a verbatim twin"), plus
  whatever test pins the twin, or the two producers of one optional wire field
  disagree about how confident it is - which is exactly what KNOWN_BUGS'
  CR-286R note asked for.

## broll-indexer-3
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: I read both ends and the gap is structural, not a timing accident.
  `stage_probe` parks an audio-only file (`not info.get("codec")`) at
  `status='skipped'` with the comment that its speech is the only index it will
  get; `batch_transcribe.TODO_SQL` selects `WHERE status NOT IN ('skipped',
  'discovered')`, and those two statuses are the only ones an audio-only row can
  ever hold - 'discovered' before probe, 'skipped' after it - so the batch job
  can never queue one at any point in its life. Every caller of the pipeline's
  transcribe stage passes `ingest_only=True` (`pipeline.py:676` and
  `parallel_local.py:73`, both deliberately, BROLL-4), so without an `.srt` the
  stage logs "no .srt yet, ingest_only" and returns. The row is then also
  invisible to later runs: `run_pipeline`'s `statuses = ["discovered",
  "probed", "proxied", ORGANISED_STATUS]` (pipeline.py:752) excludes 'skipped'.
  The clip ends with no visual segments and no cues, and nothing reports a
  failure. Medium is right: it is silent, and the only thing that would ever
  index the file is the thing excluded.
- Evidence: `grep -rn "stage_transcribe" broll/indexer` shows the two
  production call sites, both `ingest_only=True`; `pipeline.py:752`; the
  audio-only arm at `pipeline.py:118-133`; `TODO_SQL` at
  `batch_transcribe.py:85-90`. Nothing else in `broll/indexer` writes an `.srt`
  (`grep` for `transcribed_at IS NULL` / whisper callers returns only
  `batch_transcribe.py`).
- Fix note: the suggested predicate (`status != 'skipped' OR (codec IS NULL AND
  duration_s IS NOT NULL)`) is the right shape but needs care at two places.
  (1) It leans on `codec` being populated, which is exactly the property
  `skipped_for_length` uses, so it is consistent - but `broll/indexer/tests/
  test_batch_transcribe_queue.py::test_a_discarded_clip_is_not_transcribed`
  inserts its over-length row WITHOUT a codec, so that row would start matching
  the new predicate and the test would red; the fixture must gain a codec in
  the same change or the predicate must key off something else. (2) The third
  `skipped` verdict added today (a video stream with no duration,
  `pipeline.py:138-156`) has a codec and a NULL duration, so it stays excluded
  under this predicate, which is correct - but the BROLL-15 comment above
  `TODO_SQL` still says "both 'skipped' verdicts" and is now stale twice over;
  it should be rewritten in the same change.

## tests-1
- Verdict: CONFIRMED
- Duplicate of: none (this hunt's `dash-release-jobs-5` is a different defect -
  the `schema_version` collapse still present in `current.json`'s writer)
- Reasoning: the test never touches `dashboard_update.apply` or any helper of
  it. It writes a `current.json` with `_write_json`, reads it back with
  `_read_json`, and then evaluates a re-typed copy of the corrected expression
  in its own body. Worse than the hunter says: the copy is not even faithful -
  `apply` carries an extra arm (`if carried == version: carried = ""`,
  dashboard_update.py:1435-1441) that the test's expression omits, so the test
  could stay green while `apply` acquired a different bug. The only other test
  that drives `apply` end to end
  (`test_dashboard_update.py::test_apply_stages_verifies_backs_up_swaps_and_asks_to_restart`)
  starts from an ABSENT `current.json`, so `held` is `{}` and both the fixed and
  the unfixed expressions produce `previous == ""` - it asserts exactly that.
  Nothing in the suite can fail on a revert.
- Evidence: I copied `dashboard/{src,tests,templates,static,cards,pyproject.toml}`
  to the scratchpad, reverted the hunk there to
  `carried = previous if previous != version else ""` (verified by
  `inspect.getsource` -> REVERTED), and ran the dashboard venv's pytest from the
  scratch copy: `tests/test_bug_hunt_2026_09_18_dashboard_mediums.py` -> 36
  passed, including `test_reapplying_the_running_version_keeps_the_rollback_target`.
  `tests/test_dashboard_update.py` in the same scratch tree gave 87 passed with
  one failure and 14 errors, all of them artefacts of the copy (missing
  `tools/build_dashboard_bundle` on sys.path; the failure is the reload-panel
  test, unrelated to `previous`) - none of them the re-apply case. Note that a
  PYTHONPATH override does NOT work for this: the dashboard conftest puts the
  repo `src` first, which is why the whole-directory copy was needed.
- Fix note: the suggested fix is right, and the helper form is the better half
  of it - lift the arithmetic into `dashboard_update._carry_previous(held,
  version)` (it must keep the `carried == version -> ""` arm, or the fix
  regresses in a different direction) and have both `apply` and the test call
  it. If instead `apply` is driven with a bundle, the fixture to extend is
  `real_bundle_world` in `dashboard/tests/test_dashboard_update.py`, seeded with
  a `current.json` that already names the version being applied; that file is
  the other file any fix here must touch, and it is also where the existing
  `assert current["previous"] == ""` (line 405) pins the empty-start case that
  must keep passing.
