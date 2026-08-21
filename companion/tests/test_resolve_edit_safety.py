"""Save point, journal and undo around every media-pool mutation
(COMMERCIAL_READINESS.md item 9, 2026-08-17).

The mocked-Resolve rule of test_resolve_bridge.py applies: no live Resolve,
and the fakes here model the two behaviours that make this hard -- ReplaceClip
returning None even on success, and ExportProject being absent or refusing.
"""

from __future__ import annotations

import pytest

from ccsync_companion import resolve_bridge, resolve_journal


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    resolve_journal.reset_for_tests()
    monkeypatch.setattr(resolve_bridge, "_project_name_cache", None, raising=False)
    # The tray-menu courtesy wait is irrelevant here and touches ui_state.
    monkeypatch.setattr(resolve_bridge.ui_state, "wait_while_menu_open",
                        lambda *a, **kw: None)
    yield
    resolve_journal.reset_for_tests()


class Item:
    def __init__(self, path: str, name: str = "A001", proxy: str = ""):
        self.path = path
        self.name = name
        self.proxy = proxy
        self.link_calls: list[str] = []
        self.unlinked = 0
        self.link_result = True
        self.has_unlink = True

    def GetClipProperty(self):
        return {"File Path": self.path, "Proxy Media Path": self.proxy}

    def GetName(self):
        return self.name

    def ReplaceClip(self, new_path):
        self.path = new_path
        return None  # Resolve returns None even on success

    def LinkProxyMedia(self, path):
        self.link_calls.append(path)
        if self.link_result:
            self.proxy = path
        return self.link_result

    def UnlinkProxyMedia(self):
        if not self.has_unlink:
            raise AttributeError("no such method")
        self.unlinked += 1
        self.proxy = ""
        return True


class Manager:
    def __init__(self, project, export="ok"):
        self._project = project
        self.saves = 0
        self.exports: list[tuple] = []
        self._export = export

    def GetCurrentProject(self):
        return self._project

    def SaveProject(self):
        self.saves += 1
        return True

    def ExportProject(self, name, path, stills):
        self.exports.append((name, path, stills))
        if self._export == "raise":
            raise RuntimeError("collaboration project")
        if self._export == "refuse":
            return False
        # A real export writes the file; the code checks that it exists.
        import pathlib
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(path).write_bytes(b"drp")
        return True


class ManagerWithoutExport(Manager):
    ExportProject = None


class Project:
    def __init__(self, name="FF5"):
        self._name = name

    def GetName(self):
        return self._name


class Resolve:
    def __init__(self, manager):
        self._manager = manager

    def GetProjectManager(self):
        return self._manager


def _connect(monkeypatch, manager):
    monkeypatch.setattr(resolve_bridge, "connect", lambda: Resolve(manager))
    return manager


class TestSavePoint:
    def test_replace_clip_saves_and_exports_before_it_mutates(self, monkeypatch):
        manager = _connect(monkeypatch, Manager(Project("FF5")))
        item = Item(r"F:\Creators_Club\a.mov")

        result = resolve_bridge.replace_clip(item, r"P:\a.mov", tries=1,
                                             source="auto-canonical")

        assert result["ok"] is True
        assert manager.saves == 1
        assert manager.exports and manager.exports[0][0] == "FF5"
        assert manager.exports[0][2] is False  # no stills/LUTs in a rollback copy

    def test_the_save_point_is_taken_once_per_burst_not_once_per_clip(self, monkeypatch):
        manager = _connect(monkeypatch, Manager(Project("FF5")))
        for i in range(5):
            resolve_bridge.replace_clip(Item(rf"F:\a{i}.mov"), rf"P:\a{i}.mov", tries=1)
        assert manager.saves == 1

    def test_an_export_that_is_refused_does_not_stop_the_relink(self, monkeypatch):
        manager = _connect(monkeypatch, Manager(Project("FF5"), export="refuse"))
        item = Item(r"F:\a.mov")
        assert resolve_bridge.replace_clip(item, r"P:\a.mov", tries=1)["ok"] is True
        assert item.path == r"P:\a.mov"

    def test_an_api_build_with_no_ExportProject_does_not_stop_the_relink(self, monkeypatch):
        _connect(monkeypatch, ManagerWithoutExport(Project("FF5")))
        item = Item(r"F:\a.mov")
        assert resolve_bridge.replace_clip(item, r"P:\a.mov", tries=1)["ok"] is True

    def test_an_export_that_raises_does_not_stop_the_relink(self, monkeypatch):
        _connect(monkeypatch, Manager(Project("FF5"), export="raise"))
        item = Item(r"F:\a.mov")
        assert resolve_bridge.replace_clip(item, r"P:\a.mov", tries=1)["ok"] is True

    def test_the_journal_still_records_when_the_export_failed(self, monkeypatch):
        # THE POINT of the journal: it is the guarantee that survives an
        # export Resolve will not give us.
        _connect(monkeypatch, ManagerWithoutExport(Project("FF5")))
        resolve_bridge.replace_clip(Item(r"F:\a.mov"), r"P:\a.mov", tries=1,
                                    source="fix-all")
        entries = resolve_journal.read_session(
            resolve_journal.latest_session("FF5"))["entries"]
        assert entries[0]["old"] == r"F:\a.mov"
        assert entries[0]["new"] == r"P:\a.mov"
        assert entries[0]["source"] == "fix-all"


