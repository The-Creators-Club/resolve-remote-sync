"""The personal /account page's JSON routes and the services its htmx twins
call (account page 2026-09-25, docs/ACCOUNT_PAGE_FEATURES.md sections 3 and 7).

Every write here is one of the signed-in person's OWN things: their display
name, their password, their signed-in browsers, and a settings ask for one of
their computers (or, for an admin, anyone's computer and anyone's name). The
page partials in account_ui.py call the SAME service functions below, so a
refusal is worded once and a rule is enforced once; nothing is implemented
twice.

Constraints every function here holds (the spec's invariants):

* The key is the sign-in name. A display name is a LABEL: it is never written
  into an audit actor, a session, a selection or a wire key.
* "Cannot tell" is a refusal. No session is a 401 even though the middleware
  already refuses one, because account_ui.py calls these services too and a
  service must not trust its caller to have checked.
* No secret leaves: no password (nor its length) in a log, a response or an
  audit row; a session id is shown only as its 12-character handle; an SSH
  key only as its fingerprint, never its text.
* Routes that block (the NAS, the scrypt hash, the SMB probe) are plain
  `def`, so FastAPI runs them in the threadpool.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
import unicodedata
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError

from . import api, auth, db, health, local_users, sessions, site_store
from .nas import NasError, is_valid_username
from .nas import factory as nas_factory

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

# ------------------------------------------------------------------ sentences
# Exactly as the spec words them (section 3): the page renders these into its
# one result slot, and test_account_api.py pins every one (no em dash).

SIGN_IN_FIRST = "Sign in first."

NAME_EMPTY = ("A name cannot be empty. To go back to your sign-in name, clear "
              "the box and save.")
NAME_TOO_LONG = "A name can be at most 64 characters."
NAME_BAD_CHARS = "A name cannot contain invisible or control characters."
NAME_TAKEN = "Someone else already goes by that name. Pick another."
NO_SUCH_ACCOUNT = "There is no account called {username}."

SESSIONS_NOT_RECORDED = "Signed-in browsers are not being recorded on this server."
SESSION_BAD_HANDLE = "That is not a browser on this list."
SESSION_GONE = "That browser is already signed out."
SESSION_IS_CURRENT = "That is this browser. Use Sign out instead."
SESSION_AMBIGUOUS = "Two browsers match that; use sign out the others instead."

KEYS_UNREADABLE = "The server could not be asked which keys are approved just now."

MACHINE_NOT_YOURS = "Only the person this computer belongs to, or an admin, can change it."
MACHINE_UNKNOWN = "{editor} has no computer called {machine}."
MACHINE_ONLY_THESE = ("Only these can be changed from here: whether the fleet may use "
                      "the computer, and which kinds of work it takes.")
MACHINE_BAD_KIND = "{kind} is not a kind of fleet work."
MACHINE_NOT_REPORTED = "{machine} has not reported yet."
MACHINE_TOO_OLD = ("{machine}'s CCSync is too old to change this from here. Update it, "
                   "or change it in its tray: Settings, FLEET JOBS.")
# Not worded by the spec (it names no sentence for a wrong TYPE): the plain
# words the whitelist sentence uses, so the page never shows a pydantic list.
MACHINE_BAD_ENABLED = "Let the fleet use this computer must be on or off."
MACHINE_BAD_KINDS = "The kinds of work must be a list."
# 4.8's sentence, answered on the JSON route too (account page 2026-09-25,
# review round): `[]` is "every kind" on the wire, so a script that sends it
# meaning "none" would get the opposite with no warning. "Every kind" is still
# askable, by naming every kind (stored as [] by _normalise_kinds).
MACHINE_KINDS_EMPTY = ("That is the last kind of work this computer takes. Untick Let "
                       "the fleet use this computer instead.")
# Not worded by the spec: a password field over 1024 characters or not text.
# FastAPI's own 422 would echo the typed value back in detail[].input.
PASSWORD_BAD_FIELD = "A password must be text of at most 1024 characters. Nothing changed."

# The 12-hex handle api_admin_sessions already truncates a sid to.
_HANDLE_RE = re.compile(r"^[0-9a-f]{12}$")
HANDLE_CHARS = 12


def _require_user(request: Request) -> str:
    user = auth.get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail=SIGN_IN_FIRST)
    return user.lower()


def _settings(request: Request):
    return request.app.state.settings


# ------------------------------------------------------ display-name cache
# Section 3.8. Every page render asks for the whole map (topbar, fleet grid,
# audit rows), so it is held for 30 s rather than read per render; a write
# through this module drops it at once, so the person who changed their name
# sees it on the very next page. A label must never fail a page, so any error
# is an empty map ("show the sign-in names"), never a raise.

DISPLAY_NAMES_TTL_SECONDS = 30.0
_CACHE_ATTR = "display_names_cache"
# Bumped by every invalidate. A reader that loaded the map BEFORE a write
# committed must not store it with a fresh timestamp after that write's
# invalidate, or the person who just saved a name sees the old one for 30 s
# (account page 2026-09-25, review round).
_GEN_ATTR = "display_names_generation"
_cache_lock = threading.Lock()


def display_names_for(app) -> dict[str, str]:
    state = getattr(app, "state", None)
    if state is None:
        return {}
    cached = getattr(state, _CACHE_ATTR, None)
    now = time.monotonic()
    if (isinstance(cached, tuple) and len(cached) == 2
            and now - cached[0] < DISPLAY_NAMES_TTL_SECONDS):
        return dict(cached[1])
    with _cache_lock:
        generation = getattr(state, _GEN_ATTR, 0)
    try:
        settings = getattr(state, "settings", None)
        conn = db.connect(settings.db_path)
        try:
            names = dict(db.display_names(conn))
        finally:
            conn.close()
    except Exception as exc:                                    # noqa: BLE001
        # An older database (no user_profiles table yet), a lock, a missing
        # function in a half-merged tree: every one of them is "no labels".
        log.debug("display names unavailable for this render (%s)", exc)
        return {}
    with _cache_lock:
        if getattr(state, _GEN_ATTR, 0) == generation:
            setattr(state, _CACHE_ATTR, (now, names))
    return dict(names)


def invalidate_display_names(app) -> None:
    state = getattr(app, "state", None)
    if state is None:
        return
    with _cache_lock:
        setattr(state, _GEN_ATTR, getattr(state, _GEN_ATTR, 0) + 1)
        setattr(state, _CACHE_ATTR, None)


def shown_as(names: Mapping[str, str], username: str | None) -> str:
    if not username:
        return ""
    return (names or {}).get(username) or username


# ------------------------------------------------------------- the view (3.1)

def _password_facts(settings) -> dict[str, Any]:
    method = str(getattr(settings, "auth_method", "") or "smb").strip().lower()
    where = {"smb": "server", "local": "dashboard", "oidc": "organisation"}.get(method, "server")
    oidc_host = None
    if method == "oidc":
        # The issuer's HOSTNAME only: the full URL can carry a tenant path the
        # page has no reason to publish, and the host is what a person
        # recognises ("sign in at login.example.com").
        try:
            oidc_host = urlparse(str(getattr(settings, "oidc_issuer", "") or "")).hostname or None
        except ValueError:
            oidc_host = None
    return {"changeable": method in ("smb", "local"), "where": where,
            "min_chars": auth.MIN_PASSWORD_CHARS, "oidc_host": oidc_host}


def _gpu_words(caps: Mapping[str, Any]) -> str:
    name = str(caps.get("gpu_name") or "").strip()
    if not caps.get("gpu_present") and not name:
        return ""
    vram = caps.get("gpu_vram_gb")
    try:
        vram_words = f"{float(vram):g} GB" if vram not in (None, "") else ""
    except (TypeError, ValueError):
        vram_words = ""
    return ", ".join(p for p in (name, vram_words) if p)


def _plan_rows(conn: sqlite3.Connection, editor: str, machine: str) -> list[dict[str, Any]]:
    # selections_for_machine carries the one inheritance rule (the unassigned
    # bucket) and drops a wired rig's plan (CR-28), so the page and the
    # enforce cycle cannot disagree about what this computer syncs.
    return [{"slug": r["slug"], "label": r.get("label") or r["slug"],
             "sync_mode": r.get("sync_mode") or db.SYNC_MODE_FULL}
            for r in db.selections_for_machine(conn, editor, machine)]


def _has_state_row(conn: sqlite3.Connection, editor: str, machine: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM machine_state WHERE editor_username=? AND machine=?",
        (editor, machine)).fetchone() is not None


def _request_blocked(machine: str, reported: bool, accepts: Iterable[str] | None,
                     keys: Iterable[str]) -> str:
    """Section 4.7's sentence, or "" when every key asked about is accepted.
    Capability, never a version compare (4.6): a `+dirty` build and one that
    later grows a key both answer correctly."""
    if not reported:
        return MACHINE_NOT_REPORTED.format(machine=machine)
    have = set(accepts or ())
    if not have or any(k not in have for k in keys):
        return MACHINE_TOO_OLD.format(machine=machine)
    return ""


def _settings_request_view(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {k: row.get(k) for k in ("request_id", "settings", "state", "requested_by",
                                    "requested_at", "delivered_at", "answered_at", "detail")}


def _computer_view(conn: sqlite3.Connection, user: str, viewer_can_manage: bool,
                   entry: Mapping[str, Any], settings_map: Mapping, now: str,
                   *, lost: bool = False) -> dict[str, Any]:
    machine = entry["machine"]
    key = (user, machine)
    caps = dict(entry.get("capabilities") or {})
    reported_settings = settings_map.get(key)
    if reported_settings is not None and not reported_settings.get("at"):
        # NULL cfg_at is "no companion has sent the section", never defaults.
        reported_settings = None
    accepts = list((reported_settings or {}).get("accepts") or [])
    reported = _has_state_row(conn, user, machine)
    blocked = _request_blocked(machine, reported, accepts, accepts or db.MACHINE_SETTING_KEYS)
    can_request = bool(viewer_can_manage and accepts and not blocked)
    received = entry.get("received_at") or entry.get("last_seen")
    live = False
    if not lost and received:
        live = health.report_freshness(received, now)[0] == health.GREEN
    return {
        "machine": machine,
        "platform": entry.get("platform") or "",
        "mode": entry.get("mode") or "editor",
        "companion_version": entry.get("companion_version"),
        "current_version": entry.get("current_companion_version"),
        "last_seen": received,
        "live": live,
        "lost": lost,
        "why": entry.get("why"),
        # LG-1 / LG-5 (2026-09-25, G2b hand-off 3): the grid's own entry
        # carries both (health.annotate_legal in api.build_editors_view);
        # partials/account_computer.html draws them, and absent draws nothing.
        "eula": entry.get("eula"),
        "report_withheld": list(entry.get("report_withheld") or []),
        "plan": _plan_rows(conn, user, machine),
        "jobs": {
            "enabled": caps.get("jobs_enabled") if caps else None,
            "kinds": list(caps.get("job_kinds") or []),
            "idle_seconds": caps.get("idle_seconds"),
            "volunteering": entry.get("volunteering") or {},
            "gate": dict(caps.get("jobs_gate") or {"reason": "", "detail": ""}),
            "running": entry.get("job") or None,
            "gpu": _gpu_words(caps),
        },
        "settings": reported_settings,
        "settings_request": _settings_request_view(
            db.machine_settings_request(conn, user, machine)),
        "can_request": can_request,
        "request_blocked": "" if can_request else (blocked or MACHINE_TOO_OLD.format(machine=machine)),
    }


def build_account_view(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    """The whole page's data, always about the SIGNED-IN person (`?as=` is
    never read: an admin looks after other people from Settings, Users).

    Sessions and sync keys are NOT in here: each has its own route so a slow
    NAS or a busy session store never holds the page (3.4, 3.5)."""
    user = _require_user(request)
    settings = _settings(request)
    now = db.utcnow_iso()
    display_name = db.get_display_name(conn, user)
    is_admin = auth.is_admin(settings, user, conn)
    # The computers are the fleet grid's OWN entries, filtered, so the page
    # and the grid can never disagree about a machine.
    grid = api.build_editors_view(conn, now)
    settings_map = db.machine_settings_map(conn)
    computers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in grid.get("editors") or []:
        if str(entry.get("editor_username") or "").lower() != user:
            continue
        seen.add(entry["machine"])
        computers.append(_computer_view(conn, user, True, entry, settings_map, now))
    for lost in grid.get("lost_machines") or []:
        if str(lost.get("editor_username") or "").lower() != user or lost["machine"] in seen:
            continue
        seen.add(lost["machine"])
        computers.append(_computer_view(conn, user, True, lost, settings_map, now, lost=True))
    manifest = site_store.manifest_for_app(request.app, settings) or {}
    features = manifest.get("features") or {}
    return {
        "user": user,
        "display_name": display_name,
        "shown_as": display_name or user,
        "is_admin": is_admin,
        "admin_source": auth.admin_source(settings, user) if is_admin else "",
        "auth_method": str(getattr(settings, "auth_method", "") or "smb").strip().lower(),
        "password": _password_facts(settings),
        "account": {"suspended": user in db.suspended_editors(conn)},
        "computers": computers,
        "site": {"canonical_prefix": manifest.get("canonical_prefix") or "P:\\",
                 "auto_update": bool(features.get("auto_update")),
                 "youtube_download": bool(features.get("youtube_download")),
                 "fleet_halt": bool(db.get_fleet_halt(conn).get("active"))},
        # Never here: only /login and the password change return one (3.3).
        "csrf": None,
    }


@router.get("/me/account")
def api_me_account(request: Request, conn: sqlite3.Connection = Depends(api.get_conn)) -> dict[str, Any]:
    return build_account_view(request, conn)


# ------------------------------------------------------ display names (3.2)

class DisplayNameIn(BaseModel):
    # 256 BEFORE normalising: the 64-character rule is applied to the
    # normalised text, where it can be worded; this cap only stops a megabyte.
    display_name: str = Field(default="", max_length=256)


def _other_usernames(conn: sqlite3.Connection, settings, subject: str) -> set[str]:
    """Every sign-in name a display name must not impersonate (D-4), minus the
    subject's own (you may go by your own sign-in name)."""
    names: set[str] = set(db.known_editor_usernames(conn))
    try:
        names |= {str(r[0]).lower() for r in conn.execute("SELECT username FROM users")}
    except sqlite3.OperationalError:
        pass                                  # no local accounts table on this site
    names |= {str(u).lower() for u in (getattr(settings, "admin_users", None) or ())}
    names |= {str(u).lower() for u in db.display_names(conn)}
    names.discard(subject)
    return names


