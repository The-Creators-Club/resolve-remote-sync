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
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    assert compute_overall_color(_idle3(), app) == "green"


def test_paused_is_never_green():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.paused = True
    assert compute_overall_color(_idle3(), app) == "orange"


def test_sync_disabled_is_never_green():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app._sync_enabled = False
    assert compute_overall_color(_idle3(), app) == "orange"


def test_sync_disabled_on_the_base_rig_is_green():
    """2026-08-19: the base rig has no lanes BY DESIGN -- its tree is the
    server tree -- so the amber above could never clear on the one machine
    the admin watches all day. The tooltip already said "up to date"."""
    app = _FakeApp({"dashboard_url": "", "mode": "base"},
                   identity=_FakeIdentity("alex"))
    app._sync_enabled = False
    assert compute_overall_color(_idle3(), app) == "green"


def test_a_base_machine_whose_owner_is_not_an_admin_is_still_green():
    """The dashboard derives the sign-in role from its ADMIN list, so an
    office machine wired straight to the NAS is told role="editor" while its
    own config.toml says mode="base" and its lanes never start. The local
    file is what decides here, in the same monotonic direction
    _apply_identity_role() uses."""
    app = _FakeApp({"dashboard_url": "", "mode": "base"},
                   identity=_FakeIdentity("ruskin"))
    app.effective_mode = lambda: "editor"
    app._sync_enabled = False
    assert compute_overall_color(_idle3(), app) == "green"


def test_the_base_role_from_the_dashboard_also_counts():
    """effective_mode() is the same precedence _apply_identity_role() uses:
    a signed-in role="base" makes a machine the base rig even when its
    config.toml never said so."""
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("alex"))
    app.effective_mode = lambda: "base"
    app._sync_enabled = False
    assert compute_overall_color(_idle3(), app) == "green"


def test_the_base_rig_still_goes_red_on_a_lane_error():
    app = _FakeApp({"dashboard_url": "", "mode": "base"},
                   identity=_FakeIdentity("alex"))
    app._sync_enabled = False
    statuses = _idle3() + [_status("lane_c_syncthing", "error")]
    assert compute_overall_color(statuses, app) == "red"


def test_the_base_rig_still_goes_red_when_it_is_not_set_up():
    app = _FakeApp({"dashboard_url": "", "mode": "base"},
                   identity=_FakeIdentity("alex"))
    app._sync_enabled = False
    app.config_problems = ["remote_root is blank -- ..."]
    assert compute_overall_color(_idle3(), app) == "red"


def test_the_base_rig_still_goes_orange_with_its_tree_missing():
    """P: unmapped on the base rig is not "nothing to sync", it is the NAS
    share gone: the watcher, the fixer and Resolve itself are all blind."""
    app = _FakeApp({"dashboard_url": "", "mode": "base"},
                   identity=_FakeIdentity("alex"))
    app._sync_enabled = False
    app._root_absent = True
    assert compute_overall_color(_idle3(), app) == "orange"


def test_config_problems_are_red():
    """DEL-3: lanes no longer start at all in this state, so it must not
    read as anything other than broken."""
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.config_problems = ["remote_root is blank -- ..."]
    assert compute_overall_color(_idle3(), app) == "red"


def test_menu_has_dashboard_link_when_url_configured():
    from ccsync_companion.tray import _build_menu

    menu = _build_menu(_FakeApp({"dashboard_url": "http://192.168.0.10:8480"}))
    assert "Open dashboard" in _menu_labels(menu)


def test_menu_omits_dashboard_link_when_url_blank():
    from ccsync_companion.tray import _build_menu

    menu = _build_menu(_FakeApp({"dashboard_url": ""}))
    assert "Open dashboard" not in _menu_labels(menu)


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
    # The exact prompt, not any sentence with those two words in it: APP-13
    # reworded Quit to "nothing syncs until you start it again", which is
    # true on every machine whatever require_login says.
    assert not any("nothing syncs until you do" in label for label in labels)


def test_tooltip_does_not_claim_nothing_syncs_when_login_is_not_required():
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity(None))
    app._require_login = False
    assert _tooltip_text(_tray_snapshot(app)) == "CCSync: up to date"

    app._require_login = True
    assert "not signed in" in _tooltip_text(_tray_snapshot(app))


def test_menu_shows_identity_only_when_signed_in():
    """Sign out lives in Settings (the approved 2026-08-27 menu); the menu
    keeps the identity line and, when signed out, the one-click prompt."""
    from ccsync_companion.tray import _build_menu

    menu = _build_menu(_FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen")))
    labels = _menu_labels(menu)
    assert "Sign out" not in labels
    assert "Sign in…" not in labels
    assert "Signed in as owen" in labels


def test_identity_status_label_helper():
    from ccsync_companion.tray import _identity_status_label

    assert _identity_status_label(_FakeApp({}, identity=_FakeIdentity(None))) == "NOT SIGNED IN"
    assert _identity_status_label(_FakeApp({}, identity=_FakeIdentity("editor2"))) == "Signed in as editor2"


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


def test_update_item_is_never_adjacent_to_quit():
    """UX-17: `Update available…` sat DIRECTLY above `Quit` -- the one item
    you must never mis-click."""
    from ccsync_companion.tray import _build_menu

    # 99.0.0, not "0.9.9": the label reads "Update available" only for a build
    # NEWER than the running one, and 0.9.9 stopped being that the day the
    # companion became 0.9.41 (two-digit patch, 2026-08-19) -- this test was
    # the one that noticed, on CI, after the local run had passed at 0.9.5.
    labels = _menu_labels(
        _build_menu(_FakeAppWithUpgrade({"dashboard_url": ""}, {"version": "99.0.0"}))
    )
    update_i = next(i for i, la in enumerate(labels) if "Update available" in la)
    quit_i = next(i for i, la in enumerate(labels) if la.startswith("Quit"))
    assert abs(update_i - quit_i) > 1


def test_quit_says_it_stops_syncing():
    """APP-13 (sweep 2026-09-03): the old label promised the wrong way back.
    identity.json persists, so a restarted companion syncs with no sign-in at
    all, and a first-time editor read "until you next sign in" as "Quit will
    log me out"."""
    from ccsync_companion.tray import _build_menu

    labels = _menu_labels(_build_menu(_FakeApp({"dashboard_url": ""})))
    quit_label = next(la for la in labels if la.startswith("Quit"))
    assert "nothing syncs until you start it again" in quit_label
    assert "sign in" not in quit_label.lower()
    # ...and the logon entry the installers write is the other way back.
    assert "log in to this computer again" in quit_label


def test_pause_label_carries_state():
    """UX-2: after clicking Pause the only evidence was a menu checkmark
    most users never register."""
    from ccsync_companion.tray import _build_menu

    app = _FakeApp({"dashboard_url": ""})
    assert "⏸ Pause syncing" in _menu_labels(_build_menu(app))
    app.paused = True
    assert "▶ Resume syncing (currently PAUSED)" in _menu_labels(_build_menu(app))


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
                     last_error="rclone exited 1: dial tcp 100.64.0.1:22: i/o timeout")
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
    assert any("COPY DIAGNOSTICS" in m for m in app.notified)


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

    real_icon = tray_mod.tray_backend.Icon
    try:
        tray_mod.tray_backend.Icon = _FakeIcon
        icon = tray_mod.start_tray(_FakeApp({"dashboard_url": ""}), refresh_interval=0.01)
        icon.stop()
        assert getattr(icon, "_ccsync_stop", False) is True
        assert stopped == [True]
    finally:
        tray_mod.tray_backend.Icon = real_icon


# -- snapshot + fingerprint (the 2026-07-26 right-click freeze) -------------


def test_build_menu_accepts_a_prebuilt_snapshot():
    from ccsync_companion.tray import _build_menu, _tray_snapshot

    app = _FakeApp({"dashboard_url": "http://192.168.0.10:8480"})
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
    app.identity = _FakeIdentity("owen")
    assert _menu_fingerprint(_tray_snapshot(app)) != fp_plain


def test_tooltip_shows_live_numbers_and_states():
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
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


def test_the_menu_open_guard_reads_the_process_wide_flag():
    """The guard no longer INSTALLS anything (2026-08-17): it used to
    monkeypatch pystray's TrackPopupMenuEx to learn when the menu was up.
    tray_native's Icon sets the same Event itself, so all that is left here is
    that the guard reads THE flag -- ui_state.menu_open, the one
    resolve_bridge also defers its GIL-holding calls on."""
    from ccsync_companion import tray as tray_mod
    from ccsync_companion import ui_state

    guard = tray_mod._MenuOpenGuard()
    guard.install()          # a no-op, and must stay callable
    assert guard.flag is ui_state.menu_open

    ui_state.menu_open.clear()
    assert guard.is_open() is False
    ui_state.menu_open.set()
    try:
        assert guard.is_open() is True
    finally:
        ui_state.menu_open.clear()


def test_start_tray_hands_the_backend_the_menu_open_flag():
    """The whole point of the rewrite: the flag reaches the backend as an
    argument instead of through a monkeypatch."""
    from ccsync_companion import tray as tray_mod
    from ccsync_companion import ui_state

    seen = {}

    class _FakeIcon:
        def __init__(self, *a, **k):
            seen.update(k)
            self.icon = None
            self.menu = None

        def stop(self):
            pass

        def run(self):
            pass

    real_icon = tray_mod.tray_backend.Icon
    try:
        tray_mod.tray_backend.Icon = _FakeIcon
        icon = tray_mod.start_tray(_FakeApp({"dashboard_url": ""}), refresh_interval=0.01)
        icon.stop()
    finally:
        tray_mod.tray_backend.Icon = real_icon
    assert seen.get("menu_open_flag") is ui_state.menu_open


def test_start_tray_survives_a_backend_that_has_no_menu_open_flag():
    """CCSYNC_TRAY_BACKEND=pystray (and any test stand-in) knows nothing about
    the keyword; the tray must start anyway, just without the deferral."""
    from ccsync_companion import tray as tray_mod

    class _OldStyleIcon:
        def __init__(self, name, image, title, menu=None):
            self.icon = image
            self.menu = menu

        def stop(self):
            pass

        def run(self):
            pass

    real_icon = tray_mod.tray_backend.Icon
    try:
        tray_mod.tray_backend.Icon = _OldStyleIcon
        icon = tray_mod.start_tray(_FakeApp({"dashboard_url": ""}), refresh_interval=0.01)
        icon.stop()
    finally:
        tray_mod.tray_backend.Icon = real_icon


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


def test_the_snapshot_prefers_the_cached_p_mapping_over_a_probe():
    """COMP-CORE-6: p_mapping_mode() forks `net use P:`, and the snapshot runs
    every 2 s -- so the app's cached read is what the tray must use, and the
    probing one is only the fallback for an app that has none."""
    from ccsync_companion.tray import _tray_snapshot

    probes = []
    app = _FakeApp({"dashboard_url": ""})
    app.p_mapping_mode = lambda: probes.append(1) or "local"
    app.p_mapping_mode_cached = lambda: "server"

    assert _tray_snapshot(app)["p_mode"] == "server"
    assert probes == []

    # An app with only the old accessor still renders (the tray is written to
    # degrade, never to require a newer app object).
    del app.p_mapping_mode_cached
    assert _tray_snapshot(app)["p_mode"] == "local"


