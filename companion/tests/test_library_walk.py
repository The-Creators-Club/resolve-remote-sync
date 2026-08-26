"""The bridge's half of the library walk: library first, API when it can't.

No live Resolve and no live database -- a fake ProjectLibrary stands in for
the reader (tests/test_library.py covers the real one against a SQLite
fixture), and the usual FakeResolve stands in for the API.

The load-bearing assertion in here is the lock one: the whole point of
reading the project library is that Resolve is not holding still while we
do it, so `_API_LOCK` must be FREE for the entire database read. Everything
else is about what happens when the library cannot answer, which on plenty
of machines is the permanent state.
"""

from __future__ import annotations

import logging
import threading
import time

import pytest

from ccsync_companion import config as config_mod, library, resolve_bridge


# -- doubles ---------------------------------------------------------------


class FakeClip:
    """A media pool clip that answers the ONE-ARGUMENT GetClipProperty."""

    def __init__(self, uid: str, path: str = "", proxy: str = "",
                 proxy_path: str = ""):
        self._uid = uid
        self._props = {
            "File Path": path,
            "Proxy": proxy,
            "Proxy Media Path": proxy_path,
        }
        self.property_calls: list[str] = []

    def GetUniqueId(self):
        return self._uid

    def GetName(self):
        return self._uid

    def GetClipProperty(self, key=None):
        if key is None:
            return dict(self._props)
        self.property_calls.append(key)
        # Real Resolve answers None for a key the clip has no value for.
        return self._props.get(key) or None


class FakeDictOnlyClip(FakeClip):
    """A build with no one-argument overload at all: it raises."""

    def GetClipProperty(self, key=None):     # type: ignore[override]
        if key is not None:
            raise TypeError("GetClipProperty() takes 1 positional argument")
        return dict(self._props)


class FakeFolder:
    def __init__(self, clips=None, subfolders=None, name=""):
        self._clips = list(clips or [])
        self._subfolders = list(subfolders or [])
        self._name = name

    def GetClipList(self):
        return self._clips

    def GetSubFolderList(self):
        return self._subfolders

    def GetName(self):
        return self._name


class FakeMediaPool:
    def __init__(self, root):
        self._root = root

    def GetRootFolder(self):
        return self._root


class FakeTimeline:
    def __init__(self, name="Civil Defence - E1", uid="tl-1"):
        self._name = name
        self._uid = uid

    def GetName(self):
        return self._name

    def GetUniqueId(self):
        return self._uid

    def GetTrackCount(self, track_type):
        return 0

    def GetItemListInTrack(self, track_type, index):
        return []


class FakeProject:
    def __init__(self, name="Civil Defence", timeline=None, media_pool=None):
        self._name = name
        self._timeline = timeline
        self._media_pool = media_pool

    def GetName(self):
        return self._name

    def GetCurrentTimeline(self):
        return self._timeline

    def GetMediaPool(self):
        return self._media_pool


class FakeResolve:
    def __init__(self, project):
        self._project = project

    def GetProjectManager(self):
        return self

    def GetCurrentProject(self):
        return self._project


def library_item(path: str, uid: str = "", via_multicam=None) -> dict:
    return {
        "file_path": path,
        "media_pool_item": None,
        "media_pool_uid": uid or ("uid:" + path),
        "clip_name": path.rsplit("\\", 1)[-1],
        "source": "library",
        "track_type": "video",
        "track_index": 1,
        "item_index": 0,
        "via_multicam": via_multicam,
    }


def pool_item(path: str, uid: str = "") -> dict:
    return {
        "file_path": path,
        "media_pool_item": None,
        "media_pool_uid": uid or ("uid:" + path),
        "clip_name": path.rsplit("\\", 1)[-1],
        "source": "library",
        "resolve_project_name": "Civil Defence",
        "bin_path": "Interviews",
        "proxy_path": "",
        "proxy_state": "",
    }


