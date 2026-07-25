"""Pure/injectable orchestration logic for the Windows onboarding wizard
(onboard.py). Every function here takes its side-effecting collaborator
(http_post, http_get, run, ...) as an injectable keyword argument with a
real default, so onboard.py's GUI code stays thin and this module is fully
unit-testable without touching the network, Tailscale, PowerShell, or the
filesystem outside of what a test explicitly points at (see tests/).

Contract this wizard gates on (see companion/src/ccsync_companion/identity.py
for the companion-side half of the same contract):

    POST {dashboard_url}/api/v1/verify  body {"username", "password"}, no
    auth headers (open bootstrap-trust endpoint).
      200 -> {"ok": true, "username": "<lowercased>", "token": "<identity
              token>", "report_token": "<shared report token>",
              "role": "base" | "editor"}
      401 -> bad credentials / 429 -> throttled / 503 -> verify not configured

The dashboard is reachable only once this machine has joined the tailnet
(Tailscale), so the wizard's page order (Welcome -> Tailscale -> Sign in ->
Install -> Finish) mirrors that dependency -- see onboard.py.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

# Reuse the companion package rather than re-implement its identity/config
# handling -- onboard.py's PyInstaller build and this dev tree both need
# companion/src importable; see tests/conftest.py and build_onboard.spec.
from ccsync_companion import config as config_mod
from ccsync_companion import identity as identity_mod

# -- constants ---------------------------------------------------------------

INSTALLER_VERSION = "1.0.4"

DEFAULT_DASHBOARD_URL = os.environ.get("CCSYNC_DASHBOARD_URL", "http://100.71.216.3:8480")
# Base rig talks to the dashboard over the LAN, not the tailnet.
DEFAULT_BASE_DASHBOARD_URL = "http://192.168.0.102:8480"
SSH_KEY_NAME = "ccsync_ed25519"
DEFAULT_SSH_DIR = Path.home() / ".ssh"
DEFAULT_LOCAL_ROOT = r"C:\Creators_Club"
# Base rig works directly off the NAS pool mapping; local_root AND
# canonical_prefix both point at the tree root there (see the base-rig
# comments in companion config.example.toml).
DEFAULT_BASE_LOCAL_ROOT = r"T:\Creators_Club"
# Same default windows_bootstrap.ps1's -RemoteRoot parameter ships (see
# BOOTSTRAP_SCRIPT_NAME). ensure_config must force this too: the bootstrap's
# own config-seeding step is skipped whenever config.toml already exists
# (which it always does by the time run_bootstrap() runs -- ensure_config
# runs first), so a blank remote_root here means an editor's originals get
# uploaded to their bare SFTP home directory instead of the project tree.
DEFAULT_REMOTE_ROOT = "/mnt/tank/TheCreatorsPool/Creators_Club"
# subprocess timeout for the bootstrap script (winget prompts, a stalled
# Invoke-WebRequest, or a hung `subst` would otherwise block the worker
# thread forever -- see run_bootstrap).
BOOTSTRAP_TIMEOUT_SECONDS = 1800
BOOTSTRAP_SCRIPT_NAME = "windows_bootstrap.ps1"
COMPANION_EXE_NAME = "ccsync-companion.exe"
# THE canonical companion location, both roles (matches
# windows_bootstrap.ps1's $CompanionExePath default and windows_upgrade.ps1).
COMPANION_BIN_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ccsync" / "bin"

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
SUBST_TASK_NAME = "CCSync-SubstP"
COMPANION_RUN_VALUE = "CCSyncCompanion"
# Every Run value any historical CCSync tool ever registered. The lowercase
# "ccsync-companion" is the hand-made base-rig entry (cmd/vbs shim in
# %USERPROFILE%\.ccsync\bin, created 2026-07-25).
ALL_RUN_VALUES = ["CCSyncCompanion", "CCSyncSyncthing", "CCSyncSubstP", "ccsync-companion"]
# The companion exe plus the self-upgrade artifacts that can sit next to it
# (see companion upgrade.py: <exe>.old and ccsync-companion.new.exe).
COMPANION_FILE_NAMES = [
    "ccsync-companion.exe",
    "ccsync-companion.exe.old",
    "ccsync-companion.new.exe",
]

# Matches a Syncthing device ID: 8 groups of 7 [A-Z0-9] chars, dash-separated
# (same shape windows_bootstrap.ps1's Get-SyncthingDeviceId regex looks for).
_DEVICE_ID_RE = re.compile(r"([A-Z0-9]{7}(?:-[A-Z0-9]{7}){7})")

HttpPostFn = Callable[[str, dict, dict, float], Any]
HttpGetFn = Callable[[str, float], Any]
RunFn = Callable[..., "subprocess.CompletedProcess"]

# EVERY subprocess capture in this module must pass these (S-6). `text=True`
# alone decodes with the console codepage under errors="strict", so one
# non-ASCII byte -- a `C:\Users\José` profile echoed back by the bootstrap, a
# CJK path in `tailscale status` -- raises UnicodeDecodeError out of the
# wizard's worker thread, AFTER _clean_slate() has already removed the
# working install. windows_bootstrap.ps1 forces UTF-8 on its own stdout when
# redirected (see its [Console]::OutputEncoding line) so this decodes exactly
# what it printed; errors="replace" makes anything else a mangled string
# rather than an exception.
CAPTURE_TEXT_KWARGS: dict[str, Any] = {
    "capture_output": True,
    "encoding": "utf-8",
    "errors": "replace",
}

# Hard-capability misses windows_bootstrap.ps1 prints with this exact prefix
# (and counts towards its own non-zero exit). onboard.py turns any of these
# into a "completed with N warnings -- this machine is NOT ready" finish page
# instead of DONE (INST-5).
CAPABILITY_MARKER = "CAPABILITY MISSING:"
# Phrasings older bootstraps used for the same three misses, kept so an
# onboard.exe paired with a stale windows_bootstrap.ps1 still flags them.
_LEGACY_CAPABILITY_PHRASES = (
    "could not find rclone.exe inside the downloaded zip",
    "could not determine a Syncthing download URL",
    "could not find syncthing.exe inside the downloaded zip",
    "Syncthing executable path is unknown",
    "could not determine the Syncthing device ID",
)


# -- http helpers --------------------------------------------------------------

def default_http_post(url: str, data: dict, headers: dict, timeout: float) -> Any:
    """Same wire behavior as ccsync_companion.reporter.default_http_post --
    duplicated (rather than imported) only so this module has zero import-time
    dependency on the sync/watchdog stack reporter.py pulls in transitively."""
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp_data = resp.read()
    return json.loads(resp_data.decode("utf-8")) if resp_data else {}


def default_http_get(url: str, timeout: float) -> Any:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp_data = resp.read()
    return json.loads(resp_data.decode("utf-8")) if resp_data else {}


# -- account verification (the install gate) ----------------------------------

def verify_account(
    dashboard_url: str,
    username: str,
    password: str,
    http_post: HttpPostFn = default_http_post,
    timeout: float = 15,
) -> dict[str, Any]:
    """POST {username, password} to {dashboard_url}/api/v1/verify.

    Returns {"ok": True, "username", "token", "report_token"} on success, or
    {"ok": False, "error": "..."} on any failure (bad credentials, throttled,
    the dashboard not configured for login, or a network/transport error).
    Never raises -- this is the install gate, callers branch on "ok".
    """
    dashboard_url = str(dashboard_url or "").strip()
    if not dashboard_url:
        return {"ok": False, "error": "no dashboard URL configured"}
    if not str(username or "").strip():
        return {"ok": False, "error": "username is required"}
    if not password:
        return {"ok": False, "error": "password is required"}

    url = f"{dashboard_url.rstrip('/')}/api/v1/verify"
    headers = {"Content-Type": "application/json"}
    payload = {"username": username, "password": password}
    try:
        resp = http_post(url, payload, headers, timeout)
    except urllib.error.HTTPError as exc:
        # Reuse the companion's status-code -> human message mapping instead
        # of re-deriving it here.
        message = identity_mod._http_error_message(exc)
        return {"ok": False, "error": message}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    if not isinstance(resp, dict) or not resp.get("ok"):
        error = resp.get("error") if isinstance(resp, dict) else None
        return {"ok": False, "error": error or "sign-in failed"}

    return {
        "ok": True,
        "username": resp.get("username") or username,
        "token": resp.get("token"),
        "report_token": resp.get("report_token", ""),
        # Absent on older dashboards -- callers get None and fall back to
        # config.toml's static mode (see ccsync_companion.app's
        # _apply_identity_role, which write_identity()'s role param feeds).
        "role": resp.get("role"),
    }


# -- tailscale / dashboard reachability ---------------------------------------

def tailscale_installed() -> bool:
    """True if a `tailscale` executable is on PATH or in its usual Program
    Files location -- mirrors windows_bootstrap.ps1's own check."""
    import shutil

    if shutil.which("tailscale"):
        return True
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    return (Path(program_files) / "Tailscale" / "tailscale.exe").exists()


