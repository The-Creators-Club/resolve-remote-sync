"""comp-resolve-1 (2026-08-21): "Scan whole project runs it now" has to be true.

When the unprompted canonical relink is rate-limited (one burst per project
per 15 minutes, item 9) the refused clips are HELD in _canon_relink_pending
and the log tells the editor to run Tray -> Advanced -> Scan whole project.
That scan only ever collected OUT_OF_TREE clips: it never drained the queue,
and both producers latch each path once per process, so the held clips stayed
spelled for this machine alone -- Media Offline for every other editor who
opens the project -- for the life of the companion.

Nothing here touches a real Resolve (conftest's _no_live_resolve) or Tk.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ccsync_companion import resolve_bridge
from ccsync_companion.app import CompanionApp


def _cfg(tmp_path, **overrides) -> dict[str, Any]:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    cfg = {
        "editor_name": "owen",
        "local_root": str(root),
        "canonical_prefix": "P:\\",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/Creators_Club",
        "active_project": "",
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "",
        "popup_enabled": False,
        "sync_enabled": False,
        "lane_b_enabled": False,
    }
    cfg.update(overrides)
    return cfg


class _RelinkableItem:
    def __init__(self, path):
        self._path = path
        self.replace_calls = []

    def GetClipProperty(self):
        return {"File Path": self._path}

    def ReplaceClip(self, new_path):
        self.replace_calls.append(new_path)
        self._path = new_path
        return None                     # Resolve returns None even on success


def _pool_item(root: Path, rel: str) -> dict:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return {"file_path": str(path), "media_pool_item": _RelinkableItem(str(path)),
            "clip_name": path.name, "resolve_project_name": "MyProject"}


def _join_canon_relink() -> None:
    for thread in threading.enumerate():
        if thread.name == "ccsync-canon-relink":
            thread.join(timeout=5)


def _app(tmp_path) -> CompanionApp:
    app = CompanionApp(_cfg(tmp_path))
    app._notify_tray = lambda *a, **kw: None
    return app


def test_scan_whole_project_runs_the_relinks_the_limiter_deferred(tmp_path, monkeypatch):
    root = tmp_path / "root"
    app = _app(tmp_path)

    first = [_pool_item(root, "B-roll/a.mov")]
    app._handle_non_canonical(first)
    _join_canon_relink()
    assert first[0]["media_pool_item"].replace_calls == ["P:\\B-roll\\a.mov"]

    # Five minutes later: refused by the limiter, held, and the log promises
    # the scan will run them.
    held = [_pool_item(root, "B-roll/b.mov"), _pool_item(root, "B-roll/c.mov")]
    app._handle_non_canonical(held)
    _join_canon_relink()
    assert [i["media_pool_item"].replace_calls for i in held] == [[], []]
    assert len(app._canon_relink_pending) == 2

    # The editor does what they were told.
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: {"ok": True, "items": [], "project_name": "MyProject"})
    app.scan_whole_project()
    _join_canon_relink()

    assert held[0]["media_pool_item"].replace_calls == ["P:\\B-roll\\b.mov"]
    assert held[1]["media_pool_item"].replace_calls == ["P:\\B-roll\\c.mov"]
    assert app._canon_relink_pending == []


def test_a_scan_with_nothing_held_still_says_the_media_is_in_the_tree(tmp_path, monkeypatch):
    """The drain is a side errand: it must not change what the scan reports
    about the media it found."""
    app = _app(tmp_path)
    notes: list[str] = []
    app._notify_tray = lambda msg, *a, **kw: notes.append(msg)
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: {"ok": True, "items": [], "project_name": "MyProject"})

    app.scan_whole_project()
    assert any("all media is in the tree" in note for note in notes)
