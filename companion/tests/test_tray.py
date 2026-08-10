"""Pure tray-logic tests (icon color computation). The actual pystray.Icon /
Tk-style windowed bits aren't exercised here — see README.md's known
limitations for manual verification steps."""

from __future__ import annotations

from ccsync_companion.sync.base import LaneStatus
from ccsync_companion.tray import compute_overall_color


def _status(name, state):
    return LaneStatus(name=name, state=state)


def test_all_ok_is_green():
    statuses = [_status("a", "idle"), _status("b", "idle"), _status("c", "idle")]
    assert compute_overall_color(statuses) == "green"


def test_any_syncing_is_orange():
    statuses = [_status("a", "idle"), _status("b", "syncing")]
    assert compute_overall_color(statuses) == "orange"


def test_any_error_is_red_even_if_another_is_syncing():
    statuses = [_status("a", "syncing"), _status("b", "error")]
    assert compute_overall_color(statuses) == "red"


def test_empty_statuses_is_green():
    assert compute_overall_color([]) == "green"


class _FakeIdentity:
    def __init__(self, username=None):
        self._username = username

    def valid(self):
        return self._username is not None

    @property
    def username(self):
        return self._username


class _FakeApp:
    def __init__(self, config, identity=None):
        self.config = config
        self.log_path = "x.log"
        self.identity = identity if identity is not None else _FakeIdentity(None)
        self.paused = False
        self.config_problems: list[str] = []
        self._require_login = True
        self._sync_enabled = True

    def lane_statuses(self):
        return [_status("a", "idle")]

    def is_paused(self):
        return self.paused


def _menu_labels(menu):
    return [str(item.text) for item in menu.items]


def _all_menu_labels(menu):
    """Labels including those inside submenus (UX-17 added an Advanced ▸)."""
    labels = []
    for item in menu.items:
        labels.append(str(item.text))
        submenu = getattr(item, "submenu", None)
        if submenu is not None:
            labels.extend(_all_menu_labels(submenu))
    return labels


# -- UX-1: green must mean something ---------------------------------------


def _idle3():
    return [_status("lane_a_video_up", "idle"), _status("lane_b_proxy_down", "idle"),
            _status("lane_c_syncthing", "idle")]


def test_not_signed_in_is_never_green():
    """UX-1 [verified]: with require_login=true (the default) and nobody
    signed in, the icon was GREEN -- because green only ever meant "no lane
    errored and none is mid-transfer"."""
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity(None))
    assert compute_overall_color(_idle3(), app) == "orange"


def test_signed_in_and_idle_is_green():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("alex"))
    assert compute_overall_color(_idle3(), app) == "green"


def test_paused_is_never_green():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("alex"))
    app.paused = True
    assert compute_overall_color(_idle3(), app) == "orange"


def test_sync_disabled_is_never_green():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("alex"))
    app._sync_enabled = False
    assert compute_overall_color(_idle3(), app) == "orange"


def test_config_problems_are_red():
    """DEL-3: lanes no longer start at all in this state, so it must not
    read as anything other than broken."""
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("alex"))
    app.config_problems = ["remote_root is blank -- ..."]
    assert compute_overall_color(_idle3(), app) == "red"


def test_menu_has_dashboard_link_when_url_configured():
    from ccsync_companion.tray import _build_menu

    menu = _build_menu(_FakeApp({"dashboard_url": "http://192.168.0.102:8480"}))
    assert "Open dashboard" in _menu_labels(menu)


def test_menu_omits_dashboard_link_when_url_blank():
    from ccsync_companion.tray import _build_menu

    menu = _build_menu(_FakeApp({"dashboard_url": ""}))
    assert "Open dashboard" not in _menu_labels(menu)


def test_menu_always_has_scan_whole_project():
    from ccsync_companion.tray import _build_menu

    # Present regardless of managed/dashboard mode -- not gated on
    # dashboard_url the way "Open dashboard" is. UX-17 moved it (and
    # Consolidate) under Advanced: they are the two rarest and most
    # dangerous actions and used to sit above the common ones.
    menu = _build_menu(_FakeApp({"dashboard_url": ""}))
    assert "Scan whole project" in _all_menu_labels(menu)

    menu = _build_menu(_FakeApp({"dashboard_url": "http://192.168.0.102:8480"}))
    assert "Scan whole project" in _all_menu_labels(menu)


def test_menu_always_has_consolidate_under_its_new_name():
    from ccsync_companion.tray import _build_menu

    # UX-13: "Consolidate" is Resolve's own word for Media Management →
    # Consolidate, which TRIMS AND DELETES unused media. The audit calls it
    # the most dangerous single word in the product.
    labels = _all_menu_labels(_build_menu(_FakeApp({"dashboard_url": ""})))
    assert "Bring an existing project's media into the synced folder…" in labels
    assert not any("Consolidate" in label for label in labels)


# -- sign in / sign out -----------------------------------------------


def test_menu_shows_sign_in_when_not_signed_in():
    from ccsync_companion.tray import _build_menu

    menu = _build_menu(_FakeApp({"dashboard_url": ""}, identity=_FakeIdentity(None)))
    labels = _menu_labels(menu)
    # UX-1/UX-8: the sign-in step is the switch that turns sync on, and
    # nothing anywhere said so.
    assert "► Sign in… (nothing syncs until you do)" in labels
    assert "Sign out" not in labels
    assert "NOT SIGNED IN" in labels


def test_menu_does_not_claim_nothing_syncs_when_login_is_not_required():
    """With require_login=false the lanes are already running under
    editor_name, so "(nothing syncs until you do)" sends the editor chasing a
    sign-in they don't need. compute_overall_color() has always made this
    check; the menu and the tooltip did not."""
    from ccsync_companion.tray import _build_menu

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity(None))
    app._require_login = False
    labels = _menu_labels(_build_menu(app))
    assert "Sign in…" in labels
    assert not any("nothing syncs" in label for label in labels)


def test_tooltip_does_not_claim_nothing_syncs_when_login_is_not_required():
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity(None))
    app._require_login = False
    assert _tooltip_text(_tray_snapshot(app)) == "CCSync: up to date"

    app._require_login = True
    assert "not signed in" in _tooltip_text(_tray_snapshot(app))


def test_menu_shows_sign_out_and_status_when_signed_in():
    from ccsync_companion.tray import _build_menu

    menu = _build_menu(_FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("alex")))
    labels = _menu_labels(menu)
    assert "Sign out" in labels
    assert "Sign in…" not in labels
    assert "Signed in as alex" in labels


def test_identity_status_label_helper():
    from ccsync_companion.tray import _identity_status_label

    assert _identity_status_label(_FakeApp({}, identity=_FakeIdentity(None))) == "NOT SIGNED IN"
    assert _identity_status_label(_FakeApp({}, identity=_FakeIdentity("ruskin"))) == "Signed in as ruskin"


def test_menu_handles_app_without_identity_attribute():
    """Defensive: a bare app-like object without an `identity` attribute
    (e.g. an older/partial test double) must not crash menu building."""
    from ccsync_companion.tray import _build_menu

    class _BareApp:
        config = {"dashboard_url": ""}
        log_path = "x.log"

        def lane_statuses(self):
            return []

        def is_paused(self):
            return False

    menu = _build_menu(_BareApp())
    assert "NOT SIGNED IN" in _menu_labels(menu)
    assert any("Sign in" in label for label in _menu_labels(menu))


