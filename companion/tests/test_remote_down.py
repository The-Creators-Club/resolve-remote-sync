"""`remote_down`: the download route (2026-09-25 trial, docs/CONFIG.md).

Lane B, and every other path that only COPIES the tree down to this machine,
may read through a second rclone remote (a read-only WebDAV server behind a
Cloudflare tunnel). Everything that writes keeps `remote`. Three things are
pinned here:

1. ROUTING: blank means `remote`, exactly; lane A never takes the route; lane
   B, its pre-flight and root probes, the structure clone, consolidate's lane
   B preview and the on-demand fetch do.
2. FAIL-SAFE: a route that is unreachable, refuses the password, or answers
   with a page that lists as EMPTY parks lane B (paused, never error, never a
   delete). Plain http to a public host is refused (LG-4) and `remote` used.
3. THE REAL THING: the lane's own argv, through the real rclone, against a
   real `rclone serve webdav --read-only` on 127.0.0.1 -- and a second pass
   moves nothing, so the size/modtime compare holds across WebDAV. Skips
   cleanly without an rclone binary (conftest's `rclone_binary`).
"""

from __future__ import annotations

import http.server
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from ccsync_companion.sync import rclone_lane as rl
from ccsync_companion.sync import lane_guard
from ccsync_companion.sync.base import STATE_ERROR, STATE_IDLE, STATE_PAUSED
from ccsync_companion.sync.rclone_lane import (
    DIRECTION_DOWN,
    DIRECTION_UP,
    REMOTE_DOWN_FLAGS,
    VIA_REMOTE,
    VIA_REMOTE_DOWN,
    RcloneLane,
    down_route,
)

_REAL_CONFIG_DUMP = rl._default_config_dump

# What `rclone config dump` answers in every test that does not run the real
# binary: the SFTP remote the fleet has, and a download route over https.
_DUMP = {
    "ccsync_sftp": {"type": "sftp", "host": "100.64.0.9"},
    "ccsync_dl": {"type": "webdav", "url": "https://dl.example.com", "vendor": "rclone"},
}


@pytest.fixture(autouse=True)
def _no_real_rclone_config(monkeypatch):
    """Never read the developer's own rclone.conf: the route check would
    otherwise run `rclone config dump` against it."""
    rl.reset_route_cache()
    monkeypatch.setattr(rl, "_default_config_dump", lambda path, timeout: dict(_DUMP))
    for key in list(os.environ):
        if key.startswith("RCLONE_CONFIG_CCSYNC_"):
            monkeypatch.delenv(key, raising=False)
    yield
    rl.reset_route_cache()


def _cfg(**over: Any) -> dict[str, Any]:
    cfg = {
        "remote": "ccsync_sftp",
        "remote_root": "/mnt/tank/Creators_Club",
        "rclone_path": "rclone",
    }
    cfg.update(over)
    return cfg


# -- 1. routing ---------------------------------------------------------------


def test_blank_remote_down_is_todays_route_exactly():
    for blank in ("", "   ", None):
        route = down_route(_cfg(remote_down=blank, remote_down_root="/ignored"))
        assert (route.remote, route.remote_root, route.via) == (
            "ccsync_sftp", "/mnt/tank/Creators_Club", VIA_REMOTE)
    assert down_route(_cfg()).via == VIA_REMOTE  # key absent altogether


def test_remote_down_takes_its_own_root_and_blank_root_means_remote_root():
    route = down_route(_cfg(remote_down="ccsync_dl", remote_down_root="/"))
    assert (route.remote, route.remote_root, route.via) == ("ccsync_dl", "/", VIA_REMOTE_DOWN)
    route = down_route(_cfg(remote_down="ccsync_dl", remote_down_root=""))
    assert route.remote_root == "/mnt/tank/Creators_Club"
    # every caller appends its own colon
    assert down_route(_cfg(remote_down="ccsync_dl:", remote_down_root="/")).remote == "ccsync_dl"


