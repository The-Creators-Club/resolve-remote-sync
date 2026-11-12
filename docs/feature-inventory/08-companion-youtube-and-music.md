# Companion: YouTube downloads on the editor's machine, and music ingest and send-to-Resolve

Terms used throughout:

- **Companion**: the tray app on each editor's computer.
- **Dashboard**: the web app on the studio's NAS (network storage server). Its YouTube downloader page is served from the NAS, and the browser page talks both to the dashboard and to the companion's local web listener.
- **Loopback listener**: the companion's small web server on `127.0.0.1:8899`, reachable only from the same computer. Every route in this section hangs off that one listener. The routing table itself, and its origin/token guard, are described in the b-roll section; this section describes what each YouTube and music route does.
- **Job**: one YouTube download order on the dashboard, holding a list of clips.
- **Lease**: the dashboard's record that one computer is currently downloading a job. It expires unless renewed by a heartbeat.
- **Local executor**: the companion's ability to run a job's downloads on the editor's own computer instead of on the NAS.
- **Canonical tree**: the shared project folder tree as the fleet names it (for example `P:\Projects\...`). Each computer maps it to its own local root folder (`local_root`).
- **Sidecar binary**: a separate program the companion keeps on disk next to itself (yt-dlp, ffmpeg, ffprobe, deno), as opposed to code built into the companion.
- **Hand-back**: the companion giving a job back to the server by stopping work and letting the lease expire. There is no explicit "release" call; the dashboard reclaims the job when the lease runs out and downloads whatever is missing.

## Feature gates for everything YouTube on the companion
(source: ytdlp_manager.py, ytdl_cookies.py, ytdl_server.py, ytdl_executor.py)

