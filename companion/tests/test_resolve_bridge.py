"""resolve_bridge tests — a mocked Resolve object stands in for the real
scripting API (no live Resolve instance in tests, per SPEC.md's testing
requirements)."""

from __future__ import annotations

import logging
import threading

import pytest

from ccsync_companion import resolve_bridge, resolve_prefs


@pytest.fixture
def resolve_process(monkeypatch):
    """Pin whether a Resolve process exists, and clear the probe cache.

    Without this, every disconnection test reads the machine it runs on --
    green or red depending on whether the developer happened to have Resolve
    open. Returns a setter so each test states its own world.
    """
    def _set(present: bool) -> None:
        monkeypatch.setattr(resolve_bridge, "_probe_cache", None)
        monkeypatch.setattr(resolve_prefs, "resolve_is_running", lambda: present)

    yield _set
    resolve_bridge._probe_cache = None


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


class FakeFolder:
    """Fake media pool folder/bin: a list of clips and a list of subfolders."""

    def __init__(self, clips=None, subfolders=None,
                 raise_on_clip_list=False, raise_on_subfolder_list=False, name=""):
        self._clips = clips or []
        self._subfolders = subfolders or []
        self._raise_on_clip_list = raise_on_clip_list
        self._raise_on_subfolder_list = raise_on_subfolder_list
        self._name = name

    def GetClipList(self):
        if self._raise_on_clip_list:
            raise RuntimeError("boom")
        return self._clips

    def GetSubFolderList(self):
        if self._raise_on_subfolder_list:
            raise RuntimeError("boom")
        return self._subfolders

    def GetName(self):
        return self._name


class FakeMediaPool:
    def __init__(self, root_folder):
        self._root_folder = root_folder

    def GetRootFolder(self):
        return self._root_folder


class FakeProject:
    def __init__(self, timeline=None, media_pool=None, name="MyProject"):
        self._timeline = timeline
        self._media_pool = media_pool
        self._name = name

    def GetCurrentTimeline(self):
        return self._timeline

    def GetMediaPool(self):
        return self._media_pool

    def GetName(self):
        return self._name


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


def test_get_timeline_items_no_resolve(monkeypatch, resolve_process):
    resolve_process(False)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)
    result = resolve_bridge.get_timeline_items()
    assert result["ok"] is False
    assert result["message"] == resolve_bridge.NOT_RUNNING_MESSAGE
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


def test_get_media_pool_items_no_resolve(monkeypatch, resolve_process):
    resolve_process(False)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)
    result = resolve_bridge.get_media_pool_items()
    assert result["ok"] is False
    assert result["message"] == resolve_bridge.NOT_RUNNING_MESSAGE
    assert result["items"] == []
    assert result["project_name"] == ""


def test_get_media_pool_items_no_project(monkeypatch):
    pm = FakeProjectManager(None)
    resolve = FakeResolve(pm)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)
    result = resolve_bridge.get_media_pool_items()
    assert result["ok"] is False
    assert "no project" in result["message"]
    assert result["items"] == []
    assert result["project_name"] == ""


def test_get_media_pool_items_no_media_pool(monkeypatch):
    project = FakeProject(media_pool=None)
    resolve = FakeResolve(FakeProjectManager(project))
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)
    result = resolve_bridge.get_media_pool_items()
    assert result["ok"] is False
    assert "media pool" in result["message"]
    assert result["items"] == []
    assert result["project_name"] == "MyProject"


def test_get_media_pool_items_no_root_folder(monkeypatch):
    media_pool = FakeMediaPool(root_folder=None)
    project = FakeProject(media_pool=media_pool)
    resolve = FakeResolve(FakeProjectManager(project))
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)
    result = resolve_bridge.get_media_pool_items()
    assert result["ok"] is False
    assert "root folder" in result["message"]
    assert result["items"] == []
    assert result["project_name"] == "MyProject"


