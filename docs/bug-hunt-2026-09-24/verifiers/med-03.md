# Verifier med-03 (2026-09-25)

Judged against HEAD (63d4290), read with `git show HEAD:<path>` into the
session scratchpad. Nothing in the repo was edited except this file.

## bug-comp-broll-2 - CONFIRMED (medium)

The mechanism holds. `ingest_batches.create_batch` (HEAD :572-575) stores
`_clean_rel_dir(item.rel_dir if keep_subfolders else "")`, and the server's
`_clean_rel_dir` runs every component through `archive_names.safe_name`
(forbidden characters replaced, trailing `. ` stripped, capped). The companion
stages under its own `_clean_rel_dir` (:3928), which only drops `.`/`..` and
caps at 255, and `_item_from_manifest` (:1891-1901) pairs by an exact
`(name, rel_dir)` string compare. So a manifest rel_dir of `""` or `Shoot A`
matches no staged `Day1` or `Shoot A.`, `local_path` stays `""`, and
`_crunch_item` (:2282-2285) fails the item with "the source file is not on this
computer any more". `retry_failed` re-sends the same rel_dir, so it fails the
same way. Not a duplicate of bug-comp-broll-1 (a different trigger on the same
matcher), though an id-based match fixes both.

Evidence: probe from the companion venv loading HEAD's broll_ingest.py and
calling `_item_from_manifest` directly: staged `C1.MP4`/`Day1` vs manifest
`""` -> `local_path ''`; staged `Shoot A.` vs manifest `Shoot A` -> `''`;
exact match -> `S/a.mp4`. `broll/web/tests/test_ingest_batches.py:148` pins
the server's flattening, and no companion test covers the pairing.

## bug-comp-broll-3 - DOWNGRADE (low)

The mechanism is real, but most of the harm it describes is repaired
elsewhere. rclone renames `.partial` into place before `_run_job` sets DONE,
and every re-POST tests `insert_path.is_file()` first, so the DONE branch and
its "BEFORE the import" ledger rewrite in `build_insert_response` are
effectively never reached, and the DONE job stays in `_JOBS`. However: (1) the
next poll plans `PLAN_IMPORT_ORIGINAL` with `is_standin=True` (the intent row
exists), so `upgrade_rel` is set and `start_proxy_upgrade` runs after the
import, which sets `upgrade=pending`. The upgrade is not lost. (2)
`broll_standins.settle_intents` runs on the 120 s cycle and settles the row by
geometry, or else by `job_state()`, which answers `done` precisely BECAUSE the
job leaked. What is left: a stuck-pending row only when the dashboard sent no
geometry AND the companion restarts inside the 120 s window; a small
per-clip registry leak (DONE jobs do not count toward the cap, since
`_running_count` counts only `downloading`); and a one-time misleading "is the
share mounted?" (plus `forget` of a stand-in row) when a fetched clip is
deleted and sent again. The second click then works because that poll popped
the stale job. These are narrow and self-healing, so low.

Evidence: read `broll_server.py` :1150-1345 (plan_insert :959-1010,
start_proxy_upgrade call :1336-1343), `broll_fetch.py` :314-481,
`broll_standins.py` settle_intents :556-651 and `_what_landed` :653-683.

## bug-comp-broll-4 - CONFIRMED (medium)

The mechanism holds. `_note_original_failed` (:3493-3523) appends the clip to
the staging entry's `held_for_base_rig` through `_hold_staging`. The only
writers of that key are :3632 and :3650, and nothing removes a name from it.
A successful re-upload through `retry_failed` (which moves `proxies_live` items
back, ingest_batches :584-627) sets `item["original_uploaded"]` (:3047) and
never touches the list. `prune_staging` skips any entry with a non-empty
`held_for_base_rig` (:3705-3714), and that includes `max_age_days=0`, which is
CLEAR FINISHED STAGING. `staging_report` (:3663-3685) counts a held entry that
has `ended_at` as `finished_bytes`, so `_space_refusal` (:3562-3566) sends the
editor to CLEAR FINISHED STAGING, a button that frees none of it. This is the
same wrong-button shape comp-broll-music-2 fixed for unrun drops, left open
for held ones. The hold itself is intended (CMEDIA-4, KNOWN_BUGS ~12715), but
only while the file is owed. Keeping it after the original has landed is a
defect, and the retention sweep can never reclaim that disk space.

