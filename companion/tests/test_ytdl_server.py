r"""POST /ytdl/reveal -- the downloader page's "show me that clip" button.

The YouTube page is served from the NAS dashboard and its download history
knows a clip only as a path under the Projects root
("2026/FF5/Energy Transition/Youtube/links/Some Clip [abc123].mp4"). Clicking
a row has to open THAT editor's file manager on THAT editor's machine, so the
route lives on the companion's 8899 loopback listener -- the one the b-roll
and music route groups already share, because a second server on that port
breaks the tray app.

Four things this file exists to hold still:
  - the argv, per platform, built and never executed here. NOTHING in this
    suite may launch Explorer, Finder or any other process (autouse guard
    below), and nothing may touch P:\.
  - no shell, ever. MUSIC-2 (2026-08-11) was a command injection through
    cmd.exe in the music web app's own reveal route; YouTube titles carry `&`
    routinely, so the path travels as one argv element with nothing to
    re-parse it.
  - containment. A rel_path that escapes the Projects root is refused before
    anything is spawned, including the probed-mount case MED-11 fixed.
  - a request nobody meant to send (MED-5/MED-10): a non-string rel_path, a
    garbage Content-Length, a body too big to read.
"""

from __future__ import annotations

import http.client
import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from ccsync_companion import (
    broll_server, loopback_guard, music_server, ytdl_server,
)

# The dashboard the live_server fixture is pointed at -- the one origin a
# browser caller may present (COMMERCIAL_READINESS.md item 5, 2026-08-17).
DASH_ORIGIN = "http://100.64.0.1:8000"

# The junction/symlink helper is test_music_server's, not a second copy of it:
# it is the only way to build a "no '..', no drive letter, still outside the
# root" path on either host.
from test_music_server import _link_or_skip


REL = "2026/FF5/Energy Transition/Youtube/links/Some Clip [abc123].mp4"

# Captured BEFORE the autouse guard below replaces it, so the one test that
# drives the real spawn() can still reach it.
REAL_SPAWN = ytdl_server.spawn


# ---------------------------------------------------------------------------
# Guards: nothing in this file may start a process
# ---------------------------------------------------------------------------


class _NoSubprocess:
    """A stand-in for the `subprocess` name INSIDE ytdl_server.

    Not a monkeypatch of subprocess.Popen itself: that module attribute is
    what subprocess.run() calls internally, so patching it would also break
    the junction fallback these tests use to build an escaping path on
    Windows.
    """

    DEVNULL = subprocess.DEVNULL
    CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # Pure string work, no process: windows_command_line() quotes with it.
    list2cmdline = staticmethod(subprocess.list2cmdline)

    @staticmethod
    def Popen(*a, **kw):
        pytest.fail(f"a test launched a real process: {a!r} {kw!r}")


@pytest.fixture(autouse=True)
def never_spawn_anything(monkeypatch):
    """AUTOUSE, same class of guard as conftest's real-Tk one.

    This module's whole job is to launch a file manager, and a test that
    actually did would open windows all over the developer's desktop. Both
    spawn seams are nailed shut here; the tests that care about the argv
    inject their own recorder on top.
    """
    def _boom(*a, **kw):
        pytest.fail(f"a test spawned a real process: {a!r} {kw!r}")

    monkeypatch.setattr(ytdl_server, "subprocess", _NoSubprocess)
    monkeypatch.setattr(ytdl_server, "spawn", _boom)


@pytest.fixture
def spawned(monkeypatch):
    """Record what would have been launched, and launch nothing."""
    calls: list = []
    monkeypatch.setattr(ytdl_server, "spawn", lambda argv: calls.append(argv))
    return calls


@pytest.fixture
def tree(tmp_path):
    """A Projects root with the ledgered clip really in it."""
    root = tmp_path / "Projects"
    clip = root / Path(*REL.split("/"))
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"fake video bytes")
    return root, clip