def api_lock_is_free(timeout: float = 2.0) -> bool:
    """Is _API_LOCK unheld right now?

    Probed on ANOTHER THREAD deliberately: _API_LOCK is an RLock, so a
    non-blocking acquire from the thread that already owns it succeeds and
    would report "free" for a lock that is very much held.
    """
    answer: list[bool] = []

    def probe():
        got = resolve_bridge._API_LOCK.acquire(blocking=False)
        if got:
            resolve_bridge._API_LOCK.release()
        answer.append(got)

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join(timeout)
    return bool(answer and answer[0])


def library_lock_is_free(timeout: float = 2.0) -> bool:
    """Is _LIBRARY_LOCK unheld right now? Probed on another thread, and for
    the same reason api_lock_is_free() is: it is an RLock."""
    answer: list[bool] = []

    def probe():
        got = resolve_bridge._LIBRARY_LOCK.acquire(blocking=False)
        if got:
            resolve_bridge._LIBRARY_LOCK.release()
        answer.append(got)

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join(timeout)
    return bool(answer and answer[0])


class FakeProjectLibrary:
    """Stands in for library.ProjectLibrary. Records how it was used."""

    instances: list["FakeProjectLibrary"] = []

    def __init__(self, info, project_name):
        self.info = info
        self.project_name = project_name
        self.items: list[dict] = [library_item(r"P:\Projects\Show\a.mov")]
        self.pool: list[dict] = [pool_item(r"P:\Projects\Show\a.mov")]
        self.changed_answer = True
        self.raise_on_timeline: Exception | None = None
        self.raise_on_pool: Exception | None = None
        self.timeline_calls: list[str] = []
        self.pool_calls = 0
        self.changed_calls = 0
        self.closed = False
        self.lock_free: list[bool] = []
        # The real reader caches uid -> path here until changed() says the
        # library moved; the bridge clears it on the staleness ceiling.
        self._paths: dict | None = {}
        FakeProjectLibrary.instances.append(self)

    def changed(self):
        self.changed_calls += 1
        if self.changed_answer:
            self._paths = None
            return True
        return False

    def timeline_items(self, timeline_uid):
        self.lock_free.append(api_lock_is_free())
        self.timeline_calls.append(timeline_uid)
        if self.raise_on_timeline is not None:
            raise self.raise_on_timeline
        self._paths = {}
        return [dict(item) for item in self.items]

    def pool_items(self):
        self.lock_free.append(api_lock_is_free())
        self.pool_calls += 1
        if self.raise_on_pool is not None:
            raise self.raise_on_pool
        self._paths = {}
        return [dict(item) for item in self.pool]

    def close(self):
        self.closed = True


@pytest.fixture
def rig(monkeypatch):
    """A Resolve with a project and a timeline, and a library behind it."""
    FakeProjectLibrary.instances = []
    clips = [FakeClip("uid:" + r"P:\Projects\Show\a.mov",
                      path=r"P:\Projects\Show\a.mov",
                      proxy="1920x1080", proxy_path=r"P:\Proxy\a.mov")]
    root = FakeFolder(clips=clips, name="Master")
    timeline = FakeTimeline()
    project = FakeProject(timeline=timeline, media_pool=FakeMediaPool(root))
    resolve = FakeResolve(project)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    info = library.LibraryInfo(kind="PostgreSQL", name="FF5", host="nas", port=5432)
    located: list[dict] = []

    def _locate(_resolve, project_name, overrides=None, api_info=None):
        located.append({"project": project_name, "overrides": dict(overrides or {}),
                        "api_info": api_info,
                        "api_lock_free": api_lock_is_free()})
        return info

    monkeypatch.setattr(library, "locate", _locate)
    monkeypatch.setattr(library, "ProjectLibrary", FakeProjectLibrary)
    resolve_bridge.configure_library(dict(config_mod.DEFAULTS))

    class Rig:
        pass

    rig = Rig()
    rig.resolve = resolve
    rig.project = project
    rig.timeline = timeline
    rig.clips = clips
    rig.located = located
    rig.info = info
    rig.library = lambda: FakeProjectLibrary.instances[-1]
    return rig


