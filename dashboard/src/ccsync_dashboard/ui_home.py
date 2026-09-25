"""The home and project pages' server half (UI redesign port, phase
2, group `home`, 2026-09-25).

docs/UI_REDESIGN_PORT_PLAN.md 5.1, 7.0, 7.1 row 2 and R15. Kept out of ui.py
on purpose: several builders edit that file at once during the port, and the
home group needs a handful of things of its own.

- Routes for the home page's own windows (the projects tree, problems.log,
  what is moving, the sync queue, a computer's answer).
- The answers ui.py's shared POST routes hand back for these windows:
  a tick from the tree (`view=tree`) and an untick from the home queue
  (`view=home-queue`) in `partial_toggle`, and a dismiss from the home
  problems window (`view=home-problems`) in `partial_notice_dismiss`.
- Jinja globals the pages read on first paint: the readouts and the tree
  context, so ui.py's page handlers stay untouched.

Nothing ticked is never a warning (owner, 2026-09-11 and 2026-09-18): the
"online" readout leaves a computer with nothing ticked out of its count, and
never goes amber because of one.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from markupsafe import Markup, escape

from . import auth, db, health, notices, ui
from .api import build_projects_view, build_transfers_view, get_conn

log = logging.getLogger("ccsync.dashboard.ui_home")

router = APIRouter(default_response_class=HTMLResponse)

# The views partial_toggle and partial_notice_dismiss route here.
TOGGLE_VIEWS = ("tree", "home-queue")
DISMISS_VIEWS = {"home-problems": "partials/home_problems.html"}


_render_new = ui._render


def _signed_in(request: Request) -> str:
    user = auth.get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="sign in first")
    return user


# ------------------------------------------------------------ Jinja helpers

def cc_meter(n: Any, of: Any, cells: int = 16) -> Markup:
    """A text meter: filled blocks then a dim rest, the bench's CC.meter."""
    try:
        n_f, of_f = float(n or 0), float(of or 0)
    except (TypeError, ValueError):
        n_f, of_f = 0.0, 0.0
    full = 0
    if of_f > 0:
        full = max(0, min(cells, round(n_f / of_f * cells)))
    return Markup("█" * full + '<span class="rest">' + "░" * (cells - full)
                  + "</span>")


def lane_tone(lane: Mapping[str, Any], level: str) -> str:
    """The class a lane line draws. The ROW's headline level caps it: a
    muted headline (syncing normally, or nothing ticked) never shows a warn
    or err lane, because health.fleet_headline already decided that nothing
    on this computer is owed (5.1, wave 6)."""
    if lane.get("reported") is False:
        return "idle"
    chip = str(lane.get("chip") or "green")
    state = str(lane.get("state") or "").lower()
    if level not in ("red", "amber"):
        if chip == "green" and state in ("syncing", "running", "uploading", "downloading"):
            return "busy"
        return "ok" if chip == "green" else "idle"
    return {"green": "ok", "amber": "warn", "red": "err"}.get(chip, "idle")


def tone_of(level: str | None) -> str:
    """health's red / amber / muted as the terminal's err / warn / ''."""
    return {"red": "err", "amber": "warn"}.get(str(level or ""), "")


def _split_bytes(n: Any) -> tuple[str, str]:
    text = ui.human_bytes(n or 0)
    number, _, unit = str(text).partition(" ")
    return number, unit or ""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _owes(e: Mapping[str, Any]) -> bool:
    """Does this computer have anything ticked (so its silence matters)?

    home-project-4 (UI port review 2026-09-25): the readout asked
    `why.reason != 'no_selection'`, but why_not_syncing returns only its
    FIRST reason and a halt, a breaker, a full disk or "not signed in" rank
    above no_selection, so a computer with nothing ticked was counted whenever
    it had any other why. The row's own plan says it directly; a wired
    computer (mode base) holds no tick by design (CR-28). A row with no
    `plan` (an older caller) falls back to the why."""
    plan = e.get("plan")
    if isinstance(plan, Mapping):
        if str(e.get("mode") or "").strip().lower() == "base":
            return False
        return bool(plan.get("count"))
    return str(_mapping(e.get("why")).get("reason") or "") != "no_selection"


