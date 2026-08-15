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
        # Model the real API: ReplaceClip returns None EVEN ON SUCCESS (the
        # bug replace_clip used to have was trusting this value). Whether the
        # swap actually takes is `replace_applies`; the truth signal is the
        # File Path changing.
        self.replace_result = None
        self.replace_applies = True
        self.raise_on_replace = False

    def GetClipProperty(self):
        return {"File Path": self._file_path}

    def GetName(self):
        return self._name

    def ReplaceClip(self, new_path):
        if self.raise_on_replace:
            raise RuntimeError("boom")
        self.replace_calls.append(new_path)
        if self.replace_applies:
            self._file_path = new_path
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

    # -- mutation, for the import tests. Real bins grow.
    def add_clip(self, clip):
        self._clips.append(clip)
        return clip

    def add_subfolder(self, folder):
        self._subfolders.append(folder)
        return folder


class FakeMediaPool:
    """The media pool. Since the YouTube importer, it also creates bins and
    imports media -- with the current-folder bookkeeping ImportMedia actually
    obeys (it files into whatever SetCurrentFolder last named)."""

    def __init__(self, root_folder):
        self._root_folder = root_folder
        self._current = root_folder
        self.import_calls: list[list[str]] = []
        self.added_bins: list[tuple[str, str]] = []
        # Every SetCurrentFolder target, in order -- the restore-in-finally
        # contract is an assertion about this list.
        self.current_folder_names: list[str] = []
        # None = import everything asked for; a list = answer verbatim (an
        # empty one is Resolve refusing the whole batch).
        self.import_result = None
        self.raise_on_import = False
        # AddSubFolder returning None/False rather than raising is a thing
        # Resolve does on a locked project.
        self.add_subfolder_result = "make it"

    def GetRootFolder(self):
        return self._root_folder

    def GetCurrentFolder(self):
        return self._current

    def SetCurrentFolder(self, folder):
        self._current = folder
        self.current_folder_names.append(_folder_name(folder))
        return True

    def AddSubFolder(self, parent, name):
        self.added_bins.append((_folder_name(parent), name))
        if self.add_subfolder_result != "make it":
            return self.add_subfolder_result
        return parent.add_subfolder(FakeFolder(name=name))

    def ImportMedia(self, paths):
        self.import_calls.append(list(paths))
        if self.raise_on_import:
            raise RuntimeError("boom")
        if self.import_result is not None:
            return self.import_result
        items = []
        for path in paths:
            item = FakeMediaPoolItem(path, name=os.path.basename(path))
            self._current.add_clip(item)
            items.append(item)
        return items


def _folder_name(folder) -> str:
    return folder.GetName() if folder is not None else ""


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
    # Resolve returns None from ReplaceClip even on success -- ok must come
    # from the File Path actually changing, not the return value.
    mpi = FakeMediaPoolItem(r"C:\old.mov")
    assert mpi.replace_result is None
    result = resolve_bridge.replace_clip(mpi, r"C:\new.mov")
    assert result["ok"] is True
    assert mpi.replace_calls == [r"C:\new.mov"]


def test_replace_clip_already_linked_is_ok_without_a_call():
    mpi = FakeMediaPoolItem(r"C:\new.mov")
    result = resolve_bridge.replace_clip(mpi, r"C:\new.mov")
    assert result["ok"] is True
    assert mpi.replace_calls == []


def test_replace_clip_applies_on_a_retry(monkeypatch):
    # A momentarily-busy Resolve: the first call is swallowed, the second
    # takes. The old trust-the-return-value code reported failure here.
    clock = _RecordingTime()
    monkeypatch.setattr(resolve_bridge, "time", clock)
    mpi = FakeMediaPoolItem(r"C:\old.mov")
    mpi.replace_applies = False

    original = mpi.ReplaceClip

    def flaky(new_path):
        if len(mpi.replace_calls) >= 1:
            mpi.replace_applies = True
        return original(new_path)

    mpi.ReplaceClip = flaky
    result = resolve_bridge.replace_clip(mpi, r"C:\new.mov")
    assert result["ok"] is True
    assert len(mpi.replace_calls) == 2
    assert clock.sleeps  # backed off between attempts


