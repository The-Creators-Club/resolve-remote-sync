"""The personal /account page and its htmx partials (account page 2026-09-25,
docs/ACCOUNT_PAGE_FEATURES.md sections 3 and 6).

Every partial here calls the SAME service function its JSON twin in
account_api.py calls; nothing is implemented twice. The page adds only
presentation: which sentence a request row earns (4.5), which tick boxes a
computer's fleet-jobs controls show, and the result line a refusal becomes.

Three rules the page depends on and a later edit must not break:

* **It is always about the signed-in person.** `?as=` is never read (the
  sidebar is pinned to the session user as well). An admin looks after other
  people from Settings, Users; the page says so and links there.
* **Expected refusals are 200 with a result fragment** (wrong password,
  throttled, name taken, too old to ask), so htmx swaps them into the slot
  beside the control. 401 and 403 stay HTTP errors: those are not something
  the reader can fix by typing.
* **The password panel is never inside a polling wrapper.** A 30 s poll would
  wipe what the editor is typing. On success the partial answers
  `HX-Redirect`, because the CSRF token in the page's `hx-headers` belonged to
  the session the change just rotated, and the next htmx request from the old
  page would 403.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from typing import Any, Mapping
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response

from . import account_api, auth, db, health
from .api import get_conn, tick_capacity_warning
from .ui import MAX_FORM_FIELDS, _render, _sidebar_context, ago

log = logging.getLogger("ccsync.dashboard.account")

router = APIRouter(default_response_class=HTMLResponse)

SIGN_IN_FIRST = "Sign in first."

# The kinds of fleet work in the words the tray's settings window uses (the
# mock's list). The CHIP labels in db.JOB_KIND_LABELS are the shape of a
# database value; a tick box is read by a person. A kind this table does not
# know yet falls back to its chip label, so a new kind still gets a box.
KIND_WORDS = {
    "whisper": "Transcribe audio (uses the graphics card)",
    "proxy-480p": "Make small preview copies of video",
    "audio-extract": "Pull the audio out of video",
    "peaks": "Draw audio waveforms",
}

# 4.8: "every kind" is `[]` on both sides, so "none" cannot be sent. The
# settings window's own sentence.
LAST_KIND = ("That is the last kind of work this computer takes. Untick Let the "
             "fleet use this computer instead.")

# ?others= is clamped: it is only ever a count this page printed itself, and a
# hand-edited URL must not be able to print a silly number.
OTHERS_MAX = 999

# 4.5 "In effect. (and the row is quiet)": how long the green acknowledgement
# stays after the computer answered before the row goes quiet. Long enough to
# be seen on the next 30 s refresh or two, short enough not to be a badge.
IN_EFFECT_SHOWS_FOR = 10 * 60


def _user(request: Request) -> str:
    user = auth.get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail=SIGN_IN_FIRST)
    return user


async def _form_lists(request: Request) -> dict[str, list[str]]:
    """The body as lists, because the kinds form repeats `jobs_kinds`. The
    field cap is ui._form's (a megabyte of `a=1&a=1` must not spend the one
    worker's CPU inside parse_qs)."""
    try:
        return parse_qs((await request.body()).decode(), keep_blank_values=True,
                        max_num_fields=MAX_FORM_FIELDS)
    except ValueError:
        raise HTTPException(status_code=400, detail="malformed form body")


def _one(form: Mapping[str, list[str]], key: str) -> str:
    values = form.get(key) or [""]
    return values[-1]


def _refusal(exc: HTTPException) -> str:
    """The sentence a service refused with, for the result slot. 401 and 403
    re-raise: the reader cannot type their way past those."""
    if exc.status_code in (401, 403):
        raise exc
    return str(exc.detail or "That did not work. Nothing changed.")