def test_the_down_command_carries_the_route_flags_only_through_the_route(tmp_path):
    ff = rl.write_filter_file(rl.build_filter_rules_down(), tmp_path / "f.txt")
    plain = rl.build_down_command("rclone", str(tmp_path), "ccsync_sftp", "/mnt/x", ff,
                                  subpath="Projects/a")
    routed = rl.build_down_command("rclone", str(tmp_path), "ccsync_dl", "/", ff,
                                   subpath="Projects/a", via=VIA_REMOTE_DOWN)
    for flag in ("--disable-http2", "--multi-thread-streams", "--multi-thread-cutoff"):
        assert flag not in plain
    for flag in REMOTE_DOWN_FLAGS:
        assert flag in routed
    assert routed[2] == "ccsync_dl:Projects/a"
    # the gates, delete caps and trash are the same whichever way bytes come
    strip = lambda cmd: [a for a in cmd[4:] if a not in REMOTE_DOWN_FLAGS]  # noqa: E731
    assert strip(plain) == strip(routed)


def _lane(tmp_path, direction, cfg, entries=("Proxy",), listed=None, popen_calls=None,
          with_route=True):
    (tmp_path / "local").mkdir(parents=True, exist_ok=True)

    def remote_list(cmd, timeout):
        if listed is not None:
            listed.append(cmd)
        if entries is None:
            return None
        return "\n".join(entries)

    calls = popen_calls if popen_calls is not None else []

    class _Proc:
        stderr = iter([])

        def wait(self, timeout=None):
            return 0

    def factory(cmd, **kwargs):
        calls.append(cmd)
        return _Proc()

    return RcloneLane(
        direction=direction,
        local_root=str(tmp_path / "local"),
        remote=cfg["remote"],
        remote_root=cfg["remote_root"],
        state_dir=tmp_path / "state",
        cfg=cfg,
        remote_list_fn=remote_list,
        popen_factory=factory,
        route_fn=(lambda: down_route(cfg)) if with_route else None,
    )


@pytest.fixture
def _rclone_is_there(monkeypatch):
    monkeypatch.setattr(rl, "rclone_available", lambda path: (True, path))


def test_lane_a_never_uses_remote_down_even_when_handed_a_route(tmp_path, _rclone_is_there):
    cfg = _cfg(remote_down="ccsync_dl", remote_down_root="/")
    calls: list[list[str]] = []
    lane = _lane(tmp_path, DIRECTION_UP, cfg, popen_calls=calls)
    (tmp_path / "local" / "Projects" / "a").mkdir(parents=True)
    lane.run_once("Projects/a")
    assert calls, "lane A should have run"
    joined = " ".join(calls[0])
    assert "ccsync_sftp:/mnt/tank/Creators_Club/Projects/a" in joined
    assert "ccsync_dl" not in joined and "--disable-http2" not in joined
    assert lane.remote == "ccsync_sftp"


def test_lane_b_downloads_through_remote_down(tmp_path, _rclone_is_there):
    cfg = _cfg(remote_down="ccsync_dl", remote_down_root="/")
    calls: list[list[str]] = []
    listed: list[list[str]] = []
    lane = _lane(tmp_path, DIRECTION_DOWN, cfg, listed=listed, popen_calls=calls)
    assert lane.via is None, "no pass yet: the report must not guess"
    status = lane.run_once("Projects/a")
    assert status.state == STATE_IDLE
    assert calls and calls[0][1] == "sync"
    assert calls[0][2] == "ccsync_dl:Projects/a"
    assert "--disable-http2" in calls[0]
    assert lane.via == VIA_REMOTE_DOWN
    # The breaker's pre-flight listed the SAME remote the pass synced from.
    assert listed and all(cmd[-1].startswith("ccsync_dl:") for cmd in listed)


def test_lane_b_with_blank_remote_down_is_unchanged(tmp_path, _rclone_is_there):
    cfg = _cfg(remote_down="")
    calls: list[list[str]] = []
    listed: list[list[str]] = []
    routed = _lane(tmp_path / "r", DIRECTION_DOWN, cfg, listed=listed, popen_calls=calls)
    routed.run_once("Projects/a")
    plain_calls: list[list[str]] = []
    plain = _lane(tmp_path / "p", DIRECTION_DOWN, cfg, popen_calls=plain_calls,
                  with_route=False)
    plain.run_once("Projects/a")
    assert calls[0][2] == plain_calls[0][2] == "ccsync_sftp:/mnt/tank/Creators_Club/Projects/a"
    assert "--disable-http2" not in calls[0]
    assert routed.via == VIA_REMOTE
    assert listed[0][-1] == "ccsync_sftp:/mnt/tank/Creators_Club/Projects/a"


