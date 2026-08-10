"""The music library's "Send to Resolve" actions, rehomed onto 8899.

Port step 8 (2026-08-10): music/web/musicweb/resolve_link.py +
resolve_worker.py moved into this package as music_server + music_worker, and
the three actions became a /music/* route group on the b-roll server's
listener rather than a second server on the same port.

Four layers, in the order a request passes through them:
  - the "music" mount (derived from local_root, overridable in the same
    ~/.broll-companion.json table the b-roll routes read),
  - (share, rel_path) translation, which is what makes the actions work over
    Tailscale at all -- the web app's W:\\... is the editor's P:\\...,
  - the killable child process (argv, timeout, decoding),
  - build_status_response / build_send_response and a live loopback server,
    including the proof that the b-roll routes on the SAME listener are
    untouched.

The worker's own timeline arithmetic is exercised against fake Resolve
scripting objects in test_music_worker.py.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from ccsync_companion import broll_server, music_server, music_worker


# ---------------------------------------------------------------------------
# Live-server plumbing (same shape as test_broll_server's)
# ---------------------------------------------------------------------------


class Client:
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
            "POST", path, body=payload,
            headers={"Content-Type": "application/json",
                     "Content-Length": str(len(payload))},
        )
        resp = conn.getresponse()
        body = resp.read()
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, body

    def post_raw(self, path: str, payload: bytes):
        conn = self._connect()
        conn.request("POST", path, body=payload,
                     headers={"Content-Type": "application/json",
                              "Content-Length": str(len(payload))})
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
def no_real_worker(monkeypatch):
    """No test may spawn a real Resolve worker.

    Same class of guard as conftest's real-Tk one: on this developer's box
    Resolve genuinely answers, and an HTTP-layer test must not import
    anything into whatever project happens to be open. Returns the list every
    call is recorded in.
    """
    calls: list = []

    def _fake_call(action, **kw):
        calls.append((action, kw))
        return {"ok": True, "note": f"fake {action}", "clip": "x.wav"}

    monkeypatch.setattr(music_server, "call", _fake_call)
    return calls


@pytest.fixture
def live_server(no_real_worker, monkeypatch, tmp_path):
    """A real server on an ephemeral port, with both route groups wired."""
    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: False)

    cfg = {
        "server_url": "http://127.0.0.1:8000",
        "mounts": {"broll": str(tmp_path).replace("\\", "/")},
        music_server.MOUNTS_KEY: {"music": str(tmp_path).replace("\\", "/")},
    }
    srv = broll_server.make_server(cfg, host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, Client(srv.server_address[1]), no_real_worker
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ---------------------------------------------------------------------------
# The "music" mount
# ---------------------------------------------------------------------------


def test_music_share_defaults_to_the_library_in_the_tree(tmp_path):
    mounts = music_server.resolve_music_mounts({"mounts": {}}, {"local_root": str(tmp_path)})
    assert mounts["music"] == str(tmp_path / "Assets" / "Music")


def test_an_explicit_music_entry_still_wins(tmp_path):
    mounts = music_server.resolve_music_mounts(
        {"mounts": {"music": "Y:/Music"}}, {"local_root": str(tmp_path)}
    )
    assert mounts["music"] == "Y:/Music"


def test_a_blank_music_entry_counts_as_unset(tmp_path):
    mounts = music_server.resolve_music_mounts(
        {"mounts": {"music": "   "}}, {"local_root": str(tmp_path)}
    )
    assert mounts["music"] == str(tmp_path / "Assets" / "Music")


def test_no_default_without_a_local_root():
    """Same rule as the b-roll mount's: translate to "no mount configured",
    never to a relative path under the process CWD."""
    assert music_server.default_music_mount({"local_root": ""}) is None
    assert music_server.resolve_music_mounts({"mounts": {}}, {"local_root": ""}) == {}


def test_the_music_default_does_not_leak_into_the_broll_mounts(tmp_path):
    """GUARD. broll_server.resolve_mounts feeds GET /status, which is what the
    b-roll settings panel shows an editor; the music library has no business
    appearing there, and test_broll_server pins that set to {"broll"}."""
    broll_mounts = broll_server.resolve_mounts({"mounts": {}}, {"local_root": str(tmp_path)})
    assert set(broll_mounts) == {"broll"}


# ---------------------------------------------------------------------------
# (share, rel_path) translation -- the point of the whole port
# ---------------------------------------------------------------------------


def test_translation_is_local_not_the_servers_path(tmp_path):
    """The architectural change. The music DB stores (share, rel_path); the
    server's W:\\Creators_Club\\Assets\\Music\\foo.wav means nothing on an
    editor's machine, where the same file is P:\\Assets\\Music\\foo.wav."""
    editor = music_server.local_path_for(
        "music", "Ambient/foo.wav", {"music": "P:/Assets/Music"}
    )
    base_rig = music_server.local_path_for(
        "music", "Ambient/foo.wav", {"music": "W:/Creators_Club/Assets/Music"}
    )
    assert Path(editor).parts[-3:] == ("Assets", "Music", "foo.wav") or editor.endswith(
        "foo.wav"
    )
    assert editor != base_rig
    assert editor.replace("\\", "/").startswith("P:/Assets/Music")
    assert base_rig.replace("\\", "/").startswith("W:/Creators_Club/Assets/Music")


