"""Regression tests for the 2026-09-24 hunt's wave 2, c-ui group (2026-09-25).

Nothing here builds a real Tk root, a real NSMenu or a real tray icon: every
window is reached through the seams the earlier comp-ui suites use (a stubbed
`tkinter.Tk`, the picker's `dialog_fn`, the Windows icon's `_Win32.get`, the
macOS icon's `_to_main` / `_build_nsmenu`), as conftest's guards require.
"""

from __future__ import annotations

import inspect
import threading

import pytest

from ccsync_companion import popup, settings_window, tray, tray_native


# -- bug-comp-ui-1: the ingest picker -----------------------------------------


@pytest.fixture
def _fresh_picker(monkeypatch):
    monkeypatch.setattr(popup, "_live_picker", None)
    monkeypatch.setattr(popup, "_picker_popup_lock", None)
    yield


def _blocking_dialog(answer_box: dict, release: threading.Event, calls: list):
    def _ask(kind):
        calls.append(kind)
        release.wait(10)
        return answer_box.get("value", "")
    return _ask


def test_a_timed_out_picker_is_closed_not_abandoned(monkeypatch, _fresh_picker):
    """bug-comp-ui-1: the waiter returned "cancelled" and left the dialog on
    screen; a folder chosen in it afterwards was silently dropped."""
    release = threading.Event()
    calls: list = []
    asked_to_close: list = []

    def _close(live):
        asked_to_close.append(live["tid"])
        release.set()          # the dialog answers "" the way a Cancel does
        return 1

    monkeypatch.setattr(popup, "_close_picker_dialog", _close)
    out = popup.pick_media_sources("folder", timeout=0.2,
                                   dialog_fn=_blocking_dialog({}, release, calls))

    assert out == []
    assert len(asked_to_close) == 1 and asked_to_close[0], \
        "the dialog's own thread must be the one asked to close"
    assert popup._live_picker is None, "a closed picker must not stay joinable"


def test_a_second_pick_joins_the_open_picker_instead_of_a_second_root(
        tmp_path, _fresh_picker):
    """bug-comp-ui-1: a second click opened a second Tk root on a second
    thread beside the first."""
    clip = tmp_path / "A001.mp4"
    clip.write_bytes(b"x" * 10)
    release = threading.Event()
    calls: list = []
    answer = {"value": [str(clip)]}
    ask = _blocking_dialog(answer, release, calls)
    results: dict = {}

    def _pick(name):
        results[name] = popup.pick_media_sources("files", timeout=10, dialog_fn=ask)

    first = threading.Thread(target=_pick, args=("first",))
    first.start()
    for _ in range(200):
        if calls:
            break
        threading.Event().wait(0.01)
    second = threading.Thread(target=_pick, args=("second",))
    second.start()
    threading.Event().wait(0.1)
    release.set()
    first.join(5)
    second.join(5)

    assert calls == ["files"], "only ONE dialog may be opened"
    assert [f["name"] for f in results["first"]] == ["A001.mp4"]
    assert [f["name"] for f in results["second"]] == ["A001.mp4"]


def test_the_picker_refuses_beside_another_ccsync_window(_fresh_picker):
    """bug-comp-ui-1: the picker neither took nor checked the popup lock."""
    lock = threading.Lock()
    lock.acquire()
    with pytest.raises(popup.PickerBusy) as caught:
        popup.pick_media_sources("files", timeout=1, dialog_fn=lambda k: "",
                                 popup_lock=lock)
    assert "—" not in str(caught.value)
    lock.release()


def test_the_picker_holds_the_popup_lock_while_its_dialog_is_up(_fresh_picker):
    lock = threading.Lock()
    seen: list = []

    def _ask(kind):
        seen.append(lock.locked())
        return ""

    popup.set_picker_popup_lock(lock)
    assert popup.pick_media_sources("files", timeout=5, dialog_fn=_ask) == []
    assert seen == [True], "apply_upgrade's stand-down must see the picker"
    for _ in range(100):
        if not lock.locked():
            break
        threading.Event().wait(0.01)
    assert not lock.locked(), "the picker thread releases it when the dialog ends"


# -- ui-comp-windows-2: nothing ticked is not a warning -----------------------


def test_nothing_ticked_is_muted_in_settings_and_does_not_move_help():
    guard = {"blocked": {"reason": "no_selection",
                         "detail": "No projects are ticked for this computer"}}
    advisories = settings_window._lane_advisories(guard)
    assert advisories == [(settings_window.INFO,
                           "No projects are ticked for this computer")]
    lines, _hidden = settings_window.rank_advisories(advisories)
    assert [line.style for line in lines] == ["muted"]
    sections = [settings_window.Section("SYNCING", lines),
                settings_window.Section("HELP", [])]
    assert [s.title for s in settings_window._help_first(sections)] == \
        ["SYNCING", "HELP"]


def test_a_real_blocking_reason_is_still_red():
    guard = {"blocked": {"reason": "not_signed_in", "detail": "Sign in to sync"}}
    advisories = settings_window._lane_advisories(guard)
    assert (settings_window.BLOCKING, "⚠ Sign in to sync") in advisories


# -- bug-comp-ui-2: macOS menu rebuild while the menu is open -----------------


class _FakeStatusItem:
    def __init__(self):
        self.menus = []

    def setMenu_(self, menu):
        self.menus.append(menu)


