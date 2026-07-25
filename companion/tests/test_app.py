"""CompanionApp.scan_whole_project tests — resolve_bridge and popup.show_popup
are monkeypatched so nothing here touches a real Resolve instance or opens a
real Tk window (headless CI-safe, same ethos as test_watcher.py)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from ccsync_companion import popup, resolve_bridge
from ccsync_companion.app import CompanionApp


def _make_local_root(tmp_path) -> str:
    """local_root must EXIST: validate_config flags a missing one as an error
    that stops syncing, and since 0.4.5 an error genuinely does stop the
    lanes (DEL-3) and suppress the out-of-tree popup (CORE-H1). A test config
    pointing at a directory that was never created is a misconfigured
    install, not a working one."""
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)

def _cfg(tmp_path, **overrides) -> dict[str, Any]:
    cfg = {
        "editor_name": "alex",
        "local_root": _make_local_root(tmp_path),
        "canonical_prefix": "P:\\",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/Creators_Club",
        "active_project": "",
        "poll_interval": 3,
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "",
        "popup_enabled": True,
        "sync_enabled": False,  # keep lane construction inert for these tests
        "lane_b_enabled": False,
    }
    cfg.update(overrides)
    return cfg


def _make_app(tmp_path, **overrides) -> CompanionApp:
    return CompanionApp(_cfg(tmp_path, **overrides))


def _mp_result(*items, ok=True, message="", project_name="MyProject"):
    return {"ok": ok, "message": message, "items": list(items), "project_name": project_name}


class _FakeProgressWindow:
    """Headless stand-in for popup.ProgressWindow: runs the worker inline,
    never touches Tk. consolidate_project() builds the real one internally,
    so a test that didn't patch this opened an actual "COPYING THIS
    PROJECT'S MEDIA IN" window on the developer's desktop mid-run (caught by
    conftest._no_real_tk_windows, 2026-07-25)."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        self.title = title
        self.subtitle = subtitle
        self.published: list[dict] = []
        self._stop_requested = False

    def publish(self, info: dict) -> None:
        self.published.append(dict(info))

    def should_stop(self) -> bool:
        return self._stop_requested

    def run(self, worker) -> None:
        worker(self.publish, self.should_stop)


class _FakeTray:
    def __init__(self):
        self.notifications: list[tuple[str, str]] = []

    def notify(self, msg, title):
        self.notifications.append((msg, title))


def _item(file_path, clip_name="clip", project_name="MyProject"):
    return {
        "file_path": file_path,
        "media_pool_item": object(),
        "clip_name": clip_name,
        "resolve_project_name": project_name,
    }


# -- classification / filtering ---------------------------------------------


def test_scan_whole_project_shows_popup_for_out_of_tree_items(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "in_tree.mov").touch()
    in_tree = _item(str(root / "in_tree.mov"))

    other = tmp_path / "other"
    other.mkdir()
    (other / "out_of_tree.mov").touch()
    out_of_tree = _item(str(other / "out_of_tree.mov"))

    # popup_enabled=False must NOT suppress the manual scan (unlike the
    # passive watcher path).
    app = _make_app(tmp_path, popup_enabled=False)
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                         lambda: _mp_result(in_tree, out_of_tree))

    captured = {}

    def fake_show_popup(items, local_root, editor_name, ignore_tracker, project_prefix="", server_roots=None):
        captured["items"] = items
        captured["local_root"] = local_root
        captured["server_roots"] = server_roots

    monkeypatch.setattr(popup, "show_popup", fake_show_popup)

    app.scan_whole_project()

    assert "items" in captured
    paths = [item["file_path"] for item in captured["items"]]
    assert paths == [str(other / "out_of_tree.mov")]
    assert captured["local_root"] == str(root)


def test_scan_whole_project_skips_ignored_paths(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    ignored_path = other / "ignored.mov"
    ignored_path.touch()
    fresh_path = other / "fresh.mov"
    fresh_path.touch()

    app = _make_app(tmp_path)
    app.ignore_tracker.ignore(str(ignored_path))

    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(_item(str(ignored_path)), _item(str(fresh_path))),
    )

    captured = {}
    monkeypatch.setattr(
        popup, "show_popup",
        lambda items, *a, **kw: captured.__setitem__("items", items),
    )

    app.scan_whole_project()
    paths = [item["file_path"] for item in captured["items"]]
    assert paths == [str(fresh_path)]


def test_scan_whole_project_does_not_apply_popup_snooze(tmp_path, monkeypatch):
    """Unlike _handle_out_of_tree, a manual scan must show items even if
    they were shown (and dismissed) very recently."""
    other = tmp_path / "other"
    other.mkdir()
    path = other / "clip.mov"
    path.touch()

    app = _make_app(tmp_path)
    # Simulate this path having just been shown by the passive watcher.
    import time

    from ccsync_companion.watcher import _norm_key
    app._popup_snooze[_norm_key(str(path))] = time.monotonic()

    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                         lambda: _mp_result(_item(str(path))))

    captured = {}
    monkeypatch.setattr(
        popup, "show_popup",
        lambda items, *a, **kw: captured.__setitem__("items", items),
    )

    app.scan_whole_project()
    assert len(captured["items"]) == 1


def test_scan_whole_project_all_in_tree_notifies_and_skips_popup(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "in_tree.mov").touch()
    in_tree = _item(str(root / "in_tree.mov"))

    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items", lambda: _mp_result(in_tree))

    called = []
    monkeypatch.setattr(popup, "show_popup", lambda *a, **kw: called.append(True))

    app.scan_whole_project()
    assert called == []
    assert any("all media is in the tree" in msg for msg, _title in app._tray_icon.notifications)


def test_scan_whole_project_not_ok_logs_and_notifies(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(ok=False, message="DaVinci Resolve is not running"),
    )

    called = []
    monkeypatch.setattr(popup, "show_popup", lambda *a, **kw: called.append(True))

    app.scan_whole_project()
    assert called == []
    assert any("not running" in msg for msg, _title in app._tray_icon.notifications)