def test_translation_uses_the_broll_servers_helper(tmp_path):
    """Not a second copy of the rules: the '..' and drive-letter component
    guards are broll_server's, and a rule enforced in one and not the other is
    how a traversal gets served."""
    mounts = {"music": str(tmp_path)}
    assert music_server.local_path_for("music", "a/b.wav", mounts) == \
        broll_server.translate_path("music", "a/b.wav", mounts)


def test_an_unconfigured_share_raises_rather_than_guessing():
    with pytest.raises(broll_server.MountNotConfiguredError):
        music_server.local_path_for("nope", "a.wav", {"music": "P:/Assets/Music"})


@pytest.mark.parametrize(
    "rel_path",
    [
        "../secrets.txt",
        "../../Windows/System32/config/SAM",
        "Ambient/../../secrets.txt",
        "..\\secrets.txt",
        "C:/Windows/System32/config/SAM",
        "C:\\Windows\\System32\\config\\SAM",
        "/etc/passwd",
        "/Assets/Music/foo.wav",
        "Ambient/C:/x.wav",
        "",
        "   ",
    ],
)
def test_escape_attempts_raise(rel_path):
    """Anything that would leave the share root raises -- it is never served,
    and never silently contained either (an absolute rel_path is a
    contradiction, not a relative path with a stray slash)."""
    with pytest.raises(broll_server.PathTraversalError):
        music_server.local_path_for("music", rel_path, {"music": "P:/Assets/Music"})