# -- the happy path --------------------------------------------------------


def test_the_timeline_walk_comes_from_the_library(rig):
    result = resolve_bridge.poll_timeline_items()

    assert result["ok"] is True
    assert result["project_name"] == "Civil Defence"
    assert [item["file_path"] for item in result["items"]] == [r"P:\Projects\Show\a.mov"]
    assert {item["source"] for item in result["items"]} == {"library"}
    assert rig.library().timeline_calls == ["tl-1"]
    assert resolve_bridge.library_status()["source"] == "library"


def test_the_api_lock_is_free_while_the_library_is_read(rig):
    """The reason this whole module exists. A 5 s statement timeout under
    _API_LOCK is 5 s of frozen tray menu and 5 s of every other scripting
    client on the machine queueing behind us."""
    resolve_bridge.poll_timeline_items()
    resolve_bridge.get_media_pool_items()

    assert rig.library().lock_free == [True, True]


def test_the_pool_walk_comes_from_the_library(rig):
    result = resolve_bridge.get_media_pool_items()

    assert result["ok"] is True
    assert [item["bin_path"] for item in result["items"]] == ["Interviews"]
    assert {item["source"] for item in result["items"]} == {"library"}


def test_items_with_no_media_path_are_dropped(rig):
    """The API walk skips a clip whose File Path is "", and so must this one
    -- on a multicam timeline the library returns ~950 pathless repeat cuts
    of the multicam alongside the 44 items that carry a path."""
    rig_library_items = [
        library_item(r"P:\Projects\Show\a.mov"),
        library_item("", uid="uid:multicam"),
    ]
    resolve_bridge.poll_timeline_items()          # opens the library
    rig.library().items = rig_library_items
    resolve_bridge.reset_timeline_cache()

    result = resolve_bridge.poll_timeline_items()
    assert [item["media_pool_uid"] for item in result["items"]] == [
        "uid:" + r"P:\Projects\Show\a.mov"]


def test_the_overrides_handed_to_locate_are_the_config_keys(rig):
    resolve_bridge.configure_library({
        "library_walk": True,
        "library_db_host": "10.0.0.9",
        "library_db_port": 5433,
        "library_db_name": "FF5",
        "library_db_user": "postgres",
        "library_db_password": "hunter2",
    })
    resolve_bridge.poll_timeline_items()

    assert rig.located[-1]["overrides"] == {
        "library_walk": True,
        "library_db_host": "10.0.0.9",
        "library_db_port": 5433,
        "library_db_name": "FF5",
        "library_db_user": "postgres",
        "library_db_password": "hunter2",
    }


# -- falling back ----------------------------------------------------------


def test_library_walk_false_never_touches_the_library(rig, monkeypatch):
    walked: list[bool] = []
    monkeypatch.setattr(
        resolve_bridge, "_get_timeline_items_locked",
        lambda allow_cached=False: walked.append(allow_cached) or
        {"ok": True, "message": "", "items": [], "project_name": "Civil Defence"})

    cfg = dict(config_mod.DEFAULTS)
    cfg["library_walk"] = False
    resolve_bridge.configure_library(cfg)

    resolve_bridge.poll_timeline_items()

    assert walked == [True]
    assert rig.located == []
    assert FakeProjectLibrary.instances == []


def test_a_library_that_stops_answering_falls_back_to_the_api(rig, caplog):
    resolve_bridge.poll_timeline_items()
    rig.library().raise_on_timeline = library.LibraryUnavailable("connection reset")

    with caplog.at_level(logging.WARNING, logger="ccsync.resolve"):
        result = resolve_bridge.poll_timeline_items()

    assert result["ok"] is True
    assert result["items"] == []                 # the API walk's empty timeline
    assert resolve_bridge.library_status()["source"] == "api"
    assert rig.library().closed is True
    assert any("library walk unavailable (connection reset)" in record.message
               for record in caplog.records)