def test_scan_whole_project_no_tray_icon_does_not_raise(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    assert app._tray_icon is None
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(ok=False, message="no project open in Resolve"),
    )
    app.scan_whole_project()  # must not raise


# -- server_roots pass-through ------------------------------------------


def test_scan_whole_project_passes_server_roots_through(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    path = other / "clip.mov"
    path.touch()

    app = _make_app(tmp_path, dashboard_url="http://dash.example.com")
    assert app.selection_client is not None
    monkeypatch.setattr(
        app.selection_client, "project_roots_result",
        lambda: ({"myproject": "Projects/2026/FF5/Nuclear"}, "live"),
    )

    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                         lambda: _mp_result(_item(str(path))))

    captured = {}
    monkeypatch.setattr(
        popup, "show_popup",
        lambda items, local_root, editor_name, ignore_tracker, project_prefix="", server_roots=None:
        captured.__setitem__("server_roots", server_roots),
    )

    app.scan_whole_project()
    assert captured["server_roots"] == {"myproject": "Projects/2026/FF5/Nuclear"}


def test_scan_whole_project_refuses_when_project_roots_are_unreachable(tmp_path, monkeypatch):
    """INVERTED 2026-07-25 (AUDIT_2 CORE-H9). This used to assert that an
    unreachable dashboard "falls back to None" -- which means falling through
    to fixer.match_project_dir's token-overlap GUESS, so the same clip gets a
    different destination than it had five minutes earlier, silently, and
    gigabytes get filed under a guessed root and uploaded there.

    "No mapping exists" and "we couldn't ask" are different answers and must
    not share a return value. On unreachable we now refuse and say so."""
    other = tmp_path / "other"
    other.mkdir()
    path = other / "clip.mov"
    path.touch()

    app = _make_app(tmp_path, dashboard_url="http://dash.example.com")
    tray = _FakeTray()
    app._tray_icon = tray

    def boom():
        raise RuntimeError("dashboard unreachable")

    monkeypatch.setattr(app.selection_client, "project_roots_result", boom)
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                         lambda: _mp_result(_item(str(path))))

    shown = []
    monkeypatch.setattr(popup, "show_popup", lambda *a, **kw: shown.append(True))

    app.scan_whole_project()
    assert shown == []
    assert any("Can't reach the server" in msg for msg, _title in tray.notifications)


def test_scan_whole_project_uses_the_cached_mapping_when_the_dashboard_is_down(
    tmp_path, monkeypatch
):
    """A CACHED mapping is still an answer -- only "unreachable with nothing
    cached" blocks."""
    other = tmp_path / "other"
    other.mkdir()
    path = other / "clip.mov"
    path.touch()

    app = _make_app(tmp_path, dashboard_url="http://dash.example.com")
    monkeypatch.setattr(
        app.selection_client, "project_roots_result",
        lambda: ({"myproject": "Projects/2026/FF5/Nuclear"}, "cache"),
    )
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                         lambda: _mp_result(_item(str(path))))

    captured = {}
    monkeypatch.setattr(
        popup, "show_popup",
        lambda items, local_root, editor_name, ignore_tracker, project_prefix="", server_roots=None:
        captured.__setitem__("server_roots", server_roots),
    )

    app.scan_whole_project()
    assert captured["server_roots"] == {"myproject": "Projects/2026/FF5/Nuclear"}


def test_selection_client_editor_name_fn_wired_to_editor_identity(tmp_path):
    # Selection identity finding: SelectionClient must re-evaluate the
    # editor name per fetch via app.editor_identity(), so a tray sign-in
    # redirects which editor's tick list gets fetched instead of staying
    # pinned to the raw config editor_name forever.
    app = _make_app(
        tmp_path, dashboard_url="http://dash.example.com", editor_name="config-name",
        require_login=False,
    )
    assert app.selection_client is not None
    assert app.selection_client._editor_name_fn() == "config-name"

    app.identity._identity = {
        "username": "verified-user",
        # v2.identity.<base64url(username), no padding>.<expires_epoch>.<sig>
        # -- see identity.py's parse_token().
        "token": "v2.identity.dmVyaWZpZWQtdXNlcg.99999999999.deadbeef",
        "role": None,
    }
    assert app.selection_client._editor_name_fn() == "verified-user"


# -- concurrent-popup guard ------------------------------------------


def test_scan_whole_project_skips_when_popup_already_active(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    path = other / "clip.mov"
    path.touch()

    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                         lambda: _mp_result(_item(str(path))))

    called = []
    monkeypatch.setattr(popup, "show_popup", lambda *a, **kw: called.append(True))

    app._popup_active_lock.acquire()
    try:
        app.scan_whole_project()
    finally:
        app._popup_active_lock.release()

    assert called == []
    assert any("already open" in msg for msg, _title in app._tray_icon.notifications)


def test_handle_out_of_tree_and_scan_whole_project_share_the_lock(tmp_path, monkeypatch):
    """Both popup entry points must be guarded by the same lock instance."""
    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()

    other = tmp_path / "other"
    other.mkdir()
    path = other / "clip.mov"
    path.touch()

    called = []
    monkeypatch.setattr(popup, "show_popup", lambda *a, **kw: called.append(True))

    app._popup_active_lock.acquire()
    try:
        app._handle_out_of_tree([_item(str(path))])
    finally:
        app._popup_active_lock.release()

    assert called == []
    assert any("already open" in msg for msg, _title in app._tray_icon.notifications)


# -- existing _handle_out_of_tree gating is unaffected -----------------------


