# bug-comp-ytdl - companion YouTube executor, loopback routes, cookies, sign-in, attestation, yt-dlp sidecar, importer

Files read (approximate coverage): companion/src/ccsync_companion/ytdl_executor.py (all), ytdl_server.py (all), ytdl_common.py (all), ytdl_cookies.py (all), ytdl_browser_login.py (all), ytdl_attestation.py (all), ytdlp_manager.py (all), youtube_import.py (all). Followed calls into ytdl/web/ytdlweb/routes_fleet.py (claim/heartbeat/manifest/status, require_fleet_caller), db.reveal_path, sync/rclone_lane.py (lane A argv, min-age), broll_server.contained_local_path, broll_fetch.build_fetch_command, app._ytdl_deps, tray attestation calls, ytdl/web/static/app.js (local progress + STOP).
Tests/probes run: `companion/.venv python -m pytest tests/test_ytdl_executor.py tests/test_ytdlp_manager.py tests/test_ytdl_server.py tests/test_ytdl_cookies.py tests/test_ytdl_browser_login.py` (436 passed). One scratch probe (scratchpad, reusing the suite's FakeTools/FakeFleet helpers): cancel the job while the VP9->H.264 conversion runs; result below in finding 2.

## Findings

### bug-comp-ytdl-1 - A conversion longer than 120 s leaves the pre-conversion original eligible for lane A and the Resolve importer under its final name
- Severity: high
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/ytdl_executor.py:2421 and :2551 (`_ensure_edit_ready` converts in place, beside the finished original); companion/src/ccsync_companion/sync/rclone_lane.py:1739 (`--min-age 120s`, `--ignore-existing`); companion/src/ccsync_companion/youtube_import.py:667-677 (settle = mtime older than 120 s and unchanged across two scans)
- What: yt-dlp lands `<title> [id].mp4` under its deliverable name, then the executor probes it and re-encodes with libx264 (CONVERT_TIMEOUT 3 h, well below real time on a laptop). The original is not written again while ffmpeg runs, so 120 s after it landed it passes lane A's only stability gate and the importer's settle test. The YT-3 fix (`--no-mtime`) only makes the mtime "now". It closes nothing once the re-encode takes longer than 120 s, and that is exactly the YT-3 symptom ("a ten-minute re-encode starts and lane A runs during it"). YTDL_WORK_EXCLUDE_RULES cover `.editready/.original/.temp/.fNNN/.failed`, never the original under its final name.
- Failure scenario: an editor downloads a 10-minute 1080p clip that YouTube serves as VP9 and the conversion takes 10+ minutes. (a) Lane A's next pass uploads the VP9 file under the final name. `copy --ignore-existing` means the converted file that later replaces it locally is never uploaded, so the NAS keeps an undecodable copy for good. /ytdl/fetch then serves that copy to every other editor. (b) youtube_import files the VP9 original into Master/Youtube. Resolve then holds the file open, so `swap_in` cannot remove or rename it (Windows). The converted clip is delivered as `<title>.converted [id].mp4` and the original stays under the id name. The result is two clips in the pool, one undecodable, and two uploads. On the base rig the server worker's own conversion on the NAS leaves the same window open to the base rig's importer.
- Evidence: code read. Lane A argv `--min-age LANE_A_MIN_AGE` (120 s) plus `--ignore-existing`. `_collect` imports once `now - mtime >= min_age_seconds` (120) and the fingerprint repeats across scans (60 s). The executor writes nothing to `src` between landing and `swap_in`. KNOWN_BUGS "YT-3 ... PARTLY FIXED" claims `--no-mtime` "restores `--min-age` as a real gate", but that holds only for conversions shorter than 120 s.
- Ledger: related to YT-3 (partly fixed; the fix it records does not close its own symptom)
- Suggested fix: never leave an unconverted download under the deliverable name. Either have yt-dlp write to a staging name/dir outside the lane A include set (e.g. `-o` into `.ccsync-staging/` or a `.download` suffix) and move the final file in only after the probe/convert, or make lane A and the importer skip an id while its `.editready` sibling exists. Apply the same rule to the server worker.

### bug-comp-ytdl-2 - Stopping, quitting or losing the lease during "converting" leaves the unconverted original as a finished clip
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/ytdl_executor.py:2539-2545 (`_ensure_edit_ready` returns `(name, None, None)` on stop), :2422-2424 (`_download_one` then only `_cleanup_current`), :2976-2984 (`_cleanup_current` only clears sweepable names)
- What: when `_should_stop()` becomes true during the ffmpeg re-encode (the page's [ STOP ], tray Quit, or a heartbeat 410), the tmp `.editready.mp4` is deleted. The VP9/opus original stays behind as `<title> [id].mp4`: it is not disowned (`disown_output` is only called from `_fail_clip`) and is not sweepable. That name is the deliverable spelling, so the importer, lane A and the dedupe scan all read it as the finished clip.
- Failure scenario: an editor presses [ STOP ] ("the clip it is on ends now and the server picks up the rest") while the tray says "converting to H.264". The undecodable original stays in their project folder. The importer files it into Master/Youtube and lane A uploads it after 120 s. If it reaches the NAS before the server's re-download, the server's disk dedupe (`duplicate_location` anchored on `[id]`) marks the clip a duplicate and never converts it. Either way this editor's local copy stays VP9 for good. Quitting the tray at the end of the day mid-conversion does the same.
- Evidence: probe (scratchpad test reusing tests/test_ytdl_executor.py's FakeTools, with job.cancel() called from the ffmpeg call): the term folder afterwards holds exactly `['Some Channel - A clip [aaaaaaaaaaa].mp4']` with the ORIGINAL bytes, only `(vid, 'downloading')` was posted, and `YoutubeImporter._is_clip_name` accepts the name.
- Ledger: new (same family as YT-3 / YT-6)
- Suggested fix: on a stop during conversion, disown the landed file (rename to `.failed`, as `_fail_clip` does) or move it to a non-deliverable name, since a convert-needed original is never a valid deliverable. Better still, fix bug-comp-ytdl-1 with a staging name, which covers this case too.

### bug-comp-ytdl-3 - A mid-job 403 (sign-out, expired or revoked identity token) never stops the executor; it downloads the whole job unrecorded while the server reclaims and re-downloads it
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/ytdl_executor.py:1188-1199 (`heartbeat` ignores the status `_call` returns), :1251-1257 (`clip_status` logs and swallows non-200), :2074-2087 (`_heartbeat_loop` only stops on LeaseLost); server side ytdl/web/ytdlweb/routes_fleet.py:160-177 (`require_fleet_caller` answers 403 before `_leaseholder_or_410` can answer 410)
- What: only a 410 ends a job. The identity token is re-read on every call (`Deps.identity_token`), so after a sign-out, a 30-day token expiring or an admin deleting the user, every heartbeat and status post gets 403 from `require_identity`. `heartbeat()` does not look at the status, so the loop carries on and the lease lapses after 180 s. The server reclaims the job and downloads every clip itself. The server never answers 410 to this caller (the 403 comes first), so the local job keeps running to the last clip, writing into the tree with every `done` refused. A 404 (job row gone) is ignored the same way.
- Failure scenario: an editor signs out of the tray on a shared machine, or their token expires, while a 40-clip local job runs. The machine keeps fetching all 40 clips from its residential IP (bot-check exposure, disk, bandwidth) and posts 40 refused statuses. Meanwhile the NAS downloads the same 40 clips. The progress mirror reports the job finished on this machine, while the server rows show a server download.
- Evidence: code read of both sides. `heartbeat()` is `self._call(...)` with the result discarded. `_call` raises only on transport errors and 410. `require_fleet_caller` runs before `_leaseholder_or_410` in every fleet route.
- Ledger: new
- Suggested fix: treat 401/403/404 from heartbeat, manifest and clip_status as the end of the job (raise LeaseLost or a sibling `CredentialLost` that stops the job the same way and sets a hand-back reason such as "you signed out on this computer"). At minimum, have the heartbeat stop the job after its first 403.

### bug-comp-ytdl-4 - One failed yt-dlp install or floor update switches local downloads off for 24 hours; nothing retries sooner
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/ytdlp_manager.py:1266 (`wait = CHECK_INTERVAL_SECONDS if enabled else DISABLED_RECHECK_SECONDS`), :1123-1147 (ACTION_FAILED with ok=False)
- What: the sidecar loop is the only caller of `ensure()` apart from the executor's once-per-job poke, and that poke is unreachable here because capabilities() refuses before any job is claimed. An ACTION_FAILED pass (first install on a new machine, or `-U` to meet a raised floor) publishes ok=False and then sleeps the full daily interval. capabilities() answers `ok:false` for that whole time. The ffmpeg/deno sidecar pass on the same loop has the same 24 h retry when enabled. The 15-minute recheck applies only while the feature is OFF.
- Failure scenario: a new editor machine starts its tray at login. 30 s later the first ensure() runs before Wi-Fi or a captive portal lets it reach GitHub, the install fails, and that machine has no local YouTube downloads until the same time tomorrow (or a tray restart), with no retry in between. The same happens when an operator raises YTDL_MIN_YTDLP_VERSION to fix a YouTube break (the CR-80/83 situation) and `-U` hits one GitHub blip: every affected machine sends its jobs to the server for a day.
- Evidence: code read. `grep ytdlp.ensure` finds no other caller in the companion. `_loop` waits CHECK_INTERVAL_SECONDS (86400) after any enabled pass.
- Ledger: new
- Suggested fix: after an ACTION_FAILED pass (yt-dlp or sidecar), retry with backoff (e.g. 5 min doubling up to the daily interval) instead of the daily interval.

### bug-comp-ytdl-5 - swap_in's last-resort deliverable is the sweepable `.editready` temp name
- Severity: low
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/ytdl_executor.py:1680-1685
- What: when the final replace, the move-aside rename and the `converted_name` replace all fail, `swap_in` returns `tmp.name` (`<stem>.editready.mp4`) as the delivered name. `_download_one` posts it as `filepath_rel` and the server ledgers it. That name matches `_INTERMEDIATE_STEM_RE`, so the next `clear_partials` for this id deletes it, the importer never files it, and the dedupe scan cannot see it. In the non-`same` branch `os.remove(original)` may already have succeeded, so the tmp is the only copy.
- Failure scenario: an AV scanner or indexer holds the folder's files during the swap and all three renames fail. The clip is recorded `done` at a `.editready.mp4` path. A later attempt at the same id (a re-download or the other executor) sweeps it away, and the ledger's "the fleet already has this" then points at nothing.
- Evidence: code read. `is_sweepable("X [id].editready.mp4")` is True (stem ends `.editready`).
- Ledger: related to YT-6 (fixed; this branch was not covered)
- Suggested fix: when every rename fails, report the clip as failed (disowning the tmp to `.failed`) instead of delivering a name the tree treats as litter.

## Coverage note
Did not exercise ytdl_browser_login against a real Chromium (whether `Browser.close` is honoured on a page-target session, and whether Edge hands off to an existing instance of the same profile). Did not trace NFD filenames from a Mac HFS+ volume through `filepath_rel` into the ledger. Did not audit sidecar_tools.ensure itself (another territory) beyond its retry cadence.

## OUT OF TERRITORY
- ytdl/web/ytdlweb/routes_fleet.py:160: `require_fleet_caller` 403 precedes the leaseholder 410, so a stale or ex-signed-in executor is never told "stop" in the words it acts on (the server half of bug-comp-ytdl-3).
- ytdl/web/ytdlweb (worker ensure_edit_ready on the NAS): the same pre-conversion window as bug-comp-ytdl-1 is visible to the base rig's youtube_import, whose tree is the NAS.