class TestJournalledMutations:
    def test_a_relink_that_did_not_take_is_not_journalled(self, monkeypatch):
        _connect(monkeypatch, Manager(Project("FF5")))

        class Stubborn(Item):
            def ReplaceClip(self, new_path):
                return None  # never applies

        assert resolve_bridge.replace_clip(Stubborn(r"F:\a.mov"), r"P:\a.mov",
                                           tries=1)["ok"] is False
        # The save point is still recorded -- it happened -- but the entry
        # naming an inverse edit must not be, or undo would ReplaceClip a
        # clip that was never moved.
        assert resolve_journal.read_session(
            resolve_journal.latest_session("FF5"))["entries"] == []

    def test_a_proxy_repoint_records_the_old_proxy_and_the_clip(self, monkeypatch):
        _connect(monkeypatch, Manager(Project("FF5")))
        item = Item(r"P:\x\A001.braw", proxy=r"G:\Temp\A001.mov")
        assert resolve_bridge.link_proxy_media(
            item, r"P:\x\Proxy\A001.mov", source="auto-proxy-relink")["ok"] is True
        entry = resolve_journal.read_session(
            resolve_journal.latest_session("FF5"))["entries"][0]
        assert entry["kind"] == resolve_journal.KIND_LINK_PROXY
        assert entry["old"] == r"G:\Temp\A001.mov"
        assert entry["clip_path"] == r"P:\x\A001.braw"

    def test_journal_false_writes_nothing(self, monkeypatch):
        # The undo replay uses this: replaying an undo as a new edit would
        # make the next undo redo it.
        _connect(monkeypatch, Manager(Project("FF5")))
        resolve_bridge.replace_clip(Item(r"F:\a.mov"), r"P:\a.mov", tries=1,
                                    journal=False)
        assert resolve_journal.latest_session("FF5") is None


