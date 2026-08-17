"""HTML routes and htmx partials. All view data comes from api.py's builders
so the JSON API and the pages can never disagree."""
from __future__ import annotations

import datetime as dt
import logging
import secrets
import sqlite3
from pathlib import Path

from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth, db, local_users, oidc, provision
from .api import (
    build_admin_users_view, build_editors_view, build_packages_view, build_presence_view,
    build_project_view, build_projects_view, build_queue_view, build_report_tokens_view,
    build_transfers_view, get_conn, normalize_device_id,
)
# The fleet-read redaction the JSON API applies, imported under a name that
# says where the rule lives: ONE definition, two callers (COMMERCIAL_READINESS.md
# §C L1, 2026-08-17). See api.py's "scoping fleet reads" block.
from .api import _scope_editors_view as api_scope_editors_view
from .api import _scope_projects_view as api_scope_projects_view
from .nas import NasBackend, NasError, is_valid_username, looks_like_ssh_pubkey
from .nas import factory as nas_factory
from .syncthing_client import SyncthingClient, SyncthingError

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

router = APIRouter(default_response_class=HTMLResponse)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

log = logging.getLogger("ccsync.dashboard.ui")

# ONE message for every way a sign-in can be refused (2026-08-17,
# COMMERCIAL_READINESS.md item 15). "bad username or password" vs "too many
# attempts" vs "you are not an admin" is a username-and-role oracle for anyone
# who can reach the login page; the difference goes to the log, not the page.
_LOGIN_REFUSED = "sign-in refused -- check your username and password, then try again"


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
    # Every template gets it, because every partial can contain a form and a
    # partial re-rendered into the page must carry a live token (base.html puts
    # it on <body> as hx-headers, so htmx sends it on every request from the
    # page; partials/topbar.html republishes it for the mounted SPAs). "" for
    # an anonymous render -- there is no session to protect yet.
    context.setdefault("csrf_token", auth.csrf_token(request))
    # BRAND (2026-08-17, COMMERCIAL_READINESS.md item 10). The topbar used to
    # read "CREATORS CLUB" as a literal, in this template and in the three
    # SPAs' fallback headers. It is site data now, and the fallback chain is
    # org_short -> org_name -> product_name: an unbranded install shows the
    # PRODUCT's name, never the first customer's.
    context.setdefault("brand_org", (settings.site_org_short
                                     or settings.site_org_name
                                     or settings.site_product_name))
    context.setdefault("brand_product", settings.site_product_name)
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
    # ...and for the YouTube downloader (ytdl.MOUNTED only). Same rule a third
    # time: absent tree or unusable YTDL_DATA_ROOT means no nav link.
    context.setdefault("ytdl_mounted", getattr(request.app.state, "ytdl_mounted", False))
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
    # ONE snapshot for both panels: the sidebar and the queue each used to
    # build the whole thing (collector status + lanes + the N+1 fetch_projects)
    # from their own `now`, so one page render was ~2x the queries and the two
    # panels could disagree by construction (DASH-6, 2026-08-14).
    projects_view = build_projects_view(conn)
    context = {
        # _sidebar_context, not a bare view: the every-30s /partials/sidebar
        # refresh has always rendered the checkboxes, so building this page's
        # first paint without them made the sidebar sprout controls 30s in.
        **_sidebar_context(request, conn, None, projects_view=projects_view),
        # Scoped: an editor sees their own machines plus the summary counts,
        # an admin sees the fleet (COMMERCIAL_READINESS.md L1, 2026-08-17).
        "fleet": api_scope_editors_view(build_editors_view(conn),
                                        auth.scope_for(request)),
        "queue": build_queue_view(conn, queue_editor, projects_view=projects_view)
                 if queue_editor else None,
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


def _login_context(request: Request, next_path: str, error: str | None,
                   local: bool) -> dict:
    settings = request.app.state.settings
    sso = str(settings.auth_method or "").strip().lower() == "oidc"
    return {
        "error": error,
        "next_path": next_path,
        # With OIDC configured the password form is BREAK-GLASS only: hidden
        # behind ?local=1 and, when it is shown, restricted to DASH_ADMIN_USERS
        # (see page_login_submit). An IdP outage must not lock the operator out
        # of their own dashboard; it must not quietly reopen password login for
        # the whole fleet either.
        "sso_enabled": sso,
        "show_password_form": (not sso) or local,
        "sso_url": f"{oidc.LOGIN_PATH}?next={quote(next_path, safe='')}",
        "local_url": f"/login?local=1&next={quote(next_path, safe='')}",
    }


@router.get("/login")
def page_login(request: Request):
    next_path = _safe_next(request.query_params.get("next", ""))
    if auth.get_session_user(request):
        return RedirectResponse(next_path, status_code=303)
    settings = request.app.state.settings
    if auth.refuse_plaintext_login(settings, request):
        # DASH_COOKIE_SECURE=1 says the cookie only ever crosses TLS; serving
        # the form on a plain-http connection under that promise sends the
        # password in clear AND has the browser drop the cookie afterwards, so
        # the editor loops on this page with no error anywhere (2026-08-17,
        # COMMERCIAL_READINESS.md item 6).
        raise HTTPException(
            status_code=400,
            detail="this dashboard is configured for https only (DASH_COOKIE_SECURE=1) "
                   "but you reached it over http -- use the https URL",
        )
    local = request.query_params.get("local", "") == "1"
    return _render(request, "login.html", _login_context(request, next_path, None, local))


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
    local = request.query_params.get("local", "") == "1" or form.get("local", "") == "1"
    sso = str(settings.auth_method or "").strip().lower() == "oidc"
    error = None
    if not settings.session_secret:
        error = "login not configured on the server (DASH_SESSION_SECRET unset)"
    elif auth.refuse_plaintext_login(settings, request):
        error = ("this dashboard is configured for https only (DASH_COOKIE_SECURE=1) "
                 "-- use the https URL")
    elif auth.login_throttled(request, username):
        # One generic message for every refusal below, including this one: a
        # throttle that says "wait 4 minutes" for real usernames and "bad
        # password" for made-up ones is a username oracle.
        error = _LOGIN_REFUSED
    elif sso and not auth.is_admin(settings, username):
        # Break-glass is for the operator, not a password back door for the
        # fleet. Same generic message, so it does not disclose who is an admin.
        log.warning("local password login refused for non-admin %r while "
                    "DASH_AUTH_METHOD=oidc", username)
        auth.record_login_failure(request, username)
        error = _LOGIN_REFUSED
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
                auth.clear_login_failures(request, username)
                response = RedirectResponse(next_path, status_code=303)
                # Mints the cookie AND the revocable server-side session row;
                # see auth.start_session (cookie flags: Secure per
                # auth.cookie_secure, HttpOnly, SameSite=Lax).
                auth.start_session(request, response, username)
                log.info("login for %r from %s", username, auth.client_ip(request))
                return response
            auth.record_login_failure(request, username)
            error = _LOGIN_REFUSED
    return _render(request, "login.html", _login_context(request, next_path, error, local))


@router.post("/logout")
def page_logout(request: Request):
    response = RedirectResponse("/", status_code=303)
    # Revokes the server-side row too: deleting the browser's copy alone left
    # a stolen cookie valid for the rest of its lifetime (item 6 / H1).
    auth.end_session(request, response)
    return response


@router.post("/logout-everywhere")
def page_logout_everywhere(request: Request):
    """"Sign me out on every device." The one thing an editor who thinks their
    laptop was taken can do without waiting for an admin."""
    user = auth.get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="not logged in")
    store = auth.session_store(request)
    revoked = store.revoke_user(user, by=f"self:{user}") if store else 0
    log.warning("%r revoked %d session(s) from every device", user, revoked)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return response