def test_handle_out_of_tree_still_gates_on_popup_enabled(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    path = other / "clip.mov"
    path.touch()

    app = _make_app(tmp_path, popup_enabled=False)
    called = []
    monkeypatch.setattr(popup, "show_popup", lambda *a, **kw: called.append(True))

    app._handle_out_of_tree([_item(str(path))])
    assert called == []


def test_handle_out_of_tree_still_applies_snooze(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    path = other / "clip.mov"
    path.touch()

    app = _make_app(tmp_path)
    called = []
    monkeypatch.setattr(popup, "show_popup", lambda *a, **kw: called.append(True))

    app._handle_out_of_tree([_item(str(path))])
    assert len(called) == 1

    # Second call for the same (freshly-snoozed) path should be suppressed.
    app._handle_out_of_tree([_item(str(path))])
    assert len(called) == 1


# -- consolidate_project ----------------------------------------------------


def test_consolidate_project_confirm_flow(tmp_path, monkeypatch):
    from ccsync_companion import consolidate

    root = tmp_path / "root"
    root.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    stray = other / "A001.braw"
    stray.write_bytes(b"x" * 100)
    item = _item(str(stray), project_name="CCT Creator Profiles")

    # sync_enabled + a resolvable active_project are both now REQUIRED for
    # consolidate to do anything: it runs real rclone lanes, so it respects
    # the same gates every other sync path does (CORE-M13), and a blank
    # active_project with no server-root mapping means subpath is None, which
    # would build `rclone copy <the whole local_root>` (CORE-C2).
    app = _make_app(tmp_path, popup_enabled=False, sync_enabled=True,
                    active_project="Projects/2026/Creator Profiles/Season 1")
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: _mp_result(item, project_name="CCT Creator Profiles"))
    # no NAS in tests: stub the dry-run reconcile
    monkeypatch.setattr(consolidate, "reconcile_with_nas",
                        lambda cfg, subpath, sd, **kw: {"ok": True,
                        "uploads": {"count": 1, "bytes": 100, "objects": []},
                        "downloads": {"count": 0, "bytes": 0, "objects": []}})
    seen = {}
    monkeypatch.setattr("ccsync_companion.popup.confirm_dialog",
                        lambda title, body, ok_label="": seen.setdefault("report", body) or True)
    monkeypatch.setattr(popup, "ProgressWindow", _FakeProgressWindow)
    # capture the actual copy + lane runs
    copies = []
    monkeypatch.setattr(consolidate, "run_consolidation",
                        lambda ops, lr, **kw: copies.extend(ops) or
                        [{"ok": True, "message": "ok", "file_path": o["file_path"]} for o in ops])
    lane_calls = []
    app._lane_a.run_once = lambda subpath=None: lane_calls.append(("a", subpath))
    app._lane_b.run_once = lambda subpath=None: lane_calls.append(("b", subpath))

    app.consolidate_project()

    assert "scattered clip" in seen["report"]
    assert len(copies) == 1 and copies[0]["file_path"] == str(stray)
    # lane A always runs after consolidation; lane B skipped (lane_b_enabled False)
    assert ("a", None) in lane_calls or any(c[0] == "a" for c in lane_calls)
    assert not any(c[0] == "b" for c in lane_calls)


def test_consolidate_project_cancel_does_nothing(tmp_path, monkeypatch):
    from ccsync_companion import consolidate

    other = tmp_path / "other"
    other.mkdir()
    stray = other / "A001.braw"
    stray.write_bytes(b"x" * 10)
    item = _item(str(stray))

    app = _make_app(tmp_path, sync_enabled=True, active_project="Projects/2026/X/Y")
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items", lambda: _mp_result(item))
    monkeypatch.setattr(consolidate, "reconcile_with_nas",
                        lambda *a, **k: {"ok": True, "uploads": {"count": 5, "bytes": 5},
                                         "downloads": {"count": 0, "bytes": 0}})
    monkeypatch.setattr("ccsync_companion.popup.confirm_dialog", lambda *a, **k: False)
    ran = []
    monkeypatch.setattr(consolidate, "run_consolidation", lambda *a, **k: ran.append(1) or [])
    app._lane_a.run_once = lambda subpath=None: ran.append("a")

    app.consolidate_project()
    assert ran == []  # cancel = no copies, no upload


# -- upgrade channel / role-reporting wiring ---------------------------------


def test_reporter_reports_effective_mode_not_raw_config(tmp_path):
    """Regression: the reporter used to be wired to the raw config `mode`, so
    a base-role sign-in behaved as base but *reported* editor. It must use
    effective_mode() (identity role wins)."""
    app = _make_app(tmp_path, mode="editor")
    app.identity._identity = {
        "username": "alex",
        # v2.identity.<base64url(username), no padding>.<expires_epoch>.<sig>
        # -- see identity.py's parse_token().
        "token": "v2.identity.YWxleA.99999999999.deadbeef",
        "role": "base",
    }
    assert app.effective_mode() == "base"
    payload = app.reporter._build_payload(editor_name="alex")
    assert payload["mode"] == "base"


def test_reporter_response_feeds_upgrade_manager(tmp_path):
    app = _make_app(tmp_path)
    assert app.reporter._on_report_response is not None
    app.reporter._on_report_response({
        "ok": True,
        "upgrade": {"version": "9.9.9", "url": "/x", "sha256": "a" * 64},
    })
    assert app.upgrade.available["version"] == "9.9.9"


def test_report_response_fans_out_to_project_setup(tmp_path):
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com")
    assert app.project_setup is not None
    # CompanionApp builds its ProjectSetupPrompter with the REAL
    # popup.confirm_dialog and webbrowser.open (defaults bound at class
    # definition, so monkeypatching the popup module cannot reach them).
    # Un-injected, this test opened an actual "NEW PROJECT — Project 'New
    # Doc' isn't set up on the server" Tk window on the developer's desktop
    # mid-run -- indistinguishable from the live bug it was meant to guard,
    # and it cost a day of chasing (2026-07-25).
    confirmed: list[tuple] = []
    opened: list[str] = []
    app.project_setup._confirm = lambda *a, **k: confirmed.append(a) or False
    app.project_setup._open_url = opened.append
    app._on_report_response({"ok": True, "resolve_project_unmapped": "New Doc"})
    import time as _t
    deadline = _t.monotonic() + 2
    while _t.monotonic() < deadline and app.setup_project_available() != "New Doc":
        _t.sleep(0.01)
    assert app.setup_project_available() == "New Doc"


def test_report_response_fanout_isolates_failures(tmp_path):
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com")

    def boom(resp):
        raise RuntimeError("boom")

    app.upgrade.note_report_response = boom
    app._on_report_response({"ok": True})  # must not raise


# -- editor_identity(): blank editor_name must not report (S-15) -----------


def test_editor_identity_returns_none_for_blank_editor_name_when_require_login_false(tmp_path):
    app = _make_app(tmp_path, editor_name="", require_login=False)
    assert app.editor_identity() is None


def test_editor_identity_returns_none_for_whitespace_editor_name_when_require_login_false(tmp_path):
    app = _make_app(tmp_path, editor_name="   ", require_login=False)
    assert app.editor_identity() is None


def test_editor_identity_returns_configured_name_when_require_login_false(tmp_path):
    app = _make_app(tmp_path, editor_name="alex", require_login=False)
    assert app.editor_identity() == "alex"


def test_project_setup_absent_in_legacy_mode(tmp_path):
    app = _make_app(tmp_path, dashboard_url="")
    assert app.project_setup is None
    assert app.setup_project_available() is None
    app.setup_current_project()  # no-op, no raise


# -- module-level run(): logging/validation before construction (S-10) ------


def test_run_sets_up_logging_and_validates_before_constructing_app(monkeypatch, tmp_path):
    from ccsync_companion import app as app_mod

    order: list[str] = []
    cfg = _cfg(tmp_path)

    monkeypatch.setattr(app_mod.config_mod, "load_config", lambda: cfg)
    monkeypatch.setattr(app_mod, "setup_logging", lambda c: order.append("setup_logging"))

    real_validate = app_mod.config_mod.validate_config

    def spy_validate(c):
        order.append("validate_config")
        return real_validate(c)

    monkeypatch.setattr(app_mod.config_mod, "validate_config", spy_validate)

    class FakeApp:
        def __init__(self, c):
            order.append("construct")

        def run(self):
            order.append("run")

    monkeypatch.setattr(app_mod, "CompanionApp", FakeApp)

    app_mod.run()

    assert order.index("setup_logging") < order.index("construct")
    assert order.index("validate_config") < order.index("construct")
    assert order[-1] == "run"


def test_run_logs_and_reraises_when_construction_raises(monkeypatch, tmp_path, caplog):
    from ccsync_companion import app as app_mod

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(app_mod.config_mod, "load_config", lambda: cfg)
    monkeypatch.setattr(app_mod, "setup_logging", lambda c: None)
    # CORE-M7 added a single-instance guard ahead of construction; a live
    # companion on the developer's own machine would otherwise make run()
    # return before it ever builds the app.
    monkeypatch.setattr(app_mod, "acquire_single_instance", lambda: True)

    class BoomApp:
        def __init__(self, c):
            raise RuntimeError("bad config value, e.g. poll_interval='fast'")

    monkeypatch.setattr(app_mod, "CompanionApp", BoomApp)

    with caplog.at_level(logging.ERROR, logger="ccsync.app"):
        with pytest.raises(RuntimeError):
            app_mod.run()

    assert any("crashed" in r.message for r in caplog.records)


# -- CompanionApp.run(): tray-start failure must not skip shutdown (S-11) ---


def test_run_tray_start_non_import_error_still_runs_shutdown(tmp_path, monkeypatch):
    from ccsync_companion import tray as tray_mod

    app = _make_app(tmp_path)  # sync_enabled=False -> _start_lanes() is inert
    app.start = lambda: None  # skip real watcher/reporter/manifest threads

    shutdown_calls = []
    real_shutdown = app.shutdown

    def spy_shutdown():
        shutdown_calls.append(True)
        real_shutdown()

    app.shutdown = spy_shutdown

    def boom(_app):
        # Let run()'s wait loop exit immediately once we're past the tray
        # try/except -- this stands in for whatever eventually sets it in
        # a real run (KeyboardInterrupt / shutdown()).
        app._stop_event.set()
        raise OSError("tray backend unavailable (no display)")

    monkeypatch.setattr(tray_mod, "start_tray", boom)

    app.run()  # must not raise

    assert app._tray_icon is None
    assert shutdown_calls, "shutdown() must still run after a non-ImportError tray failure"


# -- toggle_pause: legacy mode must respect lane_b_enabled (finding) --------


def test_toggle_pause_legacy_mode_skips_lane_b_on_resume_when_disabled(tmp_path):
    app = _make_app(tmp_path, dashboard_url="", sync_enabled=True, lane_b_enabled=False)
    assert app._managed is False

    started: list[str] = []
    stopped: list[str] = []
    for lane in app.lanes:
        def _start(name=lane.name):
            started.append(name)

        def _stop(name=lane.name):
            stopped.append(name)

        lane.start = _start
        lane.stop = _stop

    app.toggle_pause()  # pause -> _stop_lanes()
    assert app.is_paused() is True
    assert set(stopped) == {lane.name for lane in app.lanes}

    started.clear()
    app.toggle_pause()  # resume -> _start_lanes()
    assert app.is_paused() is False
    assert "lane_a_video_up" in started
    assert "lane_b_proxy_down" not in started  # lane_b_enabled=False


# -- managed _stop_lanes must also stop lane A (finding) --------------------


def test_stop_lanes_managed_mode_stops_lane_a_too(tmp_path):
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com", sync_enabled=True)
    assert app._managed is True

    stopped: list[str] = []
    app._lane_a.stop = lambda: stopped.append("lane_a")
    app._lane_c.stop = lambda: stopped.append("lane_c")
    if app.sequencer is not None:
        app.sequencer.stop = lambda: stopped.append("sequencer")

    app._stop_lanes()

    assert "lane_a" in stopped
    assert "lane_c" in stopped


# -- _refresh_media_tree_once must skip ignored_resolve_projects (X-7) ------


def test_refresh_media_tree_once_skips_ignored_project(tmp_path, monkeypatch):
    app = _make_app(tmp_path, ignored_resolve_projects=["Untitled Project", "New Doc"])
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(_item("clip.mov"), project_name="Untitled Project"),
    )
    app._refresh_media_tree_once()
    assert app.get_media_tree() == {}


