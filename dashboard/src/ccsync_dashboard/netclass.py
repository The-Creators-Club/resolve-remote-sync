"""How a companion's report reached this dashboard (LG-4, `report_via`).

docs/LEGAL_GAP_FEATURES_PLAN.md section 4.4, 2026-09-25. PRIVACY section 10
and TELEMETRY "Transport" say the dashboard records, per computer, whether its
last report arrived over https, plain http on a private network, or plain http
from the public internet (`machine_state.report_via`), and G2b raises one
alert on the last of those. This is RECORD, NOT NAG: no middleware, no notice,
and a write only when the value changes (db.set_machine_report_via).

THE TABLE IS THE COMPANION'S. `companion/src/ccsync_companion/transport.py`
(`classify`) decides what the companion refuses to send to; this module is a
port of it, not an import, because the dashboard image carries no companion
package. `tests/test_report_via.py` loads the companion's module by path and
pins the two equal on the companion's own table, including its review-round
rules (2026-09-25): an IP literal is judged before the single-label rule, a
dotless all-digit/hex/octal label is an IPv4 address in inet_aton's
shorthand, reserved names are local without a lookup, and a NAME is public
only when every address it resolves to is globally routable. Change one,
change both.

Two differences, both deliberate:
- `loopback` is recorded as `http_local`: `report_via` has three values
  (db.REPORT_VIA_VALUES), and a companion on the dashboard's own host is on
  the studio's network in every sense the Settings line cares about.
- A resolved name is cached for 300 s, not 30 s. The companion's TTL is short
  because a stale "local" there would SEND a password in cleartext after a
  network change; here a stale answer only mislabels one row of a record, and
  every lookup runs inside a report (plan 4.4: no per-request cost). The
  resolution is the dashboard host's, of the Host header the companion sent,
  so a split-horizon name reads as the dashboard's own DNS sees it.

Never raises: a report must never fail because its transport could not be
named. Anything unclassifiable is None, and None is never written.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import threading
import time
import urllib.parse
from typing import Any, Callable, Optional

HTTPS = "https"
LOOPBACK = "loopback"
HTTP_LOCAL = "http_local"
HTTP_PUBLIC = "http_public"
INVALID = "invalid"

LOCAL_SUFFIXES = (".ts.net", ".local", ".lan", ".internal", ".home.arpa")
RESERVED_SUFFIXES = (".test", ".example", ".invalid", ".localhost")
RESERVED_DOMAINS = ("example.com", "example.net", "example.org")
CGNAT = ipaddress.ip_network("100.64.0.0/10")

RESOLVE_TTL_SECONDS = 300.0

# G2a review round, point 3 (2026-09-25): the Host header is the client's
# choice, so every new value was a fresh getaddrinfo with no timeout on the
# report path, and the cache grew without limit. A lookup now gets
# RESOLVE_TIMEOUT_SECONDS on a worker thread and at most RESOLVE_MAX_INFLIGHT
# run at once; a lookup that does not answer in time, or cannot start, is
# doubt, and doubt is `http_local` (the same verdict a failed lookup gets).
# The cache holds RESOLVE_CACHE_MAX names, expired entries going first.
RESOLVE_TIMEOUT_SECONDS = 1.0
RESOLVE_MAX_INFLIGHT = 4
RESOLVE_CACHE_MAX = 256

_cache: dict[str, tuple[float, str]] = {}
_cache_lock = threading.Lock()
_inflight = threading.BoundedSemaphore(RESOLVE_MAX_INFLIGHT)


def _default_resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [str(info[4][0]) for info in infos]


# Swappable for tests, exactly as transport.resolve is.
resolve: Callable[[str], list[str]] = _default_resolve


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _normalise_host(host: object) -> str:
    text = str(host or "").strip().lower().split("%")[0]
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text.rstrip(".")


def _ip(host: str) -> Optional[ipaddress._BaseAddress]:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    mapped = getattr(ip, "ipv4_mapped", None)
    return mapped if mapped is not None else ip


_NUMERIC_LABEL = re.compile(r"^(0x[0-9a-f]+|0[0-7]*|[1-9][0-9]*)$")


def _single_label_ipv4(host: str) -> Optional[ipaddress.IPv4Address]:
    if not _NUMERIC_LABEL.match(host):
        return None
    if host.startswith("0x"):
        value = int(host, 16)
    elif host.startswith("0") and len(host) > 1:
        value = int(host, 8)
    else:
        value = int(host, 10)
    if value > 0xFFFFFFFF:
        return None
    return ipaddress.IPv4Address(value)


def _ip_is_local(ip: ipaddress._BaseAddress) -> bool:
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    return ip.version == 4 and ip in CGNAT


def _ip_is_public(ip: ipaddress._BaseAddress) -> bool:
    return bool(ip.is_global) and not ip.is_multicast


def host_is_local(host: str) -> bool:
    """transport.host_is_local, by shape alone (no lookup)."""
    try:
        host = _normalise_host(host)
        if not host:
            return False
        ip = _ip(host)
        if ip is not None:
            return _ip_is_local(ip)
        numeric = _single_label_ipv4(host)
        if numeric is not None:
            return _ip_is_local(numeric)
        if host == "localhost" or "." not in host:
            return True
        return host.endswith(LOCAL_SUFFIXES)
    except Exception:  # noqa: BLE001 - never raises, as the companion's
        return False


def _is_loopback_host(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    ip = _ip(host)
    return ip is not None and ip.is_loopback


def _is_reserved_name(host: str) -> bool:
    if host.endswith(RESERVED_SUFFIXES):
        return True
    return any(host == d or host.endswith("." + d) for d in RESERVED_DOMAINS)


def _bounded_resolve(host: str) -> Optional[list[str]]:
    """`resolve(host)` with a deadline, or None when it could not answer in
    time or no lookup slot was free. The worker is a daemon: a resolver that
    hangs keeps its thread, never the report, and the semaphore stops a stream
    of new Host values from piling threads up behind it."""
    if not _inflight.acquire(blocking=False):
        return None
    box: dict[str, Any] = {}

    def work() -> None:
        try:
            box["addresses"] = list(resolve(host) or [])
        except Exception:  # noqa: BLE001 - a failed lookup is doubt
            box["addresses"] = []
        finally:
            _inflight.release()

    try:
        worker = threading.Thread(target=work, name="netclass-resolve", daemon=True)
        worker.start()
    except Exception:  # noqa: BLE001 - no thread: the slot goes back, verdict is doubt
        _inflight.release()
        return None
    worker.join(RESOLVE_TIMEOUT_SECONDS)
    return None if worker.is_alive() else box.get("addresses")


def _cache_put(host: str, expires: float, result: str, now: float) -> None:
    with _cache_lock:
        if host not in _cache and len(_cache) >= RESOLVE_CACHE_MAX:
            for key in [k for k, (exp, _r) in _cache.items() if exp <= now]:
                _cache.pop(key, None)
            while len(_cache) >= RESOLVE_CACHE_MAX:
                _cache.pop(min(_cache, key=lambda k: _cache[k][0]), None)
        _cache[host] = (expires, result)


def _classify_name_by_dns(host: str) -> str:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(host)
        if hit is not None and hit[0] > now:
            return hit[1]
    addresses = _bounded_resolve(host)
    if addresses is None:
        # Timed out or no slot: not cached, so a slow resolver is asked again
        # next time rather than labelled for five minutes.
        return HTTP_LOCAL
    ips = [ip for ip in (_ip(_normalise_host(a)) for a in addresses) if ip is not None]
    result = HTTP_PUBLIC if ips and all(_ip_is_public(ip) for ip in ips) else HTTP_LOCAL
    _cache_put(host, now + RESOLVE_TTL_SECONDS, result, now)
    return result


def classify(url: object) -> str:
    """transport.classify, ported: "https" | "loopback" | "http_local" |
    "http_public" | "invalid". Never raises."""
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
        scheme = (parsed.scheme or "").lower()
        host = _normalise_host(parsed.hostname)
        if scheme not in ("http", "https") or not host:
            return INVALID
        if scheme == "https":
            return HTTPS
        if _is_loopback_host(host):
            return LOOPBACK
        numeric = _single_label_ipv4(host)
        if numeric is not None:
            return HTTP_PUBLIC if _ip_is_public(numeric) else HTTP_LOCAL
        if host_is_local(host) or _is_reserved_name(host):
            return HTTP_LOCAL
        ip = _ip(host)
        if ip is not None:
            return HTTP_PUBLIC if _ip_is_public(ip) else HTTP_LOCAL
        return _classify_name_by_dns(host)
    except Exception:  # noqa: BLE001
        return INVALID


def report_via(scheme: object, host_header: object) -> Optional[str]:
    """'https' | 'http_local' | 'http_public' for one arrived report, or None
    when it cannot be said (no Host header, a scheme that is neither).

    `scheme` must already be the TRUSTED scheme (see request_report_via):
    an X-Forwarded-Proto from a peer nobody configured is not evidence."""
    try:
        scheme_text = str(scheme or "").strip().lower()
        host = str(host_header or "").strip()
        if scheme_text == "https":
            return HTTPS
        if scheme_text != "http" or not host or any(c in host for c in "/?#@ "):
            return None
        verdict = classify(f"http://{host}")
        if verdict in (LOOPBACK, HTTP_LOCAL):
            return HTTP_LOCAL
        if verdict == HTTP_PUBLIC:
            return HTTP_PUBLIC
        return None
    except Exception:  # noqa: BLE001
        return None


def request_report_via(settings: Any, request: Any) -> Optional[str]:
    """`report_via` for a Starlette request. The scheme is X-Forwarded-Proto
    ONLY from `auth.trusted_proxy` (plan 4.4, safety M7), otherwise the
    socket's own; the host is the Host header the companion sent. Never
    raises."""
    try:
        from . import auth  # local: auth imports half the package

        scheme = str(getattr(getattr(request, "url", None), "scheme", "") or "").lower()
        peer = getattr(getattr(request, "client", None), "host", "") or ""
        if scheme != "https" and auth.trusted_proxy(settings, peer):
            forwarded = (request.headers.get("x-forwarded-proto") or "")
            forwarded = forwarded.split(",")[0].strip().lower()
            if forwarded in ("http", "https"):
                scheme = forwarded
        return report_via(scheme, request.headers.get("host", ""))
    except Exception:  # noqa: BLE001
        return None