def _name_refusal(text: str) -> str:
    """Which of the three 422 sentences applies. Worked out here from the text
    rather than taken from str(DisplayNameError) so the words the page shows
    are the spec's exactly, whatever db.py's own wording is."""
    collapsed = " ".join(unicodedata.normalize("NFC", text).split())
    if not collapsed:
        return NAME_EMPTY
    if len(collapsed) > db.DISPLAY_NAME_MAX_CHARS:
        return NAME_TOO_LONG
    return NAME_BAD_CHARS


def _write_display_name(request: Request, conn: sqlite3.Connection, *, actor: str,
                        subject: str, text: str, action: str) -> dict[str, Any]:
    settings = _settings(request)
    before = db.get_display_name(conn, subject)
    now = db.utcnow_iso()
    if text == "":
        # "" is a CLEAR (back to the sign-in name); only whitespace is "empty".
        if before is None:
            return {"ok": True, "display_name": None}
        db.clear_display_name(conn, subject)
        after: str | None = None
    else:
        try:
            name = db.normalise_display_name(text)
        except db.DisplayNameError as exc:
            said = str(exc)
            detail = said if said in (NAME_EMPTY, NAME_TOO_LONG, NAME_BAD_CHARS) else _name_refusal(text)
            raise HTTPException(status_code=422, detail=detail) from None
        if name == before:
            return {"ok": True, "display_name": before}
        others = _other_usernames(conn, settings, subject)
        if db.display_name_taken(conn, subject, name, others):
            raise HTTPException(status_code=409, detail=NAME_TAKEN)
        try:
            after = db.set_display_name(conn, subject, name, by=actor, now=now,
                                        other_usernames=others)
        except db.DisplayNameError:
            # set_display_name re-normalises and re-checks (DisplayNameTaken);
            # the text already passed normalising above, so what is left is a
            # name taken between the two reads.
            conn.rollback()
            raise HTTPException(status_code=409, detail=NAME_TAKEN) from None
    # Audit BEFORE the commit so the row lands in the same transaction as the
    # change (db.audit's contract). Actor is always a SIGN-IN name.
    db.audit(conn, actor, action, subject, {"before": before, "after": after}, now=now)
    conn.commit()
    invalidate_display_names(request.app)
    return {"ok": True, "display_name": after}


