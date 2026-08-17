"""Shared helpers for the Creators Club sync server scripts.

Style conventions used across every script in this package:
  - Python + `requests` for TrueNAS REST API calls (https://<host>/api/v2.0/...)
    and Syncthing REST API calls (http(s)://<gui>/rest/...).
  - `paramiko` for SSH, copying the pattern from ~/scripts/truenas_ssh.py:
    creds from env vars, command piped via a single exec_command call,
    `echo "$SUDO_PW" | sudo -S <cmd>` for root actions. $SUDO_PW is read
    from the SSH channel's STDIN by the remote shell, never placed on the
    remote command line (AUDIT SEC-2: argv is world-readable via `ps`).
  - Every credential comes from an environment variable. Nothing is ever
    hardcoded. See each script's --help / README for the exact var names.
  - Every script accepts --dry-run. In dry-run mode no network call/SSH
    session is opened; the exact call that *would* be made is printed
    instead, prefixed "[dry-run]".
  - Every real action prints one line saying what happened: "created X",
    "already exists, skipping X", "updated X", etc. so a human (or the
    orchestrator) reading stdout can tell what changed on a re-run.

None of the functions in this file talk to the network at import time.
"""
from __future__ import annotations

import os
import re
import sys
import tomllib
from pathlib import Path

import urllib3

# TrueNAS uses a self-signed cert by default; suppress the noisy warning
# (same as the `curl -sk` pattern already used against this host).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class EnvError(RuntimeError):
    """A configuration refusal: a required env var, flag or site.toml key is
    missing. Defined up here (it used to live beside require_env, further
    down) because the site loader below runs at IMPORT time and raises it."""


# --------------------------------------------------------------------------
# site.toml -- who this deployment is (WP0 step 4, 2026-08-17)
# --------------------------------------------------------------------------
#
# Until 2026-08-17 every one of the constants below was a literal from THIS
# fleet's NAS (192.168.0.102, /mnt/tank/TheCreatorsPool, ...). That is a fork
# waiting to happen the moment a second site exists -- see
# docs/COMMERCIAL_READINESS.md item 10 and docs/SYNOLOGY_PORT_PLAN.md WP0 --
# so the identity moved OUT of the code and into one file, and the shipped
# defaults are blank.
#
# Precedence is unchanged where it already existed: a --flag beats an env var
# beats site.toml beats blank. Blank is a REFUSAL, not a fallback: a script
# that cannot name the tree it is about to chown -R must stop, and say which
# key it wanted (require_site_value).
#
# SECRETS ARE NOT IN HERE. TRUENAS_PW / SYNCTHING_API_KEY / DASH_* stay in the
# environment; site.toml is meant to be readable, diffable and (if a site
# wants) committed.
SITE_ENV_VAR = "CCSYNC_SITE"
SITE_FILENAME = "site.toml"
REPO_ROOT = Path(__file__).resolve().parents[1]

_SITE: dict | None = None
_SITE_PATH = ""