def test_get_media_pool_items_walks_nested_bins(monkeypatch):
    clip_root = FakeMediaPoolItem(r"C:\Creators_Club\root_clip.mov", name="root_clip")
    clip_no_path = FakeMediaPoolItem("", name="timeline_or_compound")
    clip_nested = FakeMediaPoolItem(r"C:\Elsewhere\nested_clip.mov", name="nested_clip")

    leaf_folder = FakeFolder(clips=[clip_nested], name="Interviews")
    sub_folder = FakeFolder(clips=[], subfolders=[leaf_folder], name="Master")
    root_folder = FakeFolder(clips=[clip_root, clip_no_path], subfolders=[sub_folder])

    media_pool = FakeMediaPool(root_folder)
    project = FakeProject(media_pool=media_pool, name="CCT Creator Profiles")
    resolve = FakeResolve(FakeProjectManager(project))
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.get_media_pool_items()
    assert result["ok"] is True
    assert result["project_name"] == "CCT Creator Profiles"

    paths = {item["file_path"] for item in result["items"]}
    assert paths == {r"C:\Creators_Club\root_clip.mov", r"C:\Elsewhere\nested_clip.mov"}

    for item in result["items"]:
        assert item["resolve_project_name"] == "CCT Creator Profiles"
        assert "media_pool_item" in item
        assert "clip_name" in item

    by_path = {item["file_path"]: item for item in result["items"]}
    # Root-level clip: bin_path is "" (root folder itself excluded).
    assert by_path[r"C:\Creators_Club\root_clip.mov"]["bin_path"] == ""
    # Two bins deep: "/"-joined chain BELOW the root.
    assert by_path[r"C:\Elsewhere\nested_clip.mov"]["bin_path"] == "Master/Interviews"


def test_get_media_pool_items_bin_path_one_level_deep(monkeypatch):
    clip = FakeMediaPoolItem(r"C:\Creators_Club\a.mov", name="a")
    bin_folder = FakeFolder(clips=[clip], name="Interviews")
    root_folder = FakeFolder(clips=[], subfolders=[bin_folder])

    media_pool = FakeMediaPool(root_folder)
    project = FakeProject(media_pool=media_pool)
    resolve = FakeResolve(FakeProjectManager(project))
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.get_media_pool_items()
    assert result["items"][0]["bin_path"] == "Interviews"


def test_get_media_pool_items_clip_name_and_media_pool_item(monkeypatch):
    clip = FakeMediaPoolItem(r"C:\Creators_Club\clip.mov", name="clip")
    root_folder = FakeFolder(clips=[clip])
    media_pool = FakeMediaPool(root_folder)
    project = FakeProject(media_pool=media_pool)
    resolve = FakeResolve(FakeProjectManager(project))
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.get_media_pool_items()
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["clip_name"] == "clip"
    assert item["media_pool_item"] is clip


def test_get_media_pool_items_tolerates_clip_list_failure(monkeypatch):
    root_folder = FakeFolder(clips=[], raise_on_clip_list=True)
    media_pool = FakeMediaPool(root_folder)
    project = FakeProject(media_pool=media_pool)
    resolve = FakeResolve(FakeProjectManager(project))
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.get_media_pool_items()
    assert result["ok"] is True
    assert result["items"] == []


def test_get_media_pool_items_tolerates_subfolder_list_failure(monkeypatch):
    clip = FakeMediaPoolItem(r"C:\Creators_Club\clip.mov")
    root_folder = FakeFolder(clips=[clip], raise_on_subfolder_list=True)
    media_pool = FakeMediaPool(root_folder)
    project = FakeProject(media_pool=media_pool)
    resolve = FakeResolve(FakeProjectManager(project))
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.get_media_pool_items()
    assert result["ok"] is True
    assert len(result["items"]) == 1
    assert result["items"][0]["file_path"] == r"C:\Creators_Club\clip.mov"


