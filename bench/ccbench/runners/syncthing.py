"""Ephemeral Syncthing pair for lane C (bidirectional, small-file, event-driven
block-delta sync).

Design: spin up two throwaway Syncthing instances, each with its own temp
config dir + random high GUI/listen ports, wire them together as mutual
devices over the loopback interface, disable relays/global+local discovery/
NAT traversal (this harness doesn't need discovery -- both addresses are
known up front, and we don't want a real-world relay muddying the timing),
share one folder seeded on one side, and poll each side's REST API for
completion. Everything is created under a temp dir and torn down (processes
killed, temp dirs removed) in a `finally` block so a crash mid-run can't
leave orphaned syncthing processes.

This mirrors the harness's own selftest requirement ("syncthing pair if
binary present, entirely locally") and is intentionally self-contained: it
never touches a real NAS. To later benchmark a *real* editor<->NAS Syncthing
pair over Tailscale, the endpoint config's `remote_address` can be pointed at
a real reachable host:port instead of the 127.0.0.1 default -- the
device-pairing/REST-configuration logic is unchanged either way.

If the syncthing binary isn't on PATH (and no `binary` override is
configured), `run()` returns a skipped RunResult instead of crashing.

**Every row this runner produces is marked `loopback=True`**: both peers are
on this machine, so the number measured is local disk + localhost TCP, not the
editor<->NAS path. The report prints those rows in a `Loopback` column and
excludes them from lane winners whenever any real-network row exists. Point
the endpoint at a real reachable host:port before treating a syncthing number
as comparable with rclone/robocopy over Tailscale.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ccbench import guard
from ccbench.result import RunResult, make_skipped

from . import base

ENGINE = "syncthing"

STARTUP_TIMEOUT_S = 20
DEFAULT_SYNC_TIMEOUT_S = 1800
POLL_INTERVAL_S = 0.5


def available(cfg: dict[str, Any] | None = None) -> tuple[bool, str]:
    binary = (cfg or {}).get("binary")
    if binary:
        if shutil.which(binary) or Path(binary).exists():
            return True, binary
        return False, f"configured syncthing binary not found: {binary}"
    return base.which("syncthing")


def param_matrix(cfg: dict[str, Any], direction: str) -> list[dict[str, Any]]:
    # Syncthing is event-driven, not stream/thread-tunable like rclone/robocopy
    # -- there's exactly one meaningful "config" per direction.
    return [{}]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(cmd: list[str], timeout: float | None = 60) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


class _Instance:
    """One ephemeral syncthing process + its REST client helpers."""

    def __init__(self, binary: str, name: str, work_dir: Path):
        self.binary = binary
        self.name = name
        self.config_dir = work_dir / f"st-{name}"
        self.folder_dir = work_dir / f"data-{name}"
        self.gui_port = _free_port()
        self.listen_port = _free_port()
        self.api_key: str | None = None
        self.device_id: str | None = None
        self.proc: subprocess.Popen | None = None

    def generate(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.folder_dir.mkdir(parents=True, exist_ok=True)
        rc, out, err = _run(
            [self.binary, "generate", "--config", str(self.config_dir), "--no-default-folder"],
            timeout=60,
        )
        if rc != 0:
            raise RuntimeError(f"syncthing generate failed ({self.name}): {err or out}")
        self.device_id = self._read_device_id()
        self.api_key = self._read_api_key()

    def _read_device_id(self) -> str:
        rc, out, _err = _run([self.binary, "--config", str(self.config_dir), "--device-id"], timeout=30)
        did = out.strip()
        if rc == 0 and did:
            return did
        # fall back: parse config.xml for our own device id (present as a
        # <device> entry once generated)
        cfg_xml = (self.config_dir / "config.xml").read_text(encoding="utf-8")
        import re

        m = re.search(r'<device id="([^"]+)"[^>]*introducer', cfg_xml)
        if not m:
            m = re.search(r'<device id="([^"]+)"', cfg_xml)
        if not m:
            raise RuntimeError(f"could not determine device id for {self.name}")
        return m.group(1)

    def _read_api_key(self) -> str:
        cfg_xml = (self.config_dir / "config.xml").read_text(encoding="utf-8")
        import re

        m = re.search(r"<apikey>([^<]+)</apikey>", cfg_xml)
        if not m:
            raise RuntimeError(f"could not read api key for {self.name}")
        return m.group(1)

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [
                self.binary,
                "--config", str(self.config_dir),
                "--gui-address", f"127.0.0.1:{self.gui_port}",
                "--no-browser",
                "--no-restart",
                "--no-default-folder",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._wait_for_gui()

    def _wait_for_gui(self) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self._get("/rest/system/ping")
                return
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(0.3)
        raise RuntimeError(f"syncthing GUI never came up for {self.name}: {last_err}")

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.gui_port}{path}"

    def _get(self, path: str) -> dict[str, Any]:
        req = urllib.request.Request(self._url(path), headers={"X-API-Key": self.api_key or ""})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}

    def _request(self, method: str, path: str, payload: Any = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            self._url(path),
            data=data,
            method=method,
            headers={"X-API-Key": self.api_key or "", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc

    def disable_discovery_and_relays(self) -> None:
        self._request(
            "PATCH",
            "/rest/config/options",
            {
                "globalAnnounceEnabled": False,
                "localAnnounceEnabled": False,
                "relaysEnabled": False,
                "natEnabled": False,
                "urAccepted": -1,
            },
        )

    def add_peer_device(self, peer_device_id: str, peer_listen_port: int) -> None:
        self._request(
            "PUT",
            f"/rest/config/devices/{peer_device_id}",
            {
                "deviceID": peer_device_id,
                "name": f"peer-{peer_device_id[:5]}",
                "addresses": [f"tcp://127.0.0.1:{peer_listen_port}"],
                "autoAcceptFolders": True,
            },
        )

    def set_listen_address(self) -> None:
        self._request(
            "PATCH",
            "/rest/config/options",
            {"listenAddresses": [f"tcp://127.0.0.1:{self.listen_port}"]},
        )

    def add_folder(self, folder_id: str, peer_device_id: str) -> None:
        self._request(
            "PUT",
            f"/rest/config/folders/{folder_id}",
            {
                "id": folder_id,
                "label": folder_id,
                "path": str(self.folder_dir),
                "type": "sendreceive",
                "devices": [{"deviceID": self.device_id}, {"deviceID": peer_device_id}],
                "rescanIntervalS": 5,
                "fsWatcherEnabled": True,
                "ignorePerms": True,
            },
        )

    def folder_status(self, folder_id: str) -> dict[str, Any]:
        return self._get(f"/rest/db/status?folder={folder_id}")

    def restart_if_required(self) -> None:
        resp = self._get("/rest/config/restart-required")
        if resp.get("requiresRestart"):
            self._request("POST", "/rest/system/restart")
            self._wait_for_gui()

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            self._request("POST", "/rest/system/shutdown")
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                self.proc.kill()


def _seed_folder_with_dataset(dataset_dir: Path, folder_dir: Path) -> None:
    folder_dir.mkdir(parents=True, exist_ok=True)
    for item in dataset_dir.iterdir():
        dest = folder_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)


def _tree_bytes(root: Path) -> int:
    """Total size of the synced payload under `root`, ignoring syncthing's own
    dot-files (.stfolder, .stversions, .stignore, .syncthing.*.tmp)."""
    total = 0
    for path in root.rglob("*"):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            total += path.stat().st_size
    return total


def _wait_for_sync(instance: "_Instance", folder_id: str, timeout_s: float) -> tuple[bool, float]:
    start = time.monotonic()
    deadline = start + timeout_s
    while time.monotonic() < deadline:
        status = instance.folder_status(folder_id)
        need_bytes = status.get("needBytes", 1)
        state = status.get("state", "")
        if need_bytes == 0 and state in ("idle", ""):
            return True, time.monotonic() - start
        time.sleep(POLL_INTERVAL_S)
    return False, time.monotonic() - start


def run(
    dataset_dir: Path,
    direction: str,
    endpoint: dict[str, Any],
    params: dict[str, Any],
    *,
    dataset_name: str = "",
    verify: bool = True,
    keep_remote_data: bool = False,
    dest_dir: Path | None = None,
    lane: str = "",
    repeat_index: int = 0,
    binary: str | None = None,
    sync_timeout_s: float = DEFAULT_SYNC_TIMEOUT_S,
) -> RunResult:
    dataset_name = dataset_name or Path(dataset_dir).name
    cfg = {"binary": binary or (endpoint or {}).get("binary")}
    ok, reason = available(cfg)
    if not ok:
        return make_skipped(
            ENGINE, dataset_name, direction, params, reason, lane, "", repeat_index, True
        )
    syncthing_binary = reason  # available() returns the resolved path/binary name on success

    if direction not in ("up", "down", "bidirectional"):
        return make_skipped(
            ENGINE, dataset_name, direction, params,
            f"unsupported direction for syncthing runner: {direction}", lane, "", repeat_index,
            True,
        )

    # The "_bench" in the prefix is load-bearing: ccbench.guard refuses to
    # rmtree anything without it (see the teardown in `finally`).
    tmp_root = Path(tempfile.mkdtemp(prefix="ccbench-_bench-syncthing-"))
    folder_id = "ccbench-bench"
    source_name, dest_name = ("editor", "nas") if direction == "up" else ("nas", "editor")

    source = _Instance(syncthing_binary, source_name, tmp_root)
    dest = _Instance(syncthing_binary, dest_name, tmp_root)

    try:
        _seed_folder_with_dataset(Path(dataset_dir), source.folder_dir)

        for inst in (source, dest):
            inst.generate()
            inst.start()

        for inst in (source, dest):
            inst.disable_discovery_and_relays()
            inst.set_listen_address()
            inst.restart_if_required()

        source.add_peer_device(dest.device_id, dest.listen_port)
        dest.add_peer_device(source.device_id, source.listen_port)

        source.add_folder(folder_id, dest.device_id)
        dest.add_folder(folder_id, source.device_id)

        with base.Timer() as timer:
            completed, _elapsed = _wait_for_sync(dest, folder_id, sync_timeout_s)
        seconds = timer.seconds

        if not completed:
            return RunResult(
                engine=ENGINE, dataset=dataset_name, direction=direction, params=params,
                seconds=seconds, num_bytes=0, MB_s=0.0, verified=False, ok=False,
                reason=f"sync did not complete within {sync_timeout_s}s", lane=lane,
                endpoint="localhost-pair", repeat_index=repeat_index,
                bytes_source="none", verify_method="none", loopback=True,
            )

        verified = False
        verify_method = "none"
        detail = ""
        if verify:
            manifest = base.manifest_files(dataset_dir)
            verified, detail = base.spot_check(manifest, dest.folder_dir)
            verify_method = "spot-check-sha256"

        # The destination folder is freshly created per run, so "bytes moved"
        # is the size of what landed there -- measured, not assumed.
        moved_bytes = _tree_bytes(dest.folder_dir)

        return RunResult(
            engine=ENGINE,
            dataset=dataset_name,
            direction=direction,
            params=params,
            seconds=seconds,
            num_bytes=moved_bytes,
            MB_s=base.mb_per_s(moved_bytes, seconds),
            verified=verified,
            ok=True,
            reason="" if verified or not verify else f"verification failed: {detail}",
            lane=lane,
            endpoint="localhost-pair",
            repeat_index=repeat_index,
            bytes_source="destination-listing",
            verify_method=verify_method,
            loopback=True,
        )
    except Exception as exc:  # noqa: BLE001 -- runners must never raise
        return RunResult(
            engine=ENGINE, dataset=dataset_name, direction=direction, params=params,
            seconds=0.0, num_bytes=0, MB_s=0.0, verified=False, ok=False,
            reason=f"exception: {exc}", lane=lane, endpoint="localhost-pair", repeat_index=repeat_index,
            bytes_source="none", verify_method="none", loopback=True,
        )
    finally:
        for inst in (source, dest):
            try:
                inst.stop()
            except Exception:  # noqa: BLE001
                pass
        if not keep_remote_data:
            try:
                guard.safe_rmtree(tmp_root, action="remove ephemeral syncthing workspace")
            except guard.DestructiveEndpointRefused:
                pass  # leave the temp workspace rather than raise out of `finally`