def set_own_display_name(request: Request, conn: sqlite3.Connection,
                         display_name: str) -> dict[str, Any]:
    user = _require_user(request)
    return _write_display_name(request, conn, actor=user, subject=user,
                               text=str(display_name or ""),
                               action=db.AUDIT_ACCOUNT_DISPLAY_NAME)


def _account_known(conn: sqlite3.Connection, settings, username: str) -> bool:
    if username in db.known_editor_usernames(conn):
        return True
    try:
        if local_users.get_user(conn, username) is not None:
            return True
    except sqlite3.OperationalError:
        pass
    if username in {str(u).lower() for u in (getattr(settings, "admin_users", None) or ())}:
        return True
    return db.get_display_name(conn, username) is not None


def set_user_display_name(request: Request, conn: sqlite3.Connection, username: str,
                          display_name: str) -> dict[str, Any]:
    """An admin sets or clears someone else's name (D-5), from Settings, Users."""
    # The spec's 401 sentence first: _require_admin's own is "log in first",
    # and account_ui calls this service without the middleware in between.
    _require_user(request)
    admin = api._require_admin(request)
    subject = str(username or "").strip().lower()
    if not is_valid_username(subject) or not _account_known(conn, _settings(request), subject):
        raise HTTPException(status_code=404, detail=NO_SUCH_ACCOUNT.format(username=subject or username))
    return _write_display_name(request, conn, actor=admin.lower(), subject=subject,
                               text=str(display_name or ""), action=db.AUDIT_USER_DISPLAY_NAME)