def test_replace_clip_refused_when_path_never_changes(monkeypatch):
    # UX-16: the message is editor-facing (it reaches the fixer dialog and a
    # tray toast verbatim), so it must name an action, not an API return
    # value. "ReplaceClip returned False for C:\..." was the old text.
    clock = _RecordingTime()
    monkeypatch.setattr(resolve_bridge, "time", clock)
    mpi = FakeMediaPoolItem(r"C:\old.mov")
    mpi.replace_applies = False
    result = resolve_bridge.replace_clip(mpi, r"C:\new.mov")
    assert result["ok"] is False
    assert "wouldn't relink" in result["message"]
    assert "Scan whole project" in result["message"]
    assert "ReplaceClip" not in result["message"]


def test_replace_clip_raises_never_propagates(monkeypatch):
    clock = _RecordingTime()
    monkeypatch.setattr(resolve_bridge, "time", clock)
    mpi = FakeMediaPoolItem(r"C:\old.mov")
    mpi.raise_on_replace = True
    result = resolve_bridge.replace_clip(mpi, r"C:\new.mov")
    assert result["ok"] is False
    # UX-16: was f"Resolve scripting error: {exc}" -- the exception text is
    # now logged instead of shown. Every attempt raising means Resolve went
    # away, so the message stays the scripting-error one, not the refusal.
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
    # The actionable half -- and the ORDER matters (2026-08-12): a stale
    # companion client can wedge every new Resolve session, so a Resolve-only
    # restart provably cannot fix this state.
    assert "Restart the companion first" in result["message"]
    assert "reopen Resolve" in result["message"]
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

    # At least one wait, and always BEFORE the Resolve call. replace_clip
    # legitimately waits more than once: its retry loop re-defers before every
    # locked ReplaceClip attempt (and once for the pre-read of File Path).
    assert waits and set(waits) == {1}


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


# -- the YouTube auto-import bin path ---------------------------------------
#
# _ensure_bin_path and import_files_to_bin_path (resolve_bridge.py, bottom) are
# what youtube_import.py drives. Two properties carry the feature: a bin is
# FOUND rather than re-created (a duplicate CJK bin every cycle is the failure
# this was written around), and a clip already anywhere in the pool is never
# imported twice.


def _import_world(monkeypatch, project_name="Energy Transition", pool_clips=()):
    """A connected Resolve whose media pool holds `pool_clips` at the root."""
    root = FakeFolder(clips=[FakeMediaPoolItem(p, name=os.path.basename(p))
                             for p in pool_clips], name="Master")
    media_pool = FakeMediaPool(root)
    project = FakeProject(media_pool=media_pool, name=project_name)
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(project)))
    return media_pool, root


def test_ensure_bin_path_creates_every_missing_segment():
    root = FakeFolder(name="Master")
    pool = FakeMediaPool(root)

    folder = resolve_bridge._ensure_bin_path(pool, root, ["Youtube", "algal reef"])

    assert folder.GetName() == "algal reef"
    assert pool.added_bins == [("Master", "Youtube"), ("Youtube", "algal reef")]
    # ...and the tree really has them, one inside the other.
    youtube = root.GetSubFolderList()[0]
    assert youtube.GetName() == "Youtube"
    assert [f.GetName() for f in youtube.GetSubFolderList()] == ["algal reef"]


def test_ensure_bin_path_reuses_the_bins_it_already_made():
    root = FakeFolder(name="Master")
    pool = FakeMediaPool(root)

    first = resolve_bridge._ensure_bin_path(pool, root, ["Youtube", "algal reef"])
    second = resolve_bridge._ensure_bin_path(pool, root, ["Youtube", "algal reef"])

    assert second is first
    assert len(pool.added_bins) == 2, "the second pass must create nothing"


