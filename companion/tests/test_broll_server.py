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
import socket
import threading
from pathlib import Path

import pytest

from ccsync_companion import (
    broll_server, config as config_mod, loopback_guard, music_server, music_worker,
    resolve_bridge, resolve_prefs,
)

# The dashboard this test fleet's companions are pointed at; live_server puts
# it in the ccsync_cfg, so it is the one Origin browser callers may use.
DASH_ORIGIN = "http://100.64.0.1:8000"


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
    """Tiny http.client-based helper for hitting the test server.

    Every POST carries the loopback token by default (2026-08-17,
    COMMERCIAL_READINESS.md item 5): a state-changing request now needs an
    allowed Origin or that header, and this client is a LOCAL caller -- the
    tray, the wizard, curl -- which is the token's whole reason for existing.
    Pass token=False (or an origin=) to exercise the other paths.
    """

    def __init__(self, port: int):
        self.port = port

    def _connect(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def _auth_headers(self, token, origin) -> dict:
        headers = {}
        if token is True:
            headers[loopback_guard.TOKEN_HEADER] = loopback_guard.read_token() or ""
        elif isinstance(token, str):
            headers[loopback_guard.TOKEN_HEADER] = token
        if origin is not None:
            headers["Origin"] = origin
        return headers

    def get(self, path: str, origin=None, token=False):
        conn = self._connect()
        conn.request("GET", path, headers=self._auth_headers(token, origin))
        resp = conn.getresponse()
        body = resp.read()
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, body

    def post_json(self, path: str, obj: dict, origin=None, token=True,
                  content_type="application/json"):
        conn = self._connect()
        payload = json.dumps(obj).encode("utf-8")
        headers = {"Content-Length": str(len(payload))}
        if content_type is not None:
            headers["Content-Type"] = content_type
        headers.update(self._auth_headers(token, origin))
        conn.request("POST", path, body=payload, headers=headers)
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
        conn.putheader(loopback_guard.TOKEN_HEADER, loopback_guard.read_token() or "")
        conn.putheader("Content-Length", str(length))
        conn.endheaders()
        conn.send(payload)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def request_raw(self, method: str, path: str, headers: dict,
                    payload: bytes = b""):
        """One request with EXACTLY these headers -- no token, no defaults.

        The envelope checks (Host, Origin, Content-Type) are about what a
        request carries, so the tests for them cannot go through a helper
        that fills anything in.
        """
        conn = self._connect()
        conn.putrequest(method, path, skip_accept_encoding=True,
                        skip_host="Host" in headers)
        for name, value in headers.items():
            conn.putheader(name, value)
        if payload:
            conn.putheader("Content-Length", str(len(payload)))
        conn.endheaders()
        if payload:
            conn.send(payload)
        resp = conn.getresponse()
        body = resp.read()
        out = dict(resp.getheaders())
        conn.close()
        return resp.status, out, body

    def put(self, path: str, payload: bytes, content_type="application/octet-stream",
            ingest_header="1", token=False, origin=None, content_length=None):
        """A streamed upload with EXACTLY the envelope the caller names.

        Defaults to the browser's shape (octet-stream + X-CCSync-Ingest) but
        with neither Origin nor token, so the auth matrix can be driven one
        header at a time.
        """
        conn = self._connect()
        headers = {"Content-Length": str(len(payload) if content_length is None
                                         else content_length)}
        if content_type is not None:
            headers["Content-Type"] = content_type
        if ingest_header is not None:
            headers[broll_server.INGEST_HEADER] = ingest_header
        headers.update(self._auth_headers(token, origin))
        conn.request("PUT", path, body=payload, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        out = dict(resp.getheaders())
        conn.close()
        return resp.status, out, body

    def options(self, path: str, origin=None):
        conn = self._connect()
        headers = {"Origin": origin} if origin is not None else {}
        conn.request("OPTIONS", path, headers=headers)
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
    """A real BrollCompanionServer on an ephemeral loopback port.

    Built with a ccsync_cfg carrying a dashboard_url so the origin allow-list
    is non-empty: an unconfigured companion refuses every browser caller, and
    that is a state worth testing on purpose, not by accident everywhere.
    """
    # Never actually try to talk to Resolve during HTTP-layer tests.
    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: False)

    srv = broll_server.make_server(
        companion_config, host="127.0.0.1", port=0,
        ccsync_cfg={"dashboard_url": DASH_ORIGIN},
    )
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


def test_a_blank_mount_is_absent_at_the_translator_too(tmp_path):
    """comp-loopback-5, 2026-08-21: "a blank one counts as absent" was true of
    resolve_mounts and FALSE of the translator, which only refused None. ''
    passed the isinstance check and became the filesystem root, so 'broll' +
    'Users/x/tax.pdf' translated to '\\Users\\x\\tax.pdf' and
    contained_local_path's containment test (guarded by `if root:`) was
    skipped for exactly the mount that needed it most.

    Reachable with a leftover template ~/.broll-companion.json on a machine
    with no local_root yet, since resolve_mounts fills a blank in only for its
    OWN share and only when a default can be derived."""
    for blank in ("", "   "):
        with pytest.raises(broll_server.MountNotConfiguredError):
            broll_server.translate_path_with_root(
                "broll", "Users/x/private.mov", {"broll": blank}, platform="win32")
        with pytest.raises(broll_server.MountNotConfiguredError):
            broll_server.contained_local_path(
                "broll", "Users/x/private.mov", {"broll": blank})


def test_a_blank_mount_on_macos_falls_back_to_the_volumes_probe(monkeypatch):
    """"Blank" must mean absent, not "the root of the disk" -- and absent on
    macOS is the /Volumes probe, the same as a share with no entry at all
    (comp-loopback-5, 2026-08-21)."""
    monkeypatch.setattr(broll_server, "probe_darwin_mount",
                        lambda share, isdir=None: "/Volumes/BRoll")

    root, local = broll_server.translate_path_with_root(
        "broll", "clip.mov", {"broll": ""}, platform="darwin")

    assert root == "/Volumes/BRoll"
    assert local == "/Volumes/BRoll/clip.mov"


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
    # These tests model a Resolve whose scripting has been dead for a long
    # time: skip the NO_SERVER_MESSAGE grace (tested in
    # test_resolve_bridge_launch_window) so the dead-server wording answers.
    monkeypatch.setattr(resolve_bridge, "_no_server_since",
                        resolve_bridge.time.monotonic() - 10 * resolve_bridge.NO_SERVER_GRACE_SECONDS)
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
    assert result == {"ok": False, "message": "no timeline open - create one first"}


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
        # CMEDIA-3 (2026-09-04): a reply proves something is listening, not
        # what. The port comes from the socket at the route, and defaults
        # here to the one the whole product hardcodes in its URLs.
        "loopback": {"bound": True, "port": broll_server.PORT},
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
    assert set(data.keys()) == {"ok", "resolve_connected", "mounts", "version",
                                "loopback"}
    assert data["ok"] is True
    assert data["version"] == config_mod.VERSION
    # CMEDIA-3: the port is the LIVE socket's, not the configured one -- the
    # test server binds an ephemeral port and the answer has to say so.
    assert data["loopback"]["bound"] is True
    assert data["loopback"]["port"] == _srv.server_address[1]


# ---------------------------------------------------------------------------
# CORS / preflight
# ---------------------------------------------------------------------------


#
# THESE TESTS USED TO PIN THE WILDCARD. Until 2026-08-17 every assertion here
# read `Access-Control-Allow-Origin == "*"` with an unconditional
# Access-Control-Allow-Private-Network beside it -- i.e. they pinned exactly
# the hole COMMERCIAL_READINESS.md item 5 (C1) exists to close, which is why
# they were rewritten rather than kept. What survives is the PROPERTY they
# were protecting: the dashboard's own page must keep working, preflight and
# all, on every route and every status code.


def test_options_preflight_returns_204_with_cors_headers(live_server):
    _srv, client = live_server
    status, headers, body = client.options("/insert", origin=DASH_ORIGIN)
    assert status == 204
    assert headers.get("Access-Control-Allow-Origin") == DASH_ORIGIN
    assert "Content-Type" in headers.get("Access-Control-Allow-Headers", "")
    assert loopback_guard.TOKEN_HEADER in headers.get("Access-Control-Allow-Headers", "")
    assert body == b""


def test_get_status_has_cors_headers(live_server):
    _srv, client = live_server
    status, headers, body = client.get("/status", origin=DASH_ORIGIN)
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == DASH_ORIGIN
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
        origin=DASH_ORIGIN, token=False,
    )
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == DASH_ORIGIN
    data = json.loads(body)
    assert data["ok"] is False


