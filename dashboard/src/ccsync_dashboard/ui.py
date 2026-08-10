"""HTML routes and htmx partials. All view data comes from api.py's builders
so the JSON API and the pages can never disagree."""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
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
    # Only offer the B-ROLL link when the mount FULLY took (broll.MOUNTED).
    # The import is guarded, so a missing or stale /broll-app leaves the
    # dashboard running with the feature absent; and a mount whose data root
    # could not be prepared is mounted "degraded", answering every request with
    # a 500. A nav link to either is worse than no link.
    context.setdefault("broll_mounted", getattr(request.app.state, "broll_mounted", False))
    # Identical rule for the music platform (music.MOUNTED only): a missing
    # music tree is absent, an unopenable DATA_ROOT is degraded, and neither
    # gets a nav link.
    context.setdefault("music_mounted", getattr(request.app.state, "music_mounted", False))
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


def _as_qs(request: Request, editor: str | None) -> str:
    """'&as=<editor>' when the viewer is ticking for somebody else, else ''.

    Every self-refreshing fragment that carries selection state has to thread
    this through: the sidebar polls /partials/sidebar every 30s, and a refresh
    that dropped ?as= re-rendered the checkboxes against the ADMIN'S OWN ticks
    while the admin believed they were still looking at the other editor's --
    so the next click silently ticked the project onto the admin's machine."""
    user = auth.get_session_user(request)
    if editor and user and editor.lower() != user.lower():
        return "&as=" + quote(editor, safe="")
    return ""


