"""Main supervised loop tying together the watcher, fixer/popup, sync lanes,
and tray — the entry point started by `ccsync-companion` (see pyproject.toml
[project.scripts] and __main__.py).
"""

from __future__ import annotations

import logging
import logging.handlers
import threading
import time
from pathlib import Path
from typing import Any, Optional

from . import config as config_mod
from . import popup
from .fixer import IgnoreTracker
from .sync.base import LaneAdapter, LaneStatus
from .sync.rclone_lane import DIRECTION_DOWN, DIRECTION_UP, RcloneLane
from .sync.syncthing_lane import SyncthingLane
from .watcher import TimelineWatcher

log = logging.getLogger("ccsync.app")


def setup_logging(cfg: dict[str, Any]) -> None:
    log_path = config_mod.resolved_log_path(cfg)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, str(cfg.get("log_level", "INFO")).upper(), logging.INFO)

    root = logging.getLogger("ccsync")
    root.setLevel(level)
    root.handlers.clear()

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    console_handler = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    for handler in (file_handler, console_handler):
        handler.setFormatter(fmt)
        root.addHandler(handler)


class CompanionApp:
    """Owns the timeline watcher, all three sync lanes, and (optionally) the
    tray icon. Every public method is safe to call from any thread (the
    tray runs its callbacks on its own thread)."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.config = cfg
        self.log_path = config_mod.resolved_log_path(cfg)
        self.ignore_tracker = IgnoreTracker()
        # Paths recently shown in a popup the user closed without acting:
        # snoozed so the dialog doesn't re-pop every poll cycle forever.
        self._popup_snooze: dict[str, float] = {}
        self.popup_snooze_seconds = float(cfg.get("popup_snooze_seconds", 300))
        self._paused = False
        self._stop_event = threading.Event()
        self._watcher_thread: Optional[threading.Thread] = None
        self._tray_icon = None

        self.lanes: list[LaneAdapter] = self._build_lanes()
        self.watcher = TimelineWatcher(
            local_root=cfg["local_root"],
            canonical_prefix=cfg["canonical_prefix"],
            poll_interval=float(cfg.get("poll_interval", 3)),
            on_out_of_tree=self._handle_out_of_tree,
            on_mapping_warning=self._handle_mapping_warning,
            ignore_tracker=self.ignore_tracker,
        )

    def _build_lanes(self) -> list[LaneAdapter]:
        cfg = self.config
        state_dir = Path(cfg.get("log_path", "~/.ccsync/companion.log")).expanduser().parent / "state"
        lane_a = RcloneLane(
            direction=DIRECTION_UP,
            local_root=cfg["local_root"],
            remote=cfg["remote"],
            remote_root=cfg["remote_root"],
            rclone_path=cfg.get("rclone_path", "rclone"),
            transfers=int(cfg.get("transfers", 4)),
            scan_interval=float(cfg.get("scan_interval_up", 300)),
            watch_debounce_seconds=float(cfg.get("watch_debounce_seconds", 10)),
            state_dir=state_dir,
        )
        lane_b = RcloneLane(
            direction=DIRECTION_DOWN,
            local_root=cfg["local_root"],
            remote=cfg["remote"],
            remote_root=cfg["remote_root"],
            rclone_path=cfg.get("rclone_path", "rclone"),
            transfers=int(cfg.get("transfers", 4)),
            scan_interval=float(cfg.get("scan_interval_down", 120)),
            state_dir=state_dir,
        )
        lane_c = SyncthingLane(
            base_url=cfg.get("syncthing_url", "http://127.0.0.1:8384"),
            api_key=cfg.get("syncthing_api_key", ""),
            expected_folder_ids=cfg.get("syncthing_folder_ids", []),
        )
        return [lane_a, lane_b, lane_c]

    # -- watcher callbacks -----------------------------------------------
    def _handle_out_of_tree(self, items: list[dict[str, Any]]) -> None:
        from .watcher import _norm_key

        now = time.monotonic()
        fresh = []
        for item in items:
            key = _norm_key(item.get("file_path", ""))
            shown_at = self._popup_snooze.get(key)
            if shown_at is not None and (now - shown_at) < self.popup_snooze_seconds:
                continue
            fresh.append(item)
        if not fresh:
            return

        log.info("popup: %d clip(s) outside %s", len(fresh), self.config.get("local_root"))
        for item in fresh:
            self._popup_snooze[_norm_key(item.get("file_path", ""))] = now
        popup.show_popup(
            fresh, self.config["local_root"], self.config.get("editor_name", ""), self.ignore_tracker,
            project_prefix=self.config.get("active_project", ""),
        )

    def _handle_mapping_warning(self, item: dict[str, Any]) -> None:
        path = item.get("file_path", "")
        msg = (
            f"clip on canonical prefix ({self.config.get('canonical_prefix')}) doesn't "
            f"resolve under local_root ({self.config.get('local_root')}): {path}"
        )
        log.warning(msg)
        if self._tray_icon is not None:
            try:
                self._tray_icon.notify(msg, "ccsync-companion: mapping warning")
            except Exception:
                log.debug("tray notify failed (backend may not support it)")

    # -- tray-facing API ---------------------------------------------------
    def lane_statuses(self) -> list[LaneStatus]:
        return [lane.status() for lane in self.lanes]

    def sync_now(self) -> None:
        for lane in self.lanes:
            try:
                lane.run_once()
            except Exception:
                log.exception("sync_now: lane %s failed", getattr(lane, "name", lane))

    def is_paused(self) -> bool:
        return self._paused

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        for lane in self.lanes:
            try:
                lane.stop() if self._paused else lane.start()
            except Exception:
                log.exception("toggle_pause: lane %s failed", getattr(lane, "name", lane))
        log.info("sync %s", "paused" if self._paused else "resumed")

    # -- lifecycle ---------------------------------------------------
    def start(self) -> None:
        for lane in self.lanes:
            try:
                lane.start()
            except Exception:
                log.exception("failed to start lane %s", getattr(lane, "name", lane))
        self._stop_event.clear()
        self._watcher_thread = threading.Thread(
            target=self.watcher.run, args=(self._stop_event,), name="ccsync-watcher", daemon=True
        )
        self._watcher_thread.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        for lane in self.lanes:
            try:
                lane.stop()
            except Exception:
                log.exception("failed to stop lane %s", getattr(lane, "name", lane))

    def run(self) -> None:
        setup_logging(self.config)
        log.info("ccsync-companion v%s starting", config_mod.VERSION)
        log.info("config: %s", config_mod.CONFIG_PATH)
        self.start()

        try:
            from . import tray as tray_mod

            self._tray_icon = tray_mod.start_tray(self)
            log.info("tray icon started")
        except ImportError:
            self._tray_icon = None
            log.warning("pystray/Pillow not installed — running headless (Ctrl+C to stop)")

        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(1.0)
        except KeyboardInterrupt:
            log.info("shutting down (KeyboardInterrupt)")
        finally:
            self.shutdown()
            if self._tray_icon is not None:
                try:
                    self._tray_icon.stop()
                except Exception:
                    pass


def run() -> None:
    cfg = config_mod.load_config()
    app = CompanionApp(cfg)
    app.run()


if __name__ == "__main__":
    run()