class TestUndo:
    def _pool(self, monkeypatch, items):
        monkeypatch.setattr(resolve_bridge, "get_media_pool_items", lambda: {
            "ok": True, "message": "", "project_name": "FF5",
            "items": [{"file_path": i.path, "clip_name": i.name,
                       "media_pool_item": i} for i in items],
        })

    def test_it_puts_every_clip_back(self, monkeypatch):
        _connect(monkeypatch, Manager(Project("FF5")))
        items = [Item(rf"F:\a{i}.mov", name=f"A{i}") for i in range(3)]
        for i, item in enumerate(items):
            resolve_bridge.replace_clip(item, rf"P:\a{i}.mov", tries=1,
                                        source="auto-canonical")
        self._pool(monkeypatch, items)

        result = resolve_bridge.undo_last_relink()

        assert result["undone"] == 3
        assert [i.path for i in items] == [r"F:\a0.mov", r"F:\a1.mov", r"F:\a2.mov"]

    def test_a_clip_touched_twice_ends_up_where_the_burst_found_it(self, monkeypatch):
        _connect(monkeypatch, Manager(Project("FF5")))
        item = Item(r"F:\a.mov")
        resolve_bridge.replace_clip(item, r"T:\a.mov", tries=1)
        resolve_bridge.replace_clip(item, r"P:\a.mov", tries=1)
        self._pool(monkeypatch, [item])

        assert resolve_bridge.undo_last_relink()["undone"] == 2
        assert item.path == r"F:\a.mov"

    def test_a_clip_that_left_the_media_pool_is_skipped_not_guessed_at(self, monkeypatch):
        _connect(monkeypatch, Manager(Project("FF5")))
        item = Item(r"F:\a.mov")
        resolve_bridge.replace_clip(item, r"P:\a.mov", tries=1)
        self._pool(monkeypatch, [])

        result = resolve_bridge.undo_last_relink()
        assert result["undone"] == 0 and result["skipped"] == 1

    def test_a_proxy_that_was_attached_to_nothing_is_detached_again(self, monkeypatch):
        _connect(monkeypatch, Manager(Project("FF5")))
        item = Item(r"P:\x\A001.braw", proxy="")
        resolve_bridge.link_proxy_media(item, r"P:\x\Proxy\A001.mov")
        self._pool(monkeypatch, [item])

        assert resolve_bridge.undo_last_relink()["undone"] == 1
        assert item.unlinked == 1 and item.proxy == ""

    def test_a_stale_proxy_path_is_put_back(self, monkeypatch):
        _connect(monkeypatch, Manager(Project("FF5")))
        item = Item(r"P:\x\A001.braw", proxy=r"G:\old\A001.mov")
        resolve_bridge.link_proxy_media(item, r"P:\x\Proxy\A001.mov")
        self._pool(monkeypatch, [item])

        assert resolve_bridge.undo_last_relink()["undone"] == 1
        assert item.proxy == r"G:\old\A001.mov"

    def test_with_no_journal_it_says_so_rather_than_doing_anything(self, monkeypatch):
        _connect(monkeypatch, Manager(Project("FF5")))
        result = resolve_bridge.undo_last_relink()
        assert result["ok"] is False and result["undone"] == 0
        assert "not changed any clip paths" in result["message"]

    def test_the_undo_itself_is_not_journalled(self, monkeypatch):
        _connect(monkeypatch, Manager(Project("FF5")))
        item = Item(r"F:\a.mov")
        resolve_bridge.replace_clip(item, r"P:\a.mov", tries=1)
        before = len(resolve_journal.sessions("FF5"))
        self._pool(monkeypatch, [item])
        resolve_bridge.undo_last_relink()
        entries = resolve_journal.read_session(
            resolve_journal.latest_session("FF5"))["entries"]
        assert len(resolve_journal.sessions("FF5")) == before
        assert len(entries) == 1


def _lock_is_held() -> bool:
    """Is `_API_LOCK` held by anybody? Asked from ANOTHER thread on purpose.

    _API_LOCK is reentrant, so the thread inside the call would be let
    straight back in and would always answer "free"; a second thread's
    non-blocking acquire is the only honest probe.
    """
    import threading

    answers: list[bool] = []

    def probe() -> None:
        acquired = resolve_bridge._API_LOCK.acquire(blocking=False)
        answers.append(acquired)
        if acquired:
            resolve_bridge._API_LOCK.release()

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join(10)
    return bool(answers) and not answers[0]


