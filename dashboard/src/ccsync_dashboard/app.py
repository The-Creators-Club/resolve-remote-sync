"""FastAPI app factory and uvicorn entry point.

The collector runs as an in-process daemon thread started by the lifespan
handler -- one container, one process, one worker (the SQLite concurrency
model depends on workers=1; see db.py).
"""
from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.requests import ClientDisconnect

from . import (
    api, assignments, auth, broll, crash_report, db, internal_sftp, local_users, music,
    oidc, release_feed, secrets_boot, sessions, setup_api, setup_routes, site_store,
    ui, ytdl,
)
from .collector import Collector
from .settings import Settings

log = logging.getLogger("ccsync.dashboard.app")

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"

# Paths reachable without a session. Everything else redirects to /login
# (pages) or 401s (JSON). The companion's token-authed endpoints and the
# login/health endpoints stay open.
_OPEN_EXACT = {
    "/login", "/api/v1/login", "/api/v1/logout", "/api/v1/me",
    "/api/v1/health", "/api/v1/report", "/api/v1/verify", "/favicon.ico",
    # The site manifest, on the same terms as /api/v1/health: an installer,
    # the onboarding wizard and the companion all read it BEFORE anyone has
    # logged in, and it carries no secret (SYNOLOGY_PORT_PLAN.md WP0 step 3;
    # see api.api_site for what may never be added to it).
    "/api/v1/site",
    # The two legs of an OIDC sign-in (COMMERCIAL_READINESS.md item 12,
    # 2026-08-17). Necessarily open: nobody has a session yet, which is the
    # entire point. Both are inert unless DASH_AUTH_METHOD=oidc -- they answer
    # 503 with the break-glass URL otherwise -- and the callback authenticates
    # on the signed flow cookie plus a verified id_token, never on being
    # reachable.
    oidc.LOGIN_PATH, oidc.CALLBACK_PATH,
    # First-admin bootstrap (WP C, docs/ZERO_TOUCH_PLAN.md §3.3/§3.5, 2026-08-17):
    # necessarily open, same reasoning as the OIDC pair above -- nobody has a
    # session before the wizard creates the first one. setup_api.setup_admin
    # enforces its own "no users yet" gate INSIDE the handler, so being open
    # here only ever matters for the single-admin bootstrap window; every
    # later call is a 409. See setup_api.py.
    "/api/v1/setup/status", "/api/v1/setup/admin",
    # The wizard page (ZERO_TOUCH_PLAN.md WP D, 2026-08-17). Open at the
    # MIDDLEWARE level only -- ui.page_setup does its own admin-or-first-run
    # gating and redirects to /login when neither applies (see
    # setup_routes.require_setup_access for the same rule on the API side).
    # This is what lets an appliance with no admin account yet land on
    # Setup instead of a 401.
    "/setup",
}

# The setup API prefix (ZERO_TOUCH_PLAN.md WP D). A prefix, not exact paths,
# because /api/v1/setup/tasks/{id}/{action} is not enumerable here -- every
# route under it gates itself via setup_routes.require_setup_access, which
# fails closed exactly like every other route in this app when the
# anonymous first-run window is not active (see that function's docstring).
_SETUP_API_PREFIX = "/api/v1/setup/"

# State-changing requests exempt from the CSRF check (COMMERCIAL_READINESS.md
# item 15, 2026-08-17). Two classes only:
#
#  * routes whose credential is a BEARER TOKEN, not the session cookie -- a
#    browser cannot be tricked into attaching an X-CCSync-Token it does not
#    have, so there is nothing to forge. The check itself already skips any
#    request that arrives without our session cookie, so this list is really
#    about the small overlap (a companion running in a logged-in browser's
#    machine).
#  * the mounted SPAs, whose own fetch() calls do not send the token YET. They
#    are documented in dashboard/README.md as owing that change; SameSite=Lax
#    on the session cookie is what holds the line until they make it, and it
#    holds it for exactly the cross-site POST case CSRF is about.
#
# /login and /api/v1/login are exempt for a third reason: there is no session
# yet, so there is no token to have. /api/v1/logout is exempt because the worst
# a forged one achieves is signing the victim OUT, and it is the JSON twin the
# onboarding flow may call without a page to read a token from; the UI's own
# /logout is NOT exempt and carries a hidden field.
#
# /api/v1/setup/admin is exempt for the same reason as /login: the FIRST call
# has no session to carry a token, and it is the call that matters -- every
# later one is a 409 regardless of CSRF (setup_api.setup_admin's own "no
# users yet" gate). Exempting it means the wizard's second retry (or a
# double-click) after the first call already minted a cookie is a clean 409,
# not a confusing 403 that reads like the wrong failure.
_CSRF_EXEMPT_EXACT = {"/login", "/api/v1/login", "/api/v1/logout", "/api/v1/report",
                      "/api/v1/verify", "/api/v1/setup/admin"}
