"""Companion config file handling.

Config lives at ~/.ccsync/config.toml (TOML, read with stdlib tomllib — see
SPEC.md's Companion App section). tomllib is read-only, so on first run we
write out DEFAULT_TOML_TEXT verbatim (a hand-maintained, commented template)
rather than round-tripping through a serializer. After that, users edit the
file directly; load_config() only ever reads.

DEFAULTS below is the single source of truth for keys + fallback values —
DEFAULT_TOML_TEXT should be kept in sync with it (see test_config.py, which
asserts the two agree on keys).
"""

from __future__ import annotations

import logging
import re
import shutil
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - project targets 3.12
    import tomli as tomllib  # type: ignore[no-redef]

from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ccsync.config")

# 0.7.0: the 2026-08-11 fix pass -- all 82 KNOWN_BUGS findings (both popup
# wedges, lane B stopped in managed mode, credentials off argv via
# WNetAddConnection2W, own-proxy audio -map, 8899 hardening, BPG gating) plus
# the ignoreDelete delete-protection retrofit, the /music/send endpoints
# reaching editors for the first time, and the parallel proxy generator
# (maxed-out while idle, demoted to one worker while Resolve runs;
# `proxy_gen_workers` overrides). See docs/bug-hunt-2026-08-11.md.
# 0.7.1: POST /ytdl/reveal on the 8899 loopback server -- clicking a row in
# the YouTube downloader page's download history opens that clip's folder in
# the editor's own file manager (Explorer/Finder), from a rel_path under the
# Projects root that the NAS-served page can send without knowing where this
# machine's tree is. Editors on an older build simply 404 on it.
# 0.7.2: every companion window (popups, tray dialogs) wears the NEW Creators
# Club mark in brand red instead of April's pre-composed icon.png -- the same
# white-on-transparent asset the tray already tints per status, so the taskbar,
# the title bar and the tray finally show one logo.
# 0.7.7: the recurring "Resolve is running but isn't accepting scripting
# connections" dialog (every resolve_scripting_warning_interval, default
# 300s) -- the only repeating warning here, for the only broken state the
# editor cannot see. Plus the R12 path-canon work reaching the fleet with a
# warning attached to it: 0.7.6 shipped the classification, this ships the
# thing that TELLS someone when the bridge those fixes depend on is dead.
# 0.7.10: the proxy ledger (proxy_history.py) -- a durable record of every
# proxy this machine has made, surviving restarts and upgrades that the
# in-process counters never did, plus per-clip percent/ETA parsed from
# ffmpeg -progress. Carries the 0.7.9 work too (requester-first ytdl, the
# pinned ffmpeg/deno sidecars, signed-in downloads), which was bumped but
# never built: the fleet goes 0.7.8 -> 0.7.10 and skips 0.7.9 entirely.
# 0.7.11: site-manifest support (site.py) -- the companion fetches
# GET /api/v1/site once per start and takes the SMB UNC (server_p_unc), the
# NAS Syncthing device ID and the rclone SFTP tuning (chunk size, concurrency,
# shell_type) from the server instead of built-in tenant literals; every
# compiled-in address/remote-name default is gone (dashboard_url and remote
# are blank until the installer sets them); derive_server_unc() learned the
# Synology /volumeN share convention. Same code now serves a TrueNAS or a
# Synology site (docs/SYNOLOGY_PORT_PLAN.md, 2026-08-17).
# 0.8.0: the commercial-readiness pass (docs/COMMERCIAL_READINESS.md,
# KNOWN_BUGS.md CR-1..CR-21, 2026-08-17). Behaviour an editor can see:
# pystray is gone -- the tray is our own tray_native.py (LGPL, CR-3); the
# 8899 loopback is origin-allow-listed and token-gated (CR-7 -- a companion
# whose dashboard_url is not the URL editors browse 403s Send-to-Resolve);
# the upgrade channel verifies an ed25519 signature before downloading and
# keeps a monotonic min_version floor (CR-6); lane B has a persisted circuit
# breaker, .ccsync-trash ages out, "Remove from this machine" is gated and a
# real halt exists (CR-11); every Resolve relink takes a save point + undo
# journal (CR-12); proxy gen has a free-space floor (CR-13); the wizard
# takes EULA acceptance and the companion gates its lanes on it (CR-5);
# YouTube features are dormant unless the site manifest enables them (CR-2);
# per-editor report tokens are preferred when present (CR-18); brand strings
# come from the site manifest (CR-16); crash reports are written locally
# (CR-19). Minor bump, not patch: the loopback contract and the signed
# channel are visible interface changes for the dashboard and the SPAs.
# 0.9.0: ingest -- an editor drags clips onto the b-roll page or tracks onto
# the music page and THIS machine does the work (docs/BROLL_INGEST_PLAN.md,
# docs/MUSIC_INGEST_PLAN.md, 2026-08-18). Sixteen new loopback routes
# (`/broll/ingest/*` and `/music/ingest/*`, eight each), the first PUT this
# listener has ever answered (octet-stream, per-file cap, streamed to
# staging), two orchestrators over one kind strategy (broll_ingest.py,
# music_ingest.py, ingest_kinds.py), the vendored local Qwen3-VL sidecar and
# the vendored CLAP audio tower as an ONNX artefact fetched once per machine,
# and a WorkProgressWindow the proxy generator now shares. Indexing takes
# precedence over proxy generation while a batch runs. New frozen
# dependencies: numpy, onnxruntime, xxhash (+35 MB). Also the Creators Club
# mark as the product default and a taskbar identity of our own (KNOWN_BUGS
# CR-25, CR-24). Minor bump, not patch: a whole new contract with both SPAs,
# and an editor on an older build 404s every route of it.
VERSION = "0.9.1"

CONFIG_DIR = Path.home() / ".ccsync"
CONFIG_PATH = CONFIG_DIR / "config.toml"

# The rclone remote name to use when nothing else supplies one -- NOT a
# tenant's name. The installers prefer the site manifest's `rclone_remote`
# (site.py) and only fall back to this, so a customer whose dashboard names
# the remote gets theirs and everybody else gets one neutral, predictable
# name instead of the studio's (2026-08-17).
NEUTRAL_REMOTE_NAME = "ccsync_sftp"

