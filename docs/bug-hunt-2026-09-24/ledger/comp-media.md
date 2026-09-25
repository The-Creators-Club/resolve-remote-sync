# Ledger - comp-media (2026-09-24 fix wave)

Builder `comp-media`. Findings in the order the brief gave them. No version
bumps, no KNOWN_BUGS edits, no commits.

How "fails on HEAD" was checked, for all three: a scratch copy of
`companion/src/ccsync_companion` with HEAD's versions of the six edited
modules (`git show HEAD:...`) was put first on the path with
`pytest -o pythonpath=<scratch>` (the suite's own `pythonpath = ["src"]`
otherwise wins), and the new tests were run against it. Every new test
failed there. The two that matter most failed on the defect itself, not on a
missing name:
`{'during': ['Some Channel - A clip [aaaaaaaaaaa].mp4'], 'deliverable': True}`
and `['cardA.mp4', 'cardA.mp4'] == ['cardA.mp4', 'cardB.mp4']`.

## bug-comp-ytdl-1 - A conversion longer than 120 s leaves the pre-conversion original eligible for lane A and the Resolve importer under its final name
- Mechanism (as you traced it): as the finding describes. yt-dlp lands
  `<title> [id].<ext>` under its deliverable name. `_ensure_edit_ready`
  probes it, then re-encodes with ffmpeg reading `src` in place. Nothing
  writes to `src` while ffmpeg runs, so once the conversion passes 120 s the
  file clears lane A's `--min-age 120s`. Lane A runs `--ignore-existing`, so
  the NAS keeps the VP9 bytes for good. The file also clears the importer's
  settle test (120 s old, unchanged over two scans). No exclusion rule
  (`YTDL_WORK_EXCLUDE_RULES`, the importer's `_INTERMEDIATE_STEM_RE`) covers
  the deliverable name. The verifier's correction is right: when Resolve
  holds the file, `swap_in` usually moves it aside to `.original`, and only
  falls back to `.converted [id]` when that fails. Either way the pool ends
  up with two clips.
- Fix: once the probe says the clip needs converting, the original is moved
  to `<stem>.source.editready.<ext>` (`SOURCE_STAGING_SUFFIX`, `staged_source_name`)
  and ffmpeg reads it from there. The new name falls inside exclusions that
  already exist, so no rule list had to change (the dashboard's
  `LANE_A_SKIP_GLOBS` mirror and its parity test stay valid):
  - lane A and the dashboard mirror skip `*.editready.*`;
  - the stem ends in `.editready`, which the importer's and the executor's
    `_INTERMEDIATE_STEM_RE` reject, so `landed_file` never takes it and
    `clear_partials` sweeps it;
  - it keeps its video extension, so lane C's extension ignores still apply.

  What happens to the staged file afterwards:
  - Success: the staged file is removed, and `swap_in(tmp, final, final)`
    keeps the locked-file handling for anything already at `final`.
  - Conversion failure: `_unstage` puts the file back under its own name
    first, so `_fail_clip` still disowns it to `.failed` (YTDL-3 evidence
    kept). The probe-failed "kept as downloaded" case is restored the same
    way.
  - Stop: the file is left staged, and `_cleanup_current` deletes it. That
    also closes the medium bug-comp-ytdl-2 shape (a stop mid-conversion used
    to leave a convert-needed original as a finished clip).
  - Rename refused (for example a scanner holding the file): the conversion
    runs in place, the old behaviour, with a warning.

  Code: `companion/src/ccsync_companion/ytdl_executor.py:1498-1513`
  (constant), `:1643` (`staged_source_name`), `:2537-2548` (staging),
  `:2570-2621` (outcomes + `_unstage`).

  Residual: the window between landing and the end of the ffprobe run is
  unchanged. The probe is bounded by `PROBE_TIMEOUT_SECONDS` (120 s) and is
  normally sub-second, and the file is freshly stamped by `--no-mtime`.
  Staging before the probe would close that too, but it would put two renames
  on every clip, including the common H.264 case. I judged that not worth it.
- Regression test: `companion/tests/test_ytdl_executor.py::test_a_long_conversion_never_leaves_the_original_under_its_deliverable_name`.
  The test ages the folder past every 120 s gate while ffmpeg "runs", then
  asserts that lane A's own predicate (`path_matches_lane_a_filter`) and the
  importer's `_is_clip_name` accept nothing. On HEAD the deliverable
  `[id].mp4` is present and accepted. Also
  `::test_a_stop_mid_conversion_leaves_no_convert_needed_clip_behind`, which
  fails on HEAD with the same leftover. `::test_a_failed_conversion_still_disowns_the_original_under_its_own_name`
  guards the `.failed` path and passes on both, by design. Two existing tests
  were updated for the intended change: `test_a_vp9_opus_clip_is_converted_here_under_its_original_name`
  (ffmpeg's `-i` is now the staged name) and `test_a_conversion_note_joins_the_truncation_note`.
  The original can no longer be the file that is held open, so a refused
  replace now takes swap_in's `.converted [id]` rung.
- Other tests run: `companion/.venv python -m pytest tests/test_ytdl_executor.py tests/test_youtube_import.py tests/test_rclone_filters.py` -> all pass (180 in the executor file);
  `server/` (Git Bash, dashboard venv) `pytest tests/test_cross_component.py` -> 70 passed.
- Skew / deploy order: companion only. No wire change. The staged name never
  leaves the machine, because lane A, lane C and the importer all exclude it.
  No ordering constraint with the dashboard.
- OWED: none after the review round (below). The NAS worker's half was
  first written here as owed to webapps-ops; nobody picked it up, so it is
  now fixed in this group (see the review round).
- Review round (2026-09-24, adversarial reviewer: "the whole path is NOT
  closed"): the reviewer is right.
  - The NAS worker's `ytdl/web/ytdlweb/vendor/downloader.py`
    `ensure_edit_ready` re-encoded the landed `<title> [id].<ext>` in place.
    For the whole conversion the original sat on the NAS under its
    deliverable name, where the base rig's importer reads it over the share,
    settles it after 120 s, and files it. The swap then delivered a second
    clip. I traced it the same way as the companion half.
  - Ownership: `ytdl/web/*` belongs to webapps-ops. That builder's diff
    touches only `worker.py`, and none of its findings name `downloader.py`,
    so the edit cannot collide. I made it here, as the reviewer and the
    orchestrator asked. `server/tests/test_cross_component.py` (also
    webapps-ops' group) needed a matching three-line change.
  - Fix: `downloader.py` gets `SOURCE_STAGING_SUFFIX`, `staged_source_name`
    (the same spelling as the companion's, pinned by the cross-component
    test), and staging in `ensure_edit_ready` before the ffmpeg `-i`. The
    outcomes match the companion's:
    - success: the staged file is removed and `_swap_in(tmp, final, final)`
      runs;
    - ffmpeg failure: `unstage()` runs before the RuntimeError, so the
      worker's `_disown_output` still produces `.failed`;
    - probe-failed guess that fails, or no ffmpeg (FileNotFoundError):
      unstaged, then delivered as downloaded;
    - any other exception: unstaged and re-raised;
    - rename refused: converts in place, the old behaviour;
    - container kill: the staged file stays behind. Its stem ends in
      `.editready`, so `worker._sweepable` is true. `_clear_partials` removes
      it on the next attempt at the id, `_sweep_stale` removes it after a
      day, and `_landed_file` never reads it as the clip.
    `worker.py` needed no change.
  - Regression test: `ytdl/web/tests/test_bug_hunt_2026_09_24_comp_media.py`.
    `::test_a_long_conversion_never_leaves_the_original_under_its_deliverable_name[.mp4|.webm]`
    fails on HEAD's `downloader.py`. That was run in a scratch copy of the
    ytdl/web tree with HEAD's downloader and only a `staged_source_name`
    helper appended, and it failed with
    `{'during': ['...[aaaaaaaaaaa].mp4']} == {'during': [], 'landed': None}`.
    The other four tests are guards (failure -> `.failed`, a guess delivered
    as downloaded, no ffmpeg, a killed staged file is litter) and pass on
    both. `server/tests/test_cross_component.py::test_the_companion_runs_the_vendored_ffmpeg_command`
    now builds the companion argv from the staged name and asserts that the
    two sides' staged names are equal.
  - Minor residual (1), fixed: a stop that lands during the companion's
    ffprobe now moves the unchecked download onto the staging name before
    returning, so `_cleanup_current` sweeps it (`ytdl_executor.py`, the
    `_should_stop()` after the probe).
    `companion/tests/test_ytdl_executor.py::test_a_stop_during_the_probe_leaves_no_unchecked_clip_behind`
    fails without that hunk. That was run against a scratch copy of the
    current package with only the hunk removed, and it failed with
    `['Some Channe...aaaaaaa].mp4'] == []`. A stop that lands in the instant
    between yt-dlp exiting 0 and the `_should_stop()` right after it has the
    same shape. It is pre-existing and not widened here.
  - Minor residual (2), accepted: a staged file from a crash-abandoned job,
    where no later attempt at that id ever runs on this machine, is never
    swept on the companion. Lane A, lane C and the importer all exclude it,
    so the only cost is local disk. The NAS side has `_sweep_stale`.
  - Tests run: `ytdl/web` (dashboard venv) `pytest tests/test_bug_hunt_2026_09_24_comp_media.py tests/test_downloader.py tests/test_worker.py tests/test_local_download.py tests/test_no_em_dash.py` -> 269 passed.
    `server/` (Git Bash) `pytest tests/test_cross_component.py` -> 70 passed.
    `companion` `pytest tests/test_ytdl_executor.py tests/test_youtube_import.py tests/test_rclone_filters.py tests/test_bug_hunt_2026_09_24_comp_media.py` -> 352 passed.
  - Skew / deploy order: no wire change on either side. The dashboard image
    (the NAS worker) and the companion can ship in either order, because each
    side's staging only uses names the other side's rules already exclude.
- Round 2 review (2026-09-25):
  - Reviewer's new defect (confirmed): the proxy scanner queued the staged
    source for a proxy. `proxy_scan.scan_project` picked candidates by
    `VIDEO_EXTS` and the settle age only. Once a NAS or companion conversion
    ran longer than 120 s plus a scan tick,
    `<title> [id].source.editready.webm` was a `preview` candidate. Its proxy,
    `Proxy/<title> [id].source.editready.mp4`, has no original. Lane B's
    `+ **/Proxy/**` would carry it to every editor, and nothing removes it.
    The converted final would also be encoded a second time.
    Fix: `companion/src/ccsync_companion/proxy_scan.py`, in the walk loop
    right after the `VIDEO_EXTS` test. It skips every basename that matches
    `rclone_lane.YTDL_WORK_EXCLUDE_RES`, the compiled form of lane A's
    `YTDL_WORK_EXCLUDE_RULES`. The scanner therefore uses the lanes' own
    definition and cannot drift from it. This follows the loop's own rule:
    if a lane would not carry a file, its absence downstream is not a proxy
    gap. The skip also covers `.editready`, `.original`, `.fNNN` and `.temp`
    files, which HEAD would have proxied too.
    Regression tests in `companion/tests/test_proxy_scan.py`:
    `::test_ytdl_work_files_are_never_queued` has five cases, including
    `.source.editready.webm` aged 600 s. A guard,
    `::test_a_finished_youtube_clip_beside_its_work_file_is_still_queued`,
    checks that a finished clip next to a work file is still queued. I ran
    all six in a scratch copy of the package with HEAD's `proxy_scan.py`, and
    all six failed (missing=1 or 2).
  - Reviewer's minor point (confirmed): on the success path, the staged
    original could stay on disk permanently. If `os.remove(staged)` failed,
    the log said "swept on the next attempt", but a clip that succeeded never
    gets another attempt on this machine.
    Fix: `ytdl_executor.py`, new `DownloadJob._remove_staged`. It makes 4
    tries, 0.5 s apart, through `deps.sleep`, because a thumbnailer or an AV
    scan lets go quickly. If the file is still held after that:
    - a WARNING says that nothing will retry it, and how many bytes stay;
    - the clip row's note names the file and its size, and says that it
      syncs nowhere and can be deleted, in YT-6's reporting style. The note
      has no em dash.
    The file keeps its staged name, so every lane and the importer still
    exclude it.
    Regression tests in `test_ytdl_executor.py`:
    `::test_a_held_staged_original_is_retried_then_named_on_the_row` and
    `::test_a_briefly_held_staged_original_is_still_removed`. I ran both
    against a scratch copy with only this hunk reverted to round 1's single
    `os.remove`. Both failed: the note was empty, and the staged file was
    still there after a one-time refusal.
  - Tests run: `companion` `pytest tests/test_proxy_scan.py tests/test_ytdl_executor.py tests/test_bug_hunt_2026_09_24_comp_media.py tests/test_proxy_gen.py`: 403 passed.
  - Skew: no wire change. The new note text rides the existing `note` field.
    Neither change runs on a startup or reporter thread. The retry sleeps at
    most 1.5 s, on the download job's own thread.

## bug-comp-media-1 - Media jobs and proxy generation spawn the bare name "ffmpeg", so a machine whose only ffmpeg is the managed sidecar copy advertises the capability and then fails every encode
- Mechanism (as you traced it): confirmed, and it is wider than the finding.
  `ffmpeg_available` (which `capabilities._ffmpeg` reports from) falls back to
  `sidecar_tools.managed_path("ffmpeg")` when PATH has no ffmpeg. The argv
  builders, though, put the raw config value (`"ffmpeg"`) at argv[0], and
  Popen searches PATH only. So the machine advertises ffmpeg, claims the job,
  and gets WinError 2. Four spawners were affected:
  - `jobs_media._popen`: the three fleet media recipes.
  - `proxy_gen._default_popen`: the encode and verify steps.
  - `broll_ingest_media.run_ffmpeg`: every b-roll proxy, sprite, poster,
    thumb, scene and frame. This is the hunter's out-of-territory note on
    `broll_ingest.py:750`, confirmed.
  - `ffmpeg_tools.detect_encoders`: a managed-only machine reported
    `nvenc: false` to the scheduler and encoded on the CPU for ever.

  ffprobe was never affected, because `ffprobe_for` resolves.
- Fix: one resolver at the spawn. `ffmpeg_tools.spawn_argv(cmd)` replaces
  argv[0] with `_resolve_binary(argv[0]) or argv[0]`, which is exactly the
  lookup `ffmpeg_available` does. `ffmpeg_available` itself now calls
  `_resolve_binary`, so the capability and the spawn cannot drift apart. The
  resolution happens at the spawn, not in the argv builders or at startup,
  for two reasons:
  - the indexer-parity tests pin the builders' argv flag for flag;
  - the generator must start working the moment the sidecar lands, with no
    restart.

  An unresolvable name passes through unchanged, so the spawn fails with the
  real OS error.

  Code:
  - `companion/src/ccsync_companion/ffmpeg_tools.py:144-162` (`spawn_argv`),
    `:221-226` (`ffmpeg_available`), `:302-304` (`detect_encoders`)
  - `jobs_media.py:469-472`
  - `proxy_gen.py:326-329`
  - `broll_ingest_media.py:403-406`

  music_clap_sidecar and ytdl_executor already resolved and are unchanged.
- Regression test: `companion/tests/test_bug_hunt_2026_09_24_comp_media.py`. PATH is stripped and a managed `ffmpeg.exe` sits in a tmp tools dir.
  - `::test_a_media_job_spawns_the_ffmpeg_the_capability_report_advertised`
    asserts that the capability's resolved binary and the Popen argv[0] are
    the same managed path. On HEAD the argv[0] is `['ffmpeg', 'ffmpeg']`.
  - `::test_the_proxy_generator_spawns_the_managed_ffmpeg`,
    `::test_broll_ingest_spawns_the_managed_ffmpeg` and
    `::test_nvenc_is_detected_through_the_managed_ffmpeg` each fail on HEAD
    with argv[0] `'ffmpeg'`.
  - `::test_an_explicit_path_that_is_missing_is_not_swapped_for_another_binary`
    checks the no-substitution rule.

  Two existing tests pinned argv[0] == "ffmpeg" on a machine that has one on
  PATH. They now neutralise the resolution or key on argv[1:]:
  `test_ffmpeg_tools.py::test_detect_encoders_parses_the_listing` and
  `test_proxy_gen.py::test_stdout_is_piped_only_when_progress_was_asked_for`.
- Other tests run: `companion/.venv python -m pytest tests/test_ffmpeg_tools.py tests/test_jobs_media.py tests/test_jobs_runner.py tests/test_jobs_phase4.py tests/test_jobs_resilience.py tests/test_jobs_runner_visibility.py tests/test_proxy_gen.py tests/test_broll_ingest_media.py tests/test_broll_ingest.py tests/test_capabilities.py tests/test_music_clap_sidecar.py tests/test_bug_hunt_2026_09_18_companion_media.py tests/test_bug_hunt_2026_09_18b_companion_media.py` -> all pass.
- Skew / deploy order: companion only. No wire change. The capability report
  is unchanged for every machine except a managed-only machine with a GPU,
  which now truthfully reports `nvenc: true`.
- OWED: none.
- Review round (2026-09-24): the adversarial reviewer raised nothing on this
  finding. No change.

## bug-comp-broll-1 - A batch holding two clips with the same name indexes the FIRST clip twice and never the second
- Mechanism (as you traced it): only the companion keys on the name.
  - The page (`ingest.js`) gives every item a unique `local_id`, and sends
    prepare and create in the same relative order. It does not need to
    dedupe names.
  - The server allocates `C0001` / `C0001_2` correctly. It does not store
    `local_id`, so the claim manifest cannot echo it, but nothing on that
    side is wrong.
  - `BrollIngestor._item_from_manifest` paired each manifest row with a
    staged file by `(orig_name, rel_dir)`, first match wins, one row at a
    time. Both rows therefore got card A's path.
  - Line ~2292 (`item["hash"] = item.get("hash") or ...`) keeps the
    manifest's hash and never checks it against the bytes, so nothing
    failed.
- Fix: the whole manifest is matched at once
  (`broll_ingest.match_manifest_rows`). Each staged file is used at most
  once, in three passes, strongest evidence first:
  1. content hash, when both sides have one;
  2. name + rel_dir + size;
  3. name + rel_dir, the old key, now consuming.

  A candidate whose known hash differs from the row's known hash is never
  paired at any tier. Rows are taken in manifest `ord` order and candidates
  in staging `ord` order, so a re-issued claim after a restart pairs
  identically.

  `BrollIngestor._items_from_manifest` replaces the per-row list
  comprehension in `run`. `_item_from_manifest` takes the paired
  `candidate`, and still matches alone when called without one. MusicIngestor
  overrides `_item_from_manifest` with its own name-only matcher and no
  `candidate` parameter, so it deliberately keeps its old per-row path (see
  OWED).

  Code: `companion/src/ccsync_companion/broll_ingest.py:71` (sentinel),
  `:1894-1930` (`_items_from_manifest`, `_item_from_manifest`), `:3952-4017`
  (`match_manifest_rows`, `_hash_compatible`).

  No server or page change was needed. Carrying `local_id` through the
  ingest_items table would be the belt-and-braces key, but it needs a b-roll
  schema migration in three trees. The hash and size tiers already separate
  two different camera files.

  Side effect: the hash tier also pairs a row whose rel_dir the server
  rewrote (bug-comp-broll-2, medium, not in this group's list), whenever
  both hashes are known. It does not cover the no-hash case of that finding.
- Regression test: `companion/tests/test_bug_hunt_2026_09_24_comp_media.py`.
  - `::test_two_same_named_clips_are_each_indexed_from_their_own_file[no-hashes-yet|page-relayed-hashes]`
    runs the real `BrollIngestor.prepare` then `run` against a FakeServer
    manifest holding two `PRIVATE/M4ROOT/CLIP/C0001.MP4` rows. On HEAD both
    variants fail with `['cardA.mp4', 'cardA.mp4']`.
  - `::test_the_row_order_is_reversed_and_the_bytes_still_decide` fails on
    HEAD with `['cardA.mp4', 'cardA.mp4']`.
  - `::test_indistinguishable_rows_still_never_share_one_file` and
    `::test_a_file_with_a_different_known_hash_is_never_paired` test the
    pure matcher.
- Other tests run: `companion/.venv python -m pytest tests/test_broll_ingest.py tests/test_music_ingest.py tests/test_bug_hunt_2026_09_11b_comp_broll_music.py tests/test_bug_hunt_2026_09_24_comp_media.py` -> all pass.
- Skew / deploy order: companion only. The manifest shape is unchanged. The
  matcher reads only keys that every server version already sends
  (`orig_name`, `rel_dir`, `size_bytes`, `hash`, `ord`).
- OWED: orchestrator (no group owns it). `companion/src/ccsync_companion/music_ingest.py:203-214`
  `MusicIngestor._item_from_manifest` has the same defect: name only, first
  match, and the file's own comment names `theme.wav` twice. The fix is to
  drop the override's matching loop and implement `_items_from_manifest`
  with `match_manifest_rows`, keyed on `content_hash` and name with no
  rel_dir. It needs a test like the one above using the music doubles.
  `_staging_holding` (broll_ingest.py) still answers "does this machine hold
  these files" by name + rel_dir. That is a yes/no used only to refuse a
  claim with no staging id, so it is left alone.
- Review round (2026-09-24): the adversarial reviewer raised nothing on this
  finding. No change, and the music_ingest item stays OWED as above.

## Round 2 (owed-music)

### bug-comp-broll-1, music half: `MusicIngestor._item_from_manifest` (2026-09-25)

- Traced: the music page stages a drop through `POST /music/ingest/prepare`
  with `{local_id, name, size, source, path}` (no rel_dir, so every staged
  entry has `rel_dir: ""`), then creates the batch with
  `{local_id, name, size, duration, content_hash, source}`. The server's claim
  manifest (`musicweb/ingest_batches.py` claim) sends back per item `uid, ord,
  orig_name, size_bytes, content_hash, ...` and no local_id. HEAD's
  `_item_from_manifest` looped the staged items and took the first whose
  `name == orig_name`, so two different `theme.wav` in one drop both got the
  first file: it was embedded and uploaded twice (as `theme.wav` and
  `theme (2).wav`, the server allocating the second name) and the second
  track never was. Confirmed as described.
- A difference from b-roll the fix had to handle: the server overwrites
  `ingest_items.content_hash` with the TRANSCODED .mp3's digest at status and
  at result (`COALESCE(?, content_hash)`), while the staged entry keeps the
  original .ogg's digest and `size_bytes` stays the original's. Feeding the
  manifest hash straight into `match_manifest_rows` would trip its "known and
  different hash means another file" veto on a re-claim (RETRY FAILED, a
  tray restart) of any transcoded track and strip its local path at every
  tier. So the manifest hash is passed to the matcher only when it equals a
  hash staged on this machine; otherwise it is no evidence either way.
- Fix (`companion/src/ccsync_companion/music_ingest.py`):
  `MusicIngestor._items_from_manifest` overrides the base and matches the
  whole manifest at once through `broll_ingest.match_manifest_rows` (reused,
  not copied), via a new `_match_staged` that maps `content_hash` to `hash`
  (filtered as above), forces `rel_dir` to `""` on both sides and keeps
  `size_bytes` and `ord`. `_item_from_manifest` now takes the base's
  `candidate=broll_ingest._UNMATCHED` keyword; called alone it matches the
  one row through the same helper. The item's own `hash` still comes from
  the manifest row, unchanged. `broll_ingest.py` was not edited.
- Regression tests (`companion/tests/test_music_ingest.py`, music doubles,
  end of file):
  - `test_two_tracks_with_one_name_are_two_files_by_size` (staged in the
    reverse order, sizes decide),
  - `test_two_tracks_with_one_name_and_size_still_get_one_file_each`,
  - `test_the_content_hash_decides_between_two_identical_names`,
  - `test_both_same_named_tracks_are_crunched_and_uploaded` (end to end
    through `tick()`: both staged files are embedded).
  How I know they fail on HEAD: I put `git show HEAD:` of music_ingest.py in
  place (fixed copy saved in the scratchpad), ran the file: those 4 FAILED,
  38 passed; restored the fixed file (diff stat re-checked).
  `test_a_reclaimed_transcoded_track_keeps_its_file` passes on HEAD by
  design: it guards the hash-veto trap described above, which a naive reuse
  of the matcher would have introduced.
- Tests run: `companion/.venv python -m pytest tests/test_music_ingest.py
  tests/test_bug_hunt_2026_09_11_comp_broll_music.py
  tests/test_bug_hunt_2026_09_11b_comp_broll_music.py
  tests/test_music_server.py tests/test_music_worker.py` -> 196 passed.
- Skew: companion only; no wire change. Reads only keys every music server
  version already sends.
- OWED (broll_ingest.py, not mine to edit): the docstring of
  `BrollIngestor._items_from_manifest` (around line 1907) still says the
  music subclass pairs row by row by name alone; it no longer does, since
  the override replaces that method. The `type(self)._item_from_manifest is
  not BrollIngestor._item_from_manifest` branch is now unreached by music
  (harmless). `_staging_holding` still answers by name + rel_dir, which is
  right for music too (rel_dir "" both sides).
