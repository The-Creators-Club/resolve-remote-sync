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

**What counts as "done" is deliberately strict.** A freshly-added, still-empty
folder scans instantly and reports `state="idle", needBytes=0` before it has
heard a word from the peer -- there is nothing to need yet. Taking that at face
value returned "sync complete" at t~=0 having moved nothing, and an `ok=True`
row of 0.0 MB/s went straight into the report's lane-C median. So the runner
now waits (untimed) for the two instances to actually connect, and only accepts
`needBytes == 0` once the global index has arrived (`globalBytes` at least the
size of what was seeded on the sending side). Measured live: the old rule
matched 0.031s in with 0 bytes on disk; the new one matched at 2.047s with all
of them.

Only "up" and "down" are measurable here. `direction = "bidirectional"` is
rejected rather than silently measured one-way -- see `run()`.

This mirrors the harness's own selftest requirement ("syncthing pair if
binary present, entirely locally") and is intentionally self-contained: it
never touches a real NAS. To later benchmark a *real* editor<->NAS Syncthing
pair over Tailscale, the endpoint config's `remote_address` can be pointed at
a real reachable host:port instead of the 127.0.0.1 default -- the
device-pairing/REST-configuration logic is unchanged either way.

If the syncthing binary isn't on PATH (and no `binary` override is
configured), `run()` returns a skipped RunResult instead of crashing.

**Syncthing 1.x and 2.x are both supported, by detection rather than
assumption.** v2 reorganised the command line -- the daemon needs the `serve`
subcommand, `generate` no longer takes `--no-default-folder`, `--device-id`
became a `device-id` subcommand, and config/database are two separate
directories. The major version is probed once per binary
(`syncthing --version`, cached) and only the process-spawn/config-generation
commands differ; the REST surface this runner measures through is identical on
both. An unrecognised major is a skipped row with a clear message, never a
guess -- a daemon started with flags it silently reinterprets would produce a
row that looks measured.