def test_unknown_route_still_has_cors_headers(live_server):
    _srv, client = live_server
    status, headers, _body = client.get("/nope", origin=DASH_ORIGIN)
    assert status == 404
    assert headers.get("Access-Control-Allow-Origin") == DASH_ORIGIN


def test_the_response_varies_on_origin(live_server):
    """The allow decision is now per-request, so a cache that ignored Origin
    would hand one page another page's permission."""
    _srv, client = live_server
    _status, headers, _body = client.get("/status", origin=DASH_ORIGIN)
    assert "Origin" in headers.get("Vary", "")


def test_preflight_allows_private_network_access(live_server):
    """The b-roll UI is served from the cc_sync dashboard, so the page sits on
    a tailnet address and calls 127.0.0.1. Chromium treats public -> private as
    a Private Network Access request and blocks it AT THE PREFLIGHT unless the
    target opts in — the insert would fail before any of our handler code
    ran."""
    _srv, client = live_server
    status, headers, _body = client.options("/insert", origin=DASH_ORIGIN)
    assert status == 204
    assert headers.get("Access-Control-Allow-Private-Network") == "true"


def test_the_header_is_present_on_real_responses_too(live_server):
    _srv, client = live_server
    _status, headers, _body = client.get("/status", origin=DASH_ORIGIN)
    assert headers.get("Access-Control-Allow-Private-Network") == "true"


def test_the_https_form_of_the_dashboard_is_allowed_too(live_server):
    """Tailscale Serve fronts the same host on https (2026-08-17). A fleet
    provisioned with an http dashboard_url must not lose the button the day
    the NAS moves behind TLS."""
    _srv, client = live_server
    status, headers, _body = client.get(
        "/status", origin=DASH_ORIGIN.replace("http://", "https://"))
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == \
        DASH_ORIGIN.replace("http://", "https://")


# ---------------------------------------------------------------------------
# Who may drive the loopback (COMMERCIAL_READINESS.md item 5 / C1)
# ---------------------------------------------------------------------------


def test_a_disallowed_origin_is_refused_with_no_cors_header(live_server):
    """The whole point: an ad iframe or a phishing page in the editor's
    browser gets 403 AND no Access-Control-Allow-Origin, so it cannot even
    read the refusal."""
    _srv, client = live_server
    status, headers, body = client.get("/status", origin="https://evil.example")
    assert status == 403
    assert "Access-Control-Allow-Origin" not in headers
    assert "Access-Control-Allow-Private-Network" not in headers
    assert json.loads(body)["ok"] is False


def test_a_disallowed_origin_cannot_post_either(live_server):
    _srv, client = live_server
    status, headers, _body = client.post_json(
        "/insert", {"share": "broll", "rel_path": "clip.mov",
                    "in_frame": 0, "out_frame": 10},
        origin="https://evil.example", token=False,
    )
    assert status == 403
    assert "Access-Control-Allow-Origin" not in headers


def test_a_suffix_of_an_allowed_origin_is_not_allowed(live_server):
    """`startswith`-shaped allow-lists let evil.net in by appending; this one
    is an exact match."""
    _srv, client = live_server
    status, _headers, _body = client.get("/status", origin=DASH_ORIGIN + ".evil.net")
    assert status == 403


def test_a_disallowed_origin_gets_no_preflight(live_server):
    _srv, client = live_server
    status, headers, _body = client.options("/insert", origin="https://evil.example")
    assert status == 403
    assert "Access-Control-Allow-Private-Network" not in headers


def test_a_preflight_with_no_origin_is_refused(live_server):
    """A preflight is a browser asking permission. Nothing else sends one."""
    _srv, client = live_server
    status, _headers, _body = client.options("/insert")
    assert status == 403


def test_a_get_with_no_origin_still_works(live_server):
    """Opening http://127.0.0.1:8899/status in a tab is the self-test all
    three web UIs tell editors to run, and a top-level navigation sends no
    Origin at all."""
    _srv, client = live_server
    status, headers, body = client.get("/status")
    assert status == 200
    assert "Access-Control-Allow-Origin" not in headers
    assert json.loads(body)["ok"] is True


def test_a_post_with_no_origin_and_no_token_is_refused(live_server):
    _srv, client = live_server
    status, _headers, body = client.post_json(
        "/insert", {"share": "broll", "rel_path": "clip.mov",
                    "in_frame": 0, "out_frame": 10}, token=False,
    )
    assert status == 403
    assert loopback_guard.REFUSED_MESSAGE in json.loads(body)["message"]


