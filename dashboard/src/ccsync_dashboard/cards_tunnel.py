"""The Timeline Cards `/agent/*` protocol, tunnelled on the fleet credential.

docs/TIMELINE-CARDS-INTO-CCSYNC.md §3.3 option (a), phase 2 (2026-08-30).

Three routes, verbatim in shape, under `/cards/agent/`:

    POST /cards/agent/state     the swept timeline, or a playhead-only ping
    GET  /cards/agent/pending   the long poll (`?wait=25`) for the next edit
    POST /cards/agent/result    how that edit went

They exist because a card click has a ~0.3 s latency budget and the report
channel's cadence is 5-60 s (§3.3 (b) is the wrong shape for this and the
right shape for jobs). Everything else about them is a deliberate NON-feature:
this module holds no state, decides nothing, and stores nothing. It is a
credential swap and a proxy.

WHAT IT IS FOR, in one sentence: `CARDS_TOKEN` disappears from the editor's
machine. Today creator-1 runs `reorder_web.py --agent` holding the Timeline
Cards server's own shared secret in a `.cmd` file; after this the companion
holds only what it already holds -- the fleet token plus a dashboard-signed
identity -- and THIS side attaches the upstream token, from the container's
environment, on the way out. A companion never learns it and a leaked
companion credential cannot be replayed at the cards server directly.

Four rules, each with its reason:

  * **THE VERIFIED IDENTITY IS THE AGENT'S NAME.** `AgentClient` puts
    `socket.gethostname()` in `name`, which is a self-asserted string; the
    away/stale text on the page is built from it. So the body's `name` is
    OVERWRITTEN here with the identity `_require_fleet_caller` verified, plus
    the machine the caller declared for legibility (`alex/CREATOR-1`). Same
    rule as every other fleet route: the verified name, never `body.editor`
    (ytdl H5).
  * **THE UPSTREAM TOKEN NEVER GOES DOWNSTREAM.** It is attached as the
    `X-Cards-Token` header on the outbound call and stripped from anything
    echoed back, and the inbound body's own `token` field is dropped rather
    than forwarded -- a companion that sent one must not be able to present a
    token of its choosing to the cards server.
  * **PER SUFFIX, NEVER PER PREFIX.** app.py's `login_gate` and `csrf_gate`
    carve out exactly these three paths. `/cards/...` will be the mounted
    page in phase 3 and it stays fully session-gated; a leaked fleet token
    must not read a timeline, only serve the machine that has Resolve open.
  * **UPSTREAM DOWN IS A SENTENCE, NOT A TRACEBACK.** 502 with what was
    tried and what answered, so "the agent has gone away" on the page and
    "the cards server is not running" in the companion log are the same
    incident and say so.

Phase 3 replaces `_forward` with an in-process call when the page is mounted
here; the routes, the credential and the name rule do not change.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .api import _require_fleet_caller, get_conn

log = logging.getLogger("ccsync.dashboard.cards")

router = APIRouter(prefix="/cards/agent")

# The agent's own ceiling (`AGENT_WAIT_S` in the cards config). Clamped here
# as well as there: a client asking for a 10 minute poll would hold one of
# this container's threadpool workers for ten minutes.
MAX_WAIT_SECONDS = 25.0
# How long we give the upstream beyond the poll itself. Matches the agent's
# own `AGENT_WAIT_S + 20`.
POLL_MARGIN_SECONDS = 20.0
# A state push is a whole timeline; the agent gives it 90 s.
POST_TIMEOUT_SECONDS = 90.0
# The name the cards server shows in "the agent is away" text.
MAX_NAME_CHARS = 96


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """No dashboard call follows a redirect (docs/GOTCHAS.md §12). Applied
    here because the outbound call carries the cards server's token, and a
    302 is somebody else choosing where that goes."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener():
    """Overridable so tests stub the OPENER, never urlopen (GOTCHAS §12)."""
    return urllib.request.build_opener(_NoRedirect)


def configured(settings: Any) -> bool:
    """Is there a Timeline Cards server to tunnel to at all?"""
    return bool(str(getattr(settings, "cards_server_url", "") or "").strip())


def _upstream(request: Request) -> tuple[str, str]:
    """(base url, token), or a 503 naming the variable that is missing.

    503 and not 500: an unconfigured tunnel is a deployment that has not been
    given a cards server yet, which is a normal state for every fleet that
    does not use Timeline Cards. The companion's role logs the sentence and
    keeps retrying, which is what it would do for a server that is down.
    """
    settings = request.app.state.settings
    base = str(getattr(settings, "cards_server_url", "") or "").strip().rstrip("/")
    token = str(getattr(settings, "cards_token", "") or "").strip()
    if not base:
        raise HTTPException(
            status_code=503,
            detail="no Timeline Cards server is configured here "
                   "(set DASH_CARDS_SERVER_URL on the dashboard)")
    if not token:
        raise HTTPException(
            status_code=503,
            detail="no Timeline Cards token is configured here "
                   "(set DASH_CARDS_TOKEN on the dashboard)")
    return base, token


