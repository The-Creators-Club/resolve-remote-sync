"""The yt-dlp sidecar manager: where the binary lives, what its version is,
and the ensure() decision table -- with no network and no real yt-dlp.

Style follows test_upgrade.py (injected http_open / recorded calls, never a
real socket) and test_broll_wiring.py for the CompanionApp half. The one place
a real process is spawned is the version probe, against a stand-in script this
file writes -- that path is subprocess plumbing (creationflags, env, timeout)
and stubbing it would prove nothing about it.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from ccsync_companion import app as app_mod
from ccsync_companion import resolve_bridge
from ccsync_companion import sidecar_tools
from ccsync_companion import ytdlp_manager as ytdlp_mod


# ---------------------------------------------------------------------------
# isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_tools_dir(tmp_path, monkeypatch):
    """No test may touch the REAL %LOCALAPPDATA%\\ccsync\\tools.

    conftest redirects HOME/USERPROFILE, which covers the POSIX branch of
    tools_dir() -- but the Windows branch reads LOCALAPPDATA, which nothing
    else redirects, and this module's install() CREATES DIRECTORIES AND WRITES
    BINARIES there. On the developer's own machine that is the directory a
    real companion would later run yt-dlp out of. Same class of guard as
    conftest's live-log and real-Tk fixtures.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))


@pytest.fixture
def tools(tmp_path):
    """The (isolated) tools dir this test's manager will use."""
    return ytdlp_mod.tools_dir()


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: bytes):
        self._stream = io.BytesIO(body)

    def read(self, n=-1):
        return self._stream.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _release(binary_body: bytes, *, name=None, sums=None, calls=None):
    """A fake github_open serving one yt-dlp release.

    `sums` overrides the SHA2-256SUMS body, which is how the mismatch and
    unlisted-asset cases are built."""
    asset = name or ytdlp_mod.binary_name()
    if sums is None:
        sums = f"{hashlib.sha256(binary_body).hexdigest()}  {asset}\n".encode()

    def opener(url, headers, timeout):
        if calls is not None:
            calls.append(url)
        if url.endswith("/" + ytdlp_mod.CHECKSUM_ASSET):
            return _FakeResponse(sums)
        if url.endswith("/" + asset):
            return _FakeResponse(binary_body)
        raise AssertionError(f"unexpected download URL {url}")

    return opener


def _dashboard(payload, *, calls=None):
    """A fake dashboard opener. `payload` may be a dict, raw bytes, or an
    exception instance to raise."""
    def opener(url, headers, timeout):
        if calls is not None:
            calls.append((url, headers, timeout))
        if isinstance(payload, Exception):
            raise payload
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return _FakeResponse(body)
    return opener


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _World:
    """A pretend machine with (or without) a yt-dlp on it.

    The binary is a REAL file at the managed path -- version() stats it before
    running anything -- but its behaviour comes from this recorded run_fn
    rather than from executing it.
    """

    def __init__(self, installed=None, update_to=None, update_ok=True):
        self.installed = installed
        self.update_to = update_to
        self.update_ok = update_ok
        self.argvs: list[list] = []
        self._sync_disk()

    @property
    def path(self) -> Path:
        return ytdlp_mod.tools_dir() / ytdlp_mod.binary_name()

    def _sync_disk(self) -> None:
        if self.installed is None:
            if self.path.exists():
                self.path.unlink()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"pretend yt-dlp")

    def run(self, argv, timeout):
        self.argvs.append(list(argv))
        if argv[1:] == ["--version"]:
            if self.installed is None:
                raise FileNotFoundError(argv[0])
            return _Proc(0, self.installed + "\n")
        if argv[1:] == ["-U"]:
            if not self.update_ok:
                return _Proc(1, "", "ERROR: unable to update")
            if self.update_to:
                self.installed = self.update_to
                self._sync_disk()
            return _Proc(0, f"Updated yt-dlp to {self.installed}\n")
        raise AssertionError(f"unexpected argv {argv}")

    @property
    def updated(self) -> bool:
        return any(argv[1:] == ["-U"] for argv in self.argvs)


def _manager(world=None, *, cfg=None, min_version="2026.08.10", github=None):
    config = {"dashboard_url": "http://dash.example.com"}
    config.update(cfg or {})
    payload = {"min_ytdlp_version": min_version, "download_pause_seconds": 3}
    return ytdlp_mod.YtDlpManager(
        config,
        http_open=_dashboard(payload),
        github_open=github or _release(b"downloaded-yt-dlp"),
        run_fn=(world.run if world is not None else None),
    )