def test_a_post_with_the_loopback_token_is_allowed(live_server):
    """The second way in: a local caller with no Origin to offer proves it is
    local by reading a file only this user can read."""
    _srv, client = live_server
    status, _headers, body = client.post_json(
        "/insert", {"share": "broll", "rel_path": "clip.mov",
                    "in_frame": 0, "out_frame": 10}, token=True,
    )
    assert status == 200
    assert json.loads(body)["ok"] is False  # no mount -- but it was ANSWERED


def test_a_wrong_token_is_refused(live_server):
    _srv, client = live_server
    status, _headers, _body = client.post_json(
        "/insert", {"share": "broll", "rel_path": "clip.mov",
                    "in_frame": 0, "out_frame": 10}, token="not-the-token",
    )
    assert status == 403


def test_the_token_file_is_written_where_local_callers_look(live_server):
    _srv, _client = live_server
    assert loopback_guard.token_path().is_file()
    assert loopback_guard.read_token()


def test_a_rebinding_host_header_is_refused(live_server):
    """`evil.example` resolved to 127.0.0.1 would make the attacker's page
    same-origin with this server and skip the Origin check entirely."""
    _srv, client = live_server
    status, _headers, _body = client.request_raw(
        "GET", "/status", {"Host": f"evil.example:{client.port}"})
    assert status == 403


def test_localhost_is_a_legitimate_host(live_server):
    _srv, client = live_server
    status, _headers, _body = client.request_raw(
        "GET", "/status", {"Host": f"localhost:{client.port}"})
    assert status == 200


def test_a_post_must_say_it_is_json(live_server):
    """text/plain is one of the three types a cross-origin <form> can send
    with no preflight at all."""
    _srv, client = live_server
    status, _headers, _body = client.post_json(
        "/insert", {"share": "broll", "rel_path": "clip.mov",
                    "in_frame": 0, "out_frame": 10},
        origin=DASH_ORIGIN, token=False, content_type="text/plain",
    )
    assert status == 415


def test_a_json_content_type_with_a_charset_is_fine(live_server):
    _srv, client = live_server
    status, _headers, _body = client.post_json(
        "/insert", {"share": "broll", "rel_path": "clip.mov",
                    "in_frame": 0, "out_frame": 10},
        origin=DASH_ORIGIN, token=False,
        content_type="application/json; charset=utf-8",
    )
    assert status == 200


def test_an_unconfigured_companion_refuses_every_browser_caller(companion_config,
                                                                monkeypatch):
    """A de-tenanted build with no dashboard_url is pointed at no dashboard,
    so no page is entitled to drive it (the token still works)."""
    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: False)
    srv = broll_server.make_server(companion_config, host="127.0.0.1", port=0,
                                   ccsync_cfg={"dashboard_url": ""})
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        status, _headers, _body = BrollClient(srv.server_address[1]).get(
            "/status", origin=DASH_ORIGIN)
        assert status == 403
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


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
                          "Origin": DASH_ORIGIN,
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


# ===========================================================================
# b-roll ingest routes (docs/BROLL_INGEST_PLAN.md §4.1, PR-G, 2026-08-18)
# ===========================================================================
#
# The orchestrator itself is test_broll_ingest.py's; everything here is about
# the ENVELOPE -- who may PUT bytes into staging, what the cap is on that one
# route, where the file is allowed to land, and that every route still refuses
# cleanly on a companion whose orchestrator never constructed.


class FakeIngestor:
    """The orchestrator's surface as broll_server uses it, and nothing else.

    Deliberately a stub rather than a real BrollIngestor: these tests are about
    the HTTP layer's rules, and a real one would drag ffmpeg, a GPU probe and a
    fleet client into an assertion about a 415.
    """

    def __init__(self, staging_root):
        self.staging_root = str(staging_root)
        self.calls: list = []
        self.slot_status = 200
        self.slot_extra: dict = {}
        self.uploads: list = []
        self.busy_state = {"batch_uid": None, "state": "nothing-to-do"}
        self.run_result = (202, {"ok": True, "batch_uid": "b" * 32, "state": "claimed"})
        self.prepare_result = (202, {"ok": True, "staging_id": "s1", "items": []})
        self.control_result = (200, {"ok": True, "state": "paused"})
        self.thumb_result = (200, b"\xff\xd8jpegbytes")
        self.stopped = False
        # What /pick recorded as the allow-list prepare measures a
        # source='path' item against (comp-loopback-6, 2026-08-21).
        self.picked: list = []

    # -- what broll_server calls ------------------------------------------
    def busy(self):
        return dict(self.busy_state)

    def upload_slot(self, staging_id, local_id):
        self.calls.append(("upload_slot", staging_id, local_id))
        if self.slot_status != 200:
            return self.slot_status, {"ok": False, "message": "no"}
        dest = Path(self.staging_root) / staging_id / f"{local_id}.mp4"
        return 200, {"path": str(dest), "staging_root": self.staging_root,
                     "size": 10, **self.slot_extra}

    def note_picked(self, files):
        self.picked.extend(files)

    def note_upload(self, staging_id, local_id, written):
        self.uploads.append((staging_id, local_id, written))
        return 200, {"ok": True, "size": written, "hash": "abc", "probe": {}}

    def progress(self, staging_id):
        self.calls.append(("progress", staging_id))
        return {"staging": {"items": []}, "batch": {"uid": None}}

    def thumb(self, staging_id, local_id):
        self.calls.append(("thumb", staging_id, local_id))
        return self.thumb_result

    def prepare(self, body):
        self.calls.append(("prepare", body))
        return self.prepare_result

    def run(self, batch_uid, staging_id, run_mode):
        self.calls.append(("run", batch_uid, staging_id, run_mode))
        return self.run_result

    def control(self, action):
        self.calls.append(("control", action))
        return self.control_result

    def stop(self):
        self.stopped = True


class FakeIngestDeps:
    def __init__(self, ingestor, editor="alex"):
        self.ingestor = ingestor
        self._editor = editor

    def editor(self):
        return self._editor


