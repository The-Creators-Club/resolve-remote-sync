"""The b-roll "Send to Resolve" server, absorbed from the retired standalone
broll-companion.

Three layers, in the order the request passes through them:
  - the mounts config (~/.broll-companion.json) and the derived "broll" mount,
  - resolve_bridge.perform_insert against fake Resolve scripting objects,
  - build_status_response / build_insert_response and a live loopback server.

Ported from that companion's tests/test_config.py, test_status.py,
test_cors.py and test_insert.py. Every message and status code they pinned is
pinned here too: the web UI shows them verbatim and its JS branches on the
400-vs-200 split.
"""

from __future__ import annotations

import http.client
import json
import os
import threading
from pathlib import Path

import pytest

from ccsync_companion import (
    broll_server, config as config_mod, music_server, music_worker, resolve_bridge,
    resolve_prefs,
)


# ---------------------------------------------------------------------------
# Live-server plumbing
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def worker_in_process(monkeypatch):
    """No test in this file may SPAWN a Resolve worker.

    MED-3 (2026-08-11) moved /status and /insert into a killable child, so the
    seam a test patches (`resolve_bridge.try_connect`, `perform_insert`) is no
    longer in the process the request runs in -- and the real child talks to
    whatever Resolve this developer has open (measured while writing this fix:
    it reached a live project and tried to import into it). Dispatching the
    action through music_worker.run_request keeps every layer under test
    except the process boundary, which test_music_server.py owns, and makes
    the patched bridge seams effective again. AUTOUSE: the same class of guard
    as conftest's real-Tk one. Returns the call log.
    """
    calls: list = []

    def _in_process_call(action, timeout=None, **kw):
        calls.append((action, dict(kw, timeout=timeout)))
        request = dict(kw)
        request["action"] = action
        return music_worker.run_request(request)

    monkeypatch.setattr(music_server, "call", _in_process_call)
    return calls


class BrollClient:
    """Tiny http.client-based helper for hitting the test server."""

    def __init__(self, port: int):
        self.port = port

    def _connect(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def get(self, path: str):
        conn = self._connect()
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, body

    def post_json(self, path: str, obj: dict):
        conn = self._connect()
        payload = json.dumps(obj).encode("utf-8")
        conn.request(
            "POST",
            path,
            body=payload,
            headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
        )
        resp = conn.getresponse()
        body = resp.read()
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, body

    def post_raw(self, path: str, payload: bytes, content_length=None):
        """POST bytes with a Content-Length the caller chooses -- including a
        length that has nothing to do with the body."""
        conn = self._connect()
        length = len(payload) if content_length is None else content_length
        conn.putrequest("POST", path, skip_accept_encoding=True)
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(length))
        conn.endheaders()
        conn.send(payload)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def options(self, path: str):
        conn = self._connect()
        conn.request("OPTIONS", path)
        resp = conn.getresponse()
        body = resp.read()
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, body


@pytest.fixture
def companion_config():
    return {"server_url": "http://127.0.0.1:8000", "mounts": {}}


@pytest.fixture
def live_server(companion_config, monkeypatch):
    """A real BrollCompanionServer on an ephemeral loopback port."""
    # Never actually try to talk to Resolve during HTTP-layer tests.
    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: False)

    srv = broll_server.make_server(companion_config, host="127.0.0.1", port=0)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, BrollClient(port)
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Mounts config
# ---------------------------------------------------------------------------


def test_first_run_creates_config_with_defaults(tmp_path):
    cfg_path = tmp_path / ".broll-companion.json"
    assert not cfg_path.exists()

    loaded = broll_server.load_config(path=cfg_path)

    assert cfg_path.exists()
    assert loaded["mounts"] == {}
    assert "server_url" in loaded


def test_first_run_creates_readme_snippet_alongside(tmp_path):
    cfg_path = tmp_path / ".broll-companion.json"
    readme_path = tmp_path / ".broll-companion.README.txt"

    broll_server.ensure_config_exists(path=cfg_path, readme_path=readme_path)

    assert readme_path.exists()
    text = readme_path.read_text(encoding="utf-8")
    assert "mounts" in text
    assert str(cfg_path) in text


def test_the_readme_snippet_says_the_standalone_companion_is_retired(tmp_path):
    """Editors have this file already, and the old one told them to keep the
    separate BRoll Companion running -- which is now the one thing that stops
    the feature working (it holds 8899)."""
    cfg_path = tmp_path / ".broll-companion.json"
    readme_path = tmp_path / ".broll-companion.README.txt"
    broll_server.ensure_config_exists(path=cfg_path, readme_path=readme_path)

    text = readme_path.read_text(encoding="utf-8").lower()
    assert "retired" in text
    assert "8899" in text


def test_existing_config_is_not_overwritten(tmp_path):
    cfg_path = tmp_path / ".broll-companion.json"
    custom = {"server_url": "http://example.com", "mounts": {"broll": "B:/"}}
    cfg_path.write_text(json.dumps(custom), encoding="utf-8")

    loaded = broll_server.load_config(path=cfg_path)

    assert loaded["mounts"] == {"broll": "B:/"}
    assert loaded["server_url"] == "http://example.com"


def test_malformed_config_falls_back_to_defaults_without_crashing(tmp_path):
    cfg_path = tmp_path / ".broll-companion.json"
    cfg_path.write_text("{not valid json", encoding="utf-8")

    loaded = broll_server.load_config(path=cfg_path)

    assert loaded["mounts"] == {}
    assert loaded["server_url"] == broll_server.DEFAULT_CONFIG["server_url"]


def test_the_default_config_path_follows_the_redirected_home():
    """GUARD, same class as conftest's ~/.ccsync one: computed as a module
    CONSTANT, Path.home() is captured at import -- before conftest redirects
    HOME -- so load_config() would create and rewrite the file in the
    developer's own home on every run, which on this machine is a live
    editor's real mounts config.
    """
    from conftest import REAL_CCSYNC_HOME

    real_home = REAL_CCSYNC_HOME.parent
    assert broll_server.config_path() == Path.home() / ".broll-companion.json"
    assert broll_server.config_path().parent != real_home


# ---------------------------------------------------------------------------
# The derived "broll" mount
# ---------------------------------------------------------------------------


def test_broll_share_defaults_to_the_archive_in_the_tree(tmp_path):
    mounts = broll_server.resolve_mounts({"mounts": {}}, {"local_root": str(tmp_path)})
    assert mounts["broll"] == str(tmp_path / "Assets" / "B-roll Archive")


def test_an_explicit_broll_entry_still_wins(tmp_path):
    mounts = broll_server.resolve_mounts(
        {"mounts": {"broll": "Y:/broll"}}, {"local_root": str(tmp_path)}
    )
    assert mounts["broll"] == "Y:/broll"


def test_a_blank_broll_entry_counts_as_unset(tmp_path):
    """Left over from when the settings panel told editors to fill this file
    in by hand. Treated as configured, it would translate every clip to a
    relative path."""
    mounts = broll_server.resolve_mounts(
        {"mounts": {"broll": "   "}}, {"local_root": str(tmp_path)}
    )
    assert mounts["broll"] == str(tmp_path / "Assets" / "B-roll Archive")