def test_get_media_pool_items_recursion_depth_cap_on_self_referential_folder(monkeypatch):
    # A folder whose subfolder list includes itself must not infinite-loop.
    clip = FakeMediaPoolItem(r"C:\Creators_Club\clip.mov")
    folder = FakeFolder(clips=[clip])
    folder._subfolders = [folder]  # self-referential

    media_pool = FakeMediaPool(folder)
    project = FakeProject(media_pool=media_pool)
    resolve = FakeResolve(FakeProjectManager(project))
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.get_media_pool_items()
    assert result["ok"] is True
    # Same clip re-collected once per depth level up to the cap -- finite,
    # not an infinite loop / stack overflow.
    assert len(result["items"]) == resolve_bridge._MAX_MEDIA_POOL_DEPTH + 1
    assert all(item["file_path"] == r"C:\Creators_Club\clip.mov" for item in result["items"])


def test_replace_clip_ok():
    mpi = FakeMediaPoolItem(r"C:\old.mov")
    result = resolve_bridge.replace_clip(mpi, r"C:\new.mov")
    assert result["ok"] is True
    assert mpi.replace_calls == [r"C:\new.mov"]


def test_replace_clip_returns_false():
    # UX-16: the message is editor-facing (it reaches the fixer dialog and a
    # tray toast verbatim), so it must name an action, not an API return
    # value. "ReplaceClip returned False for C:\..." was the old text.
    mpi = FakeMediaPoolItem(r"C:\old.mov")
    mpi.replace_result = False
    result = resolve_bridge.replace_clip(mpi, r"C:\new.mov")
    assert result["ok"] is False
    assert "wouldn't relink" in result["message"]
    assert "Scan whole project" in result["message"]
    assert "ReplaceClip" not in result["message"]


def test_replace_clip_raises_never_propagates():
    mpi = FakeMediaPoolItem(r"C:\old.mov")
    mpi.raise_on_replace = True
    result = resolve_bridge.replace_clip(mpi, r"C:\new.mov")
    assert result["ok"] is False
    # UX-16: was f"Resolve scripting error: {exc}" -- the exception text is
    # now logged instead of shown.
    assert "Resolve didn't answer" in result["message"]
    assert "boom" not in result["message"]


def test_replace_clip_none_media_pool_item():
    result = resolve_bridge.replace_clip(None, r"C:\new.mov")
    assert result["ok"] is False


def test_pin_frozen_python3_home_sets_env_when_bundled(monkeypatch, tmp_path, windows):
    # `windows`: _pin_frozen_python3_home branches on sys.platform, and this
    # case is the WINDOWS branch -- python3.dll is a Windows artifact. On a
    # Mac the unfaked test took the darwin branch, found no libpython beside
    # it and returned early, so the assertions below saw the inherited value
    # (MAC-2a). The darwin branch has its own tests further down.
    (tmp_path / "python3.dll").write_bytes(b"")
    monkeypatch.setattr(resolve_bridge.sys, "_MEIPASS", str(tmp_path), raising=False)
    # An inherited value must be OVERWRITTEN, not honored -- inside the
    # frozen exe the only correct Python is the bundled one.
    monkeypatch.setenv("PYTHON3HOME", r"C:\SomeOther\Python313")
    monkeypatch.setenv("PYTHONHOME", r"C:\SomeOther\Python313")

    resolve_bridge._pin_frozen_python3_home()

    import os as _os
    assert _os.environ["PYTHON3HOME"] == str(tmp_path)
    assert _os.environ["PYTHONHOME"] == str(tmp_path)


