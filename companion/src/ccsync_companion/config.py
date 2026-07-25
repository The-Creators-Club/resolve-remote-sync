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

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - project targets 3.12
    import tomli as tomllib  # type: ignore[no-redef]

from pathlib import Path
from typing import Any

VERSION = "0.4.3"

CONFIG_DIR = Path.home() / ".ccsync"
CONFIG_PATH = CONFIG_DIR / "config.toml"

# Keys marked "addition" in the docstring/README are small, clearly-scoped
# extensions beyond SPEC.md's literal config list — see README.md's "SPEC
# deviations" section for the why on each.
DEFAULTS: dict[str, Any] = {
    "editor_name": "",
    "local_root": "",
    "canonical_prefix": "P:\\",
    # Must match the remote name the bootstrap installers write into
    # rclone.conf ($RemoteName / $REMOTE_NAME). This used to default to "nas",
    # which silently gave every fresh install a non-existent rclone remote.
    "remote": "creators_club_sftp",
    # ABSOLUTE path on the NAS. An SFTP session lands in the editor's home
    # directory, so a relative value resolves under ~/ (e.g.
    # /mnt/tank/TheCreatorsPool/homes/<editor>/Creators_Club) and silently
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
    # Debounce window for the Lane A watchdog file events (addition; SPEC.md
    # says "10s debounce" for lane A but doesn't name a config key for it).
    "watch_debounce_seconds": 10,
    "transfers": 4,
    "syncthing_url": "http://127.0.0.1:8384",
    "syncthing_api_key": "",
    # Expected Syncthing folder ID per entry in `projects` (addition; needed
    # to fulfil "verify the expected folder ID ... is configured + shared").
    # Leave empty to skip the folder-id check for a project.
    "syncthing_folder_ids": [],
    "rclone_path": "rclone",
    "log_path": "~/.ccsync/companion.log",
    "log_level": "INFO",
    # Dashboard reporter (addition; not in SPEC.md's config list) -- posts
    # lane statuses to a server-side dashboard so an admin can see editor
    # health without remoting in. Defaults to the dashboard's tailnet
    # address so remote editors get reporting, managed sync, and the tray's
    # "Open dashboard" link out of the box. Set to "" to disable entirely
    # (reporter thread isn't even started).
    "dashboard_url": "http://100.71.216.3:8480",
    "dashboard_token": "",
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
    # False on the base rig (direct LAN access to the NAS): it reads proxies
    # straight off the share, so mirroring them locally is pure waste.
    "lane_b_enabled": True,
    # False = no sync lanes at all: the machine works directly off the NAS
    # share (base rig). The companion still runs the timeline watcher, popup
    # fixer, and dashboard reporter; lanes report idle with a "disabled"
    # detail instead of running.
    "sync_enabled": True,
    # False = never show the media-outside-tree popup (base rig: all raw
    # media legitimately lives outside/next to the tree, so the popup is
    # noise there). Out-of-tree clips are still logged.
    "popup_enabled": True,
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
    "ignored_resolve_projects": ["Untitled Project", "New Doc"],
}

# Profile defaults applied by load_config when mode is set and the file does
# not override the key explicitly. Note base keeps the popup ON: a careless
# base editor can still cut in media from outside the tree on T:, and those
# clips won't reach remote editors until fixed into the project directory.
MODE_PROFILES: dict[str, dict[str, Any]] = {
    "editor": {},
    "base": {"sync_enabled": False},
}

