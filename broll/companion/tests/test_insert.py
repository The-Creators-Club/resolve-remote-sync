"""POST /insert: error paths and success path, with a fully mocked Resolve bridge.

Two layers are tested:
  - broll_companion.resolve_bridge.perform_insert directly, against fake
    Resolve scripting objects (bin find-or-create, reuse-by-filepath,
    AppendToTimeline payload shape).
  - broll_companion.server.build_insert_response / the live HTTP server,
    for the translate -> isfile -> resolve_bridge delegation and the
    documented error message text.
"""

from __future__ import annotations

import json
import os

import pytest

from broll_companion import resolve_bridge
from broll_companion import server as server_mod
from broll_companion.paths import MountNotConfiguredError, PathTraversalError


# ---------------------------------------------------------------------------
# Fake DaVinci Resolve scripting objects
# ---------------------------------------------------------------------------


class FakeMediaPoolItem:
    def __init__(self, name: str, file_path: str):
        self._name = name
        self._file_path = file_path

    def GetName(self):
        return self._name

    def GetClipProperty(self):
        return {"File Path": self._file_path}


class FakeBinFolder:
    def __init__(self, name: str):
        self._name = name
        self.clips: list = []

    def GetName(self):
        return self._name

    def GetClipList(self):
        return self.clips


class FakeRootFolder:
    def __init__(self):
        self.subfolders: list = []

    def GetSubFolderList(self):
        return self.subfolders


class FakeMediaPool:
    def __init__(self, root_folder: FakeRootFolder):
        self.root_folder = root_folder
        self.current_folder = None
        self.import_calls: list = []
        self.append_calls: list = []
        self.append_result = True

    def GetRootFolder(self):
        return self.root_folder

    def AddSubFolder(self, parent, name):
        folder = FakeBinFolder(name)
        parent.subfolders.append(folder)
        return folder

    def SetCurrentFolder(self, folder):
        self.current_folder = folder

    def ImportMedia(self, paths):
        self.import_calls.append(paths)
        item = FakeMediaPoolItem(
            name=os.path.basename(paths[0]), file_path=paths[0]
        )
        if self.current_folder is not None:
            self.current_folder.clips.append(item)
        return [item]

    def AppendToTimeline(self, clips):
        self.append_calls.append(clips)
        return self.append_result


class FakeTimeline:
    pass


class FakeProject:
    def __init__(self, media_pool, timeline):
        self._media_pool = media_pool
        self._timeline = timeline

    def GetCurrentTimeline(self):
        return self._timeline

    def GetMediaPool(self):
        return self._media_pool


class FakeProjectManager:
    def __init__(self, project):
        self._project = project

    def GetCurrentProject(self):
        return self._project


class FakeResolve:
    def __init__(self, project_manager):
        self._project_manager = project_manager

    def GetProjectManager(self):
        return self._project_manager


def _make_stack(timeline_present=True, project_present=True, append_result=True):
    root = FakeRootFolder()
    media_pool = FakeMediaPool(root)
    media_pool.append_result = append_result
    timeline = FakeTimeline() if timeline_present else None
    project = FakeProject(media_pool, timeline) if project_present else None
    project_manager = FakeProjectManager(project)
    resolve = FakeResolve(project_manager)
    return resolve, media_pool, root


# ---------------------------------------------------------------------------
# resolve_bridge.perform_insert unit tests
# ---------------------------------------------------------------------------


def test_perform_insert_resolve_not_running(monkeypatch):
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)
    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 10)
    assert result == {"ok": False, "message": "DaVinci Resolve is not running"}


def test_perform_insert_no_project_open(monkeypatch):
    resolve, _media_pool, _root = _make_stack(project_present=False)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)
    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 10)
    assert result == {"ok": False, "message": "no project open in Resolve"}


def test_perform_insert_no_timeline_open(monkeypatch):
    resolve, _media_pool, _root = _make_stack(timeline_present=False)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)
    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 10)
    assert result == {"ok": False, "message": "no timeline open — create one first"}


def test_perform_insert_creates_broll_bin_when_missing(monkeypatch):
    resolve, media_pool, root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    assert root.subfolders == []
    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 50)

    assert result["ok"] is True
    assert len(root.subfolders) == 1
    assert root.subfolders[0].GetName() == "B-Roll"


def test_perform_insert_reuses_existing_bin_across_calls(monkeypatch):
    resolve, media_pool, root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    resolve_bridge.perform_insert("Y:/broll/clip1.mov", 0, 10)
    resolve_bridge.perform_insert("Y:/broll/clip2.mov", 0, 10)

    # Only one "B-Roll" bin should ever be created.
    assert len(root.subfolders) == 1
    assert root.subfolders[0].GetName() == "B-Roll"


def test_perform_insert_imports_when_not_already_in_bin(monkeypatch):
    resolve, media_pool, _root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 50)

    assert result["ok"] is True
    assert media_pool.import_calls == [["Y:/broll/clip.mov"]]


