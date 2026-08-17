"""Self-upgrade tests: the availability state machine, download+verify, and
the rename-swap in apply() with injected replace/spawn recorders -- in the
never-raise style of test_reporter.py.

Every offer here is SIGNED (COMMERCIAL_READINESS.md item 4, 2026-08-17) with
a throwaway key this module generates, trusted via an autouse fixture that
swaps RELEASE_PUBKEYS for the duration. That is deliberate: an unsigned offer
is now refused everywhere, so a helper that produced one would test the
refusal path in every test rather than the path it names."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import pathlib
import subprocess
import sys
from pathlib import Path

import pytest

from ccsync_companion import config as config_mod
from ccsync_companion import ed25519
from ccsync_companion import release_pubkey
from ccsync_companion import upgrade as upgrade_mod
from ccsync_companion.upgrade import UpgradeManager, cleanup_old_exe, parse_upgrade

# A fixed seed, not secrets.token_bytes: a failing signature test should fail
# the same way twice.
TEST_SEED = bytes(range(32))
TEST_PUBKEY = base64.b64encode(ed25519.public_key(TEST_SEED)).decode("ascii")
OTHER_SEED = bytes(range(32, 64))
OTHER_PUBKEY = base64.b64encode(ed25519.public_key(OTHER_SEED)).decode("ascii")


@pytest.fixture(autouse=True)
def _trust_the_test_key(monkeypatch, tmp_path):
    """Trust the throwaway key, and keep the downgrade floor out of the real
    ~/.ccsync -- note_floor() writes, and a test must never raise this
    machine's actual floor."""
    monkeypatch.setattr(release_pubkey, "RELEASE_PUBKEYS", (TEST_PUBKEY,))
    # Beside tmp_path, not inside it: several tests assert that a refused
    # download left the destination directory completely empty, and tmp_path
    # is that directory.
    floor = tmp_path.with_name(tmp_path.name + "-floor") / "upgrade_floor.json"
    monkeypatch.setattr(upgrade_mod, "floor_path", lambda cfg: floor)


def _sign(record, seed=TEST_SEED):
    return base64.b64encode(
        ed25519.sign(seed, release_pubkey.canonical_record(record))
    ).decode("ascii")


def _info(version="9.9.9", body=b"new-exe-bytes", url="/api/v1/companion/package/windows/9.9.9",
          min_version="0.0.0", seed=TEST_SEED, sign=True, **overrides):
    record = {
        "kind": "companion",
        "platform": "windows",
        "version": version,
        "filename": f"ccsync-companion-{version}.exe",
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "min_version": min_version,
        "published_at": "2026-08-17T00:00:00Z",
        "signed_binary": False,
    }
    record.update(overrides)
    info = dict(record)
    info["url"] = url
    if sign:
        info["signature"] = _sign(record, seed)
        info["pubkey_id"] = release_pubkey.pubkey_id(
            base64.b64encode(ed25519.public_key(seed)).decode("ascii")
        )
    return info


class _FakeResponse:
    def __init__(self, body: bytes):
        self._stream = io.BytesIO(body)

    def read(self, n=-1):
        return self._stream.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _no_download_left(dest_dir) -> bool:
    """No partial/finished update remains in the exe's directory.

    Was `list(dest_dir.iterdir()) == []` until 2026-08-17, which pinned "the
    directory is empty" rather than "the download was cleaned up" -- and then
    conftest's per-test ~/.ccsync isolation started materialising a directory
    inside tmp_path. What these tests are about is the ~20 MB temp file, so
    say that."""
    return not any(
        p.name.startswith("ccsync-companion.new") for p in Path(dest_dir).iterdir()
    )


def _fake_open(body: bytes, calls=None):
    def opener(url, headers, timeout):
        if calls is not None:
            calls.append((url, headers, timeout))
        return _FakeResponse(body)
    return opener


def _cfg(**overrides):
    # A tailnet address, not a public hostname: plain http off the tailnet is
    # refused by transport_ok() since item 4 (2026-08-17).
    cfg = {"dashboard_url": "http://100.64.0.1:8480", "dashboard_token": "tok123"}
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
    assert url == "http://100.64.0.1:8480/api/v1/companion/package/windows/9.9.9"
    assert headers["X-CCSync-Token"] == "tok123"


def test_download_bad_sha_removes_temp(tmp_path):
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(b"tampered"))
    info = _info(body=b"expected-bytes")
    assert mgr.download_and_verify(info, tmp_path) is None
    assert _no_download_left(tmp_path)


def test_download_network_error(tmp_path):
    def opener(url, headers, timeout):
        raise OSError("connection refused")
    mgr = UpgradeManager(_cfg(), http_open=opener)
    assert mgr.download_and_verify(_info(), tmp_path) is None
    assert _no_download_left(tmp_path)


def test_download_without_dashboard_url(tmp_path):
    mgr = UpgradeManager(_cfg(dashboard_url=""), http_open=_fake_open(b"x"))
    assert mgr.download_and_verify(_info(), tmp_path) is None


# -- size_bytes: parsed since forever, read by nothing ------------------


@pytest.mark.parametrize("raw, expected", [
    (200, 200),
    ("200", 200),
    (None, None),
    (0, None),
    (-5, None),
    ("huge", None),
    (upgrade_mod.MAX_DOWNLOAD_BYTES + 1, None),
])
def test_advertised_size_only_trusts_a_usable_number(raw, expected):
    """A bogus value must not be able to refuse a legitimate update, nor wave
    an oversized one through -- both directions are "unknown"."""
    assert upgrade_mod.advertised_size({"size_bytes": raw}) == expected