class _FakeAppWithUpgrade(_FakeApp):
    def __init__(self, config, info=None):
        super().__init__(config)
        self._info = info

    def upgrade_available(self):
        return self._info


def test_menu_shows_update_item_only_when_available():
    """The offered version here is deliberately NEWER than the running build:
    "Update available" is only correct for an upgrade (see the downgrade
    tests below)."""
    from ccsync_companion.tray import _build_menu

    menu = _build_menu(_FakeAppWithUpgrade({"dashboard_url": ""}, {"version": "99.0.0"}))
    assert "Update available → v99.0.0 (install)" in _menu_labels(menu)

    menu = _build_menu(_FakeAppWithUpgrade({"dashboard_url": ""}, None))
    assert not any("Update available" in label for label in _menu_labels(menu))

    # an app double without the method at all (older fakes) must not crash
    menu = _build_menu(_FakeApp({"dashboard_url": ""}))
    assert not any("Update available" in label for label in _menu_labels(menu))


# ===========================================================================
# An offered build that is OLDER than the running one is a DOWNGRADE
# ===========================================================================


def test_menu_calls_an_older_offered_build_a_rollback_not_an_update():
    """THE BUG, seen live 2026-07-25: this rig ran v0.4.5 (installed straight
    from a build), the dashboard still published v0.4.3 as `current`, and the
    tray offered "Update available → v0.4.3 (install)". One click would have
    silently DOWNGRADED the machine and reintroduced a whole round of
    security fixes. upgrade.py advertises "different, not newer" on purpose
    (an admin can roll the fleet back) -- so the WORDING has to carry the
    direction the mechanism doesn't."""
    from ccsync_companion import config as config_mod
    from ccsync_companion.tray import _build_menu

    older = "0.0.1"
    assert older < config_mod.VERSION
    labels = _menu_labels(_build_menu(_FakeAppWithUpgrade({"dashboard_url": ""},
                                                          {"version": older})))
    offer = next(la for la in labels if older in la)
    assert offer == "Roll back to v0.0.1 (older build, install)"
    assert "update" not in offer.lower(), "a downgrade must never read as an update"


def test_menu_uses_neutral_wording_for_an_unparseable_version():
    """A weird version string must degrade to neutral wording, never crash
    the tray and never guess a direction."""
    from ccsync_companion.tray import _build_menu

    labels = _menu_labels(
        _build_menu(_FakeAppWithUpgrade({"dashboard_url": ""}, {"version": "nightly"}))
    )
    assert "Switch to vnightly (install)" in labels


class _FakeAppWithSetup(_FakeApp):
    def __init__(self, config, name=None):
        super().__init__(config)
        self._setup_name = name

    def setup_project_available(self):
        return self._setup_name


def test_menu_shows_setup_item_only_when_unmapped():
    from ccsync_companion.tray import _build_menu

    menu = _build_menu(_FakeAppWithSetup({"dashboard_url": ""}, "New Doc"))
    assert "Set up 'New Doc' on the server…" in _menu_labels(menu)

    menu = _build_menu(_FakeAppWithSetup({"dashboard_url": ""}, None))
    assert not any("Set up" in label for label in _menu_labels(menu))

    # app double without the method must not crash
    menu = _build_menu(_FakeApp({"dashboard_url": ""}))
    assert not any("Set up" in label for label in _menu_labels(menu))


def test_menu_first_item_is_the_signed_in_status():
    """UX-17: the version string used to be the FIRST thing in the menu --
    the least actionable item in it. Signed-in status leads now; the version
    moved under Advanced (it still has to be findable for support)."""
    from ccsync_companion import config as config_mod
    from ccsync_companion.tray import _build_menu

    menu = _build_menu(_FakeApp({"dashboard_url": ""}))
    assert _menu_labels(menu)[0] == "NOT SIGNED IN"
    assert f"ccsync-companion v{config_mod.VERSION}" in _all_menu_labels(menu)


def test_update_item_is_never_adjacent_to_quit():
    """UX-17: `Update available…` sat DIRECTLY above `Quit` -- the one item
    you must never mis-click."""
    from ccsync_companion.tray import _build_menu

    labels = _menu_labels(
        _build_menu(_FakeAppWithUpgrade({"dashboard_url": ""}, {"version": "0.9.9"}))
    )
    update_i = next(i for i, la in enumerate(labels) if "Update available" in la)
    quit_i = next(i for i, la in enumerate(labels) if la.startswith("Quit"))
    assert abs(update_i - quit_i) > 1


def test_quit_says_it_stops_syncing():
    from ccsync_companion.tray import _build_menu

    labels = _menu_labels(_build_menu(_FakeApp({"dashboard_url": ""})))
    quit_label = next(la for la in labels if la.startswith("Quit"))
    assert "stops syncing" in quit_label


def test_pause_label_carries_state():
    """UX-2: after clicking Pause the only evidence was a menu checkmark
    most users never register."""
    from ccsync_companion.tray import _build_menu

    app = _FakeApp({"dashboard_url": ""})
    assert "⏸ Pause syncing" in _menu_labels(_build_menu(app))
    app.paused = True
    assert "▶ Resume syncing (currently PAUSED)" in _menu_labels(_build_menu(app))


def test_menu_offers_copy_diagnostics():
    """UX-19: the highest-leverage cheap change in the audit -- it converts
    every unknown failure into a single paste."""
    from ccsync_companion.tray import _build_menu

    assert "Copy diagnostics for your admin" in _menu_labels(
        _build_menu(_FakeApp({"dashboard_url": ""})))


# -- UX-1 / UX-2 / UX-11 / UX-12: the tray must tell the truth ------------


def test_lane_line_never_says_ok_when_not_signed_in():
    """UX-1 [verified]: three lanes reading `OK` under a GREEN icon while
    literally nothing syncs. `OK` was the first word on every line whatever
    the state, because pending-login only ever wrote to LaneStatus.detail."""
    from ccsync_companion.tray import _format_lane_line

    status = LaneStatus(
        name="lane_a_video_up", state="idle",
        detail='sign in required -- use the tray\'s "Sign in..." to authenticate before syncing',
    )
    line = _format_lane_line(status, _FakeApp({"dashboard_url": ""}))
    assert "OK" not in line
    assert "NOT SYNCING (sign in first)" in line


def test_lane_line_says_sync_disabled_rather_than_ok():
    from ccsync_companion.tray import _format_lane_line

    status = LaneStatus(name="lane_b_proxy_down", state="idle",
                        detail="sync disabled: this machine works directly off the NAS")
    line = _format_lane_line(status, _FakeApp({"dashboard_url": ""}))
    assert "OK" not in line
    assert "not used on this machine" in line


def test_lane_line_reports_paused_first():
    """UX-2: no lane ever sets state="paused" -- the sequencer owns pause --
    so all three lines read normally after clicking it."""
    from ccsync_companion.tray import _format_lane_line

    app = _FakeApp({"dashboard_url": ""})
    app.paused = True
    line = _format_lane_line(LaneStatus(name="lane_c_syncthing", state="idle"), app)
    assert "PAUSED" in line


def test_lane_line_shows_live_stats_not_a_permanently_zero_queue():
    """UX-11: `queued` is reset to 0 at the end of every run and incremented
    by nothing, so the only during-sync text was "syncing (0 queued)"."""
    from ccsync_companion.tray import _format_lane_line

    status = LaneStatus(
        name="lane_a_video_up", state="syncing", queued=0,
        bytes_done=4_400_000_000, bytes_total=41_000_000_000,
        speed_bps=50_000_000, eta_seconds=700,
    )
    line = _format_lane_line(status, _FakeApp({"dashboard_url": ""}))
    assert "queued" not in line
    assert "GB" in line and "/s" in line and "left" in line


