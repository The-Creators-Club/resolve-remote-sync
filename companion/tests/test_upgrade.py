"""Self-upgrade tests: the availability state machine, download+verify, and
the rename-swap in apply() with injected replace/spawn recorders -- in the
never-raise style of test_reporter.py."""
from __future__ import annotations

import hashlib
import io
import pathlib
from pathlib import Path

import pytest

from ccsync_companion import config as config_mod
from ccsync_companion import upgrade as upgrade_mod
from ccsync_companion.upgrade import UpgradeManager, cleanup_old_exe, parse_upgrade


def _info(version="9.9.9", body=b"new-exe-bytes", url="/api/v1/companion/package/windows/9.9.9"):
    return {
        "version": version,
        "url": url,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


class _FakeResponse:
    def __init__(self, body: bytes):
        self._stream = io.BytesIO(body)

    def read(self, n=-1):
        return self._stream.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_open(body: bytes, calls=None):
    def opener(url, headers, timeout):
        if calls is not None:
            calls.append((url, headers, timeout))
        return _FakeResponse(body)
    return opener


def _cfg(**overrides):
    cfg = {"dashboard_url": "http://dash.example.com", "dashboard_token": "tok123"}
    cfg.update(overrides)
    return cfg


# -- parse_upgrade ------------------------------------------------------


def test_parse_upgrade_valid():
    resp = {"ok": True, "upgrade": _info()}
    parsed = parse_upgrade(resp)
    assert parsed["version"] == "9.9.9"
    assert parsed["sha256"] == _info()["sha256"]


@pytest.mark.parametrize("resp", [
    None,
    "garbage",
    {},
    {"upgrade": None},
    {"upgrade": "not-a-dict"},
    {"upgrade": {"version": "9.9.9"}},                    # missing url/sha
    {"upgrade": {"version": "9.9.9", "url": "/x", "sha256": "short"}},
    {"upgrade": _info(version=config_mod.VERSION)},       # same as running
])
def test_parse_upgrade_rejects(resp):
    assert parse_upgrade(resp) is None


# -- availability state machine ----------------------------------------


def test_note_report_response_sets_and_clears():
    mgr = UpgradeManager(_cfg())
    assert mgr.available is None
    mgr.note_report_response({"ok": True, "upgrade": _info()})
    assert mgr.available["version"] == "9.9.9"
    # a well-formed response WITHOUT the key clears (rollback to our version)
    mgr.note_report_response({"ok": True})
    assert mgr.available is None
    # garbage does NOT clear an existing offer
    mgr.note_report_response({"ok": True, "upgrade": _info()})
    mgr.note_report_response("not-a-dict")
    assert mgr.available is not None


def test_on_available_fires_once_per_version():
    seen = []
    mgr = UpgradeManager(_cfg(), on_available=lambda info: seen.append(info["version"]))
    mgr.note_report_response({"upgrade": _info()})
    mgr.note_report_response({"upgrade": _info()})          # same version: silent
    assert seen == ["9.9.9"]
    mgr.note_report_response({"upgrade": _info(version="9.9.10")})
    assert seen == ["9.9.9", "9.9.10"]


def test_on_available_exception_swallowed():
    def boom(info):
        raise RuntimeError("boom")
    mgr = UpgradeManager(_cfg(), on_available=boom)
    mgr.note_report_response({"upgrade": _info()})          # must not raise
    assert mgr.available is not None


# -- download_and_verify ------------------------------------------------


def test_download_good_sha(tmp_path):
    body = b"new-exe-bytes"
    calls = []
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(body, calls))
    path = mgr.download_and_verify(_info(body=body), tmp_path)
    assert path is not None
    assert path.read_bytes() == body
    url, headers, _timeout = calls[0]
    # relative url absolutized against dashboard_url, token header attached
    assert url == "http://dash.example.com/api/v1/companion/package/windows/9.9.9"
    assert headers["X-CCSync-Token"] == "tok123"