@router.put("/me/display-name")
def api_me_display_name(payload: DisplayNameIn, request: Request,
                        conn: sqlite3.Connection = Depends(api.get_conn)) -> dict[str, Any]:
    return set_own_display_name(request, conn, payload.display_name)


@router.put("/admin/users/{username}/display-name")
def api_admin_user_display_name(username: str, payload: DisplayNameIn, request: Request,
                                conn: sqlite3.Connection = Depends(api.get_conn)) -> dict[str, Any]:
    return set_user_display_name(request, conn, username, payload.display_name)


# ------------------------------------------------- change your password (3.3)

class ChangePasswordIn(BaseModel):
    current_password: str = Field(default="", max_length=1024)
    new_password: str = Field(default="", max_length=1024)
    new_password_again: str = Field(default="", max_length=1024)


def change_password(request: Request, response: Response, conn: sqlite3.Connection, *,
                    current_password: str, new_password: str,
                    new_password_again: str) -> dict[str, Any]:
    """Section 3.3: the service both the JSON route and the page partial call.

    Steps 2-8 (and the audit row) are group B's `change_own_password`; this is
    step 1, step 9 (every browser signed out, THIS one re-issued a fresh
    cookie: D-1, D-2), the commit and the answer. Nothing typed is logged."""
    from . import account_password           # group B's module (3.3.1)

    user = _require_user(request)
    result = account_password.change_own_password(
        request, conn, user, current_password, new_password, new_password_again)
    if not result.ok:
        headers = auth.throttle_headers(result.retry_after) if result.status == 429 else None
        conn.rollback()
        raise HTTPException(status_code=result.status, detail=result.detail, headers=headers)
    # The password HAS changed by here; rotate never raises and answers None
    # when the revocation could not run (logged by B).
    # (change_own_password already wrote the audit row and the warning log
    # line, counting the other sessions before they are revoked.)
    others = account_password.rotate_after_password_change(request, response, user)
    conn.commit()
    # The token is minted AFTER start_session, so it belongs to the NEW
    # session: the old page's token would 403 on the next write.
    return {"ok": True, "method": result.method, "other_sessions_signed_out": others,
            "csrf": auth.csrf_token(request)}