def test_advertised_size_of_a_missing_or_broken_info_is_unknown():
    assert upgrade_mod.advertised_size(None) is None
    assert upgrade_mod.advertised_size({}) is None
    assert upgrade_mod.advertised_size("not-a-dict") is None


def test_the_free_space_check_accounts_for_the_advertised_size(tmp_path, monkeypatch):
    """The check was a flat 200 MB margin that never consulted size_bytes, so
    a 250 MB build downloaded onto 210 MB of free space passed it and only
    failed at the last write."""
    import shutil as _shutil

    body = b"x" * 4096
    # Passed through _info so it is part of the SIGNED record: mutating the
    # offer after signing is what the signature is there to catch.
    info = _info(body=body, size_bytes=250 * 1024 * 1024)

    class _Usage:
        free = upgrade_mod.MIN_FREE_BYTES_MARGIN + 10 * 1024 * 1024

    monkeypatch.setattr(_shutil, "disk_usage", lambda path: _Usage())
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(body))
    assert mgr.download_and_verify(info, tmp_path) is None
    assert _no_download_left(tmp_path)

    class _Plenty:
        free = upgrade_mod.MIN_FREE_BYTES_MARGIN + 400 * 1024 * 1024

    monkeypatch.setattr(_shutil, "disk_usage", lambda path: _Plenty())
    assert mgr.download_and_verify(info, tmp_path) is not None


def test_a_body_bigger_than_the_advertised_size_is_abandoned(tmp_path):
    """The advertised size is the tighter of the two ceilings: a body that
    outgrows it is not the build we were offered, and there is no reason to
    write the rest of it to disk before the sha check notices."""
    info = _info(body=b"y" * 100, size_bytes=10)
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(b"y" * 100))
    assert mgr.download_and_verify(info, tmp_path) is None
    assert _no_download_left(tmp_path)


def test_an_upgrade_with_an_unusable_advertised_size_still_downloads(tmp_path):
    """`advertised_size` returning None ("unknown") must not block a download
    -- it falls back to the hard ceiling.

    This test used to pop size_bytes entirely, standing in for a dashboard
    too old to send it. That shape no longer exists: size_bytes is one of the
    fields the release signature covers (item 4, 2026-08-17), so a record
    without it cannot be signed and a dashboard old enough to omit it sends
    no signature either. The next test pins that refusal."""
    body = b"new-exe-bytes"
    info = _info(body=body, size_bytes=upgrade_mod.MAX_DOWNLOAD_BYTES * 10)
    assert upgrade_mod.advertised_size(info) is None
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(body))
    assert mgr.download_and_verify(info, tmp_path) is not None


def test_an_offer_missing_a_signed_field_is_refused(tmp_path):
    body = b"new-exe-bytes"
    info = _info(body=body)
    info.pop("size_bytes")
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(body))
    assert mgr.download_and_verify(info, tmp_path) is None
    assert _no_download_left(tmp_path)


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


def test_apply_rolls_back_when_the_child_dies_in_the_grace_window(frozen_exe):
    """R11 belt-and-braces: the child's single-instance guard waits out our
    mutex, so an exit this early is a startup failure, not a lost hand-off
    race. Standing down anyway is how a one-click update left an editor's
    machine with no companion at all (nothing retries -- the Run-key
    autostart is logon-only)."""
    body = b"new-exe-bytes"
    shutdowns = []

    class _DeadChild:
        @staticmethod
        def poll():
            return 1

    mgr = UpgradeManager(
        _cfg(),
        http_open=_fake_open(body),
        spawn_fn=lambda exe: _DeadChild(),
        request_shutdown=lambda: shutdowns.append(True),
    )
    mgr.note_report_response({"upgrade": _info(body=body)})
    assert mgr.apply() is False
    # the original build is back in place and still running; no shutdown
    assert frozen_exe.read_bytes() == b"old-exe-bytes"
    assert shutdowns == []


def test_apply_stands_down_once_the_child_outlives_the_grace_window(frozen_exe):
    body = b"new-exe-bytes"
    shutdowns, polls = [], []

    class _LiveChild:
        @staticmethod
        def poll():
            polls.append(True)
            return None

    clock = {"now": 0.0}

    def _tick(seconds):
        clock["now"] += seconds

    mgr = UpgradeManager(
        _cfg(),
        http_open=_fake_open(body),
        spawn_fn=lambda exe: _LiveChild(),
        request_shutdown=lambda: shutdowns.append(True),
        clock_fn=lambda: clock["now"],
        sleep_fn=_tick,
    )
    mgr.note_report_response({"upgrade": _info(body=body)})
    assert mgr.apply() is True
    assert frozen_exe.read_bytes() == body
    assert shutdowns == [True]
    assert polls, "the hand-off was never watched"


def test_a_spawn_stub_returning_none_keeps_the_fire_and_forget_contract(frozen_exe):
    """Injected spawns (and the pre-R11 seam) return nothing; the grace watch
    must only engage when there is a child to poll."""
    body = b"new-exe-bytes"
    shutdowns = []
    mgr = UpgradeManager(
        _cfg(),
        http_open=_fake_open(body),
        spawn_fn=lambda exe: None,
        request_shutdown=lambda: shutdowns.append(True),
        sleep_fn=lambda s: (_ for _ in ()).throw(AssertionError("slept with no child")),
    )
    mgr.note_report_response({"upgrade": _info(body=body)})
    assert mgr.apply() is True
    assert shutdowns == [True]


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


# ===========================================================================
# AUDIT_2 round-2 regressions
# ===========================================================================


