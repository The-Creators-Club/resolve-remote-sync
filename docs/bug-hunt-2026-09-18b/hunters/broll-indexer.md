# broll-indexer - the b-roll indexer (broll/indexer/*: broll_index, tools, the scripts, tests)

Files read (with approximate coverage): `git diff -- broll/indexer` in full (6 files);
`broll_index/ffmpeg_tools.py` (probe_video, the timecode helpers, count_frames /
parse_frame_count / count_frames_cmd, FRAME_SLACK / expected_frames / frames_match /
_plausible_frames, build_proxy, build_sprite - ~80%); `broll_index/pipeline.py`
(skipped_for_length, reopen_if_now_indexable, stage_probe, stage_proxy, _frames_source,
_process_video's error path, run_pipeline's status list - ~60%); `tools/make_own_proxies.py`
(encode_one end to end, presets/long_path - ~70%); `fix_proxy_timecode.py` (whole);
`batch_transcribe.py` (docstring + TODO_SQL); `broll/migrations/012_geometry.sql` and the
three migration dirs; the new `tests/test_bug_hunt_2026_09_18_webapps_tools.py` (whole) and
the two edited test files. Cross-read for both ends of the wire:
`companion/src/ccsync_companion/ffmpeg_tools.py` (own_proxy_cmd, frames_match,
_plausible_frames, probe_video), `companion/src/ccsync_companion/broll_ingest.py`
(`_frames_missing`), `broll/web/app/routes_ingest.py` + `routes_api.py` (the `frames` column).

