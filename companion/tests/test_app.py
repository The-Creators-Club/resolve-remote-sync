"""CompanionApp.scan_whole_project tests — resolve_bridge and popup.show_popup
are monkeypatched so nothing here touches a real Resolve instance or opens a
real Tk window (headless CI-safe, same ethos as test_watcher.py)."""

from __future__ import annotations

import logging
import os
import threading
import time
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
        "editor_name": "owen",
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

    def fake_show_popup(items, local_root, editor_name, ignore_tracker, project_prefix="",
                        server_roots=None, canonical_prefix=""):
        captured["items"] = items
        captured["local_root"] = local_root
        captured["server_roots"] = server_roots
        captured["canonical_prefix"] = canonical_prefix

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
        lambda items, local_root, editor_name, ignore_tracker, project_prefix="",
               server_roots=None, canonical_prefix="":
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
        lambda items, local_root, editor_name, ignore_tracker, project_prefix="",
               server_roots=None, canonical_prefix="":
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


def test_scan_whole_project_queues_when_popup_already_active(tmp_path, monkeypatch):
    """A batch that loses the Tk lock is QUEUED, not dropped: it used to be
    thrown away behind an "already open" toast, so every clip found while the
    editor read a dialog was lost."""
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

    # Nothing shown while the lock was held...
    assert called == []
    # ...and no nagging toast about it.
    assert not any("already open" in msg for msg, _title in app._tray_icon.notifications)
    # ...but the clip is waiting, not gone.
    assert [i["file_path"] for i in app._popup_queue[0]["items"]] == [str(path)]


def test_queued_batch_is_shown_when_the_open_popup_closes(tmp_path, monkeypatch):
    """The queue drains in the same _show_out_of_tree_popup call that held the
    lock -- that is what makes it "as many popups as it takes"."""
    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()

    other = tmp_path / "other"
    other.mkdir()
    first = other / "first.mov"
    first.touch()
    second = other / "second.mov"
    second.touch()

    shown: list[list[str]] = []

    def _fake_show(items, *a, **kw):
        shown.append([i["file_path"] for i in items])
        if len(shown) == 1:
            # Arrives while the first dialog is on screen.
            app._show_out_of_tree_popup([_item(str(second))], snooze=True)

    monkeypatch.setattr(popup, "show_popup", _fake_show)

    app._show_out_of_tree_popup([_item(str(first))], snooze=True)

    assert shown == [[str(first)], [str(second)]]
    assert app._popup_queue == []
    assert app._popup_showing_keys == set()
    assert not app._popup_active_lock.locked()


def test_queue_dedupes_the_watchers_repeat_reports(tmp_path, monkeypatch):
    """The watcher re-reports the same out-of-tree clips every 3 s poll. Ten
    minutes of that must not become 200 identical dialogs."""
    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()

    other = tmp_path / "other"
    other.mkdir()
    path = other / "clip.mov"
    path.touch()

    app._popup_active_lock.acquire()
    try:
        for _ in range(50):
            app._show_out_of_tree_popup([_item(str(path))], snooze=True)
    finally:
        app._popup_active_lock.release()

    assert len(app._popup_queue) == 1
    assert len(app._popup_queue[0]["items"]) == 1


def test_queued_clip_dismissed_meanwhile_is_not_re_asked(tmp_path, monkeypatch):
    """SKIP in one dialog means skipped -- not asked again four seconds later
    because the clip was already sitting in the queue."""
    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()

    other = tmp_path / "other"
    other.mkdir()
    first = other / "first.mov"
    first.touch()
    second = other / "second.mov"
    second.touch()

    shown: list[list[str]] = []

    def _fake_show(items, *a, **kw):
        shown.append([i["file_path"] for i in items])
        if len(shown) == 1:
            app._show_out_of_tree_popup([_item(str(second))], snooze=True)
            # ...and the editor SKIPs it before the first dialog closes.
            app.ignore_tracker.ignore(str(second))

    monkeypatch.setattr(popup, "show_popup", _fake_show)

    app._show_out_of_tree_popup([_item(str(first))], snooze=True)

    assert shown == [[str(first)]]
    assert app._popup_queue == []


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
        # _handle_out_of_tree hands off to a daemon thread.
        for thread in threading.enumerate():
            if thread.name == "ccsync-popup":
                thread.join(timeout=5)
    finally:
        app._popup_active_lock.release()

    assert called == []
    assert [i["file_path"] for i in app._popup_queue[0]["items"]] == [str(path)]


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
        "username": "owen",
        # v2.identity.<base64url(username), no padding>.<expires_epoch>.<sig>
        # -- see identity.py's parse_token().
        "token": "v2.identity.YWxleA.99999999999.deadbeef",
        "role": "base",
    }
    assert app.effective_mode() == "base"
    payload = app.reporter._build_payload(editor_name="owen")
    assert payload["mode"] == "base"


def test_reporter_response_feeds_upgrade_manager(tmp_path, monkeypatch):
    """The offer is SIGNED here since 2026-08-17 (COMMERCIAL_READINESS.md
    item 4): an unsigned one is refused before it ever reaches the tray, so
    the bare version/url/sha256 dict this used to send would only exercise
    the refusal path. test_upgrade.py covers the refusals themselves."""
    import base64

    from ccsync_companion import ed25519, release_pubkey

    seed = bytes(range(32))
    monkeypatch.setattr(
        release_pubkey, "RELEASE_PUBKEYS",
        (base64.b64encode(ed25519.public_key(seed)).decode("ascii"),),
    )
    record = {
        "kind": "companion", "platform": "windows", "version": "9.9.9",
        "filename": "ccsync-companion-9.9.9.exe", "sha256": "a" * 64,
        "size_bytes": 10, "min_version": "0.0.0",
        "published_at": "2026-08-17T00:00:00Z", "signed_binary": False,
    }
    offer = dict(record, url="/x", signature=base64.b64encode(
        ed25519.sign(seed, release_pubkey.canonical_record(record))).decode("ascii"))

    app = _make_app(tmp_path)
    assert app.reporter._on_report_response is not None
    app.reporter._on_report_response({"ok": True, "upgrade": offer})
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
    app = _make_app(tmp_path, editor_name="owen", require_login=False)
    assert app.editor_identity() == "owen"


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
    from ccsync_companion import ui_dispatch

    app = _make_app(tmp_path)  # sync_enabled=False -> _start_lanes() is inert
    app.start = lambda: None  # skip real watcher/reporter/manifest threads

    # This test is about the TRAY failing, not about UI dispatch. On a Mac
    # app.run() would otherwise start a real main-thread dispatcher, whose
    # _make_root() calls tkinter.Tk() and trips conftest._no_real_tk_windows
    # -- an error in teardown, with the body still passing (MAC-2e). Force
    # the inline path so this test means the same thing on every host; the
    # dispatcher-serving path has its own test below.
    monkeypatch.setattr(ui_dispatch, "start", lambda *a, **kw: None)

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


def _instrument_lanes(app) -> tuple[list[str], list[str]]:
    started: list[str] = []
    stopped: list[str] = []
    for lane in app.lanes:
        def _start(name=lane.name):
            started.append(name)

        def _stop(name=lane.name):
            stopped.append(name)

        lane.start = _start
        lane.stop = _stop
    return started, stopped


def test_toggle_pause_legacy_mode_skips_lane_b_on_resume_when_disabled(tmp_path):
    # require_login=False, i.e. this machine trusts editor_name: without it
    # resume is refused outright (see the pair of tests below) and this test
    # would pass for the wrong reason.
    app = _make_app(tmp_path, dashboard_url="", sync_enabled=True, lane_b_enabled=False,
                    require_login=False)
    assert app._managed is False

    started, stopped = _instrument_lanes(app)

    app.toggle_pause()  # pause -> _stop_lanes()
    assert app.is_paused() is True
    assert set(stopped) == {lane.name for lane in app.lanes}

    started.clear()
    app.toggle_pause()  # resume -> _start_lanes()
    assert app.is_paused() is False
    assert "lane_a_video_up" in started
    assert "lane_b_proxy_down" not in started  # lane_b_enabled=False


# -- B10: Pause -> Resume must not start lanes with nobody signed in --------


def test_toggle_pause_resume_refuses_to_start_lanes_when_not_signed_in(tmp_path):
    """B10 [verified]. start() and on_signed_in() both gate _start_lanes() on
    require_login; toggle_pause's resume path did not -- so on a legacy
    (blank dashboard_url) machine that had correctly left its lanes down, ⏸
    then ▶ synced everything under an unverified identity and set
    _lanes_started=True. The previous version of the test above asserted the
    lanes DID start, which is why this shipped."""
    app = _make_app(tmp_path, dashboard_url="", sync_enabled=True, lane_b_enabled=True)
    assert app._managed is False
    assert app._require_login is True
    assert app.identity.valid() is False

    app.start = lambda: None  # never start real threads here
    started, _stopped = _instrument_lanes(app)

    app.toggle_pause()  # pause
    assert app.is_paused() is True
    started.clear()

    app.toggle_pause()  # resume, still signed out
    assert app.is_paused() is False
    assert started == [], "resume started sync lanes with nobody signed in"
    assert app._lanes_started is False
    assert all("sign in required" in lane.status().detail for lane in app.lanes)


def test_toggle_pause_resume_does_start_lanes_once_signed_in(tmp_path):
    """The other half: the gate must not brick ▶ for a signed-in editor."""
    app = _make_app(tmp_path, dashboard_url="", sync_enabled=True, lane_b_enabled=True)

    class _SignedIn:
        role = None
        username = "owen"
        token = "t"
        last_upgrade_info = None

        def valid(self):
            return True

    app.identity = _SignedIn()
    started, _stopped = _instrument_lanes(app)

    app.toggle_pause()  # pause
    started.clear()
    app.toggle_pause()  # resume

    assert app.is_paused() is False
    assert "lane_a_video_up" in started
    assert app._lanes_started is True


def test_toggle_pause_resume_refuses_in_managed_mode_when_not_signed_in(tmp_path):
    """Managed mode has the same hole: resume unpaused the sequencer AND lane
    A's express upload -- which pushes every new clip to the NAS on its own
    timer -- with no verified identity."""
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com", sync_enabled=True)
    app.sequencer = _FakeSequencer()

    app.toggle_pause()  # pause
    assert app._lane_a.express_paused() is True

    app.toggle_pause()  # resume, still signed out
    assert app.is_paused() is False
    assert app.sequencer.events == ["pause"], "the sequencer was resumed unsigned"
    assert app._lane_a.express_paused() is True, "express uploads resumed unsigned"


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


# -- ops-efficiency-8 (CR-66 / CR-67 item 9): the media-tree stat cache -----


def _presence_app(tmp_path, seen: list[str], present: set[str]):
    """exists_fn spy. `seen` records only the ORIGINAL paths: the same
    callable serves _relink_proxies_once's candidate Proxy/ spellings, which
    are a different question and not what this cache is about."""
    def spy(path):
        if "Proxy" not in str(path):
            seen.append(path)
        return path in present

    return CompanionApp(_cfg(tmp_path), exists_fn=spy)


def test_a_clip_that_was_there_is_not_re_statted_every_cycle(tmp_path, monkeypatch):
    """A wired rig's media pool is on the SMB share and this walk stat()ed
    every clip in it every 120 s -- a thousand round trips a minute to answer
    a question whose answer had not changed."""
    seen: list[str] = []
    app = _presence_app(tmp_path, seen, {"P:/a.mov", "P:/b.mov"})
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(_item("P:/a.mov"), _item("P:/b.mov"),
                           project_name="Real Project"),
    )

    app._refresh_media_tree_once()
    assert sorted(seen) == ["P:/a.mov", "P:/b.mov"]
    seen.clear()

    app._refresh_media_tree_once()
    assert seen == [], "a present clip must not be re-statted the next cycle"
    assert [c["present"] for c in app.get_media_tree()["Real Project"]] == [True, True]


def test_an_absent_clip_is_probed_every_cycle(tmp_path, monkeypatch):
    """"Absent" is the answer that CHANGES -- it is what a lane B download
    flips -- so it is the one worth paying for every pass."""
    seen: list[str] = []
    arrived: set[str] = set()
    app = _presence_app(tmp_path, seen, arrived)
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(_item("P:/late.mov"), project_name="Real Project"),
    )

    app._refresh_media_tree_once()
    assert app.get_media_tree()["Real Project"][0]["present"] is False
    seen.clear()

    arrived.add("P:/late.mov")
    app._refresh_media_tree_once()
    assert seen == ["P:/late.mov"]
    assert app.get_media_tree()["Real Project"][0]["present"] is True


def test_a_present_clip_is_re_checked_once_the_cache_entry_ages_out(tmp_path, monkeypatch):
    """Trusted, not believed forever: a file really can go away, and a media
    tree that never notices is worse than a slow one."""
    seen: list[str] = []
    present = {"P:/a.mov"}
    app = _presence_app(tmp_path, seen, present)
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(_item("P:/a.mov"), project_name="Real Project"),
    )
    app._refresh_media_tree_once()
    seen.clear()

    aged = time.monotonic() - (app.MEDIA_PRESENCE_TTL_SECONDS + 1)
    app._media_presence_cache = {"P:/a.mov": (True, aged)}
    present.clear()
    app._refresh_media_tree_once()

    assert seen == ["P:/a.mov"]
    assert app.get_media_tree()["Real Project"][0]["present"] is False


def test_the_presence_cache_is_pruned_to_the_open_project(tmp_path, monkeypatch):
    """Closing a project must not leave its clips in the cache for the life
    of the process."""
    seen: list[str] = []
    app = _presence_app(tmp_path, seen, {"P:/a.mov", "P:/b.mov"})
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(_item("P:/a.mov"), project_name="Real Project"),
    )
    app._media_presence_cache = {"P:/gone.mov": (True, time.monotonic())}

    app._refresh_media_tree_once()

    assert set(app._media_presence_cache) == {"P:/a.mov"}


def test_a_stat_that_throws_is_still_absent(tmp_path, monkeypatch):
    def boom(_path):
        raise OSError("the share is not mapped")

    app = CompanionApp(_cfg(tmp_path), exists_fn=boom)
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(_item("P:/a.mov"), project_name="Real Project"),
    )
    app._refresh_media_tree_once()
    assert app.get_media_tree()["Real Project"][0]["present"] is False


# -- proxy relink rides along on the media-tree walk (see proxy_relink.py) ---


def _proxy_item(app, name="A001.braw", proxy_path="G:\\gone\\Proxy\\A001.mov",
                proxy_state="Offline"):
    """A clip inside the tree whose proxy IS on disk but is mis-addressed."""
    root = app.config["local_root"]
    original = os.path.join(root, "Interviews", name)
    proxy_dir = os.path.join(root, "Interviews", "Proxy")
    os.makedirs(proxy_dir, exist_ok=True)
    proxy = os.path.join(proxy_dir, os.path.splitext(name)[0] + ".mov")
    with open(proxy, "wb") as fh:
        fh.write(b"proxy")
    item = _item(original)
    item["proxy_path"] = proxy_path
    item["proxy_state"] = proxy_state
    return item, proxy


def test_media_tree_refresh_repoints_a_stale_proxy(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    item, proxy = _proxy_item(app)
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items", lambda: _mp_result(item)
    )
    calls: list[tuple[Any, str]] = []
    monkeypatch.setattr(
        resolve_bridge, "link_proxy_media",
        # **kw: link_proxy_media grew keyword-only `source`/`journal` args
        # with the undo journal (item 9, 2026-08-17), and the automatic pass
        # names itself.
        lambda mpi, path, **kw: calls.append((mpi, path)) or {"ok": True, "message": ""},
    )
    app._refresh_media_tree_once()
    assert calls == [(item["media_pool_item"], proxy)]


def test_proxy_relink_can_be_switched_off(tmp_path, monkeypatch):
    app = _make_app(tmp_path, proxy_relink_enabled=False)
    item, _ = _proxy_item(app)
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items", lambda: _mp_result(item)
    )
    calls: list[str] = []
    monkeypatch.setattr(
        resolve_bridge, "link_proxy_media",
        lambda mpi, path: calls.append(path) or {"ok": True, "message": ""},
    )
    app._refresh_media_tree_once()
    assert calls == []


def test_a_failing_proxy_relink_never_breaks_the_media_tree(tmp_path, monkeypatch):
    """The tree cache is the reporter's data source -- a Resolve refusal on
    an unrelated proxy must not cost us it."""
    app = _make_app(tmp_path)
    item, _ = _proxy_item(app)
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items",
        lambda: _mp_result(item, project_name="Real Project"),
    )
    monkeypatch.setattr(
        resolve_bridge, "link_proxy_media",
        lambda mpi, path, **kw: (_ for _ in ()).throw(RuntimeError("fusionscript died")),
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


def test_consolidate_holds_the_popup_lock_while_its_window_is_up(tmp_path, monkeypatch):
    """B11, which REVERSES half of AUDIT_2 CORE-M13.

    CORE-M13 released the lock before the copy so watcher popups weren't
    starved -- but ProgressWindow opens a real tk.Tk() ROOT and holds it for
    the whole copy, so what that actually bought was a live root with the
    lock free: any watcher popup landing in that window opens a SECOND root,
    which is the wedged-Tcl condition the lock exists to prevent (CORE-M3 ->
    CORE-H8), and for PopupDialog it means a batch auto-ignored and never
    re-offered this session. The starvation CORE-M13 was avoiding no longer
    applies the same way: since 2026-08-01 a batch that loses the lock is
    QUEUED, and consolidate drains the queue the moment its window closes
    (see the test below). The lock IS released afterwards."""
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

    def _record_lock_state(*a, **k):
        held.setdefault("during_copy", app._popup_active_lock.locked())
        return []

    monkeypatch.setattr(consolidate, "run_consolidation", _record_lock_state)
    app._lane_a.run_once = lambda subpath=None: None
    app._lane_b.run_once = lambda subpath=None: None

    app.consolidate_project()
    assert held["during_copy"] is True, "a second Tk root could open over the progress window"
    assert not app._popup_active_lock.locked(), "the lock outlived the consolidate"


def test_consolidate_shows_the_batches_queued_while_its_window_was_up(tmp_path, monkeypatch):
    """The other half of holding the lock: a watcher batch that lost the race
    is queued, and must be shown the moment the progress window closes --
    not left waiting for the next 300 s snooze cycle."""
    from ccsync_companion import consolidate

    other = tmp_path / "other"
    other.mkdir()
    stray = other / "A001.braw"
    stray.write_bytes(b"x" * 10)
    late = other / "A002.braw"
    late.write_bytes(b"x" * 10)

    app = _make_app(tmp_path, sync_enabled=True, active_project="Projects/2026/X/Y")
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: _mp_result(_item(str(stray))))
    monkeypatch.setattr(consolidate, "reconcile_with_nas",
                        lambda *a, **k: {"ok": True, "uploads": {"count": 1, "bytes": 1},
                                         "downloads": {"count": 0, "bytes": 0}})
    monkeypatch.setattr("ccsync_companion.popup.confirm_dialog", lambda *a, **k: True)
    monkeypatch.setattr(popup, "ProgressWindow", _FakeProgressWindow)

    shown: list[list[str]] = []
    monkeypatch.setattr(
        popup, "show_popup",
        lambda items, *a, **k: shown.append([i["file_path"] for i in items]),
    )

    def _copy_and_race(*a, **k):
        # A clip found by the watcher WHILE the progress window is up.
        app._show_out_of_tree_popup([_item(str(late))])
        return []

    monkeypatch.setattr(consolidate, "run_consolidation", _copy_and_race)
    app._lane_a.run_once = lambda subpath=None: None
    app._lane_b.run_once = lambda subpath=None: None

    app.consolidate_project()

    assert shown == [[str(late)]], "the queued batch was never shown"
    assert app._popup_queue == []
    assert app._popup_queue_keys == set()


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


# -- item 3: the licence gate ----------------------------------------------
# 2026-08-17, COMMERCIAL_READINESS.md item 3. The onboarding wizard writes
# ~/.ccsync/eula_accepted.json on ACCEPT; _start_lanes() refuses without it.
# conftest's _eula_already_accepted puts a current record in every test's
# isolated home, so these tests take it away again.


def _syncing_app(tmp_path):
    app = _make_app(tmp_path, dashboard_url="", sync_enabled=True,
                    require_login=False, lane_b_enabled=True)
    assert app.config_problems == []
    started: list[str] = []
    for lane in app.lanes:
        lane.start = lambda name=lane.name: started.append(name)
    return app, started


def test_an_unaccepted_licence_stops_the_lanes(tmp_path):
    from ccsync_companion import eula as eula_mod

    app, started = _syncing_app(tmp_path)
    eula_mod.acceptance_path().unlink(missing_ok=True)

    app._start_lanes()
    assert started == []
    assert app._lanes_started is False
    assert all("NOT SYNCING" in lane.status().detail for lane in app.lanes)
    assert all("licence" in lane.status().detail for lane in app.lanes)


def test_an_outdated_acceptance_stops_the_lanes(tmp_path):
    """A bumped EULA-VERSION marker is the whole of a re-consent: a machine
    holding the previous version must be sent back to the wizard."""
    from ccsync_companion import eula as eula_mod

    app, started = _syncing_app(tmp_path)
    eula_mod.record_acceptance("0.1")

    app._start_lanes()
    assert started == []
    assert app._lanes_started is False


def test_an_accepted_licence_lets_the_lanes_start(tmp_path):
    from ccsync_companion import eula as eula_mod

    app, started = _syncing_app(tmp_path)
    eula_mod.record_acceptance()

    app._start_lanes()
    assert "lane_a_video_up" in started
    assert app._lanes_started is True