def test_lane_labels_are_editor_facing():
    """UX-12: the tray literally read "lane a video up: OK", and no legend
    for the A/B/C letters exists anywhere in the product."""
    from ccsync_companion.tray import _format_lane_line

    app = _FakeApp({"dashboard_url": ""})
    lines = [
        _format_lane_line(LaneStatus(name=n, state="idle"), app)
        for n in ("lane_a_video_up", "lane_b_proxy_down", "lane_c_syncthing")
    ]
    assert lines[0].startswith("Uploads (your footage → server)")
    assert lines[1].startswith("Proxies (server → you)")
    assert lines[2].startswith("Everything else, both ways (audio, graphics, subs)")
    assert not any("lane a" in la or "lane_a" in la for la in lines)


def test_lane_error_is_classified_not_dumped_verbatim():
    """UX-16: rclone's exit code plus 300 chars of stderr, shown raw."""
    from ccsync_companion.tray import _format_lane_line

    app = _FakeApp({"dashboard_url": ""})
    net = LaneStatus(name="lane_a_video_up", state="error",
                     last_error="rclone exited 1: dial tcp 100.71.216.3:22: i/o timeout")
    assert "Tailscale" in _format_lane_line(net, app)
    assert "dial tcp" not in _format_lane_line(net, app)

    full = LaneStatus(name="lane_a_video_up", state="error",
                      last_error="rclone exited 1: write /x: no space left on device")
    assert "disk is full" in _format_lane_line(full, app)


# ===========================================================================
# AUDIT_2 CORE-H8: the update dialog's failure path
# ===========================================================================


class _UpgradeApp(_FakeApp):
    """App double for the update dialog: records whether apply_upgrade ran."""

    def __init__(self, config=None):
        super().__init__(config or {"dashboard_url": ""})
        import threading

        self._popup_active_lock = threading.Lock()
        self.applied = 0
        self.notified: list[str] = []

    def upgrade_available(self):
        return {"version": "9.9.9", "url": "/x", "sha256": "0" * 64}

    def apply_upgrade(self):
        self.applied += 1

    def _notify_tray(self, msg, title="ccsync-companion"):
        self.notified.append(msg)


def test_tk_failure_does_not_apply_the_upgrade(monkeypatch):
    """AUDIT_2 CORE-H8. Both tray dialogs created their own tk.Tk() on a
    daemon thread with NO reference to app._popup_active_lock -- and on
    failure the handler called app.apply_upgrade() with NO confirmation
    dialog ever shown.

    The failure mode is caused by exactly the condition the lock exists to
    prevent ("tk.Tk() can raise or wedge Tcl when other Tk roots have run on
    sibling threads in this process" -- the module's own comment, seen live
    2026-07-25). So the situation that triggered the fallback was the one
    where applying was most destructive: the fixer popup is open copying
    60 GB, the exe is swapped, request_shutdown() fires ~1 s later, and the
    daemon FIX-ALL thread dies mid-shutil.copy2 -- leaving a partial
    .ccsync-tmp and a project where some clips are relinked and some are not.
    """
    import sys
    import types

    from ccsync_companion import tray as tray_mod

    app = _UpgradeApp()

    broken = types.ModuleType("tkinter")

    def _boom(*a, **k):
        raise RuntimeError("Tcl is wedged")

    broken.Tk = _boom
    monkeypatch.setitem(sys.modules, "tkinter", broken)

    tray_mod._show_update_dialog(app)

    assert app.applied == 0, "a dialog failure must ABORT, never apply silently"
    assert any("nothing was changed" in m for m in app.notified)


def test_update_dialog_refuses_while_another_window_holds_the_popup_lock(monkeypatch):
    from ccsync_companion import tray as tray_mod

    app = _UpgradeApp()
    app._popup_active_lock.acquire()  # e.g. the fixer popup is open
    tray_mod._show_update_dialog(app)
    assert app.applied == 0
    assert any("Can't update while a CCSync window is open" in m for m in app.notified)


def test_sign_in_dialog_refuses_while_another_window_holds_the_popup_lock(monkeypatch):
    from ccsync_companion import tray as tray_mod

    app = _UpgradeApp()
    app._popup_active_lock.acquire()
    opened = []
    monkeypatch.setattr(tray_mod, "_show_sign_in_dialog_locked", lambda a: opened.append(1))
    tray_mod._show_sign_in_dialog(app)
    assert opened == []


def test_tray_callbacks_log_instead_of_dying_silently(caplog):
    """AUDIT_2 CORE-M9: every tray callback spawned a bare Thread with no
    try/except. Clicking Consolidate could do nothing at all AND leave no log
    entry -- indistinguishable from a dead tray."""
    import logging

    from ccsync_companion import tray as tray_mod

    app = _UpgradeApp()

    def boom():
        raise RuntimeError("nope")

    with caplog.at_level(logging.ERROR, logger="ccsync.tray"):
        tray_mod._guarded(app, "Consolidate", boom)
    assert any("Consolidate" in r.message for r in caplog.records)
    assert any("Copy diagnostics" in m for m in app.notified)


def test_icon_stop_actually_stops_the_refresh_loop():
    """AUDIT_2 §2-low: `_ccsync_stop` was read by the 5 s refresh loop and
    ASSIGNED NOWHERE in the repo, so the thread outlived icon.stop() and kept
    calling app.lane_statuses() and assigning icon.menu on a dead icon
    through the whole shutdown/self-upgrade window."""
    import ccsync_companion.tray as tray_mod

    stopped = []

    class _FakeIcon:
        def __init__(self, *a, **k):
            self.icon = None
            self.menu = None

        def stop(self):
            stopped.append(True)

        def run(self):
            pass

    real_icon = tray_mod.pystray.Icon
    try:
        tray_mod.pystray.Icon = _FakeIcon
        icon = tray_mod.start_tray(_FakeApp({"dashboard_url": ""}), refresh_interval=0.01)
        icon.stop()
        assert getattr(icon, "_ccsync_stop", False) is True
        assert stopped == [True]
    finally:
        tray_mod.pystray.Icon = real_icon


# -- snapshot + fingerprint (the 2026-07-26 right-click freeze) -------------


def test_build_menu_accepts_a_prebuilt_snapshot():
    from ccsync_companion.tray import _build_menu, _tray_snapshot

    app = _FakeApp({"dashboard_url": "http://192.168.0.102:8480"})
    snap = _tray_snapshot(app)
    labels = _menu_labels(_build_menu(app, snap))
    assert "Open dashboard" in labels
    assert "NOT SIGNED IN" in labels


def test_fingerprint_stable_under_byte_churn_within_a_bucket():
    """The menu must NOT be rebuilt for every stats tick while syncing --
    each icon.menu assignment DestroyMenu()s a handle the user may have
    open. Only a real state change (or a tenth of progress) rebuilds."""
    from ccsync_companion.tray import _menu_fingerprint, _tray_snapshot

    def app_with(done):
        app = _FakeApp({"dashboard_url": ""})
        app.lane_statuses = lambda: [LaneStatus(
            name="lane_a_video_up", state="syncing",
            bytes_done=done, bytes_total=100_000_000_000,
            speed_bps=50_000_000 + done % 999, eta_seconds=done % 100,
        )]
        return app

    fp1 = _menu_fingerprint(_tray_snapshot(app_with(10_000_000_000)))
    fp2 = _menu_fingerprint(_tray_snapshot(app_with(14_000_000_000)))  # same tenth
    fp3 = _menu_fingerprint(_tray_snapshot(app_with(90_000_000_000)))  # different tenth
    assert fp1 == fp2
    assert fp1 != fp3

    idle = _FakeApp({"dashboard_url": ""})
    assert _menu_fingerprint(_tray_snapshot(idle)) != fp1