def _is_silent(e: Mapping[str, Any]) -> bool:
    """Has this computer stopped reporting? health._silence is the row's own
    freshness test, the one fleet_headline uses. home-project-4: reading
    `headline.reason == 'not_reporting'` missed every silent computer whose
    headline led with a fault (breaker, disk full), because fleet_headline
    returns a named fault before its silence check: an 8 h silent computer
    counted as online."""
    try:
        if health._silence(e) is not None:
            return True
    except Exception:  # noqa: BLE001 - a malformed row is judged by its headline
        pass
    return str(_mapping(e.get("headline")).get("reason") or "") == "not_reporting"


def plan_facts(conn: sqlite3.Connection, editor: str | None) -> dict[str, Any]:
    """What the "moving" and "in sync" readouts count, from the same sources
    the transfers window and sync_queue draw (home-project-5, UI port review
    2026-09-25): the transfers view (lanes A, B and C, live and queued) and
    the selections table (every tick, upload-only included). They used to
    read Syncthing folder completion alone, so the page said "moving 0 B,
    nothing waiting" and "no project is ticked anywhere" beside a transfers
    window full of moving files. `editor` is the viewer's scope (None: the
    whole fleet, an admin's view)."""
    transfers = build_transfers_view(conn, editor=editor)
    owed = 0
    moving_files = 0
    behind: set[str] = set()
    getting_ready: set[str] = set()
    for t in transfers.get("transfers") or []:
        if t.get("granularity") != "file":
            continue  # lane C's project rows are counted from the queue below
        moving_files += 1
        total, done = t.get("bytes_total"), t.get("bytes_done")
        if total is not None and done is not None:
            owed += max(0, int(total) - int(done))
    for q in transfers.get("queues") or []:
        slug = str(q.get("slug") or "")
        if q.get("pending"):
            if slug:
                getting_ready.add(slug)
            continue
        owed += int(q.get("bytes") or 0)
        if slug and (int(q.get("n_files") or 0) or int(q.get("bytes") or 0)):
            behind.add(slug)
    if editor:
        ticked = {r["slug"] for r in db.fetch_selections(conn, editor)}
    else:
        ticked = set(db.fetch_all_selections(conn))
    return {"owed_bytes": owed, "moving_files": moving_files, "behind": behind,
            "getting_ready": getting_ready, "ticked": ticked}


def _plan_facts_for(request: Request | None) -> dict[str, Any] | None:
    if request is None:
        return None
    try:
        conn = db.connect(request.app.state.settings.db_path)
        try:
            return plan_facts(conn, auth.scope_for(request).editor)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - the readouts fall back to the project view
        log.exception("could not read the transfers and ticks for the home readouts")
        return None