def test_a_build_with_no_bundled_licence_still_syncs(tmp_path, monkeypatch):
    """Fail open on a PACKAGING fault (assets/EULA.md missing from datas):
    "never gut the live thing" -- a forgotten spec line must not stop every
    editor in the fleet syncing at once. A missing ACCEPTANCE still blocks."""
    from ccsync_companion import eula as eula_mod

    app, started = _syncing_app(tmp_path)
    eula_mod.acceptance_path().unlink(missing_ok=True)
    monkeypatch.setattr(eula_mod, "EULA_VERSION", "")

    app._start_lanes()
    assert "lane_a_video_up" in started
    assert app._lanes_started is True


def test_a_raising_licence_check_does_not_stop_the_lanes(tmp_path, monkeypatch):
    from ccsync_companion import eula as eula_mod

    app, started = _syncing_app(tmp_path)

    def _boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(eula_mod, "acceptance_problem", _boom)
    assert app.eula_problem() is None

    app._start_lanes()
    assert "lane_a_video_up" in started


# -- accepting it from the tray, without the wizard -------------------------
# 2026-08-18. Item 3 recorded consent in the WIZARD alone, which never runs on
# the path editors actually upgrade by (upgrade.py swaps the exe in place), so
# 0.8.0 reached machines that then refused to sync with no clickable way out.
# These pin the way out: the dialog shows the BUNDLED document, an ACCEPT
# records it and starts the lanes in the same breath, and a DECLINE leaves the
# machine honestly not-syncing rather than half-accepted.


def _licence_app(tmp_path, monkeypatch, answer):
    """A blocked app whose licence dialog answers `answer` without any Tk.

    Returns (app, started, shown) -- `shown` collects the (intro, document)
    each dialog was built with, so a test can assert what was put in front of
    the person, not merely that something was.
    """
    from ccsync_companion import eula as eula_mod, popup as popup_mod

    app, started = _syncing_app(tmp_path)
    eula_mod.acceptance_path().unlink(missing_ok=True)
    shown: list[tuple] = []

    def _fake_dialog(title, intro, document, accept_label="ACCEPT"):
        shown.append((intro, document))
        return answer

    monkeypatch.setattr(popup_mod, "licence_dialog", _fake_dialog)
    return app, started, shown


def test_accepting_from_the_tray_records_it_and_starts_syncing(tmp_path, monkeypatch):
    from ccsync_companion import eula as eula_mod

    app, started, shown = _licence_app(tmp_path, monkeypatch, answer=True)
    assert app.eula_problem() is not None

    app._show_licence_dialog()

    assert eula_mod.acceptance_ok(), "ACCEPT must persist -- else the same dialog forever"
    assert app.eula_problem() is None
    # ...and syncing starts THERE, not at the next launch: an editor who just
    # accepted has no reason to expect a restart is still owed.
    assert "lane_a_video_up" in started
    assert app._lanes_started is True


def test_the_dialog_shows_the_document_this_build_bundles(tmp_path, monkeypatch):
    """Not a summary and not a link. An acceptance recorded against text the
    person could not read is not consent."""
    from ccsync_companion import eula as eula_mod

    app, _started, shown = _licence_app(tmp_path, monkeypatch, answer=True)
    app._show_licence_dialog()

    assert len(shown) == 1
    intro, document = shown[0]
    assert document == eula_mod.BUNDLED_TEXT
    assert document.strip(), "the fixture build must actually bundle assets/EULA.md"
    assert eula_mod.EULA_VERSION in intro


def test_declining_leaves_the_machine_not_syncing(tmp_path, monkeypatch):
    from ccsync_companion import eula as eula_mod

    app, started, _shown = _licence_app(tmp_path, monkeypatch, answer=False)

    app._show_licence_dialog()

    assert not eula_mod.acceptance_ok()
    assert started == []
    assert app._lanes_started is False


def test_a_build_with_no_document_refuses_to_record_an_acceptance(tmp_path, monkeypatch):
    """The gate is live and the text is not -- a packaging fault. Recording an
    acceptance of nothing would be worse than staying stopped."""
    from ccsync_companion import eula as eula_mod

    app, started, shown = _licence_app(tmp_path, monkeypatch, answer=True)
    monkeypatch.setattr(eula_mod, "bundled_text", lambda: "")

    app._show_licence_dialog()

    assert shown == [], "nothing may be presented as a licence when there is none"
    assert not eula_mod.acceptance_ok()
    assert started == []


def test_the_prompt_is_offered_once_per_run_but_the_tray_can_reopen_it(tmp_path, monkeypatch):
    """A modal that keeps coming back teaches an editor to dismiss it without
    reading; a modal with no way back strands the one who declined by mistake.
    So: automatic once, on request always."""
    calls: list[bool] = []

    app, _started, _shown = _licence_app(tmp_path, monkeypatch, answer=False)
    monkeypatch.setattr(app, "_show_licence_dialog", lambda: calls.append(True))

    app.prompt_licence_acceptance()
    app.prompt_licence_acceptance()
    for thread in list(threading.enumerate()):
        if thread.name == "ccsync-licence":
            thread.join(timeout=5)
    assert len(calls) == 1

    app.prompt_licence_acceptance(force=True)
    for thread in list(threading.enumerate()):
        if thread.name == "ccsync-licence":
            thread.join(timeout=5)
    assert len(calls) == 2


def test_a_dialog_that_never_got_a_window_is_offered_again(tmp_path, monkeypatch):
    """CR-27 [measured on ruskin's PC, 2026-08-18]. The clip popup takes the
    popup lock ~3s before the licence dialog asks for it, on EVERY start of a
    machine whose projects reference clips outside the tree -- so the one-shot
    offer produced no window at all, three lanes stayed parked, and the log
    said "not stacking a second modal on it" once per launch for hours."""
    app, _started, shown = _licence_app(tmp_path, monkeypatch, answer=True)

    # The retry is UNBOUNDED on purpose -- it has to outlast a clip popup an
    # editor leaves open for hours -- so nothing inside the loop ends it while
    # the lock is held. The test plays the part the tray's quit plays in the
    # product: let it lose the race a few times, then set the same
    # _stop_event. Driving it synchronously without this spins forever
    # (measured: four pytest runs stuck at 100% CPU, 2026-08-19).
    real_show = app._show_licence_dialog
    attempts: list[int] = []

    def _show_and_then_quit():
        attempts.append(1)
        real_show()
        if len(attempts) == 3:
            app._stop_event.set()

    monkeypatch.setattr(app, "_show_licence_dialog", _show_and_then_quit)
    app._popup_active_lock.acquire()            # the clip popup got there first
    try:
        app._licence_watch(first_delay=0.0, interval=0.0)
    finally:
        app._popup_active_lock.release()
    assert len(attempts) == 3, "losing the race must be retried, not written off"
    assert shown == [], "the dialog cannot be shown while another window holds the lock"
    assert app._licence_asked is False, "a lost race must not count as having asked"

    # The editor closes the clip popup; the next retry gets its window.
    monkeypatch.setattr(app, "_show_licence_dialog", real_show)
    app._stop_event.clear()
    app._licence_watch(first_delay=0.0, interval=0.0)
    assert len(shown) == 1
    assert app._licence_asked is True


def test_the_retry_stops_once_the_document_has_been_put_in_front_of_someone(
        tmp_path, monkeypatch):
    """Declining is an answer. A modal that comes back a minute later is how
    an editor learns to dismiss it unread -- the tray item is the way back."""
    app, _started, shown = _licence_app(tmp_path, monkeypatch, answer=False)

    app._licence_watch(first_delay=0.0, interval=0.0)
    app._licence_watch(first_delay=0.0, interval=0.0)

    assert len(shown) == 1
    assert app._licence_asked is True


def test_the_retry_stops_when_the_licence_is_accepted(tmp_path, monkeypatch):
    app, started, shown = _licence_app(tmp_path, monkeypatch, answer=True)

    app._licence_watch(first_delay=0.0, interval=0.0)

    assert len(shown) == 1
    assert app.eula_problem() is None
    assert "lane_a_video_up" in started
    # A second watcher (a restart of the loop) finds nothing to do.
    app._licence_watch(first_delay=0.0, interval=0.0)
    assert len(shown) == 1


def test_the_retry_gives_up_on_a_build_with_no_licence_document(tmp_path, monkeypatch):
    """A packaging fault is not something a retry can fix, and the same ERROR
    once a minute forever is how a log stops being read."""
    from ccsync_companion import eula as eula_mod

    app, _started, shown = _licence_app(tmp_path, monkeypatch, answer=True)
    monkeypatch.setattr(eula_mod, "bundled_text", lambda: "")

    app._licence_watch(first_delay=0.0, interval=0.0)
    app._licence_watch(first_delay=0.0, interval=0.0)

    assert shown == []
    assert app._licence_asked is True


def test_the_retry_stands_down_at_shutdown(tmp_path, monkeypatch):
    """It waits on _stop_event like every other loop here, so a Quit or a
    self-upgrade is not held up by a licence nobody accepted."""
    app, _started, shown = _licence_app(tmp_path, monkeypatch, answer=True)
    app._stop_event.set()

    app._licence_watch(first_delay=0.0, interval=0.0)

    assert shown == []


def test_nothing_is_offered_once_the_licence_is_accepted(tmp_path, monkeypatch):
    calls: list[bool] = []

    app, _started, _shown = _licence_app(tmp_path, monkeypatch, answer=True)
    from ccsync_companion import eula as eula_mod
    eula_mod.record_acceptance()
    monkeypatch.setattr(app, "_show_licence_dialog", lambda: calls.append(True))

    app.prompt_licence_acceptance()
    app.prompt_licence_acceptance(force=True)
    assert calls == []


# -- updates without a click (2026-08-18) -----------------------------------


def _update_app(tmp_path, monkeypatch, offer_version="9.9.9"):
    """An app holding a signed offer, with apply_upgrade replaced by a
    recorder -- what is under test is WHETHER it is called, never the exe
    swap itself (that has its own tests in test_upgrade.py)."""
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com")
    applied: list[str] = []
    # Returns None, which the pushed-update thread reads as "applied" -- the
    # refusal tests below install their own stub that returns a reason.
    monkeypatch.setattr(app, "apply_upgrade", lambda **kw: applied.append("applied"))
    monkeypatch.setattr(app, "_notify_tray", lambda *a, **kw: None)
    if offer_version:
        app.upgrade._available = {"version": offer_version, "url": "/x",
                                  "sha256": "0" * 64, "size_bytes": 1}
    return app, applied


def _join_upgrade_threads():
    import threading as _t

    for thread in list(_t.enumerate()):
        if thread.name in {"ccsync-pushed-upgrade", "ccsync-auto-upgrade"}:
            thread.join(timeout=5)


def test_an_admin_can_push_an_update_to_a_machine(tmp_path, monkeypatch):
    """The editor clicks nothing. ruskin's PC sat two versions behind for a
    day with its lanes parked, and nothing on the dashboard could move it."""
    app, applied = _update_app(tmp_path, monkeypatch)

    app._apply_pushed_update(
        {"commands": {"upgrade": {"apply": True, "version": "9.9.9",
                                  "requested_by": "alex"}}})
    _join_upgrade_threads()

    assert applied == ["applied"]


def test_a_push_for_a_build_we_are_not_being_offered_is_refused(tmp_path, monkeypatch):
    """The command names a VERSION, never a URL: the bytes come from the
    signed offer already in hand, so a push can never install anything the
    editor's own tray click could not have."""
    app, applied = _update_app(tmp_path, monkeypatch, offer_version="1.2.3")

    app._apply_pushed_update({"commands": {"upgrade": {"apply": True, "version": "9.9.9"}}})
    _join_upgrade_threads()

    assert applied == []


def test_a_push_with_no_offer_at_all_is_refused(tmp_path, monkeypatch):
    app, applied = _update_app(tmp_path, monkeypatch, offer_version="")

    app._apply_pushed_update({"commands": {"upgrade": {"apply": True, "version": "9.9.9"}}})
    _join_upgrade_threads()

    assert applied == []


def test_a_standing_push_is_applied_once_not_every_report(tmp_path, monkeypatch):
    """The request rides EVERY report until the dashboard sees the new
    version -- i.e. every 30 seconds for the minute the swap takes."""
    app, applied = _update_app(tmp_path, monkeypatch)
    command = {"commands": {"upgrade": {"apply": True, "version": "9.9.9"}}}

    app._apply_pushed_update(command)
    app._apply_pushed_update(command)
    app._apply_pushed_update(command)
    _join_upgrade_threads()

    assert applied == ["applied"]


def test_a_reply_with_no_upgrade_command_changes_nothing(tmp_path, monkeypatch):
    app, applied = _update_app(tmp_path, monkeypatch)

    app._apply_pushed_update({"commands": {"halt": {"active": False}}})
    app._apply_pushed_update({})
    app._apply_pushed_update(None)
    _join_upgrade_threads()

    assert applied == []


def _refusing_update_app(tmp_path, monkeypatch, outcomes):
    """apply_upgrade answers from `outcomes` in order ("" = swapped), and
    records the quiet_refusals flag it was called with."""
    app, _ = _update_app(tmp_path, monkeypatch)
    calls: list[bool] = []
    toasts: list[str] = []

    def fake_apply(*, quiet_refusals=False):
        calls.append(quiet_refusals)
        return outcomes.pop(0) if outcomes else ""

    monkeypatch.setattr(app, "apply_upgrade", fake_apply)
    monkeypatch.setattr(app, "_notify_tray", lambda msg, *a, **kw: toasts.append(msg))
    return app, calls, toasts


def test_a_push_refused_by_an_open_window_is_retried_not_parked(tmp_path, monkeypatch):
    """ultrareview 2026-08-19. The latch was set before apply_upgrade ran
    and never cleared, so ruskin's PC -- whose out-of-tree popup holds the
    lock from three seconds after launch (CR-27) -- got ONE "Can't update
    while a CCSync window is open" and then ignored the standing push until
    the tray was restarted. The request rides every report; once the editor
    closes the window, the next report after the pause must try again."""
    from ccsync_companion import app as app_mod

    app, calls, toasts = _refusing_update_app(tmp_path, monkeypatch, ["popup", "popup", ""])
    command = {"commands": {"upgrade": {"apply": True, "version": "9.9.9",
                                        "requested_at": "2026-08-19T10:00:00Z"}}}
    clock = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: clock[0])

    app._apply_pushed_update(command)
    _join_upgrade_threads()
    assert calls == [False]                       # first attempt, toasts allowed
    assert app._pushed_update_applying == ""      # the latch is RELEASED on refusal

    # The very next report (30 s later) does NOT hammer: the retry is held off.
    clock[0] += 30
    app._apply_pushed_update(command)
    _join_upgrade_threads()
    assert calls == [False]

    # After the pause it tries again -- quietly, the editor was already told.
    clock[0] += app_mod.PUSHED_UPDATE_RETRY_SECONDS
    app._apply_pushed_update(command)
    _join_upgrade_threads()
    assert calls == [False, True]

    clock[0] += app_mod.PUSHED_UPDATE_RETRY_SECONDS + 1
    app._apply_pushed_update(command)
    _join_upgrade_threads()
    assert calls == [False, True, True]           # third attempt swapped ("")
    assert app._pushed_update_applying != ""      # ...and the latch stays set: we are restarting

    # One "your administrator is updating" balloon for the whole episode.
    assert [t for t in toasts if "administrator" in t] == \
        ["Your administrator is updating CCSync to v9.9.9."]


def test_a_failed_download_waits_longer_before_the_next_try(tmp_path, monkeypatch):
    from ccsync_companion import app as app_mod

    app, calls, _ = _refusing_update_app(tmp_path, monkeypatch, ["failed", ""])
    command = {"commands": {"upgrade": {"apply": True, "version": "9.9.9",
                                        "requested_at": "2026-08-19T10:00:00Z"}}}
    clock = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: clock[0])

    app._apply_pushed_update(command)
    _join_upgrade_threads()
    clock[0] += app_mod.PUSHED_UPDATE_RETRY_SECONDS + 1
    app._apply_pushed_update(command)
    _join_upgrade_threads()
    assert calls == [False]                       # a stand-down pause is not enough
    clock[0] += app_mod.PUSHED_UPDATE_FAILED_RETRY_SECONDS
    app._apply_pushed_update(command)
    _join_upgrade_threads()
    assert calls == [False, True]


def test_an_admin_re_push_is_a_fresh_attempt_at_once(tmp_path, monkeypatch):
    """Cancel + push again on the dashboard mints a new requested_at; the
    companion keys on the REQUEST, so the admin is not made to wait out a
    retry timer they cannot see."""
    from ccsync_companion import app as app_mod

    app, calls, toasts = _refusing_update_app(tmp_path, monkeypatch, ["popup", ""])
    clock = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: clock[0])

    app._apply_pushed_update({"commands": {"upgrade": {
        "apply": True, "version": "9.9.9", "requested_at": "2026-08-19T10:00:00Z"}}})
    _join_upgrade_threads()
    clock[0] += 5
    app._apply_pushed_update({"commands": {"upgrade": {
        "apply": True, "version": "9.9.9", "requested_at": "2026-08-19T10:05:00Z"}}})
    _join_upgrade_threads()
    assert calls == [False, False]                # a new request is announced again
    assert len([t for t in toasts if "administrator" in t]) == 2


def test_apply_upgrade_names_why_it_stood_down(tmp_path, monkeypatch):
    """The outcome string is what the pushed path retries on; the tray
    click ignores it. A held popup lock is "popup", quietly when asked."""
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com")
    toasts: list[str] = []
    monkeypatch.setattr(app, "_notify_tray", lambda msg, *a, **kw: toasts.append(msg))
    assert app.apply_upgrade() == "no-offer"
    app.upgrade._available = {"version": "9.9.9", "url": "/x", "sha256": "0" * 64, "size_bytes": 1}
    with app._popup_active_lock:
        assert app.apply_upgrade() == "popup"
        assert len(toasts) == 1
        assert app.apply_upgrade(quiet_refusals=True) == "popup"
        assert len(toasts) == 1
    app._consolidate_active = True
    assert app.apply_upgrade() == "consolidate"
    app._consolidate_active = False
    monkeypatch.setattr(app.upgrade, "apply", lambda: False)
    assert app.apply_upgrade() == "failed"
    monkeypatch.setattr(app.upgrade, "apply", lambda: True)
    assert app.apply_upgrade() == ""


def test_auto_update_is_off_unless_the_site_says_otherwise(tmp_path, monkeypatch):
    """site.feature_enabled fails CLOSED: no manifest, an older dashboard or
    an unreadable cache all mean "wait for the click"."""
    from ccsync_companion import site as site_mod

    app, applied = _update_app(tmp_path, monkeypatch)
    monkeypatch.setattr(site_mod, "feature_enabled", lambda name, site=None: False)

    app._on_upgrade_available({"version": "9.9.9"})
    _join_upgrade_threads()

    assert applied == []


def test_auto_update_takes_a_newer_build_with_no_click(tmp_path, monkeypatch):
    from ccsync_companion import site as site_mod

    app, applied = _update_app(tmp_path, monkeypatch)
    monkeypatch.setattr(site_mod, "feature_enabled",
                        lambda name, site=None: name == "auto_update")

    app._on_upgrade_available({"version": "9.9.9"})
    _join_upgrade_threads()

    assert applied == ["applied"]


def test_auto_update_never_rolls_a_machine_backwards(tmp_path, monkeypatch):
    """"Different, not newer" is what the dashboard advertises, and a
    rollback offer taken silently is a one-click loss of everything the
    running build fixed (seen live 2026-07-25). An admin rolling one back
    deliberately has the push path, which says so."""
    from ccsync_companion import site as site_mod

    app, applied = _update_app(tmp_path, monkeypatch)
    monkeypatch.setattr(site_mod, "feature_enabled",
                        lambda name, site=None: name == "auto_update")

    app._on_upgrade_available({"version": "0.0.1"})
    _join_upgrade_threads()

    assert applied == []


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
    app = _make_app(tmp_path, sync_enabled=True, editor_name="owen")
    text = app.build_diagnostics()
    for expected in (
        "CCSYNC DIAGNOSTICS", "companion version", "platform", "effective mode",
        "signed in as", "config problems", "sequencer", "lanes", "syncthing",
        "rclone available", "last 40 log lines",
    ):
        assert expected in text, f"diagnostics missing {expected!r}"


def test_build_diagnostics_reads_lane_cs_cache_not_a_fresh_sweep(tmp_path):
    """comp-lane-c-5 (CR-50 / CR-67 item 9): check_once() walks every shared
    folder through Syncthing's REST API, which is up to 20 s of a worker
    thread -- on the slow or half-dead Syncthing that is the exact condition
    a diagnostics bundle gets collected under."""
    from ccsync_companion.sync.base import LaneStatus

    app = _make_app(tmp_path)
    calls: list[str] = []

    def no(*_a, **_k):
        calls.append("check_once")
        raise AssertionError("build_diagnostics must not sweep lane C")

    app._lane_c.check_once = no
    app._lane_c.status = lambda: LaneStatus(name="lane_c", state="idle",
                                            detail="from the last poll")
    app._lane_c.api_reachable = lambda: True

    text = app.build_diagnostics()

    assert calls == []
    assert "from the last poll" in text
    assert "api answers right now: True" in text


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
    app._lane_c.status = boom
    app._lane_c.api_reachable = boom
    text = app.build_diagnostics()
    assert "failed" in text


# -- CR-51 / CR-67 item 9: the undo summary names the journal it replayed ---