def test_upgrade_url_must_share_the_dashboards_origin():
    """AUDIT_2 CORE-M10. `upgrade.url` arrives inside a plain-HTTP
    /api/v1/report response, and the sha256 that "verifies" the download
    comes from that SAME response -- so anyone able to answer or alter one
    report response could hand the companion an arbitrary exe PLUS its
    matching hash, which is then renamed over the running companion and
    launched detached. There was no origin check at all."""
    from ccsync_companion.upgrade import same_origin

    base = "http://100.64.0.1:8480"
    assert same_origin("/api/v1/packages/ccsync-companion-0.4.5.exe", base) is True
    assert same_origin("http://100.64.0.1:8480/x.exe", base) is True
    assert same_origin("http://evil.example.com/payload.exe", base) is False
    assert same_origin("https://100.64.0.1:8480/x.exe", base) is False  # scheme differs
    assert same_origin("http://100.64.0.1:9999/x.exe", base) is False   # port differs
    assert same_origin("", base) is False


def test_download_refuses_a_foreign_host(tmp_path):
    opened = []

    def spy_open(url, headers, timeout):
        opened.append(url)
        raise AssertionError("must never be fetched")

    mgr = UpgradeManager({"dashboard_url": "http://100.64.0.1:8480"}, http_open=spy_open)
    result = mgr.download_and_verify(
        {"url": "http://evil.example.com/x.exe", "sha256": "0" * 64}, tmp_path,
    )
    assert result is None
    assert opened == []


def test_download_enforces_a_size_ceiling(tmp_path, monkeypatch):
    """AUDIT_2 §2-low: the download had no size ceiling and no free-space
    check."""
    import ccsync_companion.upgrade as upgrade_mod

    monkeypatch.setattr(upgrade_mod, "MAX_DOWNLOAD_BYTES", 1024)

    class _Endless:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return b"x" * n

    mgr = UpgradeManager({"dashboard_url": "http://d"},
                         http_open=lambda u, h, t: _Endless())
    assert mgr.download_and_verify({"url": "/x.exe", "sha256": "0" * 64}, tmp_path) is None
    assert not (tmp_path / "ccsync-companion.new.exe").exists()


def test_rollback_survives_a_non_oserror_and_cleans_up(tmp_path):
    """AUDIT_2 CORE-H7. _rollback caught only OSError, but `_replace` is an
    INJECTABLE callable and os.replace can raise TypeError/ValueError. A raise
    escaped _apply_inner -> apply() -> app.apply_upgrade() -> the tray's
    dialog handler, killing the tray daemon thread to invisible stderr WHILE
    `exe` did not exist -- renamed to .old, new build parked at .new.exe."""
    exe = tmp_path / "ccsync-companion.exe"
    old = tmp_path / "ccsync-companion.exe.old"
    aside = tmp_path / "ccsync-companion.new.exe"
    old.write_bytes(b"previous")
    exe.write_bytes(b"new build")
    aside.write_bytes(b"leftover")

    def hostile(a, b):
        raise TypeError("surrogates not allowed")

    mgr = UpgradeManager({}, replace_fn=hostile)
    mgr._rollback(old, exe, aside=aside)  # must not raise


def test_rollback_unlinks_the_rejected_build(tmp_path):
    exe = tmp_path / "ccsync-companion.exe"
    old = tmp_path / "ccsync-companion.exe.old"
    aside = tmp_path / "ccsync-companion.new.exe"
    old.write_bytes(b"previous")
    exe.write_bytes(b"new build")

    mgr = UpgradeManager({}, replace_fn=os.replace)
    mgr._rollback(old, exe, aside=aside)

    assert exe.read_bytes() == b"previous", "the previous build must be restored"
    assert not aside.exists(), "~20MB of a refused build must not be left behind"


def test_note_version_start_only_fires_on_an_actual_version_change(tmp_path):
    """AUDIT_2 CORE-H6. "Did we just upgrade?" used to be derived from whether
    cleanup_old_exe() managed to unlink an `.old` -- which forced the rollback
    copy to be destroyed before the new build had proven anything, AND fired
    the "Update complete" toast on an unrelated later restart whenever an AV
    hold had deferred the unlink."""
    import ccsync_companion.upgrade as upgrade_mod
    from ccsync_companion import config as config_mod

    state = tmp_path / "state"
    # First ever run: no marker -> not an upgrade.
    assert upgrade_mod.note_version_start(state) is False
    # Same version again -> still not an upgrade.
    assert upgrade_mod.note_version_start(state) is False
    # A different version was recorded -> this start IS the first on a new build.
    (state / "last_version.txt").write_text("0.0.1", encoding="utf-8")
    assert upgrade_mod.note_version_start(state) is True
    assert (state / "last_version.txt").read_text(encoding="utf-8") == config_mod.VERSION
    assert upgrade_mod.note_version_start(state) is False


def test_note_version_start_never_raises(tmp_path):
    import ccsync_companion.upgrade as upgrade_mod

    blocker = tmp_path / "blocked"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    assert upgrade_mod.note_version_start(blocker) is False


# ===========================================================================
# AUDIT_3 H-1: the update download must not follow redirects
# ===========================================================================


class _RedirectResponse:
    """A 3xx handed back by an injected http_open (a transport that follows
    redirects itself, or a dashboard answering the download with one)."""

    status = 302

    def __init__(self):
        self.reads = 0

    def read(self, n=-1):
        self.reads += 1
        return b"attacker-payload"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_refuses_a_redirect_response(tmp_path, caplog):
    """same_origin() is checked ONCE, before the request. urlopen follows 3xx
    automatically, so `302 Location: http://attacker/x.exe` moved the
    download off-origin afterwards -- and the sha256 proves nothing, since it
    came from the same response that supplied the URL."""
    resp = _RedirectResponse()
    calls = []

    def redirecting_open(url, headers, timeout):
        calls.append(url)
        return resp

    mgr = UpgradeManager(_cfg(), http_open=redirecting_open)
    with caplog.at_level("ERROR", logger="ccsync.upgrade"):
        result = mgr.download_and_verify(_info(), tmp_path)

    assert result is None
    assert resp.reads == 0, "not a single byte of a redirected download may be read"
    assert not (tmp_path / "ccsync-companion.new.exe").exists()
    assert len(calls) == 1, "the redirect target must never be requested"
    assert any("redirect" in r.message.lower() for r in caplog.records)


