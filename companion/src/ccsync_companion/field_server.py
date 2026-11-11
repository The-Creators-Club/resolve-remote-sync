"""The field backup page, served from this computer: http://127.0.0.1:<port>/field.

Companion half of footage-sorter docs/LEDGER-BROWSER-DESIGN.md, "The companion" item 4: a card
backup that still works in a tent. The page, its script and its style come off this process's own
disk (assets/field/), reference nothing outside it, and so work with no network at all; the
dashboard is only ever a bonus (the ledger, when it answers).

A SERVER OF ITS OWN, not a route on the b-roll server's 8899. The page is served from here and
calls back here, so it is same-origin: it needs no CORS and the b-roll server's allow-list (the
dashboard's origin) does not apply to it. The guard is still loopback_guard's, rule for rule:

  * the Host header must be this loopback by name and port (DNS rebinding);
  * a request that carries an Origin must carry this page's own origin (127.0.0.1 or localhost on
    this port) or one on the dashboard allow-list; anything else is refused with no CORS headers,
    so a hostile page cannot read even the refusal. A GET with no Origin (a tab opened straight at
    the address, or the page's own same-origin fetch) is fine: it changes nothing;
  * a POST needs an allowed Origin or the loopback token (the tray, curl), and application/json;
  * the bind is 127.0.0.1 and nothing else, and no route takes a path to write to except
    "add this folder", which only a person at this machine's page can send.

Stdlib only; never raises into a request thread (broll_server's MED-5 lesson).
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from . import config as config_mod
from . import loopback_guard
from . import site as site_mod
from .field_service import FieldService

log = logging.getLogger("ccsync.fieldserver")

HOST = "127.0.0.1"
PORT = 8898
MAX_BODY_BYTES = 64 * 1024
ORIGIN_TTL_S = 30.0
ASSET_DIR = Path(__file__).resolve().parent / "assets" / "field"
PAGE_PATH = "/field"
ASSETS = {"/field": "index.html", "/field/": "index.html", "/field/field.css": "field.css",
          "/field/field.js": "field.js"}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

_LAST_BIND_ERROR = ""


def is_enabled(cfg: dict[str, Any]) -> bool:
    raw = (cfg or {}).get("field_server_enabled", True)
    if isinstance(raw, str):
        return raw.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(raw)


def configured_port(cfg: dict[str, Any]) -> int:
    """The port, never raising on a hand-edited value (a typo here must not stop anything)."""
    try:
        port = int((cfg or {}).get("field_server_port", PORT))
    except (TypeError, ValueError):
        port = -1
    if not (1 <= port <= 65535):
        log.warning("field: field_server_port=%r is not a port number -- using %d",
                    (cfg or {}).get("field_server_port"), PORT)
        return PORT
    return port


def page_url(cfg: dict[str, Any], server: Any = None) -> str:
    port = server.server_address[1] if server is not None else configured_port(cfg)
    return f"http://{HOST}:{port}{PAGE_PATH}"


def last_bind_error() -> str:
    return _LAST_BIND_ERROR


class FieldRequestHandler(BaseHTTPRequestHandler):
    server_version = f"CCSyncField/{config_mod.VERSION}"
    _body_consumed = 0

    # -- the guard -------------------------------------------------------------------------------
    def _own_origins(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def _vet(self) -> Optional[str]:
        """-> the caller's Origin once allowed ("" for none), or None after a refusal went out."""
        if not loopback_guard.host_allowed(self.headers.get("Host"), self.server.server_address[1]):
            log.warning("field: refusing %s %s -- Host %r is not this loopback", self.command, self.path,
                        self.headers.get("Host"))
            self._refuse(403)
            return None
        origin = self.headers.get("Origin")
        if not origin:
            return ""
        allowed, dev = self.server.origin_policy()
        if origin.strip().lower() in self._own_origins() or loopback_guard.origin_allowed(origin, allowed, dev=dev):
            return origin
        log.warning("field: refusing %s %s from origin %r", self.command, self.path, origin)
        self._refuse(403)
        return None

    def _refuse(self, status: int) -> None:
        self._json(status, {"ok": False, "error": loopback_guard.REFUSED_MESSAGE})

    # -- answers ---------------------------------------------------------------------------------
    def _headers_common(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def _json(self, status: int, obj: Any) -> None:
        payload = json.dumps(obj, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(status)
        self._headers_common()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _asset(self, name: str) -> None:
        data = None
        frozen = getattr(sys, "_MEIPASS", None)       # a onefile build unpacks build.spec's datas here
        for base in ([Path(frozen) / "ccsync_companion" / "assets" / "field"] if frozen else []) + [ASSET_DIR]:
            try:
                data = (base / name).read_bytes()
                break
            except OSError:
                continue
        if data is None:
            self._json(404, {"ok": False, "error": "not found"})
            return
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if name.endswith(".js"):
            ctype = "text/javascript"
        self.send_response(200)
        self._headers_common()
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if name == "index.html":
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> Any:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            # Take a modestly oversized body off the socket before refusing it (never kept, and
            # never more than 16x the limit). Answering and closing with the body still unread
            # makes Windows RESET the connection, and the page then sees "network error" instead
            # of this sentence; the suite caught it as a WinError 10053 once in a few runs under
            # pytest -n (2026-11-11). Anything bigger is refused unread, as before.
            if 0 < length <= 16 * MAX_BODY_BYTES:
                left = length
                try:
                    while left > 0:
                        chunk = self.rfile.read(min(left, 65536))
                        if not chunk:
                            break
                        left -= len(chunk)
                except OSError:
                    pass
            self.close_connection = True
            self._json(413 if length > 0 else 400, {"ok": False, "error": "that request is too large"})
            return None
        raw = self.rfile.read(length) if length else b""
        self._body_consumed = length
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"ok": False, "error": "that is not JSON"})
            return None
        if not isinstance(body, dict):
            self._json(400, {"ok": False, "error": "a JSON object is expected"})
            return None
        return body

    def _guarded(self, fn: Any) -> None:
        try:
            fn()
        except Exception:                                         # noqa: BLE001
            log.exception("field: %s %s failed", self.command, self.path)
            try:
                self._json(500, {"ok": False, "error": "the companion failed to handle that; see its log"})
            except Exception:                                     # noqa: BLE001
                log.debug("field: could not send the 500 either", exc_info=True)

    # -- GET -------------------------------------------------------------------------------------
    def do_GET(self) -> None:
        self._guarded(self._get)

    def _get(self) -> None:
        if self._vet() is None:
            return
        parts = urlsplit(self.path)
        path = parts.path
        if path in ASSETS:
            self._asset(ASSETS[path])
            return
        if path == "/field/api/state":
            query = parse_qs(parts.query)
            self._json(200, self.server.service.state(refresh=query.get("refresh", ["0"])[0] == "1"))
            return
        self._json(404, {"ok": False, "error": "not found"})

    # -- POST ------------------------------------------------------------------------------------
    def do_POST(self) -> None:
        self._body_consumed = 0
        self._guarded(self._post)

    def _post(self) -> None:
        origin = self._vet()
        if origin is None:
            return
        if not origin and not loopback_guard.verify_token(self.headers.get(loopback_guard.TOKEN_HEADER)):
            log.warning("field: refusing POST %s -- no allowed Origin and no valid %s", self.path,
                        loopback_guard.TOKEN_HEADER)
            self._refuse(403)
            return
        if not loopback_guard.content_type_is_json(self.headers.get("Content-Type")):
            self._json(415, {"ok": False, "error": "send application/json"})
            return
        body = self._read_json()
        if body is None:
            return
        svc: FieldService = self.server.service
        path = urlsplit(self.path).path
        try:
            if path == "/field/api/copy":
                dests = body.get("dests")
                run = svc.start_copy(str(body.get("serial") or ""), dests if isinstance(dests, list) else [])
                self._json(200, {"ok": True, "run": run})
            elif path == "/field/api/cancel":
                self._json(200, {"ok": bool(svc.cancel(str(body.get("runId") or "")))})
            elif path == "/field/api/folder":
                self._json(200, {"ok": True, "folders": svc.add_folder(str(body.get("path") or ""))})
            elif path == "/field/api/folder/remove":
                self._json(200, {"ok": True, "folders": svc.remove_folder(str(body.get("path") or ""))})
            elif path == "/field/api/kind":
                svc.set_kind(str(body.get("volumeId") or ""), str(body.get("kind") or ""))
                self._json(200, {"ok": True})
            elif path == "/field/api/remember":
                dests = body.get("dests")
                svc.remember(dests if isinstance(dests, list) else [])
                self._json(200, {"ok": True})
            elif path == "/field/api/sync":
                started = svc.sync_soon()
                self._json(200, {"ok": True, "started": bool(started)})
            else:
                self._json(404, {"ok": False, "error": "not found"})
        except ValueError as exc:
            self._json(409, {"ok": False, "error": str(exc)})

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("field: " + fmt, *args)