def test_fingerprint_changes_on_pause_and_sign_in():
    from ccsync_companion.tray import _menu_fingerprint, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""})
    fp_plain = _menu_fingerprint(_tray_snapshot(app))
    app.paused = True
    fp_paused = _menu_fingerprint(_tray_snapshot(app))
    assert fp_plain != fp_paused
    app.paused = False
    app.identity = _FakeIdentity("alex")
    assert _menu_fingerprint(_tray_snapshot(app)) != fp_plain


def test_tooltip_shows_live_numbers_and_states():
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("alex"))
    assert _tooltip_text(_tray_snapshot(app)) == "CCSync: up to date"

    app.lane_statuses = lambda: [LaneStatus(
        name="lane_a_video_up", state="syncing", current_project="2026/CCT/Website Highlights",
        speed_bps=50_000_000, eta_seconds=700,
    )]
    tip = _tooltip_text(_tray_snapshot(app))
    assert "syncing" in tip and "/s" in tip and "left" in tip
    assert len(tip) <= 127

    app.paused = True
    assert "PAUSED" in _tooltip_text(_tray_snapshot(app))

    signed_out = _FakeApp({"dashboard_url": ""})
    assert "not signed in" in _tooltip_text(_tray_snapshot(signed_out))


def test_menu_open_guard_tracks_the_popup_call(monkeypatch):
    """While TrackPopupMenuEx blocks (menu open), is_open() must be True; the
    flag must clear even if the call raises."""
    import sys

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("pystray win32 backend only")
    from pystray import _win32

    from ccsync_companion import tray as tray_mod

    seen = {}
    guard = tray_mod._MenuOpenGuard()

    def fake_track(*args, **kwargs):
        seen["open_during"] = guard.is_open()
        return 0

    monkeypatch.setattr(_win32.win32, "TrackPopupMenuEx", fake_track, raising=True)
    monkeypatch.setattr(_win32.win32, "_ccsync_menu_open_flag", None, raising=False)
    guard.install()

    assert guard.is_open() is False
    _win32.win32.TrackPopupMenuEx()
    assert seen["open_during"] is True
    assert guard.is_open() is False

    # a raising call must still clear the flag
    def raising_track(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_win32.win32, "_ccsync_menu_open_flag", None, raising=False)
    monkeypatch.setattr(_win32.win32, "TrackPopupMenuEx", raising_track, raising=True)
    guard2 = tray_mod._MenuOpenGuard()
    guard2.install()
    with _pytest.raises(RuntimeError):
        _win32.win32.TrackPopupMenuEx()
    assert guard2.is_open() is False

    # a second guard adopts the existing wrap instead of double-wrapping
    guard3 = tray_mod._MenuOpenGuard()
    guard3.install()
    assert guard3._open is guard2._open


def test_icon_image_cache_returns_same_object():
    from ccsync_companion.tray import _icon_image_cached

    assert _icon_image_cached("green") is _icon_image_cached("green")
    assert _icon_image_cached("green") is not _icon_image_cached("red")


def test_wait_while_menu_open_caps_and_returns_immediately_when_closed():
    import time as _time

    from ccsync_companion import ui_state

    ui_state.menu_open.clear()
    t0 = _time.monotonic()
    ui_state.wait_while_menu_open(max_wait=5.0)
    assert _time.monotonic() - t0 < 0.05      # closed menu: no wait at all

    ui_state.menu_open.set()
    try:
        t0 = _time.monotonic()
        ui_state.wait_while_menu_open(max_wait=0.4, slice_seconds=0.1)
        elapsed = _time.monotonic() - t0
        # a wedged flag must never stall callers past the cap
        assert 0.3 <= elapsed < 2.0
    finally:
        ui_state.menu_open.clear()


def test_menu_open_guard_uses_the_shared_ui_state_flag():
    from ccsync_companion import ui_state
    from ccsync_companion.tray import _MenuOpenGuard

    guard = _MenuOpenGuard()
    assert guard._open is ui_state.menu_open


# -- Remove a project from this machine (menu + friendly marker error) ------


def test_marker_missing_becomes_an_instruction_not_a_problem():
    from ccsync_companion.tray import classify_lane_error

    text = classify_lane_error('folder(s) in error: 2026-cct-x (folder marker missing)')
    assert "deleted" in text and "Untick" in text
    assert "Copy diagnostics" not in text


def test_menu_lists_removable_projects():
    from ccsync_companion.tray import _build_menu, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""})
    app.removable_projects = lambda: [
        {"slug": "2026-cct-website-highlights-website-highlights",
         "rel": "2026/CCT/Website Highlights/Website Highlights"}]
    labels = _all_menu_labels(_build_menu(app, _tray_snapshot(app)))
    assert "Remove 'Website Highlights' from this machine…" in labels

    # and the fingerprint changes when the removable set changes
    from ccsync_companion.tray import _menu_fingerprint
    fp_with = _menu_fingerprint(_tray_snapshot(app))
    app.removable_projects = lambda: []
    fp_without = _menu_fingerprint(_tray_snapshot(app))
    assert fp_with != fp_without



def test_menu_offers_grade_swap_and_label_flips():
    from ccsync_companion.tray import _build_menu, _menu_fingerprint, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""})
    app.p_swap_available = lambda: True
    app.p_mapping_mode = lambda: "local"
    labels = _menu_labels(_build_menu(app, _tray_snapshot(app)))
    assert any("Grade from server originals" in l for l in labels)
    fp_local = _menu_fingerprint(_tray_snapshot(app))

    app.p_mapping_mode = lambda: "server"
    labels = _menu_labels(_build_menu(app, _tray_snapshot(app)))
    assert any("back to local proxies" in l for l in labels)
    assert _menu_fingerprint(_tray_snapshot(app)) != fp_local

    # hidden entirely when unavailable (base rig / unconfigured)
    app2 = _FakeApp({"dashboard_url": ""})
    labels = _menu_labels(_build_menu(app2, _tray_snapshot(app2)))
    assert not any("Grade" in l for l in labels)


# -- the sync drive is out (root_guard.py) ----------------------------------


def test_lane_lines_say_the_drive_is_disconnected():
    """An editor whose SSD is unplugged must read "PAUSED — drive
    disconnected", not "this machine isn't set up yet" -- the first names a
    five-second fix, the second sends them to their admin."""
    from ccsync_companion.tray import _format_lane_line_from

    line = _format_lane_line_from(
        _status("lane_b_proxy_down", "idle"), paused=False, problems=False,
        root_absent=True,
    )
    assert "PAUSED" in line and "drive disconnected" in line


def test_the_drive_line_outranks_the_not_set_up_line():
    from ccsync_companion.tray import _format_lane_line_from

    line = _format_lane_line_from(
        _status("lane_a_video_up", "idle"), paused=False, problems=True,
        root_absent=True,
    )
    assert "drive disconnected" in line


def test_lane_lines_are_unchanged_when_the_drive_is_there():
    from ccsync_companion.tray import _format_lane_line_from

    status = _status("lane_a_video_up", "idle")
    assert (_format_lane_line_from(status, paused=False, problems=False)
            == _format_lane_line_from(status, paused=False, problems=False,
                                      root_absent=False))


