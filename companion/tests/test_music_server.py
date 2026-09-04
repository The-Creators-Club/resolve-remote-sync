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
import time
from pathlib import Path

import pytest

from ccsync_companion import (
    broll_server, loopback_guard, music_server, music_worker, ytdl_server,
)

# The dashboard the live_server fixture is pointed at -- the one origin a
# browser caller may present (COMMERCIAL_READINESS.md item 5, 2026-08-17).
DASH_ORIGIN = "http://100.64.0.1:8000"


@pytest.fixture(autouse=True)
def _no_real_file_manager(monkeypatch):
    """/music/reveal launches Explorer/Finder (MUSIC-6), and a test that
    actually did would open windows all over the developer's desktop.

    test_ytdl_server's guard, on the same seam -- music_server.build_reveal
    _response deliberately reuses ytdl_server.spawn rather than owning a second
    launcher. The tests that care about the argv inject their own recorder on
    top of this."""
    def _boom(argv):
        pytest.fail(f"a test spawned a real file manager: {argv!r}")

    monkeypatch.setattr(ytdl_server, "spawn", _boom)


@pytest.fixture
def spawned(monkeypatch):
    """Record what would have been launched, and launch nothing."""
    calls: list = []
    monkeypatch.setattr(ytdl_server, "spawn", lambda argv: calls.append(argv))
    return calls


# ---------------------------------------------------------------------------
# Live-server plumbing (same shape as test_broll_server's)
# ---------------------------------------------------------------------------