class _FakeHTTPResponse(io.BytesIO):
    """Minimal stand-in for http.client.HTTPResponse, enough for urllib's
    handler chain (HTTPErrorProcessor -> HTTPRedirectHandler)."""

    def __init__(self, code: int, headers: dict, body: bytes = b"", url: str = ""):
        super().__init__(body)
        import email.message

        self.code = code
        self.status = code
        self.msg = "Found" if code // 100 == 3 else "OK"
        self.url = url
        self._info = email.message.Message()
        for key, value in headers.items():
            self._info[key] = value

    def info(self):
        return self._info

    def geturl(self):
        return self.url


def test_the_upgrade_opener_never_follows_a_redirect_and_never_resends_the_token():
    """Drives the REAL handler chain build_no_redirect_opener() builds: a 302
    must surface as an error, the redirect target must never be requested,
    and X-CCSync-Token must therefore never reach it."""
    import urllib.error
    import urllib.request

    seen = []

    class _RecordingHandler(urllib.request.HTTPHandler):
        def http_open(self, req):
            seen.append((req.full_url, dict(req.header_items())))
            if len(seen) == 1:
                return _FakeHTTPResponse(
                    302, {"Location": "http://evil.example.com/payload.exe"},
                    url=req.full_url,
                )
            return _FakeHTTPResponse(200, {}, b"payload", url=req.full_url)

    opener = upgrade_mod.build_no_redirect_opener(_RecordingHandler())
    req = urllib.request.Request(
        "http://dash.example.com/api/v1/companion/package/windows/9.9.9",
        headers={"X-CCSync-Token": "tok123"}, method="GET",
    )

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        opener.open(req, timeout=5)

    assert excinfo.value.code == 302
    assert len(seen) == 1, f"the redirect was followed: {seen}"
    assert "evil.example.com" not in seen[0][0]
    assert any("ccsync-token" in key.lower() for key in seen[0][1]), (
        "sanity: the token IS sent to the dashboard itself"
    )


def test_default_http_open_uses_the_no_redirect_opener(monkeypatch):
    """The production fetch path must be the hardened opener, not
    urllib.request.urlopen (which follows redirects)."""
    used = []

    class _StubOpener:
        def open(self, req, timeout=None):
            used.append((req.full_url, dict(req.header_items()), timeout))
            return _FakeHTTPResponse(200, {}, b"ok", url=req.full_url)

    monkeypatch.setattr(upgrade_mod, "build_no_redirect_opener", lambda *a: _StubOpener())
    upgrade_mod.default_http_open(
        "http://dash.example.com/x.exe", {"X-CCSync-Token": "tok123"}, 12.0
    )

    assert used and used[0][0] == "http://dash.example.com/x.exe"
    assert used[0][2] == 12.0


def test_redirect_status_reads_either_attribute():
    class _WithCode:
        code = 301

    class _WithStatus:
        status = 200

    assert upgrade_mod.redirect_status(_WithCode()) == 301
    assert upgrade_mod.redirect_status(_WithStatus()) is None
    assert upgrade_mod.redirect_status(object()) is None


# ===========================================================================
# Wording: "different, not newer" must not read as "update" for a downgrade
# ===========================================================================


@pytest.mark.parametrize(
    "text,expected",
    [
        ("0.4.5", (0, 4, 5)),
        ("v1.2", (1, 2)),
        (" 10.0.3 ", (10, 0, 3)),
        # NOT ranked as (0, 5): truncating a suffixed build would make
        # "0.4.5-hotfix" compare OLDER than the 0.4.5 it patches.
        ("0.5.0-rc1", None),
        ("2", (2,)),
        ("", None),
        ("nightly", None),
        (None, None),
        ("v", None),
    ],
)
def test_parse_version_is_tolerant_and_never_raises(text, expected):
    assert upgrade_mod.parse_version(text) == expected


def test_compare_to_running_orders_newer_older_and_same():
    assert upgrade_mod.compare_to_running("0.5.0", running="0.4.5") == "newer"
    assert upgrade_mod.compare_to_running("0.4.3", running="0.4.5") == "older"
    assert upgrade_mod.compare_to_running("0.4.5", running="0.4.5") == "same"
    # more components wins a shared prefix, both directions
    assert upgrade_mod.compare_to_running("0.4.5.1", running="0.4.5") == "newer"
    assert upgrade_mod.compare_to_running("0.4", running="0.4.5") == "older"


def test_compare_to_running_is_unknown_when_either_side_is_unparseable():
    assert upgrade_mod.compare_to_running("nightly", running="0.4.5") == "unknown"
    assert upgrade_mod.compare_to_running("0.4.5", running="dev") == "unknown"
    assert upgrade_mod.compare_to_running(None, running=None) == "unknown"


def test_compare_to_running_defaults_to_the_build_we_are_running():
    assert upgrade_mod.compare_to_running(config_mod.VERSION) == "same"


