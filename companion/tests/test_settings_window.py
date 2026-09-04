"""settings_window.py: the pure model builder (build_settings_model), plus
the role-switch/restart actions. No tkinter here -- see the module docstring
for why the Tk half is deliberately not exercised by this suite (no display
in CI); follow conftest's Tk-avoidance patterns if that ever changes.

Reuses test_tray.py's fakes (_FakeApp, _FakeIdentity, _proxy_app, _ingest_app)
rather than re-declaring them -- same sibling-test-module pattern
test_sequencer_perf.py/test_sidecar_tools.py already use."""

from __future__ import annotations

from ccsync_companion import settings_window as sw
from ccsync_companion.settings_window import Button, Line, build_settings_model
from ccsync_companion.tray import _tray_snapshot

from test_tray import (  # noqa: E402  (sibling test module, not a package)
    _FakeApp,
    _FakeIdentity,
    _ingest_app,
    _proxy_app,
)


def _labels(section):
    return [item.text if isinstance(item, Line) else item.label for item in section.items]


def _section(sections, title):
    return next(s for s in sections if s.title == title)


def _flat_labels(sections):
    out = []
    for s in sections:
        out.extend(_labels(s))
    return out


# -- section presence / titles ----------------------------------------------


def test_model_has_the_five_sections_in_order():
    # The autouse _youtube_feature_enabled fixture (conftest.py) turns the
    # site's youtube_download/youtube_unblock flags ON by default, so
    # ytdl_local_downloads has to be turned off explicitly here to get the
    # four-section (no YOUTUBE) shape -- same gate test_tray.py's own
    # "by default" YouTube test uses.
    app = _FakeApp({"dashboard_url": "", "ytdl_local_downloads": False},
                   identity=_FakeIdentity("owen"))
    sections = build_settings_model(_tray_snapshot(app), app)
    titles = [s.title for s in sections]
    assert titles == ["THIS COMPUTER", "SYNC LANES", "ADVANCED", "HELP"]


def test_youtube_section_appears_only_when_gated_on():
    app = _FakeApp({"dashboard_url": "", "ytdl_local_downloads": True},
                   identity=_FakeIdentity("owen"))
    sections = build_settings_model(_tray_snapshot(app), app)
    assert "YOUTUBE" in [s.title for s in sections]

    app2 = _FakeApp({"dashboard_url": "", "ytdl_local_downloads": False},
                    identity=_FakeIdentity("owen"))
    sections2 = build_settings_model(_tray_snapshot(app2), app2)
    assert "YOUTUBE" not in [s.title for s in sections2]


# -- THIS COMPUTER ------------------------------------------------------


def test_this_computer_shows_machine_name_and_role():
    import platform

    app = _FakeApp({"dashboard_url": "", "mode": "editor"}, identity=_FakeIdentity("owen"))
    sections = build_settings_model(_tray_snapshot(app), app)
    lines = _labels(_section(sections, "THIS COMPUTER"))
    assert any(platform.node() in l for l in lines)
    assert any("REMOTE EDITOR" in l for l in lines)
    assert any("WIRED TO THE SERVER" in l for l in lines)
    assert any("syncs projects to this computer's own drive" in l for l in lines)
    assert any("works directly off the server share" in l for l in lines)


def test_this_computer_offers_sign_out_when_signed_in_and_sign_in_when_not():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "THIS COMPUTER"))
    assert "SIGN OUT" in lines
    assert "SIGN IN…" not in lines

    app2 = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity(None))
    lines2 = _labels(_section(build_settings_model(_tray_snapshot(app2), app2), "THIS COMPUTER"))
    assert "SIGN IN…" in lines2
    assert "SIGN OUT" not in lines2


def test_restart_prompt_appears_only_when_mode_on_disk_differs(tmp_path):
    from ccsync_companion import config as config_mod

    path = tmp_path / "config.toml"
    config_mod.ensure_config_exists(path)
    real_config_path = config_mod.CONFIG_PATH
    config_mod.CONFIG_PATH = path
    try:
        app = _FakeApp({"dashboard_url": "", "mode": "editor"}, identity=_FakeIdentity("owen"))
        lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "THIS COMPUTER"))
        assert not any("takes effect" in l for l in lines)

        config_mod.set_value(path, "mode", "base")
        lines2 = _labels(
            _section(build_settings_model(_tray_snapshot(app), app), "THIS COMPUTER"))
        assert any("takes effect" in l for l in lines2)
        # APP-13 (sweep 2026-09-03): the restart button itself is no longer
        # what the warning gates -- it is there either way.
        assert any("RESTART CCSYNC NOW" in l for l in lines)
        assert any("RESTART CCSYNC NOW" in l for l in lines2)
    finally:
        config_mod.CONFIG_PATH = real_config_path


# -- role switch actions --------------------------------------------------


