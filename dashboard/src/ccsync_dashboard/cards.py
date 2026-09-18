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
  * **`/api/root` IS BLOCKED TOO** (2026-09-14, docs/CARDS_TWO_PROJECTS.md).
    It is a live route inside the page -- the drawer's root menu -- and it
    calls `engine.set_root()`, which moves THE ENGINE onto another episode.
    With one engine that was the feature; with an engine per episode it
    would move engine A onto root B, which may already have an engine of its
    own, and make the pool's own key a lie. The refusal names the landing
    page, which is where that click means to go now.

SINCE 2026-09-14 THERE IS AN ENGINE PER EPISODE, not one for the container
(docs/CARDS_TWO_PROJECTS.md phase 1). `/cards` is a landing page served by
this module -- it needs no engine to draw, so it answers when every engine is
busy, failed or absent -- and the page itself lives under `/cards/p/<slug>/`,
byte for byte as it was, with one engine behind it. `cards_pool.py` is the
pool; this module is what the pool builds and what routes into it.

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

from . import cards_pool, mount_status
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

# Routes the mounted page must never reach, and the sentence each is refused
# with. Both are live routes in the page, so both answer 200 with an `error`
# the page already knows how to show: a 403 from a fetch() the page does not
# expect to fail is a silence.
BLOCKED_PATHS = {
    "/api/restart": ("this Timeline Cards is part of the dashboard and cannot "
                     "restart itself -- redeploy the dashboard to pick up "
                     "page changes"),
    # docs/CARDS_TWO_PROJECTS.md phase 1: see the module docstring.
    "/api/root": ("this Timeline Cards has one engine per episode -- go back "
                  "to the Timeline Cards page to open another episode, and "
                  "this one stays open behind you"),
}

# Where one episode's page lives under the mount: /cards/p/<slug>/...
PROJECT_PREFIX = "/p/"

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


def data_dir_for(settings: Settings, slug: str = "") -> str | None:
    """`<data>/cards/<slug>`, made if it is not there. None if it cannot be.

    ONE DIRECTORY PER ENGINE (2026-09-14). Every engine used to share
    `<data>/cards`, which holds `cards_mirror.json`, `cards_pick.json`,
    `cards_lane_keys.json`, `library_backups`, the EN-index cache and
    `cards_ui.json` -- and `project_pick.doc_save` is a read-merge-write
    through a fixed `path + ".tmp"` with no cross-process lock, so two
    engines calling `remember()` at the same moment truncate each other's
    file. They are per-ROOT stores wearing a per-container path.
    """
    from pathlib import Path as _Path

    flat = _Path(settings.db_path).parent / "cards"
    data = flat / slug if slug else flat
    try:
        os.makedirs(data, exist_ok=True)
    except OSError:
        return None
    if slug:
        _say_where_the_old_state_went(flat, data)
    return str(data)


_SAID_WHERE: set[str] = set()

# The flat files the pre-0.7.47 single engine wrote straight into
# `<data>/cards`. Named, not globbed, so a stray file cannot make this shout.
_FLAT_STATE = ("cards_mirror.json", "cards_pick.json", "cards_lane_keys.json",
               "cards_ui.json", "library_backups")


def _say_where_the_old_state_went(flat: Any, data: Any) -> None:
    """One log line naming BOTH paths when flat state is orphaned.

    dash-cards-6 (2026-09-18). Moving the engine's data_dir from
    `<data>/cards` to `<data>/cards/<slug>` orphaned every episode's
    `cards_mirror.json`, `cards_pick.json`, `cards_lane_keys.json`,
    `cards_ui.json`, the EN-index / translation caches and - the one that
    matters - `library_backups`, the safety net for the cut list itself.
    Nothing moved them and nothing said so.

    We do NOT adopt them. Which episode the flat files belonged to is not
    recorded anywhere (§11 removed the boot root in the same change), so an
    automatic adopt is a guess, and guessing wrong writes another episode's
    pick and mirror into this one - worse than the loss. The files are only
    orphaned, not deleted, so naming both paths once is the honest fix: an
    operator who wants the backups can copy them across by hand.
    """
    try:
        orphans = [n for n in _FLAT_STATE if (flat / n).exists()]
    except OSError:  # pragma: no cover - a data dir we cannot stat
        return
    if not orphans:
        return
    key = str(data)
    if key in _SAID_WHERE:
        return
    _SAID_WHERE.add(key)
    log.warning(
        "Timeline Cards: this engine's state now lives in %s, but %s still "
        "holds %s from before one directory per episode (dashboard 0.7.47). "
        "Nothing reads them there and nothing has deleted them; copy them "
        "across by hand if you want that episode's library_backups.",
        data, flat, ", ".join(orphans))