def site_path_from_argv(argv=None) -> str:
    """The `--site <path>` value on the command line, or "".

    Read from argv at IMPORT time rather than after argparse, because the
    constants below are argparse DEFAULTS: by the time a parser exists they
    have already been baked into it. Every script also accepts --site through
    add_site_arg() so that `--help` documents it and a typo is caught.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    for i, tok in enumerate(argv):
        if tok == "--site" and i + 1 < len(argv):
            return argv[i + 1]
        if tok.startswith("--site="):
            return tok.split("=", 1)[1]
    return ""


def load_site(path: str | Path | None = None, reload: bool = False) -> dict:
    """Load the site manifest. Search order: `path` / --site, $CCSYNC_SITE,
    <repo>/site.toml, else {} (every value falls back to blank).

    A named-but-missing file is an error -- an operator who passed --site meant
    it. An absent <repo>/site.toml is not: that is the un-configured state, and
    the refusal the caller gets later names the key it needed.
    """
    global _SITE, _SITE_PATH
    if _SITE is not None and not reload and path is None:
        return _SITE

    candidate = str(path or "").strip() or site_path_from_argv() or \
        os.environ.get(SITE_ENV_VAR, "").strip()
    explicit = bool(candidate)
    if not candidate:
        candidate = str(REPO_ROOT / SITE_FILENAME)

    data: dict = {}
    p = Path(candidate)
    if p.is_file():
        with p.open("rb") as fh:
            data = tomllib.load(fh)
        _SITE_PATH = str(p)
    elif explicit:
        raise EnvError(f"--site/{SITE_ENV_VAR} points at {candidate!r}, which is not a file")
    else:
        _SITE_PATH = ""
    _SITE = data
    return data


def site_file() -> str:
    """Path of the site.toml that was loaded, or "" if there was none."""
    load_site()
    return _SITE_PATH


def site_value(section: str, key: str, default: str = "") -> str:
    """One string from site.toml, or `default`. Never raises for absence."""
    table = load_site().get(section) or {}
    if not isinstance(table, dict):
        return default
    value = table.get(key, default)
    return "" if value is None else str(value).strip()


def site_int(section: str, key: str, default: int) -> int:
    raw = site_value(section, key)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def site_bool(section: str, key: str, default: bool = False) -> bool:
    raw = site_value(section, key).lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def add_site_arg(ap) -> None:
    """Add the shared --site flag (see site_path_from_argv for why the value
    is also read straight out of argv at import time)."""
    ap.add_argument("--site", default="",
                    help=f"path to the site manifest ({SITE_FILENAME}); defaults to "
                         f"${SITE_ENV_VAR} or <repo>/{SITE_FILENAME}. It carries the "
                         f"NAS host, tree root and app paths -- never secrets. "
                         f"Start from site.example.toml.")


def require_site_value(value: str, key: str, flag: str = "") -> str:
    """Return `value`, or refuse naming the site.toml key that would set it.

    The refusal exists because the alternative -- a default pointing at the
    Creators Club NAS -- silently aims someone else's deploy at this fleet's
    IP and pool names (COMMERCIAL_READINESS.md item 10).
    """
    value = str(value or "").strip()
    if value:
        return value
    where = site_file() or f"<repo>/{SITE_FILENAME}"
    raise EnvError(
        f"{key} is not configured. Set it in {where}"
        + (f", or pass {flag}" if flag else "")
        + f". Copy site.example.toml to {SITE_FILENAME} and fill it in -- there are "
        f"deliberately no built-in defaults for site identity (host, pool, tree)."
    )


# --------------------------------------------------------------------------
# Constants shared by more than one script
# --------------------------------------------------------------------------
#
# Every one of these is "" when site.toml does not say. That blank is the
# whole point: see require_site_value.

DEFAULT_NAS_KIND = site_value("nas", "kind") or "truenas"
DEFAULT_TRUENAS_HOST = site_value("nas", "host")
DEFAULT_TRUENAS_USER = site_value("nas", "admin_user")
# <pool_root>/<tree_name> -- e.g. /mnt/tank/TheCreatorsPool + Creators_Club.
# BOTH are required: half of a path is not a path, so a site that names only
# the pool gets the same refusal as one that names neither.
DEFAULT_DATASET_ROOT = site_value("tree", "pool_root")
TREE_NAME = site_value("tree", "tree_name")
DEFAULT_CC_ROOT = (f"{DEFAULT_DATASET_ROOT.rstrip('/')}/{TREE_NAME}"
                   if DEFAULT_DATASET_ROOT and TREE_NAME else "")
PROJECTS_DIRNAME = site_value("tree", "projects_dir") or "Projects"
DEFAULT_PROJECTS_ROOT = f"{DEFAULT_CC_ROOT}/{PROJECTS_DIRNAME}" if DEFAULT_CC_ROOT else ""
# The shared b-roll archive: browsable proxies editors link against, plus
# the search index that serves them. Beside Projects/ under the tree root,
# which is what makes it P:\Assets\B-roll Archive on an editor's machine.
DEFAULT_BROLL_ARCHIVE_ROOT = f"{DEFAULT_CC_ROOT}/Assets/B-roll Archive" if DEFAULT_CC_ROOT else ""
# Where editor home directories are created (the PARENT, never a home).
# <pool_root>/homes on TrueNAS; DSM's User Home service puts them at
# /var/services/homes, so a site there sets [tree] homes_parent explicitly.
# The dashboard's own copy of this constant
# (dashboard/src/ccsync_dashboard/nas/truenas.py HOME_PARENT) is the same value
# arrived at separately -- the container cannot import this module.
DEFAULT_HOMES_PARENT = site_value("tree", "homes_parent") or (
    f"{DEFAULT_DATASET_ROOT.rstrip('/')}/homes" if DEFAULT_DATASET_ROOT else "")
# Where the dashboard app's own host tree lives (code, venv, data, the
# read-only artefact mounts). TrueNAS: /mnt/<pool>/apps/ccsync-dashboard.
DEFAULT_APPS_ROOT = site_value("apps", "root")
DEFAULT_DATASET_OWNER = site_value("stack", "owner") or "broll"
EDITORS_GROUP = site_value("stack", "group") or "editors"

# --------------------------------------------------------------------------
# Shared asset folders (added 2026-08-05)
# --------------------------------------------------------------------------
#
# Everything else in this system is PER PROJECT: a directory carrying a
# .ccsync-project marker gets a Syncthing folder, and an editor ticking it on
# the dashboard is what shares that folder with them. A shared asset folder is
# the other shape -- one fleet-wide library, outside Projects/, that every
# editor gets automatically and nobody ticks.
#
# The LUT library is the first one. It is small (tens of MB), it is useless to
# have on only some machines, and unlike a project there is no per-editor
# reason to want it absent -- so the tick model would be pure friction. It is
# deliberately NOT a project: it has no marker, it never appears in the
# dashboard project list, and the collector's project discovery never sees it
# (that walks Projects/ only).
SHARED_ASSETS_REL = "Assets"
LUTS_FOLDER_ID = "assets-luts"
LUTS_REL = "Assets/Luts"
DEFAULT_LUTS_ROOT = DEFAULT_CC_ROOT + "/" + LUTS_REL

# The shared Resolve gallery (stills + PowerGrades). Resolve derives the
# gallery directory from a media storage entry rather than naming it
# directly, and machines sharing a project database are expected to agree --
# hence the "stills location is not the same" complaint at launch when they
# don't. Every machine points its gallery at this one directory.
STILLS_FOLDER_ID = "assets-stills"
STILLS_REL = "Assets/Stills"
DEFAULT_STILLS_ROOT = DEFAULT_CC_ROOT + "/" + STILLS_REL

# (folder id, rel path under Creators_Club, human label). One entry per shared
# asset folder; the dashboard collector provisions and shares every one of
# them, and the companion accepts every one of them. Adding a second library
# (title templates, sound FX, Fusion macros) is a one-line change here plus
# the same line in dashboard/provision.py's copy.
SHARED_ASSET_FOLDERS = [
    (LUTS_FOLDER_ID, LUTS_REL, "Assets/Luts (LUT library)"),
    (STILLS_FOLDER_ID, STILLS_REL, "Assets/Stills (Resolve gallery)"),
]

# Project template subfolders, relative to <projects_root>/<year>/<series>/<project>/
# Per SPEC.md canonical layout (Z:\Cablewrap\Projects\2025\FF4\Nuclear) with Audio
# split into Music / Voiceover subfolders. Proxy/ subfolders are NOT pre-created;
# the Blackmagic Proxy Generator creates them on demand next to media.
TEMPLATE_FOLDERS = [
    "AE",
    "Audio/Music",
    "Audio/Voiceover",
    "B-roll",
    "Interviewees",
    "Render in Place",
    "Subs",
    "Youtube",
]

# Video extensions: these travel via rclone lanes A (up) / B (down), never
# via Syncthing (lane C), so lane C's .stignore must exclude them.
VIDEO_EXTENSIONS = [
    ".braw", ".mov", ".mp4", ".mxf", ".avi", ".mts", ".m2ts", ".mkv",
    ".r3d", ".crm", ".mpg", ".mpeg", ".wmv", ".webm", ".insv", ".360",
]


# --------------------------------------------------------------------------
# Pure logic (unit-testable, no I/O)
# --------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Turn a project path like '2025/FF4/Nuclear' or '2025\\FF4\\Nuclear My
    Cut' into a stable, filesystem/URL-safe id, e.g. '2025-ff4-nuclear-my-cut'.

    Used for Syncthing folder IDs, which must be short, unique, and stable
    across renames of the human-facing label.
    """
    text = text.replace("\\", "/")
    text = text.strip().lower()
    # split on path separators and any non-alnum run, rejoin with '-'
    parts = re.split(r"[^a-z0-9]+", text)
    parts = [p for p in parts if p]
    slug = "-".join(parts)
    if not slug:
        raise ValueError(f"slugify({text!r}) produced an empty slug")
    return slug


# rclone runs with its default --inplace=false, so lane A writes
# "<name>.<token>.partial" (and the express run "<name>.<token>.exp.partial")
# into the NAS project dir -- which is also a sendreceive Syncthing root. A
# lane A killed mid-transfer of a 40 GB .braw leaves that behind, lane A never
# deletes, and the extension patterns above match by EXTENSION so
# "A001.braw.42048420.partial" matched NONE of them: the NAS indexed the
# 39 GB orphan and fanned it out over lane C to every editor with the project
# ticked, where nothing ever removes it (KNOWN_BUGS B12). Both forms are
# emitted for parity with the Proxy/.ccsync-tmp patterns above; keep this
# list byte-identical to dashboard provision.build_stignore_lines() and
# companion sync/syncthing_admin.STIGNORE_LINES (server/tests/
# test_cross_component.py asserts exactly that).
PARTIAL_IGNORE_LINES = ["(?i)**/*.partial", "(?i)*.partial"]