def home_readouts(request: Request | None, fleet: Mapping[str, Any] | None,
                  view: Mapping[str, Any] | None,
                  counts: Mapping[str, Any] | None = None,
                  facts: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The four readouts and the computers bar's meta, from what the grid
    already loads (5.1). Problems is the HUD's own count (errors, with the
    warnings as the foot), so the two can never disagree. A full page passes
    the SAME `notice_counts` its HUD draws (integrator, 2026-09-25): a second
    read could land after a collector write and show 5 beside the HUD's 6.
    `facts` (plan_facts) feeds "moving" and "in sync"; without it, and with no
    request to read it through, those two fall back to the project view."""
    fleet = fleet or {}
    view = view or {}
    if facts is None:
        facts = _plan_facts_for(request)
    editors = [e for e in (fleet.get("editors") or []) if isinstance(e, Mapping)]
    counted = [e for e in editors if _owes(e)]
    silent = [e for e in counted if _is_silent(e)]
    online = len(counted) - len(silent)
    readouts: list[dict[str, Any]] = []
    if silent:
        first = silent[0]
        foot = f"{first.get('machine') or first.get('editor_username')} not heard from"
        if len(silent) > 1:
            foot += f", and {len(silent) - 1} more"
    elif counted:
        foot = "every computer with a project ticked has reported"
    else:
        foot = "no computer has a project ticked"
    readouts.append({"k": "online", "big": str(online), "of": f"/ {len(counted)}",
                     "n": online, "total": len(counted),
                     "tone": "warn" if silent else ("ok" if counted else ""),
                     "foot": foot,
                     "tip": "Computers with a project ticked that reported in the last few "
                            "minutes, out of every computer with a project ticked. A "
                            "computer with nothing ticked is left out: it owes nothing."})
    projects = [p for p in (view.get("projects") or []) if isinstance(p, Mapping)]
    if facts is not None:
        need = int(facts.get("owed_bytes") or 0)
        behind = set(facts.get("behind") or ())
        n_files = int(facts.get("moving_files") or 0)
        if behind:
            mfoot = (f"{len(behind)} project{'s' if len(behind) != 1 else ''} "
                     "catching up")
        elif n_files:
            mfoot = f"{n_files} file{'s' if n_files != 1 else ''} moving now"
        else:
            mfoot = "nothing waiting"
    else:
        need = sum(int(p.get("need_bytes_total") or 0) for p in projects)
        catching = [p for p in projects if p.get("editors_behind")]
        behind = {str(p.get("slug") or "") for p in catching}
        mfoot = (f"{len(catching)} project{'s' if len(catching) != 1 else ''} "
                 "catching up") if catching else "nothing waiting"
    number, unit = _split_bytes(need)
    readouts.append({"k": "moving", "big": number, "of": unit, "n": 1 if need else 0,
                     "total": 1, "tone": "",
                     "foot": mfoot,
                     "tip": "How much footage is still waiting to move between the server "
                            "and the computers: files moving now and files queued behind "
                            "them, uploads and downloads."})
    is_admin = False
    if request is not None:
        try:
            settings = request.app.state.settings
            is_admin = bool(auth.is_admin(settings, auth.get_session_user(request)))
        except Exception:  # noqa: BLE001
            is_admin = False
    if is_admin:
        if not counts:
            counts = ui._notice_counts_safe(request.app.state.settings)
        err = int(counts.get("error") or 0)
        warn = int(counts.get("warn") or 0)
        if warn:
            pfoot = f"{warn} warning{'s' if warn != 1 else ''}"
        elif err:
            pfoot = "listed below with what to do"
        else:
            pfoot = "nothing needs you"
        readouts.append({"k": "problems", "big": str(err), "of": "open", "n": err,
                         "total": max(err, 10), "tone": "err" if err else "ok",
                         "foot": pfoot,
                         "tip": "Things the server found wrong that someone should look "
                                "at. Each one is listed below with what to do."})
    if facts is not None:
        ticked = set(facts.get("ticked") or ())
        view_behind = {str(p.get("slug") or "") for p in projects if p.get("editors_behind")}
        not_yet = (behind | view_behind | set(facts.get("getting_ready") or ())) & ticked
        n_ticked = len(ticked)
        in_sync = n_ticked - len(not_yet)
    else:
        ticked_rows = [p for p in projects if p.get("editors")]
        n_ticked = len(ticked_rows)
        in_sync = sum(1 for p in ticked_rows if not p.get("editors_behind"))
    readouts.append({"k": "in sync", "big": str(in_sync), "of": f"/ {n_ticked}",
                     "n": in_sync, "total": n_ticked,
                     "tone": "ok" if n_ticked and in_sync == n_ticked else "",
                     "foot": ("all caught up" if in_sync == n_ticked
                              else f"{n_ticked - in_sync} still catching up")
                     if n_ticked else "no project is ticked anywhere",
                     "tip": "Projects where every computer that ticked them has "
                            "everything, out of every ticked project."})
    collector_at = None
    collector = fleet.get("collector") if isinstance(fleet.get("collector"), Mapping) else None
    if collector:
        stamps = [k.get("finished_at") for k in (collector.get("kinds") or [])
                  if isinstance(k, Mapping) and k.get("finished_at")]
        collector_at = max(stamps) if stamps else None
    return {"readouts": readouts, "computers": len(editors),
            "collector_at": collector_at}


def tree_context(request: Request, conn: sqlite3.Connection, current: str | None,
                 editor: str | None = None, machine: str | None = None,
                 projects_view: dict | None = None) -> dict[str, Any]:
    """What `partials/projects_tree.html` draws: the project tree with ONE
    COMPUTER's ticks (or the person's when no computer is picked), the ?as=
    the page is viewed under and the computer, so the 30 s poll and a tick
    from the tree stay about the same person and the same computer (5.1,
    wave 4). A computer this person does not own is the person's view."""
    toggle_editor = editor or ui._queue_editor(request)
    machines: list[str] = []
    if toggle_editor:
        try:
            machines = list(db.machines_of(conn, toggle_editor))
        except sqlite3.Error:
            machines = []
    wanted = (machine if machine is not None
              else request.query_params.get("machine", "")) or ""
    wanted = wanted.strip()
    tree_machine = wanted if wanted in machines else ""
    selected: set[str] = set()
    upload_only: set[str] = set()
    base = False
    base_machines: set[str] = set()
    if toggle_editor:
        rows = db.fetch_selections(conn, toggle_editor, machine=tree_machine or None)
        selected = {r["slug"] for r in rows}
        if tree_machine:
            upload_only = {r["slug"] for r in rows
                           if str(r.get("sync_mode") or "") == db.SYNC_MODE_UPLOAD_ONLY}
        else:
            upload_only = {
                slug for slug, by_editor in db.fetch_all_selection_modes(conn).items()
                if by_editor.get(toggle_editor) == db.SYNC_MODE_UPLOAD_ONLY}
        base_machines = {m for (e, m) in db.base_machines(conn) if e == toggle_editor}
        base = (toggle_editor in db.base_only_editors(conn)
                or (bool(tree_machine) and tree_machine in base_machines))
    view = projects_view if projects_view is not None else build_projects_view(conn)
    total = len(view.get("projects") or [])
    return {
        **ui._switcher_context(request, conn, current, toggle_editor),
        "view": view,
        "current_slug": current or None,
        "selected_slugs": selected,
        "upload_only_slugs": upload_only,
        "toggle_editor": toggle_editor,
        "toggle_editor_base": base,
        "toggle_editor_machines": machines,
        "tree_machine": tree_machine,
        "tree_base_machines": sorted(base_machines),
        "tree_ticked": sum(1 for p in (view.get("projects") or [])
                           if p.get("slug") in selected),
        "tree_total": total,
        "tick_warning": (ui.tick_capacity_warning(conn, toggle_editor, current)
                         if toggle_editor and current else None),
    }


