"""HTML routes and htmx partials. All view data comes from api.py's builders
so the JSON API and the pages can never disagree."""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth, db, provision
from .api import (
    build_admin_users_view, build_editors_view, build_packages_view, build_presence_view,
    build_project_view, build_projects_view, build_queue_view, build_transfers_view, get_conn,
)
from .syncthing_client import SyncthingClient, SyncthingError
from .truenas_client import TrueNASClient, TrueNASError, is_valid_username, looks_like_ssh_pubkey

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

router = APIRouter(default_response_class=HTMLResponse)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def human_bytes(n) -> str:
    if n is None:
        return "-"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "?"


def ago(ts: str | None) -> str:
    if not ts:
        return "never"
    try:
        delta = dt.datetime.now(dt.timezone.utc) - db.parse_iso(ts)
    except ValueError:
        return ts
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def bar(completion, width: int = 10) -> str:
    if completion is None:
        return "?" * width
    filled = round(max(0.0, min(float(completion), 100.0)) / 100 * width)
    return "█" * filled + "░" * (width - filled)


def eta(seconds) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


templates.env.filters["human_bytes"] = human_bytes
templates.env.filters["ago"] = ago
templates.env.filters["bar"] = bar
templates.env.filters["eta"] = eta


def _render(request: Request, name: str, context: dict) -> HTMLResponse:
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    context.setdefault("session_user", user)
    context.setdefault("session_is_admin", auth.is_admin(settings, user))
    return templates.TemplateResponse(request=request, name=name, context=context)


def _queue_editor(request: Request) -> str | None:
    """Whose queue to show: the session user, or ?as=<editor> for admins."""
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None:
        return None
    target = request.query_params.get("as", "").strip().lower()
    if target and auth.is_admin(settings, user):
        return target
    return user