@router.get("/partials/topbar")
def partial_topbar(request: Request, current: str = ""):
    """The shared header, fetched by the mounted SPAs (/broll, /music) so their
    pages carry the dashboard's real topbar -- session, admin links, nav --
    instead of a hand-copied imitation that drifts. `current` names the nav
    entry for the page doing the fetching; anything unrecognized simply
    highlights nothing. No view is passed, so the staleness stamp and the
    Syncthing banner stay off -- this render answers 'who am I and where can I
    go', not 'is the fleet healthy'."""
    return _render(request, "partials/topbar.html",
                   {"nav_current": current.strip().lower()})


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
    form = await _form(request)          # field-capped like every other partial (DASH-3)
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
            # Per-CHILD try, not the outer one: this probe only decides a
            # link's label, and it used to be able to end the whole listing.
            # One unreadable sibling (0700 from a hand-copy under another uid,
            # or an ESTALE/EIO from the NFS-backed /projects mount) raised out
            # to the OSError handler below, so every alphabetically later
            # folder silently vanished from the picker AND can_link_current
            # went false -- the editor lost both the folder they came for and
            # [ USE THIS FOLDER ] (DASH-5, 2026-08-14).
            has_children = False
            if slug is None:
                try:
                    has_children = any(
                        g.is_dir() and not g.name.startswith(".") for g in child.iterdir()
                    )
                except OSError:
                    pass   # unreadable: it just doesn't get the "drill in" label
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
                     editor: str | None = None,
                     projects_view: dict | None = None) -> dict:
    """Sidebar data incl. the checkbox state for the viewer's own selection
    (or the ?as=<editor> focus for admins).

    `editor` pins the target explicitly; toggle re-renders pass the editor
    from the POST path so the fragment that comes back can never disagree
    with the row that was just ticked.

    `projects_view` is the same snapshot-sharing hatch build_queue_view has --
    the fleet page renders both off one build (DASH-6, 2026-08-14)."""
    toggle_editor = editor or _queue_editor(request)   # session user, or ?as for admins
    selected = set()
    if toggle_editor:
        selected = {s["slug"] for s in db.fetch_selections(conn, toggle_editor)}
    return {
        **_switcher_context(request, conn, current, toggle_editor),
        "view": projects_view if projects_view is not None else build_projects_view(conn),
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
    scope = auth.scope_for(request)
    return _render(request, "partials/fleet_grid.html", {
        "view": api_scope_projects_view(build_projects_view(conn), scope),
        "fleet": api_scope_editors_view(build_editors_view(conn), scope),
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
    # The file paths missing from a named person's machine. Same rule (and the
    # same 404, so no device id is confirmed) as the JSON twin api_missing.
    if not auth.scope_for(request).allows(str(editor.get("editor_username") or "")):
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
    """Parse an htmx form body. The BYTE ceiling is app.py's body_size_gate
    (every write path, not just the two it used to cover -- DASH-3); the field
    ceiling is here, because 1 MB of `a=1&a=1&...` is a cheap way to spend the
    single worker's CPU inside parse_qs. page_login_submit has capped its
    fields since it was written; these routes never did (2026-08-11)."""
    try:
        parsed = parse_qs((await request.body()).decode(), max_num_fields=MAX_FORM_FIELDS)
    except ValueError:
        raise HTTPException(status_code=400, detail="malformed form body")
    return {k: v[0] for k, v in parsed.items()}


@router.get("/admin/users")
def page_admin_users(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "admin_users.html", {
        **_sidebar_context(request, conn, None),
        "admin_users": build_admin_users_view(request.app.state.settings, conn),
        "packages": build_packages_view(conn, request.app.state.settings),
    })


@router.get("/partials/admin/users")
def partial_admin_users(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(request.app.state.settings, conn),
    })


# ------------------------------------------------- admin: browser sessions
# A separate partial and a separate route from the Users panel above, loaded by
# admin_users.html with its own hx-get. Kept apart deliberately: the Users panel
# talks to the NAS and goes amber the moment the NAS blinks (DASH-7), and
# "revoke this person's sessions" -- the thing an admin reaches for when a
# laptop goes missing -- must keep working while that is happening.

def _sessions_context(request: Request, error: str | None = None) -> dict:
    store = auth.session_store(request)
    rows = store.list_all() if store is not None else []
    for row in rows:
        # A prefix only: the full sid is a keyed digest of the cookie, and
        # while it cannot be replayed, there is no reason to print it.
        row["short_sid"] = row["sid"][:12]
    return {"sessions": rows, "error": error,
            "session_user": auth.get_session_user(request)}


@router.get("/partials/admin/sessions")
def partial_admin_sessions(request: Request):
    _require_admin_page(request)
    return _render(request, "partials/admin_sessions.html", _sessions_context(request))


@router.post("/partials/admin/sessions/revoke")
async def partial_admin_revoke_sessions(request: Request):
    """Sign somebody out everywhere. The revocation is what makes a stolen
    cookie recoverable at all -- before 2026-08-17 the only answer was to
    rotate DASH_SESSION_SECRET, which signs out the entire fleet and
    invalidates every companion identity token with it."""
    admin = _require_admin_page(request)
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    error = None
    store = auth.session_store(request)
    if not username:
        error = "username required"
    elif store is None:
        error = "sessions are not being recorded on this deployment"
    else:
        revoked = store.revoke_user(username, by=f"admin:{admin}")
        log.warning("admin %r revoked %d session(s) for %r", admin, revoked, username)
        error = f"revoked {revoked} session(s) for {username}"
    return _render(request, "partials/admin_sessions.html",
                   _sessions_context(request, error))


def _create_or_update_editor_sync(
    nas: NasBackend, username: str, ssh_pubkey: str,
    full_name: str | None, password: str | None,
) -> dict:
    """Runs on a threadpool worker -- see partial_admin_create_user. The
    TrueNAS backend's job polling (_wait_for_job) blocks on time.sleep() for
    up to ~2 minutes."""
    result = nas.create_or_update_editor(username, ssh_pubkey, full_name)
    if password:
        nas.set_known_password(username, password)
    return result


@router.post("/partials/admin/users/create")
async def partial_admin_create_user(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    admin = _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    ssh_pubkey = form.get("ssh_pubkey", "").strip()
    full_name = form.get("full_name", "").strip() or None
    password = form.get("password", "").strip() or None

    if str(settings.auth_method or "smb").strip().lower() == "local":
        # No NAS account of any kind (WP C, docs/ZERO_TOUCH_PLAN.md §3.3,
        # 2026-08-17): the same form posts here, but username/password/role
        # go into the local `users` table instead. A blank password field
        # generates a one-time one, shown back to the admin exactly once.
        role = form.get("role", "editor").strip().lower() or "editor"
        generated = None
        minted = password
        if not minted:
            minted = secrets.token_urlsafe(15)
            generated = minted
        error = None
        try:
            local_users.create_user(conn, username, minted, role, created_by=admin)
            if ssh_pubkey:
                local_users.add_ssh_key(conn, username, ssh_pubkey)
        except local_users.LocalUserError as exc:
            error = str(exc)
        else:
            db.record_known_editor(conn, username, "admin")
            conn.commit()
            if generated:
                error = f"{username}: created with a generated password: {generated}"
        return _render(request, "partials/admin_users.html", {
            "admin_users": build_admin_users_view(settings, conn),
            "error": error,
        })

    error = None
    if not nas_factory.nas_configured(settings):
        error = "DASH_NAS_PW is not configured on the dashboard"
    elif not is_valid_username(username):
        error = ("username must start with a letter and contain only lowercase letters, "
                 "digits, '.', '_', '-'")
    elif not looks_like_ssh_pubkey(ssh_pubkey):
        error = "does not look like an OpenSSH public key"
    elif password and auth.check_password(password):
        # Optional field: blank still means "randomise it, no dashboard login".
        # A SHORT one is refused -- same floor as the set-password form.
        error = auth.check_password(password)
    else:
        try:
            nas = nas_factory.make_nas_client(settings)
            # Blocking NAS REST calls + job polling -- push off the event
            # loop so a slow NAS response can't stall every other
            # request for up to ~2 minutes (see the ui.py blocking-handlers
            # finding).
            result = await run_in_threadpool(
                _create_or_update_editor_sync, nas, username, ssh_pubkey, full_name, password
            )
            # The account provably exists now -- record it so a device named
            # after it is treated as an editor rather than as an unmapped
            # machine (B16). The JSON API twin has done this since the B16 fix;
            # THIS is the route the Users page posts to, and it did not, so an
            # editor created through the UI got no known_editors row and
            # enforce shared them nothing (KNOWN_BUGS DASH-2, 2026-08-11).
            db.record_known_editor(conn, username, "admin")
            conn.commit()
            if result["warnings"]:
                error = f"{username}: created with warnings ({'; '.join(result['warnings'])})"
        except NasError as exc:
            error = str(exc)

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
    })


@router.post("/partials/admin/users/password")
async def partial_admin_set_password(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    password = form.get("password", "").strip()

    if str(settings.auth_method or "smb").strip().lower() == "local":
        error = None
        if not password:
            error = "password required"
        else:
            try:
                local_users.set_password(conn, username, password)
            except local_users.LocalUserError as exc:
                error = str(exc)
            else:
                conn.commit()
        return _render(request, "partials/admin_users.html", {
            "admin_users": build_admin_users_view(settings, conn),
            "error": error,
        })

    error = None
    if not nas_factory.nas_configured(settings):
        error = "DASH_NAS_PW is not configured on the dashboard"
    elif not is_valid_username(username):
        # Same charset gate as the create form: a typo (or a hand-posted
        # "root") must never reach the NAS. set_known_password refuses system
        # and non-editor accounts too -- this is the cheap first pass.
        error = ("username must start with a letter and contain only lowercase letters, "
                 "digits, '.', '_', '-'")
    elif not password:
        error = "password required"
    elif auth.check_password(password):
        # Floor on NEW passwords only (auth.MIN_PASSWORD_CHARS): the minimum
        # used to be one character, and this password is what an editor signs
        # into the dashboard with AND their NAS/SMB credential. Existing short
        # passwords keep working -- nobody is locked out mid-shoot
        # (2026-08-17, COMMERCIAL_READINESS.md item 15, L-tier "admin password
        # min length 1").
        error = auth.check_password(password)
    else:
        try:
            nas = nas_factory.make_nas_client(settings)
            # See the ui.py blocking-handlers finding: blocking NAS call
            # off the event loop.
            await run_in_threadpool(nas.set_known_password, username, password)
        except NasError as exc:
            error = str(exc)

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
    })