def test_no_library_found_falls_back_and_says_so_once(rig, monkeypatch, caplog):
    monkeypatch.setattr(library, "locate", lambda *a, **k: None)

    with caplog.at_level(logging.DEBUG, logger="ccsync.resolve"):
        resolve_bridge.poll_timeline_items()
        resolve_bridge._library_next_attempt = 0.0
        resolve_bridge.poll_timeline_items()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING
                and "library walk unavailable" in r.message]
    repeats = [r for r in caplog.records if r.levelno == logging.DEBUG
               and "library walk unavailable" in r.message]
    assert len(warnings) == 1                    # loud once per process
    assert repeats                               # and quiet after that


def test_a_failure_is_not_retried_on_every_poll(rig):
    resolve_bridge.poll_timeline_items()          # opens the library
    opened = len(FakeProjectLibrary.instances)
    rig.library().raise_on_timeline = library.LibraryUnavailable("nope")
    resolve_bridge.poll_timeline_items()          # fails, closes, backs off

    for _ in range(5):
        resolve_bridge.poll_timeline_items()
    assert len(FakeProjectLibrary.instances) == opened
    assert resolve_bridge.library_status()["retry_in"] > 0

    # ...until the window has passed.
    resolve_bridge._library_next_attempt = time.monotonic() - 0.01
    resolve_bridge.poll_timeline_items()
    assert len(FakeProjectLibrary.instances) == opened + 1


def test_the_backoff_window_is_a_minute_not_a_poll(rig):
    resolve_bridge.poll_timeline_items()
    rig.library().raise_on_timeline = library.LibraryUnavailable("nope")
    resolve_bridge.poll_timeline_items()

    assert resolve_bridge._LIBRARY_RETRY_SECONDS == 60.0
    assert 55.0 < resolve_bridge.library_status()["retry_in"] <= 60.0


def test_no_project_falls_through_to_the_api_walk(monkeypatch, rig):
    """The dict for "no project open" must keep coming from one place."""
    monkeypatch.setattr(resolve_bridge, "connect", lambda: FakeResolve(None))

    result = resolve_bridge.poll_timeline_items()
    assert result["ok"] is False
    assert "no project" in result["message"]


# -- the poll cache --------------------------------------------------------


def test_an_unchanged_library_is_not_walked_again(rig):
    resolve_bridge.poll_timeline_items()
    rig.library().changed_answer = False

    resolve_bridge.poll_timeline_items()
    resolve_bridge.poll_timeline_items()

    assert rig.library().timeline_calls == ["tl-1"]


def test_a_changed_library_is_walked_again(rig):
    resolve_bridge.poll_timeline_items()
    rig.library().changed_answer = False
    resolve_bridge.poll_timeline_items()
    rig.library().changed_answer = True

    resolve_bridge.poll_timeline_items()

    assert rig.library().timeline_calls == ["tl-1", "tl-1"]


def test_the_safety_valve_walks_anyway(rig):
    resolve_bridge.poll_timeline_items()
    rig.library().changed_answer = False

    for _ in range(resolve_bridge._FULL_WALK_EVERY_POLLS):
        resolve_bridge.poll_timeline_items()

    assert len(rig.library().timeline_calls) == 2


def test_a_stale_answer_is_re_read_even_when_changed_says_no(rig):
    """changed() rides on DbSavedTime, which does not move at all while Live
    Save is off -- so "nothing changed" can mean "nobody has pressed Ctrl-S
    since lunch" (wave-1 review, 2026-08-26)."""
    resolve_bridge.poll_timeline_items()
    project_library = rig.library()
    project_library.changed_answer = False
    resolve_bridge.poll_timeline_items()
    assert len(project_library.timeline_calls) == 1

    resolve_bridge._library_read_stamp = (
        time.monotonic() - resolve_bridge._LIBRARY_CACHE_MAX_SECONDS - 1)
    resolve_bridge.poll_timeline_items()

    assert len(project_library.timeline_calls) == 2
    # ...and the reader's own uid -> path cache was dropped with it, or the
    # re-read would answer out of the same stale dictionary.
    assert project_library._paths == {}


