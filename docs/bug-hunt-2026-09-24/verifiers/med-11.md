# Verifier med-11 (2026-09-25)

Judged against HEAD (63d4290) with `git show HEAD:<path>`. Read-only except this file.

## logic-alerts-1 - CONFIRMED (medium)
`_check_feature_mounts` (notices.py) skips only `status == "mounted"`; every other status, including `disabled`, writes a `feature_not_mounted` warn with the fix "Check the container's bind mounts ... then restart". `mount_ytdl` returns `DISABLED` whenever `youtube_download` is off (the vendor default), and `cards.py` returns `DISABLED` for "no checkout configured / no vault", which its own comment defines as "this deployment did not ask for it". `app._record_mount` records both into `mount_status`, so the card stands on every vendor install and restarting cannot clear it. DDIAG-7 in KNOWN_BUGS describes the notice for pages that "did not start"; nothing there or in the 09-11 hunt addresses `disabled`.
Evidence: notices.py:693-746, ytdl.py:643-654, cards.py:78-84 and 670-687, app.py:1595-1630 and 1704-1718 (all at HEAD).

## logic-alerts-2 - CONFIRMED (medium)
`_check_versions_behind` counts every non-retracted `companion_packages` row (staged included) plus the vendor feed's offer, newer than the running version. Counting feed/staged builds is intended (SYS-2), but the sentence then reports "current is X" equal to the running version and the fix is [ UPDATE NOW ], which pushes the current build the machine already runs (and which `triage_actions` refuses). So on a staged-soak or manual-adoption site the alert is both contradictory and unactionable, and it never clears through the action it names. A wrong instruction on a standing warn, not data loss: medium.
Evidence: alerts.py:2379-2427 at HEAD; KNOWN_BUGS SYS-2 (line ~11342) and REL-6.

## logic-alerts-3 - CONFIRMED (medium)
`_check_platform_channel_stale` compares the two channels' CURRENT versions and never looks for a published-but-staged build on the lagging platform. Its body always says "nothing will offer it to them until somebody builds it" and its fix is a hard-coded pair of `release_macos.sh` commands (worded "On a Mac" even when the lagging platform is Windows), which is wrong when the build is already staged (re-publish is refused as already published) and impossible on a customer site with no repo. Distinct from logic-alerts-2 (different check and different wrong fix), though both fire on the same studio state.
Evidence: alerts.py:2986-3055 at HEAD; KNOWN_BUGS REL-13.

## logic-alerts-4 - DOWNGRADE (low)
Mechanism holds: `run()` sends every report and fallback with `Reply-To` set to the reply address, `compose_report` emits no CCT reference when nothing is offered ("Nothing in this check can be done by reply."), and `handle_message` refuses an authenticated allowed sender whose reply has no token under `reference`, opening a `triage_reply_refused` warn whose fix ("Reply to the most recent server check email") cannot be followed. Low rather than medium: it needs the owner to reply to a no-action email, nothing is changed or lost, the card is dismissable and closes by CR-320's rule, and the silence is the designed refusal behaviour, only mis-targeted.
Evidence: triage.py:478-535, 640-695; triage_mail.py:78-87, 426-506 at HEAD.

## logic-broll-music-1 - CONFIRMED (medium)
Reproduced. The curator panel sends the STORED `item.video_id` (resolve_items puts `entry["video_id"] = item["video_id"]`; clientfolders.js DELETE/PUT use it), and `remove_item`/`set_note` match `video_id = X OR (share, rel_path) = current-index identity of X`. After a renumbering rebuild the stored id of one item is another clip's current id, so the OR matches a second item. Probe from broll/web/.venv against HEAD's client_folders.py: folder {A=5, B=9}; rebuild A->7, B->5, C->9; `add_items([9])` -> `{'added': [], 'already': [9]}`; `remove_item(5)` -> True and rows left `[]` (both A and B deleted from a live client link). The OR was introduced by broll-4 / MEDIA-23 and causes this; no existing entry covers it.
Evidence: client_folders.py:589-697, 802-877; clientfolders.js:405-445; scratchpad probe_cf.py.

## logic-broll-music-2 - CONFIRMED (medium)
`_what_landed` returns False ("the real original") whenever the probed WxH equals the row's geometry, which is the ORIGINAL's. The preview is encoded with `scale=-2:trunc(min(1080,ih)/2)*2`, so for any original of height <= 1080 the stand-in has the original's exact geometry. Such originals are still "heavy" (edit_weight: not h264/hevc/prores, or bitrate over the cap) and `plan_insert` gives them a stand-in when the extension is .mov/.mp4/.m4v (DNxHD .mov, high-bitrate 1080p H.264). An unobserved landing then retires the ledger row and the preview bytes sit under the original's name unmarked - the exact proxy-tiers-1 outcome CR-288B/2 set out to prevent; its write-up only considered the 6064x3424 case.
Evidence: broll_standins.py:600-680, broll_server.py:935 and 1045-1090, broll/indexer ffmpeg_tools.py:555-570 (PROXY_HEIGHT 1080), edit_weight.py:24-48, KNOWN_BUGS CR-288B/2.

## logic-broll-music-3 - CONFIRMED (medium)
`write_item_result` inserts the `tracks` row (embedding, windows, peaks) and sets the item `indexed` before the audio upload; `release(state='cancelled')` flips every item not in (live, duplicate, skipped, cancelled, queued_for_base_rig) to `cancelled`, so `indexed`/`uploading` items become terminal while their tracks rows remain. `retry_failed` moves only `failed`, and `db.load_matrix` loads every track with an embedding, so the track stays searchable with no audio file and holds its name. The release docstring states the opposite ("it is `indexed` rather than `live` ... fixable by re-uploading").
Evidence: music/web/musicweb/ingest_batches.py:79, 556-600, 930-1078, 1233-1262; db.py:337-346 at HEAD.