def _password_body(body: Any) -> ChangePasswordIn:
    """Validate by hand, not as a FastAPI body parameter: the framework's 422
    carries `detail[].input`, which for an over-long or wrongly typed field is
    the TYPED PASSWORD (account page 2026-09-25, review round; /api/v1/login
    has the same shape). The answer here is one sentence and names no value."""
    if not isinstance(body, Mapping):
        raise HTTPException(status_code=422, detail=PASSWORD_BAD_FIELD)
    try:
        return ChangePasswordIn.model_validate(dict(body))
    except ValidationError:
        raise HTTPException(status_code=422, detail=PASSWORD_BAD_FIELD) from None


@router.post("/me/password")
def api_me_password(request: Request, response: Response, body: Any = Body(default=None),
                    conn: sqlite3.Connection = Depends(api.get_conn)) -> dict[str, Any]:
    _require_user(request)            # a 401 before any word about the body
    payload = _password_body(body)
    return change_password(request, response, conn,
                           current_password=payload.current_password,
                           new_password=payload.new_password,
                           new_password_again=payload.new_password_again)


# -------------------------------------------- your signed-in browsers (3.4)

def _store_or_503(request: Request) -> sessions.SessionStore:
    store = auth.session_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail=SESSIONS_NOT_RECORDED)
    return store


def _live(store: sessions.SessionStore, row: Mapping[str, Any], now: str) -> bool:
    """list_for_user returns every unrevoked row, including ones past their
    idle or absolute lifetime that no request has swept yet. Those are not
    "signed in" and must not be offered a SIGN OUT."""
    try:
        idle = db.age_seconds(row["last_seen"], now)
        age = db.age_seconds(row["created_at"], now)
    except (ValueError, TypeError, KeyError):
        return False
    return (idle <= getattr(store, "idle_seconds", float("inf"))
            and age <= getattr(store, "absolute_seconds", float("inf")))


def _own_live_rows(request: Request, store: sessions.SessionStore, user: str) -> list[dict]:
    now = db.utcnow_iso()
    return [r for r in store.list_for_user(user) if _live(store, r, now)]