def test_perform_insert_reuses_existing_mediapoolitem_by_file_path(monkeypatch):
    resolve, media_pool, root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    # Pre-populate the B-Roll bin with an already-imported clip.
    existing_bin = FakeBinFolder("B-Roll")
    existing_item = FakeMediaPoolItem("clip.mov", "Y:/broll/clip.mov")
    existing_bin.clips.append(existing_item)
    root.subfolders.append(existing_bin)

    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 100, 150)

    assert result["ok"] is True
    # No new import should have happened — the existing item was reused.
    assert media_pool.import_calls == []
    # No new bin should have been created either.
    assert len(root.subfolders) == 1


def test_perform_insert_append_payload_shape(monkeypatch):
    resolve, media_pool, _root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    resolve_bridge.perform_insert("Y:/broll/clip.mov", 24, 74)

    assert len(media_pool.append_calls) == 1
    payload = media_pool.append_calls[0]
    assert isinstance(payload, list) and len(payload) == 1
    item = payload[0]
    assert set(item.keys()) == {"mediaPoolItem", "startFrame", "endFrame"}
    assert item["startFrame"] == 24
    assert item["endFrame"] == 74
    assert isinstance(item["mediaPoolItem"], FakeMediaPoolItem)


def test_perform_insert_success_message_shape(monkeypatch):
    resolve, _media_pool, _root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 24, 74)

    assert result["ok"] is True
    assert result["message"] == "Inserted clip.mov (50 frames)"


def test_perform_insert_append_failure_reported(monkeypatch):
    resolve, _media_pool, _root = _make_stack(append_result=False)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 10)

    assert result == {"ok": False, "message": "failed to append clip to timeline"}


# ---------------------------------------------------------------------------
# server.build_insert_response: translate -> isfile -> resolve_bridge
# ---------------------------------------------------------------------------


def test_insert_mode_playhead_not_implemented():
    status, body = server_mod.build_insert_response(
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 0, "out_frame": 10, "mode": "playhead"},
        {"broll": "Y:/broll"},
    )
    assert status == 200
    assert body == {"ok": False, "message": "not implemented yet"}


def test_insert_no_mount_configured():
    status, body = server_mod.build_insert_response(
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 0, "out_frame": 10, "mode": "append"},
        {},
    )
    assert status == 200
    assert body["ok"] is False
    assert body["message"] == "no mount configured for share 'broll'"


def test_insert_path_traversal_is_http_400():
    status, body = server_mod.build_insert_response(
        {"share": "broll", "rel_path": "../../etc/passwd", "in_frame": 0, "out_frame": 10, "mode": "append"},
        {"broll": "Y:/broll"},
    )
    assert status == 400
    assert body["ok"] is False


def test_insert_file_not_found(tmp_path):
    mounts = {"broll": str(tmp_path).replace("\\", "/")}
    status, body = server_mod.build_insert_response(
        {"share": "broll", "rel_path": "missing_clip.mov", "in_frame": 0, "out_frame": 10, "mode": "append"},
        mounts,
    )
    assert status == 200
    assert body["ok"] is False
    assert "file not found at" in body["message"]
    assert "is the share mounted?" in body["message"]


def test_insert_success_delegates_to_resolve_bridge(tmp_path, monkeypatch):
    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"fake video bytes")
    mounts = {"broll": str(tmp_path).replace("\\", "/")}

    captured = {}

    def fake_perform_insert(local_path, in_frame, out_frame):
        captured["local_path"] = local_path
        captured["in_frame"] = in_frame
        captured["out_frame"] = out_frame
        return {"ok": True, "message": "Inserted clip.mov (10 frames)"}

    monkeypatch.setattr(server_mod.resolve_bridge, "perform_insert", fake_perform_insert)

    status, body = server_mod.build_insert_response(
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 5, "out_frame": 15, "mode": "append"},
        mounts,
    )

    assert status == 200
    assert body == {"ok": True, "message": "Inserted clip.mov (10 frames)"}
    assert captured["in_frame"] == 5
    assert captured["out_frame"] == 15
    assert os.path.basename(captured["local_path"]) == "clip.mov"


def test_insert_over_http_full_round_trip(live_server, tmp_path, monkeypatch):
    srv, client = live_server
    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"fake")
    srv.companion_config["mounts"] = {"broll": str(tmp_path).replace("\\", "/")}

    monkeypatch.setattr(
        server_mod.resolve_bridge,
        "perform_insert",
        lambda local_path, in_frame, out_frame: {
            "ok": True,
            "message": f"Inserted {os.path.basename(local_path)} ({out_frame - in_frame} frames)",
        },
    )

    status, _headers, body = client.post_json(
        "/insert",
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 0, "out_frame": 20, "fps": 25, "mode": "append"},
    )
    data = json.loads(body)
    assert status == 200
    assert data == {"ok": True, "message": "Inserted clip.mov (20 frames)"}


def test_insert_resolve_not_running_over_http(live_server, tmp_path, monkeypatch):
    srv, client = live_server
    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"fake")
    srv.companion_config["mounts"] = {"broll": str(tmp_path).replace("\\", "/")}

    monkeypatch.setattr(
        server_mod.resolve_bridge,
        "perform_insert",
        lambda *a, **kw: {"ok": False, "message": "DaVinci Resolve is not running"},
    )

    status, _headers, body = client.post_json(
        "/insert",
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 0, "out_frame": 20, "fps": 25, "mode": "append"},
    )
    data = json.loads(body)
    assert status == 200
    assert data == {"ok": False, "message": "DaVinci Resolve is not running"}