def test_the_fingerprint_moves_when_the_stray_lut_count_does():
    """UI-3: the count was gathered and rendered but left OUT of the
    fingerprint, and the refresh loop only reassigns icon.menu when the
    fingerprint changes. An editor drops a LUT into Resolve's own folder on
    an otherwise-idle machine, nothing else moves, and the entire shared-LUT
    onboarding item stays unreachable -- and once share_stray_luts takes the
    count back to 0 the stale item lingers."""
    from ccsync_companion.tray import _build_menu, _menu_fingerprint, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""})
    app.stray_lut_count = lambda: 0
    fp_none = _menu_fingerprint(_tray_snapshot(app))

    app.stray_lut_count = lambda: 3
    snap = _tray_snapshot(app)
    assert any("3 LUTs only on this machine" in l
               for l in _all_menu_labels(_build_menu(app, snap)))
    assert _menu_fingerprint(snap) != fp_none

    # ...and back again, so the item cannot linger after they are shared.
    app.stray_lut_count = lambda: 0
    assert _menu_fingerprint(_tray_snapshot(app)) == fp_none


# -- the sync drive is out (root_guard.py) ----------------------------------


def test_lane_lines_say_the_drive_is_disconnected():
    """An editor whose SSD is unplugged must read "PAUSED (drive
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

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
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

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app._root_absent = True
    labels = _all_menu_labels(_build_menu(app, _tray_snapshot(app)))
    assert any("drive disconnected" in label for label in labels)


def test_the_icon_goes_orange_while_the_drive_is_out():
    """Orange, not red: nothing is broken and nothing is lost -- plugging the
    drive back in resumes sync on its own."""
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app._root_absent = True
    assert compute_overall_color(_idle3(), app) == "orange"


def test_the_tooltip_names_the_drive():
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
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
    monkeypatch.setattr(tray_mod, "_build_credentials_dialog", lambda a: ("owen", "pw"))
    assert tray_mod._ask_server_credentials_locked(app) == ("owen", "pw")


def test_the_icon_runs_on_a_thread_on_windows_and_detached_on_macos(monkeypatch):
    """tray_native's Windows backend owns a message loop of its own and is
    given a daemon thread to run it on. On macOS NSStatusItem is
    main-thread-only, so the icon is installed detached against the runloop
    ui_dispatch.serve() is about to run."""
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

    real_icon = tray_mod.tray_backend.Icon
    try:
        tray_mod.tray_backend.Icon = _FakeIcon

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
        tray_mod.tray_backend.Icon = real_icon


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
    assert "restart the companion" in line


class _BridgeApp(_FakeApp):
    def __init__(self, state):
        super().__init__({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
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


# -- item 20, rewritten: the popup exists only while it is on screen --------
#
# tray_native keeps NO live HMENU (2026-08-17, COMMERCIAL_READINESS.md item 3).
# pystray did, and rebuilt it on every `icon.menu = ...` -- DestroyMenu()
# first, ~30 items, publish the new handle last -- from two threads that knew
# nothing of each other (our refresh loop, and its own post-click
# update_menu() on the pump thread). A right-click landing inside a rebuild
# got a destroyed handle and showed nothing; two interleaving destroyed one
# handle twice and leaked the other, until at the 10 000-object USER quota
# CreatePopupMenu started failing and right-click did nothing at all.
#
# The tests below pin the shape that makes every one of those impossible:
# assignment does no Win32 work, and the handle's entire life is inside one
# call, on one thread.


class _FakeUser32:
    """Only the user32 entry points the popup path touches."""

    def __init__(self, track_result=0, track_error=0, popup_handle=0x99):
        self.track_result = track_result
        self.track_error = track_error
        self.popup_handle = popup_handle
        self.tracked = []
        self.destroyed = []
        self.posted = []
        self.foreground = []

    def SetForegroundWindow(self, hwnd):
        self.foreground.append(hwnd)
        return 1

    def TrackPopupMenuEx(self, hmenu, flags, x, y, hwnd, reserved):
        import ctypes

        self.tracked.append((hmenu, flags, x, y, hwnd, reserved))
        if self.track_error:
            ctypes.set_last_error(self.track_error)
        if callable(self.track_result):
            return self.track_result()
        return self.track_result

    def DestroyMenu(self, handle):
        self.destroyed.append(handle)
        return 1

    def PostMessageW(self, hwnd, msg, wparam, lparam):
        self.posted.append((hwnd, msg, wparam, lparam))
        return 1

    def CreatePopupMenu(self):
        return self.popup_handle


class _FakeApi:
    def __init__(self, user32):
        self.user32 = user32


def _win_icon(monkeypatch, menu, track_result=0, track_error=0, popup=0x99):
    """A _WindowsIcon with user32 and the menu builder replaced.

    Constructible on any platform on purpose: __init__ touches no ctypes, so
    the popup logic is testable without a window, a display or a real HMENU --
    which is what keeps this suite headless (real Tk/Win32 windows opening
    under pytest is a standing hazard in this repo).
    """
    from ccsync_companion import tray_native

    user32 = _FakeUser32(track_result, track_error)
    monkeypatch.setattr(tray_native._Win32, "get",
                        classmethod(lambda cls: _FakeApi(user32)))
    icon = tray_native._WindowsIcon("test", None, "", menu=menu)
    icon._hwnd = 4242
    icon._added = True
    monkeypatch.setattr(icon, "_menu_anchor", lambda: (1700, 1032, 0x0128))

    def _build(source, callbacks):
        for index, item in enumerate(source.rendered()):
            if item.action is not None and item.submenu is None:
                callbacks[1000 + index] = item
        return popup

    monkeypatch.setattr(icon, "_build_popup", _build)
    return icon, user32


def _clicky_menu(fired):
    from ccsync_companion import tray_native

    return tray_native.Menu(
        tray_native.MenuItem("Header", None, enabled=False),
        tray_native.Menu.SEPARATOR,
        tray_native.MenuItem("Do it", lambda icon, item: fired.append(item.label())),
    )


def test_the_popup_handle_dies_with_the_popup(monkeypatch):
    import sys

    import pytest as _pytest

    if sys.platform != "win32":
        # _show_menu() itself calls the real ctypes.set_last_error/
        # get_last_error, which only exist when ctypes.__init__ is built for
        # win32 -- on any other host this is an AttributeError, not a
        # behaviour difference to paper over (macOS CI, 2026-08-17).
        _pytest.skip("_show_menu() is Win32-only")
    icon, user32 = _win_icon(monkeypatch, _clicky_menu([]))
    icon._show_menu()

    assert user32.foreground == [4242]              # MSDN's first requirement
    assert [call[0] for call in user32.tracked] == [0x99]
    assert user32.destroyed == [0x99]               # ...and it is gone again
    # MSDN's second: post WM_NULL to the owner or the menu can refuse to
    # dismiss on the following click.
    assert user32.posted == [(4242, 0x0000, 0, 0)]


def test_assigning_the_menu_does_no_win32_work(monkeypatch):
    """The assignment that used to DestroyMenu() a live handle."""
    from ccsync_companion import tray_native

    icon, user32 = _win_icon(monkeypatch, _clicky_menu([]))
    for _ in range(50):
        icon.menu = tray_native.Menu(tray_native.MenuItem("x", None))
    assert user32.destroyed == [] and user32.tracked == []


def test_the_menu_open_flag_is_set_only_while_the_popup_is_up(monkeypatch):
    import sys
    import threading

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("_show_menu() is Win32-only")  # see the comment above

    flag = threading.Event()
    seen = {}
    icon, user32 = _win_icon(monkeypatch, _clicky_menu([]))
    icon._menu_open = flag
    user32.track_result = lambda: seen.setdefault("during", flag.is_set()) and 0

    assert flag.is_set() is False
    icon._show_menu()
    assert seen["during"] is True
    assert flag.is_set() is False


def test_the_flag_clears_and_the_handle_dies_even_if_the_popup_raises(monkeypatch):
    import sys
    import threading

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("_show_menu() is Win32-only")  # see test_the_popup_handle...

    flag = threading.Event()

    def _boom():
        raise RuntimeError("user32 said no")

    icon, user32 = _win_icon(monkeypatch, _clicky_menu([]))
    icon._menu_open = flag
    user32.track_result = _boom

    with _pytest.raises(RuntimeError):
        icon._show_menu()
    assert flag.is_set() is False
    assert user32.destroyed == [0x99]


def test_a_failed_popup_call_is_logged(caplog):
    """TrackPopupMenuEx returns 0 for BOTH "the user pressed Escape" and "the
    call failed", and a right-click that does nothing is the single
    most-reported tray symptom. GetLastError is what separates them."""
    import logging
    import sys

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("_show_menu() is Win32-only")  # see test_the_popup_handle...

    monkeypatch = _pytest.MonkeyPatch()
    try:
        icon, _user32 = _win_icon(monkeypatch, _clicky_menu([]), track_error=1400)
        with caplog.at_level(logging.WARNING, logger="ccsync.tray.native"):
            icon._show_menu()
    finally:
        monkeypatch.undo()
    assert any("failed to open" in r.getMessage() for r in caplog.records)
    assert any("1400" in r.getMessage() for r in caplog.records)


def test_a_dismissed_popup_is_not_reported_as_a_failure(caplog, monkeypatch):
    import ctypes
    import logging
    import sys

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("_show_menu() is Win32-only")  # see test_the_popup_handle...

    ctypes.set_last_error(0)
    icon, _user32 = _win_icon(monkeypatch, _clicky_menu([]))
    with caplog.at_level(logging.WARNING, logger="ccsync.tray.native"):
        icon._show_menu()
    assert [r for r in caplog.records if "failed to open" in r.getMessage()] == []


def test_a_chosen_item_runs_its_action(monkeypatch):
    import sys

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("_show_menu() is Win32-only")  # see test_the_popup_handle...

    fired: list = []
    menu = _clicky_menu(fired)
    icon, user32 = _win_icon(monkeypatch, menu, track_result=1002)
    icon._show_menu()
    assert fired == ["Do it"]


def test_an_action_that_raises_does_not_kill_the_message_pump(monkeypatch, caplog):
    import logging
    import sys

    import pytest as _pytest

    from ccsync_companion import tray_native

    if sys.platform != "win32":
        _pytest.skip("_show_menu() is Win32-only")  # see test_the_popup_handle...

    def _boom(icon, item):
        raise RuntimeError("nope")

    menu = tray_native.Menu(tray_native.MenuItem("Explode", _boom))
    icon, _user32 = _win_icon(monkeypatch, menu, track_result=1000)
    with caplog.at_level(logging.ERROR, logger="ccsync.tray.native"):
        icon._show_menu()          # must return, not propagate
    assert any("Explode" in r.getMessage() for r in caplog.records)


def test_a_menu_that_cannot_be_created_is_logged_not_raised(monkeypatch, caplog):
    """CreatePopupMenu returning NULL is the USER-object quota. The old code
    published that as the live handle and right-click went dead until the
    companion was restarted."""
    import logging
    import sys

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("_show_menu() is Win32-only")  # see test_the_popup_handle...

    icon, user32 = _win_icon(monkeypatch, _clicky_menu([]), popup=0)
    with caplog.at_level(logging.WARNING, logger="ccsync.tray.native"):
        icon._show_menu()
    assert user32.tracked == [] and user32.destroyed == []
    assert any("could not be created" in r.getMessage() for r in caplog.records)


def test_an_empty_menu_shows_nothing_at_all(monkeypatch):
    from ccsync_companion import tray_native

    icon, user32 = _win_icon(monkeypatch, tray_native.Menu())
    icon.menu = None
    icon._show_menu()
    assert user32.tracked == []


# -- the menu model itself (pure, no OS) ------------------------------------


def test_rendered_collapses_the_separators_conditional_sections_leave_behind():
    """Half of _build_menu's sections are conditional and carry their own
    trailing separator, so on a quiet machine the raw list is a run of
    them -- and a menu that opens with a horizontal rule looks broken."""
    from ccsync_companion.tray_native import Menu, MenuItem

    menu = Menu(
        Menu.SEPARATOR,
        MenuItem("one", None),
        Menu.SEPARATOR,
        Menu.SEPARATOR,
        MenuItem("two", None),
        Menu.SEPARATOR,
    )
    assert [i.label() for i in menu.rendered()] == ["one", "- - - -", "two"]
    # ...and the raw list is untouched, because _menu_fingerprint reads it.
    assert len(menu.items) == 6


def test_rendered_drops_invisible_items():
    from ccsync_companion.tray_native import Menu, MenuItem

    menu = Menu(MenuItem("shown", None), MenuItem("hidden", None, visible=False))
    assert [i.label() for i in menu.rendered()] == ["shown"]


def test_a_checked_callable_is_resolved_per_render():
    from ccsync_companion.tray_native import MenuItem

    paused = {"value": False}
    item = MenuItem("Pause", None, checked=lambda i: paused["value"])
    assert item.is_checked() is False
    paused["value"] = True
    assert item.is_checked() is True

    # None is not False: an item with no `checked` is not a checkbox at all.
    assert MenuItem("plain", None).is_checked() is None


def test_a_raising_checked_callable_does_not_take_the_menu_down():
    from ccsync_companion.tray_native import MenuItem

    def _boom(item):
        raise RuntimeError("nope")

    assert MenuItem("x", None, checked=_boom).is_checked() is False


def test_a_menu_as_the_action_is_a_submenu():
    from ccsync_companion.tray_native import Menu, MenuItem

    inner = Menu(MenuItem("nested", None))
    item = MenuItem("Advanced", inner)
    assert item.submenu is inner
    assert item.action is None


def test_an_item_is_callable_like_the_old_backends():
    """_build_menu's handlers are (icon, item) callables and the tests reach
    them by calling the item, which is the shape pystray had."""
    from ccsync_companion.tray_native import MenuItem

    seen = []
    item = MenuItem("go", lambda icon, it: seen.append((icon, it.label())))
    item(None)
    assert seen == [(None, "go")]


def test_ampersands_and_tabs_do_not_become_windows_mnemonics():
    """'&' introduces a mnemonic and swallows itself; a tab starts the
    accelerator column. Both turn up in editor-facing strings by accident."""
    from ccsync_companion.tray_native import _escape_menu_label

    assert _escape_menu_label("audio & graphics") == "audio && graphics"
    assert "\t" not in _escape_menu_label("a\tb")


def test_the_notify_icon_structs_are_the_sizes_windows_validates():
    """Shell_NotifyIcon rejects a NOTIFYICONDATAW whose cbSize is not one it
    knows, and the only symptom is a tray icon that never appears."""
    import sys

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("Windows structs")
    from ccsync_companion.tray_native import _check_struct_sizes

    assert _check_struct_sizes() == []


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

# What tray_native._menu_anchor() starts from (and pystray passed before it).
_ANCHOR_FLAGS = 0x0008 | 0x0020 | 0x0100      # RIGHTALIGN|BOTTOMALIGN|RETURNCMD


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
        x, y, flags = tray_mod._clamp_menu_anchor(cx, cy, _ANCHOR_FLAGS, rect, edge)
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
        1700, 22, _ANCHOR_FLAGS, _TASKBAR_TOP, 1)
    assert not flags & 0x0020                      # BOTTOMALIGN gone
    assert not flags & 0x0010                      # and no VCENTER left behind

    _x, _y, flags = tray_mod._clamp_menu_anchor(
        30, 900, _ANCHOR_FLAGS, _TASKBAR_LEFT, 0)
    assert not flags & 0x0008                      # RIGHTALIGN gone
    assert not flags & 0x0004
    assert flags & 0x0020                          # ...and the other axis intact


def test_an_anchor_outside_the_taskbar_is_left_alone():
    """A click on a second monitor, or anywhere on the desktop: the primary
    taskbar's rect is none of its business."""
    from ccsync_companion import tray as tray_mod

    for point in [(1700, 500), (0, 0), (-1200, 400), (1700, 1031), (1921, 1058)]:
        assert tray_mod._clamp_menu_anchor(
            point[0], point[1], _ANCHOR_FLAGS, _TASKBAR_BOTTOM, 3
        ) == (point[0], point[1], _ANCHOR_FLAGS)