def build_engine(project_agent_mod: Any, settings: Settings,
                 claude_runner: Callable | None = None,
                 root: str = "", data_dir: str | None = None) -> Any:
    """The engine `server.main` builds for a NAS, from dashboard settings.

    `ProjectAgentEngine` with no project file is "an ordinary agent server in
    every respect, and one that can be pointed at a .cut.md from the page
    without a restart" (server.py) -- which is what the container runs today,
    so it is what this builds.

    `root` is the EPISODE, handed in by the pool, and `data_dir` is that
    episode's own state directory. Neither is read out of `cards_ui.json` any
    more: that file recorded "the root the UI last picked" for a container
    with one engine in it, and with a pool it is at best meaningless and at
    worst a second engine on a root that already has one. The pool's key is
    the root, and the URL carries it.
    """
    allow = [s.strip() for s in str(settings.cards_db_write_allow or "").split(",")
             if s.strip()]
    # The engine's own state -- the mirror, the picker's memory -- lives on
    # /data (the persistent volume), not in the container layer: a recreate
    # used to forget the open project, and every refresh landed back on the
    # deploy defaults (Alex, 2026-08-31).
    data = data_dir if data_dir is not None else data_dir_for(settings)
    root = (str(root or "").strip()
            or str(settings.cards_root or "").strip() or vault_root(settings))
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
    """Let every engine's threads go, at app shutdown. Never raises.

    They are all daemons, so this is not what stops the process -- it is what
    stops a SWEEP from running against a database the next process is opening,
    and what makes a reload in a dev run quiet instead of noisy.

    Still the one shutdown hook a mounted app gets, and it now drains the
    whole pool. `app.state.cards_engine` is kept as "an engine, if there is
    one" for the health line and for anything that asked before the pool
    existed.
    """
    pool = getattr(app.state, "cards_pool", None)
    if pool is not None:
        try:
            pool.stop_all()
        except Exception:  # noqa: BLE001 - shutdown is not the place to raise
            log.exception("the Timeline Cards pool did not stop cleanly")
    engine = getattr(app.state, "cards_engine", None)
    if engine is not None:
        try:
            stop = getattr(engine, "stop", None)
            if callable(stop):
                stop()
        except Exception:  # noqa: BLE001
            log.exception("the Timeline Cards engine did not stop cleanly")
    app.state.cards_engine = None


def engine_provider(app: FastAPI) -> Callable[[], Any]:
    """"An engine, if there is one" -- asked when it is needed, not at boot.

    `cards_exec.PinnedExecutor` used to be handed `app.state.cards_engine` at
    boot and ask `available()` there. With a lazily built pool there is no
    engine at boot, so there would be no executor for the life of the
    container, and every media job that spent its fleet retry budget would go
    `abandoned` -- a silent regression of the port plan's phase 4 rule 5.
    """
    def provider() -> Any:
        pool = getattr(app.state, "cards_pool", None)
        if pool is not None:
            engine = pool.any_engine()
            if engine is not None:
                return engine
        return getattr(app.state, "cards_engine", None)

    return provider


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
                refusal = BLOCKED_PATHS.get(path.rstrip("/") or "/")
                if refusal is not None:
                    await _json_response(send, 200, {"error": refusal})
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