def test_offer_label_never_calls_a_downgrade_an_update():
    """THE LIVE BUG (2026-07-25): running v0.4.5, dashboard still publishing
    v0.4.3 as `current`, tray offering "Update available → v0.4.3 (install)"
    -- one click from a silent downgrade that reintroduced a round of
    security fixes."""
    assert upgrade_mod.offer_label("0.5.0", running="0.4.5") == (
        "Update available → v0.5.0 (install)")

    rollback = upgrade_mod.offer_label("0.4.3", running="0.4.5")
    assert rollback == "Roll back to v0.4.3 (older build, install)"
    assert "update" not in rollback.lower()

    assert upgrade_mod.offer_label("weird", running="0.4.5") == (
        "Switch to vweird (install)")
    # equal numbers but a different string (the server only advertises a
    # DIFFERENT version, so this is reachable) -> neutral, not "update"
    assert upgrade_mod.offer_label("0.4.5-hotfix", running="0.4.5") == (
        "Switch to v0.4.5-hotfix (install)")


def test_offer_toast_matches_the_label_direction():
    assert "Update available" in upgrade_mod.offer_toast("9.9.9", running="0.4.5")
    toast = upgrade_mod.offer_toast("0.4.3", running="0.4.5")
    assert "Roll back" in toast and "OLDER" in toast
    assert "update" not in toast.lower()
    assert "0.4.5" in toast, "the toast must say what this machine is running"
    assert upgrade_mod.offer_toast("nightly", running="0.4.5").startswith("Switch to")


def test_offer_dialog_text_agrees_with_the_menu_item_that_opened_it():
    title, body, ok = upgrade_mod.offer_dialog_text("0.4.3", running="0.4.5")
    assert ok == "ROLL BACK"
    assert "OLDER" in body and "roll back" in title.lower()

    title, body, ok = upgrade_mod.offer_dialog_text("9.9.9", running="0.4.5")
    assert ok == "UPDATE"

    title, body, ok = upgrade_mod.offer_dialog_text("nightly", running="0.4.5")
    assert ok == "SWITCH"


def test_the_wording_helpers_never_raise_on_hostile_input():
    """A version string is server-supplied. Nothing here may kill the tray
    thread that renders the menu."""
    class _Hostile:
        def __str__(self):
            raise RuntimeError("boom")

    for value in (object(), 5, ["0.4.5"], {"v": 1}):
        assert upgrade_mod.compare_to_running(value) in (
            "newer", "older", "same", "unknown")
    assert upgrade_mod.parse_version(_Hostile()) is None
    assert upgrade_mod.compare_to_running(_Hostile()) == "unknown"


# ===========================================================================
# macOS port (KNOWN_BUGS #8): the swap assumed the Windows shape of the binary
#
# The macOS artifact is a bare single-file Mach-O called `ccsync-companion`
# -- no .exe, no .app. The download name was hardcoded `.new.exe`, the
# verified download was never given an execute bit (open("wb") is 0644, so
# the respawn would have failed with EACCES), and the detach was a Windows
# creationflags mask with no POSIX equivalent. Windows behaviour must come out
# of this byte-identical, so every darwin test below has a win32 twin.
# ===========================================================================


@pytest.fixture
def chmods(monkeypatch):
    """Records every os.chmod the module makes, and performs none of them."""
    calls = []
    monkeypatch.setattr(os, "chmod", lambda path, mode, **kw: calls.append((Path(path), mode)))
    return calls


# `darwin` and `windows` now live in conftest.py so every module shares one
# spelling -- and so `windows` can supply the win32-only subprocess constants
# that this module's _default_spawn tests need on a Mac (MAC-2a).


def test_the_download_name_follows_the_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert upgrade_mod.new_download_name() == "ccsync-companion.new.exe"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert upgrade_mod.new_download_name() == "ccsync-companion.new"
    monkeypatch.setattr(sys, "platform", "linux")
    assert upgrade_mod.new_download_name() == "ccsync-companion.new"


def test_the_download_is_made_executable_on_macos(tmp_path, darwin, chmods):
    """open("wb") leaves 0644 under the usual umask and macOS will not exec
    that -- the swap would rename a non-executable file over the companion and
    the respawn would die with EACCES. os.replace preserves the mode, so
    chmodding the download carries through both renames."""
    body = b"new-mach-o-bytes"
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(body))
    path = mgr.download_and_verify(_info(body=body), tmp_path)

    assert path == tmp_path / "ccsync-companion.new", "no .exe on a Mac"
    assert path.read_bytes() == body
    assert chmods == [(path, 0o755)]


def test_windows_downloads_the_exe_name_and_never_chmods(tmp_path, windows, chmods):
    """The Windows path must be untouched: os.chmod there only toggles the
    read-only bit, and calling it on the pending build is a way to fail an
    upgrade for nothing."""
    body = b"new-exe-bytes"
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(body))
    path = mgr.download_and_verify(_info(body=body), tmp_path)

    assert path == tmp_path / "ccsync-companion.new.exe"
    assert chmods == []


def test_a_download_that_fails_verification_is_never_made_executable(
    tmp_path, darwin, chmods,
):
    """Order matters: an unverified download must not be runnable, however
    briefly."""
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(b"tampered"))
    assert mgr.download_and_verify(_info(body=b"expected-bytes"), tmp_path) is None
    assert chmods == []
    assert _no_download_left(tmp_path)


def test_a_chmod_failure_does_not_refuse_the_update(tmp_path, darwin, monkeypatch, caplog):
    """chmod can fail with EPERM on exotic mounts where the file is already
    executable. Refusing a working update over that would be worse than the
    alternative: if the binary really cannot be executed, the spawn fails and
    _apply_inner rolls the whole swap back."""
    def blocked(path, mode, **kw):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(os, "chmod", blocked)
    body = b"new-mach-o-bytes"
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(body))
    with caplog.at_level("WARNING", logger="ccsync.upgrade"):
        path = mgr.download_and_verify(_info(body=body), tmp_path)

    assert path is not None and path.read_bytes() == body
    assert any("execute bit" in r.message for r in caplog.records)


