"""Auto-provisioning helpers: discover project dirs that have no Syncthing
folder yet and build the folder config for them.

slugify() and build_stignore_lines() are intentional copies of
server/common.py (the dashboard container cannot import server/) -- if the
conventions there change, change them here too. The folder config mirrors
server/setup_syncthing_folder.py so hand-provisioned and auto-provisioned
folders are indistinguishable.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Iterable

log = logging.getLogger("ccsync.dashboard.provision")

# THE canonical copy of this list. server/common.py and the companion hold
# their own (neither can import this module), and
# server/tests/test_cross_component.py pins all of them byte-identical --
# which extension counts as video decides whether a file travels by rclone
# (lanes A/B) or by Syncthing (lane C), and a drift means some media type is
# carried by both or by neither. NOT site-configurable for that reason; it is
# published read-only by GET /api/v1/site as `video_extensions` so a future
# client can read it rather than grow a fourth copy (2026-08-17,
# COMMERCIAL_READINESS.md item 11).
VIDEO_EXTENSIONS = [
    ".braw", ".mov", ".mp4", ".mxf", ".avi", ".mts", ".m2ts", ".mkv",
    ".r3d", ".crm", ".mpg", ".mpeg", ".wmv", ".webm", ".insv", ".360",
]
_VIDEO_EXT_SET = frozenset(VIDEO_EXTENSIONS)


def _site_list(env_var: str, default: list) -> list:
    """A comma-separated site override from the container's environment, or
    `default`. Blank/absent means "this site did not say" -- never an empty
    list, which would silently create projects with no subfolders at all.

    The container has no site.toml (server/common.py reads that, on the
    machine that runs the installers); its site facts arrive as DASH_SITE_*
    env vars in the compose file, which is where the installer renders
    site.toml's values (2026-08-17, COMMERCIAL_READINESS.md item 11).
    """
    raw = os.environ.get(env_var, "")
    items = [p.strip().replace("\\", "/").strip("/") for p in raw.split(",")]
    items = [p for p in items if p]
    return items or list(default)


# The out-of-the-box project template -- intentional copy of
# server/common.py's DEFAULT_TEMPLATE_FOLDERS (same reason as slugify above:
# the container cannot import server/). Used by the /project-setup "create new
# project" flow (api.create_tree_project) and published by GET /api/v1/site.
#
# The DEFAULTS are what the cross-component test pins; the folders themselves
# are documentary-shop specific ("Interviewees", "Render in Place"), so a site
# that edits differently overrides them with [tree] template_folders in
# site.toml -> DASH_SITE_TEMPLATE_FOLDERS (2026-08-17,
# COMMERCIAL_READINESS.md item 11).
DEFAULT_TEMPLATE_FOLDERS = [
    "AE",
    "Audio/Music",
    "Audio/Voiceover",
    "B-roll",
    "Interviewees",
    "Render in Place",
    "Subs",
    "Youtube",
]
TEMPLATE_FOLDERS = _site_list("DASH_SITE_TEMPLATE_FOLDERS", DEFAULT_TEMPLATE_FOLDERS)


def classify_media(rel_parts: Iterable[str], ext: str) -> str | None:
    """Classify a file for the NAS media inventory. Only video counts:
    'proxy' when it lives under a Proxy/ dir (any depth, case-insensitive),
    else 'original'. Non-video returns None (skipped). Mirrors the
    .stignore convention in build_stignore_lines()."""
    if ext.lower() not in _VIDEO_EXT_SET:
        return None
    return "proxy" if any(p.lower() == "proxy" for p in rel_parts) else "original"


def slugify(text: str) -> str:
    """Path -> stable id, byte-identical to server/common.slugify.

    NOT the authority for a project's identity. `slugify(rel)` and THE
    MARKER'S SLUG agree only for a project that has never moved: the marker
    slug is immutable and travels with the directory, which is what lets the
    collector retarget a moved/renamed project instead of treating it as a
    delete plus a brand-new project (see read_marker / MARKER_FILENAME, and
    collector._provision_slug).

    `server/setup_syncthing_folder.py` derives the folder id with slugify(rel)
    instead, so for a project that HAS moved the two disagree: the script's
    find_folder misses the real folder and creates a SECOND Syncthing folder
    over the same directory -- one that no editor is shared with and that
    fails the collector every cycle. The collector is authoritative here;
    Collector._duplicate_path_folder refuses to add to the confusion and says
    what to fix. Use the dashboard (or --slug from the marker) to repair a
    moved project's folder, not a bare --project-rel-path."""
    text = text.replace("\\", "/").strip().lower()
    parts = [p for p in re.split(r"[^a-z0-9]+", text) if p]
    slug = "-".join(parts)
    if not slug:
        raise ValueError(f"slugify({text!r}) produced an empty slug")
    return slug