# Keys marked "addition" in the docstring/README are small, clearly-scoped
# extensions beyond SPEC.md's literal config list — see README.md's "SPEC
# deviations" section for the why on each.
DEFAULTS: dict[str, Any] = {
    "editor_name": "",
    "local_root": "",
    "canonical_prefix": "P:\\",
    # Must match the remote name the bootstrap installers write into
    # rclone.conf ($RemoteName / $REMOTE_NAME). It used to default to "nas",
    # which silently gave every fresh install a non-existent rclone remote,
    # and then to one customer's literal remote name -- a compiled-in tenant
    # identity (2026-08-17, docs/SYNOLOGY_PORT_PLAN.md WP0). BLANK now: the
    # installer/wizard writes it from the site manifest's `rclone_remote`,
    # falling back to NEUTRAL_REMOTE_NAME when the dashboard has none, and
    # validate_config() below refuses a blank one loudly.
    "remote": "",
    # ABSOLUTE path on the NAS. An SFTP session lands in the editor's home
    # directory, so a relative value resolves under ~/ (e.g.
    # /var/services/homes/<editor>/<tree> on a Synology) and silently
    # misses the real project tree. Left blank so a fresh install trips
    # validate_config() instead of quietly syncing into the wrong place.
    "remote_root": "",
    "projects": [],
    # The project new editor media gets filed into (popup destinations are
    # prefixed with this) — rel path under local_root, e.g. "Projects/2025/FF4/Nuclear".
    "active_project": "",
    "poll_interval": 3,
    # SPEC.md lists a single `scan_interval` but gives Lane A and Lane B
    # different defaults (300s / 120s) — split into two keys (addition).
    "scan_interval_up": 300,
    "scan_interval_down": 120,
    # Lane B skips proxies whose mtime is newer than this, so a proxy the
    # Blackmagic Proxy Generator is still writing on the NAS is not shipped
    # truncated (see sync/rclone_lane.py: LANE_B_MIN_AGE_SECONDS). 0 = off.
    "lane_b_min_age_seconds": 120,
    # -- lane B circuit breaker + trash retention -------------------------
    # COMMERCIAL_READINESS.md item 9 (2026-08-17). rclone's own
    # --max-delete 100 / --max-delete-size 20G bounds ONE pass; these bound
    # the SEQUENCE, and stop lane B outright until an operator resumes it
    # from the tray. Documented commented-out in both templates for the same
    # reason the transport tuning is: writing them into every first-run file
    # pins them, so a later re-tune would reach nobody.
    # See sync/lane_guard.py for what each one measures.
    "lane_b_max_deletes_per_pass": 50,
    "lane_b_max_delete_fraction": 0.25,
    "lane_b_remote_shrink_fraction": 0.5,
    # The `.ccsync-trash` window. Its own reversal of an older decision (the
    # trash used to be kept forever); the breaker is what makes a bounded
    # window safe -- and prune_trash refuses to run at all while it is
    # tripped. 0 disables the age rule / the size cap respectively.
    "trash_max_age_days": 14,
    "trash_max_bytes": 50 * 1024**3,
    "trash_prune_interval_seconds": 6 * 3600,
    # Debounce window for the Lane A watchdog file events (addition; SPEC.md
    # says "10s debounce" for lane A but doesn't name a config key for it).
    "watch_debounce_seconds": 10,
    "transfers": 4,
    # -- transport tuning (see sync/rclone_lane.py: RcloneTuning) ----------
    # Every one of these disables its flag when set to "" (strings) or 0
    # (ints), so any single knob can be reverted from config.toml without a
    # code change. Defaults are the measured-good values from the round-2
    # performance work, not rclone's own defaults.
    #
    # rclone's SFTP backend has NO multi-thread upload, so one 40 GB BRAW
    # rides a single SSH stream whose in-flight window is
    # sftp_chunk_size x sftp_concurrency. At rclone's 32Ki x 64 that window
    # is 2 MiB, i.e. a hard per-file ceiling of window/RTT -- ~14 MB/s at
    # 150 ms, which is the ~60 mb/s class ceiling this project exists to
    # beat. 255Ki x 64 is a 16.3 MiB window (AUDIT_2 P1).
    #
    # THE SITE CAN OVERRIDE THIS, and on some NAS platforms it must
    # (_SITE_CONFIG_KEYS): a chunk above 64Ki needs the limits@openssh.com
    # extension, which DSM 7.2's OpenSSH 8.2p1 does not have -- 255Ki there
    # truncates every download at 539,000,832 bytes rather than failing
    # (Synology spike 6, 2026-08-17). An explicit value in config.toml still
    # wins over the site's.
    "sftp_chunk_size": "255Ki",
    "sftp_concurrency": 64,
    "sftp_connections": 16,
    "checkers": 16,
    # rclone verifies size AND hash after every transfer when a common hash
    # exists; with shell_type=unix it gets MD5 by running `md5sum <path>` on
    # the NAS, so the NAS RE-READS every file it just received or sent
    # (AUDIT_2 P2). Set false to restore post-transfer hash verification.
    "rclone_ignore_checksum": True,
    # Upload newest first (an editor wants today's card ingest to land);
    # download smallest first (many small proxies beat one huge one for
    # perceived progress). "" disables ordering.
    "order_by_up": "modtime,descending",
    "order_by_down": "size,ascending",
    # Lanes A and B are opposite directions and the link is full duplex, so
    # serializing them left one direction idle for the whole of the other's
    # run (AUDIT_2 P7). Set false to go back to strictly-serial passes.
    "concurrent_lanes": True,
    # clone_directory_tree is fully redundant once the structure exists;
    # running it every pass was three full destination traversals per
    # project per pass (AUDIT_2 P10). 0 disables the periodic re-clone.
    "structure_clone_every_n_passes": 10,
    # "none" = leave every selected Syncthing folder unpaused (lane C then
    # runs continuously alongside A/B); "rotate" = the original
    # pause-all-but-current scheme, which cost N(N-1) config commits and a
    # full rescan per unpause, and could leave a project's small files
    # unsent for ~50 minutes (AUDIT_2 P4).
    "lane_c_pause_scheme": "none",
    "lane_c_max_folder_concurrency": 2,
    # Killed uploads leave <name>.partial on the NAS and lane A never
    # deletes, so they accumulate forever (AUDIT_2 P8). This only REPORTS
    # them. 0 disables the scan.
    "orphan_scan_every_n_passes": 20,
    # Express lane A: a watchdog event uploads just that file immediately
    # instead of waiting for the sequencer to rotate round to its project,
    # which took minutes at best and a whole pass at worst (AUDIT_2 P9/C-2).
    # Upload-only (copy --ignore-existing with an explicit file list), so it
    # runs alongside the periodic pass without a delete verb between them.
    "express_upload_enabled": True,
    # Window over which watchdog events are batched. Falls back to
    # watch_debounce_seconds, which managed mode otherwise ignored entirely.
    "express_debounce_seconds": 10.0,
    # Paths per window; a bigger burst (a card ingest) is left to the
    # periodic pass rather than shipped as one enormous express run.
    "express_max_batch": 200,
    "syncthing_url": "http://127.0.0.1:8384",
    "syncthing_api_key": "",
    # Restart a dead local Syncthing (SYNC-17, 2026-08-18). Nothing else on
    # an editor machine does: the Windows Run key fires at LOGON and never
    # again, and a session that ends takes the daemon with it -- one editor
    # spent eighteen hours with lane C carrying nothing and the dashboard
    # green. false leaves the engine alone; lane C still reports the error.
    # See sync/syncthing_supervisor.py.
    "supervise_syncthing": True,
    # The server tree's SMB path for the tray's "Grade from server
    # originals" P: swap (drive_swap.py). Empty = take it from the cached
    # site manifest's smb_unc (_apply_site_manifest), else derive it from
    # dashboard_url + remote_root (app._server_p_unc), so the feature is on
    # fleet-wide by default; set a UNC to override both, "off" to disable.
    "server_p_unc": "",
    # Expected Syncthing folder ID per entry in `projects` (addition; needed
    # to fulfil "verify the expected folder ID ... is configured + shared").
    # Leave empty to skip the folder-id check for a project.
    "syncthing_folder_ids": [],
    "rclone_path": "rclone",
    "log_path": "~/.ccsync/companion.log",
    "log_level": "INFO",
    # Crash reports (addition; COMMERCIAL_READINESS.md item 13, 2026-08-17).
    # crash_report.py ALWAYS writes ~/.ccsync/crashes/<ts>.json locally -- no
    # switch, no network, that is just a better log tail. These two keys govern
    # only the OPT-IN network sender, and both are required: `true` with no DSN
    # sends nowhere, because there is no vendor endpoint compiled in. The
    # sender also needs `sentry_sdk`, which the frozen build does not ship.
    "crash_reporting": False,
    "crash_dsn": "",
    # Dashboard reporter (addition; not in SPEC.md's config list) -- posts
    # lane statuses to a server-side dashboard so an admin can see editor
    # health without remoting in. It used to default to ONE deployment's
    # tailnet address, which meant a companion nobody had configured tried to
    # phone that home (2026-08-17, docs/SYNOLOGY_PORT_PLAN.md WP0). BLANK now:
    # a companion with no dashboard_url talks to nothing at all, and the
    # installer/wizard writes the site's own URL here. "" also stays the
    # documented way to disable reporting entirely (the reporter thread isn't
    # even started) -- see validate_config, which says so out loud when
    # require_login is on.
    "dashboard_url": "",
    "dashboard_token": "",
    # The PER-EDITOR fleet token, if this machine has been handed one
    # (COMMERCIAL_READINESS.md item 15, 2026-08-17). Blank = fall back to the
    # shared `dashboard_token` above. Wherever both exist this one wins --
    # identity.preferred_report_token owns the precedence, and the tray's
    # sign-in never overwrites it.
    "report_token": "",
    # Login gate (addition; see identity.py): when true, the companion will
    # not start sync lanes/the sequencer, nor report under an identity,
    # until the editor signs in (tray "Sign in...") with their TrueNAS
    # username+password and the dashboard verifies it. The watcher, popup
    # fixer, and tray itself still run pre-sign-in so the editor can sign
    # in in the first place. Set false to fall back to the old
    # trust-editor_name-blindly behavior.
    "require_login": True,
    "dashboard_report_interval": 60,
    # Faster report cadence used while any sync lane is actively syncing, so
    # the dashboard's live transfer progress feels responsive (addition;
    # see reporter.py's _select_interval). The heavier local_manifest/
    # media_tree payload sections still only go out at most every
    # dashboard_report_interval seconds even on these fast ticks.
    "dashboard_report_interval_active": 5,
    # How often manifest.ManifestCache rescans local_root for the local
    # disk media manifest (addition; see manifest.py). Runs on its own
    # background thread -- never scanned inline on a report tick.
    "manifest_refresh_interval": 300,
    # How often app.CompanionApp rescans the Resolve media pool for the BIN
    # tree reported as "media_tree" (addition; see app.py:get_media_tree).
    # Runs on its own background thread -- never scanned inline on a report
    # tick.
    "media_tree_refresh_interval": 120,
    # Managed mode (addition; active only when dashboard_url is set): the
    # dashboard decides WHICH projects this editor has and in what order,
    # and the sequencer (sync/sequencer.py) syncs them one at a time rather
    # than the whole tree continuously. selection_poll_interval controls
    # how often the sequencer re-fetches that ordered list; how long it
    # waits for a project's Lane C (Syncthing) sync to settle before moving
    # on regardless; and how long it idles between full passes once every
    # selected project is caught up.
    "selection_poll_interval": 60,
    "project_rotation_seconds": 600,
    "sequencer_idle_seconds": 60,
    # How long selection.SelectionClient may serve the last dashboard
    # response from memory before going back to the network, and the longer
    # TTL for the sticky project_roots destination mapping. Both were read
    # via cfg.get(..., 30/300) with no entry here, in the template, or in
    # validate_config -- undiscoverable, and a hand-edited string raised
    # inside SelectionClient.__init__ i.e. inside CompanionApp construction,
    # which on the windowed exe means no tray and no log line (the same
    # class as S-10/CORE-M4).
    "selection_fetch_ttl": 30,
    "project_roots_ttl": 300,
    # False on the base rig (direct LAN access to the NAS): it reads proxies
    # straight off the share, so mirroring them locally is pure waste.
    "lane_b_enabled": True,
    # False = never repoint a clip's proxy attachment at the synced copy in
    # the tree. On by default: a project built elsewhere carries absolute
    # proxy paths (G:\Temp Transfer, F:\Resolve Renders in Place, the base
    # rig's legacy T:) that exist on no editor's machine, and an explicit
    # stale path beats SPEC.md:40's adjacent-Proxy auto-link -- so the clip
    # goes Media Offline next to a perfectly good proxy. See proxy_relink.py.
    "proxy_relink_enabled": True,
    # -- missing-proxy notifier + ffmpeg proxy generator -------------------
    # False = never mention proxy gaps. On by default, on every machine: lane
    # B is the only path that carries video DOWN to the rest of the fleet and
    # it only carries **/Proxy/**, so an original with no sibling
    # <dir>/Proxy/<stem>.mov|.mp4 is invisible to everyone but the machine it
    # sits on -- and until this existed, nothing told anyone. Telling costs
    # nothing and never touches a byte.
    "proxy_notify_enabled": True,
    # TRI-STATE, and None is the interesting value: absent/None derives
    # `not lane_b_enabled` (on where the result lands on the NAS, off where
    # lane B would sweep it away), true/false is obeyed verbatim. See
    # proxy_generation_enabled() for the whole reason.
    "proxy_gen_enabled": None,
    # Never bundled with the companion (80-120 MB on every upgrade). Since
    # 2026-08-16 the sidecar (sidecar_tools) installs a pinned static
    # ffmpeg+ffprobe into the tools dir when local YouTube downloads are on,
    # and the bare default name falls back to it behind PATH -- so "ffmpeg"
    # resolves on a fresh editor machine too. An explicit path is the
    # editor's own install and is never touched. Absent everywhere just
    # means notifier-only.
    "ffmpeg_path": "ffmpeg",
    # A SECOND full tree walk on top of manifest.ManifestCache's, hence a lazy
    # cadence; the tray's "make them now" forces one immediately.
    "proxy_scan_interval": 900,
    # Seconds away from keyboard/mouse before encoding may start. Encoding
    # stops the instant the user returns -- the scan and the notification are
    # not gated on this at all.
    "proxy_gen_idle_seconds": 300,
    # Settle window: a file still being copied off a card has a fresh mtime.
    # Same idea and the same number as lane_b_min_age_seconds above.
    "proxy_gen_min_age_seconds": 120,
    # Ceiling, not a target -- a 720p original is never upscaled.
    "proxy_gen_max_height": 1080,
    # Matches the FF4-era Resolve-generated proxies the fleet already carries,
    # so a generated proxy and an inherited one look the same in a timeline.
    # Validated by coerce_bitrate(); garbage is logged and ignored.
    "proxy_gen_bitrate": "7M",
    # Attempts on one file before it is skipped for the rest of the session.
    # Deliberately in-process only: a blacklist persisted to disk turns a
    # transient GPU failure into a permanent one.
    "proxy_gen_max_failures": 3,
    # -- item 9's data-safety gates (COMMERCIAL_READINESS.md, 2026-08-17) ---
    # Free space the generator keeps clear on the volume it writes to,
    # whichever of the two is LARGER. Proxies land next to their originals,
    # i.e. on the volume every sync lane and Resolve's own cache share, so
    # filling it stalls far more than proxy generation. 0 disables the gate.
    "proxy_gen_free_space_floor_gb": 20,
    "proxy_gen_free_space_floor_pct": 5,
    # Gap between the two (size, mtime) samples that decide a source has
    # stopped growing. The scan's own sample usually supplies the first one,
    # so this is only waited out for a clip encoded outside a scan. 0 = one
    # sample (the pre-2026-08-17 behaviour; not recommended).
    "proxy_gen_stability_seconds": 5,
    # Rehearsal switches. Both report what WOULD be done and change nothing:
    # `proxy_dry_run` for the generator, `fixer_dry_run` for FIX ALL's copy +
    # relink -- the two largest destructive actions the companion takes, and
    # until 2026-08-17 the only ones with no way to be rehearsed.
    "proxy_dry_run": False,
    "fixer_dry_run": False,
    # How long before the same "clips have no proxy" toast may appear again.
    # A day, so restarts don't re-nag about a gap already decided about.
    "proxy_notify_cooldown_seconds": 86400,
    # Off by default: the idle gate already covers a Resolve the user is
    # sitting in front of. On for a machine that leaves UNATTENDED renders
    # going, which idleness cannot see (it looks exactly like being away).
    "proxy_gen_skip_while_resolve_running": False,
    # -- b-roll ingest (docs/BROLL_INGEST_PLAN.md, 2026-08-18) -------------
    # Drag clips onto the dashboard's b-roll page and THIS machine indexes
    # them: ffmpeg, then a local Qwen3-VL, then rclone to the NAS. On by
    # default and still inert on every machine nobody drops anything on --
    # the orchestrator claims nothing until a batch is handed to it.
    "broll_ingest_enabled": True,
    # Seconds away from keyboard/mouse before a batch in "only when idle"
    # mode may crunch. Defaults to the proxy generator's number because it is
    # the same judgement about the same machine; a batch run in FOREGROUND
    # mode ignores this gate entirely (owner review (b)).
    "broll_ingest_idle_seconds": 300,
    # Stand down while Resolve is open. TRUE here where the proxy
    # generator's equivalent is false: this feature wants 4-12 GB of VRAM for
    # llama-server, which is exactly what a Resolve timeline is using.
    # Idle-mode batches only -- foreground means the editor asked for it now.
    "broll_ingest_skip_while_resolve": True,
    # Free space kept clear where clips are staged. Same floor and the same
    # reasoning as proxy_gen_free_space_floor_gb: staging is inside the tree.
    "broll_ingest_free_space_floor_gb": 20,
    # How many ffmpeg children one batch may run at once. Two, not four: the
    # describe stage owns the GPU and a wide encode beside it just makes both
    # slower.
    "broll_ingest_max_concurrent_ffmpeg": 2,
    # Override for where clips are staged. Blank = inside the archive
    # (<local_root>/Assets/B-roll Archive/.ingest). The BASE RIG needs this:
    # its local_root IS the NAS share, so staging there pushes every original
    # over SMB twice.
    "broll_ingest_staging_dir": "",
    # Hand the BRAW/R3D/CRM gap to the Blackmagic Proxy Generator once the
    # ffmpeg queue is empty (see bpg.py). Tri-state like proxy_gen_enabled:
    # None derives "wherever this machine generates proxies AND has BPG
    # installed", which is the base rig and nowhere else.
    "bpg_enabled": None,
    # "" = find it at Resolve's install path. BPG is not a separate binary;
    # this is Resolve.exe, launched with -pg.
    "bpg_path": "",
    # Add the folders holding unproxied BRAW/R3D/CRM to BPG's own watch list
    # before starting it. On by default because the alternative is what the
    # base rig did for months: start a watcher whose list was empty, three
    # times a day, and never close the gap (bpg.py fact 3, 2026-08-13).
    # Additive only -- an entry the editor added is never removed or rewritten,
    # and the file is backed up once before the first change.
    "bpg_manage_watch_folders": True,
    # Press Start in BPG's window once it is up. Its queue does NOT start
    # itself and there is no flag for it (fact 4), so a False here means an
    # editor has to click Start by hand for anything to encode.
    "bpg_autostart": True,
    # "" = %APPDATA%\Blackmagic Design\... . An override for a machine whose
    # BPG keeps its settings somewhere else; nothing in the fleet needs it yet.
    "bpg_settings_path": "",
    # -- YouTube auto-import (youtube_import.py) ---------------------------
    # False = never import downloaded YouTube clips into Resolve. On by
    # default: the dashboard's YouTube page downloads into
    # <project>/Youtube/<term>/, sync delivers it, and without this the editor
    # has to find the folder and drag it in -- which is the whole point of
    # having asked for the clips from inside the system. Reads the tree and
    # the media pool; never moves, renames or deletes a file.
    "youtube_import_enabled": True,
    # How often (seconds) the open project's Youtube folder is re-listed. A
    # one-level listdir per term folder, not a tree walk, so this can be
    # eager compared with proxy_scan_interval -- clips arrive while the editor
    # is sitting there waiting for them.
    "youtube_import_scan_interval": 60,
    # Settle window: same idea and the same number as
    # proxy_gen_min_age_seconds. A file rclone/Syncthing is still writing has
    # a fresh mtime, and importing half a video makes an offline clip.
    "youtube_import_min_age_seconds": 120,
    # Files handed to Resolve in one call, per term folder, per cycle. This is
    # what bounds how long the import holds _API_LOCK -- the watcher polls
    # every 3 s behind it -- so a 300-clip drop arrives over several cycles
    # instead of freezing the tray for one long one.
    "youtube_import_batch_limit": 20,
    # Attempts on one file before it is left alone for the rest of the
    # session. In-process only, exactly like proxy_gen_max_failures: a refusal
    # remembered on disk turns one bad evening into a file that never imports
    # again. Resolve being closed or the project having changed is a STATE,
    # not a failure, and never counts against this.
    "youtube_import_max_failures": 3,
    # -- local YouTube downloads (ytdlp_manager.py) ------------------------
    # False = this machine never downloads YouTube clips itself; the dashboard's
    # server-side worker does it, exactly as it always has. On by default (plan
    # §13 Q3: absent means opted in) -- the requester's own residential IP is
    # what YouTube is least hostile to, and clips born on the requester's
    # machine reach them with no NAS round trip. The key exists for an editor on
    # a metered or tethered link. With it false the sidecar manager below does
    # NOTHING: no binary is downloaded, nothing is checked, no thread starts.
    "ytdl_local_downloads": True,
    # "" = the companion manages its own yt-dlp under
    # %LOCALAPPDATA%\ccsync\tools (macOS: ~/Library/Application Support/ccsync/
    # tools), installing it once and letting `yt-dlp -U` keep it current --
    # yt-dlp needs updating every few weeks (YouTube breaks it deliberately)
    # and the companion's own release cadence is months for some machines, so
    # the downloader must not be bundled with it. Set this to a yt-dlp you
    # manage yourself (a brew install, a nightly) and the companion only ever
    # READS its version: it never installs over it and never runs -U against it.
    "ytdlp_path": "",
    # A Netscape cookies.txt exported from a signed-in YouTube session, or "".
    # Set = the local downloader sends it (yt-dlp --cookies), which is what
    # lets an editor's machine pass the bot check and download age-gated
    # clips instead of falling back to the server (2026-08-16). Deliberately
    # a FILE, never --cookies-from-browser: Chrome's app-bound encryption
    # defeats live-browser extraction on Windows, and reading a browser
    # profile the editor is using rotates the session out from under them.
    # Export it from a private window and DON'T use YouTube in that session
    # afterwards (docs/YTDL_LOCAL_DOWNLOAD.md). Absent = anonymous local
    # downloads, exactly as before -- fine for public clips, and age-gated
    # ones fall back to the server (which has its own signed-in cookies).
    "ytdl_cookies_file": "",
    # False = leave Resolve's LUT directory alone. On by default: syncing the
    # shared LUT library to <local_root>/Assets/Luts accomplishes nothing on
    # its own, because Resolve reads LUTs from its own fixed directory and
    # from nowhere else. The companion turns that directory into a link to
    # the library (merging anything only this machine had into it first, and
    # keeping the original renamed aside). See luts.py.
    "lut_sync_enabled": True,
    # Where Resolve's OWN LUT directory is -- the one "Open LUT Folder"
    # drops a LUT into, and so where strays collect. Blank = the platform
    # default (%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\LUT on
    # Windows, /Library/Application Support/... on macOS). Only needed for a
    # non-standard Resolve install.
    "resolve_lut_dir": "",
    # The exact string written into Resolve's LUT Locations list. Blank =
    # the canonical P:\Assets\Luts on Windows (identical on every editor's
    # machine, which is what keeps a LUT reference portable) and the real
    # local path on macOS, which has no P:.
    "lut_location_override": "",
    # False = never re-scan Resolve's LUT list behind the editor's back.
    # On by default: Resolve reads its LUT locations ONCE at startup, so an
    # editor who opens it before P: has finished mapping loses the shared
    # library for that whole session while the preference still reads
    # correctly -- the symptom is "LUTs missing" plus a per-frame "Failed to
    # read Shaper LUT" in Resolve's log. See luts.stale_lut_index().
    "lut_index_repair_enabled": True,
    # Resolve's own log, which is where that startup miss is visible. Blank =
    # the platform default. Only needed for a non-standard install.
    "resolve_log_override": "",
    # False = leave Resolve's gallery where it is. On by default: Resolve
    # derives the gallery directory from a media storage entry, which is a
    # different disk on every machine, and machines sharing a project
    # database are expected to agree -- that disagreement is the "stills
    # location is not the same" complaint at launch. See stills.py.
    "stills_sync_enabled": True,
    # How often the LUT link is re-checked, seconds. Not once-at-startup: a
    # Resolve UPGRADE deletes the link and writes a fresh factory LUT
    # directory in its place, silently detaching that machine from the shared
    # library until someone noticed. Steady state is one lstat.
    "lut_check_interval": 900,
    # False = shut down silently even mid-upload. On by default: Windows'
    # own "this app is preventing you from shutting down" screen carries the
    # warning, and the editor keeps a "Shut down anyway" button. Nothing is
    # lost either way -- but rclone cannot resume an SFTP upload, so the
    # file in flight restarts from zero. See shutdown_guard.py.
    "shutdown_warning_enabled": True,
    # False = let the machine idle into sleep mid-upload. On by default:
    # sleep sends no WM_QUERYENDSESSION, so the shutdown warning above never
    # sees it, and an overnight upload is likelier to die this way than to
    # be switched off deliberately. Holds the SYSTEM idle timer only -- the
    # screen still blanks -- and cannot stop a deliberate Start -> Sleep or
    # a closing lid. See shutdown_guard.py.
    "keep_awake_while_syncing": True,
    # The liveness bound BOTH power guards above apply before a lane counts
    # as a reason to stay on (shutdown_guard.PendingTracker). A lane reports
    # "syncing" from a NEED COUNT, not from bytes arriving, so without these
    # a NAS that went away overnight held the idle timer forever and put
    # "still syncing" on every shutdown screen with nothing in flight.
    #
    # keep_awake_stale_seconds: how long a lane may report the SAME backlog
    # -- no change in state/queued/bytes/last_sync -- before it is treated as
    # stalled rather than transferring. Too low and a slow single-file
    # transfer whose counters tick rarely reads as stalled; too high and a
    # dead link keeps the machine awake for that long after every drop.
    "keep_awake_stale_seconds": 180.0,
    # keep_awake_max_hold_seconds: the backstop staleness cannot see -- a
    # lane whose numbers churn but never finish (rclone wedged in SFTP
    # retries). After this much CONTINUOUS blocking both guards stand down
    # until the lanes actually settle. Raise it on a machine that genuinely
    # uploads for longer than this in one unbroken run.
    "keep_awake_max_hold_seconds": 8 * 3600.0,
    # False = no sync lanes at all: the machine works directly off the NAS
    # share (base rig). The companion still runs the timeline watcher, popup
    # fixer, and dashboard reporter; lanes report idle with a "disabled"
    # detail instead of running.
    "sync_enabled": True,
    # False = never show the media-outside-tree popup (base rig: all raw
    # media legitimately lives outside/next to the tree, so the popup is
    # noise there). Out-of-tree clips are still logged.
    "popup_enabled": True,
    # False = never warn that Resolve is running with its scripting server
    # dead. On by default, and it REPEATS (every
    # resolve_scripting_warning_interval seconds) unlike everything else
    # here: the editor cannot see this state -- Resolve is on screen looking
    # normal while every companion feature that needs it is silently gone --
    # and it never heals on its own (Resolve does not retry a script server
    # that failed at launch). Cost an editor a full session, 2026-08-12.
    "resolve_scripting_warning": True,
    # Seconds between those warnings, and also how long the state must have
    # held before the FIRST one -- Resolve's script server takes a moment to
    # come up, and a dialog three seconds into every Resolve launch teaches
    # editors to dismiss the one warning that matters. 0 or less switches it
    # off, same as the flag above.
    "resolve_scripting_warning_interval": 300,
    # False = don't restart the companion when the Resolve it was connected
    # to exits. On by default (added with the 2026-08-12 fixes): fusionscript
    # keeps process-global IPC state, and a stale client can wedge the NEXT
    # Resolve session's scripting server for every client on the machine --
    # the state the warning above exists to report. The safe moment to shed
    # it is while Resolve is down. See app._maybe_recover_stale_bridge.
    "bridge_auto_restart": True,
    # False = don't serve the b-roll web UI's "Send to Resolve" button. On by
    # default: that button is what the b-roll library is FOR from an editor's
    # seat, and it used to require a SECOND tray app (the standalone
    # broll-companion, absorbed here and retired 2026-08-10) that nobody kept
    # upgraded. Failing to take the port is never fatal to anything else --
    # see broll_server.start().
    "broll_server_enabled": True,
    # The port the b-roll web page's JS calls. Pinned on the page's side too
    # (broll/web/static/app.js's COMPANION_URL), so moving it here alone just
    # switches the feature off.
    "broll_server_port": 8899,
    # How long (seconds) a dismissed-without-acting out-of-tree clip is
    # snoozed before the passive watcher will pop it again (addition; see
    # app.py's _popup_snooze). Was previously read via cfg.get(..., 300)
    # with no entry here/in the template/validate_config, so it was
    # undiscoverable and a bad hand-edited value raised inside __init__
    # before logging existed (see S-10).
    "popup_snooze_seconds": 300,
    # Machine role: "editor" (default -- full sync lanes) or "base" (the
    # central machine with direct NAS access: implies sync_enabled false
    # unless the file sets it explicitly; the out-of-tree popup stays ON so
    # stray media still gets fixed into the tree).
    "mode": "editor",
    # Resolve project names (case-insensitive) the companion pretends not to
    # see: not reported to the dashboard, never trigger the new-project
    # prompt, and their clips never raise the out-of-tree popup. For scratch
    # and utility projects -- Resolve's default "Untitled Project", and
    # whatever project the Blackmagic Proxy Generator's Resolve process has
    # open (a BPG rig otherwise nags about its own helper project; seen live
    # 2026-07-25 as recurring "New Doc" popups on the base rig).
    # Each entry matches its own numbered duplicates too ("New Doc 1",
    # "New Doc 2", "Untitled Project (3)") -- see is_ignored_project().
    "ignored_resolve_projects": ["Untitled Project", "New Doc"],
}