def list_own_sessions(request: Request, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    user = _require_user(request)
    store = _store_or_503(request)
    current = auth.get_session_id(request) or ""
    out = []
    for row in _own_live_rows(request, store, user):
        client = sessions.describe_client(row.get("client") or "")
        out.append({
            # Never the whole sid: a keyed digest that cannot be replayed, but
            # there is no reason to publish it (api_admin_sessions' rule).
            "handle": str(row["sid"])[:HANDLE_CHARS],
            "ip": client.get("ip") or "",
            "browser": client.get("browser") or "",
            "created_at": row.get("created_at"),
            "last_seen": row.get("last_seen"),
            "current": bool(current) and row["sid"] == current,
        })
    return {"sessions": out}


def revoke_own_session(request: Request, conn: sqlite3.Connection, handle: str) -> dict[str, Any]:
    user = _require_user(request)
    handle = str(handle or "")
    if not _HANDLE_RE.match(handle):
        raise HTTPException(status_code=422, detail=SESSION_BAD_HANDLE)
    store = _store_or_503(request)
    current = auth.get_session_id(request) or ""
    # Matched among THIS person's live rows only: another person's session
    # with the same prefix is never touched, nor even acknowledged.
    matches = [r for r in _own_live_rows(request, store, user)
               if str(r["sid"]).startswith(handle)]
    if not matches:
        raise HTTPException(status_code=404, detail=SESSION_GONE)
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail=SESSION_AMBIGUOUS)
    if current and matches[0]["sid"] == current:
        # D-13: signing out THIS browser is the Sign out button's job.
        raise HTTPException(status_code=409, detail=SESSION_IS_CURRENT)
    try:
        revoked = store.revoke_by_handle(user, handle, by=f"self:{user}",
                                         except_sid=current or None)
    except ValueError as exc:
        # The store re-checks under its lock; its two refusals are ours too.
        detail = SESSION_IS_CURRENT if str(exc) == "current" else SESSION_AMBIGUOUS
        raise HTTPException(status_code=409, detail=detail) from None
    if not revoked:
        raise HTTPException(status_code=404, detail=SESSION_GONE)
    db.audit(conn, user, db.AUDIT_ACCOUNT_SIGNOUT_ONE, user, {"handle": handle})
    conn.commit()
    log.info("%r signed out one of their own browsers (%s)", user, handle)
    return {"ok": True, "revoked": int(revoked)}