def test_the_undo_summary_describes_the_open_projects_journal(tmp_path, monkeypatch):
    """comp-resolve-2. describe_latest() with no project reads the newest
    journal of ANY project, so an editor undoing in one project was told the
    clip count of a pass made in another -- while the bridge, since CR-51,
    replays the OPEN project's journal and refuses a mismatch."""
    from ccsync_companion import resolve_journal

    app = _make_app(tmp_path)
    asked: list[Any] = []
    monkeypatch.setattr(resolve_bridge, "current_project_name", lambda *a, **k: "FF4")
    monkeypatch.setattr(
        resolve_journal, "describe_latest",
        lambda project=None: (asked.append(project), "12 clip path(s)")[1],
    )
    monkeypatch.setattr(
        resolve_bridge, "undo_last_relink",
        lambda *a, **k: {"ok": True, "undone": 12, "skipped": 0, "message": "Put back."},
    )
    said: list[str] = []
    app._notify_tray = lambda message, title="": said.append(message)

    app.undo_last_relink()

    assert asked == ["FF4"]
    assert "12 clip path(s)" in said[0]


def test_the_undo_summary_falls_back_when_this_project_has_no_journal(tmp_path, monkeypatch):
    """The bridge's own fallback, mirrored: a journal that names no project
    (the pre-2026-08-21 shape) stays replayable, so it stays describable."""
    from ccsync_companion import resolve_journal

    app = _make_app(tmp_path)
    asked: list[Any] = []

    def describe(project=None):
        asked.append(project)
        return "" if project else "3 clip path(s)"

    monkeypatch.setattr(resolve_bridge, "current_project_name", lambda *a, **k: "FF4")
    monkeypatch.setattr(resolve_journal, "describe_latest", describe)
    monkeypatch.setattr(
        resolve_bridge, "undo_last_relink",
        lambda *a, **k: {"ok": True, "undone": 3, "skipped": 0, "message": "Put back."},
    )
    said: list[str] = []
    app._notify_tray = lambda message, title="": said.append(message)

    app.undo_last_relink()

    assert asked == ["FF4", None]
    assert "3 clip path(s)" in said[0]


# -- ops-efficiency-9 (CR-66 / CR-67 item 9): the log window ----------------


def test_the_log_keeps_ten_files_and_says_when_it_drops_one(tmp_path):
    """5 MB x 3 was 20 MB, and a machine turned up to DEBUG for an incident
    rotates through the whole of it in about half an hour -- so by the time
    the editor is asked for the log, the event that prompted the ask is gone,
    with nothing in the file to say so."""
    import logging as _logging

    from ccsync_companion import app as app_module

    assert app_module.LOG_BACKUP_COUNT == 10

    log_path = tmp_path / "companion.log"
    handler = app_module.RotatingLogHandler(
        log_path, maxBytes=200, backupCount=2, encoding="utf-8")
    handler.setFormatter(_logging.Formatter("%(message)s"))
    try:
        for i in range(40):
            handler.emit(_logging.LogRecord(
                "ccsync.test", _logging.INFO, __file__, 0,
                "filler line %d that is long enough to roll the file over", (i,), None))
    finally:
        handler.close()

    assert "log rotated" in log_path.read_text(encoding="utf-8"), \
        "a rotation nobody records reads as an event that never happened"


def test_a_rotation_note_that_fails_never_breaks_logging(tmp_path):
    import logging as _logging

    from ccsync_companion import app as app_module

    handler = app_module.RotatingLogHandler(
        tmp_path / "companion.log", maxBytes=200, backupCount=1, encoding="utf-8")
    handler.setFormatter(_logging.Formatter("%(message)s"))
    handler.emit = lambda record: (_ for _ in ()).throw(RuntimeError("no"))
    try:
        handler.doRollover()   # must not raise
    finally:
        handler.close()


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
    # require_login=False: resume is a START, and since the toggle_pause login
    # gate (B10) an unsigned machine correctly refuses to resume ANYTHING --
    # which would make this test pass for the wrong reason.
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com", sync_enabled=True,
                    require_login=False)
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


def test_lane_a_watch_state_callback_is_wired_to_a_tray_toast(tmp_path):
    """MAC-12: lane A refusing to start its file watcher because the sync
    drive stopped answering is a capability the editor loses. It must reach
    the tray, not only the log."""
    app = _make_app(tmp_path)
    tray = _FakeTray()
    app._tray_icon = tray

    assert app._lane_a.on_watch_blocked is not None
    assert app._lane_b.on_watch_blocked is None, "lane B has no watchdog to speak for"
    app._lane_a.on_watch_blocked("The sync drive isn't responding, so CCSync can't "
                                 "watch it for new files.")

    assert tray.notifications
    msg, _title = tray.notifications[0]
    assert "isn't responding" in msg


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

    username = base64.urlsafe_b64encode(b"owen").rstrip(b"=").decode("ascii")
    token = f"v2.identity.{username}.{int(_time.time()) + 3600}.deadbeef"

    headers: list[dict] = []
    app.selection_client._http_get = lambda url, hdrs, timeout: (
        headers.append(dict(hdrs)) or {"selection": []}
    )
    app.identity._identity = {"username": "owen", "token": token}
    app.selection_client.fetch(force=True)

    assert headers[0].get("X-CCSync-Identity") == token


# -- Remove this project from this machine (2026-07-26) ---------------------


def _remove_stub(tmp_path, untick_ok=True, mode="editor", blockers=None):
    """A minimal object exposing exactly what remove_project_from_machine
    reads, so the ordering guarantees are testable without a full app."""
    from ccsync_companion.app import CompanionApp

    root = tmp_path / "Creators_Club"
    proj = root / "Projects" / "2026" / "CCT" / "Website Highlights" / "Website Highlights"
    proj.mkdir(parents=True)
    (proj / "clip.braw").write_bytes(b"x")

    class _Selection:
        def __init__(self):
            self.unticked = []

        def get(self):
            return ([{"slug": "2026-cct-website-highlights-website-highlights",
                      "rel_path": "2026/CCT/Website Highlights/Website Highlights"}], "live")

        def untick(self, slug):
            self.unticked.append(slug)
            return (True, "unticked") if untick_ok else (False, "dashboard unreachable")

    class _Admin:
        def __init__(self):
            self.removed = []

        def remove_folder(self, folder_id):
            self.removed.append(folder_id)

    class _Stub:
        _managed = True
        # The drive is present here; SYNC-13's refusal has its own test below.
        _root_absent = False
        config = {"local_root": str(root)}

        def effective_mode(self):
            return mode

    stub = _Stub()
    stub.selection_client = _Selection()
    stub.syncthing_admin = _Admin()
    stub.removable_projects = lambda: CompanionApp.removable_projects(stub)
    # The caught-up gate (COMMERCIAL_READINESS.md item 9, 2026-08-17): these
    # tests are about the untick/unshare/delete ORDERING, so the gate is
    # stubbed open by default and driven explicitly by the tests that are
    # about the gate itself.
    stub.removal_blockers = lambda slug: dict(
        blockers or {"blocked": False, "reasons": [], "pending_uploads": 0,
                     "lane_c": {}, "unknown": False}
    )
    stub._note_removal_override = lambda slug, rel, b: None
    stub.remove = lambda slug, override=False: CompanionApp.remove_project_from_machine(
        stub, slug, override=override)
    return stub, proj


def test_remove_project_untick_unshare_delete_in_order(tmp_path):
    stub, proj = _remove_stub(tmp_path)
    ok, msg = stub.remove("2026-cct-website-highlights-website-highlights")
    assert ok, msg
    assert stub.selection_client.unticked == ["2026-cct-website-highlights-website-highlights"]
    assert stub.syncthing_admin.removed == ["2026-cct-website-highlights-website-highlights"]
    assert not proj.exists()
    assert "server copy is untouched" in msg


def test_remove_project_stops_before_deleting_when_untick_fails(tmp_path):
    stub, proj = _remove_stub(tmp_path, untick_ok=False)
    ok, msg = stub.remove("2026-cct-website-highlights-website-highlights")
    assert not ok
    assert "nothing was deleted" in msg
    assert proj.exists()                     # the local copy survives intact
    assert stub.syncthing_admin.removed == []


def test_remove_project_refuses_on_base_rig(tmp_path):
    stub, proj = _remove_stub(tmp_path, mode="base")
    ok, msg = stub.remove("2026-cct-website-highlights-website-highlights")
    assert not ok and "base rig" in msg
    assert proj.exists()


def test_remove_project_refuses_unselected_slug(tmp_path):
    stub, proj = _remove_stub(tmp_path)
    ok, msg = stub.remove("some-other-project")
    assert not ok and "not selected" in msg
    assert proj.exists()



# -- P: grade-swap (2026-07-26) ---------------------------------------------


def _swap_stub(monkeypatch, mode="editor", unc="\\\\nas\\Pool\\CC"):
    from ccsync_companion.app import CompanionApp

    class _Stub:
        config = {"server_p_unc": unc, "local_root": "D:\\Creators_Club"}

        def effective_mode(self):
            return mode

    stub = _Stub()
    stub._server_p_unc = lambda: CompanionApp._server_p_unc(stub)
    stub.p_swap_available = lambda: CompanionApp.p_swap_available(stub)
    stub.swap_to_server = lambda: CompanionApp.swap_p_to_server(stub)
    return stub


def test_p_swap_available_guards(monkeypatch):
    import os
    if os.name != "nt":
        import pytest
        pytest.skip("windows-only feature")
    stub = _swap_stub(monkeypatch)
    assert stub.p_swap_available() is True
    assert _swap_stub(monkeypatch, mode="base").p_swap_available() is False
    assert _swap_stub(monkeypatch, unc="").p_swap_available() is False


def test_p_mapping_mode_is_none_off_windows(monkeypatch):
    """macOS has no drive namespace: `net use`/`subst` don't exist, and the
    watcher asks for this on EVERY mapping warning -- drive_swap's default
    runner would try to spawn a missing binary each time."""
    from ccsync_companion import app as app_mod
    from ccsync_companion.app import CompanionApp

    monkeypatch.setattr(app_mod.os, "name", "posix")
    stub = _swap_stub(monkeypatch)

    assert CompanionApp.p_mapping_mode(stub) == "none"
    # and nothing was cached, so the Windows path is unaffected next call
    assert getattr(stub, "_p_mode_cache", None) is None


def test_p_swap_available_derives_when_unconfigured(monkeypatch):
    """Fleet-wide default: with server_p_unc unset, the UNC is derived from
    dashboard_url + remote_root, so every companion install gets the swap."""
    import os
    if os.name != "nt":
        import pytest
        pytest.skip("windows-only feature")
    stub = _swap_stub(monkeypatch, unc="")
    stub.config = dict(stub.config)
    stub.config.update({
        "dashboard_url": "http://192.168.0.10:8480",
        "remote_root": "/mnt/tank/TheCreatorsPool/Creators_Club",
    })
    assert stub._server_p_unc() == "\\\\192.168.0.10\\TheCreatorsPool\\Creators_Club"
    assert stub.p_swap_available() is True

    # explicit off switch hides the feature
    stub.config["server_p_unc"] = "off"
    assert stub._server_p_unc() == ""
    assert stub.p_swap_available() is False


def test_swap_p_to_server_restores_local_on_failure(monkeypatch):
    import os
    if os.name != "nt":
        import pytest
        pytest.skip("windows-only feature")
    from ccsync_companion import drive_swap

    restored = []
    monkeypatch.setattr(drive_swap, "swap_to_server",
                        lambda unc, run_fn=None, **kw: (False, "Access is denied"))
    monkeypatch.setattr(drive_swap, "swap_to_local",
                        lambda root, run_fn=None: (restored.append(root) or True, "back"))
    stub = _swap_stub(monkeypatch)
    ok, msg = stub.swap_to_server()
    assert not ok
    assert restored == ["D:\\Creators_Club"]
    assert "restored to your local copy" in msg
    assert stub._p_swap_busy is False        # busy flag always cleared


def test_swap_p_to_server_persists_credentials_on_success(monkeypatch):
    import os
    if os.name != "nt":
        import pytest
        pytest.skip("windows-only feature")
    from ccsync_companion import drive_swap

    persisted = []
    monkeypatch.setattr(drive_swap, "swap_to_server",
                        lambda unc, run_fn=None, **kw: (True, "P: now shows the SERVER originals"))
    monkeypatch.setattr(drive_swap, "persist_credentials",
                        lambda unc, u, p, run_fn=None: persisted.append((u, p)))
    stub = _swap_stub(monkeypatch)
    from ccsync_companion.app import CompanionApp
    ok, _ = CompanionApp.swap_p_to_server(stub, "owen", "pw")
    assert ok
    assert persisted == [("owen", "pw")]

    # no credentials given -> nothing persisted
    ok, _ = CompanionApp.swap_p_to_server(stub)
    assert ok
    assert persisted == [("owen", "pw")]


# --- shutdown guard wiring (shutdown_guard.py owns the policy) -------------

def _busy_lane():
    from ccsync_companion.sync.base import STATE_SYNCING, LaneStatus

    class Lane:
        name = "lane_a"

        def status(self):
            return LaneStatus(name="lane_a", state=STATE_SYNCING,
                              bytes_done=0, bytes_total=10 * 1024**3)

    return Lane()


def test_shutdown_reason_names_the_sync_in_flight(tmp_path):
    app = _make_app(tmp_path)
    app.lanes = [_busy_lane()]
    reason = app._shutdown_block_reason()
    assert reason and "still syncing" in reason


def test_no_shutdown_reason_when_lanes_are_idle(tmp_path):
    from ccsync_companion.sync.base import LaneStatus

    class Idle:
        name = "lane_a"

        def status(self):
            return LaneStatus(name="lane_a")

    app = _make_app(tmp_path)
    app.lanes = [Idle()]
    assert app._shutdown_block_reason() is None


def test_pausing_sync_also_stops_warning_about_shutdown(tmp_path):
    """Pause means the editor already chose to stop syncing; nagging them at
    the shutdown screen after that is just noise."""
    app = _make_app(tmp_path)
    app.lanes = [_busy_lane()]
    app._paused = True
    assert app._shutdown_block_reason() is None


def test_a_lane_that_cannot_report_status_never_blocks_shutdown(tmp_path):
    class Broken:
        name = "lane_a"

        def status(self):
            raise RuntimeError("boom")

    app = _make_app(tmp_path)
    app.lanes = [Broken()]
    assert app._shutdown_block_reason() is None


def test_shutdown_warning_can_be_switched_off(tmp_path):
    from ccsync_companion import shutdown_guard as sg

    app = _make_app(tmp_path, shutdown_warning_enabled=False)
    app._start_shutdown_guard()
    assert type(app._shutdown_guard) is sg.ShutdownGuard
    assert app._shutdown_guard.active is False


def test_shutdown_releases_the_guard(tmp_path):
    """A guard left holding a block reason would keep refusing shutdowns on
    behalf of a companion that has already exited."""
    stopped = []

    class Guard:
        def stop(self):
            stopped.append(True)

    app = _make_app(tmp_path)
    app._shutdown_guard = Guard()
    app.shutdown()
    assert stopped == [True]
    assert app._shutdown_guard is None


def test_a_guard_that_fails_to_stop_does_not_break_shutdown(tmp_path):
    class Guard:
        def stop(self):
            raise RuntimeError("boom")

    app = _make_app(tmp_path)
    app._shutdown_guard = Guard()
    app.shutdown()
    assert app._shutdown_guard is None


def test_keep_awake_holds_while_a_lane_is_busy(tmp_path):
    from ccsync_companion import shutdown_guard as sg

    app = _make_app(tmp_path)
    app.lanes = [_busy_lane()]
    guard = sg._WindowsKeepAwake(
        lambda: app._shutdown_block_reason() is not None,
        set_state_fn=lambda flags: sg.ES_CONTINUOUS,
    )
    assert guard.apply_once() is True


def test_keep_awake_lets_an_idle_machine_sleep(tmp_path):
    from ccsync_companion import shutdown_guard as sg
    from ccsync_companion.sync.base import LaneStatus

    class Idle:
        name = "lane_a"

        def status(self):
            return LaneStatus(name="lane_a")

    app = _make_app(tmp_path)
    app.lanes = [Idle()]
    guard = sg._WindowsKeepAwake(
        lambda: app._shutdown_block_reason() is not None,
        set_state_fn=lambda flags: sg.ES_CONTINUOUS,
    )
    assert guard.apply_once() is False


def test_keep_awake_can_be_switched_off(tmp_path):
    from ccsync_companion import shutdown_guard as sg

    app = _make_app(tmp_path, keep_awake_while_syncing=False)
    app._start_keep_awake()
    assert type(app._keep_awake) is sg.KeepAwakeGuard
    assert app._keep_awake.held is False


def test_shutdown_releases_both_power_guards(tmp_path):
    """Either guard left holding its state would outlive the companion: one
    refusing shutdowns, the other refusing sleep."""
    stopped = []

    class Guard:
        def __init__(self, label):
            self.label = label

        def stop(self):
            stopped.append(self.label)

    app = _make_app(tmp_path)
    app._shutdown_guard = Guard("shutdown")
    app._keep_awake = Guard("keep-awake")
    app.shutdown()
    assert sorted(stopped) == ["keep-awake", "shutdown"]
    assert app._shutdown_guard is None
    assert app._keep_awake is None


def test_a_failing_shutdown_guard_does_not_strand_the_keep_awake(tmp_path):
    """The stop loop must keep going past a guard that throws, or the second
    guard silently keeps the machine awake forever."""
    stopped = []

    class Boom:
        def stop(self):
            raise RuntimeError("boom")

    class Guard:
        def stop(self):
            stopped.append("keep-awake")

    app = _make_app(tmp_path)
    app._shutdown_guard = Boom()
    app._keep_awake = Guard()
    app.shutdown()
    assert stopped == ["keep-awake"]


# --- B9: a disconnected NAS must not keep the machine awake forever --------


def _lane(name, **kw):
    from ccsync_companion.sync.base import LaneStatus

    class Lane:
        def __init__(self):
            self.name = name

        def status(self):
            return LaneStatus(name=name, **kw)

    return Lane()


def test_a_stalled_lane_stops_blocking_shutdown_after_the_stale_window(tmp_path):
    """B9. Lane C reports "syncing" from a NEED COUNT, so a NAS that went off
    overnight with four unreceived files left _shutdown_block_reason()
    returning a sentence forever: ES_CONTINUOUS|ES_SYSTEM_REQUIRED held
    permanently (the PC never slept again until the companion restarted) and
    every shutdown interrupted with zero bytes in flight."""
    from ccsync_companion import shutdown_guard as sg
    from ccsync_companion.sync.base import STATE_SYNCING

    clock = {"now": 0.0}
    app = _make_app(tmp_path)
    app.lanes = [_lane("lane_c_syncthing", state=STATE_SYNCING, queued=4)]
    app._pending_tracker = sg.PendingTracker(
        stale_seconds=180.0, clock=lambda: clock["now"])

    assert app._shutdown_block_reason() is not None
    clock["now"] += 3600
    assert app._shutdown_block_reason() is None


def test_the_liveness_thresholds_come_from_config(tmp_path):
    """Editors run a prebuilt exe, so both bounds are config keys: tuning a
    machine in the field must not need a rebuild."""
    app = _make_app(tmp_path, keep_awake_stale_seconds=45,
                    keep_awake_max_hold_seconds=600)
    assert app._pending_tracker._stale_seconds == 45.0
    assert app._pending_tracker._max_hold_seconds == 600.0


def test_a_tuned_stale_window_actually_changes_the_verdict(tmp_path):
    from ccsync_companion.sync.base import STATE_SYNCING

    app = _make_app(tmp_path, keep_awake_stale_seconds=30)
    app.lanes = [_lane("lane_c_syncthing", state=STATE_SYNCING, queued=4)]
    clock = {"now": 0.0}
    app._pending_tracker._clock = lambda: clock["now"]

    assert app._shutdown_block_reason() is not None
    clock["now"] += 31
    assert app._shutdown_block_reason() is None


@pytest.mark.parametrize("bad", ["3 minutes", 0, -5, None])
def test_a_hand_edited_threshold_never_crashes_construction(tmp_path, bad):
    """CompanionApp is constructed before anything can report a config
    problem, and in the windowed build a raise here is the exe vanishing with
    no tray and no log line (CORE-H2/M4). Bad values fall back to the shipped
    defaults instead."""
    from ccsync_companion import shutdown_guard as sg

    app = _make_app(tmp_path, keep_awake_stale_seconds=bad,
                    keep_awake_max_hold_seconds=bad)
    assert app._pending_tracker._stale_seconds == sg.PROGRESS_STALE_SECONDS
    assert app._pending_tracker._max_hold_seconds == sg.MAX_HOLD_SECONDS


def test_a_config_without_the_thresholds_uses_the_shipped_defaults(tmp_path):
    """An older config.toml (or any dict that predates the keys) must behave
    exactly as before."""
    from ccsync_companion import shutdown_guard as sg

    app = _make_app(tmp_path)
    assert "keep_awake_stale_seconds" not in app.config
    assert app._pending_tracker._stale_seconds == sg.PROGRESS_STALE_SECONDS
    assert app._pending_tracker._max_hold_seconds == sg.MAX_HOLD_SECONDS


def test_a_lane_with_no_syncthing_peer_does_not_block_shutdown(tmp_path):
    """The connectivity half: lane C's poll already caches
    /rest/system/connections, and an empty connected set means its backlog has
    nowhere to go."""
    from ccsync_companion.sync.base import STATE_SYNCING

    app = _make_app(tmp_path)
    lane_c_name = app._lane_c.name
    app.lanes = [_lane(lane_c_name, state=STATE_SYNCING, queued=4)]

    app._lane_c.connection_path_summary = lambda: {
        "devices": {}, "relayed": [], "direct": []}
    assert app._shutdown_block_reason() is None

    app._pending_tracker.reset()
    app._lane_c.connection_path_summary = lambda: {
        "devices": {"ABC": "tcp-client"}, "relayed": [], "direct": ["ABC"]}
    assert app._shutdown_block_reason() is not None


