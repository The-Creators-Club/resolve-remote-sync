"""CompanionApp.scan_whole_project tests — resolve_bridge and popup.show_popup
are monkeypatched so nothing here touches a real Resolve instance or opens a
real Tk window (headless CI-safe, same ethos as test_watcher.py)."""

from __future__ import annotations

from typing import Any

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
        "token": "v1.alex.99999999999.deadbeef",
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


def test_project_setup_absent_in_legacy_mode(tmp_path):
    app = _make_app(tmp_path, dashboard_url="")
    assert app.project_setup is None
    assert app.setup_project_available() is None
    app.setup_current_project()  # no-op, no raise