def test_other_shares_get_no_default(tmp_path):
    """Only the b-roll archive has a derivable root -- everything else still
    needs its own line in ~/.broll-companion.json, exactly as before."""
    mounts = broll_server.resolve_mounts({"mounts": {}}, {"local_root": str(tmp_path)})
    assert set(mounts) == {"broll"}
    with pytest.raises(broll_server.MountNotConfiguredError):
        broll_server.translate_path("archive_2019", "clip.mov", mounts, platform="win32")


def test_no_default_without_a_local_root():
    """A companion with no tree configured must say "no mount configured"
    rather than translate to a relative path under the process CWD."""
    assert broll_server.default_broll_mount({"local_root": ""}) is None
    assert broll_server.resolve_mounts({"mounts": {}}, {"local_root": ""}) == {}


def test_the_derived_mount_translates_end_to_end(tmp_path):
    mounts = broll_server.resolve_mounts({}, {"local_root": str(tmp_path)})
    result = broll_server.translate_path("broll", "military/naval/clip.mov", mounts)
    assert Path(result) == tmp_path / "Assets" / "B-roll Archive" / "military" / "naval" / "clip.mov"


def test_the_derived_mount_is_not_required_to_exist_yet(tmp_path):
    """An archive that hasn't synced down yet must produce /insert's "is the
    share mounted?" message, not "no mount configured" -- the latter sends the
    editor to a config file with nothing wrong in it."""
    mounts = broll_server.resolve_mounts({}, {"local_root": str(tmp_path)})
    status, body = broll_server.build_insert_response(
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 0, "out_frame": 10,
         "mode": "append"},
        mounts,
    )
    assert status == 200
    assert "is the share mounted?" in body["message"]


# ---------------------------------------------------------------------------
# Fake DaVinci Resolve scripting objects
# ---------------------------------------------------------------------------


class FakeMediaPoolItem:
    def __init__(self, name: str, file_path: str, proxy: str = "None"):
        self._name = name
        self._file_path = file_path
        self.proxy = proxy
        self.link_proxy_calls: list = []
        self.link_proxy_result = True

    def GetName(self):
        return self._name

    def GetClipProperty(self):
        return {"File Path": self._file_path, "Proxy": self.proxy}

    def LinkProxyMedia(self, path):
        self.link_proxy_calls.append(path)
        if self.link_proxy_result:
            self.proxy = "960x540"
        return self.link_proxy_result


class FakeBinFolder:
    def __init__(self, name: str):
        self._name = name
        self.clips: list = []
        self.subfolders: list = []

    def GetName(self):
        return self._name

    def GetClipList(self):
        return self.clips

    def GetSubFolderList(self):
        return self.subfolders


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
        item = FakeMediaPoolItem(name=os.path.basename(paths[0]), file_path=paths[0])
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

    def GetName(self):
        return "MyProject"


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


@pytest.fixture
def resolve_process(monkeypatch):
    """Pin whether a Resolve process exists, and clear the probe cache.

    Same fixture as test_resolve_bridge's: this bridge answers "not running"
    vs "running but not accepting scripting connections" from a real process
    probe, so without pinning it the test reads whatever the developer has
    open. Returns a setter.
    """
    def _set(present: bool) -> None:
        monkeypatch.setattr(resolve_bridge, "_probe_cache", None)
        monkeypatch.setattr(resolve_prefs, "resolve_is_running", lambda: present)

    yield _set
    resolve_bridge._probe_cache = None


# ---------------------------------------------------------------------------
# resolve_bridge.perform_insert
# ---------------------------------------------------------------------------


def test_perform_insert_resolve_not_running(monkeypatch, resolve_process):
    resolve_process(False)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)
    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 10)
    assert result == {"ok": False, "message": resolve_bridge.NOT_RUNNING_MESSAGE}


def test_perform_insert_resolve_open_but_scripting_dead(monkeypatch, resolve_process):
    """The distinction this bridge exists to draw (item 19): a Resolve whose
    script server never came up looks exactly like a closed one to connect(),
    and "DaVinci Resolve is not running" is unfollowable advice with Resolve
    on screen."""
    resolve_process(True)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)
    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 10)
    assert result == {"ok": False, "message": resolve_bridge.NO_SCRIPTING_MESSAGE}


def test_perform_insert_records_the_session_connection_state(monkeypatch):
    """Every other public entry point feeds resolve_bridge.session_state(),
    which the tray and Copy diagnostics read; an insert must not be the one
    call that leaves it stale."""
    resolve, _media_pool, _root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 10)

    assert resolve_bridge.session_state()["connected"] is True


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


def test_perform_insert_creates_the_archive_sub_bin_when_missing(monkeypatch):
    """Clips land in B-Roll/Archive -- their own shelf under the editors'
    working b-roll bin, not mixed into hand-imported material."""
    resolve, _media_pool, root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    assert root.subfolders == []
    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 50)

    assert result["ok"] is True
    assert len(root.subfolders) == 1
    assert root.subfolders[0].GetName() == "B-Roll"
    assert [f.GetName() for f in root.subfolders[0].subfolders] == ["Archive"]


def test_perform_insert_reuses_existing_bins_across_calls(monkeypatch):
    resolve, _media_pool, root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    resolve_bridge.perform_insert("Y:/broll/clip1.mov", 0, 10)
    resolve_bridge.perform_insert("Y:/broll/clip2.mov", 0, 10)

    # Only one "B-Roll" bin and one "Archive" under it, ever.
    assert len(root.subfolders) == 1
    assert root.subfolders[0].GetName() == "B-Roll"
    assert [f.GetName() for f in root.subfolders[0].subfolders] == ["Archive"]


def test_perform_insert_reuses_an_existing_broll_bin_without_duplicating_it(monkeypatch):
    """A project that already has the flat B-Roll bin (every project made
    before the sub-bin change) gains only the Archive shelf inside it."""
    resolve, _media_pool, root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)
    root.subfolders.append(FakeBinFolder("B-Roll"))

    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 10)

    assert result["ok"] is True
    assert len(root.subfolders) == 1
    assert [f.GetName() for f in root.subfolders[0].subfolders] == ["Archive"]


def test_perform_insert_imports_when_not_already_in_bin(monkeypatch):
    resolve, media_pool, _root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 50)

    assert result["ok"] is True
    assert media_pool.import_calls == [["Y:/broll/clip.mov"]]


def test_perform_insert_reuses_existing_mediapoolitem_by_file_path(monkeypatch):
    resolve, media_pool, root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    # Pre-populate the B-Roll/Archive bin with an already-imported clip.
    existing_bin = FakeBinFolder("B-Roll")
    archive_bin = FakeBinFolder("Archive")
    existing_item = FakeMediaPoolItem("clip.mov", "Y:/broll/clip.mov")
    archive_bin.clips.append(existing_item)
    existing_bin.subfolders.append(archive_bin)
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
    assert set(item.keys()) == {"mediaPoolItem", "startFrame", "endFrame", "trackIndex"}
    assert item["startFrame"] == 24
    assert item["endFrame"] == 74
    assert isinstance(item["mediaPoolItem"], FakeMediaPoolItem)