def test_ensure_bin_path_matches_direct_children_only():
    """A "Youtube" bin the editor keeps somewhere else in the pool must not
    capture the import -- music_worker.find_folder's whole-tree search is
    right for one well-known bin and wrong here."""
    stray = FakeFolder(name="Youtube")
    interviews = FakeFolder(subfolders=[stray], name="Interviews")
    root = FakeFolder(subfolders=[interviews], name="Master")
    pool = FakeMediaPool(root)

    folder = resolve_bridge._ensure_bin_path(pool, root, ["Youtube"])

    assert folder is not stray
    assert pool.added_bins == [("Master", "Youtube")]


def test_ensure_bin_path_returns_none_when_resolve_refuses():
    """AddSubFolder answers None/False on a locked project rather than
    raising. The caller reads None as "not this cycle", never as a file
    failure."""
    root = FakeFolder(name="Master")
    pool = FakeMediaPool(root)
    pool.add_subfolder_result = None

    assert resolve_bridge._ensure_bin_path(pool, root, ["Youtube"]) is None


def test_ensure_bin_path_matches_a_decomposed_cjk_name():
    """macOS hands out NFD filenames and Resolve stores what it is given, so
    the on-disk term and the bin name can be different STRINGS that render
    identically. Comparing them raw is a new duplicate bin every cycle."""
    import unicodedata

    composed = "\u85fb\u790e\u516c\u5712"                             # 藻礁公園
    decomposed = unicodedata.normalize("NFD", "\u30ac\u30fc\u30c9")   # NFD ガード
    root = FakeFolder(name="Master")
    pool = FakeMediaPool(root)

    resolve_bridge._ensure_bin_path(pool, root, [composed])
    resolve_bridge._ensure_bin_path(
        pool, root, [unicodedata.normalize("NFD", composed)])
    # ...and the same in the other direction: a bin made from an NFD name is
    # found again by its NFC spelling.
    resolve_bridge._ensure_bin_path(pool, root, [decomposed])
    resolve_bridge._ensure_bin_path(
        pool, root, [unicodedata.normalize("NFC", decomposed)])

    assert len(pool.added_bins) == 2, "one bin per visible name, not one per spelling"


@pytest.mark.parametrize("raw,expected", [
    ("algal reef", "algal reef"),
    ("  algal reef  ", "algal reef"),
    ("algal reef.", "algal reef"),
    ("algal/reef", "algal-reef"),
    ("algal\\reef", "algal-reef"),
    ("...", resolve_bridge.FALLBACK_BIN_NAME),
    ("", resolve_bridge.FALLBACK_BIN_NAME),
])
def test_bin_names_are_sanitised(raw, expected):
    assert resolve_bridge._safe_bin_name(raw) == expected


def test_import_files_to_bin_path_imports_into_the_term_bin(monkeypatch):
    pool, root = _import_world(monkeypatch)
    path = "P:\\Projects\\2026\\Youtube\\algal reef\\a.mp4"

    result = resolve_bridge.import_files_to_bin_path(
        [path], ("Youtube", "algal reef"),
        expected_project_name="Energy Transition",
    )

    assert result["ok"] is True
    assert result["imported"] == [path]
    assert result["skipped_existing"] == []
    assert result["failed"] == []
    assert pool.import_calls == [[path]]
    # Filed into the bin the segments name, not wherever the pool happened
    # to be pointing.
    youtube = root.GetSubFolderList()[0]
    term_bin = youtube.GetSubFolderList()[0]
    assert [c.GetName() for c in term_bin.GetClipList()] == ["a.mp4"]