**Every row this runner produces is marked `loopback=True`**: both peers are
on this machine, so the number measured is local disk + localhost TCP, not the
editor<->NAS path. The report prints those rows in a `Loopback` column and
excludes them from lane winners whenever any real-network row exists. Point
the endpoint at a real reachable host:port before treating a syncthing number
as comparable with rclone/robocopy over Tailscale.
"""

from __future__ import annotations

import json
import re
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
# How long to wait (untimed, before the clock starts) for the two instances to
# actually dial each other. Loopback with fixed addresses and no discovery, so
# this is normally a second or two; a minute is a "something is wrong" ceiling.
CONNECT_TIMEOUT_S = 60


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


# ---------------------------------------------------------------------------
# Version detection + per-version CLI shape
# ---------------------------------------------------------------------------
#
# Syncthing 2.0 reorganised the command line: running the daemon needs the
# `serve` subcommand, `generate` lost `--no-default-folder`, the `--device-id`
# flag became a `device-id` subcommand, and config and database live in two
# separate directories (`--config` / `--data`). None of that touches the REST
# API this runner actually measures through -- `/rest/db/status`,
# `/rest/system/connections`, `/rest/config/*` are the same on both -- so the
# split is confined to process spawning and config generation, and the B25
# completion logic below is shared verbatim.

SUPPORTED_MAJORS = (1, 2)

_VERSION_RE = re.compile(r"\bv?(\d+)\.(\d+)(?:\.(\d+))?")

# binary (as resolved by `available()`) -> major version. Probing shells out,
# and the matrix spins up two instances per run per repeat, so probe once.
_VERSION_CACHE: dict[str, int] = {}


class UnsupportedSyncthingVersion(RuntimeError):
    """The binary's major version isn't one this runner knows how to drive.

    Raised instead of guessing: a wrong guess spawns a daemon with flags it
    silently reinterprets, and the resulting row would look like a measurement.
    """


def parse_version_major(version_output: str) -> int | None:
    """Major version from `syncthing --version` output, or None if unreadable.

    The line looks like:
        syncthing v2.1.2 "Hafnium Hornet" (go1.26.5 windows-amd64) ...
    """
    match = _VERSION_RE.search(version_output or "")
    if not match:
        return None
    return int(match.group(1))


def detect_major(binary: str, *, use_cache: bool = True) -> int:
    """Major version of `binary`, cached per binary path.

    Raises UnsupportedSyncthingVersion when the probe fails, the output can't
    be parsed, or the major isn't one of SUPPORTED_MAJORS.
    """
    if use_cache and binary in _VERSION_CACHE:
        return _VERSION_CACHE[binary]
    try:
        rc, out, err = _run([binary, "--version"], timeout=30)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise UnsupportedSyncthingVersion(
            f"could not probe {binary!r} for its version: {exc}"
        ) from exc
    text = out.strip() or err.strip()
    if rc != 0:
        raise UnsupportedSyncthingVersion(
            f"{binary!r} --version exited {rc}: {text or '(no output)'}"
        )
    major = parse_version_major(text)
    if major is None:
        raise UnsupportedSyncthingVersion(
            f"could not read a version number from {binary!r} --version: {text or '(no output)'}"
        )
    if major not in SUPPORTED_MAJORS:
        raise UnsupportedSyncthingVersion(
            f"syncthing major version {major} is not supported by this runner "
            f"(knows {', '.join(str(m) for m in SUPPORTED_MAJORS)}); its CLI shape is unknown, "
            f"and guessing would produce a run that looks measured but isn't"
        )
    if use_cache:
        _VERSION_CACHE[binary] = major
    return major


def generate_cmd(binary: str, config_dir: Path, major: int) -> list[str]:
    """Command that writes a fresh config + keys into `config_dir`."""
    if major >= 2:
        # v2 keeps the database out of the config dir; point it at the same
        # temp tree so a bench run cannot touch the real ~/.local/state
        # syncthing database. `generate` has no --no-default-folder any more:
        # v2 doesn't create a default folder in the first place.
        return [
            binary, "generate",
            "--config", str(config_dir),
            "--data", str(config_dir),
            "--no-port-probing",
        ]
    return [binary, "generate", "--config", str(config_dir), "--no-default-folder"]


def device_id_cmd(binary: str, config_dir: Path, major: int) -> list[str]:
    """Command that prints this config's own device ID."""
    if major >= 2:
        return [binary, "device-id", "--config", str(config_dir), "--data", str(config_dir)]
    return [binary, "--config", str(config_dir), "--device-id"]


def serve_cmd(binary: str, config_dir: Path, gui_address: str, major: int) -> list[str]:
    """Command that runs the daemon in the foreground on `gui_address`."""
    if major >= 2:
        return [
            binary, "serve",
            "--config", str(config_dir),
            "--data", str(config_dir),
            "--gui-address", gui_address,
            "--no-browser",
            "--no-restart",
            "--no-upgrade",
            "--no-port-probing",
        ]
    return [
        binary,
        "--config", str(config_dir),
        "--gui-address", gui_address,
        "--no-browser",
        "--no-restart",
        "--no-default-folder",
    ]