def tailscale_up(run: RunFn = subprocess.run) -> bool:
    """True if `tailscale status` reports this machine as joined to a
    tailnet (exit 0 and no "logged out"/"stopped"/"needs login" markers)."""
    try:
        result = run(["tailscale", "status"], timeout=15, **CAPTURE_TEXT_KWARGS)
    except Exception:
        return False
    if getattr(result, "returncode", 1) != 0:
        return False
    output = ((result.stdout or "") + (result.stderr or "")).lower()
    if any(marker in output for marker in ("logged out", "needs login", "stopped")):
        return False
    return True


def dashboard_reachable(
    dashboard_url: str,
    http_get: HttpGetFn = default_http_get,
    timeout: float = 10,
) -> bool:
    """True if GET {dashboard_url}/api/v1/health succeeds. This is the real
    end-to-end check the wizard gates "Next" on -- Tailscale can report
    "up" while the tailnet route to the dashboard is still settling."""
    dashboard_url = str(dashboard_url or "").strip()
    if not dashboard_url:
        return False
    url = f"{dashboard_url.rstrip('/')}/api/v1/health"
    try:
        http_get(url, timeout)
        return True
    except Exception:
        return False


def dashboard_host(dashboard_url: str) -> str:
    """Extract just the host (no scheme/port) from a dashboard_url, for use
    as windows_bootstrap.ps1's -TailnetHost. Falls back to the raw string if
    it doesn't parse as a URL (e.g. a bare hostname was typed in)."""
    dashboard_url = str(dashboard_url or "").strip()
    if not dashboard_url:
        return ""
    parsed = urlparse(dashboard_url if "://" in dashboard_url else f"//{dashboard_url}")
    return parsed.hostname or dashboard_url


# -- SSH key -------------------------------------------------------------------

class SshKeyError(RuntimeError):
    """ssh-keygen is missing, failed, or produced no public key. Raised (not
    swallowed) so the wizard can tell the editor lanes A/B will never
    authenticate, instead of showing DONE next to a path that doesn't exist
    (INST-22)."""