def test_refresh_media_tree_once_is_case_insensitive_for_ignored_project(tmp_path, monkeypatch):
    app = _make_app(tmp_path, ignored_resolve_projects=["New Doc"])
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(_item("clip.mov"), project_name="  NEW DOC  "),
    )
    app._refresh_media_tree_once()
    assert app.get_media_tree() == {}


@pytest.mark.parametrize("project_name", ["New Doc 1", "New Doc 2", "new doc (7)"])
def test_refresh_media_tree_once_skips_numbered_scratch_duplicates(
    tmp_path, monkeypatch, project_name
):
    """Same prefix rule the watcher uses: the Proxy Generator's helper
    project numbers itself up, and every new number used to be reported as a
    real project's media tree."""
    app = _make_app(tmp_path, ignored_resolve_projects=["Untitled Project", "New Doc"])
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(_item("clip.mov"), project_name=project_name),
    )
    app._refresh_media_tree_once()
    assert app.get_media_tree() == {}


def test_refresh_media_tree_once_keeps_a_real_project_with_a_similar_name(
    tmp_path, monkeypatch
):
    app = _make_app(tmp_path, ignored_resolve_projects=["New Doc"])
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(_item("clip.mov"), project_name="New Doc Final"),
    )
    app._refresh_media_tree_once()
    assert "New Doc Final" in app.get_media_tree()