def test_the_append_names_its_destination_track(monkeypatch):
    """MED-4: without an explicit trackIndex the append obeys the timeline's
    destination-track buttons -- video destination off places NOTHING and
    reports no error, which this button then showed as success."""
    resolve, media_pool, _root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 10)

    assert media_pool.append_calls[0][0]["trackIndex"] == resolve_bridge.BROLL_TRACK_INDEX


def test_the_append_does_not_pin_a_mediatype(monkeypatch):
    """The other half of that landmine, deliberately NOT copied from
    music_worker's audio-only place(): a mediaType would restrict the append to
    one stream, and a b-roll clip arriving without its nat sound is the same
    silent wrongness in the other direction."""
    resolve, media_pool, _root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 10)

    assert "mediaType" not in media_pool.append_calls[0][0]


def test_perform_insert_success_message_shape(monkeypatch):
    resolve, _media_pool, _root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 24, 74)

    assert result["ok"] is True
    assert result["message"] == "Inserted clip.mov (50 frames)"


class FakeTimelineItem:
    def __init__(self, start):
        self._start = start

    def GetStart(self):
        return self._start


class FakeTracksTimeline:
    """A timeline that can be asked what is on a track, which the placement
    verification reads. The plain FakeTimeline above cannot, and that is
    deliberate too: "cannot tell" must never turn a good insert into a
    failure message."""

    def __init__(self):
        self.video1: list = []

    def GetItemListInTrack(self, kind, index):
        return list(self.video1) if kind == "video" and index == 1 else []


def _stack_with_tracks(*, places: bool, returned_start=86400):
    root = FakeRootFolder()
    media_pool = FakeMediaPool(root)
    timeline = FakeTracksTimeline()

    def _append(clips):
        media_pool.append_calls.append(clips)
        item = FakeTimelineItem(returned_start)
        if places:
            timeline.video1.append(item)
        return [item]

    media_pool.AppendToTimeline = _append
    project = FakeProject(media_pool, timeline)
    return FakeResolve(FakeProjectManager(project)), media_pool, timeline


def test_an_append_that_placed_nothing_is_not_reported_as_success(monkeypatch):
    """MED-4, the failure this cost an editor: with the video destination
    toggled off (normal during audio work) AppendToTimeline returns an item,
    reports no error and places nothing -- and the toast said
    "Inserted A001 (240 frames)" over an unchanged timeline."""
    resolve, _media_pool, timeline = _stack_with_tracks(places=False)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 240)

    assert result["ok"] is False
    assert "nothing landed on the timeline" in result["message"]
    assert timeline.video1 == []


def test_an_item_that_reports_no_start_frame_is_not_placement(monkeypatch):
    """The other half of the same rule (music_worker.py:42): a returned item
    is not proof, GetStart() is."""
    resolve, _media_pool, _timeline = _stack_with_tracks(
        places=False, returned_start=None)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 240)

    assert result["ok"] is False
    assert result["message"] == resolve_bridge.NOTHING_PLACED_MESSAGE


def test_a_clip_that_did_land_is_reported_as_success(monkeypatch):
    resolve, _media_pool, timeline = _stack_with_tracks(places=True)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 240)

    assert result == {"ok": True, "message": "Inserted clip.mov (240 frames)"}
    assert len(timeline.video1) == 1


def test_a_timeline_that_cannot_be_read_still_trusts_the_api(monkeypatch):
    """A Resolve version that answers GetItemListInTrack differently must not
    turn every successful insert into "nothing landed"."""
    resolve, _media_pool, _root = _make_stack()   # FakeTimeline: no track reads
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    assert resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 10)["ok"] is True


# ---------------------------------------------------------------------------
# perform_insert, mode "playhead"
# ---------------------------------------------------------------------------


class FakeSpanItem:
    """A timeline item with an extent, which the overlay free-track scan and
    the placement verification both read."""

    def __init__(self, start, end):
        self._start = start
        self._end = end

    def GetStart(self):
        return self._start

    def GetEnd(self):
        return self._end


class FakePlayheadTimeline:
    """A timeline the playhead placement can fully interrogate: frame rate,
    current timecode, per-kind track lists, AddTrack, DeleteClips."""

    def __init__(self, video_tracks=1, audio_tracks=1, fps="24",
                 tc="01:00:00:12"):
        self.tracks = {"video": [[] for _ in range(video_tracks)],
                       "audio": [[] for _ in range(audio_tracks)]}
        self._fps = fps
        self._tc = tc
        self.added_tracks: list = []
        self.add_track_result = True
        self.deleted: list = []

    def GetSetting(self, key):
        return self._fps if key == "timelineFrameRate" else None

    def GetCurrentTimecode(self):
        return self._tc

    def GetStartFrame(self):
        return 86400

    def GetTrackCount(self, kind):
        return len(self.tracks[kind])

    def GetItemListInTrack(self, kind, index):
        lanes = self.tracks[kind]
        return list(lanes[index - 1]) if 1 <= index <= len(lanes) else []

    def AddTrack(self, kind, subtype=None):
        self.added_tracks.append((kind, subtype))
        if self.add_track_result:
            self.tracks[kind].append([])
        return self.add_track_result

    def DeleteClips(self, items, ripple):
        self.deleted.extend(items)
        return True


def _stack_with_playhead(*, timeline=None, honest=True):
    """A full fake stack whose AppendToTimeline honours (or, honest=False,
    quietly ignores) the requested recordFrame -- the Resolve behaviours the
    playhead mode must respectively use and survive."""
    root = FakeRootFolder()
    media_pool = FakeMediaPool(root)
    tl = timeline if timeline is not None else FakePlayheadTimeline()

    def _append(clips):
        media_pool.append_calls.append(clips)
        info = clips[0]
        requested = info.get("recordFrame", 0)
        start = requested if honest else requested + 7
        item = FakeSpanItem(start, start + (info["endFrame"] - info["startFrame"]))
        lanes = tl.tracks["video"]
        index = info.get("trackIndex", 1)
        if honest and 1 <= index <= len(lanes):
            lanes[index - 1].append(item)
        return [item]

    media_pool.AppendToTimeline = _append
    project = FakeProject(media_pool, tl)
    return FakeResolve(FakeProjectManager(project)), media_pool, tl


def test_playhead_payload_shape(monkeypatch):
    """recordFrame at the playhead (ABSOLUTE frames -- the 1-hour start
    counts), an explicit overlay trackIndex, and no mediaType: the nat sound
    must come along, the append's own rule."""
    resolve, media_pool, _tl = _stack_with_playhead()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert(
        "Y:/broll/clip.mov", 24, 74, mode=resolve_bridge.INSERT_MODE_PLAYHEAD)

    assert result["ok"] is True
    payload = media_pool.append_calls[0][0]
    assert payload["startFrame"] == 24
    assert payload["endFrame"] == 74
    assert payload["recordFrame"] == 86412        # 01:00:00:12 @ 24
    assert payload["trackIndex"] == resolve_bridge.FIRST_OVERLAY_TRACK
    assert "mediaType" not in payload


