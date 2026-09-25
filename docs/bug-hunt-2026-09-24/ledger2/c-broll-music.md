# Wave 2 ledger: c-broll-music (chunk 1 of 1, 2026-09-25)

Files touched (all this group's): `companion/src/ccsync_companion/broll_ingest.py`,
`broll_standins.py`, `broll_fetch.py`, `broll_server.py`, `music_server.py`,
`music_worker.py`, `music_clap_sidecar.py`; new test file
`companion/tests/test_bug_hunt_2026_09_24_w2_c-broll-music.py` (25 tests; 20 fail
on HEAD, 5 are guards that pass on both). No existing test file edited.

Tests run (companion venv, from `companion/`):
`.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_c-broll-music.py`
-> 25 passed; the same file against a `git archive HEAD` copy of `companion/src`
-> 20 failed, 5 passed. Every suite that exercises the changed functions
(test_broll_fetch, test_broll_ingest, test_broll_ingest_media,
test_broll_insert_tiers, test_broll_proxy_upgrade, test_broll_server,
test_broll_standins, test_broll_wiring, test_bug_hunt_2026_09_11_comp_broll_music,
test_bug_hunt_2026_09_11b_comp_broll_music, test_bug_hunt_2026_09_18_companion,
test_bug_hunt_2026_09_18_companion_media, test_bug_hunt_2026_09_18b_companion_media,
test_bug_hunt_2026_09_18b_mediums_broll, test_bug_hunt_2026_09_24_comp_media,
test_music_clap_sidecar, test_music_ingest, test_music_server, test_music_worker,
test_proxy_relink_standins, and the new file) -> 854 passed, 1 skipped.

All changes are companion-only. No wire key is required by either side, no
schema change. Ships with the next companion build; no deploy order.

## bug-comp-broll-2 - "keep sub-folders" unticked (or a folder safe_name changes) fails every clip from a sub-folder
- Status: FIXED
- Verified as: CONFIRMED medium (med-03). Re-checked after the highs wave: `match_manifest_rows` (bug-comp-broll-1's fix) pairs by hash first, so a drop whose hashes arrived is already fine, but tiers 2 and 3 still compared rel_dir exactly. `broll/web/app/ingest_batches.create_batch` blanks rel_dir when keep_subfolders is off and runs each component through `safe_name`; the companion's `_clean_rel_dir` does neither. With no hash on either side, `local_path` was "" and `_crunch_item` failed the item.
- Fix: `broll_ingest.match_manifest_rows` gains two last tiers that ignore the folder: name + size, then name alone. They run only after every exact-folder tier has consumed its file, keep the `_hash_compatible` veto and the ord order. Docstring updated.
- Regression test: test_keep_subfolders_unticked_still_finds_the_staged_file, test_a_folder_name_safe_name_rewrote_still_finds_the_staged_file, test_the_folder_blind_tiers_pair_in_order_and_by_size_first, test_an_exact_folder_match_is_not_stolen_by_a_folder_blind_one (fail on HEAD: `None` or the wrong path); test_the_folder_blind_tiers_never_take_a_provably_different_file is a guard.
- Tests run: as above.
- Skew / deploy order: companion-only.
- OWED: none. (Optional and stronger: the broll group could store and echo the page's `local_id` in the claim manifest, and this matcher would take it as tier 0. Not needed for this finding.)

## bug-comp-broll-4 - a staged drop whose original failed once is held for ever
- Status: FIXED
- Verified as: CONFIRMED medium (med-03). `held_for_base_rig` had writers only (`_note_original_failed` -> `_hold_staging`, `_note_staging_ended`); `_note_staging_ended` returned early on a rerun because `ended_at` was set; `prune_staging` skips held entries at every age; `staging_report` counted a held drop as `finished_bytes`, so `_space_refusal` named CLEAR FINISHED STAGING.
- Fix: `broll_ingest.py`: new `_original_landed()` called when `/uploaded` with `original_uploaded=True` returns 200. It clears the item's `original_failed` and removes the name from the staging entry's held list, unless another item of the same name in the batch still owes its original. `_note_staging_ended` now re-stamps `ended_at` on a rerun and MERGES the held list rather than overwriting it, so a name held mid-run is kept. `staging_report` reports held drops as `held_bytes` (a new key, ignored by `app.ingest_staging_report`), and `_space_refusal` names held bytes in their own sentence ("kept on this computer because the archive does not have those files yet; it is released once they reach it") instead of blaming CLEAR FINISHED STAGING.
- Regression test: test_an_original_retried_to_the_archive_releases_the_hold (end to end: an original dies, the batch finishes held, RETRY FAILED uploads it, the hold is gone and `prune_staging(0)` removes the drop), test_a_hold_stays_while_a_same_named_clip_still_owes_its_original, test_held_staging_is_not_blamed_on_clear_finished_staging. All fail on HEAD (the hold is never released, `_original_landed` does not exist, `held_bytes` absent and the message names the button).
- Tests run: as above.
- Skew / deploy order: companion-only.
- OWED: none.

## bug-comp-broll-5 - every ingest encode has a fixed 15-minute ceiling
- Status: FIXED
- Verified as: CONFIRMED medium (med-03). `_run_media` never passed a timeout, so the preview and the editing proxy (libx265 10-bit on a machine without NVENC) ran under `run_ffmpeg`'s 900 s, and a timeout became "did not decode".
- Fix: `broll_ingest.encode_timeout_seconds(duration)` = max(900, proxy_gen.STUCK_FLOOR_SECONDS, duration x proxy_gen.STUCK_DURATION_FACTOR), read from proxy_gen so the two cannot drift. `_encode_verified` passes it; `_run_media(cmd, timeout=None)` offers `timeout` only to a runner whose signature takes it (the same probe as `child_sink`, via a new `_accepts_keyword`), so one-argument test doubles keep working. Stills, sprites and frames keep 900 s. The stop path is unchanged: `_kill_child` still ends the child when the editor comes back.
- Regression test: test_the_encode_ceiling_is_proxy_gens_rule, test_the_proxy_encodes_run_under_the_duration_scaled_ceiling (a 25-minute clip's encode gets 90000 s, not 900), test_a_runner_without_a_timeout_keyword_still_runs. All fail on HEAD (no such function or keyword).
- Tests run: as above.
- Skew / deploy order: companion-only.
- OWED: none.

## bug-comp-media-6 - music "insert at playhead" cannot ripple a clip that straddles the playhead
- Status: FIXED
- Verified as: CONFIRMED medium (med-04). `affected` included a clip with `GetStart() < rec < GetEnd()`; re-appended whole at start + shift it overlaps the new cue. The HEAD run of the new test shows the fake's occupied-span refusal: "insert failed; rolled back 2/2 clip(s) on A2".
- Fix: `music_worker.act_insert` refuses before anything is deleted when an affected clip starts before the playhead: "the playhead is inside a clip on A2 (frame 50 to 150), so it cannot be rippled whole. Move the playhead to a cut, or razor the clip there first, or use 'place underneath'." (no em dash). Docstring updated. Splitting the clip was not chosen: there is no razor in the scripting API, and a delete-and-re-append split would lose the clip's volume and fades, which is the rollback damage the finding names.
- Regression test: test_insert_refuses_a_clip_that_straddles_the_playhead (HEAD: deletes, fails, rolls back); test_insert_at_a_cut_still_ripples is a guard.
- Tests run: as above (test_music_worker.py all green).
- Skew / deploy order: companion-only; the page shows the worker's `error` verbatim as before.
- OWED: none.

## logic-broll-music-2 - settle_intents calls a stand-in "the real original" for any heavy original of 1080 lines or fewer
- Status: FIXED
- Verified as: CONFIRMED medium (med-11). The preview is `scale=-2:trunc(min(1080,ih)/2)*2`, never upscaled, always H.264 (`ffmpeg_tools.preview_proxy_cmd`, indexer build_proxy), so for a 1920x1080 heavy original (DNxHD, 50 Mbps H.264) the stand-in's header equals the row's geometry and `_what_landed` returned False.
- Fix: `broll_standins._what_landed`: a geometry that differs still means the stand-in. A geometry that matches means the original only when the preview of an original that size would NOT keep its geometry (`_preview_keeps_geometry`: height <= ffmpeg_tools.PROXY_HEIGHT with even sides). Where it would, a probed codec other than the preview's `h264` means the original; H.264 or unknown falls through to the job record (DONE measures, FAILED retires, None leaves the row pending, the module's existing "not guessed at" rule). `settle_intents` docstring updated.
- Regression test: test_a_1080p_h264_header_is_not_taken_for_the_original (HEAD retires the row); test_a_1080p_header_in_another_codec_is_the_original and test_a_taller_original_still_settles_by_geometry are guards.
- Tests run: as above (test_broll_standins, test_bug_hunt_2026_09_18b_companion_media green).
- Skew / deploy order: companion-only.
- OWED: none. Residual, stated plainly: a genuine 1080p H.264 original that arrived after a restart (no job record) stays a pending row, i.e. treated as a stand-in until the six-hour rule or a new insert decides. That is the under-trusting direction the probe cannot resolve; telling them apart would need the original's codec/bitrate in the page's `insert.geometry` (broll group, `routes_api._insert_object`), which is an enhancement, not needed for this fix.

## bug-comp-broll-3 - the insert's "download done" branch is unreachable; finished fetch jobs leak (downgraded to low)
- Status: FIXED
- Verified as: DOWNGRADE low (med-03): the upgrade still starts after the import and `settle_intents` usually settles the row via the leaked DONE job; what remains is a registry leak, a sizeless row after restart-with-no-geometry, and a one-time misleading "is the share mounted?" for a deleted fetched clip. Confirmed by reading `broll_server.build_insert_response` and `broll_fetch.poll_fetch`.
- Fix: new `broll_fetch.reap_finished(dest)` pops a DONE/FAILED job (never a running one) and returns its state. `build_insert_response` calls it on the poll that finds the file in place, and when it answers DONE for a stand-in, new `broll_standins.settle_landed(path)` measures the intent row (real size, `pending_fetch=False`) before the import; the upgrade state is still set by `start_proxy_upgrade` after the import, as the verifier traced. `music_server.build_send_response` reaps the same way (the hunter's out-of-territory note: the music twin leaked identically).
- Regression test: test_the_poll_that_finds_the_file_settles_the_intent_and_pops_the_job (HEAD: row still `pending_fetch`, job still DONE), test_a_deleted_fetched_track_is_fetched_again_not_share_mounted, test_the_music_send_reaps_a_finished_job_for_a_track_in_place (HEAD: no `reap_finished`, job left behind).
- Tests run: as above (test_broll_insert_tiers, test_broll_server, test_music_server, test_broll_fetch green).
- Skew / deploy order: companion-only.
- OWED: none. ytdl_server's own fetch caller (c-ytdl) was not checked for the same shape; if it tests the file before polling, it leaks the same way and can call `broll_fetch.reap_finished`.

## bug-comp-broll-6 - the upload queue survives a batch that finishes normally
- Status: FIXED
- Verified as: real (low, unverified before). `_uploader` was set to None only in `_stop_uploads`, called from cancel and lease-lost; `_maybe_finish` never called it, and `run()` set `_upload_paused` from the claim without touching a live queue, while the heartbeat acts only on a change from that flag. Confirmed by reading `_queue`, `_new_queue`'s docstring, `run()` and the heartbeat loop.
- Fix: `_maybe_finish` calls `_stop_uploads()` after the release (every item is finished there). `run()` applies the claimed `upload_paused` to a queue that is still up via `pause_upload`. No production caller passes the constructor's `uploader`, so stopping it cannot latch a shared queue.
- Regression test: test_a_finished_batch_puts_its_upload_queue_down, test_a_claim_applies_its_pause_flag_to_a_queue_that_is_still_up (both fail on HEAD).
- Tests run: as above (test_broll_ingest, test_music_ingest green).
- Skew / deploy order: companion-only.
- OWED: none.

## bug-comp-media-7 - music ingest decodes at three times PCM size; tracks over two hours get a false duration
- Status: FIXED
- Verified as: real (low, unverified before). `decode` held the pipe's bytes, `nan_to_num`'s copy and a `.copy()` of that at once; `-t 7200` capped the decode and `duration` was the decoded count.
- Fix: `music_clap_sidecar.decode` returns `np.nan_to_num(samples, copy=True, ...)` without the extra `.copy()` (peak 2N instead of 3N; the result is still a new writable array). New `_duration_of()`: the decoded count, unless the decode reached `MAX_DECODE_SECONDS`, where the ffprobe duration is taken when it is LONGER (at the cap it is the only figure that can be right; it never shortens a count). `embed_file` uses it; its docstring notes the one exception.
- Regression test: test_decode_makes_one_copy_not_two, test_a_decode_cut_at_the_cap_takes_the_longer_probed_duration (both fail on HEAD).
- Tests run: as above (test_music_clap_sidecar green).
- Skew / deploy order: companion-only.
- OWED: none.

## bug-wire-7 - a computer whose hostname is not Latin-1 cannot make any b-roll or music ingest fleet call
- Status: PARTIAL (rest OWED)
- Verified as: real (low, unverified before). `FleetClient._headers` put `deps.machine` in `X-CCSync-Machine`; http.client encodes header values as Latin-1 and raises `UnicodeEncodeError` for `剪輯-PC` before a socket opens, on every call including the claim. Both servers skip the machine check when the header is absent (`broll/web/app/routes_fleet.py:125`, `music/web/musicweb/routes_fleet.py:90`).
- Fix: `broll_ingest.FleetClient._headers` (used by b-roll and music ingest) sends `X-CCSync-Machine` only when the name encodes as Latin-1; otherwise it sends the name percent-encoded in a new ASCII header `X-CCSync-Machine-Pct`, which today's servers ignore, so the machine check degrades to the documented older-companion behaviour (editor, lease and cancel checks still run) instead of the call raising.
- Regression test: test_a_cjk_hostname_never_reaches_http_client_as_a_header (HEAD: the header value raises on `.encode("latin-1")`); test_a_latin1_hostname_keeps_the_header_the_server_checks is a guard.
- Tests run: as above.
- Skew / deploy order: the new header is optional in both directions: an old server ignores it, and a new server must still accept the plain header and an absent one. Either side may ship first.
- OWED:
  - broll group, `broll/web/app/routes_fleet.py`: every handler that reads `x_ccsync_machine` (`_leaseholder_or_410` callers and the new release check) should also accept `X-CCSync-Machine-Pct: str | None = Header(default=None)` and use `urllib.parse.unquote(pct)` when the plain header is absent, so a CJK-named machine gets the machine check back.
  - music-ytdl group, `music/web/musicweb/routes_fleet.py`: the same for its `x_ccsync_machine` readers; and `ytdl/web/ytdlweb/routes_fleet.py` if it gains the header twin below.
  - c-ytdl group, `companion/src/ccsync_companion/ytdl_executor.py:1074` (`headers["X-CCSync-Machine"] = machine`): the same Latin-1 test, sending `X-CCSync-Machine-Pct` (percent-encoded, `safe=""`) instead when it fails; otherwise a CJK-named machine's ytdl fleet calls raise the same way.

## Owed round (2026-09-25)

Files touched: `companion/src/ccsync_companion/broll_server.py`
(`pick_ingest_sources`), and two tests appended to
`companion/tests/test_bug_hunt_2026_09_24_w2_c-broll-music.py`. Tests run
(companion venv, from `companion/`): the two new tests -> 2 passed;
`tests/test_broll_server.py -k pick` -> 6 passed. HEAD's `broll_server.py`
dropped into a scratch copy of today's `companion/src` answers a `PickerBusy`
with "the file picker could not be opened on this computer", so the first new
test fails there.

### bug-comp-ui-1 (owed by c-ui) - a busy picker is reported as a broken one
- Status: FIXED
- Verified as: c-ui's `popup.pick_media_sources` now raises `popup.PickerBusy`
  when another CCSync window holds the popup lock; `pick_ingest_sources` caught
  it in its generic `except Exception` and told the editor the picker "could
  not be opened on this computer". Both pages that call the route
  (`broll/web/static/ingest.js:700`, `music/web/static/ingest.js:509`) toast
  any message other than "cancelled", so the fix is companion-side only.
- Fix: `except popup.PickerBusy as exc: return 200, {"ok": False, "message":
  str(exc)}` before the generic branch, with a comment citing the id; the
  docstring's CORE-M3 paragraph now says popup takes the lock.
- Regression test: `test_a_busy_picker_names_the_open_window_not_a_broken_picker`
  (fails on HEAD's broll_server, see above);
  `test_a_picker_that_really_fails_still_says_so` is the guard.
- Skew / deploy order: companion only, no wire change. The route's shape
  (`{ok: false, message}`) is unchanged; only the text differs.
- OWED: none (c-app still owes `popup.set_picker_popup_lock(...)` in `app.py`
  from c-ui's ledger; until it lands PickerBusy is only raised when a caller
  passes `popup_lock`, and this branch is simply dormant).

### bug-music-ytdl-2 (owed by music-ytdl) - `--ignore-existing` for music uploads
- Status: NOT_A_DEFECT (defence in depth declined, no code change)
- Verified as: music-ytdl's server fix closes the race on both sides under
  `db.NAME_LOCK` (`claim_dest` for browser drops, `write_item_result` holding
  the lock from `allocate_name` through the commit), so a name the server hands
  a fleet item can no longer be one a browser drop took. The flag was judged
  on its own merits and would make things worse:
  1. It removes the only healing path. `verify_upload` answers a size mismatch
     with "it will be sent again"; with `--ignore-existing` the resend is a
     no-op that exits 0, the same wrong size is read back, and the item fails
     every retry for ever. A wrong-size file at our own name is reachable
     without any other writer: an rclone older than 1.63 writes SFTP uploads
     in place (no `.partial`), and nothing checks the rclone a machine
     actually has against the bootstrap's pinned 1.74.4 (the scoop path and
     a hand-set `rclone_path` bypass the pin); a verify that read a
     transient short size is the same shape.
  2. It turns an overwrite into a silent MIS-BINDING when the foreign file
     happens to have our size (lsjson is size-only, no hashes on this
     remote): rclone skips, verification passes, and the server marks the
     item live with its embedding describing audio that is not in the file.
     A loud overwrite is easier to find than that.
  3. The retry-after-a-landed-upload case (bytes landed, `uploaded` call
     lost) already works without the flag: the resend rewrites identical
     bytes. So the flag buys nothing there either.
  If a guard is ever wanted, the right one is server-side: have
  `mark_uploaded` compare the landed file's size (and, for music, a cheap
  hash) against the item's recorded transcode, which it owns; that is
  music-ytdl's file, and nobody needs it after this wave's NAME_LOCK fix.
- Regression test: none (no change).
- OWED: none


# Owed round 3 (2026-09-25)

## ui-copy (owed from c-ui's widened scan) - README_SNIPPET said "the sync lanes"
- Status: FIXED
- Verified as: `broll_server.README_SNIPPET` (written beside the editor's b-roll config) said "(over the same rclone remote the sync lanes use)", and the plural-aware scan failed on broll_server.py for it. It also had a pair of typewriter dashes around "it is what the YouTube downloader page's download history opens a folder from".
- Fix: broll_server.py README_SNIPPET now says "(over the same rclone remote that upload and proxy download use)". The dash pair was rewritten with a colon and a comma, and a comment above the constant cites this round.
- Regression test: `companion/tests/test_bug_hunt_2026_09_24_w2_c-app.py::test_the_broll_readme_says_upload_and_proxy_download` fails on HEAD. It sits in c-app's file because it was written in the same change as that group's item. `test_sweep_2026_09_04_copy.py::test_no_retired_word_in_a_sentence_an_editor_reads[broll_server.py]` failed before and passes now.
- Tests run: `companion\.venv\Scripts\python.exe -m pytest tests/test_broll_server.py -q` -> 194 passed; `tests/test_sweep_2026_09_04_copy.py` -> pass.
- Skew / deploy order: none. The file is written only when it is created.
- OWED: none
