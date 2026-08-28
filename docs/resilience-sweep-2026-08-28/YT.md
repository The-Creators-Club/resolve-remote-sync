# YouTube download (ytdl) stack

## Summary

This is the most heavily *reasoned* code in the repo - almost every constant carries the incident that set it - and the failure modes it already survives (CR-29..CR-39, CR-73..CR-80, CR-83/84) are genuinely closed. What is left has a shape: the guards are per-incident, per-job and in-memory, and almost none of them are continuous. The biggest risk is that the fleet's yt-dlp currency is still gated on a human shipping a dashboard release - `ensure()` updates a companion only when the server's hard-coded floor moves (`ytdlweb/config.py:271`) - so the exact structure that produced CR-80/CR-83 (every machine sitting on a yt-dlp that cannot download, logging "current" nightly) is unchanged, only re-dated. The second is that the canonical project tree is the download *workspace*: yt-dlp intermediates, the pre-conversion original, `.editready` and `.original` all match lane A's `+ *.mp4`, lane A is `copy --ignore-existing`, and neither executor passes `--no-mtime`, so the 120 s stability gate is satisfied on arrival and the fleet's permanent copy of a clip can be the VP9 one CR-79 exists to replace. Third: nothing anywhere measures liveness - `worker.is_alive()` is thread-object liveness, two ffmpeg/ffprobe calls have no `timeout=` at all, and the companion's own progress mirror is never read as a health signal. Best cheap wins: a max-age self-update rule (S, kills the whole CR-80 class), `timeout=` on two `subprocess.run` calls (S), five exclude lines in `build_filter_rules_up` (S), and an allow-list `cli_env` (S).

## Findings

