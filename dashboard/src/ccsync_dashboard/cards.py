"""Serve the Timeline Cards page from inside the dashboard, at /cards.

docs/TIMELINE-CARDS-INTO-CCSYNC.md §3.2 and §6 phase 3 (2026-08-30). The
same contract `/broll` and `/music` are mounted on (`broll.py:mount_broll` is
the template, and ARCHITECTURE.md §4 states the three rules): in-process,
behind `login_gate`, tri-state, NEVER fatal. An editor gets one URL and one
login instead of a second service on :8800 with a `?key=` in the address bar.

WHAT IS DIFFERENT FROM THE OTHER THREE MOUNTS, and why each is handled the
way it is:

  * **The app is not ASGI, and not even WSGI.** Timeline Cards' page is a
    `BaseHTTPRequestHandler` with ~70 hand-dispatched routes. `cards_wsgi.py`
    turns one handler class into a streaming WSGI application and
    `a2wsgi.WSGIMiddleware` turns that into an ASGI app -- so every route
    answers under `/cards/...` byte for byte, Range responses included. The
    decision not to rewrite them as an `APIRouter` is §3.2 problem 1.
  * **It carries an ENGINE, not just routes.** `ProjectAgentEngine` owns
    background threads (the library sweep, the ffmpeg worker, the translation
    and search runs). They start with the mount and stop with the app's
    shutdown, which is `stop_engine()` in app.py's lifespan -- Starlette does
    not run a mounted app's lifespan, and this one has no lifespan to run
    anyway.
  * **It needs mounts the dashboard did not have**: the vault rw and the
    footage share ro (docs/DOCKER.md, "The Timeline Cards mounts"). Both
    optional: with no vault configured this is DISABLED with a reason, which
    is the honest answer -- an engine rooted at a path that is not there
    would answer every request with an empty episode.
  * **`CARDS_KEY` IS RETIRED HERE.** The standalone server's browser gate is
    a shared secret in a URL; behind this login the session cookie is real
    auth and a second gate could only ever disagree with it. `access_key` is
    set to None at construction and there is no setting for it.
  * **`/api/restart` IS BLOCKED.** In the standalone server that route
    re-execs the process; in this one `restart_server` would `os._exit(0)`
    the DASHBOARD. It is refused by the gate, with a sentence the page can
    show, and `self.server` is an object whose `shutdown()` refuses as well.

The engine's settings are the dashboard's own (`DASH_CARDS_*`, CONFIG.md
§3), one variable for each `CARDS_*` the standalone container takes -- so
`server.main`'s `--remote-agent` branch and `build_engine` below construct
the same engine from the same values.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

from .settings import Settings

log = logging.getLogger("ccsync.dashboard.cards")

MOUNT_PATH = "/cards"

# The tri-state, on broll.py's terms. DISABLED covers every "this deployment
# did not ask for it" -- the flag is off, no checkout is configured, no vault
# is mounted -- and each carries its own sentence in `detail`, because
# "disabled" alone is the answer to a different question than the one an
# admin is asking. ABSENT is "it was asked for and the code is not there",
# which is an operator problem and logs at WARNING.
MOUNTED = "mounted"
ABSENT = "absent"
DISABLED = "disabled"

# Routes the mounted page must never reach. `/api/restart` re-execs the
# server process, which here is the dashboard (see the module docstring).
BLOCKED_PATHS = frozenset({"/api/restart"})

# The page's own `/agent/*` protocol. It is served by cards_tunnel's three
# routes, which are registered BEFORE this mount and therefore shadow it --
# this set is the belt to that brace, so a fourth agent path added upstream
# can never appear on the session-gated prefix without being noticed.
AGENT_PREFIX = "/agent/"


def _detail(status: str, detail: str) -> tuple[str, str]:
    return status, detail


# ---------------------------------------------------------------- the source

def checkout_src(settings: Settings | None) -> str:
    """Where `multicam_pipeline` is imported from, or "".

    `DASH_CARDS_SRC` is the deployment's answer (/cards-app in the container,
    shipped there by server/install_dashboard_app.py exactly as /broll-app
    is). `CARDS_SRC` in the environment is the DEV and TEST answer, and it is
    also taken as consent: a developer who points it at a checkout on a
    laptop should not also have to set the enable flag, and the deployment
    path is never reached with it set.
    """
    configured = str(getattr(settings, "cards_src", "") or "").strip()
    return configured or os.environ.get("CARDS_SRC", "").strip()


def vault_root(settings: Settings | None) -> str:
    root = str(getattr(settings, "cards_vault_root", "") or "").strip()
    return root or os.environ.get("CARDS_VAULT_ROOT", "").strip()


def enabled(settings: Settings | None) -> bool:
    """DASH_CARDS_ENABLED, or a `CARDS_SRC` pointed at a checkout by hand."""
    if bool(getattr(settings, "cards_enabled", False)):
        return True
    return bool(os.environ.get("CARDS_SRC", "").strip())


def parse_media_map(text: str) -> list[tuple[str, str]]:
    """'P:\\=/media/;X:\\=/vault/' -> [('P:\\', '/media'), ('X:\\', '/vault')].

    A copy of `multicam_pipeline.cards.server.parse_media_map`, deliberately:
    importing `server` would pull in `resolve_engine`, `webbrowser` and a
    module-level list of listening sockets to serve one four-line parser.
    `test_cards_mount.py` pins this against the real function when CARDS_SRC
    points at a real checkout.

    Semicolons separate pairs, the FIRST '=' splits one (so `P:` keeps its
    colon), and trailing slashes go -- '/media/' + '/Projects' is an absolute
    path that os.path.join throws the prefix away for, whose symptom is
    every clip silently having no audio.
    """
    out = []
    for pair in str(text or "").split(";"):
        pair = pair.strip()
        if not pair:
            continue
        left, sep, right = pair.partition("=")
        if not sep:
            continue
        left, right = left.strip(), right.strip()
        if not left or not right:
            continue
        # The RIGHT side only, exactly as `fleet_jobs.split_pairs` does it:
        # `P:\` is a drive root and stripping its backslash would make
        # `P:Projects` -- a path relative to that drive's CURRENT DIRECTORY,
        # which is a different place on Windows and does not exist here.
        out.append((left, right.rstrip("/\\") or right))
    return out


def _add_to_path(src: str) -> None:
    """APPENDED, never prepended: an explicitly configured PYTHONPATH entry
    must keep winning over this one (broll.py's rule, for its reason)."""
    if src and src not in sys.path:
        sys.path.append(src)


def import_cards(src: str):
    """(handler module, project_agent module). Raises whatever import raises.

    Imported by name rather than `from multicam_pipeline.cards import ...` so
    a test can put a minimal package on CARDS_SRC and this module needs no
    knowledge of which of the twenty modules in that package it pulls in.
    """
    _add_to_path(src)
    handler = importlib.import_module("multicam_pipeline.cards.handler")
    project_agent = importlib.import_module("multicam_pipeline.cards.project_agent")
    return handler, project_agent


# ---------------------------------------------------------------- the engine

class _NoServer:
    """What the handler's `self.server` is here.

    The standalone server hands its `ThreadingHTTPServer` in so `/api/restart`
    can close the listener and re-exec. There is no listener of ours to close
    and the process is the dashboard, so this refuses -- loudly, in the log,
    rather than by attribute error inside a thread nobody is reading.
    """

    def shutdown(self) -> None:
        log.error("Timeline Cards asked this process to shut down (/api/restart). "
                  "REFUSED: it is the dashboard. Redeploy to pick up page changes.")

    def server_close(self) -> None:
        self.shutdown()


def build_engine(project_agent_mod: Any, settings: Settings,
                 claude_runner: Callable | None = None) -> Any:
    """The engine `server.main` builds for a NAS, from dashboard settings.

    `ProjectAgentEngine` with no project file is "an ordinary agent server in
    every respect, and one that can be pointed at a .cut.md from the page
    without a restart" (server.py) -- which is what the container runs today,
    so it is what this builds.
    """
    allow = [s.strip() for s in str(settings.cards_db_write_allow or "").split(",")
             if s.strip()]
    # The engine's own state -- the mirror, the picker's memory, the
    # last-picked ROOT -- lives on /data (the persistent volume), not in
    # the container layer: a recreate used to forget the open project and
    # the episode, and every refresh landed back on the deploy defaults
    # (Alex, 2026-08-31).
    import json as _json
    import os as _os
    from pathlib import Path as _Path
    data = str(_Path(settings.db_path).parent / "cards")
    try:
        _os.makedirs(data, exist_ok=True)
    except OSError:
        data = None
    root = (str(settings.cards_root or "").strip() or vault_root(settings))
    if data:
        try:
            with open(_os.path.join(data, "cards_ui.json"),
                      encoding="utf-8-sig") as fh:
                was = _json.load(fh).get("root")
            if was and _os.path.isdir(was):
                root = was
        except (OSError, ValueError):
            pass
    engine = project_agent_mod.ProjectAgentEngine(
        str(settings.cards_project or "").strip() or None,
        root,
        str(settings.cards_token or ""),
        db_host=str(settings.cards_db_host or "").strip() or None,
        db_name=str(settings.cards_db_name or "").strip() or None,
        write_allow=allow,
        backup_dir=str(settings.cards_db_backups or "").strip() or None,
        data_dir=data,
    )
    # THE BROWSER GATE IS RETIRED (see the module docstring). Set explicitly
    # rather than left to the engine's default so the decision is visible
    # where somebody looking for `CARDS_KEY` will find it.
    engine.access_key = None
    engine.media_map = parse_media_map(settings.cards_media_map)
    # The Claude seam (§7d). A checkout that does not have it yet keeps its
    # own `_run_claude`, which finds no CLI in this container and reports so
    # honestly -- which is why `claude_status()` is read for the health line
    # rather than assumed.
    if claude_runner is not None:
        engine.claude_runner = claude_runner
    return engine


def stop_engine(app: FastAPI) -> None:
    """Let the engine's threads go, at app shutdown. Never raises.

    They are all daemons, so this is not what stops the process -- it is what
    stops a SWEEP from running against a database the next process is opening,
    and what makes a reload in a dev run quiet instead of noisy.
    """
    engine = getattr(app.state, "cards_engine", None)
    if engine is None:
        return
    try:
        stop = getattr(engine, "stop", None)
        if callable(stop):
            stop()
    except Exception:  # noqa: BLE001 - shutdown is not the place to raise
        log.exception("the Timeline Cards engine did not stop cleanly")
    app.state.cards_engine = None


# ------------------------------------------------------------------ the gate

class CardsGate:
    """Blocks two things and passes everything else to the shim.

    Deliberately thin: unlike BrollGate and MusicGate this mints NO identity
    headers. Timeline Cards has no per-editor state -- the cut, the plans and
    the notes are one document per episode that everyone with a login is
    editing together, which is what the page has always been -- so there is
    nothing here for a header to say. When that changes it changes with a
    schema, not with a header the sub-app trusts because we sent it.
    """

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http":
            for path in sub_paths(scope):
                # bug-hunt-2026-09-03 dash-release-jobs-4: the set holds bare
                # paths, so `/cards/api/restart/` walked straight past an
                # exact-membership test into a handler that may normalise the
                # trailing slash itself. The gate is the first of two locks
                # and it must not be the thinner one.
                if (path.rstrip("/") or "/") in BLOCKED_PATHS:
                    await _json_response(send, 200, {
                        "error": "this Timeline Cards is part of the dashboard "
                                 "and cannot restart itself -- redeploy the "
                                 "dashboard to pick up page changes"})
                    return
                if path.startswith(AGENT_PREFIX):
                    await _json_response(send, 404, {
                        "error": "the agent protocol is served by the dashboard "
                                 "at /cards/agent/{state,pending,result}"})
                    return
        await self.app(scope, receive, send)


def sub_paths(scope: dict) -> tuple[str, ...]:
    """Every plausible reading of "the path within the cards app".

    broll.py's function, for its reason: Starlette has changed how it hands a
    mount its path more than once, and the strictest answer wins rather than
    a pinned version.
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


# ----------------------------------------------------------------- the mount

def mount_cards(app: FastAPI, settings: Settings) -> tuple[str, str]:
    """Mount Timeline Cards at /cards. -> (status, detail).

    NEVER RAISES. Every failure below is a state with a sentence: the fleet
    dashboard is what tells everyone whether their footage is syncing, and it
    cannot be taken down by an optional feature (broll.py's rule).

    The caller stores both on `app.state` -- `cards_status`, `cards_detail`,
    `cards_engine` -- which is what the health line and the tunnel read.
    """
    app.state.cards_engine = None
    if not enabled(settings):
        return _detail(DISABLED, "DASH_CARDS_ENABLED is not 1")
    src = checkout_src(settings)
    if not src:
        return _detail(DISABLED, "no Timeline Cards checkout is configured "
                                 "(DASH_CARDS_SRC)")
    if not Path(src).is_dir():
        log.warning("Timeline Cards NOT mounted: %s is not a directory", src)
        return _detail(ABSENT, f"the configured checkout is not there ({src})")
    root = vault_root(settings)
    if not root:
        return _detail(DISABLED, "no vault is mounted here "
                                 "(DASH_CARDS_VAULT_ROOT)")
    if not Path(root).is_dir():
        log.warning("Timeline Cards NOT mounted: the vault root %s is not a "
                    "directory in this container -- check the bind mount", root)
        return _detail(ABSENT, f"the vault root is not mounted ({root})")
    try:
        handler_mod, project_agent_mod = import_cards(src)
    except Exception as e:  # noqa: BLE001 - see the docstring
        log.warning("Timeline Cards not mounted (%s: %s); the dashboard "
                    "continues without it", type(e).__name__, e)
        return _detail(ABSENT, f"the checkout did not import ({type(e).__name__}: {e})")

    from . import cards_ai, cards_wsgi

    try:
        runner = cards_ai.make_runner(settings)
        engine = build_engine(project_agent_mod, settings, claude_runner=runner)
        engine.start()
        # bug-hunt-2026-09-03 dash-release-jobs-1: published BEFORE anything
        # else can fail, because `stop_engine` is the only shutdown path and
        # it finds the engine here. Assigned after the wrap, a wrap that
        # raised left the sweep and the ffmpeg worker running for the life of
        # the container with nothing holding a reference to them.
        app.state.cards_engine = engine
    except Exception as e:  # noqa: BLE001
        log.warning("the Timeline Cards engine did not start (%s: %s); the "
                    "dashboard continues without /cards", type(e).__name__, e)
        return _detail(ABSENT, f"the engine did not start ({type(e).__name__}: {e})")

    try:
        from a2wsgi import WSGIMiddleware

        wsgi = cards_wsgi.handler_wsgi(handler_mod.make_handler(engine), _NoServer())
        # More workers than a2wsgi's default ten: one open page holds a poll
        # and a media stream at once, and a phone on the sofa is a second
        # pair. Ten is not a queue, it is a stall with no error message.
        asgi = WSGIMiddleware(wsgi, workers=24)
    except Exception as e:  # noqa: BLE001
        log.warning("the Timeline Cards handler did not wrap (%s: %s)",
                    type(e).__name__, e)
        stop_engine(app)
        return _detail(ABSENT, f"the WSGI shim did not build "
                               f"({type(e).__name__}: {e})")

    app.mount(MOUNT_PATH, CardsGate(asgi))
    log.info("Timeline Cards mounted at %s (root %s, from %s)",
             MOUNT_PATH, root, src)
    return _detail(MOUNTED, f"serving {root}")


# ------------------------------------------------------------- the health line

def health_block(app: FastAPI) -> dict[str, Any]:
    """What GET /api/v1/health says about /cards. Never raises.

    Three things an admin cannot otherwise find out without reading logs:
    whether the page is up, whether the vault it writes to is really there,
    and whether the three Claude features can run -- which in this container
    is a different answer from the standalone one, because there is no CLI in
    it (§7d).
    """
    status = getattr(app.state, "cards_status", DISABLED)
    out: dict[str, Any] = {
        "status": status,
        "detail": getattr(app.state, "cards_detail", ""),
    }
    engine = getattr(app.state, "cards_engine", None)
    if engine is None:
        return out
    try:
        out["root"] = str(getattr(engine, "root", "") or "")
        out["agent"] = bool(getattr(engine, "agent_name", None))
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import cards_ai

        out["claude"] = cards_ai.status(app.state.settings)
    except Exception as e:  # noqa: BLE001
        out["claude"] = {"ok": False, "why": f"{type(e).__name__}: {e}"}
    return out
