"""HTTP surface for the SetupEngine and the site-manifest admin routes
(ZERO_TOUCH_PLAN.md WP D / §3.2, §3.5, 2026-08-17).

Two access rules, not one:

* `/api/v1/admin/site*` -- exactly the same `_require_admin` gate every other
  `/api/v1/admin/*` route in `api.py` uses. No first-run exception: by the
  time the wizard's "Your studio" step runs, step 2 ("Create your admin
  account") has already put a session in the browser.
* `/api/v1/setup/*` -- a session-less window is required for the FIRST two
  steps (Welcome/EULA, then creating that very admin account), so these
  routes are in `app.py`'s open list and gate themselves via
  `require_setup_access`, which allows either an authenticated admin OR an
  anonymous caller during the narrow "no local account exists yet" window.
  That window is reported by agent C's identity module (WP C), which does
  not exist in this worktree -- `setup_engine.probe_admin_status` returns
  `None` here. An unknown status is treated as CLOSED, so on `smb` and
  `oidc` deployments every one of these routes requires an admin session.
  Under `DASH_AUTH_METHOD=local` the accounts table answers instead (see
  `first_run_open`, dash-admin-4): with zero rows nobody can sign in at all,
  so a shut window was a dead end rather than a guard. See `setup_engine.py`'s
  module docstring for the handoff.
"""
from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from . import auth, db, setup_engine, site_store
from .api import get_conn

router = APIRouter(prefix="/api/v1")
log = logging.getLogger("ccsync.dashboard.setup_routes")


def _ctx(request: Request, conn: sqlite3.Connection) -> setup_engine.SetupContext:
    return setup_engine.SetupContext(
        conn=conn, settings=request.app.state.settings, app=request.app
    )


def first_run_open(request: Request, conn: sqlite3.Connection) -> bool:
    """True only in the narrow pre-admin-account window: no local account
    exists yet (per the identity module's probe) and auth is not OIDC (SSO
    break-glass rules stay break-glass -- see auth.py's `sso and not
    is_admin` refusal in page_login_submit; the wizard must not become a
    second, unauthenticated way in for an OIDC deployment).

    Fails closed everywhere the answer is unknown: `probe_admin_status`
    returning `None` (module absent, see this module's docstring) means this
    is NEVER true -- EXCEPT under `DASH_AUTH_METHOD=local`, where the
    accounts table is the whole answer (dash-admin-4, 2026-08-21).

    Under local login with no row, `auth.verify_credentials` needs a password
    hash that does not exist, so nobody can sign in at all: `/setup` 303'd to
    a `/login` no credential could pass and every `/api/v1/setup/*` route
    401'd, while `POST /api/v1/setup/admin` -- the route the wizard's step 2
    calls, already open in app.py -- sat there working. The window that was
    "correctly shut" is a dead end on that method, not a safety, and it
    closes again the instant the first account exists (setup_api.setup_admin
    re-checks under BEGIN IMMEDIATE, so this is not the lock). smb and oidc
    keep the old answer: there a NAS or an IdP can already authenticate an
    admin, so an anonymous window would be a second way in.
    """
    settings = request.app.state.settings
    method = str(getattr(settings, "auth_method", "") or "").strip().lower()
    if method == "oidc":
        return False
    status = setup_engine.probe_admin_status(_ctx(request, conn))
    if status is None:
        if method != "local":
            return False
        from . import local_users

        try:
            return not local_users.any_users_exist(conn)
        except sqlite3.Error:       # a pre-v17 database has no users table
            return False
    return not bool(status.get("users_exist"))


def require_setup_access(request: Request, conn: sqlite3.Connection) -> str | None:
    """The admin username, or None for an anonymous first-run caller.
    Raises 401/403 otherwise. Every route below calls this FIRST, before
    touching setup_tasks or site_settings."""
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is not None:
        if not auth.is_admin(settings, user):
            raise HTTPException(status_code=403, detail="admins only")
        return user
    if first_run_open(request, conn):
        return None
    raise HTTPException(status_code=401, detail="log in first")


# ------------------------------------------------------------------ tasks

@router.get("/setup/tasks")
def api_setup_tasks(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    require_setup_access(request, conn)
    states = setup_engine.list_states(conn)
    return {
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "optional": task.optional,
                "can_run": task.run is not None,
                # What the button says. Only meaningful with can_run; sent
                # always so a client never has to know the default
                # ("DO IT") -- see Task.run_label.
                "run_label": task.run_label,
                **states[task.id].as_dict(),
            }
            for task in setup_engine.TASKS
        ],
        "outstanding_required": setup_engine.outstanding_required(conn),
    }


def _known_task(task_id: str) -> setup_engine.Task:
    task = setup_engine.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"unknown setup task {task_id!r}")
    return task


