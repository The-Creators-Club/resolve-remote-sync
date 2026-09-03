# Companion YouTube download side (executor, yt-dlp manager, cookies, browser login, attestation, youtube_import)

## Summary

The machinery here is excellent and the reasoning behind it is the best-documented
in the repo; the 08-28 sweep's big items (max-age self-update, `.editready`
sweeping, ffprobe/ffmpeg timeouts, `clear_aside_originals`) are genuinely built.
What is weak is the OUTPUT of all of it. Almost every decision this side makes
ends at `log.info`: which executor took the job, why this machine handed it back,
that yt-dlp is 40 days old and could not update, that the clips reached the disk
but not Resolve. Three surfaces that exist are unreachable or unread: the tray
progress line moved into the Settings window in the 2026-08-27 menu reduction and
the tooltip still says "CCSync: up to date" while a 40-clip download runs; `GET
/ytdl/progress` (the whole CR-78 byte/speed/phase mirror) has NO consumer
anywhere in the repo; and the companion's `youtube_import` report section is
parsed by the dashboard and then dropped on the floor. Biggest risk: an editor
whose downloads land but never appear in Resolve, or whose yt-dlp has quietly
gone stale, has literally no surface to look at on either the tray or the
dashboard. Best cheap wins: point the SPA's existing poll at `/ytdl/progress`
(S), put the ytdl line back in the tray tooltip (S), and fix the three strings
that send editors to a tray menu that no longer has those items (S).

## Findings

### CYT-1: a local download is invisible in the tray while it runs
- **Lens:** usability
- **Who:** editor
- **Where:** `companion/src/ccsync_companion/tray.py:2071` (snapshot), `tray.py:1899`
  (`ytdl_download_line`), `tray.py:2976-3014` (`_tooltip_text`), `tray.py:3426-3444`
  (`_build_menu`), `settings_window.py:404-405` (the only consumer)
- **Today:** `ytdl_download_line()` builds exactly the right sentence
  (`"Downloading YouTube clip 3/12 (4.2 MB/s, 38%)"`), and the ONLY place it is
  rendered is the SYNC LANES section of the Settings window. The right-click menu
  (rebuilt for the ten-item layout on 2026-08-27) has no ytdl line, the icon does
  not pulse for it (`should_pulse` reads lane state), and `_tooltip_text` returns
  `"CCSync: up to date"` while yt-dlp is pulling 12 GB. An editor who pressed
  DOWNLOAD, closed the tab and wonders whether anything is happening must open
  Settings and scroll.
- **Proposed:** (a) add the line to `_tooltip_text` as a first-class state,
  above the "up to date" ending: `"CCSync: downloading YouTube clip 3/12 (4.2 MB/s)"`;
  (b) put it back in `state_items` in `_build_menu` (it is a transient state line,
  the same class as `_sync_line`, and it self-removes when `progress()` says not
  running); (c) balloon once on completion: `"12 YouTube clips are on this
  computer now (2 failed, the server is retrying those)"` - today nothing at all
  marks the end of a job.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** CR-78, CR-88 (the menu reduction that hid it), docs/YTDL_LOCAL_DOWNLOAD.md §9