# ---------------------------------------------------------------------------
# where it lives
# ---------------------------------------------------------------------------


def test_tools_dir_on_windows_is_beside_the_install(windows, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert ytdlp_mod.tools_dir() == tmp_path / "Local" / "ccsync" / "tools"
    assert ytdlp_mod.binary_name() == "yt-dlp.exe"


def test_tools_dir_on_macos_is_application_support(darwin):
    """The plan's explicit path (YTDL_LOCAL_DOWNLOAD.md §6) -- NOT
    ~/.local/ccsync/bin, where the macOS installer puts the companion."""
    expected = Path.home() / "Library" / "Application Support" / "ccsync" / "tools"
    assert ytdlp_mod.tools_dir() == expected
    assert ytdlp_mod.binary_name() == "yt-dlp_macos"


def test_binary_path_defaults_to_the_managed_binary():
    assert ytdlp_mod.binary_path({}) == ytdlp_mod.tools_dir() / ytdlp_mod.binary_name()
    assert ytdlp_mod.binary_path(None) == ytdlp_mod.binary_path({})


def test_binary_path_honours_the_override(tmp_path):
    mine = tmp_path / "mine" / "yt-dlp"
    assert ytdlp_mod.binary_path({"ytdlp_path": str(mine)}) == mine
    # blank/whitespace is "not set", not a path
    assert ytdlp_mod.binary_path({"ytdlp_path": "   "}) == ytdlp_mod.binary_path({})


def test_ensure_tools_dir_creates_it_and_is_idempotent():
    directory = ytdlp_mod.ensure_tools_dir()
    assert directory is not None and directory.is_dir()
    assert ytdlp_mod.ensure_tools_dir() == directory


def test_ensure_tools_dir_returns_none_when_it_cannot_be_made(monkeypatch):
    monkeypatch.setattr(
        Path, "mkdir", lambda *a, **kw: (_ for _ in ()).throw(OSError("read-only"))
    )
    assert ytdlp_mod.ensure_tools_dir() is None


# ---------------------------------------------------------------------------
# opt-out
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cfg, expected", [
    ({}, True),                                   # absent = opted in (plan §13 Q3)
    ({"ytdl_local_downloads": True}, True),
    ({"ytdl_local_downloads": False}, False),
    ({"ytdl_local_downloads": "false"}, True),    # bool("false") is True: never coerced
    ({"ytdl_local_downloads": None}, True),
])
def test_local_downloads_enabled(cfg, expected):
    assert ytdlp_mod.local_downloads_enabled(cfg) is expected


# ---------------------------------------------------------------------------
# version parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("2026.08.11\n", "2026.08.11"),
    ("  2026.08.11  ", "2026.08.11"),
    ("2026.08.11.232703\n", "2026.08.11.232703"),   # nightly
    ("\n\n2026.08.11\n", "2026.08.11"),
    ("", None),
    (None, None),
    ("ERROR: unable to start\n", None),
    ("yt-dlp version 2026.08.11\n", None),          # not a bare version line
    ("2026.08.11 (from a fork)\n", None),
])
def test_parse_version_output(text, expected):
    assert ytdlp_mod.parse_version_output(text) == expected


@pytest.mark.parametrize("current, minimum, older", [
    ("2026.07.01", "2026.08.10", True),
    ("2026.08.10", "2026.08.10", False),
    ("2026.08.11", "2026.08.10", False),
    ("2026.08.11", "2026.08.11.120000", True),      # nightly beats the stable it built on
    ("garbage", "2026.08.10", False),               # unrankable = leave it alone
    ("2026.08.11", "", False),
    (None, "2026.08.10", False),
])
def test_version_is_older(current, minimum, older):
    assert ytdlp_mod.version_is_older(current, minimum) is older


# ---------------------------------------------------------------------------
# version(): every failure shape is None
# ---------------------------------------------------------------------------


def test_version_of_a_missing_binary_is_none(tmp_path):
    assert ytdlp_mod.version(tmp_path / "nothing-here") is None


def test_version_reads_a_real_stand_in_binary(tmp_path):
    """Through the REAL runner: creationflags, sanitized env, timeout and all.
    A stubbed run_fn cannot show that a windowless spawn of a file on disk
    actually works."""
    fake = _write_fake_binary(tmp_path, "2026.08.11")
    assert ytdlp_mod.version(fake) == "2026.08.11"