def revoke_own_other_sessions(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    user = _require_user(request)
    store = _store_or_503(request)
    current = auth.get_session_id(request)
    if not current:
        # Cannot tell which browser is this one, so "all but this one" cannot
        # be honoured; refuse rather than sign the person out of this page.
        raise HTTPException(status_code=503, detail=SESSIONS_NOT_RECORDED)
    # The count is of LIVE other browsers, the ones the list showed: revoke_user
    # also closes expired-but-unswept rows, and "signed out 3" after a list of
    # one reads as a lie (account page 2026-09-25, review round). Capped by what
    # the store actually revoked, in case one was signed out in between.
    live_others = sum(1 for r in _own_live_rows(request, store, user) if r["sid"] != current)
    revoked = store.revoke_user(user, by=f"self:{user} (sign out others)", except_sid=current)
    shown = min(int(revoked), live_others)
    db.audit(conn, user, db.AUDIT_ACCOUNT_SIGNOUT_OTHERS, user, {"revoked": shown})
    conn.commit()
    log.info("%r signed out %d of their other browsers", user, shown)
    return {"ok": True, "revoked": shown}


@router.get("/me/sessions")
def api_me_sessions(request: Request) -> dict[str, Any]:
    return list_own_sessions(request)


@router.post("/me/sessions/revoke-others")
def api_me_sessions_revoke_others(request: Request,
                                  conn: sqlite3.Connection = Depends(api.get_conn)) -> dict[str, Any]:
    return revoke_own_other_sessions(request, conn)


@router.post("/me/sessions/{handle}/revoke")
def api_me_session_revoke(handle: str, request: Request,
                          conn: sqlite3.Connection = Depends(api.get_conn)) -> dict[str, Any]:
    return revoke_own_session(request, conn, handle)


# --------------------------------------------------------- your sync keys (3.5)

_COMMENT_MAX_CHARS = 64
# DSM cannot show key text without an SSH session; its row says only this.
_DSM_INSTALLED_MARKER = "(installed)"


def _key_comment(line: str) -> str:
    parts = str(line or "").strip().split()
    return " ".join(parts[2:])[:_COMMENT_MAX_CHARS] if len(parts) > 2 else ""


def _approved_machine_by_fingerprint(conn: sqlite3.Connection, user: str) -> dict[str, str | None]:
    """fingerprint -> the machine named on the NEWEST approve of it. fetch_audit's
    subject filter is a substring match over three columns, so the rows are
    filtered again on the exact subject here."""
    out: dict[str, str | None] = {}
    for row in db.fetch_audit(conn, limit=1000, subject=user, actions=("ssh_key.approve",)):
        if str(row.get("subject") or "") != user:
            continue
        detail = row.get("detail") or {}
        fp = str(detail.get("fingerprint") or "")
        if fp and fp not in out:                      # newest first
            out[fp] = str(detail.get("machine") or "") or None
    return out


def build_sync_keys_view(settings, conn: sqlite3.Connection, user: str) -> dict[str, Any]:
    """Read-only (D-12): adding, approving and removing keys stay on the Users
    page, because removing a key stops that computer's upload and download.
    `key_text` is never in the answer, only fingerprints and comments."""
    user = str(user or "").strip().lower()
    keys: list[dict[str, Any]] = []
    for row in db.fetch_pending_ssh_keys(conn, user):
        keys.append({"fingerprint": row.get("fingerprint") or "", "state": "waiting",
                     "machine": row.get("machine") or None, "comment": "",
                     "at": row.get("submitted_at")})
    installed_unknown = False
    unreadable = ""
    method = str(getattr(settings, "auth_method", "") or "smb").strip().lower()
    if method == "local":
        try:
            rows = local_users.keys_for(conn, user)
        except sqlite3.OperationalError:
            rows = []
        for row in rows:
            keys.append({"fingerprint": row.get("fingerprint") or "", "state": "approved",
                         "machine": row.get("label") or None,
                         "comment": _key_comment(row.get("key_text") or ""),
                         "at": row.get("added_at")})
    elif method == "smb" and nas_factory.nas_configured(settings):
        # smb ONLY (spec 3.5): an oidc site's people are not NAS accounts, so
        # a NAS lookup there answers about someone else or nobody.
        try:
            nas = nas_factory.make_nas_client(settings)
            found = nas.find_user(user)
        except NasError as exc:
            # The NAS's own text is logged, never shown: a response body is
            # not an editor's sentence and may carry backend detail.
            log.warning("sync keys for %r: the NAS could not be asked (%s)", user, exc)
            found = None
            unreadable = KEYS_UNREADABLE
        except Exception as exc:                                # noqa: BLE001
            # Anything else (a client that cannot be built, a TypeError in a
            # backend) is the same "could not be asked", not a 500. Only the
            # type is logged: an arbitrary exception's text is not vetted.
            log.warning("sync keys for %r: the NAS lookup failed (%s)", user,
                        type(exc).__name__)
            found = None
            unreadable = KEYS_UNREADABLE
        text = str((found or {}).get("sshpubkey") or "")
        if text.strip() == _DSM_INSTALLED_MARKER:
            installed_unknown = True
        elif text:
            machines = _approved_machine_by_fingerprint(conn, user)
            for line in text.splitlines():
                line = line.strip()
                # api._install_nas_key_keeping_others' rule: a key line has a
                # type AND a body; a comment or a one-field marker is not one.
                if not line or line.startswith("#") or len(line.split()) < 2:
                    continue
                try:
                    fp = local_users.pubkey_fingerprint(line)
                except local_users.LocalUserError:
                    continue
                keys.append({"fingerprint": fp, "state": "approved",
                             "machine": machines.get(fp), "comment": _key_comment(line),
                             "at": None})
    mine = db.machines_of(conn, user)
    wired = db.base_machines(conn)
    # "none, and none needed": a wired rig syncs nothing. A person with no
    # computers yet still needs a key for the first one.
    needed = not mine or not all((user, m) in wired for m in mine)
    return {"keys": keys, "installed_unknown": installed_unknown,
            "unreadable": unreadable, "needed": needed}


@router.get("/me/sync-keys")
def api_me_sync_keys(request: Request,
                     conn: sqlite3.Connection = Depends(api.get_conn)) -> dict[str, Any]:
    user = _require_user(request)
    return build_sync_keys_view(_settings(request), conn, user)


# ----------------------------- ask a computer to change its settings (3.6)

def _normalise_kinds(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise HTTPException(status_code=422, detail=MACHINE_BAD_KINDS)
    if not value:
        # 4.8: "none" cannot be sent, and [] would be read as EVERY kind.
        raise HTTPException(status_code=422, detail=MACHINE_KINDS_EMPTY)
    out: list[str] = []
    for kind in value:
        if not isinstance(kind, str) or kind not in db.JOB_KINDS:
            raise HTTPException(status_code=422, detail=MACHINE_BAD_KIND.format(kind=kind))
        if kind not in out:
            out.append(kind)
    # Every kind is stored as [] ("every kind"), the settings window's own
    # rule, so the two spellings of "all" can never disagree on the wire.
    if set(out) >= set(db.JOB_KINDS):
        return []
    return [k for k in db.JOB_KINDS if k in out]


def _running_kinds(caps: Mapping[str, Any]) -> list[str] | None:
    """The running kinds in the stored spelling, or None for "cannot tell".
    A kind this dashboard does not know (a newer companion) is "cannot tell":
    dropping it would answer "unchanged" to an ask that WOULD change the
    computer (account page 2026-09-25, review round)."""
    raw = caps.get("job_kinds")
    if not isinstance(raw, list) or any(k not in db.JOB_KINDS for k in raw):
        return None
    return [] if set(raw) >= set(db.JOB_KINDS) else sorted(set(raw))


def _check_machine(request: Request, conn: sqlite3.Connection, editor: str,
                   machine: str) -> tuple[str, str, str]:
    user = _require_user(request)
    editor = str(editor or "").strip().lower()
    machine = str(machine or "").strip()     # exact otherwise: never NFC (spec invariants)
    if not auth.can_manage(_settings(request), user, editor):
        raise HTTPException(status_code=403, detail=MACHINE_NOT_YOURS)
    if machine not in db.machines_of(conn, editor):
        raise HTTPException(status_code=404,
                            detail=MACHINE_UNKNOWN.format(editor=editor, machine=machine))
    return user, editor, machine


def ask_machine_settings(request: Request, conn: sqlite3.Connection, editor: str,
                         machine: str, body: Mapping[str, Any] | None) -> dict[str, Any]:
    """F5: ask ONE computer to change `jobs_enabled` / `jobs_kinds`. It is
    delivered as `commands.machine_settings` on that computer's next report
    and takes effect when CCSync next starts there (D-8). Wired or remote is
    NEVER requestable (CR-88): `mode` is outside the whitelist and 422s."""
    user, editor, machine = _check_machine(request, conn, editor, machine)
    if not isinstance(body, Mapping):
        raise HTTPException(status_code=422, detail=MACHINE_ONLY_THESE)
    asked = dict(body)
    if not asked or any(k not in db.MACHINE_SETTING_KEYS for k in asked):
        raise HTTPException(status_code=422, detail=MACHINE_ONLY_THESE)
    wanted: dict[str, Any] = {}
    if "jobs_enabled" in asked:
        if not isinstance(asked["jobs_enabled"], bool):
            raise HTTPException(status_code=422, detail=MACHINE_BAD_ENABLED)
        wanted["jobs_enabled"] = asked["jobs_enabled"]
    if "jobs_kinds" in asked:
        wanted["jobs_kinds"] = _normalise_kinds(asked["jobs_kinds"])
    key = (editor, machine)
    reported = _has_state_row(conn, editor, machine)
    reported_settings = db.machine_settings_map(conn).get(key) or {}
    blocked = _request_blocked(machine, reported, reported_settings.get("accepts"), wanted)
    if blocked:
        raise HTTPException(status_code=409, detail=blocked)
    pending = db.machine_settings_request(conn, editor, machine)
    if not (pending and pending.get("state") == "pending"):
        caps = db.machine_capabilities(conn, editor, machine)
        on_disk_differs = reported_settings.get("pending_restart") or {}
        same = bool(caps)
        for k, v in wanted.items():
            if k in on_disk_differs:
                same = False
            elif k == "jobs_enabled" and caps.get("jobs_enabled") is not v:
                # A missing or non-bool value is "cannot tell", never False.
                same = False
            elif k == "jobs_kinds":
                running = _running_kinds(caps)
                if running is None or running != sorted(v):
                    same = False
        if same:
            # Nothing to ask: running AND on disk already say this.
            return {"ok": True, "unchanged": True}
    row = db.request_machine_settings(conn, editor, machine, wanted,
                                      requested_by=user, now=db.utcnow_iso())
    if row is None:
        conn.rollback()
        raise HTTPException(status_code=404,
                            detail=MACHINE_UNKNOWN.format(editor=editor, machine=machine))
    conn.commit()
    log.info("%r asked %s/%s to change %s", user, editor, machine, sorted(wanted))
    return {"ok": True, "request": row}


def withdraw_machine_settings(request: Request, conn: sqlite3.Connection, editor: str,
                              machine: str) -> dict[str, Any]:
    user, editor, machine = _check_machine(request, conn, editor, machine)
    withdrawn = db.withdraw_machine_settings_request(conn, editor, machine,
                                                     by=user, now=db.utcnow_iso())
    conn.commit()
    return {"ok": True, "withdrawn": bool(withdrawn)}


@router.post("/machines/{editor}/{machine}/settings")
def api_machine_settings_ask(editor: str, machine: str, request: Request,
                             body: Any = Body(default=None),
                             conn: sqlite3.Connection = Depends(api.get_conn)) -> dict[str, Any]:
    return ask_machine_settings(request, conn, editor, machine, body)


@router.delete("/machines/{editor}/{machine}/settings")
def api_machine_settings_withdraw(editor: str, machine: str, request: Request,
                                  conn: sqlite3.Connection = Depends(api.get_conn)) -> dict[str, Any]:
    return withdraw_machine_settings(request, conn, editor, machine)