@pytest.fixture
def ingest_server(companion_config, tmp_path, monkeypatch):
    """A live server with an ingest-capable deps object on it."""
    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: False)
    staging = tmp_path / "staging"
    (staging / "s1").mkdir(parents=True)
    ingestor = FakeIngestor(staging)
    srv = broll_server.make_server(
        companion_config, host="127.0.0.1", port=0,
        ccsync_cfg={"dashboard_url": DASH_ORIGIN,
                    "broll_ingest_staging_dir": str(staging)},
        ingest_deps=FakeIngestDeps(ingestor),
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, BrollClient(srv.server_address[1]), ingestor, staging
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


# -- capabilities -----------------------------------------------------------


def test_capabilities_answers_200_even_when_this_machine_cannot_index(live_server):
    """A non-200 reads to the page as "no companion here", which is a different
    (and less useful) message than "this GPU is too small". The verdict is in
    the body -- see ytdl's identical rule."""
    srv, client = live_server

    status, _headers, body = client.get("/broll/ingest/capabilities")

    data = json.loads(body)
    assert status == 200
    assert data["ok"] is False
    # No orchestrator on this server at all: that IS one of the reasons.
    assert any("switched off" in r for r in data["reasons"])
    assert data["run_modes"] == ["idle", "foreground"]


def test_capabilities_reports_the_staging_floor_and_free_space(ingest_server):
    srv, client, ingestor, staging = ingest_server

    data = json.loads(client.get("/broll/ingest/capabilities")[2])

    assert data["staging"]["dir"] == str(staging)
    assert data["staging"]["floor_bytes"] == 20_000_000_000
    assert data["staging"]["free_bytes"] > 0
    assert set(data["tiers"]) == {"good", "best"}


def test_capabilities_refuses_while_a_batch_is_already_running(ingest_server):
    srv, client, ingestor, staging = ingest_server
    ingestor.busy_state = {"batch_uid": "a" * 32, "state": "running"}

    data = json.loads(client.get("/broll/ingest/capabilities")[2])

    assert data["ok"] is False
    assert any("already indexing" in r for r in data["reasons"])
    assert data["busy"]["batch_uid"] == "a" * 32


def test_capabilities_does_no_gpu_probe(ingest_server, monkeypatch):
    """ZERO I/O bar one disk_usage: the page asks this before it renders the
    drop zone. A probe here would spawn nvidia-smi on every page load."""
    srv, client, ingestor, staging = ingest_server

    def _boom(*args, **kwargs):
        raise AssertionError("capabilities must not probe the GPU")

    monkeypatch.setattr(broll_server.broll_vlm_sidecar, "gpu", _boom)
    monkeypatch.setattr(broll_server.ffmpeg_tools, "detect_encoders", _boom)

    assert client.get("/broll/ingest/capabilities")[0] == 200


def test_capabilities_says_nvenc_is_unknown_until_something_probed(ingest_server):
    """None, not False: "we have not asked" and "this build has no NVENC" send
    an editor to different places. The encoder cache is a module global that
    survives between tests (and, live, for the life of the process), so this
    clears it rather than assuming what ran before it."""
    from ccsync_companion import ffmpeg_tools

    srv, client, ingestor, staging = ingest_server
    ffmpeg_tools.reset_encoder_cache()

    assert json.loads(client.get("/broll/ingest/capabilities")[2])["nvenc"] is None

    ffmpeg_tools._encoder_cache["ffmpeg"] = frozenset({"h264_nvenc"})
    try:
        assert json.loads(client.get("/broll/ingest/capabilities")[2])["nvenc"] is True
    finally:
        ffmpeg_tools.reset_encoder_cache()


# -- the JSON routes --------------------------------------------------------


def test_prepare_run_and_control_reach_the_orchestrator(ingest_server):
    srv, client, ingestor, staging = ingest_server

    assert client.post_json("/broll/ingest/prepare", {"items": []})[0] == 202
    assert client.post_json(
        "/broll/ingest/run",
        {"batch_uid": "b" * 32, "staging_id": "s1", "run_mode": "foreground"})[0] == 202
    assert client.post_json("/broll/ingest/control", {"action": "pause"})[0] == 200

    assert ("run", "b" * 32, "s1", "foreground") in ingestor.calls
    assert ("control", "pause") in ingestor.calls


def test_run_reads_only_the_three_fields_it_is_allowed_to(ingest_server):
    """The tier, the archive names, the taxonomy and the settings all come back
    from the server's claim under the fleet token. The browser dispatches; it
    does not write the work order (the /music/send principle)."""
    srv, client, ingestor, staging = ingest_server

    client.post_json("/broll/ingest/run", {
        "batch_uid": "b" * 32, "staging_id": "s1", "run_mode": "idle",
        "tier": "best", "archive_dir": "../../etc", "upload_originals": False,
    })

    assert ingestor.calls[-1] == ("run", "b" * 32, "s1", "idle")


def test_start_now_is_the_legacy_spelling_of_foreground(ingest_server):
    """The plan's first draft called it `start_now`, and a page cached before
    2026-08-18 still sends it. run_mode wins when both arrive."""
    srv, client, ingestor, staging = ingest_server

    client.post_json("/broll/ingest/run",
                     {"batch_uid": "b" * 32, "staging_id": "s1", "start_now": True})
    assert ingestor.calls[-1] == ("run", "b" * 32, "s1", "foreground")

    client.post_json("/broll/ingest/run",
                     {"batch_uid": "b" * 32, "staging_id": "s1",
                      "start_now": True, "run_mode": "idle"})
    assert ingestor.calls[-1] == ("run", "b" * 32, "s1", "idle")


def test_the_tier_block_carries_what_the_page_renders(ingest_server):
    """The SPA disables a tier it cannot run and confirms the download size
    before Run, so both have to be in the capability answer."""
    srv, client, ingestor, staging = ingest_server

    caps = json.loads(client.get("/broll/ingest/capabilities")[2])
    tiers = caps["tiers"]

    # The floor the server sends is the Apple unified-memory one on Apple
    # silicon and the discrete-VRAM one elsewhere (broll_server's own rule),
    # and GitHub's hosted macOS runners are M-series on some days and not on
    # others (2026-08-30: 24 == 12 failed a release build). So the test pins
    # the RULE against the catalogue, and the two plain numbers only where
    # the machine is not Apple silicon.
    from ccsync_companion import broll_vlm_sidecar

    def floor(key):
        meta = broll_vlm_sidecar._models().tier(key)
        return meta.apple_unified_gb if caps["gpu"]["apple_silicon"] else meta.vram_gb

    assert tiers["best"]["vram_gb"] == floor("best")
    assert tiers["good"]["vram_gb"] == floor("good")
    if not caps["gpu"]["apple_silicon"]:
        assert (tiers["best"]["vram_gb"], tiers["good"]["vram_gb"]) == (12, 8)
    assert tiers["good"]["download_bytes"] > 3_000_000_000
    assert tiers["good"]["label"]
    assert isinstance(tiers["good"]["fits"], bool)


def test_run_answers_the_orchestrators_refusal_verbatim(ingest_server):
    """A tier that does not fit is a 503 whose message is the one the tray
    balloons -- the page must be able to show the same sentence."""
    srv, client, ingestor, staging = ingest_server
    ingestor.run_result = (503, {"ok": False, "message": (
        "Can't index b-roll: Best needs 12 GB VRAM, this GPU has 8 GB - choose Good")})

    status, _headers, body = client.post_json(
        "/broll/ingest/run", {"batch_uid": "b" * 32, "staging_id": "s1"})

    assert status == 503
    assert "12 GB VRAM" in json.loads(body)["message"]


def test_progress_and_thumb_answer_from_staging(ingest_server):
    srv, client, ingestor, staging = ingest_server

    status, _h, body = client.get("/broll/ingest/progress?staging_id=s1")
    assert status == 200
    assert json.loads(body)["staging"] == {"items": []}

    status, headers, body = client.get("/broll/ingest/thumb?staging_id=s1&local_id=x")
    assert status == 200
    assert headers["Content-Type"] == "image/jpeg"
    assert headers["Cache-Control"] == "no-store"
    assert body == b"\xff\xd8jpegbytes"


def test_a_thumb_refusal_is_json_not_a_broken_image(ingest_server):
    srv, client, ingestor, staging = ingest_server
    ingestor.thumb_result = (404, {"ok": False, "message": "no such clip"})

    status, headers, body = client.get("/broll/ingest/thumb?staging_id=s1&local_id=x")

    assert status == 404
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body)["message"] == "no such clip"