def test_an_unknown_taskbar_edge_or_junk_rect_changes_nothing():
    from ccsync_companion import tray as tray_mod

    assert tray_mod._clamp_menu_anchor(
        1700, 1058, _ANCHOR_FLAGS, _TASKBAR_BOTTOM, 99
    ) == (1700, 1058, _ANCHOR_FLAGS)
    for rect in [None, (), ("x", "y", "z", "w"), (1, 2, 3)]:
        assert tray_mod._clamp_menu_anchor(
            1700, 1058, _ANCHOR_FLAGS, rect, 3
        ) == (1700, 1058, _ANCHOR_FLAGS)


def test_a_failed_geometry_lookup_leaves_the_anchor_untouched(monkeypatch):
    """The whole point of item 20 was a menu that would not open. A
    positioning nicety must never become a new way to do that."""
    from ccsync_companion import tray as tray_mod
    # The function lives in tray_native and reads ITS OWN _taskbar_geometry;
    # patching tray's re-export was inert, so this test's outcome depended on
    # the live taskbar of whoever ran it (2026-08-18).
    from ccsync_companion import tray_native as tray_native_mod

    def boom():
        raise OSError("SHAppBarMessage exploded")

    monkeypatch.setattr(tray_native_mod, "_taskbar_geometry", boom)
    assert tray_mod._anchor_clear_of_taskbar(1700, 1058, _ANCHOR_FLAGS) == (
        1700, 1058, _ANCHOR_FLAGS)

    # ...and the same when the shell simply has no answer (no taskbar, or
    # SHAppBarMessage returned 0).
    monkeypatch.setattr(tray_native_mod, "_taskbar_geometry", lambda: None)
    assert tray_mod._anchor_clear_of_taskbar(1700, 1058, _ANCHOR_FLAGS) == (
        1700, 1058, _ANCHOR_FLAGS)


def test_the_popup_is_anchored_clear_of_the_taskbar(monkeypatch):
    """End to end through tray_native._menu_anchor: the raw cursor position is
    inside the taskbar (where every tray right-click lands) and user32 is
    handed the bar's inner edge instead."""
    import sys

    import pytest as _pytest

    if sys.platform != "win32":
        _pytest.skip("wintypes.POINT is Windows-only")
    from ccsync_companion import tray_native

    monkeypatch.setattr(tray_native, "_taskbar_geometry",
                        lambda: (_TASKBAR_BOTTOM, 3))

    class _CursorUser32(_FakeUser32):
        def GetCursorPos(self, point):
            point._obj.x, point._obj.y = 1700, 1058
            return 1

    user32 = _CursorUser32()
    monkeypatch.setattr(tray_native._Win32, "get",
                        classmethod(lambda cls: _FakeApi(user32)))
    icon = tray_native._WindowsIcon("test", None, "")
    x, y, flags = icon._menu_anchor()

    assert (x, y) == (1700, 1032)                 # the bar's inner edge
    assert flags & 0x0100                          # TPM_RETURNCMD
    assert flags & 0x0020                          # TPM_BOTTOMALIGN


# ===========================================================================
# 2026-08-10: the product mark, and what a pulse is allowed to mean
# ===========================================================================
#
# The icon used to draw two chevrons in the status color. It now draws the CC
# mark alone, tinted, on transparency -- and it BREATHES, but only for the two
# states worth interrupting someone for: work in flight (amber + a syncing
# lane) and something broken (red). Every other amber -- paused, signed out,
# drive unplugged, sync disabled, not set up -- is steady, and green never
# moves at all.


def _syncing3():
    return [_status("lane_a_video_up", "syncing"), _status("lane_b_proxy_down", "idle"),
            _status("lane_c_syncthing", "idle")]


def test_red_pulses_and_so_does_amber_with_a_lane_in_flight():
    from ccsync_companion.tray import should_pulse

    assert should_pulse("red", _idle3()) is True
    assert should_pulse("red", _syncing3()) is True
    assert should_pulse("orange", _syncing3()) is True


def test_a_state_the_editor_is_simply_in_does_not_pulse():
    """Paused, signed out, drive out, sync disabled: all amber, none of them
    "work is happening or something is broken", so none of them moves."""
    from ccsync_companion.tray import should_pulse

    assert should_pulse("orange", _idle3()) is False
    assert should_pulse("orange", []) is False


def test_green_never_pulses():
    """Green already carries the strictest promise in the product (AUDIT_2
    UX-1). A breathing green would read as "…working on it", which is the one
    thing it must never say."""
    from ccsync_companion.tray import should_pulse

    assert should_pulse("green", _idle3()) is False
    assert should_pulse("green", _syncing3()) is False


def test_the_snapshot_carries_the_pulse_flag_for_each_state():
    """The truth table as the tray actually computes it -- through the app,
    not by handing should_pulse() a color by hand."""
    from ccsync_companion.tray import _tray_snapshot

    def snap_for(app):
        snap = _tray_snapshot(app)
        return snap["color"], snap["pulse"]

    signed_in = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    assert snap_for(signed_in) == ("green", False)

    syncing = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    syncing.lane_statuses = _syncing3
    assert snap_for(syncing) == ("orange", True)

    paused = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    paused.paused = True
    assert snap_for(paused) == ("orange", False)

    signed_out = _FakeApp({"dashboard_url": ""})
    assert snap_for(signed_out) == ("orange", False)

    drive_out = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    drive_out._root_absent = True
    assert snap_for(drive_out) == ("orange", False)

    disabled = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    disabled._sync_enabled = False
    assert snap_for(disabled) == ("orange", False)

    broken = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    broken.lane_statuses = lambda: [_status("lane_a_video_up", "error")]
    assert snap_for(broken) == ("red", True)

    misconfigured = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    misconfigured.config_problems = ["remote_root is blank -- ..."]
    assert snap_for(misconfigured) == ("red", True)


def test_every_pulse_frame_is_rendered_at_most_once():
    """The cache is not an optimisation here, it is the design: without it a
    breath would rebuild eight 64x64 images -- and eight win32 HICONs -- every
    three seconds for as long as the companion runs."""
    from ccsync_companion.tray import PULSE_LEVELS, _icon_image_cached, _pulse_frames

    dim = _icon_image_cached("orange", 0.35)
    assert _icon_image_cached("orange", 0.35) is dim          # same object again
    assert _icon_image_cached("orange") is not dim            # ...but not the steady one
    assert _icon_image_cached("red", 0.35) is not dim         # ...nor another color's

    frames = _pulse_frames("red")
    assert len(frames) == len(PULSE_LEVELS)
    # A second cycle must allocate nothing: identical objects, in order.
    assert all(a is b for a, b in zip(frames, _pulse_frames("red")))


def test_two_threads_reaching_for_a_new_frame_get_the_same_one():
    """The refresh loop and the pulse ticker both grab a color's frames the
    first time it appears. Without setdefault one of them walks away with an
    image the cache does not hold -- so its icon never compares identical to
    the cached frame again, and every later miss renders twice."""
    import threading

    from ccsync_companion.tray import _ICON_IMAGE_CACHE, _icon_image_cached

    _ICON_IMAGE_CACHE.pop(("red", 0.675), None)   # force a miss on both threads
    got: list = []
    ready = threading.Barrier(4)

    def _grab():
        ready.wait()
        got.append(_icon_image_cached("red", 0.675))

    threads = [threading.Thread(target=_grab) for _ in range(3)]
    for thread in threads:
        thread.start()
    ready.wait()
    for thread in threads:
        thread.join(5.0)

    assert len(got) == 3
    assert all(image is got[0] for image in got)
    assert _ICON_IMAGE_CACHE[("red", 0.675)] is got[0]


def test_a_dimmer_level_dims_the_tint_and_never_the_silhouette():
    from ccsync_companion.tray import _make_icon_image

    bright = _make_icon_image("orange")
    dim = _make_icon_image("orange", 0.45)

    assert bright.getchannel("G").getextrema()[1] > dim.getchannel("G").getextrema()[1]
    # There is no tile and no border (2026-08-10): the alpha channel IS the
    # mark, and it must not move during a breath -- a pulsing icon reads as
    # the same shape getting quieter, never as a shape flickering in and out.
    assert bright.getchannel("A").tobytes() == dim.getchannel("A").tobytes()


