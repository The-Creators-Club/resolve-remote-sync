"""Data-subject routes: export a person's data, and erase their history while
keeping their account (LG-2 and LG-3, docs/LEGAL_GAP_FEATURES_PLAN.md
sections 4.2 and 4.3, 2026-09-25).

    POST /api/v1/admin/users/{username}/export         admin, any person
    POST /api/v1/me/export                             the signed-in person
    POST /api/v1/admin/users/{username}/erase-history  admin
    POST /partials/admin/users/erase-history           the Users panel's twin

Constraints the plan's audits put on these (safety M8, correctness H7):

* POST only, and none is CSRF-exempt: an export is a copy of someone's
  records and a GET would let any page that can make the browser load a URL
  start one. The two buttons are plain forms carrying the hidden `csrf` field
  (app.csrf_gate reads it), because a download cannot come back through htmx.
* `/me/export` takes the subject from the SESSION (auth.get_session_user),
  never from auth.Scope: an admin's Scope.editor is None ("everyone") and
  `?as=` would change who the file is about.
* One export at a time per person, and at most EXPORTS_PER_HOUR per person
  per hour (429), keyed on the SUBJECT: it bounds how often one person's
  whole history is read however many admins ask. The person's own copy
  (/me/export) counts in a bucket of its own, so admins cannot use up
  someone's right to their own file, and only an export that was actually
  handed over counts (G3 review round, point 7). The file is encoded in
  memory and refused as soon as it passes MAX_EXPORT_BYTES (413) rather than
  streamed half-way.
* Every export and every erase writes a fleet_audit row carrying COUNTS
  only: the audit ledger outlives the person's history and must not become a
  second copy of it.
* Erase never touches current state (decision D15): db.purge_subject_history
  deletes the `history` kind only, and the confirm step says what stays.
"""
from __future__ import annotations

import collections
import datetime as dt
import html
import logging
import sqlite3
import threading
import time
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from . import api, auth, db, subject_data
from .nas import is_valid_username

log = logging.getLogger(__name__)

router = APIRouter()

AUDIT_USER_EXPORT = "user.export"
AUDIT_USER_ERASE_HISTORY = "user.erase_history"

MAX_EXPORT_BYTES = 50 * 1024 * 1024
EXPORTS_PER_HOUR = 5
_HOUR = 3600.0

# Sentences a person reads (HTTP detail and the Users panel): no em dashes.
SIGN_IN_FIRST = "Sign in first."
ADMINS_ONLY = "Only an admin can do this for another person."
BAD_NAME = "That is not a user name this dashboard can hold."
NO_SUCH_PERSON = "This dashboard holds nothing about {username}."
EXPORT_BUSY = "An export of {username}'s data is already being made. Try again when it has finished."
EXPORT_TOO_OFTEN = ("{username}'s data has been exported {n} times in the last hour. "
                    "Try again later.")
EXPORT_TOO_LARGE = ("The export of {username}'s data is larger than {mb} MB, so it was not "
                    "made. Erase their history first, or ask for a copy by other means.")
# The person cannot erase their own history, and most of a large file is
# current state that erase keeps, so they get a sentence they can act on.
EXPORT_TOO_LARGE_SELF = ("Your data is larger than {mb} MB, so the file was not made. Ask an "
                         "admin for a copy by other means.")
BACK_TO = "Go back"


# ------------------------------------------------------------------ gates

def _session_user(request: Request) -> str:
    user = auth.get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail=SIGN_IN_FIRST)
    return str(user).lower()


def _admin(request: Request) -> str:
    _session_user(request)
    return api._require_admin(request, ADMINS_ONLY).lower()


def _subject(username: str) -> str:
    user = str(username or "").strip().lower()
    if not user or not is_valid_username(user):
        raise HTTPException(status_code=400, detail=BAD_NAME)
    return user


def _known(request: Request, conn: sqlite3.Connection, user: str) -> bool:
    """Someone the dashboard has an account for, that the fleet knows (an
    editor with no account still has computers and history: the Users page's
    EDITORS WITHOUT AN ACCOUNT), or about whom any store holds a row.

    The last clause is G3 review round point 6 (2026-09-25): a NAS account
    made on the NAS directly that never reported is in none of the first
    lists, yet its sign-ins leave auth_sessions, login_attempts and
    fleet_audit rows, and "This dashboard holds nothing about X" was false.
    404 now means exactly that sentence."""
    from . import account_api

    try:
        if account_api._account_known(conn, request.app.state.settings, user):
            return True
    except sqlite3.Error:
        pass
    try:
        if conn.execute("SELECT 1 FROM machines WHERE editor_username = ? LIMIT 1",
                        (user,)).fetchone() is not None:
            return True
    except sqlite3.Error:
        pass
    try:
        if any(db.fetch_subject_rows(conn, user).values()):
            return True
    except sqlite3.Error:
        pass
    store = auth.session_store(request)
    rows_of = getattr(store, "subject_rows", None) if store is not None else None
    if rows_of is not None:
        try:
            return any((rows_of(user) or {}).values())
        except Exception:                                           # noqa: BLE001
            log.debug("subject_data_api: session store did not answer", exc_info=True)
    return False