def test_an_unpolled_syncthing_lane_still_blocks_shutdown(tmp_path):
    """"Can't tell" must never silence the warning -- before the first
    successful connections poll the summary is empty."""
    from ccsync_companion.sync.base import STATE_SYNCING

    app = _make_app(tmp_path)
    app.lanes = [_lane(app._lane_c.name, state=STATE_SYNCING, queued=4)]
    app._lane_c.connection_path_summary = lambda: {}
    assert app._shutdown_block_reason() is not None


def test_lane_peer_states_survives_a_lane_that_raises(tmp_path):
    app = _make_app(tmp_path)

    def boom():
        raise RuntimeError("syncthing lane exploded")

    app._lane_c.connection_path_summary = boom
    assert app._lane_peer_states() == {}


def test_both_power_guards_read_the_same_liveness_verdict(tmp_path):
    """One tracker, shared: the keep-awake loop's 30 s poll is what keeps the
    samples fresh for the shutdown guard, which is only ever called once, at
    the instant someone clicks Shut down."""
    from ccsync_companion import shutdown_guard as sg
    from ccsync_companion.sync.base import STATE_SYNCING

    clock = {"now": 0.0}
    app = _make_app(tmp_path)
    app.lanes = [_lane("lane_a", state=STATE_SYNCING, queued=1)]
    app._pending_tracker = sg.PendingTracker(
        stale_seconds=120.0, clock=lambda: clock["now"])
    guard = sg._WindowsKeepAwake(
        lambda: app._shutdown_block_reason() is not None,
        set_state_fn=lambda flags: sg.ES_CONTINUOUS,
    )
    assert guard.apply_once() is True
    clock["now"] += 600
    assert guard.apply_once() is False, "held the idle timer for a stalled lane"
    assert app._shutdown_block_reason() is None


# --- B11: copy_diagnostics opens a Tk root, so it takes the popup lock -----


class _FakeTkRoot:
    """A stand-in for the hidden clipboard root -- no window, ever."""

    instances: list = []

    def __init__(self):
        self.text = None
        self.destroyed = False
        _FakeTkRoot.instances.append(self)

    def withdraw(self):
        pass

    def clipboard_clear(self):
        self.text = ""

    def clipboard_append(self, text):
        self.text = (self.text or "") + text

    def update(self):
        pass

    def destroy(self):
        self.destroyed = True


def test_copy_diagnostics_refuses_while_another_window_is_open(tmp_path):
    """B11. Every other tk.Tk() site takes _popup_active_lock; this one did
    not, so a watcher popup on a sibling thread and this hidden root could be
    live at once -- the wedged-Tcl condition the lock exists to prevent. It
    also bypassed apply_upgrade's popup-lock guard, so a self-upgrade could
    swap the exe while a Tk root was live."""
    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    app._popup_active_lock.acquire()
    try:
        assert app.copy_diagnostics() is False
    finally:
        app._popup_active_lock.release()
    # ...and the admin is not left with nothing: it went to the log instead.
    assert any("log" in msg for msg, _title in app._tray_icon.notifications)


def test_copy_diagnostics_holds_the_lock_while_its_root_is_alive(tmp_path, monkeypatch):
    import tkinter

    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    _FakeTkRoot.instances.clear()
    locked_during = []

    def _fake_tk():
        locked_during.append(app._popup_active_lock.locked())
        return _FakeTkRoot()

    monkeypatch.setattr(tkinter, "Tk", _fake_tk)

    assert app.copy_diagnostics() is True
    assert locked_during == [True]
    assert not app._popup_active_lock.locked(), "the lock outlived the clipboard root"
    assert _FakeTkRoot.instances[0].destroyed is True
    assert "CCSYNC DIAGNOSTICS" in (_FakeTkRoot.instances[0].text or "")


def test_copy_diagnostics_releases_the_lock_when_the_clipboard_fails(tmp_path, monkeypatch):
    import tkinter

    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()

    def _boom():
        raise RuntimeError("no display")

    monkeypatch.setattr(tkinter, "Tk", _boom)
    assert app.copy_diagnostics() is False
    assert not app._popup_active_lock.locked()


# --- the popup queue must not strand a batch ------------------------------


def test_a_batch_queued_in_the_release_gap_is_still_shown(tmp_path, monkeypatch):
    """A thread finishing its last dialog sees an empty queue, and only THEN
    releases the lock. A batch queued in that gap had nobody left to show it
    -- and because its paths stay in _popup_queue_keys, every later sighting
    of those clips deduped against a batch that would never be shown, so they
    were lost for the rest of the session."""
    app = _make_app(tmp_path)
    first = _item(str(tmp_path / "first.mov"))
    late = _item(str(tmp_path / "late.mov"))

    shown: list[list[str]] = []
    monkeypatch.setattr(
        popup, "show_popup",
        lambda items, *a, **k: shown.append([i["file_path"] for i in items]),
    )

    real_take = app._take_popup_batch
    raced: list[bool] = []

    def take_and_race():
        batch = real_take()
        if batch is None and not raced:
            raced.append(True)
            # Exactly the gap: another thread queues after this one has
            # already seen an empty queue but before it releases the lock.
            app._queue_popup_batch([late], snooze=False)
        return batch

    app._take_popup_batch = take_and_race
    app._show_out_of_tree_popup([first])

    assert shown == [[first["file_path"]], [late["file_path"]]]
    assert app._popup_queue == []
    assert app._popup_queue_keys == set()


def test_a_batch_that_loses_the_race_is_still_queued_not_dropped(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    item = _item(str(tmp_path / "clip.mov"))
    monkeypatch.setattr(popup, "show_popup", lambda *a, **k: None)

    app._popup_active_lock.acquire()  # a dialog is on screen
    try:
        app._show_out_of_tree_popup([item])
        assert len(app._popup_queue) == 1
    finally:
        app._popup_active_lock.release()

    shown: list[list[str]] = []
    monkeypatch.setattr(
        popup, "show_popup",
        lambda items, *a, **k: shown.append([i["file_path"] for i in items]),
    )
    app._drain_stranded_popup_batches()
    assert shown == [[item["file_path"]]]


# --- shutdown() must not run twice ----------------------------------------


def test_shutdown_is_idempotent(tmp_path):
    """The tray's Quit calls shutdown() and then icon.stop(), which lets
    run()'s finally clause call it again -- two overlapping teardowns racing
    two _stop_lanes()/reporter.stop() sequences (RcloneLane.stop racing
    itself over self._observer = None)."""
    app = _make_app(tmp_path)
    calls: list[str] = []
    for lane in app.lanes:
        lane.stop = lambda name=lane.name: calls.append(name)
    app.reporter.stop = lambda: calls.append("reporter")
    app.manifest_cache.stop = lambda: calls.append("manifest")

    app.shutdown()
    first = list(calls)
    app.shutdown()

    assert calls == first, "shutdown() ran its teardown twice"
    assert "reporter" in first


# --- external-SSD root guard (root_guard.py) -------------------------------
#
# A macOS editor's tree lives on an external SSD that gets unplugged
# routinely. Everything here is exercised on Windows through the app's own
# seams (self._root_absent and the guard's two callbacks); nothing spawns
# diskutil and nothing depends on the host OS.


def _pretend_darwin(monkeypatch) -> None:
    import sys as _sys

    monkeypatch.setattr(_sys, "platform", "darwin", raising=False)


def _darwin_app(tmp_path, monkeypatch, **overrides) -> CompanionApp:
    """A macOS-shaped app whose local_root is on an SSD that is NOT plugged
    in -- i.e. /Volumes/T7/Creators_Club does not exist."""
    _pretend_darwin(monkeypatch)
    cfg = _cfg(tmp_path, **overrides)
    cfg["local_root"] = "/Volumes/T7/Creators_Club"
    return CompanionApp(cfg)


def test_a_missing_removable_root_is_demoted_out_of_config_problems(tmp_path, monkeypatch):
    """config_problems is computed ONCE in __init__ and _start_lanes()
    refuses on any entry -- so an SSD unplugged at login used to brick sync
    until the editor thought to restart the companion, under a tray line
    saying the machine "isn't set up": not true, and naming nothing they
    could fix."""
    from ccsync_companion import config as config_mod

    app = _darwin_app(tmp_path, monkeypatch)

    assert app.config_problems == []
    assert app._root_absent is True
    assert "local_root does not exist" in (app._root_demoted_problem or "")
    # validate_config itself is untouched: the CLI and the dashboard must
    # still be told the truth about the tree.
    errors, _warnings = config_mod.validate_config(app.config)
    assert any("local_root does not exist" in e for e in errors)


def test_the_demotion_does_not_apply_to_a_blank_local_root(tmp_path, monkeypatch):
    """A blank local_root is a real misconfiguration -- every destination
    becomes CWD-relative (AUDIT_2 CORE-H1) -- and stays a config error."""
    _pretend_darwin(monkeypatch)
    app = CompanionApp(_cfg(tmp_path, local_root=""))
    assert any("local_root is blank" in p for p in app.config_problems)
    assert app._root_absent is False


def test_the_demotion_does_not_apply_to_an_internal_root(tmp_path, monkeypatch):
    """A typo'd path on the internal disk is not a disconnected drive."""
    _pretend_darwin(monkeypatch)
    app = CompanionApp(_cfg(tmp_path, local_root=str(tmp_path / "nope")))
    assert any("local_root does not exist" in p for p in app.config_problems)
    assert app._root_absent is False


def test_the_demotion_does_not_apply_when_something_else_is_broken(tmp_path, monkeypatch):
    """Anything else in config_problems genuinely needs fixing first, so the
    lanes stay down for the reason they always did."""
    app = _darwin_app(tmp_path, monkeypatch, remote_root="")
    assert len(app.config_problems) >= 1
    assert app._root_absent is False


def test_lanes_are_deferred_while_the_drive_is_out(tmp_path, monkeypatch):
    """Deferred, not refused: _start_lanes() is the gate every entry point
    goes through (start(), on_signed_in(), toggle_pause()), and the lane
    detail has to name the drive, not the setup."""
    app = _darwin_app(tmp_path, monkeypatch, sync_enabled=True)
    started: list[str] = []
    for lane in app.lanes:
        lane.start = lambda name=lane.name: started.append(name)

    app._start_lanes()

    assert started == []
    assert app._lanes_started is False
    details = [str(s.detail) for s in app.lane_statuses()]
    assert all("drive is disconnected" in d for d in details)


def test_on_present_starts_the_deferred_lanes_and_clears_the_prefix_cache(
    tmp_path, monkeypatch
):
    from ccsync_companion import paths as paths_mod
    from ccsync_companion import root_guard as root_guard_mod

    # require_login=False: _root_resume_lanes honours every OTHER reason sync
    # might be down, and an unsigned-in machine is one of them.
    app = _darwin_app(tmp_path, monkeypatch, sync_enabled=True, require_login=False)
    app._tray_icon = _FakeTray()
    started: list[str] = []
    monkeypatch.setattr(app, "_start_lanes", lambda: started.append("start"))
    cleared: list[str] = []
    monkeypatch.setattr(paths_mod, "clear_prefix_cache", lambda: cleared.append("x"))
    refreshed: list[str] = []
    monkeypatch.setattr(root_guard_mod, "refresh_volume_record",
                        lambda root, **kw: refreshed.append(root))

    app._on_root_present()

    assert started == ["start"]
    assert app._root_absent is False
    assert cleared == ["x"]
    assert refreshed == ["/Volumes/T7/Creators_Club"]
    assert any("reconnected" in msg for msg, _title in app._tray_icon.notifications)


def test_on_present_says_nothing_when_the_drive_was_never_gone(tmp_path, monkeypatch):
    """The guard's FIRST sighting on a healthy machine fires on_present too.
    Nothing was paused, so there is nothing to resume and nothing to say."""
    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    started: list[str] = []
    monkeypatch.setattr(app, "_start_lanes", lambda: started.append("start"))

    app._on_root_present()

    assert started == []
    assert app._tray_icon.notifications == []


def test_on_absent_pauses_the_sequencer_and_toasts_once(tmp_path, monkeypatch):
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com", sync_enabled=True)
    app._tray_icon = _FakeTray()
    events: list[str] = []
    monkeypatch.setattr(app.sequencer, "pause", lambda: events.append("pause"))
    monkeypatch.setattr(app, "_set_express_paused",
                        lambda paused: events.append(f"express={paused}"))

    app._on_root_absent("absent")
    app._on_root_absent("absent")

    assert events == ["pause", "express=True", "pause", "express=True"]
    assert app._root_absent is True
    # The toast is once per EPISODE, not once per 5 s poll.
    toasts = [m for m, _t in app._tray_icon.notifications if "disconnected" in m]
    assert len(toasts) == 1
    assert "Sync paused" in toasts[0]


def test_on_absent_does_not_touch_the_editors_own_pause_toggle(tmp_path, monkeypatch):
    """self._paused is the tray's checkbox. Flipping it from a poll thread
    would leave "Resume syncing" ticked with nobody having clicked it."""
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com")
    monkeypatch.setattr(app.sequencer, "pause", lambda: None)
    app._on_root_absent("absent")
    assert app.is_paused() is False


def test_the_drive_coming_back_does_not_override_a_deliberate_pause(tmp_path, monkeypatch):
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com")
    app._paused = True
    resumed: list[str] = []
    monkeypatch.setattr(app.sequencer, "resume", lambda: resumed.append("resume"))
    monkeypatch.setattr(app, "_start_lanes", lambda: resumed.append("start"))

    app._root_absent = True
    app._on_root_present()

    assert resumed == []


def test_on_present_resumes_and_triggers_an_immediate_pass(tmp_path, monkeypatch):
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com",
                    sync_enabled=True, require_login=False)
    app._lanes_started = True
    app._root_absent = True
    events: list[str] = []
    monkeypatch.setattr(app.sequencer, "resume", lambda: events.append("resume"))
    monkeypatch.setattr(app.sequencer, "trigger_pass_now",
                        lambda: events.append("trigger"))

    app._on_root_present()

    assert events == ["resume", "trigger"]


def test_a_misplaced_drive_pops_one_dialog_per_episode(tmp_path, monkeypatch):
    """The one case the editor must ACT on: the drive is mounted at
    "/Volumes/T7 1" because a leftover folder occupies /Volumes/T7. Routed
    through the EXISTING popup lock + popup.confirm_dialog, not new UI
    plumbing."""
    app = _darwin_app(tmp_path, monkeypatch, dashboard_url="http://dash.example.com")
    app._tray_icon = _FakeTray()
    monkeypatch.setattr(app.sequencer, "pause", lambda: None)
    shown: list[tuple[str, str]] = []
    done = threading.Event()

    def _fake_confirm(title, body, **kwargs):
        shown.append((title, body))
        done.set()
        return True

    monkeypatch.setattr(popup, "confirm_dialog", _fake_confirm)

    app._on_root_absent("misplaced")
    assert done.wait(5.0), "the misplaced-drive dialog never opened"
    # Same episode: the second sighting must not stack another modal.
    app._on_root_absent("misplaced")

    assert len(shown) == 1
    title, body = shown[0]
    assert "wrong path" in title
    assert "/Volumes/T7" in body
    assert "Eject" in body and "leftover" in body


def test_the_misplaced_dialog_defers_to_a_window_already_on_screen(tmp_path, monkeypatch):
    """Tk permits one root in this process, and the toast has already
    carried the message -- do not queue a modal the editor meets minutes
    later with no context."""
    app = _darwin_app(tmp_path, monkeypatch)
    shown: list[str] = []
    monkeypatch.setattr(popup, "confirm_dialog",
                        lambda *a, **k: shown.append("shown") or True)
    app._popup_active_lock.acquire()
    try:
        app._show_root_misplaced_dialog("body")
    finally:
        app._popup_active_lock.release()
    assert shown == []


def test_scan_whole_project_is_gated_on_the_drive(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    app._root_absent = True
    called: list[str] = []
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: called.append("scan") or _mp_result())

    app.scan_whole_project()

    assert called == []
    assert any("disconnected" in msg for msg, _t in app._tray_icon.notifications)


def test_the_shutdown_warning_is_suppressed_while_the_drive_is_out(tmp_path):
    """Nothing can be moving with the tree unplugged, whatever backlog the
    lanes still report -- and "still syncing" on the shutdown screen of an
    unplugged machine is exactly the cry-wolf failure the guard avoids."""
    app = _make_app(tmp_path)
    app._root_absent = True
    assert app._shutdown_block_reason() is None


def test_the_shutdown_guard_is_given_the_apps_shutdown_path(tmp_path, monkeypatch):
    """On macOS, logout and `launchctl bootout` arrive as SIGTERM, and
    shutdown_guard deliberately installs NO handler without a callback to
    run (one that did nothing would swallow SIGTERM and hang the bootout) --
    so this argument is the whole feature."""
    from ccsync_companion import shutdown_guard as sg

    app = _make_app(tmp_path)
    captured: dict = {}

    def _fake_make(reason_fn, enabled=True, on_shutdown=None):
        captured["on_shutdown"] = on_shutdown
        return sg.ShutdownGuard()

    monkeypatch.setattr(sg, "make_shutdown_guard", _fake_make)
    app._start_shutdown_guard()
    assert captured["on_shutdown"] == app.shutdown


def test_the_watcher_stands_down_while_the_drive_is_out(tmp_path):
    """Without this every clip on the timeline misclassifies -- BAD_PREFIX
    warning storms and OUT_OF_TREE popups offering to copy media into a
    directory that does not exist."""
    app = _make_app(tmp_path)
    polled: list[str] = []
    app.watcher._get_timeline_items = lambda: polled.append("poll") or {
        "ok": True, "items": [], "project_name": "X"}

    assert app.watcher.poll_once()["ok"] is True
    app._root_absent = True
    result = app.watcher.poll_once()

    assert result["ok"] is False
    assert "drive disconnected" in result["message"]
    assert polled == ["poll"]


def test_the_manifest_cache_is_given_the_root_gate(tmp_path):
    app = _make_app(tmp_path)
    assert app.manifest_cache._root_present_fn == app.root_is_present


def test_root_is_present_is_true_unless_we_know_otherwise(tmp_path):
    app = _make_app(tmp_path)
    assert app.root_is_present() is True
    app._root_absent = True
    assert app.root_is_present() is False


# --- the self-upgrade respawn race (CCSYNC_REPLACES_PID) -------------------


def test_the_lock_file_waits_for_the_predecessor_it_replaces(monkeypatch, tmp_path):
    """upgrade._default_spawn launches the new build BEFORE this one exits
    (it must: request_shutdown() comes after the spawn, so a failed launch
    can still roll the swap back). On posix the pid file is a LIVENESS
    check, and the dying predecessor is alive for as long as its lanes take
    to stop -- so the freshly-installed build exited immediately and the
    machine was left with NO companion until the next login."""
    from ccsync_companion import app as app_mod
    from ccsync_companion import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "cc")
    (tmp_path / "cc").mkdir(parents=True)
    (tmp_path / "cc" / app_mod._SINGLE_INSTANCE_LOCKFILE).write_text(
        "4242", encoding="utf-8")
    monkeypatch.setenv(app_mod._REPLACES_PID_ENV, "4242")

    alive = {"value": True}
    slept: list[float] = []

    def _sleep(seconds):
        slept.append(seconds)
        alive["value"] = False  # the predecessor finishes its shutdown

    assert app_mod._acquire_lock_file(
        alive_fn=lambda pid: alive["value"], sleep_fn=_sleep
    ) is True
    assert slept, "it raced through instead of waiting"
    assert (tmp_path / "cc" / app_mod._SINGLE_INSTANCE_LOCKFILE).read_text(
        encoding="utf-8") == str(os.getpid())
    # Popped, so no child of ours inherits a stale claim.
    assert app_mod._REPLACES_PID_ENV not in os.environ


def test_a_predecessor_that_never_dies_falls_through_to_already_running(
    monkeypatch, tmp_path
):
    """Bounded on purpose: a predecessor that is wedged rather than shutting
    down IS a live second instance, and starting over it is what the guard
    exists to prevent."""
    from ccsync_companion import app as app_mod
    from ccsync_companion import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "cc")
    (tmp_path / "cc").mkdir(parents=True)
    (tmp_path / "cc" / app_mod._SINGLE_INSTANCE_LOCKFILE).write_text(
        "4242", encoding="utf-8")
    monkeypatch.setenv(app_mod._REPLACES_PID_ENV, "4242")

    clock = {"now": 0.0}

    def _tick(seconds):
        clock["now"] += seconds

    assert app_mod._acquire_lock_file(
        alive_fn=lambda pid: True, clock=lambda: clock["now"], sleep_fn=_tick,
    ) is False


def test_an_unrelated_live_holder_is_never_waited_for(monkeypatch, tmp_path):
    """Only the pid we were TOLD we replace. A different companion holding
    the slot is refused immediately, exactly as before."""
    from ccsync_companion import app as app_mod
    from ccsync_companion import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "cc")
    (tmp_path / "cc").mkdir(parents=True)
    (tmp_path / "cc" / app_mod._SINGLE_INSTANCE_LOCKFILE).write_text(
        "999999", encoding="utf-8")
    monkeypatch.setenv(app_mod._REPLACES_PID_ENV, "4242")

    slept: list[float] = []
    assert app_mod._acquire_lock_file(
        alive_fn=lambda pid: True, sleep_fn=slept.append
    ) is False
    assert slept == []


def test_the_replaces_pid_variable_is_popped_even_when_unused(monkeypatch, tmp_path):
    from ccsync_companion import app as app_mod
    from ccsync_companion import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "cc")
    monkeypatch.setenv(app_mod._REPLACES_PID_ENV, "4242")
    app_mod._acquire_lock_file()
    assert app_mod._REPLACES_PID_ENV not in os.environ


