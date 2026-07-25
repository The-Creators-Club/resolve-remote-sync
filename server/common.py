"""Shared helpers for the Creators Club sync server scripts.

Style conventions used across every script in this package:
  - Python + `requests` for TrueNAS REST API calls (https://<host>/api/v2.0/...)
    and Syncthing REST API calls (http(s)://<gui>/rest/...).
  - `paramiko` for SSH, copying the pattern from ~/scripts/truenas_ssh.py:
    creds from env vars, command piped via a single exec_command call,
    `export SUDO_PW=...; echo "$SUDO_PW" | sudo -S <cmd>` for root actions.
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
import urllib3

# TrueNAS uses a self-signed cert by default; suppress the noisy warning
# (same as the `curl -sk` pattern already used against this host).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# --------------------------------------------------------------------------
# Constants shared by more than one script
# --------------------------------------------------------------------------

DEFAULT_TRUENAS_HOST = "192.168.0.102"
DEFAULT_TRUENAS_USER = "truenas_admin"
DEFAULT_DATASET_ROOT = "/mnt/tank/TheCreatorsPool"
DEFAULT_CC_ROOT = DEFAULT_DATASET_ROOT + "/Creators_Club"
DEFAULT_PROJECTS_ROOT = DEFAULT_CC_ROOT + "/Projects"
DEFAULT_DATASET_OWNER = "broll"
EDITORS_GROUP = "editors"

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


def build_stignore_lines() -> list[str]:
    """Build the .stignore content for a project's Syncthing folder.

    One case-insensitive line per video extension, plus a case-insensitive
    line ignoring any Proxy/ directory anywhere in the tree (proxies travel
    via rclone lane B, not Syncthing).
    """
    lines = [f"(?i)*{ext}" for ext in VIDEO_EXTENSIONS]
    # Bare name matches a Proxy dir at ANY depth including the folder root;
    # the **/ variants alone would miss a root-level Proxy/.
    lines.append("(?i)Proxy")
    lines.append("(?i)**/Proxy")
    lines.append("(?i)**/Proxy/**")
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
    """Build the absolute NAS path for a project, posix-style, no trailing slash."""
    for part, name in ((year, "year"), (series, "series"), (project, "project")):
        if not part or "/" in part or "\\" in part:
            raise ValueError(f"invalid --{name} value: {part!r}")
    return f"{projects_root.rstrip('/')}/{year}/{series}/{project}"


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


def build_marker_write_cmd(base: str, slug: str, created_by: str = "setup_tree") -> str:
    """Shell line writing the project marker into `base` (root via sudo,
    then chowned by the caller's chown -R). JSON kept minimal + quoted for
    embedding in the SSH script."""
    import json as _json

    payload = _json.dumps({"slug": slug, "created_by": created_by})
    marker_q = shell_quote(f"{base}/{MARKER_FILENAME}")
    payload_q = shell_quote(payload)
    return (
        f'echo "$SUDO_PW" | sudo -S -p "" sh -c '
        + shell_quote(f"printf '%s' {payload_q} > {marker_q}")
        + f' && echo "marker written: {MARKER_FILENAME}"'
    )


def shell_quote(value: str) -> str:
    """Single-quote a value for embedding in a POSIX shell command."""
    return "'" + value.replace("'", "'\\''") + "'"


# --------------------------------------------------------------------------
# Env var loading
# --------------------------------------------------------------------------

class EnvError(RuntimeError):
    pass


def require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise EnvError(
            f"Required environment variable {name} is not set. "
            f"See server/README.md for the full list of env vars this script needs."
        )
    return val


def truenas_conn_params(dry_run: bool = False):
    """host/user/pw for both SSH and REST API against TrueNAS.

    In dry-run mode, TRUENAS_PW is not required -- callers only need
    host/user to print what they'd do, and a placeholder is used for pw so
    local `--dry-run` verification works without any secret configured.
    """
    host = os.environ.get("TRUENAS_HOST", DEFAULT_TRUENAS_HOST)
    user = os.environ.get("TRUENAS_USER", DEFAULT_TRUENAS_USER)
    if dry_run:
        pw = os.environ.get("TRUENAS_PW", "<TRUENAS_PW-unset-dry-run>")
    else:
        pw = require_env("TRUENAS_PW")
    return host, user, pw


# --------------------------------------------------------------------------
# SSH (paramiko), mirrors ~/scripts/truenas_ssh.py
# --------------------------------------------------------------------------

def run_ssh(cmd: str, dry_run: bool = False, timeout: int = 120):
    """Run `cmd` on the TrueNAS host over SSH as TRUENAS_USER.

    `cmd` should assume $SUDO_PW is exported in its environment if it needs
    `echo "$SUDO_PW" | sudo -S ...`. Returns (rc, stdout, stderr).

    In dry-run mode, nothing is connected; the command is printed and
    (0, "", "") is returned so callers can still exercise their own
    print-what-I-did logic.
    """
    host, user, pw = truenas_conn_params(dry_run=dry_run)
    if dry_run:
        print(f"[dry-run] ssh {user}@{host}: {cmd}")
        return 0, "", ""

    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=pw,
                   look_for_keys=False, allow_agent=False, timeout=20)
    try:
        wrapped = f"export SUDO_PW={shell_quote(pw)}; " + cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=False, timeout=timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err
    finally:
        client.close()


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