### CYT-2: `GET /ytdl/progress` has no consumer - the browser shows no progress for a download it started
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl_executor.py:1879-1892` (`snapshot`), `:3069` (`progress`),
  `broll_server.py:1819-1829` (the route); `ytdl/web/static/app.js:235,2215,2284,2478,2541`
  are every `COMPANION_URL` call the SPA makes - `/ytdl/progress` is not among them
- **Today:** the executor keeps `bytes_done`/`bytes_total`/`speed_bps`/`phase` per
  clip, parsed off yt-dlp's own progress template, and serves it on the loopback.
  Its own docstring says "this exists so the SPA can show something in the first
  seconds". The SPA never fetches it. During a 40-minute 1080p clip the page shows
  the server's row state, i.e. the word `downloading`, with no bytes, no percent,
  no rate and no clip counter, for the whole job.
- **Proposed:** in the SPA's existing job poll, when `job.download_mode === 'local'`,
  also `fetch(COMPANION_URL + '/ytdl/progress?job_id=' + jobId)` (same 1 s abort
  budget and same silent-fallback rule as `companionCapabilities`) and render
  `clip 3/12 - 38% at 4.2 MB/s` beside the "downloading on your machine" badge,
  degrading to today's text on any failure. Also render `phase === 'converting'`
  as `converting clip 3/12 to H.264` so a ten-minute re-encode does not read as a
  stall.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** CR-78, docs/YTDL_LOCAL_DOWNLOAD.md §9 ("`GET /ytdl/progress` carries the same...")

### CYT-3: the clips land on disk and never reach Resolve, and nothing anywhere says so
- **Lens:** both
- **Who:** editor, admin
- **Where:** `youtube_import.py:402-422` (`status()`), `:377-395` (`_gate`),
  `:710-717` (the give-up), `app.py:1739` (reported), `dashboard/src/ccsync_dashboard/api.py:7103`
  (parsed) vs `:7413-7415` (only `broll_ingest` and `proxy_coverage` are flattened)
- **Today:** the importer computes a full status - `state`
  (`no-project-match`, `resolve-closed`, `drive-absent`, `paused`), `pending`,
  `failed_session`, `last_error`, `last_bin` - and it reaches NOBODY. `tray.py`
  and `settings_window.py` contain no reference to `youtube_import` at all
  (verified by grep); the dashboard declares `YoutubeImportIn`, validates it, and
  then nothing reads `payload.youtube_import`. A clip that fails to import three
  times is dropped until the tray restarts with only
  `log.warning("youtube import: giving up on %s after %d attempt(s)")` behind it.
  The whole failure mode "the download worked, the clips are in
  `Youtube/<term>/`, they are not in my media pool" is invisible on both ends.
- **Proposed:** (a) one Settings > SYNC LANES line, next to the ytdl line:
  `"8 YouTube clips are waiting to go into Resolve (Resolve is closed)"` /
  `"...(this project has no server folder yet)"` / `"3 clips could not be filed:
  <last_error>"`; (b) flatten the section on the dashboard the way `broll_ingest`
  is and show `no-project-match` on the fleet grid - it is a per-machine
  misconfiguration an admin can fix and the editor cannot; (c) register an
  `alerts.ALERT_KINDS` row for "clips downloaded but not imported for > 24 h" so
  it becomes a PROBLEMS THE SERVER FOUND notice with a next action.
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** docs/SELF_DIAGNOSIS.md; the api.py comment at :7092 already admits
  the section "rode every heavy tick since their features shipped and reached nobody"

### CYT-4: three editor-facing strings send people to a tray menu that no longer has those items
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl_executor.py:341-343` (`REASON_NOT_ATTESTED`), `tray.py:1031`
  (the session balloon), `tray.py:951` (the sign-in crash notice) vs
  `settings_window.py:515-537` (where the items actually are)
- **Today:** `REASON_NOT_ATTESTED` is `"the YouTube terms have not been accepted
  on this machine: tray > 'Accept YouTube Terms...'"` and it is shown IN THE
  BROWSER, in its own louder toast (`app.js:2238 explainCompanionRefusal`). The
  balloon for a dead session appends `"(tray menu → Sign in to YouTube again…)"`.
  The crash notice says `"use Advanced → YouTube: use an exported cookies.txt…"`.
  All three items moved into the Settings window on 2026-08-27; there is no
  YouTube entry and no Advanced submenu in the right-click menu any more. A
  first-time editor right-clicks, finds nothing, and gives up - and the effect is
  that the studio's downloads stay concentrated on the NAS IP, which is CR-80's
  own cause.
- **Proposed:** one shared constant for the route, used by all three:
  `"the YouTube terms have not been accepted on this computer. Right-click the
  CC Sync tray icon, open Settings, and press [ Accept YouTube Terms ]"`; the
  balloon becomes `"... (Settings > YOUTUBE > Sign in to YouTube again)"`; the
  crash notice drops "Advanced". A tray-strings test that greps every
  user-visible string for `tray menu`/`Advanced` and checks the named item still
  exists in `_build_menu` would keep this from happening again.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** CR-88 (the menu layout), COMMERCIAL_READINESS item 2

### CYT-5: a stale YouTube-session warning can never clear itself, contrary to its own comment
- **Lens:** resilience
- **Who:** editor
- **Where:** `ytdl_executor.py:2617-2621` and the class attribute at `:2637`
  (`_cookie_health_stale = False`); `ytdl_cookies.py:290-296` (`mark_ok`),
  `tray.py:1002-1016` (`_youtube_warning_line`)
