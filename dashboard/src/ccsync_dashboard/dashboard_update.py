"""The dashboard updating its own CODE over the air (ZERO_TOUCH_PLAN.md WP K).

The owner's ruling, 2026-08-18: *"make the dashboard self-update over the air,
with the NAS UI click kept only for runtime changes."* Section 5's "no Docker
socket, no self-recreate" still stands -- it forbids replacing the BOX. This
module replaces what is INSIDE it, on exactly the companion's terms:

    a signed record in the vendor feed
      -> downloaded and sha256-verified by the running dashboard
      -> verified against the public keys BAKED INTO THE BUILD IT IS RUNNING
      -> staged, import-and-migration-checked in a subprocess
      -> the live databases backed up
      -> swapped in with one rename
      -> the process asks to be re-exec'd (exit 75; deploy/run.sh loops)

WHAT THIS IS NOT ALLOWED TO DO, and the reasoning behind each:

- **Bring a dependency.** The venv is the image's. A bundle built against a
  different `runtime_id` (runtime_id.py) is a RUNTIME update: the page names
  the one click in the NAS's own UI and no button is offered. Refusing is the
  only honest answer -- a code tree importing a module the venv does not have
  fails half way through a boot, on a customer's NAS, with the previous tree
  already swapped away.
- **Run anything from the volume during the decision.** `/data/code` is
  writable by this process; `/app` is not. So the code root is chosen by
  `deploy/select_code_root.py`, executed by the IMAGE's python from the
  IMAGE's `/app/deploy`, verifying the IMAGE's baked keys. Nothing in
  `/data/code` gets a vote in whether `/data/code` is used.
- **Leave a state in memory.** Every decision lands in
  `/data/code/update_state.json`, `current.json` or `boot_attempts.json`
  before it matters. A safety latch that only exists in RAM is the failure
  mode `docs/SYNC_SAFETY.md` was written about.
- **Take the dashboard down for longer than it must.** The swap is a rename
  and a re-exec: about ten seconds. Anything that can fail (download, extract,
  verify, migrate-on-a-copy) happens BEFORE the live tree is touched, and
  every one of those failures leaves the running dashboard exactly as it was.

BIND-MOUNT DEPLOYMENTS (every live site today, `/app` read-only from the
host) are detected by the ABSENCE of `/venv/.runtime-id` and refuse every
apply with a message naming `server/install_dashboard_app.py`. Nothing here
changes for them.

WATCHDOG. `select_code_root.py` increments `boot_attempts.json` before it
hands a volume tree to run.sh, and this module clears it once the process has
been up and answering for BOOT_HEALTHY_SECONDS. Two failed boots in a row
therefore revert `current.json` to the previous tree (or the image) with a
reason recorded, automatically, with nobody watching -- which is the whole
point, since the thing that has failed to boot is the thing an admin would
have used to fix it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request as FastAPIRequest
from pydantic import BaseModel

from . import VERSION, db, release_feed, runtime_id as runtime_id_mod
from .api import _require_admin, get_conn

log = logging.getLogger("ccsync.dashboard.dashboard_update")

# The image's own trees, as the Dockerfile lays them out. Overridable ONLY for
# tests (the same seam select_code_root.py exposes); a deployment never sets
# these, and nothing reads them from a request.
IMAGE_APP_ROOT = Path(os.environ.get("CCSYNC_APP_ROOT") or "/app")
# The three sub-app roots a code tree provides, in run.sh's order. They are
# directory names inside a bundle here, and mount points (/broll-app, ...) in
# the image -- deploy/select_code_root.py carries the same list for the same
# reason, and the two must not disagree about the order.
SUBAPP_DIRS: tuple[str, ...] = ("broll-app", "music-app", "ytdl-app")

# The exit code run.sh's loop reads as "re-select the code root and exec me
# again". 75 is EX_TEMPFAIL from sysexits.h -- a code no library and no
# uvicorn path produces by accident, which is what makes it safe to give a
# meaning to.
RESTART_EXIT_CODE = 75

# How long the process must have been up before a boot counts as healthy and
# `boot_attempts.json` is cleared. Long enough that a crash-on-first-request
# still counts as a failed boot, short enough that a restart storm cannot
# outrun it.
BOOT_HEALTHY_SECONDS = 45.0

# ...and then it has to PROVE it can serve (REL-6, resilience sweep
# 2026-08-28). Sleeping and unlinking the counter proved only that the process
# had not exited: a tree that imports cleanly (which is exactly what
# stage-verify tested), binds the port and then 500s every request -- a
# template missing from the tarball, a lifespan thread deadlocked -- was
# marked permanently healthy, so select_code_root kept booting it, the
# auto-revert never fired, and the admin could not roll it back because the
# dashboard is the thing that is broken. The probe is one loopback GET of the
# route the container healthcheck already reads; it must answer 200 with THIS
# build's version. Retried, because a slow first request on a NAS under load
# is not a wedged dashboard.
BOOT_HEALTH_PROBE_SECONDS = 45.0
BOOT_HEALTH_PROBE_INTERVAL = 3.0
BOOT_HEALTH_PROBE_TIMEOUT = 10.0

# This process, distinctly from any other that ever had this pid (REL-9).
# Container pids are small and deterministic -- run.sh is pid 1 and uvicorn is
# its child -- so `owner_pid == os.getpid()` was true for a NEW process reading
# a DEAD process's latch, and the 409 that healed on a restart did not.
PROCESS_NONCE = uuid.uuid4().hex

# Two failed boots of a volume tree revert it. One is not enough (a NAS that
# lost power mid-boot is not a bad bundle); three would mean two full outages
# before anything self-heals.
#
# The number that ACTS on this is deploy/select_code_root.py's own copy: it
# runs before anything from this package is importable, so it cannot read this
# one. Held here because this is where the reasoning belongs, and pinned
# together by dashboard/tests/test_select_code_root.py.
MAX_BOOT_ATTEMPTS = 2

# Ceilings and floors for an apply. The bundle is ~1 MB of source today; 256
# MiB is a ceiling, not an expectation. The free-space floor is what stops an
# update filling `/data` and taking the SQLite database down with it -- which
# would be a far worse outage than not updating.
BUNDLE_MAX_BYTES = 256 * 1024 * 1024
BUNDLE_FETCH_TIMEOUT = 600.0
MIN_FREE_BYTES = 256 * 1024 * 1024

# The stage-verify subprocess: import the new code and migrate COPIES of the
# databases. Generous, because a first migration on a large b-roll index is
# real work, and bounded, because a wedged verifier must not leave an apply
# "in progress" forever.
STAGE_VERIFY_TIMEOUT = 600.0

# A ytdl pipeline mid-flight is the one piece of work a ten-second restart
# actually loses (the worker restarts a resumable phase, but an editor is
# sitting there watching it). Mirrors ytdlweb.db's own non-terminal list;
# `ready_for_review` is deliberately absent -- the worker is not working on it.
_YTDL_BUSY_PHASES = ("generating_terms", "searching", "enriching", "filtering", "downloading")


class DashboardUpdateError(Exception):
    """`status_code`/`detail` mirror HTTPException without importing FastAPI
    into the worker thread's path -- the same shape (and the same reason) as
    package_store.PackageStoreError. Every message says what was refused and
    why; a refusal an operator cannot act on is a bug."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# --------------------------------------------------------------------- paths

def data_dir(settings) -> Path:
    """The persistent volume, derived from the database path (`/data` in every
    deployment). Derived rather than hardcoded so a test -- and a dev checkout
    -- can have one without a container."""
    return Path(settings.db_path).resolve().parent


def code_dir(settings) -> Path:
    return data_dir(settings) / "code"


def current_json_path(settings) -> Path:
    return code_dir(settings) / "current.json"


def boot_attempts_path(settings) -> Path:
    return code_dir(settings) / "boot_attempts.json"


def update_state_path(settings) -> Path:
    return code_dir(settings) / "update_state.json"


def backups_dir(settings) -> Path:
    return data_dir(settings) / "backups"


def version_dir(settings, version: str) -> Path:
    return code_dir(settings) / _safe_version(version)