def test_the_root_marker_probe_reads_through_the_route(tmp_path, _rclone_is_there):
    cfg = _cfg(remote_down="ccsync_dl", remote_down_root="/")
    listed: list[list[str]] = []
    lane = _lane(tmp_path, DIRECTION_DOWN, cfg, entries=["Projects", "Assets"], listed=listed)
    assert lane.check_remote_root() is True
    assert listed[-1][-1] == "ccsync_dl:"
    # ...and a tunnel serving the wrong folder is caught by it.
    rl.reset_route_cache()
    listed.clear()
    lane2 = _lane(tmp_path / "2", DIRECTION_DOWN, cfg, entries=["homes"], listed=listed)
    assert lane2.check_remote_root() is False
    assert lane2.breaker.tripped


def test_the_structure_clone_reads_through_the_route(tmp_path):
    from test_sequencer import FakeAdmin, FakeLane, FakeSelectionClient
    from test_sequencer import _cfg as seq_cfg

    from ccsync_companion.sync.sequencer import Sequencer

    root = tmp_path / "mounted"
    root.mkdir()
    for over, expected in (
        ({"remote_down": "ccsync_dl", "remote_down_root": "/"}, ("ccsync_dl", "/")),
        ({"remote_down": ""}, None),
    ):
        calls: list[dict] = []
        admin = FakeAdmin()
        cfg = seq_cfg(local_root=str(root))
        cfg.update(over)
        seq = Sequencer(
            FakeLane("lane_a", admin.events), FakeLane("lane_b", admin.events),
            admin, FakeSelectionClient([]), cfg,
            folder_status_poll_seconds=0.02,
            clone_tree_fn=lambda **kwargs: calls.append(kwargs) or 0,
        )
        seq._clone_structure("Projects/2026/FF5/Alpha")
        got = (calls[0]["remote"], calls[0]["remote_root"])
        assert got == (expected or (str(cfg.get("remote", "")), str(cfg.get("remote_root", ""))))


def test_consolidate_previews_lane_b_through_the_route_and_uploads_through_remote(tmp_path):
    from ccsync_companion import consolidate

    cfg = _cfg(local_root=str(tmp_path), remote_down="ccsync_dl", remote_down_root="/")
    ff = rl.write_filter_file(rl.build_filter_rules_down(), tmp_path / "f.txt")
    down = consolidate._dry_run_command(DIRECTION_DOWN, cfg, "Projects/a", ff)
    up = consolidate._dry_run_command(DIRECTION_UP, cfg, "Projects/a", ff)
    assert down[2] == "ccsync_dl:Projects/a" and "--disable-http2" in down
    assert up[3] == "ccsync_sftp:/mnt/tank/Creators_Club/Projects/a"
    assert "ccsync_dl" not in " ".join(up)


def test_the_on_demand_fetch_reads_through_the_route():
    from ccsync_companion import broll_fetch

    routed = broll_fetch.build_fetch_command(
        _cfg(remote_down="ccsync_dl", remote_down_root="/"), "clip.mov", "C:/t/clip.mov")
    assert routed[2] == "ccsync_dl:/Assets/B-roll Archive/clip.mov"
    assert "--disable-http2" in routed
    plain = broll_fetch.build_fetch_command(_cfg(), "clip.mov", "C:/t/clip.mov")
    assert plain[2] == "ccsync_sftp:/mnt/tank/Creators_Club/Assets/B-roll Archive/clip.mov"
    assert "--disable-http2" not in plain


def test_uploads_never_use_the_route():
    from ccsync_companion import broll_upload

    spec = broll_upload._remote_spec(
        _cfg(remote_down="ccsync_dl", remote_down_root="/"), "x/clip.mov")
    assert spec.startswith("ccsync_sftp:/mnt/tank/Creators_Club/")


def test_the_app_gives_the_route_to_lane_b_only(tmp_path):
    from ccsync_companion.app import CompanionApp

    root = tmp_path / "root"
    (root / "Projects" / "a").mkdir(parents=True)
    app = CompanionApp({
        "editor_name": "ruskin", "local_root": str(root), "canonical_prefix": "P:\\",
        "remote": "ccsync_sftp", "remote_root": "/mnt/tank/Creators_Club",
        "remote_down": "ccsync_dl", "remote_down_root": "/",
        "active_project": "", "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "", "popup_enabled": False,
        "sync_enabled": False, "lane_b_enabled": False,
    })
    assert app._lane_a._route_fn is None
    assert "ccsync_sftp:/mnt/tank/Creators_Club/Projects/a" in app._lane_a._build_command("Projects/a")
    assert app.lane_b_via() is None  # no pass yet: the key is omitted
    app._lane_b._apply_route()
    assert app._lane_b._build_command("Projects/a")[2] == "ccsync_dl:Projects/a"
    assert app.lane_b_via() == VIA_REMOTE_DOWN


