"""Who is asking. There is no auth code here, and there must never be.

The dashboard owns the session: its `login_gate` middleware wraps mounted
sub-apps, so nothing under /ytdl/ is reachable without one. `YtdlGate`
(ccsync_dashboard/ytdl.py) then decodes the `ccsync_session` cookie and
**appends** the username as `x-ccsync-user`, having first **stripped any
inbound header of that name** -- so the value this module reads cannot have
come from the browser. That strip is the entire security model of this file; if
it is ever removed, every editor can act as every other editor.

Standalone (`uvicorn ytdlweb.main:app` on a dev box) there is no gate and no
dashboard, so there is no identity and every request is a 401. That is
deliberate: an unset one means 401, not "anonymous", because a deployed host
whose gate stopped injecting the header must fail loudly rather than pool every
editor's jobs under one name.

`YTDL_DEV_USER` used to fill that hole and was REMOVED on 2026-08-17
(COMMERCIAL_READINESS.md item 15). One environment variable made every request
on a deployed host arrive as that named editor -- their ticked projects, their
jobs, their download history -- and the only thing standing between a
production host and that was a comment saying not to set it. What replaces it
is `set_test_user()`: an explicit in-process call, reachable only by code that
has already imported this package, so no value in any environment can turn the
gate off.
"""
import threading

from fastapi import HTTPException, Request

# Lower-case because Starlette's Headers mapping is case-insensitive; written
# this way to match how the gate appends it.
USER_HEADER = 'x-ccsync-user'

# The stand-in identity, for a test process or a deliberate standalone dev run.
# A module global set by a function call and NOT read from the environment: an
# attacker who can set env vars on the container is a different problem, but an
# operator who copies a dev command line into a systemd unit is a routine one,
# and this shape makes that mistake impossible rather than discouraged.
_test_user = ''
_test_user_lock = threading.Lock()


def set_test_user(username):
    """Make every un-gated request arrive as `username`. TESTS AND DEV ONLY.

    Pass '' (or None) to clear it. Returns the previous value so a caller can
    restore it -- conftest does exactly that.
    """
    global _test_user
    with _test_user_lock:
        previous = _test_user
        _test_user = str(username or '').strip()
    return previous


def current_user(request: Request) -> str:
    """-> the caller's dashboard username. 401 JSON if there isn't one.

    HTTPException, not a redirect: every caller here is a fetch() from the SPA
    and cannot follow an HTML login page (the same reason app.py lists
    '/ytdl/api/' in login_gate's JSON-401 tuple).
    """
    user = (request.headers.get(USER_HEADER) or '').strip()
    if user:
        return user

    with _test_user_lock:
        stand_in = _test_user
    if stand_in:
        return stand_in

    raise HTTPException(401, 'not signed in: no dashboard session reached this '
                             'app. If you got here directly, sign in to the '
                             'dashboard first.')