# Profile defaults applied by load_config when mode is set and the file does
# not override the key explicitly. Note base keeps the popup ON: a careless
# base editor can still cut in media from outside the tree on T:, and those
# clips won't reach remote editors until fixed into the project directory.
MODE_PROFILES: dict[str, dict[str, Any]] = {
    "editor": {},
    # lane_b_enabled=False is not redundant with sync_enabled=False, even
    # though no lane starts on a base rig either way: proxy_generation_enabled
    # derives itself from lane_b_enabled ALONE, and the shipped default for
    # that key is True. Without this line the base rig -- the one machine the
    # generator exists for, whose local_root IS the NAS tree -- derives
    # generation OFF, queues every missing proxy, encodes none of them, and
    # toasts "Ask your admin to generate proxies for them" at the admin.
    # Observed on the base rig 2026-08-10 with 1046 clips queued.
    "base": {"sync_enabled": False, "lane_b_enabled": False},
}

DEFAULT_TOML_TEXT = """\
# ccsync-companion config
# See companion/README.md for the full reference. Restart the companion
# after editing this file.

# Your name/handle, used to build the "B-roll/Editor Added/<editor_name>"
# destination suggested by the popup fixer.
editor_name = ""

# Absolute path to this machine's local copy of the project tree, e.g.
# "C:\\\\Creators_Club" (Windows), "/Volumes/<SSD>/Creators_Club" (macOS on an
# external drive -- the usual macOS setup) or "/Users/you/Creators_Club".
local_root = ""

# The canonical shared-drive prefix used in Resolve's stored clip paths
# (Windows: the "P:" virtual drive letter from SPEC.md's Path canon). Used
# to detect BAD_PREFIX (mapping-health) situations. KEEP "P:\\" ON macOS TOO:
# it is the string every Resolve project in the fleet actually stores, and a
# Mac reaches it through Resolve's own Mapped Mount preference (which the
# installer sets) rather than through a drive letter. Changing it here makes
# this machine's projects unopenable everywhere else.
canonical_prefix = "P:\\\\"

# OPTIONAL override for the tray's "Grade from server originals" P: swap.
# WINDOWS ONLY -- macOS has no drive namespace to remap, so this key does
# nothing there and the tray item does not appear.
# By default the server tree's SMB path comes from the dashboard's site
# manifest (GET /api/v1/site -> smb_unc), and failing that is derived from
# dashboard_url's host + remote_root's path -- so the feature just works on
# every install. Set an explicit UNC here to override both, or "off" to hide
# the feature on this machine.
# server_p_unc = ""

# Name of the rclone remote pointing at the NAS. Must match the stanza the
# bootstrap installer wrote into rclone.conf. ccsync-companion does not
# configure rclone remotes for you. The installer takes this name from the
# dashboard's site manifest (GET /api/v1/site -> rclone_remote) and falls
# back to "ccsync_sftp" when the dashboard doesn't publish one; blank here
# means nothing syncs and the companion says so at startup.
remote = ""

# ABSOLUTE path on the NAS under which project trees live, e.g.
# "/mnt/<pool>/<share>/<tree>" (TrueNAS) or "/volume1/<share>/<tree>"
# (Synology). It must be absolute: the SFTP session starts in your home
# directory on the NAS, so a relative value resolves under ~/ and will not
# find the project tree.
remote_root = ""

# WHICH PROJECTS SYNC is decided on the dashboard, by your ticks -- not
# here. The sequencer works through the ticked projects ONE AT A TIME; the
# tree is not replicated as a whole. These two keys are leftovers from the
# pre-dashboard mode: `projects` only pairs positionally with
# syncthing_folder_ids below, and `active_project` only supplies the folder
# the popup fixer suggests for media you add yourself.
projects = []
active_project = ""

# Resolve timeline poll interval, in seconds.
poll_interval = 3

# Lane A (video originals, up) periodic full-pass interval, in seconds.
scan_interval_up = 300

# Lane B (proxies, down) periodic full-pass interval, in seconds.
scan_interval_down = 120

# Lane B stability gate: don't download a proxy whose mtime is newer than
# this. The Blackmagic Proxy Generator writes each proxy at its FINAL name
# and grows it in place for minutes, so without this lane B ships truncated
# proxies once per pass and sweeps each superseded partial into
# .ccsync-trash. 0 disables the gate.
lane_b_min_age_seconds = 120

# -- lane B circuit breaker + .ccsync-trash retention (item 9, 2026-08-17) --
# rclone's --max-delete 100 / --max-delete-size 20G bounds ONE lane B pass.
# These bound the SEQUENCE: past any of them lane B STOPS on this machine
# (lanes A and C keep running) until someone uses the tray's "Resume proxy
# download". Nothing is ever deleted -- removals become moves into
# .ccsync-trash -- so a trip costs visibility, never footage.
#   lane_b_max_deletes_per_pass     how many files one pass may trash
#   lane_b_max_delete_fraction      ...or this share of the local proxy set,
#                                   whichever is smaller (small projects)
#   lane_b_remote_shrink_fraction   trip when the NAS listing shrinks past
#                                   this share of what it held last pass
# lane_b_max_deletes_per_pass = 50
# lane_b_max_delete_fraction = 0.25
# lane_b_remote_shrink_fraction = 0.5
#
# How long recovery copies are kept in <local_root>/.ccsync-trash, and how
# big that directory may get before the OLDEST batches are dropped. The
# newest batch is never pruned by the size rule, and NOTHING is pruned while
# the breaker above is tripped. 0 disables the age rule / the size cap.
# trash_max_age_days = 14
# trash_max_bytes = 53687091200
# trash_prune_interval_seconds = 21600

# Lane A watchdog file-stability debounce, in seconds.
watch_debounce_seconds = 10

# rclone --transfers (parallel stream count).
transfers = 4

# --- transport tuning ------------------------------------------------------
# All commented out: the values below ARE the defaults. Uncomment to
# override. Set a string to "" or an int to 0 to drop that rclone flag
# entirely.
#
# In-flight SFTP window = chunk_size x concurrency. rclone's SFTP backend
# has no multi-thread upload, so this is the hard per-file speed ceiling
# (window / round-trip time) for a single large original.
# sftp_chunk_size = "255Ki"
# sftp_concurrency = 64
# Parallel SSH connections rclone may open to the NAS.
# sftp_connections = 16
# Parallel same-or-different checks while comparing the two sides.
# checkers = 16
# true skips rclone's post-transfer hash check, which otherwise makes the
# NAS re-read (md5sum) every file it just received or sent.
# rclone_ignore_checksum = true
# Transfer order. Uploads newest-first, downloads smallest-first. "" = none.
# order_by_up = "modtime,descending"
# order_by_down = "size,ascending"
# Run lane A (up) and lane B (down) at the same time -- they are opposite
# directions on a full-duplex link, so serializing them leaves one idle.
# concurrent_lanes = true
# Re-clone the server's empty directory structure only every Nth pass; it
# is redundant once the structure exists. 0 = never re-clone.
# structure_clone_every_n_passes = 10
# "none" leaves every selected Syncthing folder unpaused; "rotate" pauses
# all but the current project (many more config commits + a rescan per
# unpause, and small files can wait a full rotation).
# lane_c_pause_scheme = "none"
# lane_c_max_folder_concurrency = 2
# Report (never delete) orphaned <name>.partial files left on the NAS by
# killed uploads, every Nth pass. 0 = never scan.
# orphan_scan_every_n_passes = 20
# Upload a newly-added clip as soon as it settles, instead of waiting for
# the sequencer to reach its project. Upload-only, runs alongside the
# periodic pass. express_debounce_seconds defaults to watch_debounce_seconds;
# a burst larger than express_max_batch is left to the periodic pass.
# express_upload_enabled = true
# express_debounce_seconds = 10.0
# express_max_batch = 200

# Local Syncthing REST API base URL and API key. Leave syncthing_api_key
# empty to read it from Syncthing's own config.xml (the installer-managed
# ccsync\\syncthing-config home first, else the stock per-OS path).
syncthing_url = "http://127.0.0.1:8384"
syncthing_api_key = ""

# Expected Syncthing folder ID per project (same order/length as `projects`
# above). Leave as [] to skip the folder-id verification.
syncthing_folder_ids = []

# Restart the sync engine when it dies. Nothing else on this machine does:
# the autostart entry runs at logon and never again, so a session that ends
# (a sign-out, a forced restart) leaves Syncthing dead until the next logon
# while everything else comes back. Commented out because the shipped value
# IS the default -- set it to false only to take the engine's lifetime into
# your own hands. Lane C reports the error either way; nothing is restarted
# while syncing is halted or paused. See docs/SYNC_SAFETY.md.
# supervise_syncthing = true

# Path to the rclone binary. Defaults to "rclone" (must be on PATH).
rclone_path = "rclone"

# Log file (rotating). Console logging is always on in addition to this.
log_path = "~/.ccsync/companion.log"
log_level = "INFO"

# Crash reports. A JSON file per unhandled exception is ALWAYS written to
# ~/.ccsync/crashes/ -- locally, and sent nowhere. These two only switch on the
# optional network sender, and BOTH are needed: there is no vendor endpoint
# compiled in, so `true` with an empty crash_dsn still sends nothing.
crash_reporting = false
crash_dsn = ""

# Dashboard reporter: periodically POSTs lane statuses to a server-side
# dashboard so an admin can see editor health without remoting in. Your
# admin's dashboard URL (the installer writes it here; remote editors use
# the tailnet address, a machine on the same LAN can use the LAN one). Left
# blank it disables reporting, managed sync and the tray's "Open dashboard"
# link entirely -- the reporter thread isn't even started. dashboard_token
# is sent as the X-CCSync-Token header; ask the admin for the value.
dashboard_url = ""
# WHO MAY DRIVE THE LOOPBACK API on 127.0.0.1:8899 -- the "Send to Resolve"
# and "Download here" buttons on the b-roll, music and YouTube pages
# (2026-08-17). Only the dashboard's own origin may, and dashboard_url above
# IS that origin, so neither of these is normally needed. Escape hatches, with
# no default; the companion names the first one when it refuses a page.
#   loopback_extra_origins  additional EXACT origins (scheme + host + port),
#                           for editors who browse the dashboard at a name
#                           dashboard_url does not use.
#   loopback_dev_origins    also accept http(s)://127.0.0.1|localhost:*.
# loopback_extra_origins = ["https://nas.example.ts.net"]
# loopback_dev_origins = false
dashboard_token = ""
# Your OWN fleet token, if your admin has minted one for you (dashboard ->
# Admin -> Users -> "report tokens"). It looks like "cce1.<id>.<secret>", it
# identifies YOUR machines rather than the whole fleet, and it can be revoked
# for you alone. Leave blank to use the shared dashboard_token above.
report_token = ""
# Login gate: when true, the companion will not start sync lanes/the
# sequencer, nor report under an identity, until the editor signs in via the
# tray ("Sign in...") with their TrueNAS username+password and the dashboard
# verifies it. The watcher, popup fixer, and tray still run pre-sign-in so
# there's a way to sign in. Set false to trust editor_name above instead.
require_login = true
dashboard_report_interval = 60
# Faster report cadence used while any sync lane is actively syncing, so the
# dashboard's live transfer progress feels responsive. The heavier
# local_manifest/media_tree payload sections still only go out at most every
# dashboard_report_interval seconds even on these fast ticks.
dashboard_report_interval_active = 5
# How often the local disk media manifest (originals/proxies rollup, per
# clip counts+bytes) is rescanned, on its own background thread.
manifest_refresh_interval = 300
# How often the Resolve media-pool BIN tree is rescanned for dashboard
# reporting, on its own background thread.
media_tree_refresh_interval = 120

# Managed mode (active only when dashboard_url above is set, which is the
# default): the dashboard decides WHICH projects this editor has and in what
# order, and a sequencer syncs them ONE AT A TIME. Only ticked projects sync
# -- lanes A and B are not whole-tree mirrors. How often the sequencer
# re-fetches the ordered selection:
selection_poll_interval = 60
# How long (seconds) the sequencer waits for a project's Lane C
# (Syncthing) sync to settle before moving on to the next project anyway:
project_rotation_seconds = 600
# How long (seconds) the sequencer idles between full passes once every
# selected project is caught up (small edits still trickle during this
# window -- every selected folder is unpaused while idle):
sequencer_idle_seconds = 60
# How long (seconds) the last selection response is served from memory
# before the companion asks the dashboard again, and the longer TTL for the
# sticky per-project destination mapping (project_roots) inside it:
selection_fetch_ttl = 30
project_roots_ttl = 300

# Set false on the base rig (direct LAN access to the NAS): it reads proxies
# straight off the share, so lane B's local proxy mirror is pure waste.
# COMMENTED OUT on purpose (S-7): mode = "base" supplies false through
# MODE_PROFILES, and a value written live into every first-run file would
# override the profile and make it dead -- which is how the base rig ended up
# deriving proxy generation OFF (2026-08-10). The default is true; uncomment
# only to pin it against the profile.
# lane_b_enabled = true

# Repoint a clip's PROXY at the copy in the tree when the project's stored
# proxy path is stale (built on another machine, e.g. a temp transfer drive) or
# was never linked. Only ever repoints -- never copies, moves or deletes.
# Set false to leave every proxy attachment exactly as the project stores it.
proxy_relink_enabled = true

# Say when clips in your projects have no proxy. Lane B is the only path that
# carries video DOWN to the other machines, and it only carries Proxy folders
# -- so an original with no Proxy/<name>.mov or .mp4 beside it is invisible to
# every editor but you, and nothing used to say so. Reporting only; no file is
# read, written or moved by this.
proxy_notify_enabled = true

# Make the missing proxies here, with ffmpeg, while you are away from the
# machine. THREE-STATE, and left commented out on purpose: absent means
# "decide from lane_b_enabled" -- on where lane B is off (the base rig, whose
# local_root IS the NAS tree, so a proxy made there fans out to everyone), off
# where lane B is on (every editor). That is not a taste call. Lane B is
# `rclone sync`, the one verb that DELETES local files: a proxy generated here
# for a project that syncs does not exist on the NAS, so the next lane-B pass
# files it into .ccsync-trash and the encode was for nothing. Uncomment to
# generate anyway -- proxies for projects lane B never touches do survive --
# and note the notifier above runs either way.
# proxy_gen_enabled = true

# The ffmpeg binary. The companion does not ship it (it would double the size
# of every upgrade), but with local YouTube downloads on it installs a pinned
# static ffmpeg+ffprobe beside yt-dlp on first run and the default name below
# finds that copy when nothing on PATH answers. Give an absolute path to use
# your own install instead; the companion never touches that one.
ffmpeg_path = "ffmpeg"

# How often (seconds) the tree is walked looking for originals with no proxy.
# This is a SECOND full walk on top of the media manifest's, hence a quarter
# hour rather than anything eager -- the tray's "make them now" forces one.
proxy_scan_interval = 900

# How long (seconds) the keyboard and mouse must have been still before
# encoding starts. It stops the instant you come back, mid-clip, and leaves no
# part-file behind. ONLY encoding waits for this -- the scan and the notice
# never do. A machine that cannot tell whether you are idle encodes nothing at
# all: a missing proxy beats ffmpeg running under your hands.
proxy_gen_idle_seconds = 300

# Skip a file whose mtime is newer than this (seconds) -- it is still being
# copied off a card or written by a render. Same settle window, for the same
# reason, as lane_b_min_age_seconds above.
proxy_gen_min_age_seconds = 120

# The rest of the generator's knobs. The values shown ARE the defaults and are
# commented out for the same reason as the transport tuning above: an explicit
# value in every first-run file pins it, so a later re-tune would reach nobody.
# Height ceiling, never an upscale -- a 720p original stays 720p.
# proxy_gen_max_height = 1080
# Bitrate for the HEVC 10-bit proxies, chosen to match the Resolve-generated
# proxies the fleet already carries. Anything that isn't a number optionally
# followed by K or M is logged and ignored.
# proxy_gen_bitrate = "7M"
# Attempts on one file before it is left alone for the rest of the session.
# Never remembered across restarts -- a blacklist on disk would turn a
# transient GPU failure into a permanent one.
# proxy_gen_max_failures = 3
# Free space kept clear on the volume the proxies are written to, whichever of
# the two is larger. Proxies land next to their originals -- the same volume
# every sync lane and Resolve's own cache share -- so filling it stalls far
# more than proxy generation. 0 disables the check.
# proxy_gen_free_space_floor_gb = 20
# proxy_gen_free_space_floor_pct = 5
# Seconds between the two (size, mtime) samples that decide a source has
# stopped growing. rclone and every card copier set the mtime when they CREATE
# a file, so a transfer in flight can look settled while its size is still
# climbing -- and ffmpeg would then make a proxy of half an interview. The
# scan's own sample usually supplies the first one, so this is rarely waited
# out. 0 = one sample (the pre-2026-08-17 behaviour; not recommended).
# proxy_gen_stability_seconds = 5
# Rehearsal: report every clip that WOULD be encoded and encode nothing.
# proxy_dry_run = false
# Rehearsal for FIX ALL: report what would be copied and where each clip would
# be relinked, and copy/relink nothing. Read once at startup.
# fixer_dry_run = false
# How long (seconds) before the same "clips have no proxy" notice may appear
# again. A day, so a restart doesn't re-nag about a gap you already know about.
# proxy_notify_cooldown_seconds = 86400
# Stand down completely while Resolve is running. Off by default: the idle
# gate already covers a Resolve you are sitting in front of. Turn it on if you
# leave UNATTENDED renders going, which idleness cannot see.
# proxy_gen_skip_while_resolve_running = false

# -- b-roll ingest ----------------------------------------------------------
# Drag clips onto the dashboard's b-roll page and THIS machine indexes them:
# ffmpeg makes the proxy, sprite, poster and the frames, a local Qwen3-VL
# describes them, and rclone puts the results in the archive on the NAS. It
# claims nothing until somebody drops something, so leaving it on costs a
# machine that never ingests exactly nothing.
# broll_ingest_enabled = true
# Seconds away from the keyboard before an "only when idle" batch may crunch.
# A batch run in FOREGROUND mode ignores this and the Resolve gate below.
# broll_ingest_idle_seconds = 300
# Stand down while Resolve is open. ON here, unlike the proxy generator's
# equivalent: indexing wants 4-12 GB of VRAM for the local model, which is
# what the timeline you left open is using.
# broll_ingest_skip_while_resolve = true
# Free space kept clear where clips are staged (staging is inside the tree).
# broll_ingest_free_space_floor_gb = 20
# ffmpeg children one batch may run at once. The describe stage owns the GPU;
# a wider encode beside it just makes both slower.
# broll_ingest_max_concurrent_ffmpeg = 2
# Where clips are staged. "" = inside the archive
# (<local_root>/Assets/B-roll Archive/.ingest). THE BASE RIG NEEDS THIS SET:
# its local_root is the NAS share, so staging there sends every original over
# SMB twice.
# broll_ingest_staging_dir = ''

# Let the Blackmagic Proxy Generator make the proxies ffmpeg cannot: BRAW, R3D
# and CRM are counted and reported but never queued here, because ffmpeg cannot
# decode them at any quality. BPG is started only once the ffmpeg queue is
# EMPTY (one GPU, one encoder at a time) and only while you are away, and is
# never stopped by us -- it is left to finish whatever it began.
# Commented out because the default is derived, exactly like proxy_gen_enabled:
# on wherever this machine already generates proxies and BPG is installed.
# bpg_enabled = true
# bpg_path = 'C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\Resolve.exe'
# BPG watches FOLDERS -- it takes no file list -- and it does not start its own
# queue. Both of these are on by default, because with either one off a
# generator can be up with your BRAW sitting there and nothing encoding, which
# is exactly what the base rig did for months. The watch list is only ever
# ADDED to (your own entries are never removed or rewritten, and the file is
# backed up once before the first change), and Start is only ever pressed when
# the button says "Start" -- never Stop.
bpg_manage_watch_folders = true
bpg_autostart = true
# "" = %APPDATA%\\Blackmagic Design\\... . Only for a BPG that keeps its
# settings somewhere else.
# bpg_settings_path = ''

# Import clips downloaded by the dashboard's YouTube page into the project you
# have open, under Master > Youtube > <search term>. They arrive on this
# machine in <project>\\Youtube\\<term>\\ like any other synced media; this just
# saves you finding the folder and dragging it in. Only ever ADDS media pool
# items -- nothing on disk is moved, renamed or deleted, and a clip already in
# the pool (in any bin, even one you moved it to) is never imported twice.
youtube_import_enabled = true
# How often (seconds) that folder is re-listed while the project is open.
youtube_import_scan_interval = 60
# Skip a file whose mtime is newer than this (seconds), and one whose size is
# still changing: it is still arriving, and half a video imports as an offline
# clip. Same settle window as proxy_gen_min_age_seconds above.
youtube_import_min_age_seconds = 120
# The rest of the importer's knobs, commented out for the same reason as the
# generator's above -- the values shown ARE the defaults.
# How many files are handed to Resolve in one go, per term folder, per cycle.
# The rest follow on the next one; this is what keeps a big drop from freezing
# the tray while Resolve chews through it.
# youtube_import_batch_limit = 20
# Attempts on one file before it is left alone for the rest of the session.
# Never remembered across restarts. Resolve being closed, or you having
# switched project, is not an attempt.
# youtube_import_max_failures = 3

# Download the YouTube clips YOU asked for on THIS machine, instead of the
# server downloading them and syncing them to you. Your own connection is the
# one YouTube is least suspicious of, and the clips land in your tree with no
# round trip through the NAS. Set false to always leave the downloading to the
# server (an editor on a metered or tethered link); nothing else changes -- the
# search, review and history pages are the same either way.
ytdl_local_downloads = true
# "" = the companion looks after its own copy of yt-dlp, under
# %LOCALAPPDATA%\\ccsync\\tools (macOS: ~/Library/Application Support/ccsync/
# tools), and keeps it current on its own -- yt-dlp has to be updated every few
# weeks because YouTube deliberately breaks it, which is exactly why it is not
# built into this app. Point this at a yt-dlp you install and update YOURSELF
# and the companion will only read its version: it never installs over your
# binary and never runs `yt-dlp -U` against it.
ytdlp_path = ""

# A cookies.txt exported from a signed-in YouTube session (Netscape format).
# Set this and YOUR downloads use it: it is what passes YouTube's bot check
# and unlocks age-restricted clips on this machine, instead of handing those
# jobs back to the server. Leave it "" for anonymous downloads (public clips
# work fine; age-gated ones fall back to the server). Export it from a
# Firefox/Chrome "cookies.txt" extension in a PRIVATE window, signed in to
# the account you want to use, and don't browse YouTube in that window
# afterwards or the session rotates and the file goes stale. The tray's
# "Sign in to YouTube (for downloads)…" writes this for you.
ytdl_cookies_file = ""

# The shared LUT library. LUTs sync to <local_root>/Assets/Luts like any other
# asset, but Resolve only reads the LUT directories it has been told about, so
# the companion adds the library to Resolve's own supported list (Preferences >
# System > General > LUT Locations). Nothing on disk is moved, renamed or
# linked, and Resolve's factory LUTs are untouched. Only writable while Resolve
# is QUIT -- it rewrites its own preferences on exit.
lut_sync_enabled = true
# Resolve's OWN LUT folder, where the tray looks for LUTs this machine has and
# the library does not. Blank = the standard location for this platform.
resolve_lut_dir = ""
# Blank = the canonical P:\\Assets\\Luts on Windows, the real local path on Mac.
lut_location_override = ""
lut_check_interval = 900
# Resolve reads its LUT locations ONCE at startup. Open it before P: has
# finished mapping and the shared library is missing for that entire session,
# with the preference still reading correctly -- "LUTs missing", and a
# "Failed to read Shaper LUT" per rendered frame. The companion spots that in
# Resolve's log and re-scans the list in place, no restart. False to disable.
lut_index_repair_enabled = true
# Resolve's own log file. Blank = the standard location for this platform.
resolve_log_override = ""

# Point Resolve's gallery (stills + PowerGrades) at the shared, synced folder
# so every machine agrees on where stills live -- the disagreement is what
# Resolve complains about at launch when machines share a project database.
# Also only writable while Resolve is QUIT.
stills_sync_enabled = true

# Warn on the Windows shutdown/restart/log-off screen while a sync is still
# in flight, naming how much is left. The editor always keeps a "Shut down
# anyway" button. Set false to switch off silently mid-upload.
shutdown_warning_enabled = true

# Keep the machine from idling into sleep while a sync is still running.
# The screen still blanks; only the system idle timer is held, and only for
# as long as something is actually transferring. Cannot stop a deliberate
# Start -> Sleep or a closing lid. Set false to let it sleep regardless.
keep_awake_while_syncing = true

# What "actually transferring" means for BOTH guards above: a lane that has
# reported the same backlog for keep_awake_stale_seconds, or that has been
# blocking continuously for keep_awake_max_hold_seconds, is treated as
# stalled and stops holding the machine. The values below ARE the defaults;
# uncomment only to tune a specific machine (an editor on a link so slow that
# a single file's counters tick less often than that, say). Left commented
# out for the same reason as the transport tuning above -- an explicit value
# in every first-run file pins it, so a later re-tune would never reach an
# existing install.
# keep_awake_stale_seconds = 180.0
# keep_awake_max_hold_seconds = 28800.0

# Set false when this machine works entirely off the NAS share and should
# never sync anything locally (base rig). Timeline watcher, popup fixer and
# dashboard reporting keep working; all sync lanes stay off. Left commented
# out here on purpose: mode="base" below already sets this to false via its
# profile (MODE_PROFILES in config.py) -- pinning an explicit value in every
# first-run file would make that profile dead. Uncomment to override it.
# sync_enabled = true

# Set false to never show the media-outside-tree popup (base rig: raw media
# legitimately lives outside the tree there). Still logged either way.
popup_enabled = true

# How long (seconds) a dismissed-without-acting out-of-tree clip is snoozed
# before the passive watcher will pop it again.
popup_snooze_seconds = 300

# The recurring "Resolve is running but isn't accepting scripting
# connections" warning. It repeats every interval (and waits one full
# interval before the first one) because that state is invisible from
# Resolve's side and never heals itself. Set the flag false, or the interval
# to 0, to switch it off. The dialog's STOP WARNING ME button silences it
# until the link recovers.
resolve_scripting_warning = true
resolve_scripting_warning_interval = 300

# Restart the companion when the Resolve it was connected to exits, so its
# scripting link starts clean against the next one. Leave this on unless you
# are debugging: a stale fusionscript client can wedge the new Resolve's
# scripting server for every client on the machine.
bridge_auto_restart = true

# "Send to Resolve" in the b-roll web UI. This companion listens on
# 127.0.0.1:8899 for that button; the standalone BRoll Companion that used to
# do it is retired and must not be left running (it would hold the port).
# Which share maps to which local folder still lives in
# ~/.broll-companion.json -- except the "broll" share itself, which defaults
# to <local_root>/Assets/B-roll Archive.
broll_server_enabled = true
broll_server_port = 8899

# Machine role: "editor" (default -- full sync lanes) or "base" (the central
# machine working directly off the NAS: implies sync_enabled false unless set
# explicitly above; the out-of-tree popup stays on so stray media still gets
# fixed into the tree).
mode = "editor"

# Resolve project names (case-insensitive) the companion pretends not to
# see: never reported, never prompt "set this up on the server", and their
# clips never raise the out-of-tree popup. Scratch/utility projects only.
# Each name also covers Resolve's numbered duplicates of it -- "New Doc"
# here silences "New Doc 1", "New Doc 2", "New Doc (3)" as well. A longer
# real name that merely starts the same ("New Doc Final") is NOT ignored.
ignored_resolve_projects = ["Untitled Project", "New Doc"]
"""