def test_refresh_media_tree_once_keeps_non_ignored_project(tmp_path, monkeypatch):
    app = _make_app(tmp_path, ignored_resolve_projects=["Untitled Project"])
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(_item("clip.mov"), project_name="Real Project"),
    )
    app._refresh_media_tree_once()
    assert "Real Project" in app.get_media_tree()


# ===========================================================================
# AUDIT_2 round-2 regressions
# ===========================================================================


# -- CORE-C2: consolidate must not run a whole-tree lane A -------------------


def test_consolidate_refuses_a_blank_active_project_and_never_runs_lane_a(
    tmp_path, monkeypatch
):
    """AUDIT_2 CORE-C2 [verified]. D-2's fix made reconcile_with_nas hard-abort
    on a None subpath, but app.py then called self._lane_a.run_once(subpath)
    UNCONDITIONALLY with that same None -- which builds
    `rclone copy <the whole local_root>` to the NAS. The dialog read
    "(could not check the NAS: no active project resolved -- refusing
    whole-tree consolidate)" and STILL offered the button; clicking it
    uploaded every file under local_root, unquantified and unmentioned by
    the consent the user gave.

    The audit notes there was no test for this case at all.
    """
    from ccsync_companion import consolidate

    other = tmp_path / "other"
    other.mkdir()
    stray = other / "A001.braw"
    stray.write_bytes(b"x" * 10)

    # Blank active_project AND no server-root mapping -> subpath is None.
    app = _make_app(tmp_path, sync_enabled=True, active_project="", popup_enabled=False)
    tray = _FakeTray()
    app._tray_icon = tray

    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: _mp_result(_item(str(stray)), project_name="Whatever"))

    ran: list[str] = []
    monkeypatch.setattr(consolidate, "reconcile_with_nas",
                        lambda *a, **k: ran.append("reconcile") or {"ok": False, "error": "x"})
    monkeypatch.setattr("ccsync_companion.popup.confirm_dialog",
                        lambda *a, **k: ran.append("dialog") or True)
    monkeypatch.setattr(consolidate, "run_consolidation",
                        lambda *a, **k: ran.append("copy") or [])
    app._lane_a.run_once = lambda subpath=None: ran.append(f"lane_a:{subpath}")
    app._lane_b.run_once = lambda subpath=None: ran.append(f"lane_b:{subpath}")

    app.consolidate_project()

    assert ran == [], "nothing may run without a resolved project subpath"
    assert any("can't tell which project" in msg for msg, _t in tray.notifications)


def test_consolidate_does_not_offer_the_button_when_the_nas_check_failed(
    tmp_path, monkeypatch
):
    """CORE-C2 / UX-10: every number in the report is unknown, so the confirm
    button must not be offered -- and neither lane may run."""
    from ccsync_companion import consolidate

    other = tmp_path / "other"
    other.mkdir()
    stray = other / "A001.braw"
    stray.write_bytes(b"x" * 10)

    app = _make_app(tmp_path, sync_enabled=True,
                    active_project="Projects/2026/X/Y", popup_enabled=False)
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: _mp_result(_item(str(stray))))
    monkeypatch.setattr(consolidate, "reconcile_with_nas",
                        lambda *a, **k: {"ok": False, "error": "rclone missing"})

    ran: list[str] = []
    monkeypatch.setattr("ccsync_companion.popup.confirm_dialog",
                        lambda *a, **k: ran.append("dialog") or True)
    app._lane_a.run_once = lambda subpath=None: ran.append("lane_a")
    app._lane_b.run_once = lambda subpath=None: ran.append("lane_b")

    app.consolidate_project()
    assert ran == []


# -- CORE-M13: consolidate respects the sync gates --------------------------


def test_consolidate_refuses_when_sync_is_disabled(tmp_path, monkeypatch):
    """AUDIT_2 CORE-M13: lane A ran even on a sync_enabled=false base rig
    whose remote_root is blank."""
    called = []
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: called.append(1) or _mp_result())
    app = _make_app(tmp_path, sync_enabled=False)
    app.consolidate_project()
    assert called == []