# ------------------------------------------------------------ rate limit

class _ExportGate:
    """In memory, per app: a restart forgets the counts, which only ever
    makes the gate more lenient for one hour, and the dashboard is one
    worker. Kept on app.state so each test app starts empty."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running: set[str] = set()
        # (subject, "self" | "admin") -> stamps of exports handed over.
        self.recent: dict[tuple[str, str], collections.deque[float]] = {}

    def enter(self, user: str, bucket: str = "admin") -> None:
        now = time.monotonic()
        with self.lock:
            if user in self.running:
                raise HTTPException(status_code=429, detail=EXPORT_BUSY.format(username=user),
                                    headers={"Retry-After": "30"})
            stamps = self.recent.setdefault((user, bucket), collections.deque())
            while stamps and now - stamps[0] >= _HOUR:
                stamps.popleft()
            if len(stamps) >= EXPORTS_PER_HOUR:
                wait = max(1, int(_HOUR - (now - stamps[0])))
                raise HTTPException(
                    status_code=429,
                    detail=EXPORT_TOO_OFTEN.format(username=user, n=len(stamps)),
                    headers={"Retry-After": str(wait)})
            self.running.add(user)

    def done(self, user: str, bucket: str = "admin") -> None:
        # Stamped only once the file is built and audited: a 413 or a 500
        # handed nothing over and must not use up the hour (review point 7).
        with self.lock:
            self.recent.setdefault((user, bucket), collections.deque()).append(
                time.monotonic())

    def leave(self, user: str) -> None:
        with self.lock:
            self.running.discard(user)


def _gate(request: Request) -> _ExportGate:
    state = request.app.state
    gate = getattr(state, "subject_export_gate", None)
    if gate is None:
        gate = _ExportGate()
        state.subject_export_gate = gate
    return gate


# ----------------------------------------------------------------- export

def _is_plain_form(request: Request) -> bool:
    ctype = request.headers.get("content-type", "").lower()
    return ctype.startswith(("application/x-www-form-urlencoded", "multipart/form-data"))


def _refusal_page(status: int, detail: str, back: str) -> HTMLResponse:
    # A plain-form download that is refused would otherwise leave the browser
    # on a bare {"detail": ...} JSON page (review point 7). Same status code,
    # the same sentence, and a way back to the page the button was on.
    return HTMLResponse(
        status_code=status,
        content=('<!doctype html><html><head><meta charset="utf-8"><title>CC Sync</title>'
                 "</head><body><p>" + html.escape(detail) + '</p><p><a href="'
                 + html.escape(back, quote=True) + '">' + html.escape(BACK_TO)
                 + "</a></p></body></html>"),
        headers={"Cache-Control": "no-store"})


def export_response(request: Request, conn: sqlite3.Connection, actor: str,
                    subject: str) -> Response:
    gate = _gate(request)
    own = actor == subject
    bucket = "self" if own else "admin"
    gate.enter(subject, bucket)
    try:
        data = subject_data.collect(conn, subject, session_store=auth.session_store(request),
                                    dashboard_version=api.VERSION)
        try:
            body = subject_data.to_json_bytes(data, max_bytes=MAX_EXPORT_BYTES)
        except subject_data.ExportTooLarge:
            mb = MAX_EXPORT_BYTES // (1024 * 1024)
            raise HTTPException(status_code=413, detail=(
                EXPORT_TOO_LARGE_SELF.format(mb=mb) if own
                else EXPORT_TOO_LARGE.format(username=subject, mb=mb)))
        tallies = subject_data.counts(data)
        db.audit(conn, actor, AUDIT_USER_EXPORT, subject,
                 {"tables": tallies, "rows": sum(tallies.values()), "bytes": len(body)})
        conn.commit()
        gate.done(subject, bucket)
    finally:
        gate.leave(subject)
    date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    return Response(
        content=body, media_type="application/json",
        headers={"Content-Disposition":
                 f'attachment; filename="ccsync-data-{subject}-{date}.json"',
                 "Cache-Control": "no-store"})


@router.post("/api/v1/admin/users/{username}/export")
def api_admin_user_export(username: str, request: Request,
                          conn: sqlite3.Connection = Depends(api.get_conn)) -> Response:
    admin = _admin(request)
    try:
        subject = _subject(username)
        if not _known(request, conn, subject):
            raise HTTPException(status_code=404, detail=NO_SUCH_PERSON.format(username=subject))
        return export_response(request, conn, admin, subject)
    except HTTPException as exc:
        if exc.status_code in (401, 403) or not _is_plain_form(request):
            raise
        return _refusal_page(exc.status_code, str(exc.detail), "/admin/users")


@router.post("/api/v1/me/export")
def api_me_export(request: Request,
                  conn: sqlite3.Connection = Depends(api.get_conn)) -> Response:
    user = _session_user(request)
    try:
        return export_response(request, conn, user, user)
    except HTTPException as exc:
        if exc.status_code in (401, 403) or not _is_plain_form(request):
            raise
        return _refusal_page(exc.status_code, str(exc.detail), "/account")


# ------------------------------------------------------------------ erase

def erase_history(request: Request, conn: sqlite3.Connection, username: str) -> dict[str, Any]:
    """The service both erase routes call. Order (plan 4.3, buildability M2):
    the dashboard database first and committed, THEN the session store,
    which opens its own connection to the same file and must not wait on
    this one's write lock, then the YouTube ledger. The audit row is written
    last so it records what was actually removed from every store."""
    admin = _admin(request)
    subject = _subject(username)
    if not _known(request, conn, subject):
        raise HTTPException(status_code=404, detail=NO_SUCH_PERSON.format(username=subject))

    removed: dict[str, int] = {k: int(v) for k, v in
                               db.purge_subject_history(conn, subject).items()}
    conn.commit()
    not_done: list[str] = []

    store = auth.session_store(request)
    purge = getattr(store, "purge_user", None) if store is not None else None
    if purge is None:
        not_done.append("sessions")
    else:
        try:
            _add_counts(removed, "sessions", purge(subject, revoked_only=True))
        except Exception:                                           # noqa: BLE001
            log.warning("erase-history %s: session purge failed", subject, exc_info=True)
            not_done.append("sessions")

    forget = _ytdl_forget_history()
    if forget is None:
        not_done.append("ytdl")
    else:
        try:
            result = forget(subject)
        except Exception:                                           # noqa: BLE001
            log.warning("erase-history %s: YouTube history failed", subject, exc_info=True)
            not_done.append("ytdl")
        else:
            # G4 answers {"status", "detail", "counts"}. The first build fed
            # the envelope to _add_counts, which recorded `ytdl.detail: 0`,
            # dropped the counts, and read a failed erase as done (review
            # point 2). "absent" is a store with nothing to erase; "error" is
            # not done, with the detail in the log and not in the audit row.
            if isinstance(result, dict) and isinstance(result.get("status"), str):
                if result["status"] == "error":
                    log.warning("erase-history %s: YouTube history not erased: %s",
                                subject, result.get("detail"))
                    not_done.append("ytdl")
                else:
                    _add_counts(removed, "ytdl", result.get("counts") or {})
            else:
                _add_counts(removed, "ytdl", result)

    db.audit(conn, admin, AUDIT_USER_ERASE_HISTORY, subject,
             {"removed": removed, "rows": sum(removed.values()), "not_done": not_done})
    conn.commit()
    return {"ok": True, "username": subject, "removed": removed,
            "rows": sum(removed.values()), "not_done": not_done}


def _ytdl_forget_history():
    try:
        from . import ytdl
    except Exception:                                               # noqa: BLE001
        return None
    return getattr(ytdl, "forget_history", None)


def _add_counts(into: dict[str, int], prefix: str, result: Any) -> None:
    """The other stores' helpers answer table -> count (or one number)."""
    if isinstance(result, dict):
        for table, n in result.items():
            try:
                into[f"{prefix}.{table}"] = int(n or 0)
            except (TypeError, ValueError):
                continue
    elif isinstance(result, int) and not isinstance(result, bool):
        into[prefix] = result