def test_a_rebuild_that_lands_while_the_menu_is_open_waits_for_it_to_close(
        monkeypatch):
    icon = tray_native._DarwinIcon("ccsync", image=None, title="t")
    icon._status_item = _FakeStatusItem()
    queued: list = []
    icon._to_main = queued.append
    built: list = []
    monkeypatch.setattr(icon, "_build_nsmenu", lambda menu: built.append(menu) or "ns")
    later: list = []
    monkeypatch.setattr(tray_native, "_darwin_after_current", later.append)

    icon._menu_open.set()                # opened after tray.py's guard check
    icon.menu = "new menu"
    queued.pop()()                       # the main queue drains mid-tracking

    assert built == [], "the open menu's delegate must not be replaced under it"
    icon._menu_did_close()
    assert not icon._menu_open.is_set()
    assert len(later) == 1
    later.pop()()
    assert built == ["new menu"]
    assert icon._status_item.menus == ["ns"]


def test_a_closed_menu_with_nothing_pending_rebuilds_nothing(monkeypatch):
    icon = tray_native._DarwinIcon("ccsync", image=None, title="t")
    later: list = []
    monkeypatch.setattr(tray_native, "_darwin_after_current", later.append)
    icon._menu_open.set()
    icon._menu_did_close()
    assert later == []


# -- bug-comp-ui-3: a work window closed before its root existed --------------


def test_close_before_the_root_exists_waits_for_the_window_thread():
    building = threading.Event()
    release = threading.Event()
    window = popup.WorkProgressWindow("X", "", lambda: None)

    def _slow_build():
        building.set()
        release.wait(5)

    window._build_and_show = _slow_build
    assert window.open() is True
    assert building.wait(5)
    window.close()
    try:
        assert window.wait_closed(0.2) is False, \
            "wait_closed must not report a window that is still being built"
        assert window._close_requested.is_set()
    finally:
        release.set()
    assert window.wait_closed(5) is True


def test_the_first_tick_honours_a_close_that_could_not_be_marshalled():
    class _Root:
        def __init__(self):
            self.destroyed = 0
            self.scheduled = 0

        def destroy(self):
            self.destroyed += 1

        def after(self, ms, fn):
            self.scheduled += 1

    window = popup.WorkProgressWindow("X", "", lambda: None)
    window.root = _Root()
    window._close_requested.set()
    window._tick()
    assert window.root.destroyed == 1
    assert window.root.scheduled == 0


def test_the_build_checks_for_a_close_before_entering_its_event_loop():
    source = inspect.getsource(popup.WorkProgressWindow._build_and_show_unpatched)
    check = source.index("self._close_requested.is_set()")
    assert check < source.index("ui_dispatch.run_dialog(root)")


# -- bug-comp-ui-5: tray dialogs that fail half-built -------------------------


class _BrokenRoot:
    destroyed: list = []

    def title(self, *a):
        raise OSError("the session went away")

    def destroy(self):
        _BrokenRoot.destroyed.append(self)


class _App:
    def _notify_tray(self, *a, **k):
        pass

    def lane_statuses(self):
        return []

    def editor_identity(self):
        return "alex"


@pytest.fixture
def _broken_tk(monkeypatch):
    import tkinter

    _BrokenRoot.destroyed = []
    monkeypatch.setattr(tkinter, "Tk", lambda *a, **k: _BrokenRoot())
    yield


@pytest.mark.parametrize("build", [
    lambda: tray._build_sign_in_dialog(_App()),
    lambda: tray._build_typed_confirmation(_App(), "t", "b", "x"),
    lambda: tray._build_credentials_dialog(_App()),
], ids=["sign-in", "typed-confirmation", "credentials"])
def test_a_raising_dialog_build_destroys_its_root(build, _broken_tk):
    with pytest.raises(OSError):
        build()
    assert len(_BrokenRoot.destroyed) == 1


@pytest.mark.parametrize("build", [
    lambda: tray._build_update_dialog(_App(), {"version": "0.9.99"}),
    lambda: tray._build_scripting_warning_dialog(_App()),
], ids=["update", "scripting-warning"])
def test_a_caught_dialog_failure_still_destroys_its_root(build, _broken_tk):
    assert build() is False
    assert len(_BrokenRoot.destroyed) == 1


# -- bug-comp-ui-6: the Windows icon's teardown -------------------------------


class _User32:
    def __init__(self, icon):
        self.icon = icon
        self.destroyed: list = []

    def DestroyIcon(self, hicon):  # noqa: N802 - the Win32 name
        # A pulse tick already past its loop check inserts while the pump
        # thread is tearing down.
        if len(self.destroyed) == 0:
            self.icon._hicon_cache[999] = (object(), 7)
        self.destroyed.append(hicon)
        return 1


class _Api:
    def __init__(self, icon):
        self.user32 = _User32(icon)


def test_teardown_survives_an_icon_cached_mid_iteration(monkeypatch):
    icon = tray_native._WindowsIcon("ccsync", None, "t")
    api = _Api(icon)
    monkeypatch.setattr(tray_native._Win32, "get", staticmethod(lambda: api))
    monkeypatch.setattr(icon, "_remove_icon", lambda: None)
    icon._hicon_cache[1] = (object(), 11)
    icon._hicon_cache[2] = (object(), 22)

    icon._teardown()

    assert api.user32.destroyed == [11, 22]


def test_a_raising_teardown_still_releases_stop(monkeypatch):
    icon = tray_native._WindowsIcon("ccsync", None, "t")
    monkeypatch.setattr(tray_native, "_check_struct_sizes", lambda: [])
    monkeypatch.setattr(icon, "_create_window", lambda: None)
    monkeypatch.setattr(icon, "_add_icon", lambda **k: None)
    monkeypatch.setattr(icon, "_pump", lambda: None)

    def _boom():
        raise RuntimeError("dictionary changed size during iteration")

    monkeypatch.setattr(icon, "_teardown", _boom)
    with pytest.raises(RuntimeError):
        icon.run()
    assert icon._stopped.is_set(), "stop() would wait its full 5 s"


# ============================================================================
# chunk 2 (2026-09-25): ui-comp-windows-1/4/5/6/7/8, logic-sync-truth-6
# ============================================================================

from pathlib import Path  # noqa: E402

