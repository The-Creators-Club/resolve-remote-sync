"""CompanionApp.scan_whole_project tests — resolve_bridge and popup.show_popup
are monkeypatched so nothing here touches a real Resolve instance or opens a
real Tk window (headless CI-safe, same ethos as test_watcher.py)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from ccsync_companion import popup, resolve_bridge
from ccsync_companion.app import CompanionApp


def _cfg(tmp_path, **overrides) -> dict[str, Any]:
    cfg = {
        "editor_name": "alex",
        "local_root": str(tmp_path / "root"),
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
    monkeypatch.setattr(app.selection_client, "get_project_roots",
                         lambda: {"myproject": "Projects/2026/FF5/Nuclear"})

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


def test_scan_whole_project_server_roots_failure_falls_back_to_none(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    path = other / "clip.mov"
    path.touch()

    app = _make_app(tmp_path, dashboard_url="http://dash.example.com")

    def boom():
        raise RuntimeError("dashboard unreachable")

    monkeypatch.setattr(app.selection_client, "get_project_roots", boom)
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                         lambda: _mp_result(_item(str(path))))

    captured = {}
    monkeypatch.setattr(
        popup, "show_popup",
        lambda items, local_root, editor_name, ignore_tracker, project_prefix="", server_roots=None:
        captured.__setitem__("server_roots", server_roots),
    )

    app.scan_whole_project()
    assert captured["server_roots"] is None


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

    app = _make_app(tmp_path, popup_enabled=False)
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

    app = _make_app(tmp_path)
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


def test_refresh_media_tree_once_keeps_non_ignored_project(tmp_path, monkeypatch):
    app = _make_app(tmp_path, ignored_resolve_projects=["Untitled Project"])
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(_item("clip.mov"), project_name="Real Project"),
    )
    app._refresh_media_tree_once()
    assert "Real Project" in app.get_media_tree()
