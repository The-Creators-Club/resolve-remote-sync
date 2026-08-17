"""The SetupEngine: a resumable task registry behind the wizard (`/setup`)
and the admin Settings page (ZERO_TOUCH_PLAN.md WP D / §3.2, §3.5,
2026-08-17).

Each `Task` is `(id, title, description, check, run, optional)`: `check()`
looks at the world and reports a `TaskState` without changing anything;
`run()` does the work (idempotent -- re-running an already-`ok` task must be
harmless) and reports the state it left things in. Every state is persisted
in `setup_tasks` (`db.py` migration v18) keyed by task id, so a container
restart mid-wizard (routine on an appliance -- `docker restart`, a host
reboot) resumes exactly where it left off instead of replaying "Welcome".

`TASKS` is the ONE registry every task lives in, in wizard order -- this
module owns the six real ones this work package delivers (`eula`, `admin`,
`studio`, `storage`, `secrets`, `syncthing`) plus a `done` marker, and
registers five PLACEHOLDERS (`tailnet`, `nas_connect`, `snapshots`,
`editors`, `software`) so the wizard's page shape is complete today and the
work packages that own them (B, C, F, G — see `ZERO_TOUCH_PLAN.md` §4) only
have to replace a placeholder entry, never touch the page.

Two of the six real tasks reach into work this repo does not have yet in
this worktree:

* `admin` calls `probe_admin_status()`, which tries to reach agent C's
  identity module (`GET /api/v1/setup/status` — SPEC "Depends on: A, B" for
  WP C). Until that module exists here, the probe returns `None` and the
  task reports `todo` / "awaiting identity module" — never a guess, and
  never a fabricated `ok`.
* `syncthing`'s "bundled, always on" framing (§3.1) is WP B/A's job; this
  worktree still pings whatever `SYNCTHING_GUI_URL` is configured (which is
  every deployment today), so the task is meaningful immediately and stays
  meaningful once the sidecar lands.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Iterable

log = logging.getLogger("ccsync.dashboard.setup_engine")

VALID_STATUSES = ("todo", "ok", "warn", "fail", "skipped")

PROBE_FILENAME = ".ccsync-setup-probe"

# The EULA text this task's check() looks for its version marker in. Same
# marker convention as the companion/onboarding wizard's own EULA gate
# (CLAUDE.md: "bumping it pushes every editor in every fleet back through
# the wizard") -- reusing the ONE file rather than growing a dashboard copy.
# parents[3] from this file (ccsync_dashboard/setup_engine.py) is the repo
# root: [0]=ccsync_dashboard, [1]=src, [2]=dashboard, [3]=repo root -- same
# arithmetic app.py's STATIC_DIR and ui.py's TEMPLATES_DIR already use one
# level short of.
EULA_PATH = Path(__file__).resolve().parents[3] / "docs" / "legal" / "EULA.md"


def now_iso() -> str:
    from . import db

    return db.utcnow_iso()


@dataclasses.dataclass
class TaskState:
    status: str
    detail: str = ""
    at: str | None = None

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"bad TaskState.status {self.status!r}")

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "detail": self.detail, "at": self.at}


class SetupContext:
    """What a task's check()/run() gets: a DB connection (caller commits --
    same convention as every other write helper in this codebase), the live
    Settings, and the FastAPI app (for probing another module's routes/state
    without importing it at module load time, which would make an absent
    work package an import error instead of a graceful "not implemented")."""

    def __init__(self, conn: sqlite3.Connection, settings: Any, app: Any = None) -> None:
        self.conn = conn
        self.settings = settings
        self.app = app


@dataclasses.dataclass
class Task:
    id: str
    title: str
    description: str
    check: Callable[[SetupContext], TaskState]
    run: Callable[[SetupContext], TaskState] | None = None
    optional: bool = False


TASKS: list[Task] = []
_BY_ID: dict[str, Task] = {}


def register(task: Task) -> Task:
    """Appended to, never overwritten -- WP B/C/F/G replace a PLACEHOLDER
    entry's `check`/`run` in their own module by calling this again with the
    same id (see `replace` below), so the page's task ORDER never depends on
    import order."""
    if task.id in _BY_ID:
        raise ValueError(f"duplicate setup task id {task.id!r}")
    TASKS.append(task)
    _BY_ID[task.id] = task
    return task


def replace(task: Task) -> Task:
    """Swap a placeholder (or any task) for a real implementation, keeping
    its position in TASKS -- what a later work package calls instead of
    `register` once it lands."""
    existing = _BY_ID.get(task.id)
    if existing is None:
        return register(task)
    idx = TASKS.index(existing)
    TASKS[idx] = task
    _BY_ID[task.id] = task
    return task


def get(task_id: str) -> Task | None:
    return _BY_ID.get(task_id)


# --------------------------------------------------------------- persistence

def load_state(conn: sqlite3.Connection, task_id: str) -> TaskState:
    row = conn.execute(
        "SELECT status, detail, at, skipped FROM setup_tasks WHERE id=?", (task_id,)
    ).fetchone()
    if row is None:
        return TaskState(status="todo", detail="", at=None)
    status = "skipped" if row["skipped"] else (row["status"] or "todo")
    return TaskState(status=status, detail=row["detail"] or "", at=row["at"])


def save_state(conn: sqlite3.Connection, task_id: str, state: TaskState) -> None:
    skipped = 1 if state.status == "skipped" else 0
    conn.execute(
        "INSERT INTO setup_tasks (id, status, detail, at, skipped) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET status=excluded.status, detail=excluded.detail, "
        "at=excluded.at, skipped=excluded.skipped",
        (task_id, state.status, state.detail, state.at, skipped),
    )


def list_states(conn: sqlite3.Connection) -> dict[str, TaskState]:
    rows = {
        row["id"]: row
        for row in conn.execute("SELECT id, status, detail, at, skipped FROM setup_tasks")
    }
    out: dict[str, TaskState] = {}
    for task in TASKS:
        row = rows.get(task.id)
        if row is None:
            out[task.id] = TaskState(status="todo", detail="", at=None)
        else:
            status = "skipped" if row["skipped"] else (row["status"] or "todo")
            out[task.id] = TaskState(status=status, detail=row["detail"] or "", at=row["at"])
    return out


def outstanding_required(conn: sqlite3.Connection) -> list[str]:
    """Task ids that are NOT optional and NOT 'ok' -- what gates the wizard
    landing page (ui.py) and the "Setup" nav badge."""
    states = list_states(conn)
    return [t.id for t in TASKS if not t.optional and states[t.id].status != "ok"]


# One lock per task id, so a double-click on [ DO IT ] cannot run the same
# task's `run()` twice concurrently (e.g. two Syncthing pings racing to write
# nas_syncthing_id) -- "Runs happen ... one at a time per task id" (the work
# package). A single global lock would serialise unrelated tasks (the storage
# probe blocking the EULA accept) for no reason.
_locks_guard = threading.Lock()
_task_locks: dict[str, threading.Lock] = {}


def _lock_for(task_id: str) -> threading.Lock:
    with _locks_guard:
        lock = _task_locks.get(task_id)
        if lock is None:
            lock = threading.Lock()
            _task_locks[task_id] = lock
        return lock


def run_check(ctx: SetupContext, task_id: str) -> TaskState:
    task = get(task_id)
    if task is None:
        raise KeyError(task_id)
    with _lock_for(task_id):
        try:
            state = task.check(ctx)
        except Exception as exc:  # noqa: BLE001 - a task bug must not 500 the page
            log.exception("setup task %r check() raised", task_id)
            state = TaskState(status="fail", detail=f"internal error: {exc}", at=now_iso())
        if state.at is None:
            state = TaskState(status=state.status, detail=state.detail, at=now_iso())
        save_state(ctx.conn, task_id, state)
        ctx.conn.commit()
        return state


def run_do_it(ctx: SetupContext, task_id: str) -> TaskState:
    task = get(task_id)
    if task is None:
        raise KeyError(task_id)
    if task.run is None:
        # No action to take -- Check is the whole story for this task
        # (e.g. `done`). Callers (setup_routes.py) turn this into a 400.
        raise NotImplementedError(f"setup task {task_id!r} has no run() action")
    with _lock_for(task_id):
        try:
            state = task.run(ctx)
        except Exception as exc:  # noqa: BLE001
            log.exception("setup task %r run() raised", task_id)
            state = TaskState(status="fail", detail=f"internal error: {exc}", at=now_iso())
        if state.at is None:
            state = TaskState(status=state.status, detail=state.detail, at=now_iso())
        save_state(ctx.conn, task_id, state)
        ctx.conn.commit()
        return state


def run_skip(ctx: SetupContext, task_id: str) -> TaskState:
    task = get(task_id)
    if task is None:
        raise KeyError(task_id)
    if not task.optional:
        raise ValueError(f"setup task {task_id!r} is required and cannot be skipped")
    with _lock_for(task_id):
        state = TaskState(status="skipped", detail="skipped by admin", at=now_iso())
        save_state(ctx.conn, task_id, state)
        ctx.conn.commit()
        return state


# ------------------------------------------------------------------- eula

def eula_marker_version(text: str) -> str | None:
    import re

    match = re.search(r"<!--\s*EULA-VERSION:\s*([^\s>]+)\s*-->", text)
    return match.group(1) if match else None


def _check_eula(ctx: SetupContext) -> TaskState:
    if not EULA_PATH.is_file():
        # Not every checkout carries docs/legal (a bare dashboard image
        # ships templates + static, not the whole repo's docs/ tree in every
        # build today) -- treat as accepted-not-required rather than
        # blocking the wizard on a file that may not exist at runtime.
        return TaskState(status="ok", detail="no EULA shipped in this build")
    try:
        text = EULA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        return TaskState(status="fail", detail=f"could not read EULA: {exc}")
    version = eula_marker_version(text) or "unversioned"
    accepted = ctx.conn.execute(
        "SELECT detail FROM setup_tasks WHERE id='eula' AND status='ok'"
    ).fetchone()
    if accepted is not None and accepted["detail"] == f"accepted v{version}":
        return TaskState(status="ok", detail=f"accepted v{version}")
    return TaskState(status="todo", detail=f"awaiting acceptance of v{version}")


def _accept_eula(ctx: SetupContext) -> TaskState:
    """Called by POST /api/v1/setup/eula, not the generic [ DO IT ] button
    (accepting requires a checkbox the wizard's own form renders) -- but
    routed through run_do_it/run() too so the state machine has one writer."""
    if not EULA_PATH.is_file():
        return TaskState(status="ok", detail="no EULA shipped in this build")
    try:
        text = EULA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        return TaskState(status="fail", detail=f"could not read EULA: {exc}")
    version = eula_marker_version(text) or "unversioned"
    return TaskState(status="ok", detail=f"accepted v{version}")


register(Task(
    id="eula", title="Welcome, EULA",
    description="Read and accept the license agreement.",
    check=_check_eula, run=_accept_eula,
))


# ------------------------------------------------------------------- admin

def probe_admin_status(ctx: SetupContext) -> dict[str, Any] | None:
    """Whatever agent C's identity module reports about local accounts, or
    None if that module is not present in this build.

    A monkeypatchable seam for tests: set `ctx.app.state.setup_status_probe`
    to a callable(ctx) -> dict | None and it is tried FIRST, before the real
    import -- this is how this worktree's own tests exercise both the
    "module absent" and "module present" shapes without WP C's code
    existing.
    """
    probe = getattr(getattr(ctx.app, "state", None), "setup_status_probe", None)
    if probe is not None:
        return probe(ctx)
    try:
        from . import identity  # WP C's not-yet-existing module
    except ImportError:
        return None
    fn = getattr(identity, "setup_status", None)
    if fn is None:
        return None
    return fn(ctx.conn)


def _check_admin(ctx: SetupContext) -> TaskState:
    status = probe_admin_status(ctx)
    if status is None:
        return TaskState(status="todo", detail="awaiting identity module")
    if status.get("users_exist"):
        return TaskState(status="ok", detail="an admin account exists")
    return TaskState(status="todo", detail="no admin account yet")


register(Task(
    id="admin", title="Create your admin account",
    description="A local account for you -- no NAS credential involved.",
    check=_check_admin, run=None,   # account creation is WP C's route, not this task's
))


# ------------------------------------------------------------------ studio

_STUDIO_REQUIRED_KEYS = ("org_name", "tree_name", "canonical_prefix", "template_folders")


def _check_studio(ctx: SetupContext) -> TaskState:
    from . import site_store

    manifest = site_store.resolved_manifest(ctx.conn, ctx.settings)
    missing = [k for k in _STUDIO_REQUIRED_KEYS if not manifest.get(k)]
    if missing:
        return TaskState(status="todo", detail=f"not set: {', '.join(missing)}")
    return TaskState(status="ok", detail=f"{manifest['org_name']} / {manifest['tree_name']}")


register(Task(
    id="studio", title="Your studio",
    description="Name, tree name, drive letter and the project template.",
    check=_check_studio, run=None,   # written by PUT /api/v1/admin/site, not a generic run()
))


# ----------------------------------------------------------------- storage

def _human_bytes(n: float | None) -> str:
    """Tiny local copy of ui.human_bytes -- not imported from ui.py to avoid
    a setup_engine -> ui -> (eventually) setup_routes import cycle; this is
    a one-line format, not logic worth sharing."""
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "?"


def _check_storage(ctx: SetupContext) -> TaskState:
    """Evidence is the SHARED ASSET FOLDERS `_run_storage` creates, not the
    probe file -- the probe is written, read back and deleted in one motion
    (leaving litter on a customer's tree defeats the point of a probe), so
    checking for ITS existence would report 'todo' immediately after a
    successful 'Do it' ran. The asset folders are the durable evidence a
    previous run succeeded."""
    projects_dir = str(getattr(ctx.settings, "projects_dir", "") or "")
    if not projects_dir or not Path(projects_dir).is_dir():
        return TaskState(status="todo", detail="DASH_PROJECTS_DIR is not mounted")
    from . import provision

    tree_root = Path(projects_dir).parent
    missing = [rel for _fid, rel, _label in provision.SHARED_ASSET_FOLDERS
               if not (tree_root / rel).is_dir()]
    if missing:
        return TaskState(status="todo", detail="not yet probed -- click Do it")
    try:
        free = shutil.disk_usage(projects_dir).free
        detail = f"writable; {_human_bytes(free)} free"
    except OSError:
        detail = "writable"
    return TaskState(status="ok", detail=detail)


def _run_storage(ctx: SetupContext) -> TaskState:
    from . import provision

    projects_dir = str(getattr(ctx.settings, "projects_dir", "") or "")
    if not projects_dir or not Path(projects_dir).is_dir():
        return TaskState(
            status="fail",
            detail="DASH_PROJECTS_DIR is not mounted -- add the volume and redeploy",
        )
    root = Path(projects_dir)
    probe = root / PROBE_FILENAME
    try:
        probe.write_text("ccsync setup probe -- safe to delete\n", encoding="utf-8")
        readback = probe.read_text(encoding="utf-8")
        probe.unlink()
        if "ccsync setup probe" not in readback:
            return TaskState(status="fail", detail="probe file read back different content")
    except OSError as exc:
        return TaskState(status="fail", detail=f"could not write/read/delete a probe file: {exc}")
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        free = None
    # Assets/... are a SIBLING of the Projects mount at the tree root (see
    # provision.py's LUTS_REL/STILLS_REL = "Assets/Luts" etc., always
    # relative to the tree root, never to Projects/). mkdir(exist_ok=True),
    # no chown -- same posture as api.create_tree_project, which never
    # chowns either (the container's own uid is what should own these, and
    # ownership repair is a SEPARATE root-in-container helper per
    # ZERO_TOUCH_PLAN.md §3.2, not this task).
    created = []
    for _fid, rel, _label in provision.SHARED_ASSET_FOLDERS:
        target = root.parent / rel
        try:
            target.mkdir(parents=True, exist_ok=True)
            created.append(rel)
        except OSError as exc:
            log.warning("setup: could not create shared asset folder %s: %s", target, exc)
    free_str = _human_bytes(free)
    return TaskState(
        status="ok",
        detail=f"writable; {free_str} free; created {len(created)} shared asset folder(s)",
    )


register(Task(
    id="storage", title="Storage check",
    description="Confirm the tree is writable and lay down the shared asset folders.",
    check=_check_storage, run=_run_storage,
))


# ----------------------------------------------------------------- secrets

def _check_secrets(ctx: SetupContext) -> TaskState:
    from . import secrets_boot

    data_dir = Path(str(getattr(ctx.settings, "db_path", "") or "/data/dashboard.db")).parent
    secrets_dir = data_dir / "secrets"
    missing = []
    for name in secrets_boot.SECRET_ENV_VARS:
        if os.environ.get(name, "").strip():
            continue
        if (secrets_dir / name.lower()).is_file():
            continue
        missing.append(name)
    if missing:
        return TaskState(status="todo", detail=f"not yet generated: {', '.join(missing)}")
    return TaskState(status="ok", detail="all five secrets present")


def _run_secrets(ctx: SetupContext) -> TaskState:
    """Backfills any secret this process is still missing on disk (the boot
    bootstrap already tried once in create_app; a data volume mounted
    read-only until now, or a first deploy that skipped it, gets a second
    chance here). A secret GENERATED just now by this call does not take
    effect in the RUNNING process -- Settings is a frozen dataclass built at
    boot -- so the detail says so rather than claiming a live fix.

    `data_dir` is passed explicitly, from `ctx.settings.db_path` -- exactly
    what `_check_secrets` above already derives it from -- rather than
    letting `ensure_secrets` fall back to `os.environ["DASH_DB_PATH"]`,
    which need not agree with it (measured: it does not, for any
    hand-built `Settings(db_path=...)`, which is every test in this suite
    and any embedder that does not set that env var).

    Also passes a SNAPSHOT of `os.environ` rather than the live mapping:
    generating a value here does not do anything useful to the RUNNING
    process anyway (see above -- Settings is already frozen), so there is
    no reason to mutate the real environment of a long-lived server process
    from a request handler; only the file on disk needs to exist by the
    next boot."""
    from . import secrets_boot

    data_dir = Path(str(getattr(ctx.settings, "db_path", "") or "/data/dashboard.db")).parent
    env_snapshot = {name: os.environ.get(name, "") for name in secrets_boot.SECRET_ENV_VARS}
    provenance = secrets_boot.ensure_secrets(env_snapshot, data_dir=data_dir)
    generated = [n for n, source in provenance.items() if source == "generated"]
    state = _check_secrets(ctx)
    if generated:
        state = TaskState(
            status=state.status,
            detail=state.detail + f"; generated {len(generated)} just now -- "
                                   "restart the container to load them",
        )
    return state


register(Task(
    id="secrets", title="Secrets",
    description="Session, report, ingest and sidecar credentials.",
    check=_check_secrets, run=_run_secrets,
))


# --------------------------------------------------------------- syncthing

def _check_syncthing(ctx: SetupContext) -> TaskState:
    if not str(getattr(ctx.settings, "syncthing_url", "") or ""):
        return TaskState(status="todo", detail="SYNCTHING_GUI_URL not configured")
    from .syncthing_client import SyncthingClient, SyncthingError

    try:
        client = SyncthingClient.from_settings(ctx.settings)
        client.timeout = min(client.timeout, 5.0)
        my_id = str(client.system_status().get("myID", "") or "")
    except SyncthingError as exc:
        return TaskState(status="fail", detail=f"unreachable: {exc}")
    if not my_id:
        return TaskState(status="warn", detail="reachable but reported no device id")
    return TaskState(status="ok", detail=f"device id {my_id[:7]}...")


def _run_syncthing(ctx: SetupContext) -> TaskState:
    if not str(getattr(ctx.settings, "syncthing_url", "") or ""):
        return TaskState(status="todo", detail="SYNCTHING_GUI_URL not configured")
    from . import site_store
    from .syncthing_client import SyncthingClient, SyncthingError

    try:
        client = SyncthingClient.from_settings(ctx.settings)
        client.timeout = min(client.timeout, 5.0)
        my_id = str(client.system_status().get("myID", "") or "")
    except SyncthingError as exc:
        return TaskState(status="fail", detail=f"unreachable: {exc}")
    if not my_id:
        return TaskState(status="warn", detail="reachable but reported no device id")
    existing = site_store.get_all(ctx.conn).get("nas_syncthing_id", "")
    if not existing:
        # Only fills a BLANK row -- never overwrites a value an admin (or a
        # migration import) already set, same "DB is authoritative once
        # written" rule site_store.py's module docstring states for every
        # other field.
        site_store.set_many(ctx.conn, {"nas_syncthing_id": my_id}, updated_by="setup:syncthing")
    return TaskState(status="ok", detail=f"device id {my_id[:7]}...")


register(Task(
    id="syncthing", title="Sync engine",
    description="Confirm the bundled Syncthing is reachable.",
    check=_check_syncthing, run=_run_syncthing,
))


# ---------------------------------------------------------------------- done

def _check_done(ctx: SetupContext) -> TaskState:
    outstanding = [t for t in outstanding_required(ctx.conn) if t != "done"]
    if outstanding:
        return TaskState(status="todo", detail=f"waiting on: {', '.join(outstanding)}")
    return TaskState(status="ok", detail="setup complete")


register(Task(
    id="done", title="Done",
    description="Everything required is configured.",
    check=_check_done, run=None,
))


# ---------------------------------------------------------- WP B/C/F/G stubs
#
# Registered now so /setup's page shape (the linear checklist, §3.5) is
# complete today; each work package REPLACES its entry (setup_engine.replace)
# instead of editing this file, once it lands. optional=True: none of these
# gate the wizard finishing, matching the plan's "connect to your NAS is
# optional" / "invites/software are day-2, not day-1" framing (§3.2, §5).

def _not_implemented(_ctx: SetupContext) -> TaskState:
    return TaskState(status="todo", detail="not implemented in this build")


for _id, _title, _description in (
    ("tailnet", "Connect to your tailnet", "Sign this node into your Tailscale network."),
    ("nas_connect", "Connect to your NAS (optional)", "One-time admin credential for snapshots and SMB users."),
    ("snapshots", "Protect your data", "Schedule NAS snapshots or export a /data backup."),
    ("editors", "Editors", "Invite your first editor."),
    ("software", "Software for editors", "Publish the current companion build."),
):
    register(Task(id=_id, title=_title, description=_description,
                  check=_not_implemented, run=None, optional=True))
del _id, _title, _description