def test_every_ingest_route_refuses_cleanly_with_no_orchestrator(live_server):
    """A companion whose orchestrator failed to construct serves every other
    route unchanged and says "cannot index here" -- it does not 500."""
    srv, client = live_server

    assert client.post_json("/broll/ingest/prepare", {"items": []})[0] == 503
    assert client.post_json("/broll/ingest/run", {"batch_uid": "x"})[0] == 503
    assert client.post_json("/broll/ingest/control", {"action": "pause"})[0] == 503
    assert client.get("/broll/ingest/progress")[0] == 503
    assert client.get("/broll/ingest/thumb")[0] == 503
    assert client.put("/broll/ingest/upload/s1/i1", b"x", token=True)[0] == 503


def test_an_unknown_ingest_route_is_a_404(ingest_server):
    srv, client, ingestor, staging = ingest_server

    assert client.get("/broll/ingest/nope")[0] == 404
    assert client.post_json("/broll/ingest/nope", {})[0] == 404
    assert client.put("/broll/ingest/upload/s1", b"x", token=True)[0] == 404


def test_pick_runs_the_dialog_on_the_ui_thread(ingest_server, monkeypatch):
    srv, client, ingestor, staging = ingest_server
    from ccsync_companion import popup

    monkeypatch.setattr(popup, "pick_media_sources", lambda kind, timeout=300: [
        {"path": "D:/card/A001.MP4", "name": "A001.MP4", "size": 5, "rel_dir": ""}])

    status, _headers, body = client.post_json("/broll/ingest/pick", {"kind": "files"})

    data = json.loads(body)
    assert status == 200
    assert data["files"][0]["name"] == "A001.MP4"


def test_pick_records_what_it_returned_as_the_allow_list(ingest_server, monkeypatch):
    """comp-loopback-6, 2026-08-21: /pick is the only route that learns a local
    path, so its answer is also what `prepare` measures a source='path' item
    against. Recorded from the PICKER, never from the body of the prepare that
    follows it."""
    srv, client, ingestor, staging = ingest_server
    from ccsync_companion import popup

    monkeypatch.setattr(popup, "pick_media_sources", lambda kind, timeout=300: [
        {"path": "D:/card/A001.MP4", "name": "A001.MP4", "size": 5, "rel_dir": ""}])

    client.post_json("/broll/ingest/pick", {"kind": "files"})

    assert [entry["path"] for entry in ingestor.picked] == ["D:/card/A001.MP4"]


def test_pick_still_answers_when_the_allow_list_cannot_be_recorded(ingest_server,
                                                                  monkeypatch):
    """Bookkeeping is not a refusal: an orchestrator too old to have
    `note_picked` (or one that raised) must still hand the editor their
    files."""
    srv, client, ingestor, staging = ingest_server
    from ccsync_companion import popup

    monkeypatch.setattr(popup, "pick_media_sources", lambda kind, timeout=300: [
        {"path": "D:/card/A001.MP4", "name": "A001.MP4", "size": 5, "rel_dir": ""}])
    monkeypatch.delattr(type(ingestor), "note_picked", raising=False)

    status, _headers, body = client.post_json("/broll/ingest/pick", {"kind": "files"})

    assert status == 200
    assert json.loads(body)["files"][0]["name"] == "A001.MP4"


def test_pick_says_cancelled_rather_than_erroring(ingest_server, monkeypatch):
    srv, client, ingestor, staging = ingest_server
    from ccsync_companion import popup

    monkeypatch.setattr(popup, "pick_media_sources", lambda kind, timeout=300: [])

    data = json.loads(client.post_json("/broll/ingest/pick", {"kind": "folder"})[2])

    assert data == {"ok": False, "message": "cancelled"}


def test_pick_refuses_a_kind_it_does_not_know(ingest_server):
    srv, client, ingestor, staging = ingest_server

    status, _headers, body = client.post_json(
        "/broll/ingest/pick", {"kind": "everything-on-this-disk"})

    assert status == 400


# -- the PUT auth matrix ----------------------------------------------------


def test_a_dropped_file_is_accepted_with_the_ingest_header(ingest_server):
    srv, client, ingestor, staging = ingest_server

    status, _headers, body = client.put(
        "/broll/ingest/upload/s1/i1", b"0123456789", origin=DASH_ORIGIN)

    assert status == 200
    assert json.loads(body)["hash"] == "abc"
    assert (staging / "s1" / "i1.mp4").read_bytes() == b"0123456789"
    assert ingestor.uploads == [("s1", "i1", 10)]


def test_a_put_with_no_origin_and_no_token_is_refused(ingest_server):
    """The same rule every POST here runs on: an allowed Origin or the token.
    The X-CCSync-Ingest header proves a preflight happened, not who called."""
    srv, client, ingestor, staging = ingest_server

    status, _headers, _body = client.put("/broll/ingest/upload/s1/i1", b"0123456789")

    assert status == 403
    assert not (staging / "s1" / "i1.mp4").exists()


def test_a_put_from_a_hostile_origin_is_refused(ingest_server):
    srv, client, ingestor, staging = ingest_server

    status, headers, _body = client.put(
        "/broll/ingest/upload/s1/i1", b"0123456789", origin="https://evil.example")

    assert status == 403
    assert "Access-Control-Allow-Origin" not in headers
    assert not (staging / "s1" / "i1.mp4").exists()