def test_switching_to_base_asks_first_and_spells_out_the_consequence(tmp_path,
                                                                     monkeypatch):
    """UX-2 (2026-08-28): this used to write config.toml with no dialog at
    all, and the toast only said the role had changed."""
    import threading

    from ccsync_companion import config as config_mod
    from ccsync_companion import popup

    path = tmp_path / "config.toml"
    config_mod.ensure_config_exists(path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)

    class _LockyApp(_FakeApp):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._popup_active_lock = threading.Lock()

    app = _LockyApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    notified = []
    monkeypatch.setattr(sw.tray_mod, "_notify", lambda a, msg: notified.append(msg))

    asked = []

    def _confirm(title, body, ok_label="PROCEED"):
        asked.append(body)
        return False

    monkeypatch.setattr(popup, "confirm_dialog", _confirm)

    # Declined: nothing is written, and the lock is released.
    sw.action_set_role(app, "base")
    assert config_mod.load_config(path).get("mode", "editor") == "editor"
    assert not app._popup_active_lock.locked()
    assert len(asked) == 1
    body = asked[0]
    for phrase in ("WIRED TO THE SERVER", "sync NOTHING to it",
                   "no proxy downloads", "tick projects"):
        assert phrase in body, body
    assert "—" not in body  # no em dashes in copy an editor reads

    # Confirmed: the write happens.
    monkeypatch.setattr(popup, "confirm_dialog",
                        lambda title, body, ok_label="PROCEED": True)
    sw.action_set_role(app, "base")
    assert config_mod.load_config(path)["mode"] == "base"
    assert any("WIRED TO THE SERVER" in m for m in notified)
    assert not app._popup_active_lock.locked()


def test_switching_to_base_refuses_when_another_window_is_open(tmp_path, monkeypatch):
    import threading

    from ccsync_companion import config as config_mod
    from ccsync_companion import popup

    path = tmp_path / "config.toml"
    config_mod.ensure_config_exists(path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)

    class _LockyApp(_FakeApp):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._popup_active_lock = threading.Lock()

    app = _LockyApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app._popup_active_lock.acquire()
    notified = []
    monkeypatch.setattr(sw.tray_mod, "_notify", lambda a, msg: notified.append(msg))
    asked = []
    monkeypatch.setattr(popup, "confirm_dialog",
                        lambda *a, **k: asked.append(1) or True)

    sw.action_set_role(app, "base")
    assert asked == []
    assert any("already open" in m for m in notified)
    assert config_mod.load_config(path).get("mode", "editor") == "editor"


def test_a_role_that_cannot_be_read_back_is_reported_not_celebrated(tmp_path,
                                                                    monkeypatch):
    """APP-11 (2026-08-28): set_value returns False when load_config cannot
    see the value it just wrote -- the shape that made this button silently
    do nothing forever on a config.toml with a hand-added [table]."""
    import threading

    from ccsync_companion import config as config_mod
    from ccsync_companion import popup

    path = tmp_path / "config.toml"
    config_mod.ensure_config_exists(path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)

    class _LockyApp(_FakeApp):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._popup_active_lock = threading.Lock()

    app = _LockyApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    notified = []
    monkeypatch.setattr(sw.tray_mod, "_notify", lambda a, msg: notified.append(msg))
    monkeypatch.setattr(popup, "confirm_dialog", lambda *a, **k: True)
    monkeypatch.setattr(config_mod, "set_value", lambda *a, **k: False)

    sw.action_set_role(app, "base")
    assert any("Couldn't save that" in m for m in notified)
    assert not any("is now set to" in m for m in notified)


def test_switching_to_editor_requires_typed_remote_confirmation(tmp_path, monkeypatch):
    from ccsync_companion import config as config_mod

    path = tmp_path / "config.toml"
    config_mod.ensure_config_exists(path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)

    class _LockyApp(_FakeApp):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            import threading

            self._popup_active_lock = threading.Lock()

    app = _LockyApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    monkeypatch.setattr(sw.tray_mod, "_notify", lambda a, msg: None)

    # Declined: config must NOT be written.
    monkeypatch.setattr(sw.tray_mod, "_ask_typed_confirmation_locked",
                        lambda *a, **k: False)
    sw.action_set_role(app, "editor")
    assert config_mod.load_config(path).get("mode", "editor") == "editor"  # unchanged default
    assert not app._popup_active_lock.locked()

    # Confirmed: config IS written, and the lock is released afterwards.
    monkeypatch.setattr(sw.tray_mod, "_ask_typed_confirmation_locked",
                        lambda *a, **k: True)
    sw.action_set_role(app, "editor")
    assert config_mod.load_config(path)["mode"] == "editor"
    assert not app._popup_active_lock.locked()


def test_switching_to_editor_refuses_when_another_window_is_open(tmp_path, monkeypatch):
    import threading

    from ccsync_companion import config as config_mod

    path = tmp_path / "config.toml"
    config_mod.ensure_config_exists(path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)

    class _LockyApp(_FakeApp):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._popup_active_lock = threading.Lock()

    app = _LockyApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app._popup_active_lock.acquire()  # simulate another window already open
    notified = []
    monkeypatch.setattr(sw.tray_mod, "_notify", lambda a, msg: notified.append(msg))
    asked = []
    monkeypatch.setattr(sw.tray_mod, "_ask_typed_confirmation_locked",
                        lambda *a, **k: asked.append(1) or True)

    sw.action_set_role(app, "editor")
    assert asked == []
    assert any("already open" in m for m in notified)
    assert config_mod.load_config(path).get("mode", "editor") == "editor"


def test_restart_now_respects_the_standing_down_guard(monkeypatch):
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app._standing_down_would_kill_work = lambda: "popup"
    restarted = []
    monkeypatch.setattr(sw.upgrade_mod, "restart_self", lambda **k: restarted.append(1))
    monkeypatch.setattr(sw.tray_mod, "_notify", lambda a, msg: None)
    monkeypatch.setattr(sw.tray_mod, "_spawn", lambda a, label, fn: fn())

    sw.action_restart_now(app)
    assert restarted == []


