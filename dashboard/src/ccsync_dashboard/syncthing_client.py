"""Thin client for the server Syncthing REST API.

Same auth pattern as server/common.py:syncthing_api -- X-API-Key header,
plain requests. Any transport or non-2xx failure raises SyncthingError so the
collector can treat "Syncthing is unreachable" as one condition.
"""
from __future__ import annotations

from typing import Any

import requests


class SyncthingError(Exception):
    pass


class SyncthingClient:
    def __init__(self, gui_url: str, api_key: str, timeout: float = 10.0, session=None):
        self.gui_url = gui_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> Any:
        url = f"{self.gui_url}{path}"
        try:
            resp = self.session.request(
                method, url, params=params, json=json_body,
                headers={"X-API-Key": self.api_key}, timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SyncthingError(f"{method} {path}: {exc}") from exc
        if resp.status_code >= 300:
            raise SyncthingError(f"{method} {path}: HTTP {resp.status_code}")
        try:
            return resp.json() if resp.content else {}
        except ValueError as exc:
            raise SyncthingError(f"{method} {path}: bad JSON") from exc

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

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
                "addresses": ["dynamic"],
                "introducer": False,
            })
        elif existing.get("name") != name:
            existing["name"] = name
            self._request("PUT", f"/rest/config/devices/{device_id}", json_body=existing)

    def connections(self) -> dict[str, Any]:
        return self._get("/rest/system/connections")

    def db_status(self, folder: str) -> dict[str, Any]:
        return self._get("/rest/db/status", {"folder": folder})

    def completion(self, folder: str, device: str) -> dict[str, Any]:
        return self._get("/rest/db/completion", {"folder": folder, "device": device})

    def remoteneed(self, folder: str, device: str, page: int, perpage: int) -> dict[str, Any]:
        return self._get(
            "/rest/db/remoteneed",
            {"folder": folder, "device": device, "page": page, "perpage": perpage},
        )

    def add_folder(self, folder_config: dict[str, Any]) -> None:
        self._request("POST", "/rest/config/folders", json_body=folder_config)

    def get_folder(self, folder_id: str) -> dict[str, Any]:
        return self._request("GET", f"/rest/config/folders/{folder_id}")

    def put_folder(self, folder_id: str, folder_config: dict[str, Any]) -> None:
        self._request("PUT", f"/rest/config/folders/{folder_id}", json_body=folder_config)

    def set_ignores(self, folder: str, lines: list[str]) -> None:
        self._request(
            "POST", "/rest/db/ignores", params={"folder": folder},
            json_body={"ignore": lines},
        )