# yt-dlp's in-flight files, same failure as B12 one lane over. The NAS-side
# ytdl worker downloads INTO the shared Projects tree (Youtube/), which is a
# sendreceive Syncthing root, so lane C replicated every growing `.part` out
# to each editor with the project ticked. Since the 2026-08-11 delete-
# protection retrofit set ignoreDelete=True on EDITOR folders too, the
# rename/delete the worker performs on completion never propagates: what
# lands on an editor's disk is permanent until someone deletes it by hand.
# Observed live 2026-08-13/14 on editor ruskin's machine -- 27 orphaned
# .part/.ytdl files, ~1.5 GB, accumulated over three days.
#
# rclone lane B has excluded `- *.part` / `- *.ytdl` since the Youtube/
# includes were added (companion sync/rclone_lane.build_filter_rules_down),
# so Syncthing was the LAST lane still leaking them; this closes it.
#
# `.part-FragN` needs its own pair: a fragment is named "<file>.part-Frag84"
# and does NOT end in `.part` (see ytdl/web/ytdlweb/worker.py `_sweepable`,
# which tests `.part-Frag` as a separate prefix for exactly this reason), so
# `*.part` alone would leave the fragments syncing.
#
# Deliberately NOT folded into PARTIAL_IGNORE_LINES above: that list is also
# spent by build_asset_stignore_lines(), whose output must stay byte-
# identical across server/dashboard/companion or the collector and the
# companion rewrite the LUT library's .stignore at each other every cycle
# (server/tests/test_cross_component.py pins it). No ytdl worker writes into
# a shared asset folder, so the lines have no business there.
#
# For these to SURVIVE on a live folder, dashboard provision.
# build_stignore_lines() and companion syncthing_admin.STIGNORE_LINES need
# the identical lines: the dashboard collector's _ensure_ignores() compares
# a folder's live ignores to its own list with `have == want` and re-POSTs
# on any difference, so a pattern only this file knows about is stripped on
# the next provision cycle.
YTDL_IGNORE_LINES = [
    "(?i)**/*.part", "(?i)*.part",
    "(?i)**/*.part-Frag*", "(?i)*.part-Frag*",
    "(?i)**/*.ytdl", "(?i)*.ytdl",
]


def build_stignore_lines() -> list[str]:
    """Build the .stignore content for a project's Syncthing folder.

    One case-insensitive line per video extension, plus a case-insensitive
    line ignoring any Proxy/ directory anywhere in the tree (proxies travel
    via rclone lane B, not Syncthing), rclone's orphaned .partial files and
    yt-dlp's in-flight .part/.part-FragN/.ytdl files.
    """
    lines = [f"(?i)*{ext}" for ext in VIDEO_EXTENSIONS]
    lines.extend(PARTIAL_IGNORE_LINES)
    lines.extend(YTDL_IGNORE_LINES)
    # Bare name matches a Proxy dir at ANY depth including the folder root;
    # the **/ variants alone would miss a root-level Proxy/.
    lines.append("(?i)Proxy")
    lines.append("(?i)**/Proxy")
    lines.append("(?i)**/Proxy/**")
    return lines


# Junk that every OS scatters through a browsed directory tree. The LUT
# library is opened in Explorer/Finder constantly (that is how a LUT gets
# added), so without these every editor's thumbnail cache and folder-view
# settings would fan out to the whole fleet and conflict-copy against each
# other. Same three-form convention as the patterns above: the extension
# forms match by extension, the bare/`**` forms match by name.
ASSET_JUNK_IGNORE_LINES = [
    "(?i)**/.DS_Store", "(?i).DS_Store",
    "(?i)**/Thumbs.db", "(?i)Thumbs.db",
    "(?i)**/desktop.ini", "(?i)desktop.ini",
    "(?i)**/*.tmp", "(?i)*.tmp",
    "(?i)**/*.ccsync-tmp", "(?i)*.ccsync-tmp",
]


def build_asset_stignore_lines() -> list[str]:
    """The .stignore for a SHARED ASSET folder (the LUT library) -- a
    different list from build_stignore_lines() above, and deliberately so.

    A project folder ignores video because lanes A and B carry it instead.
    A shared asset folder has no lane A or B: whatever this list ignores
    simply never syncs, anywhere, silently. So it ignores only two things:

      * OS junk (see ASSET_JUNK_IGNORE_LINES) -- pure noise, and the reason
        every editor would otherwise conflict-copy .DS_Store files at each
        other.
      * video, as a BLAST-RADIUS BRAKE. This folder is sendreceive and
        auto-shared with every editor, with no tick to opt out of, so a
        40 GB .mov dropped in it by accident would land on every machine in
        the fleet. Nothing that belongs in a LUT library is a video file --
        a pack's sample clip is the only realistic case, and it is worth
        losing to keep the brake. This is documented in EDITOR_SETUP.md so
        it is not a silent surprise.

    rclone's .partial pattern is included for symmetry only: no rclone lane
    ever writes here. YTDL_IGNORE_LINES deliberately is NOT: the ytdl worker
    writes into Projects/, never into a shared asset folder, and this list
    must stay byte-identical to the dashboard's and the companion's copies.
    """
    lines = [f"(?i)*{ext}" for ext in VIDEO_EXTENSIONS]
    lines.extend(PARTIAL_IGNORE_LINES)
    lines.extend(ASSET_JUNK_IGNORE_LINES)
    return lines


def project_relative_dirs(base: str = "") -> list[str]:
    """Return TEMPLATE_FOLDERS optionally prefixed with `base` (posix style).

    Kept separate from TEMPLATE_FOLDERS itself so tests can assert the raw
    template list independently of any prefix-joining logic.
    """
    if not base:
        return list(TEMPLATE_FOLDERS)
    base = base.rstrip("/")
    return [f"{base}/{folder}" for folder in TEMPLATE_FOLDERS]


def project_path(projects_root: str, year: str, series: str, project: str) -> str:
    """Build the absolute NAS path for a project, posix-style, no trailing slash.

    Rejects the same shapes project_path_rel() does -- `..`, a leading dot, an
    empty segment -- and not only the separators. Until 2026-08-17 only "/" and
    "\\" were refused here, so `--series ..` walked one level OUT of the
    projects root and everything downstream (mkdir -p, chown -R, the marker
    write) then ran as root against whatever was there
    (COMMERCIAL_READINESS.md item 9). project_path_rel has always checked this;
    the two entry points now agree.
    """
    cleaned = []
    for part, name in ((year, "year"), (series, "series"), (project, "project")):
        value = str(part or "").strip()
        if not value or "/" in value or "\\" in value or value.startswith(".") or ".." in value:
            raise ValueError(f"invalid --{name} value: {part!r}")
        cleaned.append(value)
    return f"{projects_root.rstrip('/')}/" + "/".join(cleaned)


def project_path_rel(projects_root: str, rel: str) -> str:
    """Like project_path but for an arbitrary-depth rel path
    ("2026/CCT/Creator Profiles/Season 1"). Validates every segment."""
    rel = str(rel or "").strip().strip("/")
    if not rel:
        raise ValueError("empty --project-rel-path")
    for part in rel.split("/"):
        if not part or "\\" in part or part.startswith(".") or ".." in part:
            raise ValueError(f"invalid path segment: {part!r}")
    return f"{projects_root.rstrip('/')}/{rel}"


# Intentional copy of the dashboard's provision.MARKER_FILENAME (see that
# module's marker docs) -- keep in sync. A directory IS a project because it
# carries this file; the slug inside is its immutable identity.
MARKER_FILENAME = ".ccsync-project"


