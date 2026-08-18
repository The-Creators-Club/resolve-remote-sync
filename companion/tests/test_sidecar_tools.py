"""The pinned sidecar tools (sidecar_tools.py: ffmpeg, ffprobe, deno) and the tools-dir fallback in
ffmpeg_tools that makes the rest of the companion see what it installs.

Same isolation as test_ytdlp_manager: LOCALAPPDATA is redirected so nothing
here can write into the developer's real %LOCALAPPDATA%\\ccsync\\tools, and
every "download" is a fake github_open serving gzip bytes built in the test.
No real ffmpeg is fetched or run.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import sys
import zipfile
from pathlib import Path
from typing import Optional

import pytest

from ccsync_companion import sidecar_tools as fm
from ccsync_companion import ffmpeg_tools
from ccsync_companion import ytdl_executor as ex
from ccsync_companion import ytdlp_manager as ytdlp_mod

from test_ytdl_executor import make_cfg, make_deps  # noqa: E402  (same suite)


@pytest.fixture(autouse=True)
def _isolate_tools_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    ffmpeg_tools.reset_ffmpeg_available_cache()


class _FakeResponse:
    def __init__(self, body: bytes):
        self._stream = io.BytesIO(body)

    def read(self, n=-1):
        return self._stream.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _gz(payload: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as fh:
        fh.write(payload)
    return buf.getvalue()


def _zip(member: str, payload: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member, payload)
    return buf.getvalue()


def _pin(monkeypatch, assets: dict[str, bytes], kinds: Optional[dict[str, str]] = None):
    """Pin THIS platform to fake assets: {tool: archive bytes} (gz unless
    `kinds` says zip). Returns the fake opener, which records the URLs it
    served."""
    kinds = kinds or {}
    table = {tool: (f"https://github.com/x/y/releases/download/t/{tool}-fake.{kinds.get(tool, 'gz')}",
                    hashlib.sha256(body).hexdigest(), kinds.get(tool, fm.KIND_GZ))
             for tool, body in assets.items()}
    monkeypatch.setattr(fm, "pinned_assets", lambda *a, **k: table)
    calls: list[str] = []

    def opener(url, headers, timeout):
        calls.append(url)
        for tool, (asset_url, _sha, _kind) in table.items():
            if asset_url == url:
                return _FakeResponse(assets[tool])
        raise AssertionError(f"unexpected download URL {url}")

    opener.calls = calls  # type: ignore[attr-defined]
    return opener


def _no_own_ffmpeg(monkeypatch):
    """The editor has no ffmpeg (or deno) of their own: which() finds nothing."""
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(fm.shutil, "which", lambda *_a, **_k: None)


def _both(extra: Optional[dict[str, bytes]] = None) -> dict[str, bytes]:
    """The trio every install test needs, plus whatever else."""
    d = {"ffmpeg": _gz(b"I am ffmpeg"), "ffprobe": _gz(b"I am ffprobe"),
         "deno": _zip(fm.binary_name("deno"), b"I am deno")}
    d.update(extra or {})
    return d


ZIP = {"deno": "zip"}


# ---------------------------------------------------------------------------
# the pin itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("plat,machine,expect", [
    ("win32", "AMD64", ("ffmpeg-win32-x64.gz", "ffprobe-win32-x64.gz",
                        "deno-x86_64-pc-windows-msvc.zip")),
    ("darwin", "arm64", ("ffmpeg-darwin-arm64.gz", "ffprobe-darwin-arm64.gz",
                         "deno-aarch64-apple-darwin.zip")),
    ("darwin", "x86_64", ("ffmpeg-darwin-x64.gz", "ffprobe-darwin-x64.gz",
                          "deno-x86_64-apple-darwin.zip")),
])
def test_every_editor_platform_has_a_pinned_trio(plat, machine, expect):
    table = fm.pinned_assets(plat, machine)
    assert table is not None
    assert tuple(table[t][0].rsplit("/", 1)[-1] for t in ("ffmpeg", "ffprobe", "deno")) == expect
    for url, sha, kind in table.values():
        assert url.startswith("https://github.com/")
        assert len(sha) == 64 and int(sha, 16)
        assert kind in (fm.KIND_GZ, fm.KIND_ZIP)
    assert table["deno"][2] == fm.KIND_ZIP and table["ffmpeg"][2] == fm.KIND_GZ


@pytest.mark.parametrize("plat,machine", [
    ("win32", "ARM64"),        # the source ships no winarm64
    ("linux", "x86_64"),       # the container is not an editor machine
    ("darwin", "ppc"),
])
def test_unpinned_platforms_get_none_not_a_guess(plat, machine):
    assert fm.pinned_assets(plat, machine) is None


def test_ensure_reports_unsupported_and_downloads_nothing(monkeypatch):
    _no_own_ffmpeg(monkeypatch)
    monkeypatch.setattr(fm, "pinned_assets", lambda *a, **k: None)

    def _boom(*a, **k):
        pytest.fail("downloaded on an unsupported platform")

    status = fm.ensure({"ytdl_local_downloads": True}, github_open=_boom)
    assert status["ok"] is False and status["action"] == fm.ACTION_UNSUPPORTED


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


def test_ensure_installs_all_three_verified_binaries_into_the_tools_dir(monkeypatch):
    _no_own_ffmpeg(monkeypatch)
    opener = _pin(monkeypatch, _both(), kinds=ZIP)

    status = fm.ensure({"ytdl_local_downloads": True}, github_open=opener)

    assert status["ok"] is True and status["action"] == fm.ACTION_INSTALLED
    assert fm.managed_path("ffmpeg").read_bytes() == b"I am ffmpeg"
    assert fm.managed_path("ffprobe").read_bytes() == b"I am ffprobe"
    assert fm.managed_path("deno").read_bytes() == b"I am deno", "the zip's one member"
    assert fm.managed_deno() == str(fm.managed_path("deno"))
    assert fm.managed_path("ffmpeg").parent == ytdlp_mod.tools_dir(), \
        "one tools dir, shared with yt-dlp"
    assert len(opener.calls) == 3
    # No debris: neither the archives nor the .new survive a clean install.
    leftovers = [p.name for p in ytdlp_mod.tools_dir().iterdir()
                 if p.name.endswith((".new", ".gz", ".zip"))]
    assert leftovers == []
    if sys.platform != "win32":
        assert os.access(fm.managed_path("ffmpeg"), os.X_OK)
        assert os.access(fm.managed_path("deno"), os.X_OK)


def test_a_zip_with_the_wrong_member_installs_nothing(monkeypatch):
    """Exactly the named member is read, never extractall: a zip missing it
    (or carrying ../ paths) fails closed."""
    _no_own_ffmpeg(monkeypatch)
    opener = _pin(monkeypatch, _both({"deno": _zip("../evil.exe", b"nope")}), kinds=ZIP)

    status = fm.ensure({"ytdl_local_downloads": True}, github_open=opener)

    assert status["ok"] is False and status["action"] == fm.ACTION_FAILED
    assert not fm.managed_path("deno").exists()
    assert not (ytdlp_mod.tools_dir().parent / "evil.exe").exists()
    assert fm.managed_path("ffmpeg").exists(), "the good ones still land"


def test_a_path_deno_is_left_alone(monkeypatch, tmp_path):
    """yt-dlp finds a PATH deno itself; ours would be 97 MB of duplicate."""
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(fm.shutil, "which",
                        lambda name, *a, **k: str(tmp_path / "deno") if name == "deno" else None)
    opener = _pin(monkeypatch, _both(), kinds=ZIP)

    fm.ensure({"ytdl_local_downloads": True}, github_open=opener)

    assert not fm.managed_path("deno").exists()
    assert fm.managed_path("ffmpeg").exists()
    assert fm.managed_deno() is None


def test_a_digest_that_is_not_the_pin_is_discarded_unread(monkeypatch):
    """The whole point of pinning: a swapped or corrupted asset never gets
    inflated, never gets a name ffmpeg_tools would find."""
    _no_own_ffmpeg(monkeypatch)
    opener = _pin(monkeypatch, _both({"ffmpeg": _gz(b"real")}), kinds=ZIP)
    # Serve DIFFERENT bytes than the ones the pin was computed from.
    table = fm.pinned_assets()
    table["ffmpeg"] = (table["ffmpeg"][0], hashlib.sha256(b"something else").hexdigest(),
                       fm.KIND_GZ)
    monkeypatch.setattr(fm, "pinned_assets", lambda *a, **k: table)

    status = fm.ensure({"ytdl_local_downloads": True}, github_open=opener)

    assert status["ok"] is False and status["action"] == fm.ACTION_FAILED
    assert not fm.managed_path("ffmpeg").exists()
    assert fm.managed_path("ffprobe").exists(), "the good ones still land"
    assert fm.managed_path("deno").exists()
    assert not (ytdlp_mod.tools_dir() / "ffmpeg-fake.gz.new").exists()


def test_a_second_ensure_touches_nothing(monkeypatch):
    _no_own_ffmpeg(monkeypatch)
    opener = _pin(monkeypatch, _both(), kinds=ZIP)
    fm.ensure({"ytdl_local_downloads": True}, github_open=opener)
    before = len(opener.calls)

    status = fm.ensure({"ytdl_local_downloads": True}, github_open=opener)

    assert status["action"] == fm.ACTION_NONE and status["ok"] is True
    assert len(opener.calls) == before


def test_only_the_missing_tool_is_fetched(monkeypatch):
    _no_own_ffmpeg(monkeypatch)
    opener = _pin(monkeypatch, _both(), kinds=ZIP)
    fm.ensure({"ytdl_local_downloads": True}, github_open=opener)
    fm.managed_path("ffprobe").unlink()
    opener.calls.clear()

    fm.ensure({"ytdl_local_downloads": True}, github_open=opener)

    assert [u.rsplit("/", 1)[-1] for u in opener.calls] == ["ffprobe-fake.gz"]


def test_the_opt_out_covers_ffmpeg_too(monkeypatch):
    def _boom(*a, **k):
        pytest.fail("downloaded with local downloads switched off")

    status = fm.ensure({"ytdl_local_downloads": False}, github_open=_boom)
    assert status["action"] == fm.ACTION_DISABLED


def test_an_editors_own_ffmpeg_is_left_alone_and_nothing_is_downloaded(monkeypatch, tmp_path):
    """`winget install Gyan.FFmpeg` / brew / an explicit ffmpeg_path: theirs
    wins, exactly as it always has, and we do not park 160 MB beside it."""
    own = tmp_path / "own" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    own.parent.mkdir()
    own.write_bytes(b"theirs")

    monkeypatch.setattr(fm.shutil, "which",
                        lambda name, *a, **k: str(tmp_path / "deno") if name == "deno" else None)

    def _boom(*a, **k):
        pytest.fail("downloaded over an editor's own ffmpeg")

    status = fm.ensure({"ytdl_local_downloads": True, "ffmpeg_path": str(own)},
                       github_open=_boom)
    assert status["ok"] is True and status["action"] == fm.ACTION_NONE
    assert not fm.managed_path("ffmpeg").exists()


def test_a_download_ceiling_breach_leaves_no_file(monkeypatch):
    _no_own_ffmpeg(monkeypatch)
    huge = _gz(b"x" * 1024)
    opener = _pin(monkeypatch, _both({"ffmpeg": huge}), kinds=ZIP)
    monkeypatch.setattr(fm, "MAX_DOWNLOAD_BYTES", 16)

    status = fm.ensure({"ytdl_local_downloads": True}, github_open=opener)

    assert status["ok"] is False
    assert not fm.managed_path("ffmpeg").exists()
    assert not any(p.name.startswith("ffmpeg-") or p.name == fm.binary_name("ffmpeg")
                   for p in ytdlp_mod.tools_dir().iterdir())


# ---------------------------------------------------------------------------
# what the rest of the companion sees
# ---------------------------------------------------------------------------


def test_ffmpeg_tools_falls_back_to_the_managed_binary_behind_path(monkeypatch):
    _no_own_ffmpeg(monkeypatch)
    assert ffmpeg_tools._resolve_binary("ffmpeg") is None, "nothing yet"

    fm.ensure({"ytdl_local_downloads": True},
              github_open=_pin(monkeypatch, _both(), kinds=ZIP))

    assert ffmpeg_tools._resolve_binary("ffmpeg") == str(fm.managed_path("ffmpeg"))
    assert ffmpeg_tools._resolve_binary("ffprobe") == str(fm.managed_path("ffprobe"))
    assert ffmpeg_tools.ffprobe_for("ffmpeg") == str(fm.managed_path("ffprobe")), \
        "the sibling lookup finds the managed ffprobe"


def test_path_still_wins_over_the_managed_binary(monkeypatch, tmp_path):
    own = tmp_path / "onpath" / "ffmpeg"
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda name, *a, **k: str(own))
    fm.managed_path("ffmpeg").parent.mkdir(parents=True)
    fm.managed_path("ffmpeg").write_bytes(b"ours")

    assert ffmpeg_tools._resolve_binary("ffmpeg") == str(own)


@pytest.mark.parametrize("name", ["/explicit/ffmpeg", "not-ffmpeg", "sub/ffmpeg"])
def test_only_the_bare_default_names_fall_back(monkeypatch, name):
    """An explicit path that is not there stays not-there: silently running a
    different binary than the one configured is the failure this must not
    introduce."""
    _no_own_ffmpeg(monkeypatch)
    fm.managed_path("ffmpeg").parent.mkdir(parents=True)
    fm.managed_path("ffmpeg").write_bytes(b"ours")

    assert ffmpeg_tools._resolve_binary(name) is None


def test_ffmpeg_available_sees_the_managed_binary(monkeypatch):
    """The proxy generator's probe -- the other consumer of a bare 'ffmpeg'."""
    _no_own_ffmpeg(monkeypatch)
    fm.managed_path("ffmpeg").parent.mkdir(parents=True)
    fm.managed_path("ffmpeg").write_bytes(b"ours")
    seen = {}

    class _P:
        returncode = 0

    def _run(argv, **kw):
        seen["argv"] = argv
        return _P()

    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", _run)
    ok, resolved = ffmpeg_tools.ffmpeg_available("ffmpeg", use_cache=False)
    assert ok is True and resolved == str(fm.managed_path("ffmpeg"))
    assert seen["argv"][0] == str(fm.managed_path("ffmpeg"))