def test_the_loopback_token_is_the_other_way_in(ingest_server):
    srv, client, ingestor, staging = ingest_server

    status, _headers, _body = client.put(
        "/broll/ingest/upload/s1/i1", b"0123456789", token=True, ingest_header=None)

    assert status == 200


def test_octet_stream_without_the_ingest_header_or_token_is_refused(ingest_server):
    """CSRF: a page that never preflighted must not be able to stream bytes
    into staging. The Origin got it past the envelope; this is the second,
    independent gate (plan §4.1)."""
    srv, client, ingestor, staging = ingest_server

    status, _headers, _body = client.put(
        "/broll/ingest/upload/s1/i1", b"0123456789",
        origin=DASH_ORIGIN, ingest_header=None)

    assert status == 403
    assert not (staging / "s1" / "i1.mp4").exists()


def test_a_json_body_on_the_upload_route_is_415(ingest_server):
    srv, client, ingestor, staging = ingest_server

    status, _headers, _body = client.put(
        "/broll/ingest/upload/s1/i1", b"{}", content_type="application/json",
        origin=DASH_ORIGIN)

    assert status == 415


def test_a_form_content_type_on_the_upload_route_is_415(ingest_server):
    """text/plain, multipart/form-data and x-www-form-urlencoded are the three
    a cross-origin <form> can send with no preflight at all."""
    srv, client, ingestor, staging = ingest_server

    status, _headers, _body = client.put(
        "/broll/ingest/upload/s1/i1", b"x" * 10,
        content_type="multipart/form-data", origin=DASH_ORIGIN)

    assert status == 415


# -- the PUT body rules -----------------------------------------------------


def test_a_body_bigger_than_declared_is_413_and_leaves_nothing(ingest_server):
    """The slot said 10 bytes; the request announces a megabyte. Refused
    BEFORE the first chunk is read, so the drive never sees it -- which is
    also why this is driven on a raw socket: nothing is drained, and a client
    still pushing a megabyte into a closed connection is what a browser
    handles and http.client does not."""
    srv, client, ingestor, staging = ingest_server
    ingestor.slot_extra = {"size": 10}

    sock = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5)
    try:
        sock.sendall(
            f"PUT /broll/ingest/upload/s1/i1 HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{srv.server_address[1]}\r\n"
            f"Origin: {DASH_ORIGIN}\r\n"
            f"Content-Type: application/octet-stream\r\n"
            f"{broll_server.INGEST_HEADER}: 1\r\n"
            f"Content-Length: 1000000\r\n\r\n".encode()
        )
        answer = sock.recv(4096).decode("latin-1")
    finally:
        sock.close()

    assert " 413 " in answer.splitlines()[0]
    assert not (staging / "s1" / "i1.mp4").exists()
    assert not (staging / "s1" / "i1.mp4.partial").exists()
    assert ingestor.uploads == []


def test_the_cap_is_this_files_declared_size_not_the_json_body_cap(ingest_server):
    """MAX_BODY_BYTES is 256 KiB and a camera original is 40 GB: the upload
    route's cap is per-file, which is the whole reason do_PUT exists."""
    srv, client, ingestor, staging = ingest_server
    big = broll_server.MAX_BODY_BYTES * 2
    ingestor.slot_extra = {"size": big}

    status, _headers, _body = client.put(
        "/broll/ingest/upload/s1/i1", b"y" * big, origin=DASH_ORIGIN)

    assert status == 200
    assert (staging / "s1" / "i1.mp4").stat().st_size == big


def test_a_truncated_upload_keeps_neither_file(ingest_server):
    """A short file that reached the hashing stage would be indexed and
    uploaded as if it were the whole clip.

    Driven on a raw socket with a half-close, because that is what a browser
    tab closed mid-drop actually does: http.client would sit waiting for a
    response the server is not going to send until the body it was promised
    arrives (or the connection ends).
    """
    srv, client, ingestor, staging = ingest_server

    sock = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5)
    try:
        sock.sendall(
            f"PUT /broll/ingest/upload/s1/i1 HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{srv.server_address[1]}\r\n"
            f"Origin: {DASH_ORIGIN}\r\n"
            f"Content-Type: application/octet-stream\r\n"
            f"{broll_server.INGEST_HEADER}: 1\r\n"
            f"Content-Length: 10\r\n\r\nxx".encode()
        )
        sock.shutdown(socket.SHUT_WR)
        answer = sock.recv(4096).decode("latin-1")
    finally:
        sock.close()

    assert answer.startswith("HTTP/1.0 400") or answer.startswith("HTTP/1.1 400")
    assert not (staging / "s1" / "i1.mp4").exists()
    assert not (staging / "s1" / "i1.mp4.partial").exists()


def test_the_bytes_land_through_a_partial_that_is_renamed(ingest_server, monkeypatch):
    """broll_fetch's rule: a half-written file that looks finished is worse
    than no file, and the next attempt must be able to tell them apart."""
    srv, client, ingestor, staging = ingest_server
    seen: list = []
    real_replace = broll_server.os.replace

    def _spy(src, dst):
        seen.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(broll_server.os, "replace", _spy)

    client.put("/broll/ingest/upload/s1/i1", b"0123456789", origin=DASH_ORIGIN)

    assert seen and seen[0][0].endswith("i1.mp4.partial")
    assert seen[0][1].endswith("i1.mp4")


def test_an_upload_slot_the_orchestrator_refuses_is_answered_verbatim(ingest_server):
    srv, client, ingestor, staging = ingest_server
    ingestor.slot_status = 409

    status, _headers, _body = client.put(
        "/broll/ingest/upload/s1/i1", b"0123456789", origin=DASH_ORIGIN)

    assert status == 409
    assert ingestor.uploads == []


def test_a_slot_pointing_outside_staging_is_refused(ingest_server, tmp_path):
    """Belt and braces over the orchestrator's own containment check: this is
    the only route on this listener that WRITES a caller-named file."""
    srv, client, ingestor, staging = ingest_server
    escape = tmp_path / "elsewhere"
    escape.mkdir()

    def _escaping_slot(staging_id, local_id):
        return 200, {"path": str(escape / "stolen.mp4"),
                     "staging_root": str(staging), "size": 10}

    ingestor.upload_slot = _escaping_slot

    status, _headers, _body = client.put(
        "/broll/ingest/upload/s1/i1", b"0123456789", origin=DASH_ORIGIN)

    assert status == 403
    assert not (escape / "stolen.mp4").exists()