def _mounts(root) -> dict:
    return {ytdl_server.PROJECTS_SHARE: str(root)}


# ---------------------------------------------------------------------------
# The "projects" mount
# ---------------------------------------------------------------------------


def test_the_projects_share_defaults_to_the_tree(tmp_path):
    mounts = ytdl_server.resolve_ytdl_mounts({"mounts": {}}, {"local_root": str(tmp_path)})
    assert mounts["projects"] == str(tmp_path / "Projects")


def test_an_explicit_projects_entry_still_wins(tmp_path):
    mounts = ytdl_server.resolve_ytdl_mounts(
        {"mounts": {"projects": "Y:/Creators_Club/Projects"}},
        {"local_root": str(tmp_path)},
    )
    assert mounts["projects"] == "Y:/Creators_Club/Projects"


def test_a_blank_projects_entry_counts_as_unset(tmp_path):
    mounts = ytdl_server.resolve_ytdl_mounts(
        {"mounts": {"projects": "  "}}, {"local_root": str(tmp_path)}
    )
    assert mounts["projects"] == str(tmp_path / "Projects")


def test_no_default_without_a_local_root():
    """Same rule as the other two groups': answer "no mount configured", never
    translate to a relative path under the process CWD."""
    assert ytdl_server.default_projects_mount({"local_root": ""}) is None
    assert ytdl_server.resolve_ytdl_mounts({"mounts": {}}, {"local_root": ""}) == {}


def test_the_projects_default_does_not_leak_into_the_other_groups(tmp_path):
    """GUARD. broll_server.resolve_mounts feeds GET /status, which is what the
    b-roll settings panel shows an editor -- test_broll_server pins that set to
    {"broll"} -- and the music map is its own namespace too."""
    cfg = {"local_root": str(tmp_path)}
    assert set(broll_server.resolve_mounts({"mounts": {}}, cfg)) == {"broll"}
    assert set(music_server.resolve_music_mounts({"mounts": {}}, cfg)) == {"music"}


def test_no_mount_configured_is_200_so_the_page_can_show_it(spawned):
    status, body = ytdl_server.build_reveal_response({"rel_path": REL}, {})
    assert status == 200
    assert body["ok"] is False
    assert body["message"] == "no mount configured for share 'projects'"
    assert spawned == []


# ---------------------------------------------------------------------------
# Translation: the contained helper, not a second copy of the rules
# ---------------------------------------------------------------------------


def test_translation_is_the_contained_helper(tmp_path):
    """Not a re-implementation: the '..'/drive-letter component rules, the
    absolute-rel_path refusal and MED-11's final containment check all live in
    music_server.local_path_for, and a rule enforced in one translator and not
    the other is how a traversal gets served."""
    mounts = _mounts(tmp_path)
    assert ytdl_server.local_path_for(REL, mounts) == music_server.local_path_for(
        ytdl_server.PROJECTS_SHARE, REL, mounts
    )


def test_a_legitimate_nested_path_translates_to_the_local_tree(tmp_path):
    got = ytdl_server.local_path_for(REL, _mounts(tmp_path / "Projects"))
    assert Path(got) == tmp_path / "Projects" / Path(*REL.split("/"))


def test_the_page_never_sends_the_servers_path(tmp_path):
    """The architectural point, same as the music route's: the NAS's
    W:\\Creators_Club\\Projects\\... means nothing here, where the same clip is
    P:\\Projects\\..."""
    editor = ytdl_server.local_path_for(REL, {"projects": "P:/Projects"})
    nas = ytdl_server.local_path_for(REL, {"projects": "W:/Creators_Club/Projects"})
    assert editor != nas
    assert editor.replace("\\", "/").startswith("P:/Projects/2026/FF5/")