def home_tree(request: Request, current: str | None = None) -> dict[str, Any]:
    """First-paint tree context for the two terminal pages (a Jinja global,
    so ui.py's page handlers are untouched). Best-effort: a read that fails
    draws an empty tree rather than breaking the page."""
    try:
        conn = db.connect(request.app.state.settings.db_path)
        try:
            return tree_context(request, conn, current)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        log.exception("could not build the project tree for the terminal page")
        return {"view": {"tree": {"groups": {}, "projects": [], "slugs": []}, "projects": []},
                "selected_slugs": set(), "upload_only_slugs": set(), "tree_total": 0,
                "tree_ticked": 0, "tree_machine": "", "toggle_editor_machines": [],
                "current_slug": current, "as_qs": "", "switch_editors": []}


def home_roots(request: Request) -> dict[str, Any]:
    """First paint of the project page's project_roots window."""
    try:
        settings = request.app.state.settings
        conn = db.connect(settings.db_path)
        try:
            return ui._roots_context(conn, bool(auth.is_admin(
                settings, auth.get_session_user(request))))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        log.exception("could not read the project roots for the terminal page")
        return {"roots": {"mappings": [], "unmapped": [], "projects": [], "is_admin": False}}


def tree_label(text: Any) -> Markup:
    """A snake_case window title as a heading whose accessible name has no
    underscore (3.2, wave 6): each `_` is drawn aria-hidden with a visually
    hidden space beside it."""
    parts = str(text).split("_")
    return Markup('<span aria-hidden="true">_</span><span class="vh"> </span>').join(
        escape(p) for p in parts)


ui.templates.env.globals["home_readouts"] = home_readouts
ui.templates.env.globals["home_tree"] = home_tree
ui.templates.env.globals["home_roots"] = home_roots
ui.templates.env.globals["cc_meter"] = cc_meter
ui.templates.env.globals["cc_lane_tone"] = lane_tone
ui.templates.env.globals["cc_tone"] = tone_of
ui.templates.env.filters["cc_title"] = tree_label


# ------------------------------------------------------------ routes

@router.get("/partials/projects-tree")
def partial_projects_tree(request: Request, current: str = "",
                          conn: sqlite3.Connection = Depends(get_conn)):
    """The terminal tree's 30 s poll (home and project pages). Carries
    `machine` and `as` like the tick does (5.1, wave 4)."""
    _signed_in(request)
    return _render_new(request, "partials/projects_tree.html",
                       {"t": tree_context(request, conn, current or None)})


