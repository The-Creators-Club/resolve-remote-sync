"""What the four optional mounts decided, and where a human can read it.

DDIAG-7 / BROLL-2 / MUSIC-10 / YTWEB-2 (usability + resilience sweep
2026-09-03). Each of /broll, /music, /ytdl and /cards computed a careful
tri-state with a sentence of reason, and that sentence went to the container
log and nowhere else: on the page the topbar link simply DISAPPEARED, so an
editor asking where B-ROLL had gone got no answer and the self-diagnosis
registry -- built precisely so that a diagnosis is not a log line nobody opens
-- had no kind for the four biggest refusals this dashboard makes at boot.

This file pins the plumbing that the notice writer (B4) and the alert checks
(B2) read: `mount_status.record`/`snapshot`, the `mounts` block on
/api/v1/health, and `ytdl.health_snapshot`.
"""
from __future__ import annotations

import sqlite3
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, broll, cards, mount_status, music, ytdl
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings
from test_music_mount import _build_fake_musicweb, no_musicweb  # noqa: F401

SECRET = "s" * 32


def _app(tmp_path, **kw):
    return create_app(Settings(db_path=str(tmp_path / "d.db"),
                               session_secret=SECRET, **kw))


def as_user(client, user="owen"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


@pytest.fixture
def music_env(tmp_path, monkeypatch):
    """test_music_mount.py's fixture: the fake musicweb, rooted in tmp_path."""
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "musicdata"))
    monkeypatch.setenv("MUSIC_ROOT", str(tmp_path / "library"))
    for name, module in _build_fake_musicweb().items():
        monkeypatch.setitem(sys.modules, name, module)
    return tmp_path


# ------------------------------------------------------------- the registry

def test_the_registry_records_and_snapshots():
    mount_status.reset()
    mount_status.record("broll", "degraded", "the data root is not writable")
    assert mount_status.snapshot() == {
        "broll": ("degraded", "the data root is not writable")}
    assert mount_status.get("broll") == ("degraded", "the data root is not writable")
    assert mount_status.get("music") is None


def test_a_snapshot_is_a_copy_not_the_live_dict():
    """The readers are on the collector thread and the ytdl feature gate
    rewrites its entry from a request thread."""
    mount_status.reset()
    mount_status.record("music", "mounted", "serving /music")
    snap = mount_status.snapshot()
    snap["music"] = ("absent", "tampered")
    assert mount_status.get("music") == ("mounted", "serving /music")


def test_recording_junk_never_raises():
    mount_status.reset()
    mount_status.record("cards", None, None)          # type: ignore[arg-type]
    assert mount_status.get("cards") == ("", "")


# ------------------------------------------------------------- at boot time

def test_every_mount_records_a_status_and_a_sentence(tmp_path, no_musicweb,  # noqa: F811
                                                     monkeypatch):
    import builtins

    app = _app(tmp_path)
    monkeypatch.setattr(builtins, "__import__", no_musicweb)

    snap = mount_status.snapshot()
    assert set(snap) == set(mount_status.NAMES)
    for name, (status, detail) in snap.items():
        assert status, name
        assert detail, f"{name} recorded no reason"


def test_an_absent_music_tree_says_why_on_app_state(tmp_path, no_musicweb,  # noqa: F811
                                                    monkeypatch):
    import builtins

    app = _app(tmp_path)
    monkeypatch.setattr(builtins, "__import__", no_musicweb)

    assert app.state.music_status == music.ABSENT
    assert "did not import" in app.state.music_detail
    assert mount_status.get("music") == (music.ABSENT, app.state.music_detail)


def test_a_degraded_music_mount_names_the_data_root(tmp_path, music_env, monkeypatch):
    def boom(path=None):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sys.modules["musicweb.db"], "connect", boom)
    app = _app(tmp_path)

    assert app.state.music_status == music.DEGRADED
    assert "DATA_ROOT" in app.state.music_detail
    assert "unable to open database file" in app.state.music_detail


def test_a_music_db_from_a_newer_app_is_degraded_at_boot_not_a_500_per_request(
        tmp_path, music_env, monkeypatch):
    """MUSIC-10's second half. `publish_db --which music` can land a database
    written by a newer musicweb; before this the mount reported MOUNTED, the
    nav went on offering the link, and every /music page 500'd."""
    def newer(con):
        raise RuntimeError(
            "FATAL: database at /music-data/music.db has user_version=9, newer "
            "than this app supports (max 7). Upgrade the web app before "
            "pointing it at this database.")

    monkeypatch.setattr(sys.modules["musicweb.db"], "init", newer)
    app = _app(tmp_path)

    assert app.state.music_status == music.DEGRADED
    assert app.state.music_mounted is False
    assert "newer version of the music app" in app.state.music_detail
    assert "user_version=9" in app.state.music_detail


def test_the_cards_detail_is_unchanged_by_the_new_plumbing(tmp_path, monkeypatch):
    monkeypatch.delenv("CARDS_SRC", raising=False)
    app = _app(tmp_path)
    assert app.state.cards_status == cards.DISABLED
    assert mount_status.get("cards") == (cards.DISABLED, app.state.cards_detail)