@pytest.mark.parametrize(
    "rel_path",
    [
        "../secrets.txt",
        "../../Windows/System32/config/SAM",
        "2026/../../secrets.txt",
        "..\\secrets.txt",
        "C:/Windows/System32/config/SAM",
        "C:\\Windows\\System32\\config\\SAM",
        "/etc/passwd",
        "//attacker/share/payload.mp4",
        "\\\\attacker\\share\\payload.mp4",
        "2026/C:/x.mp4",
        "",
        "   ",
    ],
)
def test_escape_attempts_are_400_and_spawn_nothing(rel_path, spawned):
    status, body = ytdl_server.build_reveal_response(
        {"rel_path": rel_path}, {"projects": "P:/Projects"}
    )
    assert status == 400
    assert body["ok"] is False
    assert spawned == [], "nothing may be launched after a rejected path"


def test_a_symlinked_escape_is_refused(tmp_path, spawned):
    """No '..', no drive letter, nothing the component rules can see -- and it
    lands outside the Projects root all the same."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.mp4").write_bytes(b"x")
    root = tmp_path / "Projects"
    root.mkdir()
    _link_or_skip(root, outside)

    status, body = ytdl_server.build_reveal_response(
        {"rel_path": "link/secret.mp4"}, _mounts(root)
    )
    assert status == 400
    assert body["ok"] is False
    assert spawned == []


def test_a_probed_mount_is_containment_checked_too(tmp_path, monkeypatch, spawned):
    """MED-11: the check was skipped whenever the root came from the macOS
    /Volumes probe rather than the mounts table -- which is exactly the case
    this route inherits by using translate_path_with_root."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.mp4").write_bytes(b"x")
    root = tmp_path / "volume"
    root.mkdir()
    _link_or_skip(root, outside)

    monkeypatch.setattr(broll_server.sys, "platform", "darwin")
    monkeypatch.setattr(broll_server, "probe_darwin_mount",
                        lambda share, isdir=None: str(root))

    # NO entry for "projects": the root can only come from the probe.
    status, body = ytdl_server.build_reveal_response({"rel_path": "link/secret.mp4"}, {})
    assert status == 400
    assert body["ok"] is False
    assert spawned == []


# ---------------------------------------------------------------------------
# The argv, per platform -- built, never run
# ---------------------------------------------------------------------------


def test_windows_selects_the_file_in_its_folder(tree, spawned):
    root, clip = tree
    status, body = ytdl_server.build_reveal_response(
        {"rel_path": REL}, _mounts(root), platform="win32"
    )

    assert status == 200 and body["ok"] is True
    (argv,) = spawned
    assert isinstance(argv, list), "the argv must be a list, not a command string"
    assert argv[0] == "explorer"
    assert len(argv) == 2 and argv[1] == f"/select,{clip}"


def test_macos_reveals_the_file_in_finder(tree, spawned):
    root, clip = tree
    status, body = ytdl_server.build_reveal_response(
        {"rel_path": REL}, _mounts(root), platform="darwin"
    )

    assert status == 200 and body["ok"] is True
    (argv,) = spawned
    assert argv[0] == "open" and argv[1] == "-R"
    assert len(argv) == 3 and Path(argv[2]) == clip


def test_the_whole_path_is_one_argument_metacharacters_and_all(tmp_path, spawned):
    """MUSIC-2, in the platform this route ships on: `&` is legal in a Windows
    filename and routine in a YouTube title, and cmd.exe would have read it as
    a command separator."""
    nasty = "rock & roll & calc [xyz789].mp4"
    root = tmp_path / "Projects"
    folder = root / "2026" / "FF5" / "Energy Transition" / "Youtube" / "links"
    folder.mkdir(parents=True)
    (folder / nasty).write_bytes(b"x")

    rel = f"2026/FF5/Energy Transition/Youtube/links/{nasty}"
    for platform, expected_index in (("win32", 1), ("darwin", 2)):
        spawned.clear()
        status, body = ytdl_server.build_reveal_response(
            {"rel_path": rel}, _mounts(root), platform=platform
        )
        assert status == 200 and body["ok"] is True
        (argv,) = spawned
        assert argv[expected_index].endswith(nasty)
        assert sum(1 for part in argv if nasty in part) == 1


