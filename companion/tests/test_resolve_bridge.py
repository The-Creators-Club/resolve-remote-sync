"""resolve_bridge tests — a mocked Resolve object stands in for the real
scripting API (no live Resolve instance in tests, per SPEC.md's testing
requirements)."""

from __future__ import annotations

import logging
import os
import threading
import time

import pytest

from ccsync_companion import resolve_bridge, resolve_prefs


@pytest.fixture(autouse=True)
def _no_python_home_leak():
    """GUARD. This file must not leave PYTHONHOME/PYTHON3HOME set.

    `_pin_frozen_python3_home()` SETS both in this very process, and
    `monkeypatch.delenv(name, raising=False)` on a variable that was not
    there records nothing to undo -- so the value the production code then
    writes leaks into every later test in the session. A leaked PYTHONHOME
    pointing at a pytest tmp dir makes ANY child interpreter fail to start:
    it broke the MAC-12 watch-probe's real-subprocess tests (2026-08-05) and
    test_consolidate's only escapes it because `consolidate` sorts before
    `resolve_bridge` -- with pytest-randomly ordering the files, it is a
    live flake.

    Autouse, so it tears down AFTER the test's own monkeypatch has undone
    what it can.
    """
    saved = {name: os.environ.get(name) for name in ("PYTHONHOME", "PYTHON3HOME")}
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


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


# -- has the bridge connected THIS SESSION? --------------------------------
#
# The follow-up items 17 and 19 both asked for. Neither incident was visible
# anywhere: the tray showed three healthy lanes and the log at the shipped
# INFO level showed nothing at all, so a bridge that had never once connected
# (MAC-10) looked exactly like one talking to a happy Resolve.


# Every test here starts from a bridge that has never connected --
# conftest's autouse _fresh_resolve_bridge_session sees to that, because the
# state is module-level and one process is one session.


def _connected_resolve():
    return FakeResolve(FakeProjectManager(FakeProject(FakeTimeline({}))))


def test_the_session_starts_out_never_polled():
    state = resolve_bridge.session_state()
    assert state["connected"] is None      # NOT False: "not checked yet"
    assert state["ever_connected"] is False
    assert state["reason"] == ""


def test_a_successful_enumeration_records_a_connection(monkeypatch):
    monkeypatch.setattr(resolve_bridge, "connect", _connected_resolve)
    resolve_bridge.get_timeline_items()
    assert resolve_bridge.session_state() == {
        "connected": True, "ever_connected": True, "reason": ""}


def test_a_bridge_that_has_never_connected_says_so(
    monkeypatch, resolve_process
):
    """MAC-10 exactly: the modules path was wrong, so the bridge never
    connected once in a session that ran for hours."""
    resolve_process(False)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)

    resolve_bridge.get_timeline_items()

    state = resolve_bridge.session_state()
    assert state["connected"] is False
    assert state["ever_connected"] is False
    assert state["reason"] == resolve_bridge.NOT_RUNNING_MESSAGE


def test_ever_connected_survives_resolve_going_away(
    monkeypatch, resolve_process
):
    """Connected and then gone is Resolve being closed (or item 19's script
    server dying); never connected at all is a broken install. The tray says
    different things about them, so the flag is sticky by design."""
    monkeypatch.setattr(resolve_bridge, "connect", _connected_resolve)
    resolve_bridge.get_timeline_items()

    resolve_process(True)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)
    resolve_bridge.get_timeline_items()

    state = resolve_bridge.session_state()
    assert state["connected"] is False
    assert state["ever_connected"] is True
    assert state["reason"] == resolve_bridge.NO_SCRIPTING_MESSAGE


def test_no_project_open_still_counts_as_connected(monkeypatch):
    """"no project open in Resolve" comes from a bridge that DID connect --
    Resolve is there, it just has nothing to show us."""
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(None)))
    result = resolve_bridge.get_timeline_items()
    assert result["ok"] is False
    assert resolve_bridge.session_state()["connected"] is True


def test_the_media_pool_walk_records_the_session_too(monkeypatch):
    """Both public enumerators share the one chokepoint, so tray → Scan whole
    project keeps the answer current even if the watcher never runs."""
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(None)))
    resolve_bridge.get_media_pool_items()
    assert resolve_bridge.session_state()["ever_connected"] is True


@pytest.mark.parametrize("message", [
    resolve_bridge.NOT_RUNNING_MESSAGE, resolve_bridge.NO_SCRIPTING_MESSAGE])
def test_is_disconnection_message_matches_the_two_no_connection_reasons(message):
    assert resolve_bridge.is_disconnection_message(message) is True


@pytest.mark.parametrize("message", [
    "", None, "no project open in Resolve", "no timeline open in Resolve",
    resolve_bridge._SCRIPTING_ERROR_MESSAGE])