# Intentional copy of server/common.py's PARTIAL_IGNORE_LINES. rclone's
# default --inplace=false writes "<name>.<token>.partial" into the project dir
# on the NAS -- also a sendreceive Syncthing root -- and lane A never deletes,
# so a killed transfer's multi-GB orphan used to be indexed and fanned out to
# every ticked editor (KNOWN_BUGS B12). The extension patterns match by
# EXTENSION and so matched none of them.
PARTIAL_IGNORE_LINES = ["(?i)**/*.partial", "(?i)*.partial"]

# Intentional copy of server/common.py's YTDL_IGNORE_LINES (read that block for
# the full story). The NAS-side ytdl worker downloads INTO the shared Projects
# tree, so lane C replicated every growing `.part` out to each editor with the
# project ticked; since the 2026-08-11 ignoreDelete retrofit the worker's
# completion rename never propagates, so what lands on an editor's disk is
# permanent -- 27 orphans, ~1.6 GB, over three days on one editor's machine
# (2026-08-13/14).
#
# THIS copy is the one that decides whether the patterns survive: collector.
# _ensure_ignores() compares a folder's live ignores to build_stignore_lines()
# below with `have == want` and re-POSTs on ANY difference, so a line the
# server writes and the dashboard does not know about is stripped on the next
# provision cycle (with a misleading "REPAIRED .stignore" warning). Order
# matters for the same reason: keep this list, and the extend() order below,
# byte-identical to server/common.py (server/tests/test_cross_component.py
# asserts it across server, dashboard and companion).
#
# `.part-FragN` needs its own pair: a fragment is "<file>.part-Frag84" and does
# NOT end in `.part`. Deliberately NOT added to build_asset_stignore_lines():
# no ytdl worker writes into the LUT library, and that list must stay
# byte-identical across the three components.
YTDL_IGNORE_LINES = [
    "(?i)**/*.part", "(?i)*.part",
    "(?i)**/*.part-Frag*", "(?i)*.part-Frag*",
    "(?i)**/*.ytdl", "(?i)*.ytdl",
]


def build_stignore_lines() -> list[str]:
    lines = [f"(?i)*{ext}" for ext in VIDEO_EXTENSIONS]
    lines.extend(PARTIAL_IGNORE_LINES)
    lines.extend(YTDL_IGNORE_LINES)
    lines.append("(?i)Proxy")
    lines.append("(?i)**/Proxy")
    lines.append("(?i)**/Proxy/**")
    return lines


# --------------------------------------------------------------------------
# Shared asset folders -- intentional copy of server/common.py's block, same
# reason as slugify/TEMPLATE_FOLDERS above (the container cannot import
# server/). server/tests/test_cross_component.py asserts byte-parity of the
# ids, rels and the .stignore list across server, dashboard and companion.
# --------------------------------------------------------------------------

LUTS_FOLDER_ID = "assets-luts"
LUTS_REL = "Assets/Luts"
STILLS_FOLDER_ID = "assets-stills"
STILLS_REL = "Assets/Stills"

