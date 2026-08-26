"""Serve the YouTube downloader UI from inside the dashboard, at /ytdl.

The app lives in this repo at ytdl/web and is deployed exactly the way
broll/web and music/web are: the tree is shipped to <host-root>/ytdl-web, the
container mounts it read-only at /ytdl-app, run.sh puts it on PYTHONPATH, and
it is imported from here. See ytdl/web/DEPLOY.md for the installer side.

The package is `ytdlweb`, NOT `app` and NOT `ytdl` -- same rule as musicweb.
broll/web is imported as the top-level package `app`, so a second package of
that name on the same PYTHONPATH would collide in sys.modules and one of the
two would silently win; and `ytdl` would collide with THIS module's name in a
checkout. Do not "tidy" it.

Editors get one URL and one login instead of a fourth service to find and sign
in to. Both apps are FastAPI, so this is a real in-process mount rather than a
proxy tier: the SPA polls api/jobs/{id} every 1.5s while a pipeline runs, and
every one of those polls would otherwise cross a proxy hop for nothing.

The mount inherits the dashboard's `login_gate` middleware for free, since
Starlette middleware wraps the whole ASGI app including mounts -- see app.py,
where /ytdl/api/ is listed alongside /broll/api/ and /music/api/ so the SPA's
fetch() calls get a 401 JSON body instead of a 303 to an HTML login page,
which they cannot follow.

EVERYTHING ABOUT THE IMPORT IS BEST-EFFORT. A missing or broken ytdl checkout
must leave the fleet dashboard completely functional: it is what tells everyone
whether their footage is syncing, and it cannot be taken down by an optional
feature.

WHAT IS NOT BEST-EFFORT IS WHO THE CALLER IS. Unlike music, this sub-app makes
per-user decisions with real consequences -- which projects a job may download
into (the caller's ticked selections), and whose jobs a manifest may be read
from -- and it learns the answer from a header this gate mints. YtdlGate
therefore STRIPS every inbound X-CCSync-User before appending its own: the
header must only ever be server-minted, or any logged-in editor could download
into another editor's projects by adding one line to a fetch(). The session
cookie is the credential; the header is only its transcription for a sub-app
that has no session code of its own.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

from . import api, auth, db, site_store
from .settings import Settings

log = logging.getLogger(__name__)

MOUNT_PATH = "/ytdl"

# mount_ytdl's four states. Everything except MOUNTED is "do not advertise it
# in the nav" (ui.py), but they are different operator problems: absent = the
# code is not there, degraded = the code is there and its data root is not
# usable (so every request would 500 with "unable to open database file"), and
# disabled = this site has not turned the feature on, which is not a problem at
# all.
MOUNTED = "mounted"
ABSENT = "absent"
DEGRADED = "degraded"
# The site said no (site.toml [features] youtube_download / the Settings tick,
# 2026-08-17 -- COMMERCIAL_READINESS.md item 2). Nothing is imported and
# nothing is served, so /ytdl and every fleet download route under it answer a
# 404: the customer, not the vendor, decides whether downloading third-party
# YouTube material is lawful for them. See docs/legal/YOUTUBE_FEATURE_NOTICE.md.
# Since dash-release-ai-1 (2026-08-21) the 404 comes from YtdlFeatureGate
# rather than from there being no mount, which is what lets a tick take effect
# without a restart; nothing is loaded until one does.
DISABLED = "disabled"

# Mounting a third FastAPI() brings its default interactive docs along, and
# they would be reachable by every editor with a session. The dashboard does
# not publish an API explorer; neither does any of its mounts.
BLOCKED_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})

# The one header the sub-app trusts (ytdlweb.session.current_user). Lowercase
# bytes because that is how it appears in an ASGI scope -- HTTP/2 requires
# lowercase field names and uvicorn lowercases HTTP/1.1's for us, but the
# comparison is done on our own lowercased copy either way.
IDENTITY_HEADER = b"x-ccsync-user"

# The MACHINE credential's verdict, minted here for the same reason
# IDENTITY_HEADER is (ytdl-web-1, 2026-08-21). Two credentials reach the fleet
# routes -- the shared DASH_REPORT_TOKEN and a per-editor `cce1.` token whose
# hash only this database holds -- and only the dashboard can tell either from
# a forgery. The sub-app therefore gets our answer rather than a second
# implementation of it, and (like the identity header) any inbound copy is
# STRIPPED first: minted here or not present at all.
FLEET_TOKEN_HEADER = b"x-ccsync-token"
FLEET_AUTH_HEADER = b"x-ccsync-fleet-auth"

# The site switch this mount obeys, resolved DB-row-first the way
# `GET /api/v1/site` resolves it (dash-release-ai-1, 2026-08-21).
FEATURE_KEY = "youtube_download"

# How long the answer to "has this site enabled the downloader" is reused for.
# Seconds, because the point of reading it per request is that an admin's tick
# on Settings takes effect without a container restart -- and the SPA polls a
# running job every 1.5 s, so the read cannot be a database open per poll.
FEATURE_TTL_SECONDS = 5.0

# ...and how long a failed lazy import is left alone before it is retried. An
# absent ytdl tree fails the same way every time and the retry is expensive
# (it walks sys.path and, in the worst case, imports yt-dlp).
LOAD_RETRY_SECONDS = 60.0


class YtdlGate:
    """ASGI wrapper around the ytdl sub-app. Three jobs, all fail-closed.

    1. The sub-app's default interactive docs are 404'd (as for /broll, /music).
    2. Every request is re-stamped with the session's identity: any inbound
       X-CCSync-User is REMOVED, and the real one -- decoded from the
       ccsync_session cookie with the dashboard's own secret -- is appended
       when, and only when, that cookie is valid. A request with no valid
       session reaches the sub-app carrying NO identity header at all, so
       ytdlweb answers its own 401 even in the impossible case that something
       let it past login_gate.

       Strip-then-append rather than "append if absent": an editor who is
       genuinely logged in sails through login_gate, and without the strip
       their own `fetch(url, {headers: {'X-CCSync-User': 'someone-else'}})`
       would be the whole authorisation story for "which projects may I
       download into".

    3. The MACHINE credential is resolved here and stamped into
       X-CCSync-Fleet-Auth (ytdl-web-1, 2026-08-21), stripped inbound first
       for the same reason the identity header is. The sub-app cannot check a
       per-editor `cce1.` token itself -- the hash is in this database, which
       it opens read-only and only for selections -- so before this it 403'd
       every claim/heartbeat/status POST from an editor whose admin had minted
       them one, while the dashboard's own gate waved the same request
       through.

    A plain ASGI wrapper rather than BaseHTTPMiddleware or add_middleware:
    nothing is re-wrapped or buffered on the way through (the manifest
    endpoints are ordinary JSON, but the poll endpoint is called every 1.5s
    per open tab and pays for any per-request machinery), and no upstream
    global is mutated by importing us.
    """

    def __init__(self, app: Any, session_secret: str,
                 settings: Settings | None = None) -> None:
        self.app = app
        self._secret = session_secret or ""
        # Optional so the identity half can still be exercised on its own (the
        # mount tests build one with two arguments). Without settings there is
        # no database to check a per-editor token against, so no stamp is
        # minted and the sub-app falls back to its own shared-token compare --
        # which is exactly what a standalone ytdl deployment does.
        self._settings = settings

    def _identified_scope(self, scope: dict) -> dict:
        """A copy of `scope` whose headers carry our identity header and no
        other. The original is left alone: it belongs to the server, and a
        mounted app is not the only thing that ever reads it."""
        headers = [(k, v) for k, v in scope.get("headers", ())
                   if k.lower() not in (IDENTITY_HEADER, FLEET_AUTH_HEADER)]
        stamp = self._fleet_stamp(headers)
        if stamp is not None:
            headers.append((FLEET_AUTH_HEADER, stamp))
        username = auth.read_session_cookie(self._secret, _session_cookie(headers))
        if username:
            encoded = _header_value(username)
            if encoded is None:
                # Fail closed: no header at all, so the sub-app answers its own
                # 401 rather than authorising a name that is not this editor's.
                log.warning("ytdl identity header not minted for %r: the name "
                            "cannot survive a latin-1 header round trip",
                            username)
            else:
                headers.append((IDENTITY_HEADER, encoded))
        new_scope = dict(scope)
        new_scope["headers"] = headers
        return new_scope

    def _fleet_stamp(self, headers: list[tuple[bytes, bytes]]) -> bytes | None:
        """Our verdict on this request's X-CCSync-Token, or None.

        `editor:<name>` for a per-editor `cce1.` token (the sub-app then
        requires that name to match the signed identity header), `shared` for
        the DASH_REPORT_TOKEN every companion holds today, and None for a
        request that presented nothing or presented rubbish -- for which the
        sub-app's own fail-closed 403 is the right answer, unchanged.

        Only a request that actually carries a token pays for this, so the
        browser's 1.5 s poll costs one list comprehension; a per-editor token
        costs one short-lived database connection, exactly as app.py's
        pre-body gate does, and for the same reason (the hash lives in the
        database and nowhere else).
        """
        if self._settings is None:
            return None
        raw = b""
        for key, value in headers:
            if key.lower() == FLEET_TOKEN_HEADER:
                raw = value
                break
        if not raw:
            return None
        try:
            token = raw.decode("latin-1")
        except Exception:  # noqa: BLE001 - a header we cannot read is not a credential
            return None
        try:
            kind, editor = self._credential(token)
        except Exception:  # noqa: BLE001 - never let auth plumbing 500 the mount
            log.exception("could not resolve a companion credential for /ytdl")
            return None
        if kind == api.AUTH_SHARED:
            return b"shared"
        if kind == api.AUTH_EDITOR and editor:
            encoded = _header_value(f"editor:{editor}")
            if encoded is None:
                # Same fail-closed rule as the identity header: a name that
                # cannot survive the trip is withheld rather than mangled.
                log.warning("ytdl fleet stamp not minted for %r: the name "
                            "cannot survive a latin-1 header round trip", editor)
                return None
            return encoded
        return None

    def _credential(self, token: str) -> tuple[str, str | None]:
        """(AUTH_*, editor) for a token, opening a connection only when the
        token has the per-editor SHAPE. Lifted from app.py's
        _companion_credential, which does this same dance in the middleware
        for the same reason: a shared token costs no database work at all."""
        settings = self._settings
        if not db.looks_like_editor_report_token(token):
            return api.resolve_companion_credential(settings, None, token)
        try:
            conn = db.connect(settings.db_path)
        except Exception:  # noqa: BLE001 - an unopenable DB is not an auth pass
            return api.AUTH_NONE, None
        try:
            return api.resolve_companion_credential(settings, conn, token)
        finally:
            conn.close()

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http":
            if any(p in BLOCKED_PATHS for p in sub_paths(scope)):
                await _json_response(send, 404, {"detail": "Not Found"})
                return
            scope = self._identified_scope(scope)
        await self.app(scope, receive, send)


def _header_value(username: str) -> bytes | None:
    """The identity header's bytes, or None if this name cannot be carried.

    LATIN-1, not UTF-8 (YTDL-29, 2026-08-11). Starlette decodes header bytes as
    latin-1, so a UTF-8-encoded `josé` reached the sub-app as `josÃ©` --
    deterministically, so that editor's ticked projects matched nothing and
    /ytdl was unusable for them. Encoding the way the reader decodes covers
    every name up to U+00FF; beyond that (a CJK username) there is no lossless
    answer and a lossy one could collide two editors into one identity, so the
    header is withheld and the sub-app 401s -- broken, but loudly and for one
    person, rather than quietly authorising the wrong name.
    """
    try:
        return username.encode("latin-1")
    except UnicodeEncodeError:
        return None


def _session_cookie(headers: list[tuple[bytes, bytes]]) -> str | None:
    """The ccsync_session value out of raw ASGI headers, or None.

    Hand-parsed rather than via Starlette's Request: building one here would
    mean constructing a request object (and its receive channel) for every
    poll, and this needs exactly one cookie by name. Split on the FIRST "="
    only -- the token is `v2.session.<b64url>.<expires>.<hmac>` and base64url
    padding is stripped, but a cookie parser that loses everything after a
    second "=" is a bug waiting for the day that changes.
    """
    for key, value in headers:
        if key.lower() != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            name, sep, raw = part.strip().partition("=")
            if sep and name == auth.COOKIE_NAME:
                return raw.strip()
    return None


def sub_paths(scope: dict) -> tuple[str, ...]:
    """Every plausible reading of "the path within the ytdl app".

    Starlette has changed how it hands a mount its path more than once (it used
    to rewrite scope["path"] to the remainder; current versions leave the full
    path and set root_path to the mount prefix), so both are checked and the
    strictest answer wins rather than pinning a version. Cheap; two string
    comparisons per request.
    """
    path = scope.get("path", "")
    candidates = [path]
    root = scope.get("root_path", "")
    if root and path.startswith(root):
        candidates.append(path[len(root):] or "/")
    if path.startswith(MOUNT_PATH):
        candidates.append(path[len(MOUNT_PATH):] or "/")
    return tuple(dict.fromkeys(candidates))


async def _json_response(send: Callable, status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode())],
    })
    await send({"type": "http.response.body", "body": payload})


def _add_in_repo_ytdl_web() -> bool:
    """Put this repo's ytdl/web on sys.path so `import ytdlweb` can find it.

    Dev convenience ONLY, for running the dashboard straight out of a checkout
    where nothing has set PYTHONPATH. In the container this file lives under
    /app/src/ccsync_dashboard/, so parents[3] is /, the candidate does not
    exist, and this is inert -- the deployed import goes on coming off the
    PYTHONPATH run.sh sets, which is why the entry is APPENDED: an explicitly
    configured path must keep winning over a guess made from __file__.
    """
    candidate = Path(__file__).resolve().parents[3] / "ytdl" / "web"
    if not (candidate / "ytdlweb" / "main.py").is_file():
        return False
    entry = str(candidate)
    if entry not in sys.path:
        sys.path.append(entry)
    log.info("importing the ytdl app from the in-repo checkout at %s "
             "(nothing put it on PYTHONPATH)", entry)
    return True


def feature_enabled(settings: Settings) -> bool:
    """Has THIS SITE enabled the YouTube downloader? DB row first, env after.

    dash-release-ai-1 (2026-08-21). The flag has two homes and this mount used
    to read only one of them: `DASH_SITE_YOUTUBE_DOWNLOAD` in the container's
    environment. The other is a `site_settings` row, which is what the Settings
    page writes and what `GET /api/v1/site` resolves the manifest from -- so on
    a vendor build (no env var) an admin ticking "YouTube downloader" turned
    the feature on for every companion in the fleet, which then called
    /ytdl/api/... and got a 404 from a dashboard that had decided the answer at
    boot and never looked again. The reverse was as wrong: env=1 with the box
    unticked left the dashboard serving downloads the site says it does not do.

    Same row-then-environment precedence as ai_providers.cli_enabled, and the
    same fail-safe: anything that goes wrong reading the row falls back to the
    environment rather than flipping a legal switch on a customer's behalf.
    """
    fallback = bool(getattr(settings, "site_feature_youtube_download", False))
    try:
        conn = db.connect(settings.db_path)
    except Exception:  # noqa: BLE001 - an unopenable DB decides nothing here
        return fallback
    try:
        resolver = getattr(site_store, "feature_enabled", None)
        if resolver is not None:
            return bool(resolver(conn, settings, FEATURE_KEY))
        manifest = site_store.resolved_manifest(conn, settings)
        return bool(manifest.get("features", {}).get(FEATURE_KEY, fallback))
    except Exception as e:  # noqa: BLE001
        log.warning("could not read the site's youtube_download flag (%s: %s); "
                    "falling back to DASH_SITE_YOUTUBE_DOWNLOAD",
                    type(e).__name__, e)
        return fallback
    finally:
        conn.close()


class YtdlFeatureGate:
    """The site switch, re-read per request rather than decided at boot.

    dash-release-ai-1 (2026-08-21). Two things live here and they are the same
    thing seen from either end of the tick:

      - while the site says NO, every path under /ytdl answers 404 and NOTHING
        is imported. That is the property the switch was written for: the
        customer, not the vendor, decides whether downloading third-party
        YouTube material is lawful for them (docs/legal/YOUTUBE_FEATURE_NOTICE.md),
        and an off site pays no yt-dlp import and runs no pipeline thread.
      - the moment it says YES, the next request loads the sub-app and serves
        it. No `--recreate`, no restart -- which matters because the SAME tick
        publishes the feature to every companion through /api/v1/site, and they
        start calling the fleet routes at once.

    The load happens inline on the request that needs it (one import, one
    schema apply, one worker start, once) rather than on a background thread:
    a companion whose claim is the first call in deserves the answer, not a
    503 while something warms up.
    """

    def __init__(self, app: FastAPI, settings: Settings, status: str,
                 sub_app: Any | None) -> None:
        self._dash = app
        self._settings = settings
        self._sub = sub_app
        self.status = status
        # What the loaded sub-app's state is, remembered separately from
        # `status`: an off-then-on again site has to be put back to the state
        # its mount actually has (a DEGRADED one must not come back as
        # MOUNTED and be advertised in the nav).
        self._loaded_status = status if sub_app is not None else ABSENT
        self._enabled = sub_app is not None
        self._checked_at = time.monotonic() if sub_app is not None else 0.0
        self._failed_at = 0.0
        self._lock = threading.Lock()

    def _feature_on(self) -> bool:
        now = time.monotonic()
        if now - self._checked_at < FEATURE_TTL_SECONDS:
            return self._enabled
        self._enabled = feature_enabled(self._settings)
        self._checked_at = now
        return self._enabled

    def _record(self, status: str) -> None:
        """Keep app.state in step, so the nav stops advertising a feature that
        has just been turned off (and starts advertising one that has just been
        turned on, from the first request that reaches here)."""
        if status == self.status:
            return
        self.status = status
        try:
            self._dash.state.ytdl_status = status
            self._dash.state.ytdl_mounted = status == MOUNTED
        except Exception:  # noqa: BLE001 - a mount is not worth a 500
            pass

    def _current(self) -> Any | None:
        if not self._feature_on():
            self._record(DISABLED)
            return None
        if self._sub is not None:
            self._record(self._loaded_status)
            return self._sub
        with self._lock:
            if self._sub is not None:
                return self._sub
            now = time.monotonic()
            if self._failed_at and (now - self._failed_at) < LOAD_RETRY_SECONDS:
                return None
            status, gated = load_ytdl_app(self._settings)
            if gated is None:
                self._failed_at = now
                self._record(status)
                return None
            self._sub = gated
            self._loaded_status = status
            self._record(status)
            log.info("ytdl UI loaded on demand: this site enabled the YouTube "
                     "downloader while the dashboard was running")
            return gated

    async def __call__(self, scope, receive, send) -> None:
        sub = self._current()
        if sub is None:
            if scope.get("type") == "websocket":
                await send({"type": "websocket.close", "code": 1000})
                return
            await _json_response(send, 404, {"detail": "Not Found"})
            return
        await sub(scope, receive, send)


def load_ytdl_app(settings: Settings) -> tuple[str, Any | None]:
    """Import the sub-app and wrap it in its gate. -> (status, gated or None).

    Everything about the import is best-effort (see the module docstring): a
    deployment whose ytdl tree is missing, stale or mid-upgrade -- or whose
    dashboard venv simply has no yt-dlp -- carries on with the feature ABSENT.
    """
    try:
        try:
            from ytdlweb.main import app as ytdl_app  # type: ignore[import-not-found]
        except ImportError:
            # A `ytdlweb` already in sys.modules is somebody's deliberate
            # choice (the tests' fake, most of all) and its failure is theirs
            # to own.
            if "ytdlweb" in sys.modules or not _add_in_repo_ytdl_web():
                raise
            from ytdlweb.main import app as ytdl_app  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001 - see module docstring
        log.warning("ytdl UI not mounted (%s: %s); dashboard continues without it",
                    type(e).__name__, e)
        return ABSENT, None

    gated = YtdlGate(ytdl_app, settings.session_secret, settings)

    # WHICH AI answers the sub-app's two calls (2026-08-18). Env at mount time
    # is not enough any more: keys are typed on Settings and can change while
    # the container runs, so what is installed is a CALLBACK the sub-app
    # invokes per call (ai_providers.make_lookup -> ai_backend's
    # set_provider_lookup). Best-effort in both directions -- an older ytdl
    # tree with no ai_backend keeps working off its own environment, and a
    # failure to install the hook must not un-mount the feature.
    _install_ai_provider_lookup(ytdl_app, settings)
    _install_fleet_stamp_trust()

    try:
        _init_ytdl_storage()
    except Exception as e:  # noqa: BLE001
        # Mounted, but NOT advertised: /ytdl is reachable for anyone who types
        # it (and logs the real error) while the nav stays quiet. Overwhelmingly
        # this is YTDL_DATA_ROOT -- a read-only bind mount, or a directory the
        # container's uid cannot write, so sqlite answers "unable to open
        # database file" on every request.
        log.error("ytdl data root could not be prepared (%s: %s); mounting it "
                  "DEGRADED -- every /ytdl request will fail until YTDL_DATA_ROOT "
                  "is writable by this container's uid, and the nav link is hidden",
                  type(e).__name__, e)
        return DEGRADED, gated

    return MOUNTED, gated


def _install_fleet_stamp_trust() -> bool:
    """Tell the sub-app it may believe X-CCSync-Fleet-Auth. -> whether it took.

    ytdl-web-1 (2026-08-21). The same shape as the AI-provider lookup and for
    the same reason: a module-level switch, because what reads it is a request
    handler with no app object in hand, and best-effort, because an older ytdl
    tree that does not know the header must keep mounting (it goes on comparing
    the shared token, which every companion still sends).
    """
    try:
        from ytdlweb import routes_fleet  # type: ignore[import-not-found]

        routes_fleet.trust_gate_stamp(True)
        return True
    except Exception as e:  # noqa: BLE001 - see the module docstring
        log.info("this ytdl tree does not take a fleet-auth stamp (%s: %s); its "
                 "fleet routes will accept the shared DASH_REPORT_TOKEN only, "
                 "so an editor holding a per-editor cce1 token cannot download "
                 "locally until it is redeployed", type(e).__name__, e)
        return False


def mount_ytdl(app: FastAPI, settings: Settings) -> str:
    """Mount the ytdl app at /ytdl. Returns MOUNTED / DISABLED / ABSENT / DEGRADED.

    The site switch comes first and short-circuits everything else: the feature
    is OFF unless this site turned it on (2026-08-17). Since 2026-08-21 that
    question is asked of the SITE SETTINGS ROW first and the environment second
    (feature_enabled), and it is asked again per request rather than once at
    boot (YtdlFeatureGate) -- because the Settings tick that turns it on is the
    same tick that publishes it to every companion through /api/v1/site, and a
    dashboard that answered at boot 404'd every one of the fleet calls that
    followed (dash-release-ai-1).

    The import is guarded and the failure is logged rather than raised, so a
    deployment whose ytdl tree is missing, stale or mid-upgrade -- or one whose
    dashboard venv simply does not have yt-dlp -- starts normally with the
    feature absent.

    Tri-state on purpose: a mount whose data root could not be prepared answers
    every request with a 500, and reporting that as success is how the nav ends
    up advertising a link to a broken page (the operator sees a green
    healthcheck and a feature that does not work).

    Takes `settings` rather than a token, unlike mount_broll: what it needs is
    the session secret, because this gate mints the identity the sub-app
    authorises on (see YtdlGate). A blank secret is not refused here -- the
    dashboard already cannot log anyone in without one, so every request would
    arrive with no session at all and the sub-app would 401 by itself.
    """
    if not feature_enabled(settings):
        # NOTHING IS IMPORTED HERE, deliberately: an off site must not load the
        # downloader's code, so there is no yt-dlp import cost and no pipeline
        # thread. What IS mounted is the feature gate, which answers 404 to
        # every path under /ytdl for exactly as long as the site says no, and
        # loads the sub-app on the first request after an admin says yes.
        log.info("ytdl UI not serving: this site has not enabled the YouTube "
                 "downloader ([features] youtube_download in site.toml / on "
                 "Settings / DASH_SITE_YOUTUBE_DOWNLOAD=1). See "
                 "docs/legal/YOUTUBE_FEATURE_NOTICE.md")
        app.mount(MOUNT_PATH, YtdlFeatureGate(app, settings, DISABLED, None))
        return DISABLED

    status, gated = load_ytdl_app(settings)
    if gated is None:
        # ABSENT: there is nothing to serve and a per-request retry would walk
        # sys.path (and import yt-dlp) on every poll. Left unmounted, as it has
        # always been -- deploying the tree is a deployment, and a deployment
        # restarts the container.
        return status

    app.mount(MOUNT_PATH, YtdlFeatureGate(app, settings, status, gated))
    if status == MOUNTED:
        log.info("ytdl UI mounted at %s", MOUNT_PATH)
    return status


def _install_ai_provider_lookup(ytdl_app: Any, settings: Settings) -> bool:
    """Give the sub-app the dashboard's "which provider, with what credential"
    callback. -> whether it took.

    TWO PLACES, on purpose. `ai_backend.set_provider_lookup` is a module
    global because the thing that asks is the ytdl WORKER THREAD, which has no
    request and no app object in hand; `ytdl_app.state.ai_provider_lookup` is
    the same callable where an operator (or a test) can see what was
    installed, and is the fallback ai_backend reads if only the attribute was
    set. Neither carries a key: the callback FETCHES one per call, so nothing
    is captured here that a later Settings edit would make stale.
    """
    try:
        from . import ai_providers

        lookup = ai_providers.make_lookup(settings)
        try:
            ytdl_app.state.ai_provider_lookup = lookup
        except Exception:  # noqa: BLE001 - a sub-app with no state is still mountable
            pass
        from ytdlweb import ai_backend  # type: ignore[import-not-found]

        ai_backend.set_provider_lookup(lookup)
        return True
    except Exception as e:  # noqa: BLE001 - see the module docstring
        log.warning("ytdl AI-provider lookup not installed (%s: %s); the sub-app "
                    "will fall back to ANTHROPIC_API_KEY / OPENAI_API_KEY / "
                    "DEEPSEEK_API_KEY from the container's environment",
                    type(e).__name__, e)
        return False


def _init_ytdl_storage() -> None:
    """Run what the ytdl app's own lifespan would have run.

    STARLETTE DOES NOT RUN A MOUNTED SUB-APP'S LIFESPAN -- only the outermost
    app's. That is not a detail here the way it is for music (whose db applies
    its schema lazily on first use): ytdlweb's pipeline runs on a singleton
    daemon thread started by ensure_started(), and without this call there is
    no thread, so every job sits in `queued` forever while the UI cheerfully
    polls it. Mounted, the lifespan never fires; this IS the lifespan.

    It doubles as the probe that tells MOUNTED from DEGRADED. Without it a data
    root the container cannot open is reported as a working mount and the nav
    offers a link to a page that 500s on every request. Idempotent throughout
    -- the schema is CREATE TABLE IF NOT EXISTS and ensure_started() is a
    no-op once the thread is alive -- and it opens and closes its own
    connection rather than priming any upstream global.
    """
    from ytdlweb import config as ytdl_config  # type: ignore[import-not-found]
    from ytdlweb import db as ytdl_db  # type: ignore[import-not-found]
    from ytdlweb import worker as ytdl_worker  # type: ignore[import-not-found]

    # The sub-app's own config is the source of truth (it resolves
    # YTDL_DATA_ROOT at import time, as musicweb.config does); the environment
    # is the fallback so a rename upstream degrades the mount's tidiness, not
    # the mount.
    root = getattr(ytdl_config, "DATA_ROOT", "") or os.environ.get(
        "YTDL_DATA_ROOT", "./data")
    Path(root).mkdir(parents=True, exist_ok=True)

    con = ytdl_db.connect()
    try:
        ytdl_db.init(con)
    finally:
        con.close()

    # After the schema, never before: the worker's first act is to recover
    # jobs left mid-pipeline by a restart, and it cannot query tables that do
    # not exist yet.
    ytdl_worker.ensure_started()

    # The download canary (ytdl 2026-08-26, docs/YTDL_RESILIENCE_PLAN.md WP5).
    # A no-op unless YTDL_CANARY_INTERVAL_SECONDS is set, which ships unset.
    #
    # WRAPPED, unlike the three imports above: this module is the mount's
    # storage probe, and its failure is what tells MOUNTED from DEGRADED. An
    # older ytdl-web tree on the host (or the fake ytdlweb the mount tests
    # install) has no ytdl_canary at all, and a missing OPTIONAL diagnostic
    # must not be able to report the whole downloader as degraded.
    try:
        from ytdlweb import ytdl_canary  # type: ignore[import-not-found]

        ytdl_canary.ensure_started()
    except (ImportError, AttributeError) as e:
        log.debug("ytdl canary not available (%s: %s); health will report it "
                  "disabled", type(e).__name__, e)