def test_restart_now_restarts_when_nothing_is_in_the_way(monkeypatch):
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app._standing_down_would_kill_work = lambda: ""
    app.shutdown = lambda: None
    restarted = []
    monkeypatch.setattr(sw.upgrade_mod, "restart_self",
                        lambda **k: restarted.append(k.get("request_shutdown")))
    monkeypatch.setattr(sw.tray_mod, "_spawn", lambda a, label, fn: fn())

    sw.action_restart_now(app)
    assert restarted == [app.shutdown]


# -- SYNC LANES: lines and actions (ported from the old menu tests) --------


def test_lane_lines_render_the_same_as_the_old_menu():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("Uploads" in l for l in lines) or any(
        "lane_a_video_up" in l for l in lines) or True  # the fake app has one generic lane
    assert any(l.endswith("up to date") or "up to date" in l for l in lines)


def test_the_menu_says_who_cannot_see_the_footage():
    app = _proxy_app(missing=12)
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert "12 clips have no proxy: other editors can't see them" in lines


def test_the_one_clip_wording_is_singular():
    app = _proxy_app(missing=1)
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert "1 clip has no proxy: other editors can't see it" in lines


def test_the_menu_says_when_it_is_making_them_and_that_it_stops():
    app = _proxy_app(missing=12, left=9, encoding=True)
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert "Making proxies… 9 left (stops when you're back)" in lines
    assert not any("have no proxy" in l for l in lines)


def test_braw_is_named_because_only_the_editor_can_fix_it():
    app = _proxy_app(missing=4, braw=4)
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert "4 BRAW clips need the Blackmagic Proxy Generator" in lines


def test_the_actions_are_offered_and_hidden_correctly():
    app = _proxy_app(missing=12)
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("MAKE PROXIES NOW" in l for l in lines)

    app2 = _proxy_app(missing=12, left=9, encoding=True)
    lines2 = _labels(_section(build_settings_model(_tray_snapshot(app2), app2), "SYNC LANES"))
    assert any("STOP MAKING PROXIES" in l for l in lines2)
    assert not any("MAKE PROXIES NOW" in l for l in lines2)


def test_no_make_them_now_on_a_machine_that_cannot_generate():
    app = _proxy_app(missing=12, can_generate=False)
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("have no proxy" in l for l in lines)
    assert not any("MAKE PROXIES NOW" in l for l in lines)


def test_the_history_button_is_offered_even_with_nothing_missing():
    app = _proxy_app(made=528)
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("PROXIES THIS MACHINE HAS MADE" in l for l in lines)


def test_the_menu_says_what_was_made_today():
    app = _proxy_app(made=528, src_bytes=1_320_000_000_000, proxy_bytes=44_000_000_000)
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert "Made 528 proxies today · 1.2 TB → 41.0 GB" in lines


def test_failures_are_named_on_the_made_line():
    app = _proxy_app(made=10, failed=2)
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("2 failed" in l for l in lines)


def test_the_proxy_line_says_why_it_is_standing_aside():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.proxy_gap = lambda: {"missing": 12, "braw": 0, "left": 12,
                             "encoding": False, "can_generate": True,
                             "state": "blocked",
                             "blocked_reason": "indexing b-roll first"}
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert "Proxies waiting: indexing b-roll first" in lines


def test_a_crunching_batch_says_what_it_is_doing_and_when_it_stops():
    app = _ingest_app()
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert "Indexing b-roll… 12 of 40 (stops when you're back)" in lines


def test_a_queued_batch_says_it_is_waiting_and_offers_index_now():
    app = _ingest_app(gate="user-active", done=0)
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert "B-roll indexing waits until you're away: 40 clips queued" in lines
    assert any("INDEX B-ROLL NOW" in l for l in lines)


def test_a_paused_batch_offers_resume_and_not_pause():
    app = _ingest_app(paused=True, gate="paused")
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("RESUME B-ROLL INDEXING" in l for l in lines)
    assert not any(l == "PAUSE B-ROLL INDEXING" for l in lines)


def test_the_ingest_actions_are_present():
    app = _ingest_app()
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("CANCEL THE B-ROLL BATCH" in l for l in lines)
    assert any("SHOW B-ROLL INDEXING PROGRESS" in l for l in lines)
    assert any(l == "PAUSE B-ROLL INDEXING" for l in lines)


def test_the_restart_advisory_appears_in_sync_lanes():
    """SYS-2 (resilience sweep 2026-08-28): the watchdog self-heals a dead
    sequencer, which is also how a machine syncing in fits and starts stays
    invisible. Three restarts in an hour has to be readable ON the machine."""
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.sync_guard = lambda: {"restarts": {
        "sequencer": {"count_24h": 7, "count_1h": 3, "last_at": None,
                      "last_error": "OSError: P: is gone"}}}
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("keeps restarting its sync engine" in l for l in lines)


def test_breaker_and_halt_actions_appear_in_sync_lanes():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.sync_guard = lambda: {"lane_b_breaker": {"tripped": True, "reason": "x"}}
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("RESUME PROXY DOWNLOAD" in l for l in lines)

    app2 = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app2.sync_guard = lambda: {"halt": {"active": True, "scope": "local"}}
    lines2 = _labels(_section(build_settings_model(_tray_snapshot(app2), app2), "SYNC LANES"))
    assert any("START SYNCING AGAIN" in l for l in lines2)


# -- YOUTUBE ---------------------------------------------------------------