# A project slug is the identity every dashboard row is keyed on. It has to
# survive being a Syncthing folder id and a URL path segment, so the charset
# is deliberately narrow (this is also slugify()'s own output alphabet).
SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def validate_slug(slug: str) -> str:
    """Return `slug` unchanged, or raise ValueError explaining why it can't be
    a project identity. Applied to --slug AND to slugify() output so both
    paths into a marker enforce the same charset (AUDIT INST-12)."""
    slug = str(slug or "").strip()
    if not slug:
        raise ValueError("empty slug: a project marker must carry an identity")
    if not SLUG_RE.match(slug):
        raise ValueError(
            f"invalid slug {slug!r}: only lowercase a-z, 0-9 and '-' are allowed "
            f"(the slug becomes a Syncthing folder id and a dashboard URL segment)"
        )
    return slug


# sed script pulling the "slug" value out of a marker's JSON, for the shell
# side of the never-overwrite check. Single-quoted below; contains no quotes
# of its own that would need escaping.
_MARKER_SLUG_SED = r's/.*"slug"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'

# read_marker_cmd's third answer. A marker that exists but cannot be read is a
# REFUSAL, not a fallback (see setup_syncthing_folder's module docstring), and
# that distinction only survives if the shell can express it.
MARKER_UNREADABLE_SENTINEL = "MARKER-UNREADABLE"
MARKER_READ_RC = 9


def build_marker_read_cmd(base: str) -> str:
    """Shell reading `base`'s marker, distinguishing THREE states, not two.

    Prints "MARKER-PRESENT" then the marker's contents, or "MARKER-ABSENT", or
    -- when the privileged read could not run at all -- prints
    MARKER_UNREADABLE_SENTINEL on stderr and exits MARKER_READ_RC.

    Read as root: the dataset is 770 and TRUENAS_USER has no traverse rights.

    SERVER-4 (2026-08-14): this used to be
    `if echo "$SUDO_PW" | sudo -S -p "" test -e M; then ... else echo
    MARKER-ABSENT; fi`, and an `if` CONDITION is exempt from its command's exit
    status -- so any sudo-level failure (revoked sudoer, lockout after failed
    attempts, requiretty, a policy change) took the else branch and the whole
    remote command still exited 0. The caller saw a clean "there is no marker
    here" and fell back to slugify(--project-rel-path), which for a project
    that has MOVED is a different identity: a second Syncthing folder over the
    same directory, shared with nobody, cleaned up by nothing -- exactly what
    reading the marker exists to prevent. The sentinels are now printed by the
    privileged shell itself, so sudo failing means no sentinel and a non-zero
    exit, never MARKER-ABSENT.
    """
    marker_q = shell_quote(f"{base}/{MARKER_FILENAME}")
    inner = (f'if [ -e {marker_q} ]; then echo MARKER-PRESENT; cat {marker_q}; '
             f"else echo MARKER-ABSENT; fi")
    return (f'echo "$SUDO_PW" | sudo -S -p "" sh -c {shell_quote(inner)} '
            f"|| {{ echo {MARKER_UNREADABLE_SENTINEL} >&2; exit {MARKER_READ_RC}; }}")


def build_marker_write_cmd(base: str, slug: str, created_by: str = "setup_tree",
                           only_if_absent: bool = False) -> str:
    """Shell line writing the project marker into `base` (root via sudo,
    then chowned by the caller's chown -R). JSON kept minimal + quoted for
    embedding in the SSH script.

    With only_if_absent=True the marker is written ONLY when none is there,
    and an existing one is reported (never clobbered) -- the slug inside is
    the project's immutable identity, and silently reassigning it orphans
    every slug-keyed dashboard row (AUDIT DEL-8). Deliberate identity changes
    go through write_marker.py, where --slug is explicit and --force gates
    the change.
    """
    import json as _json

    payload = _json.dumps({"slug": slug, "created_by": created_by})
    marker_q = shell_quote(f"{base}/{MARKER_FILENAME}")
    payload_q = shell_quote(payload)
    write = (
        f'echo "$SUDO_PW" | sudo -S -p "" sh -c '
        + shell_quote(f"printf '%s' {payload_q} > {marker_q}")
        + f' && echo "marker written: {MARKER_FILENAME}"'
    )
    if not only_if_absent:
        return write

    # Every message below interpolates only shell VARIABLES (SEC-8): the slug
    # itself is passed in via a single-quoted assignment, never pasted into a
    # double-quoted echo.
    return (
        f"want_slug={shell_quote(slug)}; "
        f'if echo "$SUDO_PW" | sudo -S -p "" test -e {marker_q}; then '
        f'  had_slug=$(echo "$SUDO_PW" | sudo -S -p "" cat {marker_q} 2>/dev/null '
        f"| sed -n '{_MARKER_SLUG_SED}' || true); "
        f'  if [ "$had_slug" = "$want_slug" ]; then '
        f'    echo "marker already present with the same identity, left as is: '
        f'{MARKER_FILENAME} (slug $had_slug)"; '
        f"  else "
        f'    echo "marker already present with a DIFFERENT identity: {MARKER_FILENAME} '
        f'keeps slug \'$had_slug\' -- NOT overwriting it with \'$want_slug\'. '
        f"The slug is the project's immutable identity; every dashboard row "
        f"(ticks, Resolve mappings, completion history, media inventory) is keyed "
        f"on it. If this project really must change identity, do it deliberately "
        f'with write_marker.py --slug ... --force"; '
        f"  fi; "
        f"else "
        f"  {write}; "
        f"fi"
    )


def shell_quote(value: str) -> str:
    """Single-quote a value for embedding in a POSIX shell command."""
    return "'" + value.replace("'", "'\\''") + "'"


# --------------------------------------------------------------------------
# Env var loading
# --------------------------------------------------------------------------

# EnvError itself is defined at the top of this module (the site loader needs
# it at import time); this section keeps the loaders that raise it.


def require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise EnvError(
            f"Required environment variable {name} is not set. "
            f"See server/README.md for the full list of env vars this script needs."
        )
    return val


# The NAS admin password, under either platform's name. TRUENAS_PW is what
# every runbook, tools\ship.cmd and this repo's history export; SYNO_PW is what
# a Synology site sets (docs/SERVER-SYNOLOGY.md), because "TRUENAS_PW" for a
# DSM box reads like a copy-paste mistake and a workstation that administers
# both NASes needs two names anyway. Whichever matches [nas] kind wins; the
# other is accepted with a one-time warning rather than refused, since it is
# nearly always the right password typed under the other platform's name.
NAS_PW_ENV = {"truenas": "TRUENAS_PW", "synology": "SYNO_PW"}
_NAS_PW_ALIAS_WARNED = False