DEFAULT_TOML_TEXT = """\
# ccsync-companion config
# See companion/README.md for the full reference. Restart the companion
# after editing this file.

# Your name/handle — used to build the "B-roll/Editor Added/<editor_name>"
# destination suggested by the popup fixer.
editor_name = ""

# Absolute path to this machine's local copy of the project tree, e.g.
# "C:\\\\Creators_Club" (Windows) or "/Users/you/Creators_Club" (macOS).
local_root = ""

# The canonical shared-drive prefix used in Resolve's stored clip paths
# (Windows: the "P:" virtual drive letter from SPEC.md's Path canon). Used
# to detect BAD_PREFIX (mapping-health) situations.
canonical_prefix = "P:\\\\"

# Name of the rclone remote pointing at the NAS. Must match the stanza the
# bootstrap installer wrote into rclone.conf. ccsync-companion does not
# configure rclone remotes for you.
remote = "creators_club_sftp"

# ABSOLUTE path on the NAS under which project trees live, e.g.
# "/mnt/tank/TheCreatorsPool/Creators_Club". It must be absolute: the SFTP
# session starts in your home directory on the NAS, so a relative value
# resolves under ~/ and will not find the project tree.
remote_root = ""

# Project relative paths to sync, e.g. ["Projects/2025/FF4/Nuclear"].
projects = []
active_project = ""

# Resolve timeline poll interval, in seconds.
poll_interval = 3

# Lane A (video originals, up) periodic full-pass interval, in seconds.
scan_interval_up = 300

# Lane B (proxies, down) periodic full-pass interval, in seconds.
scan_interval_down = 120

# Lane A watchdog file-stability debounce, in seconds.
watch_debounce_seconds = 10

# rclone --transfers (parallel stream count).
transfers = 4

# Local Syncthing REST API base URL and API key. Leave syncthing_api_key
# empty to read it from Syncthing's own config.xml (the installer-managed
# ccsync\syncthing-config home first, else the stock per-OS path).
syncthing_url = "http://127.0.0.1:8384"
syncthing_api_key = ""

# Expected Syncthing folder ID per project (same order/length as `projects`
# above). Leave as [] to skip the folder-id verification.
syncthing_folder_ids = []

# Path to the rclone binary. Defaults to "rclone" (must be on PATH).
rclone_path = "rclone"

# Log file (rotating) — console logging is always on in addition to this.
log_path = "~/.ccsync/companion.log"
log_level = "INFO"

# Dashboard reporter: periodically POSTs lane statuses to a server-side
# dashboard so an admin can see editor health without remoting in. Defaults
# to the dashboard's tailnet address (right for remote editors; the base rig
# overrides with the LAN address). Set to "" to disable entirely -- the
# reporter thread isn't even started. dashboard_token is sent as the
# X-CCSync-Token header; ask the admin for the value.
dashboard_url = "http://100.71.216.3:8480"
dashboard_token = ""
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

# Managed mode (active only when dashboard_url above is set): the dashboard
# decides WHICH projects this editor has and in what order, and a
# sequencer syncs them one at a time instead of the whole tree
# continuously. How often the sequencer re-fetches the ordered selection:
selection_poll_interval = 60
# How long (seconds) the sequencer waits for a project's Lane C
# (Syncthing) sync to settle before moving on to the next project anyway:
project_rotation_seconds = 600
# How long (seconds) the sequencer idles between full passes once every
# selected project is caught up (small edits still trickle during this
# window -- every selected folder is unpaused while idle):
sequencer_idle_seconds = 60

# Set false on the base rig (direct LAN access to the NAS): it reads proxies
# straight off the share, so lane B's local proxy mirror is pure waste.
lane_b_enabled = true

# Set false when this machine works entirely off the NAS share and should
# never sync anything locally (base rig). Timeline watcher, popup fixer and
# dashboard reporting keep working; all sync lanes stay off.
sync_enabled = true

# Set false to never show the media-outside-tree popup (base rig: raw media
# legitimately lives outside the tree there). Still logged either way.
popup_enabled = true

# Machine role: "editor" (default -- full sync lanes) or "base" (the central
# machine working directly off the NAS: implies sync_enabled false unless set
# explicitly above; the out-of-tree popup stays on so stray media still gets
# fixed into the tree).
mode = "editor"

# Resolve project names (case-insensitive) the companion pretends not to
# see: never reported, never prompt "set this up on the server", and their
# clips never raise the out-of-tree popup. Scratch/utility projects only.
ignored_resolve_projects = ["Untitled Project", "New Doc"]
"""


def ensure_config_exists(path: Path = CONFIG_PATH) -> None:
    """Write DEFAULT_TOML_TEXT to `path` if it doesn't exist yet."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_TOML_TEXT, encoding="utf-8")


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load config, creating it with defaults on first run.

    Malformed TOML falls back to defaults rather than crashing the app —
    matches the never-raise ethos used throughout this package.
    """
    ensure_config_exists(path)
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError):
        data = {}

    merged = dict(DEFAULTS)
    if isinstance(data, dict):
        merged.update(data)

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

    return merged


def validate_config(cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) describing problems with `cfg`.

    Exists because the failure mode these catch is silence: a blank
    `remote_root`, or a `remote` naming a nonexistent rclone stanza, doesn't
    crash anything -- it just means nothing ever syncs and no lane reports
    why. Callers log these at startup rather than raising; the never-raise
    ethos used throughout this package still applies.

    The split matters. **errors** stop syncing outright. **warnings** degrade
    one specific feature and are genuinely optional otherwise -- notably
    `projects` / `active_project`, which do NOT scope the rclone lanes:
    lanes A and B sync `local_root` <-> `remote_root` as whole trees, so the
    entire Projects/<year>/<series>/<project> structure replicates verbatim
    no matter what those keys say. `active_project` only supplies the
    destination the popup fixer suggests for editor-added media, and
    `projects` only pairs with `syncthing_folder_ids` for lane C's
    folder-ID check.
    """
    errors: list[str] = []
    warnings: list[str] = []

    local_root = str(cfg.get("local_root", "")).strip()
    if not local_root:
        errors.append(
            "local_root is blank -- the timeline watcher and both rclone lanes "
            "have no tree to work against; set it to this machine's sync root"
        )
    elif not Path(local_root).expanduser().exists():
        errors.append(f"local_root does not exist: {local_root}")

    if not str(cfg.get("remote", "")).strip():
        errors.append("remote is blank -- set it to the rclone remote name from rclone.conf")

    remote_root = str(cfg.get("remote_root", "")).strip()
    if not remote_root:
        errors.append(
            "remote_root is blank -- rclone would target the remote's default "
            "directory, which for SFTP is your home directory on the NAS, not "
            "the project tree. Set the absolute NAS path, e.g. "
            "/mnt/tank/TheCreatorsPool/Creators_Club"
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
            "'B-roll/Editor Added/' with an empty name component. Syncing is "
            "unaffected."
        )
    if not str(cfg.get("active_project", "")).strip():
        warnings.append(
            "active_project is blank -- the popup fixer has no project to file "
            "editor-added media into, so it will suggest a destination at the "
            "root of the tree. Syncing is unaffected: lanes A and B replicate "
            "the whole tree regardless."
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
    if dashboard_url:
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

    for key in (
        "selection_poll_interval", "project_rotation_seconds", "sequencer_idle_seconds",
        "dashboard_report_interval_active", "manifest_refresh_interval", "media_tree_refresh_interval",
    ):
        try:
            value = float(cfg.get(key, DEFAULTS[key]))
            if value <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{key} must be a positive number, got {cfg.get(key)!r}")

    return errors, warnings


def resolved_log_path(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("log_path", DEFAULTS["log_path"])).expanduser()


def resolved_local_root(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("local_root", "")).expanduser()
