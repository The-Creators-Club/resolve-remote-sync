"""Timeline Cards' `BaseHTTPRequestHandler` as a WSGI application.

docs/TIMELINE-CARDS-INTO-CCSYNC.md §3.2 problem 1, decided in phase 3: keep
the ~70 hand-dispatched routes BYTE FOR BYTE and put a shim under them,
rather than rewriting them as an `APIRouter`. `handler.make_handler` is 1 000
lines of dispatch with its own Range, ETag/If-Range and gzip code that a
browser has been seeking video through for weeks; a rewrite would be a
translation of every one of them with no test on this side to catch a
mistranslation, and the page's goldens live in the other repo.

So: this module turns one handler class into one WSGI callable, and
`a2wsgi.WSGIMiddleware` turns that into the ASGI app `cards.py` mounts. The
whole shim is the three classes below.

**IT STREAMS, AND THAT IS THE POINT.** `/audio` and `/video` serve whole
media files with byte ranges -- a 480p proxy of an hour-long interview is
hundreds of megabytes -- so the response is NOT buffered. The handler writes
into `_Writer`, which parses the status line and headers out of the first
bytes, calls `start_response` once, and hands every later chunk to the WSGI
`write()` callable. a2wsgi's `write()` puts each chunk on an asyncio queue of
ten and blocks until the event loop has taken it, so a browser that reads
slowly slows the handler's `wfile.write` loop rather than filling this
container's memory. That is the same backpressure the real socket gave it.

Three smaller decisions, each with its reason:

  * **The handler is built with `__new__`, not called.** `socketserver`'s
    `__init__` is `setup(); handle(); finish()` around a real socket, and
    `handle()` loops on keep-alive. There is no socket here and exactly one
    request per call, so the attributes are set directly and
    `handle_one_request()` is called once. Nothing in `handler.py` reads
    anything else off `self` except `client_address`, `headers`, `rfile`,
    `wfile`, `path` and `server`.
  * **`Date` and `Server` are dropped.** `send_response` emits both, and
    uvicorn emits both again: two `Date` headers is a malformed response, and
    the one a proxy believes is undefined.
  * **A handler that writes nothing answers 502**, not a hung request. It
    cannot happen today (every route ends in `_send` or `_serve_range`), and
    "cannot happen" is exactly what a shim should still have an answer for.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import threading
from typing import Any, Callable, Iterable

log = logging.getLogger("ccsync.dashboard.cards")

# Headers this side must not repeat: uvicorn writes its own, and hop-by-hop
# headers describe a connection the handler does not have.
_DROP_HEADERS = frozenset({
    "date", "server", "connection", "keep-alive", "transfer-encoding",
    "upgrade", "proxy-authenticate", "proxy-authorization",
})
# The request line + headers the handler parses. Bounded because
# `handle_one_request` bounds its own readline at 65 536 and a header block
# larger than this is not a request anybody made on purpose.
MAX_REQUEST_HEAD_BYTES = 64 * 1024

# THE BROWSER THAT WENT AWAY (audit dash-mounts-1, 2026-11-11).
#
# Behind uvicorn a `send` after the client has disconnected returns silently
# (ASGI spec 2.3), so the handler's `except (ConnectionError, OSError)`, which
# is how the standalone server has always stopped a media stream nobody is
# reading, never fired here. Every response ran to its last byte: a `<video>`
# seek aborts its request and opens `bytes=N-`, and each abort then cost the
# REST of an hour-long proxy read off the vault into nothing, on one of the
# engine's 24 workers, for seconds. A few seconds of scrubbing filled the pool
# and the page's own polls queued behind dead streams. Measured: a client that
# read 256 KiB of a 200 MB answer and closed left the producer producing all
# 200 MB; with this listener it stopped at 0.4 MiB.
#
# `DisconnectAware` watches `receive()` for `http.disconnect` and sets an
# event; the event rides a ContextVar into the WSGI thread (a2wsgi runs the
# app inside `contextvars.copy_context()`), where `_Writer.write` raises
# BrokenPipeError once it is set: the very exception the handler already
# expects from a closed socket. GET and HEAD only: a request with a body has
# other readers of `receive` (app.body_size_gate replays a buffered POST body
# as a `receive` that answers `http.request` for ever), and nothing a POST
# returns here is big enough to matter.
_CLIENT_GONE: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "ccsync_cards_client_gone", default=None)
# A `receive` that keeps answering something other than a disconnect without
# ever waiting is not one this listener can use; it stops asking after this
# many, rather than spin.
_MAX_STRAY_MESSAGES = 16


async def watch_for_disconnect(receive: Callable, on_gone: Callable[[], None],
                               forward: Any = None) -> None:
    """Read `receive()` until `http.disconnect`, then call `on_gone()`.

    Anything else it reads (a GET that does carry a body) is put on `forward`
    (an asyncio.Queue) for the application, so no message is swallowed. Never
    raises, and gives up quietly on a `receive` it cannot use: not hearing a
    disconnect is exactly how things were before, never worse."""
    stray = 0
    try:
        while True:
            message = await receive()
            if forward is not None:
                forward.put_nowait(message)
            if isinstance(message, dict) and message.get("type") == "http.disconnect":
                on_gone()
                return
            stray += 1
            if stray >= _MAX_STRAY_MESSAGES:
                return
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - e.g. BaseHTTPMiddleware's "Unexpected message received"
        log.debug("the disconnect listener stopped", exc_info=True)


class DisconnectAware:
    """ASGI wrapper for the a2wsgi-mounted handler: see _CLIENT_GONE."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http" or scope.get("method") not in ("GET", "HEAD"):
            await self.app(scope, receive, send)
            return
        gone = threading.Event()
        inbox: asyncio.Queue = asyncio.Queue()
        listener = asyncio.ensure_future(watch_for_disconnect(receive, gone.set, inbox))
        token = _CLIENT_GONE.set(gone)
        try:
            await self.app(scope, inbox.get, send)
        finally:
            _CLIENT_GONE.reset(token)
            listener.cancel()


