"""The terminal chrome's server half (UI redesign port, phase 1, 2026-09-25).

docs/UI_REDESIGN_PORT_PLAN.md 3.4, 7.0 and R15. Kept out of ui.py on
purpose: several builders edit that file at once during the port, and the
chrome needs only a few small things of its own.

- ``/partials/halt-line``: the fleet halt as shell furniture, on every page.
- ``/go/<panel>``: panel anchors named from Python and templates resolve
  through one table (R13), so a panel that moves between pages moves in ONE
  place.
- ``topbar_extras``: the problem and alert counts for ``/partials/topbar``.
  ``_render`` computes them only for full pages, so the HUD injected into the
  SPAs would never show them (3.4). They travel under ``hud_*`` names beside
  a full page's own ``notice_counts``.
"""
from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import auth, ui
from .api import get_conn

log = logging.getLogger("ccsync.dashboard.ui_chrome")

router = APIRouter(default_response_class=HTMLResponse)


def topbar_extras(request: Request) -> dict:
    """The counts the HUD shows, for the one fragment that is a whole bar."""
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if not user or not auth.is_admin(settings, user):
        return {}
    return {"hud_notice_counts": ui._notice_counts_safe(settings),
            "hud_alert_counts": ui._alert_counts_safe(settings)}


@router.get("/partials/halt-line")
def partial_halt_line(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """The every-page fleet halt line (UX-8). Any signed-in user."""
    if auth.get_session_user(request) is None:
        raise HTTPException(status_code=401, detail="sign in first")
    return ui._render(request, "partials/halt_line.html", ui._halt_banner_context(conn))


# R13: where each named panel lives now. Before the look switch was retired
# this table carried a source and a destination per panel and answered the
# one whose page group was on; with one look there is one answer.
GO_PANELS: dict[str, str] = {
    "notices": "/admin/health#server-notices",
    "collector": "/admin/health#fleet-collector",
    "diagnostics": "/admin/health#fleet-diagnostics",
    "admin-fleet-halt": "/admin/users#admin-fleet-halt",
    "ai-providers": "/admin/settings#ai-providers",
    "restore": "/admin/recovery#restore",
    "dashboard-update": "/admin/packages#dashboard-update",
}


def go_href(panel: str) -> str | None:
    return GO_PANELS.get(panel)


@router.get("/go/{panel}", include_in_schema=False)
def go_panel(panel: str):
    href = go_href(panel)
    if href is None:
        raise HTTPException(status_code=404, detail="no such panel")
    return RedirectResponse(href, status_code=303)
