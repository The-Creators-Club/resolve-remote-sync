"""Admin project<->editor assignment matrix (2026-08-17).

Before this, an admin could only tick projects for ONE editor at a time, via
the `?as=<editor>` editor switcher (`ui._sidebar_context` /
`partials/editor_switcher.html`) -- fine for a handful of editors, tedious
past a few, and there was no single view of who has what.

This module adds ONE additive page, `/admin/assignments`, that renders every
active project against every known editor as a grid. It deliberately owns NO
write path of its own: every cell tick/untick is a plain browser fetch straight
at the EXISTING `PUT|DELETE /api/v1/selection/{editor}/{slug}` (api.py,
`_require_selection_write` / `_require_selection_untick`), which already lets
a session belonging to an admin write ANY editor's selection --
`auth.can_manage` doesn't care whether the admin got there via `?as=` or by
naming the editor directly in the URL. So a tick in this grid IS an editor's
own tick: same table, same `_nudge_collector` reconciliation, same lane C
share / lane A/B scope / enforce-cycle consequences. There is deliberately no
second selection store and no bulk-write endpoint -- "tick all" / "untick
all" in assignments.js just replays that one write per cell, sequentially.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from . import db, health
from .api import build_editors_view, get_conn
from .ui import _render, _require_admin_page, _sidebar_context

router = APIRouter(default_response_class=HTMLResponse)


def _editor_presence(conn: sqlite3.Connection) -> dict[str, str]:
    """editor_username -> worst status (green/amber/red) across that editor's
    machines, or "" for an editor with no machine ever reported.

    Reuses build_editors_view's already-computed per-machine `status` --
    the fleet page (/) builds this exact view every load, so this is not a
    second presence query, just a regroup of one that already exists."""
    view = build_editors_view(conn)
    by_editor: dict[str, list[str]] = {}
    for m in view["editors"]:
        name = m.get("editor_username")
        if name:
            by_editor.setdefault(name, []).append(m.get("status") or "")
    return {name: health.worst(statuses) for name, statuses in by_editor.items()}


def _assignments_view(conn: sqlite3.Connection) -> dict[str, Any]:
    projects = [dict(r) for r in conn.execute(
        "SELECT slug, label FROM projects WHERE active=1 ORDER BY label"
    )]
    # Columns are EVIDENCE of an editor account (known_editors / a tick / a
    # stored pref / a companion report) -- the same source the ?as= switcher
    # uses (db.known_editor_usernames) -- never a guess, and never the admin
    # unless the admin is independently one of those things too.
    editors = sorted(db.known_editor_usernames(conn))
    ticks = db.fetch_all_selections(conn)  # slug -> [editor_username, ...]
    ticked_pairs = {(slug, e) for slug, es in ticks.items() for e in es}
    return {
        "projects": projects,
        "editors": editors,
        "ticked_pairs": ticked_pairs,
        "presence": _editor_presence(conn),
    }


@router.get("/admin/assignments")
def page_admin_assignments(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "admin_assignments.html", {
        **_sidebar_context(request, conn, None),
        "assignments": _assignments_view(conn),
        "nav_current": "assignments",
    })