DEFAULT_SHARED_ASSET_FOLDERS = [
    (LUTS_FOLDER_ID, LUTS_REL, "Assets/Luts (LUT library)"),
    (STILLS_FOLDER_ID, STILLS_REL, "Assets/Stills (Resolve gallery)"),
]

# Known labels for the folders the product ships with. A site that adds its
# own (sound FX, Fusion macros) gets the rel path as its label rather than a
# blank one -- a label is what the dashboard prints, never an identity.
_ASSET_LABELS = {rel: label for _fid, rel, label in DEFAULT_SHARED_ASSET_FOLDERS}


def shared_asset_folders_for(rels: Iterable[str]) -> list:
    """(id, rel, label) triples for a list of rel paths. The id is slugify(rel)
    -- exactly what the two default ids already are -- so the Syncthing folder
    id a site's extra library gets is derived by the same rule as everything
    else in the fleet, not invented per component."""
    out = []
    for rel in rels:
        rel = str(rel).replace("\\", "/").strip("/")
        if not rel:
            continue
        out.append((slugify(rel), rel, _ASSET_LABELS.get(rel, rel)))
    return out


# Site override, same shape and same reason as TEMPLATE_FOLDERS above: a
# customer with a different asset library says so once in site.toml [tree]
# shared_assets. The DEFAULTS are what test_cross_component pins across the
# three components -- an override is this site's data, not a code change
# (2026-08-17, COMMERCIAL_READINESS.md item 11).
_SITE_SHARED_ASSET_RELS = _site_list("DASH_SITE_SHARED_ASSETS", [])
SHARED_ASSET_FOLDERS = (shared_asset_folders_for(_SITE_SHARED_ASSET_RELS)
                        or DEFAULT_SHARED_ASSET_FOLDERS)

SHARED_ASSET_FOLDER_IDS = frozenset(fid for fid, _rel, _label in SHARED_ASSET_FOLDERS)

ASSET_JUNK_IGNORE_LINES = [
    "(?i)**/.DS_Store", "(?i).DS_Store",
    "(?i)**/Thumbs.db", "(?i)Thumbs.db",
    "(?i)**/desktop.ini", "(?i)desktop.ini",
    "(?i)**/*.tmp", "(?i)*.tmp",
    "(?i)**/*.ccsync-tmp", "(?i)*.ccsync-tmp",
]


def build_asset_stignore_lines() -> list[str]:
    """.stignore for a shared asset folder -- OS junk, plus video as a
    blast-radius brake (this folder is auto-shared with the whole fleet and
    has no tick to opt out of). See server/common.build_asset_stignore_lines
    for the full reasoning; keep the two byte-identical."""
    lines = [f"(?i)*{ext}" for ext in VIDEO_EXTENSIONS]
    lines.extend(PARTIAL_IGNORE_LINES)
    lines.extend(ASSET_JUNK_IGNORE_LINES)
    return lines


def build_shared_folder_config(
    folder_id: str, label: str, path: str, device_ids: list[str]
) -> dict:
    """Folder config for a shared asset library.

    Same tuning and versioning as a project folder (build_folder_config
    below) -- it is the same Syncthing on the same link. The differences are
    that the path is passed in whole rather than derived from the Projects
    prefix, and the label is a fixed human string rather than the project's
    rel path.
    """
    return {
        "id": folder_id,
        "label": label,
        "path": path,
        "type": "sendreceive",
        "fsWatcherEnabled": True,
        "ignorePerms": True,
        "rescanIntervalS": 3600,
        "maxConcurrentWrites": 32,
        "pullerMaxPendingKiB": 65536,
        "versioning": {
            "type": "staggered",
            "params": {"cleanInterval": "3600", "maxAge": "31536000"},
        },
        # delete-protection (2026-08-11, docs/delete-protection-ignoredelete.md):
        # the library auto-shares to the whole fleet with no tick to opt out
        # of, so one editor deleting a LUT must not take it off the NAS and
        # off every other machine. Same flag on every side; the companion
        # retrofits folders that predate it.
        "ignoreDelete": True,
        "devices": [{"deviceID": device_id, "introducedBy": ""} for device_id in device_ids],
    }