def test_a_second_create_app_does_not_inherit_the_first_ones_verdicts(tmp_path):
    _app(tmp_path)
    mount_status.record("broll", "absent", "left over from an older app")
    _app(tmp_path / "second")
    assert mount_status.get("broll")[1] != "left over from an older app"


# --------------------------------------------------------- the health route

def test_the_health_route_carries_every_mount(tmp_path, no_musicweb, monkeypatch):  # noqa: F811
    import builtins

    app = _app(tmp_path)
    monkeypatch.setattr(builtins, "__import__", no_musicweb)
    with TestClient(app) as c:
        body = as_user(c).get("/api/v1/health").json()

    assert set(body["mounts"]) == set(mount_status.NAMES)
    for name in mount_status.NAMES:
        assert body["mounts"][name]["status"]
        assert body["mounts"][name]["detail"]
    # Every old field is still there, `cards` block included.
    assert body["ok"] is True
    assert body["cards"]["status"] == body["mounts"]["cards"]["status"]


def test_an_unmounted_feature_never_makes_the_dashboard_unhealthy(tmp_path,
                                                                  no_musicweb,  # noqa: F811
                                                                  monkeypatch):
    import builtins

    app = _app(tmp_path)
    monkeypatch.setattr(builtins, "__import__", no_musicweb)
    with TestClient(app) as c:
        body = as_user(c).get("/api/v1/health").json()
    assert body["ok"] is True


def test_a_stranger_is_told_nothing_about_the_mounts(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as c:
        assert "mounts" not in c.get("/api/v1/health").json()


def test_the_block_falls_back_to_app_state_when_nothing_recorded(tmp_path):
    """A code bundle applied half way, or a boot that died in the middle of
    the mount block: the route still answers, from what app.state holds."""
    app = _app(tmp_path)
    mount_status.reset()
    with TestClient(app) as c:
        body = as_user(c).get("/api/v1/health").json()
    assert body["mounts"]["broll"]["status"] == app.state.broll_status


# ------------------------------------------------- ytdl.health_snapshot (B2)

def _fake_routes_api(monkeypatch, calls):
    module = types.ModuleType("ytdlweb.routes_api")

    def health_snapshot(app_or_state=None, *, allow_probe=True):
        calls.append(allow_probe)
        return {"worker_alive": True, "yt_dlp_stale": False,
                "pot_provider": "unknown"}

    module.health_snapshot = health_snapshot
    monkeypatch.setitem(sys.modules, "ytdlweb.routes_api", module)
    return module


def test_the_snapshot_is_none_when_ytdl_is_not_mounted(monkeypatch):
    app = FastAPI()
    app.state.ytdl_status = ytdl.DISABLED
    _fake_routes_api(monkeypatch, [])
    assert ytdl.health_snapshot(app) is None


def test_the_snapshot_never_probes(monkeypatch):
    """A collector cycle asking how the downloader is must not be able to make
    itself slow: the PO-token answer is the cached one."""
    app = FastAPI()
    app.state.ytdl_status = ytdl.MOUNTED
    calls: list[bool] = []
    _fake_routes_api(monkeypatch, calls)
    snap = ytdl.health_snapshot(app)
    assert snap["worker_alive"] is True
    assert calls == [False]


def test_a_sub_app_that_cannot_answer_is_none_not_a_raise(monkeypatch):
    app = FastAPI()
    app.state.ytdl_status = ytdl.MOUNTED
    module = types.ModuleType("ytdlweb.routes_api")

    def boom(app_or_state=None, **kw):
        raise RuntimeError("the downloader is having a day")

    module.health_snapshot = boom
    monkeypatch.setitem(sys.modules, "ytdlweb.routes_api", module)
    assert ytdl.health_snapshot(app) is None


def test_an_older_ytdl_tree_with_no_snapshot_function_is_none(monkeypatch):
    app = FastAPI()
    app.state.ytdl_status = ytdl.MOUNTED
    monkeypatch.setitem(sys.modules, "ytdlweb.routes_api",
                        types.ModuleType("ytdlweb.routes_api"))
    assert ytdl.health_snapshot(app) is None


def test_nothing_imports_ytdlweb_to_answer(monkeypatch):
    """An off site pays no yt-dlp import, which is the whole point of the site
    switch: the snapshot reads sys.modules and never imports."""
    app = FastAPI()
    app.state.ytdl_status = ytdl.MOUNTED
    for name in [n for n in list(sys.modules) if n.startswith("ytdlweb")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    assert ytdl.health_snapshot(app) is None


# ------------------------------------------------------- the mount contract

def test_a_broll_mount_with_no_settings_still_answers_a_pair(tmp_path, monkeypatch):
    host = FastAPI()
    status, detail = broll.mount_broll(host, "x" * 40)
    assert status in (broll.MOUNTED, broll.ABSENT, broll.DEGRADED)
    assert detail
