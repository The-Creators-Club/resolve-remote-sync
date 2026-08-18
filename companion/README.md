# ccsync-companion

Editor-side companion app for CC Sync -- fleet sync for DaVinci Resolve(R).
Requires DaVinci Resolve Studio on this machine (the free edition exposes
neither collaboration nor the external scripting interface this app drives).
See `../SPEC.md` (repo root) for the full system design — this README covers
just this `companion/` package: a tray app + three supervised daemons that
implement "Architecture + Components §2" of that spec.

## What it does

1. **Timeline watcher** (`watcher.py`) — polls the current Resolve project's
   current timeline every 3s (configurable), reads every video+audio
   timeline item's source file path, and classifies it:
   - **OK** — under your `local_root`.
   - **OUT_OF_TREE** — exists on disk but outside `local_root` → queued for
     the popup fixer.
   - **BAD_PREFIX** — starts with the canonical shared prefix (`P:\` on
     Windows) but doesn't resolve under `local_root` → a mapping-health tray
     notification (your `subst P:` / Mapped Mount setup is probably broken).
   Debounced per session — once you Ignore a path, it won't pop again until
   you restart the app.

2. **Popup fixer** (`fixer.py` + `popup.py`) — one tkinter dialog listing
   every accumulated OUT_OF_TREE clip, with a destination dropdown pre-filled
   by file type (audio → `Audio/Music`, stills → `B-roll/Stills`,
   video/other → `B-roll/Editor Added/<editor_name>`), editable free text,
   and existing directories under `local_root` (minus any `Proxy/` dirs) as
   suggestions. **Fix all** copies each file into `local_root` (never
   clobbering — collisions get ` (2)`, ` (3)`, ...) then relinks the Resolve
   media pool item via `ReplaceClip`, preserving every timeline usage.
   **Ignore** suppresses the listed clips for the rest of the session. The
   original file is never deleted or moved, even if the Resolve relink call
   fails.

3. **Sync orchestrator** (`sync/`) — three lanes behind a common
   `LaneAdapter` interface (`sync/base.py`), matching SPEC.md's table:

   | Lane | Module | Content | Direction | Trigger |
   |---|---|---|---|---|
   | A | `sync/rclone_lane.py` (`direction="up"`) | video originals, outside `Proxy/` | editor → NAS | watchdog file events (10s debounce) + periodic full pass (`scan_interval_up`, default 300s) |
   | B | `sync/rclone_lane.py` (`direction="down"`) | `**/Proxy/**` only | NAS → editor | periodic full pass only (`scan_interval_down`, default 120s) |
   | C | `sync/syncthing_lane.py` | everything else | bidirectional | supervises a locally-running Syncthing over its REST API; does not sync directly and does not install/launch Syncthing |

   Lane A uses `rclone copy` with `--ignore-existing` (never clobbers a file
   already on the NAS — SPEC.md's "editors sync originals up" is intentionally
   one-directional and non-destructive) and `--min-age 30s` (file-stability
   wait, so a file mid-copy from a camera card isn't uploaded half-written).
   Lane B uses `rclone sync` (NAS is authoritative for proxies — renames and
   deletes propagate down).

4. **Tray** (`tray.py`) — tray icon (`tray_native.py`): green = all lanes OK, orange = a lane
   is syncing, red = any lane has an error. Menu: per-lane status line,
   "Sync now", "Pause sync" toggle, "Open log", "Quit". Falls back to
   headless console logging if Pillow isn't installed (same
   try/except pattern used throughout).

`app.py` (`CompanionApp`) wires all of the above together and is what
`ccsync-companion` (see `pyproject.toml`'s `[project.scripts]`) actually runs.

## B-roll "Send to Resolve"

`broll_server.py` — a loopback-only HTTP server on `127.0.0.1:8899` (`GET
/status`, `POST /insert`) that the b-roll library's web UI calls to drop a
trimmed clip into the open Resolve timeline's `B-Roll` bin. Started as a
daemon thread by `CompanionApp.start()`; contract in `../broll/SPEC.md`
("Companion API contract"), which is still the authoritative version of it.

**This used to be a second tray app** — the standalone BRoll Companion
(`broll/companion/`). It was absorbed here and retired on 2026-08-10: two
tray apps meant two things to install, two to upgrade, and in practice the
small one was upgraded by nobody. **Do not run it alongside this one.** It
would hold port 8899, and this server would then log a warning naming that
as the likely cause and carry on without the feature — a failed bind never
stops, delays or degrades anything else the companion does.

Share → local-folder mappings still live in `~/.broll-companion.json`
(editors already have the file), with one addition: the `broll` share needs
no entry at all, because this app knows the tree — it defaults to
`<local_root>/Assets/B-roll Archive`. An explicit entry always wins, and
other shares have no derivable root, so they still need one line each.

## B-roll ingest — this machine indexes the clips you drop

`broll_ingest.py` (with `broll_vlm_sidecar.py`, `broll_ingest_media.py` and
`broll_upload.py`), 2026-08-18, `docs/BROLL_INGEST_PLAN.md`.

Drag clips — or a whole card folder — onto the dashboard's b-roll page and
**the editor's own machine** does the work: ffmpeg makes a 540p proxy, a
sprite, a poster and the frames; a local Qwen3-VL (llama.cpp, on the GPU)
describes them; rclone puts the results in `Assets/B-roll Archive` on the NAS;
and the server flips the rows live only once it has `stat()`ed the files
itself. The browser only ever hands over a batch id — every path, name and
setting comes back from the server under the fleet token.

What an operator needs to know:

- **It runs when you are away**, like the proxy generator, unless the batch was
  created in **Foreground** mode (which skips the idle and Resolve-open gates
  and nothing else). Coming back to the keyboard stops it within one stage and
  frees the GPU; it resumes from the same checkpoint.
- **Indexing beats proxy generation.** While a batch is crunching, the proxy
  generator is *blocked* and says so ("waiting: indexing b-roll first"). They
  share one GPU, and this is the one an editor is waiting on.
- **It never runs the model on the CPU.** A machine whose GPU cannot fit the
  chosen tier refuses the batch, in the page and in the tray, naming the VRAM.
- **The first batch downloads a model** (about 3.3 GB for Good, 6.2 GB for
  Best) into the same tools directory yt-dlp and ffmpeg use. Free space is
  checked first, every URL is checked against an allow-list, and progress is
  in the tray and in the window.
- **Progress is a WINDOW**, not just tray lines: model download, the clip and
  stage in flight, N of M, failures and a time estimate, with Pause / Start now
  / Cancel. Tray ▸ Advanced ▸ "Show indexing progress…" reopens it; closing it
  stops nothing. The proxy generator uses the same window.
- **State survives a restart.** `~/.ccsync/state/broll_ingest.json` is rewritten
  at every transition, so a companion killed mid-batch re-claims and carries on
  from the last checkpoint rather than re-indexing anything.
- **The base rig must set `broll_ingest_staging_dir`** — its `local_root` is
  the NAS share, and staging there would send every original over SMB twice.

## YouTube auto-import

`youtube_import.py` — a daemon thread that files the clips the dashboard's
YouTube page downloaded into the project the editor has open, as
`Master/Youtube/<search term>` bins matching the `<project>\Youtube\<term>\`
folders sync delivers. Nothing new is transferred and nothing on disk is
moved, renamed or deleted; the two bridge functions it drives
(`resolve_bridge._ensure_bin_path` / `import_files_to_bin_path`) only ever ADD
media pool items.

Four rules, and everything awkward-looking in the module is one of them:

* **Only the project that is open.** Importing needs it open anyway, and the
  rescan is idempotent — so opening a project is what picks up everything
  that arrived while it was closed. That is why there is no queue and no
  per-project state.
* **No database.** `to_import = settled files on disk MINUS the paths already
  in the media pool`, recomputed every cycle from a single pool walk. Restart,
  re-sync, a renamed bin and a project copied to another machine all self-heal.
  The documented consequence: a clip DELETED from the pool while its file
  stays on disk comes back after a companion restart (delete the file, or set
  `youtube_import_enabled = false`).
* **Nothing half-delivered.** Only `.mp4/.mov/.mkv/.webm/.m4v` (which excludes
  the `.credits.json` sidecars and `manifest.json` the downloader writes
  beside them), never a dotfile or a `.partial`/`.tmp`/`.lock`, and only once
  a file is past `youtube_import_min_age_seconds` AND has held its size across
  two consecutive scans.
* **Dedupe is pool-wide, by path.** A clip the editor dragged into a bin of
  their own is never re-imported (`music_worker.existing_item`'s rule). By
  path rather than by video id, so the same video downloaded under two search
  terms lands in both term bins — each one is self-contained on purpose.

Bin names are matched NFC-normalised: macOS hands out decomposed filenames and
Resolve stores what it is given, so a CJK term folder would otherwise spawn a
duplicate bin with the same visible name on every cycle.

## Requirements

- **DaVinci Resolve Studio**, with external scripting enabled:
  **Resolve → Preferences → System → General → External scripting using: Local.**
- Python 3.12.
- A pre-configured `rclone` remote pointing at the NAS (`rclone config`) —
  this app does not configure rclone remotes or install rclone for you.
- A locally-running Syncthing (bootstrap/installer's job, not this app's) if
  you want Lane C.

## Install & run (from source)

```
cd companion
python -m venv .venv
```

Windows:
```
.venv\Scripts\activate
pip install -e .
ccsync-companion
```

macOS:
```
source .venv/bin/activate
pip install -e .
ccsync-companion
```

Tray icon needs the optional extra: `pip install -e ".[tray]"` (Pillow, and
PyObjC on macOS). pystray is deliberately NOT a dependency any more -- it is
LGPLv3 and this app is frozen, so the tray is `tray_native.py`, written from
the OS APIs. Runs headless (console logging only) without the extra.

## Config reference

TOML at `~/.ccsync/config.toml`. Normally the bootstrap installer
(`installer/windows_bootstrap.ps1` / `macos_bootstrap.sh`) writes this file,
seeded with the values it already knows — `editor_name`, `local_root`,
`remote`, `remote_root` — leaving only `projects` and `active_project` for a
human. If the companion starts and finds no config at all, it writes its own
template with those install-specific values left **blank**, and then complains
about each one at startup rather than pretending to work.

`config.example.toml` in this directory is a filled-in reference, not a copy
of what either of those produces. Restart the app after editing.

| Key | Default | Notes |
|---|---|---|
| `editor_name` | `""` | Used to build the `B-roll/Editor Added/<editor_name>` popup destination. |
| `local_root` | `""` | This machine's local project tree root. **Must be set.** |
| `canonical_prefix` | `"P:\\"` | The shared-drive prefix Resolve's stored clip paths use (SPEC.md's Path canon). Used for BAD_PREFIX detection. |
| `remote` | `"ccsync_sftp"` | Name of the rclone remote. Must match the stanza the bootstrap installer writes into `rclone.conf`. |
| `remote_root` | `""` | **Absolute** NAS path under which project trees live, e.g. `/mnt/<pool>/<tree>`. Must be set, and must be absolute — see below. |
| `projects` | `[]` | Positional pair for `syncthing_folder_ids` (lane C's folder-ID check). Does **not** scope what syncs. |
| `active_project` | `""` | Destination the popup fixer suggests for editor-added media. Does **not** scope what syncs; blank just suggests the tree root. |
| `poll_interval` | `3` | Resolve timeline poll interval, seconds. |
| `scan_interval_up` | `300` | Lane A periodic full-pass interval, seconds. |
| `scan_interval_down` | `120` | Lane B periodic full-pass interval, seconds. |
| `watch_debounce_seconds` | `10` | Lane A watchdog debounce, seconds. |
| `transfers` | `4` | rclone `--transfers` (parallel streams). |
| `syncthing_url` | `"http://127.0.0.1:8384"` | Local Syncthing REST API base. |
| `syncthing_api_key` | `""` | Overrides reading the key from Syncthing's `config.xml`. |
| `syncthing_folder_ids` | `[]` | Expected Syncthing folder ID per project (parallel to `projects`); skipped if empty. |
| `rclone_path` | `"rclone"` | Path to the rclone binary; must be on PATH if left as the default. |
| `log_path` | `"~/.ccsync/companion.log"` | Rotating log file. |
| `log_level` | `"INFO"` | Python logging level name. |
| `dashboard_url` | `""` | Base URL of the server sync dashboard (e.g. `http://<tailnet-ip>:8480`). Blank disables the reporter thread entirely. |
| `dashboard_token` | `""` | Shared secret sent as `X-CCSync-Token` with each report; must match the server's `DASH_REPORT_TOKEN`. |
| `dashboard_report_interval` | `60` | Seconds between status reports to the dashboard. |
| `selection_poll_interval` | `60` | How often the sequencer refreshes the editor's project selection from the dashboard. |
| `project_rotation_seconds` | `600` | Max time the sequencer spends on one project's lane-C turn before rotating to the next (starvation guard). |
| `sequencer_idle_seconds` | `60` | Idle sleep between full passes over the queue. |
| `selection_fetch_ttl` | `30` | How long the last selection response is served from memory before the dashboard is asked again (the sequencer consults it from a 5-second poll loop). |
| `project_roots_ttl` | `300` | Longer TTL for the sticky per-Resolve-project destination mapping (`project_roots`) carried in the same response. |
| `lane_b_enabled` | `true` | Set `false` on the base rig (direct LAN access to the NAS): proxies are read straight off the share, so the local proxy mirror is skipped in both managed and legacy modes. |
| `sync_enabled` | `true` | Set `false` when the machine works entirely off the NAS share (base rig): no sync lanes run at all; timeline watcher, popup fixer and dashboard reporting still work, lanes report idle with a "disabled" detail. |
| `popup_enabled` | `true` | Set `false` to suppress the media-outside-tree popup entirely (still logged). |
| `broll_server_enabled` | `true` | Serve the b-roll web UI's "Send to Resolve" button (see the section above). `false` = don't listen at all. |
| `broll_server_port` | `8899` | Port for that server. Pinned on the web page's side too, so changing it here alone just switches the feature off. |
| `mode` | `"editor"` | Machine role. `"base"` = the central machine with direct NAS access: implies `sync_enabled = false` unless set explicitly. The out-of-tree popup stays ON in base mode — stray media outside the project directory on the NAS still needs fixing into the tree. |
| `proxy_notify_enabled` | `true` | Tell the editor which of their originals have no `Proxy/` sibling — i.e. which footage lane B can never carry to anyone else. Costs nothing and touches no bytes; on by default on every machine. |
| `proxy_gen_enabled` | *(derived)* | **Tri-state.** Absent = `not lane_b_enabled`: on where the result lands on the NAS (base rig), off where lane B would sweep a locally-made proxy into `.ccsync-trash`. `true`/`false` is obeyed verbatim; an editor who opts in keeps proxies for untracked projects and loses them for synced ones. |
| `ffmpeg_path` | `"ffmpeg"` | The ffmpeg binary used to make proxies and to merge YouTube downloads. Nothing bundles it (80–120 MB on every upgrade), but with local YouTube downloads on the companion installs a pinned static ffmpeg+ffprobe beside yt-dlp on first run (`sidecar_tools.py`, 2026-08-16) and the bare default name finds that copy behind PATH. An absolute path is your own install and is never touched. Absent everywhere means notifier-only; syncing is unaffected. |
| `proxy_scan_interval` | `900` | Seconds between proxy-gap scans. Lazy on purpose: this is a SECOND full tree walk on top of the manifest cache's. The tray's "Make the missing proxies now" forces one immediately. |
| `proxy_gen_idle_seconds` | `300` | Seconds away from keyboard/mouse before encoding may start. Encoding stops within ~2s of you coming back; the scan and the notification are not gated on this at all. |
| `proxy_gen_min_age_seconds` | `120` | Settle window — a file still being copied off a card has a fresh mtime. Same idea and the same number as `lane_b_min_age_seconds`. |
| `proxy_gen_max_height` | `1080` | Ceiling, not a target: a 720p original is never upscaled. Commented out in the template. |
| `proxy_gen_bitrate` | `"7M"` | Own-footage proxy bitrate (maxrate/bufsize derive from it). Matches the FF4-era Resolve proxies already in the tree. Garbage is logged and ignored, never fatal. Commented out. |
| `proxy_gen_max_failures` | `3` | Attempts on one file before it is skipped for the rest of the session. **In-process only** — a blacklist persisted to disk turns a transient GPU failure into a permanent one. Commented out. |
| `proxy_notify_cooldown_seconds` | `86400` | How long before the same "clips have no proxy" toast may appear again. Persisted, so restarts don't re-nag. Commented out. |
| `proxy_gen_skip_while_resolve_running` | `false` | Off by default: the idle gate already covers a Resolve you are sitting in front of. Turn on for a machine that leaves **unattended renders** going, which no input-based idle probe can see. Fails closed. Commented out. |
| `youtube_import_enabled` | `true` | File the clips the dashboard's YouTube page downloaded into the project you have open, under `Master > Youtube > <search term>` (see below). Only ever ADDS media pool items. |
| `youtube_import_scan_interval` | `60` | Seconds between re-listings of the open project's `Youtube/` folder. One `listdir` per term folder, not a tree walk — hence eager compared with `proxy_scan_interval`. A project change rescans immediately. |
| `youtube_import_min_age_seconds` | `120` | Settle window, same idea and the same number as `proxy_gen_min_age_seconds`. A file must ALSO have held its size across two consecutive scans: a copy that preserves the source's mtime is born looking old. |
| `youtube_import_batch_limit` | `20` | Files handed to Resolve in one call, per term folder, per cycle. This is what bounds how long the import holds the Resolve scripting lock (the timeline watcher polls behind it); the remainder goes on the next tick. Commented out. |
| `youtube_import_max_failures` | `3` | Attempts on one file before it is left alone for the rest of the session. **In-process only**, exactly like `proxy_gen_max_failures`. Resolve being closed, or you having switched project, is a state and never counts as an attempt. Commented out. |

With `dashboard_url` set, a fault-isolated reporter thread
(`reporter.py`) POSTs the current status of all three lanes to the
dashboard's `/api/v1/report` endpoint on that interval, so the admin's
fleet dashboard can show this editor's lane A/B health. Report failures
never affect syncing; they are logged and retried on the next interval.
The reporter keeps posting while sync is paused so the dashboard shows
"paused" rather than a silent gap.

### Managed mode (dashboard-driven selection, one project at a time)

Setting `dashboard_url` also switches the sync lanes into **managed mode**:
instead of each lane free-running over the whole tree, a sequencer
(`sync/sequencer.py`) fetches this editor's ticked projects from the
dashboard (cached at `~/.ccsync/state/selection.json` for offline starts)
and syncs them **one at a time, in tick order**: lane A, then lane B (both
scoped to that project's subtree), then the project's Syncthing folder gets
its turn (other selected folders paused locally). Pending Syncthing folder
offers for selected projects are auto-accepted with the correct local path
and editor-side ignore patterns. No selection data (fresh install, dashboard
down, nothing ticked) means **nothing syncs** -- that's the design: editors
choose their projects on the dashboard. With `dashboard_url` blank the
legacy whole-tree behavior is unchanged.

The selection fetch (`GET {dashboard_url}/api/v1/selection/{editor_name}`)
sends **both** auth headers, the same pair `/api/v1/report` sends:
`X-CCSync-Token` (the fleet-wide `dashboard_token`) and `X-CCSync-Identity`
(the signed identity token from sign-in). The dashboard requires both to
read an editor's selection -- the shared token alone does not authorize it.
Not signed in means no identity header and, on an up-to-date dashboard, a
401 that degrades exactly like any other fetch failure: the cached
selection keeps the sequencer working.

### What actually syncs: the whole tree

Lanes A and B run `rclone` between `local_root` and `remote:remote_root` as
**whole trees**, filtered only by file type (video-outside-Proxy up,
Proxy-contents down). The server's directory structure is therefore
replicated verbatim on every editor machine:

```
<tree>/Projects/<year>/<series>/<project>/{AE,Audio,B-roll,...}
```

Any year, any series, any project — `Projects/2026/Creator Profiles/Season 1`
and `Projects/2025/FF4/Nuclear` alike, including names with spaces — appear
without any per-project configuration. New projects added on the server show
up on the next lane-B pass. Neither `projects` nor `active_project` gates
this; see their rows above for what they really do.

### `remote_root` must be absolute

An SFTP session lands in the editor's **home directory** on the NAS
(`<pool_root>/homes/<editor>`), not at the data root. So a relative
`remote_root = "<tree>"` builds `ccsync_sftp:<tree>`, which resolves to
`~/<tree>` — a directory that doesn't exist — instead
of the shared tree. Lane A would upload into the editor's home directory and
lane B would find nothing to bring down, with no error that points at the
cause.

`validate_config()` (called at startup, logged, never raises) rejects both a
blank and a relative `remote_root` for this reason, along with a blank
`editor_name`, `local_root`, `remote`, `projects`, or `active_project`. A
half-configured install is otherwise entirely silent — nothing syncs and no
lane reports why — so these are logged at ERROR with one line per problem.

### SPEC deviations (and why)

SPEC.md's config bullet lists a single `scan_interval`, but the Lane A/B
bullets specify **different** default intervals (300s vs 120s) — so this
implementation splits it into `scan_interval_up` / `scan_interval_down`
rather than inventing an ambiguous single knob. `watch_debounce_seconds` and
`syncthing_folder_ids` aren't named explicitly in SPEC.md's config bullet
either, but both are needed to fulfil requirements stated elsewhere in the
same section (the 10s debounce, and "verify the expected folder ID... is
configured + shared") — see the inline comments in `config.py` next to each.

The **missing-proxy notifier and ffmpeg proxy generator** (`proxy_scan.py`,
`proxy_gen.py`, `ffmpeg_tools.py`, `idle.py`, 2026-08-10) are in no SPEC.md
config bullet at all: SPEC.md assumes proxies already exist beside every
original, and `docs/SERVER.md:193-196` has carried an "ffmpeg fallback
generator" to-do since the start. They implement it, and the notifier half
answers the question SPEC.md never asks — *which* originals have no proxy,
i.e. which footage lane B (`**/Proxy/**` only) can never carry to anybody
else. Nothing about the Proxy/ convention itself changes: generated files are
`<dir>/Proxy/<stem>.mp4`, exactly what Resolve's adjacent-Proxy auto-link and
`proxy_relink.py` already expect.

SPEC.md's Lane A/B description mentions "`--sftp-*`/remote params from
config" — this implementation instead relies on `rclone config`-managed
remotes (the `remote` key is just the remote's name), since rclone already
has a first-class, more secure way to store SFTP credentials than a TOML
file. Re-open this if a good reason to hand-roll SFTP params in-config
surfaces later.

## How the lanes map to SPEC.md

- **Lane A (video originals, up)** = SPEC.md Architecture table row 1 +
  "Flaws #2" (never deletes on NAS — reorganizations must happen server-side)
  and "Flaws #3" (same-name collisions: `--ignore-existing` means the
  *second* editor's file to reach `Audio/Music/track.mp3` silently loses the
  race and stays local-only, uploaded nowhere until renamed — this is a
  known sharp edge, not yet surfaced in the tray; see Known limitations).
- **Lane B (proxies, down)** = row 2. `rclone sync` direction (not `copy`)
  is deliberate: SPEC.md's Flaws #2 says renames propagate down because the
  server is authoritative for proxies.
- **Lane C (everything else)** = row 3 + Flaws #3's "Syncthing conflict-copies
  (surfaced in tray)" — this implementation currently surfaces Syncthing
  *health* (reachable / folder configured+shared / queued item count) in the
  tray, but does not yet parse individual `*.sync-conflict-*` filenames out
  of Syncthing's REST API to name-and-shame them in the tray menu. Noted as
  an open question below.
- **Popup fixer** = "Companion App" bullet 3 / Flaws is not listed but ties
  directly to the "Popup should move + relink automatically" line in the
  Current-state section — implemented as copy (not move) + `ReplaceClip`,
  matching the explicit "do NOT delete the original file ever" instruction
  in this task's own brief (which is stricter than SPEC.md's looser "move
  it" wording — copy-then-relink is a strict superset of safety, so this
  isn't really a deviation, just the stricter of two compatible readings).

## Tests

```
cd companion
.venv\Scripts\python -m pip install -e ".[tray,dev]"
.venv\Scripts\python -m pytest
```

105 tests, all green. Coverage:

- **Path classification** (`test_paths.py`) — Windows + posix paths,
  case-insensitivity, BAD_PREFIX priority over a coincidentally-existing
  file, similar-prefix-but-different-directory false positives.
- **Config** (`test_config.py`) — first-run creation, TOML parsing,
  malformed-file fallback, and a parity check that `config.py`'s DEFAULTS,
  `DEFAULT_TOML_TEXT`, and `config.example.toml` never drift apart.
- **Fixer** (`test_fixer.py`) — every extension → destination mapping,
  `Proxy/`-excluding directory listing, collision-safe renaming (`(2)`,
  `(3)`, ...), and the full copy+relink flow including relink-failure and
  missing-source paths (mocked `resolve_bridge.replace_clip`, real
  filesystem via `tmp_path`).
- **Popup logic** (`test_popup.py`) — the pure row-building /
  fix-all / ignore-all functions (no real Tk window is created in tests —
  see Known limitations).
- **Resolve interaction** (`test_resolve_bridge.py`, `test_watcher.py`) — a
  hand-rolled fake Resolve object graph (project manager → project →
  timeline → timeline items → media pool items) stands in for the real
  scripting API; no live Resolve instance is used anywhere in the suite.
- **rclone filter rules** (`test_rclone_filters.py`) — pure content
  assertions on the generated filter rule lists, PLUS integration tests that
  actually invoke rclone (`--dry-run` and for-real) against local temp dirs
  acting as both ends, proving: Lane A picks video files outside `Proxy/`
  only; `--ignore-existing` never clobbers a file already "on the NAS";
  Lane B's `+ **/Proxy/` / `+ **/Proxy/**` / `- **` rule set selects nested
  Proxy contents at any depth and excludes everything else; `rclone sync`
  propagates a rename (delete old name + add new name) locally. See "Test
  tooling" below for how rclone is sourced.
- **Syncthing lane** (`test_syncthing_lane.py`) — `config.xml` API-key
  parsing (missing file, malformed XML, no `<gui>` element), plus REST
  behaviour against a tiny in-process `http.server` fixture (idle/syncing/
  error states, missing-folder, folder-not-shared, unreachable server, no
  API key anywhere).
- **Tray** (`test_tray.py`) — the pure icon-color function
  (green/orange/red precedence).

### Test tooling: rclone

The integration tests in `test_rclone_filters.py` need a real `rclone`
binary. `tests/conftest.py`'s `rclone_binary` fixture checks `PATH` first,
then these, in order:

1. `companion/.tools/rclone[.exe]` — a **test-only** portable binary
   (downloaded from rclone.org for this build, NOT installed system-wide,
   NOT added to PATH, NOT referenced by any production code path;
   `config.py`'s `rclone_path` default remains plain `"rclone"`).
   `.tools/` is gitignored, so this only ever exists on a machine where
   someone put it there by hand.
2. `~/.local/ccsync/bin/rclone` — where `macos_bootstrap.sh` installs it.
3. `%LOCALAPPDATA%\ccsync\bin\rclone.exe` — where `windows_bootstrap.ps1`
   installs it.

2 and 3 matter because the installed rclone is deliberately kept **off**
PATH (INST-7: launchd gives a LaunchAgent
`PATH=/usr/bin:/bin:/usr/sbin:/sbin`), so a correctly-installed machine is
exactly the one where `shutil.which` comes up empty.

If none is found those specific tests skip with a message naming every
location searched — **unless `CCSYNC_REQUIRE_RCLONE=1`**, which turns the
skip into a failure. Both release scripts set it: `pytest` exits 0 when
tests skip, so 24 skipped lane-direction tests would otherwise read as a
green suite and authorise a build whose real-rclone coverage never ran.
That is what happened on the first macOS run (2026-08-04) — the fallback
was hardcoded to `rclone.exe`, so it could never match on a Mac.

## Build (PyInstaller)

```
cd companion
.venv\Scripts\activate      (or source .venv/bin/activate on macOS)
pip install -e ".[dev]"
pip install pyinstaller
pip install -e ".[tray]"     # optional, for the tray icon
pyinstaller build.spec
```

Output: `dist/ccsync-companion.exe` (Windows) or `dist/ccsync-companion`
(macOS, no extension). PyInstaller does not cross-compile — build separately
on each target OS. **This has not been run/verified in this environment**
(per task instructions) — sanity-check the resulting binary on a real
Windows/macOS box before shipping, same caveat as broll-platform's
`build.spec` this was forked from.

## Known limitations

- **PopupDialog (tkinter) is not exercised by the test suite** — it needs a
  real display. Everything it calls (`build_popup_rows`, `perform_fix_all`,
  `perform_ignore_all`) is pure and fully tested; only the widget wiring
  itself is unverified by automation. `popup.show_popup` catches any
  exception from creating the Tk window and falls back to a console listing
  (auto-suppressing nothing — the clips will be re-offered next poll) so a
  headless/no-display environment degrades rather than crashing the watcher
  thread.
- **Same-filename collisions across editors on Lane A** aren't surfaced
  anywhere yet (SPEC.md Flaws #3 flags this as a known asymmetry between
  lanes — Syncthing lane C shows conflict-copies natively; lane A's
  `--ignore-existing` silently "loses" the second editor's identically-named
  upload with no tray signal). Worth a v2 pass: e.g. content-hash compare
  before skip, or at minimum log + tray-notify on an ignored-due-to-existing
  event.
- **Syncthing lane reports aggregate health, not individual conflict
  files.** `check_once()` surfaces reachability, folder-configured+shared,
  and a queued-item count from `/rest/db/status`, but doesn't walk
  `/rest/db/browse` for `*.sync-conflict-*` names. Flagged as an open
  question below.
- **`sync/rclone_lane.py`'s watchdog integration is best-effort.** If the
  `watchdog` package (a hard dependency here, unlike the optional tray
  extras) somehow fails to start an `Observer` on a given filesystem, Lane A
  silently falls back to periodic-only uploads (logged, not raised) — there
  is no test exercising a live `Observer` end-to-end (would require real
  filesystem event delivery timing, which is flaky in CI); the debounce
  timer logic itself is straightforward enough that this was judged an
  acceptable coverage gap versus a flaky test. Since MAC-12 the observer is
  also **pre-flighted**: a short-lived subprocess opens and lists the root
  first, and if it cannot answer within `WATCH_PROBE_TIMEOUT_SECONDS` the
  observer is not started at all (ERROR + tray toast, re-checked on a
  bounded backoff). Watchdog's first act on a root is an `open()` from C
  code holding the GIL, and on a wedged volume that froze the entire
  companion — tray, sign-in and main thread included.
- **PyInstaller build unverified**, per SPEC.md's own installer milestone
  being separate work (`installer/`) — see Build section above.
- **No macOS-specific manual testing was possible in this environment**
  (Windows-only sandbox) — `resolve_bridge.py`'s Darwin paths and
  `syncthing_lane.py`'s Darwin `config.xml` path are carried over from
  documented Resolve/Syncthing conventions and the broll-platform skeleton's
  existing (also unverified-on-Mac) pattern, not independently confirmed
  here.

## Open questions (for the orchestrator / next pass)

1. Should Lane A's `--ignore-existing` collision case get a tray
   notification (per Flaws #3), and if so, what's the intended resolution
   flow — rename-and-retry automatically, or just surface-and-let-a-human-
   sort-it-out like the mapping-health warning does?
2. Syncthing conflict-copy surfacing (see Known limitations) — worth a v2
   lane-C enhancement, or out of scope for the companion app entirely (i.e.
   "check the NAS-side Syncthing web UI")?
3. `projects` / `syncthing_folder_ids` are currently informational/
   per-project-check-only — Lane A/B sync `local_root` as a whole rather
   than scoping to just the listed `projects`. Confirm that's the intended
   v1 behaviour (SPEC.md's M4 verification describes a single fake editor
   root, which matches), versus needing per-project include/exclude rules
   once an editor has multiple projects checked out side by side.
4. The `--min-age 30s` file-stability wait (SPEC.md's own phrase) combined
   with the 10s watchdog debounce means a freshly-dropped large video file
   won't start uploading for at least 30s after its last write — is that
   window fine, or should `--min-age` be config-exposed too (right now it's
   hardcoded in `rclone_lane.py`)?

---

DaVinci Resolve is a registered trademark of Blackmagic Design Pty Ltd. CC Sync
is not affiliated with, endorsed by, or sponsored by Blackmagic Design.