from ccsync_companion import root_guard as root_guard_mod  # noqa: E402
from ccsync_companion import site as site_mod  # noqa: E402
from ccsync_companion import ui_copy, ui_dispatch  # noqa: E402
from ccsync_companion.sync.base import LaneStatus, STATE_SYNCING  # noqa: E402

from test_tray import _FakeApp, _FakeIdentity  # noqa: E402  (sibling module)
from ccsync_companion.tray import _tray_snapshot  # noqa: E402

SRC = Path(popup.__file__).resolve().parent


# -- ui-comp-windows-1: confirm / notice bodies wrap --------------------------


class _Widget:
    made: list = []

    def __init__(self, *a, **kw):
        self.kw = kw
        _Widget.made.append(self)

    def pack(self, *a, **k):
        return self

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def _fake_tk_dialog(monkeypatch):
    import tkinter

    from ccsync_companion import theme

    _Widget.made = []
    monkeypatch.setattr(tkinter, "Tk", _Widget)
    monkeypatch.setattr(tkinter, "Label", _Widget)
    monkeypatch.setattr(tkinter, "Frame", _Widget)
    monkeypatch.setattr(theme, "neon_button", lambda *a, **k: _Widget())
    monkeypatch.setattr(theme, "apply_window_icon", lambda *a, **k: None)
    monkeypatch.setattr(ui_dispatch, "dispatch", lambda fn: fn())
    monkeypatch.setattr(ui_dispatch, "run_dialog", lambda root: None)
    yield


LONG_BODY = ("Make this computer a WIRED rig that works straight off the server "
             "share? " * 5).strip()


@pytest.mark.parametrize("show", [
    lambda: popup.confirm_dialog("T", LONG_BODY),
    lambda: popup.notice_dialog("T", LONG_BODY),
], ids=["confirm", "notice"])
def test_a_dialog_body_wraps_instead_of_running_off_the_screen(show, _fake_tk_dialog):
    """ui-comp-windows-1: the body Label had no wraplength, so a one-line
    paragraph asked for a window wider than the screen and Tk cut the end of
    the sentence."""
    show()
    body = [w for w in _Widget.made if w.kw.get("text") == LONG_BODY]
    assert len(body) == 1
    assert body[0].kw.get("wraplength") == popup.DIALOG_WRAP_PX == 520


# -- ui-comp-windows-4: the jump strip wraps; Lines follow the window ---------


def test_the_jump_strip_wraps_so_help_is_reachable_at_the_default_size():
    # The hunter's measured reqwidths for a healthy machine (THIS COMPUTER,
    # SYNCING, PROJECTS ON THIS COMPUTER, RESOLVE, FLEET JOBS, ADVANCED, HELP):
    # 841 px in one row against a 720 px window.
    widths = [140, 95, 250, 95, 115, 89, 61]
    available = 720 - 2 * settings_window._STRIP_PADX
    rows = settings_window._flow_rows(widths, available)
    assert rows[-1] > 0, "HELP must wrap onto a row of its own, not be clipped"
    for row in set(rows):
        used = sum(w + settings_window._STRIP_GAP
                   for w, r in zip(widths, rows) if r == row)
        assert used <= available or rows.count(row) == 1
    assert rows == sorted(rows), "the strip keeps the sections' order"
    # A button wider than the whole strip still gets a row.
    assert settings_window._flow_rows([900, 50], 300) == [0, 1]


def test_lines_wrap_to_the_canvas_not_a_fixed_660():
    assert settings_window._line_wrap_px(703) == 660     # the 720 px default
    narrow = settings_window._line_wrap_px(560 - 17)     # dragged to minsize
    assert narrow < 520
    assert settings_window._line_wrap_px(0) == 660       # before it is mapped
    source = inspect.getsource(settings_window)
    assert "wraplength=660" not in source
    assert '.pack(side="left", padx=(0, 8))' not in source


# -- ui-comp-windows-5: the owed-work line names the drive's real state -------


def _owed_lines(monkeypatch, state):
    monkeypatch.setattr(site_mod, "drive_phrase",
                        lambda capitalised=False, **k: "Your studio drive"
                        if capitalised else "your studio drive")
    app = _FakeApp({"dashboard_url": ""}, identity=_FakeIdentity("owen"))
    app._root_absent = True
    app._root_state = state
    app.drive_unfinished_summary = lambda: "2 uploads"
    sections = settings_window.build_settings_model(_tray_snapshot(app), app)
    syncing = next(s for s in sections if s.title == "SYNCING")
    return [i.text for i in syncing.items
            if isinstance(i, settings_window.Line) and "2 uploads" in i.text]


def test_a_wedged_drive_is_not_called_disconnected_in_settings(monkeypatch):
    lines = _owed_lines(monkeypatch, root_guard_mod.ROOT_NOT_ANSWERING)
    assert len(lines) == 1
    assert "not answering" in lines[0]
    assert "disconnected" not in lines[0] and "plug it back in" not in lines[0]
    assert lines[0].startswith("Your studio drive")


def test_a_misplaced_drive_is_told_to_clear_the_leftover_folder(monkeypatch):
    lines = _owed_lines(monkeypatch, root_guard_mod.ROOT_MISPLACED)
    assert len(lines) == 1
    assert "wrong place" in lines[0] and "leftover empty folder" in lines[0]
    assert "disconnected" not in lines[0]


def test_a_pulled_drive_still_says_plug_it_back_in(monkeypatch):
    lines = _owed_lines(monkeypatch, root_guard_mod.ROOT_ABSENT)
    assert lines == ["Your studio drive was disconnected with 2 uploads still "
                     "to go - plug it back in to finish syncing"]


# -- ui-comp-windows-6: the stop release is named for its cause ---------------