def test_version_of_a_binary_that_fails_is_none(tmp_path):
    fake = _write_fake_binary(tmp_path, "2026.08.11", exit_code=1)
    assert ytdlp_mod.version(fake) is None


def test_version_of_a_binary_that_prints_nonsense_is_none(tmp_path):
    fake = _write_fake_binary(tmp_path, "ERROR: this is not yt-dlp")
    assert ytdlp_mod.version(fake) is None


def test_version_timeout_is_none(tmp_path, caplog):
    existing = tmp_path / "slow"
    existing.write_text("x")

    def hangs(argv, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)

    with caplog.at_level(logging.WARNING, logger="ccsync.ytdlp"):
        assert ytdlp_mod.version(existing, run_fn=hangs) is None
    assert any("--version" in r.getMessage() for r in caplog.records)


def test_version_when_the_spawn_itself_raises_is_none(tmp_path):
    existing = tmp_path / "broken"
    existing.write_text("x")

    def boom(argv, timeout):
        raise OSError("[WinError 193] not a valid Win32 application")

    assert ytdlp_mod.version(existing, run_fn=boom) is None


def test_version_uses_the_override_path(tmp_path):
    mine = tmp_path / "mine"
    mine.write_text("x")
    seen = []

    def run(argv, timeout):
        seen.append(argv)
        return _Proc(0, "2026.08.11\n")

    assert ytdlp_mod.version(cfg={"ytdlp_path": str(mine)}, run_fn=run) == "2026.08.11"
    assert seen[0][0] == str(mine)


def _write_fake_binary(tmp_path, output: str, exit_code: int = 0) -> Path:
    """A tiny executable stand-in that prints `output` -- a .cmd on Windows,
    a /bin/sh script elsewhere."""
    if sys.platform == "win32":
        path = tmp_path / "fake-yt-dlp.cmd"
        path.write_text(
            "@echo off\r\n"
            f"echo {output}\r\n"
            f"exit /b {exit_code}\r\n",
            encoding="utf-8",
        )
        return path
    path = tmp_path / "fake-yt-dlp"
    path.write_text(f"#!/bin/sh\necho '{output}'\nexit {exit_code}\n", encoding="utf-8")
    os.chmod(path, 0o755)
    return path


# ---------------------------------------------------------------------------
# the dashboard's floor
# ---------------------------------------------------------------------------


def test_fetch_min_version_reads_the_client_config():
    calls = []
    mgr = ytdlp_mod.YtDlpManager(
        {"dashboard_url": "http://dash.example.com/"},
        http_open=_dashboard({"min_ytdlp_version": "2026.08.10"}, calls=calls),
    )
    assert mgr.fetch_min_version() == "2026.08.10"
    url, headers, timeout = calls[0]
    assert url == "http://dash.example.com/ytdl/api/config/ytdl-client"
    # Unauthenticated by design (plan §4) -- no token on a request that only
    # reads a version number.
    assert headers == {}
    assert timeout <= 10


@pytest.mark.parametrize("payload", [
    OSError("connection refused"),
    b"<html>502 Bad Gateway</html>",
    b"",
    {"something_else": 1},
    ["not", "a", "dict"],
])
def test_fetch_min_version_is_none_on_anything_unusable(payload):
    mgr = ytdlp_mod.YtDlpManager({"dashboard_url": "http://d"}, http_open=_dashboard(payload))
    assert mgr.fetch_min_version() is None


def test_fetch_min_version_without_a_dashboard_url_makes_no_request():
    called = []
    mgr = ytdlp_mod.YtDlpManager({"dashboard_url": ""},
                                 http_open=_dashboard({}, calls=called))
    assert mgr.fetch_min_version() is None
    assert called == []


# ---------------------------------------------------------------------------
# install(): verified, free-space-checked, atomic
# ---------------------------------------------------------------------------