class CardsDispatch:
    """`/cards/p/<slug>/...` -> that episode's engine. Everything else says why.

    The pool's front door, and deliberately the only thing in the request path
    that knows about slugs. Three rules:

      * **IT NEVER BUILDS AN ENGINE.** Construction reads an episode off a
        network share and this runs on the event loop. An episode that is not
        open is a redirect to the landing page (for a navigation) or a
        sentence in JSON (for a fetch), and the landing page is what opens it,
        in a thread, with a state a person can watch.
      * **THE PREFIX IS REWRITTEN, NOT STRIPPED IN PLACE.** The sub-app is
        handed `path` without the prefix and `root_path` with it, so
        `a2wsgi.build_environ` computes the same PATH_INFO it did when the
        mount was flat -- whichever way the Starlette of the day hands a mount
        its path (`sub_paths` exists for that same churn).
      * **THE FLAT PATHS STILL ANSWER.** A phone with the page installed at
        `/cards/api/...` from before this change, or an old service worker
        replaying a queued edit there, gets a sentence and a redirect rather
        than a 404 nobody can read.
    """

    def __init__(self, pool: Any, make_gate: Callable[[Any], Any]) -> None:
        self.pool = pool
        self.make_gate = make_gate
        # slug -> (the app it was built around, the gate). See __call__.
        self._gates: dict[str, tuple[Any, Any]] = {}

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await _json_response(send, 404, {"error": "not found"})
            return
        rel = _relative_path(scope)
        if rel.startswith(AGENT_PREFIX):
            # The belt to cards_tunnel's brace, kept at the OUTER door now
            # that the gate only stands behind `/p/<slug>/`: a fourth agent
            # path added upstream must never appear on the session-gated
            # prefix without being noticed.
            await _json_response(send, 404, {
                "error": "the agent protocol is served by the dashboard "
                         "at /cards/agent/{state,pending,result}"})
            return
        if not rel.startswith(PROJECT_PREFIX):
            # `/cards/` itself and its siblings are FastAPI routes registered
            # before this mount (the landing page, sw.js, the manifest), so
            # anything arriving here is a flat page URL from before the pool.
            await self._not_here(scope, send, rel)
            return
        rest = rel[len(PROJECT_PREFIX):]
        slug, _, tail = rest.partition("/")
        if not cards_pool.is_slug(slug):
            await self._not_here(scope, send, rel)
            return
        if not rel.endswith("/") and not tail:
            # The bare project URL. The page's own URLs are document-relative
            # on purpose (the sibling mounts pin that in their own tests), and
            # document-relative from `/cards/p/<slug>` resolves against
            # `/cards/p/` -- every asset, every fetch, one directory too high.
            await _redirect(send, f"{MOUNT_PATH}{PROJECT_PREFIX}{slug}/")
            return
        asgi = self.pool.ready_asgi(slug)
        if asgi is None:
            await self._not_open(scope, send, slug)
            return
        self._note(scope, slug)
        # KEYED ON THE APP, NOT JUST THE SLUG. An episode that is closed and
        # opened again is a NEW engine behind the same slug, and a gate cached
        # by slug alone would go on serving the dead one -- with its stopped
        # threads and its own idea of the cut -- for the life of the container.
        was, gate = self._gates.get(slug, (None, None))
        if gate is None or was is not asgi:
            self._evict(slug)
            gate = self.make_gate(asgi)
            self._gates[slug] = (asgi, gate)
        await gate(self._child(scope, rel, slug, tail), receive, send)

    def evict(self, slug: str) -> None:
        """Forget a closed episode's gate. Called by the pool (dash-cards-5).

        `_gates` had no deletion path at all, so an admin closing an episode
        left the a2wsgi middleware - and the ThreadPoolExecutor(max_workers=24)
        it builds in its own __init__ - reachable from this dispatcher for the
        life of the container, with whatever WSGI threads that episode had
        already spun up still alive. Closing one to free a seat therefore made
        the thread count worse than docs/CARDS_TWO_PROJECTS.md §12's accounting
        says it is. Never raises: this is tidy-up, and it runs from `drop()`.
        """
        self._evict(slug)

    def _evict(self, slug: str) -> None:
        asgi, _gate = self._gates.pop(slug, (None, None))
        executor = getattr(asgi, "executor", None)
        if executor is None:
            return
        try:
            # `wait=False`: a request may still be in flight on one of those
            # threads, and shutdown(wait=False) lets it finish while refusing
            # new work. The threads are the thing being reclaimed, not the
            # request.
            executor.shutdown(wait=False)
        except Exception:  # noqa: BLE001 - never raise out of a close
            log.exception("Timeline Cards: the WSGI pool for %s did not shut "
                          "down cleanly", slug)

    def _note(self, scope: dict, slug: str) -> None:
        """Who is in this episode -- for the cap's sentence, and for phase 1a.

        `login_gate` has already resolved the session by the time a request
        reaches a mount, and it leaves the answer in the request state, which
        is this scope's own dict. Read, never re-resolved: a SQLite session
        read per media range request would be a read per second per open page.
        """
        try:
            session = (scope.get("state") or {}).get("ccsync_session")
            user = session[0] if session else ""
        except Exception:  # noqa: BLE001 - a visit note is never worth a 500
            return
        if user:
            self.pool.note_visit(slug, user)

    @staticmethod
    def _child(scope: dict, rel: str, slug: str, tail: str) -> dict:
        prefix = PROJECT_PREFIX + slug
        path = scope.get("path", "")
        cut = path.rfind(rel)
        outer = path[:cut] if cut >= 0 else scope.get("root_path", "")
        child = dict(scope)
        child["path"] = "/" + tail
        child["root_path"] = outer + prefix
        return child

    async def _not_open(self, scope, send, slug: str) -> None:
        entry = self.pool.get(slug)
        if _wants_html(scope):
            await _redirect(send, f"{MOUNT_PATH}/?want={slug}")
            return
        state = getattr(entry, "state", "") or "not open"
        await _json_response(send, 409, {
            "error": f"this episode is {state} -- the Timeline Cards page is "
                     f"where it opens",
            "state": state, "slug": slug, "landing": MOUNT_PATH + "/"})

    async def _not_here(self, scope, send, rel: str) -> None:
        if _wants_html(scope):
            await _redirect(send, MOUNT_PATH + "/")
            return
        await _json_response(send, 404, {
            "error": "Timeline Cards is one page per episode now -- this "
                     "address has moved under /cards/p/<episode>/",
            "landing": MOUNT_PATH + "/"})


