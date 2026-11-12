# Companion: configuration, reporting to the server, fleet jobs, self-update and crash handling

Terms used throughout:

- **Companion**: the tray app on each editor's computer.
- **Dashboard**: the server the companion reports to and takes commands from.
- **Report**: the periodic status POST the companion sends to the dashboard; the dashboard's answer is the **report reply**, and the `commands` block inside it is how the dashboard tells a machine to do things.
- **Fleet job** (or "job"): a unit of work the dashboard queues and offers to machines (transcription, proxy encoding, card copy, and so on).
- **Lane A / B / C**: the three sync paths (A uploads originals with rclone, B downloads proxies with rclone, C is Syncthing).
- **Base rig**: a machine that works directly off the server share and syncs nothing locally (`mode = "base"`).
- **Site manifest**: the per-customer settings document the dashboard publishes at `GET /api/v1/site`.

## Configuration file: location, creation, loading, writing (source: config.py)

- The configuration file is `~/.ccsync/config.toml` (TOML). The folder `~/.ccsync` is the companion's home for state on every platform.
- **First run**: when the file does not exist, the companion writes a hand-maintained, commented template (every user-facing key with an explanation) and immediately restricts it to the owner only (owner-only file permissions; on Windows this runs `icacls`).
- **Hardening of an old file**: once per process, an existing `config.toml` at the real path is re-restricted to owner-only (it carries a fleet token). Not done for any other path.
- **Byte-order mark tolerated**: the file is read as UTF-8 with an optional BOM, because PowerShell installers prepend one.
- **Backup of the last good file**: every time `config.toml` parses cleanly, its exact text is copied to `config.toml.bak` (only rewritten when the content changed; the backup is also owner-only).
- **Unparseable file, backup present**: the companion runs on the backup's settings and records an error: "config.toml could not be read, so CCSync loaded the last good copy of your settings instead -- ...". It is an ERROR, so sync lanes do not start until a human fixes it.
- **Unparseable file, no backup**: every setting falls back to its built-in default and an error is recorded: "config.toml failed to load and every setting below is a DEFAULT, not what's in the file -- ...". Lanes do not start.
- **Unreadable file** (operating-system error): all defaults, and the same error.
- **Merge order** (lowest to highest): built-in default, then the role profile (only for keys the file does not set), then site-manifest values (only for three keys, see below), then whatever the file sets explicitly. An explicit value in the file always wins.
- **Role profiles**: `mode = "editor"` changes nothing; `mode = "base"` sets `sync_enabled = false` and `lane_b_enabled = false` unless the file sets those keys itself. The base profile leaves the out-of-tree popup on.
- **List repair**: if `projects` or `syncthing_folder_ids` is not a list it becomes an empty list; if `ignored_resolve_projects` is not a list it becomes the default list.
- **Site manifest fills three keys** (read from the cached manifest, never the network, at load time):
  - `server_p_unc` from the manifest's `smb_unc`, when the file leaves it absent or blank (the value `"off"` in the file survives).
  - `sftp_chunk_size` and `sftp_concurrency` from the manifest's keys of the same names, only when the file does not contain the key at all (a blank or 0 in the file is a deliberate "drop the flag" and is kept).
  - A manifest value of `""`, `0` or missing is treated as "the server did not say" and never disables anything.
  - Any failure here is silent and falls back to the defaults.