def test_import_files_are_deduped_against_the_whole_pool(monkeypatch):
    """The editor dragged the clip into a bin of their own. It is still in the
    pool, so importing it again would give them two of it (the
    music_worker.existing_item rule)."""
    already = "P:\\Projects\\2026\\Youtube\\algal reef\\a.mp4"
    fresh = "P:\\Projects\\2026\\Youtube\\algal reef\\b.mp4"
    root = FakeFolder(name="Master")
    root.add_subfolder(FakeFolder(clips=[FakeMediaPoolItem(already)],
                                  name="My Cutdowns"))
    pool = FakeMediaPool(root)
    project = FakeProject(media_pool=pool, name="Energy Transition")
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(project)))

    result = resolve_bridge.import_files_to_bin_path(
        [already, fresh], ("Youtube", "algal reef"))

    assert result["skipped_existing"] == [already]
    assert result["imported"] == [fresh]
    assert pool.import_calls == [[fresh]]


def test_import_files_folds_a_second_spelling_into_the_dedupe(monkeypatch):
    """One file, two spellings. A clip the editor hand-imported through the
    P: drive sits in the pool CANONICALLY (`P:\\Projects\\...`); the importer
    hands this function local_root paths (ImportMedia cannot resolve "P:\\"
    on a Mac). _norm_path never folds those together on its own, so without
    the caller's alias fn the first scan of a Youtube folder that predates
    the feature would duplicate every clip already filed by hand."""
    from ccsync_companion import canon

    canonical = "P:\\Projects\\2026\\Youtube\\algal reef\\a.mp4"
    local = "C:\\Creators_Club\\Projects\\2026\\Youtube\\algal reef\\a.mp4"
    pool, _root = _import_world(monkeypatch, pool_clips=[canonical])

    result = resolve_bridge.import_files_to_bin_path(
        [local], ("Youtube", "algal reef"),
        path_alias_fn=lambda p: canon.canonical_to_local(
            p, "C:\\Creators_Club", "P:\\"),
    )

    assert result["ok"] is True
    assert result["skipped_existing"] == [local]
    assert result["imported"] == []
    assert pool.import_calls == []
    assert pool.added_bins == [], "a fully-deduped import must not leave a bin"


def test_import_stores_the_canonical_spelling(monkeypatch):
    r"""The systemic half of the 2026-08-12 Energy Transition incident:
    ImportMedia is handed local_root paths and STORED them, so every
    companion-imported clip was offline on the other editor's machine. With
    canonical_fn, the freshly imported item is relinked to the `P:\` spelling
    -- while the RESULT still reports the local path (the caller's `_done`
    bookkeeping is keyed on what it passed in)."""
    from ccsync_companion import canon

    local = "F:\\Creators_Club\\Projects\\2026\\Youtube\\algal reef\\a.mp4"
    pool, _root = _import_world(monkeypatch)

    result = resolve_bridge.import_files_to_bin_path(
        [local], ("Youtube", "algal reef"),
        canonical_fn=lambda p: canon.local_to_canonical(
            p, "F:\\Creators_Club", "P:\\"),
    )

    assert result["ok"] is True
    assert result["imported"] == [local]
    assert pool.import_calls == [[local]]
    youtube = _root_bin(pool, "Youtube")
    clip = youtube.GetSubFolderList()[0].GetClipList()[0]
    assert clip.GetClipProperty()["File Path"] == (
        "P:\\Projects\\2026\\Youtube\\algal reef\\a.mp4"
    )


def test_import_keeps_the_local_spelling_when_the_relink_is_refused(monkeypatch):
    """canonical_fn is best-effort: a refused ReplaceClip must not fail the
    import (the media is in the pool either way) and must leave the local
    spelling in place, which is exactly the pre-fix behaviour."""
    local = "F:\\Creators_Club\\Projects\\2026\\Youtube\\algal reef\\a.mp4"
    pool, _root = _import_world(monkeypatch)
    stubborn = FakeMediaPoolItem(local, name="a.mp4")
    stubborn.replace_applies = False
    pool.import_result = [stubborn]

    result = resolve_bridge.import_files_to_bin_path(
        [local], ("Youtube", "algal reef"),
        canonical_fn=lambda p: "P:\\Projects\\2026\\Youtube\\algal reef\\a.mp4",
    )

    assert result["ok"] is True
    assert result["imported"] == [local]
    assert stubborn.GetClipProperty()["File Path"] == local