@router.get("/partials/home-problems")
def partial_home_problems(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """problems.log: the server's notices in the terminal home's window."""
    ui._require_admin_page(request)
    return _render_new(request, "partials/home_problems.html", ui._notices_context(conn))


@router.get("/partials/home-transfers")
def partial_home_transfers(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """Only what is moving; the queued and history halves live on /transfers."""
    _signed_in(request)
    scope = auth.scope_for(request)
    transfers = build_transfers_view(conn, editor=scope.editor)
    return _render_new(request, "partials/home_transfers.html", {
        "transfers": transfers,
        "safe_to_close": ui.safe_to_close(transfers, scope.editor),
        "scope_admin": scope.admin,
    })


def _queue_render(request: Request, conn: sqlite3.Connection, editor: str,
                  machine: str):
    transfers = build_transfers_view(conn, editor=editor)
    return _render_new(request, "partials/home_queue.html", {
        "queue": ui.build_queue_view(conn, editor, machine=machine or None),
        "queue_machine": machine,
        "safe_to_close": ui.safe_to_close(transfers, editor),
    })


@router.get("/partials/home-queue")
def partial_home_queue(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """The sync queue and its FIX DESTINATION ROOT line: one build_queue_view
    for both, so the root line costs no second queue build."""
    editor = ui._queue_editor(request)
    if editor is None:
        raise HTTPException(status_code=401, detail="not logged in")
    return _queue_render(request, conn, editor, ui._queue_machine(request, conn, editor))


@router.get("/partials/computer-answer")
def partial_computer_answer(request: Request, editor: str = "", machine: str = "",
                            conn: sqlite3.Connection = Depends(get_conn)):
    """READ THE ANSWER on the home page: a computer's stored diagnostics
    bundles (v33, SYS-7), drawn for the home window. Admin only."""
    ui._require_admin_page(request)
    editor = editor.strip().lower()
    machine = machine.strip()
    if editor or machine:
        bundles = db.fetch_diagnostics(conn, editor=editor or None,
                                       machine=machine or None, limit=5)
    else:
        bundles = db.newest_diagnostics_per_machine(conn)
    return _render_new(request, "partials/computer_answer.html", {
        "diagnostics": {"bundles": bundles, "editor": editor, "machine": machine},
        "crash_reports": len(notices.crash_files(request.app.state.settings)),
        "enforce_notes": db.enforce_notes(conn),
    })


# ------------------------------------------------------------ shared-route answers

# home-project-2 (UI port review 2026-09-25): the home page draws one plan
# twice (the projects tree and sync_queue; the project page: the tree and
# sync_plan), and each answer re-drew only its own window. The other one kept
# the old state for up to 30 s, and its confirm described the opposite of
# what the server held. Every plan answer fires this event; each of those
# bodies re-reads on it (`cc-plan-changed from:body` in its hx-trigger). The
# controls also send the state they mean (`mode=on` / `mode=off`), so a
# stale one that slips through is a no-op, never the opposite write.
PLAN_CHANGED = "cc-plan-changed"


def plan_changed(response):
    """Mark a tick/untick answer so the page's sibling plan windows re-read."""
    try:
        response.headers["HX-Trigger"] = PLAN_CHANGED
    except Exception:  # noqa: BLE001 - a response without headers is not ours to fix
        pass
    return response


def toggle_answer(request: Request, conn: sqlite3.Connection, editor: str,
                  target: str | None, view_kind: str):
    """What partial_toggle returns for a tick from the terminal tree or an
    untick from the terminal home queue (5.1): the markup of the window the
    control lives in, for the editor in the POST path and the computer the
    tree or panel was about."""
    if view_kind == "tree":
        current = request.query_params.get("slug_page") or None
        return plan_changed(_render_new(request, "partials/projects_tree.html",
                                        {"t": tree_context(request, conn, current,
                                                           editor=editor,
                                                           machine=target or "")}))
    view_machine = (request.query_params.get("queue_machine") or "").strip()
    if view_machine and view_machine not in db.machines_of(conn, editor):
        view_machine = ""
    if target is not None:
        view_machine = target
    return plan_changed(_queue_render(request, conn, editor, view_machine))


def dismiss_answer(request: Request, conn: sqlite3.Connection, view_kind: str,
                   error: str | None):
    """What partial_notice_dismiss returns for a dismiss from a terminal
    window: that window's markup."""
    return _render_new(request, DISMISS_VIEWS[view_kind],
                       ui._notices_context(conn, error))
