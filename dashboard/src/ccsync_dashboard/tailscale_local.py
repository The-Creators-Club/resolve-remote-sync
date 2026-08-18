"""Read-only client for the Tailscale sidecar's LocalAPI over its unix socket
(ZERO_TOUCH_PLAN.md WP B / section 3.1, spike S1 2026-08-17).

Spike S1 measured exactly this from a SECOND container sharing the socket
volume: a `http.client.HTTPConnection` whose `connect()` opens `AF_UNIX`
reaches `GET /localapi/v0/status` with no `Sec-Tailscale` or other header,
and the answer carries `BackendState`, `AuthURL`, `TailscaleIPs` and
`Self.DNSName` -- which is everything the wizard's "Connect to your tailnet"
step needs to say something true. No new dependency: stdlib only.

READ ONLY on purpose. The login drive (`PATCH /prefs` ->
`POST /login-interactive`) and the Serve config (`POST /serve-config`) are WP
B's own work and land here when that package does; a setup CHECK must not
mutate the node it is describing.

Every function returns `None` rather than raising: the socket is absent on
every deployment that has no sidecar (all of them today), absent on a dev
checkout, and absent on Windows, where `socket.AF_UNIX` does not exist at
all -- none of which is an error worth a traceback in a status check.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import socket
from pathlib import Path
from typing import Any, Mapping

log = logging.getLogger("ccsync.dashboard.tailscale_local")

# Where the sidecar puts it (compose.appliance.yaml's `tsd-sock` volume, and
# tailscaled's own default). TS_SOCKET overrides, same env var the plan and
# the spike's compose both use.
DEFAULT_SOCKET = "/var/run/tailscale/tailscaled.sock"

# What the real `tailscale` CLI sends as Host over the unix socket. Not
# required by the daemon (S1 got a 200 without it) but sent anyway, because
# a future tailscaled that DOES check it would otherwise 403 us.
LOCALAPI_HOST = "local-tailscaled.sock"

# A local unix socket either answers at once or is not there. This is a
# status check on a page an admin is watching, so it never waits.
TIMEOUT = 2.0

_MAX_BODY = 1 << 20


def socket_path(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return (env.get("TS_SOCKET") or "").strip() or DEFAULT_SOCKET


def socket_present(env: Mapping[str, str] | None = None) -> bool:
    """Whether there is anything to talk to. Callers check this FIRST: "no
    sidecar in this deployment" is the normal case and must not cost a
    connect() attempt, a log line or an exception."""
    if not hasattr(socket, "AF_UNIX"):      # Windows dev box; no sidecar there either
        return False
    try:
        return Path(socket_path(env)).exists()
    except OSError:
        return False


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float = TIMEOUT) -> None:
        super().__init__(LOCALAPI_HOST, timeout=timeout)
        self._unix_path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)  # type: ignore[attr-defined]
        sock.settimeout(self.timeout)
        sock.connect(self._unix_path)
        self.sock = sock


def get(path: str, *, env: Mapping[str, str] | None = None,
        timeout: float = TIMEOUT) -> dict[str, Any] | None:
    """GET a LocalAPI route and decode its JSON, or None for any reason at
    all (no socket, refused, non-200, unparseable)."""
    if not socket_present(env):
        return None
    conn = _UnixHTTPConnection(socket_path(env), timeout=timeout)
    try:
        conn.request("GET", path, headers={"Host": LOCALAPI_HOST})
        resp = conn.getresponse()
        body = resp.read(_MAX_BODY)
        if resp.status != 200:
            log.debug("tailscale LocalAPI %s answered HTTP %s", path, resp.status)
            return None
        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else None
    except (OSError, ValueError) as exc:
        log.debug("tailscale LocalAPI %s: %s", path, exc)
        return None
    finally:
        try:
            conn.close()
        except OSError:
            pass


def status(env: Mapping[str, str] | None = None,
           timeout: float = TIMEOUT) -> dict[str, Any] | None:
    return get("/localapi/v0/status", env=env, timeout=timeout)


def summarise(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """The four fields the wizard cares about, flattened. Kept separate from
    `status()` so a test can exercise the shape handling without a socket."""
    if not isinstance(raw, dict):
        return None
    self_node = raw.get("Self") if isinstance(raw.get("Self"), dict) else {}
    ips = raw.get("TailscaleIPs")
    return {
        "backend_state": str(raw.get("BackendState") or ""),
        "auth_url": str(raw.get("AuthURL") or ""),
        "dns_name": str((self_node or {}).get("DNSName") or "").rstrip("."),
        "ips": [str(ip) for ip in ips] if isinstance(ips, list) else [],
    }