def test_settings_names_the_stop_release_the_way_the_tray_does():
    guard = {"halt": {"active": True, "scope": "local"}}
    tray_words = tray.halt_release_label(guard).lstrip("► ").split(" (")[0]
    assert settings_window.CLEAR_SYNC_STOP_LABEL == tray_words.upper()
    assert ui_copy.ROUTE_ROWS[ui_copy.CLEAR_SYNC_STOP] == \
        settings_window.CLEAR_SYNC_STOP_LABEL
    assert "\"START SYNCING AGAIN\", lambda" not in inspect.getsource(settings_window)


# -- ui-comp-windows-7: the licence refusal keeps its route in the tooltip, --
# -- and Settings does not send the reader to Settings -----------------------


def _licence_sentence():
    return ("The CC Sync licence agreement has been updated (version 1.1; this "
            f"computer accepted 1.0). Open {ui_copy.ACCEPT_LICENCE_SETTINGS}.")


def test_the_tooltip_keeps_the_end_of_a_long_blocked_sentence():
    snap = {"problems": [], "signed_in": True, "require_login": True,
            "paused": False, "statuses": [],
            "sync_guard": {"blocked": {"reason": "licence_pending",
                                       "detail": _licence_sentence()}}}
    tip = tray._tooltip_text(snap)
    assert len(tip) <= 127
    assert tip.endswith(f"Open {ui_copy.ACCEPT_LICENCE_SETTINGS}.")
    assert tip.startswith("CCSync: The CC Sync licence agreement")


def test_settings_drops_the_route_to_the_button_it_is_drawn_above():
    guard = {"blocked": {"reason": "licence_pending", "detail": _licence_sentence()}}
    text = settings_window._licence_advisory(guard)
    assert "Tray >" not in text and "Open " not in text
    assert text.startswith("⚠ The CC Sync licence agreement has been updated")
    assert text.endswith("Nothing syncs until it is accepted.")


# -- ui-comp-windows-8: the destination field fits its options ----------------


def test_the_destination_field_is_wide_enough_for_the_default_folder():
    default = "Projects/2026/FF5/Civil Defence/B-roll/Editor Added/ruskin"
    width = popup.dest_combo_width([default, "Projects/2026/FF5/Civil Defence"], default)
    assert width >= len(default)
    assert popup.dest_combo_width([], "") == popup.DEST_COMBO_MIN_CHARS == 52
    assert popup.dest_combo_width(["x" * 400]) == popup.DEST_COMBO_MAX_CHARS
    source = inspect.getsource(popup.PopupDialog)
    assert "width=52" not in source
    assert "dest_combo_width(" in source


# -- logic-sync-truth-6 (a): lane C counts once, in its own direction ---------


def _sync_line_for(status):
    return tray._sync_line({"statuses": [status], "sync_guard": {}})


def test_a_lane_c_download_is_not_also_counted_as_an_upload():
    line = _sync_line_for(LaneStatus(name="lane_c_syncthing", state=STATE_SYNCING,
                                     queued=40))
    assert line == "Sync: downloading 40 files"


@pytest.mark.parametrize("detail", [
    "sending 40 file(s) (1.2 MB) to the server",
    "folder x has a problem; sending 40 file(s) (1.2 MB) to the server; P:/x",
])
def test_a_lane_c_upload_is_counted_as_one(detail):
    line = _sync_line_for(LaneStatus(name="lane_c_syncthing", state=STATE_SYNCING,
                                     queued=40, detail=detail))
    assert line == "Sync: uploading 40 files"


def test_the_outgoing_sentence_the_tray_reads_is_the_lane_s_own():
    source = (SRC / "sync" / "syncthing_lane.py").read_text(encoding="utf-8")
    assert 'f"sending {outgoing_items} file(s)' in source
    assert tray._LANE_C_SENDING.search("sending 3 file(s) (1 MB) to the server")


# -- logic-sync-truth-6, review round: a no-peer lane C names no direction ----


def test_a_no_peer_lane_c_is_waiting_not_downloading():
    # The no-peer branch sets queued=owed whether the owed files are our need
    # (a download) or the server's need of us (an upload), so the tray must
    # not name either direction. The detail is built through the lane's own
    # constant, so a rewording there cannot silently bypass this.
    from ccsync_companion.sync.syncthing_lane import NO_PEER_DETAIL
    status = LaneStatus(name="lane_c_syncthing", state=STATE_SYNCING,
                        queued=40, detail=f"{NO_PEER_DETAIL} (40 file(s) owed); P:/x")
    line = _sync_line_for(status)
    assert "downloading" not in line and "uploading" not in line
    # Owed round (logic-sync-truth-3): the only work claimed is the no-peer
    # lane's, so the line leads with waiting and names the reason.
    assert line == "Sync: waiting, not connected to the server (40 files owed)"


def test_a_no_peer_lane_c_does_not_join_another_lane_s_movement():
    from ccsync_companion.sync.syncthing_lane import NO_PEER_DETAIL
    line = tray._sync_line({"sync_guard": {}, "statuses": [
        LaneStatus(name="lane_a_video_up", state=STATE_SYNCING, queued=3),
        LaneStatus(name="lane_c_syncthing", state=STATE_SYNCING, queued=40,
                   detail=f"{NO_PEER_DETAIL} (40 file(s) owed)"),
    ]})
    assert line == "Sync: uploading 3 files"


def test_the_tray_reads_the_no_peer_sentence_from_the_lane_itself():
    from ccsync_companion.sync import syncthing_lane
    assert tray._LANE_C_NO_PEER is syncthing_lane.NO_PEER_DETAIL
    source = (SRC / "sync" / "syncthing_lane.py").read_text(encoding="utf-8")
    assert 'f"{NO_PEER_DETAIL} ({owed} file(s) owed)"' in source


# ============================================================================
# chunk 3 (2026-09-25): ui-comp-windows-9/10/11, ui-onboarding-9, ui-copy-5
# ============================================================================