class _Instance:
    """One ephemeral syncthing process + its REST client helpers.

    `version_major` decides the CLI shape only; every REST call below is
    version-stable.
    """

    def __init__(self, binary: str, name: str, work_dir: Path, *, version_major: int):
        self.binary = binary
        self.name = name
        self.version_major = version_major
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
            generate_cmd(self.binary, self.config_dir, self.version_major), timeout=60
        )
        if rc != 0:
            raise RuntimeError(
                f"syncthing generate failed ({self.name}, v{self.version_major} CLI): {err or out}"
            )
        self.device_id = self._read_device_id()
        self.api_key = self._read_api_key()

    def _read_device_id(self) -> str:
        rc, out, _err = _run(
            device_id_cmd(self.binary, self.config_dir, self.version_major), timeout=30
        )
        did = out.strip()
        if rc == 0 and did:
            return did
        # fall back: parse config.xml for our own device id (present as a
        # <device> entry once generated). Same file layout on both majors.
        cfg_xml = (self.config_dir / "config.xml").read_text(encoding="utf-8")
        m = re.search(r'<device id="([^"]+)"[^>]*introducer', cfg_xml)
        if not m:
            m = re.search(r'<device id="([^"]+)"', cfg_xml)
        if not m:
            raise RuntimeError(f"could not determine device id for {self.name}")
        return m.group(1)

    def _read_api_key(self) -> str:
        cfg_xml = (self.config_dir / "config.xml").read_text(encoding="utf-8")
        m = re.search(r"<apikey>([^<]+)</apikey>", cfg_xml)
        if not m:
            raise RuntimeError(f"could not read api key for {self.name}")
        return m.group(1)

    def start(self) -> None:
        self.proc = subprocess.Popen(
            serve_cmd(
                self.binary, self.config_dir, f"127.0.0.1:{self.gui_port}", self.version_major
            ),
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

    def peer_connected(self, peer_device_id: str) -> bool:
        """True iff this instance currently holds a live connection to the peer.

        Never raises: it is polled in a loop while the pair is still coming up,
        and a connection-refused there is just "not yet".
        """
        try:
            conns = self._get("/rest/system/connections")
        except Exception:  # noqa: BLE001
            return False
        entry = (conns.get("connections") or {}).get(peer_device_id) or {}
        return bool(entry.get("connected"))

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


def _wait_for_peer_connection(
    instance: "_Instance",
    peer_device_id: str,
    timeout_s: float = CONNECT_TIMEOUT_S,
    poll_interval: float = POLL_INTERVAL_S,
) -> bool:
    """Block (untimed) until `instance` has actually connected to the peer.

    Done before the clock starts, for two reasons: a run that never connects
    must fail loudly rather than be measured, and the TCP dial + TLS handshake
    is setup, not transfer -- the same reason the rclone runners seed and
    pre-clean untimed.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        if instance.peer_connected(peer_device_id):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_interval)


def _wait_for_sync(
    instance: "_Instance",
    folder_id: str,
    timeout_s: float,
    *,
    expected_bytes: int = 0,
    poll_interval: float = POLL_INTERVAL_S,
) -> tuple[bool, float, str]:
    """Wait until `folder_id` on `instance` holds everything the peer offers.

    Returns (completed, seconds, detail); `detail` explains a False.

    **`needBytes == 0` on its own is not completion.** A folder that has just
    been added scans its (empty) directory instantly and reports
    `state="idle", needBytes=0` *before* the peer has connected and before the
    global index has arrived -- there is nothing to need yet. The first poll
    then matched, the run returned "complete" at t~=0 with 0 bytes moved, and
    because that row is `ok=True` the report medianed a 0.0 MB/s into lane C.

    So completion also requires evidence that the index actually landed:
    `globalBytes > 0`, and at least `expected_bytes` when the caller knows what
    was seeded on the other side. Directories count toward syncthing's
    `globalBytes` (a synthetic 128 bytes each), so the seeded payload size is a
    safe lower bound.
    """
    start = time.monotonic()
    deadline = start + timeout_s
    saw_index = False
    last_need = -1
    last_global = 0
    last_state = ""
    while True:
        status = instance.folder_status(folder_id)
        last_need = status.get("needBytes", 1)
        last_global = status.get("globalBytes", 0) or 0
        last_state = status.get("state", "")
        index_arrived = last_global > 0 and last_global >= expected_bytes
        saw_index = saw_index or index_arrived
        if index_arrived and last_need == 0 and last_state in ("idle", ""):
            return True, time.monotonic() - start, ""
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_interval)

    elapsed = time.monotonic() - start
    if not saw_index:
        detail = (
            f"the global index never arrived (globalBytes={last_global}, "
            f"expected at least {expected_bytes}, state={last_state!r})"
        )
    else:
        detail = f"needBytes never reached 0 (last needBytes={last_need}, state={last_state!r})"
    return False, elapsed, detail


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

    if direction == "bidirectional":
        # The runner seeds one side and measures the other side receiving it:
        # that is a one-way sync however the row is labelled. Rather than
        # publish a "bidirectional" number that was measured one-way, say so.
        # Use direction = "both" in bench.toml, which runs up and down as two
        # separate, honestly-labelled rows.
        return make_skipped(
            ENGINE, dataset_name, direction, params,
            "syncthing runner cannot measure a true bidirectional sync (it seeds one side "
            "and times the other receiving it). Use direction = \"both\" to get separate "
            "up and down rows.",
            lane, "", repeat_index, True,
        )

    if direction not in ("up", "down"):
        return make_skipped(
            ENGINE, dataset_name, direction, params,
            f"unsupported direction for syncthing runner: {direction}", lane, "", repeat_index,
            True,
        )

    # Probed once per binary (cached) and before anything is spawned: the CLI
    # shape differs between syncthing 1.x and 2.x, and an unknown major is a
    # "can't run here" like a missing binary, not a failed measurement.
    try:
        version_major = detect_major(syncthing_binary)
    except UnsupportedSyncthingVersion as exc:
        return make_skipped(
            ENGINE, dataset_name, direction, params, str(exc), lane, "", repeat_index, True
        )

    # The "_bench" in the prefix is load-bearing: ccbench.guard refuses to
    # rmtree anything without it (see the teardown in `finally`).
    tmp_root = Path(tempfile.mkdtemp(prefix="ccbench-_bench-syncthing-"))
    folder_id = "ccbench-bench"
    source_name, dest_name = ("editor", "nas") if direction == "up" else ("nas", "editor")

    source = _Instance(syncthing_binary, source_name, tmp_root, version_major=version_major)
    dest = _Instance(syncthing_binary, dest_name, tmp_root, version_major=version_major)

    try:
        _seed_folder_with_dataset(Path(dataset_dir), source.folder_dir)
        # Measured, not assumed: what actually sits on the sending side is the
        # lower bound the receiver's global index has to reach before
        # "needBytes == 0" can mean "finished" rather than "hasn't heard yet".
        expected_bytes = _tree_bytes(source.folder_dir)

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

        # Untimed: the pair must be talking before anything can be measured.
        # Without this the first status poll lands on a folder that has never
        # heard from the peer, and an unconnected, empty, idle folder looks
        # exactly like a finished one.
        if not _wait_for_peer_connection(dest, source.device_id):
            return RunResult(
                engine=ENGINE, dataset=dataset_name, direction=direction, params=params,
                seconds=0.0, num_bytes=0, MB_s=0.0, verified=False, ok=False,
                reason=f"peers never connected within {CONNECT_TIMEOUT_S}s -- nothing was measured",
                lane=lane, endpoint="localhost-pair", repeat_index=repeat_index,
                bytes_source="none", verify_method="none", loopback=True,
            )

        with base.Timer() as timer:
            completed, _elapsed, detail = _wait_for_sync(
                dest, folder_id, sync_timeout_s, expected_bytes=expected_bytes
            )
        seconds = timer.seconds

        if not completed:
            return RunResult(
                engine=ENGINE, dataset=dataset_name, direction=direction, params=params,
                seconds=seconds, num_bytes=0, MB_s=0.0, verified=False, ok=False,
                reason=f"sync did not complete within {sync_timeout_s}s: {detail}", lane=lane,
                endpoint="localhost-pair", repeat_index=repeat_index,
                bytes_source="none", verify_method="none", loopback=True,
            )

        # The destination folder is freshly created per run, so "bytes moved"
        # is the size of what landed there -- measured, not assumed.
        moved_bytes = _tree_bytes(dest.folder_dir)

        # Backstop for the same class of bug the globalBytes guard above
        # closes: if what landed is materially short of what was seeded, the
        # seconds measured are not the seconds it takes to move this dataset.
        short = base.short_transfer_reason("syncthing", moved_bytes, expected_bytes)
        if short:
            return RunResult(
                engine=ENGINE, dataset=dataset_name, direction=direction, params=params,
                seconds=seconds, num_bytes=moved_bytes, MB_s=0.0, verified=False, ok=False,
                reason=short, lane=lane, endpoint="localhost-pair", repeat_index=repeat_index,
                bytes_source="destination-listing", verify_method="none", loopback=True,
            )

        verified = False
        verify_method = "none"
        detail = ""
        if verify:
            manifest = base.manifest_files(dataset_dir)
            verified, detail = base.spot_check(manifest, dest.folder_dir)
            verify_method = "spot-check-sha256"

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