def _safe_version(version: str) -> str:
    """A version is a directory name, so it is checked like one. Dotted
    numerals only: anything else could be `..` or an absolute path with a
    creative separator."""
    raw = str(version or "").strip()
    if not raw or any(ch not in "0123456789." for ch in raw) or ".." in raw:
        raise DashboardUpdateError(
            400, f"refusing {raw!r} as a version: dotted-numeric only (it names a directory)")
    return raw


def _read_json(path: Path) -> dict[str, Any]:
    """Every read of this module's own state files. A corrupt or absent file
    is {} -- never an exception, because these are read on the boot path and
    a JSON error must not be what stops the dashboard starting."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write-then-rename, always: a half-written current.json read by
    select_code_root.py at the next boot is a dashboard that will not start."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


# ----------------------------------------------------------- what is running

def image_runtime_id() -> str:
    """The runtime id baked into THIS image, or "" in bind-mount mode."""
    return runtime_id_mod.read_image_runtime_id(
        os.environ.get("CCSYNC_RUNTIME_ID_FILE") or runtime_id_mod.IMAGE_RUNTIME_ID_PATH)


def image_mode() -> bool:
    """True when this container was built from dashboard/deploy/Dockerfile
    with WP K's marker. False means bind-mount mode OR an image built before
    this feature existed -- both refuse an apply, with different advice."""
    return bool(image_runtime_id())


def image_version() -> str:
    """The VERSION of the code INSIDE the image, read out of the image's own
    `__init__.py` without importing it: when the volume tree is what is
    running, the image's package is not the one in sys.modules, and importing
    a second copy of it would be a second `ccsync_dashboard` in the process."""
    path = IMAGE_APP_ROOT / "src" / "ccsync_dashboard" / "__init__.py"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("VERSION"):
            _, _, value = stripped.partition("=")
            return value.strip().strip('"').strip("'")
    return ""


def version_tuple(text: str) -> tuple[int, ...]:
    """Dotted-numeric to a comparable tuple; () for anything else, which
    compares lower than every real version. Mirrors
    select_code_root.parse_version, which is the copy that decides at BOOT --
    the two must agree, or the page would offer an update the container then
    refuses to boot."""
    raw = str(text or "").strip()
    if not raw or any(ch not in "0123456789." for ch in raw):
        return ()
    try:
        return tuple(int(p) for p in raw.split(".") if p != "")
    except ValueError:
        return ()


def newer_than_image(version: str) -> bool:
    """True when a bundle of `version` would actually be booted.

    The image always wins a tie or better (select_code_root's rule), so
    offering an older bundle would be offering a button whose only effect is
    to land back on the image's own code. An image whose version cannot be
    read at all answers True: that is the "no image to compare against" case,
    and the boot-time check is still there behind it."""
    image = version_tuple(image_version())
    if not image:
        return True
    return version_tuple(version) > image


def running_root() -> Path:
    """The directory that is on sys.path as the dashboard's code root."""
    return Path(__file__).resolve().parent.parent


def running_source(settings) -> str:
    """Where the code answering this request came from: `volume` (a bundle
    applied over the air), `image` (the container's own layer) or `checkout`
    (a developer's tree). Reported by /api/v1/health so "which code is live"
    is never a guess."""
    root = running_root()
    try:
        root.relative_to(code_dir(settings))
        return "volume"
    except ValueError:
        pass
    try:
        root.relative_to(IMAGE_APP_ROOT)
        return "image"
    except ValueError:
        return "checkout"


def health_code_block(settings) -> dict[str, Any]:
    """The `code` object /api/v1/health gained (WP K). `ok` and `version` are
    untouched beside it -- the fleet reads those two and nothing else."""
    return {
        "running": VERSION,
        "image": image_version(),
        "source": running_source(settings),
        "runtime_id": image_runtime_id(),
    }


# ------------------------------------------------------------ the boot watchdog

def clear_boot_attempts(settings) -> None:
    """This boot worked. Called by the startup hook once the process has been
    up for BOOT_HEALTHY_SECONDS; until then the counter stands, which is what
    makes a crash-loop self-heal."""
    path = boot_attempts_path(settings)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:                                          # noqa: BLE001
        log.warning("could not clear %s: %s", path, exc)


def _loopback_opener():
    """The opener the health probe uses. Its own function purely as a test
    seam: the suite stubs THIS, never urlopen (docs/GOTCHAS.md section 12 --
    no dashboard call may follow a redirect, and a test that patches urlopen
    is a test that does not exercise the opener the code actually builds)."""
    return urllib.request.build_opener(_NoLoopbackRedirect)


class _NoLoopbackRedirect(urllib.request.HTTPRedirectHandler):
    """A 30x from our own health route is a misconfiguration, not a hop to
    follow: the one thing this probe must not do is measure some OTHER
    server's health."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def dashboard_port(settings) -> int:
    """The port uvicorn is listening on, as run.sh set it. DASH_PORT wins
    because it is what the process was actually started with; settings.port
    is the same value in every deployment and the fallback for a test."""
    raw = (os.environ.get("DASH_PORT") or "").strip()
    try:
        if raw:
            return int(raw)
    except ValueError:
        pass
    return int(getattr(settings, "port", 0) or 8480)


def probe_health(settings, *, timeout: float = BOOT_HEALTH_PROBE_TIMEOUT) -> tuple[bool, str]:
    """(this dashboard is serving, why not). One loopback GET, no credential:
    /api/v1/health is in app.py's _OPEN_EXACT for exactly this, and the
    unauthenticated body carries `ok` and `version`, which is all this asks
    about. `ok` itself is deliberately NOT required -- an unreachable
    Syncthing makes it False, and that is not a reason to revert the code."""
    url = f"http://127.0.0.1:{dashboard_port(settings)}/api/v1/health"
    try:
        with _loopback_opener().open(url, timeout=timeout) as resp:
            code = int(getattr(resp, "status", None) or resp.getcode() or 0)
            raw = resp.read(64 * 1024)
    except Exception as exc:                                          # noqa: BLE001
        return False, f"{url} did not answer ({type(exc).__name__}: {exc})"
    if code != 200:
        return False, f"{url} answered {code}"
    try:
        body = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return False, f"{url} answered 200 with something that is not JSON"
    served = str((body or {}).get("version") or "")
    if served != VERSION:
        return False, (f"{url} answered 200 as version {served or '?'}, but this process "
                       f"is {VERSION}")
    return True, ""


def wait_until_serving(settings, *, deadline_seconds: float = BOOT_HEALTH_PROBE_SECONDS,
                       interval: float = BOOT_HEALTH_PROBE_INTERVAL) -> tuple[bool, str]:
    """Probe until it answers or the window closes. The LAST failure is what
    is returned: an operator reading the log needs the reason it never came
    up, not the first transient one."""
    ok, why = probe_health(settings)
    if ok:
        return True, ""
    deadline = time.monotonic() + max(0.0, deadline_seconds)
    while time.monotonic() < deadline:
        time.sleep(max(0.1, interval))
        ok, why = probe_health(settings)
        if ok:
            return True, ""
    return False, why


def start_boot_watchdog(settings) -> threading.Thread | None:
    """Arm the "this boot is healthy" timer. Best-effort and daemon: a
    dashboard that cannot write its own state files still has to serve the
    fleet, and this is the only thing in WP K that runs on every boot."""
    if not code_dir(settings).is_dir():
        return None

    def _run() -> None:
        # Uptime first (a build that crashes on its first request must still
        # count as a failed boot), THEN proof that it can serve.
        time.sleep(BOOT_HEALTHY_SECONDS)
        ok, why = wait_until_serving(settings)
        if not ok:
            log.error(
                "this boot is NOT healthy: %s. Leaving boot_attempts standing -- "
                "%d failed boots revert /data/code/current.json to the previous tree "
                "at the next start (REL-6).", why, MAX_BOOT_ATTEMPTS)
            return
        clear_boot_attempts(settings)
        log.info("dashboard code boot marked healthy (%s, source=%s): /api/v1/health "
                 "answered 200 with this version", VERSION, running_source(settings))

    thread = threading.Thread(target=_run, name="code-boot-watchdog", daemon=True)
    thread.start()
    return thread


# ------------------------------------------------------------------- the state

def read_state(settings) -> dict[str, Any]:
    state = _read_json(update_state_path(settings))
    state.setdefault("step", "idle")
    state.setdefault("in_progress", False)
    state.setdefault("version", "")
    state.setdefault("message", "")
    state.setdefault("error", "")
    return _heal_orphaned_progress(settings, state)


def _heal_orphaned_progress(settings, state: dict[str, Any]) -> dict[str, Any]:
    """An `in_progress` flag whose worker THREAD no longer exists is a dead
    latch, and this is where it dies (dash-release-ai-2, 2026-08-21).

    The flag is written to disk on purpose (this module's docstring: "leave
    no state in memory"), but the thread that owned it lives in ONE process.
    A container stop, an OOM kill or a NAS reboot during the download step
    (up to BUNDLE_FETCH_TIMEOUT seconds of window) left `in_progress: true`
    in `update_state.json` with nobody to clear it: every later apply AND
    every rollback answered 409 forever, and on the appliance shape the admin
    has no shell to edit the file with. So the writer stamps `owner_pid`, and
    a flag belonging to any other pid (or to a state file written before this
    fix, which carries no pid at all) reads as "failed, interrupted".

    `restart_requested` is the ONE in-progress state that legitimately
    outlives its process: an update that reached request_restart WANTS the
    next process to see it, and `consume_restart_request` is what clears it.
    """
    if not state.get("in_progress") or state.get("restart_requested"):
        return state
    owner = state.get("owner_pid")
    # REL-9 (resilience sweep 2026-08-28): the pid alone was not "this
    # process". run.sh is pid 1 and uvicorn is its child, so a container that
    # lost power mid-download came back and gave the new worker the SAME small
    # pid the dead one had -- and this guard then read the dead latch as live,
    # 409ing every apply AND every rollback for ever, on the appliance shape
    # where there is no shell to delete the file with.
    if owner == os.getpid() and state.get("owner_nonce") == PROCESS_NONCE:
        return state
    step = str(state.get("step") or "?")
    log.warning("clearing a stale dashboard-update in-progress flag left at step %s "
                "by pid %s/%s (this process is %s/%s) -- the worker that owned it is gone",
                step, owner, state.get("owner_nonce") or "?", os.getpid(), PROCESS_NONCE)
    state.update({
        "step": "failed",
        "in_progress": False,
        "owner_pid": None,
        "owner_nonce": "",
        "error": f"interrupted by a restart at step {step}",
        "finished_at": db.utcnow_iso(),
        "updated_at": db.utcnow_iso(),
    })
    _write_json(update_state_path(settings), state)
    return state


def _set_state(settings, **fields: Any) -> dict[str, Any]:
    state = read_state(settings)
    state.update(fields)
    # Who owns the flag, so a fresh process can tell "an update is running"
    # from "an update was running when this container was killed" -- see
    # _heal_orphaned_progress (dash-release-ai-2).
    if fields.get("in_progress"):
        state["owner_pid"] = os.getpid()
        # ...and WHICH process (REL-9): a pid repeats, this does not.
        state["owner_nonce"] = PROCESS_NONCE
    elif "in_progress" in fields:
        state["owner_pid"] = None
        state["owner_nonce"] = ""
    state["updated_at"] = db.utcnow_iso()
    _write_json(update_state_path(settings), state)
    return state


def _fail_state(settings, message: str) -> None:
    log.warning("dashboard code update failed: %s", message)
    _set_state(settings, step="failed", in_progress=False, error=message,
               finished_at=db.utcnow_iso())


# ------------------------------------------------------------------ the checks

def _free_bytes(path: Path) -> int:
    try:
        return int(shutil.disk_usage(str(path)).free)
    except OSError:
        return -1                      # unknown: the caller treats it as "do not guess"


def _db_paths(settings) -> dict[str, Path]:
    """The three databases an apply backs up and migration-checks.

    Each sub-app's data root is an environment variable in every deployment
    (compose sets BROLL_DATA_ROOT/MUSIC_DATA_ROOT), and the already-imported
    module is preferred where there is one, because that is the path the
    running app actually opened -- not the path the environment claims."""
    paths: dict[str, Path] = {"dashboard": Path(settings.db_path)}

    broll_config = sys.modules.get("app.config")
    if broll_config is not None and hasattr(broll_config, "get_db_path"):
        try:
            paths["broll"] = Path(broll_config.get_db_path())
        except Exception:                                            # noqa: BLE001
            pass
    if "broll" not in paths and os.environ.get("BROLL_DATA_ROOT"):
        paths["broll"] = Path(os.environ["BROLL_DATA_ROOT"]) / "broll.db"

    music_config = sys.modules.get("musicweb.config")
    if music_config is not None and getattr(music_config, "DB_PATH", None):
        paths["music"] = Path(music_config.DB_PATH)
    elif os.environ.get("MUSIC_DB_PATH"):
        paths["music"] = Path(os.environ["MUSIC_DB_PATH"])
    elif os.environ.get("MUSIC_DATA_ROOT"):
        paths["music"] = Path(os.environ["MUSIC_DATA_ROOT"]) / "music.db"

    return {name: path for name, path in paths.items() if path.is_file()}


def _ytdl_db_path() -> Path | None:
    config = sys.modules.get("ytdlweb.config")
    if config is not None and getattr(config, "DB_PATH", None):
        return Path(config.DB_PATH)
    root = (os.environ.get("YTDL_DATA_ROOT") or "").strip()
    return Path(root) / "ytdl.db" if root else None


def active_ytdl_jobs() -> int:
    """How many YouTube pipelines are mid-flight. Read straight from the
    sub-app's SQLite file rather than through ytdlweb: this must answer even
    when the /ytdl mount is absent or degraded, and it must never import a
    module that could be missing. An unreadable database answers 0 -- an
    optional feature's bookkeeping cannot be allowed to block an update
    forever."""
    path = _ytdl_db_path()
    if path is None or not path.is_file():
        return 0
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return 0
    try:
        marks = ",".join("?" for _ in _YTDL_BUSY_PHASES)
        row = conn.execute(
            f"SELECT COUNT(*) FROM jobs WHERE phase IN ({marks})", _YTDL_BUSY_PHASES
        ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _find_record(app_state, version: str) -> dict[str, Any]:
    records = release_feed.dashboard_records(release_feed.verified_records(app_state))
    match = next((r for r in records if str(r.get("version", "")) == version), None)
    if match is None:
        raise DashboardUpdateError(
            404, f"no verified dashboard record for {version} in the last feed check. "
                 "Run Check now first (the feed is re-verified on every check, and the "
                 "cache is not kept across a restart).")
    return match


def preflight(settings, app_state, *, version: str, force: bool) -> dict[str, Any]:
    """Every refusal, in one place, BEFORE a byte is downloaded. Returns the
    verified record. Raises DashboardUpdateError with a detail that names the
    reason -- an operator reading it must know what to do next."""
    version = _safe_version(version)
    if not image_mode():
        raise DashboardUpdateError(
            409, "this deployment updates from the base rig, not over the air: it is "
                 "running in bind-mount mode (no /venv/.runtime-id), so its code comes "
                 "from server/install_dashboard_app.py. Move it to the container image "
                 "first (docs/DOCKER.md).")
    state = read_state(settings)
    if state.get("in_progress"):
        raise DashboardUpdateError(
            409, f"an update to {state.get('version') or 'another version'} is already in "
                 f"progress (step: {state.get('step')}). Wait for it to finish or fail.")
    if version == VERSION:
        raise DashboardUpdateError(409, f"this dashboard is already running {version}")
    if not newer_than_image(version):
        raise DashboardUpdateError(
            409, f"dashboard {version} is not newer than the code in this container image "
                 f"({image_version()}), and the image always wins at boot -- applying it "
                 "would land right back on the image's own code. To go back, roll back "
                 "instead.")

    root = code_dir(settings)
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".writable"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise DashboardUpdateError(
            500, f"{root} is not writable ({exc}) -- the data volume has to hold the new "
                 "code tree. Check the mount and the uid the container runs as.")

    record = _find_record(app_state, version)
    record_runtime = str(record.get("runtime_id") or "")
    if record_runtime != image_runtime_id():
        raise DashboardUpdateError(
            409, f"dashboard {version} is a RUNTIME update: it was built against a "
                 f"different image (runtime {record_runtime[:12] or 'unknown'}, this "
                 f"container is {image_runtime_id()[:12]}). Its dependencies are not in "
                 "this container's venv, so applying it would break the boot. Update the "
                 "image from your NAS's own app manager instead.")

    if not force:
        busy = active_ytdl_jobs()
        if busy:
            raise DashboardUpdateError(
                409, f"{busy} YouTube job(s) are running: an update restarts the "
                     "dashboard for about ten seconds and interrupts them. Wait, or "
                     "apply again with force.")

    size = int(record.get("size_bytes") or 0)
    # tarball + extracted tree + the previous tree still on disk + the database
    # backups, with a floor left over so a full /data can never be this
    # feature's doing (a full /data takes the SQLite database down with it).
    needed = size * 4 + sum(p.stat().st_size for p in _db_paths(settings).values()) * 2
    free = _free_bytes(root)
    if free >= 0 and free < needed + MIN_FREE_BYTES:
        raise DashboardUpdateError(
            507, f"not enough free space on the data volume: {free // (1024 * 1024)} MiB "
                 f"free, this update needs about {needed // (1024 * 1024)} MiB plus a "
                 f"{MIN_FREE_BYTES // (1024 * 1024)} MiB safety margin. Free some space "
                 "and try again.")
    return record


# ---------------------------------------------------------------- extraction

def _refuse_unsafe_member(member: tarfile.TarInfo) -> None:
    name = member.name
    if name.startswith("/") or name.startswith("\\") or ":" in name.split("/")[0]:
        raise DashboardUpdateError(400, f"bundle member {name!r} is an absolute path -- refused")
    if any(part in ("..",) for part in Path(name).parts):
        raise DashboardUpdateError(400, f"bundle member {name!r} escapes the bundle -- refused")
    if member.issym() or member.islnk():
        raise DashboardUpdateError(400, f"bundle member {name!r} is a link -- refused")
    if member.isdev() or member.isfifo():
        raise DashboardUpdateError(400, f"bundle member {name!r} is a device or fifo -- refused")
    if not (member.isfile() or member.isdir()):
        raise DashboardUpdateError(400, f"bundle member {name!r} is not a regular file -- refused")


def extract_bundle(archive: Path, dest: Path) -> dict[str, Any]:
    """Extract `archive` into `dest` and return its manifest.

    Every member is checked BEFORE it is written: absolute paths, `..`
    anywhere in the path, symlinks, hardlinks, devices and fifos are all
    refused outright (a tarball is an untrusted archive format and this
    process can write the data volume). Python's own `filter="data"` covers
    most of this from 3.12, but the refusals are spelled out here so the
    REASON reaches the operator instead of a TarError."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            _refuse_unsafe_member(member)
        for member in members:
            # No mode/owner from the archive: everything lands owned by this
            # process with a fixed mode (see the builder, which writes 0644).
            # filter="data" is Python's own version of the checks above --
            # kept as belt and braces, and because it is the default from 3.14
            # anyway; the explicit refusals stay because they are the ones
            # whose REASON reaches the operator.
            tar.extract(member, path=str(dest), set_attrs=False, filter="data")
    manifest = _read_json(dest / "manifest.json")
    if not manifest:
        raise DashboardUpdateError(400, "the bundle has no readable manifest.json -- refused")
    return manifest


def verify_extracted_tree(dest: Path, manifest: dict[str, Any], record: dict[str, Any]) -> None:
    """The extracted tree is what the signed record described.

    The cryptographic anchor is the record's own signature plus the sha256 of
    the tarball, both already checked. This adds the two cross-checks that
    catch the boring failures: a manifest that disagrees with the record it
    travelled with, and a file that did not survive extraction."""
    if str(manifest.get("kind")) != release_feed.DASHBOARD_KIND:
        raise DashboardUpdateError(400, "the bundle's manifest is not a dashboard bundle -- refused")
    for field in ("version", "runtime_id"):
        if str(manifest.get(field) or "") != str(record.get(field) or ""):
            raise DashboardUpdateError(
                400, f"the bundle's manifest {field} does not match the signed record -- refused")
    files = manifest.get("files_sha256")
    if not isinstance(files, dict) or not files:
        raise DashboardUpdateError(400, "the bundle's manifest lists no files -- refused")
    for name, expected in files.items():
        path = dest / name
        if not path.is_file():
            raise DashboardUpdateError(400, f"the bundle is missing {name} -- refused")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise DashboardUpdateError(400, f"{name} does not match the bundle manifest -- refused")


def bundle_pythonpath(root: Path) -> list[str]:
    """The four PYTHONPATH roots a code tree provides, in the order run.sh
    puts them (`src` first). `templates/` and `static/` are found relative to
    `src`'s parent by ui.py/app.py, which is why the bundle root is what a
    tree is, not `src` alone."""
    return [str(root / "src")] + [str(root / name) for name in SUBAPP_DIRS]


# ---------------------------------------------------------------- stage-verify

# Run by the IMAGE's python with the NEW tree on PYTHONPATH. Source lives here,
# in the running code, and is passed on the command line -- never read out of
# the tree being verified, which would be the tree grading its own exam.
_STAGE_VERIFY_SOURCE = r'''
import json, sqlite3, sys, traceback

checks, ok = [], True
targets = json.loads(sys.argv[1])

def record(name, fn):
    global ok
    try:
        fn()
        checks.append({"check": name, "ok": True, "detail": ""})
    except Exception as exc:
        ok = False
        checks.append({"check": name, "ok": False,
                       "detail": f"{type(exc).__name__}: {exc}",
                       "traceback": traceback.format_exc()[-2000:]})

def import_app():
    import ccsync_dashboard.app  # noqa: F401

def migrate_dashboard():
    from ccsync_dashboard import db
    conn = db.connect(targets["dashboard"])
    try:
        db.migrate(conn)
    finally:
        conn.close()

def migrate_broll():
    from app import db as broll_db
    from pathlib import Path
    broll_db.ensure_schema(Path(targets["broll"]))

def migrate_music():
    from musicweb import db as music_db
    conn = sqlite3.connect(targets["music"])
    try:
        music_db.ensure_schema(conn)
    finally:
        conn.close()

record("import ccsync_dashboard.app", import_app)
if targets.get("dashboard"):
    record("migrate dashboard.db (copy)", migrate_dashboard)
if targets.get("broll"):
    record("migrate broll.db (copy)", migrate_broll)
if targets.get("music"):
    record("migrate music.db (copy)", migrate_music)

# REL-10: the highest dashboard schema THIS tree knows how to run against.
# Asked of the new code rather than derived here, because the new code is the
# only thing that knows -- and it is what a later rollback compares the LIVE
# database against before going back to an older tree.
schema_version = 0
try:
    from ccsync_dashboard import db as _db
    schema_version = int(_db.SCHEMA_VERSION)
except Exception:
    schema_version = 0

print(json.dumps({"ok": ok, "checks": checks, "schema_version": schema_version}))
'''


def stage_verify(root: Path, db_copies: dict[str, Path], *,
                 timeout: float = STAGE_VERIFY_TIMEOUT) -> dict[str, Any]:
    """Import the staged code and run every migration against COPIES.

    In a subprocess, and this is not a detail: the new code cannot be imported
    into the running process (a second `ccsync_dashboard` in `sys.modules`
    would be a half-replaced app serving requests), and a migration that
    corrupts a database has to do it to a copy first. A non-zero exit, a
    timeout or an unparseable answer are all failures -- the running
    dashboard keeps running and nothing is swapped."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(bundle_pythonpath(root))
    # The verifier boots the app's imports, not the app: no server, no
    # collector thread, no port. Everything it could otherwise pick up from
    # the live environment that would make it write somewhere real is passed
    # explicitly as a copy path.
    env["DASH_DEV_INSECURE"] = "1"
    payload = json.dumps({name: str(path) for name, path in db_copies.items()})
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _STAGE_VERIFY_SOURCE, payload],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=env, cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        raise DashboardUpdateError(
            500, f"the staged code did not finish its checks within {int(timeout)}s -- "
                 "nothing was swapped")
    except OSError as exc:
        raise DashboardUpdateError(500, f"could not run the staged code's checks: {exc}")
    stdout = (proc.stdout or "").strip()
    tail = (proc.stderr or "").strip()[-800:]
    try:
        result = json.loads(stdout.splitlines()[-1]) if stdout else {}
    except (ValueError, IndexError):
        result = {}
    if proc.returncode != 0 or not result:
        raise DashboardUpdateError(
            400, f"the staged code failed its checks (exit {proc.returncode}). "
                 f"Nothing was swapped. {tail}")
    if not result.get("ok"):
        failed = "; ".join(
            f"{c['check']}: {c['detail']}" for c in result.get("checks", []) if not c.get("ok"))
        raise DashboardUpdateError(
            400, f"the staged code failed its checks. Nothing was swapped. {failed}")
    return result


# --------------------------------------------------------------------- backups

def backup_database(source: Path, dest: Path) -> None:
    """Copy a live SQLite database with the backup API, never the filesystem.

    Every one of these is open in WAL mode by a process that is still serving
    requests: `shutil.copy` of the .db alone silently loses everything in the
    -wal, which is exactly the data an admin restoring a backup would need
    most."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=10.0)
    try:
        out = sqlite3.connect(str(dest), timeout=10.0)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()


def backup_databases(settings, label: str) -> dict[str, Any]:
    """Back up every database this update could migrate, into
    `/data/backups/<ts>-<label>/`. Best-effort per database, and the result
    says which ones made it: a b-roll index that could not be copied must not
    stop a dashboard update, but the admin has to be able to see that it
    did not."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest_dir = backups_dir(settings) / f"{stamp}-{label}"
    made: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for name, path in _db_paths(settings).items():
        try:
            backup_database(path, dest_dir / path.name)
            made[name] = str(dest_dir / path.name)
        except (sqlite3.Error, OSError) as exc:                      # noqa: PERF203
            skipped[name] = str(exc)
            log.warning("could not back up %s (%s): %s", name, path, exc)
    _write_json(dest_dir / "backup.json", {
        "created_at": db.utcnow_iso(), "label": label, "from_version": VERSION,
        "databases": made, "skipped": skipped,
    })
    return {"dir": str(dest_dir), "databases": made, "skipped": skipped}


# -------------------------------------------------- schema vs code (REL-10)

def live_schema_versions(settings) -> dict[str, int]:
    """`PRAGMA user_version` of every database an apply migrates.

    Read at APPLY time into current.json, so that a later rollback can answer
    "the code you are going back to predates the schema this database is on"
    without having to know what the old tree would have done. Best-effort per
    database: one unreadable index must not stop an update."""
    out: dict[str, int] = {}
    for name, path in _db_paths(settings).items():
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        except sqlite3.Error:
            continue
        try:
            row = conn.execute("PRAGMA user_version").fetchone()
            out[name] = int(row[0]) if row else 0
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return out


def tree_schema_version(settings, version: str) -> int | None:
    """The dashboard schema an applied tree was built for, from its
    manifest.json (written at apply time from the stage-verify answer). None
    means "we cannot tell": a tree applied before REL-10, or the image, whose
    manifest this dashboard never wrote. None is NOT zero and must never read
    as "safe" -- see rollback."""
    if not version:
        return None
    manifest = _read_json(version_dir(settings, version) / "manifest.json")
    value = manifest.get("schema_version")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def backup_for_version(settings, version: str) -> str:
    """The newest backup taken BEFORE `version` was applied, by name. This is
    the directory an admin has to restore alongside a rollback that goes back
    past a migration, and naming it is the whole point of REL-10: "restore a
    backup" is not an instruction anybody can act on at 2am."""
    label = f"before-{version}"
    for entry in list_backups(settings):
        if str(entry.get("name", "")).endswith(f"-{label}"):
            return str(entry["name"])
    return ""


# ------------------------------------------------------ bounded disk (REL-5)

# Nothing on the release path ever pruned, and a full /data is a SQLite write
# failure -- i.e. the dashboard that tells everyone whether their footage is
# syncing going down (REL-5, resilience sweep 2026-08-28). A backup per apply
# and a code tree per version, both kept for ever, are what fills it.
#
# Three per label, because the labels are per-version (`before-0.7.19`): the
# useful history is "the last few updates", and a fourth copy of broll.db is
# gigabytes. The size budget is the second bound, for a site whose indexes are
# large enough that even three is too many.
BACKUPS_KEEP_PER_LABEL = 3
BACKUPS_KEEP_TOTAL = 8
BACKUPS_MAX_BYTES = 8 * 1024 * 1024 * 1024
# The running tree, the one it can roll back to, and one more.
CODE_TREES_KEEP = 3
# A publish (a package, or a bundle fetched by the feed) is refused below
# this, the way an apply already is. Same floor, same reason.
PUBLISH_MIN_FREE_BYTES = MIN_FREE_BYTES


def data_space(settings) -> dict[str, Any]:
    """The `/data` gauge for /api/v1/health and the Packages page. -1 means
    "could not measure", which must never be rendered as roomy."""
    root = data_dir(settings)
    try:
        usage = shutil.disk_usage(str(root))
    except OSError as exc:                                            # noqa: BLE001
        return {"path": str(root), "free_bytes": -1, "total_bytes": -1,
                "error": str(exc)}
    return {"path": str(root), "free_bytes": int(usage.free),
            "total_bytes": int(usage.total),
            "used_percent": (round(100.0 * (usage.total - usage.free) / usage.total, 1)
                             if usage.total else None),
            "error": ""}


def _backup_label(name: str) -> str:
    """`20260828T101500Z-before-0.7.19` -> `before-0.7.19`."""
    _, _, label = str(name).partition("-")
    return label


def prune_backups(settings) -> list[str]:
    """Keep the newest BACKUPS_KEEP_PER_LABEL per label, then trim the whole
    directory to BACKUPS_KEEP_TOTAL and BACKUPS_MAX_BYTES, newest first.

    Deletes only directories this module wrote (they carry a backup.json), and
    never the newest one of all -- a bounded history is still a history."""
    entries = list_backups(settings)                    # newest first
    removed: list[str] = []
    per_label: dict[str, int] = {}
    keep: list[dict[str, Any]] = []
    for entry in entries:
        label = _backup_label(entry["name"])
        per_label[label] = per_label.get(label, 0) + 1
        if per_label[label] > BACKUPS_KEEP_PER_LABEL:
            removed.append(entry["name"])
        else:
            keep.append(entry)
    running_bytes = 0
    for index, entry in enumerate(keep):
        running_bytes += int(entry.get("size_bytes") or 0)
        if index == 0:
            continue
        if index >= BACKUPS_KEEP_TOTAL or running_bytes > BACKUPS_MAX_BYTES:
            removed.append(entry["name"])
    for name in removed:
        target = backups_dir(settings) / name
        if not (target / "backup.json").is_file():
            continue
        shutil.rmtree(target, ignore_errors=True)
    if removed:
        log.info("pruned %d old database backup(s): %s", len(removed), ", ".join(removed))
    return removed


def prune_code_trees(settings) -> list[str]:
    """Keep the running tree, the one current.json can roll back to, and the
    next newest. Every other `/data/code/<version>` is a full source tree that
    nothing can reach any more."""
    current = _read_json(current_json_path(settings))
    protected = {str(current.get("version") or ""), str(current.get("previous") or ""),
                 VERSION}
    versions: list[str] = []
    root = code_dir(settings)
    if not root.is_dir():
        return []
    for entry in root.iterdir():
        if entry.is_dir() and (entry / "manifest.json").is_file():
            versions.append(entry.name)
    versions.sort(key=version_tuple, reverse=True)
    keep = [v for v in versions if v in protected]
    for version in versions:
        if len(keep) >= CODE_TREES_KEEP:
            break
        if version not in keep:
            keep.append(version)
    removed = [v for v in versions if v not in keep]
    for version in removed:
        shutil.rmtree(root / version, ignore_errors=True)
    if removed:
        log.info("pruned %d old code tree(s) from %s: %s",
                 len(removed), root, ", ".join(removed))
    return removed


def list_backups(settings) -> list[dict[str, Any]]:
    root = backups_dir(settings)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        meta = _read_json(entry / "backup.json")
        size = 0
        for path in entry.glob("*"):
            try:
                size += path.stat().st_size
            except OSError:
                pass
        out.append({
            "name": entry.name,
            "created_at": meta.get("created_at") or "",
            "from_version": meta.get("from_version") or "",
            "databases": sorted((meta.get("databases") or {}).keys()),
            "size_bytes": size,
        })
    return out


def restore_backup(settings, name: str) -> dict[str, Any]:
    """Put a named backup's databases back over the live ones.

    Deliberately NOT part of a plain rollback: rolling the CODE back is cheap
    and reversible, restoring a database throws away everything that happened
    since. It is a separate, explicitly-asked-for flag on the rollback route."""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise DashboardUpdateError(400, f"refusing {name!r} as a backup name")
    source_dir = backups_dir(settings) / name
    if not source_dir.is_dir():
        raise DashboardUpdateError(404, f"no backup called {name}")
    restored: dict[str, str] = {}
    for db_name, live in _db_paths(settings).items():
        candidate = source_dir / live.name
        if not candidate.is_file():
            continue
        # Backup-API restore, not a file copy, for the same WAL reason
        # backup_database exists: the live file is open right now.
        backup_database(candidate, live)
        restored[db_name] = str(live)
    if not restored:
        raise DashboardUpdateError(404, f"backup {name} holds no database this dashboard uses")
    return {"restored": restored}


# -------------------------------------------------------------------- snapshot

def snapshot_before(settings, label: str) -> dict[str, Any]:
    """A NAS snapshot before the swap, when the NAS can take one.

    BEST-EFFORT, exactly like server/common.snapshot_before: a NAS whose
    snapshot API says 403 must not be a NAS where the dashboard cannot be
    updated. The dataset cannot be guessed from inside a container (the
    container sees `/data`, not the pool path), so it is named by
    DASH_UPDATE_SNAPSHOT_DATASET; without it this reports skipped-and-why
    rather than pretending."""
    if str(getattr(settings, "nas_kind", "")).lower() != "truenas":
        return {"ok": False, "reason": "snapshots are only wired for TrueNAS here"}
    if not getattr(settings, "nas_api_key", ""):
        return {"ok": False, "reason": "no NAS API key is configured (DASH_NAS_API_KEY)"}
    dataset = (os.environ.get("DASH_UPDATE_SNAPSHOT_DATASET") or "").strip()
    if not dataset:
        return {"ok": False,
                "reason": "no DASH_UPDATE_SNAPSHOT_DATASET is set, so there is no dataset "
                          "to snapshot (a container cannot see the pool path behind /data)"}
    try:
        from .nas.factory import make_nas_client

        client = make_nas_client(settings)
        name = f"ccsync-{label}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
        resp = client.post("/zfs/snapshot", {"dataset": dataset, "name": name})
        ok = 200 <= getattr(resp, "status_code", 500) < 300
        return {"ok": ok, "snapshot": f"{dataset}@{name}" if ok else "",
                "reason": "" if ok else f"the NAS answered {getattr(resp, 'status_code', '?')}"}
    except Exception as exc:                                          # noqa: BLE001
        # Never fatal: this is a safety net, and a missing safety net is not a
        # reason to refuse to fix the thing the update fixes.
        log.warning("pre-update snapshot failed (continuing): %s", exc)
        return {"ok": False, "reason": str(exc)}


# ----------------------------------------------------------------- the restart

def _signal_restart() -> None:
    """Ask uvicorn to shut down. run.sh's loop sees exit 75 and re-execs.

    A SIGTERM rather than an immediate exit: the graceful shutdown path runs
    the lifespan's `finally`, which stops the collector and the feed poller
    and then exits with RESTART_EXIT_CODE (see consume_restart_request).
    Monkeypatched in tests -- a suite that signals its own pytest process is
    a suite that kills itself."""
    log.warning("dashboard code update: restarting this process to pick up the new tree")
    os.kill(os.getpid(), signal.SIGTERM)


def request_restart(settings) -> None:
    _set_state(settings, step="restarting", in_progress=True, restart_requested=True)
    _signal_restart()


def consume_restart_request(settings) -> bool:
    """True means "this shutdown was asked for by an update". The flag is
    cleared FIRST, so a crash after this point cannot make every future
    shutdown claim to be a restart."""
    state = read_state(settings)
    if not state.get("restart_requested"):
        return False
    _set_state(settings, restart_requested=False, step="done", in_progress=False,
               finished_at=db.utcnow_iso())
    return True


def _exit_process(code: int) -> None:
    """The one line that ends the process with a chosen code.

    Its own function purely as a seam: `os._exit` in the shutdown path would
    end the PYTEST process too, and a suite that kills itself when a fixture
    happens to leave the flag set is a suite nobody can debug. Everything
    around it is real in the tests; only this is stubbed."""
    os._exit(code)


def finish_restart(settings) -> bool:
    """The lifespan's shutdown half. Exits with RESTART_EXIT_CODE when an
    update asked for this shutdown, so deploy/run.sh's loop re-selects the
    code root and execs again. uvicorn owns this process's exit code, and
    there is no other way to choose it from inside the app."""
    if not consume_restart_request(settings):
        return False
    log.warning("exiting %d so run.sh re-execs with the new code tree", RESTART_EXIT_CODE)
    _exit_process(RESTART_EXIT_CODE)
    return True


# --------------------------------------------------------------------- apply

def apply(settings, app_state, *, version: str, force: bool = False,
          started_by: str = "", record: dict[str, Any] | None = None) -> dict[str, Any]:
    """Download, stage, verify, back up, swap, and ask for a restart.

    Ordered so that everything which can fail happens before anything that
    changes what runs: the live tree is untouched until `current.json` is
    rewritten, and that is the second-to-last step. Raises
    DashboardUpdateError; the caller (the route, or the worker thread) is
    responsible for turning it into a state file entry and an HTTP status.

    `record` is the already-preflighted feed record when start_apply has
    checked it: preflight is what claims the "in progress" flag, so a second
    run of it here would refuse the very apply it just admitted."""
    if record is None:
        record = preflight(settings, app_state, version=version, force=force)
    version = _safe_version(version)
    root = code_dir(settings)
    staging = root / f"{version}.staging"
    final = version_dir(settings, version)
    archive = root / f"{version}.tar.gz.part"

    _set_state(settings, step="downloading", in_progress=True, version=version,
               error="", message=f"downloading {record.get('filename')}",
               started_at=db.utcnow_iso(), started_by=started_by, finished_at="")
    url = str(record.get("url") or "")
    if not url.lower().startswith("https://"):
        raise DashboardUpdateError(400, "the feed record's url is not https -- refused")
    try:
        sha, size = release_feed.fetch_artifact_to(
            url, archive, expected_sha256=str(record.get("sha256") or ""),
            max_bytes=BUNDLE_MAX_BYTES, timeout=BUNDLE_FETCH_TIMEOUT)
    except release_feed.FeedHashMismatch as exc:
        raise DashboardUpdateError(400, str(exc))
    except release_feed.FeedError as exc:
        raise DashboardUpdateError(502, f"could not download the bundle: {exc}")

    try:
        _set_state(settings, step="extracting", message="extracting the bundle")
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        manifest = extract_bundle(archive, staging)
        verify_extracted_tree(staging, manifest, record)

        _set_state(settings, step="verifying",
                   message="importing the new code and migrating database copies")
        scratch = staging / ".dbcheck"
        copies: dict[str, Path] = {}
        for name, path in _db_paths(settings).items():
            copy = scratch / f"{name}.db"
            backup_database(path, copy)
            copies[name] = copy
        checks = stage_verify(staging, copies)
        shutil.rmtree(scratch, ignore_errors=True)

        _set_state(settings, step="backing-up", message="backing up the live databases")
        backup = backup_databases(settings, f"before-{version}")
        snapshot = snapshot_before(settings, f"dashboard-update-{version}")

        # The signed record, saved beside the tree: this is what
        # deploy/select_code_root.py re-verifies at EVERY boot, so a tree
        # without it is a tree the image will refuse to run.
        _write_json(staging / "record.json", dict(record))
        # REL-10: what schema this tree knows, from the tree itself (the
        # stage-verify subprocess asked its db module). Written into the
        # manifest AFTER verify_extracted_tree has compared the manifest with
        # the signed record, so it can add nothing to what was verified -- and
        # read back by a later rollback, which is the only thing that can be
        # too late to ask.
        staged_manifest = dict(manifest)
        staged_manifest["schema_version"] = int(checks.get("schema_version") or 0)
        _write_json(staging / "manifest.json", staged_manifest)

        _set_state(settings, step="swapping", message="swapping the code tree in")
        if final.exists():
            shutil.rmtree(final, ignore_errors=True)
        staging.rename(final)
        previous = _read_json(current_json_path(settings)).get("version") or ""
        _write_json(current_json_path(settings), {
            "version": version,
            # "" means "the image" -- the fallback select_code_root uses when
            # there is no previous VOLUME tree to go back to.
            "previous": previous if previous and previous != version else "",
            "applied_at": db.utcnow_iso(),
            "applied_by": started_by,
            "record_sha": str(record.get("sha256") or ""),
            # REL-10: where the live databases stood when this tree took over,
            # and which backup holds them at that point. A rollback compares
            # the LIVE user_version against what the target tree knows, and
            # names this directory when they disagree.
            "db_user_versions": live_schema_versions(settings),
            "schema_version": int(checks.get("schema_version") or 0),
            "backup": str(backup.get("dir") or ""),
        })
        # A fresh counter for the tree about to boot: whatever the last one
        # was about, it was not this.
        boot_attempts_path(settings).unlink(missing_ok=True)
        # REL-5: bounded, and only now that current.json names what may not be
        # deleted. Best-effort -- an update must never fail on its own tidying,
        # and the free-space floor in preflight is the guard that matters.
        try:
            prune_backups(settings)
            prune_code_trees(settings)
        except OSError as exc:                                        # noqa: BLE001
            log.warning("could not prune /data after the swap: %s", exc)
        log.warning("dashboard code %s applied (from %s, by %s); restarting",
                    version, VERSION, started_by or "?")
        result = {"version": version, "sha256": sha, "size_bytes": size,
                  "checks": checks.get("checks", []), "backup": backup,
                  "snapshot": snapshot, "previous": previous}
        _set_state(settings, step="restarting", message="restarting", last_applied=result)
        request_restart(settings)
        return result
    finally:
        archive.unlink(missing_ok=True)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def schema_rollback_check(settings, target: str) -> dict[str, Any]:
    """Is the live dashboard schema above what `target` knows (REL-10)?

    Returns {"safe", "unknown", "live", "target", "backup"}. `target` "" is
    the image, and a tree applied before REL-10 carries no schema in its
    manifest either: both are UNKNOWN, which is not the same answer as safe.
    Unknown does not refuse -- the image is the escape hatch of last resort
    and blocking it would be worse than the risk it guards -- but it is SAID,
    on the page and in the confirmation, rather than rendered as fine."""
    live = int(live_schema_versions(settings).get("dashboard") or 0)
    known = tree_schema_version(settings, target)
    current = _read_json(current_json_path(settings))
    backup = (backup_for_version(settings, str(current.get("version") or ""))
              or Path(str(current.get("backup") or "")).name)
    return {"live": live, "target": known, "backup": backup,
            "unknown": known is None,
            "safe": known is None or known >= live}


def rollback(settings, *, to_version: str = "", restore_db: str = "",
             acknowledge_schema: bool = False, started_by: str = "") -> dict[str, Any]:
    """Go back to the previous tree (or the image), optionally restoring a
    named database backup.

    The same swap as an apply and none of the rest: the tree being rolled back
    TO is already on disk and was already verified when it was applied, so
    there is nothing to download and nothing to migrate. `restore_db` is a
    separate decision and is named explicitly -- see restore_backup."""
    if not image_mode():
        raise DashboardUpdateError(
            409, "this deployment updates from the base rig, not over the air "
                 "(bind-mount mode).")
    state = read_state(settings)
    if state.get("in_progress"):
        raise DashboardUpdateError(
            409, f"an update to {state.get('version') or 'another version'} is in progress "
                 f"(step: {state.get('step')}) -- rolling back underneath it would race the "
                 "swap. Wait for it to finish or fail.")
    current = _read_json(current_json_path(settings))
    if not current.get("version"):
        raise DashboardUpdateError(409, "this dashboard is already running the image's own code")
    target = str(to_version or current.get("previous") or "").strip()
    if target:
        target = _safe_version(target)
        if not (version_dir(settings, target) / "manifest.json").is_file():
            raise DashboardUpdateError(
                404, f"there is no applied code tree for {target} on this dashboard")
    # REL-10 (resilience sweep 2026-08-28): the code goes back, the DATABASE
    # does not. Forward-only additive migrations survive that; a rename or a
    # NOT NULL column does not, and until now nothing checked and the UI said
    # nothing. Refused rather than warned, because the safe-looking choice (no
    # restore_db, so today's reports are kept) is exactly the one that breaks
    # -- and the refusal names the backup to restore alongside it.
    schema = schema_rollback_check(settings, target)
    if not schema["safe"] and not restore_db and not acknowledge_schema:
        known = f"schema v{schema['target']}"
        needs = (f"restore backup {schema['backup']} alongside it"
                 if schema["backup"] else
                 "restore a database backup taken before that update alongside it")
        raise DashboardUpdateError(
            409,
            f"rolling back to {target or 'the image'} means running {known} against a "
            f"database that is on schema v{schema['live']}. Additive columns survive "
            f"that; a renamed or NOT NULL one does not. To go back safely, {needs} - "
            "which also takes today's reports back to that moment. Send restore_db with "
            "the backup name, or acknowledge_schema to go back with the database as it "
            "is.")
    restored = restore_backup(settings, restore_db) if restore_db else {}
    _write_json(current_json_path(settings), {
        "version": target,
        "previous": "",
        "applied_at": db.utcnow_iso(),
        "applied_by": started_by,
        "rolled_back_from": str(current.get("version") or ""),
    })
    boot_attempts_path(settings).unlink(missing_ok=True)
    result = {"version": target or "image", "restored": restored,
              "rolled_back_from": current.get("version"), "schema": schema}
    _set_state(settings, step="restarting", in_progress=True, version=target,
               message="rolling back", last_applied=result, error="")
    request_restart(settings)
    return result


# -------------------------------------------------------------- the async half

_APPLY_LOCK = threading.Lock()


def start_apply(settings, app_state, *, version: str, force: bool, started_by: str) -> dict[str, Any]:
    """Run preflight synchronously (so a refusal is an HTTP status the admin
    sees immediately) and the rest on a worker thread (so a two-minute
    download is not a two-minute request). The UI polls status().

    The lock plus the in-progress flag written INSIDE it is what makes two
    admins clicking at the same moment one update and one 409: sync routes run
    in a threadpool, so "check then write" without it is a race with a very
    expensive prize (two processes extracting into the same directory)."""
    with _APPLY_LOCK:
        record = preflight(settings, app_state, version=version, force=force)
        _set_state(settings, step="starting", in_progress=True, version=version,
                   error="", message="queued", started_at=db.utcnow_iso(),
                   started_by=started_by, finished_at="")

    def _run() -> None:
        try:
            apply(settings, app_state, version=version, force=force,
                  started_by=started_by, record=record)
        except DashboardUpdateError as exc:
            _fail_state(settings, exc.detail)
        except Exception as exc:                                      # noqa: BLE001
            log.exception("dashboard code update crashed")
            _fail_state(settings, f"unexpected failure: {type(exc).__name__}: {exc}")

    thread = threading.Thread(target=_run, name="dashboard-code-update", daemon=True)
    thread.start()
    return {"started": True, "version": version}


# --------------------------------------------------------------------- status

def status(settings, app_state) -> dict[str, Any]:
    """Everything the Dashboard section of the Packages page renders, and the
    body of GET /api/v1/admin/dashboard-update."""
    running_rid = image_runtime_id()
    current = _read_json(current_json_path(settings))
    records = release_feed.dashboard_records(release_feed.verified_records(app_state))
    code_updates: list[dict[str, Any]] = []
    runtime_updates: list[dict[str, Any]] = []
    rollback_candidates: list[dict[str, Any]] = []
    running = version_tuple(VERSION)
    for record in records:
        version = str(record.get("version") or "")
        if not version or version == VERSION:
            continue
        if not newer_than_image(version):
            # Not an update from here: the image already carries that version
            # or better, and it wins at boot. Left out of BOTH lists rather
            # than shown as unavailable -- there is nothing for an admin to do
            # about it, and a row nobody can act on is noise.
            continue
        entry = {
            "version": version,
            "size_bytes": int(record.get("size_bytes") or 0),
            "published_at": str(record.get("published_at") or ""),
            "notes": str(record.get("notes") or ""),
            "runtime_id": str(record.get("runtime_id") or ""),
        }
        # Newer than the image but OLDER than what is running is not an
        # update either: with 0.6.3 live, 0.6.2 sat in code_updates beside
        # 0.6.4 (2026-08-18) and a caller that took the first entry tried to
        # go backwards. Kept in its own list -- it IS a legitimate rollback
        # target -- so the page can offer it as such and never as an update.
        if running and version_tuple(version) <= running:
            rollback_candidates.append(entry)
            continue
        if str(record.get("runtime_id") or "") == running_rid and running_rid:
            code_updates.append(entry)
        else:
            runtime_updates.append(entry)
    code_updates.sort(key=lambda e: version_tuple(e["version"]), reverse=True)
    runtime_updates.sort(key=lambda e: version_tuple(e["version"]), reverse=True)
    rollback_candidates.sort(key=lambda e: version_tuple(e["version"]), reverse=True)
    state = read_state(settings)
    return {
        "image_mode": image_mode(),
        "running": VERSION,
        "image": image_version(),
        "source": running_source(settings),
        "runtime_id": running_rid,
        "current": {
            "version": str(current.get("version") or ""),
            "previous": str(current.get("previous") or ""),
            "applied_at": str(current.get("applied_at") or ""),
            "reverted_reason": str(current.get("reverted_reason") or ""),
        },
        "code_updates": code_updates,
        "rollback_candidates": rollback_candidates,
        "runtime_updates": runtime_updates,
        "nas_hint": nas_update_hint(settings),
        "in_progress": bool(state.get("in_progress")),
        "step": str(state.get("step") or "idle"),
        "message": str(state.get("message") or ""),
        "last_error": str(state.get("error") or ""),
        "backups": list_backups(settings),
        "boot_attempts": int(_read_json(boot_attempts_path(settings)).get("attempts") or 0),
        # REL-5: the volume this dashboard's database lives on. On the page an
        # admin already visits to publish 40 MB packages onto it.
        "data": data_space(settings),
        # REL-10: what a rollback would mean for the database, worked out here
        # so the page can say it BEFORE the button is pressed rather than
        # answering 409 after.
        "schema": schema_rollback_check(settings, str(current.get("previous") or "")),
    }


# REL-11 (resilience sweep 2026-08-28): a feed that has been unreachable for
# weeks was visible on exactly one admin page. A site that quietly stops
# receiving fixes is indistinguishable from one where no fixes were published,
# and the customer's outbound DNS filter (or a renamed release tag) is not
# something anybody goes looking for.
FEED_STALE_DAYS = 7


def _age_days(stamp: str, now: str = "") -> float | None:
    if not stamp:
        return None
    try:
        then = db.parse_iso(stamp)
        return max(0.0, (db.parse_iso(now or db.utcnow_iso()) - then).total_seconds() / 86400.0)
    except (ValueError, TypeError):
        return None


def feed_health(conn, settings, app_state) -> dict[str, Any]:
    """`feed` for /api/v1/health: when the vendor channel was last read, how
    long ago that is, why it failed and how many records it carried.

    An unconfigured feed answers `configured: False` and nothing else -- a
    site that was never pointed at a channel is not a site whose updates are
    broken, and saying otherwise would train an operator to ignore this."""
    configured = bool(getattr(settings, "release_feed_url", ""))
    if not configured:
        return {"configured": False, "last_checked_at": None, "age_days": None,
                "last_error": None, "records": 0, "stale": False}
    state = db.get_feed_state(conn)
    checked = str(state.get("last_checked_at") or "")
    age = _age_days(checked)
    try:
        records = len(release_feed.verified_records(app_state) or [])
    except Exception:                                                 # noqa: BLE001
        records = 0
    return {
        "configured": True,
        "last_checked_at": checked or None,
        "age_days": None if age is None else round(age, 2),
        "last_error": str(state.get("last_error") or "") or None,
        "records": records,
        # Never checked at all is STALE, not fine: "could not check" must not
        # render as a reassurance (the sweep's rule).
        "stale": age is None or age > FEED_STALE_DAYS,
    }


def record_feed_runtime_mismatch(conn, settings, app_state) -> dict[str, Any] | None:
    """Persist "every dashboard build on offer needs a new container image".

    The condition REL-11 asks for a distinct banner about: the vendor bumped
    the dependency lock, so every bundle's runtime_id diverges from this
    customer's image and every update lands in `runtime_updates` behind a NAS
    click nobody makes. Written into `meta` because the fleet page's builder
    has a connection and no access to the in-memory feed cache."""
    view = status(settings, app_state)
    if view.get("runtime_updates") and not view.get("code_updates"):
        payload = {
            "at": db.utcnow_iso(),
            "versions": [str(u.get("version") or "") for u in view["runtime_updates"]][:5],
            "nas_hint": view.get("nas_hint") or "",
        }
    else:
        payload = None
    db.set_feed_runtime_mismatch(conn, payload)
    return payload


def nas_update_hint(settings) -> str:
    """The exact click that applies a RUNTIME update, per platform. Same three
    answers the feed's image line already gives (docs/RELEASE_FEED.md section
    4) -- one wording, two callers."""
    kind = str(getattr(settings, "nas_kind", "") or "").lower()
    if kind == "synology":
        return "Container Manager > Project ccsync > Build"
    if kind == "truenas":
        return "Apps > ccsync > Update"
    return "your NAS's own app or container manager's Update action"


# --------------------------------------------------------------------- JSON API

router = APIRouter(prefix="/api/v1/admin/dashboard-update")


class ApplyIn(BaseModel):
    version: str
    force: bool = False


class RollbackIn(BaseModel):
    to_version: str = ""
    restore_db: str = ""
    # REL-10: "yes, I know the database stays where it is". Its own field
    # rather than `force`, because it acknowledges ONE named consequence.
    acknowledge_schema: bool = False


@router.get("")
def api_dashboard_update(request: FastAPIRequest, conn=Depends(get_conn)) -> dict[str, Any]:
    _require_admin(request)
    return status(request.app.state.settings, request.app.state)


@router.get("/status")
def api_dashboard_update_status(request: FastAPIRequest, conn=Depends(get_conn)) -> dict[str, Any]:
    """The same body as GET "" -- a separate path because the progress panel
    polls it once a second while an update runs, and a URL that says what it
    is for is easier to find in a log than a second use of the parent."""
    _require_admin(request)
    return status(request.app.state.settings, request.app.state)


@router.post("/apply")
def api_dashboard_update_apply(
    payload: ApplyIn, request: FastAPIRequest, conn=Depends(get_conn)
) -> dict[str, Any]:
    user = _require_admin(request)
    settings = request.app.state.settings
    try:
        result = start_apply(settings, request.app.state, version=payload.version.strip(),
                             force=bool(payload.force), started_by=user)
    except DashboardUpdateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return {"ok": True, **result, "status": status(settings, request.app.state)}


@router.post("/rollback")
def api_dashboard_update_rollback(
    payload: RollbackIn, request: FastAPIRequest, conn=Depends(get_conn)
) -> dict[str, Any]:
    user = _require_admin(request)
    settings = request.app.state.settings
    try:
        result = rollback(settings, to_version=payload.to_version.strip(),
                          restore_db=payload.restore_db.strip(),
                          acknowledge_schema=bool(payload.acknowledge_schema),
                          started_by=user)
    except DashboardUpdateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return {"ok": True, **result}