# -- the swap, with an extensionless binary -----------------------------


@pytest.fixture
def mac_exe(tmp_path, monkeypatch, darwin):
    """The macOS artifact: `ccsync-companion`, no extension, no bundle."""
    exe = tmp_path / "ccsync-companion"
    exe.write_bytes(b"old-mach-o-bytes")
    monkeypatch.setattr(upgrade_mod.sys, "executable", str(exe))
    monkeypatch.setattr(upgrade_mod, "is_frozen", lambda: True)
    return exe


def test_apply_swaps_an_extensionless_binary(mac_exe, chmods):
    body = b"new-mach-o-bytes"
    spawned, shutdowns = [], []
    mgr = UpgradeManager(
        _cfg(),
        http_open=_fake_open(body),
        spawn_fn=lambda exe: spawned.append(Path(exe)),
        request_shutdown=lambda: shutdowns.append(True),
    )
    mgr.note_report_response({"upgrade": _info(body=body)})
    assert mgr.apply() is True

    assert mac_exe.read_bytes() == body
    old = mac_exe.with_name("ccsync-companion.old")
    assert old.read_bytes() == b"old-mach-o-bytes"
    assert spawned == [mac_exe]
    assert shutdowns == [True]
    # chmodded while it was still the .new download, not after the swap
    assert chmods == [(mac_exe.with_name("ccsync-companion.new"), 0o755)]
    assert not mac_exe.with_name("ccsync-companion.new").exists()
    assert not mac_exe.with_name("ccsync-companion.new.exe").exists()


def test_apply_rolls_an_extensionless_binary_back(mac_exe, chmods):
    def bad_spawn(exe):
        raise OSError("exec format error")

    mgr = UpgradeManager(
        _cfg(), http_open=_fake_open(b"new-mach-o-bytes"), spawn_fn=bad_spawn,
    )
    mgr.note_report_response({"upgrade": _info(body=b"new-mach-o-bytes")})
    assert mgr.apply() is False

    assert mac_exe.read_bytes() == b"old-mach-o-bytes", "the running build must be restored"
    assert not mac_exe.with_name("ccsync-companion.old").exists()
    assert not mac_exe.with_name("ccsync-companion.new").exists(), (
        "a refused ~20 MB build must not be left behind"
    )


def test_cleanup_old_removes_an_extensionless_leftover(tmp_path, darwin):
    exe = tmp_path / "ccsync-companion"
    old = tmp_path / "ccsync-companion.old"
    old.write_bytes(b"stale")
    assert cleanup_old_exe(exe) is True
    assert not old.exists()
    assert cleanup_old_exe(exe) is False


# -- _default_spawn -----------------------------------------------------


@pytest.fixture
def popen_calls(monkeypatch):
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return calls


def test_posix_spawn_detaches_with_a_new_session(tmp_path, darwin, popen_calls, monkeypatch):
    """POSIX has no creationflags (passing one raises). setsid() is the
    equivalent: the child gets its own session and process group, so it
    survives this process's death and takes no signal aimed at the dying
    parent. The macOS LaunchAgent is RunAtLoad-only with no KeepAlive, so
    nothing else would ever bring the new build up."""
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "/tmp/_MEI999")
    monkeypatch.setenv("_MEIPASS2", "/tmp/_MEI999")
    exe = tmp_path / "ccsync-companion"

    UpgradeManager._default_spawn(exe)

    (argv, kwargs), = popen_calls
    assert argv == [str(exe)]
    assert kwargs["start_new_session"] is True
    assert "creationflags" not in kwargs, "creationflags is a Windows-only kwarg"
    assert kwargs["cwd"] == str(exe.parent)
    for handle in ("stdin", "stdout", "stderr"):
        assert kwargs[handle] == subprocess.DEVNULL
    # the onefile hygiene is platform-neutral and must survive the port
    env = kwargs["env"]
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert not [k for k in env if k.startswith("_PYI") or k.startswith("_MEI")]


@pytest.mark.skipif(not hasattr(subprocess, "DETACHED_PROCESS"),
                    reason="Windows-only creation flags")
def test_windows_spawn_keeps_its_creation_flags(tmp_path, windows, popen_calls):
    """Byte-identical to before the macOS port: DETACHED_PROCESS decouples
    from this soon-dead process and CREATE_NO_WINDOW stops Windows allocating
    the empty console whose closure killed the companion (2026-07-25)."""
    exe = tmp_path / "ccsync-companion.exe"

    UpgradeManager._default_spawn(exe)

    (argv, kwargs), = popen_calls
    assert argv == [str(exe)]
    assert kwargs["creationflags"] == (
        subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.CREATE_NO_WINDOW
    )
    assert "start_new_session" not in kwargs
    assert kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_the_spawn_names_the_pid_it_replaces(tmp_path, darwin, popen_calls):
    """The new build is launched BEFORE this one exits (it has to be:
    request_shutdown() comes after the spawn, so a failed launch can still
    roll the whole swap back). For those few seconds there really are two
    companions, and app.py's posix single-instance guard -- a pid file with a
    LIVENESS check -- would refuse the newcomer and leave the machine with NO
    companion until the next login. This is what tells the child whose pid it
    may briefly wait for."""
    exe = tmp_path / "ccsync-companion"

    UpgradeManager._default_spawn(exe)

    (_argv, kwargs), = popen_calls
    assert kwargs["env"]["CCSYNC_REPLACES_PID"] == str(os.getpid())


