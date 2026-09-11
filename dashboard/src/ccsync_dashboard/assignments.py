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


# The "every computer of this person" value of the machine picker (owner,
# 2026-09-11). It is the view a request with NO ?machine= already means
# everywhere else in the product (db.selections_for_machine, the tick API), so
# it needs a spelling of its own only HERE, where "not chosen yet" and "all of
# them" are two different states of the same URL. `*` and not `all`, because a
# hostname cannot contain it and a computer really could be called ALL.
MACHINE_ALL = "*"


def _assignments_view(conn: sqlite3.Connection, editor: str | None = None,
                      machine: str | None = None) -> dict[str, Any]:
    """The grid. `editor`/`machine` narrow the COLUMNS only (owner,
    2026-09-11: "if there are many many users in a company, this would be
    very unwieldy"); every cell, tick, mode control and write path is
    unchanged, and None on both keeps the whole-fleet shape the JSON-free
    callers (and this module's own tests) have always got.

    An editor of "" is how the page asks for NO columns: the picker has not
    been answered yet, and a known editor's username is never empty."""
    # Held before the loops below, which bind `editor` and `machine` of their
    # own and would otherwise leave the filter reading the LAST column built.
    want_editor, want_machine = editor, machine
    try:
        archived = db.fetch_archived_projects(conn)
        archived_unreadable = False
    except sqlite3.OperationalError:
        archived, archived_unreadable = [], True
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
    if want_editor is not None:
        columns = [c for c in columns if c["editor"] == want_editor]
    if want_machine is not None:
        columns = [c for c in columns if c["machine"] == want_machine]
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
        # UX-1 (resilience sweep 2026-08-28): the capacity preflight's two
        # numbers, rendered into the grid so a click can confirm the
        # consequence WITHOUT a round trip -- and so [ ALL ] can add a whole
        # column up before it starts writing. A project the collector has
        # never walked is absent from the map, which the browser reads as
        # "cannot say" rather than as 0 GB.
        "proxy_bytes": db.project_proxy_bytes_map(conn),
        "disk": db.machine_disk_map(conn),
        # ...and the per-COLUMN answer (dash-admin-8, 2026-08-21). base_editors
        # is true only when EVERY one of a person's machines is wired, so a
        # mixed account (wired desktop + remote laptop, which f27c181 made a
        # supported shape) had a clickable column for the wired half. The
        # write endpoints refuse it; this is what lets the grid say so first.
        "base_machine_cells": db.base_machines(conn),
        # DCORE-5 (usability sweep 2026-09-04). Nothing could remove a
        # project: a typo made a permanent row in every tick list, in this
        # grid and in the queue. [ ARCHIVE PROJECT ] is the reversible
        # answer, and the confirm has to be able to say how many editors
        # still sync the thing before it is pressed -- hence the count here
        # rather than a round trip per row.
        # dash-db-5 (2026-09-11): dash-db-2 made the five suspension/archive
        # readers RAISE on a lock instead of answering the empty value, which
        # is right where an empty answer is a fail-open (the enforce cycle).
        # This one only renders: the page it is on is where [ UNARCHIVE ]
        # lives, and a `database is locked` while the collector writes must
        # not 500 the page carrying the button. An empty list plus the strip
        # below says "could not read this right now" - never "nothing is
        # archived", which the page would otherwise state as fact.
        "archived_projects": archived,
        "archived_unreadable": archived_unreadable,
        "tick_editor_counts": {
            slug: len(set(names)) for slug, names in ticks.items()},
    }


def _machine_options(conn: sqlite3.Connection, editor: str) -> list[dict[str, str]]:
    """The computer picker's options for one person, in the order the rest of
    the product names them: the registry (oldest first), then the unassigned
    bucket when it is a real place for this person - either they have no
    computer at all yet, or they carry bucket rows a companion has not
    adopted. Never a bucket option invented beside two real computers: a tick
    written there is the legacy shape db.selections_for_machine only honours
    for a machine with no plan of its own."""
    options = [{"value": m, "label": m} for m in db.machines_of(conn, editor)]
    if not options:
        return [{"value": db.ANY_MACHINE, "label": "no computer yet"}]
    if db.selections_for_machine(conn, editor, db.ANY_MACHINE):
        options.append({"value": db.ANY_MACHINE,
                        "label": "no computer yet (ticks no computer has claimed)"})
    return options


def _picker(conn: sqlite3.Connection, editors: list[str],
            editor: str | None, machine: str | None) -> dict[str, Any]:
    """Who and which computer the page is showing, and what the two pickers
    offer. Both come from the URL so a reload, a bookmark and a link land on
    the same view.

    A machine that is not one of that person's is NOT chosen: it is what the
    browser posts when the editor was changed in the same form, and the
    honest answer is the computer picker for the new person rather than an
    empty grid for a computer they do not own."""
    chosen_editor = (editor or "").strip()
    if chosen_editor not in editors:
        # ONE editor is preselected (owner, 2026-09-11): an admin with a
        # single person must not find this page emptier than it used to be
        # for the sake of a company that has two hundred.
        chosen_editor = editors[0] if len(editors) == 1 and editor is None else ""
    options = _machine_options(conn, chosen_editor) if chosen_editor else []
    values = {o["value"] for o in options}
    chosen_machine: str | None = machine
    if chosen_machine is not None and chosen_machine != MACHINE_ALL             and chosen_machine not in values:
        chosen_machine = None
    if chosen_machine is None and chosen_editor and len(options) == 1:
        chosen_machine = options[0]["value"]
    return {
        "editors": editors,
        "editor": chosen_editor,
        "machines": options,
        "machine": chosen_machine,
        # The grid renders only when both questions have been answered.
        "show_grid": bool(chosen_editor) and chosen_machine is not None,
    }


@router.get("/admin/assignments")
def page_admin_assignments(request: Request,
                           editor: str | None = None,
                           machine: str | None = None,
                           conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    editors = sorted(db.known_editor_usernames(conn))
    picker = _picker(conn, editors, editor, machine)
    # The whole-fleet size, in one line rather than in two hundred columns:
    # what the old grid told an admin at a glance that the per-person view
    # cannot (owner, 2026-09-11).
    picker["machine_count"] = len(db.fetch_machines(conn))
    # No selection means no columns, not every column: an empty username
    # matches none of them. The projects, the archived list and the counts
    # below are the whole-fleet half of the page and are built either way.
    column_editor = picker["editor"] if picker["show_grid"] else ""
    column_machine = (None if picker["machine"] == MACHINE_ALL
                      else picker["machine"] if picker["show_grid"] else None)
    return _render(request, "admin_assignments.html", {
        **_sidebar_context(request, conn, None),
        "assignments": _assignments_view(conn, editor=column_editor,
                                         machine=column_machine),
        "picker": picker,
        "machine_all": MACHINE_ALL,
        "nav_current": "assignments",
    })