def test_a_lane_error_while_the_drive_is_out_is_not_a_deleted_project():
    """Unplugging an external SSD takes every .stfolder with it, so Syncthing
    reports exactly what it reports when the editor DELETED a project -- and
    that message's advice ("untick it on the dashboard") would unshare a
    project sitting safely on a drive in the editor's bag."""
    from ccsync_companion.tray import classify_lane_error

    raw = "folder(s) in error: 2026-cct-x (folder marker missing)"
    assert "deleted on this machine" in classify_lane_error(raw)
    swapped = classify_lane_error(raw, root_absent=True)
    assert "disconnected" in swapped
    assert "untick" not in swapped.lower()
    assert "nothing was deleted" in swapped


def test_the_snapshot_carries_root_absent_and_the_fingerprint_changes():
    from ccsync_companion.tray import _menu_fingerprint, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("alex"))
    before = _tray_snapshot(app)
    assert before["root_absent"] is False
    fp_before = _menu_fingerprint(before)

    app._root_absent = True
    after = _tray_snapshot(app)

    assert after["root_absent"] is True
    # Without this the menu keeps its stale lane lines: the rebuild is
    # fingerprint-gated (pystray's win32 backend DestroyMenu()s a live menu
    # on every icon.menu assignment, so rebuilds are deliberately rare).
    assert _menu_fingerprint(after) != fp_before


def test_the_menu_lane_lines_pick_the_drive_wording_up():
    from ccsync_companion.tray import _build_menu, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("alex"))
    app._root_absent = True
    labels = _all_menu_labels(_build_menu(app, _tray_snapshot(app)))
    assert any("drive disconnected" in label for label in labels)


def test_the_icon_goes_orange_while_the_drive_is_out():
    """Orange, not red: nothing is broken and nothing is lost -- plugging the
    drive back in resumes sync on its own."""
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("alex"))
    app._root_absent = True
    assert compute_overall_color(_idle3(), app) == "orange"


def test_the_tooltip_names_the_drive():
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("alex"))
    app._root_absent = True
    assert "disconnected" in _tooltip_text(_tray_snapshot(app))


# ===========================================================================
# macOS port: the tray dialogs build their roots through ui_dispatch
# ===========================================================================


def _record_tray_dispatch(monkeypatch, run: bool = False):
    from ccsync_companion import ui_dispatch

    calls: list = []

    def _dispatch(fn):
        calls.append(fn)
        return fn() if run else None

    monkeypatch.setattr(ui_dispatch, "dispatch", _dispatch)
    return calls


def test_the_three_tray_dialogs_go_through_ui_dispatch(monkeypatch):
    """Sign-in, update and server-login each built a tk.Tk() on a tray worker
    thread. On macOS that thread may not touch Tk-Aqua at all, so the root
    build + mainloop is dispatched; on Windows dispatch is inline and the
    behaviour is unchanged."""
    from ccsync_companion import tray as tray_mod

    app = _UpgradeApp()
    calls = _record_tray_dispatch(monkeypatch)

    tray_mod._show_sign_in_dialog_locked(app)
    tray_mod._show_update_dialog_locked(app, {"version": "9.9.9"})
    tray_mod._ask_server_credentials_locked(app)

    assert len(calls) == 3 and all(callable(fn) for fn in calls)


def test_the_popup_lock_is_held_by_the_caller_not_by_dispatch(monkeypatch):
    """LOCK AUDIT. _popup_active_lock is taken OUTSIDE dispatch and is still
    held while the dialog body runs -- dispatch is a transport, not a second
    lock, and it must not invert the order."""
    from ccsync_companion import tray as tray_mod

    app = _UpgradeApp()
    held: list = []

    def _dispatch(fn):
        held.append(("at dispatch", app._popup_active_lock.locked()))
        return fn()

    monkeypatch.setattr(tray_mod.ui_dispatch, "dispatch", _dispatch)
    monkeypatch.setattr(tray_mod, "_build_sign_in_dialog",
                        lambda a: held.append(("in body", a._popup_active_lock.locked())))

    tray_mod._show_sign_in_dialog(app)

    assert held == [("at dispatch", True), ("in body", True)]
    assert not app._popup_active_lock.locked(), "the lock outlived the dialog"


def test_the_update_dialog_answer_survives_the_dispatch_round_trip(monkeypatch):
    """The return value is the whole point here: a dropped False would apply
    an update nobody confirmed."""
    from ccsync_companion import tray as tray_mod

    app = _UpgradeApp()
    _record_tray_dispatch(monkeypatch, run=True)
    monkeypatch.setattr(tray_mod, "_build_update_dialog", lambda a, i: True)
    assert tray_mod._show_update_dialog_locked(app, {"version": "9.9.9"}) is True
    monkeypatch.setattr(tray_mod, "_build_update_dialog", lambda a, i: False)
    assert tray_mod._show_update_dialog_locked(app, {"version": "9.9.9"}) is False


def test_the_credentials_dialog_answer_survives_the_dispatch_round_trip(monkeypatch):
    from ccsync_companion import tray as tray_mod

    app = _UpgradeApp()
    _record_tray_dispatch(monkeypatch, run=True)
    monkeypatch.setattr(tray_mod, "_build_credentials_dialog", lambda a: ("alex", "pw"))
    assert tray_mod._ask_server_credentials_locked(app) == ("alex", "pw")


def test_the_icon_runs_on_a_thread_on_windows_and_detached_on_macos(monkeypatch):
    """pystray's win32 backend owns a message loop of its own on a daemon
    thread (unchanged). On macOS NSStatusItem is main-thread-only, so the
    icon is installed detached against the runloop ui_dispatch.serve() runs."""
    import threading
    import time

    import ccsync_companion.tray as tray_mod

    events: list = []

    class _FakeIcon:
        def __init__(self, *a, **k):
            self.icon = None
            self.menu = None

        def stop(self):
            pass

        def run(self):
            events.append(("run", threading.current_thread().name))

        def run_detached(self):
            events.append(("run_detached", threading.current_thread().name))

    real_icon = tray_mod.pystray.Icon
    try:
        tray_mod.pystray.Icon = _FakeIcon

        monkeypatch.setattr(tray_mod.ui_dispatch, "uses_main_thread", lambda: False)
        icon = tray_mod.start_tray(_FakeApp({"dashboard_url": ""}), refresh_interval=0.01)
        icon.stop()
        deadline = time.monotonic() + 5.0
        while not events and time.monotonic() < deadline:
            time.sleep(0.005)
        assert events and events[0][0] == "run"
        assert events[0][1] != threading.current_thread().name

        events.clear()
        monkeypatch.setattr(tray_mod.ui_dispatch, "uses_main_thread", lambda: True)
        icon = tray_mod.start_tray(_FakeApp({"dashboard_url": ""}), refresh_interval=0.01)
        icon.stop()
        assert events == [("run_detached", threading.current_thread().name)]
    finally:
        tray_mod.pystray.Icon = real_icon


# ===========================================================================
# MAC-7: is the icon macOS just accepted actually being drawn?
# ===========================================================================
#
# The numbers below are measured, not invented: a 16" MacBook Pro, menu bar
# full, NSScreen.frame 1728x1117, auxiliaryTopLeftArea ending at x=771 and
# auxiliaryTopRightArea starting at x=956. Four status items created at once
# landed on x = 812, 774, 736, 698 and NONE of them was rendered.