def _json_string(text: str) -> str:
    return json.dumps(str(text))


class _Reader:
    """The handler's `rfile`: the synthesised request head, then the body.

    `handle_one_request` reads the request line with `readline(65537)` and
    `parse_request` reads the header block line by line off the same file,
    so the head has to be a real byte stream rather than a parsed dict. The
    BODY is the WSGI input, untouched and unbuffered -- a POST here is a JSON
    edit, but the size ceiling is app.py's and not this module's to guess.
    """

    def __init__(self, head: bytes, body: Any) -> None:
        self._head = head
        self._at = 0
        self._body = body

    def _head_left(self) -> int:
        return len(self._head) - self._at

    def readline(self, limit: int = -1) -> bytes:
        if self._head_left() > 0:
            end = self._head.find(b"\n", self._at)
            end = len(self._head) if end < 0 else end + 1
            if limit is not None and limit >= 0:
                end = min(end, self._at + limit)
            out = self._head[self._at:end]
            self._at = end
            return out
        if self._body is None:
            return b""
        return self._body.readline() if limit is None or limit < 0 else self._body.readline(limit)

    def read(self, size: int = -1) -> bytes:
        out = b""
        if self._head_left() > 0:
            take = self._head_left() if size is None or size < 0 else min(size, self._head_left())
            out = self._head[self._at:self._at + take]
            self._at += take
            if size is not None and size >= 0:
                size -= take
                if size == 0:
                    return out
        if self._body is None:
            return out
        return out + (self._body.read() if size is None or size < 0 else self._body.read(size))


class _Writer:
    """The handler's `wfile`. Parses the head, then streams.

    One buffer until `\\r\\n\\r\\n`, because `send_response`/`send_header`
    accumulate into `_headers_buffer` and `end_headers` writes the whole head
    in one call -- but only today, and a shim that assumed it would be one
    call would break silently the day it is two.
    """

    def __init__(self, start_response: Callable, gone: Any = None) -> None:
        self._start_response = start_response
        self._write: Callable[[bytes], Any] | None = None
        self._head = bytearray()
        self.started = False
        self.status = 0
        # a threading.Event set when the browser has gone, or None (see
        # _CLIENT_GONE): every write after that is the closed socket's error
        self._gone = gone

    def client_gone(self) -> bool:
        return self._gone is not None and self._gone.is_set()

    # -- the file-like surface handler.py uses -----------------------------

    def write(self, data: bytes) -> int:
        if not data:
            return 0
        if self.client_gone():
            raise BrokenPipeError("the browser went away")
        if self.started:
            self._write(bytes(data))          # type: ignore[misc]
            return len(data)
        self._head.extend(data)
        cut = self._head.find(b"\r\n\r\n")
        if cut < 0:
            if len(self._head) > MAX_REQUEST_HEAD_BYTES:
                raise ValueError("the Timeline Cards handler wrote a response "
                                 "head with no end to it")
            return len(data)
        head, rest = bytes(self._head[:cut]), bytes(self._head[cut + 4:])
        self._begin(head)
        if rest:
            self._write(rest)                 # type: ignore[misc]
        return len(data)

    def flush(self) -> None:
        return None

    # -- and the half only this module calls -------------------------------

    def _begin(self, head: bytes) -> None:
        lines = head.split(b"\r\n")
        status_line = lines[0].decode("latin-1")
        parts = status_line.split(" ", 2)
        self.status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 500
        reason = parts[2] if len(parts) > 2 else ""
        headers = []
        for raw in lines[1:]:
            if not raw:
                continue
            name, sep, value = raw.decode("latin-1").partition(":")
            if not sep:
                continue
            if name.strip().lower() in _DROP_HEADERS:
                continue
            headers.append((name.strip(), value.strip()))
        self.started = True
        self._write = self._start_response(f"{self.status} {reason}".strip(), headers)

    def fallback(self, status: str, message: str) -> None:
        """An answer for a handler that produced none. Silent once the head
        has gone out: at that point the status is already on the wire and the
        only honest thing left is to stop writing."""
        if self.started:
            return
        body = ('{"error": %s}' % _json_string(message)).encode("utf-8")
        self.status = int(status.split(" ", 1)[0])
        self._write = self._start_response(
            status,
            [("Content-Type", "application/json; charset=utf-8"),
             ("Content-Length", str(len(body)))])
        self.started = True
        self._write(body)