def test_the_mark_is_what_gets_drawn_when_the_asset_is_there(monkeypatch):
    """Proof the compositing actually happens, rather than the chevron path
    quietly still running."""
    from ccsync_companion import theme
    from ccsync_companion import tray as tray_mod

    assert theme.asset_path(tray_mod.MARK_ASSET) is not None
    with_mark = tray_mod._make_icon_image("green")
    assert with_mark.size == (64, 64)

    monkeypatch.setattr(tray_mod, "_mark_asset_path", lambda: None)
    assert with_mark.tobytes() != tray_mod._make_icon_image("green").tobytes()


def test_a_missing_mark_asset_falls_back_to_the_chevrons(tmp_path, monkeypatch):
    """An old frozen build (published before cc_mark_white.png was in
    build.spec's datas) and a stripped checkout both land here. The icon is
    decoration; the tray has to come up either way."""
    from ccsync_companion import tray as tray_mod

    monkeypatch.setattr(tray_mod, "_mark_asset_path", lambda: None)
    no_asset = tray_mod._make_icon_image("green")
    assert no_asset.size == (64, 64)

    # ...and the same when a path IS reported but there is no file on it.
    monkeypatch.setattr(tray_mod, "_mark_asset_path", lambda: tmp_path / "gone.png")
    unreadable = tray_mod._make_icon_image("green")
    assert unreadable.tobytes() == no_asset.tobytes()

    # the pulse still works, it just breathes the chevrons
    assert (no_asset.getchannel("G").getextrema()[1]
            > tray_mod._make_icon_image("green", 0.35).getchannel("G").getextrema()[1])


def test_the_frozen_build_ships_the_mark():
    """theme.asset_path() reads assets out of sys._MEIPASS at a path
    build.spec's datas has to produce. Nothing at runtime can tell you it
    doesn't -- a frozen build missing the file just reverts to chevrons, which
    is exactly why that fallback is silent."""
    from pathlib import Path

    spec = (Path(__file__).resolve().parent.parent / "build.spec").read_text(
        encoding="utf-8")
    assert "src/ccsync_companion/assets/ccsync_mark.png" in spec
    # Still shipped so a fleet already wearing it can select it with
    # CCSYNC_BRAND_LOGO instead of having its tray change on upgrade
    # (2026-08-17, COMMERCIAL_READINESS.md item 10).
    assert "src/ccsync_companion/assets/cc_mark_white.png" in spec
    assert "src/ccsync_companion/assets/icon.png" in spec
    assert '"ccsync_companion/assets"' in spec


def test_asset_path_answers_none_instead_of_raising():
    from ccsync_companion import theme

    assert theme.asset_path("icon.png") == theme.icon_path()
    assert theme.asset_path("no-such-asset.png") is None


def test_the_pulse_animates_only_while_the_snapshot_says_so():
    """The two loops in start_tray must not fight over icon.icon: the pulse
    owns it while breathing, the refresh loop owns it when steady, and a
    steady icon costs zero assignments (this sits in a taskbar all day)."""
    import time

    import ccsync_companion.tray as tray_mod

    class _FakeIcon:
        def __init__(self, *a, **k):
            object.__setattr__(self, "assignments", [])
            self.icon = a[1] if len(a) > 1 else None
            self.title = a[2] if len(a) > 2 else ""
            self.menu = k.get("menu")

        def __setattr__(self, name, value):
            if name == "icon":
                self.assignments.append(value)
            object.__setattr__(self, name, value)

        def stop(self):
            pass

        def run(self):
            pass

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.lane_statuses = _syncing3

    real_icon = tray_mod.tray_backend.Icon
    try:
        tray_mod.tray_backend.Icon = _FakeIcon
        icon = tray_mod.start_tray(app, refresh_interval=0.01, pulse_interval=0.01)
        try:
            deadline = time.monotonic() + 5.0
            while (len({id(i) for i in icon.assignments}) < 3
                   and time.monotonic() < deadline):
                time.sleep(0.01)
            assert len({id(i) for i in icon.assignments}) >= 3, "the mark never moved"

            # Everything it painted is a cached frame of the amber breath.
            amber = {id(f) for f in tray_mod._pulse_frames("orange")}
            assert {id(i) for i in icon.assignments[1:]} <= amber

            # Caught up: steady green, and then nothing at all.
            app.lane_statuses = lambda: [_status("lane_a_video_up", "idle")]
            steady = tray_mod._icon_image_cached("green")
            deadline = time.monotonic() + 5.0
            while icon.icon is not steady and time.monotonic() < deadline:
                time.sleep(0.01)
            assert icon.icon is steady
            time.sleep(0.1)                      # let the falling edge settle
            quiet = len(icon.assignments)
            time.sleep(0.2)                      # ~20 pulse ticks
            assert len(icon.assignments) == quiet
        finally:
            icon.stop()
    finally:
        tray_mod.tray_backend.Icon = real_icon


def test_the_falling_edge_frame_waits_for_the_menu_to_close(monkeypatch):
    """UI-4: the guard covers the pulsing branch AND the falling-edge restore.

    A NIM_MODIFY under an open menu forces a redraw beneath the cursor (the
    2026-07-26 hover hangs), so no tick of this loop may write while the menu
    is up. The falling-edge write skipped the check, leaving a one-shot
    window one pulse interval wide.

    The guard here answers the two loops differently ON PURPOSE: that is the
    live race, not a contrivance -- the refresh loop publishes the no-longer-
    pulsing state, THEN the menu opens, THEN the pulse thread wakes up. The
    refresh loop, which re-checks the guard itself, would otherwise freeze
    `pulse_state` and the falling edge could never be reached at all.
    """
    import threading
    import time

    import ccsync_companion.tray as tray_mod

    class _FakeIcon:
        def __init__(self, *a, **k):
            object.__setattr__(self, "assignments", [])
            self.icon = a[1] if len(a) > 1 else None
            self.title = a[2] if len(a) > 2 else ""
            self.menu = k.get("menu")

        def __setattr__(self, name, value):
            if name == "icon":
                self.assignments.append(value)
            object.__setattr__(self, name, value)

        def stop(self):
            pass

        def run(self):
            pass

    menu_open = threading.Event()
    refresh_thread: list = [None]
    main_thread = threading.current_thread()

    class _FakeGuard:
        def install(self):
            pass

        def is_open(self):
            if threading.current_thread() is refresh_thread[0]:
                return False
            return menu_open.is_set()

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    statuses = [_syncing3()]

    def _lane_statuses():
        # _tray_snapshot's caller identifies itself here (start_tray takes the
        # first snapshot on this thread).
        if threading.current_thread() is not main_thread:
            refresh_thread[0] = threading.current_thread()
        return statuses[0]

    app.lane_statuses = _lane_statuses

    monkeypatch.setattr(tray_mod, "_MenuOpenGuard", _FakeGuard)
    real_icon = tray_mod.tray_backend.Icon
    try:
        tray_mod.tray_backend.Icon = _FakeIcon
        icon = tray_mod.start_tray(app, refresh_interval=0.01, pulse_interval=0.02)
        try:
            deadline = time.monotonic() + 5.0
            while len(icon.assignments) < 3 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert len(icon.assignments) >= 3, "the mark never breathed"

            # The menu goes up while the pulse is still running: from here on
            # the pulse thread must not touch the icon at all.
            menu_open.set()
            time.sleep(0.1)
            base = len(icon.assignments)

            # ...and NOW the state stops pulsing. The refresh loop restores
            # the steady frame (exactly one write, its own); the pulse loop's
            # falling-edge restore has to wait.
            statuses[0] = [_status("lane_a_video_up", "idle")]
            steady = tray_mod._icon_image_cached("green")
            deadline = time.monotonic() + 5.0
            while icon.icon is not steady and time.monotonic() < deadline:
                time.sleep(0.005)
            assert icon.icon is steady
            time.sleep(0.2)                      # ~10 pulse ticks
            assert len(icon.assignments) - base == 1, (
                "the pulse loop wrote icon.icon under an open menu")

            # The write is deferred, not dropped: the menu closes and the
            # restoring frame lands on the next tick.
            menu_open.clear()
            deadline = time.monotonic() + 5.0
            while len(icon.assignments) - base < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            assert len(icon.assignments) - base == 2
            assert icon.assignments[-1] is steady
        finally:
            icon.stop()
    finally:
        tray_mod.tray_backend.Icon = real_icon


# -- missing proxies: advisory lines only (proxy_gen.py) --------------------
#
# NO new icon colour and NO pulse in any of these: an original with no proxy
# is not a fault, it is footage the rest of the fleet cannot see yet
# (tray.py:78-85's stance on what the mark is allowed to mean).


def _proxy_app(missing=0, braw=0, left=0, encoding=False, can_generate=True,
               made=0, failed=0, src_bytes=0, proxy_bytes=0, eta=None,
               detail=None, last_at=""):
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.proxy_gap = lambda: {
        "missing": missing, "braw": braw, "left": left, "encoding": encoding,
        "can_generate": can_generate, "state": "running" if encoding else "user-active",
        "encoding_detail": detail or [],
        "history": {
            "today": {"done": made, "failed": failed,
                      "src_bytes": src_bytes, "proxy_bytes": proxy_bytes},
            "lifetime": {"done": made, "failed": failed},
            "eta_seconds": eta,
            "last_at": last_at or ("2026-08-17T02:59:05+00:00" if made else ""),
        },
    }
    return app


def test_no_proxy_lines_at_all_when_there_is_no_gap():
    """No ADVISORY line: nothing is missing, nothing is encoding and nothing
    was made today, so there is nothing to say. The "Proxies this machine has
    made…" action is not one of these -- it is an action, it lives under
    Advanced, and it is deliberately offered when the gap is zero (that is
    exactly when "what did it do overnight?" gets asked)."""
    from ccsync_companion.tray import _build_menu, _tray_snapshot

    app = _proxy_app()
    labels = [
        label for label in _all_menu_labels(_build_menu(app, _tray_snapshot(app)))
        if label != "Proxies this machine has made…"
    ]
    assert not any("proxy" in label.lower() or "proxies" in label.lower()
                   for label in labels)


# -- what this machine has MADE (proxy_history.py) --------------------------
#
# The ledger's numbers, on the same split as everything else here: coarse
# enough for the menu, live in the tooltip.


# -- the live percentage lives in the TOOLTIP, never the menu ---------------


def test_the_tooltip_shows_the_leading_clip_percentage():
    """One number, not four: the drain runs up to 4 wide, the tooltip has
    ~120 characters for everything, and "the next one lands soon" is what an
    editor watching this wants to know."""
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _proxy_app(missing=300, left=214, encoding=True, detail=[
        {"name": "a.mp4", "percent": 12, "eta_seconds": 400.0},
        {"name": "b.mp4", "percent": 62, "eta_seconds": 200.0},
    ])
    assert "next at 62%" in _tooltip_text(_tray_snapshot(app))


def test_the_tooltip_omits_a_percentage_it_cannot_measure():
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _proxy_app(missing=300, left=214, encoding=True, detail=[
        {"name": "a.mp4", "percent": None, "eta_seconds": None},
    ])
    text = _tooltip_text(_tray_snapshot(app))
    assert "making 214 proxy file(s)" in text and "next at" not in text


def test_the_percentage_never_reaches_the_menu_fingerprint():
    """It changes every second. Hashing it would rebuild the menu every
    second, which is the freeze this whole split exists to avoid."""
    from ccsync_companion.tray import _menu_fingerprint, _tray_snapshot

    def _fp(percent):
        return _menu_fingerprint(_tray_snapshot(_proxy_app(
            missing=300, left=214, encoding=True,
            detail=[{"name": "a.mp4", "percent": percent, "eta_seconds": 1.0}])))

    assert _fp(1) == _fp(2) == _fp(99)