def test_playhead_creates_both_overlay_lanes_on_a_bare_timeline(monkeypatch):
    """V1/A1 only: the overlay needs V2 AND A2 to exist before the append --
    appending to a track that does not exist returns an item yet places
    nothing (music_worker's landmine list)."""
    resolve, _media_pool, tl = _stack_with_playhead()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert(
        "Y:/broll/clip.mov", 0, 10, mode=resolve_bridge.INSERT_MODE_PLAYHEAD)

    assert result["ok"] is True
    assert ("video", None) in tl.added_tracks
    assert ("audio", "stereo") in tl.added_tracks
    assert "(new track)" in result["message"]


def test_playhead_skips_an_occupied_overlay_track(monkeypatch):
    """V2 busy across the playhead -> the clip goes to V3, never on top of
    what is already there."""
    tl = FakePlayheadTimeline(video_tracks=2, audio_tracks=1)
    tl.tracks["video"][1].append(FakeSpanItem(86400, 86500))
    resolve, media_pool, _tl = _stack_with_playhead(timeline=tl)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert(
        "Y:/broll/clip.mov", 0, 10, mode=resolve_bridge.INSERT_MODE_PLAYHEAD)

    assert result["ok"] is True
    assert media_pool.append_calls[0][0]["trackIndex"] == 3


def test_playhead_audio_occupancy_also_moves_the_slot(monkeypatch):
    """One trackIndex serves both streams, so a slot whose AUDIO lane is busy
    is not free even with its video lane clear -- placing there would drop
    the nat sound onto an occupied track."""
    tl = FakePlayheadTimeline(video_tracks=1, audio_tracks=2)
    tl.tracks["audio"][1].append(FakeSpanItem(86400, 86500))
    resolve, media_pool, _tl = _stack_with_playhead(timeline=tl)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert(
        "Y:/broll/clip.mov", 0, 10, mode=resolve_bridge.INSERT_MODE_PLAYHEAD)

    assert result["ok"] is True
    assert media_pool.append_calls[0][0]["trackIndex"] == 3


def test_playhead_reuses_an_existing_free_track(monkeypatch):
    """V2/A2 already there and clear: no tracks are added and the message
    does not claim one was."""
    tl = FakePlayheadTimeline(video_tracks=2, audio_tracks=2)
    resolve, media_pool, _tl = _stack_with_playhead(timeline=tl)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert(
        "Y:/broll/clip.mov", 0, 10, mode=resolve_bridge.INSERT_MODE_PLAYHEAD)

    assert result == {"ok": True,
                      "message": "Placed clip.mov on V2 at the playhead"}
    assert tl.added_tracks == []
    assert media_pool.append_calls[0][0]["trackIndex"] == 2


def test_playhead_a_misplaced_clip_is_deleted_and_reported(monkeypatch):
    """A returned item is not proof of placement, and for a placement the
    ONLY acceptable landing is the requested frame (music_worker's place()
    verification): a clip that landed elsewhere is removed, not shown as
    success."""
    resolve, _media_pool, tl = _stack_with_playhead(honest=False)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert(
        "Y:/broll/clip.mov", 0, 10, mode=resolve_bridge.INSERT_MODE_PLAYHEAD)

    assert result["ok"] is False
    assert "placement failed on V2" in result["message"]
    assert len(tl.deleted) == 1


def test_playhead_refuses_when_a_track_cannot_be_added(monkeypatch):
    tl = FakePlayheadTimeline()
    tl.add_track_result = False
    resolve, media_pool, _tl = _stack_with_playhead(timeline=tl)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert(
        "Y:/broll/clip.mov", 0, 10, mode=resolve_bridge.INSERT_MODE_PLAYHEAD)

    assert result["ok"] is False
    assert "couldn't add" in result["message"]
    assert media_pool.append_calls == []


def test_playhead_drop_frame_math_matches_music_worker(monkeypatch):
    """_tc_to_frame is music_worker.tc_to_frame duplicated (that module
    imports this one, so the import cannot go the other way) -- pin the copy
    against its origin so they cannot drift apart silently."""
    for tc, base in [("01:00:00;02", 30), ("00:10:00;00", 60),
                     ("01:00:00:12", 24)]:
        assert resolve_bridge._tc_to_frame(tc, base) == \
            music_worker.tc_to_frame(tc, base)


def test_an_unknown_mode_never_reaches_resolve(monkeypatch):
    """Belt and braces under broll_server's own gate: this module's contract
    is never-raise, so a caller bug answers like an editor state."""
    resolve, media_pool, _root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert(
        "Y:/broll/clip.mov", 0, 10, mode="sideways")

    assert result["ok"] is False
    assert "sideways" in result["message"]
    assert media_pool.append_calls == []


# ---------------------------------------------------------------------------
# /insert's mode gate (build_insert_response)
# ---------------------------------------------------------------------------


def _mode_gate_body(tmp_path, **overrides):
    clip = tmp_path / "clip.mov"
    if not clip.exists():
        clip.write_bytes(b"top slot")
    body = {"share": "broll", "rel_path": "clip.mov",
            "in_frame": 0, "out_frame": 10}
    body.update(overrides)
    return body, {"broll": str(tmp_path)}


def test_insert_forwards_the_mode_to_the_worker(
        tmp_path, worker_in_process, monkeypatch, resolve_process):
    resolve_process(False)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)
    body, mounts = _mode_gate_body(tmp_path, mode="playhead")

    status, _result = broll_server.build_insert_response(body, mounts)

    assert status == 200
    action, kw = worker_in_process[0]
    assert action == music_worker.BROLL_INSERT_ACTION
    assert kw["mode"] == "playhead"


def test_a_body_without_a_mode_still_appends(
        tmp_path, worker_in_process, monkeypatch, resolve_process):
    """Every deployed page sends mode explicitly, but the field is optional
    in the contract and its absence must mean v1 behaviour."""
    resolve_process(False)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: None)
    body, mounts = _mode_gate_body(tmp_path)

    broll_server.build_insert_response(body, mounts)

    assert worker_in_process[0][1]["mode"] == "append"


def test_an_unknown_mode_is_refused_before_the_worker_spawns(
        tmp_path, worker_in_process):
    body, mounts = _mode_gate_body(tmp_path, mode="sideways")

    status, result = broll_server.build_insert_response(body, mounts)

    assert status == 200
    assert result["ok"] is False
    assert "sideways" in result["message"]
    assert worker_in_process == []


def _archive_clip_with_preview(tmp_path):
    """A top-slot file with its adjacent Proxy/ preview, archive-style."""
    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"top slot")
    proxy_dir = tmp_path / "Proxy"
    proxy_dir.mkdir()
    preview = proxy_dir / "clip.mp4"
    preview.write_bytes(b"preview")
    return clip, preview