def test_a_symlinked_escape_is_caught_by_the_containment_check(tmp_path):
    """Last line of defence, the one broll_server's translate_path does not
    have: no component is '..' and none is a drive, yet the path resolves
    outside the root."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.wav").write_bytes(b"x")
    root = tmp_path / "library"
    root.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        # Windows refuses symlinks to an unelevated process without Developer
        # Mode, but a directory JUNCTION needs no privilege at all -- and it
        # redirects exactly the same way, so the test still runs here.
        made = subprocess.run(
            [os.environ.get("COMSPEC") or "cmd.exe", "/c", "mklink", "/J",
             str(root / "link"), str(outside)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if made.returncode != 0 or not (root / "link").exists():
            pytest.skip("this host can make neither a symlink nor a junction")

    # No '..', no drive letter, nothing the component rules can see -- and it
    # lands outside the root all the same.
    with pytest.raises(broll_server.PathTraversalError):
        music_server.local_path_for("music", "link/secret.wav", {"music": str(root)})


def test_a_legitimate_nested_path_still_translates(tmp_path):
    got = music_server.local_path_for(
        "music", "Ambient/Slow/cue 01.wav", {"music": str(tmp_path)}
    )
    assert Path(got) == tmp_path / "Ambient" / "Slow" / "cue 01.wav"


# ---------------------------------------------------------------------------
# The killable child
# ---------------------------------------------------------------------------


def test_worker_command_from_source_uses_the_interpreter():
    argv = music_server.worker_command('{"action": "status"}',
                                       executable="/usr/bin/python3", frozen=False)
    assert argv == ["/usr/bin/python3", "-m", "ccsync_companion.music_worker",
                    '{"action": "status"}']


def test_worker_command_when_frozen_re_enters_the_exe():
    """In a frozen build sys.executable is the COMPANION -- handing it a
    module name would start a second tray app, not a worker (same trap
    rclone_lane.watch_probe_command is written around)."""
    argv = music_server.worker_command('{"action": "status"}',
                                       executable="C:/ccsync/ccsync-companion.exe",
                                       frozen=True)
    assert argv == ["C:/ccsync/ccsync-companion.exe",
                    music_worker.WORKER_FLAG, '{"action": "status"}']


def test_the_frozen_flag_is_the_one_app_run_answers():
    """If these two ever drift, the frozen child boots a whole second
    companion (and blocks on the single-instance lock) instead of answering."""
    import inspect

    from ccsync_companion import app as app_mod

    source = inspect.getsource(app_mod.run)
    assert "music_worker.WORKER_FLAG" in source
    assert music_worker.WORKER_FLAG == "--music-resolve-worker"


def test_call_passes_the_action_and_kwargs_as_one_json_argv():
    seen = {}

    class _Proc:
        stdout = b'{"ok": true, "note": "done"}'
        stderr = b""
        returncode = 0

    def _run(argv, timeout=None, **kwargs):
        seen["argv"] = argv
        seen["timeout"] = timeout
        seen["kwargs"] = kwargs
        return _Proc()

    result = music_server.call("under", runner=_run, path="P:/Assets/Music/a.wav")

    assert result == {"ok": True, "note": "done"}
    assert seen["timeout"] == music_server.TIMEOUT
    assert json.loads(seen["argv"][-1]) == {"action": "under",
                                            "path": "P:/Assets/Music/a.wav"}
    assert seen["kwargs"]["stdout"] is subprocess.PIPE


def test_call_strips_the_pinned_python_home_from_the_child(monkeypatch):
    """PYTHONHOME/PYTHON3HOME are pinned process-wide at OUR _MEIPASS, which
    the bootloader deletes on exit; a child that inherits them is pointed at a
    directory that is about to stop existing (resolve_bridge CORE-M6)."""
    monkeypatch.setenv("PYTHONHOME", "C:/mei-12345")
    monkeypatch.setenv("PYTHON3HOME", "C:/mei-12345")
    seen = {}

    class _Proc:
        stdout = b'{"ok": true}'
        stderr = b""
        returncode = 0

    def _run(argv, timeout=None, **kwargs):
        seen.update(kwargs)
        return _Proc()

    music_server.call("status", runner=_run)
    assert "PYTHONHOME" not in seen["env"]
    assert "PYTHON3HOME" not in seen["env"]


def test_a_timeout_is_an_answer_not_a_hang():
    """THE reason this is a child process at all: the scripting API blocks
    indefinitely when Resolve is modal, busy, or on the Project Manager."""
    def _run(argv, timeout=None, **kwargs):
        raise subprocess.TimeoutExpired(argv, timeout)

    result = music_server.call("bin", timeout=3, runner=_run, path="a.wav")
    assert result["ok"] is False
    assert "3s" in result["error"]
    assert "Project Manager" in result["error"]


def test_a_worker_that_cannot_start_is_reported():
    def _run(argv, timeout=None, **kwargs):
        raise OSError("no such file")

    result = music_server.call("status", runner=_run)
    assert result == {"ok": False,
                      "error": "could not start the Resolve worker: no such file"}


def test_silent_worker_falls_back_to_its_last_stderr_line():
    class _Proc:
        stdout = b""
        stderr = b"Traceback...\nImportError: DaVinciResolveScript"
        returncode = 1

    result = music_server.call("status", runner=lambda *a, **k: _Proc())
    assert result == {"ok": False, "error": "ImportError: DaVinciResolveScript"}


def test_silent_worker_with_no_stderr_names_the_exit_code():
    class _Proc:
        stdout = b""
        stderr = b""
        returncode = 3

    result = music_server.call("status", runner=lambda *a, **k: _Proc())
    assert result["ok"] is False
    assert "exit 3" in result["error"]


def test_non_json_output_is_not_a_traceback():
    class _Proc:
        stdout = b"Fatal Python error: something"
        stderr = b""
        returncode = 0

    result = music_server.call("status", runner=lambda *a, **k: _Proc())
    assert result == {"ok": False, "error": "Fatal Python error: something"}


# ---------------------------------------------------------------------------
# build_send_response / build_status_response
# ---------------------------------------------------------------------------


def test_only_the_three_spec_actions_are_accepted(tmp_path):
    for action in ("delete", "status", "", None, "BIN"):
        status, body = music_server.build_send_response(
            {"action": action, "share": "music", "rel_path": "a.wav"},
            {"music": str(tmp_path)},
            caller=lambda *a, **k: pytest.fail("the worker must not be reached"),
        )
        assert status == 400
        assert body["ok"] is False


def test_status_is_not_reachable_through_the_write_route(tmp_path):
    """"status" is a GET of its own; letting it in here would mean a POST body
    could ask for it, which is not a route this server has."""
    status, body = music_server.build_send_response(
        {"action": "status", "share": "music", "rel_path": "a.wav"},
        {"music": str(tmp_path)},
        caller=lambda *a, **k: pytest.fail("the worker must not be reached"),
    )
    assert status == 400


def test_send_no_mount_configured_is_200_so_the_ui_can_show_it():
    status, body = music_server.build_send_response(
        {"action": "bin", "share": "music", "rel_path": "a.wav"}, {},
        caller=lambda *a, **k: pytest.fail("the worker must not be reached"),
    )
    assert status == 200
    assert body == {"ok": False, "error": "no mount configured for share 'music'"}


def test_send_traversal_is_http_400(tmp_path):
    status, body = music_server.build_send_response(
        {"action": "under", "share": "music", "rel_path": "../../etc/passwd"},
        {"music": str(tmp_path)},
        caller=lambda *a, **k: pytest.fail("the worker must not be reached"),
    )
    assert status == 400
    assert body["ok"] is False


def test_send_file_not_found_names_the_path_and_the_likely_cause(tmp_path):
    status, body = music_server.build_send_response(
        {"action": "bin", "share": "music", "rel_path": "missing.wav"},
        {"music": str(tmp_path)},
        caller=lambda *a, **k: pytest.fail("the worker must not be reached"),
    )
    assert status == 200
    assert body["ok"] is False
    assert "is the share mounted?" in body["error"]


def test_send_hands_the_worker_a_local_absolute_path(tmp_path):
    cue = tmp_path / "Ambient" / "cue.wav"
    cue.parent.mkdir()
    cue.write_bytes(b"RIFF")
    seen = {}

    def _caller(action, **kw):
        seen["action"] = action
        seen["kw"] = kw
        return {"ok": True, "note": "imported to the Music bin"}

    status, body = music_server.build_send_response(
        {"action": "bin", "share": "music", "rel_path": "Ambient/cue.wav"},
        {"music": str(tmp_path)}, caller=_caller,
    )

    assert status == 200
    assert body == {"ok": True, "note": "imported to the Music bin"}
    assert seen["action"] == "bin"
    assert Path(seen["kw"]["path"]) == cue
    assert "track" not in seen["kw"]


def test_an_explicit_track_is_passed_through_as_an_int(tmp_path):
    cue = tmp_path / "cue.wav"
    cue.write_bytes(b"RIFF")
    seen = {}

    def _caller(action, **kw):
        seen.update(kw)
        return {"ok": True}

    music_server.build_send_response(
        {"action": "insert", "share": "music", "rel_path": "cue.wav", "track": "3"},
        {"music": str(tmp_path)}, caller=_caller,
    )
    assert seen["track"] == 3


def test_a_nonsense_track_is_a_400_not_a_crash(tmp_path):
    cue = tmp_path / "cue.wav"
    cue.write_bytes(b"RIFF")
    status, body = music_server.build_send_response(
        {"action": "insert", "share": "music", "rel_path": "cue.wav", "track": "A2"},
        {"music": str(tmp_path)},
        caller=lambda *a, **k: pytest.fail("the worker must not be reached"),
    )
    assert status == 400
    assert body["ok"] is False


def test_the_workers_answer_is_returned_verbatim(tmp_path):
    """music/web/static/app.js reads r.note on success and r.error on failure
    and shows them inline -- nothing here may reshape either."""
    cue = tmp_path / "cue.wav"
    cue.write_bytes(b"RIFF")
    answer = {"ok": False, "error": "A2 is linked to video at frame 120 -- "
                                    "rippling it alone would desync sync sound."}
    status, body = music_server.build_send_response(
        {"action": "insert", "share": "music", "rel_path": "cue.wav"},
        {"music": str(tmp_path)}, caller=lambda *a, **k: dict(answer),
    )
    assert status == 200
    assert body == answer


def test_build_status_response_is_the_workers_dict():
    status, body = music_server.build_status_response(
        caller=lambda action, **kw: {"ok": True, "project": "P", "timeline": "T"}
    )
    assert status == 200
    assert body == {"ok": True, "project": "P", "timeline": "T"}


# ---------------------------------------------------------------------------
# Over the wire, on the b-roll server's listener
# ---------------------------------------------------------------------------


def test_music_status_over_http(live_server):
    _srv, client, calls = live_server
    status, _headers, body = client.get("/music/status")
    assert status == 200
    assert json.loads(body)["ok"] is True
    assert calls[0][0] == "status"


def test_music_send_over_http(live_server, tmp_path):
    srv, client, calls = live_server
    (tmp_path / "cue.wav").write_bytes(b"RIFF")

    status, _headers, body = client.post_json(
        "/music/send", {"action": "under", "share": "music", "rel_path": "cue.wav"}
    )
    assert status == 200
    assert json.loads(body)["ok"] is True
    assert calls[0][0] == "under"
    assert Path(calls[0][1]["path"]) == tmp_path / "cue.wav"


def test_music_traversal_over_http_is_400(live_server):
    _srv, client, calls = live_server
    status, _headers, body = client.post_json(
        "/music/send",
        {"action": "under", "share": "music",
         "rel_path": "../../../Windows/System32/config/SAM"},
    )
    assert status == 400
    assert json.loads(body)["ok"] is False
    assert calls == [], "nothing may reach Resolve after a rejected path"


def test_music_malformed_json_body_is_400_not_a_traceback(live_server):
    _srv, client, _calls = live_server
    status, body = client.post_raw("/music/send", b"{not json")
    assert status == 400
    assert json.loads(body)["ok"] is False


def test_music_routes_get_the_same_cors_and_pna_headers(live_server):
    """The music UI is served from the dashboard, so the page sits on a
    tailnet address and calls loopback -- Chromium blocks that at the
    PREFLIGHT without the Private Network Access opt-in."""
    _srv, client, _calls = live_server
    status, headers, _body = client.options("/music/send")
    assert status == 204
    assert headers.get("Access-Control-Allow-Origin") == "*"
    assert headers.get("Access-Control-Allow-Private-Network") == "true"

    _status, headers, _body = client.get("/music/status")
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_a_get_on_the_send_route_is_404_not_a_500(live_server):
    _srv, client, _calls = live_server
    status, _headers, body = client.get("/music/send")
    assert status == 404
    assert json.loads(body)["ok"] is False


# ---------------------------------------------------------------------------
# The b-roll routes on that same listener, unchanged
# ---------------------------------------------------------------------------


def test_the_broll_routes_still_answer_on_the_same_listener(live_server, tmp_path, monkeypatch):
    """THE regression this port could cause. One process, one port, two route
    groups -- and the older one is the one editors already depend on."""
    srv, client, _calls = live_server
    (tmp_path / "clip.mov").write_bytes(b"fake")
    monkeypatch.setattr(
        broll_server.resolve_bridge, "perform_insert",
        lambda local_path, in_frame, out_frame: {
            "ok": True, "message": f"Inserted clip.mov ({out_frame - in_frame} frames)"},
    )

    status, _headers, body = client.get("/status")
    assert status == 200
    data = json.loads(body)
    assert set(data.keys()) == {"ok", "resolve_connected", "mounts", "version"}
    assert "music" not in data["mounts"]

    status, _headers, body = client.post_json(
        "/insert",
        {"share": "broll", "rel_path": "clip.mov", "in_frame": 0, "out_frame": 20,
         "fps": 25, "mode": "append"},
    )
    assert status == 200
    assert json.loads(body) == {"ok": True, "message": "Inserted clip.mov (20 frames)"}

    status, _headers, body = client.post_json(
        "/insert",
        {"share": "broll", "rel_path": "../../secrets.txt", "in_frame": 0,
         "out_frame": 20, "mode": "append"},
    )
    assert status == 400


def test_broll_error_bodies_still_say_message_not_error(live_server):
    """The two route groups answer to two different web apps: b-roll's JS
    reads `message`, the music page's reads `error`. Neither may be renamed to
    match the other."""
    _srv, client, _calls = live_server
    _status, _headers, body = client.get("/nope")
    assert "message" in json.loads(body)

    _status, body = client.post_raw("/music/send", b"{nope")
    assert "error" in json.loads(body)


# ---------------------------------------------------------------------------
# start() -- one listener, both groups
# ---------------------------------------------------------------------------


def test_start_serves_both_groups_from_one_port(tmp_path, monkeypatch, no_real_worker):
    """The constraint that shaped the whole port: 8899 has exactly one
    listener, and it carries both b-roll and music."""
    library = tmp_path / "Assets" / "Music"
    library.mkdir(parents=True)
    (library / "cue.wav").write_bytes(b"RIFF")
    (tmp_path / "Assets" / "B-roll Archive").mkdir(parents=True)
    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: False)

    port = _free_port()
    server = broll_server.start({"local_root": str(tmp_path), "broll_server_port": port})
    assert server is not None
    try:
        client = Client(port)
        status, _headers, body = client.get("/status")
        assert status == 200 and json.loads(body)["mounts"]["broll"].endswith(
            "B-roll Archive")

        status, _headers, body = client.get("/music/status")
        assert status == 200 and json.loads(body)["ok"] is True

        status, _headers, body = client.post_json(
            "/music/send",
            {"action": "bin", "share": "music", "rel_path": "cue.wav"},
        )
        assert status == 200
        assert json.loads(body)["ok"] is True
        assert Path(no_real_worker[-1][1]["path"]) == library / "cue.wav"
    finally:
        broll_server.stop(server)

    # ...and exactly one listener was ever taken, so it is free again.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_start_derives_the_music_mount_from_the_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: False)
    port = _free_port()
    server = broll_server.start({"local_root": str(tmp_path), "broll_server_port": port})
    assert server is not None
    try:
        mounts = server.companion_config[music_server.MOUNTS_KEY]
        assert mounts["music"] == str(tmp_path / "Assets" / "Music")
        assert "broll" not in mounts
    finally:
        broll_server.stop(server)


def test_the_readme_snippet_documents_the_music_share(tmp_path):
    cfg_path = tmp_path / ".broll-companion.json"
    readme_path = tmp_path / ".broll-companion.README.txt"
    broll_server.ensure_config_exists(path=cfg_path, readme_path=readme_path)
    text = readme_path.read_text(encoding="utf-8")
    assert "music" in text.lower()
    assert "Assets/Music" in text