def test_an_ordinary_walk_is_not_shared_with_the_api_walk(rig):
    """The two fingerprints must never collide: an API walk and a library
    walk of the same timeline are different answers."""
    resolve_bridge.poll_timeline_items()
    cfg = dict(config_mod.DEFAULTS)
    cfg["library_walk"] = False
    resolve_bridge.configure_library(cfg)

    result = resolve_bridge.poll_timeline_items()
    assert result["items"] == []                 # the API's empty timeline


# -- project lifecycle -----------------------------------------------------


def test_a_project_change_closes_the_library(rig):
    resolve_bridge.poll_timeline_items()
    first = rig.library()

    rig.project._name = "Elections"
    resolve_bridge.poll_timeline_items()

    assert first.closed is True
    assert rig.library() is not first
    assert rig.library().project_name == "Elections"


def test_reconfiguring_the_library_keys_drops_the_open_library(rig):
    resolve_bridge.poll_timeline_items()
    first = rig.library()

    cfg = dict(config_mod.DEFAULTS)
    cfg["library_db_host"] = "10.0.0.9"
    resolve_bridge.configure_library(cfg)

    assert first.closed is True
    resolve_bridge.poll_timeline_items()
    assert rig.library() is not first


# -- proxy keys ------------------------------------------------------------


def test_proxy_keys_are_enriched_where_proxies_are_made(rig, monkeypatch):
    monkeypatch.setattr(config_mod, "proxy_generation_enabled", lambda cfg: True)

    result = resolve_bridge.get_media_pool_items()

    item = result["items"][0]
    assert item["proxy_state"] == "1920x1080"
    assert item["proxy_path"] == r"P:\Proxy\a.mov"
    # One-arg reads, not the whole 60-key dict.
    assert rig.clips[0].property_calls == ["Proxy Media Path", "Proxy"]


def test_proxy_keys_are_enriched_for_the_relink_pass_too(rig, monkeypatch):
    """The lane-B editor rig: proxy_gen_enabled derives False (lane B is on),
    and app._relink_proxies_once still reads these keys every pass. Gating on
    generation alone reported proxy_state "" for all 1,298 clips, which
    proxy_relink reads as "no proxy" -- ~1,300 unasked-for LinkProxyMedia
    calls (library walk review 2, 2026-08-26)."""
    monkeypatch.setattr(config_mod, "proxy_generation_enabled", lambda cfg: False)
    monkeypatch.setattr(resolve_bridge, "_config_without_creating",
                        lambda: {**config_mod.DEFAULTS, "proxy_gen_enabled": False,
                                 "proxy_relink_enabled": True})

    result = resolve_bridge.get_media_pool_items()

    item = result["items"][0]
    assert item["proxy_state"] == "1920x1080"
    assert item["proxy_path"] == r"P:\Proxy\a.mov"


def test_proxy_keys_stay_unknown_where_nothing_reads_them(rig, monkeypatch):
    """Neither pass runs on this machine, so nothing will read them."""
    monkeypatch.setattr(config_mod, "proxy_generation_enabled", lambda cfg: False)
    monkeypatch.setattr(resolve_bridge, "_config_without_creating",
                        lambda: {**config_mod.DEFAULTS, "proxy_gen_enabled": False,
                                 "proxy_relink_enabled": False})

    result = resolve_bridge.get_media_pool_items()

    item = result["items"][0]
    assert item["proxy_state"] == ""
    assert item["proxy_path"] == ""
    assert rig.clips[0].property_calls == []      # Resolve was not asked at all


