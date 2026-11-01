"""Publish the appliance dashboard on the tailnet, and keep it published
(CR-363, GL-04 and GL-09, 2026-10-07; PRAC-4, bug-server-2, PL-RES-05).

THE GAP THIS CLOSES. compose.appliance.yaml binds the dashboard to the NAS's
own loopback (127.0.0.1:8480) and says the tailnet node's Serve config is what
editors reach. Nothing ever wrote that Serve config: `tailscale_local.py` is
read-only by design, `deploy/tailscale/serve.json` is read only by containerboot
(which the appliance deliberately does not run, spike S1b), and the wizard's
tailnet task turned GREEN the moment the node was `Running`. So a new
customer's admin could not open the wizard without an SSH tunnel, no editor
could reach the dashboard at all, and the checklist said it was done.

WHAT IS HERE. One module for everything that WRITES to the node (the read side
stays in `tailscale_local`):

* `apply_serve` / `publish`: POST the Serve config over the LocalAPI socket the
  dashboard already shares with the sidecar, and (only when the site has none
  yet) record the https name as `dashboard_url`.
* `tick`: the WATCHDOG, called once per collector cycle. Tailscale's own Serve
  config survives a restart of tailscaled but not a wiped state dir or a node
  that was removed and re-added, and nobody notices until editors cannot reach
  the server. A Running node with no Serve for this dashboard is repaired, and
  the repair is logged and counted.
* `snapshot`: what the self-diagnosis alerts read (BackendState, the node's
  key expiry, whether Serve is in place). Day 180 of a default Tailscale
  install is the whole fleet going silent at once, with one "computer has gone
  quiet" mail per machine a day later naming nothing; reading `Self.KeyExpiry`
  14 days ahead is the cheap half of that fix.

WRITE ACCESS IS PER PEER UID (CR-363 round 2, GL-04, 2026-10-07). Spike S1c is
cited elsewhere as proof the dashboard can write to the node; it ran its client
as ROOT and proves only READS for another uid. tailscaled grants a LocalAPI
connection write access only to uid 0, its own non-root uid, the operator or a
local admin; anything else gets 403 "serve config denied". So compose.appliance
.yaml runs tailscaled as the dashboard's own ${APP_UID}:${APP_GID}. Live proof
("LocalAPI write as APP_UID") is on the GL-60 checklist.

NEVER FATAL, NEVER A CONNECT STORM. Every function returns a value instead of
raising, nothing here dials out (a unix socket on this container only), and
`tick` is rate limited so a collector running every few seconds cannot hammer
tailscaled. On a deployment with no sidecar (a TrueNAS install published some
other way, a dev checkout, Windows) the socket is absent and every function is
a quiet no-op: "no bundled node" is the normal case, not a fault.
"""
from __future__ import annotations

import datetime as dt
import http.client
import json
import logging
import os
import re
import socket
import threading
import time
from typing import Any, Mapping

from . import tailscale_local

log = logging.getLogger("ccsync.dashboard.tailnet_serve")

SERVE_PATH = "/localapi/v0/serve-config"

# The dashboard as the tailscale container sees it on the compose network.
# Overridable for a stack that names its services differently; the compose
# default network resolves service names, which is why serve.json already says
# `dashboard`.
DEFAULT_BACKEND = "http://dashboard:8480"

# How often the watchdog may touch tailscaled. A repair that fails (Serve not
# enabled on the tailnet) is retried at this pace, not every collector wake.
TICK_SECONDS = 60.0

# How far ahead of a node key's expiry the alert starts. Two weeks is enough to
# find the admin console; Tailscale's own default key lifetime is 180 days.
KEY_EXPIRY_WARN_DAYS = 14

_TIMEOUT = 3.0
_lock = threading.Lock()
_last_tick = 0.0
# What the last repair attempt did, for the setup task and the alert text.
_last_repair: dict[str, Any] = {}