def test_the_lock_file_accepts_a_pre_popped_replaces_pid(monkeypatch, tmp_path):
    """acquire_single_instance() pops the variable BEFORE trying the mutex;
    when the mutex guard is broken and it falls back here, the value arrives
    as a parameter. A second pop would read nothing and silently lose the
    predecessor wait exactly when the primary guard is down."""
    from ccsync_companion import app as app_mod
    from ccsync_companion import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "cc")
    (tmp_path / "cc").mkdir(parents=True)
    (tmp_path / "cc" / app_mod._SINGLE_INSTANCE_LOCKFILE).write_text(
        "4242", encoding="utf-8")
    assert app_mod._REPLACES_PID_ENV not in os.environ  # already popped

    alive = {"value": True}

    def _sleep(seconds):
        alive["value"] = False

    assert app_mod._acquire_lock_file(
        alive_fn=lambda pid: alive["value"], sleep_fn=_sleep, replaces_pid=4242,
    ) is True


# --- R11: the win32 mutex twin of the predecessor wait ----------------------


class _FakeMutex:
    """The named kernel object, faithfully enough to catch the handle leak
    that would break the wait: the object EXISTS while any handle to it is
    open (the predecessor's or one of ours), and CreateMutexW on an existing
    object hands back a new handle plus ERROR_ALREADY_EXISTS. If the guard
    forgets to close a probe handle, the mutex can never die and every retry
    reads ALREADY_EXISTS forever -- exactly the bug these tests pin."""

    def __init__(self, predecessor_holds=True):
        self.predecessor_holds = predecessor_holds
        self.open_handles: set = set()
        self._next = 1

    def create(self):
        from ccsync_companion import app as app_mod

        existed = self.predecessor_holds or bool(self.open_handles)
        handle = self._next
        self._next += 1
        self.open_handles.add(handle)
        return handle, (app_mod._ERROR_ALREADY_EXISTS if existed else 0)

    def close(self, handle):
        self.open_handles.remove(handle)

    def predecessor_exits(self):
        self.predecessor_holds = False


def test_the_mutex_guard_waits_for_the_predecessor_it_replaces(monkeypatch):
    """R11 (2026-08-12): the win32 branch returned False the moment
    CreateMutexW said ERROR_ALREADY_EXISTS -- but the self-upgrade's child
    reaches the guard while the predecessor is still tearing down its lanes
    and holding the mutex. The child exited, the predecessor finished
    exiting, and the machine was left with NO companion until the next
    logon."""
    from ccsync_companion import app as app_mod

    monkeypatch.setattr(app_mod, "_single_instance_token", None)
    mutex = _FakeMutex(predecessor_holds=True)
    alive = {"value": True}

    def _sleep(seconds):
        mutex.predecessor_exits()
        alive["value"] = False

    assert app_mod._acquire_mutex_win32(
        mutex.create, mutex.close, replaces_pid=4242,
        alive_fn=lambda pid: alive["value"], sleep_fn=_sleep,
    ) is True
    # exactly one handle stays open: the slot we now hold
    assert mutex.open_handles == {app_mod._single_instance_token}


def test_the_mutex_wait_wins_even_when_the_liveness_probe_lies(monkeypatch):
    """Why the wait retries CreateMutexW instead of reusing
    _wait_for_predecessor's liveness-only loop: _pid_is_alive_win32 can read
    a DEAD process as alive (exit code 259, plus both fail-safe arms). Keyed
    on liveness alone the guard would sit out the full timeout and refuse --
    the retry takes the slot the moment the mutex is actually free."""
    from ccsync_companion import app as app_mod

    monkeypatch.setattr(app_mod, "_single_instance_token", None)
    mutex = _FakeMutex(predecessor_holds=True)

    def _sleep(seconds):
        mutex.predecessor_exits()  # ...but the probe keeps saying "alive"

    assert app_mod._acquire_mutex_win32(
        mutex.create, mutex.close, replaces_pid=4242,
        alive_fn=lambda pid: True, sleep_fn=_sleep,
    ) is True
    assert mutex.open_handles == {app_mod._single_instance_token}


def test_a_wedged_mutex_predecessor_falls_through_to_already_running(monkeypatch):
    """Bounded on purpose, same as the lock file: a predecessor that is
    wedged rather than shutting down IS a live second instance."""
    from ccsync_companion import app as app_mod

    monkeypatch.setattr(app_mod, "_single_instance_token", None)
    mutex = _FakeMutex(predecessor_holds=True)
    clock = {"now": 0.0}

    def _tick(seconds):
        clock["now"] += seconds

    assert app_mod._acquire_mutex_win32(
        mutex.create, mutex.close, replaces_pid=4242,
        alive_fn=lambda pid: True, clock=lambda: clock["now"], sleep_fn=_tick,
    ) is False
    assert mutex.open_handles == set(), "a probe handle leaked"
    assert app_mod._single_instance_token is None


def test_a_held_mutex_with_no_replaces_pid_is_refused_immediately(monkeypatch):
    """A plain double-start is not an upgrade hand-off: no wait, exactly the
    old behaviour."""
    from ccsync_companion import app as app_mod

    monkeypatch.setattr(app_mod, "_single_instance_token", None)
    mutex = _FakeMutex(predecessor_holds=True)
    slept: list = []

    assert app_mod._acquire_mutex_win32(
        mutex.create, mutex.close, replaces_pid=None,
        alive_fn=lambda pid: True, sleep_fn=slept.append,
    ) is False
    assert slept == []
    assert mutex.open_handles == set(), "a probe handle leaked"


def test_a_mutex_outliving_its_dead_predecessor_is_someone_elses(monkeypatch):
    """The predecessor was already gone before the retry, yet the mutex
    survived it -- so the holder is a different companion, and waiting out
    the full timeout would only delay the honest answer."""
    from ccsync_companion import app as app_mod

    monkeypatch.setattr(app_mod, "_single_instance_token", None)
    mutex = _FakeMutex(predecessor_holds=True)  # held, but not by pid 4242
    slept: list = []

    assert app_mod._acquire_mutex_win32(
        mutex.create, mutex.close, replaces_pid=4242,
        alive_fn=lambda pid: False, sleep_fn=slept.append,
    ) is False
    assert len(slept) == 1, "it should conclude after a single confirming retry"
    assert mutex.open_handles == set(), "a probe handle leaked"


def test_a_failed_mutex_creation_never_blocks_a_start(monkeypatch):
    """The guard failing is not the same as the slot being taken."""
    from ccsync_companion import app as app_mod

    monkeypatch.setattr(app_mod, "_single_instance_token", None)

    assert app_mod._acquire_mutex_win32(
        lambda: (0, 0), lambda handle: None, replaces_pid=None,
        alive_fn=lambda pid: True,
    ) is True


# --- macOS: the already-running alert + the activation policy --------------


def test_the_already_running_warning_uses_osascript_on_darwin(monkeypatch):
    """Without it, double-clicking the companion while it is already running
    does nothing visible at all -- so the editor clicks again, and again,
    and concludes it is broken."""
    from ccsync_companion import app as app_mod

    monkeypatch.setattr(app_mod.sys, "platform", "darwin", raising=False)
    spawned: list[list] = []
    monkeypatch.setattr(app_mod, "_osascript_run", spawned.append)

    app_mod._warn_already_running()

    assert len(spawned) == 1
    argv = spawned[0]
    assert argv[0] == "/usr/bin/osascript" and argv[1] == "-e"
    assert "display alert" in argv[2]
    assert "CCSync is already running." in argv[2]
    assert "menu bar" in argv[2]


def test_the_already_running_warning_is_a_no_op_on_linux(monkeypatch):
    from ccsync_companion import app as app_mod

    monkeypatch.setattr(app_mod.sys, "platform", "linux", raising=False)
    spawned: list[list] = []
    monkeypatch.setattr(app_mod, "_osascript_run", spawned.append)
    app_mod._warn_already_running()
    assert spawned == []


def test_run_sets_the_activation_policy_only_after_the_tk_root_exists(
    tmp_path, monkeypatch
):
    """Ordering regression, and it is not cosmetic: it decides whether the
    companion starts at all on a Mac.

    NSApp is a singleton whose class is fixed by its first caller. Tk-Aqua
    installs TKApplication and then sends it TKApplication-only selectors; if
    pyobjc's sharedApplication() got there first, NSApp is a plain
    NSApplication and Tk aborts the PROCESS from the ObjC runtime --
    `-[NSApplication macOSVersion]: unrecognized selector`, thrown under
    Tk_GetColor before tkinter.Tk() ever returns. libc++abi terminates on the
    uncaught NSException, so no Python handler anywhere can catch it: the
    binary just dies after "config OK" with no traceback of its own.
    Observed on macOS 15.7.4 / Tk 9.0 (A7, 2026-08-04) and fixed by moving
    the call below ui_dispatch.start(). Do not hoist it back up.
    """
    from ccsync_companion import app as app_mod
    from ccsync_companion import tray as tray_mod
    from ccsync_companion import ui_dispatch

    app = _make_app(tmp_path)
    app.start = lambda: None

    order: list[str] = []
    monkeypatch.setattr(
        ui_dispatch, "start", lambda *a, **kw: order.append("tk-root")
    )
    monkeypatch.setattr(
        app_mod, "_set_darwin_activation_policy", lambda: order.append("nsapp")
    )

    def stop_here(_app):
        app._stop_event.set()
        return None

    monkeypatch.setattr(tray_mod, "start_tray", stop_here)

    app.run()

    assert order == ["tk-root", "nsapp"], (
        "the activation policy must be set AFTER the Tk root is built, or "
        "Tk-Aqua aborts the process on macOS"
    )


def test_the_activation_policy_never_raises_without_pyobjc(monkeypatch):
    """The module must import and run on a machine that has never heard of
    pyobjc -- the AppKit import is lazy, inside the try."""
    from ccsync_companion import app as app_mod

    monkeypatch.setattr(app_mod.sys, "platform", "win32", raising=False)
    app_mod._set_darwin_activation_policy()
    monkeypatch.setattr(app_mod.sys, "platform", "darwin", raising=False)
    app_mod._set_darwin_activation_policy()


# ===========================================================================
# macOS port: main-thread UI dispatch (inline, and therefore inert, on win32)
# ===========================================================================


def test_copy_diagnostics_builds_its_hidden_root_through_ui_dispatch(tmp_path, monkeypatch):
    """Hidden or not, it is a Tk root on a tray worker thread -- on macOS it
    has to be built on the main thread like every dialog."""
    from ccsync_companion import ui_dispatch

    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    calls: list = []
    monkeypatch.setattr(ui_dispatch, "dispatch", lambda fn: calls.append(fn))

    assert app.copy_diagnostics() is True
    assert len(calls) == 1 and callable(calls[0])
    assert not app._popup_active_lock.locked()


def test_copy_diagnostics_survives_a_stopped_dispatcher(tmp_path, monkeypatch):
    from ccsync_companion import ui_dispatch

    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()

    def _stopped(fn):
        raise ui_dispatch.UIDispatchStopped("stopped")

    monkeypatch.setattr(ui_dispatch, "dispatch", _stopped)
    assert app.copy_diagnostics() is False
    assert not app._popup_active_lock.locked(), "the lock outlived the failure"
    assert any("log" in msg for msg, _title in app._tray_icon.notifications)


def test_shutdown_stops_the_ui_dispatcher_last(tmp_path, monkeypatch):
    """Ordering: a thread that asks for a dialog mid-shutdown must find the
    dispatcher still serving; stopping it first would park that thread on a
    main thread that has left its mainloop."""
    from ccsync_companion import ui_dispatch

    app = _make_app(tmp_path)
    order: list = []
    app._stop_lanes = lambda: order.append("lanes")
    app.reporter.stop = lambda: order.append("reporter")
    app.manifest_cache.stop = lambda: order.append("manifest")
    monkeypatch.setattr(ui_dispatch, "stop", lambda: order.append("ui_dispatch"))

    app.shutdown()

    assert order[-1] == "ui_dispatch", f"UI dispatch stopped too early: {order}"
    assert "lanes" in order and "reporter" in order


def test_shutdown_survives_a_ui_dispatcher_that_refuses_to_stop(tmp_path, monkeypatch, caplog):
    import logging

    from ccsync_companion import ui_dispatch

    app = _make_app(tmp_path)

    def _boom():
        raise RuntimeError("pump wedged")

    monkeypatch.setattr(ui_dispatch, "stop", _boom)
    with caplog.at_level(logging.ERROR, logger="ccsync.app"):
        app.shutdown()  # must not raise out of the tray's Quit handler
    assert any("UI dispatcher" in r.getMessage() for r in caplog.records)


def test_run_on_windows_starts_no_dispatcher_and_keeps_its_wait_loop(
    tmp_path, monkeypatch, windows
):
    """The Windows guarantee: ui_dispatch.start() returns None, active() is
    None, and run() blocks on the same _stop_event loop it always has.

    Takes the `windows` fixture, and that is the entire point of this edit:
    the test used to fake nothing at all. Its notion of "on Windows" was the
    REAL host, so it only passed because it was written on a Windows box --
    and on a Mac it started a real dispatcher, called tkinter.Tk() and tripped
    conftest._no_real_tk_windows. Worse, it still passed its own assertion
    there, because the guard's RuntimeError propagates out of
    MainThreadDispatcher.start() before `_active = dispatcher` runs -- so
    `active()` was None for entirely the wrong reason and the test proved
    nothing about the Windows path on either host (MAC-2e).
    """
    from ccsync_companion import tray as tray_mod
    from ccsync_companion import ui_dispatch

    app = _make_app(tmp_path)
    app.start = lambda: None
    monkeypatch.setattr(tray_mod, "start_tray", lambda _a: _FakeTray())
    monkeypatch.setattr(ui_dispatch, "_active", None)

    # Belt and braces: prove start() bailed on the platform check rather than
    # by raising on its way to a real Tk root.
    assert ui_dispatch.platform_mode() == ui_dispatch.MODE_INLINE

    threading.Timer(0.05, app._stop_event.set).start()
    app.run()

    assert ui_dispatch.active() is None


def test_run_on_the_main_thread_ui_platform_serves_instead_of_polling(tmp_path, monkeypatch):
    """macOS shape: the dispatcher is started BEFORE the tray (the icon is
    installed against its runloop), and the main thread then serves dialogs
    until _stop_event -- it never enters the Windows poll loop."""
    from ccsync_companion import tray as tray_mod
    from ccsync_companion import ui_dispatch

    app = _make_app(tmp_path)
    app.start = lambda: None
    order: list = []

    class _FakeDispatcher:
        def __init__(self):
            self.served = []

        def serve(self, stop_event=None):
            order.append("serve")
            self.served.append(stop_event)

        def stop(self):
            order.append("dispatcher stop")

    dispatcher = _FakeDispatcher()

    def _start(*a, **k):
        order.append("ui start")
        monkeypatch.setattr(ui_dispatch, "_active", dispatcher)
        return dispatcher

    monkeypatch.setattr(ui_dispatch, "_active", None)
    monkeypatch.setattr(ui_dispatch, "start", _start)
    monkeypatch.setattr(ui_dispatch, "stop", dispatcher.stop)

    def _start_tray(_a):
        order.append("tray")
        return _FakeTray()

    monkeypatch.setattr(tray_mod, "start_tray", _start_tray)
    app.start = lambda: order.append("app start")

    app.run()  # serve() returns immediately -> run() falls through to shutdown

    assert order[:4] == ["ui start", "app start", "tray", "serve"]
    assert order[-1] == "dispatcher stop"
    assert dispatcher.served == [app._stop_event]


# --- item 16: a self-upgrade that lost macOS's Full Disk Access grant -------
#
# The companion is ad-hoc signed, so every upgrade presents to TCC as a
# different program. On a Mac whose root is an external volume the tree then
# stops being readable with nothing anywhere naming the cause -- the drive is
# plugged in and the folder is right there. Exercised from Windows through
# root_guard's injected seams; nothing here reads a real /Volumes.


def test_a_blocked_volume_after_an_upgrade_is_named_in_the_tray(tmp_path, monkeypatch):
    from ccsync_companion import root_guard as root_guard_mod

    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    monkeypatch.setattr(root_guard_mod, "access_is_blocked", lambda root: True)

    app._check_macos_volume_access()

    assert app._macos_access_blocked is True
    toasts = [m for m, _t in app._tray_icon.notifications]
    assert len(toasts) == 1
    assert "macOS is blocking access to the sync volume" in toasts[0]
    # ...and the one action that fixes it, spelled out.
    assert "Full Disk Access" in toasts[0]
    assert "System Settings" in toasts[0]


def test_a_readable_volume_says_nothing(tmp_path, monkeypatch):
    """Windows, and every healthy Mac: this must be silent, not reassuring."""
    from ccsync_companion import root_guard as root_guard_mod

    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    monkeypatch.setattr(root_guard_mod, "access_is_blocked", lambda root: False)

    app._check_macos_volume_access()

    assert app._macos_access_blocked is False
    assert app._tray_icon.notifications == []


def test_the_access_check_never_raises(tmp_path, monkeypatch):
    """It runs on a timer thread moments after startup -- an escape there is
    an invisible dead thread."""
    from ccsync_companion import root_guard as root_guard_mod

    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()

    def _boom(root):
        raise RuntimeError("diskutil ate itself")

    monkeypatch.setattr(root_guard_mod, "access_is_blocked", _boom)
    app._check_macos_volume_access()  # must not raise
    assert app._macos_access_blocked is False


def test_diagnostics_name_the_blocked_volume(tmp_path):
    app = _make_app(tmp_path)
    assert "macOS is BLOCKING" not in app.build_diagnostics()

    app._macos_access_blocked = True
    line = next(l for l in app.build_diagnostics().splitlines()
                if l.startswith("sync drive:"))
    assert "macOS is BLOCKING access" in line
    assert "Full Disk Access" in line


def test_the_check_only_runs_after_an_upgrade(tmp_path, monkeypatch):
    """A grant is only ever lost by the binary changing, and a listdir on the
    sync root is not something to do on every start."""
    import ccsync_companion.app as app_mod
    from ccsync_companion import ui_dispatch

    calls: list[str] = []
    app = _make_app(tmp_path)
    monkeypatch.setattr(app, "_check_macos_volume_access", lambda: calls.append("checked"))
    monkeypatch.setattr(app, "start", lambda: None)
    monkeypatch.setattr(app, "shutdown", lambda: None)
    monkeypatch.setattr(app_mod.upgrade_mod, "cleanup_old_exe", lambda *a, **k: False)
    # This test is about the upgrade-marker gate, not about UI dispatch. On a
    # real Mac app.run() would otherwise start a real main-thread dispatcher,
    # whose _make_root() calls tkinter.Tk() and trips
    # conftest._no_real_tk_windows -- an error in teardown, with the body
    # still passing (MAC-2e, same fix as
    # test_run_tray_start_non_import_error_still_runs_shutdown above;
    # macOS CI, 2026-08-17).
    monkeypatch.setattr(ui_dispatch, "start", lambda *a, **kw: None)

    def _timer(delay, fn):
        fn()
        return _NullTimer()

    monkeypatch.setattr(app_mod.threading, "Timer", _timer)
    monkeypatch.setattr(app_mod, "_set_darwin_activation_policy", lambda: None)
    monkeypatch.setattr("ccsync_companion.tray.start_tray", lambda _a: _FakeTray())
    app._stop_event.set()

    monkeypatch.setattr(app_mod.upgrade_mod, "note_version_start", lambda _d: False)
    app.run()
    assert calls == []

    monkeypatch.setattr(app_mod.upgrade_mod, "note_version_start", lambda _d: True)
    app._stop_event.set()
    app.run()
    assert calls == ["checked"]


class _NullTimer:
    daemon = False

    def start(self):
        pass


# --- items 17 + 19: has the Resolve bridge connected this session? ---------


def test_diagnostics_answer_whether_the_bridge_ever_connected(tmp_path):
    """The question both incidents turned on, which the bundle an admin was
    sent could not answer."""
    app = _make_app(tmp_path)

    line = next(l for l in app.build_diagnostics().splitlines()
                if l.startswith("resolve bridge:"))
    assert "never polled this session" in line

    resolve_bridge.note_connection(False, resolve_bridge.NOT_RUNNING_MESSAGE)
    line = next(l for l in app.build_diagnostics().splitlines()
                if l.startswith("resolve bridge:"))
    assert "NOT CONNECTED" in line
    assert resolve_bridge.NOT_RUNNING_MESSAGE in line
    assert "has connected this session: NO" in line

    resolve_bridge.note_connection(True)
    resolve_bridge.note_connection(False, resolve_bridge.NO_SCRIPTING_MESSAGE)
    line = next(l for l in app.build_diagnostics().splitlines()
                if l.startswith("resolve bridge:"))
    assert "has connected this session: yes" in line
    assert "restart the companion" in line


def test_the_bridge_state_read_is_cached_not_a_probe(tmp_path, monkeypatch):
    """The tray calls this from its render path; a fusionscript call holds
    the GIL for its full native duration."""
    app = _make_app(tmp_path)
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: pytest.fail("the tray probed Resolve"))
    assert app.resolve_bridge_state() == {
        "connected": None, "ever_connected": False, "reason": ""}


def test_a_broken_bridge_state_read_degrades_to_unknown(tmp_path, monkeypatch):
    app = _make_app(tmp_path)

    def _boom():
        raise RuntimeError("no")

    monkeypatch.setattr(resolve_bridge, "session_state", _boom)
    assert app.resolve_bridge_state()["connected"] is None


# --- item 18's follow-up: shutdown must be able to end, dialog or no dialog -
#
# ui_dispatch.stop() destroying the window the UI thread is parked in is the
# fix (tests/test_ui_dispatch.py). This is the backstop under it: if serve()
# STILL has not returned a grace period after everything else stopped, the
# process ends itself rather than living on holding the single-instance slot
# so that every relaunch exits with "another ccsync-companion is already
# running" -- which is exactly what a `kill -9` was needed for on 2026-08-05.