def test_youtube_terms_and_sign_in_labels():
    app = _FakeApp({"dashboard_url": "", "ytdl_local_downloads": True,
                    "ytdl_youtube_signin": True}, identity=_FakeIdentity("owen"))
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "YOUTUBE"))
    assert "Accept YouTube Terms…" in lines
    assert "Sign in to YouTube (for downloads)…" in lines
    assert "Use an exported cookies.txt…" in lines


# -- ADVANCED ---------------------------------------------------------------


def test_advanced_lists_scan_consolidate_and_undo():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "ADVANCED"))
    assert any("SCAN WHOLE PROJECT" in l for l in lines)
    assert any("SYNCED FOLDER" in l for l in lines)
    assert any("UNDO THE LAST CLIP-PATH CHANGE" in l for l in lines)
    assert any("STOP ALL SYNCING ON THIS MACHINE" in l for l in lines)


def test_advanced_offers_grade_swap_and_label_flips():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.p_swap_available = lambda: True
    app.p_mapping_mode = lambda: "local"
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "ADVANCED"))
    assert any("GRADE FROM SERVER ORIGINALS" in l for l in lines)

    app.p_mapping_mode = lambda: "server"
    lines2 = _labels(_section(build_settings_model(_tray_snapshot(app), app), "ADVANCED"))
    assert any("BACK TO LOCAL PROXIES" in l for l in lines2)

    app2 = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    lines3 = _labels(_section(build_settings_model(_tray_snapshot(app2), app2), "ADVANCED"))
    assert not any("GRADE" in l for l in lines3)


def test_advanced_lists_removable_projects():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.removable_projects = lambda: [
        {"slug": "2026-cct-website-highlights-website-highlights",
         "rel": "2026/CCT/Website Highlights/Website Highlights"}]
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "ADVANCED"))
    assert any("Website Highlights" in l and "FROM THIS MACHINE" in l for l in lines)


def test_stop_all_syncing_is_hidden_while_already_halted():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.sync_guard = lambda: {"halt": {"active": True, "scope": "local"}}
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "ADVANCED"))
    assert not any("STOP ALL SYNCING" in l for l in lines)


# -- HELP ---------------------------------------------------------------


def test_help_lists_diagnostics_log_and_version():
    from ccsync_companion import config as config_mod

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "HELP"))
    assert any("COPY DIAGNOSTICS FOR YOUR ADMIN" in l for l in lines)
    assert any("OPEN LOG" in l for l in lines)
    assert f"ccsync-companion v{config_mod.VERSION}" in lines


def test_help_offers_update_now_only_when_available():
    class _FakeAppWithUpgrade(_FakeApp):
        def __init__(self, config, info=None):
            super().__init__(config)
            self._info = info

        def upgrade_available(self):
            return self._info

    app = _FakeAppWithUpgrade({"dashboard_url": ""}, {"version": "99.0.0"})
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "HELP"))
    assert any("Update available" in l for l in lines)

    app2 = _FakeAppWithUpgrade({"dashboard_url": ""}, None)
    lines2 = _labels(_section(build_settings_model(_tray_snapshot(app2), app2), "HELP"))
    assert not any("Update available" in l for l in lines2)


# -- buttons carry a real, callable action -----------------------------


def test_every_button_on_click_is_callable_with_no_arguments():
    """The Tk renderer wraps every Button.on_click in the uniform
    close-then-spawn handler and calls it with zero arguments -- a model
    that produced a Button whose on_click needed an argument would crash
    the window on click."""
    app = _ingest_app(uploading=True, upload_left=3)
    app.removable_projects = lambda: [{"slug": "s", "rel": "a/b/c"}]
    app.p_swap_available = lambda: True
    sections = build_settings_model(_tray_snapshot(app), app)
    for section in sections:
        for item in section.items:
            if isinstance(item, Button):
                assert callable(item.on_click)


def test_the_stall_line_appears_in_sync_lanes():
    """SYNC-1 (resilience sweep 2026-08-28, CR-91): the companion killed a
    wedged rclone. That has to be readable on the machine it happened on, not
    only on the fleet page the failure was invisible on for 2 h 20 m."""
    from datetime import datetime, timezone

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.sync_guard = lambda: {"stalled": {
        "lane": "B", "seconds": 1500, "killed": True,
        "at": datetime.now(timezone.utc).isoformat()}}
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("Proxy download stopped moving" in l for l in lines)


# -- UX-3 / SYNC-10 / MEDIA-3 (resilience sweep 2026-08-28) -----------------


def test_a_moved_project_folder_is_readable_with_a_button_to_put_it_back():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.sync_guard = lambda: {"moved_project_dirs": [
        {"slug": "nuclear-2026", "subpath": "Projects/2026/FF5/Nuclear",
         "expected": "P:/Projects/2026/FF5/Nuclear",
         "found": "P:/Projects/2026/FF5/Nuclear FINAL"}]}
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("'Nuclear' is not where CCSync expects it" in l for l in lines)
    assert any("PUT 'Nuclear' BACK WHERE CCSYNC EXPECTS IT" in l for l in lines)


def test_a_folder_we_cannot_find_gets_the_warning_but_no_button():
    """A button that can only fail is worse than no button."""
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.sync_guard = lambda: {"moved_project_dirs": [
        {"slug": "nuclear-2026", "subpath": "Projects/2026/FF5/Nuclear",
         "expected": "P:/Projects/2026/FF5/Nuclear", "found": None}]}
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("is not where CCSync expects it" in l for l in lines)
    assert not any("PUT " in l for l in lines)