def _root_bin(pool, name):
    for sub in pool.GetRootFolder().GetSubFolderList():
        if sub.GetName() == name:
            return sub
    raise AssertionError(f"no bin named {name}")


def test_find_existing_clip_matches_the_canonical_spelling():
    """After canonicalize-at-import, the stored path no longer equals the
    local spelling textually -- without the fold every repeat b-roll insert
    of the same file would file a duplicate media pool item."""
    from ccsync_companion import canon

    local = "F:\\Creators_Club\\Projects\\2026\\B-roll\\x.mov"
    stored = "P:\\Projects\\2026\\B-roll\\x.mov"
    bin_folder = FakeFolder(clips=[FakeMediaPoolItem(stored)], name="Archive")

    assert resolve_bridge._find_existing_clip(bin_folder, local) is None
    hit = resolve_bridge._find_existing_clip(
        bin_folder, local,
        canonical_fn=lambda p: canon.local_to_canonical(
            p, "F:\\Creators_Club", "P:\\"),
    )
    assert hit is bin_folder.GetClipList()[0]


def test_import_files_survives_a_raising_alias_fn(monkeypatch):
    """The alias is an OPTIMISATION (one more spelling in the dedupe set) and
    must never be able to take the import down with it."""
    fresh = "P:\\Projects\\2026\\Youtube\\algal reef\\b.mp4"
    # One unrelated clip already in the pool, so the alias fn really runs.
    pool, _root = _import_world(monkeypatch,
                                pool_clips=["P:\\Assets\\Stills\\logo.mp4"])

    def boom(_path):
        raise RuntimeError("translation failed")

    result = resolve_bridge.import_files_to_bin_path(
        [fresh], ("Youtube", "algal reef"), path_alias_fn=boom)

    assert result["ok"] is True
    assert result["imported"] == [fresh]


def test_import_files_makes_no_bin_when_everything_is_already_there(monkeypatch):
    already = "P:\\Projects\\2026\\Youtube\\algal reef\\a.mp4"
    pool, _root = _import_world(monkeypatch, pool_clips=[already])

    result = resolve_bridge.import_files_to_bin_path([already], ("Youtube", "algal reef"))

    assert result["ok"] is True
    assert result["skipped_existing"] == [already]
    assert pool.added_bins == [], "a no-op import must not leave an empty bin behind"


def test_import_files_restores_the_current_bin(monkeypatch):
    pool, root = _import_world(monkeypatch)
    editors_bin = root.add_subfolder(FakeFolder(name="Interviews"))
    pool.SetCurrentFolder(editors_bin)
    pool.current_folder_names.clear()

    resolve_bridge.import_files_to_bin_path(["P:\\a.mp4"], ("Youtube", "term"))

    assert pool.GetCurrentFolder() is editors_bin
    assert pool.current_folder_names[-1] == "Interviews"


def test_import_files_restores_the_current_bin_even_when_import_raises(monkeypatch):
    """The editor's media pool selection is theirs. A background job that
    parks it in a bin they never opened -- because ImportMedia threw -- is a
    side effect of something they never asked to see."""
    pool, root = _import_world(monkeypatch)
    editors_bin = root.add_subfolder(FakeFolder(name="Interviews"))
    pool.SetCurrentFolder(editors_bin)
    pool.raise_on_import = True

    result = resolve_bridge.import_files_to_bin_path(["P:\\a.mp4"], ("Youtube", "term"))

    assert result["ok"] is False
    assert pool.GetCurrentFolder() is editors_bin
    # A raise blames no file: nothing is proven wrong with the clip, and the
    # caller's three-strikes counter must not be spent on the bridge.
    assert result["failed"] == []