- **Today:** `mark_ok` is called only when `cookies_used and self._cookie_health_stale`,
  and `_cookie_health_stale` is a PER-JOB memo initialised False in every new
  `DownloadJob`. So the stale record can only be cleared inside the same job that
  wrote it. Once a job ends with `ytdl-cookies-status.json` = `stale`, every later
  job starts with the memo False, a successful cookied download takes the
  `return True, ""` path without ever calling `mark_ok`, and the tray shows
  `"⚠ YouTube sign-in no longer works (Google rotated the session). Sign in again"`
  forever. The comment two lines above says the opposite: "clear a stale mark so
  the tray warning goes away by itself once things are fine again". Since WP3
  made the jar a fallback, cookied downloads are rare, which makes the false
  warning long-lived; the CR-80 account-flag variant is worse, because its
  remedy is to do nothing and the warning never retires.
- **Proposed:** drop the memo from the clear path - on a successful cookied run,
  read the status file (one small read, already cheap) and `mark_ok` if it says
  stale. Keep the memo only for the write side (one `mark_stale` per job). Add an
  expiry to the record: a `stale` mark older than 7 days with no cookied attempt
  since renders as `"YouTube sign-in has not been used since <date>"`, not as a
  fault.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** 08-28 YT-11 (a different hole in the same file)

### CYT-6: the two YouTube dialogs build a raw Tk root on a tray worker thread, outside `ui_dispatch`
- **Lens:** resilience
- **Who:** editor (a tray that vanishes), developer
- **Where:** `tray.py:958-998` (`_install_youtube_cookies`, `tk.Tk()` at :977),
  `tray.py:1054-1113` (`_show_youtube_terms_dialog`, `tk.Tk()` at :1088), reached
  through `_spawn` (`tray.py:1773`, a daemon thread)
- **Today:** every other Tk site in `tray.py` (:830, :1195, :1288, :1438) is built
  inside a function handed to `ui_dispatch.dispatch(...)`; these two are the only
  ones that call `tkinter.Tk()` directly on the spawned worker thread and then
  `root.destroy()` with no `ui_dispatch.release_root()`. The docstrings justify
  it as "a native modal, not one of this process's Tk roots" - but `tk.Tk()` IS a
  Tk root and the CR-93 wrapper pins its interpreter at birth, so on Windows each
  invocation leaks a pinned interpreter that is never freed on its building
  thread, and on macOS (where `ui_dispatch.uses_main_thread()` is true) this
  builds Tk-Aqua off the main thread, which is exactly the shape CR-93 describes.
  Both are reached from a button an editor presses.
- **Proposed:** wrap both bodies in `ui_dispatch.dispatch(lambda: ...)` like
  `_show_update_dialog` does, and call `ui_dispatch.release_root(root)` from
  inside instead of `root.destroy()`. If the native-modal argument is genuinely
  wanted, the fix is still `dispatch` - it decides WHERE, which is the whole
  point of the module.
- **Effort:** S   **Value:** high   **Confidence:** med (the leak is certain; the
  macOS abort depends on `_active` being installed, which it is in the tray)
- **Related:** CR-93, docs/GOTCHAS.md §18

### CYT-7: "this machine's yt-dlp is stale / could not be installed" reaches no human
- **Lens:** both
- **Who:** admin, owner
- **Where:** `ytdlp_manager.py:607-621` (`status()`), `:696-750` (`_enforce_max_age`,
  publishing `ACTION_STALE`), `:1067-1090` (the daily loop, `log.log(INFO, ...)`);
  the only reader anywhere is `ytdl_executor.py:707-714` -> `capabilities()`