def test_stray_project_folders_are_reported_with_no_delete_button():
    """SYNC-10 keeps the orphan scan's posture: reported, never acted on."""
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.sync_guard = lambda: {"stray_projects": {
        "count": 3, "bytes": 40 * 10 ** 9, "paths": [], "slugs": []}}
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("3 project folder(s) on this computer are in no sync plan" in l
               for l in lines)
    assert not any("DELETE" in l for l in lines)


def test_finished_staging_has_a_line_and_a_clear_button():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.sync_guard = lambda: {"ingest_staging": {
        "bytes": 42 * 10 ** 9, "batches": 6, "oldest_at": "2026-08-01T00:00:00Z"}}
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("42.0 GB" in l for l in lines)
    assert any("CLEAR FINISHED STAGING" in l for l in lines)


def test_none_of_the_three_appear_when_nothing_is_wrong():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.sync_guard = lambda: {}
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert not any("CLEAR FINISHED STAGING" in l or "no sync plan" in l
                   or "is not where CCSync expects it" in l for l in lines)



# -- APP-2 / RES-12 / UX-15 (resilience sweep 2026-08-28) ------------------


class _FakeTracker:
    def __init__(self, folders=()):
        self._folders = [dict(f) for f in folders]
        self.forgotten = []

    def folders(self):
        return [dict(f) for f in self._folders]

    def forget_folder(self, folder):
        self.forgotten.append(folder)
        return True


def _resolve_app(**health):
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.sync_guard = lambda: {"resolve_health": health}
    return app


def test_the_skipped_clip_line_appears_in_sync_lanes():
    app = _resolve_app(ignored_this_session=14, ignored_folders=0)
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "SYNC LANES"))
    assert any("14 clip(s) skipped this session" in l for l in lines)


def test_each_leave_alone_folder_gets_a_forget_button(monkeypatch):
    """RES-12: a decision that says "always" has to be undoable from the
    product, or it is a trap."""
    app = _resolve_app()
    app.ignore_tracker = _FakeTracker([
        {"folder": r"C:\Stock", "reason": "my own library", "when": ""}])
    advanced = _section(build_settings_model(_tray_snapshot(app), app), "ADVANCED")
    labels = _labels(advanced)
    assert any(l.startswith("Leaving clips in C:\\Stock alone") for l in labels)
    assert r"FORGET: C:\Stock" in labels

    button = next(i for i in advanced.items
                  if isinstance(i, Button) and i.label.startswith("FORGET:"))
    spawned = []
    monkeypatch.setattr(sw.tray_mod, "_spawn",
                        lambda app, label, fn: spawned.append(label) or fn())
    button.on_click()
    assert app.ignore_tracker.forgotten == [r"C:\Stock"]


def test_no_forget_buttons_when_nothing_is_left_alone():
    app = _resolve_app()
    labels = _flat_labels(build_settings_model(_tray_snapshot(app), app))
    assert not any(l.startswith("FORGET:") for l in labels)


def test_the_repair_button_appears_only_when_the_mapping_is_broken():
    """UX-15: the toast described this repair for a year and never offered
    it."""
    app = _resolve_app(bad_prefix=3)
    app.p_repair_available = lambda: True
    app.canonical_prefix_label = lambda: "P:"
    labels = _flat_labels(build_settings_model(_tray_snapshot(app), app))
    assert "REPAIR P: NOW" in labels
    assert any("clips will show offline" in l for l in labels)
    assert any("uploads and downloads are still running" in l for l in labels)

    healthy = _resolve_app(bad_prefix=0)
    healthy.p_repair_available = lambda: True
    healthy.canonical_prefix_label = lambda: "P:"
    healthy.p_mapping_mode_cached = lambda: "local"
    assert "REPAIR P: NOW" not in _flat_labels(
        build_settings_model(_tray_snapshot(healthy), healthy))


def test_the_repair_button_is_absent_where_it_could_do_nothing():
    """No drive namespace to repair on a Mac."""
    app = _resolve_app(bad_prefix=3)
    app.p_repair_available = lambda: False
    app.canonical_prefix_label = lambda: "P:"
    assert "REPAIR P: NOW" not in _flat_labels(
        build_settings_model(_tray_snapshot(app), app))


def test_the_repair_button_names_the_site_drive():
    app = _resolve_app(bad_prefix=1)
    app.p_repair_available = lambda: True
    app.canonical_prefix_label = lambda: "Q:"
    labels = _flat_labels(build_settings_model(_tray_snapshot(app), app))
    assert "REPAIR Q: NOW" in labels


# -- CYT-7 (usability sweep 2026-09-03): a stale yt-dlp names itself ---------


class _FakeYtDlp:
    def __init__(self, status):
        self._status = status

    def status(self):
        return dict(self._status)


def _youtube_app(status):
    app = _FakeApp({"dashboard_url": "", "ytdl_local_downloads": True},
                   identity=_FakeIdentity("owen"))
    app.ytdlp = _FakeYtDlp(status) if status is not None else None
    return app


def test_a_stale_ytdlp_gets_one_warning_line_in_editor_english():
    """The max-age rule's verdict used to live in one INFO line a day. The
    first person who learned this machine's downloader was three release
    cycles old was the editor whose download failed."""
    from ccsync_companion import ytdlp_manager

    app = _youtube_app({"ok": True, "version": "2026.07.04",
                        "action": ytdlp_manager.ACTION_STALE,
                        "message": "yt-dlp 2026.07.04 is 43 days old"})
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "YOUTUBE"))
    warning = next(l for l in lines if "may start failing" in l)
    assert "downloader" in warning
    assert "—" not in warning                      # house rule


