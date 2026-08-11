"""Who is asking. There is no auth code here, and there must never be.

The dashboard owns the session: its `login_gate` middleware wraps mounted
sub-apps, so nothing under /ytdl/ is reachable without one. `YtdlGate`
(ccsync_dashboard/ytdl.py) then decodes the `ccsync_session` cookie and
**appends** the username as `x-ccsync-user`, having first **stripped any
inbound header of that name** -- so the value this module reads cannot have
come from the browser. That strip is the entire security model of this file; if
it is ever removed, every editor can act as every other editor.

Standalone (`uvicorn ytdlweb.main:app` on a dev box) there is no gate and no
dashboard, so `YTDL_DEV_USER` stands in. It is deliberately not defaulted: an
unset one means 401, not "anonymous", because a deployed host whose gate
stopped injecting the header must fail loudly rather than pool every editor's
jobs under one name.
"""
from fastapi import HTTPException, Request

# Lower-case because Starlette's Headers mapping is case-insensitive; written
# this way to match how the gate appends it.
USER_HEADER = 'x-ccsync-user'


def current_user(request: Request) -> str:
    """-> the caller's dashboard username. 401 JSON if there isn't one.

    HTTPException, not a redirect: every caller here is a fetch() from the SPA
    and cannot follow an HTML login page (the same reason app.py lists
    '/ytdl/api/' in login_gate's JSON-401 tuple).
    """
    user = (request.headers.get(USER_HEADER) or '').strip()
    if user:
        return user

    from ytdlweb import config
    if config.DEV_USER:
        return config.DEV_USER

    raise HTTPException(401, 'not signed in: no dashboard session reached this '
                             'app. If you got here directly, sign in to the '
                             'dashboard first.')
