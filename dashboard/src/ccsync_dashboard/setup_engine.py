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

`TASKS` is the ONE registry every task lives in, in wizard order: `eula`,
`admin`, `studio`, `storage`, `secrets`, `syncthing`, `done`, then the five
optional ones (`tailnet`, `nas_connect`, `snapshots`, `editors`,
`software`). The last five were PLACEHOLDERS reporting "not implemented in
this build" until 2026-08-18, on the theory that WP B/C/F/G would each
`replace()` their own entry from their own module; a shipped product cannot
say that to a customer, and none of those modules exists, so they are real
checks in this file now. `replace()` remains for the day one of them wants
its entry back.

Every check answers from what this container can see WITHOUT reaching out:
the databases, the settings, the tree mount, a unix socket, and (only where
a credential is already configured) one 3-second call to the NAS or the
Syncthing already in the stack. A check catches everything and reports a
`todo`/`warn`/`fail` with one line naming the next action -- an admin
reading this page must never see a traceback, and must never see a green
tick this build cannot actually stand behind.

`admin` is the one task whose answer depends on WHO signs in here
(`DASH_AUTH_METHOD`): see `_check_admin`.
"""
from __future__ import annotations

import dataclasses
import ipaddress
import logging
import os
import shutil
import sqlite3
import threading
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

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
    # What the wizard writes on the run() button. "DO IT" is right for a task
    # that CHANGES something (storage probe, secret generation); a task whose
    # action is a read against someone else's service should say what it is
    # about to do -- `software` polls the vendor feed, and "DO IT" next to
    # "Software for editors" reads like "publish something now"
    # (2026-08-18).
    run_label: str = "DO IT"


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


def _auth_method(ctx: SetupContext) -> str:
    return str(getattr(ctx.settings, "auth_method", "") or "smb").strip().lower()


def _configured_admins(ctx: SetupContext) -> list[str]:
    """Who can administer this dashboard, from whichever source decides it.

    Exactly `auth.is_admin`'s two sources, read in its order: DASH_ADMIN_USERS
    is the break-glass list on EVERY auth method, and under
    DASH_AUTH_METHOD=local a `role='admin'` row counts as well."""
    names = {str(u).strip().lower() for u in getattr(ctx.settings, "admin_users", ()) or ()}
    names.discard("")
    if _auth_method(ctx) == "local":
        from . import local_users

        try:
            names.update(
                u["username"] for u in local_users.list_users(ctx.conn)
                if u.get("role") == "admin" and not u.get("disabled")
            )
        except sqlite3.Error:       # a pre-v17 database has no users table
            pass
    return sorted(names)


def _check_admin(ctx: SetupContext) -> TaskState:
    """Whether SOMEBODY can administer this dashboard -- which is not the same
    question as "does a LOCAL account exist".

    Until 2026-08-18 it only ever asked the local-accounts probe, so on a site
    that authenticates admins against the NAS (`DASH_AUTH_METHOD=smb`, every
    deployment in the field) it reported "awaiting identity module" forever
    and held the whole `Done` step hostage behind a step that site will never
    take. The wizard's step 2 exists to get a first admin onto a dashboard
    with no other way in; where a NAS or an IdP plus DASH_ADMIN_USERS already
    answer that, the step is satisfied, not pending.

    Order: the identity probe first (it is the seam WP C's module plugs into
    and the one this suite drives), then whatever `DASH_AUTH_METHOD` says.
    """
    status = probe_admin_status(ctx)
    if status is not None:
        return _admin_state_from_probe(ctx, status)

    method = _auth_method(ctx)
    admins = _configured_admins(ctx)
    if method == "local":
        # Only the accounts table can answer here. A DASH_ADMIN_USERS entry is
        # NOT enough: under local login `auth.verify_credentials` needs a row
        # with a password hash, so an ok on the strength of the env var alone
        # would report a dashboard nobody can sign in to as set up.
        #
        # This fallback deliberately stays OUT of probe_admin_status, which
        # setup_routes.first_run_open also reads: teaching that one about
        # local_users would swing the anonymous first-run window open on
        # deployments where it is currently, correctly, shut.
        from . import local_users

        try:
            exists = local_users.any_users_exist(ctx.conn)
        except sqlite3.Error:
            return TaskState(status="todo", detail="awaiting identity module")
        return _admin_state_from_probe(ctx, {"users_exist": exists})
    if admins:
        kind = str(getattr(ctx.settings, "nas_kind", "") or "truenas").strip().lower()
        source = ("your identity provider (oidc)" if method == "oidc"
                  else f"NAS accounts ({kind})")
        return TaskState(status="ok", detail=f"admins are {source}: {', '.join(admins)}")
    if method == "oidc" and str(getattr(ctx.settings, "oidc_admin_claim", "") or ""):
        return TaskState(
            status="ok",
            detail="admins come from your identity provider's "
                   f"{ctx.settings.oidc_admin_claim} claim",
        )
    return TaskState(
        status="todo",
        detail=f"no admin is configured for {method} login: set DASH_ADMIN_USERS "
               "to the NAS account(s) that may administer this dashboard, then redeploy",
    )


def _admin_state_from_probe(ctx: SetupContext, status: dict[str, Any]) -> TaskState:
    if not status.get("users_exist"):
        return TaskState(status="todo", detail="no admin account yet")
    admins = _configured_admins(ctx)
    detail = f"admin account: {', '.join(admins)}" if admins else "an admin account exists"
    return TaskState(status="ok", detail=detail)


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


def _shared_asset_rels(ctx: SetupContext) -> list[str]:
    """This site's shared asset libraries, DB-first (dash-admin-3,
    2026-08-21). `provision.SHARED_ASSET_FOLDERS` is the import-time env copy
    and stays the fallback; a site that added `Assets/SFX` on Settings gets
    the folder it asked for, not the one the container booted with."""
    from . import site_store

    try:
        return [rel for _fid, rel, _label
                in site_store.shared_asset_folders(ctx.conn, ctx.settings)]
    except sqlite3.Error:                       # a pre-v18 database has no table
        from . import provision

        return [rel for _fid, rel, _label in provision.SHARED_ASSET_FOLDERS]


def _tree_root(ctx: SetupContext) -> Path | None:
    """The TREE ROOT as this container can see it, or None when it cannot.

    dash-admin-1 (2026-08-21): this used to be `Path(projects_dir).parent`,
    unconditionally. Every compose file in the repo mounts ONLY <tree>/Projects
    at /projects (compose.yaml, compose.image.yaml, compose.appliance.yaml),
    and `Path('/projects').parent` is `/` -- so the storage task was creating
    `/Assets/Luts` in the container's own root filesystem, and its check then
    looked for those same folders on the NAS tree, found nothing, and flipped
    the task back to `todo` forever. `DASH_TREE_DIR` is the explicit answer
    (a deployment that mounts the whole tree says so); absent that, the parent
    is believed only when it is not a filesystem root, which is exactly the
    case that was wrong.
    """
    explicit = (os.environ.get("DASH_TREE_DIR") or "").strip()
    if explicit:
        path = Path(explicit)
        return path if path.is_dir() else None
    projects_dir = str(getattr(ctx.settings, "projects_dir", "") or "")
    if not projects_dir:
        return None
    parent = Path(projects_dir).resolve().parent
    if parent == parent.parent:     # "/" (or a bare drive root on Windows)
        return None
    return parent if parent.is_dir() else None


# What the check and the run both say when only Projects/ is mounted. The
# asset libraries still exist on the NAS -- the collector provisions and
# shares them from the Syncthing side (DASH_SYNCTHING_ASSETS_PREFIX, a path on
# the NAS host, not a mount of this container) -- so this is a "not our job
# here", not a failure to report to the admin as one.
_ASSETS_NOT_VISIBLE = ("writable. The shared asset folders live beside Projects "
                       "on the NAS, which this container does not mount")


def _check_storage(ctx: SetupContext) -> TaskState:
    """Evidence is the SHARED ASSET FOLDERS `_run_storage` creates, not the
    probe file -- the probe is written, read back and deleted in one motion
    (leaving litter on a customer's tree defeats the point of a probe), so
    checking for ITS existence would report 'todo' immediately after a
    successful 'Do it' ran. The asset folders are the durable evidence a
    previous run succeeded.

    Where the tree root is not visible from inside this container (the shape
    every compose file in the repo actually deploys -- see `_tree_root`),
    there is no such evidence to look for and the question this task really
    asks is "is the Projects mount writable": dash-admin-1, 2026-08-21.
    """
    projects_dir = str(getattr(ctx.settings, "projects_dir", "") or "")
    if not projects_dir or not Path(projects_dir).is_dir():
        return TaskState(status="todo", detail="DASH_PROJECTS_DIR is not mounted")
    try:
        free = shutil.disk_usage(projects_dir).free
        free_str = f"; {_human_bytes(free)} free"
    except OSError:
        free_str = ""
    tree_root = _tree_root(ctx)
    if tree_root is None:
        if not os.access(projects_dir, os.W_OK):
            return TaskState(status="todo", detail="not yet probed -- click Do it")
        return TaskState(status="ok", detail=f"{_ASSETS_NOT_VISIBLE}{free_str}")
    missing = [rel for rel in _shared_asset_rels(ctx) if not (tree_root / rel).is_dir()]
    if missing:
        return TaskState(status="todo", detail="not yet probed -- click Do it")
    return TaskState(status="ok", detail=f"writable{free_str}")


def _run_storage(ctx: SetupContext) -> TaskState:
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
    free_str = _human_bytes(free)
    tree_root = _tree_root(ctx)
    if tree_root is None:
        # dash-admin-1: creating them under `/` (the container's rootfs) is
        # what this branch used to do. Reporting the probe result honestly and
        # stopping is the whole fix -- the folders are the NAS installer's and
        # the collector's job on this deployment shape.
        return TaskState(status="ok", detail=f"{_ASSETS_NOT_VISIBLE}; {free_str} free")
    created: list[str] = []
    failed: list[str] = []
    for rel in _shared_asset_rels(ctx):
        target = tree_root / rel
        try:
            target.mkdir(parents=True, exist_ok=True)
            created.append(rel)
        except OSError as exc:
            failed.append(rel)
            log.warning("setup: could not create shared asset folder %s: %s", target, exc)
    if failed:
        # warn, not ok (dash-admin-1, 2026-08-21): this used to report ok with
        # "created 0 shared asset folder(s)" and the very next check flipped
        # the chip back to todo with no reason an admin could read.
        return TaskState(
            status="warn",
            detail=f"writable, but could not create {', '.join(failed)} under "
                   f"{tree_root} - check the mount's ownership",
        )
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
        ctx.conn.commit()
        # Every writer of site_settings drops the per-process manifest cache
        # ui._render reads (product-surface-2, 2026-08-21).
        site_store.invalidate(ctx.app)
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


# ------------------------------------------------------------------ tailnet
#
# WP B/C/F/G registered PLACEHOLDERS here until 2026-08-18 ("not implemented
# in this build", optional=True) so /setup's page shape was complete before
# their work packages landed. A shipped product must not say that to a
# customer, so the five are implemented here, in the ONE registry file,
# rather than as five modules with one function each: every one of them is
# the same shape as `storage`/`secrets`/`syncthing` above -- look at the
# world, report, change nothing -- and `replace()` is still there for the day
# WP B owns a real tailscale module and wants this entry back.
#
# They stay optional=True and skippable: none of them gates a working fleet
# (sections 3.2 and 5 -- "connect to your NAS is optional", "invites/software
# are day-2"), and `done` must not wait on a customer's tailnet.

_TAILNET_CGNAT = ipaddress.ip_network("100.64.0.0/10")

# The doc that tells an admin how this dashboard gets a tailnet address:
# INSTALL.md's "Tailscale Serve is the only supported way to publish it with
# TLS" for a NAS deployment, APPLIANCE_INSTALL.md step 4 for the bundled
# sidecar. Named in the detail rather than linked -- these strings land in a
# table cell and in an API response.
_TAILNET_DOC = "docs/INSTALL.md"
_TAILNET_APPLIANCE_DOC = "docs/APPLIANCE_INSTALL.md step 4"

def _one_line(value: Any, limit: int = 160) -> str:
    """Anything an exception or a NAS says, as one line that fits a table
    cell -- a multi-line requests error in a `detail` breaks the checklist's
    layout and tells an admin nothing its first line did not."""
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _is_tailnet_address(host: str) -> bool:
    """A `*.ts.net` MagicDNS name or a 100.64.0.0/10 CGNAT address -- the two
    shapes a tailnet hands out. Anything else (a LAN IP, a public name) means
    editors reach this dashboard some other way."""
    host = str(host or "").strip().lower().rstrip(".")
    if not host:
        return False
    if host.endswith(".ts.net"):
        return True
    try:
        return ipaddress.ip_address(host) in _TAILNET_CGNAT
    except ValueError:
        return False


def _published_dashboard_url(ctx: SetupContext) -> str:
    from . import site_store

    try:
        return str(site_store.resolved_manifest(ctx.conn, ctx.settings).get("dashboard_url") or "")
    except Exception:                                                 # noqa: BLE001
        return str(getattr(ctx.settings, "site_dashboard_url", "") or "")


def _check_tailnet(ctx: SetupContext) -> TaskState:
    """Two sources, in order of authority: the bundled Tailscale node's own
    LocalAPI (it knows whether it is signed in), then the URL this site
    publishes to editors (which is what they actually type).

    Neither is a network probe: the first is a unix socket on this container,
    the second a string comparison. A setup check that dialled out would hang
    the page on exactly the deployments that are not on a tailnet yet."""
    from . import tailscale_local

    try:
        node = tailscale_local.summarise(tailscale_local.status())
    except Exception as exc:                                          # noqa: BLE001
        log.warning("tailnet check: LocalAPI read failed: %s", exc)
        node = None
    if node:
        state = node["backend_state"] or "unknown"
        if state == "Running":
            name = node["dns_name"] or (node["ips"][0] if node["ips"] else "")
            return TaskState(
                status="ok",
                detail=(f"the bundled Tailscale node is signed in as {name}" if name
                        else "the bundled Tailscale node is signed in"),
            )
        if node["auth_url"]:
            return TaskState(
                status="todo",
                detail=f"this node is not signed in yet ({state}): open {node['auth_url']} "
                       "to add it to your tailnet",
            )
        return TaskState(
            status="todo",
            detail=f"the bundled Tailscale node is {state}, with no sign-in link yet: see "
                   f"{_TAILNET_APPLIANCE_DOC}",
        )

    url = _published_dashboard_url(ctx)
    if not url:
        return TaskState(
            status="todo",
            detail="no dashboard URL is published to editors yet: set dashboard_url on the "
                   f"Settings page, or publish this dashboard with Tailscale Serve ({_TAILNET_DOC})",
        )
    host = urlsplit(url).hostname or url
    if _is_tailnet_address(host):
        return TaskState(status="ok",
                         detail=f"editors reach this dashboard at {url}, a tailnet address")
    return TaskState(
        status="todo",
        detail=f"the dashboard is reached at {url}, which is not a tailnet address. Publish it "
               f"with Tailscale Serve so editors need no VPN of their own ({_TAILNET_DOC})",
    )


register(Task(
    id="tailnet", title="Connect to your tailnet",
    description="Sign this node into your Tailscale network.",
    check=_check_tailnet, run=None, optional=True,
))


# -------------------------------------------------------------- nas_connect

# Three seconds, hard: these run while an admin watches a page, and both NAS
# backends default to a timeout chosen for provisioning calls (30s TrueNAS,
# 15s DSM), not for a status check.
NAS_PROBE_TIMEOUT = 3.0


def _nas_kind(ctx: SetupContext) -> str:
    return str(getattr(ctx.settings, "nas_kind", "") or "truenas").strip().lower()


def _nas_credential_key(kind: str) -> str:
    """The env var that is missing, by name. TrueNAS takes a scoped API key
    (COMMERCIAL_READINESS.md item 6 put the admin password out of the
    container); DSM has no API-key concept and keeps the password."""
    return "DASH_NAS_API_KEY (or TRUENAS_API_KEY)" if kind == "truenas" else "DASH_NAS_PW"


def _nas_client(ctx: SetupContext):
    """(client, refusal). Never raises: an unknown DASH_NAS_KIND is a typo an
    admin can fix, not a traceback on the wizard."""
    from .nas import NasError, factory

    kind = _nas_kind(ctx)
    if not factory.nas_configured(ctx.settings):
        return None, TaskState(
            status="todo",
            detail="no NAS credential in this container: set DASH_NAS_HOST and "
                   f"{_nas_credential_key(kind)}, then redeploy",
        )
    try:
        client = factory.make_nas_client(ctx.settings)
    except NasError as exc:
        return None, TaskState(status="fail", detail=_one_line(exc))
    try:
        client.timeout = min(
            float(getattr(client, "timeout", NAS_PROBE_TIMEOUT) or NAS_PROBE_TIMEOUT),
            NAS_PROBE_TIMEOUT,
        )
    except (TypeError, ValueError):
        pass
    return client, None


def _close_quietly(client) -> None:
    """SynologyClient holds a DSM session and an SSH channel; TrueNASClient
    has no close(). Optional, like every other per-backend capability."""
    from .nas import capability

    closer = capability(client, "close")
    if closer is None:
        return
    try:
        closer()
    except Exception:                                                 # noqa: BLE001
        pass


def _check_nas_connect(ctx: SetupContext) -> TaskState:
    """Reachability, plus what answered where the backend can say. Optional by
    design (section 3.2): a fleet syncs perfectly with no NAS credential at
    all, and this buys snapshot scheduling and SMB browsing users."""
    from .nas import NasError, capability

    kind = _nas_kind(ctx)
    where = (str(getattr(ctx.settings, "nas_host", "") or "")
             or str(getattr(ctx.settings, "nas_base_url", "") or "") or "the NAS")
    client, refusal = _nas_client(ctx)
    if refusal is not None:
        return refusal
    try:
        try:
            client.ping()
        except NasError as exc:
            return TaskState(
                status="fail",
                detail=f"{kind} at {where} refused the credential in this container: "
                       f"{_one_line(exc, 100)}",
            )
        except Exception as exc:                                      # noqa: BLE001
            return TaskState(status="fail", detail=f"{kind} at {where}: {_one_line(exc, 100)}")
        info_fn = capability(client, "system_info")
        if info_fn is not None:
            try:
                info = info_fn() or {}
                version = str(info.get("version") or "")
                hostname = str(info.get("hostname") or "") or where
                if version:
                    return TaskState(status="ok",
                                     detail=f"{kind} {version} at {hostname} answered")
            except Exception as exc:                                  # noqa: BLE001
                # Reachable is the answer to THIS task. A scoped key that
                # cannot read /system/info is not a failure of it.
                log.info("nas_connect: system_info unavailable: %s", exc)
        return TaskState(status="ok", detail=f"{kind} at {where} answered")
    finally:
        _close_quietly(client)


register(Task(
    id="nas_connect", title="Connect to your NAS (optional)",
    description="One-time admin credential for snapshots and SMB users.",
    check=_check_nas_connect, run=None, optional=True,
))


# ---------------------------------------------------------------- snapshots

# What "protected" means here, and it is a floor: BACKUP_RESTORE.md section 1
# schedules hourly snapshots kept a day and dailies kept a month. A /data
# backup older than a week is not a backup of anything that happened this
# week.
BACKUP_MAX_AGE_DAYS = 7


def _nas_snapshot_tasks(ctx: SetupContext) -> tuple[list[dict[str, Any]] | None, str]:
    """(tasks, why-not). `None` means the question could not be ASKED, which
    is not the same answer as "there are none"."""
    from .nas import NasError, capability

    kind = _nas_kind(ctx)
    client, refusal = _nas_client(ctx)
    if refusal is not None:
        return None, "no NAS credential is configured"
    try:
        lister = capability(client, "list_snapshot_tasks")
        if lister is None:
            # DSM: TAKING a share snapshot is an API call, SCHEDULING one is
            # the Snapshot Replication package, which has no supported CLI or
            # API (BACKUP_RESTORE.md section 2, "Synology").
            return None, f"{kind} snapshot schedules cannot be read over its API"
        try:
            return list(lister()), ""
        except NasError as exc:
            return None, _one_line(exc, 80)
        except Exception as exc:                                      # noqa: BLE001
            return None, _one_line(exc, 80)
    finally:
        _close_quietly(client)


def _recent_backup(ctx: SetupContext) -> dict[str, Any] | None:
    """The newest `/data/backups/<ts>-<label>/` younger than a week, if any.
    `dashboard_update.backup_databases` writes them today (before a code
    update); WP G's export page writes the same shape."""
    from . import dashboard_update
    from . import db as dbmod

    try:
        backups = dashboard_update.list_backups(ctx.settings)
    except Exception as exc:                                          # noqa: BLE001
        log.info("snapshots check: could not list /data backups: %s", exc)
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=BACKUP_MAX_AGE_DAYS)
    for entry in backups:
        raw = str(entry.get("created_at") or "")
        if not raw:
            continue
        try:
            when = dbmod.parse_iso(raw)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= cutoff:
            return entry
    return None