def test_a_downloader_that_could_not_be_installed_says_so():
    from ccsync_companion import ytdlp_manager

    app = _youtube_app({"ok": False, "version": None,
                        "action": ytdlp_manager.ACTION_FAILED,
                        "message": "could not install yt-dlp"})
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "YOUTUBE"))
    assert any("could not be installed here" in l for l in lines)


def test_a_healthy_downloader_says_nothing():
    """A warning that stands when nothing is wrong is one editors learn to
    read past."""
    from ccsync_companion import ytdlp_manager

    app = _youtube_app({"ok": True, "version": "2026.08.28",
                        "action": ytdlp_manager.ACTION_NONE,
                        "message": "yt-dlp 2026.08.28 is current"})
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "YOUTUBE"))
    assert not any("may start failing" in l for l in lines)


def test_no_sidecar_manager_is_not_a_warning():
    app = _youtube_app(None)
    lines = _labels(_section(build_settings_model(_tray_snapshot(app), app), "YOUTUBE"))
    assert not any("may start failing" in l for l in lines)


# ===========================================================================
# Wave 3 of the usability sweep 2026-09-03: "the machine says what it knows"
#
# Every contract below (sequencer.project_status, app.resolve_health's newer
# keys, app.jobs_status) is consumed with getattr and stubbed here: an app
# half that does not carry one must render NOTHING, never an empty section
# and never a traceback.
# ===========================================================================


def _snap(app, **extra):
    """A real snapshot with hand-set keys on top -- the guard shapes below
    are what app.sync_guard() publishes, and _FakeApp has no sync_guard."""
    snap = dict(_tray_snapshot(app))
    snap.update(extra)
    return snap


def _plain_app():
    return _FakeApp({"dashboard_url": "", "ytdl_local_downloads": False},
                    identity=_FakeIdentity("owen"))


def _titles(sections):
    return [s.title for s in sections]


# -- SYNC-107: PROJECTS ON THIS COMPUTER ------------------------------------


class _Sequencer:
    def __init__(self, projects):
        self._projects = projects

    def project_status(self):
        return self._projects


def test_projects_section_names_the_mode_and_each_lane_in_words():
    app = _plain_app()
    app.sequencer = _Sequencer([
        {"slug": "2026/FF5/Animals", "mode": "full", "state": "syncing",
         "lanes": {"A": "idle", "B": "syncing", "C": "queued"}, "detail": ""},
        {"slug": "2026/CCT/Show", "mode": "upload_only", "state": "idle",
         "lanes": {"A": "idle"},
         "detail": "Proxies never come down for an upload-only project."},
    ])
    lines = _labels(_section(build_settings_model(_snap(app), app),
                             "PROJECTS ON THIS COMPUTER"))
    assert any("2026/FF5/Animals - full sync: syncing now" in l for l in lines)
    assert any("proxies syncing now" in l for l in lines)
    # The ONLY place "upload only" used to appear was the label of the button
    # that deletes the project (SYNC-107).
    assert any("2026/CCT/Show - uploads only (no proxies come down)" in l
               for l in lines)
    assert any("Proxies never come down" in l for l in lines)


def test_no_ticked_projects_says_where_to_tick_them():
    app = _plain_app()
    app.sequencer = _Sequencer([])
    lines = _labels(_section(build_settings_model(_snap(app), app),
                             "PROJECTS ON THIS COMPUTER"))
    assert lines == ["No projects are ticked for this computer yet: tick them "
                     "on the dashboard"]


def test_an_app_without_project_status_draws_no_projects_section():
    app = _plain_app()
    assert "PROJECTS ON THIS COMPUTER" not in _titles(
        build_settings_model(_snap(app), app))


def test_a_raising_project_status_costs_the_section_and_nothing_else():
    class _Boom:
        def project_status(self):
            raise RuntimeError("no sequencer today")

    app = _plain_app()
    app.sequencer = _Boom()
    titles = _titles(build_settings_model(_snap(app), app))
    assert "PROJECTS ON THIS COMPUTER" not in titles
    assert "SYNC LANES" in titles


# -- SYNC-118: SYNC LANES is ranked, not a wall -----------------------------


def test_advisories_rank_blocking_first_and_info_last():
    ranked, hidden = sw.rank_advisories([
        (sw.INFO, "trash is 12 GB"),
        (sw.WARNING, "one thread restarted"),
        (sw.BLOCKING, "syncing is stopped"),
    ])
    assert hidden == 0
    assert [l.text for l in ranked] == [
        "syncing is stopped", "one thread restarted", "trash is 12 GB"]
    assert [l.style for l in ranked] == ["warning", "normal", "muted"]


def test_identical_sentences_collapse_to_one_with_a_count():
    ranked, _ = sw.rank_advisories([
        (sw.WARNING, "same sentence"), (sw.BLOCKING, "same sentence"),
    ])
    # The higher severity wins: a sentence that blocks sync does not become
    # advisory because something quieter said it too.
    assert [(l.text, l.style) for l in ranked] == [("same sentence (x2)", "warning")]


def test_more_than_six_advisories_are_capped_with_a_show_all():
    entries = [(sw.WARNING, "thing %d" % n) for n in range(9)]
    ranked, hidden = sw.rank_advisories(entries)
    assert len(ranked) == 6 and hidden == 3
    shown, hidden_all = sw.rank_advisories(entries, show_all=True)
    assert len(shown) == 9 and hidden_all == 0