Tests run:
- `cd broll/indexer; python -m pytest tests -q` -> 813 passed (my territory's own suite only).
- two scratch snippets under the scratchpad that drive `build_proxy` and
  `make_own_proxies.encode_one` with the probes/counters substituted (output quoted below).

## Findings

### broll-indexer-1 - the new cheap frame check lets a 1-2 frame short proxy through, in both indexer producers
- Severity: high
- Confidence: CONFIRMED
- Where: `broll/indexer/broll_index/ffmpeg_tools.py:563-571` (build_proxy `_bad`), same shape at
  `broll/indexer/tools/make_own_proxies.py:299-305`; the other side of the invariant is
  `companion/src/ccsync_companion/broll_ingest.py:2548-2572` and
  `companion/src/ccsync_companion/ffmpeg_tools.py:947` (`frames_match`).
- What: broll-indexer-3's optimisation skips the authoritative `count_frames(src)` whenever the
  destination's packet count is within `FRAME_SLACK` (2) of `duration * fps` of the SOURCE. When
  the source's real count equals its own `duration * fps` - the normal case for a CFR camera
  original, which is exactly the population this check exists for - a proxy 1 or 2 frames short
  of the source lands inside that window and the source is never counted, so the exact
  comparison `frames_match` performs never happens. The code therefore does the one thing its
  own constant's comment forbids ("this is the threshold for 'look properly', never for 'accept
  a short proxy'") and breaks `frames_match`'s stated invariant ("three producers have to
  agree... a tolerance on one of them is a fleet with two rules about the same file"): the
  companion counts BOTH files unconditionally and compares exactly, so the same file is refused
  on an editor's machine and accepted by the indexer.
- Failure scenario: a 60 s / 30 fps original (1800 packets, container duration 60.0). NVENC
  writes a proxy of 1799 or 1798 frames - the low end of the Reproductive Rights class (seven
  files 1-18 frames short, Resolve refused every one, the editor reported "sync is stuck").
  `build_proxy` returns without ever reading the source and the preview is published; in
  `make_own_proxies` the `.partial` is `os.replace`d into `Proxy/<stem>.mp4` inside the backup
  tree with `status: ok` in the ledger, where Resolve links it directly and refuses it, with
  nothing anywhere recording why.
- Evidence: two scratch runs with the probe, the encoder and `count_frames` substituted (no
  ffmpeg), dest short of src by 1 and by 2:
  - `build_proxy` with dest=1799, src=1800: `ACCEPTED a proxy 1 frame short of the source;
    count_frames asked: ['...\out.mp4']` - the source was never counted.
  - `make_own_proxies.encode_one` with partial=1798, src=1800: `ok | counted:
    ['...\Proxy\A001.mp4.partial']`, `proxy landed: True`.
  The suite does not catch it: `test_a_suspect_proxy_still_pays_for_the_real_count` uses a
  1782-frame dest (18 short), i.e. only the far end of the range, and passes on `git show
  HEAD:...ffmpeg_tools.py` too.
- Ledger: CR-286 (broll-indexer-3) reopens the low end of CR-281 / the 2026-09-17 frame check;
  contradicts the invariant CR-286's own `frames_match` docstring states.
- Suggested fix: make the cheap path a one-sided screen only - skip the source count when
  `dst_frames >= expected` (a proxy that is not short cannot be the failure mode), or drop the
  skip and keep the source count for the destination-short case. Either way the exact
  comparison must still run whenever `dst_frames < expected`, which is the only direction that
  matters.

### broll-indexer-2 - `_plausible_frames` discards a correct frame count on any short clip whose audio outlasts its video
- Severity: medium
- Confidence: PLAUSIBLE (arithmetic confirmed; frequency inferred from what the archive holds)
- Where: `broll/indexer/broll_index/ffmpeg_tools.py:396-411` (and its verbatim twin
  `companion/src/ccsync_companion/ffmpeg_tools.py:968`), consumed at
  `broll/indexer/broll_index/ffmpeg_tools.py:265` (`probe_video`'s `frames`).
- What: the cross-check compares the video stream's `nb_frames` against
  `format.duration * fps`, but `format.duration` is the CONTAINER's duration, i.e. the longest
  stream. In an mp4 whose audio track ends after the video - the ordinary shape of a yt-dlp
  merge, and much of this archive is YouTube downloads - the estimate is larger than the true
  frame count, and the tolerance `max(1.0, expected * 0.01)` is under one frame of wall clock
  for a short clip. A perfectly good `nb_frames` is then written as NULL.
- Failure scenario: a 3.0 s / 30 fps clip whose audio runs 0.1 s longer: claimed 90, expected
  3.1 * 30 = 93, tolerance `max(1.0, 0.93) = 1.0`, 3 > 1 -> `frames` NULL. Phase 3 writes the
  interchange file that creates the OFFLINE media-pool clip from `frames`/`start_tc`, so every
  such clip reaches a remote editor with no frame count (migration 012: "a wrong or absent
  frame count is a clip of the wrong length on every remote machine"). It also overloads the
  column's documented meaning - 012 says NULL means "probed before these columns existed", and
  no reader can now tell that from "counted and distrusted".
- Evidence: read of `probe_video` (duration from `format.duration`, falling back to the video
  stream only when the container has none) against `_plausible_frames`'s arithmetic;
  `_plausible_frames(90, 3.1, 30.0)` returns None while `_plausible_frames(90, 3.0, 30.0)`
  returns 90.
- Ledger: new (a neighbour opened by CR-286 / broll-indexer-2).
- Suggested fix: cross-check against the VIDEO STREAM's duration when it has one
  (`streams[i].duration`), falling back to the container's, and widen the floor to a few frames
  rather than one; or, since `probe_video` already holds the stream dict, prefer
  `duration_ts/time_base` where present. Whatever is chosen has to land in the companion's twin
  in the same change.

### broll-indexer-3 - audio-only clips are never transcribed, although two files say their speech is the only index they get
- Severity: medium
- Confidence: CONFIRMED
- Where: `broll/indexer/batch_transcribe.py:85-90` (`TODO_SQL`) versus
  `broll/indexer/broll_index/pipeline.py:125-133` and `:608-615`.
- What: `stage_probe` parks an audio-only file at `status='skipped'` precisely so its speech
  stays searchable ("Audio-only 'skipped' clips still transcribe - their speech is the only
  index they will ever have"), and the pipeline's own transcribe stage runs `ingest_only=True`,
  i.e. it only ever ingests an `.srt` that `batch_transcribe.py` already wrote. But
  `batch_transcribe.py`'s queue is `WHERE status NOT IN ('skipped', 'discovered')`, so it never
  writes one for an audio-only row. The `.srt` the pipeline waits for cannot arrive, and the
  clip is indexed as nothing at all.
- Failure scenario: a yt-dlp fetch that landed an audio stream in an `.mp4` is probed
  (`skipped`, "audio-only ... transcript indexed, no visuals"), excluded from the whisper batch,
  and then declined by the pipeline's transcribe stage for having no `.srt`. The search index
  has no visual segments and no cues for it; nothing reports a failure.
- Evidence: the two code sites above, read side by side; `TODO_SQL` is a module constant with
  its own test (`tests/test_batch_transcribe_queue.py`) that pins the exclusion.
- Ledger: new (pre-dates today's pass; today's third `skipped` verdict makes the BROLL-15
  comment's "both 'skipped' verdicts" stale as well).
- Suggested fix: exclude only the over-length `skipped` rows, using the same structural
  predicate the pipeline uses - `status != 'skipped' OR (codec IS NULL AND duration_s IS NOT
  NULL)` - or have `batch_transcribe` import `pipeline.skipped_for_length`'s rule rather than
  matching on the status word.

### broll-indexer-4 - the no-duration park does nothing for the rows that already crashed on it
- Severity: low
- Confidence: PLAUSIBLE (cannot be confirmed without reading the live `broll.db`, which is out
  of bounds for this hunt)
- Where: `broll/indexer/broll_index/pipeline.py:138-156` (the new arm), with
  `broll/indexer/broll_index/pipeline.py:718-722` (`set_error`) and `:717` (`statuses = [...]`).
- What: the new guard parks a no-duration container at probe time, but a row that already hit
  the `TypeError: unsupported operand ... 'NoneType' and 'float'` sits at `status='error'` with
  `duration_s` NULL and is never re-queued: `run_pipeline` selects only
  discovered/probed/proxied/organised, and nothing in the tree resets an errored row. If an
  operator clears such a row back to `probed` (its last good status) rather than to
  `discovered`, the clip re-enters at `stage_proxy` and dies on the same `TypeError`, because
  the guard lives in `stage_probe` and not where the None is dereferenced.
- Failure scenario: the operator who reported the crash re-runs after the fix, sees the same
  Python type error in the `error` column, and concludes the fix did not land.
- Evidence: `statuses = ["discovered", "probed", "proxied", ORGANISED_STATUS]` at
  `pipeline.py:717`; `set_error` -> `status="error"`; no requeue path found by
  `grep -rn "retry|requeue|status='error'" broll_index tools *.py`.
- Ledger: new (a gap in CR-286 / broll-indexer-4, not a defect in the fix itself).
- Suggested fix: have `stage_proxy` treat a NULL `video["duration_s"]` the same way (park, do
  not encode), which makes the guard hold wherever the row enters, and note in the ledger that
  affected rows are cleared to `discovered`, never to `probed`.

## Coverage note
- Not got to: `parallel_local.py` / `parallel_claude.py` / `run_queue.py` beyond their transcribe
  gating, `local_vlm.py` and the whole local-VLM backend, `build_archive.py`, `regen_sprites.py`,
  `find_broken_sources.py`, `duplicates.py`, the storage backends beyond `set_error`, and
  `normalize_search.py`. None of them are in today's diff.
- What the suite does not cover: no test runs a real ffmpeg or ffprobe, so every frame count,
  timecode round trip and decode verdict in this territory is a substituted seam - the
  drop-frame separator behaviour of a real mp4 remux (broll-indexer-5) is pinned nowhere. The
  new `test_the_parked_row_is_not_mistaken_for_an_over_length_clip` passes on `git show
  HEAD:broll/indexer/broll_index/pipeline.py` as well, because `skipped_for_length` already
  required a non-NULL `duration_s`; it guards the invariant, but it is not a regression test for
  broll-indexer-4. `test_a_suspect_proxy_still_pays_for_the_real_count` likewise passes at HEAD.
- The two env-hygiene test changes (`BROLL_LOCAL_CACHE_DIR` and friends deleted before
  `load_config`) are correct and cover every case in both files; I checked that the env-wins
  test sets all three itself and is unaffected by the autouse fixture.
- `fix_proxy_timecode.remux`'s new value check (broll-indexer-5) is consistent with `plan()`'s
  precondition - both go through `ffmpeg_tools.read_timecode` - and I found no defect in it.
- Migration/schema parity holds: `012_geometry.sql` is byte-identical (modulo comments) across
  `broll/migrations`, `broll/web/migrations` and `broll/indexer/broll_index/migrations`, and the
  new parity test proves it; `routes_ingest.py` COALESCEs `frames`, so a NULL from a re-probe
  cannot erase a good value already stored.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/broll_ingest.py:2548` (`_frames_missing`): correct and exact,
  but it is now the only one of the three producers that actually performs the comparison - see
  broll-indexer-1; comp-broll-tiers may want the same one-sided screen if the cost matters there.
- `broll/web/app/routes_api.py:210`: `frames` is passed into the detail route's `insert` object
  unchanged, so the NULL rate broll-indexer-2 raises is felt there; worth a look by `broll` at
  what the page and the companion do with `frames: null`.
