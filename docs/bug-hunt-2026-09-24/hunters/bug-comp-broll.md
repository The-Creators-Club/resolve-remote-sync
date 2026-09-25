# bug-comp-broll - companion b-roll loopback, insert/stand-ins/fetch, ingest orchestrator, uploads, VLM sidecar, loopback guard
Files read (approximate coverage): loopback_guard.py (all), broll_server.py (~85%: config, translation, insert plan, stand-in upgrade, ingest capabilities, handler), broll_fetch.py (all), broll_standins.py (all), broll_upload.py (all), broll_ingest.py (~55%: prepare/upload_slot/note_upload/retry/progress/thumb/run/_item_from_manifest/reclaim/tick/drain/crunch/encode/uploads/pump/finish/staging retention), broll_ingest_media.py (all), broll_vlm_sidecar.py (~50%), broll_vlm/* (not read). Wire partners read: broll/web/static/ingest.js (prepare, upload, create batch), broll/web/app/ingest_batches.py (create_batch, claim manifest, _clean_rel_dir), archive_names.safe_name, music_ingest._item_from_manifest.
Tests/probes run: three ad-hoc snippets from companion\.venv against temp dirs (no live state): `_item_from_manifest` matching (probe1), `build_insert_response` + real `poll_fetch` with a runner seam (probe2, probe3). No suite runs.

## Findings

### bug-comp-broll-1 - A batch holding two clips with the same name indexes the FIRST clip twice and never the second
- Severity: high
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/broll_ingest.py:1891-1901 (`_item_from_manifest`); broll/web/static/ingest.js:438-463 (drops accumulate), broll/web/app/ingest_batches.py:569 (local_id not stored)
- What: the claim manifest carries no local_id, so the companion pairs each manifest row with a staged file by `(orig_name, rel_dir)` and takes the first match. Two staged items with the same name and rel_dir (two cards dropped one after the other, both with `C0001.MP4` at the top level - the page appends drops into one batch and nothing dedupes names) both resolve to the first item's `local_path`, while the second row keeps its own `hash`.
- Failure scenario: editor drops card A's C0001.MP4, then card B's C0001.MP4, runs the batch. The server allocates `C0001` and `C0001_2`; the companion proxies, describes and uploads card A's bytes under BOTH names (the `_2` row carrying card B's hash), card B is never indexed, and its staged copy is later pruned by retention. Archive holds a duplicate, the clip the editor wanted is gone, nothing reports a failure.
- Evidence: probe1: two staging items `C0001.MP4`/`""` at `S/i1.mp4` and `S/i2.mp4`; manifest rows with hash aaa and bbb both came back `local_path='S/i1.mp4'`.
- Ledger: new
- Suggested fix: store and echo the page's `local_id` on `ingest_items` (or have the claim carry it) and match on it; failing that, match on hash first and consume each staging candidate at most once.

### bug-comp-broll-2 - "keep sub-folders" unticked (or a folder name safe_name changes) fails every clip from a sub-folder with "not on this computer any more"
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/broll_ingest.py:1897-1898 and :2282-2285; broll/web/app/ingest_batches.py:572-575 (rel_dir blanked at create), :244-254 (`_clean_rel_dir` runs `safe_name` per component)
- What: the server blanks `rel_dir` when keep_subfolders is off and otherwise rewrites each component through `safe_name` (forbidden chars replaced, trailing ". " stripped, truncation), while the staging entry keeps the page's raw rel_dir (companion `_clean_rel_dir` only drops `.`/`..` and caps at 255). The exact string compare then finds no candidate, `local_path` is "", and `_crunch_item` fails the item. retry-failed repeats it identically.
- Failure scenario: folder drop `Shoot/Day1/*.MP4` with "keep sub-folders" unticked -> every clip fails at the first stage with "the source file is not on this computer any more" while the files sit in staging. Same for a folder called `Day 1.` or `A:B` with the box ticked.
- Evidence: probe1: staging `rel_dir 'Day1'` vs manifest `''` -> `local_path ''`; staging `'Shoot A.'` vs manifest `'Shoot A'` -> `''`.
- Ledger: new (same matching function as bug-comp-broll-1)
- Suggested fix: the same fix as -1 (match on an id the server echoes), which removes the dependence on the server's rewritten rel_dir entirely.

### bug-comp-broll-3 - The insert's "download done" branch is effectively unreachable: finished fetch jobs leak in the registry, and the stand-in row is never rewritten before the import
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/broll_server.py:1155 and :1177 (`if not insert_path.is_file()` gates the whole fetch block), :1284-1314; broll_fetch.py:452-460 (terminal states popped only by a later poll)
- What: rclone renames the file into place before `_run_job` flips the job to DONE, and every page re-POST checks `is_file()` first, so the poll that would read DONE finds the file and skips the fetch block. Three things follow: the DONE job is never popped (one per fetched clip, for the life of the process); for a stand-in, the documented "BEFORE the import, always" rewrite (real size, `pending_fetch=False`, `upgrade=pending`) never runs, so the clip is imported while its ledger row is still a sizeless intent; and a later re-insert of that path after the file is gone reads the stale DONE, answers "file not found ... is the share mounted?" and, for a stand-in, `forget`s the row.
- Failure scenario: a remote editor sends a heavy clip; the stand-in lands and is imported, and its row stays `size: None, pending_fetch: True, upgrade: None`. If the dashboard sent no geometry and the companion restarts before the 120 s `settle_intents` pass, `job_state` answers None for ever, so the row can never be settled: `is_standin` stays True even after the real 6K original arrives, and the preview goes on being treated as the clip. Separately, deleting any fetched clip and pressing Send to Resolve again fails once with a misleading "is the share mounted?".
- Evidence: probe2: poll 1 `downloading`, poll 2 `inserted`, registry still `{...clip.mov: 'done'}`, file deleted, poll 3 `file not found ... is the share mounted?`. probe3 (stand-in body): after a successful insert the row is `{'size': None, 'pending_fetch': True, 'upgrade': None, 'geometry': None}`.
- Ledger: related to CR-288 / proxy-tiers-1 (the intent row design assumes the DONE rewrite runs)
- Suggested fix: in `build_insert_response`, when `local_path` exists and the ledger row is still `pending_fetch`, settle it right there (measure size, set upgrade) before the import; and have `poll_fetch` (or the insert) pop a terminal job whose dest already exists, instead of waiting for a poll that never comes.

### bug-comp-broll-4 - A staged drop whose original failed once is held for ever, even after the original is uploaded, and the disk-full message sends the editor to a button that cannot free it
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/broll_ingest.py:3521-3522 (`_note_original_failed` -> `_hold_staging`), :3634-3651, :3704-3714 (`prune_staging` skips any held entry), :3677-3678 + :3562-3565 (`staging_report` counts it as finished and `_space_refusal` names CLEAR FINISHED STAGING)
- What: `held_for_base_rig` is only ever appended to; nothing clears it when retry-failed later uploads the original, and nothing clears it on the rerun batch's finish (`_note_staging_ended` returns early because `ended_at` is already set). A held entry is skipped by both the retention sweep and CLEAR FINISHED STAGING.
- Failure scenario: a 150 GB drop has one clip whose original upload failed 4 times (link dropped); the editor presses retry and it succeeds. The whole 150 GB staging folder stays in the archive's `.ingest` for ever. When the disk fills, the next drop is refused with "... GB of that drive is finished b-roll staging: ... use CLEAR FINISHED STAGING", which removes nothing.
- Evidence: read-through; `grep held_for_base_rig` shows writers at :3632 and :3650 only, no remover.
- Ledger: new
- Suggested fix: drop the name from `held_for_base_rig` when an item with `original_failed` finally posts `/uploaded` with the original, and re-stamp `ended_at` when a rerun batch on the same staging id finishes; count held bytes separately in `staging_report` so the message does not name the wrong button.

### bug-comp-broll-5 - Every ingest encode has a fixed 15-minute ceiling, so a long clip on a CPU-only machine loses its proxy (or its whole item)
- Severity: medium
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/broll_ingest_media.py:376-421 (`RUN_TIMEOUT_SECONDS = 900` default of `run_ffmpeg`), broll_ingest.py:3357-3370 (`_run_media` never passes a timeout), :2492-2531
- What: the preview (required) and editing-proxy (HEVC Main-10, proxy_gen's recipe) encodes both run under the flat 900 s timeout; a timeout becomes `UnreadableMediaError` -> return code 1 -> "did not decode". proxy_gen runs the SAME `own_proxy_cmd` with a ceiling of `max(1800 s, duration x 60)` because encodes of long sources legitimately take longer. The comment on `MEDIA_TIMEOUT_SECONDS` ("long enough for a 40 GB original") describes a copy, not an encode.
- Failure scenario: a Mac or AMD machine (no NVENC, CPU pass only) ingests a 25-minute 4K clip; libx265 10-bit at ~20 fps needs ~30 min. Both passes are killed at 15 min, the clip gets `edit_proxy_reason = "the editing proxy did not decode"` and remote editors cut on the 1080p preview; a slow enough source fails the preview too and the item is failed after an hour of the editor's evening.
- Evidence: read-through of both timeout paths; not measured on hardware.
- Ledger: new
- Suggested fix: pass a duration-scaled timeout for the two encode calls (reuse proxy_gen's `max(STUCK_FLOOR_SECONDS, duration x STUCK_DURATION_FACTOR)`), keeping 900 s for stills and frames.

### bug-comp-broll-6 - The upload queue survives a batch that finishes normally, carrying its paused state and done/failed ledger into the next batch
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/broll_ingest.py:3252-3295 (`_maybe_finish` never drops `_uploader`), :2767-2788, :1843-1844 and :3345-3346
- What: `_new_queue`'s docstring says a queue is built once per batch so a rerun of the same batch does not see the old ledger, but only cancel/lease-lost call `_stop_uploads`. After a normal finish the next `run()` reuses the old queue: its `_done`/`_failed` lists still hold the previous run's rels, and if it was paused, `run()` sets `_upload_paused` from the claim without resuming it, and the heartbeat compares against that already-updated flag, so it never calls `pause_upload(False)`.
- Failure scenario: retry-failed on a batch whose original upload failed: the first pump sees the stale failure for that rel and burns an upload attempt before any new rclone runs; the page's upload counters keep counting the previous batch. If the queue was paused when a batch ended, the next batch's uploads never start and its items sit in `uploading` with the lease heartbeated.
- Evidence: read-through; `_uploader` is set to None only in `_stop_uploads`.
- Ledger: related to comp-loopback-1 (fixed for cancel only)
- Suggested fix: call `_stop_uploads()` (or reset `_uploader = None` once the queue is idle) in `_maybe_finish`, and apply the claimed `upload_paused` to any live queue in `run()`.

## Coverage note
Not read: broll_vlm/* (compact_format, contract, local_models, local_runtime, local_vlm), the describe/frames half of broll_ingest (`_make_frames`, `_describe`, `_stage`, status/progress model), and the music overrides beyond `_item_from_manifest`. The loopback envelope (Host, Origin, token, content type, PUT body limits, share/rel containment) was read in full and nothing wrong was found there.

## OUT OF TERRITORY
- companion/src/ccsync_companion/music_ingest.py:203-214: `_item_from_manifest` matches by name only, so two same-named tracks in one drop (its own comment names `theme.wav` twice) both index the first file (same defect as bug-comp-broll-1).
- companion/src/ccsync_companion/music_server.py / ytdl_server.py: the same `poll_fetch` callers probably leak DONE jobs the same way as bug-comp-broll-3 if they check the file before the fetch (not verified).