def test_the_tooltip_carries_the_live_number():
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _proxy_app(missing=12)
    assert _tooltip_text(_tray_snapshot(app)) == "CCSync: up to date · 12 need proxies"

    app = _proxy_app(missing=1)
    assert "1 needs a proxy" in _tooltip_text(_tray_snapshot(app))

    app = _proxy_app(missing=12, left=9, encoding=True)
    assert "making 9 proxy file(s)" in _tooltip_text(_tray_snapshot(app))


def test_the_tooltip_suffix_yields_to_everything_louder():
    """Not set up / drive gone / not signed in / paused are states where
    NOTHING syncs; burying that sentence under a proxy count would be the
    tooltip's one job done backwards."""
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _proxy_app(missing=12)
    app._root_absent = True
    # SYNC-104/105 (sweep 2026-09-04): the tooltip says which of the three
    # ways the drive is gone, in the same words as the tray line.
    assert _tooltip_text(_tray_snapshot(app)) == "CCSync: PAUSED (drive disconnected)"

    app = _proxy_app(missing=12)
    app.paused = True
    assert _tooltip_text(_tray_snapshot(app)) == "CCSync: PAUSED"

    app = _proxy_app(missing=12)
    app.config_problems = ["remote is blank"]
    assert "NOT SET UP" in _tooltip_text(_tray_snapshot(app))


def test_the_tooltip_suffix_is_dropped_rather_than_truncated():
    """Windows cuts a tooltip at ~127 chars, and a half-eaten
    "· 12 need pro" reads like a bug. This line is the least important
    thing the tooltip can say, so it is the first thing dropped."""
    from ccsync_companion.tray import TOOLTIP_LIMIT, _tooltip_text, _tray_snapshot
    from ccsync_companion.tray import _with_proxy_suffix

    snap = {"proxy_gap": {"missing": 12}}
    # The guard, exercised directly: today's longest rendered tooltip (a
    # syncing lane with a 40-char project, a speed and an ETA) lands around
    # 100 characters, so this is the promise that a future line cannot
    # quietly break it.
    crowded = "CCSync: syncing · " + ("x" * (TOOLTIP_LIMIT - 20))
    assert _with_proxy_suffix(crowded, snap) == crowded

    # ...and a real syncing tooltip does have room, and stays inside the cap.
    app = _proxy_app(missing=12)
    app.lane_statuses = lambda: [LaneStatus(
        name="lane_a_video_up", state="syncing",
        current_project="2026/CCT/Website Highlights",
        speed_bps=12_500_000, eta_seconds=3600,
    )]
    tip = _tooltip_text(_tray_snapshot(app))
    assert "12 need proxies" in tip
    assert len(tip) <= TOOLTIP_LIMIT


def test_a_proxy_getter_that_raises_degrades_to_no_lines():
    """Every snapshot getter is wrapped: one failing must cost its own line,
    never the whole menu (2026-07-26's right-click freeze)."""
    from ccsync_companion.tray import _build_menu, _tooltip_text, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))

    def _boom():
        raise RuntimeError("the generator is on fire")

    app.proxy_gap = _boom
    snap = _tray_snapshot(app)
    assert snap["proxy_gap"] == {}
    assert _tooltip_text(snap) == "CCSync: up to date"
    labels = _all_menu_labels(_build_menu(app, snap))
    assert "Sync now" in labels


def test_a_companion_with_no_generator_at_all_renders_normally():
    """proxy_gap() returns {} when the generator failed to construct."""
    from ccsync_companion.tray import _build_menu, _menu_fingerprint, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    snap = _tray_snapshot(app)
    assert snap["proxy_gap"] == {}
    assert _menu_fingerprint(snap)  # no exception, and no proxy contribution
    assert "Sync now" in _all_menu_labels(_build_menu(app, snap))


# -- the recurring Resolve-scripting warning ---------------------------------


def test_scripting_warning_yields_to_an_open_window(monkeypatch):
    """It fires on a timer, so it is the one dialog here that can arrive
    while the editor is mid-way through another. Losing a round costs
    nothing (the next interval comes round again); stacking Tk roots is what
    wedged the interpreter in AUDIT_2 CORE-M3."""
    from ccsync_companion import resolve_bridge
    from ccsync_companion import tray as tray_mod

    app = _UpgradeApp()
    app._popup_active_lock.acquire()          # e.g. the fixer popup is open
    opened = []
    monkeypatch.setattr(tray_mod, "_show_scripting_warning_locked",
                        lambda a: opened.append(1))

    assert tray_mod.show_scripting_warning(app) is False
    assert opened == []
    assert any(resolve_bridge.NO_SCRIPTING_MESSAGE in m for m in app.notified), \
        "yielding must not mean saying nothing at all"


def test_scripting_warning_releases_the_popup_lock(monkeypatch):
    from ccsync_companion import tray as tray_mod

    app = _UpgradeApp()
    monkeypatch.setattr(tray_mod, "_show_scripting_warning_locked", lambda a: True)

    assert tray_mod.show_scripting_warning(app) is True
    assert not app._popup_active_lock.locked(), "the lock outlived the dialog"


def test_scripting_warning_goes_through_ui_dispatch(monkeypatch):
    """Same contract as the other three: on macOS a tray worker thread may
    not touch Tk-Aqua at all."""
    from ccsync_companion import tray as tray_mod

    app = _UpgradeApp()
    calls = _record_tray_dispatch(monkeypatch, run=True)
    monkeypatch.setattr(tray_mod, "_build_scripting_warning_dialog", lambda a: True)

    assert tray_mod._show_scripting_warning_locked(app) is True
    assert len(calls) == 1


def test_a_broken_scripting_warning_dialog_still_tells_the_editor(monkeypatch):
    """The dialog exists to report an invisible failure. Failing to open it
    silently would leave exactly the state it was written for."""
    import sys
    import types

    from ccsync_companion import resolve_bridge
    from ccsync_companion import tray as tray_mod

    app = _UpgradeApp()
    broken = types.ModuleType("tkinter")

    def _boom(*a, **k):
        raise RuntimeError("Tcl is wedged")

    broken.Tk = _boom
    monkeypatch.setitem(sys.modules, "tkinter", broken)

    assert tray_mod._build_scripting_warning_dialog(app) is False
    assert any(resolve_bridge.NO_SCRIPTING_MESSAGE in m for m in app.notified)


# -- YouTube sign-in for the local downloader (2026-08-16) ------------------


def test_menu_hides_youtube_sign_in_when_local_downloads_off():
    from ccsync_companion.tray import _build_menu

    labels = _all_menu_labels(_build_menu(
        _FakeApp({"dashboard_url": "", "ytdl_local_downloads": False})))
    assert not any("Sign in to YouTube" in label for label in labels)


def test_install_youtube_cookies_installs_a_picked_file(tmp_path, monkeypatch):
    from ccsync_companion import tray, ytdl_cookies

    src = tmp_path / "export.txt"
    src.write_text("# Netscape HTTP Cookie File\n"
                   + "\t".join([".youtube.com", "TRUE", "/", "TRUE", "1900000000", "SID", "x"]) + "\n"
                   + "\t".join([".youtube.com", "TRUE", "/", "TRUE", "1900000000", "SAPISID", "y"]) + "\n")
    dest = tmp_path / "youtube-cookies.txt"
    monkeypatch.setattr(ytdl_cookies, "default_cookies_path", lambda: dest)

    notices = []
    app = _FakeApp({})
    app._notify_tray = lambda msg, title="ccsync-companion": notices.append(msg)

    tray._install_youtube_cookies(app, picker=lambda: str(src))

    assert dest.read_text() == src.read_text()
    assert notices and "saved" in notices[-1]


def test_install_youtube_cookies_cancelled_does_nothing(tmp_path, monkeypatch):
    from ccsync_companion import tray, ytdl_cookies
    dest = tmp_path / "youtube-cookies.txt"
    monkeypatch.setattr(ytdl_cookies, "default_cookies_path", lambda: dest)
    notices = []
    app = _FakeApp({})
    app._notify_tray = lambda msg, title="ccsync-companion": notices.append(msg)

    tray._install_youtube_cookies(app, picker=lambda: "")

    assert not dest.exists()
    assert notices == []


def test_install_youtube_cookies_reports_a_bad_file(tmp_path, monkeypatch):
    from ccsync_companion import tray, ytdl_cookies
    src = tmp_path / "loggedout.txt"
    src.write_text("# Netscape HTTP Cookie File\n"
                   + "\t".join([".youtube.com", "TRUE", "/", "TRUE", "1900000000", "PREF", "x"]) + "\n")
    monkeypatch.setattr(ytdl_cookies, "default_cookies_path", lambda: tmp_path / "out.txt")
    notices = []
    app = _FakeApp({})
    app._notify_tray = lambda msg, title="ccsync-companion": notices.append(msg)

    tray._install_youtube_cookies(app, picker=lambda: str(src))

    assert notices and "signed-in" in notices[-1]
    assert not (tmp_path / "out.txt").exists()


# tkinter's filedialog/messagebox submodules are imported HERE, at collection
# time, on purpose: conftest._no_real_tk_windows replaces tkinter.Toplevel with
# a plain function for the duration of every test, and simpledialog (which
# filedialog pulls in) does `class Dialog(Toplevel)` at import -> TypeError.
# The production code imports them inside the function, so without this the
# Tk branch below cannot be entered at all.
import tkinter.filedialog  # noqa: E402,F401
import tkinter.messagebox  # noqa: E402,F401

# -- comp-ui-1: the two YouTube dialogs build their root through ui_dispatch --
# bug-hunt-2026-09-03. Both used to call tk.Tk() inline on the tray worker
# thread and only root.destroy(), so ui_dispatch never reclaimed the
# interpreter (CR-93) and macOS built Tk-Aqua off the main thread. Every other
# test of these two functions passes the picker=/confirm= seam, which is
# exactly the branch that was wrong; these drive the Tk branch with dispatch
# stubbed, so no dialog is ever created. test_tk_interpreter_hygiene.py holds
# the source-level half (a tk.Tk() must be inside a dispatched function).


def _dispatch_spy(monkeypatch):
    from ccsync_companion import tray

    calls = []
    monkeypatch.setattr(tray.ui_dispatch, "dispatch",
                        lambda fn: (calls.append(fn), "")[1])
    return calls


def test_the_cookies_picker_is_built_through_ui_dispatch(tmp_path, monkeypatch):
    import threading

    from ccsync_companion import tray, ytdl_cookies

    monkeypatch.setattr(ytdl_cookies, "default_cookies_path",
                        lambda: tmp_path / "out.txt")
    calls = _dispatch_spy(monkeypatch)
    app = _FakeApp({})
    app._popup_active_lock = threading.Lock()

    tray._install_youtube_cookies(app)

    assert len(calls) == 1, "the picker did not go through ui_dispatch.dispatch"
    assert not app._popup_active_lock.locked(), "the popup lock was not released"


def test_the_cookies_picker_stands_down_while_a_window_is_open(monkeypatch):
    import threading

    from ccsync_companion import tray

    calls = _dispatch_spy(monkeypatch)
    notices = []
    app = _FakeApp({})
    app._notify_tray = lambda msg, title="ccsync-companion": notices.append(msg)
    app._popup_active_lock = threading.Lock()
    app._popup_active_lock.acquire()

    tray._install_youtube_cookies(app)

    assert calls == []
    assert notices and "already open" in notices[-1]