def test_the_replaced_pid_is_set_on_windows_too(tmp_path, windows, popen_calls):
    """Load-bearing since R11: the win32 mutex guard waits for exactly this
    pid. Before that it was merely one less thing to be platform-conditional
    about -- the mutex is NOT released the instant the predecessor dies from
    the child's point of view; the child reaches the guard while the
    predecessor is still tearing down lanes."""
    exe = tmp_path / "ccsync-companion.exe"

    UpgradeManager._default_spawn(exe)

    (_argv, kwargs), = popen_calls
    assert kwargs["env"]["CCSYNC_REPLACES_PID"] == str(os.getpid())


def test_the_spawn_returns_the_child_it_launched(tmp_path, darwin, popen_calls):
    """R11 belt-and-braces: _apply_inner watches this handle -- a child that
    dies inside the grace window rolls the swap back instead of the parent
    standing down over a corpse."""
    exe = tmp_path / "ccsync-companion"

    child = UpgradeManager._default_spawn(exe)

    assert child is not None


# ======================================================================
# COMMERCIAL_READINESS.md item 4 (2026-08-17): the signed upgrade channel,
# the monotonic downgrade floor, and the transport rules.
# ======================================================================


def test_a_valid_signature_is_accepted_and_names_the_key():
    ok, detail = upgrade_mod.verify_offer(_info())
    assert ok
    assert detail == release_pubkey.pubkey_id(TEST_PUBKEY)


def test_an_offer_signed_by_an_untrusted_key_is_refused(tmp_path):
    """The whole point: a dashboard that can serve bytes still cannot mint an
    offer this build will install."""
    info = _info(seed=OTHER_SEED)
    ok, detail = upgrade_mod.verify_offer(info)
    assert not ok and "no baked release key" in detail

    mgr = UpgradeManager(_cfg(), http_open=_fake_open(b"new-exe-bytes"))
    mgr.note_report_response({"upgrade": info})
    assert mgr.available is None
    assert mgr.download_and_verify(info, tmp_path) is None
    assert _no_download_left(tmp_path)


def test_an_unsigned_offer_is_refused_with_no_fallback(tmp_path, caplog):
    """A pre-signing dashboard advertises version/url/sha256 and nothing
    else. That used to be enough to rename a download over the running exe."""
    info = _info(sign=False)
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(b"new-exe-bytes"))
    with caplog.at_level("ERROR"):
        mgr.note_report_response({"upgrade": info})
    assert mgr.available is None
    assert "REFUSING" in caplog.text
    assert mgr.download_and_verify(info, tmp_path) is None


@pytest.mark.parametrize("field, value", [
    ("version", "6.6.6"),
    ("sha256", "b" * 64),
    ("filename", "ccsync-onboard-9.9.9.exe"),
    ("platform", "macos"),
    ("kind", "onboard"),
    ("size_bytes", 999),
    ("min_version", "1.2.3"),
    ("published_at", "2020-01-01T00:00:00Z"),
    ("signed_binary", True),
])
def test_tampering_with_any_signed_field_invalidates_the_offer(field, value):
    """Signing only the sha256 would leave the server free to re-label a
    genuine build -- which is how a Mac gets handed a Windows exe."""
    info = _info()
    info[field] = value
    ok, _detail = upgrade_mod.verify_offer(info)
    assert not ok


def test_a_corrupt_signature_never_raises():
    for bad in (None, "", "not-base64!!", "AAAA", 12345):
        ok, _detail = upgrade_mod.verify_offer({**_info(), "signature": bad})
        assert not ok
    assert upgrade_mod.verify_offer("garbage") == (False, "no offer")


def test_a_build_with_no_baked_key_installs_nothing(monkeypatch):
    """Fail closed: a companion built without RELEASE_PUBKEYS trusts nobody
    rather than everybody. tools/release.ps1 refuses to build one."""
    monkeypatch.setattr(release_pubkey, "RELEASE_PUBKEYS", ())
    ok, detail = upgrade_mod.verify_offer(_info())
    assert not ok and "trusts no release key" in detail


def test_the_sha256_checked_after_download_is_the_signed_one(tmp_path):
    """The old sha256 came from the same response as the url, so it proved
    only that the server got what it asked for. Now it is a signed value: a
    body that does not match it is discarded even though the offer verified."""
    info = _info(body=b"the-signed-build")
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(b"something-else"))
    assert mgr.download_and_verify(info, tmp_path) is None
    assert _no_download_left(tmp_path)


# -- the downgrade floor ------------------------------------------------


def test_the_floor_is_remembered_and_only_ever_rises(tmp_path):
    floor = tmp_path / "upgrade_floor.json"
    assert upgrade_mod.read_floor(floor) == ""
    assert upgrade_mod.note_floor(floor, "0.7.11") == "0.7.11"
    assert upgrade_mod.read_floor(floor) == "0.7.11"
    # A LOWER min_version cannot lower it -- otherwise replaying one old,
    # genuinely-signed record undoes the whole mechanism.
    assert upgrade_mod.note_floor(floor, "0.5.0") == "0.7.11"
    assert upgrade_mod.note_floor(floor, "0.8.0") == "0.8.0"
    assert json.loads(floor.read_text())["min_version"] == "0.8.0"


def test_an_unparseable_or_missing_floor_is_no_floor(tmp_path):
    floor = tmp_path / "upgrade_floor.json"
    floor.write_text("{not json", encoding="utf-8")
    assert upgrade_mod.read_floor(floor) == ""
    floor.write_text(json.dumps({"min_version": "nightly"}), encoding="utf-8")
    assert upgrade_mod.read_floor(floor) == ""
    assert upgrade_mod.note_floor(floor, None) == ""


