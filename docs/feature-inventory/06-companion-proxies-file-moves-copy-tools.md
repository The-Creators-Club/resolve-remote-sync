# Companion: making and relinking proxies, moving files, copying camera cards, and the bundled tools

Terms used throughout:

- **Original**: a camera file (or downloaded video) in the editor's project tree.
- **Proxy**: a small, low-resolution copy of an original that editors cut with. By fleet convention it lives in a folder named `Proxy` next to the original, with the same file name stem (for example `Shoot/A001.mov` has the proxy `Shoot/Proxy/A001.mov` or `Shoot/Proxy/A001.mp4`).
- **Tree** / **local root**: the editor's copy of the shared project folder (config key `local_root`).
- **Lane A / B / C**: the companion's three sync channels (A uploads originals, B downloads proxies, C is Syncthing). Lane B only carries files inside `Proxy` folders, so an original without a proxy is invisible to every other machine.
- **BPG**: the Blackmagic Proxy Generator, a program that ships with DaVinci Resolve and makes proxies for camera formats ffmpeg cannot read (BRAW, R3D, Canon RAW).
- **Gap**: originals that have no proxy.
- **Tray**: the companion's notification-area icon and its right-click menu.
- **Toast**: an operating-system notification balloon.

## Missing-proxy notifier and background proxy generator
(source: proxy_gen.py)

### What it is
- One background task on every editor machine that (a) finds originals with no proxy and tells the editor, and (b) if enabled and ffmpeg is installed, encodes the missing proxies itself while nobody is at the keyboard.
- If both the notifier and the generator are switched off by config, the task does not start at all (log: "proxy gap notifier and generator are both disabled by config").

### Settings (config keys)
- `proxy_notify_enabled`: default true. Turns the missing-proxy toast on or off.
- Proxy generation on/off is decided by `config.proxy_generation_enabled(cfg)` (the rule lives in config.py, outside this part).
- `ffmpeg_path`: default `ffmpeg` (looked up on PATH). Blank means `ffmpeg`.
- `proxy_scan_interval`: default 900 seconds (15 minutes). How often the tree is re-walked for gaps. 0 or less falls back to 900.
- `proxy_gen_idle_seconds`: default 300 (5 minutes). Encoding starts only after this long with no keyboard or mouse input.
- `proxy_gen_min_age_seconds`: default 120. An original modified more recently than this is treated as still being written and skipped.
- `proxy_gen_max_height`: default 1080. Maximum proxy height in pixels for camera footage.
- `proxy_gen_bitrate`: default `7M`. Video bitrate for camera-footage proxies.
- `proxy_gen_max_failures`: default 3. After this many failed attempts on the same file (same path, same modified time and size) the clip is "capped" and no longer tried.
- `proxy_notify_cooldown_seconds`: default 86400 (one day). Minimum time between missing-proxy toasts, and between low-disk-space toasts. 0 disables the cooldown.
- `proxy_gen_skip_while_resolve_running`: default false. When true, no encoding at all while DaVinci Resolve is running (applies to forced runs too).
- `proxy_gen_free_space_floor_gb`: default 20. Part of the free-space floor (see below). 0 switches this part off.
- `proxy_gen_free_space_floor_pct`: default 5 (percent of the volume). The other part of the floor. 0 switches it off.
- `proxy_gen_stability_seconds`: default 5. Gap between the two size/modified-time samples used to detect a file still being copied. 0 switches the check off.
- `proxy_dry_run`: default false. Rehearsal mode: every gate runs and the log says "proxy gen [dry-run]: would encode <src> -> <dest> (<kind>)", but ffmpeg is never started and no partial file is created. Warns at startup: "proxy_dry_run = true: the generator will report what it would encode and encode nothing". `DEV ONLY` in spirit, but shipped.
- `proxy_gen_workers`: default absent, meaning "derive it": 4 clips at once when the ffmpeg build has an NVIDIA hardware encoder (NVENC), otherwise 2. A hand-set value is clamped to 1..8. A value of 0, blank, or garbage means "derive".
- All three of the free-space and stability settings accept 0 as "off"; a negative or non-numeric value logs an error and uses the default. Other numeric keys with garbage values fall back to their defaults rather than crashing.

### Timing and limits
- The task wakes every 15 seconds ("tick"), or immediately when the tray asks it to.
- A running encode is checked every 2 seconds for whether it must stop; so ffmpeg is killed within about 2 seconds of the editor touching the mouse or keyboard.
- Runaway limit per clip: the larger of 30 minutes and 60 times the source duration. An encode past it is killed and counted as a failure ("the encode was still running after N minutes").
- The verification decode uses the same runaway limit as the encode.
- Only the last 200 lines of ffmpeg's error output are kept; failure messages quote the last 5 lines, truncated to 500 characters.
- Progress shown in the tray is updated at most once per second per clip.
- The "is Resolve running?" answer used to narrow the encode width is cached for 60 seconds.
- A worker that cannot get a slot (because of the Resolve narrowing) asks again every 1 second.
- At most 64 projects are included in the per-project report.
- When killed, ffmpeg is given 5 seconds to die; if it does not, it is left to the operating system and its partial file is never published (log warning).

### Process priority (platform differences)
- Windows: ffmpeg is started with "below normal" priority and no console window.
- macOS and Linux: ffmpeg is reniced to nice 10 after it starts; failure to renice is ignored.
- ffmpeg's standard input is always closed.

### States (published to the tray and the dashboard as `state`)
Evaluated in this order; the first that applies wins:
1. `disabled`: generation is switched off by config.
2. `drive-absent`: the local root folder is not present. (If the presence check itself fails, the drive is treated as present.)
3. `paused`: the editor has paused syncing.
4. `blocked`: another feature of the companion needs the GPU and gave a reason (for example b-roll indexing goes first); the reason text is published as `blocked_reason` for the tray (such as "indexing b-roll first").
5. `misconfigured`: the machine's configuration has problems (the blocking check answered a plain yes with no reason).
6. `no-ffmpeg`: no runnable ffmpeg, or ffmpeg present but no ffprobe next to it or on PATH ("ffmpeg is here but ffprobe is not (looked for '<path>' beside it and on PATH)"). Logged once as a warning until ffmpeg appears: "proxy generation is on but <why> -- this machine will still TELL you which clips have no proxy, it just cannot make them". A missing ffmpeg is re-checked every tick, so installing ffmpeg starts generation without a restart.
7. `nothing-to-do`: the queue is empty.
8. `user-active`: someone has used the keyboard or mouse within `proxy_gen_idle_seconds`, or the idle time cannot be read (unknown idle counts as "someone is here"). Skipped for a forced run.
9. `resolve-open`: `proxy_gen_skip_while_resolve_running` is on and Resolve is running (if the Resolve check fails, it counts as running).
10. `running`: encoding.
- After a scan the state is re-evaluated in the same tick, so the tray does not show `nothing-to-do` while clips are queued.

### Scanning
- A scan runs on the first tick after start, every `proxy_scan_interval` seconds after that, whenever the tray requests a run, and immediately when the tree's drive reappears after being absent (log "proxy gen: the tree is back -- rescanning for missing proxies").
- Scans only run while the tree is present and either the notifier or the generator is on.
- The scan is limited to the projects the editor has selected to sync on this machine (when that list is available).
- Clips already capped are left out by the scan itself so they do not use up the per-project queue slots.
- The queue is one list across all projects, newest original first (ties by path).
- After a scan with a gap, the log says how many clips in how many projects have no proxy, how many were queued, how many need Resolve/BPG, and how many were given up on.

### Notification of the gap (toast)
- At most one toast per scan, at most once per "episode" (an episode ends when the gap closes or the drive comes back), and at most once per `proxy_notify_cooldown_seconds`. The time of the last toast is saved in `proxy_notify.json` in the companion's state folder so restarts do not re-nag.
- The toast names the project with the biggest gap. Text:
  - If that project has fewer than the machine total: "N clips in <Project> (M on this computer) have no proxy, so nobody else in the team can see them."
  - Otherwise: "N clips in <Project> have no proxy, so nobody else in the team can see them." (singular: "1 clip in <Project> has no proxy, so nobody else in the team can see it.")
- Followed by one of:
  - every missing clip is a format only Resolve can read: " Run the Blackmagic Proxy Generator on them."
  - generation is off: " Ask your admin to generate proxies for them."
  - no ffmpeg: " This computer has no ffmpeg, so it can only tell you."
  - otherwise: " I'll make them while you're away from the keyboard."