from ccsync_companion.tray import (  # noqa: E402
    PLACEMENT_NOTCH,
    PLACEMENT_OFF_MENU_BAR,
    PLACEMENT_VISIBLE,
    classify_status_item_placement,
)

SCREEN_H = 1117.0
NOTCH = (771.0, 956.0)
MENU_BAR_Y = 1080.0


def _frame(x, y=MENU_BAR_Y, w=38.0, h=37.0):
    return (x, y, w, h)


def test_an_item_in_the_drawn_menu_bar_is_visible():
    assert classify_status_item_placement(
        _frame(1010.0), SCREEN_H, NOTCH) == PLACEMENT_VISIBLE


def test_an_item_under_the_notch_is_reported_hidden():
    assert classify_status_item_placement(
        _frame(812.0), SCREEN_H, NOTCH) == PLACEMENT_NOTCH


def test_an_item_left_of_the_notch_is_hidden_too():
    """The counter-intuitive one. Clearing the notch is not enough: the item
    measured at x=698 was entirely left of it and still never drawn."""
    assert classify_status_item_placement(
        _frame(698.0), SCREEN_H, NOTCH) == PLACEMENT_NOTCH


def test_an_item_macos_never_placed_is_reported_off_the_menu_bar():
    """An item still being laid out (or refused outright) reports y=-37."""
    assert classify_status_item_placement(
        _frame(0.0, y=-37.0), SCREEN_H, NOTCH) == PLACEMENT_OFF_MENU_BAR


def test_a_notchless_mac_only_fails_items_off_the_menu_bar():
    """No notch API, no notch verdict -- an external display or an older Mac
    must not have every icon declared invisible."""
    assert classify_status_item_placement(
        _frame(700.0), SCREEN_H, None) == PLACEMENT_VISIBLE
    assert classify_status_item_placement(
        _frame(0.0, y=-37.0), SCREEN_H, None) == PLACEMENT_OFF_MENU_BAR


# ===========================================================================
# Items 17 + 19: does the tray say whether the Resolve bridge has connected?
# ===========================================================================
#
# Two multi-hour incidents ran with a dead bridge and a tray reporting three
# healthy lanes: MAC-10 (the macOS modules path was wrong, so the bridge
# never connected once in a session that ran all evening) and item 19
# (Resolve's script server died at launch and never retried). Neither the
# tray nor the diagnostics bundle could answer "has Resolve ever answered
# us?", so both were diagnosed by hand.


def _bridge(connected=None, ever=False, reason=""):
    return {"connected": connected, "ever_connected": ever, "reason": reason}


def test_nothing_is_claimed_before_the_bridge_has_been_asked():
    """Silence, not "not connected": at startup nothing has polled Resolve
    yet, and the two are different sentences."""
    from ccsync_companion.tray import resolve_bridge_line

    assert resolve_bridge_line(_bridge()) is None
    assert resolve_bridge_line(None) is None
    assert resolve_bridge_line("nonsense") is None


def test_a_live_bridge_says_connected():
    from ccsync_companion.tray import resolve_bridge_line

    assert resolve_bridge_line(_bridge(True, ever=True)) == "Resolve: connected"


def test_a_bridge_that_has_never_connected_is_worded_differently():
    """The distinction that matters. Never connected at all is a broken
    install (MAC-10); connected and then gone is Resolve being closed."""
    from ccsync_companion.tray import resolve_bridge_line

    from ccsync_companion.resolve_bridge import NOT_RUNNING_MESSAGE

    never = resolve_bridge_line(_bridge(False, ever=False, reason=NOT_RUNNING_MESSAGE))
    lost = resolve_bridge_line(_bridge(False, ever=True, reason=NOT_RUNNING_MESSAGE))

    assert never.startswith("Resolve: NOT CONNECTED this session")
    assert lost.startswith("Resolve: not connected right now")
    assert never != lost
    assert NOT_RUNNING_MESSAGE in never and NOT_RUNNING_MESSAGE in lost


def test_the_line_carries_the_distinguished_reason():
    """Item 19: "running but isn't accepting scripting connections" asks for
    a different action from "is not running", and the tray must not flatten
    the two back together."""
    from ccsync_companion.resolve_bridge import NO_SCRIPTING_MESSAGE
    from ccsync_companion.tray import resolve_bridge_line

    line = resolve_bridge_line(_bridge(False, ever=True, reason=NO_SCRIPTING_MESSAGE))
    assert "Quit Resolve and reopen it" in line


class _BridgeApp(_FakeApp):
    def __init__(self, state):
        super().__init__({"dashboard_url": ""}, identity=_FakeIdentity("alex"))
        self._bridge_state = state
        self.probes = 0

    def resolve_bridge_state(self):
        self.probes += 1
        return self._bridge_state


def test_the_snapshot_reads_cached_state_and_the_menu_shows_it():
    from ccsync_companion.tray import _build_menu, _tray_snapshot

    from ccsync_companion.resolve_bridge import NOT_RUNNING_MESSAGE

    app = _BridgeApp(_bridge(False, ever=False, reason=NOT_RUNNING_MESSAGE))
    snap = _tray_snapshot(app)

    assert snap["resolve_line"].startswith("Resolve: NOT CONNECTED this session")
    labels = _all_menu_labels(_build_menu(app, snap))
    assert any("NOT CONNECTED this session" in label for label in labels)
    # Cached read only: a fusionscript call holds the GIL for its full native
    # duration, and the render path may never pay for one.
    assert app.probes == 1


def test_the_fingerprint_moves_when_the_bridge_does():
    """The menu is rebuilt only on fingerprint changes (pystray's win32
    backend DestroyMenu()s a live menu on every icon.menu assignment), so a
    line left out of it would stay stale forever."""
    from ccsync_companion.tray import _menu_fingerprint, _tray_snapshot

    app = _BridgeApp(_bridge(True, ever=True))
    fp_connected = _menu_fingerprint(_tray_snapshot(app))

    app._bridge_state = _bridge(False, ever=True, reason="DaVinci Resolve is not running")
    assert _menu_fingerprint(_tray_snapshot(app)) != fp_connected


def test_a_broken_bridge_state_getter_costs_only_the_line():
    from ccsync_companion.tray import _tray_snapshot

    app = _BridgeApp(_bridge(True, ever=True))

    def _boom():
        raise RuntimeError("no")

    app.resolve_bridge_state = _boom
    assert _tray_snapshot(app)["resolve_line"] is None


# -- item 20: the menu swap must never leave a destroyed handle behind ------
#
# pystray's win32 _update_menu DestroyMenu()s the live handle FIRST, rebuilds
# ~30 items, and publishes the new handle last -- so for the whole rebuild
# `_menu_handle` names a destroyed HMENU and a right-click arriving inside it
# gets nothing. It is also called from two threads that know nothing of each
# other (our refresh loop, and pystray's own post-click update_menu() on the
# pump thread), which double-destroys one handle and leaks the other until
# the 10 000-object USER quota kills menus outright.


class _HandleRegistry:
    """Stands in for CreatePopupMenu/DestroyMenu bookkeeping."""

    def __init__(self):
        import threading

        self._lock = threading.Lock()
        self.next_handle = 0
        self.live = set()
        self.destroyed = []
        self.violations = []

    def create(self):
        with self._lock:
            self.next_handle += 1
            self.live.add(self.next_handle)
            return self.next_handle

    def destroy(self, handle, icon):
        current = getattr(icon, "_menu_handle", None)
        if current is not None and current[0] == handle:
            # The handle a concurrent right-click would have picked up.
            self.violations.append(handle)
        with self._lock:
            self.live.discard(handle)
            self.destroyed.append(handle)