def nas_admin_password(dry_run: bool = False, kind: str = "") -> str:
    """The admin password for SSH `sudo -S` and the platform's API.

    In dry-run mode nothing is required -- callers only need host/user to
    print what they would do -- and a placeholder is returned so a local
    `--dry-run` works on a machine with no secret configured at all.
    """
    global _NAS_PW_ALIAS_WARNED
    try:
        chosen = (kind or "").strip().lower() or nas_kind()
    except EnvError:
        chosen = "truenas"
    primary = NAS_PW_ENV.get(chosen, "TRUENAS_PW")
    alias = "SYNO_PW" if primary == "TRUENAS_PW" else "TRUENAS_PW"

    value = os.environ.get(primary, "").strip()
    if value:
        return value
    fallback = os.environ.get(alias, "").strip()
    if fallback:
        if not _NAS_PW_ALIAS_WARNED:
            print(f"NOTE: {primary} is not set; using {alias} instead (this site's "
                  f"[nas] kind is {chosen!r}). Set {primary} to make the intent explicit.",
                  file=sys.stderr)
            _NAS_PW_ALIAS_WARNED = True
        return fallback
    if dry_run:
        return f"<{primary}-unset-dry-run>"
    raise EnvError(
        f"Required environment variable {primary} is not set. "
        f"See server/README.md for the full list of env vars this script needs."
    )


def truenas_conn_params(dry_run: bool = False):
    """host/user/pw for both SSH and REST API against the NAS.

    Named for TrueNAS because that is what every call site has said since
    2026-07; it serves both platforms (DSM's SSH channel is the same
    `sudo -S` shape, and its Web API takes the same admin account), and the
    password comes from whichever of TRUENAS_PW / SYNO_PW this site uses.

    In dry-run mode the password is not required -- callers only need
    host/user to print what they'd do, and a placeholder is used for pw so
    local `--dry-run` verification works without any secret configured.

    host/user ARE required in both modes since 2026-08-17: they used to default
    to this fleet's own NAS, so a fresh checkout with no configuration aimed
    every script at 192.168.0.102 as truenas_admin (COMMERCIAL_READINESS.md
    item 10). Blank now refuses and names the key.
    """
    host = require_site_value(
        os.environ.get("SYNO_HOST", "") or os.environ.get("TRUENAS_HOST", DEFAULT_TRUENAS_HOST),
        "[nas] host", "TRUENAS_HOST")
    user = require_site_value(
        os.environ.get("SYNO_USER", "") or os.environ.get("TRUENAS_USER", DEFAULT_TRUENAS_USER),
        "[nas] admin_user", "TRUENAS_USER")
    return host, user, nas_admin_password(dry_run=dry_run)


# --------------------------------------------------------------------------
# SSH (paramiko), mirrors ~/scripts/truenas_ssh.py
# --------------------------------------------------------------------------

# Host-key pinning (AUDIT SEC-3). Unset -> AutoAddPolicy plus a one-time
# warning, so the default stays "works on a fresh admin box"; set -> the
# offered key must match exactly or the connection is refused.
_HOST_KEY_PIN = ""
_HOST_KEY_WARNED = False


def set_host_key_pin(value: str) -> None:
    """Pin the NAS SSH host key for this process (from --host-key)."""
    global _HOST_KEY_PIN
    _HOST_KEY_PIN = str(value or "").strip()


def host_key_pin() -> str:
    """The configured pin: --host-key (via set_host_key_pin) or
    CCSYNC_SSH_HOSTKEY. Format is one `known_hosts`-style key, with or
    without a leading host field, e.g.

        ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...

    Get it from the NAS with `ssh-keyscan -t ed25519 <host>`.
    """
    return _HOST_KEY_PIN or os.environ.get("CCSYNC_SSH_HOSTKEY", "").strip()


def add_host_key_arg(ap) -> None:
    """Add the shared --host-key flag to an argparse parser."""
    ap.add_argument("--host-key", default="",
                    help="pin the NAS SSH host key (a known_hosts-style line, e.g. "
                         "\"ssh-ed25519 AAAAC3...\"; or set CCSYNC_SSH_HOSTKEY). "
                         "Unset means the key is accepted unverified on first use.")


def _parse_host_key(pin: str):
    """Turn a known_hosts-style pin into (keytype, paramiko.PKey)."""
    import base64
    import paramiko

    # Accept any of: "<type> <base64>", "<host> <type> <base64>" (ssh-keyscan
    # / known_hosts) and "<type> <base64> <comment>" (a .pub file), by
    # anchoring on the key-type token rather than on position.
    parts = pin.split()
    keytype = blob = ""
    for i, tok in enumerate(parts[:-1]):
        if tok.startswith(("ssh-", "ecdsa-", "sk-ssh-", "sk-ecdsa-")):
            keytype, blob = tok, parts[i + 1]
            break
    if not keytype:
        raise EnvError(
            f"host key pin {pin!r} is not a known_hosts-style line "
            f"(expected e.g. 'ssh-ed25519 AAAAC3...')"
        )
    try:
        data = base64.b64decode(blob)
    except Exception as e:  # noqa: BLE001 - any decode failure is the same answer
        raise EnvError(f"host key pin base64 is not decodable: {e}") from e
    try:
        key = paramiko.PKey.from_type_string(keytype, data)
    except AttributeError:
        classes = {
            "ssh-ed25519": getattr(paramiko, "Ed25519Key", None),
            "ssh-rsa": getattr(paramiko, "RSAKey", None),
            "ssh-dss": getattr(paramiko, "DSSKey", None),
            "ecdsa-sha2-nistp256": getattr(paramiko, "ECDSAKey", None),
            "ecdsa-sha2-nistp384": getattr(paramiko, "ECDSAKey", None),
            "ecdsa-sha2-nistp521": getattr(paramiko, "ECDSAKey", None),
        }
        cls = classes.get(keytype)
        if cls is None:
            raise EnvError(f"unsupported host key type in pin: {keytype!r}") from None
        key = cls(data=data)
    except Exception as e:  # noqa: BLE001
        raise EnvError(f"could not parse host key pin: {e}") from e
    return keytype, key


def ssh_client(host: str, user: str, pw: str, timeout: int = 20):
    """Connected paramiko.SSHClient with the shared host-key policy applied.

    Every SSH/SFTP entry point in this package goes through here so the
    pinning decision is made in exactly one place.
    """
    global _HOST_KEY_WARNED

    import paramiko

    client = paramiko.SSHClient()
    pin = host_key_pin()
    if pin:
        keytype, key = _parse_host_key(pin)
        client.get_host_keys().add(host, keytype, key)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        if not _HOST_KEY_WARNED:
            print(f"WARNING: accepting {host}'s SSH host key unverified (first-use trust). "
                  f"Pin it with --host-key or CCSYNC_SSH_HOSTKEY=\"$(ssh-keyscan -t ed25519 "
                  f"{host} | awk '{{print $2, $3}}')\" to make this strict.",
                  file=sys.stderr)
            _HOST_KEY_WARNED = True
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=pw,
                   look_for_keys=False, allow_agent=False, timeout=timeout)
    return client


# The remote shell reads the sudo password from stdin as its first line and
# exports it, so it never appears in the remote process's argv (SEC-2).
SUDO_PW_PREAMBLE = "IFS= read -r SUDO_PW; export SUDO_PW\n"


