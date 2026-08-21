"""Thin client for the server Syncthing REST API.

Same auth pattern as server/common.py:syncthing_api -- X-API-Key header,
plain requests. Any transport or non-2xx failure raises SyncthingError so the
collector can treat "Syncthing is unreachable" as one condition.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import requests

log = logging.getLogger("ccsync.dashboard.syncthing")


def _seg(value: str) -> str:
    """Percent-encode a folder/device ID going into a REST *path* segment.

    Folder ids are project slugs, and slugs come from an editor-writable
    marker file with no charset validation -- a slug containing '/', '?' or
    '#' would otherwise address a different endpoint entirely (silently
    updating the wrong folder, or 404ing forever). See the unquoted REST
    path segments finding."""
    return quote(str(value), safe="")


class SyncthingError(Exception):
    pass


# "dynamic" means "find me via global discovery", which for the NAS resolves
# to its PUBLIC address. HiNet's inbound is blackholed except forwarded high
# ports and nothing forwards 22000 tcp/udp, so Syncthing falls back to the
# public RELAY pool -- typically 1-5 MB/s, shared and rate-limited. That is
# the most likely literal explanation of the ~60 mb/s ceiling (AUDIT_2 P3).
DEFAULT_DEVICE_ADDRESSES = ["dynamic"]


def device_addresses_for(tailnet_ip: str, port: int = 22000) -> list[str]:
    """Address list for a new device entry: tailnet first, `dynamic` LAST.

    Keeping "dynamic" as the final fallback is deliberate -- a wrong or
    stale tailnet IP then degrades to today's behaviour instead of breaking
    the device outright. Syncthing tries all addresses and keeps the first
    that connects.

    NOTE: this only helps if the NAS's 22000 tcp+udp is actually reachable
    on its tailnet IP through the Syncthing app's container NAT
    (host_network: False + published 22000) -- verify before trusting it."""
    ip = (tailnet_ip or "").strip()
    if not ip:
        return list(DEFAULT_DEVICE_ADDRESSES)
    return [f"tcp://{ip}:{port}", f"quic://{ip}:{port}", "dynamic"]


# The global options that would force lane C onto the tailnet. OFF by
# default and deliberately so: with the path to the NAS currently DERP-
# relayed, disabling Syncthing's relays makes lane C STOP rather than
# degrade (AUDIT_2 §4.2's own risk column). Land the diagnostics first,
# confirm a direct path, then flip this.
TAILNET_ONLY_OPTIONS = {
    "relaysEnabled": False,
    "globalAnnounceEnabled": False,
    "natEnabled": False,
    # Kept ON: this is how the base rig and any same-LAN editor find each
    # other without discovery servers.
    "localAnnounceEnabled": True,
}


class SyncthingClient:
    def __init__(
        self,
        gui_url: str,
        api_key: str,
        timeout: float = 10.0,
        session=None,
        device_addresses: list[str] | None = None,
    ):
        self.gui_url = gui_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()
        # Addresses stamped onto newly-created device entries. Defaults to
        # today's ["dynamic"] so an un-wired caller is unchanged.
        self.device_addresses = list(device_addresses or DEFAULT_DEVICE_ADDRESSES)

    @classmethod
    def from_settings(cls, settings, session=None) -> "SyncthingClient":
        """Build a client with the tailnet address preference already wired
        from settings. Construction sites in api.py/collector.py/ui.py are
        owned elsewhere -- switching them to this one line is what turns
        DASH_SYNCTHING_TAILNET_IP on."""
        return cls(
            settings.syncthing_url,
            settings.syncthing_api_key,
            session=session,
            device_addresses=device_addresses_for(
                getattr(settings, "syncthing_tailnet_ip", "") or ""
            ),
        )

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        timeout: float | None = None,
    ) -> Any:
        """`timeout` overrides this client's default FOR ONE CALL
        (ops-efficiency-5, 2026-08-21).

        The collector is one thread issuing ~120 of these in series, so what
        "unreachable" costs is decided per call, not per client: a Syncthing
        that HANGS rather than refuses used to spend the default 10 s on every
        one of them while enforce, connections and the health signal waited
        behind it. A per-client default cannot express that, because the same
        client also makes the config/status calls where 10 s is right.
        """
        url = f"{self.gui_url}{path}"
        try:
            resp = self.session.request(
                method, url, params=params, json=json_body,
                headers={"X-API-Key": self.api_key},
                timeout=self.timeout if timeout is None else timeout,
            )
        except requests.RequestException as exc:
            raise SyncthingError(f"{method} {path}: {exc}") from exc
        if resp.status_code >= 300:
            raise SyncthingError(f"{method} {path}: HTTP {resp.status_code}")
        try:
            return resp.json() if resp.content else {}
        except ValueError as exc:
            raise SyncthingError(f"{method} {path}: bad JSON") from exc

    def _get(self, path: str, params: dict[str, Any] | None = None,
             timeout: float | None = None) -> Any:
        return self._request("GET", path, params=params, timeout=timeout)

    def ping(self) -> None:
        self._get("/rest/system/ping")

    def system_status(self) -> dict[str, Any]:
        return self._get("/rest/system/status")

    def config(self) -> dict[str, Any]:
        return self._get("/rest/config")

    def pending_devices(self) -> dict[str, Any]:
        return self._get("/rest/cluster/pending/devices")

    def approve_device(self, device_id: str, name: str) -> None:
        """Ensure `device_id` is a configured Syncthing device named `name`
        -- adds it if unknown (a pending device dialing in for the first
        time), renames it in place if it's already configured but unmapped
        (name doesn't resolve to a username). This is the "approve" half of
        what server/accept_device.py used to do.

        Deliberately never touches any folder's `devices` list: sharing is
        decided entirely by the selections table + the enforce cycle (see
        collector.py:_run_enforce), so a hand-added share here would just be
        reverted within one enforce interval."""
        existing = next(
            (d for d in self.config().get("devices", []) if d.get("deviceID") == device_id), None
        )
        if existing is None:
            self._request("POST", "/rest/config/devices", json_body={
                "deviceID": device_id,
                "name": name,
                # Tailnet-first when configured, else today's ["dynamic"].
                "addresses": list(self.device_addresses),
                "introducer": False,
            })
        elif existing.get("name") != name:
            existing["name"] = name
            self._request("PUT", f"/rest/config/devices/{_seg(device_id)}", json_body=existing)

    def connections(self) -> dict[str, Any]:
        return self._get("/rest/system/connections")

    def options(self) -> dict[str, Any]:
        return self._get("/rest/config/options")

    def set_options(self, options: dict[str, Any]) -> None:
        self._request("PATCH", "/rest/config/options", json_body=options)

    def apply_tailnet_only_options(self, enabled: bool) -> dict[str, Any]:
        """OPT-IN. With `enabled` False (the default everywhere) this only
        LOGS what it would change and touches nothing.

        Turning it on forces lane C onto the tailnet -- or off entirely.
        Measured on this fleet right now: the NAS Tailscale peer has an empty
        CurAddr, i.e. the path is DERP-relayed, so disabling Syncthing's own
        relays today would stop lane C rather than speed it up. Confirm a
        direct path (tailscale status --json CurAddr non-empty, and
        /rest/system/connections showing no relay-client) BEFORE enabling.

        Returns the subset of options that differ from the desired state --
        i.e. what would change / did change."""
        current = self.options() or {}
        pending = {
            key: value for key, value in TAILNET_ONLY_OPTIONS.items()
            if current.get(key) != value
        }
        if not pending:
            return {}
        if not enabled:
            log.warning(
                "syncthing: tailnet-only options NOT applied (opt-in, currently off). "
                "Would set %s. Enable only after confirming the tailnet path is "
                "direct -- with a relayed path this stops lane C instead of "
                "speeding it up (AUDIT_2 P3).",
                pending,
            )
            return pending
        log.warning("syncthing: applying tailnet-only options %s", pending)
        self.set_options(pending)
        return pending

    def events(self, since: int, types: str = "ItemFinished",
               limit: int = 200) -> list[dict[str, Any]]:
        """Non-blocking read of Syncthing's event stream (timeout=0 returns
        immediately). ItemFinished fires per file the SERVER finishes
        syncing FROM the cluster -- i.e. editor lane C uploads arriving,
        which polling alone can miss entirely for fast transfers."""
        out = self._get("/rest/events", params={
            "since": since, "events": types, "limit": limit, "timeout": 0,
        })
        return out if isinstance(out, list) else []

    def db_status(self, folder: str, timeout: float | None = None) -> dict[str, Any]:
        return self._get("/rest/db/status", {"folder": folder}, timeout=timeout)

    def completion(self, folder: str, device: str,
                   timeout: float | None = None) -> dict[str, Any]:
        return self._get("/rest/db/completion",
                         {"folder": folder, "device": device}, timeout=timeout)

    def remoteneed(self, folder: str, device: str, page: int, perpage: int,
                   timeout: float | None = None) -> dict[str, Any]:
        return self._get(
            "/rest/db/remoteneed",
            {"folder": folder, "device": device, "page": page, "perpage": perpage},
            timeout=timeout,
        )

    def add_folder(self, folder_config: dict[str, Any]) -> None:
        self._request("POST", "/rest/config/folders", json_body=folder_config)

    def get_folder(self, folder_id: str) -> dict[str, Any]:
        return self._request("GET", f"/rest/config/folders/{_seg(folder_id)}")

    def put_folder(self, folder_id: str, folder_config: dict[str, Any]) -> None:
        self._request("PUT", f"/rest/config/folders/{_seg(folder_id)}", json_body=folder_config)

    def get_ignores(self, folder: str) -> dict[str, Any]:
        """The folder's current .stignore, as {"ignore": [...], "expanded": [...]}.

        Used by the provision cycle to VERIFY ignores every pass: a
        set_ignores that failed once at folder-creation time used to leave a
        folder syncing video in both directions forever (see the .stignore
        verification finding)."""
        return self._get("/rest/db/ignores", {"folder": folder})

    def set_ignores(self, folder: str, lines: list[str]) -> None:
        self._request(
            "POST", "/rest/db/ignores", params={"folder": folder},
            json_body={"ignore": lines},
        )