def test_pin_frozen_python3_home_noop_without_bundled_dll(monkeypatch, tmp_path):
    monkeypatch.setattr(resolve_bridge.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.delenv("PYTHON3HOME", raising=False)
    monkeypatch.delenv("PYTHONHOME", raising=False)

    resolve_bridge._pin_frozen_python3_home()

    import os as _os
    assert "PYTHON3HOME" not in _os.environ
    assert "PYTHONHOME" not in _os.environ


def test_pin_frozen_python3_home_noop_when_not_frozen(monkeypatch):
    monkeypatch.delattr(resolve_bridge.sys, "_MEIPASS", raising=False)
    monkeypatch.delenv("PYTHON3HOME", raising=False)
    monkeypatch.delenv("PYTHONHOME", raising=False)

    resolve_bridge._pin_frozen_python3_home()

    import os as _os
    assert "PYTHON3HOME" not in _os.environ
    assert "PYTHONHOME" not in _os.environ


@pytest.mark.parametrize(
    "bundled", ["libpython3.12.dylib", "Python3"]
)
def test_pin_frozen_python3_home_pins_a_bundled_libpython_on_macos(monkeypatch, tmp_path, bundled):
    """fusionscript.so finds its Python the same way fusionscript.dll does."""
    (tmp_path / bundled).write_bytes(b"")
    monkeypatch.setattr(resolve_bridge.sys, "platform", "darwin")
    monkeypatch.setattr(resolve_bridge.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.delenv("PYTHON3HOME", raising=False)
    monkeypatch.delenv("PYTHONHOME", raising=False)

    resolve_bridge._pin_frozen_python3_home()

    import os as _os
    assert _os.environ["PYTHON3HOME"] == str(tmp_path)
    assert _os.environ["PYTHONHOME"] == str(tmp_path)


def test_pin_frozen_python3_home_leaves_a_macos_bundle_without_a_libpython_alone(
    monkeypatch, tmp_path
):
    """Fail-open: pinning PYTHONHOME at a directory with no Python in it
    breaks the interpreter far more thoroughly than an unpinned
    fusionscript ever could -- and python3.dll is never there on a Mac."""
    (tmp_path / "python3.dll").write_bytes(b"")
    monkeypatch.setattr(resolve_bridge.sys, "platform", "darwin")
    monkeypatch.setattr(resolve_bridge.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.delenv("PYTHON3HOME", raising=False)
    monkeypatch.delenv("PYTHONHOME", raising=False)

    resolve_bridge._pin_frozen_python3_home()

    import os as _os
    assert "PYTHON3HOME" not in _os.environ
    assert "PYTHONHOME" not in _os.environ


def test_macos_clip_path_flavor_is_logged_once(monkeypatch, caplog):
    """The open hardware question: does Resolve on a Mac hand back the stored
    canonical `P:\\...` string or the Mapped-Mount-resolved local path? One
    INFO line on the first successful poll answers it from the editor's log."""
    monkeypatch.setattr(resolve_bridge.sys, "platform", "darwin")
    monkeypatch.setattr(resolve_bridge, "_darwin_path_flavor_logged", False)
    items = [
        {"file_path": r"P:\Projects\2026\a.braw"},
        {"file_path": "/Volumes/T7/Creators_Club/Projects/2026/b.braw"},
    ]

    with caplog.at_level(logging.INFO, logger="ccsync.resolve"):
        resolve_bridge._log_darwin_clip_path_flavor(items)
        resolve_bridge._log_darwin_clip_path_flavor(items)

    lines = [r.getMessage() for r in caplog.records if "clip path" in r.getMessage()]
    assert len(lines) == 1
    assert "1 of 2" in lines[0]


def test_clip_path_flavor_log_is_darwin_only(monkeypatch, caplog):
    monkeypatch.setattr(resolve_bridge.sys, "platform", "win32")
    monkeypatch.setattr(resolve_bridge, "_darwin_path_flavor_logged", False)

    with caplog.at_level(logging.INFO, logger="ccsync.resolve"):
        resolve_bridge._log_darwin_clip_path_flavor([{"file_path": r"P:\a.braw"}])

    assert [r for r in caplog.records if "clip path" in r.getMessage()] == []
    assert resolve_bridge._darwin_path_flavor_logged is False


# -- connect() failed: which of the four reasons? --------------------------
#
# Live 2026-08-05, base rig: Resolve open on screen, its Fusion script server
# dead since launch ("Failed to connect to script server" x3 in
# davinci_resolve.log, never retried), and the companion reporting "DaVinci
# Resolve is not running" -- which sent an hour of debugging at the companion
# instead of at Resolve. The fix Resolve needed was a restart; the message
# named the one action that would not have helped.


@pytest.mark.parametrize(
    "entry_point", ["get_timeline_items", "get_media_pool_items"]
)
def test_a_running_resolve_that_wont_connect_says_so(
    monkeypatch, resolve_process, entry_point
):
    resolve_process(True)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)

    result = getattr(resolve_bridge, entry_point)()

    assert result["ok"] is False
    assert result["message"] == resolve_bridge.NO_SCRIPTING_MESSAGE
    # The actionable half: the user is told to restart the app, not to start it.
    assert "Quit Resolve and reopen it" in result["message"]
    assert result["message"] != resolve_bridge.NOT_RUNNING_MESSAGE


@pytest.mark.parametrize(
    "entry_point", ["get_timeline_items", "get_media_pool_items"]
)
def test_the_sentinel_never_reaches_a_caller(monkeypatch, resolve_process, entry_point):
    """_NOT_CONNECTED is an internal marker. It goes in the tray and the log if
    a public entry point ever forgets to translate it."""
    resolve_process(True)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)

    result = getattr(resolve_bridge, entry_point)()

    assert resolve_bridge._NOT_CONNECTED not in result["message"]


def test_the_process_probe_runs_with_the_api_lock_released(monkeypatch, resolve_process):
    """The reason the sentinel exists at all.

    The probe shells out (tasklist/pgrep, up to a 20 s timeout). Doing that
    under _API_LOCK would park the watcher, the tray and any fix-all behind a
    subprocess -- on every failed poll, i.e. every 3 s with Resolve shut.
    _API_LOCK is reentrant, so this has to be checked from another thread:
    from the calling thread it would re-acquire happily and prove nothing.
    """
    lock_was_free: list[bool] = []

    def probe_from_a_watching_thread():
        def attempt():
            acquired = resolve_bridge._API_LOCK.acquire(timeout=2.0)
            lock_was_free.append(acquired)
            if acquired:
                resolve_bridge._API_LOCK.release()

        watcher = threading.Thread(target=attempt)
        watcher.start()
        watcher.join(5.0)
        return True

    monkeypatch.setattr(resolve_bridge, "_probe_cache", None)
    monkeypatch.setattr(resolve_prefs, "resolve_is_running", probe_from_a_watching_thread)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)

    resolve_bridge.get_timeline_items()

    assert lock_was_free == [True]