# The explicit project marker (added 2026-07-25). A directory IS a project
# because it carries this file -- never because of its depth or name. The
# slug inside is the project's IMMUTABLE identity: it travels with the
# directory when it's moved/renamed on the NAS, which is what lets the
# collector retarget the Syncthing folder instead of treating a move as a
# delete + brand-new project. Written by every create path (dashboard
# /project-setup, server setup_tree.py) and self-healed each provision
# cycle for known folders. Same JSON shape as server/common.py's marker
# helpers -- intentional copy, keep in sync.
MARKER_FILENAME = ".ccsync-project"

# Intentional copy of server/common.py's SLUG_RE (same reason as slugify:
# the container cannot import server/). A marker is a plain JSON file on a
# share every editor can write, and its slug becomes a Syncthing FOLDER ID,
# a filesystem-ish path component in log lines, and a dashboard URL segment
# -- a hand-dropped {"slug": "../../etc"} or {"slug": "a/b"} must never get
# that far. read_marker enforces it at the only place markers are read.
SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def read_marker_data(directory: Path) -> dict | None:
    """The marker's full JSON dict, or None (missing/unreadable/malformed --
    never raises). Callers that only need the identity use read_marker;
    this exists for the additive keys (`includes`, SHARED_FOLDERS_PLAN.md
    §2.1) that ride in the same file."""
    import json

    try:
        data = json.loads((Path(directory) / MARKER_FILENAME).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_marker(directory: Path) -> str | None:
    """The marker's slug, or None (missing/unreadable/malformed/invalid slug
    -- never raises; callers treat None as 'not a project' or log-and-skip)."""
    data = read_marker_data(directory)
    if data is None:
        return None
    slug = str(data.get("slug", "")).strip()
    if not slug:
        return None
    if not SLUG_RE.match(slug):
        log.warning(
            "IGNORING project marker in %s: slug %r is not a valid identity "
            "(only lowercase a-z, 0-9 and '-'; it becomes a Syncthing folder id "
            "and a dashboard URL segment)", directory, slug)
        return None
    return slug


def marked_ancestor(projects_dir: Path, rel: str, include_self: bool = True) -> str | None:
    """The rel of the closest ancestor of `rel` (optionally `rel` itself)
    carrying a valid project marker, or None. Projects cannot nest."""
    projects_dir = Path(projects_dir)
    parts = [p for p in str(rel or "").replace("\\", "/").split("/") if p]
    start = len(parts) if include_self else len(parts) - 1
    for i in range(start, 0, -1):
        if read_marker(projects_dir / Path(*parts[:i])) is not None:
            return "/".join(parts[:i])
    return None


def marked_descendants(directory: Path, max_depth: int = 8) -> list[str]:
    """Rel paths (relative to `directory`) BELOW it that carry a marker.

    scan_project_dirs prunes its descent at every marker, so a marker
    hand-dropped on a CONTAINER (e.g. Projects/2026/CCT/) makes every real
    project underneath vanish from discovery -- and provisioning a Syncthing
    folder for the container then either nests folders or 400s and aborts the
    whole cycle. This is the direct look-below that catches that case."""
    import os as _os

    directory = Path(directory)
    found: list[str] = []
    for dirpath, dirnames, filenames in _os.walk(directory):
        current = Path(dirpath)
        rel = current.relative_to(directory)
        parts = () if rel == Path(".") else rel.parts
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if len(parts) >= max_depth:
            dirnames[:] = []
        if parts and MARKER_FILENAME in filenames:
            found.append(rel.as_posix())
            dirnames[:] = []   # no nested projects below a project
    found.sort()
    return found


def write_marker(directory: Path, slug: str, created_by: str = "dashboard") -> None:
    """Atomic marker write (tmp + replace) so a concurrent scan never sees a
    partial file. Raises OSError on failure -- callers decide severity.

    MERGES over any existing marker (SHARED_FOLDERS_PLAN.md WP1): additive
    keys like `includes` survive a rewrite of the identity. Before this, any
    write here (self-heal, adopt, repair) silently dropped every key it did
    not know about."""
    import datetime as _dt
    import json
    import os as _os

    data = read_marker_data(directory) or {}
    data.update({
        "slug": slug,
        "created_by": created_by,
        "created_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
    })
    write_marker_data(directory, data)


def write_marker_data(directory: Path, data: dict) -> None:
    """Atomic full-marker write (tmp + replace). The caller holds the whole
    dict (from read_marker_data) -- the link-authoring endpoints go through
    here so every key they do not own survives verbatim."""
    import json
    import os as _os

    payload = json.dumps(data, indent=1, ensure_ascii=False)
    target = Path(directory) / MARKER_FILENAME
    tmp = Path(directory) / (MARKER_FILENAME + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    _os.replace(tmp, target)


def scan_project_dirs(projects_dir: Path, max_depth: int = 8) -> list[tuple[str, str | None]]:
    """(rel_posix, marker_slug) for every directory carrying MARKER_FILENAME,
    at ANY depth up to max_depth. Hidden dirs are skipped; descent is PRUNED
    at each marker (projects cannot nest). marker_slug is None when the
    marker file exists but is unreadable/malformed -- callers log + skip.

    Bare directories (no marker) are deliberately invisible: since
    2026-07-25 a folder is a project only because someone designated it
    (picker, create flow, setup_tree.py). The old rule -- 'anything at
    exactly depth 3' -- mis-provisioned container folders the moment the
    tree grew a fourth level.
    """
    import os as _os

    projects_dir = Path(projects_dir)
    found: list[tuple[str, str | None]] = []
    for dirpath, dirnames, filenames in _os.walk(projects_dir):
        current = Path(dirpath)
        rel = current.relative_to(projects_dir)
        parts = () if rel == Path(".") else rel.parts
        depth = len(parts)
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if depth > max_depth:
            dirnames[:] = []
            continue
        if depth == 0:
            continue  # the Projects root itself is never a project
        if MARKER_FILENAME in filenames:
            found.append((rel.as_posix(), read_marker(current)))
            dirnames[:] = []  # no nested projects
    found.sort()
    return found


def build_folder_config(
    slug: str, rel: str, data_prefix: str, device_ids: list[str]
) -> dict:
    return {
        "id": slug,
        "label": rel,
        "path": f"{data_prefix.rstrip('/')}/{rel}",
        "type": "sendreceive",
        "fsWatcherEnabled": True,
        # dataset is aclmode=restricted; chmod fails without this
        "ignorePerms": True,
        "rescanIntervalS": 3600,
        # WAN pull tuning (AUDIT_2 P6/§4.2). Both are per-folder puller
        # knobs: maxConcurrentWrites raises in-flight block writes from
        # Syncthing's default 2, and pullerMaxPendingKiB (64 MiB) lets the
        # puller keep more blocks in flight on a high-latency link.
        # copiers/hashers are deliberately left unset (0 == auto): pinning
        # them is how you starve a box with many folders.
        "maxConcurrentWrites": 32,
        "pullerMaxPendingKiB": 65536,
        "versioning": {
            "type": "staggered",
            "params": {"cleanInterval": "3600", "maxAge": "31536000"},
        },
        # delete-protection (2026-08-11, docs/delete-protection-ignoredelete.md):
        # the NAS copy is the authority and never applies a delete an editor
        # made, so an accidental single-file delete only removes the file on
        # the machine that made it. Kept byte-identical to
        # server/setup_syncthing_folder.py and the companion's accept_folder
        # (server/tests/test_cross_component.py asserts it).
        "ignoreDelete": True,
        "devices": [{"deviceID": device_id, "introducedBy": ""} for device_id in device_ids],
    }
