"""The b-roll server as the companion actually starts it.

The unit-level contract lives in test_broll_server.py; this file is about the
one property that made absorbing the standalone companion worth doing safely:
the sync companion must start, run and stop exactly as before whether or not
this server can. A stale standalone broll-companion sitting on 8899 is the
expected failure on the first upgraded machine, and it must cost a log line,
not a lane.
"""

from __future__ import annotations

import http.client
import json
import logging
import socket
import threading

import pytest

from ccsync_companion import app as app_mod
from ccsync_companion import broll_server, music_server, music_worker, resolve_bridge


@pytest.fixture(autouse=True)
def worker_in_process(monkeypatch):
    """No test here may SPAWN the Resolve worker.

    Since MED-3 (2026-08-11) /status and /insert run their Resolve half in a
    child process, which ignores the `resolve_bridge` seams these tests patch
    and reaches the real Resolve on a developer box (measured while writing
    that fix -- it got as far as importing into a live project). Running the
    worker's dispatch in-process keeps the whole chain under test except the
    process boundary, which test_music_server.py owns.
    """
    def _in_process_call(action, timeout=None, **kw):
        request = dict(kw)
        request["action"] = action
        return music_worker.run_request(request)

    monkeypatch.setattr(music_server, "call", _in_process_call)


def _free_port() -> int:
    """A port nothing is listening on. Bound and released, so it is only
    *probably* still free -- fine for a test, and the alternative (port 0)
    can't be reused by a second bind, which is the point of some of these."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _assert_port_free(port: int) -> None:
    """The server released `port` -- proven the same way a REAL restart
    would prove it, not more strictly.

    A plain bind() here is too strict on Linux/macOS once a request was
    actually served: closing the accepted connection leaves that (port,
    client-port) pair in TIME_WAIT, and BSD-derived stacks refuse a bare
    bind() to the local port of ANY matching TIME_WAIT entry -- Windows does
    not enforce this the same way, so this only reproduced in CI on the
    macOS runner (2026-08-17). BrollCompanionServer itself sets
    allow_reuse_address = os.name != "nt" for exactly this reason (see its
    docstring); a real second server on this port would rebind fine, so the
    check must set SO_REUSEADDR too or it is testing something stricter than
    the production contract.
    """
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))


def _get(port: int, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, json.loads(body)


def _post(port: int, path: str, obj: dict):
    # With the loopback token, as any local (non-browser) caller must since
    # 2026-08-17: a POST needs an allowed Origin or that header
    # (COMMERCIAL_READINESS.md item 5, docs/LOOPBACK_API.md).
    from ccsync_companion import loopback_guard

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps(obj).encode("utf-8")
    conn.request("POST", path, body=payload,
                 headers={"Content-Type": "application/json",
                          loopback_guard.TOKEN_HEADER:
                              loopback_guard.read_token() or "",
                          "Content-Length": str(len(payload))})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, json.loads(body)


@pytest.fixture
def tree(tmp_path):
    """A local_root with the b-roll archive in it."""
    archive = tmp_path / "Assets" / "B-roll Archive"
    archive.mkdir(parents=True)
    return tmp_path, archive


@pytest.fixture
def inert_resolve(monkeypatch):
    """No test may reach the real scripting API.

    The app tests below call the real start(), which launches the timeline
    watcher -- and on a developer box with Resolve installed, connect()
    genuinely connects and the poll enumerates whatever project happens to be
    open (and holds the fusionscript GIL while it does). Same class of hazard
    as conftest's real-Tk guard.
    """
    empty = {"ok": False, "message": "no Resolve in tests", "items": [], "project_name": ""}
    # poll_timeline_items too: it is what TimelineWatcher binds by default
    # (the cached polling path), so patching get_timeline_items alone would
    # leave the watcher talking to a real Resolve again.
    monkeypatch.setattr(resolve_bridge, "get_timeline_items",
                        lambda *a, **kw: dict(empty))
    monkeypatch.setattr(resolve_bridge, "poll_timeline_items", lambda: dict(empty))
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items", lambda: dict(empty))
    monkeypatch.setattr(resolve_bridge, "try_connect", lambda: False)


# ---------------------------------------------------------------------------
# broll_server.start()
# ---------------------------------------------------------------------------


def test_disabled_by_config_starts_no_server(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="ccsync.broll"):
        server = broll_server.start(
            {"local_root": str(tmp_path), "broll_server_enabled": False}
        )
    assert server is None
    assert any("disabled" in r.message for r in caplog.records)


def test_disabled_by_config_leaves_the_port_alone(tmp_path):
    port = _free_port()
    broll_server.start(
        {"local_root": str(tmp_path), "broll_server_enabled": False,
         "broll_server_port": port}
    )
    # Still bindable: nothing was started on it.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_start_serves_status_on_the_configured_port(tree, monkeypatch):
    local_root, _archive = tree
    monkeypatch.setattr(resolve_bridge, "try_connect", lambda: False)
    port = _free_port()

    server = broll_server.start(
        {"local_root": str(local_root), "broll_server_port": port}
    )
    assert server is not None
    try:
        status, data = _get(port, "/status")
        assert status == 200
        assert data["ok"] is True
        assert data["mounts"]["broll"].endswith("B-roll Archive")
    finally:
        broll_server.stop(server)


def test_stop_releases_the_port(tree):
    """The self-upgrade relaunches within seconds: a socket the outgoing
    process never closed is indistinguishable, to the incoming one, from the
    stale standalone companion."""
    local_root, _archive = tree
    port = _free_port()
    server = broll_server.start({"local_root": str(local_root), "broll_server_port": port})
    assert server is not None
    broll_server.stop(server)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_a_taken_port_warns_and_names_the_likely_cause(tree, caplog):
    """The expected failure on the first upgraded machine: the old standalone
    broll-companion is still in the editor's tray, holding 8899."""
    local_root, _archive = tree
    squatter = socket.socket()
    squatter.bind(("127.0.0.1", 0))
    squatter.listen(1)
    port = squatter.getsockname()[1]
    try:
        with caplog.at_level(logging.WARNING, logger="ccsync.broll"):
            server = broll_server.start(
                {"local_root": str(local_root), "broll_server_port": port}
            )
        assert server is None
        warnings = [r.getMessage() for r in caplog.records
                    if r.levelno >= logging.WARNING]
        assert warnings, "a failed bind must not be silent"
        assert any("BRoll Companion" in w for w in warnings)
    finally:
        squatter.close()


