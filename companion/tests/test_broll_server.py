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


def test_perform_insert_creates_broll_bin_when_missing(monkeypatch):
    resolve, _media_pool, root = _make_stack()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: resolve)

    assert root.subfolders == []
    result = resolve_bridge.perform_insert("Y:/broll/clip.mov", 0, 50)

    assert result["ok"] is True
    assert len(root.subfolders) == 1
    assert root.subfolders[0].GetName() == "B-Roll"


def test_perform_insert_reuses_existing_bin_across_calls(monkeypatch):
    resolve, _media_pool, root = _make_stack()
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


def test_insert_mode_playhead_not_implemented():
    status, body = broll_server.build_insert_response(
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 0, "out_frame": 10,
         "mode": "playhead"},
        {"broll": "Y:/broll"},
    )
    assert status == 200
    assert body == {"ok": False, "message": "not implemented yet"}


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

    def fake_perform_insert(local_path, in_frame, out_frame):
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
        lambda local_path, in_frame, out_frame: {
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
        lambda path, in_frame, out_frame: {"ok": True, "message": "Inserted clip.mov"},
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