def test_note_floor_never_raises_on_an_unwritable_path(tmp_path):
    blocked = tmp_path / "a-file"
    blocked.write_text("x", encoding="utf-8")
    assert upgrade_mod.note_floor(blocked / "nested" / "floor.json", "1.0.0") == "1.0.0"


def test_below_floor_refuses_anything_it_cannot_rank():
    assert upgrade_mod.below_floor("0.7.10", "0.7.11")
    assert not upgrade_mod.below_floor("0.7.11", "0.7.11")
    assert not upgrade_mod.below_floor("0.9.0", "0.7.11")
    assert upgrade_mod.below_floor("nightly", "0.7.11")
    # No floor at all ranks nothing.
    assert not upgrade_mod.below_floor("nightly", "")


def test_an_offer_below_the_remembered_floor_is_refused(tmp_path, caplog):
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(b"new-exe-bytes"),
                         floor_file=tmp_path / "floor.json")
    # A signed 9.9.9 asserting "never go below 9.9.9" raises the floor.
    mgr.note_report_response({"upgrade": _info(version="9.9.9", min_version="9.9.9")})
    assert mgr.available["version"] == "9.9.9"
    assert upgrade_mod.read_floor(tmp_path / "floor.json") == "9.9.9"

    # A later, genuinely-signed rollback offer below it is refused -- and the
    # standing offer is cleared with it.
    older = _info(version="1.0.0", min_version="0.0.0")
    with caplog.at_level("ERROR"):
        mgr.note_report_response({"upgrade": older})
    assert mgr.available is None
    assert "downgrade floor" in caplog.text
    assert mgr.download_and_verify(older, tmp_path) is None


def test_a_rollback_at_or_above_the_floor_is_still_offered(tmp_path):
    """Different, not newer survives ABOVE the floor: a deliberate rollback
    stays one click, which is the property the floor must not cost."""
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(b"new-exe-bytes"),
                         floor_file=tmp_path / "floor.json")
    mgr.note_report_response({"upgrade": _info(version="9.9.9", min_version="1.0.0")})
    mgr.note_report_response({"upgrade": _info(version="1.0.0", min_version="1.0.0")})
    assert mgr.available["version"] == "1.0.0"
    assert upgrade_mod.offer_label("1.0.0", running="9.9.9").startswith("Roll back")


def test_the_floor_file_lives_beside_the_config_not_in_state(tmp_path, monkeypatch):
    """Documented location: ~/.ccsync/upgrade_floor.json. state/ is lane
    scratch that anything may delete; the floor may not be."""
    monkeypatch.undo()   # drop the autouse floor_path patch for this one
    cfg = {"log_path": str(tmp_path / "logs" / "companion.log")}
    assert upgrade_mod.floor_path(cfg) == tmp_path / "logs" / "upgrade_floor.json"


# -- transport ----------------------------------------------------------


@pytest.mark.parametrize("url", [
    "https://dash.example.com",
    "https://nas.example.ts.net",
    "http://100.64.0.1:8480",      # tailnet CGNAT: today's whole fleet
    "http://192.168.0.10:8480",     # LAN
    "http://127.0.0.1:8480",
    "http://localhost:8480",
    "http://truenas:8480",           # single-label intranet name
    "http://nas.local",
    "http://nas.lan:8480",
])
def test_allowed_update_origins(url):
    ok, _note = upgrade_mod.transport_ok(url)
    assert ok


@pytest.mark.parametrize("url", [
    "http://dash.example.com",       # cleartext to a public name
    "http://8.8.8.8",
    "ftp://dash.example.com",
    "",
    None,
])
def test_refused_update_origins(url):
    ok, note = upgrade_mod.transport_ok(url)
    assert not ok and note


def test_plain_http_on_the_tailnet_is_allowed_but_logged_once(tmp_path, caplog):
    mgr = UpgradeManager(_cfg(), http_open=_fake_open(b"new-exe-bytes"))
    with caplog.at_level("WARNING"):
        assert mgr.download_and_verify(_info(), tmp_path) is not None
        assert mgr.download_and_verify(_info(), tmp_path) is not None
    assert caplog.text.count("plain HTTP (tailnet/LAN)") == 1


def test_a_public_cleartext_dashboard_downloads_nothing(tmp_path, caplog):
    mgr = UpgradeManager(_cfg(dashboard_url="http://dash.example.com"),
                         http_open=_fake_open(b"new-exe-bytes"))
    with caplog.at_level("ERROR"):
        assert mgr.download_and_verify(
            _info(url="http://dash.example.com/api/v1/x"), tmp_path) is None
    assert "plain HTTP to a PUBLIC host" in caplog.text


def test_https_needs_no_advisory(tmp_path, caplog):
    mgr = UpgradeManager(_cfg(dashboard_url="https://nas.example.ts.net"),
                         http_open=_fake_open(b"new-exe-bytes"))
    with caplog.at_level("WARNING"):
        assert mgr.download_and_verify(_info(), tmp_path) is not None
    assert "plain HTTP" not in caplog.text


# -- the two copies of the primitives ----------------------------------


def test_the_dashboard_carries_an_identical_ed25519_copy():
    """ed25519.py is duplicated into the dashboard package on purpose (they
    are different deployment units). Drift between them means a build the
    dashboard accepts and the fleet refuses, discovered at ship time."""
    here = Path(upgrade_mod.__file__).resolve().parent
    theirs = here.parents[2] / "dashboard" / "src" / "ccsync_dashboard" / "ed25519.py"
    if not theirs.is_file():
        pytest.skip("no dashboard checkout beside this one")
    assert theirs.read_bytes() == (here / "ed25519.py").read_bytes()