def test_perform_insert_attaches_the_adjacent_proxy(monkeypatch, tmp_path):
    """Scripted ImportMedia does NOT run Resolve's adjacent-Proxy auto-attach
    (measured live 2026-08-12: Proxy stayed None with the preview sitting
    right there), so the insert links it explicitly."""
    clip, preview = _archive_clip_with_preview(tmp_path)
    resolve, media_pool, _root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert(str(clip), 0, 10)

    assert result["ok"] is True
    item = media_pool.current_folder.clips[0]
    assert item.link_proxy_calls == [str(preview)]
    assert item.proxy == "960x540"


def test_a_clip_without_an_adjacent_proxy_links_nothing(monkeypatch, tmp_path):
    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"top slot")
    resolve, media_pool, _root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    assert resolve_bridge.perform_insert(str(clip), 0, 10)["ok"] is True
    assert media_pool.current_folder.clips[0].link_proxy_calls == []


def test_a_refused_proxy_link_does_not_fail_the_insert(monkeypatch, tmp_path):
    """R10's live shape: Resolve validates the pairing and refuses a preview
    with no embedded timecode. The clip is inserted and usable either way --
    the editor just edits the original until the previews are fixed."""
    clip, _preview = _archive_clip_with_preview(tmp_path)
    resolve, media_pool, _root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    def refuse_link(item):
        item.link_proxy_result = False

    orig_import = media_pool.ImportMedia

    def import_and_refuse(paths):
        items = orig_import(paths)
        refuse_link(items[0])
        return items

    media_pool.ImportMedia = import_and_refuse

    result = resolve_bridge.perform_insert(str(clip), 0, 10)

    assert result["ok"] is True
    item = media_pool.current_folder.clips[0]
    assert item.link_proxy_calls != []
    assert item.proxy == "None"


def test_a_clip_that_already_has_a_proxy_is_left_alone(monkeypatch, tmp_path):
    """Re-sending a clip whose earlier insert attached the proxy must not
    churn the attachment on every send."""
    clip, _preview = _archive_clip_with_preview(tmp_path)
    resolve, media_pool, root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    broll_bin = FakeBinFolder("B-Roll")
    archive_bin = FakeBinFolder("Archive")
    existing = FakeMediaPoolItem("clip.mov", str(clip), proxy="960x540")
    archive_bin.clips.append(existing)
    broll_bin.subfolders.append(archive_bin)
    root.subfolders.append(broll_bin)

    assert resolve_bridge.perform_insert(str(clip), 0, 10)["ok"] is True
    assert existing.link_proxy_calls == []


def test_perform_insert_append_failure_reported(monkeypatch):
    resolve, _media_pool, _root = _make_stack(append_result=False)
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 10)

    assert result == {"ok": False, "message": "failed to append clip to timeline"}


def test_perform_insert_scripting_error_is_editor_facing(monkeypatch):
    """The raw exception text used to reach the web UI's toast verbatim."""
    resolve, media_pool, _root = _make_stack()

    def boom(_clips):
        raise RuntimeError("Attempt to call a nil value")

    media_pool.AppendToTimeline = boom
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 10)

    assert result["ok"] is False
    assert result["message"] == resolve_bridge._SCRIPTING_ERROR_MESSAGE


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


def test_build_status_response_shape(monkeypatch):
    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: True)
    result = broll_server.build_status_response({"broll": "B:/"})
    assert result == {
        "ok": True,
        "resolve_connected": True,
        "mounts": {"broll": "B:/"},
        "version": config_mod.VERSION,
    }


def test_status_reports_this_companions_version(monkeypatch):
    """The settings panel displays it, and the number an editor reads there
    should be the tray app's -- there is no second app to have a version of
    its own any more."""
    import ccsync_companion

    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: False)
    assert broll_server.build_status_response({})["version"] == ccsync_companion.VERSION


def test_build_status_response_tolerant_of_resolve_absent(monkeypatch):
    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: False)
    result = broll_server.build_status_response({})
    assert result["ok"] is True
    assert result["resolve_connected"] is False


def test_status_over_http(live_server):
    _srv, client = live_server
    status, _headers, body = client.get("/status")
    assert status == 200
    data = json.loads(body)
    assert set(data.keys()) == {"ok", "resolve_connected", "mounts", "version"}
    assert data["ok"] is True
    assert data["version"] == config_mod.VERSION


# ---------------------------------------------------------------------------
# CORS / preflight
# ---------------------------------------------------------------------------


def test_options_preflight_returns_204_with_cors_headers(live_server):
    _srv, client = live_server
    status, headers, body = client.options("/insert")
    assert status == 204
    assert headers.get("Access-Control-Allow-Origin") == "*"
    assert headers.get("Access-Control-Allow-Headers") == "Content-Type"
    assert body == b""


def test_get_status_has_cors_headers(live_server):
    _srv, client = live_server
    status, headers, body = client.get("/status")
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == "*"
    assert headers.get("Access-Control-Allow-Headers") == "Content-Type"
    data = json.loads(body)
    assert data["ok"] is True


def test_post_insert_has_cors_headers_even_on_error(live_server):
    _srv, client = live_server
    status, headers, body = client.post_json(
        "/insert",
        {
            "share": "broll",
            "rel_path": "clip.mov",
            "in_frame": 0,
            "out_frame": 10,
            "fps": 25,
            "mode": "append",
        },
    )
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == "*"
    data = json.loads(body)
    assert data["ok"] is False


def test_unknown_route_still_has_cors_headers(live_server):
    _srv, client = live_server
    status, headers, _body = client.get("/nope")
    assert status == 404
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_preflight_allows_private_network_access(live_server):
    """The b-roll UI is served from the cc_sync dashboard, so the page sits on
    a tailnet address and calls 127.0.0.1. Chromium treats public -> private as
    a Private Network Access request and blocks it AT THE PREFLIGHT unless the
    target opts in — the insert would fail before any of our handler code
    ran."""
    _srv, client = live_server
    status, headers, _body = client.options("/insert")
    assert status == 204
    assert headers.get("Access-Control-Allow-Private-Network") == "true"


def test_the_header_is_present_on_real_responses_too(live_server):
    _srv, client = live_server
    _status, headers, _body = client.get("/status")
    assert headers.get("Access-Control-Allow-Private-Network") == "true"


# ---------------------------------------------------------------------------
# POST /insert: translate -> isfile -> resolve_bridge
# ---------------------------------------------------------------------------


def test_insert_mode_playhead_passes_the_gate(tmp_path):
    """"playhead" stopped being reserved 2026-08-14: it must fall through to
    the ordinary path machinery (here: the missing-file answer), never the
    unknown-mode refusal it drew in v1."""
    mounts = {"broll": str(tmp_path).replace("\\", "/")}
    status, body = broll_server.build_insert_response(
        {"share": "broll", "rel_path": "missing.mov", "in_frame": 0, "out_frame": 10,
         "mode": "playhead"},
        mounts,
    )
    assert status == 200
    assert "file not found at" in body["message"]


def test_insert_no_mount_configured():
    status, body = broll_server.build_insert_response(
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 0, "out_frame": 10,
         "mode": "append"},
        {},
    )
    assert status == 200
    assert body["ok"] is False
    assert body["message"] == "no mount configured for share 'broll'"