def _check_snapshots(ctx: SetupContext) -> TaskState:
    tasks, why = _nas_snapshot_tasks(ctx)
    backup = _recent_backup(ctx)
    if tasks:
        detail = f"{len(tasks)} periodic snapshot task(s) on the NAS"
        if backup:
            detail += f"; newest /data backup {backup.get('name')}"
        return TaskState(status="ok", detail=detail)
    if backup:
        return TaskState(
            status="ok",
            detail=f"/data backup {backup.get('name')} is under {BACKUP_MAX_AGE_DAYS} days old, "
                   f"but there is no NAS snapshot schedule ({why or 'none found'})",
        )
    return TaskState(
        status="todo",
        detail=f"no NAS snapshot schedule ({why or 'none found'}) and no /data backup in the "
               f"last {BACKUP_MAX_AGE_DAYS} days: docs/BACKUP_RESTORE.md section 2",
    )


register(Task(
    id="snapshots", title="Protect your data",
    description="Schedule NAS snapshots or export a /data backup.",
    check=_check_snapshots, run=None, optional=True,
))


# ------------------------------------------------------------------ editors

def _known_editors(ctx: SetupContext) -> list[str]:
    """Everyone this dashboard has POSITIVE evidence of, from the two places
    an account can exist: `db.known_editor_usernames` (a report under a signed
    identity, an admin creating an account, a project tick, the share seed)
    and, under local login, the accounts table itself."""
    from . import db as dbmod

    names: set[str] = set()
    try:
        names |= {str(n).strip().lower() for n in dbmod.known_editor_usernames(ctx.conn)}
    except sqlite3.Error as exc:
        log.info("editors check: known_editor_usernames failed: %s", exc)
    if _auth_method(ctx) == "local":
        from . import local_users

        try:
            names |= {
                str(u["username"]).strip().lower()
                for u in local_users.list_users(ctx.conn)
                if u.get("role") == "editor" and not u.get("disabled")
            }
        except sqlite3.Error:
            pass
    names.discard("")
    return sorted(names)