def ensure_ssh_key(ssh_dir: Path = DEFAULT_SSH_DIR, run: RunFn = subprocess.run) -> Path:
    """Generate ~/.ssh/ccsync_ed25519 (no passphrase) if it doesn't already
    exist. Returns the path to the PUBLIC half either way -- that's the
    value the admin needs (see read_pubkey).

    Raises SshKeyError when ssh-keygen is absent, exits non-zero, or leaves
    no .pub behind. Three distinct cases, because they need three different
    commands:

      both halves present  -> nothing to do.
      private key present, .pub missing -> DERIVE the public half with
        `ssh-keygen -y -f <key>`. Never re-run plain `ssh-keygen -f <key>`
        here: it prompts "Overwrite (y/n)?" against the wizard's closed
        stdin, aborts, and would destroy a key the admin has already
        installed on the NAS if it did succeed.
      neither present -> generate a fresh keypair.
    """
    ssh_dir = Path(ssh_dir)
    key_path = ssh_dir / SSH_KEY_NAME
    pub_path = ssh_dir / f"{SSH_KEY_NAME}.pub"

    if key_path.exists() and pub_path.exists():
        return pub_path

    ssh_dir.mkdir(parents=True, exist_ok=True)

    if key_path.exists():
        # Derive the public half from the private one -- writing it ourselves
        # rather than with a shell redirect (no shell=True here).
        result = _run_ssh_keygen(run, ["ssh-keygen", "-y", "-f", str(key_path)])
        public = (getattr(result, "stdout", "") or "").strip()
        if not public.startswith("ssh-"):
            raise SshKeyError(
                f"could not derive the public key from the existing {key_path} "
                f"(ssh-keygen -y said: {_first_line(result) or 'nothing'}). Delete "
                f"that file if you want a brand-new keypair, then re-run."
            )
        try:
            pub_path.write_text(public + "\n", encoding="utf-8")
        except OSError as exc:
            raise SshKeyError(f"could not write {pub_path}: {exc}") from exc
        return pub_path

    _run_ssh_keygen(run, ["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", ""])
    if not pub_path.exists():
        raise SshKeyError(
            f"ssh-keygen reported success but {pub_path} does not exist -- "
            "generate the keypair by hand and re-run the installer."
        )
    return pub_path


def _run_ssh_keygen(run: RunFn, cmd: list[str]) -> Any:
    try:
        result = run(cmd, timeout=60, **CAPTURE_TEXT_KWARGS)
    except FileNotFoundError as exc:
        raise SshKeyError(
            "ssh-keygen was not found. Install the Windows OpenSSH Client "
            "(Settings > System > Optional features > Add > OpenSSH Client) "
            "and re-run the installer."
        ) from exc
    except Exception as exc:
        raise SshKeyError(f"ssh-keygen failed to run: {exc}") from exc
    if getattr(result, "returncode", 0) != 0:
        raise SshKeyError(
            f"ssh-keygen exited with code {getattr(result, 'returncode', '?')}: "
            f"{_first_line(result) or '(no output)'}"
        )
    return result


def _first_line(result: Any) -> str:
    blob = ((getattr(result, "stderr", "") or "") + (getattr(result, "stdout", "") or "")).strip()
    return blob.splitlines()[0][:200] if blob else ""


def read_pubkey(path: Path) -> str:
    """Tolerant read of an SSH public key file -- "" (not an exception) if
    it's missing or unreadable, so the Finish page can show a clear
    "not available" state instead of crashing."""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# -- bootstrap invocation -------------------------------------------------------

def find_bootstrap_script(script_path: Optional[Path] = None) -> Path:
    """Locate the bundled windows_bootstrap.ps1, checking (in order):
      1. an explicit override (script_path)
      2. PyInstaller's extraction dir (sys._MEIPASS) -- see build_onboard.spec
      3. next to the running onboard.exe (sys.executable's directory)
      4. next to this source file (dev tree: onboarding/)
      5. ../installer/ relative to this source file (dev tree checkout)
    Raises FileNotFoundError with every path it tried if none exist.
    """
    candidates: list[Path] = []
    if script_path is not None:
        candidates.append(Path(script_path))

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / BOOTSTRAP_SCRIPT_NAME)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / BOOTSTRAP_SCRIPT_NAME)

    here = Path(__file__).resolve().parent
    candidates.append(here / BOOTSTRAP_SCRIPT_NAME)
    candidates.append(here.parent / "installer" / BOOTSTRAP_SCRIPT_NAME)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    tried = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(f"{BOOTSTRAP_SCRIPT_NAME} not found (looked in: {tried})")


def find_companion_exe(exe_path: Optional[Path] = None) -> Path:
    """Locate the bundled ccsync-companion.exe (same lookup order as
    find_bootstrap_script). Raises FileNotFoundError listing what it tried."""
    candidates: list[Path] = []
    if exe_path is not None:
        candidates.append(Path(exe_path))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / COMPANION_EXE_NAME)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / COMPANION_EXE_NAME)
    here = Path(__file__).resolve().parent
    candidates.append(here / COMPANION_EXE_NAME)
    candidates.append(here.parent / "companion" / "dist" / COMPANION_EXE_NAME)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    tried = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(f"{COMPANION_EXE_NAME} not found (looked in: {tried})")


def install_companion(dest_dir: Path = COMPANION_BIN_DIR, src: Optional[Path] = None,
                      copy: Callable[[Path, Path], Any] = None) -> Path:
    """Copy the bundled companion exe into dest_dir (created if needed) so the
    bootstrap's autostart registration finds it. Must run BEFORE run_bootstrap.
    Returns the installed exe path."""
    import shutil
    src = find_companion_exe(src)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / COMPANION_EXE_NAME
    (copy or shutil.copy2)(src, dest)
    return dest