def test_install_downloads_verifies_and_lands_the_binary(tools):
    body = b"a-real-enough-yt-dlp"
    calls = []
    mgr = _manager(github=_release(body, calls=calls))
    assert mgr.install() is True

    installed = tools / ytdlp_mod.binary_name()
    assert installed.read_bytes() == body
    # The checksums are fetched BEFORE the artifact: nothing is trusted that
    # the release did not vouch for first.
    assert calls[0].endswith("/SHA2-256SUMS")
    assert calls[1].endswith("/" + ytdlp_mod.binary_name())
    assert all(u.startswith("https://github.com/yt-dlp/yt-dlp/releases/") for u in calls)
    # No temp file survives a success either.
    assert not (tools / (ytdlp_mod.binary_name() + ".new")).exists()


def test_install_sha_mismatch_leaves_the_old_binary_untouched(tools, caplog):
    tools.mkdir(parents=True, exist_ok=True)
    installed = tools / ytdlp_mod.binary_name()
    installed.write_bytes(b"the yt-dlp that already works")

    # Sums that vouch for something else entirely.
    bad = _release(b"tampered-payload",
                   sums=f"{'0' * 64}  {ytdlp_mod.binary_name()}\n".encode())
    mgr = _manager(github=bad)
    with caplog.at_level(logging.WARNING, logger="ccsync.ytdlp"):
        assert mgr.install() is False

    assert installed.read_bytes() == b"the yt-dlp that already works"
    assert not (tools / (ytdlp_mod.binary_name() + ".new")).exists()
    assert any("sha256 mismatch" in r.getMessage() for r in caplog.records)


def test_install_refuses_an_asset_the_release_does_not_list(tools, caplog):
    mgr = _manager(github=_release(b"x", sums=b"deadbeef  some-other-file\n"))
    with caplog.at_level(logging.WARNING, logger="ccsync.ytdlp"):
        assert mgr.install() is False
    assert not (tools / ytdlp_mod.binary_name()).exists()
    assert any("does not list" in r.getMessage() for r in caplog.records)


def test_install_refuses_when_the_disk_is_nearly_full(tools, monkeypatch, caplog):
    import shutil as shutil_mod

    class _Usage:
        total, used, free = 100, 99, 1

    monkeypatch.setattr(shutil_mod, "disk_usage", lambda p: _Usage)
    downloaded = []
    mgr = _manager(github=_release(b"x", calls=downloaded))
    with caplog.at_level(logging.WARNING, logger="ccsync.ytdlp"):
        assert mgr.install() is False
    # BEFORE the download, not after it: nothing was fetched at all.
    assert downloaded == []
    assert any("free" in r.getMessage() for r in caplog.records)


def test_install_leaves_nothing_behind_when_the_download_dies(tools):
    def dies(url, headers, timeout):
        if url.endswith(ytdlp_mod.CHECKSUM_ASSET):
            return _FakeResponse(f"{'a' * 64}  {ytdlp_mod.binary_name()}\n".encode())
        raise OSError("connection reset")

    mgr = _manager(github=dies)
    assert mgr.install() is False
    assert list(tools.iterdir()) == []


def test_install_refuses_a_body_over_the_ceiling(tools, monkeypatch):
    monkeypatch.setattr(ytdlp_mod, "MAX_DOWNLOAD_BYTES", 1024)
    mgr = _manager(github=_release(b"z" * 4096))
    assert mgr.install() is False
    assert list(tools.iterdir()) == []


def test_install_that_cannot_rename_leaves_no_partial_file(tools, monkeypatch):
    """The rename is the only moment anything visible changes. If it fails,
    the machine must look exactly as it did -- no half-written binary sitting
    at the name the executor will later run."""
    tools.mkdir(parents=True, exist_ok=True)
    installed = tools / ytdlp_mod.binary_name()
    installed.write_bytes(b"the yt-dlp that already works")

    def refuse(src, dst):
        raise OSError("locked by an AV scanner")

    monkeypatch.setattr(ytdlp_mod.os, "replace", refuse)
    mgr = _manager(github=_release(b"new-yt-dlp"))
    assert mgr.install() is False
    assert installed.read_bytes() == b"the yt-dlp that already works"
    assert not (tools / (ytdlp_mod.binary_name() + ".new")).exists()


def test_install_when_the_tools_dir_cannot_be_created(monkeypatch):
    monkeypatch.setattr(ytdlp_mod, "ensure_tools_dir", lambda: None)
    fetched = []
    mgr = _manager(github=_release(b"x", calls=fetched))
    assert mgr.install() is False
    assert fetched == []