def test_is_disconnection_message_ignores_a_connected_bridges_complaints(message):
    assert resolve_bridge.is_disconnection_message(message) is False


# -- the sweep must not starve the tray's message pump ----------------------
#
# Item 20. Every fusionscript call holds the GIL for its full native duration
# and the timeline sweep makes three or four PER CLIP, so a big project meant
# a 1-3 s GIL blackout every 3 s -- and pystray's win32 pump is a Python
# window procedure, which cannot process the WM_RBUTTONUP that opens the tray
# menu without the GIL. Right-click did nothing, or opened seconds late.


class _RecordingTime:
    """Stands in for resolve_bridge's `time`, recording sleeps.

    Patching the real `time.sleep` would do it for every other thread in the
    process too, for the duration of the test; delegating everything else
    keeps _resolve_process_present's monotonic() honest.
    """

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def __getattr__(self, name):
        return getattr(time, name)


def _timeline_of(n: int):
    mpis = [FakeMediaPoolItem(rf"C:\Creators_Club\{i:03d}.mov", name=f"{i:03d}")
            for i in range(n)]
    timeline = FakeTimeline(
        {"video": {1: [FakeTimelineItem(m) for m in mpis]}, "audio": {}}
    )
    return timeline, mpis


def test_the_timeline_sweep_yields_the_gil_every_k_clips(monkeypatch):
    n = 60
    timeline, _mpis = _timeline_of(n)
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(FakeProject(timeline))))
    clock = _RecordingTime()
    monkeypatch.setattr(resolve_bridge, "time", clock)

    result = resolve_bridge.get_timeline_items()

    # ...and the results are exactly what they were without the yields.
    assert result["ok"] is True
    assert [item["file_path"] for item in result["items"]] == [
        rf"C:\Creators_Club\{i:03d}.mov" for i in range(n)
    ]
    assert len(clock.sleeps) >= n // resolve_bridge._SWEEP_YIELD_EVERY
    assert set(clock.sleeps) == {resolve_bridge._SWEEP_YIELD_SECONDS}


def test_the_media_pool_walk_yields_across_the_whole_tree(monkeypatch):
    """One counter for the walk, not one per bin -- 24 clips in each of four
    bins must still yield, and a project of 25 single-clip bins must not
    sweep 25 clips without ever reaching the count."""
    n_bins, per_bin = 4, 24
    bins = [
        FakeFolder(clips=[FakeMediaPoolItem(rf"C:\CC\{b}-{i}.mov") for i in range(per_bin)],
                   name=f"bin{b}")
        for b in range(n_bins)
    ]
    root = FakeFolder(clips=[], subfolders=bins)
    project = FakeProject(media_pool=FakeMediaPool(root))
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(project)))
    clock = _RecordingTime()
    monkeypatch.setattr(resolve_bridge, "time", clock)

    result = resolve_bridge.get_media_pool_items()

    total = n_bins * per_bin
    assert len(result["items"]) == total
    assert len(clock.sleeps) >= total // resolve_bridge._SWEEP_YIELD_EVERY


# -- every Resolve entry point defers to an open tray menu ------------------


@pytest.mark.parametrize("name", [
    "get_timeline_items", "get_media_pool_items", "perform_insert",
    # The three that did not, before item 20: a LUT refresh or a fix-all's
    # ReplaceClip landing while the menu was open froze it exactly the way a
    # poll used to.
    "replace_clip", "refresh_lut_list", "link_proxy_media",
])
def test_every_resolve_entry_point_defers_while_the_tray_menu_is_open(monkeypatch, name):
    waits: list[int] = []
    monkeypatch.setattr(resolve_bridge.ui_state, "wait_while_menu_open",
                        lambda *a, **kw: waits.append(1))
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(None)))
    mpi = FakeMediaPoolItem(r"C:\Creators_Club\clip.mov")
    calls = {
        "get_timeline_items": lambda: resolve_bridge.get_timeline_items(),
        "get_media_pool_items": lambda: resolve_bridge.get_media_pool_items(),
        "perform_insert": lambda: resolve_bridge.perform_insert(r"C:\a.mov", 0, 10),
        "replace_clip": lambda: resolve_bridge.replace_clip(mpi, r"C:\new.mov"),
        "refresh_lut_list": lambda: resolve_bridge.refresh_lut_list(),
        "link_proxy_media": lambda: resolve_bridge.link_proxy_media(mpi, r"C:\p.mov"),
    }

    calls[name]()

    assert waits == [1]


# -- the poll cache: don't walk a timeline that hasn't changed --------------


class CountingMediaPoolItem(FakeMediaPoolItem):
    """Records GetClipProperty calls -- the per-clip fusionscript call the
    poll cache exists to avoid -- and can be relinked in place."""

    def __init__(self, file_path: str, name: str = "clip"):
        super().__init__(file_path, name)
        self.property_reads = 0

    def GetClipProperty(self):
        self.property_reads += 1
        return {"File Path": self._file_path}

    def relink(self, file_path: str) -> None:
        self._file_path = file_path