- **Site flag `youtube_download`** (in the customer's site manifest, published by the dashboard). Off in the vendor build. If off or unreadable (fails closed):
  - The yt-dlp sidecar is never installed or updated, and the daily check publishes "the YouTube downloader is off for this site".
  - `GET /ytdl/capabilities` answers `ok: false` with reason "the YouTube downloader is off for this site, or switched off in config".
  - `POST /ytdl/download` answers 503 with that reason.
  - `POST /ytdl/reveal` and `POST /ytdl/fetch` answer 200 with `ok: false`, "the YouTube downloader is not enabled for this site".
- **Site flag `youtube_unblock`** (off in the vendor build). Gates the two "get past YouTube's own measures" components:
  - The signed-in cookie jar: when off, no cookies file is ever passed to yt-dlp (even if one exists on disk from before), the tray's sign-in item is not offered, and installing cookies is refused with "signing in to YouTube for downloads is not enabled for this site. Ask your administrator (site.toml [features] youtube_unblock)".
  - The deno JavaScript runtime install (decided in the sidecar-tools code, outside this part; this part only uses deno if it is present).
- **Per-computer config key `ytdl_local_downloads`** (default true; absent means on). Set to false, this computer never executes downloads: yt-dlp is not installed or updated, capabilities answer "off". A non-boolean value is treated as true and logged as an error. It does NOT turn off `/ytdl/reveal` or `/ytdl/fetch` (those check only the site flag), so an editor who opted out can still open and fetch clips the server downloaded.
- The YouTube auto-import into Resolve (below) has its own switch, `youtube_import_enabled`, and is NOT gated by either site flag in this code.

## Local download capability check
(source: ytdl_executor.py `capabilities`)

What `GET /ytdl/capabilities` returns. Always HTTP 200; the verdict is in the body. It does no network calls and starts no programs, so that the browser's 1-second probe gets an answer. If the probe fails or says no, the browser sends the job down the server path with no message.

- Body fields: `ok`, `reason` (a sentence, or null), `warning` (an advisory that does not refuse, or null), `editor` (signed-in editor name), `ytdlp_version`, `template_version` (naming contract version, currently 1), `sidecar_version` (credits file contract version, currently 1), `scope_qualities` (the qualities this computer will run: `480p`, `720p`, `1080p`), `free_bytes` (free space on the volume holding `<local_root>/Projects`, or the home folder), `machine` (this computer's hostname), `mode` (`base` if this computer's config `mode` is exactly "base", otherwise `editor`; diagnostic only).
- Checks, in order; the first that fails sets `reason` and `ok: false`:
  1. Site `youtube_download` on and `ytdl_local_downloads` not false. Reason: "the YouTube downloader is off for this site, or switched off in config".
  2. A dashboard URL and fleet token are configured. Reason: "this computer has no dashboard URL or token configured".
  3. Someone is signed in (verified editor name). Reason: "nobody is signed in on this computer".
  4. A dashboard-signed identity token is held. Reason: "this computer has no valid sign-in token: sign in again from the tray".
  5. The YouTube terms were accepted on this computer by this editor (see Terms acceptance). Reason: "the YouTube terms have not been accepted on this computer: " followed by a fixed pointer to where the terms are accepted (text lives in another module).
  6. The yt-dlp sidecar's last check said ok. Reason: that check's own message, or "yt-dlp is not ready on this computer".
  7. If the last check said yt-dlp is "stale" (old and could not update), `warning` is set to that message; the job is NOT refused.
  8. ffmpeg can be found. Reason: "ffmpeg is not installed on this computer, so downloaded video and audio cannot be merged".
  9. The project tree is not known to be absent (uses the cached root-guard verdict only; "cannot tell" passes). Reason: "this computer's project tree isn't mounted right now, so there is nowhere to download into".

## Starting, cancelling and watching a local download
(source: ytdl_executor.py `start`, `cancel_job`, `cancel_all`, `snapshot`, `progress`, `stop_all`; dispatch in broll_server.py)

- **`POST /ytdl/download`**, body `{"job_id": <positive integer>}`. The job id is the ONLY thing read from the body; destination, URLs, quality and naming all come from the dashboard.
  - 400 `"job_id must be a positive integer"` when the id is missing, not an integer, zero or negative, a boolean, or a string.
  - 409 `"this computer is already downloading job N"` when a job is already running on this computer (checked before capability, and again just before starting). Only one job runs per computer at a time.
  - 503 with the capability reason when the capability check fails.
  - 503 `"the download thread could not be started"` if the background worker cannot be started.
  - 202 `{"ok": true, "job_id": N, "state": "started"}` otherwise; the download runs in the background.
  - Malformed JSON body: 400 `"invalid JSON body"`.
- **`POST /ytdl/cancel`**, body `{"job_id": N}` or `{"all": true}`. Always 200. Stops the running download on this computer (kills yt-dlp and any ffmpeg it started, deletes this clip's partial files, stops the heartbeat; the lease then expires and the server downloads what was not finished). Nothing is posted to the dashboard.
  - With a job id that does not match the running job, nothing is stopped.
  - Answer: `stopped` 1 or 0, message "Stopped. The server will download the clips this computer did not finish." or "There was no download running on this computer."
  - The job's hand-back reason becomes "You stopped this download on this computer. The server will download the clips this computer did not finish."
- **`GET /ytdl/progress[?job_id=N]`**. Always 200, `{"jobs": [...]}` with at most one row: the running job, or else the last job this companion session ran (so a page polling after the end learns how it ended). An unparseable `job_id` is ignored; a given one filters the list. Each row:
  - `job_id`, `title` (the search folder name from the manifest, falling back to the project label), `phase`, `percent`, `speed`, `eta_seconds`, `file` (last file landed), `handed_back_reason`, `clip` (video id in flight), `done`, `failed`, `total`, `running`.
  - `phase`: while running, `starting`, `downloading` or `converting`; after, `cancelled` (editor stopped it), `handed_back` (a reason was recorded), else `finished`.
  - `percent`: the clip in flight, 0 to 100 with one decimal, from yt-dlp's byte counts; null when unknown.
  - `speed`: text like `4.2 MB/s` (decimal units; `KB/s` below 1 MB/s, `B/s` below 1 KB/s); null when unknown or zero.
  - `eta_seconds`: seconds left on the CLIP in flight (not the job), null when unknown.
- A flat single-job progress dict also exists (used for the tray's progress line): job id, running, clip, done/failed/total, byte counts, speed in bytes per second, phase, title, file, cancelled, hand-back reason. With nothing to report it returns zeros and nulls.
- **Tray shutdown** kills a download in flight; what it leaves is clip-scoped partial files that the next attempt clears.

## The download job, step by step
(source: ytdl_executor.py `DownloadJob`, `FleetClient`)

All calls to the dashboard go to `<dashboard_url>/ytdl/api/...` with headers `X-CCSync-Token` (shared fleet token, re-read on every call), `X-CCSync-Identity` (signed identity token, re-read on every call), and `X-CCSync-Machine` (this computer's machine id, only when it is plain printable ASCII). No HTTP redirects are followed. Each call times out at 15 s.

1. **Capability re-check.** If it fails, the job is handed back with "This computer cannot download right now: <reason>. The server is downloading these clips."
2. **Free space check, before claiming.** Needs the companion-wide free-space margin (a constant from the upgrade module, not in this part) plus 5 GiB. If less is free: hand-back "This computer has X GB free and this download needs about Y GB, so the server is downloading it instead." (decimal GB, one decimal).
3. **Claim** `POST /jobs/{id}/claim` with editor, yt-dlp version, template version, sidecar version, the three in-scope qualities, free bytes, and machine id. Any answer other than 200 with a JSON object (or a transport failure) means "not ours": the job stays with the server. The claim is not retried.
   - Refusals that are about this computer are shown to the page as a hand-back reason (all end with "The server is downloading these clips."):
     - 403 reason `attestation`: "The dashboard has no record of you accepting the YouTube download terms, so this computer did not download. Read the notice at the top of this page and press Accept."
     - 403 reason `ytdlp_version`: "This computer's yt-dlp (<version or 'version unknown'>) is older than the <floor or 'minimum'> the server asks for, so it did not download."
     - 401/403 with no reason, `identity` or `identity_mismatch`: "The dashboard does not accept this computer's sign-in, so it did not download."
     - 409 where the holder is this same editor (their other computer): the server's own sentence plus ", so this computer left it alone."
     - 410 reason `template_version`: "This computer names downloaded clips differently from the server, so it did not download. ... Updating the companion fixes it."
     - 410 reason `sidecar_version`: "This computer writes clip credits in a different format from the server, so it did not download. ... Updating the companion fixes it."
     - 410 reason `out_of_scope`: "This computer does not download <quality> clips, so it did not download."
   - Silent refusals (no message to the page): job finished, cancelled, pinned to the server, created for the server, a lost race, another editor's lease, a 5xx, an unreachable dashboard, `identity_unconfigured`, any unknown reason.
   - On a 403 `ytdlp_version` refusal where this computer's version is NOT older than the floor by proper version ordering, a warning is logged naming the likely cause: the dashboard's `YTDL_MIN_YTDLP_VERSION` is not zero-padded.
4. **Heartbeat.** Every `heartbeat_seconds` from the claim answer (default 30 s if missing or not positive), `POST /jobs/{id}/heartbeat` with editor and machine id.
   - 410: lease lost, stop everything quietly.
   - 401, 403 or 404: credential lost. Hand-back "The dashboard no longer accepts this computer's sign-in, so it stopped downloading. The server is downloading the rest of these clips." and stop.
   - Any other failure (5xx, network): ignored; the next beat tries again.
5. **Manifest** `GET /jobs/{id}/download-manifest?machine_id=...`. A non-200 answer ends the job (logged, no hand-back sentence).
6. **Contract checks on the manifest**, each a hand-back:
   - Naming template version differs: "This computer names downloaded clips differently from the server, so it handed the job back. The server is downloading these clips. Updating the companion fixes it."
   - Credits sidecar version differs: "This computer writes clip credits in an older format than the server asked for, so it handed the job back. ... Updating the companion fixes it."
   - Quality not 480p/720p/1080p (1440p, 2160p, best, audio are server-only): "Only the server downloads <quality> clips, so this computer handed the job back. The server is downloading them."
7. **Project ownership check** on the manifest's project label (compared case-insensitively, with `\` and `/` treated alike):
   - No label: "The download did not say which project it belongs to, so this computer handed it back. ..."
   - On the base rig (config `mode = "base"`): the label's folder must exist under `<local_root>/Projects` in its original spelling; otherwise "This computer has no folder for <label>, so it handed the download back. ..."
   - On editor machines: the label must be in this computer's synced project selection. Selection unknown: "This computer could not check whether it syncs <label>, so it handed the download back. ..."; not synced: "This computer does not sync <label>, so it handed the download back. ..."
8. **Destination.** The manifest's project-relative path is validated (must be a contained relative path) and translated through the canonical prefix into this computer's local spelling (`<local_root>/Projects/<...>`); with no canonical prefix configured it is joined directly. Unresolvable: "This computer could not work out where these clips belong on its own disk, so it handed the job back. ..."
9. **Drive re-check** with the full root probe (absent, or on macOS mounted at the wrong place): "This computer's project drive is not connected, so it handed the job back. The server is downloading these clips." This prevents creating a fake `/Volumes/<Name>` on a Mac's boot disk.
10. **Create the destination folder.** Failure: "This computer could not create the folder these clips go in, so it handed the job back. ..."
11. **Clips, one at a time**, pausing `download_pause_seconds` from the manifest between clips (default 3 s). Before each clip, the stop flags and the identical-failure breaker are checked.
12. When the loop ends (normally or early) the heartbeat stops. No completion or release call exists; the server's own sweep handles what failed.

- **Transport retry on dashboard calls after the claim** (heartbeat, manifest, clip status): a network failure (not an HTTP status) is retried with backoff starting at 2 s, doubling, capped at 15 s, for up to 60 s total, stopping early if the job is stopping. HTTP statuses are never retried. A 410 on any of these calls means the lease is lost.
- **Lease lost** (410 anywhere): the current yt-dlp/ffmpeg process tree is killed, this clip's partial files are deleted, nothing more is posted, and nothing is shown to the editor.

## One clip
(source: ytdl_executor.py `_download_one`, `_fail_clip`, `build_argv`)

- A clip with no video id is skipped silently (logged).
- **URL allow-list**: only http/https URLs whose host (after stripping `www.` / `m.`) is exactly `youtube.com`, `music.youtube.com`, `youtube-nocookie.com` or `youtu.be`, or ends in `.googlevideo.com`. Anything else is reported to the dashboard as failed: "the download URL was not a YouTube URL, so this computer refused it".
- Before downloading, any `... [id].original.<ext>` file left by an earlier conversion is deleted if possible; bytes that cannot be deleted (file in use) are reported in the clip's note.
- Status `downloading` is posted for the clip, then yt-dlp runs (see Anonymous first, cookies as fallback).
- **Quality fallback on a truncated stream**: if yt-dlp's error contains both "more expected" and "giving up after", partial files are deleted and the clip is retried ONCE at the next lower quality (1080p to 720p, 720p to 480p; 480p has nothing below and fails). Success adds the note "<q> stream truncated by YouTube, fell back to <lower>".
- **No output file**: if yt-dlp exits successfully but no finished file whose name ends in `[id]` exists, the clip fails with "yt-dlp reported success but left no output file".
- **Edit-ready conversion** (see below) runs on the landed file.
- **Credits sidecar** `<clip name minus extension>.credits.json` is written beside the clip (see Naming contract), from yt-dlp's info file.
- Status `done` is posted with the file name (relative to the destination folder), the combined note, and the title and channel from the info file (omitted when unknown, so the dashboard keeps what it had).
- **A failed clip**: anything this attempt created that carries `[id]` (other than partial files) is renamed with a `.failed` suffix (so it is never mistaken for the clip and never uploaded by the sync lane); this clip's partial files are deleted; the info file is deleted; status `failed` with the error text is posted; the failure counts toward the breaker. The error text is the last 400 characters of yt-dlp's error output, or "the download failed and yt-dlp said nothing". The server retries failed clips itself.
- A status post refused by the dashboard (non-200, not 410) is logged and ignored.
- **Clip timeout**: 2 hours per yt-dlp run including merge; on timeout the process tree is killed and the clip fails with "yt-dlp did not finish within 2h and was killed".
- **The yt-dlp command line**:
  - Format selector by quality, preferring H.264 video and AAC audio at 1080p and below (for example at 1080p: `bestvideo[height<=1080][vcodec^=avc1]+bestaudio[acodec^=mp4a]/bestvideo[height<=1080][vcodec^=avc1]+bestaudio/bestvideo[height<=1080]+bestaudio/best[height<=1080]`).
  - Merged into MP4.
  - Output name template (see Naming contract).
  - `--no-playlist` (a playlist URL never becomes many downloads).
  - `--no-mtime` (the file's modified time is today, not YouTube's upload date, so the upload lane's 120 s minimum-age gate works).
  - Progress printed as one machine-readable line per update.
  - `-N <n>` fragments in parallel: config `ytdl_fragment_jobs`, default 6, clamped to 1..16; junk values use 6.
  - Embedded credits tags: channel, video URL, channel URL, uploader, plus `artist` = channel and comment = URL; chapters and metadata embedded.
  - `--write-info-json` redirected OUT of the project tree to a scratch folder (`<tools folder's parent>/ytdl-info`, else `<system temp>/ccsync-ytdl-info`); if neither can be created, no info file is requested and the clip gets no credits sidecar.
  - `--ffmpeg-location` = the folder of this computer's ffmpeg (config `ffmpeg_path`).
  - `--js-runtimes deno:<path>` when a companion-managed deno exists.
  - `--extractor-args youtube:player_client=<x>` only when config `ytdl_player_client` is a non-empty string. Default: not sent (yt-dlp's own default clients).
  - `--cookies <jar>` only on the cookies path.
- **yt-dlp runs** windowless, with stdin closed, with a cleaned environment (Python-related variables removed), in its own process group so that killing it also kills the ffmpeg it started.

## Anonymous first, cookies as fallback
(source: ytdl_executor.py `_run_ytdlp_paths`, `_run_ytdlp`)

- Every job starts trying clips **anonymously**. The signed-in cookie jar (see YouTube sign-in) is used only as a fallback.
- Anonymous attempt fails with a **bot check** (error text contains "confirm you're not a bot", straight or curly apostrophe) and a jar exists: retry once with the jar. If that works, the job switches to "cookies first" for the remaining clips, and the clip's note is "downloaded with the signed-in YouTube session (the anonymous attempt was bot-checked)".
- A cookies-first attempt fails with an **account flag** (error contains "the page needs to be reloaded"): retry once anonymously. If that works, the job switches back to anonymous first.
- Both blocked (bot check on anonymous AND account flag on cookies, in either order): the clip fails with "both download paths are blocked on this computer: YouTube is asking the anonymous one to confirm it is not a bot, and it is refusing the signed-in session as well. Export a fresh cookies.txt from a different signed-in YouTube session, or let the server download this job."
- The anonymous path carries no note; only a cookies landing is noted on the clip row.
- The "cookies first" preference lasts only for the current job.
- **Cookie health recording**: when a cookies attempt fails and its error matches a "session is dead" phrase (see YouTube sign-in health), the cookie status file is marked stale once per job. When a cookies attempt succeeds and the status file says stale, it is marked ok ("a download succeeded with the signed-in session").

## Identical-failure breaker and yt-dlp re-check
(source: ytdl_executor.py `_note_failure`, `_breaker_reason`, `_maybe_poke_ytdlp`, `failure_signature`, `max_identical_failures`)

- Each clip failure is reduced to a signature (video ids, file paths and digits removed, lowercased, first 120 characters).
- When N consecutive clip failures share the same signature, the computer stops before the next clip and hands back: "<N> clips in a row failed the same way on this computer (<signature>), so it stopped at clip <i> of <total> and handed the rest back. The server is downloading them."
- N: config `ytdl_max_identical_failures`, else environment variable `CCSYNC_YTDL_MAX_IDENTICAL_FAILURES`, else 3. 0 or negative disables the breaker; junk uses 3.
- A successful clip resets the count.
- When a clip failure contains "requested format is not available" or "http error 403", the companion asks the yt-dlp sidecar manager to re-check and update now, at most once per job.

## Edit-ready conversion on the editor's machine
(source: ytdl_executor.py `_ensure_edit_ready`, `edit_ready_plan`, `edit_ready_argv`, `swap_in`)

- After a clip lands it is probed with ffprobe (2-minute limit). If no ffprobe is found next to ffmpeg or on the system path, the clip is delivered unchecked (logged).
- **Conversion is needed** when the video codec is not H.264, the frame rate is variable (average and nominal rates differ by more than 1%, compared as numbers), or audio exists and is not AAC. A probe that failed means "convert both, on suspicion". A file with no video stream (and a working probe) needs nothing.
- While ffmpeg runs, the downloaded original is renamed to `<stem>.source.editready.<ext>` so that the upload lane and the auto-importer ignore it. If that rename fails, conversion happens in place.
- ffmpeg command: re-encode video with libx264, preset medium, CRF 18, profile high, yuv420p, constant frame rate, carrying colour tags; or copy video if fine. Audio re-encoded to AAC 320 kbps, or copied. Metadata and embedded credits carried over; MP4 with fast-start. Output to `<stem>.editready.mp4`. Limit: 3 hours.
- The progress phase shows `converting` while this runs.
- Outcomes:
  - Success: the converted file takes the clip's final name `<stem>.mp4`. If that name is held open (for example Resolve has it open on Windows), the existing file is renamed to `<stem>.original.<ext>` and noted "original was in use, kept as <name>". If even that fails, the converted file is saved as `<title>.converted [id].mp4` and noted "converted, but <name> was in use: saved as <new name>". If nothing can be renamed into place, the clip fails with "Edit-ready conversion failed: converted, but neither <name> nor its converted copy could be renamed into place".
  - The staged original is then deleted, with up to 4 tries 0.5 s apart; if it still cannot be deleted the note says "the pre-conversion download could not be removed (<size>, kept as <name>); it syncs nowhere and can be deleted".
  - ffmpeg failed after the probe said conversion was needed: the clip fails with "Edit-ready conversion failed: <last 500 characters of ffmpeg's errors>".
  - ffmpeg failed after a probe that itself failed: kept as downloaded, note "could not probe the codecs and the safety conversion failed; kept as downloaded".
  - ffmpeg vanished mid-job: kept as downloaded, note "could not convert (no ffmpeg); kept as downloaded".
  - Timeout: "ffmpeg did not finish within 3h and was killed".
  - Stopped mid-conversion: the half-written output is deleted and the unconverted download is left under the staging name (so it is swept as litter).
- Sizes in notes are written as `N.N GB`, `N MB` or `N bytes`.

## Files a local download leaves or cleans up
(source: ytdl_executor.py)

- Clip-scoped partial files (names containing `[id]` and ending `.part`, `.ytdl`, `.temp`, `.part-Frag...`, or whose stem ends `.fNNN`, `.temp` or `.editready`) are deleted on failure, stop, cancel, lease loss, and before a quality retry. Never a folder-wide sweep.
- Failed attempts' leftovers are renamed `<name>.failed` and kept.
- `... [id].original.<ext>` (an original that Resolve was holding) is retried for deletion at the next attempt at the same clip; the size still held is reported.
- `<clip>.credits.json` beside the clip, UTF-8, two-space indented, LF line endings, non-ASCII kept literal. Written only from yt-dlp's info file. The info file is deleted only after the sidecar is written; if reading or writing fails, it is kept so the credits can be rebuilt.
- Info files go to the `ytdl-info` scratch folder outside the tree, named `<video id>.info.json`; an info file found in the project folder (older yt-dlp behaviour) is used as a fallback.

## Naming contract shared with the server downloader
(source: ytdl_common.py)

- This file is a byte-identical copy of the server's; the companion refuses jobs whose versions differ (see the job steps).
- `TEMPLATE_VERSION` 1, `SIDECAR_VERSION` 1.
- Clip file name: `<uploader, max 60 bytes> - <title, max 140 bytes> [<video id>].<ext>`, truncated by bytes so non-Latin titles fit a 255-byte name limit.
- Credits sidecar: `<clip path minus extension>.credits.json` with exactly eight fields, in order: `channel` (falls back to uploader), `channel_url` (falls back to uploader URL), `uploader`, `video_url`, `title`, `video_id`, `upload_date`, `duration`.
- Quality ladder: `best`, `2160p`, `1440p`, `1080p`, `720p`, `480p`, plus `audio` (best audio, preferring AAC). H.264/AAC are preferred only at 1080p and below. The rung below `best` is 1080p.
- Truncated stream markers: "more expected" and "giving up after", both required. Note text "{q} stream truncated by YouTube, fell back to {lower}".
- The truncation test on an exception object (server side) matches only exceptions whose class is named `DownloadError`; the companion matches the same words in yt-dlp's error output instead.

## The yt-dlp sidecar binary
(source: ytdlp_manager.py)

- **Location**: Windows `%LOCALAPPDATA%\ccsync\tools\yt-dlp.exe`; macOS `~/Library/Application Support/ccsync/tools/yt-dlp_macos`; other systems `~/.local/ccsync/tools/yt-dlp`.
- **Config `ytdlp_path`**: points at an editor-managed yt-dlp. When set, the companion only reads its version and never installs or updates it. Messages: "ytdlp_path is set to <path> but nothing runnable is there -- leaving it alone (nothing is installed over an override)"; "your own yt-dlp at <path> is <v>, older than the <floor> the dashboard asks for -- update it yourself, or clear ytdlp_path to let the companion manage one" (ok false); "using your own yt-dlp at <path> (<v>)" (ok true). A path that cannot be parsed falls back to the managed location.
- **Version reading**: `yt-dlp --version`, 15 s limit; must print a `YYYY.MM.DD` (optionally more dotted numbers) line, otherwise "no version".
- **Background thread**: first pass 30 s after tray start, then every 24 h while the downloader is enabled, or every 15 minutes while it is off (so turning the site flag on is noticed without restarting the tray). After a failed pass, the wait is shortened to 5 minutes, doubling each consecutive failure, never longer than the normal wait. The flag is re-read every pass.
- **Each pass (decision table)**:
  - Downloader off: nothing installed; published as disabled with "the YouTube downloader is off for this site" or "local YouTube downloads are switched off in config (ytdl_local_downloads = false)".
  - Override set: version check only (above).
  - No binary: install the newest nightly build. Failure: "no yt-dlp on this computer and it could not be installed -- YouTube downloads stay on the server". Success: "installed yt-dlp <v>".
  - Binary older than the dashboard's minimum: run `yt-dlp --update-to nightly`. Failure: "yt-dlp <v> is older than the <floor> the dashboard asks for and it could not update itself -- YouTube downloads stay on the server". Success: "updated yt-dlp <old> -> <new>".
  - Otherwise, once per day: run `yt-dlp --update-to nightly` (see daily update).
  - Otherwise: "yt-dlp <v> is current".
- **Dashboard minimum version**: `GET <dashboard_url>/ytdl/api/config/ytdl-client`, unauthenticated, no redirects, 5 s timeout, at most 256 KB; reads `min_ytdlp_version`. Unreachable means "no floor", and a working binary is left alone. A floor that cannot be ordered as a version is logged as an error telling the operator to set `YTDL_MIN_YTDLP_VERSION` to a zero-padded `YYYY.MM.DD`.
- **Install**: requires the tools folder to be creatable and at least the companion-wide free-space margin plus 60 MiB free (if free space cannot be read, proceeds). Downloads `SHA2-256SUMS` and the platform binary from `https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest/download/`. Redirects are followed only to https on `github.com`, `www.github.com` or `*.githubusercontent.com`; any other redirect is refused. Ceilings: binary 150 MiB, checksum file 1 MiB. The file is written as `<name>.new`, its SHA-256 compared to the checksum list (if the list does not name the file, install is refused; on a mismatch the list is fetched once more in case a new nightly was cut in between), made executable on macOS/Linux (only after verification), then renamed into place. Any failure leaves the previous binary untouched. Download timeout 300 s.
- **Daily update** (`--update-to nightly`, 300 s limit):
  - Skipped if config `ytdlp_max_age_days` is 0 or negative (default 21; non-numbers use 21 with an error logged), or if the version cannot be dated (or is dated in the future).
  - Skipped if a successful check within the last 20 hours left this exact version on the nightly channel (stamp file `yt-dlp.update-check.json` in the tools folder); published as "yt-dlp <v> was the newest nightly <N> h ago; next check after 20 h" with a "latest" mark.
  - Update could not run, and the binary is older than the max age: published as STALE (still usable): "yt-dlp <v> is <N> days old and it could not update itself -- YouTube downloads on this computer may start failing". This surfaces as the capability `warning`.
  - Update could not run, younger than the max age: "yt-dlp <v> (<N> days old); could not check for a newer nightly build today, will try again on the next pass".
  - Update ran and nothing newer exists: "yt-dlp <v> is the newest nightly build (<N> days old; checked, nothing newer to take)", marked latest.
  - Update ran and changed the version: "yt-dlp <old> (<N> days old) updated to <new>"; ok only if not below the floor. A downgrade is logged.
- **Sidecar tools on the same thread**: each pass also asks the sidecar-tools module (outside this part) to keep ffmpeg/ffprobe (always, even with the downloader off) and deno (only with the downloader on) installed. Its result is kept beside yt-dlp's.
- **Fleet report block** (`sync_guard.ytdlp`, sent with the companion's status report): version, action, ok, `stale` (true only for the STALE verdict), `latest`, `age_days`, message (300 characters), `checked_at`, and an optional `sidecar` block (ok, action, up to 4 failed tool names, cause, consecutive failures, message, checked_at). Empty if no check has run yet.
- **Settings > YOUTUBE warning line**: when the sidecar install has failed on 2 or more consecutive passes: "⚠ This computer cannot install ffmpeg, so it will not make proxies or take fleet media work", plus ": <cause>" when known.

## Terms acceptance (per computer)
(source: ytdl_attestation.py)

- A notice titled "Accept YouTube Terms" (text version `2026-08-17.1`), with four numbered statements: you confirm you have the right to use the material; you are responsible for YouTube's terms and copyright law; CC Sync grants no rights in downloaded material; your username, this machine's name, the clip and the time are recorded. It also says downloads are paced, may fail, and the feature may stop working.
- Accepting writes `~/.ccsync/state/ytdl-attestation.json` with version, editor name and UTC time. Messages: success "Recorded. YouTube downloads can now run on this computer, for you."; no editor signed in "sign in first -- the record has to say who accepted these terms"; write failure "couldn't save that (<error>)".
- The computer counts as accepted only if the file exists, its version equals the current text version, and its editor equals the signed-in editor. A re-worded notice, a different editor, or a missing/unreadable file all mean not accepted, which blocks local downloads (capability reason 5).
- The window or menu item that shows this notice is outside this part.

## YouTube sign-in: the cookie jar
(source: ytdl_cookies.py)

- **Which file is used** (only when site `youtube_unblock` is on): config `ytdl_cookies_file` if set and the file exists; otherwise `~/.ccsync/youtube-cookies.txt` if it exists; otherwise none (anonymous only). A configured path that does not exist means none.
- **Installing a picked cookies.txt** (from a tray/settings action outside this part): validated for shape only:
  - Must look like a Netscape cookies file; otherwise "that is not a cookies.txt in Netscape format. Export it with a \"cookies.txt\" browser extension, not Save As".
  - Must contain at least 2 of the login cookies `SID`, `SAPISID`, `SSID`, `HSID`, `APISID`, `LOGIN_INFO` on a youtube.com domain; otherwise "those cookies are not from a signed-in YouTube session (no login cookies found). Sign in to YouTube in the browser first, then export".
  - Unreadable source: "couldn't read that file (<error>)". Write failure: "couldn't save the cookies (<error>)".
  - On success the file is written to `~/.ccsync/youtube-cookies.txt` with owner-only permissions (owner-only ACL on Windows, mode 0600 elsewhere), set before any content is written, via a temporary `.new` file then rename. The status is marked ok ("fresh sign-in"). Message: "YouTube sign-in saved: your downloads can now reach age-restricted clips".
- **Health status** for the tray, from `~/.ccsync/state/ytdl-cookies-status.json` and the cookie file:
  - `none`: no cookie file in use (or the site flag is off).
  - `stale`: a real download with the cookies was refused with one of: "cookies are no longer valid", "sign in to confirm you're not a bot", "sign in to confirm your age", "this video may be inappropriate for some users", "please sign in to view this video", "login required", "the page needs to be reloaded". Carries `aged: true` when the stale record is more than 7 days old.
  - The recorded reason for "the page needs to be reloaded" reads "YouTube is refusing your signed-in session (the page needs to be reloaded). Downloads are continuing without it."; others read "yt-dlp: <phrase>".
  - `expired`: the latest expiry among the login cookies in the file is in the past ("the login cookies in the file have expired").
  - `ok`: otherwise.
  - Precedence: none, then stale, then expired, then ok.
- The tray line that renders this health is outside this part.

## YouTube sign-in: one-click browser sign-in
(source: ytdl_browser_login.py)

- Refused when site `youtube_unblock` is off (same off message as above).
- **Browser choice**: environment variable `CCSYNC_YT_BROWSER` (a path to a browser executable) wins if the file exists (otherwise warned and ignored). Else, in order: Windows: Microsoft Edge, Google Chrome (including per-user install), Brave. macOS: Google Chrome, Microsoft Edge, Brave, Chromium. Linux: Chrome, Chromium, Edge found on the path. Safari and Firefox are never used. None found: "no Chromium browser found (Microsoft Edge, Google Chrome or Brave). Install one, or use the cookies.txt file instead".
- **Private profile** at `~/.ccsync/yt-login-profile` (made owner-only where possible), kept between sign-ins. Creation failure: "couldn't create the sign-in profile folder (<error>)".
- **Launch**: the browser is started with that profile, a remote-debugging port on a free loopback port, no first-run or default-browser prompts, sync disabled, translation disabled, a 1024x820 window, opening Google's sign-in page with YouTube as the continue address. Launch failure: "couldn't start <browser> (<error>)".
- **Progress callbacks** to the caller: first "<browser> is opening. Sign in to YouTube in that window. Close the window to cancel.", then "waiting for you to finish signing in" every 5 s with elapsed and remaining seconds, then "signed in, saving your session".
- **Waiting**: the debugging port must answer within 30 s ("<browser> started but its sign-in window never became reachable. Close any leftover windows and try again"); if no page can be attached: "the sign-in window opened but could not be inspected - try again". Then every 1 s the browser's cookies are read until at least 2 YouTube login cookies exist; up to 10 minutes. If the person closes the window: "the browser was closed before the sign-in finished - nothing saved". Timeout: "the sign-in did not finish in time. Nothing was saved - try again from Settings > YOUTUBE".
- **Saving**: only cookies on youtube.com and google.com domains (and their subdomains) are written, as a Netscape cookies file with a header warning "This is a live Google session: do not share it.", through the same validate-and-save path as a picked file. A green check page "Signed in to YouTube. Closing this window..." is shown for 2 s.
- **Cleanup always**: the browser is asked to close, given 5 s, then terminated, then killed (3 s each).
- A one-line description of which browser would be used is available for diagnostics.

## Opening a downloaded clip's folder
(source: ytdl_server.py `build_reveal_response`)

- **`POST /ytdl/reveal`**, body `{"rel_path": "<project label>/<path>"}`, a path under the Projects root. Malformed JSON: 400.
- Site `youtube_download` off: 200 `ok: false`.
- Path refused as escaping the tree (absolute path, drive letter, UNC path, `..`, or a symlink resolving outside): 400 with the reason. Projects mount not configured: 200 `ok: false` with the reason.
- The Projects root on this computer is `<local_root>/Projects`, unless the shared companion mounts file (`~/.broll-companion.json`, `mounts.projects`) names another folder.
- File exists: open the file manager with the file selected. Message "Showing <name> in <folder>".
- File missing but its folder exists: open the folder, `absent: true`, message "<name> is not on this computer - opened <folder> instead. YouTube originals only sync up, so a clip another editor downloaded, or one the server downloaded, stays on the NAS until you ask for it."
- Neither exists: `ok: false`, `absent: true`, "<path> is not on this computer. YouTube originals only sync up, ..." (nothing is opened).
- Windows uses Explorer (`/select,"<path>"` with the quotes around the path only); a path containing `"` is refused ("could not open the file manager: ..."). macOS uses `open -R` (select) or `open`. An application bundle or disk image is always revealed, never opened. Other systems: `ok: false`, "opening a folder is only supported on Windows and macOS. The file is at <path>".
- No shell is ever involved; the file manager is started windowless with a cleaned environment.

## Fetching one server-downloaded clip to this computer
(source: ytdl_server.py `build_fetch_response`)

- **`POST /ytdl/fetch`**, body `{"rel_path": ...}` (same as reveal). Same site gate and path checks.
- Already on this computer: `ok: true`, `state: "done"`, "<name> is on this computer".
- Otherwise the b-roll fetch machinery (outside this part) is asked to copy that one file down from the NAS's Projects folder. Its refusal reasons (for example, drive not mounted) come back as `state: "failed"` with its message.
- Answers: `downloading` with progress and "downloading <name> from the NAS"; `done` (re-checked on disk) with "<name> is on this computer", or `failed` "the download finished but the file is not there - try again"; `failed` with the fetcher's message or "the download failed". The page polls by repeating the call.

## Auto-import of YouTube clips into the open Resolve project
(source: youtube_import.py)

- **What it does**: watches `<project folder>/Youtube/` for the project currently open in DaVinci Resolve, and files settled video files into Resolve's media pool: clips in `Youtube/<term>/` go to bin `Master/Youtube/<term>`; clips loose in `Youtube/` itself (pasted-URL downloads) go to `Master/Youtube`. Only those two folder levels are read. A folder named `Proxy` (any case) and dot-folders are skipped.
- **Config**:
  - `youtube_import_enabled` (default true). When false the worker never starts and the state is `disabled`.
  - `youtube_import_scan_interval` seconds (default 60; 0 or less means 60).
  - `youtube_import_min_age_seconds` (default 120): a file must be at least this old by modified time.
  - `youtube_import_batch_limit` (default 20): clips per bin per pass.
  - `youtube_import_max_failures` (default 3): import attempts per file before giving up for this run of the companion.
- **Timing**: a check every 15 s; a folder scan when the scan interval has passed, on the first check after start, when the open project changes, or immediately on the next check when the last pass hit the batch limit or was interrupted.
- **What counts as a clip**: extensions `.mp4`, `.mov`, `.mkv`, `.webm`, `.m4v`; not dot-files; not ending `.partial`, `.tmp`, `.lock`; not a stem ending `.fNNN`, `.temp`, `.editready` or `.original`. Sidecar `.credits.json` and `manifest.json` are therefore never imported. A directory named like a clip is skipped.
- **Settled**: older than the minimum age AND the same size and modified time as on the previous scan.
- **Which folder is this project**: the dashboard's project-to-folder mapping (by lower-cased project name) wins; otherwise a guess by name-token overlap, accepted only if `<guess>/Youtube` exists. No answer means state `no-project-match`. The answer is cached for one scan interval.
- **Duplicates**: a file is not imported if it is already in the media pool under either its local spelling or its canonical `P:\` spelling. Imported clips are stored in Resolve under the canonical spelling where possible, so they are online on every machine. Nothing is remembered between runs: the disk minus the media pool is recomputed each time, so a clip deleted from the pool while its file stays on disk comes back after a companion restart.
- **States** (also reported to the dashboard): `disabled`, `drive-absent` (local root not present), `paused` (sync paused), `resolve-closed` (no project open, project ignored, or the Resolve connection explicitly down), `no-project-match`, `waiting-settle`, `importing`, `nothing-to-do`, `idle`. Checked in that order.
- **Status fields**: state, pending (ready plus still arriving), imported this session, failed this session, last import time, last bin, last error, given up count, and a sentence:
  - given up: "<N> downloaded clip(s) could not be filed into Resolve. CCSync tries them again the next time it starts." plus " Last error: <error>".
  - `disabled`: "Filing YouTube clips into Resolve is switched off on this computer."
  - `drive-absent`: "The sync drive is not available, so downloaded clips cannot be filed into Resolve."
  - `paused`: "Syncing is paused, so downloaded clips are waiting to go into Resolve."
  - `resolve-closed`: "Resolve is closed, so downloaded clips are waiting to go into it."
  - `no-project-match`: "This Resolve project has no folder on the server yet, so downloaded clips cannot be filed into it. Ask your admin."
  - With pending clips the sentence is prefixed "<N> downloaded clip(s) is/are waiting. ". Other states: empty sentence.
- **Error handling**: an import that touched nothing stops the pass; per-file failures are counted. Error texts: "the import failed -- see the log", "the import returned nothing usable", or the bridge's message, else "the import was refused".

## Music: where the library is on this computer
(source: music_server.py `default_music_mount`, `resolve_music_mounts`, `local_path_for`)

- The music page is served from the NAS and names a track only as a share name plus a path relative to the share (`{"share": "music", "rel_path": "Cinematic/Slow Build.wav"}`), never as a full path. The companion translates it.
- The only share is `music`. Its folder on this computer is `<local_root>/Assets/Music`, unless `~/.broll-companion.json` has a non-blank `mounts.music` entry, which wins. No local root configured means no mount.
- Path refusals (HTTP 400): absolute paths, drive letters, UNC paths, `..` components, and anything that still resolves outside the share root (for example via a symlink). Share not configured: HTTP 200 `ok: false` with the reason.

## Music: send a track to DaVinci Resolve
(source: music_server.py `build_send_response`, `call`, `worker_command`; music_worker.py)

- **`POST /music/send`**, body `{"action": "bin" | "under" | "insert", "share": ..., "rel_path": ..., "track": <optional number>}`. Errors use the key `error` (the music page's convention). Malformed JSON: 400 "invalid JSON body".
  - Unknown action (anything but the three): 400 "unknown action '<x>'". The status action is not reachable through this route.
  - Path refused: 400. Mount missing: 200 `ok: false`.
  - `track` present but not a number: 400 "track must be a number, got <x>".
- **Missing track: fetched on demand from the NAS** when the music mount is the default `<local_root>/Assets/Music` (not an explicit mounts-file entry) and this computer is not the base rig (`mode = "base"`). Otherwise: 200 `ok: false`, "file not found at <path> - is the share mounted?".
  - The b-roll fetch machinery (outside this part) copies the one file from the NAS's `Assets/Music` folder. Its refusals (for example tree not mounted) are returned as the `error`.
  - While copying: `ok: false`, `state: "downloading"`, error text "syncing the track to this computer: <N>%" (or "syncing the track to this computer…" without a percentage), plus `progress`. The page re-sends the same request about every 1.5 s.
  - Too many fetches at once: `ok: true`, `state: "busy"`, `retry_after` and a message from the fetcher (its default begins "not sent yet").
  - Fetch failed: `ok: false`, "couldn't sync the track from the NAS: <reason or 'the download failed'>".
  - Done but the file is not there: "file not found at <path> - is the share mounted?".
  - When the file is found already in place, a finished fetch record for it is cleared.
- **The Resolve work runs in a separate short-lived process** (the companion executable re-run with `--music-resolve-worker <json>`, or `python -m ccsync_companion.music_worker <json>` from source), windowless, with a cleaned environment, and a 90-second limit.
  - Before starting it, the companion looks at the computer's network table: if Resolve's scripting server is absent or still starting, it answers at once without starting the process: "could not reach DaVinci Resolve (<reason>). Is it running, with Preferences > System > General > External scripting = Local?".
  - Timeout: "Resolve did not respond within 90s. It is usually busy, showing a dialog, or on the Project Manager window."
  - Cannot start the process: "could not start the Resolve worker: <error>".
  - No output: the last line of its error output, or "the Resolve worker produced no output (exit <code>)". Output that is not JSON: the first 400 characters.
- **In Resolve, every action** first requires a connection (the same "could not reach DaVinci Resolve..." message) and an open project ("no project is open in Resolve (the Project Manager window counts as no project)").
- **Importing (shared by all three actions)**: if any clip anywhere in the media pool already points at the file (under its local spelling or its canonical `P:\` spelling), that clip is reused. Otherwise the file is imported into a bin named `Music` at the top of the media pool (found anywhere in the bin tree by name, created at the top if missing), and then re-pointed to its canonical `P:\` spelling where one exists so it is online on other machines (best effort, one try). Resolve refusing: "Resolve refused to import <name>".
- **`bin`**: import only. Answer note "imported to the Music bin" or "already in the media pool (Music)", plus the clip name.
- **`under`** ("place underneath"): needs an open timeline ("no timeline is open"). Finds the lowest audio track, starting at A2 (A1 is kept for sync/dialogue audio), with nothing across the span from the playhead for the clip's length; if none is free, adds a new stereo audio track ("could not add an audio track" on failure). Places the clip audio-only at the playhead. Nothing else moves. Note: "placed on A<n> at the playhead -- nothing moved" or "... (new track) -- nothing moved". Returns track and frame.
- **`insert`** (ripple insert): needs an open timeline. Track is the request's `track` or A2 by default; if that track does not exist, one stereo track is added. Places the clip at the playhead on that track and pushes every clip at or after the playhead on that track later by the placed clip's actual length. Refusals, all before anything is changed:
  - The playhead is inside a clip on that track: "the playhead is inside a clip on A<n> (frame X to Y), so it cannot be rippled whole. Move the playhead to a cut, or razor the clip there first, or use 'place underneath'."
  - A clip to be moved has no media pool source (compound, Fusion or generator clip): "A<n> holds a clip with no media pool source (compound, fusion or generator) at frame X -- it cannot be safely re-appended. Use 'place underneath'."
  - A clip to be moved is linked to video: "A<n> is linked to video at frame X -- rippling it alone would desync sync sound. Use 'place underneath'."
  - On any failure after clips are removed, everything placed is removed and the original clips are re-placed at their old positions: "insert failed; rolled back <restored>/<total> clip(s) on A<n>". Rolled-back clips are fresh placements (their per-clip settings are not preserved).
  - Success note: "inserted at the playhead on A<n>, <k> clip(s) rippled later".
- **Safety checks during placement**: the current timeline must still be the one read at the start ("the current timeline changed -- nothing was placed"); a placed clip that did not land at the playhead frame is removed and reported "placement failed on A<n> at frame X -- something already occupies that span, or the track is locked".
- **Playhead and length**: the playhead comes from the timeline's current timecode (drop-frame timecode understood), falling back to the timeline start. Clip length comes from its frame count, else its duration in seconds times the timeline frame rate, else its duration timecode, else one second of frames.

## Music: Resolve status
(source: music_server.py `build_status_response`, `cached_probe`; music_worker.py `act_status`)

- **`GET /music/status`**. Always 200. `{"ok": true, "project": <name>, "timeline": <name or null>, "fps", "audio_tracks", "timecode"}` (the last three only with a timeline open), or `{"ok": false, "error": ...}` with the same Resolve-unreachable / no-project / timeout messages as send.
- Answers are shared for 3 seconds: any number of status requests within that window share one worker process, and concurrent requests wait for the one in flight rather than starting their own. (The same sharing applies to the b-roll status probe, which uses this mechanism.)

## Music: show a track in its folder
(source: music_server.py `build_reveal_response`)

- **`POST /music/reveal`**, body `{"share", "rel_path"}`. Same path rules as send (400 / 200 refusals).
- File present: file manager opens with it selected, "Showing <name> in <folder>".
- File missing, folder present: folder opened, "<name> is not there - opened <folder> instead".
- Neither: `ok: false`, "<path> is not on this computer - is the share mounted?".
- Same file-manager behaviour as the YouTube reveal (Explorer on Windows, Finder on macOS, bundles revealed not opened, no shell). Other systems: "opening a folder is only supported on Windows and macOS. The file is at <path>". Failure to launch: "could not open the file manager -- see the companion's log" (details only in the log).
- Unlike the YouTube reveal, this route has no site feature flag check in this code.

## B-roll actions that run through the music worker process
(source: music_worker.py `act_broll_status`, `act_broll_insert`, `act_broll_link_proxy`)

- The separate Resolve worker process also serves three b-roll actions, which `/music/send` cannot reach: `broll_status` (answers whether Resolve can be connected to), `broll_insert` (inserts a b-roll clip range into the timeline using the shared bridge logic, default mode append), and `broll_link_proxy` (attaches an editing proxy to the media-pool clip whose file path matches; refused with reason `not_in_pool`, "that clip is not in this project's media pool"; the proxy path is re-spelled canonically when possible; Resolve's own refusal becomes "Resolve refused the proxy" when it gives no message). The routes that trigger these are in the b-roll section.
- Unknown worker action: "unknown action '<x>'". A request that is not valid JSON: "bad worker request: <error>". The worker always prints exactly one JSON answer and exits 0.

## Music ingest: embedding a dropped album on this computer
(source: music_ingest.py; shared machinery in broll_ingest.py, outside this part)

- **What it is**: an editor drops audio files on the dashboard's music page; the browser hands the batch to this companion over the loopback (`/music/ingest/*` routes, dispatched in the b-roll server); this computer claims the batch from the dashboard, analyses each track locally, posts the analysis, and uploads the audio into the NAS music library. Batch gating, run modes, checkpoints, the resumable state file, the lease, the upload queue, the progress window and the tray surfaces are the b-roll ingest machinery, described in the b-roll ingest section; the differences are listed here.
- **Differences from b-roll ingest**:
  - Never pauses proxy generation while it runs.
  - No model tier and no graphics-card memory check; a laptop without a GPU runs it. Tier is reported as "".
  - Can this computer embed at all: refused (the batch is not claimed) when the music model's runtime is missing from the build, the build's model checksum is a placeholder, or the fleet has no release feed (see Music model). Refusal text comes from the model module. If the check itself errors: "this computer could not be checked for the music indexing model".
  - The model counts as ready only when both model files are present at their pinned sizes and the runtime has not been found missing.
  - Model download: a tray balloon (built by the shared machinery) when the download starts, and "The music indexing model is ready. Indexing starts now." when it finishes; the progress window names it "the music indexing model" with percentage, rate and time left.
  - Content hash is BLAKE2b with a 16-byte digest over the whole file (read in 1 MiB blocks), as hex.
  - The library location on the NAS is the claim answer's `library_remote_rel`, else `Assets/Music`.
  - Nothing is copied into a local library folder after upload (music is not synced to editors).
  - The fleet report section carries `kind` and an empty `tier`.
- **Matching the dashboard's track list to the files this computer staged**: every row is paired with at most one staged file, by content hash first (only when the hash names a file staged here), then name plus size, then name, in order. A drop is always flat (no subfolders). Unmatched rows have no local file.
- **Per-track steps** (each checks for a stop request first; progress stages posted to the dashboard are `pending`, `transcoding`, `embedding`, `indexed`, `uploading`, `live`, or `queued_for_base_rig`):
  1. Source file must exist: otherwise failed, "the source file is not on this computer any more".
  2. Probe with ffprobe (duration, sample rate, channels, codec). Duration 0 or less: failed, "this file has no audio track that could be read". Hash the file; unreadable: "this file could not be read (<error>)".
  3. `.ogg` files only: converted to 320 kbps MP3 (metadata kept) into the batch's output folder; the hash is recomputed on the MP3. Failure: "this file could not be converted to mp3: <error>".
  4. Analyse (see Music model: embedding). If the model cannot be used on this computer, the track ends as `queued_for_base_rig` with the reason, the staged file is kept on this computer, and the audio is NOT uploaded (only the server can choose a library filename). If the file itself cannot be analysed: failed, "this track could not be analysed: <reason>".
  5. Post the result to the dashboard (embedding, dimension, model id, file name, transcoded flag, hash, size, duration from the decoded samples, sample rate/channels/codec, waveform peaks, per-window vectors). Tempo, key and loudness are not sent (left for the base rig to fill). The dashboard answers with the library filename and track id.
     - Retry when the dashboard says so (`retry: true`), on HTTP 429, 502, 503, 504, or 409 with reason `name_race` or "retry" in its text: waits 5, 15, 30, 60, 120, 300 s before tries 1 to 6 (across processing passes, not blocking), up to 6 retries per episode of refusals; the analysis is kept in memory so it is not recomputed unless the companion restarted. The item's error reads "the library is not ready yet: <detail>". The retry count resets after a success.
     - Any other refusal (for example model mismatch, validation error), or retries exhausted: failed, "the library would not take this track: <detail>".
  6. Upload the one audio file under the dashboard-chosen name. No name: failed, "the library did not name this track, so it could not be uploaded". File gone: "the audio file is not on this computer any more, so it could not be uploaded". Queue error: "this computer could not queue the track for upload". When the upload finishes, the dashboard is told the size and the track goes `live`.
- Analysis vectors are not saved in the resumable state file; a restart mid-batch re-analyses the track in progress. In-memory retry data is cleared when a batch ends.

## Music model: download, checks and embedding
(source: music_clap_sidecar.py, music_clap/__init__.py, music_clap/music_models.py, music_clap/mel_numpy.py)

- **The model**: one artefact, `clap-audio` version 1, derived from `laion/larger_clap_music_and_speech` (an audio-to-vector model). Two files: `music-clap-audio-1.onnx` (279,978,254 bytes) and `music-clap-audio-1.params.json` (1,355 bytes), each pinned by SHA-256. Output vectors have 512 numbers. Model id recorded on each track: `laion/larger_clap_music_and_speech@onnx1`.
- **Where it is stored**: `<companion tools folder>/music-clap/` (the same tools folder as yt-dlp).
- **Where it is downloaded from**: config `music_clap_feed_base` if set, else the site manifest's `release_feed_base` (published by the dashboard). File URLs are `<base>/<filename>`. Allowed hosts: the feed's own host, `github.com`, and `*.githubusercontent.com`; https required, except plain http to a loopback address (127.x, ::1, localhost).
- **Download order and refusals** (each message is what the page/tray shows):
  1. Runtime missing from this build: "this build cannot run the music indexing model (onnxruntime did not load: <error>)".
  2. Checksums still placeholders: "this build has no verified music indexing model to download yet: its checksum is still a placeholder".
  3. No feed configured: "this fleet has no release feed configured, so the music indexing model cannot be downloaded. Set the dashboard's release feed URL and the tray will fetch it".
  4. A URL on a host not allowed: "refusing to download the music indexing model: <host> is not one of the hosts this build is allowed to fetch from".
  5. Not enough space (both file sizes plus the companion-wide free-space margin; an unmeasurable disk is not a refusal): "Not enough disk space for the music indexing model: needs about X GB free at <folder>, has Y GB. Free some space and try again".
  6. Download, resumable and checksum-verified (shared fetcher). Stopped by tray exit or batch cancel: "the download was stopped - it will resume where it left off" (partial file kept). Checksum mismatch: "the music model download's checksum did not match - the file was deleted and will be fetched again". Other failure: "the music indexing model could not be downloaded: <error>".
  7. Success: "the music indexing model is ready".
- **Download progress** published: file name, bytes written, total, percent, rate, time left.
- **Readiness**: both files present at their pinned sizes (not re-hashed). The on-disk answer is cached for 60 s; the zero-cost status read (ready, runtime ready, available processors, download progress, last error) never touches the disk.
- **What `GET /music/ingest/capabilities` publishes about the model** (the route is in the b-roll server): `cached` (model on disk), `download_bytes` (0 once cached, else the two file sizes), `version`, `runtime`, `providers`, `feed` (a feed is configured), `dim`.
- **A refusal sentence** used by the tray balloon, the tray line and the page: runtime missing, placeholder checksum ("this build has no verified music indexing model yet: its checksum is still a placeholder"), or no feed ("this fleet has no release feed configured, so the music indexing model cannot be downloaded"); empty when fine.
- **Loading the model**: uses a graphics processor (CUDA or DirectML) only if this build's runtime offers one, else the processor; uses half the processor cores (at least one) so the editor's machine stays responsive. Failures: "the music indexing model is not downloaded on this computer yet", "the music indexing model's settings file is missing - it will be fetched again", "the music indexing model could not be loaded on this computer (<error>)", "the music indexing model's settings could not be read (<error>)". The loaded model (about 300 MB of memory) is released when the shared ingest machinery asks (for example when the editor returns).
- **Embedding one file**:
  - Decoded by ffmpeg straight into memory (no temporary file) as mono 32-bit float at the model's sample rate (48 kHz), at most the first 2 hours; damaged values replaced with silence. 15-minute limit. Failure: "this file could not be decoded (<error>)". Nothing decoded: "this file has no audio this computer could decode".
  - Analysis windows: 10 s each, up to 12, spread evenly across the track with 2% trimmed from each end (values read from the model's settings file); a track of 10 s or less is one zero-padded window.
  - Each window is turned into a log-mel spectrogram (a numpy reimplementation required to match the reference feature extractor bit for bit), run through the model, and the window vectors are averaged and normalised into the track vector. Wrong vector count: "the music model returned the wrong number of vectors for this file"; an unusable vector: "the music model produced an unusable vector for this file". A stop request after decoding fails the track with "stopped".
  - Duration is the decoded sample count; if decoding hit the 2-hour cap, ffprobe's longer figure is used instead.
  - Waveform overview: 900 values (0 to 255), peak per bucket, normalised to the track's own loudest point.
  - A settings file with a different `params_version` than 1 is refused, as are unsupported window, padding, truncation or log settings.
- **Probe**: ffprobe, 120 s limit; a file with no audio stream reads as duration 0. **MP3 conversion**: 15-minute limit; fails if ffmpeg errors, writes nothing, or writes a file with no audio ("transcode produced a file with no audio").
- All ffmpeg/ffprobe children are windowless, and the long ones can be killed by a tray exit or batch cancel.

## Looks redundant or overlapping

- Two parallel "is this a clip or litter" rules: the executor's intermediate-name pattern (`.fNNN`, `.temp`, `.editready`) and the importer's (`.fNNN`, `.temp`, `.editready`, `.original`, case-insensitive). They differ on `.original` and case.
- The progress mirror exists in two shapes: the `{"jobs": [...]}` list for pages and the flat dict for the tray line, computed from the same snapshot.
- `/ytdl/reveal`'s `absent` flag and `/ytdl/fetch` exist because YouTube originals do not sync down; the fetch duplicates the b-roll on-demand fetch (it is that machinery with a different NAS folder).
- Cookie installation has two entry points (picked file, browser sign-in) that converge on one save path.
- The yt-dlp "floor" update and the daily nightly update both run the same `--update-to nightly` command; the floor branch is effectively a forced version of the daily check.
- The max-age setting (`ytdlp_max_age_days`) now only grades a failed daily check as "stale", and doubles as the off switch for self-updates.
- Version, quality-ladder, naming and conversion logic are copies of the server downloader's, kept equal by tests and a build gate.
- The capability check runs twice per job (at the probe and again inside the job), plus a third drive check before writing.
- Three "show in folder" routes (`/ytdl/reveal`, `/music/reveal`, and the b-roll one) share one file-manager launcher but differ in wording, error key (`message` versus `error`) and gating (YouTube's checks the site flag, music's does not).
- Three "fetch one file from the NAS on demand" surfaces (`/ytdl/fetch`, `/music/send`'s missing-track path, and b-roll's insert) all use the b-roll fetch machinery.
- The music Resolve worker process also carries b-roll's status, insert and proxy-link actions; it is the general "run a Resolve call in a killable process" mechanism under a music name.
- The music `bin` action duplicates part of what `under` and `insert` already do (all three import into the `Music` bin first).
- Music ingest is the b-roll ingest machinery with a different per-item pipeline; two ingest products share one framework.
- The music model's download refusals are written twice with slightly different wording (the download path and the `refusal()` sentence).
- The waveform and windowing functions are ports of the indexer's (kept equal by tests), and the model catalogue and mel front end are byte copies of the indexer's.

## Claims the code does not back

- `ytdl_executor.py` module docstring: "the last clip hands the job back; the server sweeps what failed". There is no hand-back call at the end of a job; the heartbeat simply stops and the lease expires.
- `ytdl_executor.py`, `_run_ytdlp_paths` docstring: the cookies-first preference is "STICKY per executor" and "a machine that restarts starts anonymous again". In code it lives on each job object, so every new job starts anonymous, not only after a restart.
- `ytdl_executor.py` comments on `fragment_jobs` and the HLS edit-ready section describe the `web_safari` client and HLS serving as current; the code no longer pins any player client by default.
- `youtube_import.py` module docstring: "sync delivers those files to this machine like any other media". The reveal route in `ytdl_server.py` states (and its messages tell editors) that YouTube originals only sync up; files reach this machine only when downloaded locally or fetched with `/ytdl/fetch`. (Whether lane B carries them is decided in sync code outside this part.)
- `ytdl_browser_login.py` docstring: shows "Signed in -- closing" for two seconds, then pulls the cookies. In code the cookies are saved first and the done page is shown afterwards.
- `ytdlp_manager.py` `unblock_enabled` docstring says the vendor build ships "the deno n-challenge solver and the cookie sign-in" inactive; in this part, deno is passed to yt-dlp whenever a managed deno exists, with no `youtube_unblock` check here (the install gate is in the sidecar-tools module).
- `youtube_import.py` claims config values use safe numeric coercion "everywhere", but `youtube_import_enabled` is read with a plain truth test, so a string `"false"` counts as on.
- `music_ingest.py` module docstring: an item whose model fails mid-batch "is uploaded and left `queued_for_base_rig`: the audio is in the library". The code (`_queue_for_base_rig`) deliberately does NOT upload it; the file stays on the editor's computer. The `_post_uploaded` docstring repeats the "audio is in the library" claim for these items, but they are never queued for upload.
- `music_clap_sidecar.ensure` docstring orders the checks "a feed base, then free space ... 4. every URL on the allow-list"; the code checks the host allow-list before free space.
- `music_clap_sidecar` module docstring says onnxruntime "picks the best execution provider it was BUILT with"; the code picks CUDA or DirectML when offered, else CPU, and comments that the pinned package is CPU-only.
- `music_worker.py` docstring lists the request as having a `bin` field; no route in this part ever sends one, so the bin is always `Music`.

## Could not determine

- The exact free-space margin added to the 5 GiB job floor and the 60 MiB install floor (`upgrade.MIN_FREE_BYTES_MARGIN`, outside this part).
- Which tray/settings controls call the terms acceptance, cookie file picker, browser sign-in, cancel, and the cookie health line, and their exact labels (outside this part).
- Whether the deno and ffmpeg installs are checksum-gated and from where (sidecar-tools module, outside this part).
- Whether the dashboard's project-to-folder mapping used by the importer can come from anywhere other than the dashboard.
- How the dashboard reacts to the `scope_qualities`, `free_bytes` and `machine_id` fields sent in the claim.
- What the shared ingest machinery does with a music track that fails with "stopped" during embedding (a tray exit or cancel): whether it is recorded as failed or resumed.
- The exact `/music/ingest/*` route behaviours (pick, prepare, upload, progress, thumb, run, control, retry) and which of them music changes; they live in the b-roll server and shared ingest code outside this part.
- The fetcher's concurrency limit and busy message text for on-demand music and YouTube fetches (b-roll fetch module, outside this part).
- Whether the per-file content hash for a music track that is NOT `.ogg` is ever recomputed after a retry (only the transcode path re-hashes).
