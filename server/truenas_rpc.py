"""TrueNAS JSON-RPC 2.0 over WebSocket, behind a REST-shaped facade (stdlib only).

CR-365 / GL-11 + GL-46 (2026-10-07). TrueNAS deprecated the REST API
(/api/v2.0) in 25.04 and removed it in 26; the replacement is JSON-RPC 2.0 over
a WebSocket at /api/current (present from 25.04, so 25.04 and 25.10 speak
both). Every TrueNAS call in this product used to be a REST call whose callers
read `resp.status_code`, `resp.text` and `resp.json()`. Rather than rewrite
~40 call sites and their tests, this module maps each REST route this product
uses onto its JSON-RPC method and hands back an object with that same surface,
so both transports share one body of caller code.

TWO IDENTICAL COPIES, ON PURPOSE. This file lives at
  server/truenas_rpc.py
  dashboard/src/ccsync_dashboard/nas/truenas_rpc.py
because the dashboard container cannot import server/ (the split the TrueNAS
half has always had). It is therefore stdlib-only and self-contained, and
server/tests/test_truenas_rpc.py pins the two byte-identical. Edit both.

Versions assumed (no live probe was possible, 2026-10-07):
  * 24.10 and older: REST only. The WebSocket answers 404 at /api/current, which
    the "auto" transport reads as "fall back to REST". Unsupported, but works.
  * 25.04, 25.10: REST (deprecated) and JSON-RPC both. "auto" prefers JSON-RPC.
  * 26.x: JSON-RPC only. REST would 404 on every route.
Transport is DASH_NAS_API_TRANSPORT / TRUENAS_API_TRANSPORT = auto|jsonrpc|rest.

Verified-by-test: the framing and the request/response mapping against an
in-process WebSocket peer. NOT verified: a live TrueNAS. The login shapes
(`auth.login_ex` mechanisms, `auth.login_with_api_key`) and "a job method
returns its job id" are from the published middleware API; the first live run
must confirm them.

TLS: one `verify` parameter, the same meaning as requests' (False / True / a CA
bundle path / a `sha256:` certificate pin). The default is owned by the caller
(package A3b).

Overseer round 2 (CR-365, 2026-10-07), each a defect of the first build:
  * the key logs in as ITS account (`api_key_user`), not the admin's;
  * a login failure of any kind is an RpcAuthError, never a raw RpcError;
  * ONE authenticated session is reused per process and target (wait loops
    poll every 2 s; a login per poll trips TrueNAS's auth rate limit);
  * a handshake answer that is any HTTP status but 101 means "no JSON-RPC
    here" (REST fallback), and the REST-only memory expires (a NAS upgraded
    from 24.10 to 26 while we run must not be pinned to a dead API);
  * /api/current only, no version pin (CR-365 round 2): the release the NAS
    itself runs is the schema the payloads were verified against.

An API key sent over plaintext ws:// makes TrueNAS REVOKE the key, so ws://
is refused for any host that is not loopback (loopback exists for the tests).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import threading
import time
from typing import Any
from urllib.parse import urlparse

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
API_PATH = "/api/current"
# DASH_NAS_API_PATH / TRUENAS_API_PATH can still pin a versioned path by hand.
# CR-365 round 2 (GL-11, 2026-10-07): NO version pin. /api/current is the
# release the NAS itself runs, which is the schema every payload here was
# verified against (25.10.4 on the studio NAS); a pin to an older versioned
# path would move the live fleet onto models its payloads never ran on.
MAX_MESSAGE = 64 * 1024 * 1024

# First TrueNAS release with /api/current, the first that is JSON-RPC-only,
# and the newest this product has been reasoned about.
MIN_JSONRPC = (25, 4)
REST_REMOVED = (26, 0)
NEWEST_ASSUMED = (26, 99)


class RpcUnavailable(Exception):
    """This NAS does not serve JSON-RPC at /api/current (handshake 404): the
    caller may fall back to REST. NOT raised for a refused connection or a
    bad certificate, which REST would hit too."""


class RpcTransportError(Exception):
    """The socket/TLS/handshake failed for a reason a retry on REST would
    not fix. The message names what happened."""


class RpcAuthError(Exception):
    pass


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.data = data if isinstance(data, dict) else {}

    @property
    def errname(self) -> str:
        return str(self.data.get("errname") or "")


# --------------------------------------------------------------------------
# Minimal RFC 6455 client
# --------------------------------------------------------------------------

def _pin_digest(verify) -> str:
    """The hex digest in a `sha256:` certificate pin, else "" (GL-19, CR-368,
    2026-10-07: the default NAS TLS setting is a pin, see common.py)."""
    if isinstance(verify, str) and verify.lower().startswith("sha256:"):
        digest = verify[7:].replace(":", "").replace(" ", "").lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise RpcTransportError(f"{verify!r} is not a sha256 certificate pin")
        return digest
    return ""


def _ssl_context(verify) -> ssl.SSLContext:
    if _pin_digest(verify):
        # The pin IS the trust: the chain of a self-signed NAS cert is not
        # walked, and the fingerprint is compared after the handshake.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if verify is False or verify is None:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if verify is True:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=str(verify))


def _is_loopback(host: str) -> bool:
    return host in ("localhost", "::1") or host.startswith("127.")


class WebSocket:
    def __init__(self, url: str, verify=False, timeout: float = 30.0):
        u = urlparse(url)
        if u.scheme not in ("ws", "wss"):
            raise RpcTransportError(f"not a websocket URL: {url!r}")
        host = u.hostname or ""
        if u.scheme == "ws" and not _is_loopback(host):
            raise RpcTransportError(
                "refusing plaintext ws:// to a non-loopback host: TrueNAS revokes an "
                "API key used over an unencrypted connection")
        port = u.port or (443 if u.scheme == "wss" else 80)
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        self.timeout = timeout
        try:
            raw = socket.create_connection((host, port), timeout=timeout)
            if u.scheme == "wss":
                raw = _ssl_context(verify).wrap_socket(raw, server_hostname=host)
                pin = _pin_digest(verify)
                if pin and hashlib.sha256(raw.getpeercert(binary_form=True) or b"").hexdigest() != pin:
                    raw.close()
                    raise RpcTransportError(
                        f"the certificate {host}:{port} presented does not match the pinned "
                        "sha256 fingerprint; refusing (a changed NAS certificate is never "
                        "re-trusted)")
        except (OSError, ssl.SSLError) as exc:
            raise RpcTransportError(f"cannot connect to {host}:{port}: {exc}") from exc
        self.sock = raw
        self.sock.settimeout(timeout)
        self._buf = b""
        self._handshake(host, port, path)

    def _handshake(self, host: str, port: int, path: str) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n")
        try:
            self.sock.sendall(req.encode())
            while b"\r\n\r\n" not in self._buf:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise RpcTransportError("the NAS closed the connection during the handshake")
                self._buf += chunk
                if len(self._buf) > 65536:
                    raise RpcTransportError("handshake response too large")
        except (OSError, ssl.SSLError) as exc:
            self.close()
            raise RpcTransportError(f"websocket handshake failed: {exc}") from exc
        head, _, self._buf = self._buf.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        parts = lines[0].split(" ", 2)
        status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        if status != 101:
            self.close()
            # Any real HTTP answer other than the upgrade means this host has no
            # JSON-RPC endpoint here (a 24.10 nginx may answer 404, a UI catch-all
            # 200, a proxy 400/405/301): the caller may use REST. A 5xx or 429 is a
            # NAS that is busy or booting, which REST would hit too.
            if status and status < 500 and status != 429:
                raise RpcUnavailable(f"{path} answered HTTP {status}")
            raise RpcTransportError(f"websocket handshake refused: {lines[0]!r}")
        headers = {}
        for ln in lines[1:]:
            k, _, v = ln.partition(":")
            headers[k.strip().lower()] = v.strip()
        want = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != want:
            self.close()
            raise RpcTransportError("websocket handshake: bad Sec-WebSocket-Accept")

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RpcTransportError("the NAS closed the websocket")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        head = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(head + mask + masked)

    def send_text(self, text: str) -> None:
        try:
            self._send_frame(0x1, text.encode("utf-8"))
        except (OSError, ssl.SSLError) as exc:
            raise RpcTransportError(f"websocket send failed: {exc}") from exc

    def recv_text(self) -> str:
        message = b""
        try:
            while True:
                b1, b2 = self._read(2)
                fin, opcode = b1 & 0x80, b1 & 0x0F
                n = b2 & 0x7F
                if n == 126:
                    n = struct.unpack(">H", self._read(2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", self._read(8))[0]
                if n > MAX_MESSAGE:
                    raise RpcTransportError("websocket message too large")
                masked = b2 & 0x80
                mask = self._read(4) if masked else b""
                data = self._read(n)
                if masked:
                    data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
                if opcode == 0x8:
                    raise RpcTransportError("the NAS closed the websocket")
                if opcode == 0x9:
                    self._send_frame(0xA, data)
                    continue
                if opcode == 0xA:
                    continue
                message += data
                if len(message) > MAX_MESSAGE:
                    raise RpcTransportError("websocket message too large")
                if fin:
                    return message.decode("utf-8")
        except (OSError, ssl.SSLError) as exc:
            raise RpcTransportError(f"websocket read failed: {exc}") from exc

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except Exception:  # noqa: BLE001 - best effort on the way out
            pass
        try:
            self.sock.close()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------
# JSON-RPC session
# --------------------------------------------------------------------------

class RpcSession:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self._id = 0
        self._lock = threading.Lock()
        # True once the last request frame left this machine: a transport
        # failure after that may have executed the call, so a non-GET is never
        # replayed on a fresh connection.
        self.request_sent = False

    def call(self, method: str, params: list | None = None) -> Any:
        with self._lock:
            self._id += 1
            rid = self._id
            self.request_sent = False
            self.ws.send_text(json.dumps(
                {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or []}))
            self.request_sent = True
            while True:
                try:
                    msg = json.loads(self.ws.recv_text())
                except ValueError as exc:
                    raise RpcTransportError(f"{method}: reply was not JSON") from exc
                # Notifications (collection_update, ...) carry no id: skip them.
                if not isinstance(msg, dict) or msg.get("id") != rid:
                    continue
                if "error" in msg and msg["error"] is not None:
                    err = msg["error"] if isinstance(msg["error"], dict) else {}
                    raise RpcError(int(err.get("code") or 0),
                                   str(err.get("message") or "error"), err.get("data"))
                return msg.get("result")

    def login(self, user: str, password: str, api_key: str, api_key_user: str = "") -> None:
        """Authenticate, or raise RpcAuthError. NEVER a raw RpcError: a rate
        limit (EBUSY) or any other login refusal is an auth failure with the
        NAS's own words in it, so no caller's error contract is bypassed."""
        try:
            self._login(user, password, api_key, api_key_user)
        except RpcError as exc:
            raise RpcAuthError(f"the NAS refused the login: {exc.message}"
                               + (f" ({exc.errname})" if exc.errname else "")) from exc

    def _login(self, user: str, password: str, api_key: str, api_key_user: str) -> None:
        if api_key:
            # A key acts as the account it was minted for, which is NOT the
            # admin (create_api_key.py's dedicated account), so API_KEY_PLAIN
            # names that account: api_key_user, else `user` (a key minted for
            # the admin itself).
            key_user = api_key_user or user
            if key_user:
                try:
                    res = self.call("auth.login_ex", [{
                        "mechanism": "API_KEY_PLAIN", "username": key_user,
                        "api_key": api_key}])
                    if isinstance(res, dict) and res.get("response_type") == "SUCCESS":
                        return
                except RpcError as exc:
                    if exc.code != -32601 and exc.errname not in ("EINVAL", "EAUTH"):
                        raise
            # LEGACY fallback only: auth.login_with_api_key is deprecated from
            # 25.04 and may be gone on 26 (a missing method is just "no").
            try:
                if self.call("auth.login_with_api_key", [api_key]) is True:
                    return
            except RpcError as exc:
                if exc.code != -32601 and exc.errname not in ("EINVAL", "EAUTH"):
                    raise
            if key_user and not api_key_user:
                hint = (f"The key was presented as account {key_user!r}; a key only works "
                        "for the account it was made for. Set DASH_NAS_API_KEY_USER / "
                        "TRUENAS_API_KEY_USER to that account (create_api_key.py "
                        "--username). It may also be revoked or expired")
            elif key_user:
                hint = (f"The key was presented as account {key_user!r}. Check that is the "
                        "account the key was made for; it may also be revoked or expired")
            else:
                hint = ("No account name was given for the key: set DASH_NAS_API_KEY_USER / "
                        "TRUENAS_API_KEY_USER to the account it was made for")
            raise RpcAuthError("the NAS refused the API key. " + hint +
                               ". A key sent over a connection TrueNAS does not treat as "
                               "secure is revoked by it")
        try:
            res = self.call("auth.login_ex", [{
                "mechanism": "PASSWORD_PLAIN", "username": user, "password": password}])
            if isinstance(res, dict):
                if res.get("response_type") == "SUCCESS":
                    return
                raise RpcAuthError(f"the NAS refused the login ({res.get('response_type')})")
        except RpcError as exc:
            if exc.code != -32601:
                raise
            if self.call("auth.login", [user, password]) is True:
                return
        raise RpcAuthError("the NAS refused the username or password")

    def close(self) -> None:
        self.ws.close()


# --------------------------------------------------------------------------
# REST route -> JSON-RPC method
# --------------------------------------------------------------------------

class UnmappedRoute(Exception):
    pass


def _filters(params: dict | None) -> list:
    return [[k, "=", int(v) if k == "id" and str(v).isdigit() else v]
            for k, v in (params or {}).items()]


def _id_arg(raw: str):
    return int(raw) if raw.isdigit() else raw


def route(method: str, path: str, params: dict | None, body: Any) -> tuple[str, list]:
    """(rpc method, positional params) for a REST call, or UnmappedRoute.

    Every route here is one this product calls (see create_api_key.py's list
    and server/backends/truenas.py). Nothing is guessed for the rest: a route
    nobody mapped is a named refusal, not a wrong call on someone's NAS.
    """
    m = method.upper()
    seg = [s for s in path.split("/") if s]
    if not seg:
        raise UnmappedRoute(f"{m} {path}")
    ns = seg[0]
    body = {} if body is None else body

    if len(seg) == 1 and ns in ("user", "group", "app", "api_key"):
        rpc = {"GET": f"{ns}.query", "POST": f"{ns}.create"}.get(m)
        if rpc is None:
            raise UnmappedRoute(f"{m} {path}")
        return rpc, ([_filters(params)] if m == "GET" else [body])
    if len(seg) == 3 and seg[1] == "id" and ns in ("user", "group", "app", "api_key"):
        ident = _id_arg(seg[2])
        if m == "GET":
            return f"{ns}.get_instance", [ident]
        if m == "PUT":
            return f"{ns}.update", [ident, body]
        if m == "DELETE":
            return f"{ns}.delete", [ident, body] if body else [ident]
        raise UnmappedRoute(f"{m} {path}")
    if ns == "pool" and seg[1:2] == ["snapshottask"]:
        if len(seg) == 2 and m == "GET":
            return "pool.snapshottask.query", [_filters(params)]
        if len(seg) == 2 and m == "POST":
            return "pool.snapshottask.create", [body]
        if len(seg) == 4 and seg[2] == "id" and m == "PUT":
            return "pool.snapshottask.update", [_id_arg(seg[3]), body]
    if path == "/filesystem/setperm" and m == "POST":
        return "filesystem.setperm", [body]
    if path == "/core/get_jobs" and m == "GET":
        return "core.get_jobs", [_filters(params)]
    if path == "/zfs/snapshot" and m == "POST":
        # dashboard_update's pre-update snapshot. pool.snapshot.create is the
        # 25.04+ name; rest_call retries zfs.snapshot.create where it is absent.
        return "pool.snapshot.create", [body]
    if path == "/system/info" and m == "GET":
        return "system.info", []
    if path == "/ssh" and m == "GET":
        return "ssh.config", []
    if path == "/ssh" and m == "PUT":
        return "ssh.update", [body]
    # catalog/train were query filters over REST and app.available entries
    # carry both fields, so they stay filters here (CR-365 round 2): dropping
    # them let find_catalog_entry take an entry from another train.
    if path == "/app/available" and m == "GET":
        return "app.available", [_filters(params)]
    if path == "/catalog/apps" and m == "GET":
        return "catalog.apps", []
    if path == "/app/redeploy" and m == "POST":
        name = body.get("app_name") if isinstance(body, dict) else None
        if not name:
            raise UnmappedRoute(f"{m} {path} without app_name")
        return "app.redeploy", [name]
    raise UnmappedRoute(f"{m} {path}")


class RpcResponse:
    """The slice of requests.Response every caller here reads."""

    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload
        self.headers: dict = {}
        self.text = json.dumps(payload, default=str)

    def json(self) -> Any:
        return self._payload


_STATUS_BY_ERRNAME = {
    "EINVAL": 422, "ENOENT": 404, "EACCES": 403, "EPERM": 403,
    "ENOTAUTHENTICATED": 401, "EAUTH": 401, "EEXIST": 409,
}


def _error_response(exc: RpcError) -> RpcResponse:
    status = _STATUS_BY_ERRNAME.get(exc.errname)
    if status is None:
        status = {-32601: 404, -32602: 422}.get(exc.code, 500)
    detail = {"message": exc.message, "errname": exc.errname,
              "reason": exc.data.get("reason"), "extra": exc.data.get("extra")}
    return RpcResponse(status, detail)


# Method renamed between releases: tried second when the first is "no such method".
FALLBACK_METHODS = {"pool.snapshot.create": "zfs.snapshot.create"}


def ws_url_for(host: str, path: str = API_PATH) -> str:
    return f"wss://{host}{path}"


def api_paths() -> tuple[str, ...]:
    raw = (os.environ.get("DASH_NAS_API_PATH", "").strip()
           or os.environ.get("TRUENAS_API_PATH", "").strip())
    if raw:
        if raw.lower() == "current":
            return (API_PATH,)
        return (raw if raw.startswith("/") else f"/api/{raw}",)
    return (API_PATH,)


# Hosts that answered "no JSON-RPC here", with the time the answer expires. A
# TTL, not forever: a NAS upgraded from 24.10 to 26 under a running process
# must not stay pinned to an API that no longer exists.
REST_ONLY_TTL = 300.0
_REST_ONLY: dict[str, float] = {}
_GOOD_PATH: dict[str, str] = {}


def rest_only(host: str) -> bool:
    exp = _REST_ONLY.get(host)
    if exp is None:
        return False
    if time.monotonic() >= exp:
        _REST_ONLY.pop(host, None)
        return False
    return True


def mark_rest_only(host: str) -> None:
    _REST_ONLY[host] = time.monotonic() + REST_ONLY_TTL


def clear_rest_only(host: str) -> None:
    _REST_ONLY.pop(host, None)


# One authenticated session per target, reused (CR-365 overseer 3): a wait loop
# polls core.get_jobs every 2 s, and a fresh login per poll is ~30 unauthenticated
# auth calls a minute from one address, which TrueNAS rate-limits (and every
# login lands in its audit log). Idle sessions are dropped before they can be
# closed under us by the NAS.
IDLE_LIMIT = 25.0
_POOL: dict = {}
_POOL_LOCK = threading.Lock()


class _Pooled:
    def __init__(self, session: RpcSession):
        self.session = session
        self.last_used = time.monotonic()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reset_pool() -> None:
    """Close every pooled session (tests, and a deliberate reconnect)."""
    with _POOL_LOCK:
        pooled = list(_POOL.values())
        _POOL.clear()
    for p in pooled:
        p.session.close()


def _drop(key: tuple, pooled: "_Pooled") -> None:
    with _POOL_LOCK:
        if _POOL.get(key) is pooled:
            del _POOL[key]
    pooled.session.close()


def _open_ws(host: str, url: str | None, verify, timeout: float) -> WebSocket:
    if url:
        return WebSocket(url, verify=verify, timeout=timeout)
    paths = api_paths()
    if host in _GOOD_PATH and _GOOD_PATH[host] in paths:
        paths = (_GOOD_PATH[host],)
    last: RpcUnavailable | None = None
    for path in paths:
        try:
            ws = WebSocket(ws_url_for(host, path), verify=verify, timeout=timeout)
        except RpcUnavailable as exc:
            last = exc
            continue
        _GOOD_PATH[host] = path
        return ws
    _GOOD_PATH.pop(host, None)
    raise last or RpcUnavailable("no JSON-RPC endpoint")


def _acquire(key: tuple, host: str, url: str | None, verify, timeout: float,
             user: str, password: str, api_key: str, api_key_user: str):
    """(pooled session, reused?). Login failures never enter the pool."""
    stale = None
    with _POOL_LOCK:
        pooled = _POOL.get(key)
        if pooled is not None and time.monotonic() - pooled.last_used > IDLE_LIMIT:
            del _POOL[key]
            stale, pooled = pooled, None
    if stale is not None:
        stale.session.close()
    if pooled is not None:
        return pooled, True
    session = RpcSession(_open_ws(host, url, verify, timeout))
    try:
        session.login(user, password, api_key, api_key_user)
    except BaseException:
        session.close()
        raise
    fresh = _Pooled(session)
    with _POOL_LOCK:
        existing = _POOL.get(key)
        if existing is None:
            _POOL[key] = fresh
            return fresh, False
    session.close()  # another thread connected first: use theirs
    return existing, True


def rest_call(host: str, method: str, path: str, json_body: Any = None,
              params: dict | None = None, *, user: str = "", password: str = "",
              api_key: str = "", api_key_user: str = "", verify=False,
              timeout: float = 30.0, url: str | None = None) -> RpcResponse:
    """Run one REST-shaped call over a pooled, authenticated JSON-RPC session.

    Raises RpcUnavailable (no JSON-RPC endpoint: caller may use REST),
    UnmappedRoute, RpcTransportError or RpcAuthError (named failures); an
    error the NAS answers to the call itself comes back as a response with an
    HTTP-like status, as REST would give it.
    """
    rpc, args = route(method, path, params, json_body)
    key = (url or host, _digest(user), _digest(password), _digest(api_key),
           api_key_user, str(verify))
    for attempt in (0, 1):
        pooled, reused = _acquire(key, host, url, verify, timeout,
                                  user, password, api_key, api_key_user)
        if reused and method.upper() != "GET":
            # A pooled socket the NAS closed while idle swallows a send into a
            # dead TCP connection, which would leave a write unretryable (its
            # frame "was sent"). A cheap liveness call first, so a dead socket
            # is replaced BEFORE the write; a live peer's write is still never
            # replayed (CR-365 round 2, 2026-10-07).
            try:
                pooled.session.call("core.ping", [])
            except RpcTransportError:
                _drop(key, pooled)
                pooled, reused = _acquire(key, host, url, verify, timeout,
                                          user, password, api_key, api_key_user)
            except RpcError:
                pass  # answered: the socket is alive
        try:
            try:
                result = pooled.session.call(rpc, args)
            except RpcError as exc:
                alt = FALLBACK_METHODS.get(rpc)
                if alt and exc.code == -32601:
                    result = pooled.session.call(alt, args)
                else:
                    raise
        except RpcError as exc:
            pooled.last_used = time.monotonic()
            return _error_response(exc)
        except RpcTransportError:
            _drop(key, pooled)
            # A pooled socket the NAS closed while idle fails like this; one
            # retry on a fresh login, but never a replay of a write that may
            # already have run.
            if (reused and attempt == 0
                    and (method.upper() == "GET" or not pooled.session.request_sent)):
                continue
            raise
        pooled.last_used = time.monotonic()
        return RpcResponse(200, result)
    raise RpcTransportError("unreachable")  # pragma: no cover


# --------------------------------------------------------------------------
# Transport choice + version statement
# --------------------------------------------------------------------------

TRANSPORTS = ("auto", "jsonrpc", "rest")


def transport_setting() -> str:
    raw = (os.environ.get("DASH_NAS_API_TRANSPORT", "").strip()
           or os.environ.get("TRUENAS_API_TRANSPORT", "").strip()).lower()
    return raw if raw in TRANSPORTS else "auto"


def parse_version(text: str) -> tuple[int, int] | None:
    import re
    m = re.search(r"(\d{2})\.(\d{1,2})", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def version_note(text: str) -> str:
    """"" when `text` (system.version / system.info version) is a release this
    product supports, else a sentence naming why not. Never a refusal on
    doubt: an unparseable version returns a note, not an error."""
    ver = parse_version(text)
    if ver is None:
        return f"cannot tell the TrueNAS version from {text!r}"
    if ver < MIN_JSONRPC:
        return (f"TrueNAS {text} predates 25.04: only the REST API exists there, which "
                "works but is not a supported version. Upgrade to 25.04 or later")
    if ver > NEWEST_ASSUMED:
        return (f"TrueNAS {text} is newer than this CC Sync release has been tested "
                "against. Check docs/SERVER.md for the supported versions before upgrading")
    return ""
