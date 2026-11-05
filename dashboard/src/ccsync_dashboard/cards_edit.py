"""The NEW Timeline Cards editor, served beside the old page at /cards/edit.

2026-11-05, MulticamPipeline `editor/docs/NAS-CUTOVER.md` phase 2 ("beside
first, then flip"). The new editor is a Node server (`editor/dist-server/
host.mjs`, one esbuild bundle that rides in the Cards checkout at
`/cards-app`); this module is the dashboard's half of the contract in that
repo's `editor/features/projects/README.md` section 3:

  * **START IT AS A CHILD.** `<node> host.mjs --write` with `TC_VAULT` = the
    vault mount, `TC_MOUNT_BASE=/cards/edit`, a loopback port and a secret
    made in memory at start. `--write` is deliberate: this is the live editor
    and it edits the vault the old page edits, not a working copy.
  * **SUPERVISE IT.** A crash restarts it with a backoff, its output goes to
    the dashboard log behind an `editor:` prefix, and the lifespan's shutdown
    stops it (`shutdown`, the sibling of `cards.stop_engine`) -- gracefully,
    because its SIGTERM handler is what flushes every open cut list to its
    `.cut.md`.
  * **PROXY IT, BEHIND THE LOGIN.** HTTP is a streamed reverse proxy (Range /
    206 pass untouched: audio and video seek), the `/sync` WebSocket is
    relayed both ways. Every `X-TC-*` header the browser sent is stripped,
    then `X-TC-Proxy-Secret` and `X-TC-User` are added -- so the editor's own
    port is no way round the dashboard's sign-in, and a client cannot claim to
    be somebody else.

THE WEBSOCKET IS AUTHENTICATED HERE, NOT BY `login_gate`. `login_gate` is an
`@app.middleware("http")` and Starlette's BaseHTTPMiddleware never sees a
websocket scope, so the `/sync` route resolves the session cookie itself and
also refuses an Origin that is not the page's own (cross-site WebSocket
hijacking: a WebSocket is not stopped by CORS).

HOST AND ORIGIN. The editor refuses a request whose `Host` is a DNS name it
was not told about, and a browser `Origin` that is not its own `Host`. Behind
this proxy the browser's Host is the dashboard's (`truenas.tail....ts.net`),
which the child cannot know at start. So the proxy does the same-origin test
itself (the browser Origin against the Host it was sent) and then speaks to
the child as a loopback client: `Host: 127.0.0.1:<port>` and, only for an
Origin that passed, `Origin: http://127.0.0.1:<port>`. An Origin that did not
pass is forwarded unchanged and the editor refuses it. No `TC_ALLOWED_*`
setting is needed and none can go stale.

TRI-STATE AND NEVER FATAL, like every mount. DISABLED = `DASH_CARDS_EDITOR`
is not 1: nothing is registered and nothing is spawned. With it on, the routes
exist even when a prerequisite is missing (no Node, no bundle, no vault),
because the useful answer to a person who opens /cards/edit/ is a page that
says WHAT is missing; the dashboard itself boots either way and `health_block`
reports it.

The child is started by the lifespan (`start`), never by `create_app`: a test
that builds an app must not spawn a process.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, Response
from starlette.responses import RedirectResponse

from .settings import Settings

log = logging.getLogger("ccsync.dashboard.cards_edit")

MOUNT_PATH = "/cards/edit"
HOME_PATH = "/cards/"

MOUNTED = "mounted"
ABSENT = "absent"
DISABLED = "disabled"

# Supervisor states.
S_IDLE = "idle"          # created, not started (or stopped)
S_ABSENT = "absent"      # a prerequisite is missing; the sentence is `detail`
S_STARTING = "starting"  # spawned, the port does not answer yet
S_RUNNING = "running"    # the port answers
S_BACKOFF = "backoff"    # it exited; waiting to start it again
S_FAILED = "failed"      # crash loop: still retrying, slowly

DEFAULT_NODE = "/opt/node/bin/node"
BUNDLE_REL = ("editor", "dist-server", "host.mjs")
STATIC_REL = ("editor", "dist")

# A child that lives this long was not crash-looping.
STABLE_SECONDS = 60.0
# Consecutive quick exits before the state is `failed` rather than `backoff`.
CRASHLOOP_AFTER = 5
BACKOFF_FIRST = 1.0
BACKOFF_CAP = 60.0
BACKOFF_CAP_FAILED = 300.0
# How long a spawned child may take to open its port (it mirrors nothing and
# mounts ~20 feature services; seconds in practice, a share can be slower).
START_DEADLINE = 120.0
# SIGTERM -> SIGKILL. The editor flushes every open cut list on SIGTERM.
STOP_GRACE = 15.0
# How long a prerequisite that is missing is re-checked (node provisioned or
# a Cards commit deployed while the container runs).
ABSENT_RECHECK = 30.0
LOG_TAIL = 40

# RFC 9110 section 7.6.1, plus the two a proxy must never forward.
HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "proxy-connection"})
# Never reach the editor: it speaks for the proxy, not for the browser's
# credentials. The dashboard's own cookies and tokens are not the editor's.
DASHBOARD_COOKIES = ("ccsync_session", "ccsync_cards_last")
STRIP_REQUEST = frozenset({"host", "authorization", "x-forwarded-for",
                           "x-forwarded-host", "x-forwarded-proto",
                           "x-forwarded-port", "forwarded"})
# The upstream's own Date/Server would duplicate the ones uvicorn adds.
STRIP_RESPONSE = frozenset({"date", "server"})
METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]

PROXY_SECRET_HEADER = "X-TC-Proxy-Secret"
USER_HEADER = "X-TC-User"


# ------------------------------------------------------------- the child

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def resolve_node(settings: Settings | None) -> tuple[str, str]:
    """(path, problem). `DASH_NODE`, else /opt/node/bin/node, else PATH.

    A path the admin NAMED that is not a file is a problem, not a silent
    fallback to another Node: the setting is a statement about which runtime
    the editor was tested on.
    """
    named = str(getattr(settings, "cards_node", "") or "").strip()
    if named:
        found = shutil.which(named) if os.sep not in named and "/" not in named \
            else (named if os.path.isfile(named) else "")
        if found:
            return str(found), ""
        return "", f"DASH_NODE is set to {named} and that is not a file"
    if os.path.isfile(DEFAULT_NODE):
        return DEFAULT_NODE, ""
    found = shutil.which("node")
    if found:
        return found, ""
    return "", ("no Node runtime here: the host's node directory is not "
                f"provisioned (it is mounted at {os.path.dirname(os.path.dirname(DEFAULT_NODE))}) "
                "and there is no node on PATH. The deploy provisions it when "
                "[timeline_cards] editor is on")


class Editor:
    """The supervised child, and what the proxy needs to reach it.

    Thread-based on purpose: the dashboard's other background workers are
    threads, `subprocess` is blocking, and the proxy only ever reads
    `target()`. All state is behind `_lock`.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Made once per process and kept across child restarts; memory only.
        self.secret = secrets.token_urlsafe(32)
        self.state = S_IDLE
        self.detail = "not started"
        self.port = 0
        self.pid = 0
        self.restarts = 0
        self.last_exit = ""
        self.started_at = 0.0
        self.tail: list[str] = []
        # Overridable for tests: they run a stand-in child in milliseconds.
        self.stable_seconds = STABLE_SECONDS
        self.backoff_first = BACKOFF_FIRST
        self.backoff_cap = BACKOFF_CAP
        self.start_deadline = START_DEADLINE
        self.absent_recheck = ABSENT_RECHECK
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None

    # ---- what is needed

    def paths(self) -> dict[str, str]:
        from . import cards

        src = cards.checkout_src(self.settings)
        return {
            "src": src,
            "bundle": str(Path(src, *BUNDLE_REL)) if src else "",
            "static": str(Path(src, *STATIC_REL)) if src else "",
            "vault": cards.vault_root(self.settings),
        }

    def data_dir(self) -> Path:
        return Path(self.settings.db_path).parent / "cards-edit"

    def problem(self) -> str:
        """"" when the child can be started, else the sentence that says why not."""
        p = self.paths()
        if not p["src"]:
            return "no Timeline Cards checkout is configured (DASH_CARDS_SRC)"
        if not Path(p["src"]).is_dir():
            return f"the Timeline Cards checkout is not there ({p['src']})"
        if not Path(p["bundle"]).is_file():
            return (f"the editor bundle is not in the Cards checkout "
                    f"({p['bundle']}). Deploy a Cards commit that carries "
                    "editor/dist-server/host.mjs")
        if not p["vault"]:
            return "no vault is mounted here (DASH_CARDS_VAULT_ROOT)"
        if not Path(p["vault"]).is_dir():
            return f"the vault root is not mounted ({p['vault']})"
        _node, why = resolve_node(self.settings)
        if why:
            return why
        try:
            for sub in ("work", "media", "video", "translate", "search", "home"):
                (self.data_dir() / sub).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return f"the editor's data directory cannot be made ({self.data_dir()}: {e})"
        return ""

    def child_env(self, port: int) -> dict[str, str]:
        """An allow-listed environment: the dashboard holds the NAS password,
        the session secret and the fleet tokens, and the child gets none."""
        from . import cli_tools

        try:
            env = cli_tools.cli_env(self.settings, cli_tools.CLAUDE_CODE)
            claude = cli_tools.installed_binary(self.settings, cli_tools.CLAUDE_CODE)
        except Exception:  # noqa: BLE001 - a CLI lookup never stops the editor
            env = {k: v for k, v in os.environ.items()
                   if k in ("PATH", "HOME", "LANG", "TZ", "TMPDIR", "SYSTEMROOT",
                            "TEMP", "TMP")}
            claude = ""
        p = self.paths()
        d = self.data_dir()
        node, _ = resolve_node(self.settings)
        env["PATH"] = os.pathsep.join(
            x for x in (os.path.dirname(node), env.get("PATH", "")) if x)
        env.update({
            "TC_VAULT": p["vault"],
            "TC_HOST": "127.0.0.1",
            "TC_PORT": str(port),
            "TC_MOUNT_BASE": MOUNT_PATH,
            "TC_MOUNT_HOME": HOME_PATH,
            "TC_PROXY_SECRET": self.secret,
            "TC_WORK": str(d / "work"),
            "TC_MEDIA_CACHE": str(d / "media"),
            "TC_VIDEO_CACHE": str(d / "video"),
            "TC_TRANSLATE_CACHE": str(d / "translate"),
            "TC_SEARCH_DATA": str(d / "search"),
            # The editor's Python workers import `multicam_pipeline` from the
            # Cards checkout; this container's own interpreter runs them.
            "TC_PYTHON": _python(),
            "PYTHONPATH": p["src"],
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        if Path(p["static"]).is_dir():
            env["TC_STATIC"] = p["static"]
        if claude:
            env["TC_CLAUDE_BIN"] = claude
        env.setdefault("HOME", str(d / "home"))
        return env

    def argv(self) -> list[str]:
        node, _ = resolve_node(self.settings)
        return [node, self.paths()["bundle"], "--write"]

    # ---- life cycle

    def start(self) -> None:
        """Begin supervising. Never raises, never blocks."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="cards-editor",
                                            daemon=True)
            self._thread.start()

    def stop(self, grace: float = STOP_GRACE) -> None:
        """Stop supervising and stop the child, gracefully first. Never raises."""
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                log.warning("the editor did not stop in %.0fs; killing it", grace)
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    log.exception("could not kill the editor")
            except Exception:  # noqa: BLE001
                log.exception("could not stop the editor")
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=5)
        with self._lock:
            self.state = S_IDLE
            self.detail = "stopped"
            self.pid = 0

    def adopt(self, port: int, secret: str | None = None) -> None:
        """TEST HOOK: treat a server already listening on `port` as the child."""
        with self._lock:
            self.port = port
            if secret:
                self.secret = secret
            self.state = S_RUNNING
            self.detail = f"serving on 127.0.0.1:{port}"

    def _set(self, state: str, detail: str) -> None:
        with self._lock:
            self.state, self.detail = state, detail

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            why = self.problem()
            if why:
                if self.state != S_ABSENT or self.detail != why:
                    log.warning("the new Timeline Cards editor is not started: %s", why)
                self._set(S_ABSENT, why)
                self._stop.wait(self.absent_recheck)
                continue
            port = int(getattr(self.settings, "cards_editor_port", 0) or 0) or _free_port()
            began = time.monotonic()
            try:
                proc = subprocess.Popen(
                    self.argv(), env=self.child_env(port),
                    cwd=str(self.data_dir()),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT)
            except OSError as e:
                failures += 1
                delay = self._delay(failures)
                self._set(S_FAILED if failures >= CRASHLOOP_AFTER else S_BACKOFF,
                          f"the editor could not be started ({type(e).__name__}: {e}); "
                          f"trying again in {delay:.0f}s")
                log.error("the editor could not be started: %s", e)
                self._stop.wait(delay)
                continue
            self._proc = proc
            with self._lock:
                self.port, self.pid, self.started_at = port, proc.pid, time.time()
                self.state, self.detail = S_STARTING, f"starting on 127.0.0.1:{port}"
            pump = threading.Thread(target=self._pump, args=(proc,),
                                    name="cards-editor-log", daemon=True)
            pump.start()
            log.info("the new Timeline Cards editor started (pid %d, port %d)",
                     proc.pid, port)
            while not self._stop.is_set() and proc.poll() is None:
                if self.state == S_STARTING:
                    if _port_open(port):
                        self._set(S_RUNNING, f"serving on 127.0.0.1:{port}")
                        log.info("the new Timeline Cards editor is answering")
                    elif time.monotonic() - began > self.start_deadline:
                        self._set(S_STARTING, "it never opened its port; killing it")
                        log.error("the editor never opened port %d; killing it", port)
                        proc.kill()
                        break
                self._stop.wait(0.2)
            if self._stop.is_set():
                return  # stop() terminates the child
            try:
                rc = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                rc = None
            pump.join(timeout=2)
            lived = time.monotonic() - began
            failures = 0 if lived >= self.stable_seconds else failures + 1
            delay = self._delay(failures)
            with self._lock:
                self.restarts += 1
                self.pid = 0
                self.last_exit = f"exit {rc} after {lived:.0f}s"
            tail = " | ".join(self.tail[-3:])
            self._set(S_FAILED if failures >= CRASHLOOP_AFTER else S_BACKOFF,
                      f"the editor exited ({self.last_exit}); starting it again in "
                      f"{delay:.0f}s" + (f". Last output: {tail}" if tail else ""))
            log.error("the editor exited (%s); restarting in %.0fs", self.last_exit, delay)
            self._stop.wait(delay)

    def _delay(self, failures: int) -> float:
        cap = BACKOFF_CAP_FAILED if failures >= CRASHLOOP_AFTER else self.backoff_cap
        return min(cap, self.backoff_first * (2 ** max(0, failures - 1)))

    def _pump(self, proc: subprocess.Popen) -> None:
        try:
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if not line:
                    continue
                self.tail = (self.tail + [line])[-LOG_TAIL:]
                log.info("editor: %s", line)
        except Exception:  # noqa: BLE001 - a closed pipe at exit
            pass

    # ---- what the proxy and the page read

    def target(self) -> tuple[int, str] | None:
        with self._lock:
            if self.state == S_RUNNING and self.port:
                return self.port, self.secret
        return None

    def ready(self) -> bool:
        return self.target() is not None

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return {"state": self.state, "detail": self.detail,
                    "port": self.port or None, "pid": self.pid or None,
                    "restarts": self.restarts, "last_exit": self.last_exit}


def _python() -> str:
    import sys

    return sys.executable or "python3"


# ---------------------------------------------------------------- the mount

def enabled(settings: Settings | None) -> bool:
    return bool(getattr(settings, "cards_editor", False))


def mount_editor(app: FastAPI, settings: Settings) -> tuple[str, str]:
    """Register /cards/edit. -> (status, detail). NEVER RAISES.

    Must be called BEFORE `cards.mount_cards`: that mounts a catch-all at
    /cards, and Starlette matches in the order routes were added.
    """
    app.state.cards_edit = None
    if not enabled(settings):
        return DISABLED, "DASH_CARDS_EDITOR is not 1"
    try:
        editor = Editor(settings)
        app.state.cards_edit = editor
        app.include_router(router)
        why = editor.problem()
    except Exception as e:  # noqa: BLE001 - see the docstring
        log.exception("the new Timeline Cards editor is not mounted")
        app.state.cards_edit = None
        return ABSENT, f"it could not be set up ({type(e).__name__}: {e})"
    if why:
        log.warning("the new Timeline Cards editor will not start: %s", why)
        return ABSENT, why
    return MOUNTED, f"proxying {MOUNT_PATH}/ to a child process"


def start(app: FastAPI) -> None:
    """The lifespan's startup hook. Never raises."""
    editor = getattr(app.state, "cards_edit", None)
    if editor is None:
        return
    try:
        editor.start()
    except Exception:  # noqa: BLE001
        log.exception("could not start the editor supervisor")


async def shutdown(app: FastAPI) -> None:
    """The lifespan's shutdown hook, beside `cards.stop_engine`. Never raises."""
    editor = getattr(app.state, "cards_edit", None)
    if editor is not None:
        try:
            await asyncio.to_thread(editor.stop)
        except Exception:  # noqa: BLE001
            log.exception("the editor did not stop cleanly")
    client = getattr(app.state, "cards_edit_client", None)
    if client is not None:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass
        app.state.cards_edit_client = None


def health_block(app: FastAPI) -> dict[str, Any]:
    """What /api/v1/health says about the editor. Never raises."""
    editor = getattr(app.state, "cards_edit", None)
    if editor is None:
        return {"status": DISABLED, "detail": "DASH_CARDS_EDITOR is not 1"}
    try:
        out = editor.as_dict()
        out["status"] = MOUNTED if editor.ready() else ABSENT
        return out
    except Exception as e:  # noqa: BLE001
        return {"status": "unknown", "detail": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------- the landing's link

_CUT_CACHE: dict[str, tuple[float, str]] = {}
_CUT_TTL = 30.0


def newest_cut(root: str) -> str:
    """The file name of the newest `<root>/Script Docs/Cuts/*.cut.md`, or ""."""
    now = time.monotonic()
    hit = _CUT_CACHE.get(root)
    if hit is not None and now - hit[0] < _CUT_TTL:
        return hit[1]
    best, best_m = "", -1.0
    try:
        for entry in os.scandir(os.path.join(root, "Script Docs", "Cuts")):
            if entry.name.endswith(".cut.md") and not entry.name.startswith("."):
                try:
                    m = entry.stat().st_mtime
                except OSError:
                    continue
                if m > best_m:
                    best, best_m = entry.name, m
    except OSError:
        pass
    _CUT_CACHE[root] = (now, best)
    return best


def editor_href(vault: str, root: str) -> str:
    """`/cards/edit/?key=<Episode>/Script Docs/Cuts/<name>.cut.md`, or the
    bare `/cards/edit/` (the editor's own sheet chooses) when the episode has
    no cut list or is not under the vault. The key is vault-relative with
    forward slashes, the editor's form (`names.ts` keyFor)."""
    try:
        rel = os.path.relpath(root, vault).replace(os.sep, "/")
    except ValueError:
        return MOUNT_PATH + "/"
    if rel.startswith("..") or rel == ".":
        return MOUNT_PATH + "/"
    cut = newest_cut(root)
    if not cut:
        return MOUNT_PATH + "/"
    return MOUNT_PATH + "/?key=" + quote(f"{rel}/Script Docs/Cuts/{cut}", safe="/")


# ---------------------------------------------------------------- the proxy

router = APIRouter()


def _editor(request: Any) -> Editor | None:
    return getattr(request.app.state, "cards_edit", None)


def _wants_html(request: Request) -> bool:
    if request.method not in ("GET", "HEAD"):
        return False
    mode = request.headers.get("sec-fetch-mode")
    if mode:
        return mode == "navigate"
    return "text/html" in request.headers.get("accept", "")


def unavailable(request: Request, editor: Editor | None) -> Response:
    """A plain page (or JSON for a fetch) saying what the editor is missing."""
    if editor is None:
        state, why = S_ABSENT, "the new editor is not set up on this dashboard"
    else:
        d = editor.as_dict()
        state, why = d["state"], d["detail"]
    starting = state in (S_STARTING, S_IDLE)
    headline = ("The new editor is starting" if starting
                else "The new editor is not running")
    headers = {"Retry-After": "5", "Cache-Control": "no-store"}
    if not _wants_html(request):
        return JSONResponse({"detail": f"{headline}: {why}", "state": state},
                            status_code=503, headers=headers)
    refresh = '<meta http-equiv="refresh" content="4">' if starting else ""
    body = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(headline)}</title>{refresh}"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:4rem auto;"
        "padding:0 1rem}code{background:#8882;padding:.1em .3em}</style></head><body>"
        f"<h1>{html.escape(headline)}</h1><p>{html.escape(why)}</p>"
        "<p>Your cut lists are untouched. The original Timeline Cards page still "
        "works: <a href=\"/cards/\">go to Timeline Cards</a>.</p></body></html>")
    return Response(body, status_code=503, media_type="text/html; charset=utf-8",
                    headers=headers)


def _same_origin(origin: str, host: str) -> bool:
    """The browser's Origin is the page's own Host (scheme-agnostic: a TLS
    terminator in front may have made the scheme differ from what we see)."""
    try:
        u = urlsplit(origin)
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(host) and u.netloc.lower() == host.lower()


def _user_value(user: str) -> str:
    """The signed-in name as an HTTP header value. Plain when it is ASCII (it
    nearly always is: a NAS account name), percent-encoded otherwise, because
    a header value is latin-1 on the wire and Node would mojibake the rest."""
    user = "".join(ch for ch in user if ch >= " " and ch != "\x7f").strip()[:120]
    return user if user.isascii() else quote(user)


def _clean_cookie(value: str) -> str:
    kept = []
    for part in value.split(";"):
        name = part.split("=", 1)[0].strip()
        if name and name not in DASHBOARD_COOKIES:
            kept.append(part.strip())
    return "; ".join(kept)


def upstream_headers(raw: list[tuple[str, str]], *, port: int, secret: str,
                     user: str, host: str, scheme: str, client_ip: str,
                     websocket: bool = False) -> list[tuple[str, str]]:
    """The headers the child is sent. The one place the trust rules live.

    Stripped: hop-by-hop (and whatever `Connection` names), every `X-TC-*`
    the client sent (the editor believes `X-TC-User` only WITH the secret, but
    a client must not even be able to attempt it), the dashboard's cookies,
    `Authorization`, and the forwarding headers (replaced by ours). Added:
    the secret, the user, `Host` as a loopback client and, for a same-origin
    Origin, the matching loopback Origin.
    """
    named = set()
    for k, v in raw:
        if k.lower() == "connection":
            named.update(t.strip().lower() for t in v.split(",") if t.strip())
    out: list[tuple[str, str]] = []
    for k, v in raw:
        low = k.lower()
        if (low in HOP_BY_HOP or low in named or low in STRIP_REQUEST
                or low.startswith("x-tc-")):
            continue
        if websocket and (low.startswith("sec-websocket-") or low == "sec-websocket-key"):
            continue
        if low == "cookie":
            v = _clean_cookie(v)
            if not v:
                continue
        if low == "origin":
            v = f"http://127.0.0.1:{port}" if _same_origin(v, host) else v
        out.append((k, v))
    out.append(("Host", f"127.0.0.1:{port}"))
    out.append(("X-Forwarded-Host", host))
    out.append(("X-Forwarded-Proto", scheme))
    if client_ip:
        out.append(("X-Forwarded-For", client_ip))
    out.append((PROXY_SECRET_HEADER, secret))
    out.append((USER_HEADER, _user_value(user)))
    return out


def _http_client(app: FastAPI):
    import httpx

    client = getattr(app.state, "cards_edit_client", None)
    if client is None:
        # No overall read timeout: a media range or a long poll is legitimately
        # slow. The connect timeout is what a dead child costs a request.
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=None, write=120.0, pool=10.0),
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=20),
            follow_redirects=False)
        app.state.cards_edit_client = client
    return client