def ensure_config_exists(path: Path = CONFIG_PATH) -> None:
    """Write DEFAULT_TOML_TEXT to `path` if it doesn't exist yet.

    Owner-only from the moment it exists: this file carries a fleet report
    token, and it used to be created at the process default umask -- 0644 on
    POSIX, and on Windows whatever the profile directory happened to inherit
    (COMMERCIAL_READINESS.md item 15, 2026-08-17). See secretfile.harden.
    """
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_TOML_TEXT, encoding="utf-8")
        # Imported here, not at module scope: config.py is imported by almost
        # everything in this package and secretfile pulls in subprocess.
        from . import secretfile

        secretfile.harden(path)
        return
    if path == CONFIG_PATH:
        # An install that predates the rule above still has a world-readable
        # config.toml, and it will never be rewritten -- config.toml is written
        # by the installer, not by the running companion. Tightened once per
        # process, and ONLY for the real path: a tests' tmp_path config must
        # never spawn icacls.
        global _CONFIG_HARDENED
        if not _CONFIG_HARDENED:
            _CONFIG_HARDENED = True
            from . import secretfile

            secretfile.harden(path)


# Set by ensure_config_exists; see its "install that predates the rule" branch.
_CONFIG_HARDENED = False


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load config, creating it with defaults on first run.

    Malformed TOML falls back to defaults rather than crashing the app —
    matches the never-raise ethos used throughout this package. Unlike a
    silent fallback, though, a parse failure is LOUD: logged here (the root
    logger buffers records emitted before setup_logging() configures
    handlers, so this is never lost even this early in startup) and
    recorded on the returned dict under "_config_load_error" so
    validate_config()/app.py's config_problems make an otherwise
    indistinguishable-from-blank-first-run failure visible.

    Reads with encoding="utf-8-sig" + tomllib.loads() rather than a binary
    "rb" + tomllib.load(): PowerShell's Set-Content (windows_bootstrap.ps1,
    windows_upgrade.ps1) prepends a UTF-8 BOM even when overwriting a
    BOM-less file, and a binary tomllib.load() raises TOMLDecodeError on
    that BOM -- see identity.py's load_identity(), which already reads
    identity.json the same way for the same reason.
    """
    ensure_config_exists(path)
    data: Any = {}
    load_error: Optional[str] = None
    try:
        text = path.read_text(encoding="utf-8-sig")
        data = tomllib.loads(text)
    except OSError as exc:
        load_error = f"could not read {path}: {exc}"
        log.error("config: %s -- falling back to defaults", load_error)
        data = {}
    except tomllib.TOMLDecodeError as exc:
        load_error = f"{path} is not valid TOML: {exc}"
        log.error(
            "config: %s -- falling back to ALL DEFAULTS; the file on disk "
            "looks fine to a human but every setting below is now a "
            "default, not what's actually in the file",
            load_error,
        )
        data = {}

    merged = dict(DEFAULTS)
    if isinstance(data, dict):
        merged.update(data)
    # None when the file parsed cleanly -- see validate_config().
    merged["_config_load_error"] = load_error

    # Role profile: mode="base" flips the sync/popup defaults, but an
    # explicit key in the file always wins.
    profile = MODE_PROFILES.get(str(merged.get("mode", "editor")).strip().lower(), {})
    for key, value in profile.items():
        if not isinstance(data, dict) or key not in data:
            merged[key] = value

    # Defensive type coercion for list fields — a hand-edited TOML file can
    # easily get these wrong (e.g. a bare string instead of a one-item list).
    if not isinstance(merged.get("projects"), list):
        merged["projects"] = []
    if not isinstance(merged.get("syncthing_folder_ids"), list):
        merged["syncthing_folder_ids"] = []
    if not isinstance(merged.get("ignored_resolve_projects"), list):
        merged["ignored_resolve_projects"] = list(DEFAULTS["ignored_resolve_projects"])

    _apply_site_manifest(merged, data)

    return merged


# What the SERVER is allowed to fill in, and under what name it publishes it:
#   config key -> (manifest key, "how do we know the file didn't set it")
#
# "absent"  -- the key is not in config.toml at all. Used where a blank/zero
#              value in the file is itself a MEANINGFUL setting: the transport
#              knobs disable their rclone flag when set to "" or 0 (see
#              DEFAULTS above), so "" from a user is not the same as "unset".
# "blank"   -- the key is absent OR blank. Used for server_p_unc, where ""
#              already means "work it out for me" and "off" is the kill
#              switch that must survive.
_SITE_CONFIG_KEYS: dict[str, tuple[str, str]] = {
    # The grade swap's SMB target. It was derived from dashboard_url's host
    # plus remote_root's tail (drive_swap.derive_server_unc) -- a derivation
    # that only holds where the NAS shares a dataset under its own name, i.e.
    # TrueNAS. A Synology serves /volume1/<share>/<tree> as
    # \\host\<share>\<tree>, and a NAS whose SMB name differs from its SFTP
    # path cannot be derived at all (WP0 step 3, 2026-08-17).
    "server_p_unc": ("smb_unc", "blank"),
    # NOT a preference -- a property of the NAS's sshd, which no client can
    # discover. DSM 7.2's OpenSSH 8.2p1 has no limits@openssh.com, and the
    # fleet's measured-good 255Ki silently TRUNCATES every download at
    # 539,000,832 bytes against it; 64Ki is that box's ceiling, 255Ki stays
    # right for TrueNAS (Synology spike 6, 2026-08-17).
    "sftp_chunk_size": ("sftp_chunk_size", "absent"),
    "sftp_concurrency": ("sftp_concurrency", "absent"),
}


def _apply_site_manifest(merged: dict[str, Any], data: Any) -> None:
    """Fill in what only the SERVER knows, from the cached site manifest.

    Precedence, deliberately: an explicit value in config.toml wins over the
    manifest, the manifest wins over the built-in default, and the built-in
    default still applies when neither exists -- so a TrueNAS install that
    has never seen a manifest behaves exactly as it did before this existed.

    The CACHE is read, never the network: this runs at startup, on the path
    that must work offline. site.py's fetch is the installers' job.
    """
    try:
        from . import site as site_mod

        file_keys = data if isinstance(data, dict) else {}
        wanted = {}
        for key, (site_key, rule) in _SITE_CONFIG_KEYS.items():
            if key in file_keys and (rule == "absent" or str(file_keys[key]).strip()):
                continue
            wanted[key] = site_key
        if not wanted:
            return

        site = site_mod.cached_site()
        if not site:
            return
        for key, site_key in wanted.items():
            value = site.get(site_key)
            # "" / 0 from the manifest means "the server didn't say", never
            # "switch this off" -- the server has no business disabling an
            # editor's transport tuning.
            if value in ("", 0, None):
                continue
            merged[key] = value
    except Exception:
        # Never fatal: every key here has a working built-in fallback, and
        # nothing about a missing manifest may stop a config load.
        log.debug("site manifest not applied to config", exc_info=True)


def validate_config(cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) describing problems with `cfg`.

    Exists because the failure mode these catch is silence: a blank
    `remote_root`, or a `remote` naming a nonexistent rclone stanza, doesn't
    crash anything -- it just means nothing ever syncs and no lane reports
    why. Callers log these at startup rather than raising; the never-raise
    ethos used throughout this package still applies.

    The split matters. **errors** stop syncing outright -- since 0.4.5 they
    genuinely do: app._start_lanes() refuses to start the lanes or the
    sequencer while any is present (AUDIT_2 DEL-3). **warnings** degrade one
    specific feature and are genuinely optional otherwise -- notably
    `projects` / `active_project`, which do NOT scope the rclone lanes.

    What DOES scope them, in managed mode (i.e. whenever `dashboard_url` is
    set -- the default): the dashboard's per-editor selection. Only the
    projects an editor has TICKED sync, and the sequencer syncs them ONE AT
    A TIME. The old claim that "lanes A and B sync local_root <-> remote_root
    as whole trees, so the entire structure replicates verbatim" is legacy
    non-managed behaviour and was materially misleading (AUDIT_2 UX-21).
    `active_project` only supplies the destination the popup fixer suggests
    for editor-added media, and `projects` only pairs with
    `syncthing_folder_ids` for lane C's folder-ID check.
    """
    errors: list[str] = []
    warnings: list[str] = []

    load_error = cfg.get("_config_load_error")
    if load_error:
        errors.append(
            f"config.toml failed to load and every setting below is a DEFAULT, "
            f"not what's in the file -- {load_error}"
        )

    raw_local_root = cfg.get("local_root", "")
    if not isinstance(raw_local_root, str):
        # PRESENT AND WRONG-TYPED, the same failure class the log_path check
        # below exists for: `local_root = 5` is valid TOML, and str()-ing it
        # here reported "local_root does not exist: 5" while the real fault
        # was Path(5)'s TypeError inside resolved_local_root -- which used to
        # kill the windowed exe on the _start_lut_link() call, before the tray
        # icon existed (COMP-CORE-4, 2026-08-14).
        errors.append(
            f"local_root must be a path string, got {raw_local_root!r} -- "
            f"nothing syncs until it names this machine's sync root"
        )
    elif not raw_local_root.strip():
        errors.append(
            "local_root is blank -- the timeline watcher and both rclone lanes "
            "have no tree to work against; set it to this machine's sync root"
        )
    elif not Path(raw_local_root.strip()).expanduser().exists():
        errors.append(f"local_root does not exist: {raw_local_root.strip()}")

    if not str(cfg.get("remote", "")).strip():
        errors.append("remote is blank -- set it to the rclone remote name from rclone.conf")

    remote_root = str(cfg.get("remote_root", "")).strip()
    if not remote_root:
        errors.append(
            "remote_root is blank -- rclone would target the remote's default "
            "directory, which for SFTP is your home directory on the NAS, not "
            "the project tree. Set the absolute NAS path your admin gave you, "
            "e.g. /mnt/<pool>/<share>/<tree> (TrueNAS) or "
            "/volume1/<share>/<tree> (Synology)"
        )
    elif not remote_root.startswith("/"):
        errors.append(
            f"remote_root is not absolute: {remote_root!r} -- an SFTP session "
            f"starts in your home directory on the NAS, so this resolves to "
            f"~/{remote_root} and will miss the project tree"
        )

    if not str(cfg.get("editor_name", "")).strip():
        warnings.append(
            "editor_name is blank -- popup 'Fix' destinations will land in "
            "'B-roll/Editor Added/' with an empty name component, and (with "
            "require_login=false) dashboard reporting silently stops entirely: "
            "the server rejects a blank editor_name on every report. Local "
            "rclone/Syncthing sync lanes are unaffected either way."
        )
    if not str(cfg.get("active_project", "")).strip():
        warnings.append(
            "active_project is blank -- the popup fixer has no project to file "
            "editor-added media into, so it will suggest a destination at the "
            "root of the tree. Which projects sync is decided by your ticks on "
            "the dashboard, not by this key."
        )

    # Absent is fine (load_config merges DEFAULTS in); PRESENT AND WRONG is
    # the failure being caught here.
    log_path = cfg.get("log_path", DEFAULTS["log_path"])
    if not isinstance(log_path, str) or not log_path.strip():
        # setup_logging() does log_path.parent.mkdir() on Path(cfg["log_path"])
        # with no coercion: a non-str raises TypeError and a blank string
        # raises PermissionError, both of which used to kill the windowed exe
        # before it could say why (AUDIT_2 CORE-H2).
        errors.append(
            f"log_path must be a non-blank path string, got {log_path!r} -- "
            f"the default is {DEFAULTS['log_path']!r}"
        )

    folder_ids = cfg.get("syncthing_folder_ids") or []
    projects = cfg.get("projects") or []
    if folder_ids and len(folder_ids) != len(projects):
        warnings.append(
            f"syncthing_folder_ids has {len(folder_ids)} entry/entries but "
            f"projects has {len(projects)} -- they are positional pairs, so "
            f"lane C's folder-ID check will be skipped or mismatched"
        )

    dashboard_url = str(cfg.get("dashboard_url", "")).strip()
    if not dashboard_url:
        # Since 2026-08-17 this key has no default at all -- it used to carry
        # one deployment's tailnet IP, i.e. a compiled-in tenant identity, and
        # a companion nobody had configured phoned that home (WP0,
        # docs/SYNOLOGY_PORT_PLAN.md). So "blank" now means "nobody has
        # pointed this install at a dashboard" as often as it means "the admin
        # switched reporting off", and the difference has to be SAID.
        #
        # A WARNING, not an error, on purpose: errors here stop the lanes
        # outright (DEL-3), and a blank dashboard_url breaks nothing the lanes
        # themselves do -- it breaks SIGN-IN, which app.py already gates on and
        # already names ("sign-in required (require_login=true) -- sync lanes/
        # sequencer will not start"). Two gates for one fault would have made
        # every legacy non-managed install unstartable for a reason it does not
        # have.
        message = (
            "dashboard_url is blank -- this companion is not pointed at any "
            "dashboard, so there is no reporting, no managed sync selection, "
            "no upgrade channel and no site manifest. Set it to the URL your "
            "admin gave you (the installer normally writes it)"
        )
        if bool(cfg.get("require_login", DEFAULTS["require_login"])):
            message += (
                " -- and require_login is on, so nobody can sign in and NO "
                "SYNC LANE WILL EVER START until it is set"
            )
        warnings.append(message)
    else:
        if not (dashboard_url.startswith("http://") or dashboard_url.startswith("https://")):
            warnings.append(
                f"dashboard_url is set but doesn't start with http:// or https://: "
                f"{dashboard_url!r} -- the dashboard reporter will fail to post"
            )
        if not str(cfg.get("dashboard_token", "")).strip():
            warnings.append(
                "dashboard_url is set but dashboard_token is blank -- reports will "
                "be sent without the X-CCSync-Token header, which the dashboard "
                "server may reject"
            )

    try:
        report_interval = float(cfg.get("dashboard_report_interval", DEFAULTS["dashboard_report_interval"]))
        if report_interval <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append(
            f"dashboard_report_interval must be a positive number, got "
            f"{cfg.get('dashboard_report_interval')!r}"
        )

    mode = str(cfg.get("mode", "editor")).strip().lower()
    if mode not in MODE_PROFILES:
        warnings.append(
            f"unknown mode {cfg.get('mode')!r} -- treated as 'editor' "
            f"(valid: {', '.join(sorted(MODE_PROFILES))})"
        )

    # Every numeric key whose bad value raises inside CompanionApp.__init__ /
    # _build_lanes rather than being caught here. The loop used to omit
    # exactly the ones that crash: poll_interval="fast" (which run()'s own
    # comment names as the case it protects against), transfers="four",
    # scan_interval_up="soon" and watch_debounce_seconds=None all produced
    # errors == [] and then raised at construction, taking the windowed exe
    # down with no log line (AUDIT_2 CORE-M4).
    for key in (
        "selection_poll_interval", "project_rotation_seconds", "sequencer_idle_seconds",
        "selection_fetch_ttl", "project_roots_ttl",
        "dashboard_report_interval_active", "manifest_refresh_interval", "media_tree_refresh_interval",
        "popup_snooze_seconds", "resolve_scripting_warning_interval",
        "poll_interval", "transfers", "scan_interval_up", "scan_interval_down",
        "watch_debounce_seconds",
        # Transport tuning: a string in sftp_concurrency is the same class of
        # bug -- it crashes lane construction.
        "sftp_concurrency", "sftp_connections", "checkers",
        "lane_c_max_folder_concurrency",
        "express_debounce_seconds", "express_max_batch",
    ):
        try:
            value = float(cfg.get(key, DEFAULTS[key]))
            if value <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{key} must be a positive number, got {cfg.get(key)!r}")

    # Same, but 0 is legal here: it means "disable this behaviour entirely".
    for key in ("structure_clone_every_n_passes", "orphan_scan_every_n_passes"):
        try:
            if float(cfg.get(key, DEFAULTS[key])) < 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(
                f"{key} must be a number >= 0 (0 disables it), got {cfg.get(key)!r}"
            )

    # WARNINGS, not errors, and deliberately so. Everything in the numeric
    # loop above either crashes construction or scopes what syncs; these two
    # only tune how patient the shutdown/keep-awake guards are, and
    # coerce_numeric already falls back to the packaged default. Making them
    # errors would mean a typo in a power-management knob sets
    # config_problems -- which STOPS every lane (DEL-3) and, since
    # _shutdown_block_reason() returns None on config_problems, switches off
    # the very guards the key was being tuned for.
    for key in ("keep_awake_stale_seconds", "keep_awake_max_hold_seconds"):
        try:
            value = float(cfg.get(key, DEFAULTS[key]))
            if value <= 0:
                raise ValueError
        except (TypeError, ValueError):
            warnings.append(
                f"{key} must be a positive number, got {cfg.get(key)!r} -- "
                f"using the default ({DEFAULTS[key]})"
            )

    # A WARNING, and it must never become an error. Errors stop every sync
    # lane (DEL-3), and a machine with no ffmpeg is a machine that syncs
    # perfectly well and merely cannot make its own proxies -- the notifier
    # still tells it which clips are missing them. Only checked when
    # generation is actually on, so an editor is never warned about a binary
    # this machine was never going to run.
    if proxy_generation_enabled(cfg):
        ffmpeg_path = str(cfg.get("ffmpeg_path", DEFAULTS["ffmpeg_path"]) or "").strip()
        if not ffmpeg_path:
            warnings.append(
                "ffmpeg_path is blank but proxy generation is on -- no proxies "
                "will be generated on this machine; syncing is unaffected"
            )
        elif not _ffmpeg_resolves(ffmpeg_path):
            warnings.append(
                f"ffmpeg not found ({ffmpeg_path!r}) but proxy generation is on "
                f"-- this machine will report missing proxies and generate none. "
                f"Install ffmpeg (or set ffmpeg_path to it), or set "
                f"proxy_gen_enabled = false. Syncing is unaffected either way."
            )

    scheme = str(cfg.get("lane_c_pause_scheme", DEFAULTS["lane_c_pause_scheme"])).strip().lower()
    if scheme not in ("none", "rotate"):
        warnings.append(
            f"unknown lane_c_pause_scheme {cfg.get('lane_c_pause_scheme')!r} -- "
            f"treated as 'none' (valid: none, rotate)"
        )

    return errors, warnings