def test_the_report_carries_lane_b_via_only_when_there_is_one():
    from ccsync_companion.reporter import DashboardReporter

    cfg = {"editor_name": "ruskin", "dashboard_url": "http://dash.example.com"}
    for value, expected in (("remote_down", "remote_down"), ("remote", "remote"),
                            (None, None), ("garbage", None)):
        rep = DashboardReporter(lambda: [], cfg, get_lane_b_via=lambda v=value: v)
        payload = rep._build_payload(editor_name="ruskin")
        assert payload.get("lane_b_via") == expected
        assert ("lane_b_via" in payload) is (expected is not None)
    boom = DashboardReporter(lambda: [], cfg, get_lane_b_via=lambda: 1 / 0)
    assert "lane_b_via" not in boom._build_payload(editor_name="ruskin")
    assert "lane_b_via" not in DashboardReporter(lambda: [], cfg)._build_payload(
        editor_name="ruskin")


# -- 2. fail-safe ---------------------------------------------------------------


def _seed_local_proxies(tmp_path, scope="Projects/a", n=3) -> Path:
    proxy = tmp_path / "local" / Path(*scope.split("/")) / "Proxy"
    proxy.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (proxy / f"p{i}.mov").write_bytes(b"x" * 10)
    return proxy


def test_an_unreachable_route_parks_lane_b_and_runs_nothing(tmp_path, _rclone_is_there):
    cfg = _cfg(remote_down="ccsync_dl", remote_down_root="/")
    calls: list[list[str]] = []
    lane = _lane(tmp_path, DIRECTION_DOWN, cfg, entries=None, popen_calls=calls)
    proxy = _seed_local_proxies(tmp_path)
    status = lane.run_once("Projects/a")
    assert calls == [], "nothing may run against a route that did not answer"
    assert status.state == STATE_PAUSED and status.state != STATE_ERROR
    assert status.detail.startswith("NOT DOWNLOADING (route)")
    assert "remote_down" not in status.detail, "the editor's sentence names no config key"
    assert status.last_error is None
    assert not lane.breaker.tripped, "a route outage clears by itself; no latch"
    assert len(list(proxy.iterdir())) == 3
    # ...and it comes back by itself.
    lane2 = _lane(tmp_path, DIRECTION_DOWN, cfg, entries=["Proxy"], popen_calls=calls)
    assert lane2.run_once("Projects/a").state == STATE_IDLE and calls


def test_an_empty_listing_over_local_proxies_parks_even_with_no_baseline(tmp_path,
                                                                          _rclone_is_there):
    """The sign-in-page case: a 200 that is not WebDAV lists as EMPTY, exit 0.
    The breaker has no count for this scope (first pass / just resumed)."""
    cfg = _cfg(remote_down="ccsync_dl", remote_down_root="/")
    calls: list[list[str]] = []
    lane = _lane(tmp_path, DIRECTION_DOWN, cfg, entries=[], popen_calls=calls)
    proxy = _seed_local_proxies(tmp_path)
    status = lane.run_once("Projects/a")
    assert calls == []
    assert status.state == STATE_PAUSED
    assert "as empty" in status.detail
    assert not lane.breaker.tripped
    assert len(list(proxy.iterdir())) == 3


def test_an_empty_listing_with_nothing_local_is_not_a_park(tmp_path, _rclone_is_there):
    cfg = _cfg(remote_down="ccsync_dl", remote_down_root="/")
    calls: list[list[str]] = []
    lane = _lane(tmp_path, DIRECTION_DOWN, cfg, entries=[], popen_calls=calls)
    assert lane.run_once("Projects/new").state == STATE_IDLE
    assert calls


def test_an_empty_listing_after_a_populated_one_still_trips_the_breaker(tmp_path,
                                                                         _rclone_is_there):
    cfg = _cfg(remote_down="ccsync_dl", remote_down_root="/")
    lane = _lane(tmp_path, DIRECTION_DOWN, cfg, entries=[])
    lane.breaker.check_remote("Projects/a", ["Proxy", "Footage"])
    status = lane.run_once("Projects/a")
    assert status.state == STATE_PAUSED
    assert lane.breaker.tripped  # the existing rule still fires first