_CSRF_EXEMPT_PREFIXES = ("/api/v1/selection/", "/api/v1/admin/packages/",
                         "/broll/", "/music/", "/ytdl/")
_CSRF_METHODS = ("POST", "PUT", "PATCH", "DELETE")

# Hard ceiling on a companion report body, enforced from Content-Length BEFORE
# anything is parsed. Every field inside ReportIn is individually capped too;
# this is the belt to that pair of braces, and the one thing that stops a
# holder of the shared report token from OOMing the single-worker container
# with a multi-GB body (see the unbounded-report finding). A full report with
# the maximum permitted manifest is well under 8 MB.
MAX_REPORT_BODY_BYTES = 8 * 1024 * 1024
# Companion builds are single-file PyInstaller exes; the current one is ~40 MB
# and this is a deliberately generous ceiling on top of it. Without a cap the
# publish route streamed an unbounded body straight to the /data dataset (an
# admin session, but a filled dataset takes the SQLite DB down with it).
# api_publish_package also counts the bytes it actually receives, because
# Content-Length is advisory for a chunked request.
MAX_PACKAGE_BODY_BYTES = 200 * 1024 * 1024
# The music UI's drag-and-drop ingest: a batch of cues an editor dropped on the
# page. Generous because a lossless drop is legitimately large, and it is a
# declared-length refusal only -- the bytes themselves are never buffered here.
MAX_UPLOAD_BODY_BYTES = 512 * 1024 * 1024
# Routes whose body is BUFFERED IN MEMORY downstream (FastAPI reads the whole
# thing before the route function runs), so the gate counts the bytes itself
# and stops at the ceiling. Content-Length is advisory: a chunked request
# carries none at all, which is what made the cap bypassable (KNOWN_BUGS B15).
_BODY_LIMITS = {"/api/v1/report": ("POST", MAX_REPORT_BODY_BYTES)}
# (path prefix, method, limit) -- the packages route has the platform and
# version in its path, so it can't be matched exactly. These are declaration
# checks ONLY: api_publish_package streams its body to disk and counts the
# bytes as it goes (api.py), so buffering it here would turn a 200 MB upload
# into 200 MB of resident memory -- exactly what this middleware exists to
# prevent.
_BODY_LIMIT_PREFIXES = (
    ("/api/v1/admin/packages/", "PUT", MAX_PACKAGE_BODY_BYTES),
    # musicweb's drag-and-drop ingest is a multipart audio upload that Starlette
    # spools past this middleware; buffering it here would turn a dropped album
    # into that many bytes of resident memory. Declaration check only, exactly
    # like the packages route above (DASH-3, 2026-08-11).
    ("/music/api/ingest", "POST", MAX_UPLOAD_BODY_BYTES),
)
# Everything else that writes: htmx form posts and small JSON documents. The
# gate used to cover exactly the two entries above, so every POST /partials/...
# and every pydantic-bodied /api/v1 route read an unbounded body into the
# single-worker container BEFORE any length check -- any editor with a valid
# session could OOM the fleet's sync-status view by posting a multi-GB body to
# a selection toggle (KNOWN_BUGS DASH-3, 2026-08-11). The largest legitimate
# body in this class is a b-roll /api/ingest/index document (a long clip's
# segments + transcript), well under a megabyte.
MAX_DEFAULT_BODY_BYTES = 4 * 1024 * 1024
_BODY_LIMIT_METHODS = ("POST", "PUT", "PATCH")