def run_bootstrap(
    editor_name: str,
    dashboard_token: str,
    tailnet_host: str,
    local_root: Optional[str] = None,
    dashboard_url: str = DEFAULT_DASHBOARD_URL,
    companion_exe_source: Optional[Path] = None,
    run: RunFn = subprocess.run,
    script_path: Optional[Path] = None,
) -> tuple[int, str]:
    """Invoke `powershell -ExecutionPolicy Bypass -File <bootstrap> ...`
    with the verified editor's identity. Returns (exit_code, combined
    stdout+stderr) -- never raises for a non-zero exit, only if the script
    itself can't be located (find_bootstrap_script).

    `companion_exe_source`, when given, is passed through as
    -CompanionExeSource so the bootstrap script installs the bundled
    companion exe into place (P:\\ once mapped), registers its autostart,
    launches it, and confirms it's still running a few seconds later --
    see windows_bootstrap.ps1's "Companion" step. Find it with
    find_companion_exe() before calling this.

    Bounded by BOOTSTRAP_TIMEOUT_SECONDS: `powershell -File` inherits a
    non-interactive captured stdin, so a winget prompt, a hung `subst`, or a
    stalled Invoke-WebRequest would otherwise block forever with no way out.
    A timeout is reported like any other bootstrap failure -- a non-zero
    exit code plus an explanatory message -- rather than raised, since
    _clean_slate has already run by the time callers get here and the
    wizard needs a normal failed-install result, not an exception."""
    script = find_bootstrap_script(script_path)

    cmd = [
        "powershell",
        # -NoProfile: a user profile script that prompts, errors, or sets
        # Set-StrictMode would otherwise alter or hang the install and surface
        # as an unrelated bootstrap error. -NonInteractive: this process has a
        # captured, closed stdin, so any prompt is an immediate hang (INST-23).
        "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", str(script),
        "-TailnetHost", tailnet_host,
        "-EditorName", editor_name,
        "-DashboardUrl", dashboard_url,
        "-DashboardToken", dashboard_token,
    ]
    if local_root:
        cmd += ["-LocalRoot", str(local_root)]
    if companion_exe_source:
        cmd += ["-CompanionExeSource", str(companion_exe_source)]

    try:
        result = run(cmd, timeout=BOOTSTRAP_TIMEOUT_SECONDS, **CAPTURE_TEXT_KWARGS)
    except subprocess.TimeoutExpired as exc:
        partial = ((exc.stdout or "") if isinstance(exc.stdout, str) else "") + (
            (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        )
        message = (
            f"{partial}\nbootstrap timed out after {BOOTSTRAP_TIMEOUT_SECONDS}s "
            "-- it may be stuck on a prompt (e.g. winget) or a stalled download; "
            "re-run the installer, or run windows_bootstrap.ps1 by hand to see "
            "where it hangs."
        )
        return 1, message
    output = (getattr(result, "stdout", "") or "") + (getattr(result, "stderr", "") or "")
    return getattr(result, "returncode", 1), output


def parse_device_id(bootstrap_output: str) -> Optional[str]:
    """Pull the Syncthing device ID out of windows_bootstrap.ps1's stdout
    (it prints it near the end of a successful run). None if not found."""
    if not bootstrap_output:
        return None
    match = _DEVICE_ID_RE.search(bootstrap_output)
    return match.group(1) if match else None


def bootstrap_capability_warnings(bootstrap_output: str) -> list[str]:
    """Every hard-capability miss windows_bootstrap.ps1 reported: no rclone
    installed, no Syncthing installed/found, no device ID determined.

    The bootstrap warns-and-continues on each of these and used to exit 0, so
    the wizard showed a green DONE page for a machine that will never sync
    anything -- after clean-slate had already removed the previous working
    install (INST-5). It now exits non-zero and tags each miss with
    CAPABILITY_MARKER; this scans for that (plus the older phrasings, so a
    mismatched script pairing still gets flagged). De-duplicated, order
    preserved."""
    if not bootstrap_output:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for line in str(bootstrap_output).splitlines():
        stripped = line.strip()
        message = ""
        if CAPABILITY_MARKER in stripped:
            message = stripped.split(CAPABILITY_MARKER, 1)[1].strip()
        else:
            for phrase in _LEGACY_CAPABILITY_PHRASES:
                if phrase in stripped:
                    message = stripped
                    break
        if message and message not in seen:
            seen.add(message)
            found.append(message)
    return found


# -- identity + config finalization --------------------------------------------

def write_identity(username: str, token: str, role: Optional[str] = None) -> None:
    """Write ~/.ccsync/identity.json so the companion is already signed in
    (with its role already resolved, if the dashboard sent one) when the
    editor first launches it -- see identity.save_identity."""
    path = identity_mod.identity_path()
    identity_mod.save_identity(path, username, token, role=role)


def finalize_config_identity(username: str, config_path: Optional[Path] = None) -> None:
    """Make sure ~/.ccsync/config.toml's editor_name matches the verified
    username. windows_bootstrap.ps1 already seeds this correctly on a fresh
    install (it's called with -EditorName <verified username>, see
    onboard.py), so this is normally a no-op -- it only rewrites the line
    when it disagrees (e.g. a pre-existing config from an older install).
    Tolerant of every failure mode (missing file, unreadable, unwritable):
    this is a convenience touch-up, not a step that should ever block
    onboarding."""
    path = Path(config_path) if config_path is not None else config_mod.CONFIG_PATH
    username = str(username or "").strip()
    if not username:
        return

    try:
        cfg = config_mod.load_config(path)
    except Exception:
        return
    if str(cfg.get("editor_name", "")).strip() == username:
        return

    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return

    new_text, count = re.subn(
        r'(?m)^editor_name\s*=\s*".*"\s*$',
        f'editor_name = "{username}"',
        text,
        count=1,
    )
    if count == 0:
        return

    try:
        path.write_text(new_text, encoding="utf-8")
    except OSError:
        pass


# -- local_root validation (gates BEGIN INSTALL) -------------------------------

# Anything not of the shape "<letter>:\..." is rejected before the install
# starts: the value is forced into config.toml AND handed to
# windows_bootstrap.ps1 as -LocalRoot, where Ensure-Dir runs under
# $ErrorActionPreference = "Stop" -- a nonexistent drive is a hard abort
# AFTER _clean_slate() has removed the previous install (INST-21).
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def validate_local_root(
    value: str,
    role: str = "editor",
    drive_exists: Optional[Callable[[str], bool]] = None,
) -> Optional[str]:
    """None when `value` is usable as local_root, else a one-line, plain
    English reason to show inline next to the field.

    `drive_exists` takes a drive letter ("D") and is injectable for tests.
    """
    role = str(role or "").strip().lower()
    raw = str(value or "")
    if not raw.strip():
        return "enter a folder for the project tree, e.g. C:\\Creators_Club"
    if raw != raw.strip():
        return (
            "remove the leading/trailing space -- it silently becomes part of "
            "the folder name and nothing will ever find the tree"
        )
    if '"' in raw:
        # The logon remap runs through `cmd /c subst P: "<root>"`; a quote in
        # the path breaks that command line irrecoverably (INST-2).
        return 'a double-quote (") is not allowed in the folder path'
    if not _DRIVE_PATH_RE.match(raw):
        if raw.startswith("\\\\"):
            return "a network path (\\\\server\\share) will not work -- use a local drive, e.g. D:\\Creators_Club"
        return "use a full path starting with a drive letter, e.g. C:\\Creators_Club"

    drive = raw[0].upper()
    if role != "base" and drive == "P":
        # The install unmounts P: and remaps it AT this folder; pointing the
        # folder at P: means Ensure-Dir runs against a drive that no longer
        # exists, mid-install.
        return (
            "P: is the drive this installer creates for you -- pick the real "
            "folder it should point at (e.g. C:\\Creators_Club)"
        )

    if drive_exists is None:
        drive_exists = _default_drive_exists
    try:
        present = drive_exists(drive)
    except Exception:
        present = True  # never block the install on a probe that itself broke
    if not present:
        return f"drive {drive}: does not exist on this machine"
    return None


def _default_drive_exists(letter: str) -> bool:
    return Path(f"{letter}:\\").exists()


# -- clean slate (remove every trace of previous installs) ---------------------

@dataclass
class CleanupPlan:
    """Everything execute_cleanup() will remove. Built by build_cleanup_plan()
    as pure data so tests can assert on the enumeration without touching the
    machine."""
    kill_process_names: list[str] = field(default_factory=list)
    kill_pythonw_launcher: bool = True
    run_values: list[str] = field(default_factory=list)
    scheduled_tasks: list[str] = field(default_factory=list)
    exe_paths: list[Path] = field(default_factory=list)
    shim_paths: list[Path] = field(default_factory=list)
    unmount_p: bool = False
    # Directories a syncthing.exe must be running from for us to kill it.
    # NEVER a blanket `taskkill /IM syncthing.exe`: editors in this
    # population commonly run their own Syncthing, and killing it (we never
    # restart it) silently breaks whatever they were using it for (INST-20).
    syncthing_managed_dirs: list[Path] = field(default_factory=list)


def default_read_run_value(name: str) -> Optional[str]:
    """Read a value from HKCU\\...\\Run, or None. Never raises."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, name)
            return str(value)
    except OSError:
        return None


def default_delete_run_value(name: str) -> bool:
    """Delete a value from HKCU\\...\\Run. True if it was there. Never raises."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
            return True
    except OSError:
        return False


def default_set_run_value(name: str, value: str) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def read_config_local_root(config_path: Optional[Path] = None) -> Optional[str]:
    """local_root from an existing ~/.ccsync/config.toml, or None. Never
    raises -- a broken/missing config just contributes no extra cleanup dir."""
    path = Path(config_path) if config_path is not None else config_mod.CONFIG_PATH
    try:
        if not path.exists():
            return None
        cfg = config_mod.load_config(path)
        value = str(cfg.get("local_root", "")).strip()
        return value or None
    except Exception:
        return None


def _exe_dir_from_run_value(value: Optional[str]) -> Optional[Path]:
    """The directory the CCSyncCompanion Run value points at, if it's a raw
    exe path (the bootstrap's style). wscript shim values contribute nothing
    (their cmd/vbs files are covered by shim_paths)."""
    if not value:
        return None
    raw = value.strip().strip('"')
    if not raw.lower().endswith(".exe") or "wscript" in raw.lower():
        return None
    try:
        return Path(raw).parent
    except (ValueError, OSError):
        return None


def build_cleanup_plan(
    role: str,
    local_root: Optional[str] = None,
    read_run_value: Callable[[str], Optional[str]] = default_read_run_value,
    read_local_root: Callable[[], Optional[str]] = read_config_local_root,
    exists: Callable[[Path], bool] = lambda p: Path(p).exists(),
) -> CleanupPlan:
    """Enumerate every trace a previous install could have left. Pure given
    its injected readers.

    Deliberately NEVER listed: rclone.exe / syncthing.exe (preserved package
    installs), %LOCALAPPDATA%\\ccsync\\syncthing-config (device identity --
    deleting it forces admin re-approval), ~/.ssh keys, identity.json,
    config.toml, rclone.conf. "All traces of previous VERSIONS" means the
    software, not the machine's identity.
    """
    role = str(role or "").strip().lower()

    candidate_dirs: list[Path] = [COMPANION_BIN_DIR]
    # On the BASE rig, local_root (and the local_root read back out of an
    # existing config.toml) IS the NAS pool mapping (T:\Creators_Club) --
    # never a cleanup candidate. Only an editor's local_root is a real local
    # directory the installer might have dropped exe copies into.
    if role != "base":
        if local_root:
            candidate_dirs.append(Path(local_root))
        config_root = read_local_root()
        if config_root:
            candidate_dirs.append(Path(config_root))
    candidate_dirs.append(Path(DEFAULT_LOCAL_ROOT))
    if role == "editor":
        # Editors' P: is a subst of their local root -- the bootstrap
        # historically installed the exe there. On the BASE rig P:/T: are
        # SMB mappings of the NAS itself: never reach into those.
        candidate_dirs.append(Path("P:/"))
    run_dir = _exe_dir_from_run_value(read_run_value(COMPANION_RUN_VALUE))
    if run_dir is not None:
        candidate_dirs.append(run_dir)
    home_bin = Path.home() / ".ccsync" / "bin"
    candidate_dirs.append(home_bin)

    seen: set[str] = set()
    exe_paths: list[Path] = []
    for directory in candidate_dirs:
        key = os.path.normcase(str(directory))
        if key in seen:
            continue
        seen.add(key)
        for name in COMPANION_FILE_NAMES:
            path = directory / name
            if exists(path):
                exe_paths.append(path)

    shim_candidates = [
        COMPANION_BIN_DIR / "CCSyncSubstP.cmd",
        COMPANION_BIN_DIR / "CCSyncSubstP.vbs",
        COMPANION_BIN_DIR / "CCSyncSyncthing.cmd",
        COMPANION_BIN_DIR / "CCSyncSyncthing.vbs",
        home_bin / "ccsync-companion.cmd",
        home_bin / "ccsync-companion.vbs",
    ]
    shim_paths = [p for p in shim_candidates if exists(p)]

    return CleanupPlan(
        kill_process_names=["ccsync-companion", "ccsync-companion.new"],
        kill_pythonw_launcher=True,
        run_values=list(ALL_RUN_VALUES),
        scheduled_tasks=[SUBST_TASK_NAME],
        exe_paths=exe_paths,
        shim_paths=shim_paths,
        unmount_p=(role == "editor"),
        syncthing_managed_dirs=managed_syncthing_dirs(),
    )


def managed_syncthing_dirs() -> list[Path]:
    """The only places a syncthing.exe is ours: the installer's bin dir and
    anything else under %LOCALAPPDATA%\\ccsync (which contains it), plus the
    historical ~/.ccsync/bin. A syncthing.exe anywhere else -- Program Files,
    scoop, the editor's own portable copy -- belongs to the editor."""
    ccsync_local = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ccsync"
    return [ccsync_local, COMPANION_BIN_DIR, Path.home() / ".ccsync"]


def default_list_processes(name: str, run: RunFn = subprocess.run) -> list[tuple[str, str]]:
    """[(pid, executable_path)] for every running process called `name`.exe.
    Empty on any failure -- callers degrade to "leave it alone"."""
    query = (
        f"Get-CimInstance Win32_Process -Filter \"Name='{name}.exe'\" | "
        "ForEach-Object { \"$($_.ProcessId)|$($_.ExecutablePath)\" }"
    )
    try:
        result = run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
            timeout=30,
            **CAPTURE_TEXT_KWARGS,
        )
    except Exception:
        return []
    found: list[tuple[str, str]] = []
    for line in (getattr(result, "stdout", "") or "").splitlines():
        pid, sep, exe = line.strip().partition("|")
        if sep and pid.isdigit():
            found.append((pid, exe.strip()))
    return found