def test_the_sftp_route_keeps_its_old_failed_listing_behaviour(tmp_path, _rclone_is_there):
    """No remote_down: a failed listing is left to fail the pass, as before."""
    calls: list[list[str]] = []
    lane = _lane(tmp_path, DIRECTION_DOWN, _cfg(), entries=None, popen_calls=calls)
    lane.run_once("Projects/a")
    assert calls, "today's behaviour: the pass runs and fails on its own"


def test_a_route_fn_that_raises_keeps_the_lane_on_remote(tmp_path, _rclone_is_there):
    calls: list[list[str]] = []
    lane = _lane(tmp_path, DIRECTION_DOWN, _cfg(), popen_calls=calls)
    lane._route_fn = lambda: 1 / 0
    lane.run_once("Projects/a")
    assert calls[0][2].startswith("ccsync_sftp:")
    assert lane.via == VIA_REMOTE


# -- LG-4: no cleartext to a public host -----------------------------------------


@pytest.mark.parametrize("url, refused", [
    ("https://dl.example.com", False),
    ("http://192.168.0.10:8080", False),      # studio LAN
    ("http://100.71.216.3:8080", False),      # tailnet
    ("http://127.0.0.1:18765", False),        # loopback (the tests below)
    ("http://8.8.8.8", True),                 # public IP literal
])
def test_plain_http_to_a_public_host_is_refused(monkeypatch, url, refused):
    monkeypatch.setattr(rl, "_default_config_dump",
                        lambda p, t: {"ccsync_dl": {"type": "webdav", "url": url}})
    route = down_route(_cfg(remote_down="ccsync_dl", remote_down_root="/"))
    if refused:
        assert route.via == VIA_REMOTE and route.remote == "ccsync_sftp"
        assert route.remote_root == "/mnt/tank/Creators_Club"
        assert "http" in route.refused
    else:
        assert route.via == VIA_REMOTE_DOWN and not route.refused


def test_an_env_override_of_the_url_is_checked_too(monkeypatch):
    monkeypatch.setenv("RCLONE_CONFIG_CCSYNC_DL_URL", "http://8.8.8.8")
    assert down_route(_cfg(remote_down="ccsync_dl")).via == VIA_REMOTE


def test_an_inline_connection_string_is_checked_without_reading_the_config(monkeypatch):
    def no_dump(*a):
        raise AssertionError("the url is in the string; no config read needed")
    monkeypatch.setattr(rl, "_default_config_dump", no_dump)
    bad = down_route(_cfg(remote_down=":webdav,url='http://8.8.8.8',vendor=rclone"))
    assert bad.via == VIA_REMOTE
    good = down_route(_cfg(remote_down=":webdav,url='https://dl.example.com'",
                           remote_down_root="/"))
    assert good.via == VIA_REMOTE_DOWN


def test_an_unreadable_rclone_config_fails_open(monkeypatch):
    """rclone reads the same file for the pass itself, so this sends nothing
    anywhere: the pass fails, and lane B parks on the failed listing."""
    monkeypatch.setattr(rl, "_default_config_dump", lambda p, t: None)
    assert down_route(_cfg(remote_down="ccsync_dl", remote_down_root="/")).via == VIA_REMOTE_DOWN


def test_a_refused_route_is_logged_once(monkeypatch, caplog):
    monkeypatch.setattr(rl, "_default_config_dump",
                        lambda p, t: {"ccsync_dl": {"type": "webdav", "url": "http://8.8.8.8"}})
    with caplog.at_level("WARNING", logger=rl.log.name):
        for _ in range(3):
            down_route(_cfg(remote_down="ccsync_dl"))
    assert sum("plain http" in r.getMessage() for r in caplog.records) == 1


def test_config_validation_warns_and_never_errors():
    from ccsync_companion import config as config_mod

    base = {"editor_name": "e", "local_root": ".", "remote": "ccsync_sftp",
            "remote_root": "/mnt/x"}
    errors, warnings = config_mod.validate_config({**base, "remote_down_root": "/"})
    assert any("remote_down_root is set but remote_down is blank" in w for w in warnings)
    errors2, warnings2 = config_mod.validate_config({**base, "remote_down": "ccsync_dl"})
    assert any('remote_down_root = "/"' in w for w in warnings2)
    assert errors == errors2 == [e for e in config_mod.validate_config(base)[0]]