def test_the_youtube_terms_dialog_is_built_through_ui_dispatch(monkeypatch):
    import threading

    from ccsync_companion import tray, ytdl_attestation

    monkeypatch.setattr(ytdl_attestation, "accepted", lambda who: False)
    calls = _dispatch_spy(monkeypatch)
    app = _FakeApp({})
    app.editor_identity = lambda: "alex"
    app._popup_active_lock = threading.Lock()

    tray._show_youtube_terms_dialog(app)

    assert len(calls) == 1, "the terms dialog did not go through ui_dispatch.dispatch"
    assert not app._popup_active_lock.locked()


# -- CR-22: the licence gate needs a way out that is IN the menu -------------
# 2026-08-18. The lane lines already say "NOT SYNCING (this machine isn't set
# up yet)"; until this item existed, nothing in the menu could change that on
# a machine that had self-upgraded, because the wizard that records consent is
# a download away.


class _FakeAppWithLicence(_FakeApp):
    def __init__(self, config, problem=""):
        super().__init__(config)
        self._problem = problem
        self.prompted: list[bool] = []

    def eula_problem(self):
        return self._problem or None

    def prompt_licence_acceptance(self, force=False):
        self.prompted.append(force)


def test_menu_offers_the_licence_when_it_is_what_is_blocking():
    from ccsync_companion.tray import _build_menu

    app = _FakeAppWithLicence({"dashboard_url": ""},
                              problem="The CC Sync licence agreement has not been accepted…")
    labels = _menu_labels(_build_menu(app))
    assert any("Accept the licence agreement" in label for label in labels)


def test_menu_omits_the_licence_item_once_it_is_accepted():
    from ccsync_companion.tray import _build_menu

    labels = _menu_labels(_build_menu(_FakeAppWithLicence({"dashboard_url": ""})))
    assert not any("licence" in label.lower() for label in labels)


def test_accepting_the_licence_changes_the_menu_fingerprint():
    """Same rule as the safety latches: without it the item survives the click
    that cleared it, and the lane lines keep saying "isn't set up yet" until
    something unrelated moves (UI-3's shape)."""
    from ccsync_companion.tray import _menu_fingerprint, _tray_snapshot

    blocked = _FakeAppWithLicence({"dashboard_url": ""}, problem="not accepted")
    clear = _FakeAppWithLicence({"dashboard_url": ""})
    assert (_menu_fingerprint(_tray_snapshot(blocked))
            != _menu_fingerprint(_tray_snapshot(clear)))


# -- b-roll ingest lines (BROLL_INGEST_PLAN.md §3.3, 2026-08-18) ------------


def _ingest_app(**ingest):
    """A machine with a b-roll batch on it. Defaults describe a batch that is
    crunching right now, because that is the state most of these are about."""
    from ccsync_companion.tray import _tray_snapshot  # noqa: F401 - import parity

    view = {
        "active": True, "batch_uid": "b" * 32, "state": "running",
        "gate": "running", "done": 12, "failed": 0, "total": 40,
        "clip": "A001.MP4", "stage": "describing", "percent": 70,
        "tier": "good", "run_mode": "idle", "uploading": False,
        "upload_left": 0, "upload_paused": False,
        "model_download_percent": None, "warning": "", "paused": False,
    }
    view.update(ingest)
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.broll_ingest_view = lambda: view
    return app


def test_the_menu_does_not_rebuild_while_the_percentage_ticks():
    """_proxy_fingerprint's rule applied to the newer feature: a rebuild per
    finished clip destroys a menu the editor may have open (and on the win32
    backend resolves their click against the new callback list)."""
    from ccsync_companion.tray import _menu_fingerprint, _tray_snapshot

    before = _tray_snapshot(_ingest_app(percent=10, clip="A001.MP4"))
    after = _tray_snapshot(_ingest_app(percent=95, clip="A002.MP4", done=13))

    assert _menu_fingerprint(before) == _menu_fingerprint(after)


def test_the_live_count_is_in_the_tooltip_where_it_is_safe():
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    snap = _tray_snapshot(_ingest_app())

    assert "indexing b-roll 12/40" in _tooltip_text(snap)


def test_the_tooltip_shows_the_model_download_instead_while_it_runs():
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    snap = _tray_snapshot(_ingest_app(gate="no-model", model_download_percent=43))

    assert "fetching the b-roll model 43%" in _tooltip_text(snap)


def test_a_companion_with_no_orchestrator_renders_normally():
    from ccsync_companion.tray import (_build_menu, _menu_fingerprint,
                                       _tooltip_text, _tray_snapshot)

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    snap = _tray_snapshot(app)

    assert snap["broll_ingest"] == {}
    assert _tooltip_text(snap) == "CCSync: up to date"
    assert _menu_fingerprint(snap)
    assert "Sync now" in _all_menu_labels(_build_menu(app, snap))


def test_an_orchestrator_on_fire_does_not_take_the_menu_with_it():
    from ccsync_companion.tray import _build_menu, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))

    def _boom():
        raise RuntimeError("the orchestrator is on fire")

    app.broll_ingest_view = _boom
    snap = _tray_snapshot(app)

    assert snap["broll_ingest"] == {}
    assert "Sync now" in _all_menu_labels(_build_menu(app, snap))


# -- the sync engine is not running (SYNC-17, 2026-08-18) -------------------


def test_the_tray_says_what_the_dashboard_says_about_a_dead_sync_engine():
    """The supervisor writes ONE sentence and lane C, the tray line and the
    dashboard chip all say it. Before this the tray turned eighteen hours of
    a dead Syncthing into "Something went wrong"."""
    from ccsync_companion.tray import _format_lane_line_from, classify_lane_error

    sentence = ("the sync engine (Syncthing) is not running on this machine "
                "-- restarting it")
    assert classify_lane_error(sentence) == sentence

    status = LaneStatus(name="lane_c_syncthing", state="error", last_error=sentence)
    line = _format_lane_line_from(status, paused=False, problems=False)
    assert sentence in line
    assert "Copy diagnostics" not in line


def test_a_sync_engine_that_will_not_start_names_the_obstacle():
    from ccsync_companion.tray import classify_lane_error

    sentence = ("the sync engine (Syncthing) could not be started: "
                "Load failed: 5: Input/output error")
    assert classify_lane_error(sentence) == sentence


def test_the_unsupervised_wording_still_reads_as_an_instruction():
    """A lane built without a supervisor still publishes the old literal
    "Syncthing not running", which used to fall through to the generic
    shrug."""
    from ccsync_companion.tray import classify_lane_error

    text = classify_lane_error("Syncthing not running")
    assert "sync engine" in text.lower()
    assert "Something went wrong" not in text


def test_a_dead_sync_engine_turns_the_icon_red():
    statuses = [_status("lane_a_video_up", "idle"),
                LaneStatus(name="lane_c_syncthing", state="error",
                           last_error="the sync engine (Syncthing) is not running "
                                      "on this machine -- restarting it")]
    assert compute_overall_color(statuses) == "red"


# -- CR-70: click-to-menu latency instrumentation (2026-08-21) ---------------


def test_queue_latency_is_modulo_tick_wrap():
    from ccsync_companion.tray_native import _queue_latency_ms

    assert _queue_latency_ms(1000, 800) == 200
    # GetTickCount wraps every 49.7 days; a click posted just before the wrap
    # and dispatched just after must read as a few ms, never as negative.
    assert _queue_latency_ms(5, (1 << 32) - 10) == 15
    assert _queue_latency_ms("bad", None) == 0


def test_describe_slow_click_names_the_resolve_call(monkeypatch):
    from ccsync_companion import resolve_bridge, tray_native

    monkeypatch.setattr(resolve_bridge, "bridge_activity",
                        lambda: {"call": "get_timeline_items", "seconds": 4.2})
    text = tray_native._describe_slow_click(1830, 3.0)
    assert "1830 ms in the queue" in text
    assert "get_timeline_items for 4.2s" in text
    assert "gc counts" in text

    monkeypatch.setattr(resolve_bridge, "bridge_activity", lambda: {})
    assert "no Resolve call in flight" in tray_native._describe_slow_click(200, 1.0)

    def boom():
        raise RuntimeError("stubbed away")

    monkeypatch.setattr(resolve_bridge, "bridge_activity", boom)
    assert "bridge unavailable" in tray_native._describe_slow_click(200, 1.0)


# -- the YouTube download line (2026-08-25) ----------------------------------
# The owner: "when it is downloading a youtube clip it shows the information.
# Downloading: x/x (xx mb/s)". Built from ytdl_executor.progress()'s dict;
# nothing here touches the executor.


def _dl(**over):
    base = {"job_id": 7, "running": True, "clip": "aaaaaaaaaaa", "done": 2,
            "failed": 0, "total": 12, "bytes_done": 38_000_000,
            "bytes_total": 100_000_000, "speed_bps": 4_200_000.0}
    base.update(over)
    return base


def test_the_download_line_is_the_sentence_the_owner_asked_for():
    from ccsync_companion.tray import ytdl_download_line

    assert ytdl_download_line(_dl()) == "Downloading YouTube clip 3/12 (4.2 MB/s, 38%)"
    # a failed clip still counts as "past": clip 4 is in flight
    assert ytdl_download_line(_dl(done=2, failed=1)).startswith("Downloading YouTube clip 4/12")
    # never 13/12 on the last clip's tail
    assert ytdl_download_line(_dl(done=12)).startswith("Downloading YouTube clip 12/12")


def test_the_download_line_leaves_out_what_it_does_not_know():
    from ccsync_companion.tray import ytdl_download_line

    # no rate yet (yt-dlp printed NA), a total: the percent alone
    assert ytdl_download_line(_dl(speed_bps=None)) == "Downloading YouTube clip 3/12 (38%)"
    # HLS with no total: the rate alone, never a made-up percent
    assert ytdl_download_line(_dl(bytes_total=None)) == "Downloading YouTube clip 3/12 (4.2 MB/s)"
    # before the first update, or merging: the count alone
    assert ytdl_download_line(_dl(speed_bps=None, bytes_done=None, bytes_total=None)) == \
        "Downloading YouTube clip 3/12"
    # below a megabyte reads as a rate, not "0 MB/s" (which reads as stuck)
    assert ytdl_download_line(_dl(speed_bps=300_000)) == "Downloading YouTube clip 3/12 (0.3 MB/s, 38%)"
    # a manifest not yet read: still a line, still true
    assert ytdl_download_line(_dl(total=0, done=0)) == "Downloading YouTube clips"


def test_a_conversion_in_flight_says_so_instead_of_looking_stalled():
    from ccsync_companion.tray import ytdl_download_line

    # CR-79: ffmpeg re-encoding a VP9 clip on this machine has no rate and no
    # byte total; "Downloading 3/12" for ten minutes would read as stuck
    assert ytdl_download_line(_dl(phase="converting", speed_bps=None, bytes_done=None,
                                  bytes_total=None)) == "Converting YouTube clip 3/12 to H.264"
    # stale numbers from the download do not leak into the sentence
    assert ytdl_download_line(_dl(phase="converting")) == "Converting YouTube clip 3/12 to H.264"
    assert ytdl_download_line(_dl(phase="downloading")) == "Downloading YouTube clip 3/12 (4.2 MB/s, 38%)"
    assert ytdl_download_line(_dl(phase=None)) == "Downloading YouTube clip 3/12 (4.2 MB/s, 38%)"
    assert "—" not in ytdl_download_line(_dl(phase="converting"))


def test_no_download_is_no_line_and_junk_is_no_line():
    from ccsync_companion.tray import ytdl_download_line

    assert ytdl_download_line(_dl(running=False)) is None
    assert ytdl_download_line(None) is None
    assert ytdl_download_line("nonsense") is None
    assert ytdl_download_line({"running": True, "total": "many"}) is None
    assert ytdl_download_line({"job_id": 7, "running": False, "clip": None, "done": 0,
                               "failed": 0, "total": 0, "bytes_done": None,
                               "bytes_total": None, "speed_bps": None}) is None