def test_a_nonsense_port_falls_back_to_the_default(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="ccsync.broll"):
        assert broll_server.configured_port({"broll_server_port": "eight thousand"}) == 8899
        assert broll_server.configured_port({"broll_server_port": -1}) == 8899
    assert broll_server.configured_port({}) == 8899


def test_the_port_key_is_never_a_config_problem(tmp_path):
    """validate_config's error list STOPS every sync lane (DEL-3). A typo in
    a knob for one button in a web page must not reach it."""
    from ccsync_companion import config as config_mod

    cfg = {
        "editor_name": "editor2",
        "local_root": str(tmp_path),
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/TheCreatorsPool/Creators_Club",
        "active_project": "Projects/2026/X",
        "broll_server_port": "nope",
        "broll_server_enabled": "sure",
    }
    errors, _warnings = config_mod.validate_config(cfg)
    assert errors == []


# ---------------------------------------------------------------------------
# CompanionApp wiring
# ---------------------------------------------------------------------------


def _app(cfg_overrides: dict, tmp_path):
    """A CompanionApp with every lane and guard inert -- this file is only
    interested in what start()/shutdown() do with the b-roll server."""
    from ccsync_companion import config as config_mod

    cfg = dict(config_mod.DEFAULTS)
    cfg.update({
        "editor_name": "tester",
        "local_root": str(tmp_path),
        "remote_root": "/mnt/tank/TheCreatorsPool/Creators_Club",
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "",
        "require_login": False,
        "sync_enabled": False,
        "lane_b_enabled": False,
        "popup_enabled": False,
        "lut_sync_enabled": False,
        "stills_sync_enabled": False,
        "shutdown_warning_enabled": False,
        "keep_awake_while_syncing": False,
    })
    cfg.update(cfg_overrides)
    return app_mod.CompanionApp(cfg)


def test_app_start_brings_the_server_up_and_shutdown_takes_it_down(tree, inert_resolve):
    local_root, _archive = tree
    port = _free_port()

    app = _app({"broll_server_port": port, "poll_interval": 0.2}, local_root)
    app.start()
    try:
        assert app._broll_server is not None
        status, data = _get(port, "/status")
        assert status == 200 and data["ok"] is True
    finally:
        app.shutdown()

    assert app._broll_server is None
    _assert_port_free(port)