- Toast title comes from the site branding (`site.notify_title()`).

### Encoding a clip
- Before encoding, each queued clip is re-checked against the disk and skipped (silently, no failure counted) if:
  - it is itself a proxy: inside a folder named `Proxy` or `proxies` at any depth, a `.partial` file, or a file that would be its own output;
  - it no longer exists or is empty;
  - it was modified within `proxy_gen_min_age_seconds`;
  - its size or modified time changed between two samples `proxy_gen_stability_seconds` apart (the scan's sample usually serves as the first, so normally there is no wait);
  - it already has a proxy (for example lane B delivered one);
  - BPG is currently writing its proxy;
  - it is capped.
- Free-space floor: before writing, the free space on the drive that will hold the proxy is checked against the larger of `proxy_gen_free_space_floor_gb` and `proxy_gen_free_space_floor_pct` of the volume. Below it the clip is skipped (not counted as a failure) and:
  - the reason is published as `low_space` ("only X GB free on the drive holding <dir> (CCSync keeps Y GB clear so syncing and Resolve's cache do not run out)");
  - a toast is shown at most once per cooldown: "CCSync stopped making video proxies: <reason>. Free some space and they will resume on their own." with title "<brand>: low disk space" (via `site.notify_title("low disk space")`);
  - if free space cannot be read, encoding goes ahead.
  - The low-space flag clears on the next clip that passes the check.
- Two originals that would produce the same proxy file (same stem, different container, for example `A001.mov` and `A001.mp4`) are never encoded at once; the second is skipped.
- The proxy is written as `Proxy/<stem>.<ext>.partial` next to the original; the `Proxy` folder is created if needed (failure to create it is a failure of the clip).
- The original is probed first (duration, frame rate, timecode). An unreadable file (for example no index atom, a truncated download) is a failure.
- Two encoding recipes, chosen by the clip's footage kind (see proxy_scan):
  - camera footage ("own"): the CC Sync proxy recipe with `proxy_gen_max_height` and `proxy_gen_bitrate`, and the original's timecode copied in (Resolve refuses to link a proxy whose timecode does not match);
  - downloaded/preview footage: the b-roll preview recipe, with the probed frame rate.
  - Both write the generated container (see proxy_scan, `.mov`).
- ffmpeg is asked for a progress stream; the tray gets per-clip percent (output time divided by source duration, clamped to 0-100), ETA from ffmpeg's reported speed, and elapsed time.
- With NVENC available: first attempt on the GPU; if it fails, exactly one retry on the CPU (the GPU failure is only logged: "the GPU encode of X failed (...) -- retrying once on the CPU"). Without NVENC: one CPU attempt.
- Verification after every encode: a full decode of the new file; any decode error lines or non-zero exit fail it ("the proxy does not decode cleanly (N error line(s))"). Then its duration must be at least 97% of the source ("the proxy is X s of a Y s source -- ffmpeg stopped early").
- Publishing: if a proxy appeared under any accepted name while encoding, the new one is deleted and the clip counts as done ("first writer wins"). Otherwise the partial is renamed onto the final name. If the rename is refused (for example Resolve holds the file open), it is a failure and the partial stays ("could not put the finished proxy in place (...) -- it is still there as <name>").
- While encoding stops because of an interruption (shutdown, the editor pressed stop, syncing paused, or the user came back, including idle becoming unreadable), ffmpeg is killed, the partial is deleted, the clip goes back to the front of the queue, and every other worker stops picking up new clips for the rest of this pass. Messages: "the companion is shutting down", "you asked it to stop", "syncing is paused", "you're back at the keyboard".
- On success, the cached missing counts shrink immediately, so the tray counts down during a run.
- Every finished clip (done or failed, not interrupted or skipped) is appended to the proxy history ledger (see proxy_history), with the encoder that actually ran, source and proxy sizes, duration and wall time.

### Parallel encoding and the Resolve narrowing
- Several clips are encoded at once (width as described under `proxy_gen_workers`).
- While Resolve is running, only one clip is encoded at a time (applies to forced runs too). When Resolve closes mid-run, waiting workers widen back out within about a second (plus up to 60 s of cache).
- The width is logged once per change: "proxy gen: encoding N clip(s) at a time (NVENC|CPU|proxy_gen_workers)".

### Failure memory ("capped" clips)
- Failures are counted per file in memory only; a restart forgets them.
- A file that changes (different modified time or size) starts a fresh count.
- At the cap the log says "giving up on X after N attempt(s) ... It will be retried if the file changes, or on the next companion restart"; before it, "X failed (attempt n/N)".
- Running out of disk space never counts as a failure.

### Tray actions
- "Make the missing proxies now": forces a run (skips the idle requirement, but not pause, misconfiguration, missing ffmpeg or the Resolve rules), triggers a fresh scan immediately, and forgets every capped clip. A forced run ends when its queue is done.
- "Stop making proxies": kills encodes in flight (no partial left behind) and drops this cycle's queue; the next scheduled scan refills it. It is not a disable. If nothing is encoding, the queue is simply dropped.

### What the tray and the dashboard are told
- Tray snapshot (`gap()`): missing count, count of Resolve-only (BRAW) clips, count needing Resolve, clips left (queued plus encoding), whether encoding, which clips are encoding and how many, per-clip progress, whether this machine can generate, state, blocked reason, this session's generated and failed counts, the history rollup, and three "brakes" with one-sentence explanations:
  - capped: "N clip(s) failed too many times and CCSync has stopped trying them. It will try again if the file changes, or after CCSync restarts."
  - low_space: "CCSync stopped making proxies: <reason>. They start again on their own once there is room."
  - truncated: "There are more clips without proxies than CCSync queues at once. It will pick up the rest as the queue drains."
- Dashboard report (`coverage()`): state, enabled, missing / BRAW / needs-Resolve / own / preview counts, queue length, generated, failed, whether ffmpeg and NVENC are available, time of last scan, low-space reason, per-project counts (only projects with a gap, at most 64), the history rollup, blocked reason, and the same three brakes.

### Shutdown and sleep
- While any encode is running, the companion supplies a Windows shutdown-block reason and keeps the machine awake: "still making video proxies so the rest of the team can see this footage (N clip(s) left[, M at once])". When encoding stops, the machine may sleep again.
- On companion shutdown the generator is told to stop first; that kills ffmpeg.

### Leftover partial files
- A helper finds `Proxy/*.partial` files under the tree older than 6 hours and logs each one as a warning ("leftover half-made proxy from an interrupted encode: ... -- NOT deleted; it is excluded from every sync lane and will be redone on the next pass"). It never deletes them. (Who calls it and when is outside this part.)

### Handing off to the Blackmagic Proxy Generator
- After each tick, if a BPG launcher exists and is enabled, and the generator's state is one of `disabled`, `no-ffmpeg`, `nothing-to-do`, `user-active` or `resolve-open` (never `paused`, `misconfigured`, `drive-absent`, `blocked` or `running`), and nothing is queued or encoding, the launcher is offered the count of clips needing Resolve and the folders they are in. See the BPG section for what it then does.

## Finding originals that have no proxy (the gap scan)
(source: proxy_scan.py)

- Walks each project folder (`<local root>/Projects/<project>`) of this machine and counts every original that has no proxy beside it. Never stops the companion on an error.
- Which projects: the companion's list of project folders (identified by a marker, rule in fixer.py), with the selected projects and most recently touched ones kept first, capped at the manifest's project limit (64). Projects pushed out by the cap are counted as `dropped`.
- A blank or absent local root gives an empty result, not an error.

### What counts as an original
- Only files whose extension is in the sync lanes' video-extension list.
- Skipped entirely: macOS resource-fork files whose names start with `._`; YouTube-download work files (names matching the lanes' YouTube work-file patterns, such as `<title> [id].source.editready.<ext>`); `.insv` and `.360` files (360-degree camera files; never counted, never queued); zero-byte files; files modified within the settle window (`proxy_gen_min_age_seconds`, default 120 s).
- Folders not descended into: any folder named `Proxy` (any letter case), lane B's trash folder, and any folder whose name starts with a dot.

### What counts as "has a proxy"
- A file `Proxy/<stem>.mov` or `Proxy/<stem>.mp4` next to the original (either extension counts; existing `.mp4` proxies remain valid).
- A clip whose proxy BPG is writing right now (a hidden `.<stem>.tmp` or `.<stem>.lock` in the `Proxy` folder) is counted nowhere: neither missing nor queued.

### Classification
- `.braw`, `.r3d`, `.crm` (camera raw formats): counted as missing and as "needs Resolve" (BRAW also counted separately as `braw`), never queued for ffmpeg. The folders they are in are collected for the BPG watch list (deduplicated, at most 24 across the whole tree; the log notes when more exist).
- Everything else that is missing is queued, and classified as:
  - "own" (camera footage, full proxy quality): any file with a camera extension (`.braw`, `.mxf`, `.r3d`, `.crm`, `.mts`, `.m2ts`) wherever it lives, and any file whose path has no download marker; ambiguous paths default to own.
  - "preview" (downloaded reference footage, encoded with the b-roll preview recipe): any path component containing `youtube`, `yt` or `downloads` as a separate word (words are split on any character that is not a letter or digit, so `Kyoto` does not match `yt`, but `YouTube Downloads` and `yt-dlp` do).
- Two originals in one folder with the same stem (for example `A001.mov` and `A001.mp4`) share one proxy name; only the newest is queued, both are still counted as missing, and the log notes it ("... share a proxy name with a newer original and are not queued: ...", first 5 names).
- Clips the generator has given up on (capped) are counted as `capped` and not queued.

### Limits
- At most 500 clips queued per project, newest first; when more exist the project is marked `truncated`. Counts are always exact.

### Unreadable projects
- A project folder that cannot be walked at all (for example the drive is unplugged), or whose walk fails, is marked with an error and `partial`, and is never reported as fully covered. Text: "CCSync could not read <folder> to check its proxies[ (<reason>)]. Until it can, nobody knows whether that project's clips have proxies."
- Totals carry `unreadable` (number of such projects), the first error text, and `partial`.
- Whatever had already been counted before a failure is kept.

### Conventions other parts use
- Generated proxies are written as `.mov` (QuickTime) so BPG recognises them; the codec is HEVC for own footage and H.264 for previews.
- In-progress name: `Proxy/<stem>.mov.partial` (excluded from every sync lane).

## Pointing Resolve clips at their synced proxies (proxy relink)
(source: proxy_relink.py)

- Repoints a DaVinci Resolve clip's attached proxy to the proxy file that already sits in the tree. It never copies, moves or deletes a file. (It runs as a repeating pass from app.py; comments here say every 120 seconds; the scheduling itself is outside this part.)

### Which clips are touched
- Only clips whose original is inside the tree: under `local_root` or under the canonical drive prefix (for example `P:\`). The editor's own local or cloud media is ignored.
- Only clips whose proxy is not working. Resolve reports a working proxy as its resolution (text starting with a digit, such as "1920x1080"); "Offline", "None" or blank are not working.
- Only when a proxy file exists right now at `Proxy/<stem>.mov` or `Proxy/<stem>.mp4` next to the original. `.mov` is preferred when both exist.
- Existence is also checked through the local spelling of a canonical path (for a process or a Mac that has no `P:` drive), but the path written into Resolve is always in the original's own spelling (canonical stays canonical, so the project stays portable). A canonical `P:\...` path is always handled with Windows path rules, even on a Mac.
- Reason recorded per change: "stale" (a proxy was attached but unreachable) or "unlinked" (none attached).

### Skipped, with a reason the editor can be shown
- The clip already points at that exact proxy file and Resolve still cannot play it: not relinked; note "Resolve already points at this proxy and still cannot play it, so the proxy file itself is damaged. Delete it and CCSync will make it again."
- In the b-roll archive only: a `Proxy/<stem>.mp4` is the browser preview, not an editing proxy. If the clip's real original is on this machine (and is not a stand-in, meaning the preview's bytes saved under the original's name), the `.mp4` is not attached; note "This file is the b-roll browser preview, not an editing proxy, and the full quality original is already on this computer. CCSync left the clip on the original so you are not cutting at preview quality." Outside the archive a `.mp4` proxy is attached normally.
- A pairing Resolve has already refused is not offered again until the proxy file's modified time or size changes. This memory lasts until the companion restarts.

### Re-reading clips that were born from a stand-in (b-roll archive only)
- For an archive clip whose real original is on this machine (and is not itself a stand-in), the companion checks whether the clip's stored frame count disagrees with the file's. If so, it asks Resolve to replace the clip with its own path (forced), which makes Resolve re-read the file's real geometry.
- Questions asked cheapest first: (1) a remembered verdict for these exact bytes (keyed by file, modified time, size and the clip's stored frame count; in memory only); (2) this machine's stand-in ledger says the file is no longer the stand-in it placed; (3) the dashboard's report reply listed this archive path among stand-ins placed by any machine (`standins_known`; a reply without that key means "unknown", and earlier knowledge is kept); (4) a header-only estimate (duration times frame rate) within 1 frame of the stored count means "agrees"; (5) only then an exact frame count with ffprobe.
- If either side cannot be read, the clip is treated as agreeing (no refresh).
- The stored frame count must be supplied by the caller; without it no refresh ever happens.
- The refresh runs before any proxy link on the same clip; if it fails, the proxy link for that clip is skipped this pass.
- If Resolve accepts the refresh but the geometry did not change, that verdict is remembered until the file changes (unless an attempt inside it raised, in which case it is asked again next pass). After a successful refresh the verdict "agrees" is also remembered under the old stored count.
- If the clip had a working proxy before the refresh and has none after, the old proxy is re-attached immediately.

### Results reported for each pass
- Counts: relinked (also as `attached`), refreshed, failed, list of failing clip names, per-clip details.
- Per-clip reasons: "Resolve would not attach this proxy. Usually the proxy's timecode does not match the original." / "Resolve did not answer about this clip, so CCSync will try it again." / "This clip is not in the project's media pool any more, so there was nothing to attach the proxy to."
- One sentence for the editor (`why`), built from: "Repointed N proxy file(s) to the copies in your sync folder." / "N could not be attached: usually the proxy's timecode does not match the original." / "N got no answer from Resolve and will be tried again."
- Log summary line: "repointed N proxy link(s)[, re-read N clip(s) from their own file][, N refused by Resolve]", plus one warning per pass when any were refused ("... not retried until the proxy file changes...").
- A Resolve scripting error is a "no answer", never remembered as a refusal; only an explicit refusal (or a result with no reason) is remembered.
- The Resolve changes themselves go through the companion's Resolve bridge (link proxy; replace clip with a save point and undo journal).

## Proxy history ledger and report
(source: proxy_history.py)

- Records every clip the generator finished (made or failed; skipped and interrupted clips are not recorded).
- Files in the companion's state folder, created only when the first clip is recorded:
  - `proxy_history.jsonl`: one line per clip (UTC time, result, project, file name, full path, footage kind, encoder, source bytes, proxy bytes, media duration, encode wall time, and error text truncated to 300 characters). Rotated at 2,000,000 bytes into a single `proxy_history.jsonl.1`. Non-ASCII names are written as-is.
  - `proxy_totals.json`: running totals for all time and per local calendar day (made, failed, source bytes, proxy bytes, encode seconds, media seconds), plus first and last record times. Keeps the last 90 days. A missing or unreadable file means the totals start from zero.
  - `proxy_history.txt`: a human-readable report, written on request.
- Rate: clips finished per hour, measured over the last 60 completions (in memory only, so it restarts with the companion); needs at least 3 completions. ETA for the remaining clips is derived from it.
- Snapshot sent to the tray and the dashboard: today's totals, all-time totals, today's date key, first and last times, rate per hour (one decimal), ETA in seconds.
- Report text (plain text, written to `proxy_history.txt` when the tray asks; the tray item itself is outside this part):
  - heading "CCSync: proxies made on this machine", the ledger path, "Since: <first> (last: <last>)";
  - TODAY and ALL TIME blocks: "N proxies made, M failed", "<size> of footage → <size> of proxies (N× smaller)", "<duration> of footage covered, <duration> spent encoding";
  - "Recent rate: N clips/hour";
  - BY DAY: the 14 most recent days with made, failed, sizes and ratio;
  - LAST N CLIPS (default 60, newest first, across the current and rotated ledger): "ok" or "FAIL", time, name, project, sizes, encoder, encode time, or the error;
  - "Nothing has been encoded on this machine yet." when the ledger is empty;
  - "The proxy history could not be read." on any error.
- Sizes are shown as B/KB/MB/GB/TB (1024-based); durations as "45s", "18m", "2h 40m", "3d 4h".

## VP9 render warning
(source: vp9_guard.py)

- Purpose: warns the editor when the timeline open in DaVinci Resolve uses an original whose video codec is VP9 (typically a YouTube download), because Resolve cannot render VP9 originals at full resolution even though editing with H.264 proxies looks fine.
- Config key `vp9_guard`: on by default; off only for an explicit false (`false`, `0`, `no`, `off`, case-insensitive, or a boolean false).
- Trigger: after each successful poll of the open Resolve timeline by the companion's watcher (the watcher is outside this part). It never calls Resolve itself.
- Only clips on video tracks with a file path are considered.
- A check runs when the set of video clips (project, timeline, path and position of each) changes, or every 120 seconds for an unchanged timeline.
- Each distinct original path is read once with ffprobe. The codec answer is cached by path, size and modified time, in memory and in `vp9_codec_cache.json` in the companion's state folder (at most 5,000 entries; oldest dropped).
- A file that cannot be found (for example a proxy-only remote machine where originals are not on disk) or cannot be probed is "unknown": never warned about, and re-probed after 10 minutes (missing files are re-checked every check).
- Popup (shown through the companion's normal dialog mechanism):
  - Title: "<brand>: VP9 media in this timeline" (fallback "CC Sync: VP9 media in this timeline").
  - Body: "N source media file(s) is/are VP9 in project “<project>”, and DaVinci Resolve cannot render VP9 originals at full resolution. This timeline WILL FAIL to render with “Error decoding full resolution media”." then "It plays fine now only because Resolve is using the H.264 proxies." then "Affected clips:" listing up to 12 files, each with clip name, file name and up to 4 positions (such as "V2 clip 5", "and N more"), then "... and N more files" if more than 12. Then "How to fix it: convert each original to H.264, then relink the clip to the converted file or remake its proxy. For a folder of downloads, MontagePipeline's montage_editready.py does the conversion." and "STOP WARNING FOR THIS TIMELINE keeps this quiet until a new VP9 clip is added to this timeline."
  - Buttons: "STOP WARNING FOR THIS TIMELINE" and "CLOSE".
- Warn-once behaviour: within one companion session, the same set of VP9 files on the same timeline is not shown again after either button. A newly added VP9 file shows the popup again.
- "STOP WARNING FOR THIS TIMELINE" stores the VP9 paths for that project and timeline in `vp9_guard.json` in the state folder (at most 500 timelines; oldest dropped). A VP9 file not in that stored set still warns.
- If a stored file is later found not to be VP9 (converted in place), it is removed from the stored set, so a future VP9 file at the same path warns again.
- If the popup could not be shown (another window open, no display), the warning stays owed and is retried at the next poll.
- A warning line is also written to the log for each warning.

## Following an admin's file move from the dashboard
(source: file_moves.py)

Background: an admin can move a file or folder on the server from the dashboard's project page. The dashboard tells each machine that held a copy through the report reply (`commands.file_moves`). This machine moves its own copy, carries its proxies along, repoints Resolve clips, and answers in its next report (`file_moves_applied`). The command loop and the reporting are in app.py; this part is the rules for one move and the on-disk ledger.

### Validating a command
- Each command must have a numeric id and four relative paths (source project, source path, destination project, destination path); otherwise it is ignored.
- A path is refused if it is absolute, contains a drive-letter colon, a `.` or `..` segment, a blank segment, or any control character. Backslashes are treated as forward slashes.
- Optional fields: `is_dir` (a folder move) and `requested_by` (default "your administrator").

### Applying one move on this machine
All paths are under `<local root>/Projects/`. Nothing is ever deleted and nothing is ever overwritten. Possible outcomes, with the exact detail sentence sent back:
- Nothing at the old path: ok, "nothing at the old path on this computer". Exceptions (resume after a crash or an earlier partial attempt), all ok and followed by a relink:
  - this machine had started the move (an "applying" row) or an earlier failed attempt already moved it, and the file is now at the destination: "finished a move this computer was interrupted during" (plus proxy wording below);
  - lane B (proxy download) already carried this exact file to the destination within the last day: "proxy download had already moved it on this computer";
  - folder moves: lane B carried every file under the folder to the matching place under the destination (and nothing elsewhere): "proxy download had already moved this folder on this computer".
- Old and new path are byte-identical: ok, "already where the server has it".
- Old and new path differ only in letter case or Unicode form (a rename the server's case-sensitive disk made):
  - a folder: refused, "a folder cannot be renamed by spelling alone on this computer; ask your admin to do it in two steps";
  - a file: renamed through a temporary name `.ccsync-move-<process id>-<name>` (put back if the second step fails), and its proxies are renamed with it: "renamed to match the server's spelling[, N proxy file(s) with it]"; failure: "could not rename it on this computer: <error>".
- The destination already exists: refused, "the destination already exists on this computer (<path>)". Exception: a folder move where lane B already moved every file and only an empty source folder is left, which answers "proxy download had already moved this folder on this computer".
- A folder moved into itself: refused, "a folder cannot be moved into itself".
- The destination is not a place this machine syncs (see below): the local copy goes to the lane B trash instead:
  - trash location: `<local root>/.ccsync-trash/<YYYYMMDD-HHMMSS>/Projects/<source project>/<source path>`;
  - a single file: moved there with its proxies; ok, "trashed locally, destination not synced here" (state `not_synced_here`). Failure: "could not move it out of the way on this computer: <error>". Resolve is not relinked.
  - a folder: each file is checked against the server's listing of the destination (`rclone lsf -R` on lane A's remote, 2-minute timeout; matched by name, compared ignoring case and Unicode form, and by exact size). Only files the server is known to hold go to the trash; files that changed size since the listing, files already in the trash, files that arrived during the listing, and anything not on the server stay at the old path (lane A will upload them after the one-day exclusion). Emptied folders are removed one at a time (never a recursive delete). Answers: everything trashed: "trashed locally, destination not synced here"; some kept: "destination not synced here; kept N file(s) at the old path that the server may not have (e.g. <name>), trashed M" (still ok).
  - a folder that holds at least one original lane A would upload, when the server cannot be listed: not ok, "destination not synced here, and the server could not be asked which of these files it already holds; keeping the folder where it is and trying again" (retried on the schedule below). A folder with no originals (only proxies or sidecars) goes to the trash whole when the listing is unavailable.
- Otherwise: an intent row is written, the file or folder is renamed to the destination (folders created as needed), and for a single file its proxies follow: ok, "moved[, N proxy file(s) with it][; N proxy file(s) were in use and stayed at the old path]". Failure: "could not move it on this computer: <error>".

### "Is the destination synced here?"
- Decided from the list of Projects-relative paths this machine syncs (selected projects plus borrowed subfolders).
- Treated as synced (so the normal move happens) when: no list is available, the list is empty, the move stays inside one project, or the source is not inside any listed path. Otherwise synced only if the destination path is inside a listed path.

### Proxies follow their original
- Every file in the `Proxy` folder beside the original whose stem matches (ignoring case and Unicode form) is moved to the `Proxy` folder beside the destination.
- When the move also renames the file, the proxy takes the new stem; a plain move keeps the proxy's name.
- A proxy is never overwritten; if the target exists and is a different file, the proxy stays. A target that is the same file under a different letter case is renamed in place.
- A proxy that cannot be moved (for example Resolve has it open) stays at the old path, is logged, and is named in the answer; the move still counts as done.
- Folder moves do not move proxies separately (they travel inside the folder).

### Retry schedule for a move that could not be applied
- First retry after 10 minutes, then every hour.
- Gives up after 20 attempts or 7 days from the first attempt, whichever comes first; the state becomes `blocked` (shown on the dashboard). Before that it is `retryable`.
- A retryable entry with no next-attempt time (written by an older build) counts as due.

### Keeping the old path out of lane A
- Every move this machine has heard of keeps its old path out of lane A's uploads for 24 hours, whether it was applied or refused.
- A move that is still `retryable`, `blocked` or `applying` keeps the exclusion for as long as it stays in that state.
- Exclusions are produced relative to each lane A run's root (a project, a borrowed subfolder, or the whole tree) and in both Unicode forms (NFC and NFD), so accented names on a Mac are matched.

### Relinking Resolve clips after a move
- After a move that moved something, every media-pool clip at the old path (or under the old folder) is repointed to the new path, written in the canonical drive spelling, through the Resolve bridge's replace-clip (with save point and undo journal, tagged as a file move).
- Paths are compared ignoring letter case (Windows and macOS, not Linux) and Unicode form; the new path keeps the on-disk spelling of the remainder.
- Answers: "Resolve not relinked (<message or 'not open'>)" when the media pool cannot be read; "N Resolve clip(s) relinked[, M could not be]" otherwise (count wording from ui_copy); "Resolve relink failed (see the log)" on an unexpected error. Only a pass that found clips at the old path retires the pending relink.
- A move whose clips were not found (the project was not open) stays "relink pending" for 30 days; the app re-tries when projects change (outside this part).
- Several pending relinks in a row share one media-pool read until one of them changes the pool.
- The watcher can ask "which move took this missing file away?" (old path matching exactly, or inside a moved folder), within 30 days. Moves to the trash, and interrupted moves whose file is not actually at the new path, are never offered.

### The ledger file
- `file_moves.json` in the companion's state folder: one row per move id (last 200 kept) with paths, ok, detail (truncated to 512 characters), time, state (`done`, `retryable`, `blocked`, `applying`, `not_synced_here`), attempts, first attempt time, next attempt time, relink-pending flag and the local old and new paths; plus up to 500 "relocation" notes written when lane B followed a move on its own, kept for 24 hours.
- Written through a uniquely named temporary file and then swapped in.
- A redelivered command after a restart is not applied twice (the app reads the ledger; the decision logic is in app.py).

## ffmpeg and ffprobe: finding them, probing, and the proxy recipes
(source: ffmpeg_tools.py)

### Finding the programs
- `ffmpeg_path` config value (default `ffmpeg`). A bare name is looked up on PATH first; if not found, the companion's own managed copy in its tools folder (installed by the sidecar installer) is used. An explicit path is used only if it exists; it never falls back to a different binary.
- ffprobe is taken from the same folder as the resolved ffmpeg (keeping `.exe` on Windows), else the bare name `ffprobe`.
- Every launch resolves the program the same way, so a machine whose only ffmpeg is the managed copy works without restart once it is installed.
- Windows: every ffmpeg/ffprobe launch is hidden (no console window flashes). Output is read as UTF-8 with bad bytes replaced.

### "Is ffmpeg available?"
- Runs `ffmpeg -version` (10-second timeout). Success is cached for 300 seconds per path; failure is never cached (so installing ffmpeg takes effect immediately).
- Messages: "ffmpeg not found on PATH ('<name>')", "ffmpeg not found at '<path>'", "ffmpeg at '<path>' failed to run: <error>", "ffmpeg at '<path>' exited N".

### Hardware encoder detection
- Runs `ffmpeg -hide_banner -encoders` (20-second timeout) and reports which of `hevc_nvenc`, `h264_nvenc`, `libx265`, `libx264` the build lists. A non-empty answer is cached for the life of the process; an empty answer (probe failed) is not cached. A zero-cost "already known?" read exists for web-request callers (the b-roll ingest capability check).

### Probing a clip
- `ffprobe -v error -print_format json -show_format -show_streams` with a 60-second timeout.
- Returns: duration, frame rate, width, height, video codec, whether audio exists, audio channel count, shoot date (first 10 characters of `creation_time`), start timecode (normalised, see below), the raw start timecode as the file prints it, frame count (the container's claim only if it agrees with duration times frame rate within 1 frame or 1%, else unknown), and video bitrate (stream rate, falling back to the container's).
- Errors (all "unreadable media"): "ffprobe timed out after 60s on <name> -- unreachable drive, or a file still being written"; "ffprobe could not be run (<path>): <error>"; "ffprobe failed on <name>: <first 200 chars>" plus " -- file is truncated or incompletely downloaded" (no index atom) or " -- file is not valid media"; "... was not JSON"; "... was not an object"; "<name> has no video stream".
- Timecode source order: the container tag, then a QuickTime timecode track (`tmcd`), then any stream's tag.
- Drop-frame correction: at 29.97 or 59.94 fps, a colon-separated timecode from a file with no `tmcd` track (for example Sony cameras) is rewritten with a semicolon before the frames (drop-frame form), because Resolve refuses a proxy otherwise. A timecode from a `tmcd` track, one already containing a semicolon, or any other frame rate is left as is.

### Is a file already light enough to edit with ("edit weight")
- Yes when its codec is H.264, HEVC or any ProRes, its height is at most 1080 and its bitrate at most 12,000,000 bit/s. Unknown bitrate or a non-numeric value gives "cannot tell". Other codecs give no. (Used by b-roll ingest, outside this part.)

### Recipe: camera-footage proxy
- HEVC 10-bit (Main10), height capped at `proxy_gen_max_height` (default 1080) and never upscaled, height forced even; width scales to match.
- Target bitrate `proxy_gen_bitrate` (default 7M), peak 1.43 times it, buffer 2 times it (for example 7M gives peak 10M and buffer 14M; an unreadable bitrate uses the same value for all three).
- GPU: `hevc_nvenc`, preset p5, variable bitrate. CPU: `libx265`, preset medium, quiet logging.
- All video and all audio streams of the source are kept (first video stream plus every audio stream; a silent source still encodes); source metadata copied; source timecode written when it has one.
- Tagged `hvc1` (so QuickTime and Resolve accept it), AAC audio at 192 kbit/s, fast-start, container named explicitly (`.mov` for the generator).

### Recipe: preview / downloaded-footage proxy
- H.264 8-bit 4:2:0, height capped at 1080 (never upscaled, even height).
- GPU: `h264_nvenc` preset p5, constant quality 25. CPU: `libx264` preset medium, CRF 23.
- One keyframe per second when the source frame rate is known.
- Timecode written when given (b-roll ingest passes it; YouTube proxies have none).
- AAC 128 kbit/s, fast-start, explicit container (`.mov` for the proxy generator, `.mp4` for b-roll ingest).

### Checks
- Full decode check (`ffmpeg -v error -i <file> -f null -`); every non-blank error line counts as an error.
- Exact frame count by counting video packets with ffprobe (60-second timeout; unknown on any failure). Source and proxy frame counts must match exactly (no tolerance).

## Downloading the bundled helper programs (ffmpeg, ffprobe, deno)
(source: sidecar_tools.py)

### What and where
- The companion downloads pinned copies of three helper programs into its tools folder (the same folder as its yt-dlp):
  - Windows: `%LOCALAPPDATA%\ccsync\tools\ffmpeg.exe`, `ffprobe.exe`, `deno.exe`;
  - macOS: `~/Library/Application Support/ccsync/tools/ffmpeg`, `ffprobe`, `deno`. (The folder location itself is defined in ytdlp_manager.py.)
- Pinned versions: ffmpeg/ffprobe from the `eugeneware/ffmpeg-static` GitHub release `b6.1.1` (ffmpeg 6.1.1, gzip per platform); deno `v2.9.5` from deno's GitHub release (zip with one file). Each download's SHA-256 is hardcoded; a mismatch means nothing is installed.
- Supported machines: Windows x64, macOS Apple silicon (arm64), macOS Intel (x64). Anything else (Linux, Windows on ARM, unknown CPU): "unsupported", nothing installed ("no pinned ffmpeg for <platform>/<cpu> -- this machine cannot make proxies or index b-roll").
- Runs on the yt-dlp manager's daily background task (outside this part), never blocks startup, never shows an error dialog.

### ffmpeg and ffprobe (no feature flag)
- Installed whenever they are missing, regardless of the YouTube feature, because proxy generation and b-roll ingest need them.
- Skipped when the editor has their own ffmpeg: the configured `ffmpeg_path` is an explicit path (whether or not it exists), or a bare name found on PATH. Message: "using the ffmpeg already on this machine".
- Already installed: "ffmpeg b6.1.1 is installed". An installed binary is trusted as-is; deleting the file is the way to force a re-download.

### deno (JavaScript runtime used by yt-dlp for signed-in YouTube downloads)
- Installed only when the YouTube downloader is enabled for this site and machine (site feature `youtube_download`, and the machine's `ytdl_local_downloads` not set to false) AND the site feature `youtube_unblock` is on, AND no `deno` is already on PATH. `DORMANT` in the vendor build.
- Even if a deno file is on disk, it is handed to yt-dlp only while `youtube_unblock` is on (an unreadable flag counts as off).

### Install steps and limits
- Free-space check before downloading: needs the yt-dlp manager's margin plus 300 MB; otherwise warns ("... need about N MB (+ margin) -- not downloading them. Local YouTube downloads stay off on this machine.") and fails. If free space cannot be read, it proceeds.
- Download streams to `<asset>.new` in the tools folder; a download over 96 MB is aborted; a redirect status is refused; the hash is checked before unpacking; the binary is unpacked to `<binary>.new`, made executable (macOS only, mode 755), then swapped into place. A zip must contain the exact expected member name (no other files are extracted).
- Download timeout: the yt-dlp manager's download timeout.
- Leftover `.new` files from a killed process are overwritten next time.

### Failure reporting
- The last failure cause per tool is remembered in memory (up to 200 characters), for example a certificate error, a hash mismatch ("sha256 mismatch on <asset> (got <12 hex>, pinned <12 hex>)"), "could not unpack <asset>: ...", "could not move the verified <tool> into place: ...", "no tools dir, or not enough free space for it".
- Consecutive failed passes are counted (in memory); from the second failed pass on, a warning is logged: "sidecar: <tools> could not be installed on N consecutive passes (<cause>) -- this machine will not be offered proxy, audio or peaks work". A clean pass resets the count.
- Result messages include "could not install <tools>: <cause>", "could not install <tools> -- YouTube downloads stay on the server (<cause>)" (when ffmpeg failed) or "... -- signed-in YouTube downloads stay off on this machine (<cause>)" (deno only), "sidecar tools could not be installed (tools dir or free space) -- YouTube downloads stay on the server", "installed <tools> into <folder>", "the YouTube downloader is off for this site or switched off in config", and a status line such as "ffmpeg b6.1.1 is installed; deno v2.9.5 is installed" or "...; no JS runtime (this site has not enabled youtube_unblock)".

### HTTPS certificate fix at startup
- Once at startup, for the frozen (packaged) app, and for any macOS run, if `SSL_CERT_FILE` is not already set, the companion points HTTPS certificate checking at a certificate bundle: certifi's if installed, else the first existing of `/etc/ssl/cert.pem`, `/private/etc/ssl/cert.pem`, `/opt/homebrew/etc/openssl@3/cert.pem`, `/usr/local/etc/openssl@3/cert.pem`, `/etc/ssl/certs/ca-certificates.crt`, `/etc/pki/tls/certs/ca-bundle.crt`. It also sets `SSL_CERT_DIR` if unset. This affects every HTTPS download in the process (yt-dlp, these tools, upgrades, release feed).
- If no bundle is found: warning "no CA bundle was found on this machine, so HTTPS downloads (yt-dlp, ffmpeg, deno, the upgrade channel) may fail to verify certificates (CR-280)". An existing `SSL_CERT_FILE` always wins.

## Copying camera cards and drives for the footage sorter (fleet jobs `card-ingest` and `drive-copy`)
(source: card_copy.py)

Background: the footage sorter (another program, driven from the dashboard) plans which files on a camera card or a local drive go where, and sends the plan to this machine as a fleet job. This part is the copier that carries the plan out and returns a receipt. Job claiming, heartbeats and posting results are outside this part (jobs_runner).

### Job kinds and inputs
- `card-ingest`: copy from a camera card named by its volume serial number (`inputs.serial`); a source given as a plain string is a path on that card.
- `drive-copy`: copy from a local drive; plain-string sources are read from `inputs.src_root` (`local:<serial>`), or from `local:<inputs.serial>`. Missing both: "a drive-copy must name its source (a local:<serial> root)".
- Each copy names `src`, `dst` (a root and relative path), `size`, and a write `mode`: `copy` (default), `resume` or `collision`. Any other mode fails that file: "'<mode>' is not a write mode this companion knows".
- Roots: `card:<serial>`, `local:<serial>`, or one of the fleet's named roots (`pool`, `vault`, `media`, `tree`) resolved per machine by job_paths.
- Optional `folders` list: folders created before any file is copied (failure: "could not make the folder <path>: <error>", retryable, stops the job).
- Missing `copies` list: "the job has no copies list". Wrong kind: "'<kind>' is not a card copy kind".

### Before anything is copied
- The card must be in a reader on this machine (removable or fixed readers, never the system disk). If not: "card <serial> is not in a card reader on this computer, so nothing was copied" (not retryable). If the drive letter that last held this card now holds another: "drive <X> now holds a different card (<serial>), not <wanted>: nothing was copied" (not retryable). Missing serial: "the job named no card serial".
- For a drive copy, a source drive that is not present: "the drive with serial <serial> is not on this computer" (retryable).
- Every destination root must be placeable on this machine before copying starts (an unmounted pool fails the whole job up front rather than file by file).
- While a card is being ingested it is marked busy, so nothing else in the companion reads that volume (sorter_cards).
- Paths inside a volume are refused if empty ("the job named no path inside the volume"), containing control characters, absolute, containing `..`, containing a `:` in any part (drive letter or alternate data stream), or resolving outside the volume. All not retryable.

### Automatic backups copy only at home
- A `drive-copy` with `homeOnly` set first checks whether this computer is on the NAS's home network: three TCP connections to the SMB port (445) of `inputs.homeHost` or, if absent, the host of the pool share (on Windows a mapped pool drive is translated to its network path); half-second timeout each. Home means at least two answered and the median round trip is under `homeRttMs` (default 15 ms).
- Not home: "away from home: the NAS's home address <host> did not answer; nothing was copied" or "... answered in N ms, not like the same network (under 15 ms); nothing was copied". No host known: "away from home: cannot tell, no homeHost and no pool share to find the NAS by".

### Rules for every file (both copiers)
- Never overwrite anything.
- The source's current size must equal the planned size, else that file fails: "the source is N bytes now and the job listed M: it changed since it was scanned". Unreadable source: "the source cannot be read (<error>)"; not a file: "the source is not a file".
- Destination decisions:
  - nothing there: write;
  - something there of the same size: compared byte for byte with the source; identical is `skipped` (counted as verified), different is a `conflict` ("a different file of the same size is already there (<why>); it was left alone");
  - a folder or link there: conflict ("a folder or link is already there; it was left alone");
  - mode `resume` and a shorter file there: finish it (below);
  - any other file there: conflict ("a different file is already there; it was left alone");
  - mode `collision`: write beside it as `name (2).ext`, `name (3).ext` ... up to 99; if the plain name or any renamed copy is already a byte-identical copy (from an interrupted earlier run), report `skipped`; if 99 renamed copies exist: conflict ("99 renamed copies of it are already there").
  - destination unreadable: fails ("the destination cannot be read (<error>)").
- If a read error happens and the card is no longer in any reader, the job stops (retryable) with "the card was taken out of its reader" instead of failing each remaining file.
- A stop request (halt or cancel from the job runner) stops the job between or during files; what landed before is still reported.

### The Python copier (macOS, Linux, Windows without TeraCopy, or when TeraCopy cannot be used for a file)
- Copies through an 8 MB buffer into `<destination>.partial` (a leftover `.partial` from a crashed run is deleted first), hashing as it reads (BLAKE2b), flushes to disk, copies the source's timestamps, reads the whole copy back and compares the hash, then renames it into place without replacing anything (Windows rename refuses an existing name; elsewhere a hard link is made and the partial removed, or on filesystems without hard links an existence check right before the rename).
- The read-back bypasses the operating system's file cache where possible (Windows: unbuffered read; macOS: no-cache on both write and read; Linux: cache pages dropped first), so the check reads the drive, not memory. If that is not possible it reads normally.
- Failures: "verify failed: the copy is N bytes and the source M", "verify failed: the copy read back differs from the source", "verify failed: the copy cannot be read back / could not be verified (<error>)", "the copy failed (<error>)", "could not make the destination folder (<error>)". A file that appears at the destination during the copy becomes a conflict ("a file appeared at the destination during the copy; it was left alone"). In every failure the `.partial` is deleted.
- Resume: builds a new `.partial` from the existing short file (each byte compared with the card; any difference is a conflict "the file already there is not the start of the card's file; it was left alone") plus the rest of the card's file, verifies the whole file, checks the short file has not changed size, then swaps it in. A short file that changed size meanwhile is a conflict.

### The TeraCopy copier (Windows only)
- Used when TeraCopy is detected and usable (see the TeraCopy section) and only for files whose destination is a Windows drive path and keeps the source's file name; other files go to the Python copier. Log when not used: "card copy: using the Python copier (<why>)".
- Files are grouped by destination folder and by switch (plain copy = skip existing, resume = overwrite only if size differs, collision = rename), run one group at a time, shorter folder paths first and plain copies before resumes before renames.
- Just before each group starts, each destination is looked at again; anything that appeared is skipped or a conflict. Two files in one plain-copy group going to the same name (ignoring case): the later is a conflict ("another file in this job is going to the same name; it was left alone").
- A resume via TeraCopy is allowed only if the existing file's first and last MiB match the card; otherwise a conflict.
- TeraCopy writes in place (no `.partial`). Receipt per file: verified by TeraCopy and the right size on disk is `copied, verified`; verified but missing or wrong size: failed ("TeraCopy reported it verified but <name> is missing / N bytes at the destination"); a TeraCopy error result: failed with its message; right size but not hash-verified by TeraCopy: `copied, verified: false`; otherwise failed ("it did not reach the destination whole (N of M bytes)"). If TeraCopy could not be started: every file in the group fails "TeraCopy could not be run (<error>)". If the job was stopped mid-group, files without a verified record are not reported as landed.
- When a collision file's new name is not in TeraCopy's record, the companion looks for a new `name (N).ext` of the right size that was not there before.
- `teracopy_allow_unverified` (config): when true, TeraCopy is not required to report a hash verify.

### Receipt and progress
- Result: lists `copied`, `skipped`, `conflicts`, `failed` (each entry with source, destination, size, verified flag, written file name, or reason), and `copier` = `teracopy` or `python`. If the job was stopped, the reason and whether a retry makes sense are available to the caller.
- Live progress body (for the sorter's progress display): bytes done and total, files done and total, the file in hand, phase `copy` or `verify`, copier, and bytes per second averaged over about the last 5 seconds (0 during verify).

## Driving TeraCopy for card copies (Windows only)
(source: teracopy.py)

TeraCopy is a third-party Windows file copier with its own hash verification. Only one TeraCopy runs at a time; launching it again hands the job to the running copy and exits immediately, so the companion reads TeraCopy's own job history to learn what happened.

### When TeraCopy is used
- Windows only ("TeraCopy is Windows-only" elsewhere).
- Config `card_copier`: default `auto`; `python` turns TeraCopy off ("card_copier is set to python").
- Config `teracopy_path`: the program location; if set but the file does not exist, TeraCopy counts as not installed. Otherwise `C:\Program Files\TeraCopy\TeraCopy.exe` or `C:\Program Files (x86)\TeraCopy\TeraCopy.exe`. Not found: "TeraCopy is not installed".
- TeraCopy's verify must be on: `TestAlways=1` under `[Transfer]` in `%APPDATA%\TeraCopy\Options.ini`. Otherwise refused with "TeraCopy verify is OFF: set TestAlways=1 under [Transfer] in Options.ini, then restart TeraCopy so it reloads the file", or if the file is missing "TeraCopy Options.ini not found at <path>: launch TeraCopy once, then re-check". Config `teracopy_allow_unverified` (true/1/yes/on) allows TeraCopy anyway.
- The companion's capability report gets two facts: TeraCopy usable here, and whether its verify is on.
- An install check (not called from this part) lists warnings: program not found, history folder `%APPDATA%\TeraCopy\History` missing ("... copies can then only be checked by presence and size, never by TeraCopy's own hash verify"), verify off.

### Launching a job
- A list file is written (UTF-8, Windows line endings, one path per line) into `%TEMP%\ccsync-teracopy-lists\`, named `<tag>-<unix seconds>[-N].txt` (tag = destination folder name with anything other than ASCII letters, digits, `_` and `-` replaced; never overwrites another list). List files older than 14 days are deleted at each launch.
- Command line: `"<exe>" Copy *"<list>" "<dest>" <switch> /Close`, started hidden and detached. Switches: `/SkipAll` (plain copy, never replace), `/OverwriteDiffSize` (resume), `/RenameCopied` (collision). A path containing a double quote is refused ("teracopy: unusable path (empty, or contains a quote)"). Empty list: "teracopy: nothing to copy"; no destination: "teracopy: no destination". The destination folder is created.
- Launches are made one at a time inside the companion. After each launch it waits for TeraCopy's history database for this job (listing these files and this destination) to appear: up to 20 seconds the first time, 6 seconds on re-launches or for 5 minutes after any launch that never registered. A database listing our files but with no run yet for 3 seconds counts as queued and accepted. If it never appears, the job is launched again, up to 3 tries in total (only when the history folder exists). Log: "TeraCopy (<tag>): no history record of this job within N s of launch", "... launching it again", "... could not launch: <error>".

### Waiting for the job
- Polls every 5 seconds. Reads only history databases created after the launch (5-second slack) and not present before it, whose file list belongs to this job and whose run targets this destination.
- States read: missing, locked (being written; never treated as finished), queued, running, copied (copy phase done), done (copy and verify phases done).
- Ends when: done; copy finished and verify not expected; copy finished with no verify pass seen within 3 minutes; TeraCopy's process has been gone for 60 seconds; no job record appeared and TeraCopy is not running after 2 minutes; the time limit (30 minutes plus the total bytes at 20 MB/s) passes; or the job runner asks to stop (TeraCopy itself is never killed, since it may also be copying the person's own files).
- Every 60 seconds a log line: "TeraCopy (<tag>): <state>, N/M file(s) verified, K min elapsed." or "waiting (<state>), K min elapsed."
- Whether TeraCopy is running is checked through the companion's process snapshot, falling back to `tasklist` (15-second timeout).

### Results
- Codes: 0 every file copied and hash-verified ("N/M file(s) copied and verified."); 10 finished but some files not verified ("finished with N of M file(s) not verified.") or verify off ("copied, verify is off: nothing is verified."); 11 a file missing or wrong size at the destination; 12 files present at the right size but TeraCopy's record unreadable ("... treating as UNCONFIRMED."); 13 stopped by request (only TeraCopy-verified files count as landed).
- Per-file receipts from the history: result (3 = copied and verified, the only success; 1 = copied not verified; 2 = queued), hash, renamed file name if TeraCopy renamed it, and message. A file with no record counts as outstanding.
- Without a readable record, a presence-and-size check of the destination is used, always reported as unverified.
- TeraCopy writes in place: a stopped job can leave a short file at the final name, which the sorter's next plan resumes.

## Starting the Blackmagic Proxy Generator for camera-raw clips
(source: bpg.py)

BPG is DaVinci Resolve started with the `-pg` argument. It takes no file list: it watches the folders listed in its own settings file and makes a proxy for everything there that has none. Its window opens idle with a Start button.

### Settings (config keys)
- `bpg_enabled`: true/false. When absent it is derived: on wherever this machine generates proxies and a BPG program was found. A non-boolean value is logged as an error ("config: bpg_enabled=<value> is not true/false -- deriving it") and the derivation is used.
- `bpg_path`: the program to start (with `-pg` added). If set and missing, BPG counts as not installed. When not set: `C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe` on Windows only; on macOS and Linux there is no default (so the feature is off unless `bpg_path` is set). `bpg_path` itself is not limited to Windows.
- `bpg_manage_watch_folders`: default true. Lets the companion add folders to BPG's watch list.
- `bpg_autostart`: default true. Lets the companion press BPG's Start button.
- `bpg_settings_path`: BPG's settings file; default `%APPDATA%\Blackmagic Design\Blackmagic Proxy Generator\Preferences\ProxyGeneratorSettings.ini`.
- Bad values for the two flags are logged ("config: <key>=<value> is not true/false -- using <default>") and the default is used.

### When it starts BPG (checked after every proxy-generator tick; see the generator section for the states that allow it)
In order; the first failing condition is the reason it does not:
1. enabled ("disabled");
2. a BPG program exists ("no proxy generator installed");
3. at least one clip needs Resolve ("nothing needs BPG");
4. the ffmpeg queue is empty and nothing is encoding ("ffmpeg still has clips queued");
5. the user is away from the keyboard per the generator's idle rule ("user is at the keyboard");
6. a BPG this companion started is not still running ("already running"; it then tries pressing Start);
7. at least 30 minutes since its last launch attempt ("launched too recently");
8. no BPG is already running on the machine (detected by reading every `Resolve.exe` command line through PowerShell for `-pg`; cached 60 seconds; if unreadable it counts as not running) ("already running"; it then tries pressing Start);
9. the watch folders could be set ("watch folders could not be set"; no cooldown is started).
- Then it starts BPG detached (it outlives the companion; started with a cleaned environment so the frozen companion's Python settings do not leak into Resolve), logs "bpg: started the Blackmagic Proxy Generator for N clip(s) ffmpeg cannot decode -- watching M folder(s), and never stopped by us", and presses Start. A failed start is logged and also starts the 30-minute cooldown ("launch failed").
- Running alongside an open Resolve is allowed.
- The companion never stops or kills BPG.

### Watch list management
- Before launching, and only while BPG is not running, the folders that hold the camera-raw clips missing proxies are added to BPG's `watchFolderList`.
- Additive: existing entries are kept verbatim; a folder already covered by an existing entry or one of its parent folders is not added. Comparison ignores case and slash direction.
- At most 8 folders added per launch, and the list is never taken above 32 entries. Full list: warning "bpg: <file> already lists N watch folders -- not adding M more" and the launch is refused ("watch list is full"). More than 8 needed: "bpg: N folder(s) need watching, adding 8 this time".
- An empty-list marker (`@Invalid()`) counts as no folders.
- Entries are written with Qt's own escaping (non-Latin-1 characters as `\xHHHH`; quoted when they contain `,`, `;`, `=` or `"`, or leading/trailing spaces).
- Garbled entries from an earlier companion version (a folder name stored as mis-decoded UTF-8) are removed when they match a folder being added; this is the only case where existing text is rewritten.
- If the settings file does not exist, a new one is created with a `[General]` section; the Preferences folder is created too when a BPG program exists here.
- Before the first change, the original file is saved once as `ProxyGeneratorSettings.ini.ccsync-backup` and never overwritten.
- No `%APPDATA%`: refused ("no %APPDATA%"). Unwritable file: "settings file could not be written".
- Log: "bpg: added N watch folder(s) to <file> so the generator can see the clips ffmpeg cannot decode: <list>".

### Pressing Start (Windows only)
- Runs a PowerShell UI Automation script that waits up to 180 seconds for a window titled "Blackmagic Proxy Generator", finds its Start/Stop checkbox and, only if it reads "Start", invokes it, then checks it now reads "Stop". Overall timeout 240 seconds. Runs on a background thread.
- At most once every 5 minutes.
- Outcomes: pressed (clears the editor note); already running or not Windows (clears the note); anything else (no window, no button, pressed with no change, unknown label, failure) sets an editor-facing note "CCSync opened the Blackmagic Proxy Generator to make proxies, but could not press Start. Press Start in its window." and logs a warning.
- Status available to the tray or settings window (rendering is outside this part): enabled, installed, autostart, whether the BPG it started is still running, how many clips it was launched for, and the editor note.

## Reading a WAV file's length from its header
(source: wav_header.py)

- Given a file, reads only its RIFF header chunks (never the audio data) and returns duration in seconds, byte rate, data bytes, sample rate, channel count and bit depth; nothing for a file that is not a parseable WAV (shorter than 12 bytes, wrong signature, no format or data chunk, zero byte rate).
- If the header's data size is the "never closed" value (0xFFFFFFFF) or runs past the end of the file, the bytes actually on disk are used.
- Used for the camera-card listing's WAV durations (the caller is outside this part), so they match the footage sorter's own calculation.

## Replaceable LGPL library (psycopg2)
(source: lgpl_libs.py)

- At startup (and before the Timeline Cards engine is loaded; callers are outside this part), two folders are put at the front of Python's import path, if they exist:
  1. the user folder `~/.ccsync/lib`, or the folder named by environment variable `CCSYNC_LGPL_LIB_DIR`;
  2. in the packaged app, the bundled `ccsync_lib` folder.
- A user can drop a rebuilt `psycopg2` package into the user folder and it loads instead of the bundled one (log: "lgpl_libs: loading psycopg2 from the user directory <dir> (replaces the bundled copy)"). This exists to satisfy the LGPL's "user can replace the library" requirement.
- Safe to call repeatedly; never fails startup.

## Looks redundant or overlapping

- Two separate "remember what failed and don't retry until the file changes" memories exist in this part, both in memory only and both keyed by file modified time and size: the generator's capped-clip memory (proxy_gen.py) and the relinker's Resolve-refusal memory (proxy_relink.py). A third, the frame-count (geometry) verdict memory (proxy_relink.py), uses the same shape. The VP9 guard has a fourth (unknown-codec retry) plus a disk-backed codec cache.
- Proxy-sibling moving exists twice in file_moves.py: `move_proxy_siblings` and `rename_proxy_siblings_case_only`, which overlap heavily (the first now also handles renames and case-only targets).
- Two Python-level relink paths for moved files: `file_moves.relink_moved` here and, per its own docstring, a twin `CompanionApp._relink_moved` in app.py.
- Two ways to run the BPG process probe and the Resolve-running probe: proxy_gen keeps its own 60-second cache of "Resolve running" for worker narrowing and a separate uncached check for the `proxy_gen_skip_while_resolve_running` gate; bpg.py keeps a third 60-second cache of Resolve command lines.
- Two copiers for card ingest (Python copier and TeraCopy) with largely duplicated decision logic (`_decide` runs before both, then TeraCopy re-runs it just before each group).
- Two "is the file still being copied" checks back to back before an encode: the min-age test and the two-sample size/modified-time test (proxy_gen.py), on top of the scan's own min-age filter (proxy_scan.py).
- ffmpeg_tools.py carries verbatim copies of logic from the b-roll indexer (preview recipe, timecode handling, drop-frame rule, frame-count rules) and from the b-roll web app (edit-weight rule), kept equal by tests rather than shared.
- The low-space, capped and truncated "brakes" are published twice in the dashboard report (`low_space` appears both as a top-level key and inside the brakes block).
- The BPG watch-folder management exists to work around BPG's own behaviour; since generated proxies became `.mov`, part of the duplicate-encode problem the module describes (BPG not recognising companion `.mp4` proxies) applies only to older `.mp4` proxies.
- `wait_limit_seconds`, `check()`, `harvest`, result codes 0/10/11/12/13 in teracopy.py are computed, but card_copy.py only reads the per-file receipts and the `stopped` field; the overall code is not used by this part.

## Claims the code does not back

- proxy_gen.py module docstring and proxy_scan.partial_path docstring say in-progress proxies are `Proxy/<stem>.mp4.partial`; the code writes `Proxy/<stem>.mov.partial` (the generated extension is `.mov`).
- bpg.py docstring says BPG does not recognise "this companion's `Proxy/<stem>.mp4`" and that proxy_gen writes `<stem>.mp4.partial`; the generator now writes `.mov`, which the same docstring says BPG does recognise.
- proxy_scan.py says the preview kind gets "the b-roll platform's 540p preview spec"; ffmpeg_tools.py's preview recipe is now 1080p.
- bpg.py `_norm` docstring says watch-folder entries are "always canonical `P:\Projects\...` strings"; the folders actually handed in come from walking the local root, so they are in the local root's spelling (which equals `P:\` only where the local root is `P:\`).
- proxy_relink.py summary message says "N refused by Resolve" using the count of all failures, including clips that got no answer and clips missing from the pool; only some of those were refusals.
- card_copy.py says a laptop away from home "tries again an hour later"; this code raises a non-retryable job error and does not schedule any retry (any retry is up to the sorter or job runner, outside this part).
- lgpl_libs.py says "In a source checkout ... nothing is added"; the user folder `~/.ccsync/lib` is added whenever it exists, frozen or not.
- proxy_gen.py `gap()`/`coverage()` do not publish the scan's `unreadable`, `error` or `partial` totals, although proxy_scan.py says callers must be able to tell an unreadable project from a covered one.
- vp9_guard.py popup text says "It plays fine now only because Resolve is using the H.264 proxies" for every VP9 clip, whether or not a proxy exists or is attached.
- teracopy.py docstring says card_copy uses TeraCopy "with verify on"; with `teracopy_allow_unverified` it is used with verify off.

## Could not determine

- Where and how often `sweep_stale_partials` (proxy_gen.py) is called; nothing in this part calls it.
- The exact rule behind `config.proxy_generation_enabled` (whether proxy generation is on by default, and on which machines); it lives in config.py.
- The tray menu labels and window texts that call "make the missing proxies now", "stop making proxies", the proxy history report and the BPG status; only the underlying actions are in this part.
- How app.py schedules the relink pass (comments say every 120 seconds) and how it chooses when to call `relink_moved` for pending moves.
- How the job runner treats `card-ingest`/`drive-copy` failures marked retryable versus not (for example, the "away from home" refusal).
- What the yt-dlp manager's daily task interval, free-space margin, download timeout and tools-folder path are exactly (they are constants in ytdlp_manager.py).
- Whether anything calls `TeraCopy.check()` (the install warnings) or `teracopy.status_for_capabilities` beyond the capability report.
- The exact list of video extensions (`rclone_lane.VIDEO_EXTS`) and YouTube work-file patterns used by the gap scan.
- Which UI, if any, renders `ProxyGenerator.gap()["reasons"]` and `relink` per-clip `details`/`why`.