class _FakeServingDispatcher:
    def __init__(self, serving=True, dialogs=()):
        self.serving = serving
        self.open_dialogs = list(dialogs)
        self.stopped_calls = 0

    def stop(self):
        self.stopped_calls += 1


class _RecordingTimer:
    """threading.Timer that records instead of waiting."""

    armed: list = []

    def __init__(self, delay, fn):
        self.delay = delay
        self.fn = fn
        self.daemon = False

    def start(self):
        type(self).armed.append(self)


def _fake_timer(monkeypatch):
    import ccsync_companion.app as app_mod

    _RecordingTimer.armed = []
    monkeypatch.setattr(app_mod.threading, "Timer", _RecordingTimer)
    return _RecordingTimer.armed


def test_shutdown_arms_a_hard_exit_while_the_ui_thread_is_still_serving(
        tmp_path, monkeypatch):
    from ccsync_companion import ui_dispatch

    app = _make_app(tmp_path)
    dispatcher = _FakeServingDispatcher()
    monkeypatch.setattr(ui_dispatch, "_active", dispatcher)
    monkeypatch.setattr(ui_dispatch, "stop", dispatcher.stop)
    armed = _fake_timer(monkeypatch)

    app.shutdown()

    import ccsync_companion.app as app_mod

    assert dispatcher.stopped_calls == 1
    backstops = [t for t in armed if t.fn == app._hard_exit_if_ui_wedged]
    assert len(backstops) == 1
    assert backstops[0].delay == app_mod.UI_SHUTDOWN_GRACE_SECONDS
    assert backstops[0].daemon is True, "a live timer would delay a clean exit"


def test_windows_shutdown_arms_no_backstop_at_all(tmp_path, monkeypatch):
    """There is no dispatcher off darwin, and run()'s wait loop always ends
    on its own -- an os._exit timer there would be all risk and no benefit."""
    from ccsync_companion import ui_dispatch

    app = _make_app(tmp_path)
    monkeypatch.setattr(ui_dispatch, "_active", None)
    armed = _fake_timer(monkeypatch)

    app.shutdown()

    assert [t for t in armed if t.fn == app._hard_exit_if_ui_wedged] == []


def test_no_backstop_when_the_mainloop_has_already_returned(tmp_path, monkeypatch):
    from ccsync_companion import ui_dispatch

    app = _make_app(tmp_path)
    dispatcher = _FakeServingDispatcher(serving=False)
    monkeypatch.setattr(ui_dispatch, "_active", dispatcher)
    monkeypatch.setattr(ui_dispatch, "stop", dispatcher.stop)
    armed = _fake_timer(monkeypatch)

    app.shutdown()

    assert [t for t in armed if t.fn == app._hard_exit_if_ui_wedged] == []


def test_the_backstop_exits_hard_and_names_the_window_that_would_not_close(
        tmp_path, monkeypatch, caplog):
    import ccsync_companion.app as app_mod
    from ccsync_companion import ui_dispatch

    class _Window:
        def title(self):
            return "CCSync — FIX ALL"

    app = _make_app(tmp_path)
    monkeypatch.setattr(ui_dispatch, "_active",
                        _FakeServingDispatcher(dialogs=[_Window()]))
    exits: list[int] = []
    monkeypatch.setattr(app_mod, "_hard_exit", exits.append)

    with caplog.at_level(logging.ERROR, logger="ccsync.app"):
        app._hard_exit_if_ui_wedged()

    assert exits == [1]
    message = " ".join(r.getMessage() for r in caplog.records)
    assert "FIX ALL" in message
    assert "Nothing is left to flush" in message


def test_the_backstop_stands_down_if_serve_returned_in_the_meantime(
        tmp_path, monkeypatch):
    """The normal case by a mile: the window closed, serve() came back, and
    run()'s finally is already tidying up. Exiting hard there would cut off a
    tray stop and, on a self-upgrade, the successor's handover."""
    import ccsync_companion.app as app_mod
    from ccsync_companion import ui_dispatch

    app = _make_app(tmp_path)
    monkeypatch.setattr(ui_dispatch, "_active", _FakeServingDispatcher(serving=False))
    exits: list[int] = []
    monkeypatch.setattr(app_mod, "_hard_exit", exits.append)

    app._hard_exit_if_ui_wedged()

    assert exits == []


def test_arming_the_backstop_never_raises_out_of_shutdown(tmp_path, monkeypatch):
    import ccsync_companion.app as app_mod
    from ccsync_companion import ui_dispatch

    class _Broken:
        @property
        def serving(self):
            raise RuntimeError("no")

    app = _make_app(tmp_path)
    monkeypatch.setattr(ui_dispatch, "_active", _Broken())
    monkeypatch.setattr(app_mod, "_hard_exit", lambda code: pytest.fail("exited"))

    app.shutdown()  # must not raise -- this runs inside a SIGTERM handler


# --- missing-proxy notifier + generator wiring (proxy_gen.py owns the policy)


class _FakeGenerator:
    """Records the lifecycle calls app.py is supposed to make, and answers
    the four accessors. Never a real thread: this file is about the WIRING,
    the state machine has its own suite (test_proxy_gen.py)."""

    def __init__(self, reason=None):
        self.started = 0
        self.stopped = 0
        self.joined: list[float] = []
        self.requested = 0
        self.cancelled = 0
        self.reason = reason

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def join(self, timeout=5.0):
        self.joined.append(timeout)

    def gap(self):
        return {"missing": 12, "braw": 4, "left": 3, "encoding": True,
                "can_generate": True, "state": "running"}

    def coverage(self):
        return {"missing": 12, "state": "running", "projects": {}}

    def block_reason(self):
        return self.reason

    def request_run(self):
        self.requested += 1

    def cancel_run(self):
        self.cancelled += 1


@pytest.fixture
def _inert_resolve(monkeypatch):
    """start() launches the timeline watcher, and on this developer box
    connect() genuinely connects and enumerates whatever project is open --
    holding the fusionscript GIL while it does. Same hazard as conftest's
    real-Tk guard (test_broll_wiring.py carries the same fixture)."""
    empty = {"ok": False, "message": "no Resolve in tests", "items": [], "project_name": ""}
    monkeypatch.setattr(resolve_bridge, "get_timeline_items", lambda *a, **kw: dict(empty))
    monkeypatch.setattr(resolve_bridge, "poll_timeline_items", lambda: dict(empty))
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items", lambda: dict(empty))
    monkeypatch.setattr(resolve_bridge, "try_connect", lambda: False)


def _quiet_app(tmp_path, **overrides) -> CompanionApp:
    """An app whose every other subsystem is inert, so start()/shutdown()
    can be called for real without a port, a dialog or a Resolve."""
    overrides.setdefault("popup_enabled", False)
    overrides.setdefault("require_login", False)
    overrides.setdefault("broll_server_enabled", False)
    overrides.setdefault("lut_sync_enabled", False)
    overrides.setdefault("stills_sync_enabled", False)
    overrides.setdefault("shutdown_warning_enabled", False)
    overrides.setdefault("keep_awake_while_syncing", False)
    overrides.setdefault("poll_interval", 0.2)
    return _make_app(tmp_path, **overrides)


def test_the_generator_is_built_with_the_apps_own_seams(tmp_path):
    app = _make_app(tmp_path)
    gen = app.proxy_generator
    assert gen is not None
    # The state dir, not the log dir: proxy_notify.json belongs beside
    # project_prompts.json and the lanes' filter files.
    assert gen.state_path.parent == app._state_dir
    assert gen.local_root == app.config["local_root"]

    # Every gate reads the app's LIVE state rather than a snapshot taken at
    # construction -- pausing, unplugging the drive and breaking the config
    # all have to reach a thread that started before any of them happened.
    assert gen._is_paused() is False
    app._paused = True
    assert gen._is_paused() is True
    app._root_absent = True
    assert gen._root_present() is False
    app.config_problems = ["remote is blank"]
    assert gen._is_blocked() is True


def test_a_generator_that_cannot_be_built_never_stops_the_companion(tmp_path, monkeypatch):
    """An advisory feature must never be the reason a companion fails to
    construct -- the windowed exe vanishing with no tray and no log line is
    this file's oldest failure mode."""
    from ccsync_companion import proxy_gen as proxy_gen_mod

    def _boom(*a, **kw):
        raise RuntimeError("no")

    monkeypatch.setattr(proxy_gen_mod, "ProxyGenerator", _boom)
    app = _make_app(tmp_path)
    assert app.proxy_generator is None
    # ...and every accessor stays safe.
    assert app.proxy_gap() == {}
    assert app.proxy_coverage() == {}
    assert app._shutdown_block_reason() is None
    app._tray_icon = _FakeTray()
    app.generate_proxies_now()
    app.stop_proxy_generation()
    assert any("not set up" in msg for msg, _t in app._tray_icon.notifications)


def test_start_runs_the_generator_even_with_the_lanes_off(tmp_path, _inert_resolve):
    """The base rig runs sync_enabled=false and needs this MOST: its
    local_root IS the NAS tree, so a proxy made there fans out over lane B.
    Same reasoning as _start_lut_link being outside the lanes branch."""
    app = _quiet_app(tmp_path, sync_enabled=False)
    fake = _FakeGenerator()
    app.proxy_generator = fake
    app.start()
    try:
        assert fake.started == 1
    finally:
        app.shutdown()


def test_start_runs_the_generator_even_when_the_config_stops_syncing(
        tmp_path, _inert_resolve):
    app = _quiet_app(tmp_path)
    app.config_problems = ["remote is blank"]
    fake = _FakeGenerator()
    app.proxy_generator = fake
    app.start()
    try:
        assert fake.started == 1
    finally:
        app.shutdown()


def test_a_generator_that_will_not_start_costs_a_log_line_and_nothing_else(
        tmp_path, _inert_resolve, caplog):
    class _Broken(_FakeGenerator):
        def start(self):
            raise RuntimeError("boom")

    app = _quiet_app(tmp_path)
    app.proxy_generator = _Broken()
    with caplog.at_level(logging.ERROR, logger="ccsync.app"):
        app.start()
    try:
        assert app._watcher_thread is not None and app._watcher_thread.is_alive()
        assert any("proxy generator" in r.getMessage() for r in caplog.records)
    finally:
        app.shutdown()


def test_shutdown_stops_the_generator_early_and_joins_it_bounded(tmp_path, _inert_resolve):
    """stop() is what kills the ffmpeg child, so it goes right behind the
    power guards; the join is bounded because the worker may be inside a
    kill+wait on a process stuck on a disconnected share."""
    app = _quiet_app(tmp_path)
    fake = _FakeGenerator()
    app.proxy_generator = fake
    app.start()
    app.shutdown()
    assert fake.stopped == 1
    assert fake.joined and fake.joined[0] <= 5.0


def test_a_generator_that_will_not_stop_never_blocks_shutdown(tmp_path, _inert_resolve):
    class _Broken(_FakeGenerator):
        def stop(self):
            raise RuntimeError("boom")

        def join(self, timeout=5.0):
            raise RuntimeError("boom")

    app = _quiet_app(tmp_path)
    app.proxy_generator = _Broken()
    app.start()
    app.shutdown()  # must not raise
    assert app._broll_server is None


def test_an_encode_in_flight_holds_the_shutdown_screen_and_the_keep_awake(tmp_path):
    """One function feeds both guards (_start_keep_awake reads it), so a
    machine will not idle-sleep mid-encode -- which is exactly when it
    otherwise would, since the generator only runs while the user is away."""
    app = _make_app(tmp_path)
    app.lanes = []
    app.proxy_generator = _FakeGenerator(reason="still making video proxies (3 left)")
    assert app._shutdown_block_reason() == "still making video proxies (3 left)"

    app.proxy_generator = _FakeGenerator(reason=None)
    assert app._shutdown_block_reason() is None


def test_a_sync_in_flight_still_wins_the_shutdown_message(tmp_path):
    """Moving bytes outranks making proxies: the sentence an editor needs at
    the shutdown screen is the one about footage that has not arrived."""
    app = _make_app(tmp_path)
    app.lanes = [_busy_lane()]
    app.proxy_generator = _FakeGenerator(reason="still making video proxies")
    reason = app._shutdown_block_reason()
    assert reason and "still syncing" in reason


def test_a_generator_whose_block_reason_raises_never_blocks_shutdown(tmp_path):
    class _Broken(_FakeGenerator):
        def block_reason(self):
            raise RuntimeError("boom")

    app = _make_app(tmp_path)
    app.lanes = []
    app.proxy_generator = _Broken()
    assert app._shutdown_block_reason() is None


def test_the_generator_is_not_consulted_while_the_drive_is_out(tmp_path):
    app = _make_app(tmp_path)
    app.lanes = []
    app._root_absent = True
    app.proxy_generator = _FakeGenerator(reason="still making video proxies")
    assert app._shutdown_block_reason() is None


def test_the_tray_accessors_pass_the_generators_answers_through(tmp_path):
    app = _make_app(tmp_path)
    fake = _FakeGenerator()
    app.proxy_generator = fake
    assert app.proxy_gap()["missing"] == 12
    assert app.proxy_coverage()["missing"] == 12

    app._tray_icon = _FakeTray()
    app.generate_proxies_now()
    assert fake.requested == 1
    app.stop_proxy_generation()
    assert fake.cancelled == 1
    assert len(app._tray_icon.notifications) == 2


class _FakeImporter:
    """The YouTube importer's lifecycle, recorded. Same division of labour as
    _FakeGenerator above: this file is about the WIRING, the state machine has
    its own suite (test_youtube_import.py)."""

    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.joined: list[float] = []

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def join(self, timeout=5.0):
        self.joined.append(timeout)

    def status(self):
        return {"state": "importing", "pending": 3, "imported_session": 7}


def test_the_youtube_importer_is_built_with_the_apps_own_seams(tmp_path):
    app = _make_app(tmp_path)
    importer = app.youtube_importer
    assert importer is not None
    assert importer.local_root == app.config["local_root"]

    # LIVE reads, like the generator's: pausing and unplugging the drive both
    # have to reach a thread that started before either happened.
    assert importer._is_paused() is False
    app._paused = True
    assert importer._is_paused() is True
    app._root_absent = True
    assert importer._root_present() is False

    # And the project it imports into is whatever the watcher last saw --
    # None while Resolve is closed, unreachable, or on an ignored project.
    assert importer._current_project() is None
    app.watcher.last_resolve_project = "Energy Transition"
    assert importer._current_project() == "Energy Transition"


def test_an_importer_that_cannot_be_built_never_stops_the_companion(tmp_path, monkeypatch):
    """Same rule as the proxy generator's: a convenience bolted onto the thing
    that keeps the fleet's media in sync must never be the reason a companion
    fails to construct."""
    from ccsync_companion import youtube_import as youtube_import_mod

    def _boom(*a, **kw):
        raise RuntimeError("no")

    monkeypatch.setattr(youtube_import_mod, "YoutubeImporter", _boom)
    app = _make_app(tmp_path)
    assert app.youtube_importer is None
    # ...and the reporter's getter stays safe, which is what keeps the section
    # absent rather than the report broken.
    assert app.youtube_import_status() == {}


def test_start_and_shutdown_carry_the_youtube_importer(tmp_path, _inert_resolve):
    """It needs no lanes and no sign-in -- the clips are already on this disk
    -- only a project open in Resolve."""
    app = _quiet_app(tmp_path, sync_enabled=False)
    fake = _FakeImporter()
    app.youtube_importer = fake
    app.start()
    app.shutdown()
    assert fake.started == 1
    assert fake.stopped == 1
    # Bounded, like the generator's: its worker may be inside a fusionscript
    # call on a Resolve that has stopped answering.
    assert fake.joined and fake.joined[0] <= 5.0


def test_an_importer_that_will_not_start_or_stop_costs_a_log_line(
        tmp_path, _inert_resolve, caplog):
    class _Broken(_FakeImporter):
        def start(self):
            raise RuntimeError("boom")

        def stop(self):
            raise RuntimeError("boom")

        def join(self, timeout=5.0):
            raise RuntimeError("boom")

    app = _quiet_app(tmp_path)
    app.youtube_importer = _Broken()
    with caplog.at_level(logging.ERROR, logger="ccsync.app"):
        app.start()
        assert app._watcher_thread is not None and app._watcher_thread.is_alive()
        app.shutdown()  # must not raise
    assert any("youtube importer" in r.getMessage() for r in caplog.records)


def test_the_stale_sweep_reports_half_made_proxies_without_deleting_them(
        tmp_path, caplog):
    """Same refusal as the .ccsync-tmp sweep: nothing on the filesystem
    proves some other process isn't writing that file this second."""
    root = Path(_make_local_root(tmp_path))
    proxy_dir = root / "Projects" / "2026" / "FF5" / "Nuclear" / "Proxy"
    proxy_dir.mkdir(parents=True)
    stale = proxy_dir / "A001.mp4.partial"
    stale.write_bytes(b"half an encode")
    old = time.time() - (24 * 3600)
    os.utime(stale, (old, old))

    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    with caplog.at_level(logging.WARNING, logger="ccsync.proxy_gen"):
        app._sweep_stale_tmp_files()

    assert stale.is_file()
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "A001.mp4.partial" in messages
    assert "NOT deleted" in messages


# ===========================================================================
# 2026-08-11 hunt: the companion sync-core findings (SYNC-1/3/5/6/9/12/13)
# ===========================================================================


def test_stop_lanes_managed_mode_stops_lane_b_too(tmp_path):
    """SYNC-1. RcloneLane.stop() is the ONLY path to _kill_running_process(),
    and sequencer.stop() joins its worker with timeout=10 -- so it returns
    while lane B may still be inside run_once(). On Windows the rclone child
    outlives the parent, so a self-upgrade left the OLD delete-authorised
    `rclone sync` racing the new process's lane B over one destination."""
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com", sync_enabled=True)
    assert app._managed is True

    stopped: list[str] = []
    app._lane_a.stop = lambda: stopped.append("lane_a")
    app._lane_b.stop = lambda: stopped.append("lane_b")
    app._lane_c.stop = lambda: stopped.append("lane_c")

    app._stop_lanes()

    assert "lane_b" in stopped


def test_a_lane_b_that_will_not_stop_does_not_strand_the_teardown(tmp_path, caplog):
    """Same discipline as every other lane in here: one that throws costs a
    log line, not the rest of the shutdown."""
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com", sync_enabled=True)

    def _boom():
        raise RuntimeError("boom")

    app._lane_b.stop = _boom
    stopped: list[str] = []
    app._lane_a.stop = lambda: stopped.append("lane_a")

    with caplog.at_level(logging.ERROR, logger="ccsync.app"):
        app._stop_lanes()

    assert stopped == ["lane_a"]
    assert any("failed to stop lane" in r.getMessage() for r in caplog.records)


def test_signing_in_does_not_override_the_trays_pause(tmp_path):
    """SYNC-3. require_login=true (the default) with "Pause syncing" ticked:
    on_signed_in() gated on _lanes_started and the login gate only, so the
    full rotation and express uploads resumed while the checkbox still
    rendered checked."""
    app = _make_app(tmp_path, dashboard_url="", sync_enabled=True, lane_b_enabled=True)

    class _SignedIn:
        role = None
        username = "owen"
        token = "t"
        last_upgrade_info = None

        def valid(self):
            return True

    app.identity = _SignedIn()
    started, _stopped = _instrument_lanes(app)
    app._paused = True

    app.on_signed_in()

    assert started == []
    assert app._lanes_started is False
    assert app.is_paused() is True


def test_resume_still_starts_the_lanes_after_the_pause_gate(tmp_path):
    """The other half of SYNC-3: the gate lives in _start_lanes(), which is
    also resume's own door -- toggle_pause clears _paused first, so the
    resume click must still work."""
    app = _make_app(tmp_path, dashboard_url="", sync_enabled=True,
                    lane_b_enabled=True, require_login=False)
    started, _stopped = _instrument_lanes(app)

    app.toggle_pause()   # pause
    started.clear()
    app.toggle_pause()   # resume

    assert "lane_a_video_up" in started


def test_sharing_luts_refuses_while_another_window_is_open(tmp_path, monkeypatch):
    """SYNC-5. The only confirm_dialog site in the companion that built a Tk
    root without _popup_active_lock -- the sibling-root condition that wedges
    the Tcl interpreter (CORE-M3/H8), and invisible to apply_upgrade's
    locked() check so a self-upgrade could exit mid-adopt()."""
    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()

    class _Links:
        def library(self):
            return tmp_path

        def adopt(self, strays):
            raise AssertionError("adopt() ran with another window open")

    app._lut_links = _Links()
    app._stray_luts = [{"name": "Kodak.cube", "size": 10}]
    dialogs: list[str] = []
    monkeypatch.setattr(popup, "confirm_dialog",
                        lambda *a, **k: dialogs.append("shown") or True)

    app._popup_active_lock.acquire()
    try:
        app.share_stray_luts()
    finally:
        app._popup_active_lock.release()

    assert dialogs == []
    assert any("window is open" in msg for msg, _t in app._tray_icon.notifications)


def test_sharing_luts_holds_the_popup_lock_across_the_copy(tmp_path, monkeypatch):
    """The lock must cover adopt() too, not just the dialog: apply_upgrade
    reads locked() to decide whether it may swap the exe and shut down."""
    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    held: list[bool] = []

    class _Links:
        def library(self):
            return tmp_path

        def adopt(self, strays):
            held.append(app._popup_active_lock.locked())
            return {"copied": len(strays), "errors": []}

        def find_strays(self):
            return []

    app._lut_links = _Links()
    app._stray_luts = [{"name": "Kodak.cube", "size": 10}]
    monkeypatch.setattr(popup, "confirm_dialog",
                        lambda *a, **k: held.append(app._popup_active_lock.locked()) or True)

    app.share_stray_luts()

    assert held == [True, True]
    assert app._popup_active_lock.locked() is False
    assert any("Shared 1 LUT" in msg for msg, _t in app._tray_icon.notifications)