def test_the_default_config_enriches(rig):
    """Shipped defaults: proxy_relink_enabled is True, so the keys the API
    walk always carried keep coming back."""
    assert config_mod.DEFAULTS["proxy_relink_enabled"] is True

    result = resolve_bridge.get_media_pool_items()

    assert result["items"][0]["proxy_state"] == "1920x1080"


# -- half an answer is not an answer ---------------------------------------


def test_a_half_enriched_pool_walk_falls_back_to_the_api(rig, monkeypatch):
    """A project that goes away mid-enrichment leaves the later chunks at
    proxy_state "" -- which reads as "no proxy", not as "unknown". The whole
    list goes back as None (library walk review 2, 2026-08-26)."""
    monkeypatch.setattr(resolve_bridge, "_PROXY_ENRICH_CHUNK", 2)
    clips = [FakeClip("uid-%d" % n, path=r"P:%d.mov" % n, proxy="1920x1080")
             for n in range(5)]
    rig.project._media_pool = FakeMediaPool(FakeFolder(clips=clips))
    resolve_bridge.poll_timeline_items()          # opens the library
    rig.library().pool = [pool_item(r"P:%d.mov" % n, uid="uid-%d" % n)
                          for n in range(5)]

    chunks: list[int] = []
    real_head = resolve_bridge._current_project_locked

    def head():
        chunks.append(1)
        if len(chunks) > 2:                       # first chunk only, then gone
            return ({"ok": False, "message": "no project open in Resolve",
                     "items": [], "project_name": ""}, rig.resolve, None, "")
        return real_head()

    monkeypatch.setattr(resolve_bridge, "_current_project_locked", head)

    result = resolve_bridge.get_media_pool_items()

    # The API walk answered instead, and nobody was handed the half-filled
    # library list -- these items are Resolve's own, objects and all, where
    # a library item carries a uid and no object.
    assert {item["source"] for item in result["items"]} == {"api"}
    assert all(item["media_pool_item"] is not None for item in result["items"])
    assert resolve_bridge.library_status()["source"] == "api"


def test_the_library_lock_is_free_while_the_proxy_keys_are_enriched(rig, monkeypatch):
    """Enrichment touches no library object, and holding _LIBRARY_LOCK for
    its 5 s parked _library_attempt_due(), library_status() and
    configure_library() -- the wedge warning included."""
    free: list[bool] = []
    real = resolve_bridge._clip_property
    monkeypatch.setattr(
        resolve_bridge, "_clip_property",
        lambda clip, key: free.append(library_lock_is_free()) or real(clip, key))

    resolve_bridge.get_media_pool_items()

    assert free and all(free)


def test_the_enrichment_lets_go_of_the_lock_between_chunks(rig, monkeypatch):
    """5.5 s of proxy reads on 1,298 clips is fine as 13 holds and hostile as
    one: another client waits for a chunk, not for the walk."""
    monkeypatch.setattr(config_mod, "proxy_generation_enabled", lambda cfg: True)
    monkeypatch.setattr(resolve_bridge, "_PROXY_ENRICH_CHUNK", 2)
    clips = [FakeClip("uid-%d" % n, path=r"P:%d.mov" % n, proxy="1920x1080")
             for n in range(5)]
    rig.project._media_pool = FakeMediaPool(FakeFolder(clips=clips))
    resolve_bridge.poll_timeline_items()          # opens the library
    rig.library().pool = [pool_item(r"P:%d.mov" % n, uid="uid-%d" % n)
                          for n in range(5)]

    holds: list[str] = []
    real_call = resolve_bridge._bridge_call

    class Counted(real_call):
        __slots__ = ()

        def __enter__(self):
            holds.append(self._name)
            return super().__enter__()

    monkeypatch.setattr(resolve_bridge, "_bridge_call", Counted)
    result = resolve_bridge.get_media_pool_items()

    assert [item["proxy_state"] for item in result["items"]] == ["1920x1080"] * 5
    # One hold for the pool walk's head, then ONE PER CHUNK: ceil(5/2) = 3,
    # so four takes of _API_LOCK where the old code took it once and kept it
    # (library walk review 2, 2026-08-26). connect() re-enters the same
    # RLock inside each of them, which is why this counts takes by name
    # rather than expecting an exact number.
    assert holds.count("get_media_pool_items") >= 4