def test_no_free_space_is_507_before_a_byte_is_accepted(ingest_server, monkeypatch):
    srv, client, ingestor, staging = ingest_server
    ingestor.slot_extra = {"size": 5_000_000_000}
    monkeypatch.setattr(broll_server, "_free_bytes_at", lambda path: 6_000_000_000)

    status, _headers, body = client.put(
        "/broll/ingest/upload/s1/i1", b"z" * 10, content_length=10,
        origin=DASH_ORIGIN)

    assert status == 507
    assert "free some space" in json.loads(body)["message"]
    assert ingestor.uploads == []


# -- CORS -------------------------------------------------------------------


def test_the_preflight_advertises_put_and_the_ingest_header(ingest_server):
    """A method (or header) a preflight does not name is one the browser
    refuses before the request is made -- i.e. no drag-and-drop at all."""
    srv, client, ingestor, staging = ingest_server

    status, headers, _body = client.options("/broll/ingest/upload/s1/i1",
                                            origin=DASH_ORIGIN)

    assert status == 204
    assert "PUT" in headers["Access-Control-Allow-Methods"]
    assert broll_server.INGEST_HEADER in headers["Access-Control-Allow-Headers"]


def test_a_hostile_origin_gets_no_preflight_for_the_upload_route(ingest_server):
    srv, client, ingestor, staging = ingest_server

    status, headers, _body = client.options("/broll/ingest/upload/s1/i1",
                                            origin="https://evil.example")

    assert status == 403
    assert "Access-Control-Allow-Origin" not in headers


# -- staging paths ----------------------------------------------------------


def test_staging_lives_inside_the_archive_by_default(tmp_path):
    cfg = {"local_root": str(tmp_path / "tree")}

    root = broll_server.ingest_staging_root(cfg)

    assert root == Path(tmp_path / "tree", "Assets", "B-roll Archive", ".ingest")


def test_the_base_rig_can_stage_somewhere_else(tmp_path):
    """Its local_root IS the NAS share, so staging there pushes every original
    over SMB twice (plan §9.2)."""
    cfg = {"local_root": str(tmp_path / "tree"),
           "broll_ingest_staging_dir": str(tmp_path / "fast-ssd")}

    assert broll_server.ingest_staging_root(cfg) == tmp_path / "fast-ssd"


def test_a_machine_with_no_tree_has_nowhere_to_stage(tmp_path):
    assert broll_server.ingest_staging_root({"local_root": ""}) is None


def test_stopping_the_server_stops_the_orchestrator(ingest_server):
    """An ffmpeg still writing into staging after the tray exits is an orphan
    nothing supervises -- same rule as the fetch jobs and the ytdl executor."""
    srv, client, ingestor, staging = ingest_server

    broll_server.stop(srv)

    assert ingestor.stopped is True


# ---------------------------------------------------------------------------
# The origin allow-list is CACHED, not frozen at startup
# (bug-hunt-2026-09-03 comp-broll-music-2)
# ---------------------------------------------------------------------------


def test_a_manifest_that_lands_after_startup_is_picked_up(companion_config,
                                                          monkeypatch):
    """app.start() refreshes the site manifest on a BACKGROUND thread and then
    starts this server synchronously a few statements later, so a manifest
    whose dashboard_url has just changed lands after the allow-list was built.
    It used to stay stale for the whole session: every Send-to-Resolve,
    /music/send and ingest POST from the dashboard the editor is actually
    looking at answered 403 until the next tray start.
    """
    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: False)
    site = {"dashboard_url": ""}
    monkeypatch.setattr(broll_server.site_mod, "cached_site", lambda: dict(site))

    srv = broll_server.make_server(companion_config, host="127.0.0.1", port=0,
                                   ccsync_cfg={"dashboard_url": ""})
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        client = BrollClient(port)
        moved = "https://nas.example.ts.net"
        status, _headers, _body = client.get("/status", origin=moved)
        assert status == 403

        # The re-provision lands, and the TTL passes (the deadline is the
        # wall clock the fix reads -- 30 s later this is what it holds).
        site["dashboard_url"] = moved
        srv._origin_deadline = 0.0

        status, headers, _body = client.get("/status", origin=moved)
        assert status == 200
        assert headers.get("Access-Control-Allow-Origin") == moved
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_the_allow_list_is_not_rebuilt_on_every_request(companion_config,
                                                        monkeypatch):
    """Building it READS THE SITE MANIFEST OFF DISK, and a request thread is
    not the place for a file read -- the reason it was computed once in the
    constructor in the first place."""
    reads = []

    def _cached_site():
        reads.append(1)
        return {"dashboard_url": DASH_ORIGIN}

    monkeypatch.setattr(broll_server.site_mod, "cached_site", _cached_site)
    srv = broll_server.make_server(companion_config, host="127.0.0.1", port=0,
                                   ccsync_cfg={"dashboard_url": DASH_ORIGIN})
    try:
        built = len(reads)
        for _ in range(20):
            assert srv.origin_policy()[0] == srv.allowed_origins
        assert len(reads) == built
    finally:
        srv.server_close()


def test_a_site_manifest_that_has_gone_unreadable_keeps_the_last_policy(
        companion_config, monkeypatch):
    """A refresh that raises must not empty the allow-list: the dashboard the
    editor is looking at does not stop being theirs because site.json went
    missing for a moment."""
    monkeypatch.setattr(broll_server.site_mod, "cached_site",
                        lambda: {"dashboard_url": DASH_ORIGIN})
    srv = broll_server.make_server(companion_config, host="127.0.0.1", port=0,
                                   ccsync_cfg={"dashboard_url": DASH_ORIGIN})
    try:
        held = srv.allowed_origins
        assert DASH_ORIGIN in held

        def _boom():
            raise OSError("site.json is gone")

        monkeypatch.setattr(broll_server.site_mod, "cached_site", _boom)
        srv._origin_deadline = 0.0

        assert srv.origin_policy()[0] == held
    finally:
        srv.server_close()


# ---------------------------------------------------------------------------
# A refused POST drains its body (bug-hunt-2026-09-03 comp-broll-music-4)
# ---------------------------------------------------------------------------


def _bare_handler():
    """A handler with no socket, driven method by method (the pattern
    test_music_ingest.py uses for _dispatch_get)."""
    return broll_server.BrollRequestHandler.__new__(broll_server.BrollRequestHandler)


def test_a_refused_post_swallows_its_body():
    """do_PUT has had this since the upload route existed: a refusal that
    leaves an unread body in the receive buffer makes the CLOSE a reset, and
    the client loses the 403 that explained what happened -- it sees what a
    firewall looks like instead. do_POST refused the same way and did not
    drain, so a 200 KB /broll/ingest/prepare from a stale origin reported "the
    companion is not running"."""
    import io as _io

    handler = _bare_handler()
    body = b"x" * 4096
    handler.command, handler.path = "POST", "/broll/ingest/prepare"
    handler.rfile = _io.BytesIO(body)
    handler.headers = {"Content-Length": str(len(body))}
    handler._vet_request = lambda: False  # the 403 is already on the wire

    handler.do_POST()

    assert handler.rfile.tell() == len(body)