def test_app_start_with_the_knob_off_starts_no_thread(tree, inert_resolve):
    local_root, _archive = tree
    before = {t.name for t in threading.enumerate()}
    app = _app({"broll_server_enabled": False, "poll_interval": 0.2}, local_root)
    app.start()
    try:
        assert app._broll_server is None
        assert "ccsync-broll" not in {t.name for t in threading.enumerate()} - before
    finally:
        app.shutdown()


def test_app_startup_survives_a_taken_port(tree, inert_resolve, caplog):
    """THE hard requirement. A stale standalone companion on the port must
    cost the sync companion nothing: it still starts, its watcher thread still
    runs, and the failure is a warning naming the cause."""
    local_root, _archive = tree
    squatter = socket.socket()
    squatter.bind(("127.0.0.1", 0))
    squatter.listen(1)
    port = squatter.getsockname()[1]

    app = _app({"broll_server_port": port, "poll_interval": 0.2}, local_root)
    try:
        with caplog.at_level(logging.WARNING, logger="ccsync.broll"):
            app.start()
        assert app._broll_server is None
        assert app._watcher_thread is not None and app._watcher_thread.is_alive()
        assert any("BRoll Companion" in r.getMessage() for r in caplog.records)
    finally:
        app.shutdown()
        squatter.close()


# ---------------------------------------------------------------------------
# End-to-end smoke: the real entry point, a fake Resolve, a real socket
# ---------------------------------------------------------------------------


class _FakeMediaPool:
    def __init__(self):
        self.appended = []

    def GetRootFolder(self):
        return self

    def GetSubFolderList(self):
        return []

    def GetClipList(self):
        return []

    def AddSubFolder(self, _parent, name):
        self.bin_name = name
        return self

    def GetName(self):
        return getattr(self, "bin_name", "B-Roll")

    def SetCurrentFolder(self, _folder):
        pass

    def ImportMedia(self, paths):
        self.imported = paths
        return [_FakeClip(paths[0])]

    def AppendToTimeline(self, clips):
        self.appended.append(clips)
        return True


class _FakeClip:
    def __init__(self, path):
        self._path = path

    def GetName(self):
        return self._path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

    def GetClipProperty(self):
        return {"File Path": self._path}


class _FakeResolve:
    def __init__(self, media_pool):
        self._media_pool = media_pool

    def GetProjectManager(self):
        return self

    def GetCurrentProject(self):
        return self

    def GetCurrentTimeline(self):
        return object()

    def GetMediaPool(self):
        return self._media_pool

    def GetName(self):
        return "SmokeProject"


def test_smoke_status_and_insert_through_the_real_entry_point(tree, monkeypatch):
    """Start the server the way the app does, then drive it over a real
    socket: /status answers with this companion's version, a traversal is
    refused with 400, and a real relative path reaches Resolve."""
    local_root, archive = tree
    (archive / "military").mkdir()
    clip = archive / "military" / "clip.mov"
    clip.write_bytes(b"fake video bytes")

    media_pool = _FakeMediaPool()
    monkeypatch.setattr(resolve_bridge, "connect", lambda: _FakeResolve(media_pool))

    port = _free_port()
    server = broll_server.start({"local_root": str(local_root), "broll_server_port": port})
    assert server is not None
    try:
        status, data = _get(port, "/status")
        assert status == 200
        assert data["ok"] is True
        assert data["version"] == __import__("ccsync_companion").VERSION

        status, data = _post(port, "/insert", {
            "share": "broll", "rel_path": "../../secrets.txt",
            "in_frame": 0, "out_frame": 10, "fps": 25, "mode": "append",
        })
        assert status == 400
        assert data["ok"] is False

        status, data = _post(port, "/insert", {
            "share": "broll", "rel_path": "military/clip.mov",
            "in_frame": 12, "out_frame": 62, "fps": 25, "mode": "append",
        })
        assert status == 200
        assert data == {"ok": True, "message": "Inserted clip.mov (50 frames)"}
        assert media_pool.appended[0][0]["startFrame"] == 12
        assert media_pool.appended[0][0]["endFrame"] == 62
    finally:
        broll_server.stop(server)