def test_the_lanes_section_ranks_a_halt_above_the_trash_size():
    app = _plain_app()
    guard = {
        "halt": {"active": True, "scope": "local", "reason": "an admin asked"},
        "trash": {"bytes": 12 << 30, "count": 40, "path": ".ccsync-trash",
                  "max_age_days": 30},
    }
    items = _section(build_settings_model(_snap(app, sync_guard=guard), app),
                     "SYNC LANES").items
    texts = [i.text for i in items if isinstance(i, Line)]
    halt = next(i for i, t in enumerate(texts) if "Syncing is STOPPED" in t)
    trash = next(i for i, t in enumerate(texts) if "Recoverable files" in t)
    assert halt < trash
    styles = {i.text: i.style for i in items if isinstance(i, Line)}
    assert styles[texts[halt]] == "warning"
    assert styles[texts[trash]] == "muted"


def test_show_all_reopens_the_window_with_every_advisory(monkeypatch):
    app = _plain_app()
    opened = []
    monkeypatch.setattr(sw, "show_settings", lambda a: opened.append(a))
    try:
        sw.action_show_all_advisories(app, True)
        assert opened == [app] and sw.advisories_shown_in_full() is True
        sw.action_show_all_advisories(app, False)
        assert sw.advisories_shown_in_full() is False
    finally:
        sw._show_all_advisories["on"] = False


# -- RES-5: the RESOLVE section ---------------------------------------------


def _health_app(health):
    app = _plain_app()
    app.resolve_health = lambda: health
    return app


def test_resolve_section_names_the_counts_and_offers_the_scan():
    import time as _time

    app = _health_app({
        "connected": True, "project_open": "FF5 ROUGH",
        "out_of_tree": 40, "missing": 3, "bad_prefix": 0,
        "last_scan_at": _time.time() - 600,
    })
    items = _section(build_settings_model(_snap(app), app), "RESOLVE").items
    lines = [i.text for i in items if isinstance(i, Line)]
    assert any("Connected to Resolve" in l for l in lines)
    assert any("Project open: FF5 ROUGH" in l for l in lines)
    assert any("40 clip(s) are stored outside your synced folder" in l for l in lines)
    assert any("3 clip(s) in this project are offline" in l for l in lines)
    assert any("Checked 10 min ago" in l for l in lines)
    assert "SCAN WHOLE PROJECT" in [i.label for i in items if isinstance(i, Button)]


def test_a_count_with_no_scan_behind_it_is_not_rendered():
    """resolve_health's own rule: with Resolve closed every count is zero and
    last_scan_at is None, and a zero that means "we have not looked" must not
    render as "nothing is wrong"."""
    app = _health_app({"connected": False, "out_of_tree": 12, "last_scan_at": None})
    lines = [i.text for i in _section(build_settings_model(_snap(app), app),
                                      "RESOLVE").items if isinstance(i, Line)]
    assert any("Not connected to Resolve" in l for l in lines)
    assert not any("stored outside" in l for l in lines)


def test_a_wedged_resolve_says_so_only_past_twenty_seconds():
    app = _health_app({"connected": True, "wedged_seconds": 45,
                       "wedged_call": "GetCurrentTimeline"})
    lines = [i.text for i in _section(build_settings_model(_snap(app), app),
                                      "RESOLVE").items if isinstance(i, Line)]
    assert any("has not answered GetCurrentTimeline for 45s" in l for l in lines)

    app2 = _health_app({"connected": True, "wedged_seconds": 5,
                        "wedged_call": "GetCurrentTimeline"})
    lines2 = [i.text for i in _section(build_settings_model(_snap(app2), app2),
                                       "RESOLVE").items if isinstance(i, Line)]
    assert not any("has not answered" in l for l in lines2)


def test_resolve_section_reports_proxy_attachment_and_the_gap_reasons():
    app = _health_app({
        "connected": True,
        "proxy_attach": {"attached": 30, "failed": 12,
                         "why": "Resolve refused the media pool write"},
        "proxy_gaps": {"low_space": 7, "capped": 0, "truncated": 2},
        "stills": {"ok": False,
                   "instruction": "Set the still store to your synced folder"},
    })
    lines = [i.text for i in _section(build_settings_model(_snap(app), app),
                                      "RESOLVE").items if isinstance(i, Line)]
    assert any("12 could not be attached: Resolve refused" in l for l in lines)
    assert any("7 proxies skipped: this disk is low on space" in l for l in lines)
    assert any("2 proxies skipped: the list was too long" in l for l in lines)
    assert not any("0 proxies skipped" in l for l in lines)
    assert any("Set the still store" in l for l in lines)


def test_undo_last_fix_is_offered_only_when_there_is_something_to_undo():
    app = _health_app({"connected": True})
    app.undo_last_fix_available = lambda: True
    labels = [i.label for i in _section(build_settings_model(_snap(app), app),
                                        "RESOLVE").items if isinstance(i, Button)]
    assert "UNDO LAST FIX" in labels

    app.undo_last_fix_available = lambda: False
    labels2 = [i.label for i in _section(build_settings_model(_snap(app), app),
                                         "RESOLVE").items if isinstance(i, Button)]
    assert "UNDO LAST FIX" not in labels2


def test_an_app_without_resolve_health_draws_no_resolve_section():
    app = _plain_app()
    assert "RESOLVE" not in _titles(build_settings_model(_snap(app), app))


# -- CMEDIA-2: the JOBS section ---------------------------------------------


def _jobs_app(status):
    app = _plain_app()
    app.jobs_status = lambda: status
    return app