from ccsync_companion import theme  # noqa: E402


# -- ui-comp-windows-9: the fixer window is held on the screen ----------------


def test_the_fixer_row_list_gives_way_to_a_narrow_screen():
    # A 1,366 px laptop and a window that asked for 1,900 px because of one
    # long path: the canvas shrinks by the overflow, the chrome keeps its size.
    width = popup.fixer_canvas_width(1800, 1900, 1366)
    assert width + (1900 - 1800) <= int(1366 * popup.FIXER_MAX_SCREEN_FRACTION)
    # A window that already fits is left alone, and so is an unreadable screen.
    assert popup.fixer_canvas_width(500, 600, 1920) == 500
    assert popup.fixer_canvas_width(1800, 1900, 0) == 1800
    # Never squeezed to nothing on an absurd screen.
    assert popup.fixer_canvas_width(1800, 1900, 100) == 200


def test_the_fixer_rows_wrap_instead_of_setting_the_window_width():
    source = inspect.getsource(popup.PopupDialog._build)
    assert "wraplength=FIXER_ROW_WRAP_PX" in source
    assert source.count("wraplength=FIXER_ROW_WRAP_PX") >= 2, \
        "both the clip name and its path must wrap"
    assert "fixer_canvas_width(" in source
    assert popup.FIXER_ROW_WRAP_PX == 620


# -- ui-comp-windows-10: the fleet-jobs sentences -----------------------------


def test_re_enabling_fleet_work_says_it_waits_for_a_restart(monkeypatch):
    said: list = []
    monkeypatch.setattr(settings_window, "_config_on_disk",
                        lambda: {"jobs_enabled": False})
    monkeypatch.setattr(settings_window, "action_write_setting",
                        lambda app, key, value, sentence: said.append((key, value, sentence)))
    items = settings_window._fleet_jobs_controls(object())
    toggle = next(i for i in items if isinstance(i, settings_window.Button)
                  and "Let the fleet use this computer" in i.label)
    toggle.on_click()
    assert said and said[0][:2] == ("jobs_enabled", True)
    assert said[0][2].endswith("Takes effect the next time CCSync starts.")


def test_the_kind_sentence_quotes_the_kind_instead_of_mangling_it():
    off = settings_window._kind_change_sentence("whisper", was_on=True)
    assert off == ("This computer will no longer do this for the fleet: "
                   "Transcribe audio (uses the graphics card). Takes effect the "
                   "next time CCSync starts.")
    on = settings_window._kind_change_sentence("peaks", was_on=False)
    assert on.startswith("This computer will now do this for the fleet: Draw audio waveforms.")


# -- ui-comp-windows-11 / ui-onboarding-9: contrast and keyboard focus --------


def _contrast(a: str, b: str) -> float:
    def lum(h):
        h = h.lstrip("#")
        c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("ground", ["BG", "FIELD", "PANEL"])
def test_secondary_text_clears_aa_for_small_text(ground):
    assert _contrast(theme.MUTED, getattr(theme, ground)) >= 4.5


@pytest.mark.parametrize("ground", ["BG", "FIELD"])
def test_an_input_outline_is_visible_against_both_sides(ground):
    assert _contrast(theme.FIELD_BORDER, getattr(theme, ground)) >= 3.0


def test_entries_and_the_dest_label_do_not_use_the_rule_colour():
    tray_src = (SRC / "tray.py").read_text(encoding="utf-8")
    assert "highlightbackground=theme.RED_DIM" not in tray_src
    assert '"  dest:", fg=theme.RED_DIM' not in inspect.getsource(popup.PopupDialog._build)


class _KeyWidget:
    made: list = []

    def __init__(self, *a, **kw):
        self.kw = kw
        self.bound: dict = {}
        self.focused = False
        self.destroyed = False
        _KeyWidget.made.append(self)

    def pack(self, *a, **k):
        return self

    def bind(self, seq, fn, *a):
        self.bound[seq] = fn

    def focus_set(self):
        self.focused = True

    def destroy(self):
        self.destroyed = True

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def _key_tk(monkeypatch):
    import tkinter

    _KeyWidget.made = []
    buttons = _Buttons()

    def _button(tk, parent, text, command, primary=True):
        w = _KeyWidget(text=text, command=command)
        buttons.append(w)
        return w

    monkeypatch.setattr(tkinter, "Tk", _KeyWidget)
    monkeypatch.setattr(tkinter, "Label", _KeyWidget)
    monkeypatch.setattr(tkinter, "Frame", _KeyWidget)
    monkeypatch.setattr(theme, "neon_button", _button)
    monkeypatch.setattr(theme, "apply_window_icon", lambda *a, **k: None)
    monkeypatch.setattr(ui_dispatch, "dispatch", lambda fn: fn())
    # What the "user" does while the dialog is up; set per test.
    _key_tk_user = {"act": lambda root, buttons: None}
    monkeypatch.setattr(ui_dispatch, "run_dialog",
                        lambda root: _key_tk_user["act"](root, buttons))
    buttons.user = _key_tk_user  # type: ignore[attr-defined]
    yield buttons


class _Buttons(list):
    pass


def test_escape_cancels_a_confirm_and_return_does_not_confirm_it(_key_tk):
    # Review round: the first version only checked that <Escape> was bound.
    # Now the key is PRESSED mid-dialog, and a control run through the OK
    # button proves the harness can see a True at all.
    _key_tk.user["act"] = lambda root, b: next(
        x for x in b if x.kw["text"] == "DELETE").kw["command"]()
    assert popup.confirm_dialog("T", "Delete everything?", ok_label="DELETE") is True

    _KeyWidget.made = []
    _key_tk.clear()

    # Recorded, not asserted, in here: confirm_dialog turns ANY exception in
    # the dialog into a safe False, which would swallow an assert.
    seen = {}

    def _escape(root, b):
        seen["return_bound"] = "<Return>" in root.bound
        seen["cancel_focused"] = next(x for x in b if x.kw["text"] == "CANCEL").focused
        root.bound["<Escape>"](None)
        seen["destroyed"] = root.destroyed
    _key_tk.user["act"] = _escape
    assert popup.confirm_dialog("T", "Delete everything?", ok_label="DELETE") is False
    assert seen == {"return_bound": False, "cancel_focused": True, "destroyed": True}