def run_ssh(cmd: str, dry_run: bool = False, timeout: int = 120):
    """Run `cmd` on the TrueNAS host over SSH as TRUENAS_USER.

    `cmd` should assume $SUDO_PW is exported in its environment if it needs
    `echo "$SUDO_PW" | sudo -S ...`. Returns (rc, stdout, stderr).

    The password is written to the SSH channel's STDIN and read by the remote
    shell (see SUDO_PW_PREAMBLE) rather than passed as `export SUDO_PW=...`,
    which any local NAS account could read out of `ps` (AUDIT SEC-2). `cmd`
    therefore must not consume stdin itself.

    In dry-run mode, nothing is connected; the command is printed and
    (0, "", "") is returned so callers can still exercise their own
    print-what-I-did logic.
    """
    host, user, pw = truenas_conn_params(dry_run=dry_run)
    if dry_run:
        print(f"[dry-run] ssh {user}@{host}: {cmd}")
        return 0, "", ""

    client = ssh_client(host, user, pw)
    try:
        wrapped = SUDO_PW_PREAMBLE + cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=False, timeout=timeout)
        stdin.write(pw + "\n")
        stdin.flush()
        # EOF on stdin: without this a remote `read`/`cat` in cmd would hang
        # waiting for more input.
        stdin.channel.shutdown_write()
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err
    finally:
        client.close()


def sftp_put_text(remote_dir: str, files: dict, dry_run: bool = False) -> bool:
    """Write small TEXT files into `remote_dir` over SFTP. True on success.

    For the compose.yaml + .env pair the Synology deploy installs. Deliberately
    not a heredoc through `sh -c`: the quoting eats a compose file (spike 5),
    and a .env carrying five secrets must never appear in a remote command line
    at all (AUDIT SEC-2 is about argv, and argv is what a heredoc becomes).

    `remote_dir` is in the SFTP channel's own namespace -- on DSM that is the
    share view, not the filesystem (backend.sftp_path does the translation).
    Existing files are replaced; nothing is deleted.
    """
    if dry_run:
        for name, body in files.items():
            print(f"[dry-run] would SFTP {len(body.encode('utf-8'))} bytes to "
                  f"{remote_dir}/{name}")
        return True
    host, user, pw = truenas_conn_params()
    try:
        client = ssh_client(host, user, pw)
        try:
            sftp = client.open_sftp()
            try:
                for name, body in files.items():
                    target = f"{remote_dir.rstrip('/')}/{name}"
                    with sftp.file(target, "w") as fh:
                        fh.write(body)
                    print(f"uploaded {len(body.encode('utf-8'))} bytes to {target} "
                          f"(SFTP view)")
            finally:
                sftp.close()
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001 - any transport failure is one answer
        print(f"FAILED: SFTP write to {remote_dir} did not finish "
              f"({type(exc).__name__}: {exc})", file=sys.stderr)
        return False
    return True


# --------------------------------------------------------------------------
# TrueNAS REST API (requests)
# --------------------------------------------------------------------------

def truenas_api(method: str, path: str, json_body=None, dry_run: bool = False,
                 params=None):
    """Call the TrueNAS REST API (v2.0) with HTTP basic auth.

    `path` must start with '/', e.g. '/user' or '/group'.
    Returns a requests.Response in real mode, or None in dry-run mode.
    """
    host, user, pw = truenas_conn_params(dry_run=dry_run)
    url = f"https://{host}/api/v2.0{path}"
    if dry_run:
        print(f"[dry-run] {method.upper()} {url} params={params} body={json_body}")
        return None

    import requests

    resp = requests.request(
        method, url, json=json_body, params=params,
        auth=(user, pw), verify=False, timeout=30,
    )
    return resp


# --------------------------------------------------------------------------
# Synology DSM Web API (requests) -- docs/synology-spikes-2026-08-17.md
# --------------------------------------------------------------------------
#
# The install-time twin of dashboard/src/ccsync_dashboard/nas/synology.py's
# client. Deliberately a separate implementation rather than a shared module:
# server/ runs on the admin's workstation off `python server/<script>.py` and
# the dashboard runs in a container that cannot import this package -- the same
# split the TrueNAS half has always had. What must NOT diverge is the recorded
# SHAPES; both files cite the same spike document, and both carry the same
# three traps:
#
#   1. SYNO.API.Auth must be VERSION 7. A lower version hands back a sid that
#      reads fine and is refused on every mutation with 105 -- for a full
#      administrators-group account (spike 3.1).
#   2. Every parameter is JSON. A Python `False` reaches DSM as "False" and
#      comes back as error 3103 naming nothing. _dsm_param() is the only way a
#      value is allowed to reach the wire.
#   3. SYNO.Core.Group.Member add returns success whatever you send it and
#      reads `name`, not `members`. Callers read membership back.
#
# Nothing here runs at import time, and --dry-run opens no socket.

SYNO_LOGIN_VERSION = 7
# A NAMED session: DSM tracks sids per session name, so logging this one out
# cannot take the operator's own DSM browser session with it.
SYNO_SESSION_NAME = "ccsync"
SYNO_DEFAULT_PORT = 5001

# Every API/version pair the Synology backend calls, checked against
# SYNO.API.Info before the first login. A DSM that does not offer one of these
# at the version we call is a REFUSAL, not a "try something else": half a
# provisioning run is worse than none (the install_syncthing_app.py pattern,
# 2026-07-22).
SYNO_REQUIRED_APIS = {
    "SYNO.API.Auth": SYNO_LOGIN_VERSION,
    "SYNO.Core.User": 1,
    "SYNO.Core.Group": 1,
    "SYNO.Core.Group.Member": 1,
    "SYNO.Core.User.Group": 1,
    "SYNO.Core.AppPriv.Rule": 1,
    "SYNO.Core.FileServ.FTP.SFTP": 1,
    "SYNO.Core.Share": 1,
    "SYNO.Core.Share.Permission": 1,
    "SYNO.Core.Share.Snapshot": 1,
}

# Codes seen on the wire during the spikes. The text says what to DO, because
# DSM's own message for most of these is the number.
DSM_ERRORS = {
    103: "no such method (this DSM does not implement the call)",
    105: (f"the session has no privilege for this call -- almost always a sid minted with "
          f"SYNO.API.Auth < {SYNO_LOGIN_VERSION}, which DSM refuses on every mutation"),
    119: "the session id expired",
    400: "invalid account or password",
    402: "the account has no permission to log in to DSM",
    403: ("the account needs a 2-factor code, or the feature is not installed "
          "(Share.Snapshot scheduling needs the Snapshot Replication package)"),
    3101: "bad argument (a name that had to be a JSON array was sent as a string)",
    3103: 'invalid parameter -- classically a Python bool serialised as "True"/"False"',
    3106: "no such user",
    3107: "that user already exists",
    3117: "the password does not satisfy this DSM's password policy",
    3201: "bad group argument",
    3205: "no such group",
    3206: "that group already exists",
    3400: "bad/missing parameters (AppPriv.Rule get answers this to everything -- use list)",
}


