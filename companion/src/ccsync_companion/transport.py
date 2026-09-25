"""How a dashboard address reaches the dashboard, and the one refusal of it.

LG-4, `refuse-cleartext-dashboard-url` (docs/LEGAL_GAP_FEATURES_PLAN.md
section 4.4, 2026-09-25). PRIVACY section 10 and TELEMETRY "Transport" promise
that the companion sends nothing -- the fleet token, a sign-in password, a
report -- to a dashboard addressed over plain http ON THE PUBLIC INTERNET.
Plain http on the studio network or the tailnet is how the whole live fleet
runs (`http://192.168.0.10:8480`, `http://100.x`), so that stays allowed and
is only ever warned about; "require https for the whole site" is deferred
(Tier 2b) because one tick of it could silence that fleet, and the report
reply is the only way a fix could reach it again.

Two consumers, one table:
- `classify(url)` is what the settings window, the setup wizard and the
  dashboard's parity copy (`dashboard/netclass.py`) agree on.
- `CleartextGuard` is installed in `upgrade.build_no_redirect_opener()`, the
  opener every credentialed dashboard call already goes through, so the
  refusal has exactly one choke point.

THE REFUSAL NEVER FIRES ON DOUBT (safety H3). An address is `http_public`
only on positive evidence: a public IP literal, or a name every one of whose
resolved addresses is public. A name that does not resolve, resolves to
nothing, or resolves to anything private/tailnet (split-horizon DNS) is
`http_local`. A wrong "public" would stop a working fleet; a wrong "local"
leaves today's behaviour in place.

A LEAF MODULE on purpose: no import from this package, because the wizard
(onboarding/) and the dashboard's parity test load it standalone (plan 7.1,
wave 0). Never raises out of `classify` or `host_is_local`.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

HTTPS = "https"
LOOPBACK = "loopback"
HTTP_LOCAL = "http_local"
HTTP_PUBLIC = "http_public"
INVALID = "invalid"

CLASSES = (HTTPS, LOOPBACK, HTTP_LOCAL, HTTP_PUBLIC, INVALID)

# The intranet name shapes a customer's NAS actually answers to. Moved here
# verbatim from upgrade._host_is_local (2026-09-25, LG-4), which is now an
# alias of host_is_local below.
LOCAL_SUFFIXES = (".ts.net", ".local", ".lan", ".internal", ".home.arpa")

# RFC 2606 / RFC 6761 names that can never be somebody's public dashboard.
# Classified without a lookup, so a test fixture's `http://dash.example.com`
# neither touches DNS nor reads as a public host (and so is never refused).
RESERVED_SUFFIXES = (".test", ".example", ".invalid", ".localhost")
RESERVED_DOMAINS = ("example.com", "example.net", "example.org")

CGNAT = ipaddress.ip_network("100.64.0.0/10")

# A resolved name is re-asked after this long. Thirty seconds, for success
# and failure alike (2026-09-25 review round, amending plan 4.4's 600 s): a
# verdict outlives a NETWORK CHANGE. A laptop that cached "local" for
# `dashboard.studio.com` on the studio's split-horizon DNS and then joined
# cafe Wi-Fi (same name, the studio's public port forward) would have sent
# reports, the fleet token and a sign-in password in cleartext for ten
# minutes, while the socket's own getaddrinfo already saw the new address
# (Windows flushes its DNS cache on a network change; this cache is not
# flushed). The OS resolver caches too, so a short TTL costs a local cache
# hit, not a DNS query. The guard's lookup and the connection's lookup are
# still two lookups, so a record that flips between them is a race this
# cannot close; the window is the gap between two calls, not a TTL.
RESOLVE_TTL_SECONDS = 30.0
RESOLVE_FAIL_TTL_SECONDS = 30.0

_cache: dict[str, tuple[float, str]] = {}
_cache_lock = threading.Lock()


def _default_resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [str(info[4][0]) for info in infos]


# Swappable for tests; production is getaddrinfo, the same call the
# connection itself makes a moment later.
resolve: Callable[[str], list[str]] = _default_resolve


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
        _refusal_logged.clear()


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
    """The address a one-label numeric host means to inet_aton, or None.
    Out of range (above 2**32 - 1) is None: no resolver reads it as an
    address, so it stays a name. An octal-looking label with an 8 or 9 in
    it (`09`) does not match and stays a name too."""
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
    """Positive evidence only: `is_global` excludes CGNAT, documentation,
    reserved and unspecified ranges, so none of those can be refused."""
    return bool(ip.is_global) and not ip.is_multicast


def host_is_local(host: str) -> bool:
    """True for a tailnet/LAN/loopback host, by its SHAPE alone (no lookup).

    100.64.0.0/10 is the CGNAT range Tailscale hands out; *.ts.net is a
    MagicDNS name for the same thing. RFC1918 and loopback cover a LAN
    deployment, and so do the intranet name shapes a customer's NAS actually
    answers to: a single-label host (`truenas`, resolved by the search
    domain) and the .local/.lan/.internal/.home.arpa suffixes. Everything
    else -- anything that looks like a name the public DNS could resolve --
    is "the open internet" as far as THIS check is concerned; `classify`
    then asks DNS before calling it public. The updater (`upgrade.transport_ok`)
    still uses this shape-only answer, deliberately stricter: it refuses to
    pull a binary over cleartext from any name it cannot vouch for."""
    try:
        host = _normalise_host(host)
        if not host:
            return False
        # IP literal FIRST (2026-09-25, found writing LG-4's table): an IPv6
        # literal has no dot, so the single-label rule below used to call
        # `2001:4860::8888` an intranet name and the updater allowed plain
        # http to it.
        ip = _ip(host)
        if ip is not None:
            return _ip_is_local(ip)
        # A dotless all-digit/hex/octal label is an IPv4 address in
        # inet_aton's shorthand, not an intranet name (2026-09-25 review
        # round): `134744072` and `0x08080808` are 8.8.8.8 to getaddrinfo on
        # macOS and Linux, so the single-label rule below would have let
        # plain http go to a public address. Parsed here rather than by
        # socket.inet_aton so every platform (and the dashboard's parity
        # copy) gets one answer.
        numeric = _single_label_ipv4(host)
        if numeric is not None:
            return _ip_is_local(numeric)
        if host == "localhost" or "." not in host:
            return True
        return host.endswith(LOCAL_SUFFIXES)
    except Exception:
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


def _classify_name_by_dns(host: str) -> str:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(host)
        if hit is not None and hit[0] > now:
            return hit[1]
    try:
        addresses = list(resolve(host) or [])
    except Exception:
        addresses = []
    ips = [ip for ip in (_ip(_normalise_host(a)) for a in addresses) if ip is not None]
    if ips and all(_ip_is_public(ip) for ip in ips):
        result, ttl = HTTP_PUBLIC, RESOLVE_TTL_SECONDS
    elif ips:
        result, ttl = HTTP_LOCAL, RESOLVE_TTL_SECONDS
    else:
        result, ttl = HTTP_LOCAL, RESOLVE_FAIL_TTL_SECONDS
    with _cache_lock:
        _cache[host] = (now + ttl, result)
    return result


def classify(url: object) -> str:
    """"https" | "loopback" | "http_local" | "http_public" | "invalid".

    `loopback` is plain http to this machine; https to anything is `https`
    (urllib verifies it against the system trust store, and nothing here
    changes that). `invalid` is any other scheme, or no host. Never raises;
    anything unexpected is `invalid`, which nothing refuses on the wire (the
    guard refuses `http_public` only)."""
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
    except Exception:
        return INVALID


class CleartextRefused(urllib.error.URLError):
    """A request to a plain-http address on the public internet, not sent.

    A URLError on purpose: every caller of the shared opener already treats
    a URLError as "the dashboard could not be reached" and keeps its
    never-raise contract, so the refusal lands on the same path as a network
    failure. Callers that want to SAY why (the tray line, G1a) test for this
    class."""

    def __init__(self, url: str) -> None:
        self.url = str(url or "")
        try:
            self.host = urllib.parse.urlparse(self.url).hostname or ""
        except Exception:
            self.host = ""
        super().__init__(
            f"not sent: {self.host or self.url} is plain http on the public "
            f"internet; use the dashboard's https address")


# The ticket id lives in the log, never in the exception's reason
# (2026-09-25 review round): reporter, site, selection and jobs turn a
# URLError into str(exc) for the tray and the grid, and "(LG-4)" is not
# something an editor can act on. Once per host per ten minutes, because a
# refused report retries every few seconds.
log = logging.getLogger("ccsync.transport")
_REFUSAL_LOG_EVERY_SECONDS = 600.0
_refusal_logged: dict[str, float] = {}


def _log_refusal(host: str) -> None:
    try:
        now = time.monotonic()
        with _cache_lock:
            last = _refusal_logged.get(host)
            if last is not None and now - last < _REFUSAL_LOG_EVERY_SECONDS:
                return
            _refusal_logged[host] = now
        log.warning("LG-4: refused plain http to public address %s; "
                    "nothing was sent", host)
    except Exception:
        pass


class CleartextGuard(urllib.request.BaseHandler):
    """Refuses, before any byte is written, a plain-http request whose
    address classifies as `http_public`. https, loopback and LAN/tailnet
    http pass untouched, so the live fleet cannot be affected.

    Early in the chain (the default order is 500) so a request processor
    added later cannot have already acted on a request this refuses."""

    handler_order = 100

    def http_request(self, req):  # noqa: D102 - urllib's pre-processor hook
        url = req.get_full_url()
        if classify(url) == HTTP_PUBLIC:
            refused = CleartextRefused(url)
            _log_refusal(refused.host or refused.url)
            raise refused
        return req


def is_refused(url: object) -> bool:
    """True when the guard would refuse this address. Never raises."""
    return classify(url) == HTTP_PUBLIC