@pytest.mark.parametrize("key", ["<Return>", "<Escape>"])
def test_a_notice_can_be_dismissed_from_the_keyboard(_key_tk, key):
    seen = {}

    def _act(root, b):
        seen["focused"] = b[0].focused
        root.bound[key](None)
        seen["destroyed"] = root.destroyed
    _key_tk.user["act"] = _act
    popup.notice_dialog("T", "Done.")
    assert seen == {"focused": True, "destroyed": True}


class _FakeTkModule:
    class Button:
        def __init__(self, parent, **kw):
            self.kw = kw

        def bind(self, *a):
            pass

        def config(self, **kw):
            self.kw.update(kw)


def test_a_themed_button_can_show_keyboard_focus():
    # Review round (2026-09-25): measured on Windows with a real Tk root in
    # the foreground, highlightthickness=0 changes 0 pixels on focus; at 1,
    # Windows draws its dotted focus box. The ring must be there, and must
    # not show until the button has focus.
    btn = theme.neon_button(_FakeTkModule, None, "CANCEL", lambda: None, primary=False)
    assert int(btn.kw["highlightthickness"]) >= 1
    assert btn.kw["highlightbackground"] == theme.BG
    assert btn.kw["highlightcolor"] != theme.BG
    assert str(btn.kw.get("takefocus")) == "1"


# -- ui-copy-5: one route to Copy diagnostics ---------------------------------


def test_the_diagnostics_route_passes_through_help():
    from ccsync_companion import ui_copy as uc
    assert uc.DIAGNOSTICS == f"{uc.HELP_PAGE} > {uc.ROUTE_ROWS[uc.DIAGNOSTICS]}"
    assert uc.DIAGNOSTICS == "Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN"
    # And the button really is in the HELP section of the Settings window.
    source = inspect.getsource(settings_window)
    help_block = source[source.index("# -- [ HELP ]"):]
    assert 'Button("COPY DIAGNOSTICS FOR YOUR ADMIN"' in help_block[:400]


# ============================================================================
# owed round (2026-09-25): items other groups left in c-ui's files
# ============================================================================

import json  # noqa: E402
import os  # noqa: E402

from ccsync_companion import crash_report, fixer  # noqa: E402


# -- logic-resolve-1: a reused copy is not "copied" again ---------------------


def test_a_reused_copy_is_not_counted_in_the_copied_total(tmp_path):
    src_a = tmp_path / "a.braw"
    src_a.write_bytes(b"x" * 1000)
    src_b = tmp_path / "b.braw"
    src_b.write_bytes(b"y" * 300)
    rows = [{"file_path": str(src_a)}, {"file_path": str(src_b)}]
    results = [
        {"ok": True, "file_path": str(src_a), "copied_to": "d/a.braw",
         "reused_copy": True},
        {"ok": True, "file_path": str(src_b), "copied_to": "d/b.braw",
         "reused_copy": False},
    ]
    assert popup.fix_copied_bytes(rows, results) == 300


# -- logic-resolve-5: a relink stopped part way is its own outcome ------------


def _partial(path="a.braw"):
    return {"ok": False, "aborted": True, "partial_relink": True,
            "copied_to": "P:/Projects/x/a.braw", "relinked": 1, "file_path": path,
            "message": ("Stopped by you. a.braw was copied in and 1 of 3 clips "
                        "were repointed at the copy. Run FIX ALL again to finish "
                        "the rest.")}


def test_a_partial_relink_is_not_called_skipped_by_you():
    head = popup.summarize_fix_results([_partial()], 1, False)
    assert "skipped by you" not in head
    assert head == "0 of 1 copied in, 1 stopped part way"
    # A real skip beside it is still a skip, and nothing is counted as failed.
    skip = {"ok": False, "aborted": True, "file_path": "b.braw"}
    assert popup.summarize_fix_results([_partial(), skip], 2) == (
        "0 of 2 copied in, 1 stopped part way, 1 skipped by you")


def test_the_window_shows_the_part_way_message_and_the_undo():
    from test_popup import _bare_dialog, _row
    dialog = _bare_dialog([_row("a.braw")])
    dialog._fix_done([_partial("a.braw")])
    text = dialog.status_label.text
    assert "You skipped" not in text
    assert "half-copied files were deleted" not in text
    assert "1 of 3 clips were repointed" in text
    assert popup.UNDO_POINTER in text
    assert [r["file_path"] for r in dialog._failed_rows] == ["a.braw"], \
        "RETRY FAILED must be able to finish it"
    assert dialog._retry_btn.packed
    assert dialog.root.destroyed is False


def _relink_refused(relinked=None):
    # fixer.py's relink-failure shape (the copy landed, ReplaceClip refused).
    # Today's fixer omits "relinked" here (owed to c-resolve).
    r = {"ok": False, "file_path": "a.srt", "copied_to": "P:/Projects/x/a.srt",
         "reused_copy": False, "stays_local": False,
         "message": "copied to P:/Projects/x/a.srt but relink failed for 1 of 1 item: refused"}
    if relinked is not None:
        r["relinked"] = relinked
    return r