def test_import_files_refuses_when_the_project_changed(monkeypatch):
    """The scan and the import are seconds apart on a background thread, and
    an editor can close one project and open another in between."""
    pool, _root = _import_world(monkeypatch, project_name="Something Else")

    result = resolve_bridge.import_files_to_bin_path(
        ["P:\\a.mp4"], ("Youtube", "term"),
        expected_project_name="Energy Transition",
    )

    assert result["ok"] is False
    assert result["message"] == "project changed"
    assert pool.import_calls == []
    assert result["failed"] == []


def test_import_files_reports_a_refused_import_as_failed(monkeypatch):
    """ImportMedia answering [] is Resolve refusing the file (an unreadable
    container, a codec it will not take). Reported, never raised."""
    pool, _root = _import_world(monkeypatch)
    pool.import_result = []

    result = resolve_bridge.import_files_to_bin_path(["P:\\a.mp4"], ("Youtube", "term"))

    assert result["ok"] is False
    assert result["failed"] == ["P:\\a.mp4"]
    assert result["imported"] == []


def test_import_files_verifies_the_bin_before_calling_anything_failed(monkeypatch):
    """ImportMedia's return is not the whole truth -- it has been seen to
    answer with fewer items than it filed. Re-read the bin first, or a clip
    that IS in the project gets counted as a failure three times and then
    left alone for the session."""
    pool, _root = _import_world(monkeypatch)

    def _quiet_import(paths):
        pool.import_calls.append(list(paths))
        for path in paths:
            pool.GetCurrentFolder().add_clip(
                FakeMediaPoolItem(path, name=os.path.basename(path)))
        return []          # ...and says nothing about it

    pool.ImportMedia = _quiet_import

    result = resolve_bridge.import_files_to_bin_path(["P:\\a.mp4"], ("Youtube", "term"))

    assert result["ok"] is True
    assert result["imported"] == ["P:\\a.mp4"]
    assert result["failed"] == []


def test_import_files_with_no_paths_never_touches_resolve(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(resolve_bridge, "connect", lambda: calls.append(1))

    result = resolve_bridge.import_files_to_bin_path([], ("Youtube", "term"))

    assert result == {"ok": True, "message": "nothing to import",
                      "imported": [], "skipped_existing": [], "failed": []}
    assert calls == []


def test_import_files_explains_a_closed_resolve(monkeypatch, resolve_process):
    resolve_process(False)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)

    result = resolve_bridge.import_files_to_bin_path(["P:\\a.mp4"], ("Youtube", "term"))

    assert result["ok"] is False
    assert result["message"] == resolve_bridge.NOT_RUNNING_MESSAGE
    assert result["failed"] == []


def test_import_files_defers_while_the_tray_menu_is_open(monkeypatch):
    waits: list[int] = []
    monkeypatch.setattr(resolve_bridge.ui_state, "wait_while_menu_open",
                        lambda *a, **kw: waits.append(1))
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(None)))

    resolve_bridge.import_files_to_bin_path(["P:\\a.mp4"], ("Youtube", "term"))

    assert waits == [1]


# -- the b-roll insert against a project Resolve will not add a bin to ------


def test_a_project_that_refuses_the_bin_says_so_instead_of_didnt_answer(monkeypatch):
    """COMP-MEDIA-8: AddSubFolder returns None/False on a locked project
    rather than raising, and BROLL_BIN_PATH is TWO segments -- so the raw
    answer was fed back in as the next root and the walk dereferenced None.
    The editor was told "Resolve didn't answer. Make sure a project is open"
    with their project open, about a bin Resolve had refused."""
    root = FakeFolder(name="Master")
    pool = FakeMediaPool(root)
    pool.add_subfolder_result = None
    project = FakeProject(
        timeline=FakeTimeline({"video": {1: []}, "audio": {1: []}}), media_pool=pool
    )
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: FakeResolve(FakeProjectManager(project)))

    result = resolve_bridge.perform_insert(r"P:\Assets\B-roll Archive\a.mov", 0, 10)

    assert result["ok"] is False
    assert result["message"] == resolve_bridge.BIN_REFUSED_MESSAGE
    assert result["message"] != resolve_bridge._SCRIPTING_ERROR_MESSAGE
    assert pool.import_calls == [], "nothing was imported into a bin that isn't there"


