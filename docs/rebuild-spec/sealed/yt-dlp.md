# Sealed notes: yt-dlp

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 10 notes.

### YTD-S01: The downloader stamps finished files with YouTube's upload date.
- Why: By default it sets a file's modified time from the server's Last-Modified header, usually the upload date, so a file written seconds ago looks years old.
- Must: Downloaded files keep their real write time, so any rule that waits for a file to settle treats a just-written file as new.
- Tool: yt-dlp (default mtime; --no-mtime / updatetime False)
- Where it bit: YouTube downloads

### YTD-S02: With no paths set, the downloader writes scratch files in the working folder.
- Why: Given no paths, it writes format-test files in the current folder, which on the server was the read-only root, so downloads died "permission denied".
- Must: The downloader always runs with a writable scratch location the product owns, and a failed clip records the full error.
- Tool: yt-dlp (paths home/temp defaults)
- Where it bit: YouTube downloads

### YTD-S03: Single-stream pieces look exactly like finished videos.
- Why: Fetching video and audio apart, it names a piece "Title [id].f137.mp4", stops changing it before merging, and keeps it if anything fails.
- Must: Files with ".f" plus digits before the extension are never imported into Resolve, synced or left behind; only the merged file counts.
- Tool: yt-dlp
- Where it bit: YouTube downloads

### YTD-S04: The downloader rewrites the cookie file it is given on every run.
- Why: An emptied cookie file fills with anonymous visitor cookies that hold no login, and an operator's original export gets overwritten.
- Must: A cookie file counts as a sign-in only if it holds a real login cookie, and the operator's original export is kept separately.
- Tool: yt-dlp (cookies.txt jar handling)
- Where it bit: YouTube downloads

### YTD-S05: Signed-in downloads found no formats at all.
- Why: With a cookie file the downloader also needs a proof-of-origin token and a JavaScript runtime; anonymous downloads reached 1080p without them, signed-in ones found nothing.
- Must: Signed-in downloads run only where every piece YouTube demands is present, and a missing piece is reported rather than looking like an empty video.
- Tool: yt-dlp (cookies, PO token provider, deno JS runtime)
- Where it bit: YouTube downloads

### YTD-S06: Without its script runtime the downloader hangs or every format vanishes.
- Why: Lacking its runtime it falls back to a slow built-in interpreter (97 s, no output, against 6.4 s) or fails "format not available", which reads as YouTube flakiness.
- Must: The runtime is checked however the app was started, a missing one shows as a banner, and failures it causes name it instead of advising an update.
- Tool: yt-dlp (needs deno or node on PATH; lost it when started from a Windows scheduled task's stripped environment)
- Where it bit: YouTube downloads

### YTD-S07: A pinned YouTube player client stops working within weeks.
- Why: The default client needed a token editors lacked; another worked at full quality, then failed as enforcement tightened; naming several let it pick a token-bound 403 format.
- Must: The downloader uses its own default client, and which client it imitates can be changed without a product release.
- Tool: yt-dlp player_client (android_vr, ios, tv, web, web_safari) and GVS PO tokens
- Where it bit: YouTube downloads

### YTD-S08: Only the downloader's newest nightly keeps up with YouTube.
- Why: Mid-stream 403s at 40-70% were fixed only by a pre-release; plain self-update never leaves stable, and installing a nightly from the package index took 146 s.
- Must: Update explicitly to the nightly channel in the background, keep the last working copy to fall back on, and show when a newer build awaits a restart.
- Tool: yt-dlp (nightly channel, self-update, package index)
- Where it bit: YouTube downloads

### YTD-S09: Judging the downloader stale by age alone raised false alarms.
- Why: Its makers can go five weeks or more without a stable release, so a 21-day age rule called three computers out of date on the newest release.
- Must: "Out of date" is shown only when a newer version is known to exist, never by age alone.
- Tool: yt-dlp
- Where it bit: YouTube downloads

### YTD-S10: Segmented downloads need parallel fetching and a working token helper.
- Why: Without the token helper add-on only throttled segmented formats remain, and fetched one segment at a time they crawl; its failed install was only in a log.
- Must: Fetch about six segments in parallel, retry a failed helper install, and record and show its install result, unknown reading "not checked".
- Tool: yt-dlp HLS (concurrent_fragment_downloads) and the bgutil PO-token provider plugin
- Where it bit: YouTube downloads