def _check_editors(ctx: SetupContext) -> TaskState:
    names = _known_editors(ctx)
    if not names:
        return TaskState(status="todo", detail="no editors yet: Users page, add one")
    shown = ", ".join(names[:5])
    if len(names) > 5:
        shown += f", and {len(names) - 5} more"
    return TaskState(status="ok", detail=f"{len(names)} editor(s): {shown}")


register(Task(
    id="editors", title="Editors",
    description="Add your first editor.",
    check=_check_editors, run=None, optional=True,
))


# ----------------------------------------------------------------- software

# Both halves of the fleet. A studio with no Mac still sees "macos: none
# published" rather than a green tick that becomes a lie the day someone
# joins on one -- and the Mac build is exactly the one that gets forgotten,
# because it has to be made ON a Mac (RELEASE.md).
SOFTWARE_PLATFORMS = ("windows", "macos")


def _current_companions(ctx: SetupContext) -> dict[str, str]:
    from . import db as dbmod

    out: dict[str, str] = {}
    for platform in SOFTWARE_PLATFORMS:
        row = dbmod.get_current_package(ctx.conn, platform, "companion")
        out[platform] = str(row["version"]) if row is not None else ""
    return out


def _check_software(ctx: SetupContext) -> TaskState:
    try:
        current = _current_companions(ctx)
    except sqlite3.Error as exc:
        return TaskState(status="fail",
                         detail=f"could not read the packages table: {_one_line(exc)}")
    published = [p for p, v in current.items() if v]
    if not published:
        return TaskState(
            status="todo",
            detail="no companion build is current for any platform: publish one on the Users "
                   "page, under PUBLISHED PACKAGES",
        )
    parts = [f"{p} {v} current" if v else f"{p}: none published" for p, v in current.items()]
    # warn, not ok: half a fleet cannot upgrade itself. Still optional, so it
    # never blocks Done.
    status = "ok" if len(published) == len(current) else "warn"
    return TaskState(status=status, detail=", ".join(parts))