def test_find_or_create_bin_returns_none_when_resolve_refuses():
    """The contract _ensure_bin_path already had, two hundred lines below."""
    root = FakeFolder(name="Master")
    pool = FakeMediaPool(root)
    pool.add_subfolder_result = False

    assert resolve_bridge._find_or_create_bin(pool, root, "B-Roll") is None


# -- a fusionscript call that does not come back (COMP-MEDIA-9) -------------


@pytest.fixture(autouse=True)
def _clean_bridge_activity():
    """The in-flight record is module-global, like the session state and the
    process probe cache above it."""
    resolve_bridge.reset_bridge_activity()
    yield
    resolve_bridge.reset_bridge_activity()


def test_the_call_in_flight_is_readable_without_touching_the_bridge():
    """The thread that knows a call is wedged is the one that cannot say so,
    so the fact has to be readable from outside -- cheaply, with no lock on
    the bridge and no probe (the tray render path's rule)."""
    assert resolve_bridge.bridge_activity() == {}

    with resolve_bridge._bridge_call("ImportMedia"):
        activity = resolve_bridge.bridge_activity()

    assert activity["call"] == "ImportMedia"
    assert activity["seconds"] >= 0.0
    assert resolve_bridge.bridge_activity() == {}


def test_a_nested_call_keeps_the_outer_name_and_does_not_deadlock():
    """Every public function calls connect() with the lock already held; the
    RLock lets it through and the OUTER call is the one worth naming."""
    with resolve_bridge._bridge_call("perform_insert"):
        with resolve_bridge._bridge_call("connect"):
            assert resolve_bridge.bridge_activity()["call"] == "perform_insert"
        assert resolve_bridge.bridge_activity()["call"] == "perform_insert"

    assert resolve_bridge.bridge_activity() == {}


def test_a_wedged_call_is_named_in_the_log_by_the_thread_stuck_behind_it(
        monkeypatch, caplog):
    """The failure this exists for: P: drops mid-import, ImportMedia never
    returns, and the watcher, the media-tree thread and the tray all park on
    _API_LOCK with nothing in the log to say why. Nothing here can interrupt
    a native call -- but the wait is now attributable."""
    monkeypatch.setattr(resolve_bridge, "BRIDGE_WEDGE_SECONDS", 0.02)
    held = threading.Event()
    release = threading.Event()

    def _wedged():
        with resolve_bridge._bridge_call("ImportMedia"):
            held.set()
            release.wait(10.0)

    stuck = threading.Thread(target=_wedged, daemon=True)
    stuck.start()
    assert held.wait(5.0)
    threading.Timer(0.2, release.set).start()

    with caplog.at_level(logging.WARNING, logger="ccsync.resolve"):
        with resolve_bridge._bridge_call("poll_timeline_items"):
            pass
    stuck.join(timeout=5.0)

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    # ONE line per episode, not one per timeout per waiting thread: four
    # threads behind a wedge would otherwise flood the rotating log.
    assert len(warnings) == 1
    assert "ImportMedia" in warnings[0]
    assert "poll_timeline_items" in warnings[0]


def test_a_public_entry_point_names_itself_while_it_holds_the_bridge(
        monkeypatch, resolve_process):
    resolve_process(False)
    seen: dict = {}

    def _connect():
        seen["activity"] = resolve_bridge.bridge_activity()
        return None

    monkeypatch.setattr(resolve_bridge, "connect", _connect)
    resolve_bridge.get_media_pool_items()

    assert seen["activity"]["call"] == "get_media_pool_items"
    assert resolve_bridge.bridge_activity() == {}