def test_insert_path_traversal_is_http_400():
    status, body = broll_server.build_insert_response(
        {"share": "broll", "rel_path": "../../etc/passwd", "in_frame": 0, "out_frame": 10,
         "mode": "append"},
        {"broll": "Y:/broll"},
    )
    assert status == 400
    assert body["ok"] is False


def test_insert_file_not_found(tmp_path):
    mounts = {"broll": str(tmp_path).replace("\\", "/")}
    status, body = broll_server.build_insert_response(
        {"share": "broll", "rel_path": "missing_clip.mov", "in_frame": 0, "out_frame": 10,
         "mode": "append"},
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

    def fake_perform_insert(local_path, in_frame, out_frame, canonical_fn=None,
                            mode="append"):
        captured["local_path"] = local_path
        captured["in_frame"] = in_frame
        captured["out_frame"] = out_frame
        return {"ok": True, "message": "Inserted clip.mov (10 frames)"}

    monkeypatch.setattr(broll_server.resolve_bridge, "perform_insert", fake_perform_insert)

    status, body = broll_server.build_insert_response(
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 5, "out_frame": 15,
         "mode": "append"},
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
        broll_server.resolve_bridge,
        "perform_insert",
        lambda local_path, in_frame, out_frame, canonical_fn=None, mode="append": {
            "ok": True,
            "message": f"Inserted {os.path.basename(local_path)} ({out_frame - in_frame} frames)",
        },
    )

    status, _headers, body = client.post_json(
        "/insert",
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 0, "out_frame": 20,
         "fps": 25, "mode": "append"},
    )
    data = json.loads(body)
    assert status == 200
    assert data == {"ok": True, "message": "Inserted clip.mov (20 frames)"}


def test_insert_traversal_over_http_is_400(live_server, tmp_path):
    srv, client = live_server
    srv.companion_config["mounts"] = {"broll": str(tmp_path).replace("\\", "/")}

    status, _headers, body = client.post_json(
        "/insert",
        {"share": "broll", "rel_path": "../../../Windows/System32/config/SAM",
         "in_frame": 0, "out_frame": 20, "fps": 25, "mode": "append"},
    )
    assert status == 400
    assert json.loads(body)["ok"] is False


def test_insert_resolve_not_running_over_http(live_server, tmp_path, monkeypatch):
    srv, client = live_server
    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"fake")
    srv.companion_config["mounts"] = {"broll": str(tmp_path).replace("\\", "/")}

    monkeypatch.setattr(
        broll_server.resolve_bridge,
        "perform_insert",
        lambda *a, **kw: {"ok": False, "message": "DaVinci Resolve is not running"},
    )

    status, _headers, body = client.post_json(
        "/insert",
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 0, "out_frame": 20,
         "fps": 25, "mode": "append"},
    )
    data = json.loads(body)
    assert status == 200
    assert data == {"ok": False, "message": "DaVinci Resolve is not running"}


def test_a_malformed_json_body_is_400_not_a_traceback(live_server):
    conn = http.client.HTTPConnection("127.0.0.1", live_server[1].port, timeout=5)
    payload = b"{not json"
    conn.request("POST", "/insert", body=payload,
                 headers={"Content-Type": "application/json",
                          "Content-Length": str(len(payload))})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    assert resp.status == 400
    assert json.loads(body)["ok"] is False


# ---------------------------------------------------------------------------
# A request nobody meant to send: types, Content-Length, and the dispatch guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [123, ["clip.mov"], {"name": "clip.mov"}, None, True])
def test_a_non_string_rel_path_is_400_not_a_dead_request(bad):
    """MED-5: translate_path assumed strings, so an AttributeError/TypeError
    escaped to socketserver.handle_error -- which writes to a sys.stderr that
    is None in the windowed build. No response, no log line, a browser tab
    waiting for its own timeout."""
    status, body = broll_server.build_insert_response(
        {"share": "broll", "rel_path": bad, "in_frame": 0, "out_frame": 10,
         "mode": "append"},
        {"broll": "Y:/broll"},
    )
    assert status == 400
    assert body["ok"] is False
    assert "rel_path" in body["message"]


@pytest.mark.parametrize("bad", [123, ["broll"], {"share": "broll"}, None])
def test_a_non_string_share_is_400_too(bad):
    """A dict share was the worst of them: mounts.get() raises TypeError on an
    unhashable key before any of the path rules run."""
    status, body = broll_server.build_insert_response(
        {"share": bad, "rel_path": "clip.mov", "in_frame": 0, "out_frame": 10,
         "mode": "append"},
        {"broll": "Y:/broll"},
    )
    assert status == 400
    assert body["ok"] is False


def test_a_mount_that_is_not_a_path_is_reported_not_crashed_on():
    """A hand-edited ~/.broll-companion.json can put anything in there."""
    status, body = broll_server.build_insert_response(
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 0, "out_frame": 10,
         "mode": "append"},
        {"broll": ["Y:/broll"]},
    )
    assert status == 200
    assert body["ok"] is False
    assert "not a path" in body["message"]


def test_a_non_string_rel_path_over_http_gets_an_answer(live_server):
    _srv, client = live_server
    status, _headers, body = client.post_json(
        "/insert",
        {"share": "broll", "rel_path": ["clip.mov"], "in_frame": 0, "out_frame": 10,
         "mode": "append"},
    )
    assert status == 400
    assert json.loads(body)["ok"] is False


@pytest.mark.parametrize("payload", [b'"just a string"', b"[1, 2, 3]", b"null"])
def test_a_json_body_that_is_not_an_object_is_400(live_server, payload):
    """`body.get` on a list is the same class of crash as the above."""
    _srv, client = live_server
    status, body = client.post_raw("/insert", payload)
    assert status == 400
    assert json.loads(body)["ok"] is False


def test_a_non_numeric_content_length_is_400(live_server):
    """MED-10: int(header) was unguarded, so "abc" crashed the handler.

    Header only, no body bytes: the handler answers WITHOUT reading, and
    bytes left unread in the receive buffer make the close an RST, which the
    client sees as a connection abort instead of the answer (Windows, seen
    while writing this)."""
    _srv, client = live_server
    status, body = client.post_raw("/insert", b"", content_length="abc")
    assert status == 400
    assert "Content-Length" in json.loads(body)["message"]


def test_an_oversized_body_is_refused_without_reading_it(live_server):
    """The other half of MED-10: an invented Content-Length parked a daemon
    thread in an unbounded buffered read -- which is exactly this request,
    a length nobody intends to send. CORS here is "*" plus private-network,
    so any page in the editor's browser can post to it."""
    _srv, client = live_server
    status, body = client.post_raw(
        "/insert", b"", content_length=broll_server.MAX_BODY_BYTES + 1)
    assert status == 413
    assert json.loads(body)["ok"] is False


def test_the_cap_is_a_few_hundred_kb_not_a_few_bytes():
    """Big enough that no legitimate body can reach it, small enough that the
    read is bounded."""
    assert 64 * 1024 <= broll_server.MAX_BODY_BYTES <= 1024 * 1024