class LockWatchingItem(Item):
    """Records every fusionscript-side call made with _API_LOCK NOT held.

    The module's invariant (resolve_bridge.py's header): a call into
    fusionscript.dll made concurrently with another one has faulted
    0xc0000005 and taken the windowed companion down with no log at all.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unlocked_calls: list[str] = []

    def _note(self, name: str) -> None:
        if not _lock_is_held():
            self.unlocked_calls.append(name)

    def GetName(self):
        self._note("GetName")
        return super().GetName()

    def GetClipProperty(self):
        self._note("GetClipProperty")
        return super().GetClipProperty()

    def ReplaceClip(self, new_path):
        self._note("ReplaceClip")
        return super().ReplaceClip(new_path)

    def LinkProxyMedia(self, path):
        self._note("LinkProxyMedia")
        return super().LinkProxyMedia(path)

    def UnlinkProxyMedia(self):
        self._note("UnlinkProxyMedia")
        return super().UnlinkProxyMedia()


class TestEveryNativeCallIsSerialised:
    """comp-resolve-3, 2026-08-21: the JOURNAL bookkeeping (GetName, and the
    proxy path's GetClipProperty) used to run after the locked block closed,
    on the FIX ALL worker, while the watcher polled under the lock."""

    def test_a_journalled_relink_makes_no_call_outside_the_lock(self, monkeypatch):
        _connect(monkeypatch, Manager(Project("FF5")))
        item = LockWatchingItem(r"F:\a.mov")

        assert resolve_bridge.replace_clip(item, r"P:\a.mov", tries=1,
                                           source="fix-all")["ok"] is True
        assert item.unlocked_calls == []
        # ...and the name still reached the journal.
        entry = resolve_journal.read_session(
            resolve_journal.latest_session("FF5"))["entries"][0]
        assert entry["clip"] == "A001"

    def test_a_journalled_proxy_repoint_makes_no_call_outside_the_lock(self, monkeypatch):
        _connect(monkeypatch, Manager(Project("FF5")))
        item = LockWatchingItem(r"P:\x\A001.braw", proxy=r"G:\old\A001.mov")

        assert resolve_bridge.link_proxy_media(
            item, r"P:\x\Proxy\A001.mov", source="auto-proxy-relink")["ok"] is True
        assert item.unlocked_calls == []
        entry = resolve_journal.read_session(
            resolve_journal.latest_session("FF5"))["entries"][0]
        assert entry["clip"] == "A001"
        assert entry["clip_path"] == r"P:\x\A001.braw"

    def test_an_unjournalled_relink_makes_no_call_outside_the_lock(self, monkeypatch):
        # The undo replay's path (journal=False).
        _connect(monkeypatch, Manager(Project("FF5")))
        item = LockWatchingItem(r"P:\a.mov")
        assert resolve_bridge.replace_clip(item, r"F:\a.mov", tries=1,
                                           journal=False)["ok"] is True
        assert item.unlocked_calls == []


class TestUndoBelongsToTheOpenProject:
    """comp-resolve-2, 2026-08-21: undo replayed the newest journal of ANY
    project against whatever was open, matching clips by file path alone --
    and every project shares the paths under Assets."""

    def _pool(self, monkeypatch, items, project):
        monkeypatch.setattr(resolve_bridge, "get_media_pool_items", lambda: {
            "ok": True, "message": "", "project_name": project,
            "items": [{"file_path": i.path, "clip_name": i.name,
                       "media_pool_item": i} for i in items],
        })

    def test_another_projects_journal_never_touches_the_open_project(self, monkeypatch):
        manager = _connect(monkeypatch, Manager(Project("FF5")))
        # FF5 canonicalises a shared music bed.
        bed = Item(r"F:\Creators_Club\Assets\Music\bed.wav", name="bed")
        resolve_bridge.replace_clip(bed, r"P:\Assets\Music\bed.wav", tries=1,
                                    source="auto-canonical")

        # The editor opens a DIFFERENT project that uses the same bed, and
        # presses Undo meaning to revert something there.
        manager._project = Project("Energy Transition")
        same_bed = Item(r"P:\Assets\Music\bed.wav", name="bed")
        self._pool(monkeypatch, [same_bed], project="Energy Transition")

        result = resolve_bridge.undo_last_relink()

        assert result["ok"] is False
        assert result["undone"] == 0
        assert same_bed.path == r"P:\Assets\Music\bed.wav"
        assert "FF5" in result["message"]
        assert "Energy Transition" in result["message"]

    def test_a_journal_named_explicitly_is_refused_for_the_wrong_project(self, monkeypatch):
        manager = _connect(monkeypatch, Manager(Project("FF5")))
        item = Item(r"F:\a.mov")
        resolve_bridge.replace_clip(item, r"P:\a.mov", tries=1)
        session = resolve_journal.latest_session("FF5")

        manager._project = Project("Doc 2")
        shared = Item(r"P:\a.mov")
        self._pool(monkeypatch, [shared], project="Doc 2")

        result = resolve_bridge.undo_last_relink(session)

        assert result["ok"] is False and result["skipped"] == 1
        assert shared.path == r"P:\a.mov"

    def test_the_open_projects_own_journal_still_replays(self, monkeypatch):
        # The guard must not cost the case it exists to protect: two projects
        # with journals, the open one's is the one that runs.
        manager = _connect(monkeypatch, Manager(Project("FF5")))
        resolve_bridge.replace_clip(Item(r"F:\ff5.mov"), r"P:\ff5.mov", tries=1)

        manager._project = Project("Energy Transition")
        # The bridge caches the project name for 20 s; the editor switching
        # projects is a slower event than that, so age the cache out rather
        # than journalling the next edit under the project they left.
        monkeypatch.setattr(resolve_bridge, "_project_name_cache", None, raising=False)
        resolve_journal.reset_for_tests()
        mine = Item(r"F:\et.mov", name="ET1")
        resolve_bridge.replace_clip(mine, r"P:\et.mov", tries=1)
        self._pool(monkeypatch, [mine], project="Energy Transition")

        result = resolve_bridge.undo_last_relink()

        assert result["undone"] == 1
        assert mine.path == r"F:\et.mov"