def _path_under_any(path: str, directories: list[Path]) -> bool:
    if not path:
        return False
    try:
        resolved = os.path.normcase(os.path.abspath(str(path)))
    except (ValueError, OSError):
        return False
    for directory in directories:
        prefix = os.path.normcase(os.path.abspath(str(directory)))
        if resolved == prefix or resolved.startswith(prefix + os.sep):
            return True
    return False


def execute_cleanup(
    plan: CleanupPlan,
    log: Callable[[str], None],
    run: RunFn = subprocess.run,
    delete_file: Optional[Callable[[Path], None]] = None,
    delete_run_value: Callable[[str], bool] = default_delete_run_value,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
    p_drive_exists: Callable[[], bool] = lambda: Path("P:/").exists(),
    list_processes: Optional[Callable[[str], list[tuple[str, str]]]] = None,
) -> list[str]:
    """Execute a CleanupPlan. Returns accumulated warnings; NEVER raises --
    a half-cleaned machine plus warnings beats an aborted install.

    Order matters: processes die first (they hold the exe files and, via
    open handles under P:, can pin the drive mapping), then autostart
    entries (so a crash mid-cleanup can't leave an entry pointing at a
    deleted exe), then files, then the drive."""
    warnings: list[str] = []

    def _delete(path: Path) -> None:
        if delete_file is not None:
            delete_file(path)
        else:
            Path(path).unlink()

    def _quiet_run(cmd: list[str]) -> Any:
        try:
            return run(cmd, timeout=30, **CAPTURE_TEXT_KWARGS)
        except Exception as exc:
            warnings.append(f"{' '.join(cmd[:3])}...: {exc}")
            return None

    # 1. processes
    for name in plan.kill_process_names:
        _quiet_run(["taskkill", "/F", "/IM", f"{name}.exe"])

    # 1b. Syncthing, but ONLY the instance we manage. A blanket
    # `taskkill /IM syncthing.exe` also kills the editor's own Syncthing --
    # which nothing here ever restarts (INST-20).
    if plan.syncthing_managed_dirs:
        lister = list_processes
        if lister is None:
            lister = lambda name: default_list_processes(name, run=run)  # noqa: E731
        try:
            processes = lister("syncthing")
        except Exception as exc:
            processes = []
            warnings.append(f"could not enumerate Syncthing processes: {exc}")
        for pid, exe_path in processes:
            if _path_under_any(exe_path, plan.syncthing_managed_dirs):
                _quiet_run(["taskkill", "/F", "/PID", str(pid)])
                log(f"stopped our Syncthing (pid {pid}, {exe_path})")
            else:
                warnings.append(
                    f"another Syncthing is running from {exe_path or '(unknown path)'} "
                    f"(pid {pid}) -- left alone; it is not ours to stop or restart"
                )

    if plan.kill_pythonw_launcher:
        _quiet_run([
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
            "Where-Object { $_.CommandLine -match 'launcher\\.py' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
        ])
    if plan.kill_process_names or plan.kill_pythonw_launcher:
        sleep(1.0)

    # 2. autostart Run values
    for name in plan.run_values:
        if delete_run_value(name):
            log(f"removed autostart entry {name}")

    # 3. scheduled tasks
    for task in plan.scheduled_tasks:
        result = _quiet_run(["schtasks", "/Delete", "/TN", task, "/F"])
        if result is not None and getattr(result, "returncode", 0) != 0:
            stderr = (getattr(result, "stderr", "") or "").lower()
            if "cannot find" in stderr or "does not exist" in stderr:
                pass  # nothing to remove
            elif "access" in stderr or "denied" in stderr:
                # Deliberately NOT "re-run this installer as administrator":
                # an elevated install maps P: into a token the editor's own
                # session cannot see, which is a far worse outcome than a
                # leftover task (INST-1). Give the one targeted command
                # instead.
                warnings.append(
                    f"could not delete the old scheduled task {task} (access denied). "
                    "It is harmless -- the install continues. To clear it, open "
                    "Start > type 'cmd' > right-click 'Command Prompt' > Run as "
                    f"administrator, and run:  schtasks /Delete /TN {task} /F"
                )
            else:
                warnings.append(f"schtasks /Delete {task} failed: {stderr.strip()[:120]}")
        elif result is not None:
            log(f"removed scheduled task {task}")

    # 4. old exe copies (kill above should have freed them; AV can lag)
    for path in plan.exe_paths:
        deleted = False
        for attempt in range(3):
            try:
                _delete(path)
                deleted = True
                break
            except FileNotFoundError:
                deleted = True
                break
            except OSError:
                if attempt < 2:
                    sleep(1.0)
        if deleted:
            log(f"removed {path}")
        else:
            stale = Path(str(path) + f".stale-{int(now())}")
            try:
                os.replace(path, stale)
                warnings.append(f"{path} was locked -- renamed to {stale.name}")
            except OSError as exc:
                warnings.append(f"could not remove {path}: {exc}")

    # 5. shim files
    for path in plan.shim_paths:
        try:
            _delete(path)
            log(f"removed {path.name}")
        except FileNotFoundError:
            pass
        except OSError as exc:
            warnings.append(f"could not remove {path}: {exc}")
    # a now-empty ~/.ccsync/bin can go entirely (BinDir stays: rclone/syncthing)
    home_bin = Path.home() / ".ccsync" / "bin"
    try:
        if home_bin.is_dir() and not any(home_bin.iterdir()):
            home_bin.rmdir()
    except OSError:
        pass

    # 6. P: drive (editor role only) -- both mapping styles, errors ignored:
    # subst covers our own mapping, net use covers a hand-made SMB mapping
    # that subst can't even see.
    if plan.unmount_p:
        _quiet_run(["cmd", "/c", "subst", "P:", "/D"])
        _quiet_run(["cmd", "/c", "net", "use", "P:", "/delete", "/y"])
        if p_drive_exists():
            warnings.append(
                "P: is still mapped after unmounting -- something has files "
                "open on it; close those apps and retry"
            )
        else:
            log("P: drive unmounted (will be re-created by the install)")

    return warnings