def _relative_path(scope: dict) -> str:
    """The path within the cards app, on `sub_paths`' terms: strictest wins."""
    best = ""
    for path in sub_paths(scope):
        if not best or len(path) < len(best):
            best = path
    return best or "/"


def _wants_html(scope: dict) -> bool:
    """Is this a navigation? A redirect answers one and breaks the other.

    A `fetch()` or an `<audio src=>` handed a 303 to a page is the CR-100
    shape: the SPA parses HTML as JSON, or the clip reads as having no audio.
    """
    if scope.get("method", "GET").upper() not in ("GET", "HEAD"):
        return False
    for name, value in scope.get("headers", []):
        if name == b"sec-fetch-mode":
            return value == b"navigate"
        if name == b"accept":
            return b"text/html" in value
    return False


async def _redirect(send: Callable, location: str) -> None:
    await send({"type": "http.response.start", "status": 303,
                "headers": [(b"location", location.encode()),
                            (b"content-length", b"0")]})
    await send({"type": "http.response.body", "body": b""})


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

    from . import cards_ai, cards_landing, cards_wsgi

    try:
        from a2wsgi import WSGIMiddleware
    except Exception as e:  # noqa: BLE001
        log.warning("the Timeline Cards shim is not installed (%s: %s)",
                    type(e).__name__, e)
        return _detail(ABSENT, f"a2wsgi is not installed ({type(e).__name__}: {e})")

    runner = cards_ai.make_runner(settings)

    def build(episode_root: str) -> tuple[Any, Any]:
        """One episode -> (engine, asgi). Raises; the pool holds the failure.

        Runs in the pool's builder THREAD, never in a request: an engine
        reads an episode off the vault share as it comes up.
        """
        slug = cards_pool.slug_for(episode_root)
        engine = build_engine(project_agent_mod, settings, claude_runner=runner,
                              root=episode_root,
                              data_dir=data_dir_for(settings, slug))
        engine.start()
        try:
            wsgi = cards_wsgi.handler_wsgi(handler_mod.make_handler(engine),
                                           _NoServer())
            # More workers than a2wsgi's default ten: one open page holds a
            # poll and a media stream at once, and a phone on the sofa is a
            # second pair. Ten is not a queue, it is a stall with no error
            # message.
            return engine, WSGIMiddleware(wsgi, workers=24)
        except Exception:
            # bug-hunt-2026-09-03 dash-release-jobs-1, in its new home. The
            # engine is STARTED by the line above, and a wrap that raises
            # leaves the sweep and the ffmpeg worker running with nothing
            # holding a reference to them -- the pool only ever sees the
            # exception. Stopped here, where the reference still exists.
            try:
                engine.stop()
            except Exception:  # noqa: BLE001 - the original failure wins
                log.exception("could not stop the engine whose wrap failed")
            raise

    pool = cards_pool.EnginePool(build, cap=int(
        getattr(settings, "cards_engines", 0) or cards_pool.DEFAULT_CAP))
    app.state.cards_pool = pool

    # res-fleet-2 (2026-09-11): the vault root the collector re-probes every
    # cycle. A Timeline Cards page with no vault under it answers nothing.
    mount_status.record_root("cards", str(root))
    # BEFORE the mount, so the landing page, the kill-switch worker and the
    # manifest win over it: Starlette matches routes in the order they were
    # added, which is the same reason cards_tunnel's router is registered
    # ahead of this (app.py).
    app.include_router(cards_landing.router)
    dispatch = CardsDispatch(pool, CardsGate)
    # dash-cards-5 (2026-09-18): the pool is built before the dispatcher (it is
    # the dispatcher's argument), so the eviction hook is wired here rather
    # than passed to the constructor.
    pool.set_evict_hook(dispatch.evict)
    app.mount(MOUNT_PATH, dispatch)
    log.info("Timeline Cards mounted at %s (vault %s, from %s, up to %d "
             "episode(s) at once)", MOUNT_PATH, root, src, pool.cap)
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
    pool = getattr(app.state, "cards_pool", None)
    if pool is not None:
        # ONE LINE PER EPISODE (2026-09-14). The old block named "the" root
        # and "the" agent, which with a pool would be whichever engine came
        # back first -- a health line that is right by luck. `open` is a list
        # so an admin reading /api/v1/health can see the cap being spent.
        try:
            out["cap"] = pool.cap
            out["open"] = [{"slug": e.slug, "root": e.root, "state": e.state,
                            "agent": bool(getattr(e.engine, "agent_name", None)),
                            "occupants": e.occupants()}
                           for e in pool.entries()]
            ready = [e for e in pool.entries() if e.state == cards_pool.READY]
            if ready:
                out["root"] = ready[0].root
                out["agent"] = any(r["agent"] for r in out["open"])
        except Exception:  # noqa: BLE001
            pass
    engine = getattr(app.state, "cards_engine", None)
    if engine is not None:
        try:
            out.setdefault("root", str(getattr(engine, "root", "") or ""))
            out.setdefault("agent", bool(getattr(engine, "agent_name", None)))
        except Exception:  # noqa: BLE001
            pass
    if pool is None and engine is None:
        return out
    try:
        from . import cards_ai

        out["claude"] = cards_ai.status(app.state.settings)
    except Exception as e:  # noqa: BLE001
        out["claude"] = {"ok": False, "why": f"{type(e).__name__}: {e}"}
    return out
