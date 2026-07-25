"""Self-upgrade tests: the availability state machine, download+verify, and
the rename-swap in apply() with injected replace/spawn recorders -- in the
never-raise style of test_reporter.py."""
from __future__ import annotations

import hashlib
import io
import os
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

    base = "http://100.71.216.3:8480"
    assert same_origin("/api/v1/packages/ccsync-companion-0.4.5.exe", base) is True
    assert same_origin("http://100.71.216.3:8480/x.exe", base) is True
    assert same_origin("http://evil.example.com/payload.exe", base) is False
    assert same_origin("https://100.71.216.3:8480/x.exe", base) is False  # scheme differs
    assert same_origin("http://100.71.216.3:9999/x.exe", base) is False   # port differs
    assert same_origin("", base) is False


def test_download_refuses_a_foreign_host(tmp_path):
    opened = []

    def spy_open(url, headers, timeout):
        opened.append(url)
        raise AssertionError("must never be fetched")

    mgr = UpgradeManager({"dashboard_url": "http://100.71.216.3:8480"}, http_open=spy_open)
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