class Client:
    def __init__(self, port: int):
        self.port = port

    def _connect(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def _auth(self, token, origin) -> dict:
        headers = {}
        if token:
            headers[loopback_guard.TOKEN_HEADER] = (
                token if isinstance(token, str) else (loopback_guard.read_token() or "")
            )
        if origin is not None:
            headers["Origin"] = origin
        return headers

    def get(self, path: str, origin=None):
        conn = self._connect()
        conn.request("GET", path, headers=self._auth(False, origin))
        resp = conn.getresponse()
        body = resp.read()
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, body

    def post_json(self, path: str, obj: dict, origin=None, token=True):
        # The loopback token by default: since 2026-08-17 a POST here needs an
        # allowed Origin or that header (COMMERCIAL_READINESS.md item 5), and
        # this client stands in for a LOCAL caller.
        conn = self._connect()
        payload = json.dumps(obj).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "Content-Length": str(len(payload))}
        headers.update(self._auth(token, origin))
        conn.request("POST", path, body=payload, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, body

    def post_raw(self, path: str, payload: bytes):
        conn = self._connect()
        headers = {"Content-Type": "application/json",
                   "Content-Length": str(len(payload))}
        headers.update(self._auth(True, None))
        conn.request("POST", path, body=payload, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def options(self, path: str, origin=None):
        conn = self._connect()
        conn.request("OPTIONS", path, headers=self._auth(False, origin))
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

    def _fake_call(action, timeout=None, **kw):
        calls.append((action, kw))
        if action.startswith("broll_"):
            # The b-roll routes on this same listener went through the child
            # too in MED-3 (2026-08-11); they are answered here by the
            # worker's own dispatch, in-process, so the resolve_bridge seams
            # those tests patch still apply. The music actions stay faked --
            # their argv/timeout contract is tested separately below.
            request = dict(kw)
            request["action"] = action
            return music_worker.run_request(request)
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
    srv = broll_server.make_server(cfg, host="127.0.0.1", port=0,
                                   ccsync_cfg={"dashboard_url": DASH_ORIGIN})
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


# ---------------------------------------------------------------------------
# build_reveal_response (MUSIC-6, 2026-08-14)
# ---------------------------------------------------------------------------
#
# The music page's "show in folder" used to POST the SERVER's /api/reveal,
# which spawned Explorer in the dashboard's Linux container -- a button that
# could not work for any editor, ever. Revealing a file is an action on the
# machine the editor is sitting at, so it is a route here. Nothing below
# spawns a real file manager: the launcher is injected, exactly as
# test_ytdl_server drives the same code.


def _spawns() -> tuple:
    """(recorder, spawned-argv list). The one seam a real Explorer is behind."""
    spawned: list = []
    return spawned.append, spawned


def test_reveal_selects_the_track_in_its_folder(tmp_path):
    cue = tmp_path / "Ambient" / "cue.wav"
    cue.parent.mkdir()
    cue.write_bytes(b"RIFF")
    spawner, spawned = _spawns()

    status, body = music_server.build_reveal_response(
        {"share": "music", "rel_path": "Ambient/cue.wav"},
        {"music": str(tmp_path)}, spawner=spawner, platform="win32",
    )

    assert status == 200 and body["ok"] is True
    assert body["message"] == f"Showing cue.wav in {cue.parent}"
    (argv,) = spawned
    # A LIST with the path as ONE element (MUSIC-2, 2026-08-11): a track called
    # `rock & roll.wav` is an argument, never a command separator, because
    # nothing re-parses this.
    assert isinstance(argv, list)
    assert argv == ["explorer", f"/select,{cue}"]


def test_reveal_on_macos_asks_finder(tmp_path):
    cue = tmp_path / "cue.wav"
    cue.write_bytes(b"RIFF")
    spawner, spawned = _spawns()

    status, body = music_server.build_reveal_response(
        {"share": "music", "rel_path": "cue.wav"},
        {"music": str(tmp_path)}, spawner=spawner, platform="darwin",
    )

    assert status == 200 and body["ok"] is True
    assert spawned == [["open", "-R", str(cue)]]


def test_reveal_falls_back_to_the_folder_when_the_track_has_not_synced(tmp_path):
    """The row is in the index and the file is not here: still syncing, or a
    half-mounted share. The folder is what the editor clicked the row to look
    at, and it is opened WITHOUT /select -- selecting a file that is not there
    is what makes Explorer open Documents instead.

    The message SAYS the file is not there, in ytdl_server's words: an editor
    on this branch is usually asking "why isn't my track here", and
    "Showing X in Y" would claim a file they can see."""
    (tmp_path / "Ambient").mkdir()
    spawner, spawned = _spawns()

    status, body = music_server.build_reveal_response(
        {"share": "music", "rel_path": "Ambient/cue.wav"},
        {"music": str(tmp_path)}, spawner=spawner, platform="win32",
    )

    assert status == 200 and body["ok"] is True
    assert spawned == [["explorer", str(tmp_path / "Ambient")]]
    assert body["message"] == \
        f"cue.wav is not there - opened {tmp_path / 'Ambient'} instead"


def test_reveal_with_nothing_there_says_so_and_launches_nothing(tmp_path):
    """Spawning `explorer <missing>` opens the editor's Documents folder and
    looks like a bug -- so the answer is the message, not a window."""
    spawner, spawned = _spawns()

    status, body = music_server.build_reveal_response(
        {"share": "music", "rel_path": "Nowhere/cue.wav"},
        {"music": str(tmp_path)}, spawner=spawner, platform="win32",
    )

    assert status == 200 and body["ok"] is False
    # `error`, not `message`: the music page's api() helper reads r.error
    # first, and a message-only body would show it a blank failure.
    assert "is the share mounted?" in body["error"]
    # ...and it says COMPUTER (wave 5 of the 2026-09-03 sweep, owner-approved
    # 2026-09-04): the music page prints this string verbatim, beside a tray
    # that has said "computer" since wave 4.
    assert "is not on this computer" in body["error"]
    assert "machine" not in body["error"]
    assert spawned == []


def test_reveal_traversal_is_http_400_and_launches_nothing(tmp_path):
    """Same translator as /music/send (local_path_for), so the '..' rules, the
    absolute-rel_path refusal and MED-11's containment check apply here too --
    and this route hands its answer to a process spawner."""
    for rel_path in ("../../etc/passwd", "/etc/passwd", "C:/Windows/System32"):
        spawner, spawned = _spawns()
        status, body = music_server.build_reveal_response(
            {"share": "music", "rel_path": rel_path},
            {"music": str(tmp_path)}, spawner=spawner, platform="win32",
        )
        assert status == 400, rel_path
        assert body["ok"] is False and body["error"]
        assert spawned == [], "nothing may be launched after a rejected path"


def test_reveal_without_a_mount_is_200_so_the_page_can_show_it():
    spawner, spawned = _spawns()

    status, body = music_server.build_reveal_response(
        {"share": "music", "rel_path": "cue.wav"}, {}, spawner=spawner,
        platform="win32",
    )

    assert status == 200
    assert body == {"ok": False, "error": "no mount configured for share 'music'"}
    assert spawned == []


def test_reveal_on_a_platform_with_no_file_manager_answers_instead_of_raising(
        tmp_path):
    cue = tmp_path / "cue.wav"
    cue.write_bytes(b"RIFF")
    spawner, spawned = _spawns()

    status, body = music_server.build_reveal_response(
        {"share": "music", "rel_path": "cue.wav"},
        {"music": str(tmp_path)}, spawner=spawner, platform="linux",
    )

    assert status == 200 and body["ok"] is False
    assert str(cue) in body["error"]
    assert spawned == []


def test_a_file_manager_that_will_not_start_is_not_a_500(tmp_path):
    cue = tmp_path / "cue.wav"
    cue.write_bytes(b"RIFF")

    def _boom(argv):
        raise OSError("explorer is not installed")

    status, body = music_server.build_reveal_response(
        {"share": "music", "rel_path": "cue.wav"},
        {"music": str(tmp_path)}, spawner=_boom, platform="win32",
    )

    assert status == 200 and body["ok"] is False
    assert "could not open the file manager" in body["error"]


def test_reveal_reuses_the_ytdl_route_groups_launcher():
    """One reveal implementation on this listener, not two: the shell-free argv
    (MUSIC-2) and the sanitized-env spawn are ytdl_server's, and a second copy
    is how one of them quietly grows a shell."""
    from ccsync_companion import ytdl_server

    assert music_server.build_reveal_response.__module__ == "ccsync_companion.music_server"
    assert ytdl_server.reveal_command("/x/y.wav", select=True, platform="darwin") == \
        ["open", "-R", "/x/y.wav"]


def test_the_isfile_and_isdir_probes_are_injectable(tmp_path):
    """The checks are seams for the same reason the spawner is: a test must be
    able to describe a share that is mounted, half-mounted or absent without
    building three of them."""
    spawner, spawned = _spawns()
    status, body = music_server.build_reveal_response(
        {"share": "music", "rel_path": "Ambient/cue.wav"},
        {"music": str(tmp_path)}, spawner=spawner, platform="darwin",
        isfile=lambda path: True, isdir=lambda path: False,
    )
    assert status == 200 and body["ok"] is True
    assert spawned == [["open", "-R", str(tmp_path / "Ambient" / "cue.wav")]]


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


def test_music_reveal_over_http(live_server, tmp_path, spawned):
    """MUSIC-6 end to end, on the ONE listener: the page posts {share,
    rel_path} -- never a path -- and the file manager opens HERE, on the
    machine the editor is sitting at, instead of in the dashboard's container
    where the old server-side /api/reveal sent it."""
    _srv, client, calls = live_server
    (tmp_path / "cue.wav").write_bytes(b"RIFF")

    status, _headers, body = client.post_json(
        "/music/reveal", {"share": "music", "rel_path": "cue.wav"}
    )

    assert status == 200
    assert json.loads(body)["ok"] is True
    (argv,) = spawned
    assert isinstance(argv, list), "the argv must be a list, not a command string"
    assert Path(argv[-1].split(",", 1)[-1]) == tmp_path / "cue.wav"
    assert calls == [], "revealing a file must not go near Resolve"


def test_music_reveal_traversal_over_http_is_400(live_server, spawned):
    _srv, client, _calls = live_server
    status, _headers, body = client.post_json(
        "/music/reveal",
        {"share": "music", "rel_path": "../../../Windows/System32/config/SAM"},
    )
    assert status == 400
    assert json.loads(body)["ok"] is False
    assert spawned == [], "nothing may be launched after a rejected path"


def test_music_reveal_malformed_body_is_400_in_the_pages_error_shape(live_server,
                                                                     spawned):
    _srv, client, _calls = live_server
    status, body = client.post_raw("/music/reveal", b"{not json")
    assert status == 400
    parsed = json.loads(body)
    assert parsed["ok"] is False
    assert "error" in parsed, "the music page reads `error`, not `message`"
    assert spawned == []


def test_a_get_on_the_reveal_route_is_404_not_a_500(live_server):
    _srv, client, _calls = live_server
    status, _headers, body = client.get("/music/reveal")
    assert status == 404
    assert json.loads(body)["ok"] is False


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
    PREFLIGHT without the Private Network Access opt-in.

    Pinned the "*" wildcard until 2026-08-17; now it pins that the DASHBOARD's
    origin -- and only it -- gets the same treatment on this route group as on
    b-roll's (COMMERCIAL_READINESS.md item 5)."""
    _srv, client, _calls = live_server
    status, headers, _body = client.options("/music/send", origin=DASH_ORIGIN)
    assert status == 204
    assert headers.get("Access-Control-Allow-Origin") == DASH_ORIGIN
    assert headers.get("Access-Control-Allow-Private-Network") == "true"

    _status, headers, _body = client.get("/music/status", origin=DASH_ORIGIN)
    assert headers.get("Access-Control-Allow-Origin") == DASH_ORIGIN


def test_a_hostile_page_cannot_drive_the_music_routes(live_server):
    """The music route group is on the same listener, so it inherits the same
    allow-list -- checked here rather than assumed."""
    _srv, client, calls = live_server
    status, headers, _body = client.post_json(
        "/music/send", {"action": "bin", "share": "music", "rel_path": "a.wav"},
        origin="https://evil.example", token=False,
    )
    assert status == 403
    assert "Access-Control-Allow-Origin" not in headers
    assert calls == []


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
        lambda local_path, in_frame, out_frame, canonical_fn=None, mode="append": {
            "ok": True, "message": f"Inserted clip.mov ({out_frame - in_frame} frames)"},
    )

    status, _headers, body = client.get("/status")
    assert status == 200
    data = json.loads(body)
    # The b-roll status contract, not an exact dict: this test is about the
    # two route groups sharing one listener, and pinning the whole body made
    # it fail for a field added to the OTHER group's neighbour (CMEDIA-3 added
    # `loopback` on 2026-09-04). test_broll_server.py owns the exact shape.
    assert {"ok", "resolve_connected", "mounts", "version"} <= set(data.keys())
    assert "music" not in data["mounts"]
    assert data["loopback"]["bound"] is True
    assert data["loopback"]["port"] == srv.server_address[1]

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
    _assert_port_free(port)


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


# ---------------------------------------------------------------------------
# The containment check needs a root even when nobody configured one (MED-11)
# ---------------------------------------------------------------------------


def _link_or_skip(root, outside):
    """Make root/link point at `outside`, or skip. Windows refuses symlinks to
    an unelevated process without Developer Mode, but a directory JUNCTION
    needs no privilege and redirects identically."""
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    made = subprocess.run(
        [os.environ.get("COMSPEC") or "cmd.exe", "/c", "mklink", "/J",
         str(root / "link"), str(outside)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if made.returncode != 0 or not (root / "link").exists():
        pytest.skip("this host can make neither a symlink nor a junction")


def test_the_root_comes_back_with_the_path():
    """translate_path's own answer is unchanged; the pair is what the
    containment check needs, and rediscovering it from `mounts` is exactly
    what did not work."""
    mounts = {"music": "P:/Assets/Music"}
    root, local = broll_server.translate_path_with_root(
        "music", "a/b.wav", mounts, platform="win32")
    assert root == "P:/Assets/Music"
    assert local == broll_server.translate_path(
        "music", "a/b.wav", mounts, platform="win32")


def test_a_probed_volumes_mount_is_containment_checked_too(tmp_path, monkeypatch):
    """MED-11: the guard ran only `if root:` and read `mounts.get(share)`,
    which is None for a mount that came from the /Volumes probe -- the
    documented Mac case (volume mounted, no config entry). Component
    validation alone does not see a symlink out of the volume."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.wav").write_bytes(b"x")
    root = tmp_path / "volume"
    root.mkdir()
    _link_or_skip(root, outside)

    monkeypatch.setattr(broll_server.sys, "platform", "darwin")
    monkeypatch.setattr(broll_server, "probe_darwin_mount",
                        lambda share, isdir=None: str(root))

    # NO entry for "music" in mounts: the root can only come from the probe.
    with pytest.raises(broll_server.PathTraversalError):
        music_server.local_path_for("music", "link/secret.wav", {})


def test_a_probed_mount_still_serves_what_is_inside_it(tmp_path, monkeypatch):
    """...and the check does not turn the probe into a refusal."""
    monkeypatch.setattr(broll_server.sys, "platform", "darwin")
    monkeypatch.setattr(broll_server, "probe_darwin_mount",
                        lambda share, isdir=None: str(tmp_path))

    got = music_server.local_path_for("music", "Ambient/cue.wav", {})
    assert Path(got) == tmp_path / "Ambient" / "cue.wav"


@pytest.mark.parametrize("bad", [123, ["cue.wav"], {"n": "cue.wav"}, None])
def test_a_non_string_rel_path_is_a_400_on_the_music_route_too(bad):
    """MED-5, the same request-thread crash on the other route group."""
    status, body = music_server.build_send_response(
        {"action": "bin", "share": "music", "rel_path": bad},
        {"music": "P:/Assets/Music"},
        caller=lambda action, **kw: {"ok": True},
    )
    assert status == 400
    assert body["ok"] is False


def test_a_non_string_share_is_a_400_on_the_music_route_too():
    status, body = music_server.build_send_response(
        {"action": "bin", "share": {"music": 1}, "rel_path": "cue.wav"},
        {"music": "P:/Assets/Music"},
        caller=lambda action, **kw: {"ok": True},
    )
    assert status == 400
    assert body["ok"] is False


# ---------------------------------------------------------------------------
# POST /music/send: a missing track is synced down from the NAS (2026-08-16)
# ---------------------------------------------------------------------------
#
# The library is not a synced folder, so on every remote editor's machine
# "+ Resolve" answered "file not found -- is the share mounted?" and stopped
# (an editor's rig, 2026-08-16) -- the dead end the b-roll insert escaped on 2026-08-11.
# Same escape, same gate (derived mount only, never a base rig, never another
# share), same job registry (broll_fetch), one NAS-side folder parameter.


def _editor_cfg(tmp_path):
    return {
        "local_root": str(tmp_path),
        "mode": "editor",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/creators_club",
        "rclone_path": "rclone",
    }


def _send_body(rel="Ambient/cue.wav", action="under"):
    return {"action": action, "share": "music", "rel_path": rel}


def test_a_missing_track_starts_a_download_and_reports_progress(tmp_path):
    cfg = _editor_cfg(tmp_path)
    mounts = music_server.resolve_music_mounts({}, cfg)
    calls = []

    def fetcher(ccsync_cfg, rel_path, dest, remote_rel=None):
        calls.append((ccsync_cfg, rel_path, dest, remote_rel))
        return {"state": "downloading", "progress": {"percent": 12, "bytes": 12,
                                                     "total_bytes": 100}}

    status, body = music_server.build_send_response(
        _send_body(), mounts, ccsync_cfg=cfg, fetcher=fetcher,
        caller=lambda *a, **k: pytest.fail("the worker must not run before the file lands"))

    assert status == 200
    assert body["ok"] is False
    assert body["state"] == "downloading"
    assert "12%" in body["error"], "this route's message key is `error`"
    assert body["progress"]["percent"] == 12
    assert calls[0][1] == "Ambient/cue.wav"
    assert calls[0][2] == str(tmp_path / "Assets" / "Music" / "Ambient" / "cue.wav")
    from ccsync_companion import broll_fetch
    assert calls[0][3] == broll_fetch.MUSIC_REMOTE_REL == "Assets/Music"


def test_the_poll_that_finds_the_track_performs_the_send(tmp_path):
    cfg = _editor_cfg(tmp_path)
    mounts = music_server.resolve_music_mounts({}, cfg)
    dest = tmp_path / "Assets" / "Music" / "Ambient" / "cue.wav"
    seen = {}

    def fetcher(ccsync_cfg, rel_path, d, remote_rel=None):
        # The download finished between polls: the file is there now.
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"RIFF")
        return {"state": "done"}

    def worker(action, **kw):
        seen["action"], seen["kw"] = action, kw
        return {"ok": True, "note": "placed"}

    status, body = music_server.build_send_response(
        _send_body(), mounts, ccsync_cfg=cfg, fetcher=fetcher, caller=worker)

    assert status == 200 and body["ok"] is True
    assert seen["action"] == "under"
    assert Path(seen["kw"]["path"]) == dest


def test_a_failed_download_says_so_in_the_error(tmp_path):
    cfg = _editor_cfg(tmp_path)
    mounts = music_server.resolve_music_mounts({}, cfg)

    status, body = music_server.build_send_response(
        _send_body(), mounts, ccsync_cfg=cfg,
        fetcher=lambda *a, **k: {"state": "failed", "message": "sftp: connection refused"},
        caller=lambda *a, **k: pytest.fail("no send on a failed fetch"))

    assert status == 200 and body["ok"] is False
    assert "couldn't sync the track" in body["error"]
    assert "connection refused" in body["error"]


def test_no_ccsync_cfg_keeps_the_old_not_found_message(tmp_path):
    """The pre-fetch contract, pinned: without the companion's own config
    there is no remote to fetch from."""
    status, body = music_server.build_send_response(
        _send_body(rel="cue.wav"), {"music": str(tmp_path)}, ccsync_cfg=None,
        fetcher=lambda *a, **k: pytest.fail("must not fetch without a ccsync config"),
        caller=lambda *a, **k: pytest.fail("no worker"))
    assert status == 200
    assert "is the share mounted?" in body["error"]


def test_a_base_rig_does_not_fetch_a_track_from_itself(tmp_path):
    cfg = dict(_editor_cfg(tmp_path), mode="base")
    mounts = music_server.resolve_music_mounts({}, cfg)
    status, body = music_server.build_send_response(
        _send_body(), mounts, ccsync_cfg=cfg,
        fetcher=lambda *a, **k: pytest.fail("a base rig must not fetch"),
        caller=lambda *a, **k: pytest.fail("no worker"))
    assert "is the share mounted?" in body["error"]


def test_a_hand_overridden_music_mount_is_not_downloaded_into(tmp_path):
    cfg = _editor_cfg(tmp_path)
    mounts = {"music": "Y:/some/smb/mount"}
    status, body = music_server.build_send_response(
        _send_body(), mounts, ccsync_cfg=cfg,
        fetcher=lambda *a, **k: pytest.fail("an overridden mount must not be fetched into"),
        caller=lambda *a, **k: pytest.fail("no worker"))
    assert "is the share mounted?" in body["error"]


def test_the_downloading_state_travels_over_the_music_route(live_server, tmp_path, monkeypatch):
    """The live handler passes the companion's own config through -- without
    that the whole feature is inert, exactly as b-roll's was until wired."""
    from ccsync_companion import broll_fetch
    srv, client, _calls = live_server
    cfg = _editor_cfg(tmp_path)
    srv.ccsync_cfg = cfg
    srv.companion_config[music_server.MOUNTS_KEY] = music_server.resolve_music_mounts({}, cfg)
    monkeypatch.setattr(
        broll_fetch, "poll_fetch",
        lambda ccsync_cfg, rel_path, dest, remote_rel=None: {
            "state": "downloading", "progress": {"percent": 40}},
    )

    status, _headers, body = client.post_json("/music/send", _send_body())

    data = json.loads(body)
    assert status == 200
    assert data["ok"] is False
    assert data["state"] == "downloading"
    assert data["progress"]["percent"] == 40


def test_the_fetch_command_targets_the_music_library_on_the_nas(tmp_path):
    from ccsync_companion import broll_fetch
    cfg = _editor_cfg(tmp_path)
    cmd = broll_fetch.build_fetch_command(cfg, "Ambient/cue.wav", str(tmp_path / "cue.wav"),
                                          remote_rel=broll_fetch.MUSIC_REMOTE_REL)
    assert cmd[1] == "copyto"
    assert cmd[2] == "creators_club_sftp:/mnt/tank/creators_club/Assets/Music/Ambient/cue.wav"
    # ...and the archive default is untouched.
    cmd = broll_fetch.build_fetch_command(cfg, "x/clip.mov", str(tmp_path / "clip.mov"))
    assert cmd[2] == "creators_club_sftp:/mnt/tank/creators_club/Assets/B-roll Archive/x/clip.mov"


# ---------------------------------------------------------------------------
# The status probes are memoised and serialised
# (bug-hunt-2026-09-03 comp-broll-music-3)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _empty_probe_cache():
    """Every test in this file starts with no memoised probe, and leaves
    none: the cache is keyed on the caller, but a live_server test and a
    direct one can share the module's own `call`."""
    music_server.reset_probe_cache()
    yield
    music_server.reset_probe_cache()


def test_fifty_concurrent_status_requests_spawn_one_worker(monkeypatch):
    """A GET needs no Origin and no token (a subresource load sends neither),
    and each one used to spawn a Resolve worker child: 300 <img> tags on any
    page an editor had open meant 300 copies of the frozen companion, each
    living up to 90 s, all knocking on fuscript's door (CR-68). The answer is
    a yes/no a settings dot draws, so the losers of the race read the
    winner's."""
    calls = []
    started = threading.Event()

    def _slow_call(action, timeout=None, **kw):
        calls.append(action)
        started.set()
        # Long enough that every other thread is queued behind this one.
        time.sleep(0.3)
        return {"ok": True, "project": "P", "timeline": "T"}

    monkeypatch.setattr(music_server, "call", _slow_call)

    answers: list = []
    threads = [threading.Thread(
        target=lambda: answers.append(music_server.build_status_response()))
        for _ in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert started.is_set()
    assert len(calls) == 1
    assert len(answers) == 50
    assert all(body["project"] == "P" for _status, body in answers)


def test_a_memoised_status_is_not_a_permanent_one(monkeypatch):
    """It is a few seconds of de-duplication, not a cache: an editor who opens
    the project the dot said was missing must see it on the next look."""
    seen = []

    def _call(action, timeout=None, **kw):
        seen.append(action)
        return {"ok": True, "n": len(seen)}

    monkeypatch.setattr(music_server, "call", _call)
    monkeypatch.setattr(music_server, "PROBE_TTL_S", 0.0)

    assert music_server.build_status_response()[1]["n"] == 1
    assert music_server.build_status_response()[1]["n"] == 2


def test_the_broll_status_probe_shares_the_same_slot(monkeypatch):
    """/status is the same shape on the same listener and spawns the same
    child -- it may not be the route that is left uncapped."""
    calls = []

    def _call(action, timeout=None, **kw):
        calls.append(action)
        time.sleep(0.2)
        return {"resolve_connected": True}

    monkeypatch.setattr(music_server, "call", _call)
    threads = [threading.Thread(target=lambda: broll_server.build_status_response({}))
               for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert calls == [music_worker.BROLL_STATUS_ACTION]


def test_at_the_download_cap_the_music_route_says_wait_not_error(tmp_path):
    """CMEDIA-7: an editor who clicked "+ Resolve" on a cue while two camera
    originals were in flight got a red toast and had to remember to come back.
    The key is `message` and not `error` BECAUSE nothing failed."""
    from ccsync_companion import broll_fetch

    cfg = _editor_cfg(tmp_path)
    mounts = music_server.resolve_music_mounts({}, cfg)

    status, body = music_server.build_send_response(
        _send_body(), mounts, ccsync_cfg=cfg,
        fetcher=lambda *a, **k: {"state": broll_fetch.STATE_BUSY,
                                 "message": broll_fetch.BUSY_MESSAGE,
                                 "retry_after": 1.5},
        caller=lambda *a, **k: pytest.fail("nothing is sent while it waits"))

    assert status == 200
    assert body["ok"] is True and body["state"] == "busy"
    assert body["retry_after"] == broll_fetch.BUSY_RETRY_AFTER_SECONDS
    assert "error" not in body
    assert "already downloading" in body["message"]