def backend_url(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return (env.get("DASH_SERVE_BACKEND") or "").strip().rstrip("/") or DEFAULT_BACKEND


def build_config(dns_name: str, backend: str | None = None) -> dict[str, Any]:
    """The same document `deploy/tailscale/serve.json` carries, with the node's
    own name in place of `${TS_CERT_DOMAIN}` (containerboot expands that; the
    LocalAPI does not)."""
    host = str(dns_name or "").strip().rstrip(".")
    return {
        "TCP": {"443": {"HTTPS": True}},
        "Web": {
            f"{host}:443": {
                "Handlers": {"/": {"Proxy": backend or backend_url()}},
            },
        },
    }


def serve_covers(cfg: Mapping[str, Any] | None, dns_name: str = "") -> bool:
    """Whether a Serve config already publishes SOMETHING over https for this
    node. A config an admin wrote by hand (`tailscale serve --bg http://...`)
    counts: the point is that editors can reach a dashboard, not that the
    document is byte for byte ours, and rewriting an admin's own working
    setup on every cycle would be hostile."""
    if not isinstance(cfg, Mapping):
        return False
    web = cfg.get("Web")
    if not isinstance(web, Mapping):
        return False
    want = f"{str(dns_name or '').strip().rstrip('.')}:443".lower()
    for hostport, entry in web.items():
        if dns_name and str(hostport).lower() != want:
            continue
        handlers = entry.get("Handlers") if isinstance(entry, Mapping) else None
        if isinstance(handlers, Mapping) and any(
                isinstance(h, Mapping) and (h.get("Proxy") or h.get("Path") or h.get("Text"))
                for h in handlers.values()):
            return True
    return False


# ----------------------------------------------------------------- wire

class _Conn(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__(tailscale_local.LOCALAPI_HOST, timeout=timeout)
        self._unix_path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)  # type: ignore[attr-defined]
        sock.settimeout(self.timeout)
        sock.connect(self._unix_path)
        self.sock = sock


def _post_json(path: str, body: dict[str, Any], env: Mapping[str, str] | None = None,
               timeout: float = _TIMEOUT) -> tuple[bool, str]:
    """(ok, why-not). The reason is whatever tailscaled said, trimmed: for
    "Serve is not enabled on your tailnet" it carries the URL that fixes it,
    which is the single most useful sentence this flow can show an admin."""
    if not tailscale_local.socket_present(env):
        return False, "there is no bundled Tailscale node in this deployment"
    payload = json.dumps(body).encode("utf-8")
    conn = _Conn(tailscale_local.socket_path(env), timeout)
    try:
        conn.request("POST", path, body=payload, headers={
            "Host": tailscale_local.LOCALAPI_HOST,
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
        })
        resp = conn.getresponse()
        text = resp.read(1 << 14).decode("utf-8", "replace")
        if 200 <= resp.status < 300:
            return True, ""
        return False, " ".join(text.split())[:300] or f"HTTP {resp.status}"
    except (OSError, ValueError) as exc:
        return False, str(exc)
    finally:
        try:
            conn.close()
        except OSError:
            pass


def read_serve(env: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    """The node's current Serve config. `{}` is an EMPTY config (nothing is
    published); None is "could not ask" and must never read as empty.

    CR-363 / GL-04 overseer fix (2026-10-07): a node with NO Serve config
    answers HTTP 200 with the body `null` (spike S1c recorded exactly that),
    and `tailscale_local.get` maps every non-object body to None, which made
    every fresh appliance read as "could not ask": publish never POSTed and
    the watchdog never repaired. So this reads the raw answer itself and
    tells `200 null` (empty) apart from a refusal or a dead socket (None)."""
    if not tailscale_local.socket_present(env):
        return None
    conn = _Conn(tailscale_local.socket_path(env), _TIMEOUT)
    try:
        conn.request("GET", SERVE_PATH, headers={"Host": tailscale_local.LOCALAPI_HOST})
        resp = conn.getresponse()
        body = resp.read(1 << 20)
        if resp.status != 200:
            return None
        parsed = json.loads(body) if body.strip() else None
        if parsed is None:
            return {}
        return parsed if isinstance(parsed, dict) else None
    except (OSError, ValueError) as exc:
        log.debug("tailscale LocalAPI %s: %s", SERVE_PATH, exc)
        return None
    finally:
        try:
            conn.close()
        except OSError:
            pass


HTTPS_OFF_MESSAGE = (
    "HTTPS is off for your tailnet (open https://login.tailscale.com/admin/dns, press "
    "Enable HTTPS under HTTPS Certificates, then press this again), so no editor could connect")


def https_capable(raw: Mapping[str, Any] | None) -> bool:
    """Whether the tailnet lets this node get certificates. The LocalAPI's
    POST /serve-config does NOT check this (the tailscale CLI does, client
    side), so a default tailnet, where HTTPS is off, accepts the config and
    then serves nothing anybody can open: the green tick with a dashboard
    nobody can reach. /status carries it as a non-empty top-level
    `CertDomains`, or an `https` entry in the node's capabilities."""
    if not isinstance(raw, Mapping):
        return False
    domains = raw.get("CertDomains")
    if isinstance(domains, list) and any(str(d).strip() for d in domains):
        return True
    me = raw.get("Self")
    if isinstance(me, Mapping):
        caps = me.get("Capabilities")
        if isinstance(caps, list) and any("https" == str(c).lower() or str(c).lower().endswith("/cap/https")
                                          for c in caps):
            return True
        capmap = me.get("CapMap")
        if isinstance(capmap, Mapping) and any(
                "https" == str(k).lower() or str(k).lower().endswith("/cap/https") for k in capmap):
            return True
    return False


def node_summary(env: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    raw = tailscale_local.status(env)
    node = tailscale_local.summarise(raw)
    if node is None:
        return None
    node["key_expiry"] = key_expiry(raw)
    node["https"] = https_capable(raw)
    return node


# ------------------------------------------------------------- key expiry

_FRACTION = re.compile(r"(\.\d{6})\d+")


def key_expiry(raw: Mapping[str, Any] | None) -> dt.datetime | None:
    """`Self.KeyExpiry` as an aware datetime, or None for a node whose key does
    not expire (the field is absent, or Go's zero time for a tagged node or one
    with expiry disabled in the admin console)."""
    if not isinstance(raw, Mapping):
        return None
    me = raw.get("Self")
    value = me.get("KeyExpiry") if isinstance(me, Mapping) else None
    if not value or not isinstance(value, str):
        return None
    text = _FRACTION.sub(r"\1", value.strip().replace("Z", "+00:00"))
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return None if when.year < 2000 else when


def days_until(when: dt.datetime | None, now: dt.datetime | None = None) -> float | None:
    if when is None:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    return (when - now).total_seconds() / 86400.0


# --------------------------------------------------------------- the write

def apply_serve(dns_name: str, env: Mapping[str, str] | None = None) -> tuple[bool, str]:
    """POST the Serve config. Only meaningful once the node is Running: before
    that tailscaled answers 500 "netMap is nil" (spike S1c), and the caller is
    expected to have checked."""
    if not str(dns_name or "").strip():
        return False, "the node has no name on the tailnet yet"
    ok, why = _post_json(SERVE_PATH, build_config(dns_name, backend_url(env)), env)
    if ok:
        return True, ""
    low = why.lower()
    if "not enabled" in low or "https" in low and "enable" in low:
        # Serve needs HTTPS certificates enabled for the tailnet, once, in the
        # admin console; tailscaled's own message carries the link.
        return False, ("Tailscale says Serve is not turned on for your tailnet "
                       f"({why}). Open the link in that message once, then press this again")
    return False, why


def publish(conn, settings, env: Mapping[str, str] | None = None) -> tuple[bool, str]:
    """The wizard button and the watchdog's repair, one path: make sure Serve
    publishes this dashboard, then record the https address as the site's
    `dashboard_url` if the site has none. Returns (published, detail).

    `dashboard_url` is written ONLY when blank. A site that already published
    an address (the studio, with its own) keeps it: that value is what every
    companion was told to call, and silently re-pointing a live fleet is the
    one thing this must never do."""
    node = node_summary(env)
    if node is None:
        return False, "the bundled Tailscale node did not answer"
    if node["backend_state"] != "Running":
        return False, f"the node is {node['backend_state'] or 'not signed in'}, not Running"
    name = node["dns_name"]
    if not node.get("https"):
        # Before anything is written or recorded: see https_capable.
        return False, HTTPS_OFF_MESSAGE
    current = read_serve(env)
    if current is None:
        return False, "could not read the node's Serve settings"
    if not serve_covers(current, name):
        ok, why = apply_serve(name, env)
        if not ok:
            return False, why
        log.warning("tailnet: published this dashboard at https://%s through Serve", name)
    _record_dashboard_url(conn, settings, f"https://{name}")
    return True, f"https://{name}"


def _record_dashboard_url(conn, settings, url: str) -> None:
    from . import site_store

    try:
        existing = str(site_store.resolved_manifest(conn, settings).get("dashboard_url") or "")
        if existing:
            return
        site_store.set_many(conn, {"dashboard_url": url}, updated_by="setup:tailnet")
        conn.commit()
    except Exception:                                                  # noqa: BLE001
        # The Serve config is the thing that matters; the stored URL is a
        # convenience for installers, and the admin can type it on Settings.
        log.warning("tailnet: could not record dashboard_url %s", url, exc_info=True)


# ---------------------------------------------------------------- watchdog

def last_repair() -> dict[str, Any]:
    return dict(_last_repair)


def tick(conn, settings, env: Mapping[str, str] | None = None,
         now_monotonic: float | None = None) -> str:
    """One watchdog pass. Returns a short word for the log and the tests:
    "no-node", "skipped", "not-running", "ok", "repaired" or "failed".
    Never raises."""
    global _last_tick
    try:
        if not tailscale_local.socket_present(env):
            return "no-node"
        mono = time.monotonic() if now_monotonic is None else now_monotonic
        with _lock:
            if _last_tick and mono - _last_tick < TICK_SECONDS:
                return "skipped"
            _last_tick = mono
        node = node_summary(env)
        if node is None or node["backend_state"] != "Running" or not node["dns_name"]:
            return "not-running"
        current = read_serve(env)
        if current is None:
            return "failed"
        if serve_covers(current, node["dns_name"]) or serve_covers(current):
            return "ok"
        published, detail = publish(conn, settings, env)
        _last_repair.clear()
        _last_repair.update({"at": time.time(), "ok": published, "detail": detail})
        if published:
            log.warning("tailnet watchdog: Serve was missing and has been put back (%s)", detail)
            return "repaired"
        log.error("tailnet watchdog: Serve is missing and could not be restored: %s", detail)
        return "failed"
    except Exception:                                                  # noqa: BLE001
        log.exception("tailnet watchdog failed; continuing")
        return "failed"


def reset_for_tests() -> None:
    global _last_tick
    _last_tick = 0.0
    _last_repair.clear()


def snapshot(env: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    """What the self-diagnosis reads, or None when this deployment has no
    bundled node (not applicable) or the node could not be asked.

    {"backend_state", "dns_name", "key_expiry" (datetime|None), "serve" (bool|None)}
    where `serve` None means the Serve settings could not be read: a check
    must treat that as NOT CHECKED, never as "missing"."""
    if not tailscale_local.socket_present(env):
        return None
    node = node_summary(env)
    if node is None:
        return {"backend_state": "unreachable", "dns_name": "", "key_expiry": None,
                "serve": None}
    serve: bool | None = None
    if node["backend_state"] == "Running":
        cfg = read_serve(env)
        serve = None if cfg is None else (serve_covers(cfg, node["dns_name"]) or serve_covers(cfg))
    return {"backend_state": node["backend_state"], "dns_name": node["dns_name"],
            "key_expiry": node.get("key_expiry"), "serve": serve}