def _log_shared_token_migration(conn, settings: Settings) -> None:
    """Say at every boot how much of the fleet is still on the SHARED token.

    Per-editor report tokens landed 2026-08-17 (COMMERCIAL_READINESS.md item
    15) and every companion in the field holds only the shared one, so
    `DASH_SHARED_REPORT_TOKEN_ENABLED` defaults to true and this is the number
    that says when it can be turned off. Without it the migration has no
    finish line an operator can see, and "one token for the whole fleet" stays
    forever. Best-effort: a database that cannot be read must never stop the
    dashboard starting.
    """
    try:
        usage = db.count_shared_token_machines(conn)
    except Exception:  # noqa: BLE001
        return
    if not settings.shared_report_token_enabled:
        log.info("shared fleet report token is DISABLED; %d machine(s) authenticate "
                 "with per-editor tokens", usage["editor"])
        if usage["shared"]:
            log.warning("...but %d machine(s) last reported with the shared token and "
                        "will now be refused until they are given a per-editor token: %s",
                        usage["shared"], ", ".join(usage["machines"]))
        return
    if usage["shared"]:
        log.warning(
            "%d machine(s) still authenticate with the SHARED fleet report token "
            "(%s); %d use per-editor tokens. The shared token cannot be revoked for "
            "one editor -- mint per-editor tokens on Admin > Users, then set "
            "DASH_SHARED_REPORT_TOKEN_ENABLED=0.",
            usage["shared"], ", ".join(usage["machines"]), usage["editor"])
    elif usage["editor"]:
        log.info("every reporting machine (%d) uses a per-editor token; the shared "
                 "fleet token is still ACCEPTED -- set "
                 "DASH_SHARED_REPORT_TOKEN_ENABLED=0 to retire it", usage["editor"])


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        # Fills in any of the five secrets this deployment's environment does
        # not already carry, from <data>/secrets/ or freshly generated
        # (ZERO_TOUCH_PLAN.md WP D / secrets_boot.py, 2026-08-17) -- BEFORE
        # Settings.from_env() reads them. Only reached on the real `run()`
        # path: every test in this suite (and any caller with its own
        # provisioning story) passes `settings` explicitly and never touches
        # a filesystem here, which is what makes this a no-op for every
        # deployment that already sets all five in its compose env (every
        # deployment today) -- see secrets_boot.ensure_secrets' docstring.
        secrets_boot.ensure_secrets()
        settings = Settings.from_env()

    # Before the first thing that can refuse to start. Writes a JSON crash file
    # under /data for every unhandled exception -- the COLLECTOR THREAD above
    # all, which can die leaving a container that answers 200 forever (DASH-2).
    # Local and silent by default: the network sender needs DASH_SENTRY_DSN
    # *and* a sentry_sdk that deploy/requirements.txt does not install, and the
    # rotating json-lines file needs DASH_LOG_DIR. Never raises
    # (2026-08-17, COMMERCIAL_READINESS.md item 13).
    crash_report.install(settings)

    # Credentials are checked before anything is built, and a bad one refuses
    # to start (see the b-roll ingest token below for where this posture came
    # from). DASH_SESSION_SECRET and DASH_REPORT_TOKEN had no strength check at
    # all while that token had a 24-character floor -- and the shipped compose
    # sets both to "REPLACE_ME". A weak session secret is a forgeable ADMIN
    # cookie, which outranks everything else in this file. Same rule, same
    # function (broll.check_ingest_token), same answer.
    # COMMERCIAL_READINESS.md item 15, 2026-08-17.
    boot_problems = auth.check_boot_secrets(settings)
    if boot_problems and not settings.dev_insecure:
        raise RuntimeError(
            "refusing to start: " + "; ".join(boot_problems)
            + ". Generate secrets with `openssl rand -hex 24` and redeploy. "
              "(A lab may set DASH_DEV_INSECURE=1 to bypass this; never do that "
              "on a deployment.)"
        )
    if settings.dev_insecure:
        log.warning(
            "DASH_DEV_INSECURE=1: the secret-strength floor, the server-side session "
            "check and the CSRF token are all relaxed. This is a test/dev switch and "
            "must never be set on a deployment.%s",
            (" Problems bypassed: " + "; ".join(boot_problems)) if boot_problems else "",
        )
    log.info("%s", auth.describe_auth(settings))
    auth.warn_about_password_floor(settings)

    # Built here rather than in the lifespan so a test that calls create_app
    # without entering the lifespan still gets a working store (it creates its
    # own tables on first use).
    session_store = sessions.SessionStore(
        settings.db_path,
        idle_seconds=settings.session_idle_seconds,
        absolute_seconds=settings.session_absolute_seconds,
    )

    # The b-roll ingest routes are a WRITE path that no session protects (the
    # indexer is not a browser), so the token guarding them is a credential and
    # is validated before anything else happens. Refusing to start is the point:
    # a blank token used to fall through to the b-roll app's own dev mode, where
    # any logged-in editor -- or a stolen session cookie -- could repoint every
    # clip's archive path, and a placeholder token is a credential published in
    # this repo. Neither may be reachable by accident.
    broll_ingest_token = (settings.broll_ingest_token
                          or os.environ.get("BROLL_INGEST_TOKEN", "")).strip()
    if settings.broll_enabled:
        problem = broll.check_ingest_token(broll_ingest_token)
        if problem:
            raise RuntimeError(
                f"DASH_BROLL_ENABLED=1 but BROLL_INGEST_TOKEN {problem}. The b-roll "
                f"ingest endpoints are an unauthenticated write path for the indexer; "
                f"they are never served without a strong token. Set BROLL_INGEST_TOKEN "
                f"(e.g. `openssl rand -hex 24`) and redeploy, or set "
                f"DASH_BROLL_ENABLED=0 to run the dashboard without the b-roll UI."
            )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = db.connect(settings.db_path)
        db.migrate(conn)
        # Additive, idempotent DDL owned by the auth layer rather than a
        # numbered migration step (see sessions.SCHEMA): it carries no data any
        # other module reads, and a numbered step would have to be co-ordinated
        # with every other schema change in flight.
        session_store.ensure_schema(conn)
        _log_shared_token_migration(conn, settings)
        if str(settings.auth_method or "smb").strip().lower() == "local":
            # DASH_ADMIN_USERS names with no matching local account (break-
            # glass entries left over from an smb-mode deployment, or a typo)
            # -- one WARNING at boot rather than a silent no-op forever (see
            # local_users.warn_missing_admin_users).
            try:
                local_users.warn_missing_admin_users(conn, settings.admin_users)
            except Exception:  # noqa: BLE001 - a boot-time nicety, never fatal
                log.exception("could not check DASH_ADMIN_USERS against local accounts")
        # One-time DASH_SITE_* -> site_settings copy (ZERO_TOUCH_PLAN.md WP D,
        # 2026-08-17): a no-op after the first boot, and a no-op forever on a
        # deployment with no DASH_SITE_* set at all (see
        # site_store.seed_from_env_once's docstring for why that gate reads
        # os.environ rather than `settings`).
        try:
            site_store.seed_from_env_once(conn, settings)
        except Exception:  # noqa: BLE001 - never block boot over the manifest
            log.exception("site_settings seed-from-env failed")
        conn.close()
        session_store.prune()
        session_store.prune_attempts()
        # The collector runs even with no SYNCTHING_GUI_URL configured: it is
        # the only thing that ever calls db.prune, and eight tables grow
        # without bound on /data otherwise. run_cycle() skips every
        # Syncthing-backed kind in that configuration (see
        # collector.SYNCTHING_FREE_KINDS).
        collector = Collector(settings)
        collector.start()
        app.state.collector = collector
        # The vendor release feed's poller (ZERO_TOUCH_PLAN.md WP E,
        # 2026-08-17): gated on release_feed_url being set, so an
        # unconfigured feed adds no thread, no DNS lookup, no log line --
        # release_feed.py's own module docstring is the design writeup.
        feed_poller = None
        if settings.release_feed_url:
            feed_poller = release_feed.FeedPoller(settings, app.state)
            feed_poller.start()
        app.state.feed_poller = feed_poller
        try:
            yield
        finally:
            if collector is not None:
                collector.stop()
            if feed_poller is not None:
                feed_poller.stop()

    # No interactive docs, matching both mounts (broll.BLOCKED_PATHS /
    # music.BLOCKED_PATHS 404 theirs). FastAPI's defaults published the whole
    # route inventory and every admin request schema to any logged-in editor --
    # authz still held at each route, so disclosure rather than bypass, but the
    # dashboard publishes no API explorer (KNOWN_BUGS DASH-4, 2026-08-11).
    # The PRODUCT's name, not a customer's: this is the ASGI app title, which
    # a second deployment must not inherit branded as the first one
    # (2026-08-17, COMMERCIAL_READINESS.md item 10). A site that says who it
    # is gets "<org> — <product> Dashboard".
    app_title = " — ".join(
        p for p in (settings.site_org_name,
                    f"{settings.site_product_name or 'CC Sync'} Dashboard") if p)
    app = FastAPI(title=app_title, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.session_store = session_store

    def _too_large(limit: int) -> JSONResponse:
        return JSONResponse(
            {"detail": f"request body too large (max {limit} bytes)"},
            status_code=413,
        )

    def _declared_too_large(request, limit: int) -> bool:
        """Content-Length says it is over the ceiling. A missing header is NOT
        a pass -- that is a chunked request, which _buffer_body handles. Only
        reading this header is what made the cap bypassable (B15)."""
        declared = request.headers.get("content-length")
        if declared is None:
            return False
        try:
            return int(declared) > limit
        except ValueError:
            return True   # unparseable length: refuse rather than guess

    def _companion_credential(request) -> tuple[str, str | None]:
        """(AUTH_*, editor) for this request's X-CCSync-Token, middleware-side.

        A per-editor token can only be checked against the database, and this
        runs before any route has a connection -- so one is opened HERE, and
        only for a token that already has the per-editor SHAPE. The shared
        token (every companion in the fleet today) still costs no database
        work at all, and an unauthenticated request costs a regex.
        """
        token = request.headers.get("x-ccsync-token", "")
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

    def _report_auth_denial(request) -> JSONResponse | None:
        """The /api/v1/report token check, run BEFORE the body is read.

        /api/v1/report is in _OPEN_EXACT (the companion authenticates with
        X-CCSync-Token, not a session), and its route signature is
        `payload: ReportIn` -- so FastAPI used to read and pydantic-validate
        the entire body before api_report ever looked at the token. Any host
        on the LAN/tailnet could therefore spend the container's memory and
        CPU with no credentials at all (KNOWN_BUGS B15). api_report repeats
        this check: this is the belt, that is the braces, and a direct-to-route
        unit test must still 401.
        """
        if _companion_credential(request)[0] != api.AUTH_NONE:
            return None
        token = request.headers.get("x-ccsync-token", "")
        if not settings.report_token and not db.looks_like_editor_report_token(token):
            if settings.report_token_optional:
                return None
            return JSONResponse(
                {"detail": "report token not configured on server (set DASH_REPORT_TOKEN)"},
                status_code=401,
            )
        return JSONResponse(
            {"detail": "bad or missing X-CCSync-Token"}, status_code=401)

    async def _buffer_body(request, limit: int) -> bool:
        """Read the body in chunks, stopping at `limit`, and re-arm the
        request so the route still sees it.

        Returns True when the ceiling was exceeded. Nothing downstream reads
        from the socket afterwards: the replayed receive channel hands over
        the bytes already buffered here, which is what bounds the memory a
        single request can cost regardless of what Content-Length claimed.
        """
        chunks: list[bytes] = []
        size = 0
        try:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    return True
                chunks.append(chunk)
        except ClientDisconnect:
            return False
        body = b"".join(chunks)

        async def replay():
            return {"type": "http.request", "body": body, "more_body": False}

        request._body = body
        request._receive = replay
        return False

    def _origin_mismatch(request) -> bool:
        """True when the browser told us this request came from somewhere else.

        Browsers attach `Origin` to every cross-site POST, so this catches the
        whole class on its own -- including the forms a template might forget
        to give a token to. Same-origin requests either carry a matching Origin
        or none at all (some browsers omit it for same-origin form posts),
        which is why an ABSENT header is not a refusal."""
        origin = (request.headers.get("origin") or "").strip()
        if not origin or origin.lower() == "null":
            origin = (request.headers.get("referer") or "").strip()
            if not origin:
                return False
        host = (request.headers.get("host") or "").strip().lower()
        if not host:
            return False
        from urllib.parse import urlsplit

        return (urlsplit(origin).netloc or "").lower() != host

    async def _csrf_from_form(request) -> str:
        """The hidden field, for the plain (non-htmx) forms -- today just the
        logout button. body_size_gate has already buffered and re-armed the
        body by the time this middleware runs, so this costs no second read."""
        content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type != "application/x-www-form-urlencoded":
            return ""
        from urllib.parse import parse_qs

        try:
            body = await request.body()
            parsed = parse_qs(body.decode("utf-8", "replace"), max_num_fields=64)
        except Exception:                                       # noqa: BLE001
            return ""
        values = parsed.get(auth.CSRF_FIELD) or []
        return values[0] if values else ""

    # Added FIRST on purpose, which makes it the INNERMOST middleware: it runs
    # after body_size_gate has buffered and re-armed the body, so reading the
    # hidden form field here costs nothing and cannot steal the stream from the
    # route. Reversing the two would leave every htmx POST bodyless.
    @app.middleware("http")
    async def csrf_gate(request, call_next):
        if request.method not in _CSRF_METHODS:
            return await call_next(request)
        path = request.url.path
        if path in _CSRF_EXEMPT_EXACT or path.startswith(_CSRF_EXEMPT_PREFIXES):
            return await call_next(request)
        # Only sessions THIS server minted are checked -- see
        # auth._resolve_session. In a deployment that is every session there
        # is (an unknown session id does not authenticate at all), and in the
        # suite it is none of the hand-signed ones.
        if not auth.session_is_tracked(request):
            return await call_next(request)
        presented = request.headers.get(auth.CSRF_HEADER, "")
        if not presented:
            presented = await _csrf_from_form(request)
        if _origin_mismatch(request) or not auth.csrf_ok(request, presented):
            log.warning("CSRF refusal: %s %s from %s", request.method, path,
                        auth.client_ip(request))
            return JSONResponse(
                {"detail": "missing or bad CSRF token -- reload the page and try again"},
                status_code=403,
            )
        return await call_next(request)

    @app.middleware("http")
    async def body_size_gate(request, call_next):
        exact = _BODY_LIMITS.get(request.url.path)
        if exact is not None and request.method == exact[0]:
            limit = exact[1]
            if _declared_too_large(request, limit):
                return _too_large(limit)
            # Credentials first: never spend memory or a pydantic parse on an
            # unauthenticated body.
            if request.url.path == "/api/v1/report":
                denial = _report_auth_denial(request)
                if denial is not None:
                    return denial
            if await _buffer_body(request, limit):
                return _too_large(limit)
            return await call_next(request)
        for prefix, method, value in _BODY_LIMIT_PREFIXES:
            if request.method == method and request.url.path.startswith(prefix):
                if _declared_too_large(request, value):
                    return _too_large(value)
                # Carved out of the default ceiling below ON PURPOSE: these
                # bodies are streamed/spooled downstream, so buffering them
                # here would BE the memory problem this middleware prevents.
                return await call_next(request)
        if request.method in _BODY_LIMIT_METHODS:
            if _declared_too_large(request, MAX_DEFAULT_BODY_BYTES):
                return _too_large(MAX_DEFAULT_BODY_BYTES)
            if await _buffer_body(request, MAX_DEFAULT_BODY_BYTES):
                return _too_large(MAX_DEFAULT_BODY_BYTES)
        return await call_next(request)

    def _broll_ingest_token_ok(request) -> bool:
        """The indexer writing to /broll/api/ingest/* is not a browser.

        This only decides whether the request may SKIP the login gate; the
        mounted sub-app is wrapped in broll.BrollGate, which re-checks the same
        token on every ingest request and fails closed. So a session alone never
        reaches ingest, and neither does a deployment that somehow got here with
        no token (create_app refuses to build one, and the token validated there
        is the token captured here -- the environment is not re-read per
        request, where it could have been mutated).
        """
        if not broll_ingest_token:
            return False
        return api.token_ok(broll_ingest_token, request.headers.get("x-ingest-token", ""))

    def _companion_token_ok(request) -> bool:
        # Either fleet credential: the shared DASH_REPORT_TOKEN, or a
        # per-editor token (COMMERCIAL_READINESS.md item 15, 2026-08-17). Both
        # are compared with hmac.compare_digest inside api.py -- `==` on a
        # secret leaks its length and matching prefix through timing.
        #
        # This decides only whether the request may SKIP the login gate; the
        # routes behind it re-check, and the selection routes additionally
        # demand that a per-editor token match the editor in the path.
        return _companion_credential(request)[0] != api.AUTH_NONE

    # The ytdl fleet routes (docs/YTDL_LOCAL_DOWNLOAD.md §4): claim, heartbeat,
    # manifest, per-clip status. Machine-to-machine, so they authenticate with
    # the fleet token and there is no session to gate on -- but ONLY these
    # four shapes. /ytdl/api/jobs/{id} itself (the SPA's 1.5 s poll), mode-lock,
    # cancel and the rest stay session-gated: the bypass is per-suffix, not
    # per-prefix, so a leaked token cannot read a browser's job view.
    _ytdl_fleet_re = re.compile(
        r"^/ytdl/api/jobs/\d+/(claim|heartbeat|download-manifest|clips/[^/]+/status)$"
    )

    # The b-roll ingest fleet routes (docs/BROLL_INGEST_PLAN.md §4.2,
    # 2026-08-18): claim, heartbeat, release and the three per-item posts. Same
    # posture as the ytdl block above and for the same reason -- these calls
    # happen while the editor is away from their desk and no browser is open,
    # so there is no session to gate on; they authenticate with the fleet token
    # and re-check it (plus a SIGNED identity) inside the sub-app.
    #
    # Per-suffix, never per-prefix. /broll/api/ingest-batches -- the SPA's own
    # panel, which decides whose batches you may cancel -- stays fully
    # session-gated, so a leaked fleet token cannot read or stop one.
    #
    # The 32-hex uid shape is pinned here on purpose: it is what
    # ingest_batches.new_uid mints, and a route that took an integer id would
    # be one an editor could enumerate.
    _broll_fleet_re = re.compile(
        r"^/broll/api/fleet/ingest/batches/[0-9a-f]{32}/"
        r"(claim|heartbeat|release|items/[0-9a-f]{32}/(status|result|uploaded))$"
    )

    # The MUSIC ingest fleet routes (docs/MUSIC_INGEST_PLAN.md step 2,
    # 2026-08-18). Identical posture and identical shape to the b-roll block
    # above -- an editor's companion embedding a dropped album with the CLAP
    # audio tower while nobody is at the browser -- so it gets its own regex
    # rather than a widened one: two mounts, two prefixes, and a pattern that
    # tried to cover both would be a pattern nobody can read a carve-out out of.
    #
    # Per-suffix, never per-prefix. /music/api/ingest-batches -- the SPA's own
    # panel, which decides whose batches you may cancel -- stays fully
    # session-gated, so a leaked fleet token cannot read or stop one.
    _music_fleet_re = re.compile(
        r"^/music/api/fleet/ingest/batches/[0-9a-f]{32}/"
        r"(claim|heartbeat|release|items/[0-9a-f]{32}/(status|result|uploaded))$"
    )

    @app.middleware("http")
    async def login_gate(request, call_next):
        path = request.url.path
        if (
            path in _OPEN_EXACT
            or path.startswith("/static/")
            # internal_sftp.py's own routes: no cookie jar on the other end (a
            # sidecar container), gated on a bearer token instead -- see
            # internal_sftp._require_internal_token. Never session-reachable
            # either way (it is a plain-text authorized_keys dump), so this
            # is not a login bypass for a browser, only for that one bearer.
            or path.startswith("/internal/sftp/")
            # companion reads its selection with the shared token (the route
            # itself additionally demands a matching X-CCSync-Identity)
            or (path.startswith("/api/v1/selection/") and _companion_token_ok(request))
            # companion downloads published upgrade packages the same way
            or (path.startswith("/api/v1/companion/package/") and _companion_token_ok(request))
            # the indexer pushing into the mounted b-roll app, token-gated
            or (path.startswith("/broll/api/ingest/") and _broll_ingest_token_ok(request))
            # the ytdl local-download client config: unauthenticated-read BY
            # DESIGN (docs/YTDL_LOCAL_DOWNLOAD.md §4) -- the companion's
            # yt-dlp sidecar manager reads it before it holds anything to
            # claim, and nothing in it is secret (a version floor and a pause).
            or path == "/ytdl/api/config/ytdl-client"
            # the companion executing a local download for a claimed job --
            # same fleet-token posture as the selection route above
            or (_ytdl_fleet_re.match(path) is not None and _companion_token_ok(request))
            # the companion indexing a claimed b-roll ingest batch -- same
            # fleet-token posture again (docs/BROLL_INGEST_PLAN.md §4.2)
            or (_broll_fleet_re.match(path) is not None and _companion_token_ok(request))
            # and the same for a claimed MUSIC ingest batch
            # (docs/MUSIC_INGEST_PLAN.md step 2)
            or (_music_fleet_re.match(path) is not None and _companion_token_ok(request))
            # the setup wizard's own API (ZERO_TOUCH_PLAN.md WP D). Open at
            # THIS layer only -- every route under it re-checks via
            # setup_routes.require_setup_access, which is the actual gate
            # (admin session, or the narrow anonymous first-run window).
            or path.startswith(_SETUP_API_PREFIX)
        ):
            return await call_next(request)
        if auth.get_session_user(request) is None:
            # /broll/api and /broll/media are fetched by JS and by <video>, which
            # cannot follow a 303 to an HTML login page -- the SPA would parse
            # the page as JSON and the player would fail opaquely. Answer them
            # the same way the dashboard's own API does. Same for /music/api,
            # which carries both the music SPA's fetches and its <audio> src
            # (musicweb serves audio from /api/audio/{id}, not a /media prefix).
            # /ytdl/api is the same story again, and worse if it is missed: the
            # downloader SPA POLLS api/jobs/{id} every 1.5s, so a session that
            # expired mid-pipeline would hand it a login page to JSON.parse
            # once per tick.
            if path.startswith(("/api/", "/broll/api/", "/broll/media/",
                                "/music/api/", "/ytdl/api/")):
                return JSONResponse({"detail": "login required"}, status_code=401)
            # Preserve the destination through login (e.g. the companion's
            # /project-setup deep link) -- ui.py's _safe_next re-validates it.
            from urllib.parse import quote, urlsplit

            target = path + (f"?{request.url.query}" if request.url.query else "")
            # htmx polls every live fragment on every page (/partials/transfers
            # every 2s, the sidebar every 30s, ...) over XHR, which follows a
            # 303 TRANSPARENTLY: the poll got 200 + the whole login DOCUMENT
            # and swapped it inside <main> or the sidebar -- a garbled page,
            # nested <html>, a second topbar still naming the logged-out user,
            # still polling, and no navigation to /login ever. HX-Redirect is
            # the header htmx turns into a real browser navigation; plain
            # document GETs keep the 303 (DASH-4, 2026-08-14).
            if request.headers.get("hx-request", "").lower() == "true":
                # ...to the PAGE the fragment belongs to, not the fragment's
                # own URL -- ?next=/partials/transfers would land the editor on
                # a bare fragment after logging in.
                current = urlsplit(request.headers.get("hx-current-url", ""))
                page = current.path + (f"?{current.query}" if current.query else "")
                if page.startswith("/"):
                    target = page
                return Response(
                    status_code=401,
                    headers={"HX-Redirect": f"/login?next={quote(target, safe='')}"},
                )
            return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)
        return await call_next(request)

    @app.exception_handler(Exception)
    async def unhandled_error(request, exc):  # noqa: ANN001
        """One generic body for every unhandled exception; the detail is logged.

        Starlette's default answers a plain-text "Internal Server Error", which
        leaks nothing -- but it is HTML-ish text handed to fetch() callers that
        parse JSON, and it leaves no record tying the failure to a request.
        This logs the traceback WITH the method and path (the thing an operator
        needs) and answers the same shape as every other error in this API
        (COMMERCIAL_READINESS.md §C L "error detail leaks", 2026-08-17).

        Nothing derived from the exception reaches the client: no message, no
        type name, no path -- a stack frame in a 500 body is how an editor
        learns the container's directory layout. Starlette's ServerErrorMiddleware
        still re-raises afterwards, so `TestClient(raise_server_exceptions=True)`
        and uvicorn's own error log are unchanged.
        """
        log.exception("unhandled error serving %s %s", request.method,
                      request.url.path)
        return JSONResponse({"detail": "internal error"}, status_code=500)

    app.include_router(api.router)
    app.include_router(setup_api.router)
    app.include_router(internal_sftp.router)
    # The SetupEngine's API (ZERO_TOUCH_PLAN.md WP D): wizard task state and
    # the site-manifest admin routes. Its own module, its own router, one
    # line here -- CLAUDE.md's "new logic in NEW modules" for shared files.
    app.include_router(setup_routes.router)
    app.include_router(release_feed.router)
    app.include_router(ui.router)
    # The admin project<->editor assignment matrix (2026-08-17): one page,
    # /admin/assignments, that writes nothing itself -- it calls the selection
    # routes api.router already registered above (see assignments.py).
    app.include_router(assignments.router)
    # Always mounted, never active unless DASH_AUTH_METHOD=oidc: both routes
    # start by re-checking the OIDC settings and answer 503 with the
    # break-glass URL when they are absent. Mounting it conditionally would
    # mean a misconfigured issuer produced a 404 -- indistinguishable from an
    # old build -- instead of a message naming the missing variable.
    app.include_router(oidc.router)

    # Mounted AFTER the routers so a b-roll route can never shadow a dashboard
    # one, and behind a flag so the fleet dashboard never depends on the b-roll
    # code being present. mount_broll() reports mounted/absent/degraded; only a
    # fully working mount is advertised in the nav (ui.py), because a link to a
    # page that 500s on every request is worse than no link.
    # `settings` as well as the token since 2026-08-18: BrollGate mints the
    # ingest panel's identity (X-CCSync-User/X-CCSync-Admin) from the session
    # cookie with settings.session_secret, the way YtdlGate already does.
    app.state.broll_status = (
        broll.mount_broll(app, broll_ingest_token, settings) if settings.broll_enabled
        else broll.ABSENT
    )
    app.state.broll_mounted = app.state.broll_status == broll.MOUNTED

    # Same contract for the music platform, and mounted the same way: after the
    # routers, best-effort, tri-state, only advertised when it fully took. Still
    # no flag and no token, unlike b-roll -- the music FLEET routes fail closed
    # on their own and there is no "unconfigured = open" branch to re-check;
    # whether the music tree is shipped to the host IS the switch, and a host
    # without it simply reports ABSENT. `settings` since 2026-08-18: MusicGate
    # mints the ingest panel's identity from the session cookie the way
    # BrollGate does. See music.py.
    app.state.music_status = music.mount_music(app, settings)
    app.state.music_mounted = app.state.music_status == music.MOUNTED

    # And the YouTube downloader, on the same terms as music -- shipping the
    # tree is the switch, no flag and no token. It gets `settings` rather than
    # nothing because its gate mints the identity the sub-app authorises on
    # (which projects a job may download into), and that identity is decoded
    # from the session cookie with settings.session_secret. See ytdl.py.
    app.state.ytdl_status = ytdl.mount_ytdl(app, settings)
    app.state.ytdl_mounted = app.state.ytdl_status == ytdl.MOUNTED
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Browsers request /favicon.ico unprompted (the path is already in
    # _OPEN_EXACT); serve the product mark instead of a 404. The
    # <link rel="icon"> in base.html covers everything else.
    favicon_file = STATIC_DIR / "favicon.ico"
    if favicon_file.is_file():
        @app.get("/favicon.ico", include_in_schema=False)
        def favicon() -> FileResponse:
            return FileResponse(str(favicon_file), media_type="image/x-icon")

    return app


def run() -> None:
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port, workers=1)


if __name__ == "__main__":
    run()