# What may follow an ignored project name and still be the SAME scratch
# project: Resolve's duplicate suffix -- "New Doc 1", "New Doc 2",
# "Untitled Project (3)". Nothing else ("New Doc Final" is a real project).
_NUMBERED_DUPLICATE_RE = re.compile(r"^[\s_\-]*[\(\[]?\d+[\)\]]?$")


def normalize_ignored_projects(values: Any) -> set[str]:
    """The `ignored_resolve_projects` config list as a normalized match set.

    Normalization is strip + lower + internal-whitespace collapse, so a
    hand-edited "  New  Doc " entry still matches Resolve's "New Doc".
    Blank/garbage entries are dropped; a non-list (already coerced by
    load_config, but this is also called with raw values) yields an empty
    set, i.e. "ignore nothing" -- never an exception.
    """
    try:
        items = list(values or [])
    except TypeError:
        return set()
    normalized: set[str] = set()
    for value in items:
        if value is None:
            continue
        try:
            text = " ".join(str(value).split()).lower()
        except Exception:
            continue
        if text:
            normalized.add(text)
    return normalized


def is_ignored_project(name: Any, ignored: Any) -> bool:
    """True if `name` is one of the ignored scratch/utility Resolve projects.

    Matching is a PREFIX match, not equality: Resolve names duplicates of its
    scratch projects "New Doc 1", "New Doc 2", "Untitled Project (3)", and
    the Blackmagic Proxy Generator's helper project counts up like that all
    day. Only a trailing number (with optional spaces/dashes/underscores and
    optional brackets) is allowed after the ignored name -- "New Documentary"
    and "New Doc Final" are real projects and never match.

    `ignored` may be the raw config list or an already-normalized set; both
    are accepted so callers can normalize once at construction. Never raises.
    """
    try:
        candidate = " ".join(str(name or "").split()).lower()
    except Exception:
        return False
    if not candidate:
        return False

    if isinstance(ignored, (set, frozenset)):
        entries = ignored
    else:
        entries = normalize_ignored_projects(ignored)

    for entry in entries:
        if candidate == entry:
            return True
        if candidate.startswith(entry):
            if _NUMBERED_DUPLICATE_RE.match(candidate[len(entry):]):
                return True
    return False