class _FakeMenuIcon:
    """A pystray win32 Icon reduced to what _atomic_update_menu touches."""

    def __init__(self, registry):
        self.menu = object()
        self._menu_handle = None
        self._registry = registry
        self.creates = 0
        self.raise_on_create = False
        self.handle_on_create = None   # 0 fakes the exhausted USER-object quota

    def _create_menu(self, menu, callbacks):
        import time

        if self.raise_on_create:
            raise RuntimeError("CreatePopupMenu boom")
        self.creates += 1
        callbacks.append(lambda icon: None)
        time.sleep(0)   # widen the interleaving window for the race below
        if self.handle_on_create is not None:
            return self.handle_on_create
        return self._registry.create()


def _fake_win32_menus(monkeypatch, icon, registry):
    """Point pystray's DestroyMenu at the registry -- win32-only, like the
    backend being patched."""
    import sys

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("pystray win32 backend only")
    from pystray import _win32

    monkeypatch.setattr(_win32.win32, "DestroyMenu",
                        lambda handle: registry.destroy(handle, icon), raising=True)
    return _win32


def test_the_menu_handle_never_names_a_destroyed_menu(monkeypatch):
    import threading

    from ccsync_companion import tray as tray_mod

    registry = _HandleRegistry()
    icon = _FakeMenuIcon(registry)
    _fake_win32_menus(monkeypatch, icon, registry)

    def churn():
        for _ in range(150):
            icon.menu = object()          # a genuinely different menu each time
            tray_mod._atomic_update_menu(icon)

    threads = [threading.Thread(target=churn) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert registry.violations == []
    # Every menu ever created is destroyed except the one still on the icon:
    # the counts balance, so nothing leaks toward the USER quota.
    assert icon._menu_handle is not None
    assert len(registry.destroyed) == icon.creates - 1
    assert registry.live == {icon._menu_handle[0]}


def test_an_unchanged_menu_object_is_not_rebuilt(monkeypatch):
    """pystray calls update_menu() after every left-click and every menu
    selection with the menu untouched -- and our refresh loop only assigns
    icon.menu when the fingerprint really moved."""
    from ccsync_companion import tray as tray_mod

    registry = _HandleRegistry()
    icon = _FakeMenuIcon(registry)
    _fake_win32_menus(monkeypatch, icon, registry)

    tray_mod._atomic_update_menu(icon)
    first = icon._menu_handle
    tray_mod._atomic_update_menu(icon)
    tray_mod._atomic_update_menu(icon)

    assert icon.creates == 1
    assert icon._menu_handle is first
    assert registry.destroyed == []

    icon.menu = object()
    tray_mod._atomic_update_menu(icon)
    assert icon.creates == 2
    assert registry.destroyed == [first[0]]


def test_a_failed_rebuild_leaves_the_old_menu_usable(monkeypatch):
    from ccsync_companion import tray as tray_mod

    registry = _HandleRegistry()
    icon = _FakeMenuIcon(registry)
    _fake_win32_menus(monkeypatch, icon, registry)

    tray_mod._atomic_update_menu(icon)
    good = icon._menu_handle

    icon.menu = object()
    icon.raise_on_create = True
    tray_mod._atomic_update_menu(icon)
    assert icon._menu_handle is good
    assert registry.destroyed == []
    assert good[0] in registry.live

    # ...and the same for the quota case: CreatePopupMenu returning NULL is
    # how the leak used to end, with _menu_handle set to None and right-click
    # dead until a restart.
    icon.raise_on_create = False
    icon.handle_on_create = 0
    tray_mod._atomic_update_menu(icon)
    assert icon._menu_handle is good
    assert registry.destroyed == []

    # An icon whose MENU is falsy is a different thing -- pystray's own
    # _create_menu returns None for one by contract -- and must be published,
    # not warned about forever.
    icon.menu = None
    tray_mod._atomic_update_menu(icon)
    assert icon._menu_handle is None
    assert registry.destroyed == [good[0]]


def test_the_swap_falls_back_to_stock_pystray_when_the_internals_move():
    """Same fail-open posture as _MenuOpenGuard.install: an unrecognised
    pystray costs the fix, never the tray."""
    from ccsync_companion import tray as tray_mod

    class _Alien:
        menu = None

    called = []
    tray_mod._atomic_update_menu(_Alien(), lambda icon: called.append(icon))
    assert len(called) == 1


def test_the_swap_guard_installs_once_over_the_win32_backend(monkeypatch):
    import sys

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("pystray win32 backend only")
    from pystray import _win32

    from ccsync_companion import tray as tray_mod

    stock = _win32.Icon._update_menu
    monkeypatch.setattr(_win32.Icon, "_update_menu", stock, raising=True)
    monkeypatch.setattr(_win32.Icon, "_ccsync_atomic_menu_swap", False, raising=False)

    tray_mod._MenuSwapGuard().install()
    wrapped = _win32.Icon._update_menu
    assert wrapped is not stock

    tray_mod._MenuSwapGuard().install()
    assert _win32.Icon._update_menu is wrapped   # not double-wrapped

    # ...and what got installed is the atomic one: build, publish, destroy.
    registry = _HandleRegistry()
    icon = _FakeMenuIcon(registry)
    monkeypatch.setattr(_win32.win32, "DestroyMenu",
                        lambda handle: registry.destroy(handle, icon), raising=True)
    wrapped(icon)
    assert icon._menu_handle is not None
    assert registry.violations == []


# -- item 20: a right-click that does nothing has to say so -----------------


def test_a_failed_popup_call_is_logged(monkeypatch, caplog):
    """TrackPopupMenuEx is declared with no restype and no errcheck, so a 0
    return -- the handle was destroyed under it, or the USER quota is gone --
    looked exactly like the user pressing Escape: silence."""
    import logging
    import sys

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("pystray win32 backend only")
    from pystray import _win32

    from ccsync_companion import tray as tray_mod

    monkeypatch.setattr(_win32.win32, "TrackPopupMenuEx", lambda *a, **kw: 0, raising=True)
    monkeypatch.setattr(_win32.win32, "_ccsync_menu_open_flag", None, raising=False)
    tray_mod._MenuOpenGuard().install()

    with caplog.at_level(logging.WARNING, logger="ccsync.tray"):
        assert _win32.win32.TrackPopupMenuEx() == 0

    assert any("tray menu failed to open" in r.getMessage() for r in caplog.records)


def test_a_chosen_menu_item_is_not_reported_as_a_failure(monkeypatch, caplog):
    import logging
    import sys

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("pystray win32 backend only")
    from pystray import _win32

    from ccsync_companion import tray as tray_mod

    posted = []
    monkeypatch.setattr(_win32.win32, "TrackPopupMenuEx", lambda *a, **kw: 3, raising=True)
    monkeypatch.setattr(_win32.win32, "PostMessage",
                        lambda *a: posted.append(a), raising=True)
    monkeypatch.setattr(_win32.win32, "_ccsync_menu_open_flag", None, raising=False)
    tray_mod._MenuOpenGuard().install()

    with caplog.at_level(logging.WARNING, logger="ccsync.tray"):
        assert _win32.win32.TrackPopupMenuEx(1, 2, 3, 4, 4242, None) == 3

    assert [r for r in caplog.records if "failed to open" in r.getMessage()] == []
    # MSDN's TrackPopupMenu note, which pystray omits: post WM_NULL to the
    # owner window afterwards, or the menu can refuse to dismiss on the next
    # click.
    assert posted == [(4242, 0x0000, 0, 0)]


def test_pystray_records_reach_the_companion_log(tmp_path):
    """The tray backend logs under "pystray", which had no handler at all --
    and in the windowed build sys.stderr is None, so logging's last resort
    had nowhere to write either."""
    import logging

    from ccsync_companion import app as app_mod

    log_path = tmp_path / "companion.log"
    app_mod.setup_logging({"log_path": str(log_path), "log_level": "INFO"})

    logging.getLogger("pystray").warning("An error occurred in the main loop")
    for handler in logging.getLogger("pystray").handlers:
        handler.flush()

    assert "An error occurred in the main loop" in log_path.read_text(encoding="utf-8")


# -- item 21: the menu that opened behind an auto-hide taskbar --------------
#
# Geometry below is the base rig's: 1920x1080, a 48 px taskbar, and a cursor
# at y=1058 -- inside the bar, where every tray right-click lands.

_TASKBAR_BOTTOM = (0, 1032, 1920, 1080)
_TASKBAR_TOP = (0, 0, 1920, 48)
_TASKBAR_LEFT = (0, 0, 62, 1080)
_TASKBAR_RIGHT = (1858, 0, 1920, 1080)

# What pystray actually passes (pystray/_win32.py:215).
_PYSTRAY_FLAGS = 0x0008 | 0x0020 | 0x0100      # RIGHTALIGN|BOTTOMALIGN|RETURNCMD


def test_an_anchor_inside_the_taskbar_moves_to_its_inner_edge():
    """Table over all four docked positions. The anchor must end up on the
    edge of the bar that faces the desktop, with the alignment that grows the
    menu away from it."""
    from ccsync_companion import tray as tray_mod

    cases = [
        # edge, rect, cursor, expected (x, y), expected alignment bits
        (3, _TASKBAR_BOTTOM, (1700, 1058), (1700, 1032), 0x0008 | 0x0020),  # bottom
        (1, _TASKBAR_TOP, (1700, 22), (1700, 48), 0x0008 | 0x0000),         # top
        (0, _TASKBAR_LEFT, (30, 900), (62, 900), 0x0000 | 0x0020),          # left
        (2, _TASKBAR_RIGHT, (1890, 900), (1858, 900), 0x0008 | 0x0020),     # right
    ]
    for edge, rect, (cx, cy), expected_xy, expected_align in cases:
        x, y, flags = tray_mod._clamp_menu_anchor(cx, cy, _PYSTRAY_FLAGS, rect, edge)
        assert (x, y) == expected_xy, edge
        # only the alignment bits move; RETURNCMD (and anything else the
        # backend asked for) survives
        assert flags & 0x0100, edge
        assert flags & (0x0004 | 0x0008 | 0x0010 | 0x0020) == expected_align, edge


def test_a_top_or_left_taskbar_clears_pystrays_right_bottom_alignment():
    """The bit that an OR cannot express: LEFTALIGN and TOPALIGN are 0, so
    they only exist as the ABSENCE of the others. Left as pystray sent them,
    the menu would be moved off the bar and then drawn straight back over
    it."""
    from ccsync_companion import tray as tray_mod

    _x, _y, flags = tray_mod._clamp_menu_anchor(
        1700, 22, _PYSTRAY_FLAGS, _TASKBAR_TOP, 1)
    assert not flags & 0x0020                      # BOTTOMALIGN gone
    assert not flags & 0x0010                      # and no VCENTER left behind

    _x, _y, flags = tray_mod._clamp_menu_anchor(
        30, 900, _PYSTRAY_FLAGS, _TASKBAR_LEFT, 0)
    assert not flags & 0x0008                      # RIGHTALIGN gone
    assert not flags & 0x0004
    assert flags & 0x0020                          # ...and the other axis intact


def test_an_anchor_outside_the_taskbar_is_left_alone():
    """A click on a second monitor, or anywhere on the desktop: the primary
    taskbar's rect is none of its business."""
    from ccsync_companion import tray as tray_mod

    for point in [(1700, 500), (0, 0), (-1200, 400), (1700, 1031), (1921, 1058)]:
        assert tray_mod._clamp_menu_anchor(
            point[0], point[1], _PYSTRAY_FLAGS, _TASKBAR_BOTTOM, 3
        ) == (point[0], point[1], _PYSTRAY_FLAGS)


def test_an_unknown_taskbar_edge_or_junk_rect_changes_nothing():
    from ccsync_companion import tray as tray_mod

    assert tray_mod._clamp_menu_anchor(
        1700, 1058, _PYSTRAY_FLAGS, _TASKBAR_BOTTOM, 99
    ) == (1700, 1058, _PYSTRAY_FLAGS)
    for rect in [None, (), ("x", "y", "z", "w"), (1, 2, 3)]:
        assert tray_mod._clamp_menu_anchor(
            1700, 1058, _PYSTRAY_FLAGS, rect, 3
        ) == (1700, 1058, _PYSTRAY_FLAGS)


def test_a_failed_geometry_lookup_leaves_the_anchor_untouched(monkeypatch):
    """The whole point of item 20 was a menu that would not open. A
    positioning nicety must never become a new way to do that."""
    from ccsync_companion import tray as tray_mod

    def boom():
        raise OSError("SHAppBarMessage exploded")

    monkeypatch.setattr(tray_mod, "_taskbar_geometry", boom)
    assert tray_mod._anchor_clear_of_taskbar(1700, 1058, _PYSTRAY_FLAGS) == (
        1700, 1058, _PYSTRAY_FLAGS)

    # ...and the same when the shell simply has no answer (no taskbar, or
    # SHAppBarMessage returned 0).
    monkeypatch.setattr(tray_mod, "_taskbar_geometry", lambda: None)
    assert tray_mod._anchor_clear_of_taskbar(1700, 1058, _PYSTRAY_FLAGS) == (
        1700, 1058, _PYSTRAY_FLAGS)


def test_the_popup_wrapper_hands_win32_the_clamped_anchor(monkeypatch):
    """End to end through the installed wrapper: pystray asks for the raw
    cursor position inside the taskbar, user32 is handed the inner edge."""
    import sys

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("pystray win32 backend only")
    from pystray import _win32

    from ccsync_companion import tray as tray_mod

    seen = []
    monkeypatch.setattr(tray_mod, "_taskbar_geometry",
                        lambda: (_TASKBAR_BOTTOM, 3))
    monkeypatch.setattr(_win32.win32, "TrackPopupMenuEx",
                        lambda *a: (seen.append(a), 3)[1], raising=True)
    monkeypatch.setattr(_win32.win32, "PostMessage", lambda *a: None, raising=True)
    monkeypatch.setattr(_win32.win32, "_ccsync_menu_open_flag", None, raising=False)
    tray_mod._MenuOpenGuard().install()

    assert _win32.win32.TrackPopupMenuEx(
        77, _PYSTRAY_FLAGS, 1700, 1058, 4242, None) == 3
    (hmenu, flags, x, y, hwnd, reserved), = seen
    assert (hmenu, hwnd, reserved) == (77, 4242, None)   # everything else intact
    assert (x, y) == (1700, 1032)
    assert flags & 0x0100 and flags & 0x0020

    # A call that carries no coordinates at all (the bare-call tests above,
    # and anything that stops passing them positionally) must still work.
    seen.clear()
    assert _win32.win32.TrackPopupMenuEx() == 3
    assert seen == [()]
