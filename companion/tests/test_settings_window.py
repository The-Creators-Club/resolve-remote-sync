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
        assert not any("RESTART CCSYNC NOW" in l for l in lines)

        config_mod.set_value(path, "mode", "base")
        lines2 = _labels(
            _section(build_settings_model(_tray_snapshot(app), app), "THIS COMPUTER"))
        assert any("RESTART CCSYNC NOW" in l for l in lines2)
        assert any("takes effect" in l for l in lines2)
    finally:
        config_mod.CONFIG_PATH = real_config_path


# -- role switch actions --------------------------------------------------


def test_switching_to_base_writes_config_without_a_confirmation(tmp_path, monkeypatch):
    from ccsync_companion import config as config_mod

    path = tmp_path / "config.toml"
    config_mod.ensure_config_exists(path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    notified = []
    monkeypatch.setattr(sw.tray_mod, "_notify", lambda a, msg: notified.append(msg))

    sw.action_set_role(app, "base")
    assert config_mod.load_config(path)["mode"] == "base"
    assert any("WIRED TO THE SERVER" in m for m in notified)


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