def coerce_numeric(cfg: dict[str, Any], key: str, default: Any) -> float:
    """float(cfg[key]) with the packaged default as a never-raise fallback.

    validate_config() now flags these, and _start_lanes() refuses to run on
    an error -- but CompanionApp is still CONSTRUCTED first, and construction
    must not raise on a hand-edited value (that is the failure mode with no
    log line and no tray)."""
    try:
        value = float(cfg.get(key, default))
        if value <= 0:
            raise ValueError
        return value
    except (TypeError, ValueError):
        log.error("config: %s=%r is not a positive number -- using %r", key, cfg.get(key), default)
        return float(default)


def coerce_count(cfg: dict[str, Any], key: str, default: Any) -> int:
    """coerce_numeric's sibling for the "every N passes, 0 disables" knobs.

    Same never-raise contract and the same reason for existing (construction
    must survive a hand-edited value -- see coerce_numeric), but 0 is a legal
    value here rather than an error, so these cannot go through
    coerce_numeric's positive-only gate. A negative number is garbage and
    falls back to the packaged default."""
    try:
        value = int(float(cfg.get(key, default)))
        if value < 0:
            raise ValueError
        return value
    except (TypeError, ValueError):
        log.error(
            "config: %s=%r is not a number >= 0 (0 disables it) -- using %r",
            key, cfg.get(key), default,
        )
        return int(default)