def test_consolidate_refuses_while_paused(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: called.append(1) or _mp_result())
    app = _make_app(tmp_path, sync_enabled=True)
    app._paused = True
    app.consolidate_project()
    assert called == []


def test_consolidate_refuses_while_config_problems_exist(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: called.append(1) or _mp_result())
    app = _make_app(tmp_path, sync_enabled=True)
    app.config_problems = ["remote_root is blank -- ..."]
    app.consolidate_project()
    assert called == []


def test_consolidate_releases_the_popup_lock_before_the_long_copy(tmp_path, monkeypatch):
    """AUDIT_2 CORE-M13: the lock was held across run_consolidation --
    potentially hours -- during which every watcher popup was dropped with
    "A popup is already open" and the new-project prompt starved."""
    from ccsync_companion import consolidate

    other = tmp_path / "other"
    other.mkdir()
    stray = other / "A001.braw"
    stray.write_bytes(b"x" * 10)

    app = _make_app(tmp_path, sync_enabled=True,
                    active_project="Projects/2026/X/Y", popup_enabled=False)
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: _mp_result(_item(str(stray))))
    monkeypatch.setattr(consolidate, "reconcile_with_nas",
                        lambda *a, **k: {"ok": True, "uploads": {"count": 1, "bytes": 1},
                                         "downloads": {"count": 0, "bytes": 0}})
    monkeypatch.setattr("ccsync_companion.popup.confirm_dialog", lambda *a, **k: True)
    monkeypatch.setattr(popup, "ProgressWindow", _FakeProgressWindow)

    held = {}
    monkeypatch.setattr(
        consolidate, "run_consolidation",
        lambda *a, **k: held.setdefault("during_copy", app._popup_active_lock.locked()) or [],
    )
    app._lane_a.run_once = lambda subpath=None: None
    app._lane_b.run_once = lambda subpath=None: None

    app.consolidate_project()
    assert held["during_copy"] is False


# -- DEL-3: config errors actually stop syncing -----------------------------


def test_config_errors_stop_the_lanes_from_starting(tmp_path):
    """AUDIT_2 DEL-3. validate_config's "errors that STOP syncing" were
    logged, assigned to config_problems, and then start() ran anyway. A
    typo'd remote_root makes lane B's `rclone sync` DELETE every local proxy
    tree-wide; a blank local_root makes every destination CWD-relative."""
    app = _make_app(tmp_path, sync_enabled=True, require_login=False,
                    remote_root="not-absolute")
    assert app.config_problems, "a non-absolute remote_root must be an error"

    started: list[str] = []
    for lane in app.lanes:
        lane.start = lambda name=lane.name: started.append(name)

    app._start_lanes()
    assert started == []
    assert app._lanes_started is False
    assert all("NOT SYNCING" in lane.status().detail for lane in app.lanes)


def test_a_good_config_still_starts_the_lanes(tmp_path):
    """The other half: DEL-3's gate must not brick a healthy install."""
    app = _make_app(tmp_path, dashboard_url="", sync_enabled=True,
                    require_login=False, lane_b_enabled=True)
    assert app.config_problems == []

    started: list[str] = []
    for lane in app.lanes:
        lane.start = lambda name=lane.name: started.append(name)

    app._start_lanes()
    assert "lane_a_video_up" in started
    assert app._lanes_started is True


# -- CORE-H1: a blank local_root must not scatter media into the CWD --------


def test_popup_is_suppressed_while_local_root_is_broken(tmp_path, monkeypatch):
    """AUDIT_2 CORE-H1 [measured]. With local_root="", classify_path returns
    OUT_OF_TREE for EVERY clip, so the popup lists the whole timeline -- and
    Path("").resolve() is the process CWD, so one FIX ALL scatters the
    project's media into the autostart exe's working directory."""
    other = tmp_path / "other"
    other.mkdir()
    path = other / "clip.mov"
    path.touch()

    app = _make_app(tmp_path, local_root="")
    assert any("local_root" in p for p in app.config_problems)

    shown = []
    monkeypatch.setattr(popup, "show_popup", lambda *a, **kw: shown.append(True))
    app._handle_out_of_tree([_item(str(path))])
    assert shown == []

    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: _mp_result(_item(str(path))))
    app.scan_whole_project()
    assert shown == []


# -- CORE-H2: a bad log_path must not make the exe vanish -------------------


def test_run_survives_an_unusable_log_path(tmp_path, monkeypatch):
    """AUDIT_2 CORE-H2 [measured]. setup_logging(cfg) was run()'s first
    statement after load_config() and sat OUTSIDE any try -- so log_path = 5
    (TypeError), an unmounted drive (FileNotFoundError) or "" (PermissionError)
    killed the windowed exe with no log, no tray and no toast: the exact S-10
    symptom the original fix was written to eliminate."""
    from ccsync_companion import app as app_mod

    for bad in (5, ["x"], "", "   "):
        cfg = _cfg(tmp_path, log_path=bad)
        monkeypatch.setattr(app_mod.config_mod, "load_config", lambda c=cfg: c)
        monkeypatch.setattr(app_mod, "acquire_single_instance", lambda: True)

        built = {}

        class _StubApp:
            def __init__(self, c):
                built["ok"] = True

            def run(self):
                built["ran"] = True

        monkeypatch.setattr(app_mod, "CompanionApp", _StubApp)
        app_mod.run()
        assert built.get("ran") is True, f"startup died on log_path={bad!r}"


def test_bad_log_path_is_a_config_error_and_resolves_to_the_default(tmp_path):
    from pathlib import Path

    from ccsync_companion import config as config_mod

    errors, _warnings = config_mod.validate_config(_cfg(tmp_path, log_path=5))
    assert any("log_path" in e for e in errors)
    # ...and nothing that reads it may raise.
    assert config_mod.resolved_log_path({"log_path": 5}) == \
        Path(config_mod.DEFAULTS["log_path"]).expanduser()