def test_download_bad_sha_removes_temp(tmp_path):
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(b"tampered"))
    info = _info(body=b"expected-bytes")
    assert mgr.download_and_verify(info, tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_download_network_error(tmp_path):
    def opener(url, headers, timeout):
        raise OSError("connection refused")
    mgr = UpgradeManager(_cfg(), http_open=opener)
    assert mgr.download_and_verify(_info(), tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_download_without_dashboard_url(tmp_path):
    mgr = UpgradeManager(_cfg(dashboard_url=""), http_open=_fake_open(b"x"))
    assert mgr.download_and_verify(_info(), tmp_path) is None


# -- apply() ------------------------------------------------------------


@pytest.fixture
def frozen_exe(tmp_path, monkeypatch):
    exe = tmp_path / "ccsync-companion.exe"
    exe.write_bytes(b"old-exe-bytes")
    monkeypatch.setattr(upgrade_mod.sys, "executable", str(exe))
    monkeypatch.setattr(upgrade_mod, "is_frozen", lambda: True)
    return exe


def test_apply_swaps_spawns_and_shuts_down(frozen_exe):
    body = b"new-exe-bytes"
    spawned, shutdowns = [], []
    mgr = UpgradeManager(
        _cfg(),
        http_open=_fake_open(body),
        spawn_fn=lambda exe: spawned.append(Path(exe)),
        request_shutdown=lambda: shutdowns.append(True),
    )
    mgr.note_report_response({"upgrade": _info(body=body)})
    assert mgr.apply() is True
    assert frozen_exe.read_bytes() == body
    old = frozen_exe.with_name(frozen_exe.name + ".old")
    assert old.read_bytes() == b"old-exe-bytes"
    assert spawned == [frozen_exe]
    assert shutdowns == [True]


def test_apply_spawn_failure_rolls_back(frozen_exe):
    body = b"new-exe-bytes"
    shutdowns = []

    def bad_spawn(exe):
        raise OSError("blocked by AV")

    mgr = UpgradeManager(
        _cfg(),
        http_open=_fake_open(body),
        spawn_fn=bad_spawn,
        request_shutdown=lambda: shutdowns.append(True),
    )
    mgr.note_report_response({"upgrade": _info(body=body)})
    assert mgr.apply() is False
    # the original build is back in place and still running; no shutdown
    assert frozen_exe.read_bytes() == b"old-exe-bytes"
    assert shutdowns == []


def test_apply_refuses_when_not_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(upgrade_mod, "is_frozen", lambda: False)
    spawned = []
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(b"x"), spawn_fn=spawned.append)
    mgr.note_report_response({"upgrade": _info()})
    assert mgr.apply() is False
    assert spawned == []


def test_apply_without_available_is_noop(frozen_exe):
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(b"x"))
    assert mgr.apply() is False
    assert frozen_exe.read_bytes() == b"old-exe-bytes"


def test_apply_download_failure_touches_nothing(frozen_exe):
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(b"tampered"))
    mgr.note_report_response({"upgrade": _info(body=b"expected")})
    assert mgr.apply() is False
    assert frozen_exe.read_bytes() == b"old-exe-bytes"
    assert not frozen_exe.with_name(frozen_exe.name + ".old").exists()


# -- cleanup_old_exe ----------------------------------------------------


def test_cleanup_old_exe_removes_and_tolerates_missing(tmp_path):
    exe = tmp_path / "ccsync-companion.exe"
    old = tmp_path / "ccsync-companion.exe.old"
    old.write_bytes(b"stale")
    cleanup_old_exe(exe)
    assert not old.exists()
    cleanup_old_exe(exe)  # nothing there: still no raise


def test_cleanup_old_exe_swallows_oserror(tmp_path, monkeypatch):
    def locked(self, missing_ok=False):
        raise OSError("held by AV scan")
    monkeypatch.setattr(pathlib.Path, "unlink", locked)
    cleanup_old_exe(tmp_path / "ccsync-companion.exe")  # must not raise