Evidence: `grep -n held_for_base_rig` over HEAD broll_ingest.py; read the
lines cited above.

## bug-comp-broll-5 - CONFIRMED (medium)

The mechanism holds, and if anything the hunter understates the load.
`_run_media` (:3357-3370) never passes a timeout, so every encode runs under
`run_ffmpeg`'s `RUN_TIMEOUT_SECONDS = 900`. That constant's own comment says
it is sized for "a still or a sprite". `_encode_verified` (:2492-2531) runs
the editing proxy through `own_proxy_cmd`, and on a machine without NVENC that
is `libx265 -preset medium` 10-bit (ffmpeg_tools ~733-735). A timeout becomes
`UnreadableMediaError` -> rc 1 -> "did not decode", so the clip loses its
editing proxy (`required=False`), or the whole item when the preview times
out. proxy_gen runs the same recipe with `max(1800, duration x 60)`
(proxy_gen :89-94, :2103). libx265 medium on a CPU runs well under real time,
so on a Mac or AMD machine a clip of roughly 10 minutes or more is enough to
hit the ceiling. Not measured on hardware.

Evidence: read broll_ingest_media.py :368-450, broll_ingest.py :2470-2531 and
:3357-3370, and the proxy_gen constants.

## bug-comp-ytdl-2 - CONFIRMED (medium)

The mechanism holds. When `_should_stop()` is set during the conversion,
`_ensure_edit_ready` (:2539-2545 region) deletes the `.editready.mp4` and
returns `(name, None, None)`. `_download_one` then calls only
`_cleanup_current` (:2976-2984), which clears `is_sweepable` partials and
scratch info, and `disown_output` is reached only from `_fail_clip`. The VP9
original stays under its deliverable name `<title> [id].mp4`, where the
importer and lane A read it as the finished clip. The stop happens in
ordinary use: the page's STOP, tray Quit, or a 410. The root is shared with
the high bug-comp-ytdl-1 (converting in place beside an original under its
final name). This is a distinct trigger that makes the bad file PERMANENT
rather than racing a 120 s window, so it is not a duplicate. A staging-name
fix for ytdl-1 would close both, and they should be fixed together.

Evidence: read ytdl_executor.py :2395-2440, :2495-2560, :2976-2984 and
`is_sweepable` :1319-1332. The hunter's FakeTools probe matches this reading.

## bug-comp-ytdl-3 - DOWNGRADE (low)

The mechanism is real. `heartbeat()` discards `_call`'s status, `_call` raises
only on a transport failure or a 410, and `clip_status` logs a non-200 and
moves on. `_heartbeat_loop` stops only on `LeaseLost`, and
`require_fleet_caller` (routes_fleet :160-177) answers 403 before any lease
check, so a caller whose identity has gone never sees the 410. `sign_out` in
app.py stops the lanes but not the ytdl executor. The consequence is wasted
work, though, not damage: one duplicate download of the job's remaining clips
from the editor's IP. The server's copy is canonical, the local files have
the same `[id]` names, and lane A is already stopped by the sign-out. The
triggers are also rare: a sign-out, a 30-day token expiring, or an admin
deleting the user, in each case in the middle of a local job. Low.

Evidence: read ytdl_executor.py :1077-1125, :1188-1257 and :2060-2090,
routes_fleet.py :150-177, and app.py `sign_out` (~6528-6545).

## bug-comp-ytdl-4 - CONFIRMED (medium)

The mechanism holds. `_loop` waits `CHECK_INTERVAL_SECONDS` (24 h) after any
pass while the feature is enabled (:1266), whatever the pass's action.
ACTION_FAILED (the first install failed, or the self-update needed to meet a
floor failed) publishes `ok=False` (:1123-1147), and `capabilities()` then
refuses local downloads. The only other caller of `ensure()` is the
executor's `_maybe_poke_ytdlp`, which needs a job, and a machine with
`ok=False` never claims one. So a single failed pass (a boot before the
network is up, or a GitHub blip) turns requester-first downloads off for a day.
The fallback is the server, which is safe but is the path CR-73 and CR-80 made
slow or flagged. Medium is right.

Evidence: read ytdlp_manager.py :1051-1160 and :1211-1270, and
ytdl_executor.py `capabilities` :876-940 and :2610-2640.
`git grep "\.ensure("` shows no other caller.
