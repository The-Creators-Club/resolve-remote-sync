# broll-indexer - the b-roll indexing pipeline (`broll/indexer/*`): probe/proxy/sprite/frames, migrations, the repair tools

Files read (with approximate coverage):
- `broll/indexer/broll_index/ffmpeg_tools.py` (100%, the week's diff hunk by hunk)
- `broll/indexer/broll_index/migrate.py` (100%), `broll_index/migrations/012_geometry.sql` (100%),
  all 11 bundled migrations compared byte-for-byte against `broll/migrations/` and `broll/web/migrations/`
- `broll/indexer/broll_index/pipeline.py` (stage_probe / stage_proxy / _frames_source / stage_frames, ~40%)
- `broll/indexer/broll_index/storage/sqlite_backend.py` + `http_backend.py` (update_video path)
- `broll/indexer/fix_proxy_timecode.py` (100%), `broll/indexer/tools/make_own_proxies.py` (~70%),
  `broll/indexer/build_archive.py` (dest_rel / archive_source / preview_source)
- `broll/indexer/tests/`: `test_ffmpeg_tools.py`, `test_migrate.py`, `test_schema_parity.py`,
  `test_proxy_integrity.py`, `conftest.py` (100% of each)
- Cross-read for contract only (not reported on): `companion/src/ccsync_companion/ffmpeg_tools.py`
  (`timecode_from_probe`, `dropframe_normalized`, `count_frames_cmd`, `preview_proxy_cmd`),
  `broll/web/app/schemas.py`, `broll/web/app/routes_api.py::_insert_object`
- `docs/BROLL_PROXY_TIERS_PLAN.md` + `_AUDIT.md` (the sections naming the indexer), `KNOWN_BUGS.md` R17 / CR-281

Tests run: `cd broll/indexer; python -m pytest tests/test_ffmpeg_tools.py tests/test_migrate.py tests/test_schema_parity.py tests/test_proxy_integrity.py -q` -> 52 passed (ffmpeg/ffprobe present, so the `require_ffmpeg` skips did not fire).

Positive results worth recording, so nobody re-hunts them: companion/indexer parity of
`timecode_from_probe`, `dropframe_normalized`, `count_frames_cmd`/`parse_frame_count` and the
`preview_proxy_cmd` vs `build_proxy` argv is now exact (including the `trunc(min(h,ih)/2)*2` filter
the companion's comment still claims is the "ONE thing" that differs - stale comment, correct code).
The three migration trees are identical apart from a bundled-copy header comment; index-side EOLs are
all LF; migration 012 is three plain `ALTER TABLE ... ADD COLUMN` plus the version pragma, so it is
transactional and cannot half-apply, and `migrate_sqlite_db` still refuses to loop on a script that
forgets its pragma. A v47-era b-roll DB is not a thing (b-roll has its own `user_version`, 12), and a
v11 database migrates to 12 cleanly. The 012 wire is declared on both sides (`VideoIn.frames /
start_tc / bitrate`, COALESCEd on the upsert), so an older indexer that sends nothing does not wipe them.

## Findings

### broll-indexer-1 - `make_own_proxies.py` never got the frame-count check that the rest of the fleet did
- Severity: medium
- Confidence: CONFIRMED
- Where: `broll/indexer/tools/make_own_proxies.py:271-289` (`_bad`), against
  `broll/indexer/broll_index/ffmpeg_tools.py:462-488` (`build_proxy._bad`) and
  `companion/src/ccsync_companion/broll_ingest.py:2509-2510`
- What: 2026-09-17 added a third proxy-verification failure mode - "a few frames short, decodes
  perfectly, Resolve refuses it as a proxy" - to the indexer's browsing proxy and to the companion's
  ingest path. `make_own_proxies.py` produces **editor-grade** `Proxy/<stem>.mp4` files (HEVC Main-10,
  the companion's own `own_proxy_cmd`) that Resolve links directly, and its `_bad()` still checks only
  (a) libav decode errors and (b) duration >= 97% of source. A proxy 1-18 frames short passes both:
  18 frames at 30 fps is 0.6 s, and 0.97 of a 60 s clip is a 1.8 s tolerance.
- Failure scenario: a run over a backup tree (its stated use: FF2's older episodes, the 2023
  Disinformation and 2022 WCT backups, ~6,700 clips) drops an NVENC session a few frames early. The
  `.partial` verifies clean, is `os.replace`d into `Proxy/`, indexed and shipped to editors via lane B.
  Resolve silently refuses to attach it; the editor reports "sync is stuck". That is verbatim the
  Reproductive Rights incident the check exists to end.
- Evidence: read both `_bad()` implementations side by side. `grep -n "count_frames" broll/indexer/tools/make_own_proxies.py` -> no hits; `broll_index.ffmpeg_tools.count_frames` is already imported into the module's namespace via `from broll_index import ffmpeg_tools`, so the check is two lines away. CR-281's ledger text says `make_own_proxies.py` "moved with the rule" - it moved with the *timecode* rule only.
- Ledger: new (the frame check landed with CR-281; this is the one editor-proxy producer it missed)
- Suggested fix: in `_bad()`, add `src_n, dst_n = ffmpeg_tools.count_frames(long_path(src)), ffmpeg_tools.count_frames(long_path(partial))` and return a mismatch reason when both are known and differ, exactly as `build_proxy._bad` does (both-known-or-skip, never treat None as 0).

### broll-indexer-2 - the `frames` column that decides an offline clip's LENGTH is read from `nb_frames`, which this same module documents as a lie
- Severity: medium
- Confidence: CONFIRMED (the inconsistency); PLAUSIBLE (the wrong-length clip downstream)
- Where: `broll/indexer/broll_index/ffmpeg_tools.py:253` (`probe_video`: `"frames": _int_or_none(video_stream.get("nb_frames"))`) vs `:305-322` (`count_frames_cmd`'s docstring) and `broll/indexer/broll_index/migrations/012_geometry.sql` (the column's own comment)
- What: migration 012's comment states `frames` is "what phase 3 writes into the interchange file that
  creates an OFFLINE media-pool clip ... a wrong or absent frame count is a clip of the wrong length on
  every remote machine". Fifty lines below `probe_video`, `count_frames_cmd` explains that `nb_frames`
  "is a container field and is absent or a lie in exactly the cases that matter (an mp4 written by a
  killed encoder still carries the count it intended)" - which is precisely why the proxy check counts
  packets instead. `probe_video` nonetheless populates the column from `nb_frames`, and nothing ever
  cross-checks it.
- Failure scenario: a partially-written original (the truncated-download class `UnreadableMediaError`'s
  own docstring says the archive already contains) probes with an over-stated `nb_frames`. The row goes
  to the web DB, `_insert_object`'s `geometry.frames` carries it to the page, the page forwards it to the
  companion, and a remote editor gets an offline clip longer than the media that will eventually arrive -
  a timeline whose tail is empty, with nothing anywhere saying why. Separately, on containers that do not
  carry the field (mkv/webm - a large share of the Downloads collection) `frames` is silently NULL.
- Evidence: read `probe_video` and `count_frames_cmd` in the same file; `tests/test_probe_video_reports_frames_and_bitrate` asserts only `frames is None or frames > 0`, i.e. it cannot fail on a wrong count. The companion's twin (`ccsync_companion/ffmpeg_tools.py:567`) has the same line, so the two agree - on the same unreliable source.
- Ledger: new (CR-281 / audit F3 introduced the column)
- Suggested fix: either fall back to `count_frames(path)` when `nb_frames` is absent or disagrees with `round(duration_s * fps)` by more than a frame, or record `frames` only when the packet count confirms it; NULL ("probed before the column existed") is already handled by every reader and is safer than a confident wrong number.

### broll-indexer-3 - the new frame check costs a second full network read of every original, on the one path the pipeline was tuned to read once
- Severity: medium
- Confidence: CONFIRMED
- Where: `broll/indexer/broll_index/ffmpeg_tools.py:478` (`src_frames, dst_frames = count_frames(src), count_frames(dest)`), against `broll/indexer/broll_index/pipeline.py:168-175`
- What: `count_frames` runs `ffprobe -count_packets`, which demuxes the file end to end. In `build_proxy._bad()` it is run against `src` - the ORIGINAL - for every clip, in addition to the encode's own read. `stage_proxy` and `_frames_source` exist precisely to avoid that: their comments say "with source media on a 46 MB/s network share those reads dominate the whole run ... one network read per file instead of three". The check reinstates a second one.
- Failure scenario: a back-catalogue run over a share of multi-GB originals roughly doubles its wall-clock time and its NAS read load, with no log line attributing the cost. On the archive's scale (the module's own numbers: a ~1 TB queue) that is hours, and the run competes with the fleet's sync lanes for the same NAS.
- Evidence: `count_frames_cmd` passes `-count_packets` with no `-read_intervals`, which forces a full demux; `_bad()` calls it unconditionally on `src` before the (cheap, metadata-only) duration comparison. `verify_decodes(dest)` and `probe_video(dest)` are local-disk reads; `count_frames(src)` and `probe_video(src)` are not.
- Ledger: new
- Suggested fix: derive the expected source frame count from the probe `build_proxy` already ran (`duration_s * fps`, tolerance one frame) and fall back to `count_frames(src)` only when the proxy's own packet count disagrees with it - the expensive read then happens only for the clips that are actually suspect. Alternatively cache the source count on the row (finding 2's fix would supply it once per clip rather than once per proxy build).