# -- config write/merge ---------------------------------------------------------

def _toml_string(value: str) -> str:
    """A double-quoted TOML basic string with backslashes escaped -- the same
    form the bootstrap seeds (local_root = "C:\\\\Creators_Club")."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _existing_literal(text: str, key: str) -> Optional[str]:
    """The raw literal currently assigned to `key`, or None when the key is
    not assigned at all. Deliberately the same line-oriented view
    merge_config_text takes, not a TOML parse."""
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*(.*?)\s*(?:#.*)?$", text)
    return match.group(1) if match else None


def _literal_is_blank(literal: Optional[str]) -> bool:
    return literal is None or literal.strip() in ("", '""', "''")


def merge_config_text(text: str, forced: dict[str, str],
                      defaults: Optional[dict[str, str]] = None) -> str:
    """Force `key = <value-literal>` lines into TOML text: replace the first
    existing assignment of each `forced` key (whatever its value), else
    append. Everything else -- comments, unknown keys, ordering -- is
    preserved. Pure; values must already be TOML literals (use _toml_string).

    `defaults` are applied the same way but ONLY when the key is absent or
    its current value is blank -- the installer seeds them, it does not own
    them. That distinction is what stops a re-run silently resetting an
    admin's customised remote_root (§7 new-defect 7) or blanking a working
    dashboard_token when the verify response carried no report_token
    (INST-11).
    """
    lines = text.splitlines()
    remaining = dict(forced)
    for key, value in (defaults or {}).items():
        if key in remaining:
            continue
        if _literal_is_blank(_existing_literal(text, key)):
            remaining[key] = value
    for i, line in enumerate(lines):
        for key in list(remaining):
            if re.match(rf"^\s*{re.escape(key)}\s*=", line):
                lines[i] = f"{key} = {remaining.pop(key)}"
                break
    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# -- set by the CCSync installer --")
        for key, value in remaining.items():
            lines.append(f"{key} = {value}")
    return "\n".join(lines) + "\n"


def ensure_config(
    role: str,
    *,
    editor_name: str,
    dashboard_url: str,
    dashboard_token: str,
    local_root: Optional[str] = None,
    config_path: Optional[Path] = None,
) -> Path:
    """Write or refresh ~/.ccsync/config.toml BEFORE anything launches the
    companion. An existing file is merged (user tweaks survive; the keys the
    installer owns are forced); a missing one starts from the companion's
    own DEFAULT_TOML_TEXT so this never depends on the bootstrap's seeding
    (which skips existing files entirely)."""
    role = str(role or "").strip().lower()
    path = Path(config_path) if config_path is not None else config_mod.CONFIG_PATH

    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        text = config_mod.DEFAULT_TOML_TEXT

    forced: dict[str, str] = {
        "editor_name": _toml_string(editor_name),
        "dashboard_url": _toml_string(dashboard_url),
        "mode": _toml_string(role if role in ("base", "editor") else "editor"),
    }
    defaults: dict[str, str] = {}
    if str(dashboard_token or "").strip():
        forced["dashboard_token"] = _toml_string(dashboard_token)
    else:
        # A verify response with no report_token (older dashboard, a field
        # rename) must never overwrite a token that already works -- the
        # companion would then post unauthenticated forever and the fleet
        # grid would show this editor offline, with the wizard saying DONE
        # (INST-11).
        defaults["dashboard_token"] = _toml_string("")
    if role == "base":
        root = local_root or DEFAULT_BASE_LOCAL_ROOT
        forced["local_root"] = _toml_string(root)
        # Everything on the same drive OUTSIDE the tree counts as
        # out-of-tree on a base rig (see config.example.toml).
        forced["canonical_prefix"] = _toml_string(root)
    else:
        forced["local_root"] = _toml_string(local_root or DEFAULT_LOCAL_ROOT)
        forced["canonical_prefix"] = _toml_string("P:\\")
        forced["remote"] = _toml_string("creators_club_sftp")
        # SEEDED, not owned: a blank remote_root uploads an editor's
        # originals into their bare SFTP home instead of the project tree
        # (S-1), so it must never stay blank -- but an admin who pointed this
        # editor at a different pool path keeps it across re-runs.
        defaults["remote_root"] = _toml_string(DEFAULT_REMOTE_ROOT)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(merge_config_text(text, forced, defaults), encoding="utf-8")
    return path


# -- base-mode companion install ------------------------------------------------

def register_companion_autostart(
    exe_path: Path,
    set_run_value: Callable[[str, str], None] = default_set_run_value,
) -> None:
    """HKCU Run entry pointing straight at the exe -- same style the
    bootstrap registers for editors (windows_bootstrap.ps1's companion
    step), so both roles end up with the identical autostart shape."""
    set_run_value(COMPANION_RUN_VALUE, str(exe_path))


def launch_companion(
    exe_path: Path,
    popen: Callable[..., Any] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Start the companion detached and confirm it's still alive ~3s later
    (mirrors the bootstrap's launch-and-confirm step). False on any failure
    -- callers log it; the install itself still succeeded."""
    try:
        creationflags = 0
        if sys.platform == "win32":
            # CREATE_NO_WINDOW: without it a console-build companion gets a
            # fresh EMPTY console allocated, and closing that window kills
            # the app (seen live 2026-07-25 right after a base install).
            creationflags = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
        # This wizard is itself a frozen onefile app: strip inherited
        # PyInstaller runtime vars and force the companion to be a fully
        # independent instance with its OWN extraction dir, never a borrower
        # of ours (which dies when the wizard closes) -- see the companion's
        # upgrade._default_spawn for the live failure this prevents.
        child_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("_PYI") and not k.startswith("_MEI")
        }
        child_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        proc = popen(
            [str(exe_path)],
            cwd=str(Path(exe_path).parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
            env=child_env,
        )
        sleep(3.0)
        return proc.poll() is None
    except Exception:
        return False


def installer_on_forbidden_drive() -> bool:
    """True when the running installer lives on P: or a UNC share -- running
    it from there locks the file server-side for as long as the wizard is
    open (seen live 2026-07-25: an editor ran onboard.exe off the NAS and
    pinned the package folder all day), and the editor flow is about to
    unmount P: out from under itself."""
    if not getattr(sys, "frozen", False):
        return False
    exe = str(sys.executable)
    return exe.upper().startswith("P:") or exe.startswith("\\\\")