@router.get("/")
def page_fleet(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    settings = request.app.state.settings
    queue_editor = _queue_editor(request)
    context = {
        # _sidebar_context, not a bare view: the every-30s /partials/sidebar
        # refresh has always rendered the checkboxes, so building this page's
        # first paint without them made the sidebar sprout controls 30s in.
        **_sidebar_context(request, conn, None),
        "fleet": build_editors_view(conn),
        "queue": build_queue_view(conn, queue_editor) if queue_editor else None,
    }
    if queue_editor:
        context.update(_roots_context(
            conn, auth.is_admin(settings, auth.get_session_user(request))
        ))
    return _render(request, "fleet.html", context)


def _safe_next(raw: str) -> str:
    """Only same-site absolute paths survive; anything else (external URLs,
    protocol-relative //host tricks, and the backslash variant '/\\host')
    falls back to '/'."""
    raw = str(raw or "").strip()
    if raw.startswith("/") and not (len(raw) > 1 and raw[1] in "/\\"):
        return raw
    return "/"


@router.get("/login")
def page_login(request: Request):
    next_path = _safe_next(request.query_params.get("next", ""))
    if auth.get_session_user(request):
        return RedirectResponse(next_path, status_code=303)
    return _render(request, "login.html", {"error": None, "next_path": next_path})


MAX_LOGIN_BODY_BYTES = 8 * 1024   # generous for a username/password/next form
MAX_FORM_FIELDS = 16


@router.post("/login")
async def page_login_submit(request: Request):
    # /login is unauthenticated (app.py's _OPEN_EXACT), so an unbounded body
    # read here is a single-worker OOM open to anyone on the tailnet -- check
    # Content-Length BEFORE reading, and re-check the actual body length as a
    # fallback for chunked/absent-header requests (see the unbounded /login
    # body finding).
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_too_big = int(content_length) > MAX_LOGIN_BODY_BYTES
        except ValueError:
            declared_too_big = True
        if declared_too_big:
            raise HTTPException(status_code=413, detail="request body too large")
    body = await request.body()
    if len(body) > MAX_LOGIN_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request body too large")
    try:
        parsed = parse_qs(body.decode(), max_num_fields=MAX_FORM_FIELDS)
    except ValueError:
        raise HTTPException(status_code=400, detail="malformed form body")
    form = {k: v[0] for k, v in parsed.items()}
    settings = request.app.state.settings
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
        # verifier is a blocking SMB session setup (up to a 10s timeout) --
        # push it off the event loop so a slow/unreachable SMB server can't
        # freeze every other request, including companions' /api/v1/report
        # (see SEC-13 / the ui.py blocking-handlers finding).
        try:
            verified = await run_in_threadpool(verifier, settings, username, password)
        except auth.CredentialProbeBusy:
            # Saturated probe pool (see auth.MAX_CONCURRENT_SMB_PROBES): this
            # is NOT a failed password, so it must not count toward the
            # throttle either.
            error = "the server is busy checking sign-ins -- try again in a moment"
        else:
            if verified:
                auth.clear_login_failures(username)
                response = RedirectResponse(next_path, status_code=303)
                response.set_cookie(
                    auth.COOKIE_NAME,
                    auth.make_session_cookie(settings.session_secret, username),
                    max_age=auth.SESSION_TTL_SECONDS, httponly=True, samesite="lax",
                    # see auth.cookie_secure: on for https, off for the
                    # current plain-http LAN/tailnet deployment (where a
                    # hardcoded True makes the browser drop the cookie and
                    # login silently loops)
                    secure=auth.cookie_secure(settings, request), path="/",
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
    # A rel path picked in the folder browser (any folder under Projects/,
    # not only registered projects). The companion only ever consumes the
    # mapping as a rel path (_project_roots_view falls back to the raw
    # stored value), so an unregistered folder works end to end.
    root_rel = form.get("root_rel", "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="resolve_project required")
    if root_rel:
        from .api import ProjectSetupError, _safe_rel

        try:
            target, norm_rel = _safe_rel(settings, root_rel)
        except ProjectSetupError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if not norm_rel or not target.is_dir():
            raise HTTPException(status_code=404, detail=f"no such folder under Projects/: {root_rel!r}")
        # Prefer the slug when the picked folder IS a registered project, so
        # the dropdown keeps showing it as selected.
        marker_slug = provision.read_marker(target)
        db.admin_set_project_root(conn, name, marker_slug or norm_rel,
                                  admin=user, now=db.utcnow_iso())
    elif slug is None:
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


@router.get("/partials/project-roots/browse")
def partial_project_roots_browse(
    request: Request, resolve_project: str = "", rel: str = ""
):
    """The FILES INTO folder browser: any folder under Projects/ can be
    picked as a Resolve project's destination root, not only the dropdown's
    registered projects. Admin-gated like the setter it feeds."""
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None or not auth.is_admin(settings, user):
        raise HTTPException(status_code=403 if user else 401,
                            detail="admins only: destination roots are fixed once set")
    return _render(request, "partials/project_roots_browse.html",
                   _browse_context(request, resolve_project, rel))


# -------------------------------------------------- project setup (new-project)

def _browse_context(request: Request, resolve_project: str, rel: str) -> dict:
    """The folder-browser box: children of `rel` under the Projects tree,
    each flagged is_project (marker present) and name_match (same name as the
    Resolve project -- almost always the folder the editor means). Tolerant:
    an invalid rel or unmounted tree degrades to an error entry, never a
    crash.

    can_link_current says whether the folder you are STANDING IN may itself be
    picked: without that button, drilling into an already-existing project
    folder left "create a new subfolder here" as the only action, which is how
    <project>/<project> double-nesting happened."""
    from .api import ProjectSetupError, _marked_ancestor, _safe_rel

    settings = request.app.state.settings
    error = None
    entries: list[dict] = []
    crumbs: list[dict] = []
    inside_project = False
    current_is_project = False
    norm_rel = ""
    wanted = resolve_project.strip().casefold()
    try:
        target, norm_rel = _safe_rel(settings, rel)
        projects_dir = Path(settings.projects_dir)
        if norm_rel:
            acc = []
            for part in norm_rel.split("/"):
                acc.append(part)
                crumbs.append({"name": part, "rel": "/".join(acc)})
            marked = _marked_ancestor(projects_dir, norm_rel)
            inside_project = marked is not None
            current_is_project = marked == norm_rel
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
                "name_match": bool(wanted) and child.name.casefold() == wanted,
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
        "current_is_project": current_is_project,
        # the current folder is pickable unless it sits inside a DIFFERENT
        # project (projects cannot nest) -- adopt_folder re-checks all of this
        "can_link_current": bool(norm_rel) and error is None
                            and (not inside_project or current_is_project),
        "entries": entries,
        "error": error,
    }}


def _setup_context(
    request: Request, conn: sqlite3.Connection, resolve_project: str,
    error: str | None = None, created: dict | None = None, browse_rel: str = "",
    suggest_rel: str = "",
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
        # rel of an existing folder the failed action should have used --
        # rendered next to the banner as a one-click [ USE THIS FOLDER ]
        "suggest_rel": suggest_rel,
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


def _link_folder_sync(settings, conn, rel: str, name: str, user: str, existing) -> dict:
    """Runs on a threadpool worker -- see partial_project_setup_link. Does a
    depth-8 os.walk of the whole Projects tree plus marker writes."""
    from .api import adopt_folder

    created = adopt_folder(settings, conn, rel, name if existing is None else "", user)
    if existing is not None:
        # admin re-pointing an existing mapping
        db.admin_set_project_root(conn, name, created["slug"], admin=user, now=db.utcnow_iso())
        created["mapped"] = True
    conn.commit()
    return created


@router.post("/partials/project-setup/link")
async def partial_project_setup_link(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """Link the browsed folder to the Resolve project: adopt_folder claims
    the directory (marker + projects row) and does the tiered sticky map.
    Already-mapped Resolve projects: sticky insert returns False -> banner
    (adopt_folder itself only touches project_roots via sticky, so a
    non-admin can never overwrite an existing mapping)."""
    from .api import ProjectSetupError

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
                # Full-tree NAS I/O off the event loop: this walk takes tens of
                # seconds on a loaded NAS, and blocking here freezes every
                # companion report and every htmx poll (see the blocking
                # project-setup handlers finding).
                created = await run_in_threadpool(
                    _link_folder_sync, settings, conn, rel, name, user, existing
                )
            except ProjectSetupError as exc:
                error = str(exc)

    return await run_in_threadpool(
        _render_setup_panel, request, conn, name, error, created,
        rel.rsplit("/", 1)[0] if "/" in rel else "",
    )


def _create_project_sync(settings, conn, parent_rel: str, name: str,
                          resolve_project: str, user: str) -> dict:
    """Runs on a threadpool worker -- see partial_project_setup_create."""
    from .api import create_tree_project

    created = create_tree_project(settings, conn, parent_rel, name, resolve_project, user)
    conn.commit()
    return created


@router.post("/partials/project-setup/create")
async def partial_project_setup_create(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    from .api import FolderExistsError, ProjectSetupError

    user = auth.get_session_user(request)
    form = await _form(request)
    name = form.get("resolve_project", "").strip()
    parent_rel = form.get("parent_rel", "").strip()

    error = None
    created = None
    suggest_rel = ""
    if user is None:
        error = "not signed in"
    else:
        try:
            created = await run_in_threadpool(
                _create_project_sync, request.app.state.settings, conn,
                parent_rel, form.get("name", ""), name, user,
            )
        except FolderExistsError as exc:
            # the typed name is already a folder here -- offer it instead of
            # making the admin invent a second, nested name
            error, suggest_rel = str(exc), exc.rel
        except ProjectSetupError as exc:
            error = str(exc)

    return await run_in_threadpool(
        _render_setup_panel, request, conn, name, error, created, parent_rel, suggest_rel
    )


def _render_setup_panel(request: Request, conn, name: str, error, created, browse_rel: str,
                        suggest_rel: str = ""):
    """_setup_context does per-row iterdir() over the NAS mount, so rendering
    the panel is itself blocking work -- always call this in a threadpool."""
    return _render(request, "partials/project_setup_panel.html",
                   _setup_context(request, conn, name, error=error, created=created,
                                  browse_rel=browse_rel, suggest_rel=suggest_rel))


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
    # Reconcile Syncthing sharing promptly -- ticking used to wait out
    # interval_enforce (up to 60s) before anything started (2026-07-26).
    from .api import _nudge_collector

    _nudge_collector(request)
    # Return the partial the control lives in.
    view_kind = request.query_params.get("view")
    # Re-render for `editor` (the POST path), not for whoever _queue_editor
    # would infer: an admin ticking for someone else must get that editor's
    # checkboxes back, not their own.
    if view_kind == "sidebar" or "sidebar" in (request.headers.get("hx-target") or ""):
        current = request.query_params.get("slug_page")
        return _render(request, "partials/sidebar.html",
                       _sidebar_context(request, conn, current, editor=editor))
    if view_kind == "project":
        page_slug = request.query_params.get("slug_page", slug)
        view = build_project_view(conn, page_slug)
        if view is None:
            raise HTTPException(status_code=404)
        return _render(request, "partials/project_detail.html",
                       {"project": view,
                        "selected_by": db.fetch_all_selections(conn),
                        "tick_editor": editor,
                        "as_qs": _as_qs(request, editor)})
    return _render(request, "partials/my_queue.html", {
        "queue": build_queue_view(conn, editor),
    })


@router.get("/project/{slug}")
def page_project(slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    view = build_project_view(conn, slug)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    scope = auth.scope_for(request)
    tick_editor = _queue_editor(request)
    return _render(request, "project.html", {
        **_sidebar_context(request, conn, slug),
        "project": view,
        "presence": build_presence_view(conn, slug, editor=scope.editor),
        "selected_by": db.fetch_all_selections(conn),
        "scope_admin": scope.admin,
        "tick_editor": tick_editor,
    })


def _sidebar_context(request: Request, conn, current: str | None,
                     editor: str | None = None) -> dict:
    """Sidebar data incl. the checkbox state for the viewer's own selection
    (or the ?as=<editor> focus for admins).

    `editor` pins the target explicitly; toggle re-renders pass the editor
    from the POST path so the fragment that comes back can never disagree
    with the row that was just ticked."""
    toggle_editor = editor or _queue_editor(request)   # session user, or ?as for admins
    selected = set()
    if toggle_editor:
        selected = {s["slug"] for s in db.fetch_selections(conn, toggle_editor)}
    return {
        **_switcher_context(request, conn, current, toggle_editor),
        "view": build_projects_view(conn),
        "current_slug": current or None,
        "selected_slugs": selected,
        "toggle_editor": toggle_editor,
    }


def _switcher_context(request: Request, conn, current: str | None,
                      target: str | None) -> dict:
    """The admin-only 'ticking for <editor>' control, plus the ?as= fragment
    every self-refreshing partial on the page has to carry.

    Lives apart from _sidebar_context because the fleet page has no sidebar
    checkboxes -- there the switcher retargets the SYNC QUEUE panel instead,
    which is that page's ticking UI."""
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    others: list[str] = []
    if auth.is_admin(settings, user):
        others = sorted(
            n for n in db.known_editor_usernames(conn) if n != (user or "").lower()
        )
    return {
        # `switch_action` is the PAGE the form returns to -- never
        # request.url.path, which is /partials/sidebar when this context is
        # built for the 30s refresh.
        "switch_editors": others,
        "switch_action": f"/project/{current}" if current else "/",
        "acting_as": target if target and user
                     and target.lower() != user.lower() else None,
        "as_qs": _as_qs(request, target),
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
    tick_editor = _queue_editor(request)
    return _render(request, "partials/project_detail.html", {
        "project": view,
        "selected_by": db.fetch_all_selections(conn),
        "tick_editor": tick_editor,
        "as_qs": _as_qs(request, tick_editor),
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


def _create_or_update_editor_sync(
    truenas: TrueNASClient, username: str, ssh_pubkey: str,
    full_name: str | None, password: str | None,
) -> dict:
    """Runs on a threadpool worker -- see partial_admin_create_user. TrueNAS
    job polling (_wait_for_job) blocks on time.sleep() for up to ~2 minutes."""
    result = truenas.create_or_update_editor(username, ssh_pubkey, full_name)
    if password:
        truenas.set_known_password(username, password)
    return result


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
                                 base_url=settings.truenas_base_url or None,
                                 verify_ssl=settings.truenas_verify_ssl)
        try:
            # Blocking TrueNAS REST calls + job polling -- push off the event
            # loop so a slow TrueNAS response can't stall every other
            # request for up to ~2 minutes (see the ui.py blocking-handlers
            # finding).
            result = await run_in_threadpool(
                _create_or_update_editor_sync, truenas, username, ssh_pubkey, full_name, password
            )
            if result["warnings"]:
                error = f"{username}: created with warnings ({'; '.join(result['warnings'])})"
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
    elif not is_valid_username(username):
        # Same charset gate as the create form: a typo (or a hand-posted
        # "root") must never reach TrueNAS. set_known_password refuses system
        # and non-editor accounts too -- this is the cheap first pass.
        error = ("username must start with a letter and contain only lowercase letters, "
                 "digits, '.', '_', '-'")
    elif not password:
        error = "password required"
    else:
        truenas = TrueNASClient(settings.truenas_host, settings.truenas_user, settings.truenas_pw,
                                 base_url=settings.truenas_base_url or None,
                                 verify_ssl=settings.truenas_verify_ssl)
        try:
            # See the ui.py blocking-handlers finding: blocking TrueNAS call
            # off the event loop.
            await run_in_threadpool(truenas.set_known_password, username, password)
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
        syncthing = SyncthingClient.from_settings(settings)
        try:
            # See the ui.py blocking-handlers finding: blocking Syncthing
            # REST call off the event loop.
            await run_in_threadpool(syncthing.approve_device, device_id, username)
        except SyncthingError as exc:
            error = str(exc)

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings),
        "error": error,
    })


# --------------------------------------------------------- installer download

# The [ INSTALLER ] header link. Serves the CURRENT kind='onboard' package
# (onboard.exe on Windows; on macOS the zipped onboarding wizard since
# installer 1.0.17, or the Terminal bootstrap script on older rows) -- the
# full clean-install/repair package, NOT the bare companion exe.
# Session-gated by app.py's login_gate like every other page: a new editor
# signs in here with the same TrueNAS credentials the wizard itself will ask
# for. Downloading to the local disk is the supported path -- running
# onboard.exe off the NAS share locks the file for everyone and is refused
# by the wizard itself.

def _detect_platform(user_agent: str) -> str:
    ua = user_agent.lower()
    if "mac os" in ua or "macintosh" in ua:
        return "macos"
    # Anything unrecognized falls back to windows: the fleet is Windows-first
    # and /download/macos stays reachable directly.
    return "windows"


@router.get("/download")
def page_download(request: Request):
    plat = _detect_platform(request.headers.get("user-agent", ""))
    return RedirectResponse(f"/download/{plat}", status_code=303)


@router.get("/download/{platform}")
def page_download_platform(
    platform: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    platform = platform.strip().lower()
    if platform not in ("windows", "macos"):
        return PlainTextResponse("unknown platform -- use /download/windows or /download/macos",
                                 status_code=404)
    settings = request.app.state.settings
    row = db.get_current_package(conn, platform, kind="onboard")
    if row is None:
        if platform == "macos":
            hint = ("on the Mac:\n"
                    "  ./tools/build_onboard_macos.sh --publish --make-current")
        else:
            hint = ("from the base rig:\n"
                    "  .\\installer\\build_editor_package.ps1 -Publish -MakeCurrent")
        return PlainTextResponse(
            f"no {platform} installer is published yet. Publish one {hint}",
            status_code=404,
        )
    path = settings.packages_path() / row["platform"] / row["filename"]
    if not path.is_file():
        return PlainTextResponse("installer file is missing on the server -- re-publish it",
                                 status_code=404)
    # The stored (versioned) filename is what lands in the editor's Downloads
    # folder, so "which installer did you run?" has an answer.
    return FileResponse(
        str(path),
        media_type="application/octet-stream",
        filename=row["filename"],
        headers={"X-CCSync-SHA256": row["sha256"], "X-CCSync-Version": row["version"]},
    )


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
    kind = form.get("kind", "companion").strip().lower()

    error = None
    if not db.set_current_package(conn, platform, version, kind):
        error = f"no published {platform} {kind} package {version}"
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
    kind = form.get("kind", "companion").strip().lower()

    error = None
    row = db.get_package(conn, platform, version, kind)
    if row is None:
        error = f"no published {platform} {kind} package {version}"
    elif row["is_current"]:
        error = "cannot delete the current version; make another version current first"
    else:
        db.delete_companion_package(conn, platform, version, kind)
        conn.commit()
        try:
            (settings.packages_path() / row["platform"] / row["filename"]).unlink(missing_ok=True)
        except OSError:
            pass

    return _render(request, "partials/admin_packages.html", {
        "packages": build_packages_view(conn, settings),
        "error": error,
    })
