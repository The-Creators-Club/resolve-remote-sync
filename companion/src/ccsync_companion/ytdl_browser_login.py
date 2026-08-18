"""One-click "Sign in to YouTube": a real browser, a private profile, and the
cookies file written for the editor.

WHY (2026-08-17). Until now "Sign in to YouTube (for downloads)…" meant: go
find a cookies.txt export extension, sign in, export, come back, pick the
file. Most editors never got that far. What they asked for was "click, log
in with Google, done" -- and that exact result is possible, but not the way
it sounds:

- OAuth / "Sign in with Google" cannot do it. yt-dlp does not download as a
  Google ACCOUNT, it impersonates a browser SESSION, and the endpoints it
  talks to accept session cookies (SID/SAPISID/...), not OAuth tokens. The
  one OAuth route that ever existed (the TV device-code login the
  yt-dlp-youtube-oauth2 plugin used) was shut by Google in late 2024. So the
  flow has to END in a cookies file whatever it looks like at the start.
- Reading the editor's everyday browser is not reliable either: Chrome on
  Windows (127+) app-bound-encrypts its cookies so nothing outside Chrome
  can decrypt them, and cookies lifted from a profile the person keeps using
  rotate out from under yt-dlp within days -- yt-dlp's own guidance is to
  sign in in a fresh private window, export, and never browse with it again.

So this does the recommended thing, automatically: launch a REAL Chromium
browser (Edge is on every Windows box; Chrome/Edge on macOS) with a private
profile the companion owns and a DevTools port on loopback, open Google's
sign-in with YouTube as the continue URL, watch over the Chrome DevTools
Protocol until logged-in session cookies exist, show "Signed in -- closing"
in the window for two seconds, pull the cookies with Network.getAllCookies,
write them as Netscape cookies.txt through ytdl_cookies (same validate, same
0600 hardening as the manual path), and close the browser. The profile is
kept (so "sign in again" is instant) but never browsed with, which is what
keeps the cookies from rotating.

A real browser rather than an embedded webview on purpose: Google refuses
sign-in from embedded frameworks ("this browser or app may not be secure"),
and passkeys/2FA/security keys only work in the real thing.

Trust boundary. While the window is open, its DevTools port on 127.0.0.1 is
an unauthenticated local API over a live Google session. It is an ephemeral
port, loopback only (Chrome binds it there itself), open for the minutes the
sign-in takes, and closed the moment the cookies are captured or the flow
gives up. Chrome 136+ additionally refuses remote debugging on the DEFAULT
profile -- ours is never the default profile, so this keeps working. Nothing
here changes the feature's gate: `ytdl_cookies.enabled()` (site
`youtube_unblock`, the customer's legal decision) is checked first and the
tray never offers the item on a site that has not turned it on.

Every OS/network seam is injectable so the tests drive the whole flow with a
fake browser and a fake CDP session; the WebSocket framing is tested against
RFC 6455 vectors on its own.
"""
from __future__ import annotations

import base64
import http.client
import json
import logging
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import ytdl_cookies

log = logging.getLogger("ccsync.ytdl")

# The sign-in page. Google's own entry point with youtube.com as the
# continue target lands the person on a signed-in youtube.com, which is where
# the session cookies we need get set. Signing in "somewhere on Google" is not
# enough: SID/SAPISID must exist on the youtube.com domain.
LOGIN_URL = ("https://accounts.google.com/ServiceLogin"
             "?continue=https%3A%2F%2Fwww.youtube.com%2F&hl=en")

# How long the person gets to type a password, do 2FA, pick an account.
# Generous: security-key prompts and "verify it's you" loops are slow.
LOGIN_TIMEOUT_SECONDS = 10 * 60
# How long the browser gets to open its DevTools port before we call the
# launch failed. Cold Edge on a slow laptop takes ~5 s; 30 leaves room.
DEVTOOLS_READY_SECONDS = 30
# The "Signed in ✓" page stays up this long so the person sees the outcome
# instead of a window vanishing. The user chose two seconds (2026-08-17).
DONE_PAGE_SECONDS = 2.0
POLL_SECONDS = 1.0

# Only these domains go into the file. yt-dlp reads youtube.com; the
# .google.com session cookies are what a full manual export carries too and
# what keeps age verification consistent across the two. Everything else the
# profile picked up (doubleclick, gstatic...) is noise and stays out.
COOKIE_DOMAIN_SUFFIXES = ("youtube.com", "google.com")