- **Today:** the max-age rule (YT-1's fix) works and publishes
  `"yt-dlp 2026.07.04 is 43 days old and it could not update itself - YouTube
  downloads on this machine may start failing"` with `ok=True`. Because `ok` is
  True, `capabilities()` never surfaces it, so the browser toast never fires;
  there is no tray line, and the manager status is not in the report payload at
  all. The message goes to `~/.ccsync/companion.log` once a day. That is exactly
  the CR-80 shape re-dated: the mechanism now detects staleness and the detection
  is still invisible until an editor's download fails.
- **Proposed:** (a) add a `ytdlp` section to the report (`version`, `action`,
  `message`, `checked_at`) and store it, next to `capabilities`; (b) two
  `alerts.ALERT_KINDS` rows - `ytdlp_stale` (any machine on `action=stale` or a
  version older than N days) and `ytdlp_missing` (`action=failed`) - each with
  the next action ("the machine could not reach github.com; check its network or
  set `ytdlp_path`"); (c) one Settings > YOUTUBE warning line when
  `action in (stale, failed)`.
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** 08-28 YT-1 (built), CR-80, CR-83, docs/SELF_DIAGNOSIS.md

### CYT-8: the download claims a disk that lane B has already parked as too full
- **Lens:** resilience
- **Who:** editor
- **Where:** `ytdl_executor.py:322-325` (`MIN_FREE_BYTES_MARGIN` 200 MB +
  `NOMINAL_JOB_BYTES` 5 GB), `:1983-1993` (the one check, before the claim);
  `sync/lane_guard.py:96` (`DEFAULT_LANE_B_MIN_FREE_BYTES = 20 GiB`)
- **Today:** the executor claims a job whenever ~5.2 GB is free and then never
  looks again. Lane B parks proxy download at 20 GB free on the same volume. So
  on a disk with 8 GB free: lane B is parked (and the editor has a
  [ RESUME PROXY DOWNLOAD ] button and a tray line about it), while the YouTube
  executor cheerfully accepts a 40-clip job, fills the remaining space, and the
  first symptom is a run of ENOSPC clip failures (which the WP6 breaker will stop
  after 3, with `"No space left on device"` in three job rows and nothing on the
  machine). Nothing links the two, and the ytdl job is what caused the disk state
  the editor is now told to resume out of.
- **Proposed:** (a) raise the claim floor to `lane_b_min_free_bytes` when it is
  configured (one shared reader), so a machine lane B has parked never claims a
  download; (b) re-check free space between clips in `_download_all`'s loop and
  hand the rest back with `log.warning` + the same "handback" surface as CYT-11,
  rather than filling the volume; (c) name the number in the refusal the editor
  sees: `"this computer has 4.1 GB free and YouTube downloads need 20 GB, so the
  server is downloading this job"`.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** SYS-5 / SYNC-7 (the free-space park), 08-28 YT-5

### CYT-9: the daily `yt-dlp -U` can fire mid-download and be recorded as a permanent failure
- **Lens:** resilience
- **Who:** editor, admin
- **Where:** `ytdlp_manager.py:1067-1090` (the 24 h loop), `:696-750`
  (`_enforce_max_age` -> `self_update()`), `:883-905` (`self_update`); nothing in
  the module consults `ytdl_executor.current_job()`
- **Today:** the loop wakes on its own schedule and can run `yt-dlp -U` while a
  job is downloading clip 12 of 40 with that exact binary. On Windows the
  in-place replace of a running image fails, `-U` exits non-zero, and
  `_enforce_max_age` publishes `ACTION_STALE` - "it could not update itself" -
  which is wrong, sticks until the next daily pass (24 h), and (with CYT-7 fixed)
  would be an alert. The real cause, "a download was running", is nowhere.
- **Proposed:** guard both `install()` and `self_update()` with a one-line seam:
  if `ytdl_executor.current_job()` is not None, skip and publish
  `action=deferred, message="yt-dlp update deferred: a download is running"`, and
  retry on a short timer (say 15 min) rather than waiting a day. Same guard
  protects the `_maybe_poke_ytdlp` path from re-entering during a job.
- **Effort:** S   **Value:** med   **Confidence:** med (the Windows sharing
  violation is inferred from `os.replace` semantics, not measured here)

### CYT-10: bumping the attestation text silently switches local downloads off for the whole fleet
- **Lens:** both
- **Who:** owner, editor
- **Where:** `ytdl_attestation.py:49` (`TEXT_VERSION = "2026-08-17.1"`),
  `accepted()` (version-equality); `ytdl_executor.py:341` +
  `capabilities()`:`if not ytdl_attestation.accepted(...)`; the only way to
  accept is the Settings button (`settings_window.py:517-521`)
- **Today:** an unreadable, missing, mis-versioned or wrong-editor file all mean
  NOT ACCEPTED, which is the right safe direction - but nothing PROMPTS. The day
  `TEXT_VERSION` moves, every machine in every fleet silently stops downloading
  locally, every job goes to the NAS's one IP (CR-80's cause), and the only
  signal is a browser toast the editor sees if they happen to press DOWNLOAD, and
  it points at the wrong menu (CYT-4).
- **Proposed:** the same pattern the licence gate already uses: when the site has
  `youtube_download` on and `accepted()` is false for a NEWER version than the
  one on file, put a conditional item in the tray menu -
  `"► Accept the updated YouTube terms to download on this computer…"` - and
  balloon once per version. Record the previous version in the state file so
  "never accepted" and "accepted an older text" can be told apart in copy.
- **Effort:** S   **Value:** med   **Confidence:** high
- **Related:** the EULA gate's own pattern (`eula_problem`, tray.py:3333)

### CYT-11: every whole-job hand-back is a log line, so "why did the server do it" has no answer on the machine
- **Lens:** usability
- **Who:** editor, admin
- **Where:** `ytdl_executor.py:2033-2078` (template/sidecar skew, out-of-scope
  quality, unresolvable destination, tree misplaced), `:2129-2178`
  (`_label_is_ours`), `:1983-1993` (free space), `:2249-2262` (the WP6 breaker)
- **Today:** all seven paths do `log.warning(...)` and `return`, then let the
  lease expire. The SPA has already had its 202 and shows "downloading on your
  machine" until the reclaim flips the badge minutes later, with no reason
  attached. `_label_is_ours` returning False is the likely everyday case (the
  editor downloads into a project this computer does not sync) and its evidence
  is one log line an editor will never open.
- **Proposed:** add `handback` (`{"why": "<one sentence>", "at": ...}`) to the
  progress snapshot, which `_LAST` already survives the job with, and render it
  wherever CYT-2 lands the progress poll: `"Your computer handed this job back to
  the server: it does not sync 2026/FF5/Energy Transition."` One extra field, no
  new endpoint, no new server route, and it makes the seven silent refusals
  legible without touching the "no release endpoint" design.
- **Effort:** S   **Value:** high   **Confidence:** high

### CYT-12: `install()` and `self_update()` throw away every reason they failed
- **Lens:** resilience
- **Who:** editor, admin
- **Where:** `ytdlp_manager.py:811-880` (`install` returns bool; six distinct
  failure branches), `:883-905` (`self_update` returns bool), `:981-987`
  (the ACTION_FAILED message the editor sees)
- **Today:** the toast an editor gets is `"no yt-dlp on this machine and it could
  not be installed -- YouTube downloads stay on the server"`. The six causes -
  no tools dir, not enough disk, the SHA2-256SUMS fetch failed, the download
  failed, a checksum MISMATCH, the rename failed - are distinguishable at the
  point of failure, are logged at INFO/WARNING, and are then collapsed to
  `False`. A checksum mismatch in particular deserves to be loud (it is the
  trust-model-7 refusal shape) and is currently indistinguishable from "the wifi
  dropped".
- **Proposed:** return `(bool, reason)` from both and put the reason in the
  published message: `"yt-dlp could not be installed: this computer could not
  reach github.com. YouTube downloads stay on the server."` / `"...the download
  did not match its published checksum, so it was discarded."` The second should
  additionally be an alert kind (a mismatch is either a corrupt mirror or an
  attack, and it is the one that must never look like a network blip).
- **Effort:** S   **Value:** med   **Confidence:** high

### CYT-13: editor-visible copy carries `--` and an admin config key
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl_executor.py:353` (`REASON_NO_IDENTITY`), `ytdlp_manager.py:960,969,984,998,728,743`
  (published messages that become the SPA toast), `ytdl_cookies.py:63-66` (`OFF_MESSAGE`),
  `companion/tests/test_no_em_dash.py:35` (`FORMS` covers only U+2014 and its entities)
- **Today:** `"this machine has no valid sign-in token -- sign in again from the
  tray"` and `"yt-dlp 2026.07.04 is older than the 2026.08.19 the dashboard asks
  for and it could not update itself -- YouTube downloads stay on the server"`
  are rendered verbatim in a browser toast. The house rule bans the em dash and
  the scan test enforces the character only, so the ASCII stand-in - which paints
  as a typo, not as punctuation - is unscanned. `OFF_MESSAGE` tells an editor
  `"Ask your administrator (site.toml [features] youtube_unblock)"`, i.e. names a
  file on the NAS in copy an editor reads.
- **Proposed:** extend `test_no_em_dash.py` to flag ` -- ` inside non-log string
  constants in the same AST walk (it already has the machinery and the ALLOWED
  set for exceptions), and rewrite the offenders with a spaced hyphen or two
  sentences. `OFF_MESSAGE` becomes `"signing in to YouTube for downloads is not
  switched on for your studio. Ask your administrator to enable it."` - the
  config key belongs in the admin-facing docs, not in the editor's balloon.
- **Effort:** S   **Value:** med   **Confidence:** high
- **Related:** the owner's 2026-08-18 rule; `docs/YTDL_LOCAL_DOWNLOAD.md`

### CYT-14: no way to stop a local download from the machine doing it
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl_executor.py:3085-3101` (`stop_all`, called only from
  `broll_server.stop`), `broll_server.py:1813-1909` (no cancel route),
  `tray.py`/`settings_window.py` (no control)
- **Today:** the escape hatch is `[ DOWNLOAD ON THE SERVER INSTEAD ]` in the
  browser, which reclaims server-side; the companion learns at its next heartbeat
  (up to 30 s) and kills yt-dlp. That is a real cancel, but it needs the page
  open and the tailnet up. The editor at the machine - about to close the lid,
  tethered, or watching their upload lane starve - has only "Quit CCSync", which
  stops syncing too.
- **Proposed:** one Settings > SYNC LANES button beside the ytdl line,
  `[ STOP THIS YOUTUBE DOWNLOAD ]`, calling `job.stop()`; the lease then expires
  and the server picks up what is missing, which is the documented behaviour for
  every other hand-back. Copy after the click: `"Stopped. The server will
  download the clips this computer did not finish."`
- **Effort:** S   **Value:** med   **Confidence:** high
- **Related:** 08-28 YT-13 (partly answered by the SPA's mode-lock; the machine-side half is still missing)

### CYT-15: the browser sign-in can block for ten minutes with one balloon and no way to abandon it
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl_browser_login.py:84` (`LOGIN_TIMEOUT_SECONDS = 600`),
  `:493` (`progress` callback), `tray.py:917-956` (`_youtube_sign_in`, which never
  passes `progress`)
- **Today:** one balloon on launch (`"Edge is opening. Sign in to YouTube in that
  window; it closes by itself when you're done"`), then silence until the outcome
  balloon up to ten minutes later. The `progress` seam exists and is unused. If
  the editor gets distracted and comes back, the browser window is gone (the
  `finally` closes it) and the only trace is a balloon that has expired. There is
  also no way to cancel: closing the browser is detected (`"the browser was closed
  before the sign-in finished - nothing saved"`), which is the practical escape,
  but nothing says so.
- **Proposed:** pass `progress=lambda msg: _notify(app, msg)` and emit two more
  steps ("waiting for you to finish signing in", "signed in, saving your
  session"); extend the first balloon with `"Close the window to cancel."`; and
  on the timeout say what to do next: `"The sign-in did not finish in time.
  Nothing was saved - try again from Settings > YOUTUBE."`
- **Effort:** S   **Value:** med   **Confidence:** high

### CYT-16: an hours-long re-encode shows one static line and no way to know it is progressing
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl_executor.py:2334-2354` (`_ensure_edit_ready`, `phase="converting"`),
  `tray.py:1925-1928` (`"Converting YouTube clip 3/12 to H.264"`), `CONVERT_TIMEOUT_SECONDS`
- **Today:** during a libx264 conversion the tray line is a constant string with
  no percent, no elapsed time and no rate, for as long as ffmpeg takes (bounded
  only by the convert timeout), at 100% CPU while the editor is editing. It is
  correct that this is not a download - but "static line, hot fan, hours" is what
  an editor reads as a hang, and it is the exact complaint CR-78 answered for the
  download half.
- **Proposed:** parse ffmpeg's `-progress pipe:1` `out_time_us` (the argv is
  already built in `edit_ready_argv`; adding `-progress` and `-nostats` does not
  change the output file) against the probed duration and publish
  `convert_percent`, so the line becomes `"Converting YouTube clip 3/12 to H.264
  (41%, about 6 min left)"`. Cheap, and it is the same `_on_ytdlp_line` plumbing
  already in place for stdout lines.
- **Effort:** M   **Value:** med   **Confidence:** med

### CYT-17: an expired cookie jar is still spent on the bot-check fallback
- **Lens:** resilience
- **Who:** editor
- **Where:** `ytdl_executor.py:2537-2551` (the anonymous -> jar fallback),
  `ytdl_cookies.py:329-365` (`health()`, which already knows the jar is expired)
- **Today:** `_run_ytdlp_paths` asks only `_cookies_file(cfg)` ("is a file
  there"). If `health()` says `expired` (the login cookies' own expiry has
  passed) the fallback still runs a full second yt-dlp attempt with a jar that
  cannot work, and the outcome is `BOTH_BLOCKED_ERROR` telling the editor to
  "Export a fresh cookies.txt from a different signed-in YouTube session" - which
  is not what an expired session needs to hear (it needs "sign in again").
- **Proposed:** read `health()` once per job (it is two small reads) and (a) skip
  the cookies fallback when the status is `expired`, (b) make the clip error say
  which case it is: `"YouTube asked this computer to prove it is not a bot, and
  your YouTube sign-in has expired. Sign in again in Settings > YOUTUBE, or let
  the server download this job."`
- **Effort:** S   **Value:** med   **Confidence:** high
- **Related:** CR-80, WP3

### CYT-18: `/ytdl/reveal`'s dead end names a folder but never offers to open the project
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl_server.py:306-313` (the "nothing to point a file manager at"
  branch), `:166-168` (`NOT_HERE_WHY`)
- **Today:** when neither the file nor its folder exists, the answer is
  `"P:\Projects\2026\FF5\...\clip.mp4 is not on this machine. YouTube originals
  only sync up, so a clip another editor downloaded, or one the server
  downloaded, stays on the NAS until you ask for it."` - a full local path and an
  explanation, with no action. The action exists one route away (`/ytdl/fetch`),
  and the SPA offers it only on the `absent` branch that DID find a folder
  (`app.js:2505 offerFetch`). An editor who has never opened that project sees
  the sentence and nothing to press.
- **Proposed:** set `"absent": True` on this branch too (it already is) and have
  the SPA offer the fetch on it as well - `fetch` creates the folder through
  `broll_fetch` anyway. Copy: `"This clip is on the server, not on this computer.
  [ GET IT NOW ]"`.
- **Effort:** S   **Value:** med   **Confidence:** med (the SPA half is the ytdl-web agent's territory)
- **Related:** CR-32

## Still open from 08-28

- YT-2 reclaim-on-expiry can put two yt-dlp processes on one clip: not built (no cross-process guard on the outdir).
- YT-5 nothing bounds what one clip may write: not built on this side (still no per-clip byte ceiling; see CYT-8).
- YT-12 the identical-failure breaker is in-memory per job: not built - `self._identical_failures` resets on every job and every restart, against WP6's own rule that "a latch must be on disk and cleared by a person".
- YT-13 no way to cancel a running local download from the machine: partly built (the SPA's mode-lock reclaims within ~30 s; the machine-side control is still missing - CYT-14).
- YT-19 nothing sweeps disowned corpses or orphaned intermediates: partly built (`.editready` joined `_INTERMEDIATE_STEM_RE`, `clear_aside_originals` retries `.original`); `.failed` corpses still accumulate with no sweep and no surface reporting the space.
- YT-23 the canary is off by default: not built (still no scheduled extraction test; CYT-7 is the cheaper substitute).

## Cross-cutting notes

- **ytdl web SPA (whoever owns `ytdl/web/static/app.js`):** `noCompanion` at
  `:2596` builds `'Projects\\' + winParent(...)` and appends `"(P: on Windows)"`.
  The drive letter is site data since 2026-08-17 (`canonical_prefix`) and the
  backslash path is wrong for every Mac editor. It should come from the
  companion's own answer or from `/api/v1/site`.
- **Dashboard/report agent:** `ReportIn.youtube_import` is validated and then
  never read (`api.py:7103` vs `:7413`). Either flatten it or delete the model -
  a schema field nothing consumes is a promise the fleet grid does not keep. The
  same is worth checking for any other section added after `broll_ingest`.
- **Tray/menu agent:** the 2026-08-27 menu reduction left at least three strings
  in this area pointing at items it moved (CYT-4). It is worth grepping the whole
  companion for `tray menu`, `Advanced →` and `tray >` in user-visible copy.
- **Jobs agent:** `ytdlp_manager`'s daily loop is the only caller of
  `sidecar_tools.ensure_ffmpeg_pair` anywhere in the companion
  (`ytdlp_manager.py:1101-1108`). Anything else that needs ffmpeg (proxy
  generation, b-roll ingest, the `proxy-480p`/`audio-extract` fleet jobs)
  silently depends on the YouTube module's thread still being started.