def test_consolidate_refuses_while_the_drive_is_disconnected(tmp_path, monkeypatch):
    """SYNC-6. _root_absent is invisible to a config_problems check
    (_demote_removable_root_problem strips it at startup), and fixer.fix_clip
    refuses only a BLANK local_root -- so with the SSD unplugged this copied
    the originals onto the boot volume and relinked Resolve to canonical
    paths lane A then correctly refused to upload."""
    called: list[int] = []
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: called.append(1) or _mp_result())
    app = _make_app(tmp_path, sync_enabled=True)
    app._tray_icon = _FakeTray()
    app._root_absent = True

    app.consolidate_project()

    assert called == []
    assert any("disconnected" in msg for msg, _t in app._tray_icon.notifications)


def test_consolidate_stops_at_the_failure_report(tmp_path, monkeypatch):
    """SYNC-12: the failures branch had no return, so the editor read
    "1 failed -- copy diagnostics" and then, a beat later, an unqualified
    "Copy & upload finished"."""
    from ccsync_companion import consolidate

    other = tmp_path / "other"
    other.mkdir()
    stray = other / "A001.braw"
    stray.write_bytes(b"x" * 10)

    app = _make_app(tmp_path, sync_enabled=True, popup_enabled=False,
                    active_project="Projects/2026/X/Y")
    app._tray_icon = _FakeTray()
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: _mp_result(_item(str(stray))))
    monkeypatch.setattr(consolidate, "reconcile_with_nas",
                        lambda *a, **k: {"ok": True, "uploads": {"count": 1, "bytes": 10},
                                         "downloads": {"count": 0, "bytes": 0}})
    monkeypatch.setattr("ccsync_companion.popup.confirm_dialog", lambda *a, **k: True)
    monkeypatch.setattr(popup, "ProgressWindow", _FakeProgressWindow)
    monkeypatch.setattr(consolidate, "run_consolidation",
                        lambda ops, lr, **kw: [{"ok": False, "message": "denied",
                                                "file_path": o["file_path"]} for o in ops])
    app._lane_a.run_once = lambda subpath=None: None
    app._lane_b.run_once = lambda subpath=None: None

    app.consolidate_project()

    messages = [msg for msg, _t in app._tray_icon.notifications]
    assert any("failed" in msg for msg in messages)
    assert not any("Copy & upload finished" in msg for msg in messages)


def test_removing_a_project_refuses_while_the_drive_is_out(tmp_path):
    """SYNC-13: with the drive merely unplugged every step "succeeded" --
    untick, unshare, then the folder read as already gone. The multi-GB copy
    was still on the SSD, now unticked and unshared so nothing would ever
    reclaim it, while the editor believed the space was back."""
    app = _make_app(tmp_path, dashboard_url="http://dash.example.com", sync_enabled=True)
    unticked: list[str] = []
    app.selection_client.untick = lambda slug: unticked.append(slug) or (True, "ok")
    app._root_absent = True

    ok, message = app.remove_project_from_machine("ff5-nuclear")

    assert ok is False
    assert unticked == []
    assert "disconnected" in message


def test_pid_liveness_never_terminates_the_process_it_asks_about(monkeypatch):
    """SYNC-9: os.kill(pid, 0) on Windows is TerminateProcess(handle, 0) --
    it KILLS the pid, and raises for one that is already gone (which the
    OSError arm then read as "alive")."""
    from ccsync_companion import app as app_mod

    killed: list[tuple] = []
    monkeypatch.setattr(app_mod.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(app_mod.sys, "platform", "win32")
    monkeypatch.setattr(app_mod, "_pid_is_alive_win32", lambda pid: False)

    assert app_mod._pid_is_alive(4321) is False
    assert killed == [], "os.kill must never be reached on win32"


def test_pid_liveness_falls_back_to_alive_when_it_cannot_tell(monkeypatch):
    """Fail safe, exactly as the posix OSError arm does: an unknown answer
    must never let a second companion take a live instance's slot."""
    from ccsync_companion import app as app_mod

    def _boom(pid):
        raise OSError("no ctypes here")

    monkeypatch.setattr(app_mod.sys, "platform", "win32")
    monkeypatch.setattr(app_mod, "_pid_is_alive_win32", _boom)
    assert app_mod._pid_is_alive(4321) is True


@pytest.mark.skipif(os.name != "nt", reason="the win32 probe itself")
def test_the_win32_pid_probe_agrees_with_reality():
    from ccsync_companion import app as app_mod

    assert app_mod._pid_is_alive(os.getpid()) is True
    # A pid that cannot exist here: Windows pids are multiples of 4 and this
    # one is deliberately absurd.
    assert app_mod._pid_is_alive(0x7FFFFFF1) is False


# -- the 120s pool sweep classifies every bin (the 2026-08-12 blind spot) ----


def _pool_item(tmp_path, rel, make_file=True):
    path = tmp_path / rel
    if make_file:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    item = _item(str(path))
    item["media_pool_item"] = _RelinkableItem(str(path))
    return item


class _RelinkableItem:
    def __init__(self, path):
        self._path = path
        self.replace_calls = []

    def GetClipProperty(self):
        return {"File Path": self._path}

    def ReplaceClip(self, new_path):
        self.replace_calls.append(new_path)
        self._path = new_path
        return None  # Resolve returns None even on success


def test_pool_sweep_auto_relinks_non_canonical_clips(tmp_path, monkeypatch):
    """A bin-only clip stored under the LOCAL spelling never crosses the
    timeline watcher; the media-tree sweep must catch it and relink it to
    the canonical spelling without asking anybody anything."""
    root = tmp_path / "root"
    item = _pool_item(root, "B-roll/clip.mov")
    app = _make_app(tmp_path, canonical_prefix="P:\\")
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items", lambda: _mp_result(item),
    )

    app._refresh_media_tree_once()
    # The relink batch runs on its own daemon thread (COMP-GUARD-5), so the
    # sweep returns before it lands -- join it the way the popup tests do.
    _join_canon_relink()

    mpi = item["media_pool_item"]
    assert mpi.replace_calls == [r"P:\B-roll\clip.mov"]
    # Once per process: the next sweep must not re-offer the same path.
    mpi._path = str(root / "B-roll" / "clip.mov")  # pretend the relink reverted
    app._refresh_media_tree_once()
    _join_canon_relink()
    assert len(mpi.replace_calls) == 1


def test_pool_sweep_warns_once_for_foreign_clips_in_one_batch(tmp_path, monkeypatch):
    toasts = []
    app = _make_app(tmp_path, canonical_prefix="P:\\")
    monkeypatch.setattr(app, "_notify_tray", lambda msg, title="": toasts.append(msg))
    foreign = [
        _item(r"W:\Creators_Club\Projects\x\a.braw"),
        _item(r"W:\Creators_Club\Projects\x\b.braw"),
    ]
    monkeypatch.setattr(
        resolve_bridge, "get_media_pool_items", lambda: _mp_result(*foreign),
    )

    app._refresh_media_tree_once()

    assert len(toasts) == 1, "a backlog must be ONE toast, not one per clip"
    assert "another editor's machine" in toasts[0]

    app._refresh_media_tree_once()
    assert len(toasts) == 1, "warn-once per path"


from ccsync_companion import app as app_mod  # noqa: E402  (section-local import)


# -- stale fusionscript recovery (the 2026-08-12 wedge) ----------------------


def _arm_stale_bridge(app, monkeypatch, *, connected, ever, resolve_running):
    resolve_bridge.note_connection(True)  # sets ever_connected
    if not ever:
        resolve_bridge.reset_session_state()
    resolve_bridge.note_connection(connected)
    if not connected and not ever:
        resolve_bridge.reset_session_state()
    monkeypatch.setattr(
        app_mod.resolve_prefs_mod, "resolve_is_running", lambda: resolve_running,
    )


def test_stale_bridge_restarts_when_its_resolve_has_exited(tmp_path, monkeypatch):
    """Connected once, now disconnected, Resolve process gone: the stale
    fusionscript state must be shed NOW, while there is no Resolve to wedge
    -- restarting Resolve alone provably cannot fix this (2026-08-12)."""
    app = _make_app(tmp_path)
    _arm_stale_bridge(app, monkeypatch, connected=False, ever=True, resolve_running=False)
    calls = []
    monkeypatch.setattr(app_mod.upgrade_mod, "restart_self",
                        lambda request_shutdown: calls.append(request_shutdown))

    app._maybe_recover_stale_bridge()
    assert len(calls) == 1
    assert calls[0] == app.shutdown

    # Once per process -- a second sweep must not spawn a second replacement.
    app._maybe_recover_stale_bridge()
    assert len(calls) == 1


@pytest.mark.parametrize("connected,ever,resolve_running", [
    (True, True, False),    # still connected: nothing stale
    (False, False, False),  # never connected: fresh DLL, nothing to shed
    (False, True, True),    # Resolve still up: transient hiccup, not an exit
])
def test_stale_bridge_restart_does_not_fire_otherwise(
    tmp_path, monkeypatch, connected, ever, resolve_running
):
    app = _make_app(tmp_path)
    _arm_stale_bridge(app, monkeypatch,
                      connected=connected, ever=ever, resolve_running=resolve_running)
    calls = []
    monkeypatch.setattr(app_mod.upgrade_mod, "restart_self",
                        lambda request_shutdown: calls.append(1))

    app._maybe_recover_stale_bridge()
    assert calls == []


def test_stale_bridge_restart_respects_the_config_flag(tmp_path, monkeypatch):
    app = _make_app(tmp_path, bridge_auto_restart=False)
    _arm_stale_bridge(app, monkeypatch, connected=False, ever=True, resolve_running=False)
    calls = []
    monkeypatch.setattr(app_mod.upgrade_mod, "restart_self",
                        lambda request_shutdown: calls.append(1))

    app._maybe_recover_stale_bridge()
    assert calls == []


# -- the recurring "Resolve is up but scripting is dead" warning -------------
#
# The one warning in this app that repeats. Everything else is
# warn-once-per-path precisely so the companion is not a nag; this state
# earns the exception because the editor cannot see it (Resolve looks
# perfectly normal) and it never heals itself.


NO_SCRIPTING = resolve_bridge.NO_SCRIPTING_MESSAGE


class _InlineThread:
    """threading.Thread stand-in that runs the target on start().

    The real thread is right in production -- a Tk mainloop on the watcher
    thread freezes timeline polling for as long as the window is up (AUDIT_2
    CORE-M2) -- and useless here, where a test would have to join a daemon by
    name to see anything.
    """

    def __init__(self, target=None, name="", daemon=False, args=(), kwargs=None):
        self._target = target
        self.name = name
        self.daemon = daemon
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


class _InlineThreading:
    """Stands in for app.py's `threading` module. Narrower than patching
    threading.Thread itself, which is process-global and would follow the
    monkeypatch into anything else running during the test."""

    Thread = _InlineThread
    Lock = threading.Lock
    Event = threading.Event


class _FakeClock:
    """The app's _scripting_clock. One source for both the check (watcher
    thread) and the re-stamp when the dialog closes (dialog thread), so a
    test drives the real timing instead of poking _scripting_warned_at."""

    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


def _arm_scripting_warning(app, monkeypatch, *, seen=True, silence=False, thread=_InlineThreading):
    """Positive Resolve sighting, inline dialog thread, a fake clock, and a
    dialog that never touches Tk. Returns (shown, clock)."""
    shown: list = []

    def _fake_show(a):
        shown.append(a)
        return silence

    clock = _FakeClock()
    app._scripting_clock = clock
    monkeypatch.setattr(app_mod.resolve_prefs_mod, "resolve_process_state", lambda: seen)
    monkeypatch.setattr(app_mod, "threading", thread)
    import ccsync_companion.tray as tray_mod
    monkeypatch.setattr(tray_mod, "show_scripting_warning", _fake_show)
    return shown, clock


def test_scripting_warning_waits_a_full_interval_before_the_first_one(tmp_path, monkeypatch):
    """A dialog three seconds into every Resolve launch -- its script server
    takes a moment to come up -- would train editors to dismiss the one
    warning that matters."""
    app = _make_app(tmp_path, resolve_scripting_warning_interval=300)
    shown, clock = _arm_scripting_warning(app, monkeypatch)

    clock.now = 1000.0
    app._maybe_warn_scripting_dead()
    assert shown == [], "the first bad poll only starts the clock"

    clock.now = 1000.0 + 299
    app._maybe_warn_scripting_dead()
    assert shown == []

    clock.now = 1000.0 + 300
    app._maybe_warn_scripting_dead()
    assert len(shown) == 1


def test_scripting_warning_repeats_every_interval(tmp_path, monkeypatch):
    """The whole point: it keeps warning until the editor fixes it."""
    app = _make_app(tmp_path, resolve_scripting_warning_interval=300)
    shown, clock = _arm_scripting_warning(app, monkeypatch)

    app._maybe_warn_scripting_dead()
    for tick in (300.0, 600.0, 900.0):
        clock.now = tick
        app._maybe_warn_scripting_dead()
    assert len(shown) == 3

    clock.now = 901.0
    app._maybe_warn_scripting_dead()
    assert len(shown) == 3, "and not in between"


def test_the_process_probe_is_not_run_on_every_poll(tmp_path, monkeypatch):
    """resolve_process_state() SHELLS OUT (tasklist/pgrep) and this runs on
    the watcher's 3 s poll -- probing before the interval gate is twenty
    spawns a minute for as long as Resolve's scripting stays down, the exact
    cost resolve_bridge's _PROBE_TTL_SECONDS exists to avoid."""
    app = _make_app(tmp_path, resolve_scripting_warning_interval=300)
    shown, clock = _arm_scripting_warning(app, monkeypatch)
    probes: list = []
    monkeypatch.setattr(app_mod.resolve_prefs_mod, "resolve_process_state",
                        lambda: (probes.append(1), True)[1])

    for tick in range(0, 601, 3):            # ten minutes of polling
        clock.now = float(tick)
        app._maybe_warn_scripting_dead()

    assert len(shown) == 2, "two intervals, two warnings"
    assert len(probes) == 2, f"one spawn per warning, not per poll (got {len(probes)})"


def test_an_inconclusive_probe_is_not_retried_every_poll_either(tmp_path, monkeypatch):
    """The warn slot is spent whether or not the probe confirms -- otherwise
    a machine whose tasklist will not spawn re-tries it every 3 s forever."""
    app = _make_app(tmp_path, resolve_scripting_warning_interval=300)
    shown, clock = _arm_scripting_warning(app, monkeypatch)
    probes: list = []
    monkeypatch.setattr(app_mod.resolve_prefs_mod, "resolve_process_state",
                        lambda: (probes.append(1), None)[1])

    for tick in range(0, 601, 3):
        clock.now = float(tick)
        app._maybe_warn_scripting_dead()

    assert shown == []
    assert len(probes) == 2


def test_scripting_warning_never_fires_on_an_inconclusive_probe(tmp_path, monkeypatch):
    """resolve_is_running() fails CLOSED (an unspawnable tasklist reports
    "running"), which here would nag forever on a machine with Resolve shut.
    This warning demands a POSITIVE sighting instead."""
    app = _make_app(tmp_path, resolve_scripting_warning_interval=300)
    shown, clock = _arm_scripting_warning(app, monkeypatch, seen=None)

    for tick in (0.0, 300.0, 600.0, 6000.0):
        clock.now = tick
        app._maybe_warn_scripting_dead()
    assert shown == []


def test_scripting_warning_stays_quiet_when_resolve_is_definitely_gone(tmp_path, monkeypatch):
    app = _make_app(tmp_path, resolve_scripting_warning_interval=300)
    shown, clock = _arm_scripting_warning(app, monkeypatch, seen=False)

    for tick in (0.0, 300.0):
        clock.now = tick
        app._maybe_warn_scripting_dead()
    assert shown == []


@pytest.mark.parametrize("overrides", [
    {"resolve_scripting_warning": False},
    {"resolve_scripting_warning_interval": 0},
])
def test_scripting_warning_can_be_switched_off(tmp_path, monkeypatch, overrides):
    app = _make_app(tmp_path, **overrides)
    shown, clock = _arm_scripting_warning(app, monkeypatch)

    for tick in (0.0, 300.0, 3000.0):
        clock.now = tick
        app._maybe_warn_scripting_dead()
    assert shown == []


def test_scripting_warning_can_be_silenced_from_the_dialog(tmp_path, monkeypatch):
    """STOP WARNING ME means it: an editor mid-render who cannot restart
    Resolve right now has to be able to make it stop."""
    app = _make_app(tmp_path, resolve_scripting_warning_interval=300)
    shown, clock = _arm_scripting_warning(app, monkeypatch, silence=True)

    app._maybe_warn_scripting_dead()
    clock.now = 300.0
    app._maybe_warn_scripting_dead()
    assert len(shown) == 1
    assert app._scripting_warn_silenced is True

    for tick in (600.0, 900.0, 9000.0):
        clock.now = tick
        app._maybe_warn_scripting_dead()
    assert len(shown) == 1


def test_a_recovered_bridge_resets_the_clock_and_the_silence(tmp_path, monkeypatch):
    """Silenced until the link RECOVERS, not forever -- the next time
    scripting dies, the editor hears about it again."""
    app = _make_app(tmp_path, resolve_scripting_warning_interval=300)
    shown, clock = _arm_scripting_warning(app, monkeypatch, silence=True)

    app._handle_bridge_state(False, NO_SCRIPTING)
    clock.now = 300.0
    app._handle_bridge_state(False, NO_SCRIPTING)
    assert len(shown) == 1 and app._scripting_warn_silenced

    app._handle_bridge_state(True, "")
    assert app._scripting_warn_silenced is False
    assert app._scripting_bad_since is None
    assert app._scripting_warned_at is None


def test_resolve_merely_closed_is_not_warned_about(tmp_path, monkeypatch):
    """"Resolve is not running" is the normal state of an editor's evening,
    and _maybe_recover_stale_bridge's business, not this one's."""
    app = _make_app(tmp_path, resolve_scripting_warning_interval=300)
    shown, clock = _arm_scripting_warning(app, monkeypatch)

    for tick in range(0, 4000, 300):
        clock.now = float(tick)
        app._handle_bridge_state(False, resolve_bridge.NOT_RUNNING_MESSAGE)
    assert shown == []


def test_scripting_warning_does_not_stack_dialogs(tmp_path, monkeypatch):
    """The watcher polls every 3 s. One dialog left on screen must not
    become a hundred of them."""
    app = _make_app(tmp_path, resolve_scripting_warning_interval=300)
    shown, clock = _arm_scripting_warning(app, monkeypatch)
    app._maybe_warn_scripting_dead()
    app._scripting_warn_open = True          # as if one were on screen

    for tick in (300.0, 600.0, 900.0):
        clock.now = tick
        app._maybe_warn_scripting_dead()
    assert shown == []


def test_the_dialog_runs_off_the_watcher_thread(tmp_path, monkeypatch):
    """A Tk mainloop on the watcher thread freezes timeline polling for as
    long as the window is up (AUDIT_2 CORE-M2)."""
    spawned: list = []

    class _Recording(_InlineThread):
        def start(self):
            spawned.append((self.name, self.daemon))

    class _RecordingThreading(_InlineThreading):
        Thread = _Recording

    app = _make_app(tmp_path, resolve_scripting_warning_interval=300)
    _shown, clock = _arm_scripting_warning(app, monkeypatch, thread=_RecordingThreading)

    app._maybe_warn_scripting_dead()
    clock.now = 300.0
    app._maybe_warn_scripting_dead()
    assert spawned == [("ccsync-scripting-warning", True)]


def test_the_interval_is_measured_from_when_the_dialog_closes(tmp_path, monkeypatch):
    """A window left up for an hour must not re-pop the instant it closes:
    the next interval starts when the editor is DONE reading."""
    app = _make_app(tmp_path, resolve_scripting_warning_interval=300)
    shown, clock = _arm_scripting_warning(app, monkeypatch)

    def _slow_read(_a):
        shown.append(_a)
        clock.now += 3600          # the editor left it up for an hour
        return False

    import ccsync_companion.tray as tray_mod
    monkeypatch.setattr(tray_mod, "show_scripting_warning", _slow_read)

    app._maybe_warn_scripting_dead()
    clock.now = 300.0
    app._maybe_warn_scripting_dead()
    assert len(shown) == 1
    assert app._scripting_warn_open is False

    # Closed at 3900. One second later is NOT another warning...
    clock.now = 3901.0
    app._maybe_warn_scripting_dead()
    assert len(shown) == 1

    # ...a full interval after the close is.
    clock.now = 3900.0 + 300
    app._maybe_warn_scripting_dead()
    assert len(shown) == 2


def test_bridge_state_handling_never_raises(tmp_path, monkeypatch):
    """It runs inside the watcher's poll loop, where a raise would cost that
    poll its out-of-tree detection."""
    def _boom():
        raise RuntimeError("probe exploded")

    app = _make_app(tmp_path)
    monkeypatch.setattr(app_mod.resolve_prefs_mod, "resolve_process_state", _boom)
    app._handle_bridge_state(False, NO_SCRIPTING)   # must not raise


# ===========================================================================
# 2026-08-14 hunt: COMP-CORE / COMP-GUARD
# ===========================================================================


# -- COMP-CORE-2: the stale-bridge restart inherits apply_upgrade's guards --