def _counting_timeline(*paths):
    mpis = [CountingMediaPoolItem(p) for p in paths]
    timeline = FakeTimeline(
        {"video": {1: [FakeTimelineItem(m) for m in mpis]}, "audio": {}}
    )
    return timeline, mpis


def _reads(mpis) -> int:
    return sum(m.property_reads for m in mpis)


def test_an_unchanged_timeline_is_not_walked_a_second_time(monkeypatch):
    timeline, mpis = _counting_timeline(r"C:\CC\a.mov", r"C:\CC\b.mov")
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(FakeProject(timeline))))

    first = resolve_bridge.poll_timeline_items()
    after_first = _reads(mpis)
    second = resolve_bridge.poll_timeline_items()

    assert after_first == 2                 # the full walk
    assert _reads(mpis) == after_first      # ...and not one per-clip call since
    assert second["ok"] is True
    assert second["items"] == first["items"]
    assert second["project_name"] == first["project_name"]
    # A fresh list: the watcher and the fixer own what they are handed.
    assert second["items"] is not first["items"]


def test_a_changed_clip_count_is_walked_immediately(monkeypatch):
    timeline, mpis = _counting_timeline(r"C:\CC\a.mov")
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(FakeProject(timeline))))
    resolve_bridge.poll_timeline_items()

    added = CountingMediaPoolItem(r"C:\CC\b.mov")
    timeline._tracks["video"][1].append(FakeTimelineItem(added))

    result = resolve_bridge.poll_timeline_items()
    assert [item["file_path"] for item in result["items"]] == [
        r"C:\CC\a.mov", r"C:\CC\b.mov"]


def test_an_in_place_relink_is_caught_by_the_safety_valve(monkeypatch):
    """The reason the cache cannot be trusted indefinitely: a relink changes
    no name and no count, and the watcher feeds the popup fixer."""
    timeline, mpis = _counting_timeline(r"F:\dead\a.mov")
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(FakeProject(timeline))))
    resolve_bridge.poll_timeline_items()          # the full walk
    mpis[0].relink(r"P:\Projects\2026\a.mov")

    cached = [
        resolve_bridge.poll_timeline_items()["items"][0]["file_path"]
        for _ in range(resolve_bridge._FULL_WALK_EVERY_POLLS - 1)
    ]
    assert set(cached) == {r"F:\dead\a.mov"}      # stale, by design

    valve = resolve_bridge.poll_timeline_items()
    assert valve["items"][0]["file_path"] == r"P:\Projects\2026\a.mov"


def test_a_disconnection_is_never_masked_by_the_cache(monkeypatch, resolve_process):
    timeline, _mpis = _counting_timeline(r"C:\CC\a.mov")
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(FakeProject(timeline))))
    assert resolve_bridge.poll_timeline_items()["ok"] is True

    resolve_process(True)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)

    result = resolve_bridge.poll_timeline_items()
    assert result["ok"] is False
    assert result["message"] == resolve_bridge.NO_SCRIPTING_MESSAGE
    assert result["items"] == []


def test_a_closed_timeline_is_never_masked_by_the_cache(monkeypatch):
    """Same rule one layer in: the fingerprint is gathered from the live
    project, so "no timeline open" reaches the caller as itself."""
    timeline, _mpis = _counting_timeline(r"C:\CC\a.mov")
    project = FakeProject(timeline)
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(project)))
    assert resolve_bridge.poll_timeline_items()["ok"] is True

    project._timeline = None
    result = resolve_bridge.poll_timeline_items()
    assert result["ok"] is False
    assert "no timeline" in result["message"]
    assert result["items"] == []


def test_the_scan_and_fixer_path_never_sees_the_cache(monkeypatch):
    """app.scan_whole_project and the fixer act on what they are shown, so
    the uncached entry point walks every time, however recently the watcher
    polled."""
    timeline, mpis = _counting_timeline(r"F:\dead\a.mov")
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(FakeProject(timeline))))
    resolve_bridge.poll_timeline_items()
    mpis[0].relink(r"P:\Projects\2026\a.mov")
    before = _reads(mpis)

    result = resolve_bridge.get_timeline_items()

    assert result["items"][0]["file_path"] == r"P:\Projects\2026\a.mov"
    assert _reads(mpis) == before + 1


def test_poll_timeline_items_is_the_only_caller_that_arms_the_cache(monkeypatch):
    seen: list[bool] = []
    monkeypatch.setattr(resolve_bridge, "_get_timeline_items_locked",
                        lambda allow_cached=False: seen.append(allow_cached) or
                        {"ok": True, "message": "", "items": [], "project_name": ""})

    resolve_bridge.poll_timeline_items()
    resolve_bridge.get_timeline_items()

    assert seen == [True, False]