def test_the_enrichment_reuses_the_uid_map(rig, monkeypatch):
    """One folder walk, not two: the map behind media_pool_item_by_uid is
    the same map the enrichment needs."""
    monkeypatch.setattr(config_mod, "proxy_generation_enabled", lambda cfg: True)
    walks: list[int] = []
    real_walk = resolve_bridge._walk_media_pool_uids

    def counted(folder, found, depth=0, swept=None):
        if depth == 0:
            walks.append(1)
        return real_walk(folder, found, depth, swept)

    monkeypatch.setattr(resolve_bridge, "_walk_media_pool_uids", counted)

    resolve_bridge.get_media_pool_items()
    assert resolve_bridge.media_pool_item_by_uid(
        "uid:" + r"P:\Projects\Show\a.mov") is rig.clips[0]

    assert len(walks) == 1


# -- one-arg GetClipProperty ----------------------------------------------


def test_the_api_walk_reads_one_property_at_a_time(rig):
    clip = FakeClip("uid-1", path=r"P:\a.mov")
    assert resolve_bridge._clip_property(clip, "File Path") == r"P:\a.mov"
    assert clip.property_calls == ["File Path"]
    assert resolve_bridge._ONE_ARG_CLIP_PROPERTY is True


def test_a_build_without_the_one_arg_form_uses_the_dict(rig, caplog):
    clip = FakeDictOnlyClip("uid-1", path=r"P:\a.mov")

    with caplog.at_level(logging.INFO, logger="ccsync.resolve"):
        assert resolve_bridge._clip_property(clip, "File Path") == r"P:\a.mov"

    assert resolve_bridge._ONE_ARG_CLIP_PROPERTY is False
    assert any("full property dict" in record.message for record in caplog.records)
    # And it stays decided -- the probe is per process, not per clip.
    second = FakeDictOnlyClip("uid-2", path=r"P:\b.mov")
    assert resolve_bridge._clip_property(second, "File Path") == r"P:\b.mov"


def test_a_one_arg_none_that_the_dict_can_answer_condemns_the_fast_path():
    class Liar(FakeClip):
        def GetClipProperty(self, key=None):
            if key is None:
                return {"File Path": r"P:\a.mov"}
            return None

    clip = Liar("uid-1")
    assert resolve_bridge._clip_property(clip, "File Path") == r"P:\a.mov"
    assert resolve_bridge._ONE_ARG_CLIP_PROPERTY is False


def test_a_missing_property_on_a_proven_build_is_just_empty():
    good = FakeClip("uid-1", path=r"P:\a.mov")
    resolve_bridge._clip_property(good, "File Path")     # proves the form
    assert resolve_bridge._ONE_ARG_CLIP_PROPERTY is True

    assert resolve_bridge._clip_property(good, "Proxy") == ""
    assert resolve_bridge._ONE_ARG_CLIP_PROPERTY is True


# -- locating the library --------------------------------------------------


def test_locate_does_its_filesystem_work_outside_the_api_lock(rig):
    """locate() reads the WHOLE Resolve log and, for a disk library, walks
    "Resolve Project Library/*/Resolve Projects/<project>". Only the one API
    call it makes belongs under _API_LOCK (library walk review 2,
    2026-08-26)."""
    resolve_bridge.poll_timeline_items()

    assert rig.located[-1]["api_lock_free"] is True