# ---------------------------------------------------------------------------
# download origin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url, allowed", [
    ("https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe", True),
    ("https://objects.githubusercontent.com/blah", True),
    ("https://release-assets.githubusercontent.com/blah", True),
    ("http://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe", False),
    ("https://github.evil.com/yt-dlp.exe", False),
    ("https://githubusercontent.com.evil.net/x", False),
    ("", False),
    (None, False),
])
def test_is_allowed_release_url(url, allowed):
    assert ytdlp_mod.is_allowed_release_url(url) is allowed


def test_the_default_github_opener_refuses_a_non_github_url():
    with pytest.raises(ValueError):
        ytdlp_mod.default_github_open("http://attacker.example/yt-dlp.exe", {}, 1.0)


def test_parse_checksums():
    text = (
        "aaaa  yt-dlp\n"
        f"{'b' * 64}  yt-dlp.exe\n"
        f"{'c' * 64} *yt-dlp_macos\n"
        "# a comment\n"
    )
    assert ytdlp_mod.parse_checksums(text, "yt-dlp.exe") == "b" * 64
    assert ytdlp_mod.parse_checksums(text, "yt-dlp_macos") == "c" * 64
    assert ytdlp_mod.parse_checksums(text, "yt-dlp") is None       # too short a digest
    assert ytdlp_mod.parse_checksums(text, "yt-dlp_linux") is None
    assert ytdlp_mod.parse_checksums(None, "yt-dlp.exe") is None


# ---------------------------------------------------------------------------
# ensure(): the decision table
# ---------------------------------------------------------------------------


def test_ensure_installs_when_the_binary_is_missing(tools):
    world = _World(installed=None)
    mgr = _manager(world)
    # The real install() lands the file; the world then reports its version.
    real_install = mgr.install

    def install_and_record():
        ok = real_install()
        world.installed = "2026.08.12"
        world._sync_disk()
        return ok

    mgr.install = install_and_record
    status = mgr.ensure()
    assert status["action"] == ytdlp_mod.ACTION_INSTALLED
    assert status["ok"] is True
    assert status["version"] == "2026.08.12"
    assert not world.updated


def test_ensure_reports_failure_when_the_install_cannot_happen():
    world = _World(installed=None)
    mgr = _manager(world)
    mgr.install = lambda: False
    status = mgr.ensure()
    assert status["action"] == ytdlp_mod.ACTION_FAILED
    assert status["ok"] is False
    assert status["version"] is None
    assert "server" in status["message"]


def test_ensure_updates_a_stale_binary():
    world = _World(installed="2026.07.01", update_to="2026.08.14")
    mgr = _manager(world, min_version="2026.08.10")
    installs = []
    mgr.install = lambda: installs.append(1) or True

    status = mgr.ensure()
    assert world.updated, "a stale binary must be handed to yt-dlp's own -U"
    assert installs == [], "an update must never be a fresh install over the binary"
    assert status["action"] == ytdlp_mod.ACTION_UPDATED
    assert status["ok"] is True
    assert status["version"] == "2026.08.14"


def test_ensure_reports_failure_when_the_self_update_fails():
    world = _World(installed="2026.07.01", update_ok=False)
    mgr = _manager(world, min_version="2026.08.10")
    status = mgr.ensure()
    assert status["action"] == ytdlp_mod.ACTION_FAILED
    assert status["ok"] is False
    assert status["version"] == "2026.07.01"


def test_ensure_does_nothing_when_the_binary_is_current():
    world = _World(installed="2026.08.11")
    mgr = _manager(world, min_version="2026.08.10")
    mgr.install = lambda: pytest.fail("install() on a current binary")
    status = mgr.ensure()
    assert status["action"] == ytdlp_mod.ACTION_NONE
    assert status["ok"] is True
    assert not world.updated


def test_ensure_leaves_a_present_binary_alone_when_the_dashboard_is_down():
    """An unreachable dashboard is not evidence that anything is stale."""
    world = _World(installed="2020.01.01")
    mgr = ytdlp_mod.YtDlpManager(
        {"dashboard_url": "http://dash.example.com"},
        http_open=_dashboard(OSError("dashboard down")),
        github_open=_release(b"x"),
        run_fn=world.run,
    )
    status = mgr.ensure()
    assert not world.updated
    assert status["action"] == ytdlp_mod.ACTION_NONE
    assert status["ok"] is True