def test_companion_app_constructs_with_hostile_numeric_config(tmp_path):
    """AUDIT_2 CORE-M4: poll_interval="fast", transfers="four",
    scan_interval_up="soon" and watch_debounce_seconds=None all yielded
    errors == [] and then raised inside __init__/_build_lanes."""
    from ccsync_companion import config as config_mod

    cfg = _cfg(tmp_path, poll_interval="fast", transfers="four",
               scan_interval_up="soon", watch_debounce_seconds=None)
    errors, _warnings = config_mod.validate_config(cfg)
    for key in ("poll_interval", "transfers", "scan_interval_up", "watch_debounce_seconds"):
        assert any(key in e for e in errors), f"{key} must be flagged"
    # Construction must still succeed -- a crash here has no log line.
    CompanionApp(cfg)


# -- lane C wiring (L-6 / UX-3) --------------------------------------------


def test_lane_c_gets_the_sequencers_live_folder_set(tmp_path):
    """AUDIT_2 L-6/UX-3: lane C judged itself against cfg["syncthing_folder_ids"],
    written as a literal [] by every installer and populated by nothing -- so
    it reported idle/queued=0/last_sync=now unconditionally for every managed
    editor, while carrying ALL the audio, GFX, AE and subtitles."""
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com")
    assert app.sequencer is not None
    assert app._lane_c.expected_folder_ids_fn is not None

    app.sequencer._slug_to_item = {"2026-cct-season-1": {}, "2025-ff4-nuclear": {}}
    assert app._lane_c._effective_folder_ids() == ["2026-cct-season-1", "2025-ff4-nuclear"]


def test_lane_c_has_no_folder_fn_in_legacy_mode(tmp_path):
    app = _make_app(tmp_path, dashboard_url="")
    assert app._lane_c.expected_folder_ids_fn is None


# -- CORE-M7: single-instance guard ----------------------------------------


def test_single_instance_guard_blocks_a_second_acquisition(monkeypatch, tmp_path):
    """AUDIT_2 CORE-M7: two companions = two watchers hammering the Resolve
    C extension, two rclone lane sets writing the same tree and state files,
    two reporters under one identity, two competing self-upgrades. The
    trigger is the likeliest action after "it looks like it is not running":
    double-clicking the desktop exe."""
    from ccsync_companion import app as app_mod
    from ccsync_companion import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "cc")
    monkeypatch.setattr(app_mod, "_single_instance_token", None)

    assert app_mod._acquire_lock_file() is True
    monkeypatch.setattr(app_mod, "_pid_is_alive", lambda pid: True)
    # A different live pid holds it.
    (tmp_path / "cc" / app_mod._SINGLE_INSTANCE_LOCKFILE).write_text("999999", encoding="utf-8")
    assert app_mod._acquire_lock_file() is False


def test_single_instance_guard_ignores_a_stale_lock(monkeypatch, tmp_path):
    """A crashed companion must never lock the editor out permanently."""
    from ccsync_companion import app as app_mod
    from ccsync_companion import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "cc")
    (tmp_path / "cc").mkdir(parents=True)
    (tmp_path / "cc" / app_mod._SINGLE_INSTANCE_LOCKFILE).write_text("999999", encoding="utf-8")
    monkeypatch.setattr(app_mod, "_pid_is_alive", lambda pid: False)
    assert app_mod._acquire_lock_file() is True


def test_run_exits_cleanly_when_another_instance_holds_the_slot(monkeypatch, tmp_path):
    from ccsync_companion import app as app_mod

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(app_mod.config_mod, "load_config", lambda: cfg)
    monkeypatch.setattr(app_mod, "setup_logging", lambda c: None)
    monkeypatch.setattr(app_mod, "acquire_single_instance", lambda: False)
    monkeypatch.setattr(app_mod, "_warn_already_running", lambda: None)

    built = []
    monkeypatch.setattr(app_mod, "CompanionApp", lambda c: built.append(1))
    app_mod.run()  # must not raise, must not construct
    assert built == []


# -- UX-19: Copy diagnostics -----------------------------------------------


def test_build_diagnostics_covers_the_audits_checklist(tmp_path):
    app = _make_app(tmp_path, sync_enabled=True, editor_name="alex")
    text = app.build_diagnostics()
    for expected in (
        "CCSYNC DIAGNOSTICS", "companion version", "platform", "effective mode",
        "signed in as", "config problems", "sequencer", "lanes", "syncthing",
        "rclone available", "last 40 log lines",
    ):
        assert expected in text, f"diagnostics missing {expected!r}"


def test_build_diagnostics_never_raises_on_a_broken_subsystem(tmp_path):
    """A diagnostics gather that dies on the one broken subsystem is worse
    than useless."""
    app = _make_app(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("subsystem is on fire")

    app.lane_statuses = boom
    app.effective_mode = boom
    app.editor_identity = boom
    app._lane_c.check_once = boom
    text = app.build_diagnostics()
    assert "failed" in text


# ===========================================================================
# AUDIT_3 H-2: a dashboard rel_path may not escape local_root
# ===========================================================================


def test_consolidate_refuses_a_project_root_outside_local_root(tmp_path, monkeypatch):
    """selection.py drops unsafe project_roots entries; this is the assertion
    right before the lanes run. `subpath` becomes lane A's SOURCE, so a
    traversal turns the consolidate upload into
    `rclone copy <somewhere outside the tree> nas:...`."""
    from ccsync_companion import consolidate

    other = tmp_path / "other"
    other.mkdir()
    stray = other / "A001.braw"
    stray.write_bytes(b"x" * 10)

    app = _make_app(
        tmp_path, sync_enabled=True, popup_enabled=False,
        active_project="Projects/../../../Windows/Temp",
    )
    tray = _FakeTray()
    app._tray_icon = tray

    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: _mp_result(_item(str(stray)), project_name="Whatever"))
    ran: list[str] = []
    monkeypatch.setattr(consolidate, "reconcile_with_nas",
                        lambda *a, **k: ran.append("reconcile") or {"ok": True})
    monkeypatch.setattr("ccsync_companion.popup.confirm_dialog",
                        lambda *a, **k: ran.append("dialog") or True)
    monkeypatch.setattr(consolidate, "run_consolidation",
                        lambda *a, **k: ran.append("copy") or [])
    app._lane_a.run_once = lambda subpath=None: ran.append(f"lane_a:{subpath}")
    app._lane_b.run_once = lambda subpath=None: ran.append(f"lane_b:{subpath}")

    app.consolidate_project()

    assert ran == [], "nothing may run for a destination outside local_root"
    assert any("outside your sync folder" in msg for msg, _t in tray.notifications)


