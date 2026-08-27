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
    # COLUMNS ARE COMPUTERS since 2026-08-18 (MULTI_MACHINE_PLAN.md WP5): one
    # person can own two editing machines and give each its own plan. An
    # editor whose companion has never reported gets a single column with no
    # machine name -- the unassigned bucket, which their first report adopts.
    machine_ticks = db.fetch_machine_selections(conn)
    columns: list[dict[str, Any]] = []
    for editor in editors:
        machines = db.machines_of(conn, editor)
        if not machines:
            columns.append({"editor": editor, "machine": "", "label": editor,
                            "sub": "no computer yet"})
            continue
        for machine in machines:
            columns.append({"editor": editor, "machine": machine,
                            "label": editor, "sub": machine,
                            # The other computers this plan can be copied from
                            # -- a new machine starts empty by design, and
                            # this is the one click that fills it.
                            "siblings": [m for m in machines if m != machine]})
    ticked_cells = {
        (slug, e, m) for slug, pairs in machine_ticks.items() for e, m in pairs
    }
    # The upload-only half of a cell (docs/UPLOAD_ONLY_TICK.md): the same
    # rows, narrowed to the ticks that run lane A alone.
    upload_only_cells = {
        (slug, e, m)
        for slug, pairs in db.fetch_machine_selections(
            conn, sync_modes=(db.SYNC_MODE_UPLOAD_ONLY,)).items()
        for e, m in pairs
    }
    return {
        "projects": projects,
        "editors": editors,
        "columns": columns,
        "ticked_cells": ticked_cells,
        "upload_only_cells": upload_only_cells,
        "ticked_pairs": ticked_pairs,
        "presence": _editor_presence(conn),
        # A base rig column is READ-ONLY (CR-28): every one of that account's
        # machines works directly off the NAS tree, so a tick would sync
        # nothing and could never clear. The write endpoint refuses it; the
        # grid says so before anyone clicks.
        "base_editors": db.base_only_editors(conn),
        # ...and the per-COLUMN answer (dash-admin-8, 2026-08-21). base_editors
        # is true only when EVERY one of a person's machines is wired, so a
        # mixed account (wired desktop + remote laptop, which f27c181 made a
        # supported shape) had a clickable column for the wired half. The
        # write endpoints refuse it; this is what lets the grid say so first.
        "base_machine_cells": db.base_machines(conn),
    }


@router.get("/admin/assignments")
def page_admin_assignments(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "admin_assignments.html", {
        **_sidebar_context(request, conn, None),
        "assignments": _assignments_view(conn),
        "nav_current": "assignments",
    })