@pytest.mark.parametrize("floor, rankable", [
    ("2026.08.10", True),
    ("2026.08.11.120000", True),
    ("v2026.08.10", True),
    ("2026.8.5", True),                 # unpadded, but still numeric
    ("latest", False),
    ("2026.08.11-nightly", False),
    ("", False),
])
def test_version_floor_is_rankable(floor, rankable):
    assert ytdlp_mod.version_floor_is_rankable(floor) is rankable


def test_a_floor_this_cannot_rank_is_said_out_loud(caplog):
    """COMP-BROLL-9 (2026-08-14). An unrankable YTDL_MIN_YTDLP_VERSION is not
    harmless: this side refuses to order it and therefore never updates, while
    the dashboard -- which compares the raw strings -- can be 403-ing every
    claim in the fleet with the same value. Left unsaid, the only evidence
    anywhere is a 403 whose message contradicts the daily "yt-dlp X is
    current" in every companion's log."""
    world = _World(installed="2026.08.11")
    mgr = _manager(world, min_version="latest")

    with caplog.at_level(logging.ERROR, logger="ccsync.ytdlp"):
        status = mgr.ensure()

    assert any("is not a version this can rank" in r.getMessage()
               for r in caplog.records)
    # ...and the binary is still left exactly as it was: refusing to rank means
    # refusing to touch it, never replacing it on a guess.
    assert not world.updated
    assert status["action"] == ytdlp_mod.ACTION_NONE


def test_a_rankable_floor_says_nothing(caplog):
    world = _World(installed="2026.08.11")
    with caplog.at_level(logging.ERROR, logger="ccsync.ytdlp"):
        _manager(world, min_version="2026.08.10").ensure()
    assert [r.getMessage() for r in caplog.records] == []


def test_ensure_accepts_an_explicit_min_version_without_asking_the_dashboard():
    world = _World(installed="2026.07.01", update_to="2026.08.14")
    asked = []
    mgr = ytdlp_mod.YtDlpManager(
        {"dashboard_url": "http://dash.example.com"},
        http_open=_dashboard({"min_ytdlp_version": "2000.01.01"}, calls=asked),
        github_open=_release(b"x"),
        run_fn=world.run,
    )
    status = mgr.ensure(min_version="2026.08.10")
    assert asked == []
    assert status["action"] == ytdlp_mod.ACTION_UPDATED


def test_ensure_does_nothing_at_all_when_local_downloads_are_off(tools):
    world = _World(installed=None)
    mgr = _manager(world, cfg={"ytdl_local_downloads": False})
    mgr.install = lambda: pytest.fail("install() with the feature switched off")

    status = mgr.ensure()
    assert status["action"] == ytdlp_mod.ACTION_DISABLED
    assert status["ok"] is False
    assert world.argvs == [], "the binary must not even be probed"
    assert not tools.exists(), "nothing may be created on an opted-out machine"


def test_ensure_with_an_override_only_checks_the_version(tmp_path):
    """An editor who manages their own yt-dlp must not have it overwritten --
    no install, and no `-U` against a binary brew (or they) own."""
    mine = tmp_path / "mine" / "yt-dlp"
    mine.parent.mkdir(parents=True)
    mine.write_text("x")

    world = _World(installed=None)          # nothing at the MANAGED path

    def run(argv, timeout):
        world.argvs.append(list(argv))
        assert argv[0] == str(mine)
        return _Proc(0, "2026.08.11\n")

    mgr = ytdlp_mod.YtDlpManager(
        {"dashboard_url": "http://d", "ytdlp_path": str(mine)},
        http_open=_dashboard({"min_ytdlp_version": "2026.08.10"}),
        github_open=_release(b"x"),
        run_fn=run,
    )
    mgr.install = lambda: pytest.fail("install() over a hand-managed yt-dlp")

    status = mgr.ensure()
    assert status["action"] == ytdlp_mod.ACTION_CHECKED
    assert status["ok"] is True
    assert status["version"] == "2026.08.11"
    assert [argv[1:] for argv in world.argvs] == [["--version"]]