@router.post("/partials/admin/users/approve")
async def partial_admin_approve_device(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
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
        try:
            # Shape-check + uppercase BEFORE Syncthing sees it, as the JSON API
            # twin has since _DEVICE_ID_RE was added. This partial -- the only
            # approve path a human uses -- skipped it, so a truncated or
            # lowercased paste came back as a generic 502, or created a device
            # that can never connect (KNOWN_BUGS DASH-1, 2026-08-11).
            device_id = normalize_device_id(device_id)
            syncthing = SyncthingClient.from_settings(settings)
            # See the ui.py blocking-handlers finding: blocking Syncthing
            # REST call off the event loop.
            await run_in_threadpool(syncthing.approve_device, device_id, username)
            # An admin naming the device is the strongest evidence the username
            # is a real editor account (B16 / DASH-2).
            db.record_known_editor(conn, username, "admin")
            conn.commit()
        except ValueError as exc:
            error = str(exc)
        except SyncthingError as exc:
            error = str(exc)

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
    })


@router.post("/partials/admin/users/disable")
async def partial_admin_disable_user(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """Disable (or re-enable) a LOCAL account -- there is no NAS twin of this
    in scope here, same carve-out as api.api_admin_disable_user."""
    _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    disabled = form.get("disabled", "1").strip() != "0"

    error = None
    if str(settings.auth_method or "smb").strip().lower() != "local":
        error = "this action is only available with DASH_AUTH_METHOD=local"
    else:
        try:
            local_users.disable_user(conn, username, disabled)
        except local_users.LocalUserError as exc:
            error = str(exc)
        else:
            conn.commit()

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
    })