def _run_software(ctx: SetupContext) -> TaskState:
    """[ CHECK NOW ] against the vendor feed, then re-report. The feed client
    applies this site's policy (manual/stage/current) itself and never raises
    -- see release_feed.check_now."""
    state = _check_software(ctx)
    if not str(getattr(ctx.settings, "release_feed_url", "") or ""):
        return TaskState(
            status=state.status,
            detail=state.detail + "; no vendor feed is configured (DASH_RELEASE_FEED_URL), so "
                                  "there is nothing to check for",
        )
    from . import release_feed

    app_state = getattr(ctx.app, "state", None)
    if app_state is None:
        app_state = types.SimpleNamespace()
    try:
        result = release_feed.check_now(ctx.conn, ctx.settings, app_state)
    except Exception as exc:                                          # noqa: BLE001
        log.warning("software task: the feed check raised: %s", exc)
        result = {"ok": False, "error": _one_line(exc)}
    state = _check_software(ctx)
    if not result.get("ok"):
        return TaskState(
            status="warn" if state.status == "ok" else state.status,
            detail=f"{state.detail}; the vendor feed check failed: "
                   f"{_one_line(result.get('error') or 'unknown error', 80)}",
        )
    applied = [str(a) for a in (result.get("applied") or [])]
    suffix = (f"; published from the vendor feed: {', '.join(applied)}" if applied
              else "; the vendor feed has nothing this dashboard does not already hold")
    return TaskState(status=state.status, detail=state.detail + suffix)


register(Task(
    id="software", title="Software for editors",
    description="Publish the current companion build for Windows and macOS.",
    check=_check_software, run=_run_software, optional=True,
    run_label="CHECK NOW",
))