def test_ensure_with_a_stale_override_says_so_and_still_touches_nothing(tmp_path):
    mine = tmp_path / "mine-yt-dlp"
    mine.write_text("x")

    def run(argv, timeout):
        assert argv[1:] == ["--version"], "an override must never be handed -U"
        return _Proc(0, "2020.01.01\n")

    mgr = ytdlp_mod.YtDlpManager(
        {"dashboard_url": "http://d", "ytdlp_path": str(mine)},
        http_open=_dashboard({"min_ytdlp_version": "2026.08.10"}),
        github_open=_release(b"x"),
        run_fn=run,
    )
    mgr.install = lambda: pytest.fail("install() over a hand-managed yt-dlp")
    status = mgr.ensure()
    assert status["action"] == ytdlp_mod.ACTION_CHECKED
    assert status["ok"] is False
    assert status["version"] == "2020.01.01"
    # The message has to name what the editor must do themselves -- nothing
    # else is going to fix a binary the companion is forbidden to touch.
    assert "clear ytdlp_path" in status["message"]


def test_ensure_with_an_override_that_is_not_there(tmp_path):
    mgr = ytdlp_mod.YtDlpManager(
        {"dashboard_url": "", "ytdlp_path": str(tmp_path / "absent")},
        github_open=_release(b"x"),
        run_fn=lambda argv, timeout: pytest.fail("nothing to run"),
    )
    mgr.install = lambda: pytest.fail("install() over a hand-managed yt-dlp")
    status = mgr.ensure()
    assert status["action"] == ytdlp_mod.ACTION_CHECKED
    assert status["ok"] is False