PROFILE_DIRNAME = "yt-login-profile"
BROWSER_ENV = "CCSYNC_YT_BROWSER"


@dataclass
class Browser:
    name: str
    path: str


@dataclass
class Outcome:
    ok: bool
    message: str
    cookies_written: int = 0


# ------------------------------------------------------------ discovery
def _candidates() -> list[tuple[str, list[str]]]:
    """(name, [paths]) in preference order for THIS OS. Edge first on
    Windows because it is on every Windows 10/11 machine; Chrome first on
    macOS because it is the one editors there usually have."""
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        return [
            ("Microsoft Edge", [
                os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
            ]),
            ("Google Chrome", [
                os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(local, "Google", "Chrome", "Application", "chrome.exe") if local else "",
            ]),
            ("Brave", [
                os.path.join(pf, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
                os.path.join(pf86, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
            ]),
        ]
    if sys.platform == "darwin":
        return [
            ("Google Chrome", ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                               os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]),
            ("Microsoft Edge", ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                                os.path.expanduser("~/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]),
            ("Brave", ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]),
            ("Chromium", ["/Applications/Chromium.app/Contents/MacOS/Chromium"]),
        ]
    return [
        ("Google Chrome", ["google-chrome", "google-chrome-stable"]),
        ("Chromium", ["chromium", "chromium-browser"]),
        ("Microsoft Edge", ["microsoft-edge"]),
    ]


def find_browser(environ: Optional[dict] = None, is_file=os.path.isfile,
                 which=shutil.which) -> Optional[Browser]:
    """The Chromium browser to drive, or None. `CCSYNC_YT_BROWSER` (a path)
    wins so an editor with an odd install location is not stuck; Safari and
    Firefox are deliberately absent -- neither speaks CDP."""
    env = os.environ if environ is None else environ
    forced = str(env.get(BROWSER_ENV, "") or "").strip()
    if forced:
        if is_file(forced):
            return Browser(Path(forced).stem, forced)
        log.warning("ytdl sign-in: %s=%r is not a file; ignoring it", BROWSER_ENV, forced)
    for name, paths in _candidates():
        for p in paths:
            if not p:
                continue
            if os.path.isabs(p):
                if is_file(p):
                    return Browser(name, p)
            else:
                found = which(p)
                if found:
                    return Browser(name, found)
    return None


def profile_dir(home: Optional[Path] = None) -> Path:
    base = (home or Path.home()) / ".ccsync" / PROFILE_DIRNAME
    return base


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def launch_args(browser: Browser, profile: Path, port: int, url: str = LOGIN_URL) -> list[str]:
    """The exact command line. Flags explained where they are not obvious:
    --user-data-dir: OUR profile, never the person's (see module docstring);
    --remote-debugging-port: loopback CDP; --no-first-run /
    --no-default-browser-check: no welcome tour, no 'make me default' nag;
    --disable-sync: this profile must never sync anything anywhere;
    --new-window: a window, not a tab in an existing instance -- and because
    the user-data-dir is unique, this launch IS its own instance even if the
    person's Edge/Chrome is already running."""
    return [
        browser.path,
        f"--user-data-dir={profile}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-features=Translate",
        "--window-size=1024,820",
        "--new-window",
        url,
    ]


# ------------------------------------------------------------ websocket
def _mask(payload: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % 4] for i, b in enumerate(payload))


def encode_frame(payload: bytes, opcode: int = 0x1, mask_key: Optional[bytes] = None) -> bytes:
    """Client->server frame (RFC 6455 §5.2). Client frames MUST be masked."""
    key = mask_key if mask_key is not None else os.urandom(4)
    head = bytes([0x80 | (opcode & 0x0F)])
    n = len(payload)
    if n < 126:
        head += bytes([0x80 | n])
    elif n < (1 << 16):
        head += bytes([0x80 | 126]) + struct.pack("!H", n)
    else:
        head += bytes([0x80 | 127]) + struct.pack("!Q", n)
    return head + key + _mask(payload, key)


def decode_frame(read: Callable[[int], bytes]) -> tuple[bool, int, bytes]:
    """One frame from a blocking `read(n)` (which must return exactly n
    bytes or raise). Returns (fin, opcode, payload); unmasks if masked."""
    b0, b1 = read(2)
    fin = bool(b0 & 0x80)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    n = b1 & 0x7F
    if n == 126:
        (n,) = struct.unpack("!H", read(2))
    elif n == 127:
        (n,) = struct.unpack("!Q", read(8))
    key = read(4) if masked else b""
    payload = read(n) if n else b""
    if masked:
        payload = _mask(payload, key)
    return fin, opcode, payload


class WebSocket:
    """The little of RFC 6455 a CDP client needs: handshake, text frames in
    both directions, continuation frames reassembled, pings answered, close
    honoured. Loopback only -- no TLS, no origin, no extensions."""

    def __init__(self, url: str, timeout: float = 30.0):
        u = urllib.parse.urlsplit(url)
        if u.scheme != "ws":
            raise ValueError(f"only ws:// is supported here, got {url!r}")
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        req = (f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port or 80}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode("ascii"))
        status = self._read_http_head()
        if " 101 " not in status.split("\r\n", 1)[0]:
            raise ConnectionError(f"websocket handshake refused: {status.splitlines()[0]!r}")
        self._lock = threading.Lock()

    def _read_http_head(self) -> str:
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(1)
            if not chunk:
                raise ConnectionError("websocket handshake: connection closed")
            buf += chunk
            if len(buf) > 65536:
                raise ConnectionError("websocket handshake: header too large")
        return buf.decode("latin-1")

    def _read_exact(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise ConnectionError("websocket: connection closed")
            out += chunk
        return out

    def send_text(self, text: str) -> None:
        with self._lock:
            self.sock.sendall(encode_frame(text.encode("utf-8"), 0x1))

    def recv_text(self) -> str:
        """Next complete text message; answers pings; raises on close."""
        buf = b""
        while True:
            fin, opcode, payload = decode_frame(self._read_exact)
            if opcode == 0x9:                       # ping -> pong
                with self._lock:
                    self.sock.sendall(encode_frame(payload, 0xA))
                continue
            if opcode == 0xA:                       # pong: ignore
                continue
            if opcode == 0x8:
                raise ConnectionError("websocket: closed by peer")
            if opcode in (0x1, 0x0):
                buf += payload
                if fin:
                    return buf.decode("utf-8", errors="replace")
                continue
            # binary frames never happen on CDP; skip anything else
            continue

    def close(self) -> None:
        try:
            with self._lock:
                self.sock.sendall(encode_frame(b"", 0x8))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# ------------------------------------------------------------ CDP
class CdpSession:
    """Request/response over one page target's websocket. Events that arrive
    while waiting for a reply are dropped -- nothing here subscribes to any."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self._next = 0

    def call(self, method: str, params: Optional[dict] = None, timeout: float = 30.0) -> dict:
        self._next += 1
        msg_id = self._next
        self.ws.send_text(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = self.ws.recv_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method}: {msg['error']}")
                return msg.get("result") or {}
        raise TimeoutError(f"CDP {method}: no reply in {timeout}s")

    def close(self) -> None:
        self.ws.close()


def _http_json(port: int, path: str, timeout: float = 5.0) -> Any:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        data = resp.read()
        if resp.status != 200:
            raise ConnectionError(f"devtools {path}: HTTP {resp.status}")
        return json.loads(data.decode("utf-8", errors="replace"))
    finally:
        conn.close()


def wait_for_devtools(port: int, deadline_seconds: float = DEVTOOLS_READY_SECONDS,
                      alive: Callable[[], bool] = lambda: True,
                      sleep=time.sleep, clock=time.monotonic) -> bool:
    end = clock() + deadline_seconds
    while clock() < end:
        if not alive():
            return False
        try:
            _http_json(port, "/json/version", timeout=2.0)
            return True
        except Exception:  # noqa: BLE001 -- not up yet
            sleep(0.25)
    return False


def page_websocket_url(port: int) -> Optional[str]:
    """The first 'page' target's debugger URL, or None."""
    try:
        targets = _http_json(port, "/json/list")
    except Exception:  # noqa: BLE001
        return None
    for t in targets if isinstance(targets, list) else []:
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            return str(t["webSocketDebuggerUrl"])
    return None


def open_session(port: int) -> Optional[CdpSession]:
    url = page_websocket_url(port)
    if not url:
        return None
    return CdpSession(WebSocket(url))


# ------------------------------------------------------------ cookies
def relevant(cookies: Iterable[dict]) -> list[dict]:
    out = []
    for c in cookies or []:
        dom = str(c.get("domain", "")).lower().lstrip(".")
        if any(dom == s or dom.endswith("." + s) for s in COOKIE_DOMAIN_SUFFIXES):
            out.append(c)
    return out


def signed_in(cookies: Iterable[dict]) -> bool:
    """Same rule as ytdl_cookies.validate: a couple of the real login cookies
    on a youtube.com domain. Consent/visitor cookies alone do not count."""
    names = set()
    for c in cookies or []:
        dom = str(c.get("domain", "")).lower()
        if "youtube.com" in dom and c.get("name") in ytdl_cookies._SESSION_COOKIE_NAMES:
            names.add(c["name"])
    return len(names) >= ytdl_cookies._MIN_SESSION_COOKIES


def netscape_text(cookies: Iterable[dict]) -> str:
    """CDP cookie dicts -> Netscape cookies.txt. Fields: domain, include-
    subdomains (TRUE when the domain is host-wide, i.e. leading dot / not
    hostOnly), path, secure, expiry (0 for session), name, value. HttpOnly
    cookies get the `#HttpOnly_` prefix curl/yt-dlp understand."""
    lines = ["# Netscape HTTP Cookie File",
             "# Written by ccsync-companion (Sign in to YouTube). This is a live "
             "Google session: do not share it.", ""]
    for c in cookies:
        domain = str(c.get("domain", ""))
        host_only = bool(c.get("hostOnly")) if "hostOnly" in c else not domain.startswith(".")
        if not host_only and not domain.startswith("."):
            domain = "." + domain
        include_sub = "FALSE" if host_only else "TRUE"
        path = str(c.get("path") or "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        exp = c.get("expires", -1)
        try:
            expiry = int(exp) if exp is not None and float(exp) > 0 else 0
        except (TypeError, ValueError):
            expiry = 0
        name = str(c.get("name", ""))
        value = str(c.get("value", ""))
        if not name or "\t" in name or "\n" in value or "\t" in value:
            continue
        prefix = "#HttpOnly_" if c.get("httpOnly") else ""
        lines.append("\t".join([prefix + domain, include_sub, path, secure, str(expiry), name, value]))
    return "\n".join(lines) + "\n"


DONE_HTML = (
    "<!doctype html><meta charset='utf-8'><title>Signed in</title>"
    "<body style='margin:0;height:100vh;display:flex;align-items:center;justify-content:center;"
    "font:20px system-ui,sans-serif;background:#0f0f10;color:#eee'>"
    "<div style='text-align:center'><div style='font-size:64px;color:#3ddc84'>&#10003;</div>"
    "<div>Signed in to YouTube.</div><div style='opacity:.6;margin-top:8px'>"
    "Closing this window&hellip;</div></div></body>"
)


def done_page_url() -> str:
    return "data:text/html;charset=utf-8," + urllib.parse.quote(DONE_HTML, safe="")


# ------------------------------------------------------------ the flow
def run(
    *,
    browser: Optional[Browser] = None,
    profile: Optional[Path] = None,
    launcher: Callable[[list[str]], Any] = None,
    session_factory: Callable[[int], Optional[CdpSession]] = open_session,
    wait_devtools: Callable[..., bool] = wait_for_devtools,
    port_picker: Callable[[], int] = free_port,
    install_text: Callable[[str], tuple[bool, str]] = ytdl_cookies.install_text,
    sleep=time.sleep,
    clock=time.monotonic,
    login_timeout: float = LOGIN_TIMEOUT_SECONDS,
    done_page_seconds: float = DONE_PAGE_SECONDS,
    progress: Optional[Callable[[str], None]] = None,
) -> Outcome:
    """The whole thing. Never raises; returns an Outcome the tray can show.

    Cleanup is unconditional: whatever happens after launch, the browser is
    told to close (Browser.close over CDP, then terminate/kill) so no
    signed-in window with an open debug port is left behind."""
    if not ytdl_cookies.enabled():
        return Outcome(False, ytdl_cookies.OFF_MESSAGE)
    browser = browser or find_browser()
    if browser is None:
        return Outcome(False, "no Chromium browser found (Microsoft Edge, Google Chrome or Brave). "
                              "Install one, or use the cookies.txt file instead")
    profile = profile or profile_dir()
    try:
        profile.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(profile, 0o700)
        except OSError:
            pass
    except OSError as exc:
        return Outcome(False, f"couldn't create the sign-in profile folder ({exc})")

    port = port_picker()
    argv = launch_args(browser, profile, port)
    launcher = launcher or _default_launcher
    try:
        proc = launcher(argv)
    except OSError as exc:
        return Outcome(False, f"couldn't start {browser.name} ({exc})")
    log.info("ytdl sign-in: launched %s with a private profile, devtools on 127.0.0.1:%d", browser.name, port)
    if progress:
        progress(f"{browser.name} is opening. Sign in to YouTube in that window")

    session: Optional[CdpSession] = None
    try:
        if not wait_devtools(port, alive=lambda: _alive(proc), sleep=sleep, clock=clock):
            return Outcome(False, f"{browser.name} started but its sign-in window never became reachable. "
                                  "Close any leftover windows and try again")
        session = session_factory(port)
        if session is None:
            return Outcome(False, "the sign-in window opened but could not be inspected - try again")

        end = clock() + login_timeout
        cookies: list[dict] = []
        while clock() < end:
            if not _alive(proc):
                return Outcome(False, "the browser was closed before the sign-in finished - nothing saved")
            try:
                cookies = list((session.call("Network.getAllCookies", timeout=10) or {}).get("cookies") or [])
            except (ConnectionError, TimeoutError, RuntimeError, OSError) as exc:
                # The page target we attached to can go away on redirects
                # (accounts.google.com -> youtube.com is same-target in
                # practice, but a popup/2FA tab is not). Re-attach and go on.
                log.debug("ytdl sign-in: CDP call failed (%s); re-attaching", exc)
                try:
                    session.close()
                except Exception:  # noqa: BLE001
                    pass
                session = session_factory(port)
                if session is None:
                    sleep(POLL_SECONDS)
                    continue
                cookies = []
            if signed_in(cookies):
                break
            sleep(POLL_SECONDS)
        else:
            return Outcome(False, "the sign-in did not finish in time - nothing saved; try again")

        text = netscape_text(relevant(cookies))
        ok, message = install_text(text)
        if not ok:
            return Outcome(False, message)
        try:
            session.call("Page.navigate", {"url": done_page_url()}, timeout=10)
        except Exception:  # noqa: BLE001 -- cosmetic
            log.debug("ytdl sign-in: could not show the done page", exc_info=True)
        sleep(done_page_seconds)
        return Outcome(True, message, cookies_written=len(relevant(cookies)))
    finally:
        _shutdown(session, proc, sleep=sleep, clock=clock)


def _default_launcher(argv: list[str]):
    kw: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                          "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(argv, **kw)


def _alive(proc) -> bool:
    poll = getattr(proc, "poll", None)
    if poll is None:
        return True
    try:
        return poll() is None
    except Exception:  # noqa: BLE001
        return False


def _shutdown(session: Optional[CdpSession], proc, sleep=time.sleep, clock=time.monotonic) -> None:
    """Close politely over CDP (Browser.close flushes the profile to disk),
    then make sure the process is gone. Order matters: a killed Chromium
    leaves the profile 'locked' and the next launch shows a restore banner."""
    if session is not None:
        try:
            session.call("Browser.close", timeout=5)
        except Exception:  # noqa: BLE001
            pass
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass
    if proc is None:
        return
    end = clock() + 5.0
    while clock() < end and _alive(proc):
        sleep(0.1)
    if _alive(proc):
        for meth in ("terminate", "kill"):
            fn = getattr(proc, meth, None)
            if fn is None:
                continue
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
            end = clock() + 3.0
            while clock() < end and _alive(proc):
                sleep(0.1)
            if not _alive(proc):
                break


def describe() -> str:
    """One line for the tray/diagnostics: which browser this machine would use."""
    b = find_browser()
    if b is None:
        return "no Chromium browser found (Edge/Chrome/Brave); the cookies.txt path is the fallback"
    return f"{b.name} at {b.path} ({platform.system()})"


__all__ = ["Browser", "Outcome", "find_browser", "run", "netscape_text", "signed_in", "relevant",
           "launch_args", "encode_frame", "decode_frame", "WebSocket", "CdpSession", "describe"]