### YT-1: nothing on an editor's machine ever updates yt-dlp on its own initiative
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/ytdlp_manager.py:873`, `:889`, `:788-889`; `ytdl/web/ytdlweb/config.py:271-272`; `ytdl_executor.py:2249-2277`
- **Scenario:** YouTube ships a change on a Tuesday; yt-dlp fixes it that week; nobody at the studio is watching yt-dlp's release feed.
- **Today:** `ensure()` updates only on `if floor and version_is_older(current, floor)` (:873); otherwise it publishes `"yt-dlp X is current"` (:889) every 24 h forever. The floor is `DEFAULT_MIN_YTDLP_VERSION = '2026.08.19'`, a **constant in a dashboard release**, overridable only by an env var typed by hand. `_maybe_poke_ytdlp` (executor:2249) was added so a failure triggers a re-check - but it calls the same `ensure()`, re-reads the same unchanged floor, and does nothing. The CR-80/CR-83 structure is intact: the whole fleet goes dark, every companion logs "current", and the cure is a release plus an OTA. Server-side there are three yt-dlp locks (CR-84) and the image's is the one that counts.
- **Proposed:** a MAX-AGE rule in `ensure()`. yt-dlp versions *are* dates, so `upgrade.parse_version(current)` already yields one: if the installed version is older than `YTDLP_MAX_AGE_DAYS` (~21) run `self_update()` regardless of the floor, and say so in the published status. It cannot roll backwards (`-U` goes to latest stable only) and the `ytdlp_path` override branch returns before it. Mirror server-side: `/ytdl/api/health` should say "the running yt-dlp is N days old" so the owner sees drift before an editor does.
- **Effort:** S   **Severity:** critical   **Confidence:** high
- **Related:** CR-80, CR-83, CR-84; `docs/YTDL_RESILIENCE_PLAN.md` WP1 raised the constant but did not remove the dependence on raising it.

### YT-2: reclaim-on-expiry can put two yt-dlp processes on the same clip in the same folder
- **Lens:** pitfall
- **Where:** `ytdl/web/ytdlweb/worker.py:1406-1411`, `:1321-1342`; `db.py:713-722`, `:912-930`; `ytdl_executor.py:1781-1794`; `config.py:240-241`
- **Scenario:** a dashboard container restart for an image update, a 3-minute wifi drop, or a laptop suspend - while an editor's machine is mid-file on a large clip.
- **Today:** the companion swallows every heartbeat failure that is not a 410 at `ytdl_executor.py:1793-1794` (`log.debug`) and keeps downloading. Six failures expire the 180 s lease. The worker sees `lease_active() == False`, runs `_reclaim_local_job`, and at `worker.py:1322` treats a row still in `downloading` as reclaimable: `_landed_file` finds nothing (it is a `.part`), so the row returns to `pending` (:1341) and the server starts the same video. The companion only learns at its next heartbeat or status post. On the base rig, where `local_root` **is** the NAS share, that is two yt-dlp processes writing the same `[id].f137.mp4.part` into one directory, each give-up path deleting the other's resume state - YTDL-WEB-4's incident at job level, which `begin_download`'s row CAS does not cover because the reclaim rewrote the row first.
- **Proposed:** make reclaim conservative about rows that were in flight - leave `dl_state='downloading'` rows alone for one further lease period, or requeue only on a second consecutive reclaim. Cheaper complement on the other end: treat N consecutive heartbeat *transport* failures spanning ≥ `lease_seconds` as a lease loss and stop, rather than only a 410.
- **Effort:** M   **Severity:** high   **Confidence:** high

### YT-3: the pre-conversion original is uploaded under the final name, and `--ignore-existing` makes it the fleet's permanent copy
- **Lens:** pitfall
- **Where:** `ytdl_executor.py:2060-2092`, `:2106-2192`; `companion/src/ccsync_companion/sync/rclone_lane.py:397-402`, `:1362`, `:196-210`
- **Scenario:** an editor downloads a 1080p clip; YouTube serves VP9; `_ensure_edit_ready` starts a ten-minute libx264 re-encode (`CONVERT_TIMEOUT_SECONDS` allows three hours). Lane A's periodic pass runs during those ten minutes.
- **Today:** `build_filter_rules_up` is `[appledouble, express excludes, -Proxy, + *<ext>..., - **]` (:397-402) and the Youtube dir is deliberately in scope (originals go up). The only stability gate is `--min-age 120s` (:1362) - and **neither executor passes `--no-mtime`**, so yt-dlp stamps the media response's `Last-Modified` (often the upload date, years back) on the finished file: it is eligible instantly. Lane A is `copy --ignore-existing`, whose own documented rule (:206-210) is that the first version of a name to reach the NAS is the only one that ever will. The VP9 file lands on the NAS; the editor keeps the H.264 one; every other editor and every future project gets the undecodable copy, permanently, with no error anywhere. CR-79's failure, arriving through the sync lane instead of the download.
- **Proposed:** download and convert OUTSIDE the tree and move the finished file in - the move `INFO_JSON_DIR_NAME` (executor:179-192) already made for info jsons, for the same reason. Cheapest partial: pass `--no-mtime` (so `--min-age` is a real gate again) AND add `- *.editready.*`, `- *.original.*`, `- *.temp.*`, `- *.f[0-9][0-9][0-9]*.*`, `- *.failed` ahead of the `+ *<ext>` block (first-match-wins, the file's own ordering rule). Neither alone suffices: a conversion longer than the lane interval still races.
- **Effort:** M (staging) / S (filter + `--no-mtime`)   **Severity:** high   **Confidence:** high
- **Related:** CR-79; COMP-BROLL-3 closed the `.f137` half on the executor side only; AUDIT_2 L-14 is the same mtime trap.

### YT-4: nothing measures liveness - a wedged download or conversion is indistinguishable from a working one, on either executor
- **Lens:** pitfall
- **Where:** `worker.py:194-196` (`is_alive`), `:252-267`, `:304-310`; `vendor/downloader.py:293`, `:409-411` (two `subprocess.run` with **no `timeout=`**); `ytdl_executor.py:308`, `:1325`, `:1781-1794`, `:1728-1740`; `routes_api.py:145`
- **Scenario:** the known 100 %-CPU hang (yt-dlp falling back to its pure-Python JS interpreter in a stripped environment), a half-open TCP connection after a VPN drop, or - server-side - a NAS mount that wedges and leaves ffmpeg in uninterruptible sleep on a 10 GB file.
- **Today:** server-side, `is_alive()` is thread-object liveness and never progress; `_run`/`run_job` have no wall clock; `probe_streams` and `ensure_edit_ready` can block forever. The worker is the **only** executor for the whole fleet and `_tick` is strictly serial, so every other editor's *search* queues behind it. `/api/health` says `worker_alive: true` throughout; the only cure is restarting the container. Companion-side the sole bound is a 2 h clip timeout (3 h for ffmpeg) while the heartbeat renews the lease throughout; `bytes_done`/`speed_bps` stop advancing but **nothing reads them for liveness**, so the tray shows `Downloading YouTube clip 3/12 (0%)` for two hours on a pinned core, and `converting` deliberately shows no rate at all.
- **Proposed:** (a) pass `timeout=` to both `subprocess.run` calls (ffprobe 120 s, ffmpeg a per-GB budget) so expiry becomes an ordinary clip failure and `_record_failure`/`_disown_output` run. (b) A module-level `_last_progress` touched by `_tick` and the progress hook, exposed as `worker_stalled_seconds` in `/api/health`, with the SPA saying "the server has not moved in N minutes" instead of a frozen bar. (c) On the companion, a stall watchdog: if `bytes_done` has not increased for ~10 min while `phase == "downloading"` (or the `.editready` tmp has not grown while `converting`), kill the child and fail the clip with "the download stopped making progress and was stopped", counted against the breaker.
- **Effort:** S (a) / M (b, c)   **Severity:** high   **Confidence:** high
- **Related:** CR-78 built the progress mirror; nothing consumes it as a health signal.

### YT-5: nothing bounds what one clip may write - and the duration cap does not apply to pasted-URL jobs at all
- **Lens:** pitfall + user-error
- **Where:** `routes_api.py:566-613` (`_ID_PATHS` includes `'live'`); `worker.py:396-406`, `:630-661`, `:1400-1404`; `vendor/downloader.py:193-257`; `ytdl_executor.py:2463-2589`, `:317-326`, `:1816-1825`; `config.py:152`
- **Scenario:** an editor pastes `youtube.com/live/<id>` for a press conference that is still streaming - a reasonable thing to paste, and `video_id_of` accepts it by design - or a 6-hour ambience video.
- **Today:** `_phase_start` sends a `KIND_URLS` job straight to `downloading` (:405-406), bypassing `_phase_filter` - the **only** place `MAX_DURATION_SECONDS` (1800) and the "live or no duration" drop are enforced (:645-651). `build_opts` sets no `max_filesize`, no `is_live` refusal and no `socket_timeout`, with `retries: 10` and `fragment_retries: 10`. The companion is the same: no `--max-filesize`, no `--match-filter`, and a free-space check made **once, before the claim**, against a fixed 5 GB guess (:326, :1816-1825), never again for the remaining 39 clips. Server-side there is no free-space check *at all* (`grep statvfs|disk_usage` over `ytdlweb/` finds only two informational uses in `routes_fleet`). So a livestream pins the fleet's singleton worker for its whole duration - blocking every other editor's search - and fills the NAS as it goes; on the base rig the companion path does the same to the canonical tree.
- **Proposed:** in `_phase_download`, `probe_info(url)` (already present at `downloader.py:565`) any `KIND_URLS` row with no duration and refuse `is_live`/over-cap clips as a readable per-clip failure. Add `max_filesize` and an explicit `socket_timeout` to `build_opts`, and `--max-filesize` / `--match-filter "!is_live"` to `build_argv` (they must agree - §5). Add a `shutil.disk_usage` floor at the top of `_phase_download` and a `free_bytes_at(outdir)` re-check between clips in the companion's loop, handing the rest back the way the breaker does. Refuse `/live/` links at paste time with "download it after it ends". Add an ENOSPC branch to `identical_failure_note` so a full NAS does not tell the editor to press RETRY.
- **Effort:** S   **Severity:** high   **Confidence:** high

### YT-6: `.original.mp4` and `.editready.mp4` become second copies of the clip - in the media pool and on the NAS
- **Lens:** pitfall
- **Where:** `ytdl_executor.py:1442-1467` (`swap_in`), `:1316-1317`; `companion/src/ccsync_companion/youtube_import.py:520-540`, `:100-114`; `worker.py:816-846`; `vendor/downloader.py:405`, `:434-467`
- **Scenario:** the clip being converted is already open in the editor's Resolve project - the normal case, since the importer files clips into `Master/Youtube` automatically. Windows refuses `os.remove` on the open file.
- **Today:** `swap_in` moves the locked original aside to `... [id].original.mp4`; if even that fails, the deliverable stays `... [id].editready.mp4` and the broken original keeps the real name. Nothing ever removes `.original`. Both end `.mp4`, so lane A uploads both (YT-3's filter), and `youtube_import._is_clip_name` excludes dotfiles, `.partial/.tmp/.lock` and `.fNNN/.temp` stems but **not** `.original` or `.editready` - so the importer files them into the pool as extra clips. The editor gets two clips per download, one undecodable. Server-side the same names are deliberately outside `_SWEEPABLE` (worker.py:816-821) because `_swap_in` can legitimately deliver under `.editready` - which also means a *truncated* `.editready.mp4` from a container kill is never swept, never disowned, and matches `+ *.mp4`.
- **Proposed:** rename the fallback deliverable to something whose stem still ends in `[id]` (e.g. `<title>.converted [id].mp4`), then add `.editready` to `_SWEEPABLE` and to `youtube_import._is_clip_name`'s intermediate test; add `.original` there too and retry its delete on the next job (id-scoped), reporting the space as reclaimable rather than deleting footage nobody chose to lose. Thread `swap_in`'s existing note into the clip row so the dashboard explains an odd name.
- **Effort:** S   **Severity:** high   **Confidence:** high
- **Related:** CR-79; COMP-BROLL-4 is exactly this, one suffix earlier, in the same function.

### YT-7: a container restart during the conversion ledgers a Resolve-undecodable file as "the fleet already has this"
- **Lens:** pitfall
- **Where:** `db.py:1013-1046`; `vendor/downloader.py:405-431`; `worker.py:936-955`, `:1170`, `:1245-1273`
- **Scenario:** an image update, an OOM, or a compose edit lands while `ensure_edit_ready` is re-encoding a VP9 clip.
- **Today:** `_disown_output` (the YTDL-3 guard) runs only on the **exception** path (:1170) - a container kill is not an exception, the process just ends. It leaves the merged `... [id].mp4` (still VP9/Opus) plus a half-written `.editready.mp4`. On boot `reset_stale_jobs` returns the row to `pending` and the job resumes; `duplicate_location`'s **disk** half (:1269-1272) finds `[id].mp4`, whose stem does end in `[id]` so it passes the anchoring rule, and the clip is marked `skipped, duplicate_of=...`. The editor gets an ALREADY IN badge pointing at a file Resolve flashes Media Offline on, with no route back through the UI. The guard exists; the hole is that it is exception-scoped while the disk-dedupe half accepts an **unledgered** file as proof.
- **Proposed:** in `duplicate_location`, treat a disk hit with no ledger row as *suspect* for a clip the current job itself queued - require a matching `.credits.json` beside it (written only after a successful `download()`), otherwise disown it and download.
- **Effort:** S   **Severity:** high   **Confidence:** high

### YT-8: two executors racing into two projects - `ledger_add`'s UPSERT silently orphans the first copy
- **Lens:** pitfall / user-error (two editors, same clip)
- **Where:** `db.py:1412-1431`; `worker.py:1245-1273`, `:1609-1612`; `routes_fleet.py:560-568`, `:608-628`
- **Scenario:** editor A's companion is fetching video X into project P1 under a lease; the server worker is concurrently fetching X into P2 for editor B's separate job (`claim_next_job` hides only the *leased* job, so the fleet is not serialised across executors).
- **Today:** `duplicate_location` is check-then-act with a gap the size of a whole download. Both checks passed before either file existed; both then call `ledger_add`, whose `ON CONFLICT(video_id) DO UPDATE` **moves** the fleet's record to whichever landed second. The first copy becomes an unledgered file findable only by a disk scan scoped to its own project - REQ 6 ("never re-downloaded") quietly broken, plus double bandwidth from two IPs against YouTube. The docstring at `routes_fleet.py:560-568` identifies this UPSERT hazard for the *stale manifest* case and closes that one; the concurrent case is open.
- **Proposed:** reserve the video id, not just the row: a `download_claims(video_id PRIMARY KEY, job_id, at)` taken at `begin_download` and at `_still_owed`'s hand-out, released on terminal state, gives both executors a fleet-wide CAS and a third source for `duplicate_location`. Alternatively make `ledger_add` non-clobbering (`DO NOTHING` + a `download_locations` child table) so a second copy can never erase the first's provenance.
- **Effort:** M   **Severity:** high   **Confidence:** med-high (wants a live two-job repro)

### YT-9: the AI CLI is handed the dashboard's entire secret environment
- **Lens:** pitfall
- **Where:** `dashboard/src/ccsync_dashboard/cli_tools.py:297-298`, `:348-354`; `ytdl/web/ytdlweb/ai_backend.py:702-713`, `:775-778`; call sites `cli_tools.py:1197`, `:1241-1243`, `:1317`, `:1447`; `ai_providers.py:492`, `:556`
- **Scenario:** a site turns on `ai_cli_providers`; the wizard installs `claude`; an editor's search runs it over YouTube titles and descriptions - untrusted text - in the container that holds the fleet's credentials.
- **Today:** `STRIPPED_ENV_VARS` is exactly four names (the three API keys plus `ANTHROPIC_AUTH_TOKEN`) and `cli_env` is `dict(os.environ)` minus those four. So the CLI receives `DASH_SESSION_SECRET`, `DASH_REPORT_TOKEN`, `SYNCTHING_API_KEY`, `TRUENAS_API_KEY`, `BROLL_INGEST_TOKEN`, `DASH_RELEASE_PUBKEYS`. `ai_backend._cli_argv` passes no `--disallowed-tools` (only the *probe* default does, `ai_providers.py:123`). Both modules' docstrings assert the posture is "the container's own AI keys are removed"; nothing states or enforces that the rest is withheld.
- **Proposed:** invert `cli_env` to an allow-list - `PATH, HOME, LANG, LC_*, TZ, TERM, TMPDIR, HTTP(S)_PROXY, NO_PROXY` plus the `CLAUDE_*`/`CODEX_*` the admin set. One helper, which is `cli_env`'s stated reason for existing, so probe/Test/sign-in/ytdl stay in agreement. Pin with a test asserting `DASH_SESSION_SECRET` is absent from the child env.
- **Effort:** S   **Severity:** high   **Confidence:** high

### YT-10: a wrong API key is stored unvalidated and parks the whole provider chain behind a green chip
- **Lens:** user-error
- **Where:** `ai_providers.py:247-264`, `:275`, `:680-681`, `:624-632`, `:725-734`, `:992-1039`
- **Scenario:** the admin pastes an OpenAI `sk-proj-…` into the adjacent Claude API box. Or the key is revoked, past its spend cap, or from the wrong org.
- **Today:** `validate_key` checks blank / length / control chars only; nothing calls the provider. An API row's availability is `bool(value)` (:680-681) - a **CLI** row, by contrast, is only available after a real probe (:725-734). Anthropic is rank 2, so `resolve_provider` picks the dead key over a working DeepSeek key at rank 5. Every editor's job then dies `claude_auth:` while Settings shows a green "available". The Test button would catch all of it; it is simply never on the write path.
- **Proposed:** run the existing `_live_api_check` inside `api_set_ai_key` after `set_key` and return the verdict in the 200 body; on failure keep the key but record `ai_<name>_last_check = {ok, at, detail}` in `site_settings` (this module already owns rows there, :352-366) so `provider_states` renders the row unavailable-with-a-reason and the chain falls through. Expire the negative verdict (~1 h) so a restored key recovers itself.
- **Effort:** M   **Severity:** high   **Confidence:** high

### YT-11: the editor's YouTube cookie jar is machine-global, rewritten by yt-dlp, and survives sign-out
- **Lens:** pitfall + user-error
- **Where:** `companion/src/ccsync_companion/ytdl_cookies.py:91-115`, `:169-206`; `ytdl_executor.py:2361-2362`, `:2586-2587`, `:1752`; `identity.py:542-548`; `app.py:4220-4234`; `vendor/downloader.py:262-263`
- **Scenario (a):** a shared edit bay - editor A signs in to YouTube through the tray, later signs out of CC Sync, editor B signs in. **(b)** a lost lease kills yt-dlp mid-run while it is rewriting the jar.
- **Today:** (a) `sign_out` clears only the identity file; `resolve()` returns `~/.ccsync/youtube-cookies.txt` for whoever is signed in now. The attestation is per-editor (`ytdl_attestation.accepted(editor)`) but the Google session is not - editor B downloads as editor A's account while the ledger attributes it to B, against the notice's own "downloads are attributed to you". (b) yt-dlp rewrites `cookies.txt` in place on every run it is passed (CR-84 measured exactly this on the NAS, where a parked jar silently refilled with anonymous cookies). Nothing re-runs `validate()` or `secretfile.harden()` afterwards - `resolve()` only checks `isfile` (:110-112) - so a jar degraded to consent cookies, or truncated by a kill, is still "the cookies path", spent on every bot-check fallback and reported as `BOTH_BLOCKED_ERROR`. WP7 solved this for the server (`cookies.txt.orig`) and left the companion column blank; server-side the admin's `YTDL_COOKIES_FILE` is still written back to.
- **Proposed:** (1) hand yt-dlp a per-run **copy** in the scratch dir, never the canonical jar - on both ends, so neither a killed child nor a rewrite can touch the operator's or the editor's file; (2) record `accepted_by` beside the jar and clear it when the signed-in editor changes; (3) have `_run_ytdlp_paths` skip the cookies path when `ytdl_cookies.health()` already says `expired`/`stale`, and mirror the server's CR-84 `JAR_ANONYMOUS` state into `resolve()` (a jar with no login cookie is not a path); (4) delete jar + browser profile on sign-out, with the tray saying so.
- **Effort:** M   **Severity:** high   **Confidence:** high

### YT-12: both halves of the identical-failure breaker have a hole - in-memory per-job on the companion, consecutive-only on the server
- **Lens:** safeguard-with-a-hole
- **Where:** `ytdl_executor.py:1707-1711`, `:2224-2247`; `worker.py:1426-1442`, `:1577-1581`; `docs/YTDL_RESILIENCE_PLAN.md` WP6
- **Scenario (a):** a machine's yt-dlp is broken (YT-1) and every job the editor starts hits the same wall. **(b)** a YouTube change breaks only 1080p+AVC clips, so successes and failures alternate.
- **Today:** (a) `_last_signature`/`_identical_failures` are instance attributes of `DownloadJob` and die with it, so job N stops at clip 3 and job N+1 starts the count at zero, forever - with yt-dlp's full retry budget behind each. WP6 explicitly cites lane B's rule ("a latch must be on disk and cleared by a person, never in-memory") and the companion half does not follow it. Nothing on the machine records that local downloads have failed identically for a week, so the tray says nothing and the editor concludes "requester-first just doesn't work" - CR-38's exact complaint. (b) server-side, `streak` resets to zero on **any** landed clip (:1581), so an alternating wall never reaches 3: the phase grinds through all 41 clips against an angry YouTube and ends `done` with 22 opaque row errors and no note.
- **Proposed:** persist the companion breaker to `~/.ccsync/state/ytdl_breaker.json` in `sync/lane_guard.py`'s shape; on N consecutive identical failures ACROSS jobs stop claiming, publish it through `capabilities()`'s `reason` and surface a tray line ("YouTube downloads on this machine keep failing the same way - the server is downloading them"), cleared by a success or a click. Server-side, keep the consecutive rule and add a rate rule beside it: a `Counter` over signatures tripping when ≥ 8 clips have been attempted and ≥ 60 % failed with the same signature.
- **Effort:** M   **Severity:** high   **Confidence:** high

### YT-13: there is no way to cancel a running local download short of quitting the tray
- **Lens:** user-error
- **Where:** `ytdl_executor.py:2898-2913` (`stop_all`, called only from `broll_server.py:2125` at shutdown); `tray.py:1820-1863` (display only)
- **Scenario:** the editor started a 40-clip job and has to leave for a shoot on a tethered link; or an ffmpeg re-encode is eating the machine mid-edit.
- **Today:** the tray shows `Downloading YouTube clip 3/12 (4.2 MB/s)` and offers nothing to click. `DownloadJob.stop()` exists and is safe (it kills the child; the litter is id-scoped) but is wired only to tray shutdown. Quitting the companion also stops all three sync lanes, so the only available answer to "stop downloading" is "stop syncing".
- **Proposed:** a tray item and Settings button `[ STOP THIS DOWNLOAD ]` calling `stop_all()`, plus `POST /ytdl/stop` on the 8899 loopback so the SPA's cancel reaches the machine that actually holds the job. Stopping should let the lease lapse via the existing hand-back path, so the server picks up the rest exactly as it does for the breaker.
- **Effort:** S   **Severity:** med-high   **Confidence:** high
- **Related:** CR-30/CR-75 fixed cancel semantics server-side; the requester's own machine has none.

### YT-14: cancelling a download job is a one-way door - the clips left `pending` can never be retried
- **Lens:** user-error
- **Where:** `routes_api.py:1084-1096`, `:955-958`, `:963-968`; `worker.py:339-342`, `:1461-1464`
- **Today:** `_phase_download` returns on cancel leaving unreached rows `pending`, and `run_job` sets phase `cancelled`. `start_download` accepts only `('ready_for_review', 'done', 'failed')`, so a job cancelled at clip 12 of 41 can never be resumed: the editor's only route to the remaining 29 clips is a whole new search - another AI spend, another ~20 minutes of enrichment, another 29 requests at YouTube. CR-75 built three affordances for the `ready_for_review` parking case but not this one, and YTDL-16's resume path is exactly what a mid-download cancel needs.
- **Proposed:** add `'cancelled'` to the accepted phases alongside the same `failed_videos or unfinished_downloads` guard already written for `failed` (:963-968) - `clear_cancel` and `clear_mode_lock` are called two lines later, so the state machinery is already in place.
- **Effort:** S   **Severity:** med-high   **Confidence:** high

### YT-15: an API key is written non-atomically, so a job can read a truncated key - permanently, on ENOSPC
- **Lens:** pitfall
- **Where:** `ai_providers.py:275`, `:241`, `:786`; `secrets_boot.py:66-77`
- **Today:** `write_secret_file` is `os.open(O_WRONLY|O_CREAT|O_TRUNC, 0o600)` plus one `fh.write` - no temp file, no rename, no fsync, unlike `cli_tools._write_state` (`cli_tools.py:272-277`) which does it correctly. `read_key` runs on **every** AI call from the ytdl worker thread. Concurrent with an admin's PUT a job reads `""` or a prefix; on ENOSPC or a container kill mid-write the file stays truncated, `key_present` is still `True`, the mask still looks plausible, and every job 401s until someone re-pastes.
- **Proposed:** tmp-at-0600 + `flush`/`fsync` + `os.replace` in `secrets_boot._write_secret_file`. It is the shared helper, so this also hardens the five boot secrets and the `setup-token` file (`cli_tools.py:1366`).
- **Effort:** S   **Severity:** med-high   **Confidence:** high

### YT-16: a stale `setup-token` makes a failed sign-in report success, then poisons every job
- **Lens:** pitfall
- **Where:** `cli_tools.py:1320`, `:1399-1412`, `:1440-1447`, `:341-344`, `:907`, `:1202`
- **Today:** `_run_strategy` deliberately pops `CLAUDE_CODE_OAUTH_TOKEN` before the login child so the login cannot succeed against the held token - but the verification immediately after does not: `auth_status` runs with `cli_env(...)` and `cli_env_overlay` re-injects the token whenever the file exists. A cancelled or failed `auth login` therefore still answers `loggedIn: true` from the *old* token, the session flips to `signed_in`, and the chip goes green. If that token is revoked, the same overlay reaches every real ytdl call and the CLI prefers it - jobs fail auth while the page says signed in. Only `sign_out`/`remove_install` ever delete it.
- **Proposed:** pass an explicit `use_token: bool` to `auth_status` and pop the var when confirming a non-token strategy; delete `token_path` on a successful `auth-login` - a fresh login supersedes the stash, and holding two is what makes the page and the job disagree.
- **Effort:** S   **Severity:** med-high   **Confidence:** high
- **Related:** CR-26 (the pty wizard has never been exercised on a real container).

### YT-17: a 429 reads as "the model returned something unparseable", and nothing backs off
- **Lens:** pitfall + user-error
- **Where:** `ai_backend.py:469-474`, `:604-631`, `:746-750`; `worker.py:363-368`; `claude_cli.py:1094-1105`
- **Today:** `_http_error` maps 401/403 → auth and 408/504 → timeout, and **everything else, 429 and 529 included, → `ERR_OUTPUT`**, whose SPA hint is "the model returned something unparseable" - the wrong call to action for a rate limit or an exhausted balance. Nothing retries or honours `Retry-After`; `worker._tick` fails the job outright, so a tier-1 key at its per-minute limit fails every queued editor's job in sequence, each burning another request against the limit. Separately `_AUTH_MARKERS` contains `'subscription'`, so a CLI's "you have reached your subscription usage limit" is classified as auth and the admin is told to sign in again.
- **Proposed:** classify 429/529 (and a usage-limit stderr phrase, tested *before* `_AUTH_MARKERS`) as a distinct retryable class, honour `Retry-After`, and re-queue with backoff instead of `set_phase('failed')`. Map it onto the existing `ERR_TIMEOUT` wire prefix so cached SPA bundles keep a sensible hint.
- **Effort:** M   **Severity:** med-high   **Confidence:** high

### YT-18: the CLI install lock has no deadline, no cancel and no free-space check
- **Lens:** pitfall
- **Where:** `cli_tools.py:706-716`, `:736-738`, `:468-513`, `:186`, `:900-903`, `:1589-1622`, `:414-432`, `:203-206`
- **Today:** `_install_running` is set before the thread starts and cleared only in the worker's `finally`; `thread.start()` (:714) is outside any try, so a failure there pins the lock. `DOWNLOAD_TIMEOUT = 900.0` is a urllib **per-read** socket timeout, not a total deadline, so a dribbling CDN keeps the thread alive indefinitely. While held, every install 409s, `remove_install` refuses, and there is **no cancel route** - the cure is a container restart, which to this owner reads as "the dashboard is stuck". There is also no free-space test anywhere: `tools_root` shares the volume with `dashboard.db` and `<data>/secrets/ai/`, an install is ~313 MiB against a 512 MiB cap, and a `.staging/*.part` can be resident alongside a version dir - filling that volume gives sqlite ENOSPC on the fleet database and turns YT-15 into a truncated key.
- **Proposed:** record `started_at`, enforce a total deadline inside `_download`'s read loop (it already calls `progress()` every MiB - the natural place for a cancel flag too), wrap `thread.start()`, add `POST .../install/cancel`, and compare `shutil.disk_usage(...).free` against `size * 1.5` in `install_supported` with the same refusal shape as the existing writability check.
- **Effort:** M   **Severity:** med-high   **Confidence:** high
- **Related:** trust-model-7 (CR-56) covers the checksum; nothing covers the transfer.

### YT-19: nothing sweeps disowned corpses or orphaned intermediates on the companion, and lane A uploads them
- **Lens:** pitfall
- **Where:** `ytdl_executor.py:141`, `:1190-1203`, `:1237-1283`; `worker.py:849-873` (`_sweep_stale`, `STALE_AFTER = 24 h`)
- **Scenario:** a 40-clip job failing at 90 % each on a bot check; a laptop lid closing at clip 7; the tray killed from Task Manager.
- **Today:** the server has an age-based sweep of its term folder; the companion has only the id-scoped cleanups it runs on its own failure paths, and `disown_output` renames a failed attempt to `... .mp4.failed` which **nothing anywhere ever deletes**. A killed companion runs neither, so `... [id].f137.mp4` - a complete video-only stream, not a `.part` - sits in the term folder, matches lane A's `+ *.mp4` and is uploaded to the canonical tree as a silent 1.4 GB orphan. On the base rig both accumulate directly on the NAS.
- **Proposed:** port `_sweep_stale` into the executor as a startup/job-start sweep of its own term folders (`is_sweepable` is already the predicate; it just has no scheduled caller), delete `.part`/`.ytdl`/`.temp.*`/`.fNNN.*` older than 24 h, and report `.failed` corpses older than 7 days through the report payload as reclaimable space rather than deleting them.
- **Effort:** S   **Severity:** med-high   **Confidence:** high
- **Related:** YTDL-3, COMP-BROLL-3, R15 fix 3.

### YT-20: `reset_stale_jobs` reaches across every job in the database, including one a companion is downloading right now
- **Lens:** pitfall
- **Where:** `db.py:1039-1042`
- **Today:** `UPDATE job_videos SET dl_state='pending' WHERE dl_state='downloading'` - no `job_id`, no lease predicate. A lease is a timestamp in SQLite, not in-process, so it survives a container restart: restarting while an editor holds a live lease resets the clip that companion is fetching *right now* back to `pending`, `download-manifest` lists it again via `db.pending_videos`, and `_still_owed` hands it out a second time. The companion's own `done` post then wins the `finish_download` CAS and the duplicate work is invisible. The docstring's reasoning ("anything that actually finished is caught by the dedupe re-check") is a server-worker argument that does not hold for a local executor mid-file.
- **Proposed:** scope the reset to jobs with no live lease - `AND job_id IN (SELECT id FROM jobs WHERE download_mode<>'local' OR lease_expires_at IS NULL OR lease_expires_at<=?)`.
- **Effort:** S   **Severity:** med   **Confidence:** high

### YT-21: a momentary DB blip 404s the whole downloader for the fleet, silently
- **Lens:** pitfall
- **Where:** `dashboard/src/ccsync_dashboard/ytdl.py:365-368`, `:375-379`, `:422-428`, `:468-476`
- **Today:** `feature_enabled` swallows a `db.connect` failure with **no log line at all** (the sibling `except` two lines down does warn) and returns `fallback` - `False` on a vendor build. So a transient `database is locked`, an ENOSPC or a NAS remount makes the gate record DISABLED and answer **404 to every path under `/ytdl`**, for editors mid-job and for every companion's fleet call, for the 5 s TTL. The comment says "an unopenable DB decides nothing here"; the code decides *off*.
- **Proposed:** log a warning naming the exception (once per TTL) and, on an unreadable DB, keep the gate's previous answer - `YtdlFeatureGate` already holds `self._enabled` - rather than flipping a live feature off on a default.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** CR-58 is the same class in the other direction.

### YT-22: a `done` post's filename is not checked against the clip it claims to be
- **Lens:** pitfall
- **Where:** `routes_fleet.py:683-684`, `:727-765`, `:441-449`; `worker.py:931`
- **Today:** the path is correctly rebuilt server-side through `safe_join` from the job's own label, so traversal is blocked (§8's rule is honoured). What is *not* checked is that `name` bears this clip's `[video_id]` at the end of its stem - the anchoring rule every other reader of the tree uses. A companion whose template skew slipped past the `template_version` gate (declared, not measured), or whose `swap_in` fell through to `.editready.mp4`, posts a name the fleet's dedupe can never find again: the ledger says the clip is in the fleet, `duplicate_location`'s disk half disagrees on every future search, and `_reclaim_local_job`'s `_landed_file` re-downloads it.
- **Proposed:** record `failed` with a named reason for any `done` post whose `Path(name).stem` does not end in `[{video_id}]` - the one-line rule `_landed_file` already applies.
- **Effort:** S   **Severity:** med   **Confidence:** high

### YT-23: the canary is off by default, so the only always-on evidence is a side effect of somebody downloading
- **Lens:** safeguard-with-a-hole
- **Where:** `ytdl_canary.py:50-52`, `:187-192`; `config.py:359-360`; `routes_api.py:170-174`
- **Today:** `ytdl_evidence` plus the canary are a genuinely good answer to CR-73/CR-80's "health was green throughout". But `CANARY_INTERVAL_SECONDS` is unset in the vendor build and `ensure_started` returns `False` with a `log.debug`, so on a default deployment `paths` in `/api/health` is populated only by real downloads. A fleet that downloads nothing for a week is back to the CR-83 symptom exactly: the first editor to press DOWNLOAD after a YouTube change is the detector, days late.
- **Proposed:** when the canary is off and `last_download.at` is older than ~48 h, return `evidence: 'stale'` and have the SPA say "nothing has been fetched from YouTube since <date>, so this pip is not proof" - an honest unknown instead of a stale green.
- **Effort:** S   **Severity:** med   **Confidence:** high

### YT-24: the browser sign-in profile holds a live Google session at default Windows permissions
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/ytdl_browser_login.py:506-512`, `:181-183`; `secretfile.py:85-104`; `installer/windows_uninstall.ps1:359-373`
- **Today:** the cookie *jar* is written through `secretfile.harden` precisely because `os.chmod(0o600)` is a no-op on Windows (COMMERCIAL_READINESS item 5) - but `~/.ccsync/yt-login-profile`, which holds the same live Google session in Chromium's own store, is created and then `os.chmod(profile, 0o700)`'d with the failure swallowed (:510-512). On Windows that is item 5's exact bug, on the directory holding the *larger* copy of the secret. The profile is kept deliberately (so "sign in again" is instant) and is deleted by neither sign-out nor a non-`-Full` uninstall.
- **Proposed:** harden the profile directory the same way the jar is hardened, delete it on sign-out along with the jar (YT-11), and have the non-`-Full` uninstall at least *name* the leftover Google session in its "KEPT" line so the owner can decide.
- **Effort:** S   **Severity:** med   **Confidence:** high

### Smaller items, noted not ranked
- **`_redact` knows one token shape** (`cli_tools.py:925`, `:946-950`): `sk-ant-…` only, and it is the sole guard on the session tail, the status detail, `auth_status`'s echo, and an INFO log line that writes 120 raw bytes of the pty transcript (`:1286-1287`). A Codex bearer, an `sk-proj-…`, or a changed Anthropic prefix all survive - and in that last case `_extract_token` also returns `""`, so the token is neither captured nor scrubbed. Widen to a pattern set; never log a transcript slice.
- **`run()`'s generic-exception path skips cleanup** (`ytdl_executor.py:1797-1808`): `except LeaseLost` calls `_cleanup_current()`, the bare `except Exception` does not - so an unexpected failure leaves the in-flight `.part` uncleaned and the row at `downloading` with no `failed` post. Move it into the `finally` (it is idempotent) and post a reason.
- **AUTO probes every CLI on every cache miss** (`ai_providers.py:761-766`, `:653-735`): `resolved()` short-circuits only when a pin is set, so a site with Claude Code signed in still spends a billed Codex call every 600 s and can block the worker thread for over a minute inside someone's job. The `only=` parameter already exists; walk `PROVIDER_ORDER` and stop at the first available.
- **A plain-`http://` provider base URL leaks the key** (`ai_providers.py:1060-1070`, `ai_backend.py:541-561`): both credential-carrying paths take the base URL from an env var with no scheme check, while going to some trouble over redirects for exactly this reason. One `_require_https()` helper (allowing loopback) makes the existing comment true end to end.
- **After any restart the wizard reports a signed-in CLI as not signed in** (`cli_tools.py:1539`, `:305-309`): only the `setup-token` strategy writes a file, so the *preferred* `auth-login` looks lost after `docker compose up` and the admin is invited to re-run the one operation that can break a working install (YT-16). Cache `auth_status`'s verdict in `state.json`.
- **`_await_local_claim` blocks the singleton worker 4 s per download phase** (`worker.py:1351-1380`) with no early exit for structurally unclaimable jobs (`mode_lock='server'`, a cancelled job, an empty pending list). Return `False` immediately for those.
- **`ai_backend._anthropic_provider` is a module global** stashed for one call (`:418-440`), safe only because the worker is a singleton. `threading.local()` is two lines and removes the constraint before someone relies on it.

## Cross-cutting notes

- **For the sync-lane agent (highest value):** `build_filter_rules_up` (`sync/rclone_lane.py:397-402`) is `+ *<ext>` over the whole tree with `copy --ignore-existing` and a `--min-age` gate that mtime-preserving writers defeat. That is not ytdl-specific: anything that writes a video under its final name and then rewrites it (proxy generation, the fixer, an ingest tool) has the same "first bytes to reach the NAS win, forever" exposure. The general question is whether lane A should ever upload a file a local process still holds open.
- **For the Resolve/importer agent:** `youtube_import._is_clip_name` (`youtube_import.py:520-540`) is the only thing between yt-dlp's working files and the media pool, and it is a hand-maintained deny-list already retrofitted once (COMP-BROLL-4). `.editready`/`.original` are missing today; the next suffix will be missing tomorrow. A positive rule - "the stem ends in `[id]`", which `landed_file` already uses - would be self-maintaining.
- **For the dashboard/deploy agent:** CR-84's rule (three yt-dlp locks, `dashboard/deploy/requirements.lock` is the image's) is enforced by one test comparing locks to floor files. It does not catch "the floor itself is six weeks old", which is YT-1's server half.
- **For whoever owns secrets:** `secrets_boot.write_secret_file` (YT-15) is shared by five boot secrets, not just the AI keys; the fix is one function.
- **Guards verified sound - do not re-propose:** `begin_download`/`finish_download` as a matched CAS pair with a 200 `{duplicate:true}` for the loser; `_disown_output`/`_clear_partials` id-scoping; `_landed_file`'s `[id]`-anchoring; the `_bot_checked`/`_account_flagged` two-classifier split and the anonymous-first inversion; `expire_lease` as the single stop signal; `clear_mode_lock`'s five-column reset (CR-37); fail-closed `require_fleet_caller`; `video_id_of`'s loud refusal of playlist and channel URLs; the `ytdl_common` byte-identical vendoring gate; `ytdlp_manager.install`'s checksum-then-rename ordering and its GitHub-only redirect handler.
