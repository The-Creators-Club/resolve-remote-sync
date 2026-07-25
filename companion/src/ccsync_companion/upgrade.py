"""Companion self-upgrade (notify + one-click).

The dashboard advertises the published "current" build in its report/verify
responses as a conditional `upgrade` key (absent = up to date -- see the
dashboard's api._upgrade_info). The reporter hands every report response to
UpgradeManager.note_report_response(); when an upgrade is available the tray
grows an "Update now" item, and apply() does the whole swap:

    download to <exe dir>/ccsync-companion.new.exe -> sha256 verify
    -> os.replace(exe, exe.old)      (a RUNNING exe can't be overwritten on
                                      Windows, but it CAN be renamed on the
                                      same volume -- hence same-dir download)
    -> os.replace(new, exe)
    -> spawn the new exe detached    (failure here ROLLS BACK both renames
                                      and keeps the current build running)
    -> request_shutdown()

The stale `.old` is deleted on the NEXT startup (cleanup_old_exe) because the
new process may start while the old one still holds its own image briefly.

"Different, not newer": the server only advertises when the current published
version differs from what we reported, so an admin rollback is offered to the
fleet exactly like an upgrade. Nothing here compares version numbers.

Never-raise ethos throughout, injectable I/O for tests (same conventions as
reporter.py).
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod

log = logging.getLogger("ccsync.upgrade")

# (url, headers, timeout) -> file-like response usable as a context manager.
HttpOpenFn = Callable[[str, dict, float], Any]
ReplaceFn = Callable[[Path, Path], Any]
SpawnFn = Callable[[Path], Any]

# Generous: editors may be on slow links and the exe is ~20 MB.
DOWNLOAD_TIMEOUT = 600.0
_NEW_NAME = "ccsync-companion.new.exe"
_OLD_SUFFIX = ".old"


def platform_key() -> str:
    """The dashboard's platform discriminator for this machine."""
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def default_http_open(url: str, headers: dict, timeout: float):
    req = urllib.request.Request(url, headers=headers, method="GET")
    return urllib.request.urlopen(req, timeout=timeout)


def cleanup_old_exe(exe_path: Optional[Path] = None) -> None:
    """Delete the `<exe>.old` a previous apply() left behind. Swallows
    OSError entirely -- an AV scanner may still hold the file; we simply try
    again on the next start. At most one `.old` ever exists."""
    try:
        if exe_path is None:
            if not is_frozen():
                return
            exe_path = Path(sys.executable)
        exe_path.with_name(exe_path.name + _OLD_SUFFIX).unlink(missing_ok=True)
    except OSError:
        log.debug("cleanup_old_exe: .old still locked; will retry next start")


def parse_upgrade(resp: Any) -> Optional[dict[str, Any]]:
    """Extract + validate the `upgrade` dict from a report/verify response.

    None for anything unusable, and None when the advertised version equals
    the running one (the server omits the key then, but belt and braces --
    offering a "downgrade" to the version already running would loop)."""
    if not isinstance(resp, dict):
        return None
    info = resp.get("upgrade")
    if not isinstance(info, dict):
        return None
    version = str(info.get("version") or "").strip()
    url = str(info.get("url") or "").strip()
    sha256 = str(info.get("sha256") or "").strip().lower()
    if not version or not url or len(sha256) != 64:
        return None
    if version == config_mod.VERSION:
        return None
    return {"version": version, "url": url, "sha256": sha256,
            "size_bytes": info.get("size_bytes")}