def proxy_generation_enabled(cfg: dict[str, Any]) -> bool:
    """Whether THIS machine should encode the missing proxies itself.

    Tri-state: an explicit `proxy_gen_enabled` (true or false) wins outright;
    absent/None -- the shipped default -- derives `not lane_b_enabled`.

    That derivation is not a preference, it is the lane-B sweep. Lane B is
    `rclone sync`, the one verb in this system that DELETES local files, and a
    proxy generated locally for a SYNCED project exists nowhere on the NAS --
    so the next lane-B pass moves it into .ccsync-trash and the encode is
    thrown away. The loop only closes through the machine whose local_root IS
    the NAS tree (the base rig, which runs lane_b_enabled=false): editor
    originals go up lane A, the base rig generates, and lane B fans the result
    back out to the fleet. So generation defaults on exactly where the result
    lands somewhere it survives and reaches everyone.

    Editors can still force it on -- proxies for projects lane B never touches
    do survive -- and the NOTIFIER is unconditional either way: knowing a clip
    is invisible to the fleet is useful on every machine.

    The base rig gets `lane_b_enabled = False` from MODE_PROFILES rather than
    from this function noticing `sync_enabled` is off. Deliberate: "sync is
    off" is NOT the same claim as "lane B will never sweep this tree". An
    editor who disables sync for a week, generates proxies while away, then
    re-enables it hands the next lane-B pass a tree full of files the NAS has
    never seen -- which is precisely the sweep this derivation exists to dodge.

    Never raises: a hand-edited non-boolean falls back to the derivation.
    """
    value = cfg.get("proxy_gen_enabled", DEFAULTS["proxy_gen_enabled"])
    if isinstance(value, bool):
        return value
    if value is not None:
        # bool("false") is True, so a string here cannot be coerced honestly.
        log.error(
            "config: proxy_gen_enabled=%r is not true/false -- deriving it "
            "from lane_b_enabled instead", value,
        )
    return not bool(cfg.get("lane_b_enabled", DEFAULTS["lane_b_enabled"]))