def test_the_music_route_is_capped_on_the_same_terms(live_server):
    _srv, client = live_server
    status, body = client.post_raw(
        "/music/send", b"", content_length=broll_server.MAX_BODY_BYTES + 1)
    assert status == 413
    # ...in that route group's error shape, not the b-roll one.
    assert "error" in json.loads(body)


# ---------------------------------------------------------------------------
# POST /music/reveal (MUSIC-6, 2026-08-14)
# ---------------------------------------------------------------------------
#
# The music page's "show in folder" used to POST the SERVER's /api/reveal,
# which drove Explorer inside the dashboard's Linux container -- a button no
# editor could ever see the result of. It is a route on THIS listener now, for
# the same reason /music/send is: the one machine that can both be reached by
# that page and open a window in front of the editor is this one. What is
# pinned here is the DISPATCH; music_server owns the behaviour and
# test_music_server owns its tests.


def test_the_music_reveal_route_dispatches_with_this_groups_mounts(
        live_server, companion_config, monkeypatch):
    seen: list = []

    def _recorder(body, mounts):
        seen.append((body, mounts))
        return 200, {"ok": True, "message": "Showing cue.wav in P:\\Assets\\Music"}

    companion_config[music_server.MOUNTS_KEY] = {"music": "P:/Assets/Music"}
    monkeypatch.setattr(music_server, "build_reveal_response", _recorder)

    _srv, client = live_server
    status, _headers, body = client.post_json(
        "/music/reveal", {"share": "music", "rel_path": "Ambient/cue.wav"})

    assert status == 200
    assert json.loads(body)["ok"] is True
    (posted, mounts), = seen
    # The body reaches the handler intact, and the mounts come from the MUSIC
    # group's own key -- not "mounts", which is what GET /status hands the
    # b-roll settings panel.
    assert posted == {"share": "music", "rel_path": "Ambient/cue.wav"}
    assert mounts == {"music": "P:/Assets/Music"}


def test_the_music_reveal_route_answers_without_a_mount_configured(live_server):
    """No monkeypatching: the real handler, on a machine with no music mount.
    200 with the reason, because the page shows it inline -- and nothing is
    launched, so this cannot open a window on the developer's desktop."""
    _srv, client = live_server
    status, _headers, body = client.post_json(
        "/music/reveal", {"share": "music", "rel_path": "cue.wav"})
    assert status == 200
    assert json.loads(body) == {
        "ok": False, "error": "no mount configured for share 'music'"}


@pytest.mark.parametrize("payload", [b"{not json", b'"just a string"', b"[1, 2]",
                                     b"null"])
def test_a_music_reveal_body_that_is_not_an_object_is_400(live_server, payload):
    """`body.get` on a list is a crash, not a route -- in the music group's
    `error` shape, which is the key that page's api() helper reads."""
    _srv, client = live_server
    status, body = client.post_raw("/music/reveal", payload)
    assert status == 400
    parsed = json.loads(body)
    assert parsed["ok"] is False and "error" in parsed


def test_the_music_reveal_route_is_capped_on_the_same_terms(live_server):
    _srv, client = live_server
    status, body = client.post_raw(
        "/music/reveal", b"", content_length=broll_server.MAX_BODY_BYTES + 1)
    assert status == 413
    assert "error" in json.loads(body)


def test_a_handler_that_raises_answers_500_and_logs(live_server, monkeypatch, caplog):
    """The dispatch guard. socketserver's own handler prints the traceback to
    sys.stderr, which is None in the windowed build."""
    _srv, client = live_server

    def _boom(*a, **kw):
        raise RuntimeError("something nobody anticipated")

    monkeypatch.setattr(broll_server, "build_insert_response", _boom)

    with caplog.at_level("ERROR", logger="ccsync.broll"):
        status, _headers, body = client.post_json(
            "/insert",
            {"share": "broll", "rel_path": "clip.mov", "in_frame": 0,
             "out_frame": 10, "mode": "append"},
        )

    assert status == 500
    assert json.loads(body)["ok"] is False
    assert any("failed" in r.getMessage() for r in caplog.records)


def test_a_get_that_raises_is_guarded_too(live_server, monkeypatch, caplog):
    def _boom(*a, **kw):
        raise RuntimeError("nope")

    _srv, client = live_server
    monkeypatch.setattr(broll_server, "build_status_response", _boom)
    with caplog.at_level("ERROR", logger="ccsync.broll"):
        status, _headers, _body = client.get("/status")
    assert status == 500


# ---------------------------------------------------------------------------
# The Resolve half runs in a child (MED-3)
# ---------------------------------------------------------------------------


def test_status_asks_the_worker_not_the_api_on_this_thread(worker_in_process):
    """MED-3: try_connect() ran scriptapp() in-process under _API_LOCK, on the
    8899 request thread. Against a modal Resolve that blocks indefinitely, and
    the watcher, the fixer, FIX ALL and every tray read queue behind it."""
    broll_server.build_status_response({})
    assert [action for action, _kw in worker_in_process] == [
        music_worker.BROLL_STATUS_ACTION]


def test_the_status_probe_is_not_given_the_full_music_timeout(worker_in_process):
    """A settings-panel dot is not worth 90 seconds of "checking...", while an
    ImportMedia off a cold share genuinely is."""
    broll_server.build_status_response({})
    assert worker_in_process[0][1]["timeout"] == broll_server.STATUS_TIMEOUT
    assert broll_server.STATUS_TIMEOUT < music_server.TIMEOUT


def test_a_worker_that_never_answers_reports_resolve_as_absent():
    """A timeout arrives as the worker's own failure shape; the panel says
    "Resolve: no" rather than hanging."""
    result = broll_server.build_status_response(
        {}, caller=lambda action, **kw: {"ok": False, "error": "Resolve did not respond"})
    assert result["ok"] is True
    assert result["resolve_connected"] is False


def test_the_insert_goes_through_the_worker_with_the_translated_path(
        tmp_path, worker_in_process, monkeypatch):
    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"fake")
    monkeypatch.setattr(
        broll_server.resolve_bridge, "perform_insert",
        lambda path, in_frame, out_frame, canonical_fn=None, mode="append": {"ok": True, "message": "Inserted clip.mov"},
    )

    status, body = broll_server.build_insert_response(
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 5, "out_frame": 15,
         "mode": "append"},
        {"broll": str(tmp_path).replace("\\", "/")},
    )

    assert status == 200 and body["ok"] is True
    action, kw = worker_in_process[-1]
    assert action == music_worker.BROLL_INSERT_ACTION
    assert os.path.basename(kw["path"]) == "clip.mov"
    assert (kw["in_frame"], kw["out_frame"]) == (5, 15)