@pytest.mark.parametrize("relinked", [None, 0])
def test_a_copy_with_nothing_relinked_does_not_point_at_the_undo(relinked):
    # Review round (2026-09-25): nothing was journaled, so UNDO LAST FIX would
    # replay an EARLIER fix's journal.
    from test_popup import _bare_dialog, _row
    result = _relink_refused(relinked)
    assert popup.UNDO_POINTER not in popup.fix_summary_text([result], 1)
    dialog = _bare_dialog([_row("a.srt")])
    dialog._fix_done([result])
    assert popup.UNDO_POINTER not in dialog.status_label.text


def test_a_relink_failure_that_repointed_some_clips_points_at_the_undo():
    from test_popup import _bare_dialog, _row
    result = _relink_refused(relinked=2)
    assert popup.UNDO_POINTER in popup.fix_summary_text([result], 1)
    dialog = _bare_dialog([_row("a.srt")])
    dialog._fix_done([result])
    assert popup.UNDO_POINTER in dialog.status_label.text


def test_a_real_skip_still_says_nothing_was_copied():
    from test_popup import _bare_dialog, _row
    dialog = _bare_dialog([_row("b.braw")])
    dialog._fix_done([{"ok": False, "aborted": True, "file_path": "b.braw",
                       "message": "Skipped", "copied_to": None}])
    text = dialog.status_label.text
    assert "You skipped: b.braw" in text
    assert popup.UNDO_POINTER not in text


# -- logic-resolve-4: a destination outside every project says so -------------


@pytest.mark.parametrize("dest, warned", [
    ("B-roll/Editor Added/owen", True),
    ("", True),
    ("Projects/2026/FF5/Civil Defence/B-roll/Editor Added/owen", False),
    ("Assets/B-roll Archive/x", False),
])
def test_the_row_warns_before_the_copy_when_the_folder_will_not_sync(dest, warned):
    assert bool(popup.dest_stays_local_warning(dest)) is warned
    assert "\u2014" not in popup.STAYS_LOCAL_WARNING


def test_the_row_warning_follows_what_the_editor_picks():
    class _Var:
        def __init__(self, v):
            self.v = v

        def get(self):
            return self.v

    class _Label:
        def __init__(self):
            self.text, self.gridded = None, None

        def config(self, **kw):
            self.text = kw.get("text", self.text)

        def grid(self, **kw):
            self.gridded = True

        def grid_remove(self):
            self.gridded = False

    class _Combo:
        def __init__(self):
            self.bound = {}

        def bind(self, seq, fn, add=None):
            self.bound[seq] = fn

    var, label, combo = _Var("B-roll/Editor Added/owen"), _Label(), _Combo()
    popup.PopupDialog._watch_destination(object(), combo, var, label)
    assert label.gridded is True and label.text == popup.STAYS_LOCAL_WARNING
    var.v = "Projects/2026/FF5/x/B-roll"
    combo.bound["<<ComboboxSelected>>"](None)
    assert label.gridded is False
    var.v = "B-roll/typed"
    combo.bound["<KeyRelease>"](None)
    assert label.gridded is True
    # A trace would be a Tcl command no widget owns (CR-93 holder); the row
    # is watched through the combobox's own bindings.
    assert "trace_add" not in inspect.getsource(popup.PopupDialog._watch_destination)
    assert "_watch_destination(combo, var, local_warning)" in inspect.getsource(
        popup.PopupDialog._build)


def test_a_copy_that_stays_local_is_named_after_the_run():
    results = [
        {"ok": True, "file_path": "C:/card/A001.braw", "copied_to": "P:/B-roll/x/A001.braw",
         "stays_local": True, "message": "Fixed"},
        {"ok": True, "file_path": "C:/card/A002.braw", "copied_to": "P:/Projects/x/A002.braw",
         "stays_local": False, "message": "Fixed"},
    ]
    text = popup.fix_summary_text(results, 2)
    assert text.startswith("Fixed 2 of 2")
    assert "Will not sync: A001.braw." in text
    assert "A002.braw" not in text
    assert popup.UNDO_POINTER in text


def test_the_window_names_a_local_copy_when_it_stays_open():
    from test_popup import _bare_dialog, _row
    dialog = _bare_dialog([_row("a.braw"), _row("b.braw")])
    dialog._fix_done([
        {"ok": True, "file_path": "a.braw", "copied_to": "P:/B-roll/a.braw",
         "stays_local": True, "message": "Fixed"},
        {"ok": False, "file_path": "b.braw", "copied_to": None, "message": "disk full"},
    ])
    assert "Will not sync: a.braw." in dialog.status_label.text


def test_fixer_and_popup_agree_on_what_stays_local():
    # The popup's pre-copy warning and fixer's post-copy `stays_local` must be
    # the same test, or the dialog could warn about a row fixer calls synced.
    for dest in ("B-roll/x", "Projects/x", "assets/y", ""):
        assert bool(popup.dest_stays_local_warning(dest)) == \
            fixer.destination_stays_local(dest)


# -- logic-sync-truth-3: a no-peer lane C does not breathe --------------------


def _no_peer_lane_c(owed=40):
    from ccsync_companion.sync.syncthing_lane import NO_PEER_DETAIL
    return LaneStatus(name="lane_c_syncthing", state=STATE_SYNCING, queued=owed,
                      detail=f"{NO_PEER_DETAIL} ({owed} file(s) owed)")


def test_a_no_peer_lane_c_is_steady_amber_not_a_pulse():
    statuses = [_no_peer_lane_c()]
    color = tray.compute_overall_color(statuses)
    assert color == "orange", "owed files are still not 'caught up'"
    assert tray.should_pulse(color, statuses) is False
    # A lane that is really moving still pulses beside it.
    moving = [_no_peer_lane_c(), LaneStatus(name="lane_a_video_up",
                                            state=STATE_SYNCING, queued=2)]
    assert tray.should_pulse(tray.compute_overall_color(moving), moving) is True