def dom_id(machine: str) -> str:
    """A stable element id for one computer's panel. Machine names are matched
    EXACTLY everywhere (they are not normalised), so they may hold spaces or
    characters an id cannot; a digest of the exact bytes keeps two names that
    differ only in those apart."""
    return "pc-" + hashlib.sha1(str(machine).encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- presentation

def request_status(pc: Mapping[str, Any]) -> dict[str, str] | None:
    """Section 4.5's line for a computer's settings request, or None when the
    row says nothing worth a line (withdrawn, or no request at all)."""
    req = pc.get("settings_request") or None
    if not req:
        return None
    machine = str(pc.get("machine") or "")
    state = str(req.get("state") or "")
    detail = str(req.get("detail") or "")
    if state == "pending":
        if detail:
            return {"tone": "amber", "text": f"{machine} could not save it yet and will "
                                             f"try again: {detail}"}
        if not req.get("delivered_at"):
            return {"tone": "muted", "text": f"Asked {ago(req.get('requested_at'))}. "
                                             f"{machine} gets it the next time it reports in."}
        return {"tone": "muted", "text": f"Sent to {machine} {ago(req.get('delivered_at'))}. "
                                         "Waiting for its answer."}
    if state == "applied":
        asked = req.get("settings") or {}
        waiting = (pc.get("settings") or {}).get("pending_restart") or {}
        saved = {"tone": "muted", "text": f"{machine} saved it. It takes effect the next "
                                          "time CCSync starts there."}
        if any(k in waiting for k in asked):
            return saved
        # Spec 4.4/4.5 (account page 2026-09-25, review round): "In effect."
        # only once the RUNNING value matches what was asked. `applied` means
        # written to config.toml; a companion that sends no pending_restart
        # (or a report that has not caught up yet) must not read as in effect.
        # Not matching, or not reported, keeps the saved line: never claim
        # more than the computer has told us.
        if not _running_matches(pc, asked):
            return saved
        # "...and the row is quiet": the green line is an acknowledgement, not
        # a permanent badge. It shows for a short while after the answer and
        # then the row says nothing, like a withdrawn request.
        if not _recent(req.get("answered_at"), IN_EFFECT_SHOWS_FOR):
            return None
        return {"tone": "green", "text": "In effect."}
    if state == "refused":
        return {"tone": "red", "text": f"{machine} refused: {detail}"}
    if state == "expired":
        return {"tone": "amber", "text": f"{machine} did not report in for 14 days, so the "
                                         "request was dropped."}
    return None


def _every_kind(kinds: Any) -> bool:
    return not kinds or set(kinds) >= set(db.JOB_KINDS)


def _running_matches(pc: Mapping[str, Any], asked: Mapping[str, Any]) -> bool:
    """Whether every key the request asked for is what the computer RUNS now
    (capabilities: jobs.enabled / jobs.kinds). An unknown running value is not
    a match. `[]` and "every kind listed" are the same answer (4.8)."""
    jobs = pc.get("jobs") or {}
    for key, want in asked.items():
        if key == "jobs_enabled":
            if not isinstance(jobs.get("enabled"), bool) or jobs["enabled"] != want:
                return False
        elif key == "jobs_kinds":
            running = jobs.get("kinds")
            if running is None or not isinstance(want, list):
                return False
            if _every_kind(want) or _every_kind(running):
                if _every_kind(want) != _every_kind(running):
                    return False
            elif set(map(str, want)) != set(map(str, running)):
                return False
        else:
            # A key this page cannot read back: cannot tell, so not "in effect".
            return False
    return True


def _recent(ts: Any, seconds: int) -> bool:
    if not ts:
        return False
    try:
        return db.age_seconds(str(ts), db.utcnow_iso()) <= seconds
    except (TypeError, ValueError):
        return False


def _wanted(pc: Mapping[str, Any]) -> tuple[bool | None, list[str]]:
    """What the tick boxes show: the pending ask if there is one, else what is
    on disk there (pending_restart), else what is running. The boxes are
    what the computer WILL do, which is what the person is changing."""
    jobs = pc.get("jobs") or {}
    enabled = jobs.get("enabled")
    kinds = list(jobs.get("kinds") or [])
    waiting = (pc.get("settings") or {}).get("pending_restart") or {}
    if "jobs_enabled" in waiting and isinstance(waiting["jobs_enabled"], bool):
        enabled = waiting["jobs_enabled"]
    if "jobs_kinds" in waiting and isinstance(waiting["jobs_kinds"], list):
        kinds = [str(k) for k in waiting["jobs_kinds"]]
    req = pc.get("settings_request") or {}
    if req.get("state") == "pending":
        asked = req.get("settings") or {}
        if isinstance(asked.get("jobs_enabled"), bool):
            enabled = asked["jobs_enabled"]
        if isinstance(asked.get("jobs_kinds"), list):
            kinds = [str(k) for k in asked["jobs_kinds"]]
    return enabled, kinds


def _kind_boxes(kinds: list[str]) -> list[dict[str, Any]]:
    every = not kinds or set(kinds) >= set(db.JOB_KINDS)
    return [{"kind": k, "label": KIND_WORDS.get(k) or db.JOB_KIND_LABELS.get(k) or k,
             "checked": every or k in kinds}
            for k in db.JOB_KIND_LABELS]


def _minutes(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{n:g} min"


def _readonly_rows(pc: Mapping[str, Any], site: Mapping[str, Any],
                   is_rig: bool) -> list[dict[str, str]]:
    """F6: what the computer last REPORTED. NULL is "not reported", never a
    default (a companion older than the section sends nothing)."""
    reported = pc.get("settings") or None
    rows: list[dict[str, str]] = []
    lend = (reported or {}).get("jobs_volunteer_minutes")
    rows.append({"name": "lend it to the fleet for",
                 "value": _minutes(lend) if lend is not None else "",
                 "where": "tray: Settings, FLEET JOBS"})
    if not is_rig:
        remind = (reported or {}).get("drive_reminder_minutes")
        if remind is None:
            words = ""
        elif float(remind) == 0:
            words = "the first warning only"
        else:
            words = f"every {_minutes(remind)}"
        rows.append({"name": "drive reminder", "value": words,
                     "where": "the computer's config file; tray: Settings, SYNCING mutes one"})
    if site.get("youtube_download"):
        # D-14: hidden entirely when the site has YouTube downloads off.
        yt = (reported or {}).get("youtube")
        if not isinstance(yt, Mapping):
            terms = signin = ""
        else:
            terms = {True: "accepted", False: "not accepted"}.get(yt.get("terms_accepted"), "")
            if yt.get("signin_enabled") is False:
                signin = "not used on this computer"
            else:
                signin = {"ok": "signed in", "stale": "signed in, needs a refresh",
                          "expired": "expired: sign in again", "none": "not signed in"
                          }.get(str(yt.get("signin") or ""), str(yt.get("signin") or ""))
            if yt.get("downloads") is False:
                terms = (terms + ", " if terms else "") + "downloads off on this computer"
        rows.append({"name": "YouTube terms", "value": terms, "where": "tray: Settings, YOUTUBE"})
        rows.append({"name": "YouTube sign-in", "value": signin, "where": "tray: Settings, YOUTUBE"})
    return rows


def _gate_words(pc: Mapping[str, Any]) -> tuple[str, str]:
    jobs = pc.get("jobs") or {}
    gate = jobs.get("gate") or {}
    detail = str(gate.get("detail") or "").strip()
    enabled = jobs.get("enabled")
    if pc.get("lost"):
        return "red", "Not taking work: not heard from"
    if enabled is False:
        return "muted", "Not taking work: switched off on this computer"
    if detail:
        return "amber", detail
    if enabled is True:
        if pc.get("mode") == "base":
            return "green", "Taking fleet work"
        return "green", "Taking fleet work while nobody is using it"
    return "muted", "not reported"


def _idle_words(pc: Mapping[str, Any]) -> str:
    if pc.get("mode") == "base":
        return "no wait (a computer wired to the server is exempt)"
    idle = (pc.get("jobs") or {}).get("idle_seconds")
    try:
        seconds = int(idle)
    except (TypeError, ValueError):
        return "not reported"
    if seconds < 60:
        return f"{seconds} s with nobody using it"
    return f"{seconds // 60} min with nobody using it"


def _running_words(pc: Mapping[str, Any]) -> str:
    job = (pc.get("jobs") or {}).get("running") or {}
    if not job or not job.get("id"):
        return ""
    label = job.get("label") or job.get("kind") or "a job"
    where = f" on {job['rel_path']}" if job.get("rel_path") else ""
    pct = f", {job['percent']}%" if job.get("percent") is not None else ""
    return f"{label}{where}{pct}"


def _add_options(conn: sqlite3.Connection, user: str, pc: Mapping[str, Any]) -> list[dict]:
    """The projects this computer could be given, each with the UX-1 capacity
    sentence the tick asks first.

    Built from ONE proxy-bytes map and ONE free-space read per computer, not
    tick_capacity_warning per project (two queries each, for every active
    project, on every 30 s refresh of every panel; account page 2026-09-25,
    review round). The sentence itself is health.capacity_warning, the same
    one tick_capacity_warning returns for a single named machine, so the
    words cannot drift; the assignment grid batches the same way."""
    ticked = {p.get("slug") for p in pc.get("plan") or []}
    machine = str(pc.get("machine") or "")
    try:
        proxy_map = db.project_proxy_bytes_map(conn)
        free, _at = db.machine_free_bytes(conn, user, machine) if machine else (None, None)
    except Exception:  # noqa: BLE001 - a missing sentence must not cost the rows
        log.exception("account page: capacity figures for %s", machine)
        proxy_map, free = {}, None
    out = []
    for row in conn.execute(
            "SELECT slug, label FROM projects WHERE active=1 ORDER BY label, slug"):
        if row["slug"] in ticked:
            continue
        label = row["label"] or row["slug"]
        warning = None
        proxy_bytes = proxy_map.get(row["slug"])
        if proxy_bytes and machine:
            try:
                warning = health.capacity_warning(label, proxy_bytes, machine, free)
            except Exception:  # noqa: BLE001 - a missing sentence must not cost the row
                log.exception("account page: capacity sentence for %s", row["slug"])
        out.append({"slug": row["slug"], "label": label, "warning": warning or ""})
    return out


def decorate_computer(conn: sqlite3.Connection, user: str, view: Mapping[str, Any],
                      pc: dict[str, Any]) -> dict[str, Any]:
    is_rig = pc.get("mode") == "base"
    enabled, kinds = _wanted(pc)
    tone, gate = _gate_words(pc)
    why = pc.get("why")
    pc = dict(pc)
    pc.update({
        "dom_id": dom_id(pc.get("machine") or ""),
        "is_rig": is_rig,
        "status": request_status(pc),
        "pending": (pc.get("settings_request") or {}).get("state") == "pending",
        "want_enabled": enabled,
        "kind_boxes": _kind_boxes(kinds),
        "kinds_every": not kinds or set(kinds) >= set(db.JOB_KINDS),
        "kind_words": [KIND_WORDS.get(k) or db.JOB_KIND_LABELS.get(k) or k
                       for k in ((pc.get("jobs") or {}).get("kinds") or [])],
        "readonly": _readonly_rows(pc, view.get("site") or {}, is_rig),
        "gate_tone": tone,
        "gate_words": gate,
        "idle_words": _idle_words(pc),
        "running_words": _running_words(pc),
        "why_sentence": (why.get("sentence") if isinstance(why, Mapping) else str(why or "")),
        "up_to_date": bool(pc.get("companion_version")) and (
            not pc.get("current_version")
            or pc.get("companion_version") == pc.get("current_version")),
        "add_options": [] if is_rig else _add_options(conn, user, pc),
        "plan": [] if is_rig else _plan_with_warnings(conn, user, pc),
    })
    return pc


def _plan_with_warnings(conn: sqlite3.Connection, user: str,
                        pc: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The plan rows, each upload-only row carrying the UX-1 capacity sentence
    its [ SYNC FULLY ] asks first: switching to full brings the proxies down,
    which is the same cost as a new full tick."""
    rows = []
    for p in pc.get("plan") or []:
        row = dict(p)
        row["warning"] = ""
        if row.get("sync_mode") == db.SYNC_MODE_UPLOAD_ONLY:
            try:
                row["warning"] = tick_capacity_warning(
                    conn, user, row.get("slug") or "", pc.get("machine")) or ""
            except Exception:  # noqa: BLE001 - a missing sentence must not cost the row
                log.exception("account page: capacity sentence for %s", row.get("slug"))
        rows.append(row)
    return rows


def _changed_line(request: Request) -> dict[str, Any] | None:
    """?changed=password&others=<n>, printed by the password partial's
    redirect. Any other `changed` renders nothing: the values only choose
    between sentences this module wrote, and `others` is parsed as an int and
    clamped.

    A missing or unreadable `others` is "the password changed, and we cannot
    say whether the other browsers were signed out" (account page 2026-09-25,
    review round): B's rotate_after_password_change answers None when the
    server keeps no session store or the sign-out failed, and a person who
    sees no confirmation after a real change will change it again."""
    if request.query_params.get("changed") != "password":
        return None
    raw = request.query_params.get("others", "")
    try:
        others: int | None = max(0, min(int(raw), OTHERS_MAX))
    except (TypeError, ValueError):
        others = None
    return {"others": others, "others_unknown": others is None}


def _page_context(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    user = _user(request)
    view = account_api.build_account_view(request, conn)
    computers = [decorate_computer(conn, user, view, pc)
                 for pc in view.get("computers") or []]
    remote = [pc for pc in computers if not pc["is_rig"]]
    rigs = [pc for pc in computers if pc["is_rig"]]
    return {"acct": view, "remote": remote, "rigs": rigs,
            "site": view.get("site") or {}}


# ---------------------------------------------------------------------- page

@router.get("/account")
def page_account(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """F7. Always the signed-in person: `?as=` is ignored, and the sidebar is
    pinned to them too (its own ?as= reading is for admins on other pages)."""
    user = _user(request)
    ctx = _page_context(request, conn)
    ctx.update(_sidebar_context(request, conn, None, editor=user))
    ctx.update({"nav_current": "account", "changed": _changed_line(request),
                "as_qs": ""})
    return _render(request, "account.html", ctx)


@router.get("/partials/account/computer")
def partial_account_computer(request: Request, machine: str = "",
                             conn: sqlite3.Connection = Depends(get_conn)):
    """One computer, refreshed every 30 s. A computer that has left the
    person's list (forgotten, renamed) answers an empty 200, which htmx swaps
    in as nothing: the panel goes rather than showing a stale row."""
    user = _user(request)
    view = account_api.build_account_view(request, conn)
    for pc in view.get("computers") or []:
        if pc.get("machine") == machine:
            return _render(request, "partials/account_computer.html",
                           {"pc": decorate_computer(conn, user, view, pc),
                            "acct": view, "site": view.get("site") or {}})
    return HTMLResponse("")


def _computer_fragment(request: Request, conn: sqlite3.Connection, editor: str,
                       machine: str, result: dict[str, str] | None) -> Response:
    """The fleet-jobs fragment after an ask. The page only ever shows the
    signed-in person's computers, so an admin's ask for somebody else's (from
    a hand-built request) answers with the result line alone."""
    user = _user(request)
    view = account_api.build_account_view(request, conn)
    if editor == user:
        for pc in view.get("computers") or []:
            if pc.get("machine") == machine:
                return _render(request, "partials/account_jobs.html",
                               {"pc": decorate_computer(conn, user, view, pc),
                                "acct": view, "result": result})
    return _render(request, "partials/account_result.html", {"result": result})


# --------------------------------------------------------------- display name

@router.post("/partials/account/display-name")
async def partial_account_display_name(request: Request,
                                       conn: sqlite3.Connection = Depends(get_conn)):
    """F1. The "you" panel comes back with a result line; a refusal (empty,
    too long, invisible characters, taken) is that line, not an HTTP error."""
    _user(request)
    form = await _form_lists(request)
    text = _one(form, "display_name")
    result: dict[str, str]
    try:
        out = account_api.set_own_display_name(request, conn, text)
    except HTTPException as exc:
        result = {"tone": "red", "text": _refusal(exc)}
    else:
        name = out.get("display_name")
        # The cache is invalidated by the service after its commit; this
        # render reads the new map.
        result = ({"tone": "green", "text": f"Saved. Other people now see {name}."}
                  if name else
                  {"tone": "green", "text": "Cleared. Other people now see your sign-in name."})
    view = account_api.build_account_view(request, conn)
    return _render(request, "partials/account_you.html",
                   {"acct": view, "result": result, "typed": text})


@router.post("/partials/admin/users/display-name")
async def partial_admin_user_display_name(request: Request,
                                          conn: sqlite3.Connection = Depends(get_conn)):
    """F1a, from Settings, Users. Re-renders the Users panel, as every other
    control in it does, with the answer as its notice or error line."""
    from .api import build_admin_users_view

    user = _user(request)
    if not auth.is_admin(request.app.state.settings, user):
        raise HTTPException(status_code=403, detail="admins only")
    form = await _form_lists(request)
    username = _one(form, "username").strip().lower()
    error = notice = None
    try:
        out = account_api.set_user_display_name(request, conn, username,
                                                _one(form, "display_name"))
    except HTTPException as exc:
        error = _refusal(exc)
    else:
        name = out.get("display_name")
        notice = (f"{username} is now shown as {name}." if name
                  else f"{username} is shown by their sign-in name again.")
    # build_admin_users_view asks the NAS (the SMB account list); section 0
    # keeps blocking work off the event loop, so it runs in the threadpool
    # (account page 2026-09-25, review round). ui.partial_admin_set_password
    # calls it inline; that is not a pattern to copy.
    users_view = await run_in_threadpool(build_admin_users_view,
                                         request.app.state.settings, conn)
    return _render(request, "partials/admin_users.html", {
        "admin_users": users_view, "error": error, "notice": notice,
    })


# ------------------------------------------------------------------ sync keys

@router.get("/partials/account/sync-keys")
def partial_account_sync_keys(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """F4, loaded on its own after the page paints (hx-trigger="load"): it may
    ask the NAS, and a slow NAS must never hold the page. A plain def, so the
    NAS call runs in the threadpool."""
    user = _user(request)
    keys = account_api.build_sync_keys_view(request.app.state.settings, conn, user)
    return _render(request, "partials/account_sync_keys.html", {"keys": keys})


# ------------------------------------------------------------------- password

def _password_blocking(request: Request, response: Response, conn: sqlite3.Connection,
                       current: str, new: str, again: str) -> dict[str, Any]:
    return account_api.change_password(request, response, conn,
                                       current_password=current, new_password=new,
                                       new_password_again=again)


@router.post("/partials/account/password")
async def partial_account_password(request: Request,
                                   conn: sqlite3.Connection = Depends(get_conn)):
    """F2. The service verifies the current password the way /login does (the
    SMB probe or scrypt, both blocking, hence the threadpool) under the sign-in
    throttle, sets it, signs every other browser out and re-issues THIS
    browser's cookie. Nothing typed is logged or echoed back."""
    _user(request)
    form = await _form_lists(request)
    response = HTMLResponse("")
    try:
        out = await run_in_threadpool(
            _password_blocking, request, response, conn,
            _one(form, "current_password"), _one(form, "new_password"),
            _one(form, "new_password_again"))
    except HTTPException as exc:
        return _render(request, "partials/account_result.html",
                       {"result": {"tone": "red", "text": _refusal(exc)}})
    others = out.get("other_sessions_signed_out")
    # The rotated cookie is on `response` (start_session set it there); the
    # redirect carries it, and the page it lands on carries the NEW token.
    # No count (None: no session store, or signing the others out failed)
    # still redirects with changed=password, so the page confirms the change
    # and says the other browsers may still be signed in.
    target = "/account?changed=password"
    if isinstance(others, int) and not isinstance(others, bool):
        target += f"&others={max(0, min(others, OTHERS_MAX))}"
    response.headers["HX-Redirect"] = target
    return response


# ------------------------------------------------------ signed-in browsers

def _sessions_panel(request: Request, conn: sqlite3.Connection,
                    result: dict[str, str] | None = None) -> Response:
    user = _user(request)
    try:
        rows = account_api.list_own_sessions(request, conn).get("sessions") or []
        unavailable = ""
    except HTTPException as exc:
        rows, unavailable = [], _refusal(exc)
    return _render(request, "partials/account_sessions.html",
                   {"sessions": rows, "unavailable": unavailable, "result": result,
                    "others": sum(1 for r in rows if not r.get("current")),
                    "user": user})


@router.get("/partials/account/sessions")
def partial_account_sessions(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    return _sessions_panel(request, conn)


@router.post("/partials/account/sessions/revoke")
async def partial_account_session_revoke(request: Request,
                                         conn: sqlite3.Connection = Depends(get_conn)):
    """F3a: one of your OTHER browsers. This one is refused (D-13)."""
    _user(request)
    form = await _form_lists(request)
    try:
        account_api.revoke_own_session(request, conn, _one(form, "handle").strip())
    except HTTPException as exc:
        result = {"tone": "red", "text": _refusal(exc)}
    else:
        result = {"tone": "green", "text": "Signed that browser out."}
    return _sessions_panel(request, conn, result)


@router.post("/partials/account/sessions/revoke-others")
async def partial_account_sessions_revoke_others(request: Request,
                                                 conn: sqlite3.Connection = Depends(get_conn)):
    """F3b: every browser but this one."""
    _user(request)
    try:
        out = account_api.revoke_own_other_sessions(request, conn)
    except HTTPException as exc:
        result = {"tone": "red", "text": _refusal(exc)}
    else:
        n = int(out.get("revoked") or 0)
        result = {"tone": "green", "text": (
            f"Signed out {n} other browser{'' if n == 1 else 's'}. This one stays signed in."
            if n else "No other browser was signed in.")}
    return _sessions_panel(request, conn, result)


# ------------------------------------------------ a computer's fleet jobs (F5)

@router.post("/partials/account/machines/settings")
async def partial_account_machine_settings(request: Request,
                                           conn: sqlite3.Connection = Depends(get_conn)):
    """Ask one computer to change `jobs_enabled` or `jobs_kinds`. Two forms on
    the page, one key each, so a click asks for the one thing it changed and
    never re-asks the other. `mode` is not a field here and never can be
    (CR-88): the service 422s any key outside db.MACHINE_SETTING_KEYS."""
    _user(request)
    form = await _form_lists(request)
    editor = _one(form, "editor").strip().lower()
    machine = _one(form, "machine")
    body: dict[str, Any] = {}
    if "jobs_enabled" in form:
        # The hidden "0" comes first and the checkbox's "1" after it, so the
        # LAST value is the box's state.
        body["jobs_enabled"] = _one(form, "jobs_enabled") in ("1", "true", "on")
    if "jobs_kinds_sent" in form:
        kinds = [k for k in form.get("jobs_kinds") or [] if k]
        if not kinds:
            # 4.8: an empty list means EVERY kind on the wire, the opposite
            # of what unticking the last box meant. Refused before any ask.
            return _computer_fragment(request, conn, editor, machine,
                                      {"tone": "red", "text": LAST_KIND})
        body["jobs_kinds"] = kinds
    for key in form:
        # Any other field that names a setting (mode, a hand-built request)
        # goes to the service, which refuses the whole ask with its sentence.
        if key not in ("editor", "machine", "jobs_enabled", "jobs_kinds",
                       "jobs_kinds_sent", "csrf"):
            body[key] = _one(form, key)
    try:
        out = account_api.ask_machine_settings(request, conn, editor, machine, body)
    except HTTPException as exc:
        result = {"tone": "red", "text": _refusal(exc)}
    else:
        result = ({"tone": "muted", "text": "Nothing to ask: it already works that way."}
                  if out.get("unchanged") else None)
    return _computer_fragment(request, conn, editor, machine, result)


@router.post("/partials/account/machines/settings/withdraw")
async def partial_account_machine_settings_withdraw(request: Request,
                                                    conn: sqlite3.Connection = Depends(get_conn)):
    _user(request)
    form = await _form_lists(request)
    editor = _one(form, "editor").strip().lower()
    machine = _one(form, "machine")
    try:
        out = account_api.withdraw_machine_settings(request, conn, editor, machine)
    except HTTPException as exc:
        result = {"tone": "red", "text": _refusal(exc)}
    else:
        result = ({"tone": "muted", "text": "Withdrawn. Nothing is asked of it now."}
                  if out.get("withdrawn") else
                  {"tone": "muted", "text": "There was nothing waiting to withdraw."})
    return _computer_fragment(request, conn, editor, machine, result)