def test_stale_bridge_restart_waits_for_a_consolidate_to_finish(tmp_path, monkeypatch):
    """restart_self is the same spawn + request_shutdown() sequence
    apply_upgrade refuses to run mid-copy (AUDIT_2 CORE-H8/H5): shutdown()
    stops the lanes and the process exits ~1 s later, killing the consolidate
    worker inside shutil.copy2. Quitting Resolve part-way through "Copy this
    project's media in" passes every other guard."""
    app = _make_app(tmp_path)
    _arm_stale_bridge(app, monkeypatch, connected=False, ever=True, resolve_running=False)
    calls = []
    monkeypatch.setattr(app_mod.upgrade_mod, "restart_self",
                        lambda request_shutdown: calls.append(1))

    app._consolidate_active = True
    app._maybe_recover_stale_bridge()
    assert calls == []
    # DEFERRED, not abandoned: the latch must stay unset or the recovery is
    # lost for the rest of the process's life.
    assert app._bridge_restart_started is False

    app._consolidate_active = False
    app._maybe_recover_stale_bridge()
    assert len(calls) == 1


def test_stale_bridge_restart_waits_for_an_open_ccsync_window(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    _arm_stale_bridge(app, monkeypatch, connected=False, ever=True, resolve_running=False)
    calls = []
    monkeypatch.setattr(app_mod.upgrade_mod, "restart_self",
                        lambda request_shutdown: calls.append(1))

    app._popup_active_lock.acquire()
    try:
        app._maybe_recover_stale_bridge()
    finally:
        app._popup_active_lock.release()
    assert calls == []
    assert app._bridge_restart_started is False

    app._maybe_recover_stale_bridge()
    assert len(calls) == 1


def test_one_predicate_answers_for_both_stand_down_callers(tmp_path):
    """The point of factoring it out: a third caller of restart_self cannot
    miss the test."""
    app = _make_app(tmp_path)
    assert app._standing_down_would_kill_work() == ""
    app._consolidate_active = True
    assert app._standing_down_would_kill_work() == "consolidate"
    app._consolidate_active = False
    app._popup_active_lock.acquire()
    try:
        assert app._standing_down_would_kill_work() == "popup"
    finally:
        app._popup_active_lock.release()


# -- COMP-CORE-6: the tray reads the P: mapping, it does not probe for it ----


def test_the_tray_read_of_the_p_mapping_never_spawns_a_probe(tmp_path, monkeypatch):
    """_tray_snapshot pulls this every 2 s, so a 10 s memo expired and
    re-populated forever: ~8,600 `net use P:` processes a day to re-derive a
    value that normally never changes."""
    app = _make_app(tmp_path)
    probes = []

    def _probe():
        probes.append(1)
        return "server"

    monkeypatch.setattr(app, "_probe_p_mapping_mode", _probe)
    monkeypatch.setattr(app_mod.os, "name", "nt")

    # Cold cache: exactly one probe, so the first menu is still right.
    assert app.p_mapping_mode_cached() == "server"
    assert len(probes) == 1

    for _ in range(50):
        assert app.p_mapping_mode_cached() == "server"
    assert len(probes) == 1, "the tray must read the cache, never re-derive it"


def test_the_background_refresh_catches_a_mapping_changed_outside_this_process(
    tmp_path, monkeypatch
):
    """P: can also be remapped by the installer's logon task or a manual
    `net use`, so the cache-only tray read needs something refreshing it."""
    app = _make_app(tmp_path)
    # AFTER construction, not before: CompanionApp.__init__ computes its
    # guard_state_dir with a real pathlib.Path(cfg's log_path), and pathlib's
    # WindowsPath.__new__ is bound at interpreter start to unconditionally
    # raise NotImplementedError on a real posix host (its `os.name != 'nt'`
    # guard is evaluated once, at import) -- patching os.name to fake
    # Windows earlier let the outer Path() through (it dispatches via
    # object.__new__, sidestepping the subclass check) but blew up the first
    # time something recursed into a fresh WindowsPath, e.g. `.parent`
    # (macOS CI, 2026-08-17). Nothing under test here reads os.name during
    # __init__ -- only p_mapping_mode()/_refresh_p_mapping_mode() do.
    monkeypatch.setattr(app_mod.os, "name", "nt")
    answers = ["local", "server"]
    monkeypatch.setattr(app, "_probe_p_mapping_mode", lambda: answers.pop(0))

    assert app.p_mapping_mode_cached() == "local"
    app._refresh_p_mapping_mode()
    assert app.p_mapping_mode_cached() == "server"


def test_a_grade_swap_invalidates_the_cached_mapping(tmp_path, monkeypatch):
    """Both in-process mutators clear the cache, which is what lets the tray
    read it without a TTL."""
    from ccsync_companion import drive_swap as drive_swap_mod

    app = _make_app(tmp_path)
    app._p_mode_cache = (time.monotonic(), "local")
    monkeypatch.setattr(drive_swap_mod, "swap_to_local", lambda root: (True, "ok"))

    app.swap_p_to_local()
    assert app._p_mode_cache is None


# -- COMP-CORE-7: a returning drive restamps the REAL blocker ----------------


def test_a_returning_drive_restamps_the_sign_in_gate_on_the_lanes(tmp_path, monkeypatch):
    """start()'s _root_absent branch outranks the sign-in gate, so all three
    lanes read "PAUSED: your <site> drive is disconnected". With the
    drive back that sentence names nothing the editor can fix -- and the tray
    renders it as "up to date (PAUSED: your drive is disconnected)"."""
    app = _make_app(tmp_path, sync_enabled=True, require_login=True)
    app._root_absent = True
    app._mark_lanes_root_absent()
    started = []
    monkeypatch.setattr(app, "_start_lanes", lambda: started.append("start"))

    app._on_root_present()

    assert started == [], "the sign-in gate still holds the lanes down"
    details = [str(s.detail) for s in app.lane_statuses()]
    assert details and all("sign in required" in d for d in details)
    assert not any("disconnected" in d for d in details)


def test_a_returning_drive_restamps_a_config_problem_on_the_lanes(tmp_path, monkeypatch):
    app = _make_app(tmp_path, sync_enabled=True, require_login=False)
    app._root_absent = True
    app._mark_lanes_root_absent()
    app.config_problems = ["remote is blank -- set it to the rclone remote name"]
    monkeypatch.setattr(app, "_start_lanes", lambda: pytest.fail("must not start"))

    app._on_root_present()

    details = [str(s.detail) for s in app.lane_statuses()]
    assert details and all("NOT SYNCING" in d for d in details)
    assert not any("disconnected" in d for d in details)


# -- COMP-CORE-8: the diagnostics tail seeks, it does not read 5 MB ----------


def test_the_log_tail_reads_a_window_off_the_end_of_a_rotating_log(tmp_path):
    """setup_logging rotates companion.log at 5 MB and machines sit at that
    ceiling, so readlines()[-40:] decoded the whole file to keep 40 lines --
    on the tray worker thread, inside "Copy diagnostics"."""
    app = _make_app(tmp_path)
    log_file = Path(app.log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "w", encoding="utf-8") as fh:
        for i in range(60000):
            fh.write(f"2026-08-14 12:00:00 INFO ccsync.app line {i} " + "x" * 60 + "\n")

    tail = app._diagnostic_log_tail(40)

    assert len(tail) == 40
    assert tail[-1].endswith("x" * 60)
    assert "line 59999" in tail[-1]
    assert "line 59960" in tail[0]
    # No partial first line: the window almost never starts on a boundary.
    assert all(line.startswith("2026-08-14") for line in tail)


def test_the_log_tail_handles_a_file_shorter_than_the_window(tmp_path):
    app = _make_app(tmp_path)
    log_file = Path(app.log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("one\ntwo\nthree\n", encoding="utf-8")
    assert app._diagnostic_log_tail(40) == ["one", "two", "three"]


def test_the_log_tail_still_explains_an_unreadable_log(tmp_path):
    app = _make_app(tmp_path)
    app.log_path = str(tmp_path / "nope" / "companion.log")
    tail = app._diagnostic_log_tail(40)
    assert len(tail) == 1 and "could not read" in tail[0]


# -- COMP-GUARD-5: the relink batch leaves the watcher thread ----------------


def _join_canon_relink():
    for thread in threading.enumerate():
        if thread.name == "ccsync-canon-relink":
            thread.join(timeout=5)


def test_non_canonical_relinks_run_off_the_watcher_thread(tmp_path, monkeypatch):
    """The watcher calls on_non_canonical synchronously from poll_once, and
    the batch is every newly-seen NON_CANONICAL clip -- 158 of them in the
    incident that motivated the handler. Inline, that parked the watcher for
    80+ seconds: last_resolve_project stale, no further detection, and
    _stop_event unobserved so a Quit could not stop it cleanly (CORE-M2)."""
    root = tmp_path / "root"
    items = [_pool_item(root, f"B-roll/clip{i}.mov") for i in range(5)]
    app = _make_app(tmp_path, canonical_prefix="P:\\")
    app._tray_icon = _FakeTray()

    # A ReplaceClip that has not answered yet must not hold the CALLER: this
    # is the watcher's poll thread.
    release = threading.Event()
    inside = threading.Event()
    original = app_mod.resolve_bridge.replace_clip

    def _slow_replace(mpi, path, **kw):
        inside.set()
        release.wait(5.0)
        return original(mpi, path, **kw)

    monkeypatch.setattr(app_mod.resolve_bridge, "replace_clip", _slow_replace)

    app._handle_non_canonical(items)
    assert inside.wait(5.0), "the batch never started"
    release.set()
    # Handed to a named daemon thread -- exactly what _handle_out_of_tree
    # does, and for the same reason.
    _join_canon_relink()

    for item in items:
        assert item["media_pool_item"].replace_calls == [
            "P:\\B-roll\\" + Path(item["file_path"]).name
        ]


def test_overlapping_relink_batches_extend_one_thread(tmp_path, monkeypatch):
    """Single-flight, but nothing is dropped: the watcher offers each path
    once per process, so a batch discarded here is a clip stranded forever."""
    root = tmp_path / "root"
    spawned = []
    real_thread = threading.Thread

    class _CountingThread(real_thread):
        def start(self):
            spawned.append(self.name)
            return super().start()

    monkeypatch.setattr(threading, "Thread", _CountingThread)
    app = _make_app(tmp_path, canonical_prefix="P:\\")
    app._tray_icon = _FakeTray()

    # Hold the worker inside its first ReplaceClip so the second batch lands
    # while it is busy.
    release = threading.Event()
    inside = threading.Event()
    original = app_mod.resolve_bridge.replace_clip

    def _slow_replace(mpi, path, **kw):
        inside.set()
        release.wait(5.0)
        return original(mpi, path, **kw)

    monkeypatch.setattr(app_mod.resolve_bridge, "replace_clip", _slow_replace)

    first = [_pool_item(root, "B-roll/a.mov")]
    second = [_pool_item(root, "B-roll/b.mov")]
    app._handle_non_canonical(first)
    assert inside.wait(5.0)
    app._handle_non_canonical(second)
    release.set()
    _join_canon_relink()

    assert spawned.count("ccsync-canon-relink") == 1
    assert first[0]["media_pool_item"].replace_calls == ["P:\\B-roll\\a.mov"]
    assert second[0]["media_pool_item"].replace_calls == ["P:\\B-roll\\b.mov"]


def test_the_unprompted_relink_is_rate_limited_per_project(tmp_path, monkeypatch):
    """COMMERCIAL_READINESS.md item 9 (2026-08-17): the automatic canonical
    relink rewrites the project database with no popup, and a machine whose
    canonical_prefix or local_root is wrong re-offers the same rewrite every
    sweep. One burst per project per window; the clips are HELD, not dropped
    (the watcher offers each path once per process)."""
    from ccsync_companion import resolve_journal

    root = tmp_path / "root"
    app = _make_app(tmp_path, canonical_prefix="P:\\")
    app._tray_icon = _FakeTray()

    first = [_pool_item(root, "B-roll/a.mov")]
    app._handle_non_canonical(first)
    _join_canon_relink()
    assert first[0]["media_pool_item"].replace_calls == [r"P:\B-roll\a.mov"]

    second = [_pool_item(root, "B-roll/b.mov")]
    app._handle_non_canonical(second)
    _join_canon_relink()
    assert second[0]["media_pool_item"].replace_calls == []
    assert len(app._canon_relink_pending) == 1

    # The window expiring lets the held clip through on the next offer.
    monkeypatch.setattr(resolve_journal, "AUTOMATIC_MIN_INTERVAL_SECONDS", 0.0)
    third = [_pool_item(root, "B-roll/c.mov")]
    app._handle_non_canonical(third)
    _join_canon_relink()
    assert second[0]["media_pool_item"].replace_calls == [r"P:\B-roll\b.mov"]
    assert third[0]["media_pool_item"].replace_calls == [r"P:\B-roll\c.mov"]


def test_a_relink_batch_stops_when_the_companion_is_shutting_down(tmp_path):
    """The R11 hand-off hazard: a self-upgrade landing mid-batch must not
    have to wait out 158 ReplaceClips."""
    root = tmp_path / "root"
    items = [_pool_item(root, f"B-roll/clip{i}.mov") for i in range(4)]
    app = _make_app(tmp_path, canonical_prefix="P:\\")
    app._stop_event.set()

    app._relink_non_canonical(items)

    assert all(i["media_pool_item"].replace_calls == [] for i in items)


# -- COMP-GUARD-1: the 0-byte reservation a hard kill leaves behind ----------


def test_the_startup_sweep_removes_a_stranded_0_byte_reservation(tmp_path, caplog):
    """fix_clip creates the FINAL name with O_CREAT|O_EXCL before the copy
    starts and cleans it on both failure exits -- but a process that simply
    dies cleans nothing, and lane A then uploads the empty file that
    --ignore-existing guarantees the real footage can never replace."""
    from ccsync_companion import fixer as fixer_mod

    root = Path(_make_local_root(tmp_path))
    folder = root / "B-roll" / "Editor Added" / "editor2"
    folder.mkdir(parents=True)
    reservation = folder / "A001_C012.braw"
    reservation.write_bytes(b"")
    partial = folder / f"A001_C012.braw.424242-abcd1234{fixer_mod.TMP_SUFFIX}"
    partial.write_bytes(b"ten minutes of copying")
    old = time.time() - 600
    os.utime(partial, (old, old))
    os.utime(reservation, (old, old))

    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    with caplog.at_level(logging.WARNING, logger="ccsync.fixer"):
        app._sweep_stale_tmp_files()

    assert not reservation.exists()
    assert partial.exists(), "the half-copied file is still the editor's data"
    assert "0-byte placeholder" in " ".join(r.getMessage() for r in caplog.records)


def test_a_reservation_too_fresh_to_judge_is_rechecked_once_it_ages(tmp_path, monkeypatch):
    """The self-upgrade restarts in SECONDS, so the residue of the copy it
    killed is normally younger than the idle floor when the startup sweep
    reaches it -- and lane A releases the 0-byte file 120 s after creation,
    after which --ignore-existing makes it permanent on the NAS."""
    from ccsync_companion import fixer as fixer_mod

    monkeypatch.setattr(fixer_mod, "RESERVATION_IDLE_SECONDS", 0.05)
    root = Path(_make_local_root(tmp_path))
    folder = root / "B-roll" / "Editor Added" / "editor2"
    folder.mkdir(parents=True)
    reservation = folder / "A002_C001.braw"
    reservation.write_bytes(b"")
    partial = folder / f"A002_C001.braw.424242-abcd1234{fixer_mod.TMP_SUFFIX}"
    partial.write_bytes(b"seconds ago")

    app = _make_app(tmp_path)
    app._tray_icon = _FakeTray()
    tmp_files = fixer_mod.walk_ccsync_tmp_files(str(root))
    # Too fresh on the first pass: the reservation survives it...
    assert fixer_mod.sweep_orphan_reservations(str(root), tmp_files=tmp_files) == []
    assert reservation.exists()

    app._recheck_orphan_reservations(str(root), tmp_files)

    assert not reservation.exists()
    assert partial.exists()


def test_the_recheck_gives_up_immediately_when_the_companion_is_stopping(tmp_path):
    from ccsync_companion import fixer as fixer_mod

    root = Path(_make_local_root(tmp_path))
    folder = root / "B-roll"
    folder.mkdir(parents=True)
    (folder / "A003.braw").write_bytes(b"")
    (folder / f"A003.braw.424242-abcd1234{fixer_mod.TMP_SUFFIX}").write_bytes(b"x")

    app = _make_app(tmp_path)
    app._stop_event.set()
    started = time.monotonic()
    app._recheck_orphan_reservations(
        str(root), fixer_mod.walk_ccsync_tmp_files(str(root)))
    assert time.monotonic() - started < 1.0
    assert (folder / "A003.braw").exists()


# -- b-roll ingest wiring (broll_ingest.py, 2026-08-18) ---------------------


def test_the_orchestrator_is_built_and_knows_who_is_signed_in(tmp_path):
    app = _make_app(tmp_path)

    assert app.broll_ingestor is not None
    # The SAME deps object the 8899 routes get, carrying `.ingestor` -- a
    # second one would answer every route "this machine cannot index".
    assert app._broll_ingest_deps.ingestor is app.broll_ingestor
    assert app._broll_ingest_deps.machine, "the fleet routes compare it per call"


def test_a_broken_orchestrator_never_stops_the_companion(tmp_path, monkeypatch):
    """The oldest failure mode in this file: the windowed exe vanishing with
    no tray and no log line because an advisory feature raised in __init__."""
    from ccsync_companion import broll_ingest as broll_ingest_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("the orchestrator is on fire")

    monkeypatch.setattr(broll_ingest_mod, "BrollIngestor", _boom)

    app = _make_app(tmp_path)

    assert app.broll_ingestor is None
    assert app.broll_ingest_status() == {}
    assert app.broll_ingest_view() == {}


def test_a_crunching_batch_blocks_the_proxy_generator(tmp_path):
    """Owner review (a): indexing takes precedence, and the generator learns
    it through the seam it already had."""
    app = _make_app(tmp_path)
    app.broll_ingestor.blocking_reason = lambda: "indexing b-roll first"

    assert app._proxy_block_reason() == "indexing b-roll first"


def test_a_config_problem_still_blocks_it_as_a_bool(tmp_path):
    """The DEL-3 gate the lanes use, unchanged: a half-configured install must
    not be quietly encoding into a tree whose local_root is wrong."""
    app = _make_app(tmp_path)
    app.config_problems = ["remote_root is blank"]

    assert app._proxy_block_reason() is True


def test_nothing_indexing_means_nothing_blocking(tmp_path):
    app = _make_app(tmp_path)

    assert app._proxy_block_reason() is False


def test_an_orchestrator_on_fire_does_not_block_proxies_forever(tmp_path):
    app = _make_app(tmp_path)

    def _boom():
        raise RuntimeError("the orchestrator is on fire")

    app.broll_ingestor.blocking_reason = _boom

    assert app._proxy_block_reason() is False


def test_a_dashboard_cancel_reaches_the_orchestrator(tmp_path):
    app = _make_app(tmp_path)
    seen = []
    app.broll_ingestor.note_report_response = seen.append

    app._on_report_response({"commands": {"broll_ingest": {"cancel": ["b" * 32]}}})

    assert seen and seen[0]["commands"]["broll_ingest"]["cancel"] == ["b" * 32]


def test_a_report_consumer_on_fire_does_not_stop_the_others(tmp_path):
    app = _make_app(tmp_path)

    def _boom(resp):
        raise RuntimeError("the orchestrator is on fire")

    app.broll_ingestor.note_report_response = _boom

    app._on_report_response({"commands": {"halt": {"active": False}}})  # no raise


def test_the_shutdown_screen_says_indexing_before_it_says_proxies(tmp_path):
    """Both hold the machine awake; the b-roll one is the longer job and the
    one an editor is waiting on."""
    app = _make_app(tmp_path)
    app.broll_ingestor.block_reason = lambda: "still indexing b-roll (12 clip(s) left)"
    if app.proxy_generator is not None:
        app.proxy_generator.block_reason = lambda: "still making video proxies"

    assert app._shutdown_block_reason() == "still indexing b-roll (12 clip(s) left)"


def test_the_progress_window_is_one_at_a_time(tmp_path, monkeypatch):
    """Two live Tk roots in this process is CORE-M3's wedged interpreter, so
    opening the second closes the first rather than refusing."""
    from ccsync_companion import popup

    opened = []

    class _FakeWindow:
        def __init__(self, title, subtitle, snapshot_fn, action_fn=None):
            self.title = title
            self.closed = False
            self._open = False
            opened.append(self)

        def open(self):
            self._open = True
            return True

        def is_open(self):
            return self._open

        def close(self):
            self.closed = True
            self._open = False

    monkeypatch.setattr(popup, "WorkProgressWindow", _FakeWindow)
    app = _make_app(tmp_path)

    app.show_ingest_progress()
    app.show_ingest_progress()          # the same one: no second window
    assert len(opened) == 1

    app.show_proxy_progress()           # a different one: the first closes
    assert len(opened) == 2
    assert opened[0].closed is True

    app.close_work_window()
    assert opened[1].closed is True


def test_the_proxy_window_shows_the_generators_own_numbers(tmp_path):
    """Its ETA and per-clip percentage, not a second estimate computed here:
    two ETAs for one queue is two ETAs that disagree."""
    app = _make_app(tmp_path)
    app.proxy_gap = lambda: {
        "encoding": True, "left": 28, "generated": 12, "failed": 1,
        "state": "running", "blocked_reason": "",
        "encoding_detail": [{"path": r"P:\a\A001.mp4", "percent": 62}],
        "history": {"eta_seconds": 900},
    }

    model = app._proxy_progress_model()

    assert model.item_line() == "A001.mp4 - 62%"
    assert model.overall_line() == "12 of 40 clips · 1 failed"
    assert model.eta_line() == "~15 min left"
    assert model.actions == ("cancel",)


def test_the_proxy_window_says_why_it_is_standing_aside(tmp_path):
    app = _make_app(tmp_path)
    app.proxy_gap = lambda: {"encoding": False, "left": 12, "generated": 0,
                             "state": "blocked",
                             "blocked_reason": "indexing b-roll first"}

    assert app._proxy_progress_model().note == "indexing b-roll first"
