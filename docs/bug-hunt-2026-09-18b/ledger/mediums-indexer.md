# CR-296 - the b-roll indexer never transcribes an audio-only clip - FIXED in repo 2026-09-18 (mediums wave, indexer group)

### CR-296A (broll-indexer-3) - audio-only clips are never transcribed, although two files say their speech is the only index they get - FIXED (`broll/indexer/batch_transcribe.py`, `broll/indexer/broll_index/pipeline.py`)

`stage_probe` parks a file with no video stream at `status='skipped'` on
purpose, with a comment saying its speech is the only index it will ever have.
Both halves of the transcript path then refused it: `batch_transcribe.TODO_SQL`
queued `WHERE status NOT IN ('skipped', 'discovered')`, and 'skipped' and
'discovered' are the only two statuses such a row can ever hold, so the one job
in the tree that writes an `.srt` could never see it; and `run_pipeline`'s
status widening for `transcribe`/`embed` did not include 'skipped' either, so
even a hand-written `.srt` would never have been ingested (every caller of
`stage_transcribe` passes `ingest_only=True`). The clip was indexed as nothing
at all, silently. The fix tells the three 'skipped' verdicts apart
structurally, the way `skipped_for_length` already does rather than by the
status word: the queue now also takes `status = 'skipped' AND codec IS NULL AND
duration_s IS NOT NULL` (audio-only), leaving the over-length clip (codec +
duration), the no-duration container (codec, no duration, broll-indexer-4) and
the scanner's proxy-folder rows (neither) excluded; and `run_pipeline` adds
'skipped' to the `transcribe`/`embed` widening only. That widening cannot undo
the park: none of probe, proxy, frames or claude accepts 'skipped' as a
prerequisite status, the transcribe stage still declines `skipped_for_length`,
and `ingest_only` makes the pass a no-op for a row with no `.srt`. Per the
verifier's fix note, `test_a_discarded_clip_is_not_transcribed`'s row gained a
codec (its over-length row had none, so it would have started matching the new
predicate) and the stale "both 'skipped' verdicts" comment above `TODO_SQL`,
plus the module docstring's line about it, were rewritten.

Tests: `broll/indexer/tests/test_batch_transcribe_queue.py` gains
`test_an_audio_only_clip_is_transcribed` (red before: `assert set() ==
{'podcast.mp4'}`) and `test_a_clip_with_no_duration_is_not_transcribed` (pins
the third verdict staying out); new file
`broll/indexer/tests/test_bug_hunt_2026_09_18b_indexer.py` drives
`run_pipeline` end to end against a real SQLite backend for the ingest half -
`test_an_audio_only_clip_reaches_the_transcribe_stage` (red before: `assert []
== [1]`) and `test_a_skipped_clip_is_not_selected_for_the_visual_stages`, which
would catch the widening leaking into the paid and visual stages.

### Verification
- broll-indexer-3: `python -m pytest tests/test_batch_transcribe_queue.py tests/test_bug_hunt_2026_09_18b_indexer.py tests/test_pipeline.py tests/test_pipeline_embed.py tests/test_share_not_indexed.py tests/test_scanner_proxy_skip.py -q` from `broll/indexer` on system python: 76 passed. Both new assertions were watched red on the unfixed source. `py_compile` clean on every touched file.

### Not fixed
- None. The group had one confirmed medium.

### OWED TO ANOTHER GROUP
- None. Both files are in this group's file set (`broll/indexer/*`).

### Deploy order
- Not a wire change. `broll/indexer` runs on the base rig only; no companion or
  dashboard release is involved. A re-run of `batch_transcribe.py` followed by
  `broll-index run --stages transcribe,embed` is what picks up the backlog of
  audio-only rows already in the DB.

### Owner decisions
- None needed.