# ffmpeg's own -b:v grammar, narrowed to what this app writes: a number with
# an optional K/M multiplier ("7M", "700k", "2.5M").
_BITRATE_RE = re.compile(r"^\d+(\.\d+)?[KkMm]?$")


def coerce_bitrate(cfg: dict[str, Any], key: str, default: Any) -> str:
    """An ffmpeg -b:v value from config, with the packaged default as a
    never-raise fallback.

    ffmpeg gives no useful protection here: a bogus -b:v either kills the
    spawn (one failed encode per clip, for as long as the value stays wrong)
    or is parsed as something else entirely -- "fast" reads as 0 bits/s, which
    encodes an unwatchable proxy rather than an error. Same contract as
    coerce_numeric: garbage is LOGGED and the packaged default is used."""
    value = cfg.get(key, default)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        # A bare number is bits per second, which is what ffmpeg reads it as.
        return str(value)
    if isinstance(value, str) and _BITRATE_RE.match(value.strip()):
        return value.strip()
    log.error(
        "config: %s=%r is not an ffmpeg bitrate like \"7M\" or \"700k\" -- using %r",
        key, value, default,
    )
    return str(default)


def _ffmpeg_resolves(ffmpeg_path: str) -> bool:
    """Cheap "is there a binary at all" check for validate_config().

    Deliberately NOT a -version probe: this runs at startup before anything is
    on screen, and the runnable check belongs to the generator (which caches
    it). which() first because it is the one that knows about PATHEXT -- an
    absolute "C:\\tools\\ffmpeg" is really ffmpeg.exe on disk."""
    try:
        candidate = str(Path(str(ffmpeg_path)).expanduser())
        if shutil.which(candidate) is not None:
            return True
        return Path(candidate).exists()
    except Exception:
        # Unresolvable for some other reason -- say nothing rather than warn
        # about an ffmpeg that may well be fine.
        return True


def resolved_log_path(cfg: dict[str, Any]) -> Path:
    """Never raises. A non-str or blank `log_path` falls back to the packaged
    default -- Path(5) raises TypeError, and this is called from
    CompanionApp.__init__, _build_lanes AND setup_logging, i.e. three places
    where an exception means the windowed exe vanishes silently (AUDIT_2
    CORE-H2). validate_config() reports the bad value."""
    raw = cfg.get("log_path", DEFAULTS["log_path"])
    if not isinstance(raw, str) or not raw.strip():
        raw = DEFAULTS["log_path"]
    try:
        return Path(raw).expanduser()
    except Exception:
        return Path(DEFAULTS["log_path"]).expanduser()


def resolved_local_root(cfg: dict[str, Any]) -> Path:
    """Never raises, for the same reason resolved_log_path() doesn't: a
    hand-edited or mis-templated `local_root = 5` is valid TOML, and this is
    the FIRST statement of _start_lut_link(), which start() calls outside any
    try -- so Path(5)'s TypeError tore the process down before the tray icon
    existed, leaving the editor with no tray, no toast and only a log line
    they had no tray menu item to open (COMP-CORE-4, 2026-08-14).

    A non-str value degrades to Path(""), i.e. exactly the "we don't know
    where the tree is" state every caller already refuses on (fixer's
    CORE-H1 guard, _local_root_is_broken); validate_config() reports the bad
    value."""
    raw = cfg.get("local_root", "")
    if not isinstance(raw, str):
        raw = ""
    try:
        return Path(raw).expanduser()
    except Exception:
        return Path("")