def test_no_code_path_hands_anything_to_a_shell():
    """The MUSIC-2 shape, pinned at the source: `os.spawnl(P_NOWAIT, COMSPEC,
    'cmd', '/c', ...)`. A future edit that reaches for a shell -- for quoting,
    for `start`, for anything -- fails here.

    Read as an AST, not as text: this module's own comments have to be free to
    say the words "shell=True" and "COMSPEC" while warning against them.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ytdl_server))
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "shell":
            pytest.fail("a shell keyword reached the spawn")
        if isinstance(node, ast.Attribute) and node.attr in {
            "system", "spawnl", "spawnv", "spawnle", "popen", "startfile"
        }:
            pytest.fail(f"os.{node.attr} is a shell or a shell in disguise")
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node not in docstrings):
            assert "COMSPEC" not in node.value
            assert "cmd.exe" not in node.value


# ---------------------------------------------------------------------------
# The Windows command line: the quote goes AROUND THE PATH, never before /select
# ---------------------------------------------------------------------------
#
# 2026-08-16, an editor: every "open in Explorer" click opened Documents.
# Popen(list) quotes any argument with a space, and every path in this tree
# has one, so Explorer got `"/select,F:\...\Season 1\clip.mp4"` -- a token
# that starts with a quote, which it does not recognise as a switch and
# silently answers with the default folder. A window opened and the endpoint
# said ok:true, so nothing looked wrong. The exact command line is therefore
# pinned here, including the cases that hid it: a SPACE-FREE path is built
# identically (so a convenient test path cannot pass by luck), a UNC path
# keeps both leading backslashes, and a path containing `"` is refused rather
# than escaped.


@pytest.mark.parametrize("path", [
    r"F:\Creators_Club\Projects\2026\CCT\Creator Profiles\Season 1\Youtube\a b [x].mp4",
    r"C:\tmp\a.mp4",                                        # no spaces: same shape
    r"\\192.168.0.10\TheCreatorsPool\Creators_Club\Projects\x y\clip.mp4",
    r"C:\rock & roll & calc [xyz789].mp4",                  # MUSIC-2's metacharacters
])
def test_windows_select_line_is_bare_switch_then_quoted_path(path):
    line = ytdl_server.windows_command_line(["explorer", f"/select,{path}"])
    assert line == f'explorer /select,"{path}"'
    assert not line.split(" ", 1)[1].startswith('"'), "the switch must not be inside the quotes"
    assert line.count('"') == 2


def test_windows_folder_open_is_a_plainly_quoted_path():
    line = ytdl_server.windows_command_line(["explorer", r"F:\some folder\Season 1"])
    assert line == r'explorer "F:\some folder\Season 1"'
    line = ytdl_server.windows_command_line(["explorer", r"C:\nospaces"])
    assert line == r"explorer C:\nospaces"


def test_a_path_with_a_quote_is_refused_not_escaped():
    with pytest.raises(ValueError):
        ytdl_server.windows_command_line(["explorer", '/select,C:\\bad"name.mp4'])


def test_the_reveal_answers_ok_false_when_the_command_line_is_refused(tree):
    """...and that refusal reaches the page as an inline message, never a 500."""
    root, clip = tree

    def _refuse(argv):
        raise ValueError("refusing to reveal a path containing a quote")

    status, body = ytdl_server.build_reveal_response(
        {"rel_path": REL}, _mounts(root), spawner=_refuse, platform="win32"
    )
    assert status == 200 and body["ok"] is False
    assert "file manager" in body["message"]


def test_spawn_uses_popen_with_no_shell(monkeypatch):
    """The one function that really launches something, driven with a
    recorder in place of the subprocess module it reaches for.

    On Windows the argument is the hand-built command LINE (a string
    CreateProcess gets verbatim -- Popen(str) on win32 involves no shell);
    elsewhere it is the argv list. Either way `&` in the path is data."""
    seen: dict = {}

    class _Recorder:
        DEVNULL = subprocess.DEVNULL
        CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        list2cmdline = staticmethod(subprocess.list2cmdline)

        @staticmethod
        def Popen(argv, **kwargs):
            seen["argv"] = argv
            seen["kwargs"] = kwargs
            return object()

    monkeypatch.setenv("PYTHONHOME", "C:/mei-12345")
    monkeypatch.setattr(ytdl_server, "subprocess", _Recorder)

    REAL_SPAWN(["explorer", "/select,C:/x & y.mp4"])

    if sys.platform == "win32":
        assert seen["argv"] == 'explorer /select,"C:/x & y.mp4"'
    else:
        assert seen["argv"] == ["explorer", "/select,C:/x & y.mp4"]
    assert not seen["kwargs"].get("shell")
    # PYTHONHOME is pinned at OUR _MEIPASS, which the bootloader deletes when
    # we exit -- and every app the editor launches from that Explorer window
    # would inherit it (resolve_bridge CORE-M6).
    assert "PYTHONHOME" not in seen["kwargs"]["env"]


def test_the_command_builder_has_no_answer_off_these_two_platforms():
    assert ytdl_server.reveal_command("/tmp/x.mp4", True, platform="linux") is None
    assert ytdl_server.reveal_command("/tmp/x.mp4", False, platform="linux") is None


def test_a_bundle_is_revealed_never_opened():
    """`open /Volumes/x/Thing.app` LAUNCHES it, and both reveal routes on this
    listener pass a folder-shaped target through here with select=False (the
    "file isn't here yet, show the folder" branch). A share holding a bundle
    would have turned "show me where this is" into "run this"
    (COMMERCIAL_READINESS.md item 5, 2026-08-17)."""
    assert ytdl_server.reveal_command("/Users/x/Thing.app", False,
                                      platform="darwin") == \
        ["open", "-R", "/Users/x/Thing.app"]
    assert ytdl_server.reveal_command("C:/x/Thing.app", False,
                                      platform="win32") == \
        ["explorer", "/select,C:/x/Thing.app"]


@pytest.mark.parametrize("name", ["Thing.app", "Disk.dmg", "Setup.pkg",
                                  "Some.Bundle", "thing.APP"])
def test_every_launchable_shape_is_revealed_not_opened(name):
    assert ytdl_server.reveal_command(f"/Users/x/{name}", False,
                                      platform="darwin")[1] == "-R"


def test_an_ordinary_folder_is_still_opened_as_a_folder():
    """...and the guard does not turn every folder reveal into a select."""
    assert ytdl_server.reveal_command("/Users/x/Youtube", False,
                                      platform="darwin") == \
        ["open", "/Users/x/Youtube"]


def test_an_unsupported_platform_says_so_and_spawns_nothing(tree, spawned):
    root, clip = tree
    status, body = ytdl_server.build_reveal_response(
        {"rel_path": REL}, _mounts(root), platform="linux"
    )
    assert status == 200 and body["ok"] is False
    assert str(clip) in body["message"]
    assert spawned == []


def test_a_file_manager_that_will_not_start_is_an_answer_not_a_crash(tree, monkeypatch):
    root, _clip = tree

    def _explode(argv):
        raise OSError("no explorer here")

    status, body = ytdl_server.build_reveal_response(
        {"rel_path": REL}, _mounts(root), spawner=_explode, platform="win32"
    )
    assert status == 200 and body["ok"] is False
    assert "no explorer here" in body["message"]


# ---------------------------------------------------------------------------
# The file is gone, the folder is not (and vice versa)
# ---------------------------------------------------------------------------


def test_a_missing_file_with_a_present_folder_opens_the_folder(tree, spawned):
    """The row is in the dashboard's ledger and the clip has not arrived (or
    somebody moved it). The folder is what the editor clicked to look at."""
    root, clip = tree
    clip.unlink()

    status, body = ytdl_server.build_reveal_response(
        {"rel_path": REL}, _mounts(root), platform="win32"
    )

    assert status == 200 and body["ok"] is True
    (argv,) = spawned
    assert argv == ["explorer", str(clip.parent)], "no /select, for a file that is gone"
    assert clip.name in body["message"]


def test_the_folder_open_is_the_same_shape_on_macos(tree, spawned):
    root, clip = tree
    clip.unlink()

    ytdl_server.build_reveal_response(
        {"rel_path": REL}, _mounts(root), platform="darwin"
    )

    (argv,) = spawned
    assert argv[0] == "open" and "-R" not in argv
    assert Path(argv[-1]) == clip.parent


def test_neither_the_file_nor_the_folder_spawns_nothing(tmp_path, spawned):
    """"explorer <a path that does not exist>" opens the editor's Documents
    folder, which reads as a bug. Say what happened instead."""
    root = tmp_path / "Projects"
    root.mkdir()

    status, body = ytdl_server.build_reveal_response(
        {"rel_path": REL}, _mounts(root), platform="win32"
    )

    assert status == 200 and body["ok"] is False
    assert "is not on this machine" in body["message"]
    # 2026-08-16: originals no longer sync down, so the message must not
    # promise "has it synced here yet?" -- it says where the clip is instead.
    assert "synced here yet" not in body["message"]
    assert "stays on the NAS" in body["message"]
    assert spawned == []


# ---------------------------------------------------------------------------
# A request nobody meant to send (MED-5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [123, ["clip.mp4"], {"rel_path": "clip.mp4"}, None, True])
def test_a_non_string_rel_path_is_400_not_a_dead_request(bad, spawned):
    """MED-5: the string methods in the translator raised straight out of the
    request thread -- no response, and no log line either, because
    socketserver.handle_error writes to a sys.stderr that is None in the
    windowed build."""
    status, body = ytdl_server.build_reveal_response(
        {"rel_path": bad}, {"projects": "P:/Projects"}
    )
    assert status == 400
    assert body["ok"] is False
    assert "rel_path" in body["message"]
    assert spawned == []


def test_a_body_with_no_rel_path_at_all_is_400(spawned):
    status, body = ytdl_server.build_reveal_response({}, {"projects": "P:/Projects"})
    assert status == 400
    assert body["ok"] is False
    assert spawned == []


def test_a_mount_that_is_not_a_path_is_reported_not_crashed_on(spawned):
    """A hand-edited ~/.broll-companion.json can put anything in there."""
    status, body = ytdl_server.build_reveal_response(
        {"rel_path": REL}, {"projects": ["P:/Projects"]}
    )
    assert status == 200
    assert body["ok"] is False
    assert "not a path" in body["message"]
    assert spawned == []


# ---------------------------------------------------------------------------
# Over the wire, on the one listener
# ---------------------------------------------------------------------------


class Client:
    """As the other two route groups' clients: every POST carries the loopback
    token, because since 2026-08-17 a state-changing request needs an allowed
    Origin or that header (COMMERCIAL_READINESS.md item 5), and this stands in
    for a local caller. `origin=` exercises the browser path."""

    def __init__(self, port: int):
        self.port = port

    def _connect(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def _auth(self, token, origin) -> dict:
        headers = {}
        if token:
            headers[loopback_guard.TOKEN_HEADER] = loopback_guard.read_token() or ""
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

    def post_raw(self, path: str, payload: bytes, content_length=None):
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

    def options(self, path: str, origin=None):
        conn = self._connect()
        conn.request("OPTIONS", path, headers=self._auth(False, origin))
        resp = conn.getresponse()
        body = resp.read()
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, body


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live_server(tree, monkeypatch):
    """A real server on an ephemeral port, with all three route groups wired."""
    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: False)
    monkeypatch.setattr(music_server, "call",
                        lambda action, timeout=None, **kw: {"ok": True, "note": "fake"})

    root, clip = tree
    cfg = {
        "server_url": "http://127.0.0.1:8000",
        "mounts": {"broll": str(root)},
        music_server.MOUNTS_KEY: {"music": str(root)},
        ytdl_server.MOUNTS_KEY: {"projects": str(root)},
    }
    srv = broll_server.make_server(cfg, host="127.0.0.1", port=0,
                                   ccsync_cfg={"dashboard_url": DASH_ORIGIN})
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, Client(srv.server_address[1]), clip
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_reveal_over_http(live_server, spawned):
    _srv, client, clip = live_server
    status, _headers, body = client.post_json("/ytdl/reveal", {"rel_path": REL})

    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True and clip.name in data["message"]
    (argv,) = spawned
    assert isinstance(argv, list)
    assert Path(argv[-1].split(",", 1)[-1]) == clip


def test_reveal_traversal_over_http_is_400(live_server, spawned):
    _srv, client, _clip = live_server
    status, _headers, body = client.post_json(
        "/ytdl/reveal", {"rel_path": "../../../Windows/System32"}
    )
    assert status == 400
    assert json.loads(body)["ok"] is False
    assert spawned == []


def test_a_non_string_rel_path_over_http_gets_an_answer(live_server, spawned):
    _srv, client, _clip = live_server
    status, _headers, body = client.post_json("/ytdl/reveal", {"rel_path": ["x.mp4"]})
    assert status == 400
    assert json.loads(body)["ok"] is False
    assert spawned == []


def test_malformed_json_over_http_is_400_not_a_traceback(live_server, spawned):
    _srv, client, _clip = live_server
    status, body = client.post_raw("/ytdl/reveal", b"{not json")
    assert status == 400
    assert json.loads(body)["ok"] is False
    assert "message" in json.loads(body), "the page reads `message`, not `error`"
    assert spawned == []


@pytest.mark.parametrize("payload", [b'"just a string"', b"[1, 2, 3]", b"null"])
def test_a_json_body_that_is_not_an_object_is_400(live_server, payload, spawned):
    _srv, client, _clip = live_server
    status, body = client.post_raw("/ytdl/reveal", payload)
    assert status == 400
    assert json.loads(body)["ok"] is False
    assert spawned == []


def test_a_garbage_content_length_is_400(live_server, spawned):
    """MED-10, on this route too. Header only, no body bytes: unread bytes in
    the receive buffer turn the close into an RST on Windows, which the client
    sees as an abort instead of the answer."""
    _srv, client, _clip = live_server
    status, body = client.post_raw("/ytdl/reveal", b"", content_length="abc")
    assert status == 400
    assert "Content-Length" in json.loads(body)["message"]
    assert spawned == []


def test_an_oversized_body_is_refused_without_reading_it(live_server, spawned):
    _srv, client, _clip = live_server
    status, body = client.post_raw(
        "/ytdl/reveal", b"", content_length=broll_server.MAX_BODY_BYTES + 1)
    assert status == 413
    assert json.loads(body)["ok"] is False
    assert spawned == []


def test_a_handler_that_raises_answers_500_and_logs(live_server, monkeypatch, caplog):
    """The dispatch guard covers this route as well -- socketserver's own
    handler prints the traceback to a sys.stderr that is None in the windowed
    build."""
    _srv, client, _clip = live_server

    def _boom(*a, **kw):
        raise RuntimeError("something nobody anticipated")

    monkeypatch.setattr(ytdl_server, "build_reveal_response", _boom)
    with caplog.at_level("ERROR", logger="ccsync.broll"):
        status, _headers, body = client.post_json("/ytdl/reveal", {"rel_path": REL})

    assert status == 500
    assert json.loads(body)["ok"] is False


def test_the_route_gets_the_same_cors_and_pna_headers(live_server):
    """The downloader page is served from the dashboard, so it sits on a
    tailnet address and calls loopback -- Chromium blocks that at the
    PREFLIGHT without the Private Network Access opt-in.

    THIS TEST USED TO PIN THE WILDCARD, as its b-roll twin did. Since
    2026-08-17 (COMMERCIAL_READINESS.md item 5 / C1) the answer is the
    caller's own origin, echoed only when it is on the allow-list, and a
    preflight from anywhere else gets 403 with no CORS headers at all -- so a
    hostile page cannot even read the refusal. The PROPERTY the wildcard
    assertion protected is what survives: the dashboard's own page must still
    get through the private-network preflight.
    """
    _srv, client, _clip = live_server
    status, headers, _body = client.options("/ytdl/reveal", origin=DASH_ORIGIN)
    assert status == 204
    assert headers.get("Access-Control-Allow-Origin") == DASH_ORIGIN
    assert headers.get("Access-Control-Allow-Private-Network") == "true"
    assert loopback_guard.TOKEN_HEADER in headers.get("Access-Control-Allow-Headers", "")

    status, headers, _body = client.options("/ytdl/reveal",
                                            origin="https://evil.example.com")
    assert status == 403
    assert "Access-Control-Allow-Origin" not in headers


def test_a_get_on_the_reveal_route_is_404_not_a_500(live_server):
    _srv, client, _clip = live_server
    status, _headers, body = client.get("/ytdl/reveal")
    assert status == 404
    assert json.loads(body)["ok"] is False


def test_the_other_two_route_groups_still_answer(live_server, monkeypatch):
    """THE regression a third route group could cause: one process, one port,
    and the older groups are the ones editors already depend on."""
    _srv, client, _clip = live_server
    monkeypatch.setattr(music_server, "call",
                        lambda action, timeout=None, **kw: {"ok": True, "note": "fake"})

    status, _headers, body = client.get("/status")
    assert status == 200
    data = json.loads(body)
    assert set(data.keys()) == {"ok", "resolve_connected", "mounts", "version"}
    assert "projects" not in data["mounts"]

    status, _headers, body = client.get("/music/status")
    assert status == 200 and json.loads(body)["ok"] is True


# ---------------------------------------------------------------------------
# start(): one listener, three groups
# ---------------------------------------------------------------------------


def test_start_derives_the_projects_mount_from_the_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: False)
    port = _free_port()
    server = broll_server.start({"local_root": str(tmp_path), "broll_server_port": port})
    assert server is not None
    try:
        mounts = server.companion_config[ytdl_server.MOUNTS_KEY]
        assert mounts["projects"] == str(tmp_path / "Projects")
        # its own namespace, like the music map's
        assert "broll" not in mounts and "music" not in mounts
    finally:
        broll_server.stop(server)


def test_start_serves_the_reveal_route_on_the_one_port(tmp_path, monkeypatch, spawned):
    monkeypatch.setattr(broll_server.resolve_bridge, "try_connect", lambda: False)
    clip = tmp_path / "Projects" / Path(*REL.split("/"))
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"x")

    port = _free_port()
    server = broll_server.start({"local_root": str(tmp_path), "broll_server_port": port})
    assert server is not None
    try:
        status, _headers, body = Client(port).post_json("/ytdl/reveal", {"rel_path": REL})
        assert status == 200
        assert json.loads(body)["ok"] is True
        (argv,) = spawned
        assert Path(argv[-1].split(",", 1)[-1]) == clip
    finally:
        broll_server.stop(server)

    # ...and exactly one listener was ever taken, so the port is free again.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_the_readme_snippet_documents_the_projects_share(tmp_path):
    cfg_path = tmp_path / ".broll-companion.json"
    readme_path = tmp_path / ".broll-companion.README.txt"
    broll_server.ensure_config_exists(path=cfg_path, readme_path=readme_path)
    text = readme_path.read_text(encoding="utf-8")
    assert "projects" in text.lower()
    assert "<local_root>/Projects" in text