### broll-indexer-4 - a probe that yields no duration crashes the proxy stage with a bare TypeError
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/indexer/broll_index/ffmpeg_tools.py:573` (`build_sprite`), `:608` (`build_poster`), `:646` (`fill_gaps`), reached from `broll/indexer/broll_index/pipeline.py:164` and `:217-220`
- What: `probe_video` returns `duration_s = None` when neither `format.duration` nor the video stream's
  own duration is present (raw elementary streams, some MPEG-TS, a growing recording). `stage_probe`
  guards only on a missing `codec`, so such a row reaches `probed`. `stage_proxy` then passes that None
  straight into `build_sprite`/`build_poster`, and `stage_frames` into `fill_gaps`.
- Failure scenario: the clip fails with `TypeError: unsupported operand type(s) for //: 'NoneType' and
  'float'` instead of a diagnosis; the row's `error` column records a Python type error rather than
  "no duration in the container", which is what the operator would need to act on.
- Evidence:
  ```
  $ python -c "from broll_index import ffmpeg_tools as f; f.build_sprite('x.mp4','/tmp/o.jpg',duration_s=None)"
  TypeError unsupported operand type(s) for //: 'NoneType' and 'float'
  TypeError unsupported operand type(s) for *: 'NoneType' and 'float'   # build_poster
  ```
- Ledger: new (pre-dates this week's diff)
- Suggested fix: have `stage_probe` park a row with a video stream but no duration at `skipped` with an explicit reason, the way it already does for audio-only and over-cap clips.

### broll-indexer-5 - `fix_proxy_timecode` verifies that the remux has *a* timecode, not the one it just decided on
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/indexer/fix_proxy_timecode.py:117` (`if not ffmpeg_tools.read_timecode(tmp)`)
- What: since audit F6 the *value* is the entire point of this tool - a colon and a semicolon at the same
  numbers are different absolute frames, and writing the wrong one is what makes Resolve refuse the proxy.
  The post-remux guard only asserts that some timecode survived; it never compares it to `tc`.