# -- 3. the real rclone, against a real read-only WebDAV server --------------------

_PASSWORD = "trial-password"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_listening(port: int, proc=None, seconds: float = 20.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"server exited {proc.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"nothing listening on {port}")


def _obscure(rclone: str, text: str) -> str:
    out = subprocess.run([rclone, "obscure", text], capture_output=True, text=True,
                         timeout=30, creationflags=rl._win_creationflags())
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


class _PageHandler(http.server.BaseHTTPRequestHandler):
    """A 200 HTML page for every verb: what a sign-in or error page in front
    of the tunnel looks like to rclone."""

    def _page(self):
        body = b"<html><body>Sign in</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_HEAD = do_PROPFIND = do_OPTIONS = _page

    def log_message(self, *args):
        pass


@pytest.fixture
def webdav(rclone_binary, tmp_path, monkeypatch):
    """`rclone serve webdav <tree> --read-only` on 127.0.0.1, an rclone.conf
    with a good stanza and three bad ones, and RCLONE_CONFIG pointing at it.

    The server runs with the lane's own LOCAL_ENCODING so a Windows test host
    serves names the way the Linux NAS does (fullwidth punctuation verbatim),
    and the tree holds one such name on purpose."""
    tree = tmp_path / "served"
    proxy = tree / "Projects" / "2025" / "Proj" / "Proxy"
    proxy.mkdir(parents=True)
    (tree / "Projects" / "2025" / "Proj" / "Footage").mkdir()
    (tree / "Assets").mkdir()
    (proxy / "clip1.mov").write_bytes(os.urandom(300 * 1024 + 7))
    (proxy / "有完沒完？.mov").write_bytes(os.urandom(4096))
    (tree / "Projects" / "2025" / "Proj" / "Footage" / "orig.braw").write_bytes(b"o" * 99)
    old = time.time() - 3600  # past lane B's --min-age 120s
    for path in tree.rglob("*"):
        os.utime(path, (old, old))

    port = _free_port()
    server = subprocess.Popen(
        [rclone_binary, "serve", "webdav", str(tree), "--read-only",
         "--addr", f"127.0.0.1:{port}", "--user", "ccdl", "--pass", _PASSWORD,
         "--local-encoding", rl.LOCAL_ENCODING],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=rl._win_creationflags(),
    )
    page_port = _free_port()
    page = http.server.ThreadingHTTPServer(("127.0.0.1", page_port), _PageHandler)
    threading.Thread(target=page.serve_forever, daemon=True).start()
    try:
        _wait_listening(port, server)
        good = _obscure(rclone_binary, _PASSWORD)
        bad = _obscure(rclone_binary, "wrong")
        conf = tmp_path / "rclone.conf"
        conf.write_text(
            f"[ccsync_dl]\ntype = webdav\nurl = http://127.0.0.1:{port}\n"
            f"vendor = rclone\nuser = ccdl\npass = {good}\n\n"
            f"[ccsync_dl_badpw]\ntype = webdav\nurl = http://127.0.0.1:{port}\n"
            f"vendor = rclone\nuser = ccdl\npass = {bad}\n\n"
            f"[ccsync_dl_down]\ntype = webdav\nurl = http://127.0.0.1:{_free_port()}\n"
            f"vendor = rclone\nuser = ccdl\npass = {good}\n\n"
            f"[ccsync_dl_page]\ntype = webdav\nurl = http://127.0.0.1:{page_port}\n"
            f"vendor = rclone\nuser = ccdl\npass = {good}\n",
            encoding="utf-8")
        monkeypatch.setenv("RCLONE_CONFIG", str(conf))
        # These tests read THIS config for real, through the real binary.
        monkeypatch.setattr(rl, "_default_config_dump", _REAL_CONFIG_DUMP)
        rl.reset_route_cache()
        rl.reset_rclone_available_cache()
        yield {"tree": tree, "rclone": rclone_binary}
    finally:
        page.shutdown()
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


def _real_lane(tmp_path, webdav, remote_down: str, spawned: list):
    cfg = {
        "remote": "ccsync_sftp_not_used", "remote_root": "/mnt/tank/Creators_Club",
        "remote_down": remote_down, "remote_down_root": "/",
        "rclone_path": webdav["rclone"],
    }
    local = tmp_path / "local"
    local.mkdir(exist_ok=True)

    def spy(cmd, **kwargs):
        spawned.append(cmd)
        return subprocess.Popen(cmd, **kwargs)

    return RcloneLane(
        direction=DIRECTION_DOWN, local_root=str(local),
        remote=cfg["remote"], remote_root=cfg["remote_root"],
        rclone_path=webdav["rclone"], state_dir=tmp_path / "state", cfg=cfg,
        popen_factory=spy, route_fn=lambda: down_route(cfg),
    ), local


SCOPE = "Projects/2025/Proj"


def test_real_lane_b_round_trip_over_webdav_and_a_second_pass_moves_nothing(tmp_path, webdav):
    spawned: list[list[str]] = []
    lane, local = _real_lane(tmp_path, webdav, "ccsync_dl", spawned)

    first = lane.run_once(SCOPE)
    assert first.state == STATE_IDLE, (first.detail, first.last_error)
    assert lane.via == VIA_REMOTE_DOWN
    sync_cmds = [c for c in spawned if c[1] == "sync"]
    assert sync_cmds and sync_cmds[0][2] == f"ccsync_dl:{SCOPE}"
    # The whole production argv, SFTP window flags included, ran clean.
    for flag in (*REMOTE_DOWN_FLAGS, "--sftp-chunk-size", "--sftp-concurrency",
                 "--ignore-checksum", "--backup-dir", "--max-delete", "--min-age"):
        assert flag in sync_cmds[0]

    served = webdav["tree"] / "Projects" / "2025" / "Proj" / "Proxy"
    got = local / "Projects" / "2025" / "Proj" / "Proxy"
    for name in ("clip1.mov", "有完沒完？.mov"):
        assert (got / name).read_bytes() == (served / name).read_bytes(), name
    assert not (local / "Projects" / "2025" / "Proj" / "Footage" / "orig.braw").exists(), (
        "lane B's filter must hold over WebDAV: originals stay on the server")
    assert lane.last_run_moved() == 2

    second = lane.run_once(SCOPE)
    assert second.state == STATE_IDLE
    assert lane.last_run_moved() == 0, (
        "size/modtime must compare equal across WebDAV, or every pass re-downloads")
    assert len([c for c in spawned if c[1] == "sync"]) == 2


@pytest.mark.parametrize("remote_down, why", [
    ("ccsync_dl_badpw", "401: the server refuses the password"),
    ("ccsync_dl_down", "nothing listening: the tunnel is down"),
    ("ccsync_dl_page", "a 200 sign-in page: lists as EMPTY with exit 0"),
])
def test_real_route_failures_park_lane_b_and_touch_nothing(tmp_path, webdav, remote_down, why):
    spawned: list[list[str]] = []
    lane, local = _real_lane(tmp_path, webdav, remote_down, spawned)
    proxy = local / "Projects" / "2025" / "Proj" / "Proxy"
    proxy.mkdir(parents=True)
    for i in range(3):
        (proxy / f"mine{i}.mov").write_bytes(b"p" * 64)

    status = lane.run_once(SCOPE)

    assert status.state == STATE_PAUSED, (why, status.state, status.detail, status.last_error)
    assert status.detail.startswith("NOT DOWNLOADING (route)"), why
    assert [c for c in spawned if c[1] == "sync"] == [], f"{why}: rclone sync must not run"
    assert sorted(p.name for p in proxy.iterdir()) == ["mine0.mov", "mine1.mov", "mine2.mov"]
    assert not (local / lane_guard.TRASH_DIR_NAME).exists()
    assert not lane.breaker.tripped, f"{why}: a route problem is not a latched trip"


def test_real_rclone_proves_why_the_empty_guard_exists(tmp_path, webdav):
    """The hazard itself, measured: `rclone sync --dry-run` from the sign-in
    page plans to delete every local proxy. If a future rclone stops doing
    this, the guard is merely redundant -- never wrong."""
    local = tmp_path / "victim" / "Proxy"
    local.mkdir(parents=True)
    (local / "a.mov").write_bytes(b"x")
    ff = rl.write_filter_file(rl.build_filter_rules_down(), tmp_path / "f.txt")
    proc = subprocess.run(
        [webdav["rclone"], "sync", f"ccsync_dl_page:{SCOPE}", str(tmp_path / "victim"),
         "--filter-from", str(ff), "--dry-run", "--use-json-log"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        creationflags=rl._win_creationflags())
    assert proc.returncode == 0, proc.stderr
    assert "Skipped delete" in proc.stderr