class FieldHTTPServer(ThreadingHTTPServer):
    # posix only: on Windows SO_REUSEADDR lets a second process share a bound port (broll_server)
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def __init__(self, address: tuple[str, int], service: FieldService, ccsync_cfg: Optional[dict] = None) -> None:
        super().__init__(address, FieldRequestHandler)
        self.service = service
        self.ccsync_cfg = ccsync_cfg or {}
        self._lock = threading.Lock()
        self._deadline = 0.0
        self._allowed: frozenset = frozenset()
        self._dev = False
        self._refresh()
        try:
            loopback_guard.ensure_token()
        except Exception:                                         # noqa: BLE001
            log.warning("field: could not publish a loopback token", exc_info=True)

    def _refresh(self) -> None:
        try:
            self._allowed = loopback_guard.allowed_origins(self.ccsync_cfg, site=site_mod.cached_site())
            self._dev = loopback_guard.dev_origins_enabled(self.ccsync_cfg)
        except Exception:                                         # noqa: BLE001
            log.warning("field: could not build the origin allow-list; keeping the old one", exc_info=True)
        self._deadline = time.monotonic() + ORIGIN_TTL_S

    def origin_policy(self) -> tuple[frozenset, bool]:
        if time.monotonic() >= self._deadline:
            with self._lock:
                if time.monotonic() >= self._deadline:
                    self._refresh()
        return self._allowed, self._dev