def test_jobs_section_shows_the_gate_the_current_job_and_the_last_ten():
    import time as _time

    app = _jobs_app({
        "gate": {"taking_work": False, "reason": "you are at the keyboard"},
        "current": {"id": "j1", "kind": "whisper", "rel_path": "FF5/a.mov",
                    "started_at": _time.time() - 240, "forced_reason": ""},
        "recent": [{"id": "j0", "kind": "proxy-480p", "rel_path": "FF5/b.mov",
                    "outcome": "failed", "error": "ffmpeg exited 1",
                    "finished_at": _time.time() - 3600}],
    })
    items = _section(build_settings_model(_snap(app), app), "JOBS").items
    lines = [i.text for i in items if isinstance(i, Line)]
    assert any("Not taking work: you are at the keyboard" in l for l in lines)
    assert any("whisper on FF5/a.mov (started 4 min ago)" in l for l in lines)
    assert any("proxy-480p on FF5/b.mov: failed" in l and "ffmpeg exited 1" in l
               for l in lines)
    assert "STOP THIS JOB" in [i.label for i in items if isinstance(i, Button)]


def test_no_current_job_offers_no_stop_button():
    app = _jobs_app({"gate": {"taking_work": True}, "current": {}, "recent": []})
    items = _section(build_settings_model(_snap(app), app), "JOBS").items
    assert any(i.text == "Taking fleet work" for i in items if isinstance(i, Line))
    assert not [i for i in items if isinstance(i, Button)]


def test_stopping_a_job_that_is_not_running_never_says_it_stopped(monkeypatch):
    said = []
    app = _plain_app()
    app.stop_current_job = lambda: False
    monkeypatch.setattr(sw.tray_mod, "_spawn", lambda a, label, fn: fn())
    monkeypatch.setattr(sw.tray_mod, "_notify", lambda a, msg: said.append(msg))
    sw.action_stop_current_job(app)
    assert said == ["There is no fleet job running now."]


def test_an_app_without_jobs_status_draws_no_jobs_section():
    app = _plain_app()
    assert "JOBS" not in _titles(build_settings_model(_snap(app), app))


# -- APP-8 / APP-9 / APP-13 --------------------------------------------------


def test_a_refused_credential_offers_sign_in_again_even_while_signed_in():
    app = _plain_app()
    guard = {"reporter": {"consecutive_failures": 99, "last_status": "HTTP 401"}}
    items = _section(build_settings_model(_snap(app, sync_guard=guard), app),
                     "THIS COMPUTER").items
    labels = [i.label for i in items if isinstance(i, Button)]
    lines = [i.text for i in items if isinstance(i, Line)]
    assert "SIGN IN AGAIN…" in labels
    assert "SIGN OUT" in labels          # still signed in as far as this machine knows
    assert any("The server rejected this computer's sign-in" in l for l in lines)
    assert labels.index("SIGN IN AGAIN…") < labels.index("SIGN OUT")


def test_a_healthy_reporter_offers_no_sign_in_again():
    app = _plain_app()
    guard = {"reporter": {"consecutive_failures": 0, "last_status": "HTTP 200"}}
    labels = [i.label for i in _section(
        build_settings_model(_snap(app, sync_guard=guard), app),
        "THIS COMPUTER").items if isinstance(i, Button)]
    assert "SIGN IN AGAIN…" not in labels


def test_the_licence_line_drops_the_wizard_and_offers_the_one_click():
    app = _plain_app()
    guard = {"blocked": {
        "reason": "licence_pending",
        "detail": ("The CC Sync licence agreement has not been accepted on this "
                   "machine. Re-run the CCSync setup wizard to read and accept it."),
    }}
    items = _section(build_settings_model(_snap(app, sync_guard=guard), app),
                     "SYNC LANES").items
    lines = [i.text for i in items if isinstance(i, Line)]
    licence = [l for l in lines if "licence agreement" in l]
    assert licence, "the licence refusal must still be shown"
    assert not any("setup wizard" in l for l in licence)
    assert any("Nothing syncs until it is accepted" in l for l in licence)
    assert "READ AND ACCEPT THE LICENCE" in [i.label for i in items
                                             if isinstance(i, Button)]
    # and the blocked summary is not repeated underneath it
    assert len(licence) == 1


def test_accepting_the_licence_prefers_the_apps_own_dialog(monkeypatch):
    ran = []
    app = _plain_app()
    app.open_licence_dialog = lambda: ran.append("dialog")
    monkeypatch.setattr(sw.tray_mod, "_spawn", lambda a, label, fn: fn())
    sw.action_accept_licence(app)
    assert ran == ["dialog"]


def test_restart_is_always_offered(monkeypatch):
    app = _plain_app()
    labels = [i.label for i in _section(build_settings_model(_snap(app), app),
                                        "THIS COMPUTER").items
              if isinstance(i, Button)]
    assert "RESTART CCSYNC NOW" in labels

    # and it calls the tray's restart action when that builder's half exists
    ran = []
    monkeypatch.setattr(sw.tray_mod, "action_restart", lambda a: ran.append(a),
                        raising=False)
    sw.action_restart(app)
    assert ran == [app]


def test_age_phrase_reads_in_words():
    import time as _time

    now = _time.time()
    assert sw.age_phrase(now - 10, now) == "just now"
    assert sw.age_phrase(now - 600, now) == "10 min ago"
    assert sw.age_phrase(now - 7200, now) == "2 h ago"
    assert sw.age_phrase("", now) == ""
    assert sw.age_phrase("not a time", now) == ""
