"""resolve_bridge tests — a mocked Resolve object stands in for the real
scripting API (no live Resolve instance in tests, per SPEC.md's testing
requirements)."""

from __future__ import annotations

from ccsync_companion import resolve_bridge


class FakeMediaPoolItem:
    def __init__(self, file_path: str, name: str = "clip"):
        self._file_path = file_path
        self._name = name
        self.replace_calls: list[str] = []
        self.replace_result = True
        self.raise_on_replace = False

    def GetClipProperty(self):
        return {"File Path": self._file_path}

    def GetName(self):
        return self._name

    def ReplaceClip(self, new_path):
        if self.raise_on_replace:
            raise RuntimeError("boom")
        self.replace_calls.append(new_path)
        return self.replace_result


class FakeTimelineItem:
    def __init__(self, media_pool_item):
        self._media_pool_item = media_pool_item

    def GetMediaPoolItem(self):
        return self._media_pool_item


class FakeTimelineItemNoMedia(FakeTimelineItem):
    def __init__(self):
        super().__init__(None)


class FakeTimeline:
    def __init__(self, tracks: dict[str, dict[int, list]]):
        self._tracks = tracks  # {"video": {1: [items]}, "audio": {1: [items]}}

    def GetTrackCount(self, track_type):
        return len(self._tracks.get(track_type, {}))

    def GetItemListInTrack(self, track_type, track_index):
        return self._tracks.get(track_type, {}).get(track_index, [])


class FakeProject:
    def __init__(self, timeline):
        self._timeline = timeline

    def GetCurrentTimeline(self):
        return self._timeline


class FakeProjectManager:
    def __init__(self, project):
        self._project = project

    def GetCurrentProject(self):
        return self._project


class FakeResolve:
    def __init__(self, project_manager):
        self._pm = project_manager

    def GetProjectManager(self):
        return self._pm


def test_get_timeline_items_no_resolve(monkeypatch):
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)
    result = resolve_bridge.get_timeline_items()
    assert result["ok"] is False
    assert "not running" in result["message"]
    assert result["items"] == []


def test_get_timeline_items_no_project(monkeypatch):
    pm = FakeProjectManager(None)
    resolve = FakeResolve(pm)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)
    result = resolve_bridge.get_timeline_items()
    assert result["ok"] is False
    assert "no project" in result["message"]


def test_get_timeline_items_no_timeline(monkeypatch):
    project = FakeProject(None)
    pm = FakeProjectManager(project)
    resolve = FakeResolve(pm)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)
    result = resolve_bridge.get_timeline_items()
    assert result["ok"] is False
    assert "no timeline" in result["message"]


def test_get_timeline_items_skips_items_without_media_pool_item(monkeypatch):
    mpi = FakeMediaPoolItem(r"C:\Creators_Club\clip.mov")
    timeline = FakeTimeline(
        {
            "video": {1: [FakeTimelineItemNoMedia(), FakeTimelineItem(mpi)]},
            "audio": {},
        }
    )
    project = FakeProject(timeline)
    pm = FakeProjectManager(project)
    resolve = FakeResolve(pm)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.get_timeline_items()
    assert result["ok"] is True
    assert len(result["items"]) == 1
    assert result["items"][0]["file_path"] == r"C:\Creators_Club\clip.mov"
    assert result["items"][0]["track_type"] == "video"
    assert result["items"][0]["track_index"] == 1
    assert result["items"][0]["item_index"] == 1


def test_get_timeline_items_skips_empty_file_path(monkeypatch):
    mpi = FakeMediaPoolItem("")
    timeline = FakeTimeline({"video": {1: [FakeTimelineItem(mpi)]}, "audio": {}})
    project = FakeProject(timeline)
    resolve = FakeResolve(FakeProjectManager(project))
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.get_timeline_items()
    assert result["ok"] is True
    assert result["items"] == []


def test_get_timeline_items_covers_video_and_audio_tracks(monkeypatch):
    video_mpi = FakeMediaPoolItem(r"C:\Creators_Club\v.mov")
    audio_mpi = FakeMediaPoolItem(r"C:\Creators_Club\a.wav")
    timeline = FakeTimeline(
        {
            "video": {1: [FakeTimelineItem(video_mpi)]},
            "audio": {1: [FakeTimelineItem(audio_mpi)]},
        }
    )
    project = FakeProject(timeline)
    resolve = FakeResolve(FakeProjectManager(project))
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.get_timeline_items()
    track_types = {item["track_type"] for item in result["items"]}
    assert track_types == {"video", "audio"}


def test_replace_clip_ok():
    mpi = FakeMediaPoolItem(r"C:\old.mov")
    result = resolve_bridge.replace_clip(mpi, r"C:\new.mov")
    assert result["ok"] is True
    assert mpi.replace_calls == [r"C:\new.mov"]


def test_replace_clip_returns_false():
    mpi = FakeMediaPoolItem(r"C:\old.mov")
    mpi.replace_result = False
    result = resolve_bridge.replace_clip(mpi, r"C:\new.mov")
    assert result["ok"] is False
    assert "ReplaceClip returned False" in result["message"]


def test_replace_clip_raises_never_propagates():
    mpi = FakeMediaPoolItem(r"C:\old.mov")
    mpi.raise_on_replace = True
    result = resolve_bridge.replace_clip(mpi, r"C:\new.mov")
    assert result["ok"] is False
    assert "Resolve scripting error" in result["message"]


def test_replace_clip_none_media_pool_item():
    result = resolve_bridge.replace_clip(None, r"C:\new.mov")
    assert result["ok"] is False
