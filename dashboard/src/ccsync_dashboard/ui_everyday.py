"""The everyday pages' server half (UI redesign port, phase 3, group
`everyday`, 2026-09-25).

docs/UI_REDESIGN_PORT_PLAN.md 5.1, 7.1 row 3 and R15. Kept out of ui.py and
account_ui.py on purpose: several builders edit those files at once during
the port.

- `/partials/person-queue`: the signed-in person's sync queue on /account.
- Two answers for `partial_toggle`: `view=person-queue` (an untick from that
  window gets that window back) and `view=none` (the account page's swap-none
  buttons: an EMPTY 200, so no other window's markup, and none of its oob
  parts, reaches the page).

Nothing ticked is never an error (owner rule): an empty queue is a plain line.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from . import auth, db, ui
from .api import build_projects_view, build_queue_view, build_transfers_view, get_conn

log = logging.getLogger("ccsync.dashboard.ui_everyday")

router = APIRouter(default_response_class=HTMLResponse)

# The views partial_toggle routes here.
TOGGLE_VIEWS = ("person-queue", "none")
# The event every account computer window's poll also listens for on body.
ACCOUNT_REFRESH_ALL = "account-refresh-all"


_render_new = ui._render


def person_queue_context(conn: sqlite3.Connection, user: str) -> dict[str, Any]:
    """The person's queue, "safe to close", and one fix-root read-out per
    remote computer. One fleet snapshot is built and handed to every queue
    view, so N computers do not cost N snapshots."""
    projects = build_projects_view(conn)
    queue = build_queue_view(conn, user, projects_view=projects)
    wired = {m for (e, m) in db.base_machines(conn) if e == user}
    fix_roots = []
    for machine in queue.get("machines") or []:
        if machine in wired:
            continue
        try:
            fix_roots.append({"machine": machine,
                              "queue": build_queue_view(conn, user, projects_view=projects,
                                                        machine=machine)})
        except Exception:  # noqa: BLE001 - one computer's read-out must not cost the window
            log.exception("person queue: fix root for %s", machine)
    transfers = build_transfers_view(conn, editor=user)
    return {"queue": queue, "fix_roots": fix_roots,
            "safe_to_close": ui.safe_to_close(transfers, user)}


def _person(request: Request) -> str:
    user = auth.get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="not logged in")
    return user.strip().lower()


@router.get("/partials/person-queue")
def partial_person_queue(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """Always the signed-in person, as /account is: `?as=` is not read."""
    user = _person(request)
    return _render_new(request, "partials/person_queue.html",
                       person_queue_context(conn, user))


def toggle_answer(request: Request, conn: sqlite3.Connection, editor: str,
                  view_kind: str):
    """What partial_toggle answers for the everyday views, after its write."""
    if view_kind == "none":
        return HTMLResponse("")
    # person-queue: the window is about the signed-in person; an admin's
    # hand-built request for somebody else gets that person's queue drawn,
    # which is what the write changed.
    response = _render_new(request, "partials/person_queue.html",
                           person_queue_context(conn, editor))
    # everyday-apps-1 (UI port review 2026-09-25): an untick from the queue
    # window changes every computer window on the page too. Without this they
    # kept showing the project (and its Untick / Upload only keys) until their
    # own 30 s poll. Each computer window's poll listens for this on body.
    response.headers["HX-Trigger"] = ACCOUNT_REFRESH_ALL
    return response