@router.get("/")
def page_fleet(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    settings = request.app.state.settings
    queue_editor = _queue_editor(request)
    context = {
        "view": build_projects_view(conn),
        "fleet": build_editors_view(conn),
        "queue": build_queue_view(conn, queue_editor) if queue_editor else None,
        "current_slug": None,
    }
    if queue_editor:
        context.update(_roots_context(
            conn, auth.is_admin(settings, auth.get_session_user(request))
        ))
    return _render(request, "fleet.html", context)


def _safe_next(raw: str) -> str:
    """Only same-site absolute paths survive; anything else (external URLs,
    protocol-relative //host tricks) falls back to '/'."""
    raw = str(raw or "").strip()
    if raw.startswith("/") and not raw.startswith("//"):
        return raw
    return "/"


@router.get("/login")
def page_login(request: Request):
    next_path = _safe_next(request.query_params.get("next", ""))
    if auth.get_session_user(request):
        return RedirectResponse(next_path, status_code=303)
    return _render(request, "login.html", {"error": None, "next_path": next_path})


@router.post("/login")
async def page_login_submit(request: Request):
    settings = request.app.state.settings
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
    username = form.get("username", "").strip().lower()
    password = form.get("password", "")
    next_path = _safe_next(form.get("next", ""))
    error = None
    if not settings.session_secret:
        error = "login not configured on the server (DASH_SESSION_SECRET unset)"
    elif auth.login_throttled(username):
        error = "too many failed attempts -- wait a minute"
    else:
        verifier = getattr(request.app.state, "credential_verifier", auth.verify_credentials)
        if verifier(settings, username, password):
            auth.clear_login_failures(username)
            response = RedirectResponse(next_path, status_code=303)
            response.set_cookie(
                auth.COOKIE_NAME,
                auth.make_session_cookie(settings.session_secret, username),
                max_age=auth.SESSION_TTL_SECONDS, httponly=True, samesite="lax", path="/",
            )
            return response
        auth.record_login_failure(username)
        error = "bad username or password"
    return _render(request, "login.html", {"error": error, "next_path": next_path})


@router.post("/logout")
def page_logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return response


@router.get("/partials/queue")
def partial_queue(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    editor = _queue_editor(request)
    if editor is None:
        raise HTTPException(status_code=401, detail="not logged in")
    return _render(request, "partials/my_queue.html", {
        "queue": build_queue_view(conn, editor),
    })


def _roots_context(conn: sqlite3.Connection, is_admin: bool) -> dict:
    from .api import _project_roots_view

    projects = [
        {"slug": r["slug"], "label": r["label"]}
        for r in conn.execute("SELECT slug, label FROM projects WHERE active=1 ORDER BY label")
    ]
    return {"roots": {
        "mappings": _project_roots_view(conn),
        "unmapped": db.fetch_unmapped_resolve_projects(conn),
        "projects": projects,
        "is_admin": is_admin,
    }}


@router.get("/partials/project-roots")
def partial_project_roots(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    settings = request.app.state.settings
    is_admin = auth.is_admin(settings, auth.get_session_user(request))
    return _render(request, "partials/project_roots.html", _roots_context(conn, is_admin))


@router.post("/partials/project-roots")
async def partial_set_project_root(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None or not auth.is_admin(settings, user):
        raise HTTPException(status_code=403 if user else 401,
                            detail="admins only: destination roots are fixed once set")
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
    name = form.get("resolve_project", "").strip()
    slug = form.get("root", "").strip() or None
    if not name:
        raise HTTPException(status_code=422, detail="resolve_project required")
    if slug is None:
        db.delete_project_root(conn, name)
    else:
        exists = conn.execute(
            "SELECT 1 FROM projects WHERE slug=? AND active=1", (slug,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
        db.admin_set_project_root(conn, name, slug, admin=user, now=db.utcnow_iso())
    conn.commit()
    return _render(request, "partials/project_roots.html", _roots_context(conn, True))


# -------------------------------------------------- project setup (new-project)

def _browse_context(request: Request, resolve_project: str, rel: str) -> dict:
    """The folder-browser box: children of `rel` under the Projects tree,
    each flagged is_project (marker present). Tolerant: an invalid rel or
    unmounted tree degrades to an error entry, never a crash."""
    from .api import ProjectSetupError, _marked_ancestor, _safe_rel

    settings = request.app.state.settings
    error = None
    entries: list[dict] = []
    crumbs: list[dict] = []
    inside_project = False
    norm_rel = ""
    try:
        target, norm_rel = _safe_rel(settings, rel)
        projects_dir = Path(settings.projects_dir)
        if norm_rel:
            acc = []
            for part in norm_rel.split("/"):
                acc.append(part)
                crumbs.append({"name": part, "rel": "/".join(acc)})
            inside_project = _marked_ancestor(projects_dir, norm_rel) is not None
        for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            child_rel = f"{norm_rel}/{child.name}" if norm_rel else child.name
            slug = provision.read_marker(child)
            has_children = any(
                g.is_dir() and not g.name.startswith(".") for g in child.iterdir()
            ) if slug is None else False
            entries.append({
                "name": child.name,
                "rel": child_rel,
                "is_project": slug is not None,
                "slug": slug,
                "has_children": has_children,
            })
    except ProjectSetupError as exc:
        error = str(exc)
    except OSError as exc:
        error = f"could not list the folder: {exc}"

    return {"browse": {
        "resolve_project": resolve_project.strip(),
        "rel": norm_rel,
        "crumbs": crumbs,
        "inside_project": inside_project,
        "entries": entries,
        "error": error,
    }}


def _setup_context(
    request: Request, conn: sqlite3.Connection, resolve_project: str,
    error: str | None = None, created: dict | None = None, browse_rel: str = "",
) -> dict:
    from .api import _project_roots_view

    settings = request.app.state.settings
    user = auth.get_session_user(request)
    name = resolve_project.strip()
    mapping = None
    for row in _project_roots_view(conn):
        if row["resolve_project"].strip().lower() == name.lower():
            mapping = row
            break
    projects_dir = str(getattr(settings, "projects_dir", "") or "")
    projects_dir_ok = bool(projects_dir) and Path(projects_dir).is_dir()
    context = {"setup": {
        "resolve_project": name,
        "mapping": mapping,
        "is_admin": auth.is_admin(settings, user),
        "projects_dir_ok": projects_dir_ok,
        "template_folders": provision.TEMPLATE_FOLDERS,
        "error": error,
        "created": created,
    }}
    if projects_dir_ok:
        context.update(_browse_context(request, name, browse_rel))
    else:
        context["browse"] = None
    return context


@router.get("/project-setup")
def page_project_setup(
    request: Request, resolve_project: str = "", conn: sqlite3.Connection = Depends(get_conn)
):
    if not resolve_project.strip():
        return RedirectResponse("/", status_code=303)
    return _render(request, "project_setup.html", {
        **_sidebar_context(request, conn, None),
        **_setup_context(request, conn, resolve_project),
    })


@router.get("/partials/project-setup/browse")
def partial_project_setup_browse(
    request: Request, rel: str = "", resolve_project: str = "",
    conn: sqlite3.Connection = Depends(get_conn),
):
    if auth.get_session_user(request) is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return _render(request, "partials/project_setup_panel.html",
                   _setup_context(request, conn, resolve_project, browse_rel=rel))


@router.post("/partials/project-setup/link")
async def partial_project_setup_link(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """Link the browsed folder to the Resolve project: adopt_folder claims
    the directory (marker + projects row) and does the tiered sticky map.
    Already-mapped Resolve projects: sticky insert returns False -> banner
    (adopt_folder itself only touches project_roots via sticky, so a
    non-admin can never overwrite an existing mapping)."""
    from .api import ProjectSetupError, adopt_folder

    settings = request.app.state.settings
    user = auth.get_session_user(request)
    form = await _form(request)
    name = form.get("resolve_project", "").strip()
    rel = form.get("rel", "").strip()

    error = None
    created = None
    if user is None:
        error = "not signed in"
    elif not rel:
        error = "pick a folder to link"
    else:
        existing = conn.execute(
            "SELECT 1 FROM project_roots WHERE resolve_project=?", (name,)
        ).fetchone() if name else None
        if existing is not None and not auth.is_admin(settings, user):
            error = "this Resolve project is already mapped -- ask an admin to change it"
        else:
            try:
                created = adopt_folder(settings, conn, rel, name if existing is None else "", user)
                if existing is not None:
                    # admin re-pointing an existing mapping
                    db.admin_set_project_root(conn, name, created["slug"],
                                              admin=user, now=db.utcnow_iso())
                    created["mapped"] = True
                conn.commit()
            except ProjectSetupError as exc:
                error = str(exc)

    return _render(request, "partials/project_setup_panel.html",
                   _setup_context(request, conn, name, error=error, created=created,
                                  browse_rel=rel.rsplit("/", 1)[0] if "/" in rel else ""))


@router.post("/partials/project-setup/create")
async def partial_project_setup_create(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    from .api import ProjectSetupError, create_tree_project

    user = auth.get_session_user(request)
    form = await _form(request)
    name = form.get("resolve_project", "").strip()
    parent_rel = form.get("parent_rel", "").strip()

    error = None
    created = None
    if user is None:
        error = "not signed in"
    else:
        try:
            created = create_tree_project(
                request.app.state.settings, conn,
                parent_rel, form.get("name", ""), name, user,
            )
            conn.commit()
        except ProjectSetupError as exc:
            error = str(exc)

    return _render(request, "partials/project_setup_panel.html",
                   _setup_context(request, conn, name, error=error, created=created,
                                  browse_rel=parent_rel))


@router.post("/partials/selection/{editor}/{slug}/toggle")
def partial_toggle(
    editor: str, slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    settings = request.app.state.settings
    editor = editor.strip().lower()
    user = auth.get_session_user(request)
    if not auth.can_manage(settings, user, editor):
        raise HTTPException(status_code=403 if user else 401, detail="not allowed")
    ticked = {s["slug"] for s in db.fetch_selections(conn, editor)}
    if slug in ticked:
        db.remove_selection(conn, editor, slug)
    else:
        project = conn.execute(
            "SELECT slug FROM projects WHERE slug=? AND active=1", (slug,)
        ).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
        db.add_selection(conn, editor, slug, created_by=user, now=db.utcnow_iso())
    conn.commit()
    # Return the partial the control lives in.
    view_kind = request.query_params.get("view")
    if view_kind == "sidebar" or "sidebar" in (request.headers.get("hx-target") or ""):
        current = request.query_params.get("slug_page")
        return _render(request, "partials/sidebar.html", _sidebar_context(request, conn, current))
    if view_kind == "project":
        view = build_project_view(conn, request.query_params.get("slug_page", slug))
        if view is None:
            raise HTTPException(status_code=404)
        return _render(request, "partials/project_detail.html", {"project": view,
                                                                "selected_by": db.fetch_all_selections(conn)})
    return _render(request, "partials/my_queue.html", {
        "queue": build_queue_view(conn, editor),
    })


@router.get("/project/{slug}")
def page_project(slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    view = build_project_view(conn, slug)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    scope = auth.scope_for(request)
    return _render(request, "project.html", {
        **_sidebar_context(request, conn, slug),
        "project": view,
        "presence": build_presence_view(conn, slug, editor=scope.editor),
        "selected_by": db.fetch_all_selections(conn),
        "scope_admin": scope.admin,
    })


def _sidebar_context(request: Request, conn, current: str | None) -> dict:
    """Sidebar data incl. the checkbox state for the viewer's own selection
    (or the ?as=<editor> focus for admins)."""
    toggle_editor = _queue_editor(request)   # session user, or ?as for admins
    selected = set()
    if toggle_editor:
        selected = {s["slug"] for s in db.fetch_selections(conn, toggle_editor)}
    return {
        "view": build_projects_view(conn),
        "current_slug": current or None,
        "selected_slugs": selected,
        "toggle_editor": toggle_editor,
    }


@router.get("/partials/sidebar")
def partial_sidebar(request: Request, current: str = "", conn: sqlite3.Connection = Depends(get_conn)):
    return _render(request, "partials/sidebar.html", _sidebar_context(request, conn, current))


@router.get("/transfers")
def page_transfers(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    scope = auth.scope_for(request)
    return _render(request, "transfers.html", {
        **_sidebar_context(request, conn, None),
        "transfers": build_transfers_view(conn, editor=scope.editor),
        "scope_admin": scope.admin,
    })


@router.get("/partials/transfers")
def partial_transfers(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    scope = auth.scope_for(request)
    return _render(request, "partials/transfers.html", {
        "transfers": build_transfers_view(conn, editor=scope.editor),
        "scope_admin": scope.admin,
    })


@router.get("/partials/project/{slug}/bins")
def partial_bins(slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    scope = auth.scope_for(request)
    view = build_presence_view(conn, slug, editor=scope.editor)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    return _render(request, "partials/bins.html", {"presence": view, "scope_admin": scope.admin})


@router.get("/partials/fleet")
def partial_fleet(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    return _render(request, "partials/fleet_grid.html", {
        "view": build_projects_view(conn),
        "fleet": build_editors_view(conn),
    })


@router.get("/partials/project/{slug}")
def partial_project(slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    view = build_project_view(conn, slug)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    return _render(request, "partials/project_detail.html", {
        "project": view,
        "selected_by": db.fetch_all_selections(conn),
    })


@router.get("/partials/project/{slug}/missing/{device_id}")
def partial_missing(
    slug: str, device_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    project = db.fetch_project(conn, slug)
    if project is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    editor = next((e for e in project["editors"] if e["device_id"] == device_id), None)
    if editor is None:
        raise HTTPException(status_code=404, detail=f"device not in project: {device_id}")
    missing = db.fetch_missing(conn, project["id"], editor["device_row_id"])
    return _render(request, "partials/missing_files.html", {
        "missing": missing,
        "need_items": editor["need_items"],
        "editor_label": editor["editor_username"] or editor["name"],
    })


# ------------------------------------------------------------- admin users

def _require_admin_page(request: Request) -> str:
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None or not auth.is_admin(settings, user):
        raise HTTPException(status_code=403 if user else 401, detail="admins only")
    return user


async def _form(request: Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}


@router.get("/admin/users")
def page_admin_users(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "admin_users.html", {
        **_sidebar_context(request, conn, None),
        "admin_users": build_admin_users_view(request.app.state.settings),
        "packages": build_packages_view(conn, request.app.state.settings),
    })


@router.get("/partials/admin/users")
def partial_admin_users(request: Request):
    _require_admin_page(request)
    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(request.app.state.settings),
    })


@router.post("/partials/admin/users/create")
async def partial_admin_create_user(request: Request):
    _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    ssh_pubkey = form.get("ssh_pubkey", "").strip()
    full_name = form.get("full_name", "").strip() or None
    password = form.get("password", "").strip() or None

    error = None
    if not settings.truenas_pw:
        error = "TRUENAS_PW is not configured on the dashboard"
    elif not is_valid_username(username):
        error = ("username must start with a letter and contain only lowercase letters, "
                 "digits, '.', '_', '-'")
    elif not looks_like_ssh_pubkey(ssh_pubkey):
        error = "does not look like an OpenSSH public key"
    else:
        truenas = TrueNASClient(settings.truenas_host, settings.truenas_user, settings.truenas_pw,
                                 base_url=settings.truenas_base_url or None)
        try:
            result = truenas.create_or_update_editor(username, ssh_pubkey, full_name)
            if password:
                truenas.set_known_password(username, password)
            if result["warnings"]:
                error = f"{username}: created with warnings — {'; '.join(result['warnings'])}"
        except TrueNASError as exc:
            error = str(exc)

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings),
        "error": error,
    })


@router.post("/partials/admin/users/password")
async def partial_admin_set_password(request: Request):
    _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    password = form.get("password", "").strip()

    error = None
    if not settings.truenas_pw:
        error = "TRUENAS_PW is not configured on the dashboard"
    elif not password:
        error = "password required"
    else:
        truenas = TrueNASClient(settings.truenas_host, settings.truenas_user, settings.truenas_pw,
                                 base_url=settings.truenas_base_url or None)
        try:
            truenas.set_known_password(username, password)
        except TrueNASError as exc:
            error = str(exc)

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings),
        "error": error,
    })


@router.post("/partials/admin/users/approve")
async def partial_admin_approve_device(request: Request):
    _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    device_id = form.get("device_id", "").strip()
    username = form.get("username", "").strip().lower()

    error = None
    if not settings.syncthing_url:
        error = "SYNCTHING_GUI_URL is not configured"
    elif not is_valid_username(username):
        error = "username must be a valid TrueNAS-style username"
    else:
        syncthing = SyncthingClient(settings.syncthing_url, settings.syncthing_api_key)
        try:
            syncthing.approve_device(device_id, username)
        except SyncthingError as exc:
            error = str(exc)

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings),
        "error": error,
    })


# --------------------------------------------------------- admin packages

@router.get("/partials/admin/packages")
def partial_admin_packages(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "partials/admin_packages.html", {
        "packages": build_packages_view(conn, request.app.state.settings),
    })


@router.post("/partials/admin/packages/current")
async def partial_admin_package_current(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    platform = form.get("platform", "").strip().lower()
    version = form.get("version", "").strip()

    error = None
    if not db.set_current_package(conn, platform, version):
        error = f"no published {platform} package {version}"
    else:
        conn.commit()

    return _render(request, "partials/admin_packages.html", {
        "packages": build_packages_view(conn, settings),
        "error": error,
    })


@router.post("/partials/admin/packages/delete")
async def partial_admin_package_delete(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    platform = form.get("platform", "").strip().lower()
    version = form.get("version", "").strip()

    error = None
    row = db.get_package(conn, platform, version)
    if row is None:
        error = f"no published {platform} package {version}"
    elif row["is_current"]:
        error = "cannot delete the current version — make another version current first"
    else:
        db.delete_companion_package(conn, platform, version)
        conn.commit()
        try:
            (settings.packages_path() / row["platform"] / row["filename"]).unlink(missing_ok=True)
        except OSError:
            pass

    return _render(request, "partials/admin_packages.html", {
        "packages": build_packages_view(conn, settings),
        "error": error,
    })