@router.post("/setup/tasks/{task_id}/check")
async def api_setup_task_check(
    task_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    require_setup_access(request, conn)
    _known_task(task_id)
    ctx = _ctx(request, conn)
    state = await run_in_threadpool(setup_engine.run_check, ctx, task_id)
    return state.as_dict()


@router.post("/setup/tasks/{task_id}/run")
async def api_setup_task_run(
    task_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    require_setup_access(request, conn)
    task = _known_task(task_id)
    if task.run is None:
        raise HTTPException(
            status_code=400,
            detail=f"{task_id!r} has no automatic action -- see its description",
        )
    ctx = _ctx(request, conn)
    state = await run_in_threadpool(setup_engine.run_do_it, ctx, task_id)
    return state.as_dict()


@router.post("/setup/tasks/{task_id}/skip")
def api_setup_task_skip(
    task_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    require_setup_access(request, conn)
    task = _known_task(task_id)
    if not task.optional:
        raise HTTPException(status_code=400, detail=f"{task_id!r} is required and cannot be skipped")
    ctx = _ctx(request, conn)
    state = setup_engine.run_skip(ctx, task_id)
    return state.as_dict()


# ------------------------------------------------------------------- eula

@router.get("/setup/eula")
def api_setup_eula_get(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    require_setup_access(request, conn)
    if not setup_engine.EULA_PATH.is_file():
        return {"text": "", "version": None}
    try:
        text = setup_engine.EULA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not read EULA: {exc}")
    return {"text": text, "version": setup_engine.eula_marker_version(text)}


@router.post("/setup/eula")
def api_setup_eula_accept(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    require_setup_access(request, conn)
    ctx = _ctx(request, conn)
    state = setup_engine.run_do_it(ctx, "eula")
    return state.as_dict()


# ------------------------------------------------------------- admin/site

def _require_admin(request: Request) -> str:
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="log in first")
    if not auth.is_admin(settings, user):
        raise HTTPException(status_code=403, detail="admins only")
    return user


@router.get("/admin/site")
def api_admin_site_get(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    _require_admin(request)
    manifest = site_store.resolved_manifest(conn, request.app.state.settings)
    manifest["auto_derived"] = sorted(site_store.AUTO_DERIVED_KEYS)
    return manifest


class SiteSettingsIn(BaseModel):
    # Raw strings only -- site_store.validate() does the typed parsing (int/
    # bool/csv) and is the ONE place that decides a value is acceptable, so
    # the API and a future Settings-page form can never disagree about what
    # is valid. Capped generously; nothing here is meant to hold a file.
    values: dict[str, str] = Field(default_factory=dict)


@router.put("/admin/site")
def api_admin_site_put(
    payload: SiteSettingsIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    admin = _require_admin(request)
    settings = request.app.state.settings
    # UX-21 (resilience sweep 2026-08-28): "The same snapshot belongs on
    # [ SAVE ] for the three tree keys" -- canonical_prefix, tree_name and
    # remote_root are read by both installers and every companion, so a save
    # that changes one of them gets a site_history entry, exactly like an
    # import does below. Computed BEFORE set_many writes, from the same
    # validate-then-diff path the import preview uses (site_store.py), so a
    # save that fails validation leaves no half-taken snapshot.
    tree_raw = {k: v for k, v in payload.values.items() if k in site_store.TREE_KEYS}
    tree_changes: list[dict[str, str]] = []
    try:
        if tree_raw:
            tree_normalized = site_store.validate_many(tree_raw)
            tree_changes = site_store.diff_against_current(conn, settings, tree_normalized)
        site_store.set_many(conn, payload.values, updated_by=admin)
    except site_store.SiteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if tree_changes:
        before = {c["key"]: c["from"] for c in tree_changes}
        after = {c["key"]: c["to"] for c in tree_changes}
        db.record_site_change(conn, admin, "save", before, after)
    # SYS-11 (resilience sweep 2026-08-28): the KEYS, never the values -- a
    # site setting can be a token, and this table is read by a page.
    db.audit(conn, admin, "site.settings_save", "site",
             {"keys": sorted(payload.values)})
    conn.commit()
    # The brand ui._render paints comes from this table now (product-surface-2,
    # 2026-08-21) and is cached per process, so every writer of site_settings
    # drops that cache in the same breath as its commit.
    site_store.invalidate(request.app)
    log.info("admin %r updated site settings: %s", admin, ", ".join(sorted(payload.values)))
    manifest = site_store.resolved_manifest(conn, settings)
    manifest["auto_derived"] = sorted(site_store.AUTO_DERIVED_KEYS)
    return manifest


@router.get("/admin/site/export")
def api_admin_site_export(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    from fastapi.responses import PlainTextResponse

    _require_admin(request)
    text = site_store.export_toml(conn, request.app.state.settings)
    return PlainTextResponse(text, media_type="text/plain")


class SiteImportIn(BaseModel):
    text: str = Field(max_length=65536)


@router.post("/admin/site/import")
def api_admin_site_import(
    payload: SiteImportIn, request: Request, conn: sqlite3.Connection = Depends(get_conn),
    dry_run: bool = False,
) -> dict:
    """UX-21 (resilience sweep 2026-08-28): pasting an older or another
    site's config used to overwrite every recognised key with no confirmation
    and no way back. `dry_run=1` runs the SAME validate-then-diff path the
    apply below does and writes nothing, so the confirm dialog the UI shows
    can never disagree with what an apply would actually do."""
    admin = _require_admin(request)
    settings = request.app.state.settings
    try:
        parsed = site_store.import_toml(payload.text)
        if not parsed:
            raise HTTPException(status_code=422, detail="no recognised [section] keys found in that text")
        normalized = site_store.validate_many(parsed)
    except site_store.SiteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    changes = site_store.diff_against_current(conn, settings, normalized)

    if dry_run:
        return {"changes": site_store.mask_changes(changes), "count": len(changes)}

    before = {c["key"]: c["from"] for c in changes}
    after = {c["key"]: c["to"] for c in changes}
    site_store.set_many(conn, normalized, updated_by=admin)
    if changes:
        # A re-paste of the running config changes nothing, so it leaves no
        # history entry -- [ UNDO LAST IMPORT ] never offers a no-op.
        db.record_site_change(conn, admin, "import", before, after)
    db.audit(conn, admin, "site.settings_import", "site",   # keys only, see above
             {"keys": sorted(parsed)})
    conn.commit()
    site_store.invalidate(request.app)          # see api_admin_site_put
    log.info("admin %r imported site settings: %s", admin, ", ".join(sorted(parsed)))
    manifest = site_store.resolved_manifest(conn, settings)
    manifest["auto_derived"] = sorted(site_store.AUTO_DERIVED_KEYS)
    return manifest


@router.get("/admin/site/history")
def api_admin_site_history(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """UX-21 (resilience sweep 2026-08-28): who changed the site manifest,
    when and how, for the [ UNDO LAST IMPORT ] button's own display. Never
    the actual before/after values -- those stay inside site_history's raw
    storage (needed for a correct undo, see db.record_site_change) and are
    not put on the wire here."""
    _require_admin(request)
    entries = db.site_history(conn)
    return {
        "entries": [
            {
                "at": e.get("at"),
                "actor": e.get("actor"),
                "action": e.get("action"),
                "count": len(e.get("before") or {}),
            }
            for e in entries
        ],
    }


@router.post("/admin/site/undo-last-change")
def api_admin_site_undo_last_change(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    """[ UNDO LAST IMPORT ] (UX-21, resilience sweep 2026-08-28): reapplies
    the newest site_history entry's BEFORE values through the SAME
    validate/set_many path a save or an import uses, so validation and every
    side effect (the manifest cache drop, the audit row) run identically --
    an undo is not a second, less-checked write path. Records the undo as
    its own history entry (action="undo"), so undoing an undo is just
    another undo."""
    admin = _require_admin(request)
    settings = request.app.state.settings
    entries = db.site_history(conn)
    if not entries:
        raise HTTPException(status_code=404, detail="no site setting change is recorded to undo")
    latest = entries[0]
    restore = {str(k): str(v) for k, v in (latest.get("before") or {}).items()}
    if not restore:
        raise HTTPException(status_code=409, detail="that change recorded no values to restore")
    try:
        normalized = site_store.validate_many(restore)
    except site_store.SiteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    changes = site_store.diff_against_current(conn, settings, normalized)
    site_store.set_many(conn, normalized, updated_by=admin)
    if changes:
        before = {c["key"]: c["from"] for c in changes}
        after = {c["key"]: c["to"] for c in changes}
        db.record_site_change(conn, admin, "undo", before, after)
    db.audit(conn, admin, "site.settings_undo", "site",
             {"keys": sorted(restore)})
    conn.commit()
    site_store.invalidate(request.app)          # see api_admin_site_put
    log.info("admin %r undid the site setting change made by %r at %s: %s",
             admin, latest.get("actor"), latest.get("at"), ", ".join(sorted(restore)))
    manifest = site_store.resolved_manifest(conn, settings)
    manifest["auto_derived"] = sorted(site_store.AUTO_DERIVED_KEYS)
    return {
        "manifest": manifest,
        "changes": site_store.mask_changes(changes),
        "count": len(changes),
    }
