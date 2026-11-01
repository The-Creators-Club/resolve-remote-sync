"""In-process TrueNAS JSON-RPC websocket peer for tests (CR-365, 2026-10-07).

A stdlib RFC 6455 SERVER on 127.0.0.1, so truenas_rpc's own client framing is
exercised end to end (handshake, masking, length forms, ping, fragmentation).
Shared by dashboard/tests and server/tests (the latter loads this file by path).

It models only what the client relies on: auth.login_ex / login_with_api_key,
and a `handlers` dict of rpc-method -> callable(params) -> result. Raise Fail
for a JSON-RPC error. `calls` records (method, params) after login.

Knobs added for the overseer round (CR-365): `endpoint_status` (what a host
with no JSON-RPC answers at the upgrade), `paths` (which request paths
upgrade), `login_error` (a Fail for every auth method, e.g. a rate limit),
`no_legacy_key` (26 without auth.login_with_api_key), `connections` and
`drop_connections()` (session reuse and reconnect).
"""
from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class Fail(Exception):
    def __init__(self, code=-32001, message="Method call error", errname="", reason="", extra=None):
        self.code, self.message = code, message
        self.data = {"errname": errname, "reason": reason, "extra": extra}


class FakeRpcNas:
    def __init__(self, handlers=None, *, username="admin", password="pw", api_key="1-key",
                 endpoint=True, key_user=None, legacy_login=False,
                 endpoint_status=404, paths=None, login_error=None, no_legacy_key=False):
        self.handlers = handlers or {}
        self.username, self.password, self.api_key = username, password, api_key
        self.key_user = key_user or username
        self.endpoint = endpoint
        self.legacy_login = legacy_login   # no auth.login_ex: method not found
        self.endpoint_status = endpoint_status
        self.paths = paths                  # None = any request path upgrades
        self.request_paths: list[str] = []
        self.login_error = login_error
        self.no_legacy_key = no_legacy_key
        self.connections = 0
        self._conns: list = []
        self.calls: list[tuple[str, list]] = []
        self.logins: list[tuple[str, dict]] = []
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.port = self.srv.getsockname()[1]
        self._stop = False
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/api/current"

    def drop_connections(self):
        """Close every accepted socket, as a NAS does to an idle session."""
        for c in list(self._conns):
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                c.close()
            except OSError:
                pass

    def close(self):
        self._stop = True
        try:
            self.srv.close()
        except OSError:
            pass
        self.drop_connections()

    def _accept(self):
        while not self._stop:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            self.connections += 1
            self._conns.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    # -- frames
    @staticmethod
    def _read(conn, n):
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise EOFError
            buf += chunk
        return buf

    def _recv_text(self, conn):
        while True:
            text = self._recv_one(conn)
            if text is not None:
                return text

    def _recv_one(self, conn):
        b1, b2 = self._read(conn, 2)
        opcode, n = b1 & 0x0F, b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._read(conn, 2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._read(conn, 8))[0]
        mask = self._read(conn, 4)
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(self._read(conn, n)))
        if opcode == 0x8:
            raise EOFError
        if opcode in (0x9, 0xA):      # the client's pong to our ping
            return None
        return data.decode()

    @staticmethod
    def _frame(opcode, payload, fin=True):
        head = bytes([(0x80 if fin else 0) | opcode])
        n = len(payload)
        if n < 126:
            head += bytes([n])
        elif n < 65536:
            head += bytes([126]) + struct.pack(">H", n)
        else:
            head += bytes([127]) + struct.pack(">Q", n)
        return head + payload

    def _send(self, conn, obj):
        raw = json.dumps(obj).encode()
        # A notification first (the client must skip it), a ping (it must
        # pong), then the answer split across two frames when it is large.
        conn.sendall(self._frame(1, json.dumps(
            {"jsonrpc": "2.0", "method": "collection_update", "params": {}}).encode()))
        conn.sendall(self._frame(0x9, b"hi"))
        if len(raw) > 200:
            h = len(raw) // 2
            conn.sendall(self._frame(1, raw[:h], fin=False) + self._frame(0, raw[h:]))
        else:
            conn.sendall(self._frame(1, raw))

    def _serve(self, conn):
        try:
            buf = b""
            while b"\r\n\r\n" not in buf:
                buf += conn.recv(4096)
            head = buf.decode("latin-1")
            req_path = head.split(" ", 2)[1] if " " in head else ""
            self.request_paths.append(req_path)
            if not self.endpoint or (self.paths is not None and req_path not in self.paths):
                code = self.endpoint_status if not self.endpoint else 404
                conn.sendall(
                    f"HTTP/1.1 {code} X\r\nContent-Length: 0\r\n\r\n".encode())
                return
            key = [ln.split(":", 1)[1].strip() for ln in head.split("\r\n")
                   if ln.lower().startswith("sec-websocket-key")][0]
            acc = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
            conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                          f"Connection: Upgrade\r\nSec-WebSocket-Accept: {acc}\r\n\r\n").encode())
            authed = False
            while True:
                msg = json.loads(self._recv_text(conn))
                method, params, rid = msg["method"], msg.get("params") or [], msg["id"]

                def err(e):
                    return {"jsonrpc": "2.0", "id": rid, "error": {
                        "code": e.code, "message": e.message, "data": e.data}}
                if method.startswith("auth."):
                    self.logins.append((method, params))
                    if self.login_error is not None:
                        self._send(conn, err(self.login_error))
                        continue
                    res = self._auth(method, params)
                    if res == "NOMETHOD":
                        self._send(conn, err(Fail(-32601, "Method not found")))
                        continue
                    authed = authed or res is True or (
                        isinstance(res, dict) and res.get("response_type") == "SUCCESS")
                    self._send(conn, {"jsonrpc": "2.0", "id": rid, "result": res})
                    continue
                if not authed:
                    self._send(conn, err(Fail(errname="ENOTAUTHENTICATED", message="Not authenticated")))
                    continue
                self.calls.append((method, params))
                fn = self.handlers.get(method)
                try:
                    if fn is None:
                        raise Fail(-32601, "Method not found")
                    self._send(conn, {"jsonrpc": "2.0", "id": rid, "result": fn(params)})
                except Fail as e:
                    self._send(conn, err(e))
        except (EOFError, OSError, ValueError):
            pass
        finally:
            conn.close()

    def _auth(self, method, params):
        if method == "auth.login_ex":
            if self.legacy_login:
                return "NOMETHOD"
            p = params[0]
            if p["mechanism"] == "PASSWORD_PLAIN":
                ok = (p["username"], p["password"]) == (self.username, self.password)
            elif p["mechanism"] == "API_KEY_PLAIN":
                ok = p["api_key"] == self.api_key and p["username"] == self.key_user
            else:
                ok = False
            return {"response_type": "SUCCESS" if ok else "AUTH_ERR"}
        if method == "auth.login":
            return (params[0], params[1]) == (self.username, self.password)
        if method == "auth.login_with_api_key":
            if self.no_legacy_key:
                return "NOMETHOD"
            return params[0] == self.api_key
        return "NOMETHOD"