def test_capabilities_turn_ok_the_moment_the_managed_ffmpeg_lands(tmp_path, monkeypatch):
    """The end-to-end reason this module exists: an editor's probe said
    REASON_NO_FFMPEG and every job took the server path. With the default
    bare `ffmpeg_path` and nothing on PATH, the same probe says yes once the
    daily thread has installed the pair -- no restart, no config edit."""
    _no_own_ffmpeg(monkeypatch)
    deps = make_deps(tmp_path, cfg=make_cfg(tmp_path, ffmpeg_path="ffmpeg"))
    assert ex.capabilities(deps)["reason"] == ex.REASON_NO_FFMPEG

    fm.ensure(deps.cfg, github_open=_pin(monkeypatch, _both(), kinds=ZIP))

    cap = ex.capabilities(deps)
    assert cap["ok"] is True and cap["reason"] is None
    assert ex._ffmpeg_location(deps.cfg) == str(ytdlp_mod.tools_dir()), \
        "and --ffmpeg-location will point at the tools dir"


def test_the_daily_loop_runs_the_sidecar_after_yt_dlp(monkeypatch):
    """One thread, one cadence, one opt-out (module docstring)."""
    order = []
    mgr = ytdlp_mod.YtDlpManager({"ytdl_local_downloads": True})
    monkeypatch.setattr(mgr, "ensure", lambda: order.append("ytdlp") or {"message": "m"})
    monkeypatch.setattr(fm, "ensure",
                        lambda cfg, github_open=None: order.append("sidecar") or {"message": "f"})
    monkeypatch.setattr(ytdlp_mod, "INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(ytdlp_mod, "CHECK_INTERVAL_SECONDS", 3600)
    # Let the loop run one iteration, then stop it via the wait.
    waits = iter([False, True])
    monkeypatch.setattr(mgr._stop_event, "wait", lambda t: next(waits))

    mgr._loop()

    assert order == ["ytdlp", "sidecar"]


def test_an_explicit_but_missing_ffmpeg_path_is_not_papered_over(monkeypatch, tmp_path):
    """An explicit path is the editor's decision either way. Absent, our copy
    would land somewhere the bare-name fallback never looks -- 160 MB nothing
    can use -- so nothing is downloaded and the honest answer stays
    capabilities()' REASON_NO_FFMPEG against the path they wrote."""
    _no_own_ffmpeg(monkeypatch)
    monkeypatch.setattr(fm.shutil, "which",
                        lambda name, *a, **k: str(tmp_path / "deno") if name == "deno" else None)

    def _boom(*a, **k):
        pytest.fail("downloaded for an explicit ffmpeg_path")

    status = fm.ensure({"ytdl_local_downloads": True,
                        "ffmpeg_path": str(tmp_path / "nowhere" / "ffmpeg")},
                       github_open=_boom)
    assert status["action"] == fm.ACTION_NONE
    assert not fm.managed_path("ffmpeg").exists()


# ---------------------------------------------------------------------------
# ensure_ffmpeg_pair -- the ungated half (2026-08-18, BROLL_INGEST_PLAN §3.3)
# ---------------------------------------------------------------------------
#
# ffmpeg was installed only where the site turned `youtube_download` on,
# because that was the only feature that needed one. B-roll ingest needs it on
# every editor machine that indexes a clip -- proxy, sprite, poster, scene
# detection and frame extraction are all ffmpeg -- and the proxy generator has
# always wanted one. A codec is not an entitlement. deno still is.


def test_the_ffmpeg_pair_installs_with_the_youtube_feature_off(monkeypatch):
    _no_own_ffmpeg(monkeypatch)
    opener = _pin(monkeypatch, _both(), kinds=ZIP)

    status = fm.ensure_ffmpeg_pair({"ytdl_local_downloads": False}, github_open=opener)

    assert status["ok"] is True and status["action"] == fm.ACTION_INSTALLED
    assert fm.managed_path("ffmpeg").read_bytes() == b"I am ffmpeg"
    assert fm.managed_path("ffprobe").read_bytes() == b"I am ffprobe"


def test_the_ffmpeg_pair_never_installs_deno(monkeypatch):
    """deno is the n-challenge solver, not a codec: it stays behind BOTH
    YouTube flags, and this function must never be the way it arrives."""
    _no_own_ffmpeg(monkeypatch)
    opener = _pin(monkeypatch, _both(), kinds=ZIP)

    fm.ensure_ffmpeg_pair({}, github_open=opener)

    assert [u.rsplit("/", 1)[-1] for u in opener.calls] == ["ffmpeg-fake.gz", "ffprobe-fake.gz"]
    assert not fm.managed_path("deno").exists()
    assert fm.managed_deno() is None


def test_the_ffmpeg_pair_leaves_an_editors_own_ffmpeg_alone(monkeypatch, tmp_path):
    own = tmp_path / "own" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    own.parent.mkdir()
    own.write_bytes(b"theirs")
    monkeypatch.setattr(fm.shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(ffmpeg_tools.shutil, "which",
                        lambda name, *a, **k: str(own) if name == "ffmpeg" else None)

    def _boom(*a, **k):
        pytest.fail("downloaded over the editor's own ffmpeg")

    status = fm.ensure_ffmpeg_pair({}, github_open=_boom)

    assert status["action"] == fm.ACTION_NONE and status["own_ffmpeg"] is True
    assert not fm.managed_path("ffmpeg").exists()


def test_the_ffmpeg_pair_reports_unsupported_and_downloads_nothing(monkeypatch):
    _no_own_ffmpeg(monkeypatch)
    monkeypatch.setattr(fm, "pinned_assets", lambda *a, **k: None)

    def _boom(*a, **k):
        pytest.fail("downloaded on an unsupported platform")

    status = fm.ensure_ffmpeg_pair({}, github_open=_boom)
    assert status["ok"] is False and status["action"] == fm.ACTION_UNSUPPORTED


def test_a_second_ffmpeg_pair_call_touches_nothing(monkeypatch):
    _no_own_ffmpeg(monkeypatch)
    opener = _pin(monkeypatch, _both(), kinds=ZIP)
    fm.ensure_ffmpeg_pair({}, github_open=opener)
    before = len(opener.calls)

    status = fm.ensure_ffmpeg_pair({}, github_open=opener)

    assert status["action"] == fm.ACTION_NONE and len(opener.calls) == before


def test_the_ffmpeg_pair_refuses_when_there_is_no_room(monkeypatch):
    _no_own_ffmpeg(monkeypatch)
    opener = _pin(monkeypatch, _both(), kinds=ZIP)
    monkeypatch.setattr(fm, "_free_space_ok", lambda d: False)

    status = fm.ensure_ffmpeg_pair({}, github_open=opener)

    assert status["ok"] is False and status["action"] == fm.ACTION_FAILED
    assert opener.calls == []


def test_ensure_still_gates_on_youtube_and_delegates_the_pair(monkeypatch):
    """The gated wrapper: with the downloader off it downloads NOTHING (not
    even the pair, which its own caller fetches directly); with it on, it
    installs through ensure_ffmpeg_pair and adds deno on top."""
    calls = []
    monkeypatch.setattr(fm, "ensure_ffmpeg_pair",
                        lambda *a, **kw: calls.append("pair") or {
                            "ok": True, "action": fm.ACTION_NONE, "own_ffmpeg": False,
                            "installed": [], "failed": [], "message": "x"})

    status = fm.ensure({"ytdl_local_downloads": False})
    assert status["action"] == fm.ACTION_DISABLED
    assert calls == []

    _no_own_ffmpeg(monkeypatch)
    monkeypatch.setattr(fm, "_unblock_enabled", lambda: False)
    status = fm.ensure({"ytdl_local_downloads": True})
    assert calls == ["pair"]
    assert status["action"] == fm.ACTION_NONE
