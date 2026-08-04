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
# The shared b-roll archive: browsable proxies editors link against, plus
# the search index that serves them. Beside Projects/ under Creators_Club,
# which is what makes it P:\Assets\B-roll Archive on an editor's machine.
DEFAULT_BROLL_ARCHIVE_ROOT = DEFAULT_CC_ROOT + "/Assets/B-roll Archive"
DEFAULT_DATASET_OWNER = "broll"
EDITORS_GROUP = "editors"

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

# (folder id, rel path under Creators_Club, human label). One entry per shared
# asset folder; the dashboard collector provisions and shares every one of
# them, and the companion accepts every one of them. Adding a second library
# (title templates, sound FX, Fusion macros) is a one-line change here plus
# the same line in dashboard/provision.py's copy.
SHARED_ASSET_FOLDERS = [
    (LUTS_FOLDER_ID, LUTS_REL, "Assets/Luts (LUT library)"),
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


def build_stignore_lines() -> list[str]:
    """Build the .stignore content for a project's Syncthing folder.

    One case-insensitive line per video extension, plus a case-insensitive
    line ignoring any Proxy/ directory anywhere in the tree (proxies travel
    via rclone lane B, not Syncthing) and rclone's orphaned .partial files.
    """
    lines = [f"(?i)*{ext}" for ext in VIDEO_EXTENSIONS]
    lines.extend(PARTIAL_IGNORE_LINES)
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
    ever writes here.
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