class Passthrough(Response):
    """The editor's answer, byte for byte: status, raw headers, streamed body.

    NOT `StreamingResponse`, for two reasons found 2026-11-05. It cannot carry
    a multi-valued header list exactly as the editor sent it. And, worse, on an
    ASGI server that does not speak spec 2.4 it starts a `listen_for_disconnect`
    task that reads `receive()` -- and behind `body_size_gate`, which replays a
    buffered POST body as a `receive` that ALWAYS answers `http.request`, that
    task dies with "Unexpected message received" in BaseHTTPMiddleware. This
    never reads `receive` at all: a browser that goes away is noticed by the
    next `send` failing, which ends the generator and closes the upstream.
    """

    def __init__(self, chunks: Any, status: int, raw_headers: list[tuple[bytes, bytes]]) -> None:
        super().__init__(status_code=status)
        self._chunks = chunks
        self.raw_headers = raw_headers

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": self.status_code,
                    "headers": self.raw_headers})
        if self._chunks is not None:
            async for chunk in self._chunks:
                await send({"type": "http.response.body", "body": chunk,
                            "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})


def _rest(scope: dict) -> str:
    """The raw (still percent-encoded) path under the mount, with a leading /."""
    raw = scope.get("raw_path")
    path = raw.decode("latin-1") if raw else quote(scope.get("path", ""), safe="/")
    cut = path.find(MOUNT_PATH)
    path = path[cut + len(MOUNT_PATH):] if cut >= 0 else path
    return path if path.startswith("/") else "/" + path


@router.api_route(MOUNT_PATH, methods=METHODS, include_in_schema=False)
async def edit_bare(request: Request) -> Response:
    """`/cards/edit` -> `/cards/edit/`. The editor's URLs are base-relative."""
    q = request.url.query
    return RedirectResponse(MOUNT_PATH + "/" + (f"?{q}" if q else ""), status_code=308)


@router.api_route(MOUNT_PATH + "/{path:path}", methods=METHODS, include_in_schema=False)
async def edit_proxy(request: Request, path: str) -> Response:
    from . import auth

    user = auth.get_session_user(request)
    if user is None:
        # login_gate answers this first; this is the belt (a route reached
        # some other way must still never speak for nobody).
        return JSONResponse({"detail": "login required"}, status_code=401)
    editor = _editor(request)
    target = editor.target() if editor is not None else None
    if target is None:
        return unavailable(request, editor)
    port, secret = target

    import httpx

    query = request.scope.get("query_string", b"").decode("latin-1")
    url = f"http://127.0.0.1:{port}{MOUNT_PATH}{_rest(request.scope)}" + (f"?{query}" if query else "")
    client_ip = (request.client.host if request.client else "")
    headers = upstream_headers(
        list(request.headers.items()), port=port, secret=secret, user=user,
        host=request.headers.get("host", ""), scheme=request.url.scheme,
        client_ip=client_ip)

    has_body = (request.method in ("POST", "PUT", "PATCH", "DELETE")
                or "content-length" in request.headers
                or "transfer-encoding" in request.headers)

    async def body():
        async for chunk in request.stream():
            yield chunk

    client = _http_client(request.app)
    try:
        upstream_request = client.build_request(
            request.method, url, headers=headers,
            content=body() if has_body else None)
        upstream = await client.send(upstream_request, stream=True)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return unavailable(request, editor)
    except httpx.HTTPError as e:
        log.warning("the editor did not answer %s %s (%s: %s)",
                    request.method, request.url.path, type(e).__name__, e)
        return JSONResponse({"detail": "the new editor did not answer"}, status_code=502)

    drop = set(HOP_BY_HOP) | STRIP_RESPONSE
    for k, v in upstream.headers.multi_items():
        if k.lower() == "connection":
            drop.update(t.strip().lower() for t in v.split(",") if t.strip())

    async def stream():
        try:
            # aiter_raw: the bytes as the editor sent them, so a gzip body
            # and its Content-Length stay a matching pair.
            async for chunk in upstream.aiter_raw():
                yield chunk
        except httpx.HTTPError:
            pass  # the child went away mid-body; the client sees a short read
        finally:
            await upstream.aclose()

    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in upstream.headers.multi_items() if k.lower() not in drop]
    if request.method == "HEAD":
        # No body to stream, and the headers (Content-Length of the body a GET
        # would carry) must reach the client untouched.
        await upstream.aclose()
        return Passthrough(None, upstream.status_code, raw_headers)
    return Passthrough(stream(), upstream.status_code, raw_headers)


def _close_code(code: int | None) -> int:
    if code in (None, 1005):
        return 1000
    if code == 1006 or code in (1004, 1015) or not (1000 <= code < 5000):
        return 1011
    return code


@router.websocket(MOUNT_PATH + "/{path:path}")
async def edit_socket(websocket: WebSocket, path: str) -> None:
    """The editor's `/sync` socket (and any other under the mount), relayed.

    Auth is done here: see the module docstring. Nothing is accepted from the
    browser until the child has accepted the upgrade, so a refusal is an HTTP
    403 to the page and not an open socket that dies.
    """
    from . import auth

    user = auth.get_session_user(websocket)
    host = websocket.headers.get("host", "")
    origin = websocket.headers.get("origin")
    if user is None or (origin is not None and not _same_origin(origin, host)):
        await websocket.close(code=1008)
        return
    editor = _editor(websocket)
    target = editor.target() if editor is not None else None
    if target is None:
        await websocket.close(code=1013)
        return
    port, secret = target

    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed

    query = websocket.scope.get("query_string", b"").decode("latin-1")
    url = f"ws://127.0.0.1:{port}{MOUNT_PATH}{_rest(websocket.scope)}" + (f"?{query}" if query else "")
    sent = upstream_headers(
        list(websocket.headers.items()), port=port, secret=secret, user=user,
        host=host, scheme=websocket.url.scheme,
        client_ip=(websocket.client.host if websocket.client else ""),
        websocket=True)
    # websockets adds Host, Origin and the Sec-WebSocket-* set itself.
    origin_out = next((v for k, v in sent if k.lower() == "origin"), None)
    extra = [(k, v) for k, v in sent if k.lower() not in ("host", "origin")]
    try:
        upstream = await connect(
            url, additional_headers=extra, origin=origin_out,
            subprotocols=list(websocket.scope.get("subprotocols") or []) or None,
            open_timeout=10, ping_interval=None, max_size=None, compression=None,
            user_agent_header=None)
    except Exception as e:  # noqa: BLE001 - a refusal or a dead child
        log.warning("the editor refused the socket %s (%s: %s)", websocket.url.path,
                    type(e).__name__, e)
        await websocket.close(code=1011)
        return
    await websocket.accept(subprotocol=upstream.subprotocol)

    async def to_editor() -> None:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                return
            data = msg.get("text") if msg.get("text") is not None else msg.get("bytes")
            if data is not None:
                await upstream.send(data)

    async def to_browser() -> None:
        try:
            async for message in upstream:
                if isinstance(message, str):
                    await websocket.send_text(message)
                else:
                    await websocket.send_bytes(message)
        except ConnectionClosed:
            return

    tasks = [asyncio.create_task(to_editor()), asyncio.create_task(to_browser())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await upstream.close(_close_code(upstream.close_code))
        except Exception:  # noqa: BLE001
            pass
        try:
            await websocket.close(code=_close_code(upstream.close_code))
        except Exception:  # noqa: BLE001 - already closed by the browser
            pass