@router.post("/partials/admin/users/keys/add")
async def partial_admin_add_ssh_key(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    key_text = form.get("key_text", "").strip()
    label = form.get("label", "").strip()

    error = None
    if str(settings.auth_method or "smb").strip().lower() != "local":
        error = "this action is only available with DASH_AUTH_METHOD=local"
    else:
        try:
            local_users.add_ssh_key(conn, username, key_text, label=label)
        except local_users.LocalUserError as exc:
            error = str(exc)
        else:
            conn.commit()

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
    })


@router.post("/partials/admin/users/keys/remove")
async def partial_admin_remove_ssh_key(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    fingerprint = form.get("fingerprint", "").strip()

    error = None
    if str(settings.auth_method or "smb").strip().lower() != "local":
        error = "this action is only available with DASH_AUTH_METHOD=local"
    else:
        local_users.remove_ssh_key(conn, username, fingerprint)
        conn.commit()

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
    })


# ------------------------------------------------- per-editor report tokens
#
# COMMERCIAL_READINESS.md item 15 (2026-08-17). Its own panel and its own
# routes rather than fields bolted onto the Users partial: that partial's
# render calls a NAS backend, and minting a fleet credential must not be able
# to fail because the NAS is slow. The secret is rendered exactly once, in the
# response to the mint -- nothing stores it, so no later render can repeat it.

