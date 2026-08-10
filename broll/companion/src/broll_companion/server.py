"""HTTP server for BRoll Companion.

Implements the "Companion API contract" section of SPEC.md exactly:
  GET  /status
  POST /insert
plus OPTIONS preflight handling and permissive CORS (loopback-only bind
makes that safe — see SPEC.md).

Uses stdlib http.server only, to keep a PyInstaller bundle small.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse

from . import config as config_mod
from . import resolve_bridge
from .paths import MountNotConfiguredError, PathTraversalError, translate_path

HOST = "127.0.0.1"
PORT = 8899


def _json_bytes(obj: dict) -> bytes:
    return json.dumps(obj).encode("utf-8")


def build_status_response(mounts: dict) -> dict:
    """GET /status body, per SPEC.md: {ok, resolve_connected, mounts, version}."""
    return {
        "ok": True,
        "resolve_connected": resolve_bridge.try_connect(),
        "mounts": mounts,
        "version": config_mod.VERSION,
    }


def build_insert_response(body: dict, mounts: dict) -> tuple[int, dict]:
    """POST /insert logic. Returns (http_status, json_body).

    Path traversal is the one failure that gets a non-200 HTTP status (400);
    every other expected failure path returns 200 with {"ok": false, ...} so
    the web UI can show the message inline.
    """
    share = body.get("share")
    rel_path = body.get("rel_path")
    in_frame = body.get("in_frame")
    out_frame = body.get("out_frame")
    mode = body.get("mode", "append")

    if mode != "append":
        # mode "playhead" is reserved; anything else isn't a defined v1 mode.
        return 200, {"ok": False, "message": "not implemented yet"}

    if not isinstance(in_frame, int) or not isinstance(out_frame, int):
        return 400, {"ok": False, "message": "in_frame and out_frame must be integers"}
    if out_frame <= in_frame:
        return 200, {"ok": False, "message": "out point must be after in point"}

    try:
        local_path_str = translate_path(share, rel_path, mounts)
    except PathTraversalError as exc:
        return 400, {"ok": False, "message": str(exc)}
    except MountNotConfiguredError as exc:
        return 200, {"ok": False, "message": str(exc)}

    local_path = Path(local_path_str)
    if not local_path.is_file():
        return 200, {
            "ok": False,
            "message": f"file not found at {local_path} — is the share mounted?",
        }

    result = resolve_bridge.perform_insert(str(local_path), in_frame, out_frame)
    return 200, result


class CompanionRequestHandler(BaseHTTPRequestHandler):
    server_version = f"BRollCompanion/{config_mod.VERSION}"

    def _set_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        # Private Network Access. Once the b-roll UI is served from the cc_sync
        # dashboard, the page comes from a tailnet address and calls loopback —
        # exactly the public-to-private direction Chromium is progressively
        # blocking, and it blocks at the PREFLIGHT, so without this the insert
        # button fails before any of our code runs. Harmless on browsers that
        # don't implement it, and on the current :8420 origin.
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send_json(self, status: int, obj: dict) -> None:
        payload = _json_bytes(obj)
        self.send_response(status)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # CORS preflight
        self.send_response(204)
        self._set_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/status":
            mounts = self.server.companion_config.get("mounts", {})
            self._send_json(200, build_status_response(mounts))
        else:
            self._send_json(404, {"ok": False, "message": f"not found: {path}"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/insert":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"ok": False, "message": "invalid JSON body"})
                return
            mounts = self.server.companion_config.get("mounts", {})
            status, result = build_insert_response(body, mounts)
            self._send_json(status, result)
        else:
            self._send_json(404, {"ok": False, "message": f"not found: {path}"})

    def log_message(self, fmt: str, *args) -> None:  # quiet, prefixed console log
        sys.stdout.write("[companion] " + (fmt % args) + "\n")


class CompanionServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler_cls, companion_config: dict):
        super().__init__(server_address, handler_cls)
        self.companion_config = companion_config


def make_server(
    cfg: dict, host: str = HOST, port: int = PORT
) -> CompanionServer:
    return CompanionServer((host, port), CompanionRequestHandler, cfg)


def run(host: str = HOST, port: int = PORT) -> None:
    cfg = config_mod.load_config()
    server = make_server(cfg, host, port)

    print(f"[companion] BRoll Companion v{config_mod.VERSION} listening on http://{host}:{port}")
    print(f"[companion] config: {config_mod.CONFIG_PATH}")
    print(f"[companion] mounts: {cfg.get('mounts', {})}")

    tray_icon = None
    try:
        from . import tray as tray_mod

        tray_icon = tray_mod.start_tray(server)
        print("[companion] tray icon started")
    except ImportError:
        print("[companion] pystray/Pillow not installed — running headless (Ctrl+C to stop)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[companion] shutting down")
    finally:
        server.server_close()
        if tray_icon is not None:
            tray_icon.stop()


if __name__ == "__main__":
    run()