def test_ensure_never_raises_even_when_everything_is_broken(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("the world is on fire")

    mgr = ytdlp_mod.YtDlpManager({"dashboard_url": "http://d"},
                                 http_open=boom, github_open=boom, run_fn=boom)
    status = mgr.ensure()
    assert status["ok"] is False
    assert status["action"] == ytdlp_mod.ACTION_FAILED


def test_status_is_cached_and_does_no_io():
    world = _World(installed="2026.08.11")
    mgr = _manager(world, min_version="2026.08.10")
    assert mgr.status()["action"] is None            # nothing checked yet
    mgr.ensure()
    before = len(world.argvs)
    assert mgr.status()["version"] == "2026.08.11"
    assert len(world.argvs) == before, "status() must not spawn anything"


# ---------------------------------------------------------------------------
# scheduling
# ---------------------------------------------------------------------------


def test_start_runs_ensure_on_its_own_thread_and_stop_ends_it(monkeypatch):
    monkeypatch.setattr(ytdlp_mod, "INITIAL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(ytdlp_mod, "CHECK_INTERVAL_SECONDS", 0.05)
    ran = threading.Event()
    calls = []

    mgr = ytdlp_mod.YtDlpManager({"dashboard_url": ""})

    def fake_ensure(min_version=None):
        calls.append(1)
        ran.set()
        return {"ok": True, "version": "2026.08.11", "action": "none", "message": "ok"}

    mgr.ensure = fake_ensure
    mgr.start()
    try:
        assert ran.wait(5), "the sidecar thread never ran ensure()"
        assert any(t.name == "ccsync-ytdlp" for t in threading.enumerate())
    finally:
        mgr.stop()
        mgr.join(timeout=5)
    assert calls, "ensure() must run at startup, not only on the daily tick"


def test_the_thread_survives_an_ensure_that_raises(monkeypatch, caplog):
    monkeypatch.setattr(ytdlp_mod, "INITIAL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(ytdlp_mod, "CHECK_INTERVAL_SECONDS", 0.01)
    seen = []
    done = threading.Event()

    mgr = ytdlp_mod.YtDlpManager({})

    def angry_ensure(min_version=None):
        seen.append(1)
        if len(seen) >= 2:
            done.set()
        raise RuntimeError("boom")

    mgr.ensure = angry_ensure

    # _loop() also runs sidecar_tools.ensure() every tick (ffmpeg + deno,
    # 2026-08-16), UNMOCKED here until this fix -- and conftest's autouse
    # _youtube_feature_enabled fixture turns both youtube_download AND
    # youtube_unblock "on" for every companion test, so that real call went
    # looking for a real ffmpeg/ffprobe/deno, found none in the isolated
    # tools dir, and tried to actually reach GitHub to install them. That is
    # real, variable-latency network I/O sitting BETWEEN the two angry_ensure()
    # calls this test needs to see -- on a slow/degraded runner (observed on
    # macos-latest) it alone can exceed the 5 s below, which is what made this
    # test flake: `done` was never a timing problem, the thread was just stuck
    # in a real network call the test never intended to make. Stubbing this
    # out is the actual fix; the wait below is a generous ceiling on top of a
    # loop body that no longer does any real I/O, not a race against one.
    monkeypatch.setattr(sidecar_tools, "ensure",
                        lambda *a, **kw: {"ok": True, "action": "none",
                                          "message": "stubbed for this test"})

    with caplog.at_level(logging.ERROR, logger="ccsync.ytdlp"):
        mgr.start()
        try:
            assert done.wait(5), "one bad check must not end the daily thread"
        finally:
            mgr.stop()
            mgr.join(timeout=5)


def test_start_with_the_feature_off_starts_no_thread(caplog):
    before = {t.name for t in threading.enumerate()}
    mgr = ytdlp_mod.YtDlpManager({"ytdl_local_downloads": False})
    with caplog.at_level(logging.INFO, logger="ccsync.ytdlp"):
        mgr.start()
    try:
        assert "ccsync-ytdlp" not in {t.name for t in threading.enumerate()} - before
        assert any("disabled" in r.getMessage() for r in caplog.records)
    finally:
        mgr.stop()


def test_start_is_idempotent(monkeypatch):
    monkeypatch.setattr(ytdlp_mod, "INITIAL_DELAY_SECONDS", 5.0)
    mgr = ytdlp_mod.YtDlpManager({})
    mgr.start()
    try:
        first = mgr._thread
        mgr.start()
        assert mgr._thread is first
    finally:
        mgr.stop()
        mgr.join(timeout=5)


# ---------------------------------------------------------------------------
# CompanionApp wiring
# ---------------------------------------------------------------------------


@pytest.fixture
def inert_resolve(monkeypatch):
    """No test here may reach a real Resolve (test_broll_wiring's fixture)."""
    empty = {"ok": False, "message": "no Resolve in tests", "items": [], "project_name": ""}
    monkeypatch.setattr(resolve_bridge, "get_timeline_items", lambda *a, **kw: dict(empty))
    monkeypatch.setattr(resolve_bridge, "poll_timeline_items", lambda: dict(empty))
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items", lambda: dict(empty))
    monkeypatch.setattr(resolve_bridge, "try_connect", lambda: False)


def _app(cfg_overrides: dict, tmp_path):
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
        "broll_server_enabled": False,
        "poll_interval": 0.2,
    })
    cfg.update(cfg_overrides)
    return app_mod.CompanionApp(cfg)


def test_app_start_brings_the_sidecar_up_and_shutdown_takes_it_down(
    tmp_path, inert_resolve, monkeypatch
):
    monkeypatch.setattr(ytdlp_mod, "INITIAL_DELAY_SECONDS", 30.0)   # never fires here
    app = _app({}, tmp_path)
    assert app.ytdlp is not None
    app.start()
    try:
        assert any(t.name == "ccsync-ytdlp" for t in threading.enumerate())
    finally:
        app.shutdown()
    assert app.ytdlp._stop_event.is_set()


def test_app_start_with_local_downloads_off_starts_no_sidecar_thread(
    tmp_path, inert_resolve
):
    before = {t.name for t in threading.enumerate()}
    app = _app({"ytdl_local_downloads": False}, tmp_path)
    app.start()
    try:
        assert "ccsync-ytdlp" not in {t.name for t in threading.enumerate()} - before
    finally:
        app.shutdown()


def test_app_startup_survives_a_sidecar_that_cannot_start(tmp_path, inert_resolve, caplog):
    """THE hard requirement, the b-roll server's rule applied here: a yt-dlp
    manager that explodes costs a log line, not a companion."""
    app = _app({}, tmp_path)

    def boom():
        raise RuntimeError("no tools dir, no network, no nothing")

    app.ytdlp.start = boom
    try:
        with caplog.at_level(logging.ERROR, logger="ccsync"):
            app.start()
        assert app._watcher_thread is not None and app._watcher_thread.is_alive()
        assert any("yt-dlp" in r.getMessage() for r in caplog.records)
    finally:
        app.shutdown()


def test_the_ytdlp_keys_are_never_a_config_problem(tmp_path):
    """validate_config's error list STOPS every sync lane (DEL-3). A typo in a
    downloader knob must never reach it."""
    from ccsync_companion import config as config_mod

    errors, _warnings = config_mod.validate_config({
        "editor_name": "editor2",
        "local_root": str(tmp_path),
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/TheCreatorsPool/Creators_Club",
        "active_project": "Projects/2026/X",
        "ytdl_local_downloads": "sure",
        "ytdlp_path": 5,
    })
    assert errors == []