class UpgradeManager:
    """Holds the "is an update available" state and performs the swap.

    Thread model: note_report_response() is called from the reporter thread,
    available/apply() from tray-spawned threads -- everything touching
    _available goes through _lock. apply() itself is serialized by the
    _applying flag (a second click while one is in flight is a no-op)."""

    def __init__(
        self,
        cfg: dict[str, Any],
        http_open: Optional[HttpOpenFn] = None,
        replace_fn: ReplaceFn = os.replace,
        spawn_fn: Optional[SpawnFn] = None,
        request_shutdown: Optional[Callable[[], None]] = None,
        on_available: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self.cfg = cfg
        self._http_open = http_open or default_http_open
        self._replace = replace_fn
        self._spawn = spawn_fn or self._default_spawn
        self._request_shutdown = request_shutdown
        self._on_available = on_available
        self._lock = threading.Lock()
        self._available: Optional[dict[str, Any]] = None
        self._applying = False

    @property
    def available(self) -> Optional[dict[str, Any]]:
        with self._lock:
            return dict(self._available) if self._available else None

    def note_report_response(self, resp: Any) -> None:
        """Feed a parsed report/verify response. Sets the available state on
        a valid `upgrade` key, CLEARS it when a well-formed response has none
        (the admin rolled current back to our version, or unpublished it).
        Never raises."""
        try:
            info = parse_upgrade(resp)
        except Exception:
            info = None
        newly: Optional[dict[str, Any]] = None
        with self._lock:
            if info is not None:
                if self._available is None or self._available["version"] != info["version"]:
                    newly = info
                self._available = info
            elif isinstance(resp, dict):
                self._available = None
        if newly is not None and self._on_available is not None:
            try:
                self._on_available(newly)
            except Exception:
                log.exception("on_available callback failed")

    # -- download ------------------------------------------------------
    def download_and_verify(self, info: dict[str, Any], dest_dir: Path) -> Optional[Path]:
        """Stream the advertised build to dest_dir/ccsync-companion.new.exe
        and verify its sha256. Returns the path, or None on any failure
        (temp file removed). Never raises."""
        url = str(info.get("url") or "")
        if url.startswith("/"):
            base = str(self.cfg.get("dashboard_url", "")).strip().rstrip("/")
            if not base:
                log.warning("upgrade: dashboard_url is not configured -- cannot download")
                return None
            url = base + url
        headers = {}
        token = str(self.cfg.get("dashboard_token", "")).strip()
        if token:
            headers["X-CCSync-Token"] = token

        tmp = dest_dir / _NEW_NAME
        digest = hashlib.sha256()
        try:
            with self._http_open(url, headers, DOWNLOAD_TIMEOUT) as resp, tmp.open("wb") as fh:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    digest.update(chunk)
        except Exception as exc:
            log.warning("upgrade: download failed: %s", exc)
            self._unlink_quietly(tmp)
            return None
        if digest.hexdigest() != info.get("sha256"):
            log.warning("upgrade: sha256 mismatch on downloaded build -- discarding it")
            self._unlink_quietly(tmp)
            return None
        return tmp

    # -- the swap ------------------------------------------------------
    def apply(self) -> bool:
        """Download + swap + restart. Never raises; False means "nothing
        happened / rolled back, the current build keeps running"."""
        info = self.available
        if info is None:
            return False
        if not is_frozen():
            log.info("upgrade: not a frozen exe (source run) -- self-upgrade skipped")
            return False
        with self._lock:
            if self._applying:
                return False
            self._applying = True
        try:
            return self._apply_inner(info)
        finally:
            with self._lock:
                self._applying = False

    def _apply_inner(self, info: dict[str, Any]) -> bool:
        exe = Path(sys.executable)
        new = self.download_and_verify(info, exe.parent)
        if new is None:
            return False

        old = exe.with_name(exe.name + _OLD_SUFFIX)
        try:
            self._replace(exe, old)
        except OSError as exc:
            log.warning("upgrade: could not move the running exe aside: %s", exc)
            self._unlink_quietly(new)
            return False
        try:
            self._replace(new, exe)
        except OSError as exc:
            log.warning("upgrade: could not move the new exe into place: %s -- rolling back", exc)
            self._rollback(old, exe, aside=None)
            return False
        try:
            self._spawn(exe)
        except Exception as exc:
            log.warning("upgrade: could not launch the new build: %s -- rolling back", exc)
            self._rollback(old, exe, aside=new)
            return False

        log.info("upgrade: v%s launched; shutting down v%s", info["version"], config_mod.VERSION)
        if self._request_shutdown is not None:
            try:
                self._request_shutdown()
            except Exception:
                log.exception("upgrade: request_shutdown failed (exit manually)")
        return True

    def _rollback(self, old: Path, exe: Path, aside: Optional[Path]) -> None:
        """Restore `old` to `exe`; if the failed new build currently sits at
        `exe`, park it back at `aside` first so the restore can land."""
        try:
            if aside is not None:
                self._replace(exe, aside)
            self._replace(old, exe)
        except OSError:
            log.error(
                "upgrade: ROLLBACK FAILED -- the previous build is at %s; "
                "rename it back to %s by hand", old, exe.name,
            )

    @staticmethod
    def _unlink_quietly(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _default_spawn(exe: Path) -> None:
        # DETACHED_PROCESS: the child gets no console (build.spec builds a
        # console exe; inheriting this process's soon-dead console would be
        # worse than none). All std handles to DEVNULL for the same reason.
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [str(exe)],
            cwd=str(exe.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