def test_a_worker_failure_still_reaches_the_toast_as_a_message(tmp_path):
    """The worker's own failures are {"ok": false, "error": ...}; the b-roll
    web UI's toast reads "message"."""
    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"fake")
    status, body = broll_server.build_insert_response(
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 0, "out_frame": 10,
         "mode": "append"},
        {"broll": str(tmp_path).replace("\\", "/")},
        caller=lambda action, **kw: {"ok": False, "error": "could not start the worker"},
    )
    assert status == 200 and body["ok"] is False
    assert body["message"] == "could not start the worker"


# ---------------------------------------------------------------------------
# POST /insert: a missing clip is synced down from the NAS (2026-08-11)
# ---------------------------------------------------------------------------


def _editor_cfg(tmp_path):
    """A remote editor's config: tree at tmp_path, working rclone remote."""
    return {
        "local_root": str(tmp_path),
        "mode": "editor",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/creators_club",
        "rclone_path": "rclone",
    }


def _insert_body(rel="military/naval/clip.mov"):
    return {"share": "broll", "rel_path": rel, "in_frame": 0, "out_frame": 10,
            "mode": "append"}


def test_a_missing_clip_starts_a_download_and_reports_progress(tmp_path):
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)
    calls = []

    def fetcher(ccsync_cfg, rel_path, dest):
        calls.append((ccsync_cfg, rel_path, dest))
        return {"state": "downloading", "progress": {"percent": 12, "bytes": 12,
                                                     "total_bytes": 100}}

    status, body = broll_server.build_insert_response(
        _insert_body(), mounts, ccsync_cfg=cfg, fetcher=fetcher)

    assert status == 200
    assert body["ok"] is False
    assert body["state"] == "downloading"
    assert "12%" in body["message"]
    assert body["progress"]["percent"] == 12
    assert calls[0][1] == "military/naval/clip.mov"
    assert calls[0][2] == str(
        tmp_path / "Assets" / "B-roll Archive" / "military" / "naval" / "clip.mov")


def test_the_fetch_gets_the_validated_rel_not_the_raw_client_string(tmp_path):
    """Backslashes and empty components are normalized before the rel is
    joined into an rclone remote spec."""
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)
    calls = []

    def fetcher(ccsync_cfg, rel_path, dest):
        calls.append(rel_path)
        return {"state": "downloading", "progress": {}}

    broll_server.build_insert_response(
        _insert_body(rel="military\\naval//clip.mov"), mounts,
        ccsync_cfg=cfg, fetcher=fetcher)

    assert calls == ["military/naval/clip.mov"]


def test_a_failed_download_reaches_the_toast_with_its_cause(tmp_path):
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)

    status, body = broll_server.build_insert_response(
        _insert_body(), mounts, ccsync_cfg=cfg,
        fetcher=lambda *a, **kw: {"state": "failed", "message": "sftp: permission denied"})

    assert status == 200
    assert body["ok"] is False
    assert "state" not in body
    assert "couldn't sync the clip from the NAS" in body["message"]
    assert "sftp: permission denied" in body["message"]


def test_a_finished_download_falls_through_to_the_insert(tmp_path, monkeypatch):
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)
    dest = tmp_path / "Assets" / "B-roll Archive" / "military" / "naval" / "clip.mov"

    def fetcher(ccsync_cfg, rel_path, dest_path):
        # The job's last act before reporting done is landing the file.
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake")
        return {"state": "done"}

    captured = {}
    monkeypatch.setattr(
        broll_server.resolve_bridge, "perform_insert",
        lambda path, in_frame, out_frame, canonical_fn=None, mode="append": (
            captured.setdefault("path", path),
            {"ok": True, "message": "Inserted clip.mov (10 frames)"})[-1],
    )

    status, body = broll_server.build_insert_response(
        _insert_body(), mounts, ccsync_cfg=cfg, fetcher=fetcher)

    assert status == 200
    assert body == {"ok": True, "message": "Inserted clip.mov (10 frames)"}
    assert captured["path"] == str(dest)


def test_no_ccsync_cfg_keeps_the_old_not_found_message(tmp_path):
    """The pre-fetch contract, pinned: without the companion's own config
    there is no remote to fetch from, and the old message must come back
    rather than a downloading state nothing will ever finish."""
    mounts = {"broll": str(tmp_path).replace("\\", "/")}

    def fetcher(*a, **kw):
        raise AssertionError("must not fetch without a ccsync config")

    status, body = broll_server.build_insert_response(
        _insert_body(rel="clip.mov"), mounts, ccsync_cfg=None, fetcher=fetcher)

    assert status == 200
    assert "is the share mounted?" in body["message"]


def test_a_base_rig_does_not_fetch_from_itself(tmp_path):
    """The base rig's local_root IS the NAS share: a file missing there is
    missing at the source, and rclone copying the NAS onto the NAS's own
    SMB mapping helps nobody."""
    cfg = dict(_editor_cfg(tmp_path), mode="base")
    mounts = broll_server.resolve_mounts({}, cfg)

    def fetcher(*a, **kw):
        raise AssertionError("a base rig must not fetch")

    status, body = broll_server.build_insert_response(
        _insert_body(), mounts, ccsync_cfg=cfg, fetcher=fetcher)

    assert "is the share mounted?" in body["message"]


def test_a_hand_overridden_mount_is_not_downloaded_into(tmp_path):
    """An explicit ~/.broll-companion.json entry means the editor pointed the
    share somewhere deliberate (an SMB mount, a mirror drive). rclone writing
    into it behind their back is not our call."""
    cfg = _editor_cfg(tmp_path)
    mounts = {"broll": "Y:/some/smb/mount"}

    def fetcher(*a, **kw):
        raise AssertionError("an overridden mount must not be fetched into")

    status, body = broll_server.build_insert_response(
        _insert_body(), mounts, ccsync_cfg=cfg, fetcher=fetcher)

    assert "is the share mounted?" in body["message"]


def test_other_shares_are_never_fetched(tmp_path):
    """Only "broll" has a derivable NAS-side location; a missing file on any
    other share keeps the old message."""
    cfg = _editor_cfg(tmp_path)
    mounts = {"archive_2019": str(tmp_path / "nowhere").replace("\\", "/")}

    def fetcher(*a, **kw):
        raise AssertionError("only the broll share may fetch")

    status, body = broll_server.build_insert_response(
        {"share": "archive_2019", "rel_path": "clip.mov", "in_frame": 0,
         "out_frame": 10, "mode": "append"},
        mounts, ccsync_cfg=cfg, fetcher=fetcher)

    assert "is the share mounted?" in body["message"]


def test_the_downloading_state_travels_over_http(live_server, tmp_path, monkeypatch):
    srv, client = live_server
    cfg = _editor_cfg(tmp_path)
    srv.ccsync_cfg = cfg
    srv.companion_config["mounts"] = broll_server.resolve_mounts({}, cfg)
    monkeypatch.setattr(
        broll_server.broll_fetch, "poll_fetch",
        lambda ccsync_cfg, rel_path, dest: {
            "state": "downloading", "progress": {"percent": 40}},
    )

    status, _headers, body = client.post_json("/insert", _insert_body())

    data = json.loads(body)
    assert status == 200
    assert data["ok"] is False
    assert data["state"] == "downloading"
    assert data["progress"]["percent"] == 40