- Failure scenario: if ffmpeg normalises the separator on a given container/build, every file is reported
  "fixed" and `os.replace`d while still carrying the form `plan()` rejected. The next run re-plans all of
  them as `fix` and rewrites them again, forever, and the run exits 0 each time - "green while dead" for a
  repair sweep whose whole output is a count.
- Evidence: read `remux()`; `plan()` compares `read_timecode(preview) == wanted`, so the round-trip
  assertion exists one function away and is simply not applied to the temp file.
- Ledger: new (the strictness became load-bearing with CR-281's F6 change)
- Suggested fix: `if ffmpeg_tools.read_timecode(tmp) != tc:` and report the value actually written.

### broll-indexer-6 - a killed indexer leaves a truncated proxy under its final name, and a later `--stages frames` indexes from it
- Severity: low
- Confidence: CONFIRMED (the mechanism); PLAUSIBLE (that it has happened)
- Where: `broll/indexer/broll_index/ffmpeg_tools.py:427-451` (`build_proxy` writes straight to `dest`), `broll/indexer/broll_index/pipeline.py:202-204` (`_frames_source`)
- What: unlike the companion's proxy pipeline and `make_own_proxies.py` - both `.partial` + atomic rename,
  "first writer wins" - `build_proxy` has ffmpeg write the final path directly. A kill (or a full disk)
  mid-encode leaves a non-empty, truncated `proxies/<id>.mp4`. `_frames_source` accepts any non-empty file
  at that path, and `stage_frames` is skipped only by its `_complete` marker, not by the proxy's validity.
- Failure scenario: the run is interrupted; the operator resumes with `--stages frames` (documented in
  `_frames_source`'s own docstring as a normal thing to do). Scene detection and contact sheets are built
  from the truncated proxy, so the model describes only the first part of the clip and the segment
  timestamps that reach search are wrong - silently, because the sheets look fine.
- Evidence: no `.partial` or `os.replace` anywhere in `build_proxy`; `_frames_source` tests only `is_file() and st_size > 0`.
- Ledger: new
- Suggested fix: encode to `<id>.mp4.partial` and `os.replace` after `_bad()` passes (the container must be named for ffmpeg, so pass `-f mp4` as the companion's `preview_proxy_cmd` already does for exactly this reason).

## Coverage note

Not reached: `broll_index/` claude_client, local_vlm / local_models / local_runtime, transcribe /
batch_transcribe / transcript_quality, embed / normalize / duplicates / origins / rebase / sorter /
taxonomy / share_push / dashboard_site / site_data / manifest / contract, `scanner.py` beyond
`PROXY_DIR_RE`'s use in `make_own_proxies`, `parallel_claude.py` / `parallel_local.py` / `run_queue.py`
/ `watchdog.ps1`, `regen_sprites.py`, `fix_10bit_proxies.py`, `find_broken_sources.py`,
`normalize_search.py`, `embed_transcripts.py`, and about 50 of the 63 test files.

What the suite does not cover: nothing anywhere exercises `make_own_proxies.encode_one`'s verification
(no test file for it at all), and no test asserts the `frames` column against a real frame count -
`test_probe_video_reports_frames_and_bitrate` is written so it cannot fail on a wrong one. There is no
test for `stage_probe` -> `stage_proxy` with a duration-less probe, and none for an interrupted
`build_proxy`. `broll/indexer` also has no test that a v11 database from a machine still on the
0.7.43-era build migrates while holding rows with NULL `archive_path` - `test_migrate` starts from a
synthetic v1 schema only.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/proxy_gen.py`: the tray's editor-proxy generator verifies decode errors and `VERIFY_DURATION_RATIO = 0.97` only - it has no frame-count check either, although `ffmpeg_tools.count_frames` was added beside it on 2026-09-17 and `broll_ingest.py:2509` uses it. Same defect as broll-indexer-1, on the path that actually serves the fleet (comp-resolve).
- `companion/src/ccsync_companion/ffmpeg_tools.py:849-856`: the comment claiming the even-height `trunc` is "the ONE thing in this argv that is not byte-identical to the b-roll indexer's build_proxy ... until it gets one the two differ on odd-height sources" is stale - the indexer now carries the identical filter (comp-broll-tiers).
- `companion/src/ccsync_companion/ffmpeg_tools.py:567`: same `nb_frames` source for `frames` as broll-indexer-2, so the two pipelines agree on an unreliable value rather than disagreeing (comp-broll-tiers).
- `broll/web/static/sprite.js:51` and `broll/web/app/client_folders.py:6`, `broll/web/app/routes_share.py:10`: still describe the preview as 540p after the 1080p change; CR-281's "still owed" list names `SPEC.md`'s 540p wording but not these (broll / dash-mounts-ui).
- `broll/indexer/build_archive.py:255-270` is mine, but its consumer is not: `preview_source`'s "two copies of a ~27 MB proxy is the cheaper mistake (BROLL-6)" reasoning was costed at 540p; at 1080p/cq25 the same duplication is ~10x the bytes, and the duplicated file is the one thing lane B pushes to every editor. Worth a disk-budget check by whoever owns the archive's growth.