def test_the_download_line_has_no_em_dash():
    from ccsync_companion.tray import ytdl_download_line

    for line in (ytdl_download_line(_dl()), ytdl_download_line(_dl(total=0)),
                 ytdl_download_line(_dl(bytes_total=None))):
        assert "\u2014" not in line


# ===========================================================================
# The reduced tray menu (2026-08-27): everything the menu no longer shows
# moved to Settings (settings_window.py). See _build_menu's own docstring.
# ===========================================================================


def test_the_reduced_menu_matches_the_approved_shape_exactly():
    """A quiet, signed-in, dashboard-configured machine with nothing
    conditional to say: identity, one separator, an EMPTY conditional block
    (still bracketed by its own pair of separators), Sync:/Resolve state,
    another separator, the five action items, a final separator, Quit.
    Exactly the approved list -- nothing more, nothing less."""
    from ccsync_companion.tray import _build_menu

    app = _FakeApp({"dashboard_url": "http://dash:8480", "ytdl_local_downloads": False},
                   identity=_FakeIdentity("alex"))
    labels = _menu_labels(_build_menu(app))
    assert labels == [
        "Signed in as alex",
        "- - - -",
        "- - - -",
        "Sync: up to date",
        "- - - -",
        "Sync now",
        "\u23f8 Pause syncing",
        "Open my sync drive",
        "Open dashboard",
        "Settings\u2026",
        "- - - -",
        # APP-13: Restart joined Quit in the bottom block (sweep 2026-09-03).
        "Restart CCSync",
        "Quit CCSync (nothing syncs until you start it again, or log in to "
        "this computer again)",
    ]


def test_the_reduced_menu_has_no_settings_only_content():
    """None of what moved to Settings leaks back into the tray, at ANY
    nesting depth -- there is no submenu left to hide it in (Advanced is
    gone), so _all_menu_labels and _menu_labels must now agree."""
    from ccsync_companion.tray import _build_menu

    app = _ingest_app(uploading=True, upload_left=3)
    app.removable_projects = lambda: [{"slug": "s", "rel": "a/b/c"}]
    app.p_swap_available = lambda: True
    app.stray_lut_count = lambda: 2  # this one DOES stay -- see below
    menu = _build_menu(app)
    assert _menu_labels(menu) == _all_menu_labels(menu)
    labels = _all_menu_labels(menu)
    for gone in (
        "Scan whole project", "Bring an existing project's media",
        "Undo the last clip-path change", "Copy diagnostics for your admin",
        "Open log", "Advanced", "Grade from server originals",
        "REMOVE", "ccsync-companion v",
    ):
        assert not any(gone in l for l in labels), gone


def test_the_conditional_block_items_appear_and_disappear_together():
    """NOT SET UP, the licence prompt, project setup and the LUT prompt all
    stay in the tray's conditional block (2026-08-27) -- they are blockers
    or "something to do" prompts, not advisory state."""
    from ccsync_companion.tray import _build_menu

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("alex"))
    assert not any(
        l.startswith(("\u26a0 NOT SET UP", "\u25ba Accept the licence", "Set up '", "\u25ba 0 LUT"))
        for l in _menu_labels(_build_menu(app))
    )

    app.config_problems = ["remote_root is blank"]
    app.eula_problem = lambda: "not accepted"
    app.setup_project_available = lambda: "New Doc"
    app.stray_lut_count = lambda: 5
    labels = _menu_labels(_build_menu(app))
    assert any(l.startswith("\u26a0 NOT SET UP") for l in labels)
    assert "\u25ba Accept the licence agreement to start syncing\u2026" in labels
    assert "Set up 'New Doc' on the server\u2026" in labels
    assert any(l.startswith("\u25ba 5 LUTs only on this machine") for l in labels)


def test_open_my_project_folder_was_renamed_to_open_my_sync_drive():
    from ccsync_companion.tray import _build_menu

    labels = _menu_labels(_build_menu(_FakeApp({"dashboard_url": ""})))
    assert "Open my sync drive" in labels
    assert not any("project folder" in l for l in labels)


def test_open_my_sync_drive_opens_local_root(monkeypatch, tmp_path):
    from ccsync_companion import tray as tray_mod

    app = _FakeApp({"dashboard_url": "", "local_root": str(tmp_path)})
    opened = []
    monkeypatch.setattr(tray_mod, "_open_log", lambda path: opened.append(str(path)))
    monkeypatch.setattr(tray_mod, "_spawn", lambda a, label, fn: fn())

    tray_mod.action_open_sync_drive(app)
    assert opened == [str(tmp_path)]


def test_settings_menu_item_opens_the_settings_window(monkeypatch):
    from ccsync_companion import tray as tray_mod
    from ccsync_companion.tray import _build_menu

    app = _FakeApp({"dashboard_url": ""})
    spawned = []
    monkeypatch.setattr(tray_mod, "_spawn", lambda a, label, fn: spawned.append(label))

    menu = _build_menu(app)
    item = next(i for i in menu.items if str(i.text) == "Settings\u2026")
    item(None)
    assert spawned == ["Settings"]


# -- _sync_line ---------------------------------------------------------


def _snap(**over):
    base = {
        "sync_guard": {}, "problems": False, "eula_problem": "", "paused": False,
        "root_absent": False, "statuses": [],
    }
    base.update(over)
    return base


def test_sync_line_default_is_up_to_date():
    from ccsync_companion.tray import _sync_line

    assert _sync_line(_snap()) == "Sync: up to date"


def test_sync_line_priority_halt_beats_everything():
    from ccsync_companion.tray import _sync_line

    snap = _snap(
        sync_guard={"halt": {"active": True, "scope": "local"},
                   "lane_b_breaker": {"tripped": True}},
        problems=True, paused=True, root_absent=True,
    )
    assert _sync_line(snap) == "Sync: stopped on this machine"

    snap["sync_guard"]["halt"]["scope"] = "fleet"
    assert _sync_line(snap) == "Sync: stopped by your admin"


def test_sync_line_breaker_beats_not_set_up_and_paused():
    from ccsync_companion.tray import _sync_line

    snap = _snap(sync_guard={"lane_b_breaker": {"tripped": True}},
                problems=True, paused=True)
    assert _sync_line(snap) == "Sync: proxy download stopped (see Settings)"


def test_sync_line_not_set_up_covers_problems_and_licence():
    from ccsync_companion.tray import _sync_line

    assert _sync_line(_snap(problems=True)) == "Sync: not set up yet"
    assert _sync_line(_snap(eula_problem="not accepted")) == "Sync: not set up yet"


def test_sync_line_root_absent_beats_plain_paused():
    from ccsync_companion.tray import _sync_line

    assert _sync_line(_snap(root_absent=True, paused=True)) == \
        "Sync: paused (drive disconnected)"


def test_sync_line_paused():
    from ccsync_companion.tray import _sync_line

    assert _sync_line(_snap(paused=True)) == "Sync: paused"


def test_sync_line_uploading_only():
    from ccsync_companion.tray import _sync_line

    statuses = [_status("lane_a_video_up", "syncing")]
    statuses[0].transferring = 4
    statuses[0].speed_bps = 2_000_000
    assert _sync_line(_snap(statuses=statuses)) == "Sync: uploading 4 files \u00b7 2.0 MB/s"


def test_sync_line_downloading_only():
    from ccsync_companion.tray import _sync_line

    statuses = [_status("lane_b_proxy_down", "syncing")]
    statuses[0].transferring = 1
    assert _sync_line(_snap(statuses=statuses)) == "Sync: downloading 1 file"


def test_sync_line_both_directions_at_once():
    from ccsync_companion.tray import _sync_line

    up = _status("lane_a_video_up", "syncing")
    up.transferring = 2
    down = _status("lane_b_proxy_down", "syncing")
    down.transferring = 3
    assert _sync_line(_snap(statuses=[up, down])) == "Sync: up 2 \u00b7 down 3 files"


def test_sync_line_lane_c_counts_toward_both_totals():
    """Lane C is "everything else, both ways" (LANE_LABELS) -- it has no
    up/down split of its own."""
    from ccsync_companion.tray import _sync_line

    c = _status("lane_c_syncthing", "syncing")
    c.transferring = 5
    assert _sync_line(_snap(statuses=[c])) == "Sync: up 5 \u00b7 down 5 files"


def test_sync_line_queued_but_idle():
    from ccsync_companion.tray import _sync_line

    idle = _status("lane_a_video_up", "idle")
    idle.queued = 7
    assert _sync_line(_snap(statuses=[idle])) == "Sync: 7 files waiting"


# -- CR-92: the drive went out with work owed ---------------------------------


def test_sync_line_names_what_the_drive_went_out_owing():
    from ccsync_companion.tray import _sync_line

    assert _sync_line(_snap(root_absent=True)) == "Sync: paused (drive disconnected)"
    assert _sync_line(_snap(root_absent=True, root_unfinished="2 uploads (1.9 GB left)")) == (
        "Sync: paused (drive disconnected, 2 uploads (1.9 GB left) still to go)")
    # Only while the drive is out: the summary alone changes nothing.
    assert _sync_line(_snap(root_unfinished="2 uploads")) == "Sync: up to date"


def test_the_snapshot_carries_root_unfinished_and_the_fingerprint_changes():
    from ccsync_companion.tray import _menu_fingerprint, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app._root_absent = True
    before = _tray_snapshot(app)
    assert before["root_unfinished"] == ""
    fp_before = _menu_fingerprint(before)

    app.drive_unfinished_summary = lambda: "2 uploads"
    after = _tray_snapshot(app)

    assert after["root_unfinished"] == "2 uploads"
    assert _menu_fingerprint(after) != fp_before


def test_the_tooltip_names_what_is_owed_and_stays_short():
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app._root_absent = True
    app.drive_unfinished_summary = lambda: "2 uploads, 3 proxy downloads and 14 other files (123.4 GB left)"
    text = _tooltip_text(_tray_snapshot(app))
    assert text.startswith("CCSync: PAUSED (drive disconnected, 2 uploads")
    assert len(text) <= 127



# -- APP-2 / UX-4: the clips somebody dismissed ----------------------------


def test_ignored_line_names_the_way_back():
    from ccsync_companion.tray import _ignored_line

    line = _ignored_line({"resolve_health": {"ignored_this_session": 14,
                                             "ignored_folders": 0}})
    assert line.startswith("\u26a0 14 clip(s) skipped this session")
    assert "SCAN WHOLE PROJECT" in line
    assert "\u2014" not in line


def test_ignored_line_mentions_the_folders_left_alone_on_purpose():
    from ccsync_companion.tray import _ignored_line

    line = _ignored_line({"resolve_health": {"ignored_this_session": 0,
                                             "ignored_folders": 2}})
    assert "2 folder(s) are set to be left alone" in line
    assert "skipped this session" not in line


def test_ignored_line_is_silent_on_a_healthy_machine():
    from ccsync_companion.tray import _ignored_line

    assert _ignored_line({}) is None
    assert _ignored_line({"resolve_health": {"ignored_this_session": 0,
                                             "ignored_folders": 0}}) is None
    assert _ignored_line({"resolve_health": {"ignored_this_session": "x"}}) is None


# -- section 10: "take fleet jobs now" (2026-08-30) -------------------------


class _FakeJobRunner:
    """The two things the tray reads off the runner, and the one it calls."""

    def __init__(self, until=None, enabled=True, minutes=30):
        self.until = until
        self.enabled = enabled
        self.volunteer_minutes = minutes
        self.calls: list = []

    def status(self):
        return {"state": "nothing_offered", "volunteer_until": self.until,
                "forced": [], "offered": [], "queue": {}, "job": None}

    def volunteer(self, minutes=None):
        self.calls.append(minutes)
        self.until = None if minutes == 0 else "2026-08-30T12:30:00+00:00"
        return self.until


