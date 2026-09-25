"""The Health page's server half (UI redesign port, phase 5,
2026-09-25). docs/UI_REDESIGN_PORT_PLAN.md 1.3, 1.5, 5.3, 7.1 row 5, R15.

Kept out of ui.py on purpose: several builders edit that file at once during
the port, and Health needs only three small routes of its own.

The Health page carries the server's problems, the collector and what the
computers said as TABS, each on its own route:

- ``GET /partials/health-notices`` and ``POST
  /partials/health-notices/{id}/dismiss``: the notices panel and its dismiss.
- ``GET /partials/health-collector``: the collector's cycles and the pending
  share diff.
- ``GET /partials/health-diagnostics``: with no parameters, the newest bundle
  per computer (``db.newest_diagnostics_per_machine``); ``editor``/``machine``
  narrow it to one computer's last five.

All four are admin only.

``cc_unbracket`` is a Jinja filter for Python-built button labels that still
carry the classic ``[ LABEL ]`` shape (``db.notice_href``, the Health rows'
``detail_label``) until phase 7's copy sweep rewrites them: the terminal look
draws no bracket on a control.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from . import db, notices, ui
from .api import get_conn

router = APIRouter(default_response_class=HTMLResponse)

def cc_unbracket(value) -> str:
    """"[ TAKE ME THERE ]" -> "take me there"; anything else unchanged."""
    text = str(value or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
        if text.isupper():
            text = text.lower()
    return text


ui.templates.env.filters.setdefault("cc_unbracket", cc_unbracket)


_render_health = ui._render


@router.get("/partials/health-notices")
def partial_health_notices(request: Request,
                           conn: sqlite3.Connection = Depends(get_conn)):
    ui._require_admin_page(request)
    return _render_health(request, "partials/health_notices.html",
                          ui._notices_context(conn))


@router.post("/partials/health-notices/{notice_id}/dismiss")
def partial_health_notice_dismiss(notice_id: int, request: Request,
                                  conn: sqlite3.Connection = Depends(get_conn)):
    """The notice dismiss, answering with the Health panel. Only hidden: db.notice() reopens it on the next cycle
    that still sees the problem."""
    admin = ui._require_admin_page(request)
    row = db.dismiss_notice(conn, notice_id, admin)
    conn.commit()
    error = None if row else "that notice is already gone. Reload the page."
    resp = _render_health(request, "partials/health_notices.html",
                          ui._notices_context(conn, error))
    # settings-6 (UI port review 2026-09-25): the open findings tab (its
    # count, its list, the page head's totals) is drawn once with the page,
    # so a dismissed notice stayed counted and listed there until a reload.
    # The page re-reads those parts itself on this event (admin_health.html,
    # #health-open-list); a refused dismiss changed nothing and says so here.
    if row and resp.status_code == 200:
        resp.headers["HX-Trigger"] = HEALTH_CHANGED
    return resp


# The event a Health write answers with, so the open findings tab re-reads.
HEALTH_CHANGED = "cc-health-changed"


@router.get("/partials/health-collector")
def partial_health_collector(request: Request,
                             conn: sqlite3.Connection = Depends(get_conn)):
    """The collector panel on its own (db.collector_health)."""
    ui._require_admin_page(request)
    return _render_health(request, "partials/health_collector.html", {
        "collector": db.collector_health(conn),
        "enforce_notes": db.enforce_notes(conn),
    })


@router.get("/partials/health-diagnostics")
def partial_health_diagnostics(request: Request, editor: str = "", machine: str = "",
                               conn: sqlite3.Connection = Depends(get_conn)):
    """The stored diagnostics bundles (v33, SYS-7). ADMIN ONLY: a bundle
    names an editor's paths, their Resolve project and their tree."""
    ui._require_admin_page(request)
    editor = editor.strip().lower()
    machine = machine.strip()
    if editor or machine:
        bundles = db.fetch_diagnostics(conn, editor=editor or None,
                                       machine=machine or None, limit=5)
    else:
        bundles = db.newest_diagnostics_per_machine(conn)
    return _render_health(request, "partials/health_diagnostics.html", {
        "diagnostics": {"bundles": bundles, "editor": editor, "machine": machine},
        "crash_reports": len(notices.crash_files(request.app.state.settings)),
        "enforce_notes": db.enforce_notes(conn),
    })