- **Writing one key** (used by the tray's Settings window and by dashboard-asked machine settings): the companion rewrites exactly one top-level `key = value` line and leaves every other line, including comments, byte for byte.
  - Only the top section of the file (above the first `[table]` header) is searched. If the key is absent it is appended at the end of the top section (before any table header, after backing up over blank lines), never inside a table.
  - Values: booleans as `true`/`false`, numbers as written, anything else as a quoted single-line string with backslash and quote escaped.
  - Written to `config.toml.tmp`, restricted to owner-only, then renamed over the real file.
  - After writing, the file is re-read; if the key does not read back as the written value (booleans compared as booleans, others as trimmed strings) the write is reported as failed and the log says: "the setting did NOT take. A [table] header in the file, or a second definition of the same key, is the usual cause; fix the file by hand."
  - Writes are serialised across the whole process.
- **Version constants**: the companion's own version is `0.9.91`. The minimum dashboard version this build needs is `0.7.23`; it is copied into the signed release record as `requires_dashboard`.
- **Neutral rclone remote name**: `ccsync_sftp` is the fallback remote name the installers use when the site manifest names none (the companion's own default for `remote` is blank).

## Configuration validation at startup and on save (source: config.py)

Errors stop all sync lanes and the sequencer from starting. Warnings degrade one feature only. Neither crashes the app.

- Errors:
  - Config load failure (see above, two wordings).
  - `local_root` not a string: "local_root must be a path string, got ... -- nothing syncs until it names this machine's sync root".
  - `local_root` blank: "local_root is blank -- the timeline watcher and both rclone lanes have no tree to work against; set it to this machine's sync root".
  - `local_root` path does not exist: "local_root does not exist: <path>".
  - `remote` blank: "remote is blank -- set it to the rclone remote name from rclone.conf".
  - `remote_root` blank (long message explaining SFTP lands in the home directory, with TrueNAS and Synology examples).
  - `remote_root` not starting with `/`: "remote_root is not absolute: ...".
  - `log_path` present but not a non-blank string.
  - `dashboard_report_interval` not a positive number.
  - Any of these not a positive number: `selection_poll_interval`, `project_rotation_seconds`, `sequencer_idle_seconds`, `selection_fetch_ttl`, `project_roots_ttl`, `dashboard_report_interval_active`, `manifest_refresh_interval`, `media_tree_refresh_interval`, `popup_snooze_seconds`, `resolve_scripting_warning_interval`, `poll_interval`, `transfers`, `scan_interval_up`, `scan_interval_down`, `watch_debounce_seconds`, `sftp_concurrency`, `sftp_connections`, `checkers`, `lane_c_max_folder_concurrency`, `express_debounce_seconds`, `express_max_batch`. Message: "<key> must be a positive number, got ...".
  - `structure_clone_every_n_passes` or `orphan_scan_every_n_passes` negative or not a number.
  - Only when SAVING (the Settings window): a `dashboard_url` that is plain http to a public internet address.
- Warnings:
  - `remote_down_root` set with `remote_down` blank (ignored).
  - `remote_down` naming the same remote as `remote`.
  - `remote_down` set and `remote_down_root` blank (explains that a tunnel serving the tree as its root needs `"/"`).
  - `editor_name` blank (popup destinations get an empty name component; with `require_login = false` the server rejects every report).
  - `active_project` blank (popup fixer suggests the tree root).
  - `syncthing_folder_ids` length differs from `projects`.
  - `dashboard_url` blank: "dashboard_url is blank -- this companion is not pointed at any dashboard, so there is no reporting, no managed sync selection, no upgrade channel and no site manifest...", plus, when `require_login` is on, "-- and require_login is on, so nobody can sign in and NO SYNC LANE WILL EVER START until it is set".
  - `dashboard_url` not starting with `http://` or `https://`.
  - `dashboard_url` set but `dashboard_token` blank.
  - `dashboard_url` plain http on a public address (at startup a warning, not an error), or plain http on the local network or tailnet (a note: "This address is not https. It is fine on your studio network or tailnet."). At startup no DNS lookup is done; a name only DNS could judge is given the local-network note.
  - The public-http sentence shown to an editor: "The dashboard address is plain http on the internet, so CCSync will not send anything to it. Ask your admin for its https address."
  - Any of the four `report_*` switches not a boolean (treated as false).
  - Unknown `mode` (treated as `editor`).
  - `keep_awake_stale_seconds` / `keep_awake_max_hold_seconds` not positive (default used).
  - `drive_reminder_minutes`, `unopened_scan_minutes`, `lane_a_verify_seconds`, `sftp_connections_verify`, `checkers_verify`, `lane_b_idle_recheck_seconds` negative or not a number (default used).
  - Proxy generation on but `ffmpeg_path` blank, or not found on disk or PATH.
  - `library_db_port` not a valid TCP port (1 to 65535).
  - `library_db_password` set while `library_db_host` is blank.
  - Unknown `lane_c_pause_scheme` (treated as `none`).
- Runtime fallbacks used instead of crashing: a non-positive or garbage number falls back to its default with a log line; a "count" knob (0 allowed) falls back to its default when negative; a bad bitrate (anything not a number optionally followed by K or M, or a positive bare number) falls back to `7M`; a non-string or blank `log_path` falls back to `~/.ccsync/companion.log`; a non-string `local_root` is treated as empty.

## Ignored Resolve projects (source: config.py)

- Names in `ignored_resolve_projects` are compared case-insensitively with surrounding and repeated internal whitespace collapsed.
- A project matches if its name equals an entry, or equals an entry followed only by a duplicate number (optional spaces, dashes or underscores, optional brackets): "New Doc 1", "New Doc 2", "Untitled Project (3)". "New Doc Final" and "New Documentary" do not match.
- An ignored project is not reported, never triggers the new-project prompt, and its clips never raise the out-of-tree popup.

## Every configuration key (source: config.py)

Format: key, default, effect. "Template" means the key is written, uncommented, into a new `config.toml`; "commented" means it appears only as a commented-out line; "not in template" means it is only a built-in default.

### Identity, tree and remote

- `editor_name` = `""` (template). Name used to build the popup fixer's suggested destination `B-roll/Editor Added/<editor_name>`; with `require_login = false` it is the identity reports are sent under.
- `local_root` = `""` (template). Absolute path to this machine's copy of the project tree. Required (error if blank, wrong type or missing).
- `canonical_prefix` = `"P:\"` (template). The shared-drive prefix stored in Resolve clip paths, used to detect clips with the wrong prefix. The template tells Mac users to keep `P:\` too.
- `remote` = `""` (template). Name of the rclone remote pointing at the server. Required.
- `remote_root` = `""` (template). Absolute server path of the tree. Required and must start with `/`.
- `remote_down` = `""` (commented). Optional second rclone remote that only downloads use (lane B, b-roll fetch, folder-structure copy). Writes always use `remote`.
- `remote_down_root` = `""` (commented). Tree path on `remote_down`; blank means same as `remote_root`.
- `projects` = `[]` (template). Legacy; pairs positionally with `syncthing_folder_ids` for lane C's folder-ID check only.
- `active_project` = `""` (template). Folder (relative to `local_root`) the popup fixer suggests for media the editor adds.
- `mode` = `"editor"` (template). `editor` or `base`; `base` applies the base profile (above).

### Timing of the core loops

- `poll_interval` = `3` seconds (template). Resolve timeline poll interval.
- `scan_interval_up` = `300` seconds (template). Lane A full-pass interval.
- `scan_interval_down` = `120` seconds (template). Lane B full-pass interval.
- `watch_debounce_seconds` = `10` (template). Lane A file-watcher debounce.
- `selection_poll_interval` = `60` seconds (template). How often the sequencer re-fetches the dashboard's ordered project selection.
- `project_rotation_seconds` = `600` (template). How long the sequencer waits on one project before moving on.
- `sequencer_idle_seconds` = `60` (template). Idle time between full passes once all projects are caught up.
- `lane_b_idle_recheck_seconds` = `600` (commented). A project whose lane B turn ran out with files left gets another turn at once if every other ticked project's last turn (within this many seconds) found nothing. 0 = off.
- `lane_a_verify_seconds` = `7200` (commented). A project with no local change since a clean lane A check is re-checked on the server only this often. 0 = every turn.
- `selection_fetch_ttl` = `30` seconds (template). How long the last selection answer is reused from memory.
- `project_roots_ttl` = `300` seconds (template). How long the per-project destination mapping is reused.

### Lane B safety and trash

- `lane_b_min_age_seconds` = `120` (template). Proxies on the server newer than this are not downloaded yet. 0 = off.
- `lane_b_max_deletes_per_pass` = `50` (commented). Circuit breaker: maximum files one lane B pass may move to trash.
- `lane_b_max_delete_fraction` = `0.25` (commented). Or this share of the local proxy set, whichever is smaller.
- `lane_b_remote_shrink_fraction` = `0.5` (commented). Trip when the server listing shrinks past this share of the previous pass.
- `lane_b_min_free_bytes` = 20 GiB (commented). Lane B pauses below this free space on the sync drive and resumes by itself at twice the floor or on the tray's "Resume proxy download". 0 = off.
- `trash_max_age_days` = `14` (commented). Age after which `.ccsync-trash` batches are pruned. 0 = no age rule.
- `trash_max_bytes` = 50 GiB (commented). Size cap; oldest batches dropped first, newest never by this rule. 0 = no cap. Nothing is pruned while the breaker is tripped.
- `trash_prune_interval_seconds` = `21600` (6 hours) (commented). How often pruning runs.
- `lane_b_enabled` = `true` (commented; the base profile sets false). False = no local proxy mirror.

### Transport tuning (rclone)

Each string set to `""` or number set to `0` removes that rclone flag.

- `transfers` = `4` (template). rclone parallel transfers.
- `sftp_chunk_size` = `"255Ki"` (commented; the site manifest may override when absent).
- `sftp_concurrency` = `64` (commented; site may override when absent).
- `sftp_connections` = `16` (commented).
- `checkers` = `16` (commented).
- `sftp_connections_verify` = `4` and `checkers_verify` = `4` (commented). Used for a lane A run that only re-checks an unchanged project. 0 = use the normal values.
- `rclone_ignore_checksum` = `true` (commented). Skips the post-transfer hash check.
- `order_by_up` = `"modtime,descending"` (commented). Upload newest first.
- `order_by_down` = `"size,ascending"` (commented). Download smallest first.
- `concurrent_lanes` = `true` (commented). Lanes A and B run at the same time.
- `structure_clone_every_n_passes` = `10` (commented). Re-copy the server's empty folder structure every Nth pass. 0 = never.
- `lane_c_pause_scheme` = `"none"` (commented). `none` leaves all selected Syncthing folders unpaused; `rotate` pauses all but the current project.
- `lane_c_max_folder_concurrency` = `2` (commented).
- `orphan_scan_every_n_passes` = `20` (commented). Every Nth pass, report (never delete) leftover `.partial` files on the server. 0 = never.
- `express_upload_enabled` = `true` (commented). A newly settled file is uploaded at once rather than waiting for its project's turn.
- `express_debounce_seconds` = `10.0` (commented). Batching window for express uploads.
- `express_max_batch` = `200` (commented). A bigger burst is left to the periodic pass.
- `lane_a_handoff_enabled` = `true` (commented). Uploads still running when a project's turn ends finish in the background.
- `rclone_path` = `"rclone"` (template).

### Syncthing

- `syncthing_url` = `"http://127.0.0.1:8384"` (template).
- `syncthing_api_key` = `""` (template). Blank = read from Syncthing's own config.xml.
- `syncthing_folder_ids` = `[]` (template). Expected folder ID per entry in `projects`.
- `supervise_syncthing` = `true` (commented). Restart a dead local Syncthing.

### Crash supervision, logging, crash reporting

- `supervise` = `true` (commented). Relaunch the companion after an unrequested death (Windows frozen builds only; see the supervisor section).
- `log_path` = `"~/.ccsync/companion.log"` (template). Rotating log file.
- `log_level` = `"INFO"` (template).
- `crash_reporting` = `false` (template). Opt-in network crash sender; needs `crash_dsn` too.
- `crash_dsn` = `""` (template). Where the network sender sends. No vendor endpoint is built in.

### Dashboard connection and reporting

- `dashboard_url` = `""` (template). The dashboard address. Blank = no reporting, no managed sync selection, no upgrade channel, no site manifest, no "Open dashboard" link; the reporter is not started.
- `dashboard_token` = `""` (template). Shared fleet token, sent as the `X-CCSync-Token` header.
- `report_token` = `""` (template). Per-person fleet token (`cce1.<id>.<secret>`); wins over `dashboard_token`.
- `require_login` = `true` (template). Sync lanes, the sequencer and identity-bearing reports wait until the editor signs in from the tray.
- `dashboard_report_interval` = `60` seconds (template). Report cadence when idle.
- `dashboard_report_interval_active` = `5` seconds (template). Report cadence while a lane is syncing.
- `manifest_refresh_interval` = `300` seconds (template). How often the local media manifest is rebuilt.
- `media_tree_refresh_interval` = `120` seconds (template). How often the Resolve bin tree is rescanned for reporting.
- `loopback_extra_origins` (commented in template only; no built-in default). Extra exact web origins allowed to call the 127.0.0.1:8899 loopback.
- `loopback_dev_origins` (commented in template only; no built-in default). Also accept `http(s)://127.0.0.1|localhost:*`.

### Proxy relink, notifier and generator

- `proxy_relink_enabled` = `true` (template). Repoint a clip's proxy at the synced copy when the stored proxy path is stale.
- `proxy_notify_enabled` = `true` (template). Tell the editor about originals with no proxy.
- `proxy_gen_enabled` = unset (commented). Three states: true, false, or unset meaning "on exactly when `lane_b_enabled` is false". A non-boolean value is logged and treated as unset.
- `ffmpeg_path` = `"ffmpeg"` (template).
- `proxy_scan_interval` = `900` seconds (template). Tree walk for missing proxies.
- `proxy_gen_idle_seconds` = `300` (template). Keyboard/mouse idle time before encoding.
- `proxy_gen_min_age_seconds` = `120` (template). Skip files modified more recently.
- `proxy_gen_max_height` = `1080` (commented). Height ceiling; never upscales.
- `proxy_gen_bitrate` = `"7M"` (commented).
- `proxy_gen_max_failures` = `3` (commented). Attempts per file per session.
- `proxy_gen_free_space_floor_gb` = `20` and `proxy_gen_free_space_floor_pct` = `5` (commented). Free space kept clear, the larger of the two. 0 disables.
- `proxy_gen_stability_seconds` = `5` (commented). Gap between two size/mtime samples. 0 = one sample.
- `proxy_dry_run` = `false` (commented). Report what would be encoded and encode nothing.
- `fixer_dry_run` = `false` (commented). FIX ALL reports copies/relinks and does nothing. Read once at startup.
- `proxy_notify_cooldown_seconds` = `86400` (commented). Minimum gap between identical "no proxy" notices.
- `proxy_gen_skip_while_resolve_running` = `false` (commented).

### B-roll ingest

- `broll_ingest_enabled` = `true` (commented).
- `broll_ingest_idle_seconds` = `300` (commented). Idle gate for "only when idle" batches.
- `broll_ingest_skip_while_resolve` = `true` (commented).
- `broll_ingest_free_space_floor_gb` = `20` (commented).
- `broll_ingest_max_concurrent_ffmpeg` = `2` (commented).
- `broll_ingest_staging_dir` = `""` (commented). Blank = `<local_root>/Assets/B-roll Archive/.ingest`.
- `broll_ingest_staging_retention_days` = `7` (commented). Finished-batch staging is deleted after this. Music ingest reads `music_ingest_staging_retention_days` (not a built-in key) and falls back to this.

### Blackmagic Proxy Generator (BPG)

- `bpg_enabled` = unset (commented). Unset = on where this machine generates proxies and BPG is installed.
- `bpg_path` = `""` (commented). Blank = Resolve's install path (BPG is Resolve.exe with `-pg`).
- `bpg_manage_watch_folders` = `true` (template). Add folders with unproxied BRAW/R3D/CRM to BPG's watch list (additive only, file backed up once).
- `bpg_autostart` = `true` (template). Press Start in BPG's window.
- `bpg_settings_path` = `""` (commented). Blank = under `%APPDATA%\Blackmagic Design`.

### YouTube

- `youtube_import_enabled` = `true` (template). Import downloaded YouTube clips into the open project under Master > Youtube > term.
- `youtube_import_scan_interval` = `60` seconds (template).
- `youtube_import_min_age_seconds` = `120` (template).
- `youtube_import_batch_limit` = `20` (commented). Files per term folder per cycle.
- `youtube_import_max_failures` = `3` (commented).
- `ytdl_local_downloads` = `true` (template). This machine downloads YouTube clips it asked for. False = no yt-dlp is installed or checked at all.
- `ytdlp_path` = `""` (template). Blank = companion-managed yt-dlp under `%LOCALAPPDATA%\ccsync\tools` (macOS `~/Library/Application Support/ccsync/tools`).
- `ytdlp_max_age_days` = `21` (template). Age after which a failed daily update check is reported stale; 0 or less turns self-updating off. Ignored with `ytdlp_path` set.
- `ytdl_cookies_file` = `""` (template). Netscape cookies.txt used only after an anonymous attempt hits a bot check.
- `ytdl_fragment_jobs` = `6` (template). yt-dlp `-N`, clamped 1 to 16.
- `ytdl_player_client`, `ytdl_max_identical_failures` (default 3): mentioned in the version history comment only, not in the built-in defaults or template.

### LUTs, stills, Resolve

- `lut_sync_enabled` = `true` (template). Link Resolve's LUT locations to the shared library.
- `resolve_lut_dir` = `""` (template). Blank = platform default Resolve LUT folder.
- `resolve_factory_luts_extra` = `""` (template). Extra comma-separated factory names never offered by Share LUTs.
- `lut_location_override` = `""` (template). Blank = `P:\Assets\Luts` on Windows, the real local path on macOS.
- `lut_check_interval` = `900` seconds (template).
- `lut_index_repair_enabled` = `true` (template). Re-scan Resolve's LUT list when its log shows a startup miss.
- `resolve_log_override` = `""` (template).
- `stills_sync_enabled` = `true` (template). Point Resolve's gallery at the shared folder.
- `resolve_scripting_warning` = `true` (template). Repeating warning when Resolve's scripting server is dead.
- `resolve_scripting_warning_interval` = `300` seconds (template). Also the delay before the first warning. 0 or less = off.
- `bridge_auto_restart` = `true` (template). Restart the companion when the Resolve it was connected to exits.
- `vp9_guard` = `true` (template). Warn when the open timeline uses VP9 source media.
- `ignored_resolve_projects` = `["Untitled Project", "New Doc"]` (template).
- `library_walk` = `true` (commented). Read clips from Resolve's project library database instead of the scripting API.
- `library_db_host` = `""`, `library_db_port` = `5432`, `library_db_name` = `""`, `library_db_user` = `""`, `library_db_password` = `""` (commented). Overrides for which library to read.

### Power, drives, popups

- `shutdown_warning_enabled` = `true` (template). Windows shutdown screen warning while syncing.
- `keep_awake_while_syncing` = `true` (template). Hold the system idle timer while transferring.
- `keep_awake_stale_seconds` = `180.0` (commented). Same backlog this long = stalled.
- `keep_awake_max_hold_seconds` = `28800.0` (8 hours) (commented). Continuous blocking cap.
- `drive_reminder_minutes` = `30.0` (commented). Reminder cadence for an unplugged external sync drive. 0 = first warning only.
- `unopened_scan_minutes` = `30.0` (commented). Scan of every project in the Resolve libraries for clips only on this computer. 0 = off.
- `sync_enabled` = `true` (commented; base profile sets false). False = no sync lanes.
- `popup_enabled` = `true` (template). Media-outside-tree popup.
- `popup_snooze_seconds` = `300` (template).
- `server_p_unc` = `""` (commented). SMB path for "Grade from server originals". Blank = site manifest's `smb_unc`, else derived; `"off"` disables. Windows only.

### Loopback servers

- `broll_server_enabled` = `true` (template). The 127.0.0.1 loopback that b-roll/music/YouTube pages call.
- `broll_server_port` = `8899` (template).
- `field_server_enabled` = `true` (commented). Field backup page at `http://127.0.0.1:<port>/field`.
- `field_server_port` = `8898` (commented).
- `field_dest_folders` = `[]` (commented). Laptop folders offered as backup destinations.
- `field_pool_folder` = `"FieldBackup"` (commented).
- `field_state_path` = `""`, `field_copies_path` = `""` (commented). Blank = `~/.ccsync`.

### Fleet jobs, Footage Sorter, Timeline Cards

- `jobs_enabled` = `true` (commented). Master switch for taking fleet jobs.
- `jobs_whisper_python` = `""` (commented). Python with faster-whisper. Blank = no whisper capability.
- `jobs_mulcam_pipeline` = `""` (commented). MulticamPipeline checkout. Blank = no whisper capability.
- `jobs_vault_root` = `""`, `jobs_media_root` = `""` (commented). Where the `vault` and `media` roots are on this machine.
- `jobs_pool_root` = `""` (commented). Where the `pool` root (footage dataset) is.
- `sorter_cards_enabled` = `true` (commented). Report camera cards to the Footage Sorter and take `card-ingest` / `drive-copy` jobs.
- `sorter_ledger_enabled` = `true` (commented). Report drives, take `ledger-scan` jobs, send the copies outbox.
- `sorter_ledger_volume_seconds` = `10` (commented). Drive check cadence.
- `ledger_outbox_path` = `""`, `ledger_mirror_path` = `""` (commented). Blank = `~/.ccsync`.
- `card_copier` = `"auto"` (commented). `auto` = TeraCopy on Windows when installed with verify on, else built-in copier; `python` = never TeraCopy.
- `teracopy_path` = `""` (commented).
- `teracopy_allow_unverified` = `false` (commented).
- `jobs_idle_seconds` = `300` (commented). Keyboard/mouse idle time before claiming a job.
- `jobs_skip_while_resolve_running` = `true` (commented).
- `jobs_poll_seconds` = `20` (commented). Job loop tick.
- `jobs_volunteer_minutes` = `30` (commented). Length of the tray's "Take fleet jobs now" lend.
- `cards_agent` = `false` (commented). DORMANT by default: serve Timeline Cards from this machine's Resolve.
- `cards_vault_root` = `""` (commented). Blank = `jobs_vault_root`.

### What this computer reports

- `report_resolve_project` = `true` (template). The open Resolve project's name.
- `report_local_manifest` = `true` (template). The list of media files on this disk.
- `report_media_tree` = `true` (template). The Resolve bin structure.
- `report_input_idle` = `true` (template). Time since the last keyboard or mouse input.
- These four can never be changed remotely by the dashboard (see machine settings).

### Keys read by the code but absent from the built-in defaults and the template

- `report_timeout_full` (default `30.0` seconds, never below the 5 second light timeout). Timeout for a "heavy" report that carries the media manifest and bin tree. Read by the reporter. Undocumented.
- `music_ingest_staging_retention_days` (falls back to `broll_ingest_staging_retention_days`'s default).
- `loopback_extra_origins`, `loopback_dev_origins` (see above).

## Reporting to the dashboard: cadence and sending (source: reporter.py)

- **Off entirely when `dashboard_url` is blank**: no report thread is created, no diagnostics upload is possible.
- **First report** 2 seconds after start.
- **Cadence**: every `dashboard_report_interval` (60 s) normally; every `dashboard_report_interval_active` (5 s) while any sync lane is in the "syncing" state.
- **Light and heavy reports**: on a fast (active) tick the report is "light" (no media manifest, no bin tree, no undo-journal list, no licence block) unless a heavy one has not been attempted for a full `dashboard_report_interval`. Every idle-cadence tick is heavy. The heavy attempt time is recorded before sending, so a heavy report that keeps timing out falls back to the normal cadence instead of retrying every 5 s.
- **Endpoint**: `POST <dashboard_url>/api/v1/report`, JSON body.
- **Headers**: `Content-Type: application/json`; `X-CCSync-Token: <token>` when a token exists (re-read from the live settings on every post, so a token adopted at sign-in is used at once; falls back to the token read at startup); `X-CCSync-Identity: <signed identity token>` when signed in.
- **Timeouts**: 5 s for a light report; `report_timeout_full` (30 s) for a heavy one.
- **Redirects are never followed**: a 3xx answer is treated as a failed report (protects the token headers).
- **Plain http to a public internet address is refused before sending** (see the transport section).
- **No verified identity, no report**: when sign-in is required and nobody is signed in, the cycle is skipped silently (no request is made).
- **Sign-in as a different person** resets the "unchanged section" memory so the new identity gets full sections.
- **Manual triggers**: other parts of the companion (the tray's "Sync now", the loopback server) can trigger a report directly; they count toward the same health record.

## Reporting: every field the companion sends (source: reporter.py, telemetry_policy.py)

Always sent (every tick, light or heavy):

- `editor_name`: the verified signed-in name (or `editor_name` from config when sign-in is not in use).
- `machine`: the computer's network host name.
- `machine_id`: the companion-minted permanent id of this computer (null if none). Re-read after the id is re-minted from Settings.
- `syncthing_device_id`: this machine's own Syncthing device id, re-read at most every 300 s; a failed read keeps the last known id; a changed id is logged as a warning ("this machine's Syncthing device id changed ... reporting the new one").
- `companion_version`: for example `0.9.91`.
- `platform`: `windows`, `macos` or `linux` (see self-update).
- `arch`: `x86_64` (also for `AMD64`/`x64`), `arm64` (also for `aarch64`/`armv8`/`armv8l`), otherwise the raw machine string lowercased, or `unknown`.
- `reported_at`: current UTC time, ISO 8601.
- `lanes`: one entry per sync lane with `name`, `state`, `queued`, `transferring`, `last_error` (cut to 2,000 characters), `last_sync`, `detail` (cut to 500), `current_project` (cut to 512), `bytes_done`, `bytes_total`, `speed_bps`, `eta_seconds`, `transfers` (at most 256, each `name` cut to 512, `project_slug` to 128, `direction` to 16), and, when the lane supplies them, `state_since` and `progress_token` (the token only when the lane is not idle, error or paused).
- `report_optouts`: sorted list of the reporting categories withheld (empty list when none), always sent.

Sent when the corresponding part of the companion supplies it (every tick):

- `completed`: finished-file history records drained from the lanes (at most 200; `name` 512, `direction` 16, `lane` 64, `at` 64 characters). Omitted when empty. A failed post loses that tick's entries.
- `queue` (at most 64 project slugs; a warning is logged when more are cut) and `current_project` (cut to 512): the managed-sync queue and the project being synced now.
- `resolve_project`: the open Resolve project's name or null.
- `mode`: `base` or `editor`.
- `lane_b_via`: `remote` or `remote_down`, only on a machine using the second download route.
- `transport_health`: connection-path and orphaned-upload diagnostics.
- `proxy_coverage`: which originals have no proxy; the per-project map is cut to 64 projects. Omitted when empty.
- `youtube_import`: state of importing downloaded YouTube clips into Resolve. Omitted when empty.
- `sync_guard`: lane B breaker, trash size, sync halt, lane A "skipped, exists" counter, Resolve health and the reporter's own health block. Omitted when empty. Never shed for size.
- `file_moves_applied`: answers to the dashboard's file-move commands. Omitted when empty.
- `resolve_undo_applied`: answers to undo requests. Omitted when empty.
- `capabilities`: what this machine can do (see the capabilities section). Sent whenever available, even when empty, never suppressed.
- `machine_settings`: the settings the dashboard may ask to change, current values, and the last answer (see machine settings). Omitted when empty.
- `broll_ingest`: b-roll ingest batch in progress. Omitted when empty; its absence means "the batch finished".
- `music_ingest`: the same for music. Omitted when empty.

Heavy ticks only:

- `resolve_journals`: list of Resolve undo journals this machine holds (an empty list is sent, meaning "nothing to undo").
- `local_manifest`: the local media manifest per project.
- `media_tree`: the Resolve bin tree.
- `eula`: which licence this computer accepted. Omitted when unavailable.

Reporter health (the `reporter` block that goes inside `sync_guard`; built by the reporter):

- `last_success_at` (ISO UTC), `last_status` (`ok`, `HTTP <code>`, an exception name, or `refused: plain http on the internet`), `consecutive_failures`.

## Reporting: unchanged-section suppression and size limits (source: reporter.py)

- **Unchanged sections are not re-sent**: `local_manifest` and `media_tree` are omitted when they are identical (by digest) to the last version the dashboard accepted less than 600 s ago. After 600 s they are sent again regardless. Failed posts, sections shed for size, withheld sections, and a reply saying the dashboard truncated something all clear this memory so the next heavy report sends in full.
- **Size budget**: a heavy report is kept under 7 MiB (the dashboard refuses bodies over 8 MiB). Sections are shed in this order until it fits, each step logged as a warning:
  1. Per-file lists from manifest projects, lowest priority (last) project first, only as many as needed; each trimmed project is marked `truncated: true`. If the estimate fell short, every project's lists go.
  2. Bin tree clip lists cut to 500 clips per bin.
  3. The per-project proxy-gap map emptied (totals kept, marked `truncated`).
  4. Only the first half of manifest projects kept.
  5. `media_tree`, then `local_manifest`, dropped entirely.
- The lane and status core is never shed.
- **Dashboard truncation**: when the reply carries `truncated`, the companion logs "the dashboard truncated this report: ...".

## Reporting: privacy switches and withholding (source: telemetry_policy.py, reporter.py)

- Four categories, each switchable per computer (`report_*` config keys, default on) and per site (the site manifest's `telemetry` block; only an explicit `false` turns one off; a missing or unreadable manifest means "all on").
- Effective setting = computer AND site. Switching `resolve_project` off also switches `media_tree` off.
- A per-computer key that is present but not a boolean is treated as off.
- Data is always collected; only the report omits it. Withholding never stops sync or any background pass.
- Fields removed per category:
  - `resolve_project`: top-level `resolve_project`; `capabilities.resolve.project`; `sync_guard.resolve_health.open_project`, `.project_open`, `.unopened_out_of_tree`; every `resolve_journals[].project`; and the whole `media_tree`.
  - `resolve_project` also MASKS rather than removes: each `resolve_journals[].id` becomes `withheld:project/<file name>`; each `resolve_undo_applied[].detail` has every curly-quoted project name replaced by `<project>` and journal ids masked (if that fails, the text becomes "(detail withheld: this computer does not report project names)").
  - `local_manifest`: `local_manifest`; `sync_guard.resolve_health.missing_clips`, `.non_canonical_refused`; `sync_guard.sync_conflicts.paths` (the count stays); `sync_guard.stray_projects`; `sync_guard.moved_project_dirs`; `sync_guard.skipped_exists.samples` (counts stay).
  - `media_tree`: `media_tree`.
  - `input_idle`: `capabilities.idle_seconds` (absent means "not idle", so withholding only means less background work is given to this machine).
- An older companion handed a masked journal id cannot map it back, so undo from the dashboard needs a current companion while the site withholds project names (the tray undo still works).
- **Diagnostics redaction helper**: rewrites free text so every path under given roots becomes `<root>/<file>` (case-insensitive, either slash, not matching inside words like `http:`) and every whole-word occurrence of given project names (3 characters or longer) becomes `<project>`.
- The four switches are never in the list of settings the dashboard may change remotely.

## Reporting: health, failures, clock skew (source: reporter.py)

- **Persistent health record** at `<log folder>/state/reporter.json` (normally `~/.ccsync/state/reporter.json`): `last_success_at`, `last_status`, `clock_skew_seconds`. Survives restarts. Written at once on a status change, otherwise at most once a minute while healthy, and on every failure. Written atomically.
- **Failure logging**: the first failure of a streak is logged as a WARNING ("dashboard report failed (<status>, <n> in a row): ..."), repeats at DEBUG; a success re-arms the warning.
- **Rejected credential** (HTTP 401 or 403): re-logged at WARNING every hour; one tray toast per process (re-armed after a success): "Your CCSync credential was rejected by the dashboard - sign in again".
- **Plain http on the internet refused**: status becomes `refused: plain http on the internet`; one tray toast per run: "Not sent: the dashboard address is plain http on the internet. Ask your admin for its https address."
- **Clock skew**: on each success the dashboard's `received_at` is compared with the local clock (positive = this computer ahead). At 300 s or more of disagreement a warning is logged ("this computer's clock is N s ahead of/behind the dashboard's -- lane B's --min-age filter and every timestamp this machine reports are wrong until it is fixed"), at most once an hour. A dashboard that sends no `received_at` leaves the last measurement in place.
- **Skew wording** shared by the tray, sign-in toast and diagnostics: "N seconds" under 90 s, "N minutes" under 90 minutes, else "N hours", followed by "ahead" or "behind".
- **Report reply handling**: the parsed reply is handed to the rest of the companion (upgrade advertisement, commands, job offers, machine-settings asks). A broken consumer cannot stop the loop.

## Diagnostics upload (source: reporter.py)

- `POST <dashboard_url>/api/v1/diagnostics` with `editor_name`, `machine`, `machine_id`, `trigger` (default `button`), `at` (UTC ISO), `text` (cut to 262,144 characters).
- Same token and identity headers as the report; timeout = the heavy report timeout.
- Refused (returns false, nothing sent) when `dashboard_url` is blank or no verified identity exists.
- Logged on success: "diagnostics uploaded to the dashboard (<trigger>, <n> chars)".

## Transport rule: refusing plain http on the public internet (source: transport.py, upgrade.py)

- Every credentialed call to the dashboard (reports, sign-in, site manifest, selection, jobs, update downloads) goes through one shared connection path that (a) never follows redirects and (b) refuses, before any byte is sent, a plain-http request to a public internet address.
- **Address classes**:
  - `https`: any https address (certificate verified against the system trust store; nothing disables that).
  - `loopback`: plain http to `localhost`, `*.localhost`, or a loopback IP.
  - `http_local`: plain http to a private, link-local or Tailscale (100.64.0.0/10) address; a single-label name (for example `truenas`); a name ending `.ts.net`, `.local`, `.lan`, `.internal`, `.home.arpa`; a reserved test name (`.test`, `.example`, `.invalid`, `.localhost`, `example.com/.net/.org`); a name that does not resolve; or a name that resolves to at least one non-public address.
  - `http_public`: plain http to a public IP literal, or to a name every one of whose resolved addresses is public.
  - `invalid`: any other scheme or no host. Never refused on the wire.
- A dotless numeric host (`134744072`, `0x08080808`, octal) is read as the IPv4 address it means, so it cannot slip through as an "intranet name".
- DNS verdicts are cached for 30 seconds (success and failure alike).
- **Refusal**: only `http_public` is refused. The error text is "not sent: <host> is plain http on the public internet; use the dashboard's https address". Logged at most once per host per 10 minutes as "LG-4: refused plain http to public address <host>; nothing was sent".
- **The updater is stricter**: it allows plain http only to hosts that look local by shape alone (no DNS lookup); any other plain-http host is refused for downloads (see below).

## Windows certificate trust fix (source: win_trust.py)

- Windows only, applied once at startup before the first https call: when Python loads the Windows certificate stores ("CA" and "ROOT"), certificates whose expiry date is provably in the past are left out. A certificate whose date cannot be read is kept.
- Effect: an expired cached intermediate certificate in a user's store can no longer make every https report fail with "certificate has expired" while the browser works.
- If the running Python lacks the internal hook, it logs "this Python has no SSLContext._load_windows_store_certs: expired Windows certificates are still trusted (CR-350)" and changes nothing.
- macOS and Linux: does nothing.

## Self-update: offers and how they are shown (source: upgrade.py)

- **Where offers come from**: the dashboard's report reply (and sign-in verify reply) may carry an `upgrade` object. Absent means "nothing to take". The companion does not poll a separate update URL.
- **An offer is usable only when** it has a version, a URL and a 64-character sha256, and its version differs from the running one.
- **"Different, not newer"**: the dashboard offers whatever build is current, so an admin rollback is offered exactly like an upgrade. The wording tells them apart:
  - Tray menu item: "Update available → v<X> (install)" when newer; "Roll back to v<X> (older build, install)" when older; "Switch to v<X> (install)" when the order cannot be told. Followed by " - <first line of release notes>" (cut to 48 characters) when the offer carries notes.
  - Toast, raised once when a new version is first offered: "Update available → v<X>. Use the tray menu to install"; or "Roll back to v<X> offered. That is OLDER than the v<running> you are running. Only install it if your admin asked you to."; or "Switch to v<X>. Use the tray menu to install". With notes: "... What's new: <first line>" (90 characters).
  - Confirmation dialog: title from the site brand ("update" / "roll back" / "switch build"); body "Update to v<X>? The companion will restart itself." / "Roll back to v<X>? That is OLDER than the v<running> on this machine. You would LOSE whatever v<running> fixed. The companion will restart itself." / "Switch to v<X>? You are running v<running>. The companion will restart itself."; button UPDATE / ROLL BACK / SWITCH. Full release notes appended ("What is new in v<X>:"), cut to 1,200 characters.
  - Release notes are cleaned (control characters removed, whitespace collapsed per line).
- **Version ordering**: only plain dotted numbers (an optional leading `v`) are ranked; anything else (for example `0.4.5-hotfix`) is "unknown" and worded neutrally.
- **Offer cleared** when a later reply has no `upgrade` key.
- **Every offer is checked on arrival, before it is shown**. A refused offer is never shown in the tray, is logged once per distinct version and reason ("upgrade: REFUSING the offered build v<X> -- <reason>"), and is remembered as the "standing refusal" for the report.

## Self-update: checks before anything is downloaded (source: upgrade.py, release_pubkey.py, ed25519.py)

In order; any failure refuses the offer:

1. **Offline release signature**. The whole release record is verified with Ed25519 against public keys built into the companion (one key today; several may be trusted during a key change). The dashboard cannot produce a valid signature. Signed fields: `kind`, `platform`, `version`, `filename`, `sha256`, `size_bytes`, `min_version`, `published_at`, `signed_binary`, plus `arch` and `requires_dashboard` when the record carries them non-blank. `url` is not signed. The signed bytes are a fixed prefix `ccsync-release-record-v1` followed by sorted, whitespace-free JSON. Refusal reasons: "this build trusts no release key at all", "signature is not valid base64", "signature is N bytes, not 64", "record is not signable (...)", "no baked release key verifies this record". The verifier is a built-in pure-language Ed25519 implementation (no external crypto library).
2. **Kind must be `companion`**: "the release record for v<X> is kind '<kind>', not a companion build. Only a companion record may be installed over this program".
3. **Platform must match this machine** (`windows`, `macos`, `linux`): "the release record for v<X> is for platform '<p>', and this machine is '<q>'". CPU architecture is not checked here (the dashboard enforces it).
4. **Self-contradictory floor**: a record whose `min_version` is higher than its own version is refused and does not raise the floor: "...says it needs v<min> or newer, which that build is not. The record is malformed and this machine's downgrade floor has NOT been changed".
5. **Downgrade floor**: the highest `min_version` this machine has ever accepted is stored in `~/.ccsync/upgrade_floor.json` and only ever goes up (raised on receipt of any valid offer). An offer below it, or an unrankable version while a floor exists, is refused: "v<X> is below the downgrade floor v<floor> this machine has accepted. Rolling back past the floor is deliberate and manual: delete <path> on this machine (docs/RELEASE.md)". A corrupt floor file counts as no floor. A floor that older builds kept beside a redirected log file is carried forward once.

At download time, additionally:

6. **Same origin**: the download URL must be relative or on the same scheme, host and port as `dashboard_url`. A relative URL starting with `/` is appended to `dashboard_url` (keeping any path prefix); other relative URLs are resolved and must still be on the same origin. Refusals: "the update URL is not on the dashboard's own host", "the update URL resolves off the dashboard's own host", "dashboard_url is not configured on this machine".
7. **Transport**: https is allowed; plain http only to a host that looks local by shape (tailnet, LAN, single-label, local suffixes); the first time per process it logs that the channel is "plain HTTP (tailnet/LAN). Downloads are not confidential and not TLS-authenticated; every build is accepted only on its offline release signature...". Plain http to any other host: "dashboard_url ... is plain HTTP to a PUBLIC host -- refusing to download a companion build over it. Use https." A non-http scheme: "...is not http(s) -- refusing to update from it".
8. **Free space**: at least 200 MB plus the advertised size must be free in the program's folder, else "no-space".

## Self-update: download, swap and hand-off (source: upgrade.py)

- Only possible in the packaged (frozen) build; from source it logs "not a frozen exe (source run) -- self-upgrade skipped".
- Only one install at a time; a second click while one runs does nothing.
- **Download**: `GET` the URL with `X-CCSync-Token` (shared token from config), redirects refused, 600 s timeout, streamed in 256 KiB chunks to `ccsync-companion.new.exe` (Windows) or `ccsync-companion.new` (macOS/Linux) beside the running program. Ceiling: the advertised size, or 300 MiB when no usable size is advertised; exceeding it aborts. A redirect is logged: "REFUSING the update download -- <url> answered with a redirect ... nothing was downloaded and no token was re-sent."
- **Hash check** against the signed sha256; a mismatch deletes the file ("sha256 mismatch on downloaded build -- discarding it").
- **Execute permission** (macOS/Linux only): set to 0755 after the hash check; a failure is logged and the update continues.
- **Swap**: the running program is renamed to `<name>.old`, the download is renamed into its place.
- **Launch**: the new build is started detached (Windows: detached, new process group, no console window; macOS/Linux: new session), with standard streams discarded, PyInstaller's temp-folder variables removed and `PYINSTALLER_RESET_ENVIRONMENT=1`, Resolve-specific Python variables cleaned, and `CCSYNC_REPLACES_PID=<old pid>` so the new build waits for the old one to exit before taking the single-instance slot.
- **Hand-off watch**: the old build waits up to 30 s for the new one to write a "started" marker naming its own pid (or its parent's, for the two-process packaged build). If the new one exits first, everything is rolled back and the old build keeps running ("the new build exited with code N before it reported that it had started -- rolling back rather than standing down"). If it is alive but silent at 30 s, the old one stands down anyway. Without a pid the wait is a fixed 2 s.
- **Rollback** on any failed rename or launch: the new build is moved aside, `.old` is moved back, leftovers deleted. If the rollback itself fails: "ROLLBACK FAILED -- the previous build is at <path>; rename it back to <name> by hand".
- **Success**: logs "v<new> launched; shutting down v<old>" and asks the app to shut down.
- **Failure codes** recorded for the report: `download-failed`, `sha-mismatch`, `no-space`, `refused`, `swap-failed`, `exec-failed`, `crash-looped`.

## Self-update: retry back-off and give-up (source: upgrade.py)

- Failed attempts at a version are counted in `~/.ccsync/state/upgrade_attempts.json` (survives restarts; deleting it restarts the retries).
- Back-off after consecutive failures: 10 minutes, then 1 hour, then 6 hours for every later failure. A clock that went backwards counts as "due".
- After 8 failures of the same version the machine stops trying that version on the unattended paths (automatic update and admin push). A click in the tray is not gated by this.
- A different target version resets the count. Coming up on the target version clears the count.

## Self-update: crash-loop detection and automatic revert (source: upgrade.py)

- **Start record** at `~/.ccsync/state/last_version.json` (`version`, `previous_version`, `starts`, `first_start_at`, `last_clean_shutdown`), plus a legacy one-line `last_version.txt` written for older builds.
- Each start of the same version within 10 minutes of the first, without a clean shutdown in between, increments `starts`. A clean shutdown, or a start more than 10 minutes after the first, resets it to 1.
- **"Update complete"**: the first start on a version different from the recorded one (not a first-ever run) is flagged as "upgraded" (the app uses this for its toast).
- **Crash loop** = 3 starts of the same version within 10 minutes with no clean shutdown.
- **Automatic revert** on a crash loop: restore `<name>.old` and launch it. Refused (and logged for a human) when: running from source ("this is a source run, so there is no previous build to restore"); no `.old` ("there is no rollback copy at <path>"); the previous version is unknown ("...so it will not be restored automatically"); the previous version is below the downgrade floor ("...so the crash loop needs a human"); `.old` could not be moved back; the restored build could not be launched or exits within 2 s.
- Before launching the restored build the start record is rewritten for it, and the fled version is recorded: `reverted_from`, and the version is added to a `crash_looped` list (last 8 kept) and marked as an exhausted version (8 attempts, `crash-looped`), so neither automatic update nor an admin push reinstalls it. A newly published version is a new question and is tried.
- Logged: "v<X> has restarted 3 times in under 10 minutes, so this machine has restored v<Y> and is standing down".
- `reverted_from` is cleared after the first accepted report; the restored build can announce the revert once (tracked by `reverted_announced`). The `crash_looped` mark is cleared only when the machine comes up running that version (for example a person installed it by hand).
- **Rollback copy retention**: `<name>.old` is kept until this build has both had a report accepted by the dashboard AND been up 10 minutes, or has been up 60 minutes, checked every 30 s. If the process shuts down first, the copy survives to the next start. Deletion retries 3 times one second apart, then waits for the next start.
- **State-write failures**: every failed write of these records is logged as a warning ("could not write <path> (failure N this run) -- the crash-loop counter cannot be kept on this machine") and counted.

## Self-update: what is reported (source: upgrade.py)

The `sync_guard.upgrade` block, always sent (all-zero when nothing has failed):

- `version` (target of failed attempts), `attempts`, `last_error` (one of the failure codes), `last_attempt_at` (UTC ISO), `reverted_from`, `starts_this_version`, `refused_version`, `refused_reason`, `refused_at`, `state_write_failures`.
- The standing refusal clears itself when the machine is now running the refused version, or when a reply carries no `upgrade` key and no `upgrade_none_reason` (the dashboard saying there is nothing to take). A reply with `upgrade_none_reason` (retracted package, needs newer dashboard, wrong arch, unknown platform) keeps it.

## Self-restart without an update (source: upgrade.py)

- The companion can relaunch its own current build (used after the Resolve it was connected to exits, so the scripting link starts clean): same detached launch and 30 s hand-off watch as an update, no download or swap. Not possible from source ("restart the companion by hand to refresh its Resolve link"). If the replacement dies first, the current instance keeps running.

## Fleet jobs: how work reaches this machine (source: jobs_runner.py)

- **Offers ride the report reply**: `commands.jobs` may carry `offered` (job ids this machine may claim; first 16 kept), `cancel` (ids an admin asked to stop), `forced` (ids an admin marked "run now"; first 16), and `queue` (`queued`, `running`, `pinned`, `oldest_age_s`). An unreadable block is ignored. A new offer or forced id wakes the job loop at once.
- **Claiming is the decision**: `POST <dashboard_url>/api/v1/jobs/claim` with `machine` (host name), `capabilities` (the full capabilities section), `kinds` (the kinds this machine can run now) and, for a forced claim, `ids` (only those ids). The dashboard does a compare-and-set, so two machines never get the same job. 20 s timeout. Headers: `X-CCSync-Token` (only the `dashboard_token` key, re-read per call), `X-CCSync-Identity`.
- **Claim outcomes**: 200 with a `job` = run it; anything else = nothing claimed, offers cleared until the next reply. A network failure is logged as "jobs: could not reach the dashboard to claim (...); waiting for the next offer" (no traceback). HTTP 401/403 marks the machine's fleet credential as refused (see below).
- **One job at a time**: the loop never claims while it holds a job. Exception: drive scans (`ledger-scan`) run on their own lane, so a card copy can be claimed while a scan runs; only one scan at a time.
- **Loop cadence**: every `jobs_poll_seconds` (20 s, at least 2 s). When the dashboard reports an empty queue (nothing queued or running) and nothing is offered, the wait becomes 4 times longer, at most 120 s. A missing queue depth (older dashboard) keeps the base cadence. A deep queue never lengthens the wait.
- **Kinds this machine can run** (sent with every claim, derived from capabilities):
  - `whisper` when the whisper set-up is configured and present.
  - `proxy-480p`, `audio-extract`, `peaks` when both ffmpeg and ffprobe are available.
  - `card-ingest`, `drive-copy` when the Footage Sorter card feature is enabled.
  - `ledger-scan` when the ledger feature is enabled and no scan is already running.
  - Narrowed to the machine's own allow-list (`job_kinds` in the capabilities section) when one is set; empty means every kind.
- **A claimed kind this build cannot run** is handed straight back, not retryable: "this companion has no runner for '<kind>' jobs".

## Fleet jobs: the gate (when this machine will claim) (source: jobs_runner.py)

Checked in this order; the first that applies wins. The tray and Settings show the sentence.

1. `disabled` (`jobs_enabled = false`): "Fleet jobs are switched off on this computer."
2. `no_dashboard` (no `dashboard_url` or no `dashboard_token`): "This computer is not signed in to the dashboard, so the fleet has no way to give it work."
3. `halted` (fleet sync halt, or the halt check failed): "Your admin has stopped syncing for the whole fleet, so this computer is not taking work of any kind."
4. `running` (already holding a job): "This computer is running a fleet job."
5. `no_capability` (no runnable kind): "This computer is not set up for any of the kinds of work the fleet queues." plus either "It is set to take only: <kinds>." or "There is no whisper set-up here, and no ffmpeg for the media jobs."
6. `local_work` (the editor's own b-roll/music indexing or proxy work is using the machine, or that check failed): "This computer is busy with your own work, so it is not taking fleet work." plus the specific reason.
7. Unless the person has volunteered the machine:
   - `user_active` (keyboard/mouse idle less than `jobs_idle_seconds`, or idle time unknown): "Somebody is at this computer, so it is not taking fleet work. It waits for <N minutes> of quiet."
   - `resolve_open` (with `jobs_skip_while_resolve_running` on, Resolve running or the check failed): "Resolve is open here, so this computer is not taking fleet work."
   - Either of these is bypassed for an offered job the admin marked forced: only those ids are claimed ("jobs: claiming forced job #N with somebody at the keyboard").
8. `nothing_offered`: "This computer is ready for fleet work. The dashboard has not offered it any."
9. `ready`: "This computer is ready for fleet work."
- While running a forced job the state is `forced`: "Your admin asked this computer to run a fleet job now."
- A forced or volunteer override never bypasses steps 1 to 6.
- **Credential refused** (the dashboard answered 401/403 to a claim, heartbeat or result): the gate reports "not taking work" and adds "This computer's fleet work is not being accepted right now: ask the studio to check this account." Cleared by the next call that gets through.
- **Running jobs are not stopped when the person comes back** (only no new job is claimed).

## Fleet jobs: volunteering (source: jobs_runner.py)

- The person at the machine can lend it to the fleet for `jobs_volunteer_minutes` (30) from the tray. It is a timer, not a switch: it expires on its own. 0 turns it off at once.
- While volunteering, the idle and Resolve gates are skipped. The deadline is reported as `capabilities.volunteer_until` (UTC ISO) and disappears when the timer runs out.
- Logged: "jobs: volunteering for the next N minutes (until <time>)", "jobs: the volunteer window has run out -- back to the idle gate", "jobs: no longer volunteering -- back to the idle gate".
- A job started this way records "You lent this computer to the fleet, so it took this job while you are here." An admin-forced one records "Your admin asked this computer to run this job now, without waiting for you to step away."

## Fleet jobs: while a job runs (source: jobs_runner.py)

- **Heartbeat**: `POST /api/v1/jobs/<id>/heartbeat` with `machine`, optional `progress` (0 to 1; omitted when unknown, never sent as 0 by the whisper parser), and extra fields for card copies (`done`, `of`, `bytes`). Every 30 s (the dashboard's lease is 300 s). Whisper also beats early when progress has moved at least 1% and the last beat is at least 5 s old.
- A heartbeat that cannot be delivered (network) is ignored ("a heartbeat for job #N did not get through -- carrying on"). HTTP 410 means the job is no longer this machine's: stop. HTTP 401/403: stop and mark the credential refused.
- **Stopping a running job** happens on: an admin cancel (the id in `commands.jobs.cancel`), a stop from the person at this machine, a lost lease (410), a fleet halt, or the companion shutting down. The child process and everything it spawned are killed; a half-written `.partial` is discarded.
- **Stop from the tray**: puts the id on the cancel list; returns at once. A local stop survives later report replies until the result is posted; at most 16 local stops are remembered; the admin's cancels are listed first so they are never crowded out.
- **Cancelled jobs are never retried** (posted as `cancelled`, not retryable).
- **Result**: `POST /api/v1/jobs/<id>/result` with `machine`, `ok`, `retryable`, `error` (cut to 2,000 characters), `result`. 401/403 is logged as an error and marks the credential refused; other 4xx/5xx are logged; a network failure is logged and left to the lease expiry.
- **Recent jobs**: the last 10 finished jobs (`id`, `kind`, `rel_path`, outcome `done`/`failed`/`cancelled`, `error` cut to 300 characters, `finished_at`) are kept in `~/.ccsync/state/jobs_recent.json` and shown to the editor. Recorded before the result is sent.
- **Status snapshot** for the tray and diagnostics: state, offered ids, queue depth, volunteer deadline, forced ids, gate (`taking_work` + sentence), credential refusal code, current job (`id`, `kind`, `rel_path`, `started_at`, `forced_reason`), recent jobs.

## Fleet jobs: the `whisper` kind (source: jobs_runner.py)

- Runs `<jobs_whisper_python> <jobs_mulcam_pipeline>/pipeline.py transcribe --folder <folder> --root <episode root> [--speakers]`.
- Inputs: `root` (default `vault`), `rel_path` (the folder), optional `episode_rel` (default: the folder's parent), optional `speakers`.
- Refused if either config path is blank: "this computer has no whisper venv or MulticamPipeline checkout configured (jobs_whisper_python / jobs_mulcam_pipeline)".
- The child runs in its own process group with no console window (Windows). Its output is read live; the last 2,000 lines are held and the last 4,000 characters go back with the result.
- **Progress** parsed from exactly three line shapes: "N media file(s), M already transcribed, K to do" (sets the total to K), "[i/N] ..." (start of file i), "    a s / b s" (position within the file), and "done: N transcribed" (100%). A run with 0 to do reports 100% on success.
- **Success result**: `seconds`, `realtime` (the pipeline's own "Nx realtime" figure, or null), `files` (up to 200 `Clips/*/<stem>_words.json` paths relative to the episode), `output`. Tray toast: "Finished a transcription job for the fleet (Ns)."
- **Failure**: "pipeline.py transcribe exited N", "could not start the transcription: ...", "the lease was lost", "a fleet halt stopped this job", "this computer is shutting down", or `cancelled`. Retryable unless cancelled.

## Fleet jobs: Timeline Cards media kinds (source: jobs_media.py, jobs_runner.py)

- Three kinds, run inside the companion: `audio-extract`, `proxy-480p`, `peaks`.
- Inputs: `root` (default `media`), `rel_path` (source file), `out_root` (default = `root`), `out_rel` (required: "a media job must name the directory its output goes in (out_root + out_rel) -- nothing here guesses where a cache belongs in somebody's vault"), optional `out_stem` (default: the source file's own name without extension).
- Source missing on this machine: retryable failure "the source media is not here: <path>".
- **Already made**: a finished output whose modification time is not older than the source's is reused and reported as `skipped`.
- **audio-extract**: if a fresh `<stem>.m4a` or `<stem>.ogg` exists, skip. No audio stream: not retryable "no audio track". AAC source: stream-copied to `<stem>.m4a` (`-vn -sn -dn -c:a copy -movflags +faststart -f ipod`); the copy is kept only if ffmpeg succeeded and its audio duration is within 0.05 s of the source's; otherwise it is discarded and the audio is re-encoded to `<stem>.ogg` (mono, Opus 64 kbit/s VBR). 30 minute ceiling.
- **proxy-480p**: `<stem>.480p.mp4`. No video stream: not retryable "no video track". Picture capped at 480 lines, never upscaled, even width; keyframe every second (GOP = source frame rate rounded, default 30); H.264 with NVIDIA `h264_nvenc` preset p4 at constant quality 26 when this machine reported NVENC, otherwise `libx264` veryfast CRF 26; yuv420p; AAC stereo 96 kbit/s; fast-start MP4. 60 minute ceiling. A proxy whose audio length differs from the source by more than 0.05 s is logged as a warning, not a failure.
- **peaks**: `<stem>.peaks`. Audio decoded to mono 8 kHz 16-bit and reduced to 200 bins a second; file = `PK`, rate byte (200), `0`, then one byte per bin (peak scaled to 0-255). A fresh file whose rate byte is not 200 is remade. No audio (ffmpeg's "does not contain any stream" and no audio codec), or no samples at all: not retryable. 30 minute ceiling. Decoded in a streaming fashion, so memory stays small for long recordings.
- **Write discipline**: every output is written as `<final>.partial` (excluded from sync) and renamed into place only if no fresh finished file appeared meanwhile; if one did, ours is discarded and the existing one is reported ("already exists and is current -- discarding the one just made rather than overwriting it"). Two writers in this process on one output: "another writer on this machine already has <name>.partial -- leaving it to them". A stopped or failed run discards its `.partial`. If the final rename fails, the finished `.partial` is kept: "could not put the finished file in place (...) -- it is still there as <name>.partial".
- **ffmpeg runs** with no console window and below-normal priority (Windows), stdin closed, every pipe drained. Progress from ffmpeg's `-progress` stream, published at most once a second as a fraction of the source duration (unknown duration = no fraction). Stop checks every 0.5 s; a killed ffmpeg is waited for at most 5 s, then left to the operating system ("...Its output stays a .partial and is never published.").
- Stop reasons: cancelled, "the lease was lost", "a fleet halt stopped this job", "this computer is shutting down", "ffmpeg did not finish within Ns", "could not start ffmpeg: ...", "the decode failed: ...", "the decode output could not be read to the end".
- ffprobe is the sibling of whatever ffmpeg this machine resolved (including the companion-installed copy); probes time out after 120 s.
- **Result**: `files` (paths relative to `out_root`, prefixed with `out_rel`), `out_root`, `seconds`, `skipped`, and `realtime` (media seconds divided by elapsed) when meaningful.

## Fleet jobs: Footage Sorter copy kinds (source: jobs_runner.py)

- Kinds `card-ingest` and `drive-copy` (copier lives outside this section's files).
- First fetches the copy list: `GET <dashboard_url>/sorter/agent/ingest/<id>` (60 s timeout). 404/409 = not retryable ("the sorter has no copy list for this job (HTTP N)"); other errors retryable.
- While copying: heartbeat every 30 s with progress fraction plus `{done, of, bytes}`; for `card-ingest` also `POST /sorter/agent/ingest/<id>/progress` every 2 s (best effort).
- Stops on cancel, lost lease, halt, shutdown.
- **Receipt**: `POST /sorter/agent/ingest/<id>/receipt` with `copied`, `skipped`, `conflicts`, `failed`, `copier`, and `final: false` when the job stopped early (not cancelled). Up to 4 tries, 3 s apart; 404/409/401/403 are not retried.
- Receipt not delivered: the local-drive copies it lists are appended to the ledger outbox (when the ledger feature is on), and the job is posted as a retryable failure "the copy finished but the receipt could not be delivered to the dashboard".
- Result posted to the job row is counts only (`copied`, `skipped`, `conflicts`, `failed`, `seconds`, `copier`, `receipt`). A job that ran is a success even if some files were skipped, conflicted or failed.

## Fleet jobs: the drive scan kind (source: jobs_runner.py)

- Kind `ledger-scan`, run on its own lane (does not block claiming other jobs); one at a time; a second claim during a scan is handed back retryable: "a drive scan is already running on this computer".
- Drive identified by `serial` or `volumeId` (`vol:<serial>`).
- Stops on cancel, lost lease, halt, shutdown, or "the drive is being copied from" (a copy is using that drive).
- Heartbeat every 30 s without progress.
- Result: `files`, `bytes`, `chunks`, `complete`, `seconds`. An incomplete scan is retryable unless cancelled or its reason mentions the drive being gone, copied from, unreadable, the system drive, or "no longer current". A finished scan whose finish could not be delivered is a retryable failure.

## Fleet jobs: where a job's paths land (source: job_paths.py)

- Jobs never carry absolute paths, only (root name, relative path) pairs.
- Four roots: `tree` = `local_root`; `vault` = `jobs_vault_root`; `media` = `jobs_media_root`; `pool` = `jobs_pool_root`. A root counts only if configured AND currently exists on disk (an unplugged drive is not a root).
- The present roots are reported as `mounts` in the capabilities section.
- Refusals (each becomes the job's failure text):
  - Unknown or missing root: "this machine has no <name> root configured or reachable (it has: ...)" (retryable elsewhere).
  - Empty path: "the job named no path inside the root".
  - Control character: not retryable.
  - Absolute path (leading `/`, drive letter, or OS-absolute): "a job's path must be RELATIVE to its root, and ... is absolute ...".
  - Path that climbs out of the root: "... climbs out of the <name> root".
  - Unresolvable path: retryable only for an operating-system error.
- **Output names** (`out_stem`): empty, `.`/`..`, containing `/` or a control character = not retryable anywhere. Containing `\` or `:` = refused on Windows only, retryable (a Mac or the server can write it).

## What this machine can do: the capabilities report section (source: capabilities.py)

Sent on every report as `capabilities`. The hardware half is reassembled at most every 45 s; the idle time, Resolve block, Timeline Cards block, volunteer deadline and job gate are fresh on every report.

- `gpu_present`, `gpu_name`, `gpu_vram_gb`: from the NVIDIA GPU probe (the same one the b-roll indexer uses).
- `nvenc`: true if this machine's ffmpeg lists `h264_nvenc` or `hevc_nvenc` (asked once per binary).
- `ffmpeg`, `ffprobe`: whether each runs (`-version`), success cached 300 s.
- `whisper` and `whisper_detail`: ready only when both `jobs_whisper_python` and `jobs_mulcam_pipeline` are set and exist and `pipeline.py` exists in the checkout. Reasons: "jobs_whisper_python and jobs_mulcam_pipeline are not both set in this computer's config", "jobs_whisper_python does not exist here: <path>", "jobs_mulcam_pipeline does not exist here: <path>", "there is no pipeline.py under <path>".
- `claude`: true when the environment variable `ANTHROPIC_API_KEY` is set or a `claude` program is on PATH. Advisory only; nothing schedules on it.
- `mounts`: the job roots present here (`tree`, `vault`, `media`, `pool`).
- `sorter_cards`, `sorter_ledger`: whether the Footage Sorter card feature and ledger feature are enabled.
- `teracopy`, `teracopy_verify`: TeraCopy installed, and its verify option on.
- `cpu_count`; `load` (one-minute load average; null on Windows).
- `companion_version`.
- `jobs_enabled`, `jobs_idle_seconds`.
- `job_kinds`: this machine's allow-list from the config key `jobs_kinds` (not in the built-in defaults; a list or a comma/semicolon-separated string). Empty = every kind. Unknown names are dropped with a warning ("...which is not a job kind this build knows ... -- ignoring it"); a non-list is ignored with a warning. Known kinds: `whisper`, `proxy-480p`, `audio-extract`, `peaks`, `card-ingest`, `drive-copy`, `ledger-scan`. `conform` and `resolve-edit` are deliberately not kinds.
- `idle_seconds`: seconds since the last keyboard or mouse input, or null when it cannot be told. Null when the `input_idle` report switch is off, and also whenever `jobs_enabled` is false.
- `resolve`: `running` (process check only, true when the check fails) and `project` (the name the watcher last saw; blanked when `resolve_project` is withheld). Never calls Resolve's scripting API.
- `cards_agent`: `connected`, `state` (default `disabled`), `timeline`, `version`, `since`, and when the role supplies them `detail`, `gate_state`, `last_poll_at`, `last_http_status`.
- `volunteer_until`: the volunteer deadline or null.
- `jobs_gate`: `taking_work`, `reason`, and `detail` when present; omitted when the job runner cannot answer.

## Keyboard and mouse idle detection (source: idle.py)

- Answers "seconds since the last keyboard or mouse input". When it cannot tell, it answers nothing, and every user treats that as "the person is here".
- **Windows**: the system's last-input time against the system tick counter, computed so the 49.7-day counter wrap never produces a false "idle for weeks". Only sees the session the companion runs in (a second user's session or a disconnected/RDP session is not seen).
- **macOS**: runs `/usr/sbin/ioreg -c IOHIDSystem -d 1 -w 0` (10 s timeout) and reads `HIDIdleTime`.
- **Linux and anything else**: always "cannot tell", so idle-gated work never runs.
- Cannot see an unattended render: a Resolve render with nobody at the keyboard counts as idle.

## This computer's permanent id (source: machine.py)

- On first need, the companion creates `~/.ccsync/machine.json` holding a random id (`machine_id`, a UUID), `version` 1 and `created_at`. It is reported with every report so the dashboard can recognise the same computer after a host-name change. It is not a credential and not derived from hardware.
- A missing file is created; a file that exists but cannot be read is NOT replaced (warning: "could not read <path> -- this machine reports no id this run (NOT re-minting: a new id reads as a new computer)"), and the machine reports no id.
- If the file cannot be written, no id is reported ("could not write <path> -- this machine reports no id").
- **Repair** (from a button in Settings): moves the unreadable file aside as `machine.json.unreadable-<epoch seconds>` and creates a new id. If the file has become readable, its id is kept. Reports pick up the new id without a restart.

## Fleet-job settings the dashboard may ask to change (source: machine_settings.py)

- The dashboard's report reply may carry `commands.machine_settings` = `{id, set}`. It is re-sent on every reply until answered.
- Only two keys may be asked for: `jobs_enabled` and `jobs_kinds`. Any other key (including `mode`, wired/remote) refuses the whole request.
- Validation and refusals:
  - "this computer does not take <key> from the dashboard"
  - "the request named nothing to change"
  - "jobs_enabled must be true or false"
  - "jobs_kinds must be a list of kinds of work"
  - "this computer does not know those kinds of work" (a non-empty list naming only unknown kinds)
- `jobs_kinds`: unknown names dropped; an empty list or a list of every known kind is written as `""` (every kind); otherwise written as a comma-separated list in the built-in kind order.
- Malformed commands (not an object, no id, id over 64 characters, `set` not an object) are ignored and logged.
- Writes go to `config.toml` one key at a time through the same one-line writer as the Settings window. Answer states: `applied`, `refused`, or `failed` ("could not save config.toml").
- **Nothing takes effect until the companion next starts.** Nothing restarts automatically.
- **Idempotent**: answers are kept by id (last 16) in `~/.ccsync/state/machine_settings_request.json` and in memory; a re-sent `applied` or `refused` id is answered from the record without writing; a `failed` one is retried only after 300 s.
- **Report section `machine_settings`** (every report): `accepts` (`["jobs_enabled","jobs_kinds"]`), `jobs_volunteer_minutes`, `drive_reminder_minutes`, `youtube` (only when the site has YouTube downloads enabled: `downloads`, `signin_enabled`, `terms_accepted`, `signin` status word; no cookies or reasons), `pending_restart` (which of `jobs_enabled`, `jobs_kinds`, `jobs_volunteer_minutes`, `drive_reminder_minutes` differ between `config.toml` on disk and the running values; kinds compared as sets; omitted when the file cannot be read or parsed), `applied` (the last answer: `id`, `state`, `detail` up to 255 characters, `at`).
- **Tray balloon** after applying: "<Who> asked this computer to stop taking fleet work / take fleet work again / take every kind of fleet work / take only these kinds of fleet work: <labels>. It takes effect the next time CCSync starts." (joined with "and"; "Your administrator" when no name is given; "<Who> changed this computer's fleet work settings. ..." when nothing specific).

## Signing in and which credential is presented (source: identity.py)

- **Sign-in** (from the tray): `POST <dashboard_url>/api/v1/verify` with `username`, `password`, `companion_version`, `platform`, `arch`, `machine` (host name). No auth headers. 15 s timeout. Redirects refused; plain http on the public internet refused.
- Refused locally when `dashboard_url` is blank: "dashboard_url is not configured -- cannot sign in".
- **Messages shown on failure**: the dashboard's own `detail` sentence when present; otherwise 401 "invalid username or password", 403 "this account is not allowed to sync -- ask an admin to add it to the 'editors' group on the NAS", 429 "too many sign-in attempts -- try again shortly", 503 "sign-in is not available on this server right now -- try again shortly", other "sign-in failed (HTTP N)". Public plain http: "Not sent: the dashboard address is plain http on the internet. Ask your admin for its https address." Network errors show the raw error text.
- **Success** stores `~/.ccsync/identity.json` (owner-only, written atomically): `username`, `token` (signed identity token), `role`, `report_token` (shared fleet token from the reply, or the previous one if the reply has none), `editor_report_token` (preserved from before), `verified_at`.
- A reply whose token cannot be parsed or has expired changes nothing and shows: "The server's sign-in reply couldn't be used. If this keeps happening, check this computer's clock is correct, then <diagnostics instruction>."
- **Token validity**: the token must look like `v2.identity.<base64 user>.<expiry>.<signature>` with a non-empty user and an expiry in the future. Current dashboards issue tokens that effectively never expire (a century out); older ones do. The signature is only checked by the dashboard.
- **Role** (`base` or `editor`) returned by the dashboard is stored and shown in diagnostics only; it does not decide whether the machine syncs.
- **Upgrade offer on sign-in**: the verify reply's `upgrade` and `upgrade_none_reason` are passed to the updater.
- **Sign-out**: forgets the identity and deletes `identity.json` (including any per-person token stored there).
- **Credential precedence** (the one presented as `X-CCSync-Token`, published at startup and after every sign-in): per-person token in `identity.json`, then `report_token` in `config.toml`, then the shared token captured at the last sign-in, then `dashboard_token` in `config.toml`. Logged: "using the report token from <source>".

## Site manifest (source: site.py)

- `GET <dashboard_url>/api/v1/site`, unauthenticated, 5 s timeout, redirects refused. Any failure (including 404 from an older dashboard) returns nothing and is logged only at debug level.
- Accepted only with `schema` 1 or higher. Fields kept: strings `org_name`, `org_short`, `product_name`, `support_contact`, `brand_logo`, `tree_name`, `canonical_prefix`, `remote_root`, `smb_unc`, `sftp_host`, `rclone_remote`, `nas_syncthing_id`, `dashboard_url`, `nas_kind`, `sftp_chunk_size`, `sftp_shell_type`, `sftp_hostkey`, `release_feed_base`; lists `template_folders`, `shared_asset_folders`; numbers `sftp_port` (default 22), `sftp_concurrency` (default 0 = not said).
- **Feature flags** (`features`): `youtube_download`, `youtube_unblock`, `auto_update`. On only when the server sends a real JSON `true`; anything else, a missing block, a missing cache or an unknown flag is off.
- **Reporting switches** (`telemetry`): `resolve_project`, `local_manifest`, `media_tree`, `input_idle`. Off only on a real JSON `false`.
- **Cache**: `~/.ccsync/state/site.json` (atomic write, stamped `_fetched_at`). Everything reads the cache, never the network, so an offline start works. A refresh writes the cache on success and otherwise returns the old cache. Who fetches it: the installers and wizard at install time, and any caller of the refresh function.
- **Branding used by tray and dialogs**:
  - Notification and dialog titles: "<org short name or product name>: <suffix>".
  - Product name: from the manifest, else "CC Sync".
  - Support contact: from the manifest, else "support@thecreatorsclub.co".
  - "the <org short> server" or "the server".
  - "your <org name> drive" or "your studio drive" (capitalised variant "Your ...").
  - `brand_logo`: a built-in asset name or a path; blank means the product's own mark.
  - The cache is re-parsed only when its file changes.

## Crash reports written locally (source: crash_report.py)

- **Always on, local only**: every unhandled exception in the main thread or any background thread writes one JSON file to `~/.ccsync/crashes/` (beside the log folder if `log_path` is redirected). `KeyboardInterrupt` and normal exits are not crashes. The interpreter's own error output still happens afterwards.
- **File name**: `<UTC stamp>-<thread name>.json`; a second crash in the same second on the same thread gets `~01`, `~02` and so on (up to 99). Owner-only permissions (0600), created exclusively.
- **Contents**: `schema` 1, `when` (UTC), `version`, `thread`, `frozen` (packaged build or source run), `platform` (system, release, machine, Python version), `exception` (`type`, `message`, `traceback`), and `log_tail` (the last 200 lines of `companion.log`, read from at most the last 256,000 bytes).
- **Redaction** applied to the message, traceback and log tail: values after keys like `token`, `password`, `passwd`, `secret`, `api_key`/`apikey`, `dsn`, `pw` (including suffixed forms like `TRUENAS_PW`, `..._SECRET_PREVIOUS`) become `<redacted>`; `user:password@` in URLs becomes `<redacted>@`; `Bearer <token>` becomes `Bearer <redacted>`. Best effort.
- **Retention**: at most 20 crash files; the oldest are deleted.
- Logged: "unhandled exception in <thread> -- crash report written to <path>". At startup, if files remain from earlier runs: "<n> crash report(s) from an earlier run are in <dir> (newest: <name>)".
- **Report summary**: `{count, newest}` is available for the `sync_guard.crashes` report block, rescanned at most once a minute (immediately after a new crash).
- **Diagnostics list**: the newest 3 crash files with `name`, `when`, `thread`, `type` (`<unreadable>` if the file cannot be parsed).
- **Opt-in network sender**: only when `crash_reporting = true` AND `crash_dsn` is set AND the optional Sentry library is importable (it is not in the packaged build). Then each crash is also sent to that address, with release `ccsync-companion@<version>`, no personal data, no performance tracing, environment `frozen` or `source`. Logs: "crash_reporting is on but sentry_sdk is not installed (the frozen build does not ship it) -- crash files only", "crash reporting: sending to the configured DSN (opt-in)", or "...sentry_sdk.init failed -- crash files only". DORMANT in every shipped build.

## Native crash capture and unclean-exit detection (source: crash_report.py)

- **Native dump**: at startup (after the single-instance lock is taken) the companion turns on Python's fault handler, writing the stack of every thread to `~/.ccsync/crashes/native.log` if the process dies on a fatal signal (for example an abort). The file is deleted at startup when over 512,000 bytes.
- **Run marker**: `~/.ccsync/crashes/running.marker` records `pid`, `version`, `started`, `frozen`, `fresh_build` (first start of a build this machine had not run before) and `booted: false`.
  - Set to `booted: true` once startup completes.
  - Stamped `exiting: true` when the interpreter exits normally (sys.exit, an uncaught error, a startup failure), but kept.
  - Deleted at the very start of a deliberate shutdown, only if it names this process.
- **Unclean exit report**: at the next start, a leftover marker naming a process that is no longer alive produces a crash file of type `UncleanExit`, thread `process`, message "a companion (pid N, version V, started T) stopped without ever starting a shutdown" (plus " -- the supervisor relaunched it at <when> (exit code C, relaunch K of 3 this hour)" when relaunched), traceback = the last 120 lines of `native.log`, or a fixed note pointing at the Windows Event Log when there is none; `previous_run` and the log tail. Logged as an error. A marker naming a still-running process (an update hand-off) is not a crash.
- A pulled power cord or a forced kill also produces this report.

## Automatic relaunch after a crash: the supervisor (source: supervisor.py, crash_report.py)

- **When it runs**: in packaged Windows and macOS builds only, with `supervise` not false and the environment variable `CCSYNC_NO_SUPERVISOR` unset. The companion starts a second copy of its own program with `--supervise <pid> --exe <path> --crash-dir <dir> --state-dir <dir> [--launchd-label <label>] [--prior <t,t,t>]`, detached, with a clean environment.
- Logs when off: "supervisor: disabled by config (supervise = false) -- a crash leaves this machine without a companion until the next logon"; when it cannot start: "supervisor: not started (source run, not Windows/macOS, or CCSYNC_NO_SUPERVISOR set) -- if this companion dies without shutting down, nothing relaunches it and this machine syncs nothing until the next logon" (warning on macOS, info elsewhere); when on: "supervisor: pid N is watching this companion and will relaunch it after a crash (never after a Quit or an upgrade)". Linux: never.
- **Waiting**: Windows waits on the process handle and reads its exit code; macOS waits with a kernel process-exit event (falls back to polling every 2 s) and never learns the exit code.
- **Decision** after the companion exits:
  - No run marker: deliberate exit, stand down.
  - Marker names a different pid: replaced (update or a manual start), stand down.
  - A just-upgraded build (`fresh_build`) that died before `booted`, with exit code unknown or 1 or an `exiting` stamp: treated as a failed start and relaunched (still subject to the ceiling).
  - `exiting` stamp present: deliberate, stand down.
  - Exit code 0, 1, 0xFFFFFFFF (Stop-Process) or 0xC000013A (console closed): deliberate, stand down.
  - Program file missing: stand down ("nothing to relaunch"), after first trying to restore an interrupted update (below).
  - 3 relaunches already within an hour (clock steps either way still count): stand down ("this build cannot stay up, leaving it to the logon autostart and the admin").
  - Otherwise relaunch.
- **Relaunch**: waits 10 s, re-reads the marker (a companion someone started meanwhile wins), records the relaunch, writes `relaunched.json` into the crash folder (`when`, `previous_pid`, `exit_code`, `reason`, `attempt`, `supervisor_pid`, `history`), then starts the program detached with no window. On macOS under the LaunchAgent it first tries `launchctl kickstart gui/<uid>/<label>` and only starts directly if that fails.
- **Relaunch history** (`~/.ccsync/state/supervisor.json`, up to 20 stamps) is merged with the count carried on the command line, so the 3-an-hour ceiling survives an unwritable state folder. Write failures are logged as warnings in the supervisor log.
- **Interrupted update repair**: if the companion program is missing but `<name>.old` exists (non-empty) and the dead companion left a marker, the supervisor renames `.old` back so there is something to relaunch.
- **Supervisor log**: `~/.ccsync/crashes/supervisor.log`, timestamped lines, deleted when over 256,000 bytes.
- **Relaunched companion**: reads and removes `relaunched.json`, writes the UncleanExit report, logs "this companion was RELAUNCHED by its supervisor: pid N died with exit code C at T and never started a shutdown (...). It was down for about 10 s. Relaunch K of 3 this hour...", and spawns a fresh supervisor carrying the history.
- **macOS limits**: a Force Quit from Activity Monitor reads as a crash and is relaunched (within the ceiling); a build killed before it can start a supervisor is not covered.

## Looks redundant or overlapping

- Two copies of the "token" credential: `dashboard_token` (shared) and `report_token` (per-person) in `config.toml`, plus `report_token` and `editor_report_token` in `identity.json`, collapsed at runtime into `dashboard_token` by a four-way precedence rule.
- The job runner's fleet calls use only `dashboard_token` from the live settings, while the reporter also falls back to the startup copy; the updater's download also reads `dashboard_token` only. Same credential, three readers with slightly different rules.
- Two "plain http to a public host" checks with different strictness: the shared connection guard (DNS-based) and the updater's own shape-only `transport_ok`.
- Two version records for crash-loop detection: `last_version.json` and the legacy `last_version.txt`, both written on every start.
- Two crash-loop mechanisms that overlap: the updater's "3 starts in 10 minutes" revert to `.old`, and the supervisor's "3 relaunches an hour" ceiling; plus the supervisor's own `.old` restore when the program is missing.
- Two relaunch-history stores for the supervisor (the state file and the command-line copy via `relaunched.json`).
- Three "idle" style gates with the same 300 s default under different keys: `proxy_gen_idle_seconds`, `broll_ingest_idle_seconds`, `jobs_idle_seconds`.
- Three "skip while Resolve is open" keys with different defaults: `proxy_gen_skip_while_resolve_running` (false), `broll_ingest_skip_while_resolve` (true), `jobs_skip_while_resolve_running` (true).
- Four near-identical "settle window" keys at 120 s: `lane_b_min_age_seconds`, `proxy_gen_min_age_seconds`, `youtube_import_min_age_seconds` (and the same idea in `proxy_gen_stability_seconds`).
- Two free-space floors for the same drive: `proxy_gen_free_space_floor_gb` and `broll_ingest_free_space_floor_gb` (20 GB each), plus `lane_b_min_free_bytes` (20 GiB).
- `projects`, `syncthing_folder_ids` and `active_project` are legacy keys from before dashboard-managed selection; the template itself calls them leftovers.
- `sync_enabled` and `lane_b_enabled` are both forced off by `mode = "base"`; `mode` itself is a third switch for the same state.
- The release-notes wording is produced three times (menu label, toast, dialog) with different length caps.
- `report_input_idle` and `jobs_enabled = false` both blank `capabilities.idle_seconds`.
- Status text for the job gate is sent twice: as `capabilities.jobs_gate` and implicitly through the tray/status snapshot.
- The `report_timeout_full` key exists only in code (no default entry, no template line), unlike every other key.

## Claims the code does not back

- `config.py` comment on `supervise` says "Windows frozen builds only"; the supervisor also runs on packaged macOS builds.
- `config.py` FLEET JOBS comment says "today, one kind: `whisper`"; the runner handles seven kinds (`whisper`, three media kinds, two card-copy kinds, `ledger-scan`).
- `jobs_runner.py` module docstring says "Four kinds"; there are seven.
- `config.py` template text for `lut_sync_enabled` says "Nothing on disk is moved, renamed or linked"; the defaults comment above it says the companion "turns that directory into a link to the library". The two comments disagree (the LUT code is outside this section, so which is true was not checked).
- The job gate's `no_dashboard` sentence says the computer "is not signed in to the dashboard"; the code only checks that `dashboard_url` and `dashboard_token` are non-empty, not that anyone is signed in.
- `upgrade.py` module docstring says the stale `.old` "is deleted on the NEXT startup"; the code also deletes it during the current run once the build has had a report accepted and been up 10 minutes, or after 60 minutes.
- `upgrade.py` module docstring says the tray grows an "Update now" item; the label the code produces is "Update available → v<X> (install)" (or the roll-back/switch wording).
- `config.py` version note for 0.7.11 says the companion "fetches GET /api/v1/site once per start"; nothing in this section's files does that on its own (the fetch function exists; whether the app calls it at startup was not visible here).
- `reporter.py` comments describe a "30 s" report cadence in several places; the defaults are 60 s idle and 5 s active.
- `transport.py` docstring says the shared opener refuses public plain http for "every credentialed dashboard call"; the job runner, card-copy and scan calls go through `broll_ingest.default_request`, which is outside this section, so whether it uses that opener was not verified here.

## Could not determine

- Who calls `site.refresh_site()` during normal running (only install-time callers are named in comments).
- Whether `broll_ingest.default_request` (used for all fleet-job and Footage Sorter calls) carries the no-redirect opener and the cleartext guard.
- How the app maps the job runner's status (`gate.taking_work`, sentence) into the `capabilities.jobs_gate` `{taking_work, reason, detail}` shape, where `reason` is described as a machine-readable state.
- Where the reporter's `reporter` health block, the crash summary and the `upgrade` block are attached inside `sync_guard` (done in `app.py`, outside this section).
- The exact tray menu wording for "Take fleet jobs now", the stop button and the update item (built in `tray.py`/`settings_window.py`, outside this section).
- What the card copier (`card_copy.py`), ledger scan (`ledger_scan.py`), ledger outbox and TeraCopy detection actually do; only their interface with the job runner is described here.
- Whether `music_ingest_staging_retention_days` is read anywhere (only mentioned in a config comment).
- The `ytdl_player_client` and `ytdl_max_identical_failures` keys are mentioned only in version-history comments; whether code elsewhere reads them was not checked.