def test_locate_is_handed_the_api_answer_it_would_have_asked_for(rig, monkeypatch):
    """The bridge makes GetCurrentDatabase() itself, under the lock, and
    passes it in -- so locate() never touches `resolve`."""
    info = library.LibraryInfo(kind="PostgreSQL", name="FF5", host="nas")
    monkeypatch.setattr(library, "database_info", lambda resolve: info)

    resolve_bridge.poll_timeline_items()

    assert rig.located[-1]["api_info"] is info


# -- the uid map -----------------------------------------------------------


def test_a_reopened_project_is_not_served_from_the_uid_cache(rig):
    """Same NAME, new object: every MediaPoolItem in the cached map is a dead
    fusionscript pointer, and handing one to ReplaceClip is an access
    violation (library walk review 2, 2026-08-26)."""
    uid = "uid:" + r"P:\Projects\Show\a.mov"
    assert resolve_bridge.media_pool_item_by_uid(uid) is rig.clips[0]

    reopened_clip = FakeClip(uid, path=r"P:\Projects\Show\a.mov")
    reopened = FakeProject(name=rig.project._name, timeline=rig.timeline,
                           media_pool=FakeMediaPool(FakeFolder(clips=[reopened_clip])))
    rig.resolve._project = reopened

    assert resolve_bridge.media_pool_item_by_uid(uid) is reopened_clip


def test_the_same_project_object_still_reuses_the_map(rig):
    """The identity check must not throw the cache away on every call: a FIX
    ALL over 50 clips pays for one pool walk, not 50."""
    walks: list[int] = []
    real_walk = resolve_bridge._walk_media_pool_uids

    def counted(folder, found, depth=0, swept=None):
        if depth == 0:
            walks.append(1)
        return real_walk(folder, found, depth, swept)

    resolve_bridge._walk_media_pool_uids = counted
    try:
        uid = "uid:" + r"P:\Projects\Show\a.mov"
        for _ in range(3):
            assert resolve_bridge.media_pool_item_by_uid(uid) is rig.clips[0]
    finally:
        resolve_bridge._walk_media_pool_uids = real_walk

    assert len(walks) == 1


# -- configuration ---------------------------------------------------------


def test_a_partial_config_does_not_switch_the_walk_off(rig):
    """A cfg dict built by hand (the dashboard's, a tool's) carries no
    library_walk key, and cfg.get(key) answered None -- which is false, so
    the walk quietly stopped happening (library walk review 2, 2026-08-26)."""
    resolve_bridge.configure_library({"library_db_host": "10.0.0.9"})

    result = resolve_bridge.poll_timeline_items()

    assert {item["source"] for item in result["items"]} == {"library"}
    assert resolve_bridge.library_status()["enabled"] is True


def test_the_lazy_config_read_never_creates_config_toml(monkeypatch):
    """A tool, a test or a bare import must not be the thing that writes the
    installer's first-run config.toml."""
    created: list = []
    monkeypatch.setattr(config_mod, "ensure_config_exists",
                        lambda *a, **k: created.append(1))

    resolve_bridge.reset_library_state()
    assert resolve_bridge._library_settings()["library_walk"] is True

    assert created == []
    assert not config_mod.CONFIG_PATH.exists()


# -- status ----------------------------------------------------------------


def test_library_status_reports_the_connection(rig):
    before = resolve_bridge.library_status()
    assert before["enabled"] is True
    assert before["connected"] is False
    assert before["source"] == ""

    resolve_bridge.poll_timeline_items()

    after = resolve_bridge.library_status()
    assert after["connected"] is True
    assert after["source"] == "library"
    assert after["project"] == "Civil Defence"
    assert "FF5" in after["library"]
    assert after["error"] == ""
    assert after["walk_ms"] >= 0.0


def test_library_status_never_loads_config(monkeypatch):
    """A status read must not be the thing that creates a first-run
    config.toml -- the dashboard may ask before the app has started."""
    def _boom(*args, **kwargs):
        raise AssertionError("library_status() loaded config")

    monkeypatch.setattr(config_mod, "load_config", _boom)
    assert resolve_bridge.library_status()["enabled"] is True