def request_head(environ: dict) -> bytes:
    """The request line and headers, as the handler expects to read them.

    PATH_INFO, not the ASGI path: a2wsgi has already stripped the mount
    prefix, which is the whole reason the handler can keep its absolute
    `/api/...` dispatch under `/cards/`.
    """
    method = str(environ.get("REQUEST_METHOD") or "GET")
    path = str(environ.get("PATH_INFO") or "/") or "/"
    query = str(environ.get("QUERY_STRING") or "")
    target = path + (("?" + query) if query else "")
    # HTTP/1.0: one request per call, no keep-alive to negotiate, and no
    # chance of the handler deciding to answer chunked.
    out = [f"{method} {target} HTTP/1.0"]
    for key, value in environ.items():
        if key == "CONTENT_TYPE":
            out.append(f"Content-Type: {value}")
        elif key == "CONTENT_LENGTH":
            out.append(f"Content-Length: {value}")
        elif key.startswith("HTTP_"):
            name = key[5:].replace("_", "-").title()
            if name.lower() in _DROP_HEADERS:
                continue
            out.append(f"{name}: {value}")
    return ("\r\n".join(out) + "\r\n\r\n").encode("latin-1", "replace")


def handler_wsgi(handler_cls: type, server: Any = None) -> Callable:
    """One `make_handler()` class -> one WSGI application.

    `server` is what the handler's `self.server` is: the mount passes an
    object whose `shutdown()` refuses, because `/api/restart` in this process
    would restart the DASHBOARD (see cards.CardsGate, which blocks the route
    before it can get here -- this is the second lock on that door).
    """

    def app(environ: dict, start_response: Callable) -> Iterable[bytes]:
        writer = _Writer(start_response, _CLIENT_GONE.get())
        handler = handler_cls.__new__(handler_cls)
        handler.rfile = _Reader(request_head(environ), environ.get("wsgi.input"))
        handler.wfile = writer
        handler.connection = None
        handler.client_address = (str(environ.get("REMOTE_ADDR") or ""),
                                  int(environ.get("REMOTE_PORT") or 0))
        handler.server = server
        handler.close_connection = True
        handler.requestline = ""
        handler.request_version = "HTTP/1.0"
        handler.command = ""
        try:
            handler.handle_one_request()
        except OSError:
            if writer.client_gone():
                # the browser left and a route that does not catch its own
                # write errors let this one out: a closed tab, not a crash
                log.debug("the browser went away during %s %s",
                          environ.get("REQUEST_METHOD"), environ.get("PATH_INFO"))
                return ()
            log.exception("the Timeline Cards handler raised on %s %s",
                          environ.get("REQUEST_METHOD"), environ.get("PATH_INFO"))
            writer.fallback("500 Internal Server Error",
                            "the Timeline Cards handler raised; see the "
                            "dashboard log")
        except Exception:  # noqa: BLE001 - a route's crash is a 500, not a dead mount
            log.exception("the Timeline Cards handler raised on %s %s",
                          environ.get("REQUEST_METHOD"), environ.get("PATH_INFO"))
            writer.fallback("500 Internal Server Error",
                            "the Timeline Cards handler raised; see the "
                            "dashboard log")
        else:
            # It cannot happen -- every route ends in `_send` or
            # `_serve_range` -- and "cannot happen" still needs an answer, or
            # the browser waits for a response nobody is going to write.
            writer.fallback("502 Bad Gateway",
                            "the Timeline Cards handler answered nothing")
        return ()

    return app