def test_a_post_whose_body_was_read_is_not_waited_for_twice():
    """The drain subtracts what the route already consumed. Without that
    accounting the tail read would sit waiting for a second copy of the body
    that no client is going to send."""
    import io as _io

    handler = _bare_handler()
    payload = json.dumps({"items": []}).encode("utf-8")
    handler.command, handler.path = "POST", "/insert"
    handler.rfile = _io.BytesIO(payload)
    handler.headers = {"Content-Length": str(len(payload))}
    handler._vet_request = lambda: True
    handler._post_authorised = lambda: True
    handler._content_type_ok = lambda: True
    handler._dispatch_post = lambda: handler._read_json_body("message")

    handler.do_POST()

    assert handler._body_consumed == len(payload)


# ---------------------------------------------------------------------------
# CMEDIA-7 / BROLL-5 (2026-09-04)
# ---------------------------------------------------------------------------


def test_at_the_download_cap_the_answer_is_a_wait_not_a_failure(tmp_path):
    """The page loops only while the state is downloading, so `ok: false` was
    a red toast and the end of the attempt: "come back in an hour and click
    again". Nothing has gone wrong here - the clip is behind this machine's
    other download."""
    from ccsync_companion import broll_fetch

    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)

    status, body = broll_server.build_insert_response(
        _insert_body(), mounts, ccsync_cfg=cfg,
        fetcher=lambda *a, **k: {"state": broll_fetch.STATE_BUSY,
                                 "message": broll_fetch.BUSY_MESSAGE,
                                 "retry_after": 1.5})

    assert status == 200
    assert body["ok"] is True
    assert body["state"] == "busy"
    assert body["retry_after"] == broll_fetch.BUSY_RETRY_AFTER_SECONDS
    assert "already downloading" in body["message"]


def test_the_ingest_retry_route_reaches_the_orchestrator(tmp_path, monkeypatch):
    """One listener, one dispatcher: /broll/ingest/retry and
    /music/ingest/retry are the same route, one kind apart."""
    seen = []

    class _Ingestor:
        def retry(self, body):
            seen.append(body)
            return 200, {"ok": True, "retried": 2}

    class _Deps:
        ingestor = _Ingestor()

    monkeypatch.setattr(music_server, "call",
                        lambda action, timeout=None, **kw: {"ok": True})
    srv = broll_server.make_server({"mounts": {}}, host="127.0.0.1", port=0,
                                   ccsync_cfg={"dashboard_url": DASH_ORIGIN},
                                   ingest_deps=_Deps(), music_ingest_deps=_Deps())
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        port = srv.server_address[1]
        for prefix in ("/broll", "/music"):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            payload = json.dumps({"staging_id": "s1", "items": ["l1", "l2"]}).encode()
            conn.request("POST", f"{prefix}/ingest/retry", body=payload,
                         headers={"Content-Type": "application/json",
                                  "Content-Length": str(len(payload)),
                                  loopback_guard.TOKEN_HEADER:
                                      loopback_guard.read_token() or ""})
            resp = conn.getresponse()
            body = json.loads(resp.read())
            conn.close()
            assert resp.status == 200
            assert body == {"ok": True, "retried": 2}
        assert [b["items"] for b in seen] == [["l1", "l2"], ["l1", "l2"]]
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


# -- CMEDIA-9: the staging floor is the KIND's number ------------------------

def test_the_music_floor_is_musics_own_number_by_default():
    """20 GB was sized for 40 GB camera originals. The largest thing a music
    batch can stage is 512 MiB a file, and the b-roll number refused a drop
    on a laptop with 15 GB free - the drop zone never even rendered."""
    from ccsync_companion import ingest_kinds

    assert ingest_kinds.BROLL_KIND.free_space_floor_gb == 20.0
    assert ingest_kinds.MUSIC_KIND.free_space_floor_gb == 2.0
    assert broll_server._ingest_floor_bytes({}, ingest_kinds.BROLL_KIND) == 20_000_000_000
    assert broll_server._ingest_floor_bytes({}, ingest_kinds.MUSIC_KIND) == 2_000_000_000
    # No kind at all still means b-roll's, for the callers that predate it.
    assert broll_server._ingest_floor_bytes({}) == 20_000_000_000


def test_the_config_key_still_wins_over_the_kinds_default():
    from ccsync_companion import ingest_kinds

    cfg = {"music_ingest_free_space_floor_gb": 40,
           "broll_ingest_free_space_floor_gb": 5}
    assert broll_server._ingest_floor_bytes(
        cfg, ingest_kinds.MUSIC_KIND) == 40_000_000_000
    assert broll_server._ingest_floor_bytes(
        cfg, ingest_kinds.BROLL_KIND) == 5_000_000_000


# -- wave 5 of the 2026-09-03 sweep: one vocabulary, on the loopback too -----
#
# Every one of these sentences is printed VERBATIM by the b-roll and music
# pages (they render the companion's `message` / `reasons` and do not
# translate them), so an editor comparing the drop zone with the tray was
# reading "machine" on one and "computer" on the other. Owner-approved
# 2026-09-04: a computer is a computer.

def test_no_ingest_refusal_calls_the_editors_computer_a_machine():
    """Every reason in the answer, the two sidecars' included: the b-roll and
    music pages print this list as-is, and the GPU refusal is the one an
    editor on a laptop reads most."""
    broll = broll_server.build_ingest_capabilities({}, None, None)
    music = broll_server.build_music_ingest_capabilities({}, None, None)
    assert broll["reasons"] and music["reasons"], (
        "a capability answer with nothing wrong proves nothing here")
    for caps in (broll, music):
        for said in caps["reasons"]:
            assert "machine" not in said.lower(), said
    # ...and the sentences are still the same sentences, not blanked.
    assert "nobody is signed in on this computer" in broll["reasons"]
    assert any("indexing is switched off on this computer" in r
               for r in music["reasons"])


def test_the_send_to_resolve_progress_line_says_computer():
    """`message` is what the b-roll page shows while the clip it was asked to
    insert is still being fetched down. Its KEY and its presence are the
    contract the web UI pins (broll/web/tests); only the words moved."""
    import ast

    source = (Path(broll_server.__file__)).read_text(encoding="utf-8")
    said = [n.value for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.startswith("syncing the clip to this")]
    assert said and all("computer" in s for s in said), said