def agent_name(editor: str, machine: str) -> str:
    """The name the cards server will show, built from the VERIFIED identity.

    `editor/MACHINE` when the caller declared a machine, the editor alone
    otherwise. Never the raw `name` the body carried: that is a self-asserted
    string and this is the one place that knows who is really calling.
    """
    editor = str(editor or "").strip()
    machine = "".join(
        ch for ch in str(machine or "").strip() if ch.isalnum() or ch in "-_. "
    ).strip()
    name = f"{editor}/{machine}" if machine else editor
    return name[:MAX_NAME_CHARS]


def _forward(
    request: Request, method: str, suffix: str,
    body: dict[str, Any] | None = None, query: str = "",
    timeout: float = POST_TIMEOUT_SECONDS,
) -> Any:
    """One call to the cards server. Returns its parsed JSON, or raises 502.

    The token rides in the header only. `handler._agent_ok` accepts it there,
    in the query string or in the body; the header is the one of the three
    that never ends up in a log line or a browser history.
    """
    base, token = _upstream(request)
    url = base + suffix + (("?" + query) if query else "")
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"X-Cards-Token": token, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _opener().open(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        # A 403 here is THIS dashboard's token being wrong, not the caller's:
        # say which, or an admin spends the evening rotating the wrong secret.
        detail = ("the Timeline Cards server refused this dashboard's token "
                  "(check DASH_CARDS_TOKEN against the server's CARDS_TOKEN)"
                  if exc.code in (401, 403) else
                  f"the Timeline Cards server answered HTTP {exc.code}")
        log.warning("cards tunnel: %s %s -> HTTP %s", method, suffix, exc.code)
        raise HTTPException(status_code=502, detail=detail) from None
    except (TimeoutError, OSError) as exc:
        log.warning("cards tunnel: %s %s could not be reached (%s)",
                    method, suffix, exc)
        raise HTTPException(
            status_code=502,
            detail=f"could not reach the Timeline Cards server at {base} "
                   f"({type(exc).__name__})") from None
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="the Timeline Cards server did not answer with JSON") from None


def _clean(answer: Any) -> Any:
    """Nothing the upstream echoes carries a token back down.

    `agent_state` answers `{ok, version, root, resend}` and `agent_pending`
    answers an edit request; neither contains a credential today. This is
    here so that a future field on the other side of a repo boundary cannot
    quietly become one.
    """
    if isinstance(answer, dict):
        return {k: v for k, v in answer.items() if k != "token"}
    return answer


@router.post("/state")
def cards_agent_state(
    payload: dict[str, Any], request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> Any:
    """The agent's swept state, or a playhead-only ping.

    The body is passed through untouched except for the two fields this side
    owns: `name` becomes the verified identity, and `token` is dropped.
    """
    editor = _require_fleet_caller(request, conn)
    body = dict(payload or {})
    body.pop("token", None)
    body["name"] = agent_name(editor, body.get("machine") or body.get("name") or "")
    body.pop("machine", None)
    return _clean(_forward(request, "POST", "/agent/state", body))


@router.get("/pending")
def cards_agent_pending(
    request: Request, wait: float = 25.0,
    conn: sqlite3.Connection = Depends(get_conn),
) -> Any:
    """The long poll. `wait` is passed through, clamped to the agent's own
    ceiling, and the read timeout is that plus the agent's own margin.

    A blocking `def` route, so it runs in the threadpool rather than on the
    event loop: 25 s of `await`-less socket read on the loop would stop the
    fleet page dead. One worker per connected agent, and there is one agent
    per machine.
    """
    _require_fleet_caller(request, conn)
    seconds = max(0.0, min(float(wait or 0.0), MAX_WAIT_SECONDS))
    query = urllib.parse.urlencode({"wait": int(seconds)})
    return _clean(_forward(request, "GET", "/agent/pending", query=query,
                           timeout=seconds + POLL_MARGIN_SECONDS))


@router.post("/result")
def cards_agent_result(
    payload: dict[str, Any], request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> Any:
    """How the edit went. Forwarded verbatim, minus the token."""
    _require_fleet_caller(request, conn)
    body = dict(payload or {})
    body.pop("token", None)
    return _clean(_forward(request, "POST", "/agent/result", body))