class DsmError(RuntimeError):
    """A DSM call that answered success:false. Carries the numeric code so a
    caller can branch on the handful that mean something specific (3205 no such
    group, 3107 user exists) without matching on text."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def dsm_message(code: int) -> str:
    return DSM_ERRORS.get(code, f"DSM error {code}")


def _dsm_param(value) -> str:
    """The ONE place a value becomes a DSM parameter (trap 2 above)."""
    import json as _json

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, dict)):
        return _json.dumps(list(value) if isinstance(value, tuple) else value)
    return str(value)


def synology_verify_ssl():
    """False (trust the self-signed DSM cert, the out-of-the-box state), True,
    or a CA bundle path -- from SYNO_VERIFY_SSL / TRUENAS_VERIFY_SSL / [nas]
    verify_ssl, in that order."""
    raw = (os.environ.get("SYNO_VERIFY_SSL", "").strip()
           or os.environ.get("TRUENAS_VERIFY_SSL", "").strip()
           or site_value("nas", "verify_ssl"))
    if raw in ("", "0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    return raw


def synology_port() -> int:
    return site_int("nas", "dsm_port", SYNO_DEFAULT_PORT)


# (host, user) -> {"sid", "token", "paths"}. Module-level so a script making
# twenty calls logs in once; keyed by identity so a test that switches host
# does not inherit a stale sid.
_DSM_SESSIONS: dict = {}
_DSM_REDACT = ("passwd", "password")


def dsm_reset_session() -> None:
    """Forget every cached sid (tests, and the retry after a 119)."""
    _DSM_SESSIONS.clear()


def _dsm_url(host: str, cgi: str) -> str:
    return f"https://{host}:{synology_port()}/webapi/{cgi}"


def _dsm_http(host: str, cgi: str, params: dict, post: bool, token: str = ""):
    import requests

    url = _dsm_url(host, cgi)
    headers = {"X-SYNO-TOKEN": token} if token else {}
    if post:
        return requests.post(url, data=params, headers=headers,
                             verify=synology_verify_ssl(), timeout=30)
    return requests.get(url, params=params, headers=headers,
                        verify=synology_verify_ssl(), timeout=30)


def _dsm_body(resp, what: str) -> dict:
    """resp.json() that cannot raise something unrelated: a 2xx carrying HTML
    (a reverse proxy's error page, DSM's login redirect) would otherwise come
    back as a JSONDecodeError traceback halfway through an install."""
    if not 200 <= resp.status_code < 300:
        raise DsmError(0, f"{what}: DSM answered HTTP {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise DsmError(0, f"{what}: response was not JSON ({resp.text[:120]!r})") from exc
    if not isinstance(body, dict):
        raise DsmError(0, f"{what}: response was not a JSON object ({resp.text[:120]!r})")
    return body


def _dsm_check_shapes(host: str) -> dict:
    """SYNO.API.Info for every API this repo calls. Returns {api: cgi path}.

    Refuse rather than guess: a DSM that offers Auth <= 6 is not "slightly
    older", it is a box where every mutation answers 105 and an install would
    half-create the tree, the group and the accounts before anyone noticed
    (spike 3.1).
    """
    params = {"api": "SYNO.API.Info", "version": "1", "method": "query",
              "query": ",".join(sorted(SYNO_REQUIRED_APIS))}
    body = _dsm_body(_dsm_http(host, "query.cgi", params, post=False),
                     "SYNO.API.Info.query")
    if not body.get("success"):
        raise DsmError(0, f"the DSM web API at {host}:{synology_port()} refused "
                          f"SYNO.API.Info -- this does not look like a DSM 7 box")
    info = body.get("data") or {}
    paths, problems = {}, []
    for api, want in sorted(SYNO_REQUIRED_APIS.items()):
        entry = info.get(api)
        if not isinstance(entry, dict):
            problems.append(f"{api}: not offered by this DSM")
            continue
        paths[api] = str(entry.get("path") or "entry.cgi")
        low = int(entry.get("minVersion") or 1)
        high = int(entry.get("maxVersion") or 0)
        if not low <= want <= high:
            problems.append(f"{api}: need version {want}, this DSM offers {low}-{high}")
    if problems:
        raise DsmError(0,
                       "this DSM does not offer the web API shapes CC Sync installs with: "
                       + "; ".join(problems)
                       + ". Refusing to guess a different shape -- a half-provisioned NAS "
                         "is worse than an unprovisioned one. See "
                         "docs/synology-spikes-2026-08-17.md spike 3.")
    return paths


def _dsm_session(host: str, user: str, pw: str) -> dict:
    """Log in (version 7, format=sid) and cache the sid + SynoToken."""
    cached = _DSM_SESSIONS.get((host, user))
    if cached:
        return cached
    paths = _dsm_check_shapes(host)
    params = {
        "api": "SYNO.API.Auth", "method": "login",
        "version": str(SYNO_LOGIN_VERSION),
        "account": user, "passwd": pw, "session": SYNO_SESSION_NAME,
        "format": "sid", "enable_syno_token": "yes",
    }
    # POSTed, so the password is not in a request line DSM writes to its own
    # log -- the same reason its own UI posts the login.
    body = _dsm_body(_dsm_http(host, paths.get("SYNO.API.Auth", "auth.cgi"), params, post=True),
                     "SYNO.API.Auth.login")
    if not body.get("success"):
        code = int((body.get("error") or {}).get("code") or 0)
        raise DsmError(code, f"DSM login for {user!r} failed: error {code} -- {dsm_message(code)}")
    data = body.get("data") or {}
    sid = data.get("sid")
    if not sid:
        raise DsmError(0, "DSM login succeeded but returned no sid (format=sid was ignored)")
    session = {"sid": str(sid), "token": str(data.get("synotoken") or ""), "paths": paths}
    _DSM_SESSIONS[(host, user)] = session
    return session


def synology_api(api: str, method: str, version: int = 1, post: bool = False,
                 dry_run: bool = False, **params) -> dict:
    """One DSM Web API call. Returns the `data` object; raises DsmError.

    `post=True` for anything that changes state (DSM accepts either, but a GET
    that mutates ends up in access logs with its parameters).

    In dry-run mode nothing is connected: the call is printed, secrets
    redacted, and {} is returned -- the same contract truenas_api() has.
    """
    host, user, pw = truenas_conn_params(dry_run=dry_run)
    if dry_run:
        shown = {k: ("<redacted>" if k in _DSM_REDACT else v) for k, v in params.items()}
        print(f"[dry-run] DSM {api}.{method} v{version} on {host}: {shown}")
        return {}

    for attempt in (1, 2):
        session = _dsm_session(host, user, pw)
        call = {"api": api, "method": method, "version": _dsm_param(version)}
        call.update({k: _dsm_param(v) for k, v in params.items() if v is not None})
        call["_sid"] = session["sid"]
        if session["token"]:
            call["SynoToken"] = session["token"]
        what = f"{api}.{method}"
        body = _dsm_body(
            _dsm_http(host, session["paths"].get(api, "entry.cgi"), call, post,
                      token=session["token"]),
            what)
        if body.get("success"):
            data = body.get("data")
            return data if isinstance(data, dict) else {"data": data}
        code = int((body.get("error") or {}).get("code") or 0)
        # 119 = the sid aged out, which is expected on a long install. Anything
        # else is reported as-is -- 105 in particular must NOT be retried: it
        # means the login version was wrong and a retry only doubles the wait.
        if code == 119 and attempt == 1:
            _DSM_SESSIONS.pop((host, user), None)
            continue
        raise DsmError(code, f"{what} failed: DSM error {code} -- {dsm_message(code)}")
    raise DsmError(119, f"{api}.{method} kept losing its DSM session")


# --------------------------------------------------------------------------
# Syncthing REST API (requests)
# --------------------------------------------------------------------------

def syncthing_api(method: str, gui_url: str, path: str, api_key: str,
                   json_body=None, dry_run: bool = False, params=None):
    """Call a Syncthing REST endpoint, e.g. path='/rest/config/folders'."""
    url = gui_url.rstrip("/") + path
    if dry_run:
        print(f"[dry-run] {method.upper()} {url} params={params} body={json_body}")
        return None

    import requests

    headers = {"X-API-Key": api_key}
    resp = requests.request(
        method, url, json=json_body, params=params,
        headers=headers, timeout=30,
    )
    return resp


def ok(resp) -> bool:
    """True if a requests.Response looks like a 2xx success."""
    return resp is not None and 200 <= resp.status_code < 300


def wait_for_job(job_id: int, timeout: float = 120.0, poll: float = 2.0):
    """Block until a TrueNAS job finishes. Returns (state, error_or_None).

    Several TrueNAS endpoints (filesystem.setperm among them) return a job id
    immediately and do the work asynchronously, so a 200 from the POST only
    means "accepted" — the call can still fail afterwards. Returns
    ("TIMEOUT", msg) rather than raising if the job never settles.
    """
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(poll)
        resp = truenas_api("GET", "/core/get_jobs", params={"id": job_id})
        if not ok(resp):
            continue
        rows = resp.json()
        if not rows:
            continue
        job = rows[0]
        state = job.get("state")
        if state in ("SUCCESS", "FAILED", "ABORTED"):
            return state, job.get("error")
    return "TIMEOUT", f"job {job_id} did not finish within {timeout}s"


# --------------------------------------------------------------------------
# Backend selection (docs/SYNOLOGY_PORT_PLAN.md WP3, 2026-08-17)
# --------------------------------------------------------------------------
#
# Everything platform-specific a server script does -- create the app/stack,
# restart it, create the editors group and the editor account, fix a home
# directory sshd will accept, own the tree, ask tailscale for its status --
# lives on a backend object now. `server/backends/truenas.py` is the code that
# used to sit inline in these scripts, moved unchanged;
# `server/backends/synology.py` is the stub the DSM port fills in.
#
# The scripts keep their CLI, their --dry-run semantics and their output text:
# a backend method is a lift, not a redesign.

NAS_KIND_ENV = "CCSYNC_NAS_KIND"
NAS_KINDS = ("truenas", "synology")


def add_nas_kind_arg(ap) -> None:
    ap.add_argument("--nas-kind", choices=NAS_KINDS, default="",
                    help=f"which NAS platform this site runs on; defaults to "
                         f"${NAS_KIND_ENV}, else [nas] kind in {SITE_FILENAME}, "
                         f"else {DEFAULT_NAS_KIND!r}.")


def nas_kind(args=None) -> str:
    """--nas-kind, else $CCSYNC_NAS_KIND, else site.toml, else 'truenas'."""
    flag = str(getattr(args, "nas_kind", "") or "").strip().lower()
    env = os.environ.get(NAS_KIND_ENV, "").strip().lower()
    kind = flag or env or DEFAULT_NAS_KIND
    if kind not in NAS_KINDS:
        raise EnvError(f"unknown NAS kind {kind!r}: expected one of {', '.join(NAS_KINDS)}")
    return kind


class ScriptCalls:
    """How a backend reaches the NAS: through the CALLING SCRIPT's own names.

    Not decoration. server/tests patches `install_dashboard_app.truenas_api`,
    `check_health.run_ssh` and friends on the SCRIPT module to run the whole
    suite offline; a backend that imported common.truenas_api directly would
    sail straight past those patches and the tests would silently stop testing
    anything (2026-08-17, when the bodies moved into backends/). Attribute
    lookup happens per call, so a monkeypatch applied after the backend was
    built still takes effect.
    """

    def __init__(self, module=None):
        self._module = module

    def _resolve(self, name):
        return getattr(self._module, name, None) or globals()[name]

    def api(self, *a, **kw):
        return self._resolve("truenas_api")(*a, **kw)

    def ssh(self, *a, **kw):
        return self._resolve("run_ssh")(*a, **kw)

    def ssh_guarded(self, cmd, dry_run, timeout):
        """The caller's run_ssh_guarded if it has one, else plain ssh.

        Only install_dashboard_app.py has a guarded variant (OPS-3: a dropped
        transport is an error RESULT, not a traceback, because the caller may
        be on the post-swap failure path). Resolving it here keeps the restart
        exactly as guarded as it was before the body moved (2026-08-17).
        """
        guarded = getattr(self._module, "run_ssh_guarded", None)
        if guarded is not None:
            return guarded(cmd, dry_run, timeout)
        return self.ssh(cmd, dry_run=dry_run, timeout=timeout)

    def put_text(self, *a, **kw):
        """SFTP a few small text files (the Synology stack's compose.yaml and
        .env), resolved through the calling script for the same reason."""
        return self._resolve("sftp_put_text")(*a, **kw)

    def dsm(self, *a, **kw):
        """The DSM Web API, resolved the same way -- server/tests patches
        `install_dashboard_app.synology_api` to run the Synology suite offline
        against a fake DSM, exactly as it patches truenas_api."""
        return self._resolve("synology_api")(*a, **kw)

    def wait_for_job(self, *a, **kw):
        return self._resolve("wait_for_job")(*a, **kw)

    def ok(self, resp):
        return self._resolve("ok")(resp)


def get_backend(args=None, kind: str = "", calls: ScriptCalls | None = None):
    """The ServerBackend for this site. `args` supplies --nas-kind if present.

    Selecting an unimplemented backend fails HERE, before a single connection
    is opened -- the Synology stub is importable on purpose, so that `--nas-kind
    synology` is a clear "not yet", not an ImportError.
    """
    chosen = (kind or "").strip().lower() or nas_kind(args)
    calls = calls or ScriptCalls()
    if chosen == "truenas":
        from backends.truenas import TrueNASBackend  # noqa: PLC0415 - avoid an import cycle
        return TrueNASBackend(calls=calls)
    from backends.synology import SynologyBackend  # noqa: PLC0415
    backend = SynologyBackend(calls=calls)
    if not getattr(backend, "ready", False):
        from backends.synology import PENDING  # noqa: PLC0415
        raise NotImplementedError(PENDING)
    return backend


def cli(main_fn) -> int:
    """Run a script's main(), turning a configuration refusal into one line.

    EnvError (a missing TRUENAS_PW, an unset [tree] pool_root) and a backend
    that is not written yet are ANSWERS, not crashes: an admin running
    setup_tree.py on a fresh checkout should read "here is the key you have not
    set", not a traceback ending in KeyError (2026-08-17).
    """
    try:
        return main_fn()
    except EnvError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 2
    except NotImplementedError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 2