def make_server(cfg: dict[str, Any], service: FieldService, port: Optional[int] = None,
                host: str = HOST) -> FieldHTTPServer:
    """Bind a loopback-only server. Raises OSError if the port is taken."""
    return FieldHTTPServer((host, configured_port(cfg) if port is None else port), service, cfg)


def start(cfg: dict[str, Any], service: FieldService) -> Optional[FieldHTTPServer]:
    """What app.py calls. A thin name over start_server, so the suite can stub this one (it must not
    bind 8898 for real in every test that starts a CompanionApp) and still test start_server."""
    return start_server(cfg, service)


def start_server(cfg: dict[str, Any], service: FieldService) -> Optional[FieldHTTPServer]:
    """Serve the page on a daemon thread. Never raises; None when it is off or the port is taken."""
    global _LAST_BIND_ERROR
    if not is_enabled(cfg):
        log.info("field: the field backup page is switched off by config")
        return None
    try:
        server = make_server(cfg, service)
    except OSError as exc:
        text = f"{type(exc).__name__}: {exc}"
        log.log(logging.DEBUG if text == _LAST_BIND_ERROR else logging.WARNING,
                "field: could not listen on %s:%d (%s) -- the field backup page will not open on this "
                "computer. Everything else is unaffected.", HOST, configured_port(cfg), exc)
        _LAST_BIND_ERROR = text
        return None
    except Exception as exc:                                      # noqa: BLE001
        _LAST_BIND_ERROR = f"{type(exc).__name__}: {exc}"
        log.warning("field: the page failed to start (%s) -- continuing without it", exc, exc_info=True)
        return None
    try:
        threading.Thread(target=server.serve_forever, name="ccsync-field", daemon=True).start()
    except Exception:                                             # noqa: BLE001
        log.warning("field: could not start the server thread", exc_info=True)
        try:
            server.server_close()
        except Exception:                                         # noqa: BLE001
            pass
        return None
    _LAST_BIND_ERROR = ""
    log.info("field: the field backup page is at %s", page_url(cfg, server))
    return server


def stop(server: Optional[FieldHTTPServer]) -> None:
    """Stop the page and any copy it started. Never raises."""
    if server is None:
        return
    try:
        server.service.stop_all()
    except Exception:                                             # noqa: BLE001
        log.debug("field: stopping copies failed", exc_info=True)
    try:
        server.shutdown()
    except Exception:                                             # noqa: BLE001
        log.debug("field: shutdown() failed", exc_info=True)
    try:
        server.server_close()
    except Exception:                                             # noqa: BLE001
        log.debug("field: server_close() failed", exc_info=True)
