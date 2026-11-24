# Points settled from the code: CC Sync and the Footage Sorter

Answers to the 21 points in `_unsettled-ccsync.md`, read from the code on 2026-11-24 (ccsync `main` at 8ebdaec, footage-sorter working tree). One block per point, in the list's order.

### accounts-privacy-legal-U1
- Answer: There is no such period. Records of conversations with the assistant (the Timeline Cards montage conversations, and the assistant program's own session logs on the server) are kept with no age or count limit and nothing ever deletes them; there is no site setting for it. Only one small use of the assistant (gear descriptions) asks the assistant program not to keep its session at all.
- Sure: not in the code
- Where: dashboard/src/ccsync_dashboard/cards_ai.py:1209-1214 (`_session_path`, `_sessions_dir` -> `<data>/cards_sessions/<id>.json`; written, never pruned; no caller removes files there); dashboard/src/ccsync_dashboard/db.py `prune()` has no assistant-record rule; dashboard/src/ccsync_dashboard/gear_ai.py:267 (`--no-session-persistence`, the one exception). Lesson ACC-050 is marked "outcome not found" in the knowledge base.

### broll-U1
- Answer: Good needs 8 GB of graphics memory (16 GB on an Apple Silicon Mac); Best needs 12 GB (24 GB on Apple Silicon). The model download is 3.33 GB for Good (2.50 GB of model plus 0.84 GB of image reader) and 6.19 GB for Best (5.03 GB plus 1.16 GB). These match the figures the specification already uses.
- Sure: read in the code
- Where: companion/src/ccsync_companion/broll_vlm/local_models.py:104-157 (`TIERS`: `vram_gb`, `apple_unified_gb`, `size_bytes` 2_497_281_664 + 836_180_256 and 5_027_784_800 + 1_159_029_824); same values in broll/indexer/broll_index/local_models.py:88,114.

### broll-U2
- Answer: Yes. At the playhead the clip's sound goes to the audio track with the same number as its video track (V3 and A3, for example). A track number is chosen only when both its video and its audio track are free over the clip's span; missing video tracks and stereo audio tracks are added up to that number.
- Sure: read in the code
- Where: companion/src/ccsync_companion/resolve_bridge.py:3096-3117 (`_overlay_track`: "One index serves both streams because AppendToTimeline takes a single trackIndex -- the clip's nat sound rides to the same-numbered audio track"), 3120-3141 (`_ensure_track`, audio added as "stereo"), 3465-3527 (`place at playhead`, one `trackIndex`, no `mediaType`).

### dashboard-1-U1
- Answer: A background pass of the server counts as slow when it takes longer than 60 seconds (one cycle); the card closes when that pass next finishes within 60 seconds. Slow-work card: heading "one of this server's background passes is taking longer than a cycle"; text "<N> time(s) the <pass name> pass took longer than a cycle; the last one took <S> s. Most of a pass is a walk of the NAS tree or a Syncthing round trip, which happen outside any database transaction, so on its own this does not mean anything waited on the database."; what to do: "If the fleet also shows 'database busy', look for a 'slow write' notice from the same minute: that is the writer that held the lock. If this is the inventory pass alone, the tree it walks has grown; archive the projects nobody syncs any more." Moves-left-out card (an error, raised when one pass finds more than 500 moves): heading "more file moves were made on the server in one go than could be followed"; text "<found> file moves were found on the server in one pass and only <recorded> could be recorded, so <dropped> were dropped. Those files are a deletion as far as every editor's computer is concerned: their copies go back up to the old paths, and proxy download stops itself on the computers that held them."; what to do: "Find what changed on the server (a restore, a remount, or a big reorganisation), then move the rest with "Move on the server and on every computer" on the project page so every computer follows." (Separately, saving one computer's report counts as slow at over 1 second, and has its own card.)
- Sure: read in the code
- Where: dashboard/src/ccsync_dashboard/notices.py:1611-1662 (`SLOW_POLL_SECONDS = 60.0`, `record_slow_poll`, `clear_slow_poll`); collector.py:576-583 (open/close); db.py:3894-3902 (headings of `slow_poll` and `file_moves_dropped`); notices.py:852-881 (`record_moves_dropped`); collector.py:2599 (`DETECTED_MOVE_LIMIT = 500`), 2041-2074; api.py:109,11463 (`SLOW_REPORT_SECONDS = 1.0`).

### dashboard-1-U2
- Answer: The computer's row shows "clock ... ahead/behind" (AHEAD or SLOW) once its clock is 1 minute or more away from the server's; the "why it is not syncing" explanation uses the same 1 minute. The mailed alert "a computer's clock is wrong" waits until the difference reaches 5 minutes. Two different thresholds in two places.
- Sure: read in the code
- Where: dashboard/src/ccsync_dashboard/db.py:672 (`CLOCK_SKEW_WARN_SECONDS = 60.0`) used at api.py:1224-1227 and templates/partials/fleet_grid.html:120; health.py:544,861-864 (`CLOCK_SKEW_WHY_SECONDS = 60.0`); alerts.py:127 (`CLOCK_SKEW_ALERT_SECONDS = 5 * 60`), 1645-1664, 4245-4246.

### dashboard-2-U1
- Answer: Every 2 seconds: the live transfers panel on the home page, and the transfer list on the Transfers page. Every 5 seconds: the panel on a project page that shows which computers hold the project's media. Those are the only panels at those two paces, so they are the ones a phone or tablet slows to 10 and 15 seconds. The other panels: every 10 s (the sync queue on the home page, the sync plan on a project page, a panel on the account page), 15 s (a home-page panel, the shared-work panel), 30 s (sidebar, top bar, admin users and packages lists, project roots, each computer on the account page) and 60 s (several home-page and admin-users panels).
- Sure: read in the code
- Where: dashboard/templates/fleet.html:100 (home page "/", `/partials/home-transfers` every 2s), templates/transfers.html:32 (every 2s), templates/project.html:50 (`/partials/project/<slug>/bins` every 5s); dashboard/static/pwa.js:19 (`SLOWER = { '2s': '10s', '5s': '15s' }`); the other `hx-trigger` paces in fleet.html:69,77,109,119, project.html:44,80, account.html:106,180, admin_users.html:41,50,58,66, admin_packages.html:31, partials/admin_jobs.html:29, partials/topbar.html:62, partials/home_macros.html:91, partials/account_computer.html:21, shell.html:139.

### fleet-jobs-U1
- Answer: In the code, b-roll and music analysis are not kinds of the shared-work queue at all, so they have no entry in its tries or studio-wide limit tables. They run as their own batches: a batch is taken by one computer of the person who dropped the clips (another of that person's computers is refused while the first holds it), and there is no studio-wide limit on how many batches run at once. Each clip or track is tried at most 2 times; after that it is left as failed until someone presses retry. The quiet wait is 5 minutes without keyboard or mouse by default (the computer's proxy-making quiet time unless set separately for b-roll or music), and a batch can be run "in the foreground", which ignores the quiet wait.
- Sure: read in the code
- Where: dashboard/src/ccsync_dashboard/db.py:12442-12516 (`JOB_KINDS`, `JOB_RETRY_BUDGET`, `JOB_MAX_RUNNING`: no b-roll or music kind); broll/web/app/ingest_batches.py:775-808 (`claim`: owner only, 409 while another machine's lease lives), 136-139, 227 (`RUN_MODES`, default "idle"), 584 (`retry_failed`); companion/src/ccsync_companion/broll_ingest.py:126 (`MAX_ITEM_ATTEMPTS = 2`), 818-820 (`<kind>_idle_seconds`, falls back to `proxy_gen_idle_seconds`, 300); music_ingest.py:10 (music reuses the b-roll ingestor); ingest_kinds.py:120-127.

### footage-sorter-and-camera-cards-1-U1
- Answer: There is no "no progress for a set time" stop for a card or drive copy. The copy is stopped only when the card is taken out, the destination goes away or changes letter, the destination is full, or the person presses Stop. With the outside copier on Windows, the wait for it is bounded overall (at least 30 minutes plus the time the files take at 20 MB a second), after which the product stops waiting and checks the destination by name and size; that only writes a log line ("still unfinished after <N> min; giving up waiting"), nothing a person is shown.
- Sure: not in the code
- Where: companion/src/ccsync_companion/card_copy.py (stop reasons at 268-477, 737, 753-1089; no stall timer); companion/src/ccsync_companion/teracopy.py:76-95 (`MIN_WAIT_SECONDS`, `ASSUMED_BYTES_PER_SECOND`, `wait_limit_seconds`), 423-441 and 640-731 (`wait_for_job`: start grace 120 s, idle grace 60 s, verify grace 180 s, overall limit). Nothing in E:\Projects\Editing\footage-sorter either.

### footage-sorter-and-camera-cards-1-U2
- Answer: Every 10 minutes by default (a setting, never more often than every 1 minute; the first look is 90 seconds after the Sorter starts). The "about every hour" figure is a different thing: how often a watched folder is re-scanned for the record of which drives hold which files (60 minutes by default, per watched folder).
- Sure: read in the code
- Where: footage-sorter/footage_sorter/autobackup.py:23 (`DEFAULTS["everyMinutes"]: 10`); footage_sorter/engine.py:319 (`max(1.0, everyMinutes) * 60`, `first=90`); the hourly one is footage_sorter/ledger.py:154,488,686 (`watch.every_minutes` default 60, the watch scan).

### footage-sorter-and-camera-cards-1-U3
- Answer: There is no separate reminder about laptop-only footage. It is the first section ("Only on a laptop") of the one daily mail about footage not at home, sent once a day, and the mail's subject adds "⚠ <size> only on a laptop" when there is any.
- Sure: not in the code
- Where: footage-sorter/cloud/ledger/wrangler.toml (`crons = ["0 0 * * *"]`, once a day); cloud/ledger/src/index.js:554 (`sec('laptop-only', '⚠ Only on a laptop')`), 612-635 (`remind`, subject built at 623, `scheduled`); footage_sorter/ledger.py:1870-1891 (`_digest`, same sections).

### music-U1
- Answer: 200 MB (binary megabytes, about 210 million bytes) on top of the model's own size. The refusal reads "Not enough disk space for the music indexing model: needs about <X> GB free at <folder>, has <Y> GB. Free some space and try again", where X already includes the margin.
- Sure: read in the code
- Where: companion/src/ccsync_companion/music_clap_sidecar.py:281-307 (`required_bytes` adds `upgrade.MIN_FREE_BYTES_MARGIN`; `free_space_refusal`); companion/src/ccsync_companion/upgrade.py:115 (`MIN_FREE_BYTES_MARGIN = 200 * 1024 * 1024`).

### music-U2
- Answer: Neither. The code leaves out recorder takes, voiceover, short stings and long recordings nowhere: not from a person's drop, and not from the look over the whole library. The only thing the library-wide look skips is anything inside a folder named "_stems". A track of any length is taken (the mood and tempo analysis reads at most its first 6 minutes).
- Sure: not in the code
- Where: music/indexer/index_music.py:54-63 (`iter_files`: audio extension and `EXCLUDE_DIRS` only); music/indexer/music_index/config.py:60-64 (`EXCLUDE_DIRS = {'_stems'}`, `AUDIO_EXTS`); music/indexer/music_index/features.py:87-100 (`max_seconds=360`); no duration or name filter in companion/src/ccsync_companion/music_ingest.py or music/web/musicweb/routes_ingest.py.

### proxies-and-file-moves-U1
- Answer: Not on every computer. Unless someone sets it, a computer makes proxies itself only when it does not download proxies from the server. So it is off by default on an ordinary editing computer (which downloads proxies), and on by default on a computer wired to the server (which works straight off the NAS). Set explicitly on or off, the setting is obeyed as set.
- Sure: read in the code
- Where: companion/src/ccsync_companion/config.py:457 (`lane_b_enabled: True`), 477 (`proxy_gen_enabled: None`), 977-988 (`MODE_PROFILES["base"]` sets `lane_b_enabled: False`), 2646-2684 (`proxy_generation_enabled`: explicit bool wins, else `not lane_b_enabled`).

### proxies-and-file-moves-U2
- Answer: Originals are files ending .braw, .mov, .mp4, .mxf, .avi, .mts, .m2ts, .mkv, .r3d, .crm, .mpg, .mpeg, .wmv or .webm (any letter case). Files ending .insv or .360 are video too but never counted or queued. .braw, .r3d and .crm count as missing but are left for the Blackmagic Proxy Generator rather than made by the app. The YouTube working files skipped are names matching "*.editready.*", "*.original.*", "*.temp.*", "*.f<three or more digits>*.*" (the separate picture-only or sound-only download pieces) and "*.failed".
- Sure: read in the code
- Where: companion/src/ccsync_companion/sync/rclone_lane.py:52-55 (`VIDEO_EXTS`), 143-149 (`YTDL_WORK_EXCLUDE_RULES`); companion/src/ccsync_companion/proxy_scan.py:80 (`SKIP_GENERATION_EXTS`), 161-180 (`generation_state`, `NEEDS_RESOLVE_EXTS`), 410-438 (the scan's filters).

### proxies-and-file-moves-U3
- Answer: Every 2 minutes by default, counted from the end of one pass to the start of the next (a per-computer setting). The pointing at proxies rides on the app's regular walk of the open Resolve project's media and can be switched off on a computer (on by default).
- Sure: read in the code
- Where: companion/src/ccsync_companion/config.py:420 (`media_tree_refresh_interval: 120`), 464 (`proxy_relink_enabled: True`); app.py:2121, 4843-4856 (`_relink_proxies_once` called from `_refresh_media_tree_once`), 5316 (`_media_tree_stop_event.wait(self.media_tree_refresh_interval)`).

### server-install-and-running-1-U1
- Answer: Both are off for a new site. Timeline Cards is on only when the site turns it on and its code is being installed; the same for the Footage Sorter. Timeline Cards' new editor is off too, and is on only when asked for and Timeline Cards is on.
- Sure: read in the code
- Where: server/install_dashboard_app.py:547 (`site_bool("timeline_cards", "enabled", False)`), 562 (`editor`, False), 996-1002 (`cards_enabled_for_site`), 1060 (`site_bool("footage_sorter", "enabled", False)`), 1291-1294 (`sorter_enabled_for_site`), 1825-1831; dashboard/src/ccsync_dashboard/settings.py:1021,1033 (`DASH_CARDS_ENABLED` / `DASH_SORTER_ENABLED` must be "1").

### server-install-and-running-2-U1
- Answer: Nothing tells the admin. The NAS's clock is never compared with true time. The only related step reads the NAS's time-zone name once at install, for the Footage Sorter's schedules; it does not check the clock or warn about it.
- Sure: not in the code
- Where: server/install_dashboard_app.py:1143-1192 (`SITE_SORTER_TIMEZONE`, `probe_nas_timezone`, `parse_nas_timezone`); no clock check in dashboard/src/ccsync_dashboard/alerts.py (`ALERT_KINDS` has `clock_skew` for editors' computers only) or in footage-sorter.

### sync-1-U1
- Answer: None of these has a control on any screen. They are changed only by editing that computer's own settings file (so: whoever can edit files on that computer), and take effect when the app restarts. An admin cannot set them from the dashboard: the only things the dashboard can ask a computer to change are whether it lends itself to shared work and which kinds. The settings window's own switches are wired or editing mode, the four reporting switches and the shared-work settings.
- Sure: worked out from the code
- Where: companion/src/ccsync_companion/config.py:241-264 (`lane_b_min_age_seconds`, `lane_b_max_deletes_per_pass`, `lane_b_max_delete_fraction`, `lane_b_min_free_bytes`, `trash_max_age_days`, `trash_max_bytes`), 430 (`project_rotation_seconds: 600`), 718-743 (`shutdown_warning_enabled`, `keep_awake_while_syncing`, `keep_awake_*`); settings_window.py:482, 1182-1201, 1388-1492 (what the window writes: `mode`, report switches, `jobs_enabled`, `jobs_volunteer_minutes`, `jobs_kinds`); dashboard/src/ccsync_dashboard/db.py:14108 (`MACHINE_SETTING_KEYS = ("jobs_enabled", "jobs_kinds")`).

### sync-1-U3
- Answer: More than a quarter of the active projects (rounded down), and never fewer than 2: if more than that many would be marked inactive in one check, none are. A project seen within the last 15 minutes is never counted.
- Sure: read in the code
- Where: dashboard/src/ccsync_dashboard/db.py:3259-3319 (`deactivate_missing_projects`: `ceiling = max(2, n_active // 4)`, refused when `len(candidates) > ceiling`; `grace_seconds=900`); collector.py:1325-1330.

### sync-2-U1
- Answer: Yes. Syncing does not start while the computer's settings have an error that stops syncing (for example no sync folder or no server folder set) or while nobody on it has accepted the current licence; the menu then says "Sync: not set up yet", and the reason given is the sentence naming the broken setting, or "This computer is not set up for syncing yet." Everything else (reporting to the server, the tray) keeps running so the computer can still be seen and fixed. The code does not record whether the setting-up wizard itself was finished; it judges by the settings and the licence.
- Sure: read in the code
- Where: companion/src/ccsync_companion/app.py:7130-7159 (`_lanes_refusal`: `LANE_GATE_CONFIG`, `LANE_GATE_EULA`), 7202-7230 (`_start_lanes` returns without starting); tray.py:2605-2606.

### youtube-U1
- Answer: There is no "wrote nothing for a set time" stop. The only limits are on the whole run: a download on an editor's computer is stopped after 2 hours and the conversion to an editable file after 3 hours (the raw reasons recorded are "yt-dlp did not finish within 2h and was killed" and "ffmpeg did not finish within 3h and was killed").
- Sure: not in the code
- Where: companion/src/ccsync_companion/ytdl_executor.py:324 (`CLIP_TIMEOUT_SECONDS = 2 * 3600.0`), 3060-3064, 1639 (`CONVERT_TIMEOUT_SECONDS = 3 * 3600.0`), 2703-2716; no progress watchdog in ytdl/web/ytdlweb/worker.py.