def test_the_probe_is_cached_between_polls(monkeypatch, resolve_process):
    """A closed Resolve means a failed poll every 3 s. Each one must not cost
    a process spawn."""
    calls: list[int] = []

    def counting_probe():
        calls.append(1)
        return False

    monkeypatch.setattr(resolve_bridge, "_probe_cache", None)
    monkeypatch.setattr(resolve_prefs, "resolve_is_running", counting_probe)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)

    for _ in range(10):
        resolve_bridge.get_timeline_items()

    assert len(calls) == 1


def test_an_expired_cache_is_probed_again(monkeypatch, resolve_process):
    """Stale in the direction that matters: Resolve was running, the user quit
    it, and the message must stop telling them to restart it."""
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)
    resolve_process(True)
    assert resolve_bridge.describe_disconnection() == resolve_bridge.NO_SCRIPTING_MESSAGE

    # Age the cache past its TTL without sleeping through it.
    stamped_at, present = resolve_bridge._probe_cache
    monkeypatch.setattr(
        resolve_bridge,
        "_probe_cache",
        (stamped_at - resolve_bridge._PROBE_TTL_SECONDS - 1.0, present),
    )
    monkeypatch.setattr(resolve_prefs, "resolve_is_running", lambda: False)

    assert resolve_bridge.describe_disconnection() == resolve_bridge.NOT_RUNNING_MESSAGE


def test_an_inconclusive_probe_reports_the_running_case(monkeypatch, resolve_process):
    """resolve_is_running fails closed (True when it cannot tell) and this
    inherits that bias deliberately: "quit and reopen Resolve" still works for
    someone whose Resolve is shut, while "it is not running" is a dead end for
    someone looking straight at it."""
    def cannot_tell():
        raise RuntimeError("tasklist unavailable")

    monkeypatch.setattr(resolve_bridge, "_probe_cache", None)
    monkeypatch.setattr(resolve_prefs, "resolve_is_running", cannot_tell)

    assert resolve_bridge.describe_disconnection() == resolve_bridge.NO_SCRIPTING_MESSAGE