def _app_with_runner(runner):
    app = _FakeApp({"dashboard_url": ""})
    app.job_runner = runner
    return app


def test_menu_offers_the_machine_to_the_fleet():
    from ccsync_companion.tray import _build_menu

    menu = _build_menu(_app_with_runner(_FakeJobRunner()))
    assert "⚡ Take fleet jobs now (30 min)" in _menu_labels(menu)


def test_menu_says_when_the_machine_is_already_lent():
    from ccsync_companion.tray import _build_menu

    runner = _FakeJobRunner(until="2026-08-30T12:30:00+00:00")
    labels = _menu_labels(_build_menu(_app_with_runner(runner)))
    assert any(label.startswith("⚡ Taking fleet jobs until ")
               and label.endswith(" (click to stop)") for label in labels), labels


def test_menu_omits_the_volunteer_item_without_a_job_runner():
    """A switch that cannot do anything is worse than no switch: on a
    companion with no runner, or one whose owner set jobs_enabled = false,
    the item is simply not there."""
    from ccsync_companion.tray import _build_menu

    assert not any(label.startswith("⚡") for label
                   in _menu_labels(_build_menu(_FakeApp({"dashboard_url": ""}))))
    off = _app_with_runner(_FakeJobRunner(enabled=False))
    assert not any(label.startswith("⚡") for label
                   in _menu_labels(_build_menu(off)))


def test_the_volunteer_item_sits_between_sync_now_and_pause():
    """Where the approved 2026-08-27 menu puts the everyday actions, and next
    to the other switch about what this machine does with itself."""
    from ccsync_companion.tray import _build_menu

    labels = _menu_labels(_build_menu(_app_with_runner(_FakeJobRunner())))
    assert labels.index("Sync now") + 1 == labels.index(
        "⚡ Take fleet jobs now (30 min)")
    assert labels[labels.index("⚡ Take fleet jobs now (30 min)") + 1] \
        == "⏸ Pause syncing"


def test_the_volunteer_label_survives_an_unreadable_deadline():
    from ccsync_companion.tray import _volunteer_label

    assert _volunteer_label({"jobs_volunteer_minutes": 30,
                             "jobs_volunteer_until": "soon"}) \
        == "⚡ Taking fleet jobs now (click to stop)"


def test_fingerprint_moves_when_the_machine_is_lent_and_back():
    """UI-3's shape: without this the item would still say "Take fleet jobs
    now" after the click that started the timer."""
    from ccsync_companion.tray import _menu_fingerprint, _tray_snapshot

    runner = _FakeJobRunner()
    app = _app_with_runner(runner)
    before = _menu_fingerprint(_tray_snapshot(app))
    runner.volunteer(None)
    lent = _menu_fingerprint(_tray_snapshot(app))
    assert lent != before
    runner.volunteer(0)
    assert _menu_fingerprint(_tray_snapshot(app)) == before


def test_the_volunteer_action_switches_the_timer_both_ways():
    from ccsync_companion.tray import action_volunteer

    runner = _FakeJobRunner()
    app = _app_with_runner(runner)
    action_volunteer(app, {"jobs_volunteer_minutes": 30,
                           "jobs_volunteer_until": ""})
    _join_tray_threads()
    assert runner.calls == [None]
    action_volunteer(app, {"jobs_volunteer_minutes": 30,
                           "jobs_volunteer_until": "2026-08-30T12:30:00+00:00"})
    _join_tray_threads()
    assert runner.calls == [None, 0]


def _join_tray_threads():
    """_spawn runs every action on its own daemon thread (2026-07-26: the
    tray's message loop is the one thread nothing may block)."""
    import threading

    for thread in threading.enumerate():
        if thread.name.startswith("ccsync-tray-"):
            thread.join(timeout=5.0)


# -- Open dashboard prefers the SITE's browse URL (2026-08-31) --------------
# The dashboard went https-only for browsers (DASH_COOKIE_SECURE=1): the
# config.toml dashboard_url is the REPORTING address and may be plain http,
# so the tray click follows the manifest's published dashboard_url instead,
# falling back to config exactly as before when no manifest is cached.


def test_open_dashboard_prefers_site_manifest_url(monkeypatch):
    from ccsync_companion import site as site_mod
    from ccsync_companion import tray as tray_mod
    monkeypatch.setattr(site_mod, "cached_site",
                        lambda *a, **k: {"dashboard_url":
                                         "https://nas.tailnet.ts.net:9443"})
    app = _FakeApp({"dashboard_url": "http://192.168.0.102:8480"})
    assert tray_mod._dashboard_url(app) == "https://nas.tailnet.ts.net:9443"


def test_open_dashboard_falls_back_to_config_url(monkeypatch):
    from ccsync_companion import site as site_mod
    from ccsync_companion import tray as tray_mod
    monkeypatch.setattr(site_mod, "cached_site", lambda *a, **k: None)
    app = _FakeApp({"dashboard_url": "http://192.168.0.102:8480"})
    assert tray_mod._dashboard_url(app) == "http://192.168.0.102:8480"


def test_open_dashboard_ignores_a_junk_manifest_url(monkeypatch):
    from ccsync_companion import site as site_mod
    from ccsync_companion import tray as tray_mod
    monkeypatch.setattr(site_mod, "cached_site",
                        lambda *a, **k: {"dashboard_url": "not a url"})
    app = _FakeApp({"dashboard_url": "http://192.168.0.102:8480"})
    assert tray_mod._dashboard_url(app) == "http://192.168.0.102:8480"


# -- APP-1: the icon and the tooltip read sync_guard.blocked ---------------
#
# Before 2026-09-04 the colour consulted five things and the tooltip four, and
# `sync_guard.blocked` -- the one field whose whole job is to answer "why is
# this machine not syncing" -- was in neither. A reporter 401'd for a week
# showed a steady green mark over "CCSync: up to date".


def _blocked(reason, detail="something is wrong"):
    return {"blocked": {"reason": reason, "detail": detail, "since": None}}


def test_a_blocked_machine_is_not_green():
    """APP-1 [verified]: green with `blocked` set was the shipped behaviour --
    compute_overall_color() never received the guard at all."""
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    assert compute_overall_color(_idle3(), app) == "green"
    assert compute_overall_color(
        _idle3(), app, _blocked("transport_offline")) == "orange"


def test_a_broken_blocked_reason_is_red_not_amber():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    for reason in ("clock_skew", "lane_stalled", "syncthing_down"):
        assert compute_overall_color(_idle3(), app, _blocked(reason)) == "red"
    assert compute_overall_color(
        _idle3(), app, _blocked("project_dir_moved")) == "orange"


def test_no_guard_and_an_empty_guard_stay_green():
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    assert compute_overall_color(_idle3(), app, None) == "green"
    assert compute_overall_color(_idle3(), app, {}) == "green"
    assert compute_overall_color(_idle3(), app, {"blocked": None}) == "green"


def test_the_base_rig_keeps_its_green_for_the_vacuous_reasons():
    """2026-08-19's carve-out survives APP-1: a machine whose tree IS the
    server tree can never tick a project, and a permanent amber on the one
    machine the admin watches all day teaches them to ignore amber."""
    app = _FakeApp({"dashboard_url": "", "mode": "base"},
                   identity=_FakeIdentity("alex"))
    app._sync_enabled = False
    assert compute_overall_color(_idle3(), app, _blocked("no_selection")) == "green"
    # ...but a broken clock on the base rig is still a fault.
    assert compute_overall_color(_idle3(), app, _blocked("clock_skew")) == "red"


def test_the_snapshot_hands_the_guard_to_the_colour():
    from ccsync_companion.tray import _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    assert _tray_snapshot(app)["color"] == "green"
    app.sync_guard = lambda: _blocked("folders_unfiltered")
    assert _tray_snapshot(app)["color"] == "orange"


def test_the_tooltip_says_why_instead_of_up_to_date():
    """APP-1 [verified]: `_tooltip_text` ended `return ... "up to date"` with
    no read of sync_guard anywhere in the function."""
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    assert _tooltip_text(_tray_snapshot(app)) == "CCSync: up to date"
    app.sync_guard = lambda: _blocked(
        "transport_offline", "This computer cannot reach the server")
    tip = _tooltip_text(_tray_snapshot(app))
    assert tip == "CCSync: This computer cannot reach the server"
    assert "up to date" not in tip


def test_the_tooltip_stays_inside_the_windows_limit():
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.sync_guard = lambda: _blocked("folders_unfiltered", "x" * 400)
    assert len(_tooltip_text(_tray_snapshot(app))) <= 127


def test_a_louder_tooltip_state_still_wins_over_blocked():
    """The reasons above this line in _tooltip_text (not set up, drive gone,
    paused) are the same reasons _BLOCKED_ORDER puts first, and they must not
    be answered twice in two different wordings."""
    from ccsync_companion.tray import _tooltip_text, _tray_snapshot

    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app.paused = True
    app.sync_guard = lambda: _blocked("paused", "Syncing is paused from this computer's tray")
    assert _tooltip_text(_tray_snapshot(app)) == "CCSync: PAUSED"


# -- RES-8: Quit while a FIX ALL copy is live ------------------------------


def test_quit_asks_nothing_when_no_copy_is_running(monkeypatch):
    from ccsync_companion import popup
    from ccsync_companion import tray as tray_mod

    popup._set_copy_state(None)
    assert tray_mod._confirm_quit_while_copying(_FakeApp({})) is True


def test_quit_mid_copy_asks_and_a_no_keeps_copying(monkeypatch):
    """RES-8 [verified]: on_quit went straight to icon.stop() + shutdown(),
    tearing the process down inside write() and stranding a multi-GB
    .ccsync-tmp that is reported an hour later and never deleted."""
    from ccsync_companion import popup
    from ccsync_companion import tray as tray_mod

    popup._set_copy_state({"index": 12, "total": 69, "name": "A012.braw"})
    asked = {}
    monkeypatch.setattr(tray_mod.sys, "platform", "win32")

    class _Fake:
        class windll:
            class user32:
                @staticmethod
                def MessageBoxW(handle, body, title, flags):
                    asked["body"] = body
                    return 7  # IDNO

    monkeypatch.setitem(__import__("sys").modules, "ctypes", _Fake)
    try:
        assert tray_mod._confirm_quit_while_copying(_FakeApp({})) is False
        assert "12" in asked["body"] and "69" in asked["body"]
        _Fake.windll.user32.MessageBoxW = staticmethod(lambda *a: 6)  # IDYES
        assert tray_mod._confirm_quit_while_copying(_FakeApp({})) is True
    finally:
        popup._set_copy_state(None)


def test_quit_fails_open_when_it_cannot_ask(monkeypatch):
    """A Quit that silently does nothing is the worse bug: the question is a
    courtesy, not a lock."""
    from ccsync_companion import popup
    from ccsync_companion import tray as tray_mod

    popup._set_copy_state({"index": 1, "total": 2, "name": "a.mov"})
    monkeypatch.setattr(tray_mod.sys, "platform", "win32")

    class _Boom:
        class windll:
            class user32:
                @staticmethod
                def MessageBoxW(*a):
                    raise OSError("no user32 here")

    monkeypatch.setitem(__import__("sys").modules, "ctypes", _Boom)
    try:
        assert tray_mod._confirm_quit_while_copying(_FakeApp({})) is True
    finally:
        popup._set_copy_state(None)


def test_the_quit_question_names_the_file_and_the_batch():
    from ccsync_companion.tray import quit_confirm_text

    text = quit_confirm_text({"index": 12, "total": 69, "name": "A012.braw"})
    assert "file 12" in text and "69" in text
    assert "abandons" in text
    assert "—" not in text  # no em dashes in copy an editor reads
    # A batch that has not published its first chunk yet still says something
    # true about what is at stake.
    assert "69" in quit_confirm_text({"index": 0, "total": 69})
