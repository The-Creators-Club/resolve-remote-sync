"""The terminal Health group's server half (UI redesign port, phase 5,
2026-09-25). docs/UI_REDESIGN_PORT_PLAN.md 1.3, 1.5, 5.3, 7.1 row 5, R15.

Kept out of ui.py on purpose: several builders edit that file at once during
the port, and Health needs only three small routes of its own.

The terminal Health page carries the three panels the classic look draws on
the home page (problems the server found, the collector, what the computers
said) as TABS. Their markup lives under NEW names, so the classic home that
still fetches `partials/notices.html`, `collector_health.html` and
`admin_diagnostics.html` can never be handed terminal markup (R15, 7.0):

- ``GET /partials/health-notices`` and ``POST
  /partials/health-notices/{id}/dismiss``: the notices panel and its dismiss,
  which answers with ``health_notices`` markup (never ``notices``).
- ``GET /partials/health-collector``: the collector's cycles and the pending
  share diff. Classic builds this context inside the fleet grid; here it is
  its own route (the plan's "BACKEND, small").
- ``GET /partials/health-diagnostics``: with no parameters, the newest bundle
  per computer (``db.newest_diagnostics_per_machine``, as the classic route);
  ``editor``/``machine`` narrow it to one computer's last five.

Each answers 404 whenever ``settings-health`` is not in the asking page's
resolved set (the templates exist only under ``templates/cc/``), and all four
are admin only, as their classic twins are.

``cc_unbracket`` is a Jinja filter for Python-built button labels that still
carry the classic ``[ LABEL ]`` shape (``db.notice_href``, the Health rows'
``detail_label``) until phase 7's copy sweep rewrites them: the terminal look
draws no bracket on a control.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from jinja2 import TemplateNotFound

from . import db, notices, ui, ui_variant
from .api import get_conn

router = APIRouter(default_response_class=HTMLResponse)

GROUP = "settings-health"


def cc_unbracket(value) -> str:
    """"[ TAKE ME THERE ]" -> "take me there"; anything else unchanged."""
    text = str(value or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
        if text.isupper():
            text = text.lower()
    return text


ui.templates.env.filters.setdefault("cc_unbracket", cc_unbracket)
ui_variant.sync_envs()


def _render_health(request: Request, name: str, context: dict):
    try:
        return ui._render(request, name, context)
    except TemplateNotFound:
        raise HTTPException(status_code=404,
                            detail="not part of this page's look") from None


def _require_group(request: Request) -> None:
    """For a WRITE: refuse before anything changes when the asking page's
    look has no Health group, so a dismiss is never committed behind a 404."""
    res = ui_variant.resolve(request)
    if GROUP not in res.groups:
        raise HTTPException(status_code=404, detail="not part of this page's look")


@router.get("/partials/health-notices")
def partial_health_notices(request: Request,
                           conn: sqlite3.Connection = Depends(get_conn)):
    ui._require_admin_page(request)
    return _render_health(request, "partials/health_notices.html",
                          ui._notices_context(conn))


@router.post("/partials/health-notices/{notice_id}/dismiss")
def partial_health_notice_dismiss(notice_id: int, request: Request,
                                  conn: sqlite3.Connection = Depends(get_conn)):
    """The classic dismiss (ui.partial_notice_dismiss), answering with the
    terminal panel. Only hidden: db.notice() reopens it on the next cycle
    that still sees the problem."""
    admin = ui._require_admin_page(request)
    _require_group(request)
    row = db.dismiss_notice(conn, notice_id, admin)
    conn.commit()
    error = None if row else "that notice is already gone. Reload the page."
    return _render_health(request, "partials/health_notices.html",
                          ui._notices_context(conn, error))


@router.get("/partials/health-collector")
def partial_health_collector(request: Request,
                             conn: sqlite3.Connection = Depends(get_conn)):
    """The collector panel on its own (classic draws it inside the fleet
    grid from `fleet.collector`, which is db.collector_health too)."""
    ui._require_admin_page(request)
    return _render_health(request, "partials/health_collector.html", {
        "collector": db.collector_health(conn),
        "enforce_notes": db.enforce_notes(conn),
    })


@router.get("/partials/health-diagnostics")
def partial_health_diagnostics(request: Request, editor: str = "", machine: str = "",
                               conn: sqlite3.Connection = Depends(get_conn)):
    """ui.partial_admin_diagnostics' data, terminal markup, its own window."""
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