def test_the_tooltip_says_waiting_not_syncing_for_a_no_peer_lane():
    snap = {"problems": [], "signed_in": True, "require_login": True,
            "paused": False, "statuses": [_no_peer_lane_c(40)], "sync_guard": {}}
    tip = tray._tooltip_text(snap)
    assert tip == "CCSync: waiting, not connected to the server (40 files owed)"


# -- bug-dash-ops-4 (companion): the redactor catches env-style keys ----------


@pytest.mark.parametrize("text, secret", [
    ("DASH_SESSION_SECRET=abcdef0123456789", "abcdef0123456789"),
    ("TRUENAS_PW=hunter2", "hunter2"),
    ("SYNCTHING_API_KEY: q1w2e3r4", "q1w2e3r4"),
    ("{'password': 'two words'}", "two words"),
    ('{"api_key": "sk-live-1"}', "sk-live-1"),
    ("pw=letmein", "letmein"),
    ("SECRET_PREVIOUS=oldkey99", "oldkey99"),
])
def test_env_style_and_quoted_keys_are_redacted(text, secret):
    out = crash_report.redact(text)
    assert secret not in out and "<redacted>" in out, out


def test_words_that_merely_contain_a_key_are_left_alone():
    for text in ("tokenizer=fast", "passwordless login", "dsnless=1"):
        assert crash_report.redact(text) == text
    # What was already redacted still is.
    assert "abc123" not in crash_report.redact("token=abc123")


# -- bug-dash-ops-9 (companion): two crashes in one second keep both ----------


def test_two_crashes_in_one_second_on_one_thread_keep_both(tmp_path):
    cfg = {"log_path": str(tmp_path / "companion.log")}
    report = {"when": "2026-09-25T10:00:00+00:00", "thread": "ccsync-lane"}
    first = crash_report.write_report(dict(report, n=1), cfg)
    second = crash_report.write_report(dict(report, n=2), cfg)
    assert first and second and first != second
    assert json.loads(first.read_text(encoding="utf-8"))["n"] == 1
    assert json.loads(second.read_text(encoding="utf-8"))["n"] == 2
    assert os.path.basename(second).endswith("~01.json")


def test_the_second_crash_of_a_second_is_the_newest(tmp_path):
    # Review round (2026-09-25): every reader sorts by name and takes the last
    # as newest; `<base>-1.json` sorted BEFORE `<base>.json`.
    cfg = {"log_path": str(tmp_path / "companion.log")}
    report = {"when": "2026-09-25T10:00:00+00:00", "thread": "process"}
    paths = [crash_report.write_report(dict(report, n=i), cfg) for i in range(12)]
    assert all(paths) and len(set(paths)) == 12
    assert crash_report.crash_summary(cfg)["newest"] == paths[-1].name
    recent = crash_report.recent_reports(cfg, limit=3)
    assert [r["name"] for r in recent] == [p.name for p in reversed(paths[-3:])]
    # A thread whose own name ends in a number is not read as a counter.
    other = crash_report.write_report(
        {"when": "2026-09-25T10:00:01+00:00", "thread": "Thread-1"}, cfg)
    crash_report.invalidate_summary()
    assert crash_report.crash_summary(cfg)["newest"] == other.name


def test_prune_keeps_the_latest_crashes_of_a_burst(tmp_path, monkeypatch):
    monkeypatch.setattr(crash_report, "MAX_CRASH_FILES", 3)
    cfg = {"log_path": str(tmp_path / "companion.log")}
    report = {"when": "2026-09-25T10:00:00+00:00", "thread": "process"}
    paths = [crash_report.write_report(dict(report, n=i), cfg) for i in range(12)]
    left = sorted(p.name for p in crash_report.crash_dir(cfg).glob("*.json"))
    assert left == sorted(p.name for p in paths[-3:])


# -- ui-onboarding-8 (companion): Enter presses a focused themed button -------


class _BindingTk:
    class Button:
        def __init__(self, parent, **kw):
            self.kw, self.bound = kw, {}

        def bind(self, seq, fn=None, add=None):
            self.bound[seq] = fn

        def config(self, **kw):
            self.kw.update(kw)

        def invoke(self):
            if self.kw.get("state") != "disabled":
                self.kw["command"]()


@pytest.mark.parametrize("key", ["<Return>", "<KP_Enter>"])
def test_enter_presses_a_focused_themed_button(key):
    pressed = []
    btn = theme.neon_button(_BindingTk, None, "OK", lambda: pressed.append(1))
    # "break": the root's own <Return> must not ALSO fire (notice_dialog's
    # would destroy a root the button has just destroyed).
    assert btn.bound[key](None) == "break"
    assert pressed == [1]
    btn.config(state="disabled")
    btn.bound[key](None)
    assert pressed == [1], "a disabled button ignores Enter"


# -- owed round 2 (2026-09-25): the vocabulary scan takes plurals -------------


def test_the_vocabulary_scan_catches_a_plural():
    """The shared scan's pattern was `\b(lane|machine|...)\b`, so "both sync
    lanes are failing" and "edited on two machines at once" passed it."""
    import importlib
    copy_scan = importlib.import_module("test_sweep_2026_09_04_copy")
    for text in ("both sync lanes are failing",
                 "edited on two machines at once",
                 "both rigs keep their selections"):
        assert copy_scan._WORD_RE.search(text), text
    assert not copy_scan._WORD_RE.search("the planes and machinery")


def test_the_conflict_line_says_computers():
    """tray._conflicts_line reaches the tray and the Settings window; it said
    "two machines at once", which the singular-only scan could not see."""
    import re

    for count in (1, 3):
        line = tray._conflicts_line(
            {"sync_conflicts": {"count": count, "paths": ["a/b/cut.drp"]}})
        assert "two computers at once" in line
        assert not re.search(r"\bmachines?\b", line, re.I), line
