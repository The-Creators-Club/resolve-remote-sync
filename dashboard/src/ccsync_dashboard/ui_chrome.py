"""The terminal chrome's server half (UI redesign port, phase 1, 2026-09-25).

docs/UI_REDESIGN_PORT_PLAN.md 3.4, 7.0 and R15. Kept out of ui.py on
purpose: several builders edit that file at once during the port, and the
chrome needs only three small things of its own.

- ``/partials/halt-line``: the fleet halt as terminal shell furniture. A NEW
  route for a NEW-named partial (``partials/halt_line.html`` exists only
  under ``templates/cc/partials/``), so it answers 404 whenever ``chrome`` is
  not in the request's resolved set, and a classic page keeps
  ``/partials/fleet-halt-banner`` and its classic markup.
- Two Jinja globals the HUD reads: ``hud_next`` (where the look-switch links
  send the reader back to) and ``hud_preview_cc`` (whether this account may
  switch its browser into the unreviewed look at all).
- ``topbar_extras``: the problem and alert counts for ``/partials/topbar``.
  ``_render`` computes them only for full pages, so the HUD injected into the
  SPAs would never show them (3.4). They travel under ``hud_*`` names so the
  classic bar, which reads ``notice_counts``, is unchanged in the SPAs.
"""
from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from jinja2 import TemplateNotFound

from . import auth, ui, ui_variant
from .api import get_conn

log = logging.getLogger("ccsync.dashboard.ui_chrome")

router = APIRouter(default_response_class=HTMLResponse)

# The SPAs fetch /partials/topbar?current=<app>, so a request-derived `next`
# would be that fragment's URL. Their own page is known by name instead.
_SPA_HOME = {"broll": "/broll/", "music": "/music/", "ytdl": "/ytdl/", "cards": "/cards/"}


def hud_next(request: Request | None, nav_current: str = "") -> str:
    """Where `/ui/preview` returns to: the SPA's own page for an injected
    bar, else this page's path and query. Always a same-site path."""
    spa = _SPA_HOME.get(str(nav_current or "").strip().lower())
    if spa:
        return spa
    if request is None:
        return "/"
    path = request.url.path or "/"
    if path.startswith("/partials/"):
        return "/"
    query = request.url.query
    return ui._safe_next(path + (f"?{query}" if query else ""))


def hud_preview_cc(request: Request | None) -> bool:
    """True when the `ui_preview` setting lets this signed-in account put its
    browser into the terminal look (3.4). Best-effort: a read that fails
    offers no link rather than breaking the bar."""
    if request is None:
        return False
    try:
        user = auth.get_session_user(request)
        if not user:
            return False
        return bool(ui_variant.preview_allowed(request.app.state.settings,
                                               request.app, user))
    except Exception:  # noqa: BLE001
        log.exception("could not decide whether to offer the new-look preview")
        return False


ui.templates.env.globals["hud_next"] = hud_next
ui.templates.env.globals["hud_preview_cc"] = hud_preview_cc
ui_variant.sync_envs()


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
    """The every-page fleet halt line on a terminal page (UX-8). Any signed-in
    user. 404 when the asking page's set has no `chrome` (R15, 7.0)."""
    if auth.get_session_user(request) is None:
        raise HTTPException(status_code=401, detail="sign in first")
    try:
        return ui._render(request, "partials/halt_line.html",
                          ui._halt_banner_context(conn))
    except TemplateNotFound:
        raise HTTPException(status_code=404, detail="not part of this page's look") from None