def test_subpath_containment_helper(tmp_path):
    app = _make_app(tmp_path)
    assert app._subpath_is_contained("Projects/2026/FF5/Alpha") is True
    assert app._subpath_is_contained("Projects/../../evil") is False
    assert app._subpath_is_contained("/evil") is False
    assert app._subpath_is_contained("") is False
    assert app._subpath_is_contained("C:/Windows/Temp") is False


# ===========================================================================
# AUDIT_3 M-7: the lanes' state dir goes through config.resolved_log_path
# ===========================================================================


def test_state_dir_survives_a_blank_log_path(tmp_path):
    """`Path("")` is the process CWD -- C:\\Windows\\system32 for a Run-key
    autostart -- so a blank log_path silently put every lane's filter file
    and express list there."""
    from ccsync_companion import config as config_mod

    app = _make_app(tmp_path, log_path="")
    expected = Path(config_mod.DEFAULTS["log_path"]).expanduser().parent / "state"
    assert app._state_dir == expected
    assert app._state_dir.is_absolute()


def test_state_dir_survives_a_non_str_log_path(tmp_path):
    """`log_path = 5` raised TypeError inside CompanionApp.__init__ -- the
    windowed exe vanishing with no tray and no log line."""
    from ccsync_companion import config as config_mod

    app = _make_app(tmp_path, log_path=5)
    expected = Path(config_mod.DEFAULTS["log_path"]).expanduser().parent / "state"
    assert app._state_dir == expected


# ===========================================================================
# AUDIT_3 M-3: Pause must stop the express lane, not just the rotation
# ===========================================================================


class _FakeSequencer:
    def __init__(self):
        self.events: list[str] = []

    def pause(self):
        self.events.append("pause")

    def resume(self):
        self.events.append("resume")


def test_toggle_pause_pauses_and_resumes_the_express_lane(tmp_path):
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com", sync_enabled=True)
    app.sequencer = _FakeSequencer()

    app.toggle_pause()
    assert app.is_paused() is True
    assert app.sequencer.events == ["pause"]
    assert app._lane_a.express_paused() is True

    app.toggle_pause()
    assert app.is_paused() is False
    assert app.sequencer.events == ["pause", "resume"]
    assert app._lane_a.express_paused() is False


def test_toggle_pause_survives_a_lane_without_the_express_api(tmp_path):
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com", sync_enabled=True)
    app.sequencer = _FakeSequencer()
    app._lane_a = object()  # an adapter that predates pause_express
    app.toggle_pause()  # must not raise
    assert app.is_paused() is True


# ===========================================================================
# AUDIT_3 L-9: the popup snooze map is shared between two threads
# ===========================================================================


def test_popup_snooze_map_survives_concurrent_write_and_prune(tmp_path):
    """The watcher thread prunes/reads _popup_snooze while a ccsync-popup
    thread inserts into it; mutating a dict mid-iteration raises
    RuntimeError, inside the watcher's poll loop."""
    import threading

    app = _make_app(tmp_path)
    stop = threading.Event()
    errors: list[BaseException] = []

    def _writer():
        i = 0
        while not stop.is_set():
            app._popup_snooze_stamp([f"key-{i}"], 0.0)
            i += 1

    def _pruner():
        try:
            for _ in range(2000):
                app._prune_popup_snooze(10_000.0)
                app._popup_snooze_snapshot()
        except BaseException as exc:  # pragma: no cover -- the regression
            errors.append(exc)

    writer = threading.Thread(target=_writer, daemon=True)
    writer.start()
    try:
        _pruner()
    finally:
        stop.set()
        writer.join(timeout=5)

    assert errors == []


# ===========================================================================
# AUDIT_3 L-12: the .ccsync-trash toast is wired to lane B
# ===========================================================================


def test_lane_b_trash_callback_is_wired_to_a_tray_toast(tmp_path):
    app = _make_app(tmp_path)
    tray = _FakeTray()
    app._tray_icon = tray

    assert app._lane_b.on_trash is not None
    app._lane_b.on_trash(r"T:\Creators_Club\.ccsync-trash\20260725-101500")

    assert tray.notifications
    msg, _title = tray.notifications[0]
    assert ".ccsync-trash" in msg
    assert "moved" in msg.lower() and "deleted" in msg.lower()


def test_selection_client_gets_the_identity_token_getter(tmp_path):
    """The dashboard's selection endpoint requires X-CCSync-Identity, so the
    companion's SelectionClient must be wired to the same IdentityManager the
    reporter uses -- otherwise every managed editor 401s and silently runs
    off its cached selection."""
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com")
    assert app.selection_client is not None
    assert app.selection_client._identity_token_fn is not None

    import base64
    import time as _time

    username = base64.urlsafe_b64encode(b"alex").rstrip(b"=").decode("ascii")
    token = f"v2.identity.{username}.{int(_time.time()) + 3600}.deadbeef"

    headers: list[dict] = []
    app.selection_client._http_get = lambda url, hdrs, timeout: (
        headers.append(dict(hdrs)) or {"selection": []}
    )
    app.identity._identity = {"username": "alex", "token": token}
    app.selection_client.fetch(force=True)

    assert headers[0].get("X-CCSync-Identity") == token