@router.post("/api/v1/admin/users/{username}/erase-history")
def api_admin_user_erase_history(username: str, request: Request,
                                 conn: sqlite3.Connection = Depends(api.get_conn)) -> dict[str, Any]:
    return erase_history(request, conn, username)


# ----------------------------------------------------------- Users panel

def _erase_notice(out: dict[str, Any]) -> str:
    rows = int(out.get("rows") or 0)
    text = (f"Erased {rows} past record{'' if rows == 1 else 's'} about {out['username']}. "
            "Their account and their computers' current state are unchanged.")
    if out.get("not_done"):
        text += " Some stores could not be reached; press it again later."
    return text


@router.post("/partials/admin/users/erase-history")
async def partial_admin_user_erase_history(request: Request,
                                           conn: sqlite3.Connection = Depends(api.get_conn)):
    """The Users panel's [ ERASE HISTORY ]: re-renders the panel with the
    answer as its notice or error line, as every other control there does."""
    from .api import build_admin_users_view
    from .ui import MAX_FORM_FIELDS, _render

    _admin(request)
    try:
        form = parse_qs((await request.body()).decode(), keep_blank_values=True,
                        max_num_fields=MAX_FORM_FIELDS)
    except ValueError:
        raise HTTPException(status_code=400, detail="malformed form body")
    username = (form.get("username") or [""])[-1]
    error = notice = None
    try:
        out = await run_in_threadpool(erase_history, request, conn, username)
    except HTTPException as exc:
        if exc.status_code in (401, 403):
            raise
        error = str(exc.detail)
    else:
        notice = _erase_notice(out)
    # build_admin_users_view asks the NAS, so it stays off the event loop
    # (the same note account_ui.partial_admin_user_display_name carries).
    users_view = await run_in_threadpool(build_admin_users_view,
                                         request.app.state.settings, conn)
    return _render(request, "partials/admin_users.html", {
        "admin_users": users_view, "error": error, "notice": notice,
    })