def _report_tokens_render(request, conn, *, error: str | None = None,
                          minted: str | None = None, minted_username: str = ""):
    return _render(request, "partials/admin_report_tokens.html", {
        "report_tokens": build_report_tokens_view(conn),
        "error": error,
        "minted": minted,
        "minted_username": minted_username,
    })


@router.get("/partials/admin/report-tokens")
def partial_admin_report_tokens(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    _require_admin_page(request)
    return _report_tokens_render(request, conn)


@router.post("/partials/admin/report-tokens/create")
async def partial_admin_create_report_token(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    admin = _require_admin_page(request)
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    label = form.get("label", "").strip()
    if not is_valid_username(username):
        return _report_tokens_render(
            request, conn,
            error=("username must start with a letter and contain only lowercase "
                   "letters, digits, '.', '_', '-'"))
    token, _row = db.create_editor_report_token(conn, username, created_by=admin,
                                                label=label)
    conn.commit()
    return _report_tokens_render(request, conn, minted=token, minted_username=username)


@router.post("/partials/admin/report-tokens/revoke")
async def partial_admin_revoke_report_token(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    admin = _require_admin_page(request)
    form = await _form(request)
    revoked = db.revoke_editor_report_token(conn, form.get("token_id", "").strip(),
                                            revoked_by=admin)
    conn.commit()
    error = None if revoked else "that token was already revoked (or never existed)"
    return _report_tokens_render(request, conn, error=error)


# ------------------------------------------------------------- fleet halt
#
# COMMERCIAL_READINESS.md item 9 (2026-08-17). One switch that stops every
# companion in the fleet, honoured on each machine's next report reply. It
# lives on the Users page rather than the fleet grid deliberately: this is an
# administrative control with a blast radius of the whole company, and the
# fleet grid is a page people leave open and click around on.
#
# The route is a thin wrapper over the same db helpers /api/v1/fleet/halt
# uses, so the button and the API can never disagree about what is stored.

def _fleet_halt_render(request, conn, *, error: str | None = None):
    return _render(request, "partials/fleet_halt.html", {
        "halt": db.get_fleet_halt(conn),
        "error": error,
    })


@router.get("/partials/admin/fleet-halt")
def partial_admin_fleet_halt(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    _require_admin_page(request)
    return _fleet_halt_render(request, conn)


@router.post("/partials/admin/fleet-halt")
async def partial_admin_set_fleet_halt(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    admin = _require_admin_page(request)
    form = await _form(request)
    active = form.get("active", "") == "1"
    reason = form.get("reason", "").strip()
    if active and not reason:
        # The reason is shown in EVERY editor's tray. A halt with no reason
        # produces a fleet of people who cannot work and cannot find out why.
        return _fleet_halt_render(
            request, conn, error="say why -- every editor's tray will show this")
    db.set_fleet_halt(conn, active, reason, admin)
    conn.commit()
    log.warning(
        "FLEET HALT %s from the Users page by %s: %s",
        "ENGAGED" if active else "released", admin, reason or "(no reason)",
    )
    return _fleet_halt_render(request, conn)


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
