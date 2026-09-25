"""Bug hunt 2026-09-24, fix pass wave 2 (2026-09-25), group c-app: app.py.

One section per finding. Nothing here touches a real Resolve, Tk root,
dashboard, rclone or clock: the app is built the way the 2026-09-11 hunt's
tests build it, and every thread race is made deterministic by a seam rather
than by a sleep and a hope.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

from ccsync_companion import app as app_mod
from ccsync_companion import config as config_mod
from ccsync_companion import eula as eula_mod
from ccsync_companion import site as site_mod
from ccsync_companion.app import CompanionApp

from test_bug_hunt_2026_09_11_comp_app import _app, _consolidate_app  # noqa: E402


# -- bug-comp-app-2: consolidate asks the lanes' own gate ------------------


def _consolidate_with_copy_spy(tmp_path, monkeypatch, results=None):
    from ccsync_companion import consolidate

    app, tray, lanes = _consolidate_app(
        tmp_path, monkeypatch, results or [{"ok": True, "file_path": "A001.braw"}])
    copies: list[str] = []
    real = consolidate.run_consolidation

    def _spy(*a, **k):
        copies.append("copy")
        return real(*a, **k)

    monkeypatch.setattr(consolidate, "run_consolidation", _spy)
    return app, tray, lanes, copies


def test_consolidate_refuses_during_a_fleet_halt(tmp_path, monkeypatch):
    """A halt persisted across a restart leaves every lane unstarted, so no
    stop event stands between run_once() and the NAS: the gate at the door is
    the only brake there is."""
    app, tray, lanes, copies = _consolidate_with_copy_spy(tmp_path, monkeypatch)
    app.halt.engage("the NAS is being rebuilt", scope="fleet")

    app.consolidate_project()

    assert lanes == [], "lane A/B ran through an admin's halt"
    assert copies == []
    messages = [m for m, _t in tray.notifications]
    assert any("STOPPED" in m and "Nothing was copied in" in m for m in messages), messages


def test_consolidate_refuses_behind_the_licence_gate(tmp_path, monkeypatch):
    app, tray, lanes, copies = _consolidate_with_copy_spy(tmp_path, monkeypatch)
    eula_mod.acceptance_path().unlink(missing_ok=True)
    assert app.eula_problem()

    app.consolidate_project()

    assert lanes == [] and copies == []
    assert any("licence" in m.lower() for m, _t in tray.notifications)


def test_consolidate_refuses_when_nobody_is_signed_in(tmp_path, monkeypatch):
    app, tray, lanes, copies = _consolidate_with_copy_spy(tmp_path, monkeypatch)
    app._require_login = True
    app.identity.valid = lambda: False

    app.consolidate_project()

    assert lanes == [] and copies == []
    assert any("Sign in" in m for m, _t in tray.notifications)


def test_a_halt_landing_during_the_copy_skips_the_upload_and_says_so(
        tmp_path, monkeypatch):
    """The copy can take hours. A halt engaged meanwhile must stop the upload
    and the toast must not say "Copy & upload finished"."""
    from ccsync_companion import consolidate

    app, tray, lanes = _consolidate_app(tmp_path, monkeypatch, [])

    def _copy_then_halt(*a, **k):
        app.halt.engage("stopped mid-copy", scope="fleet")
        return [{"ok": True, "file_path": "A001.braw"}]

    monkeypatch.setattr(consolidate, "run_consolidation", _copy_then_halt)

    app.consolidate_project()

    assert lanes == []
    messages = [m for m, _t in tray.notifications]
    assert not any("Copy & upload finished" in m for m in messages), messages
    assert any("upload did not run" in m and "STOPPED" in m for m in messages), messages


def test_a_clean_consolidate_still_uploads(tmp_path, monkeypatch):
    app, tray, lanes, copies = _consolidate_with_copy_spy(tmp_path, monkeypatch)
    app.consolidate_project()
    assert copies == ["copy"] and "lane_a" in lanes
    assert any("Copy & upload finished" in m for m, _t in tray.notifications)


# -- bug-comp-app-3: the admin's diagnostics ask is stamped on SUCCESS ------


def _diag_reply(requested_at: str) -> dict:
    return {"ok": True, "commands": {"diagnostics": {
        "requested_by": "alex", "requested_at": requested_at}}}


class _Poster:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self, text, trigger="button"):
        self.calls += 1
        return self.answers.pop(0) if self.answers else True


def _diag_app(tmp_path, poster):
    app = _app(tmp_path)
    app._notify_tray = lambda *a, **kw: None
    app.editor_identity = lambda: "owen"
    app.build_diagnostics = lambda: "bundle"
    app.reporter.post_diagnostics = poster
    app._upload_diagnostics_async = lambda trigger: app._upload_diagnostics(trigger)
    return app


def test_a_failed_upload_is_retried_by_the_standing_ask(tmp_path, monkeypatch):
    """HEAD wrote applied_request BEFORE the upload and ignored its answer, so
    one timed-out POST meant the ask was never answered at all."""
    poster = _Poster([False, True])
    app = _diag_app(tmp_path, poster)
    stamp = "2026-09-25T10:00:00+00:00"

    app._apply_diagnostics_request(_diag_reply(stamp))
    assert poster.calls == 1
    assert app._read_diagnostics_state().get("applied_request") in (None, "")

    # Inside the floor: the redelivery waits, it does not hammer the uplink.
    app._apply_diagnostics_request(_diag_reply(stamp))
    assert poster.calls == 1

    # Past the floor: the redelivery IS the retry.
    now = time.time()
    monkeypatch.setattr(app_mod.time, "time",
                        lambda: now + app_mod.DIAGNOSTICS_REQUEST_RETRY_SECONDS + 1)
    app._apply_diagnostics_request(_diag_reply(stamp))
    assert poster.calls == 2
    assert app._read_diagnostics_state().get("applied_request") == stamp

    # Answered: every later redelivery of the same ask is refused.
    app._apply_diagnostics_request(_diag_reply(stamp))
    assert poster.calls == 2


def test_a_signed_out_machine_does_not_burn_the_ask(tmp_path):
    poster = _Poster([True])
    app = _diag_app(tmp_path, poster)
    app.editor_identity = lambda: None
    app._apply_diagnostics_request(_diag_reply("2026-09-25T10:00:00+00:00"))
    assert poster.calls == 0
    assert app._read_diagnostics_state().get("applied_request") in (None, "")


def test_one_ask_in_flight_is_not_started_twice(tmp_path):
    app = _diag_app(tmp_path, _Poster([True]))
    started: list[str] = []
    app._upload_diagnostics_async = started.append   # never completes
    stamp = "2026-09-25T10:00:00+00:00"
    for _ in range(3):
        app._apply_diagnostics_request(_diag_reply(stamp))
    assert started == ["admin_request"]


# -- bug-comp-core-3: the site manifest is kept current ---------------------


def test_the_site_manifest_is_refreshed_for_the_life_of_the_process(
        tmp_path, monkeypatch):
    """HEAD fetched it once at start: a companion started before the tailnet
    was up never had it, and a flag flipped later never reached a running
    tray."""
    app = _app(tmp_path)
    answers = [None, {"org_name": "Studio", "features": {"auto_update": True}},
               {"org_name": "Studio", "features": {"auto_update": False}}]
    saved: list[dict] = []
    monkeypatch.setattr(site_mod, "fetch_site",
                        lambda url, **k: answers.pop(0) if answers else None)
    monkeypatch.setattr(site_mod, "save_site", lambda site, path=None: saved.append(site))
    waits: list[float] = []

    class _Stop:
        def wait(self, seconds):
            waits.append(seconds)
            return len(waits) >= 3

    app._stop_event = _Stop()
    app._site_refresh_loop("http://dash.example:8480")

    assert [s["features"]["auto_update"] for s in saved] == [True, False]
    assert waits == [app_mod.SITE_REFRESH_RETRY_SECONDS,
                     app_mod.SITE_REFRESH_SECONDS, app_mod.SITE_REFRESH_SECONDS]


def test_a_refresh_that_raises_keeps_the_loop_alive(tmp_path, monkeypatch):
    app = _app(tmp_path)

    def boom(url, **k):
        raise OSError("no route to host")

    monkeypatch.setattr(site_mod, "fetch_site", boom)
    waits: list[float] = []

    class _Stop:
        def wait(self, seconds):
            waits.append(seconds)
            return len(waits) >= 2

    app._stop_event = _Stop()
    app._site_refresh_loop("http://dash.example:8480")
    assert waits == [app_mod.SITE_REFRESH_RETRY_SECONDS] * 2


# -- bug-comp-app-4: the companion half of the relink-done answer -----------


def test_the_relink_done_answer_is_a_plain_success(tmp_path):
    """The dashboard half is d-db's (bug-wire-1): a later `ok` answer with no
    state and no relink_pending clears relink_pending on an applied row. This
    pins the companion half of that contract: the second answer carries
    exactly that shape."""
    app = _app(tmp_path)
    app._queue_file_move_answer(7, True, "moved; relinked 1 clip")
    [answer] = app._file_move_results()
    assert answer["ok"] is True
    assert "state" not in answer and "relink_pending" not in answer


# -- bug-comp-app-5: one report reply at a time -----------------------------


def test_an_off_cycle_reply_waits_for_the_one_being_applied(tmp_path):
    app = _app(tmp_path)
    inside = {"now": 0, "max": 0}
    entered = threading.Event()

    def _slow_consumer(resp):
        inside["now"] += 1
        inside["max"] = max(inside["max"], inside["now"])
        entered.set()
        time.sleep(0.3)
        inside["now"] -= 1

    app._apply_diagnostics_request = _slow_consumer
    first = threading.Thread(target=app._on_report_response, args=({},))
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=app._on_report_response, args=({},))
    second.start()
    first.join(5)
    second.join(5)
    assert inside["max"] == 1, "two replies were fanned out at once"


# -- bug-comp-app-6 / bug-wire-6: filter and append under one hold ----------


class _SwapBetweenLoadAndAppend(CompanionApp):
    """The race exactly: the reporter's swap lands AFTER the queuer has
    loaded `self._file_move_answers` and BEFORE it appends to what it loaded.
    The second read of the attribute (the append's) starts the drain on
    another thread and gives it a moment; if the queuer holds the lock there,
    the drain waits for it and sees the answer, and if it does not, the drain
    takes the list and the append lands in an orphan."""

    @property
    def _file_move_answers(self):
        value = self.__dict__["_fma_store"]
        self.__dict__["_fma_reads"] += 1
        if self.__dict__["_fma_reads"] == 2:
            thread = threading.Thread(
                target=lambda: self.__dict__["_fma_drained"].extend(
                    self._file_move_results()))
            self.__dict__["_fma_threads"].append(thread)
            thread.start()
            thread.join(0.5)
        return value

    @_file_move_answers.setter
    def _file_move_answers(self, value):
        self.__dict__["_fma_store"] = value


def test_an_answer_queued_while_the_reporter_drains_is_not_lost(tmp_path):
    app = _app(tmp_path)
    app.__dict__["_fma_store"] = list(app.__dict__.pop("_file_move_answers", []))
    app.__dict__.update(_fma_reads=0, _fma_drained=[], _fma_threads=[])
    app.__class__ = _SwapBetweenLoadAndAppend
    app._queue_file_move_answer(3, True, "moved; relinked")
    for thread in app.__dict__["_fma_threads"]:
        thread.join(5)
    everything = app.__dict__["_fma_drained"] + list(app.__dict__["_fma_store"])
    assert [a["id"] for a in everything] == [3], everything


# -- bug-comp-app-7: a stale pid that is not a companion -------------------


def test_a_live_pid_that_is_not_a_companion_is_not_a_holder():
    assert app_mod._pid_looks_like_companion(
        812, platform="darwin", ps_fn=lambda pid: "/usr/libexec/logd") is False
    assert app_mod._pid_looks_like_companion(
        812, platform="darwin",
        ps_fn=lambda pid: "/Applications/CCSync.app/Contents/MacOS/ccsync-companion"
    ) is True
    assert app_mod._pid_looks_like_companion(
        812, platform="linux",
        ps_fn=lambda pid: "/usr/bin/python3 -m ccsync_companion") is True
    # Cannot tell: fail safe, as _pid_is_alive does.
    assert app_mod._pid_looks_like_companion(
        812, platform="darwin", ps_fn=lambda pid: None) is True
    # The Windows lock file is the mutex's fallback and is left as it was.
    assert app_mod._pid_looks_like_companion(
        812, platform="win32", ps_fn=lambda pid: "notepad.exe") is True


def test_a_reused_pid_after_a_reboot_does_not_lock_the_mac_out(
        monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "cc")
    monkeypatch.setattr(app_mod, "_single_instance_token", None)
    (tmp_path / "cc").mkdir(parents=True)
    (tmp_path / "cc" / app_mod._SINGLE_INSTANCE_LOCKFILE).write_text(
        "812", encoding="utf-8")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(app_mod, "_pid_is_alive", lambda pid: True)
    monkeypatch.setattr(app_mod, "_ps_command", lambda pid: "/usr/sbin/syslogd")
    assert app_mod._acquire_lock_file() is True

    # A real companion holding it is still refused.
    (tmp_path / "cc" / app_mod._SINGLE_INSTANCE_LOCKFILE).write_text(
        "812", encoding="utf-8")
    monkeypatch.setattr(app_mod, "_ps_command",
                        lambda pid: "/Applications/CCSync.app/Contents/MacOS/ccsync-companion")
    assert app_mod._acquire_lock_file() is False


def test_a_companion_at_an_owner_chosen_path_still_holds_the_slot(
        monkeypatch, tmp_path):
    """Review round: macos_bootstrap.sh --companion-path lets the binary live
    at a path with no "ccsync" in it. A live companion there must still
    refuse a second instance."""
    exe = "/Applications/Sync Tools/companion"
    own = [exe]
    assert app_mod._pid_looks_like_companion(
        812, platform="darwin", ps_fn=lambda pid: exe, own_executables=own) is True
    assert app_mod._pid_looks_like_companion(
        812, platform="darwin", ps_fn=lambda pid: exe + " --supervise",
        own_executables=own) is True
    # Launched by basename (PATH lookup) still matches.
    assert app_mod._pid_looks_like_companion(
        812, platform="darwin", ps_fn=lambda pid: "companion",
        own_executables=own) is True
    # A different daemon whose name merely starts the same is not us.
    assert app_mod._pid_looks_like_companion(
        812, platform="darwin", ps_fn=lambda pid: "/usr/libexec/companiond",
        own_executables=own) is False
    assert app_mod._pid_looks_like_companion(
        812, platform="darwin", ps_fn=lambda pid: "/usr/sbin/syslogd",
        own_executables=own) is False

    # End to end through _acquire_lock_file, with the frozen executable
    # resolved from sys itself (not the seam).
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", exe)
    monkeypatch.setattr(sys, "argv", [exe])
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "cc")
    monkeypatch.setattr(app_mod, "_single_instance_token", None)
    (tmp_path / "cc").mkdir(parents=True)
    (tmp_path / "cc" / app_mod._SINGLE_INSTANCE_LOCKFILE).write_text(
        "812", encoding="utf-8")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(app_mod, "_pid_is_alive", lambda pid: True)
    monkeypatch.setattr(app_mod, "_ps_command", lambda pid: exe)
    assert app_mod._acquire_lock_file() is False


def test_from_source_a_bare_python_is_not_our_executable(monkeypatch):
    """Unfrozen, sys.executable is python: matching on it would call every
    python process a companion. The `-m ccsync_companion` token covers
    source runs instead."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert app_mod._own_executables() == []


# -- ui-comp-windows-3: the licence as a person reads it --------------------


def test_the_licence_dialog_shows_no_authoring_comment_or_markup(
        tmp_path, monkeypatch):
    from ccsync_companion import popup

    document = eula_mod.bundled_text()
    assert "<!--" in document, "the fixture this test is about has changed"
    shown: list[str] = []
    monkeypatch.setattr(popup, "licence_dialog",
                        lambda title, intro, doc, **k: shown.append(doc) or False)
    app = _app(tmp_path)
    app._notify_tray = lambda *a, **kw: None
    app._show_licence_dialog()

    [text] = shown
    # The authoring comment is gone. (The body's own inline TODO(legal)
    # markers are the document's CONTENT, an owner/counsel decision.)
    assert "<!--" not in text and "NOT YET EXECUTABLE" not in text
    assert "almost certainly NOT" not in text
    assert "EULA-VERSION" not in text
    assert "**" not in text
    assert not any(line.lstrip().startswith("#") for line in text.splitlines())
    assert chr(0x2014) not in text
    assert "End User Licence Agreement" in text
    # Display only: the text the acceptance is recorded against is untouched.
    assert eula_mod.bundled_text() == document
    assert eula_mod.parse_version(document) == eula_mod.EULA_VERSION


# -- owed round (2026-09-25) ------------------------------------------------
#
# Items other groups' builders fixed on their side and left for app.py.


def _signed_in_app(tmp_path, reply, *, keep_reply_attr=True):
    """An app whose IdentityManager.sign_in succeeds with `reply` as the
    verify result's upgrade keys, and whose post-sign-in plumbing is inert."""
    app = _app(tmp_path)

    def _sign_in(username, password):
        app.identity.last_upgrade_info = reply.get("upgrade")
        if keep_reply_attr:
            app.identity.last_upgrade_reply = dict(reply)
        return True, None

    app.identity.sign_in = _sign_in
    if not keep_reply_attr and hasattr(app.identity, "last_upgrade_reply"):
        # An identity double from before bug-comp-core-4 has no such key.
        app.identity.last_upgrade_reply = None
    app._apply_identity_role = lambda: None
    app.on_signed_in = lambda: None
    return app


def test_a_sign_in_whose_verify_names_a_reason_keeps_a_standing_refusal(tmp_path):
    """bug-comp-core-4 / bug-wire-4: sign_in rebuilt {"upgrade": None} from
    the verify reply, which note_report_response reads as "nothing to take"
    and clears a refusal on. A dashboard WITHHOLDING the refused build never
    re-offers it, so the machine's `[ REFUSING ...]` state was gone for good."""
    app = _signed_in_app(tmp_path, {"upgrade": None,
                                    "upgrade_none_reason": "retracted"})
    app.upgrade._note_refusal("0.0.1", "signature did not verify")
    assert app.upgrade.refusal() is not None

    ok, _err = app.sign_in("owen", "pw")

    assert ok
    assert app.upgrade.refusal() is not None, "sign-in cleared a standing refusal"


def test_a_sign_in_with_no_offer_and_no_reason_still_clears(tmp_path):
    """The comp-ytdl-jobs-1 rule is kept: a reply with neither key is the
    dashboard saying there is nothing to take."""
    app = _signed_in_app(tmp_path, {"upgrade": None, "upgrade_none_reason": None})
    app.upgrade._note_refusal("0.0.1", "signature did not verify")

    assert app.sign_in("owen", "pw")[0]
    assert app.upgrade.refusal() is None


def test_a_sign_in_with_an_identity_that_keeps_no_reply_still_works(tmp_path):
    app = _signed_in_app(tmp_path, {"upgrade": None}, keep_reply_attr=False)
    seen: list = []
    app.upgrade.note_report_response = seen.append
    assert app.sign_in("owen", "pw")[0]
    assert seen == [{"upgrade": None}]


def test_the_no_ffmpeg_sentence_names_ffprobe_too():
    """bug-comp-media-5: proxy_gen's gate now also stops on a missing
    ffprobe under STATE_NO_FFMPEG, so "ffmpeg is not installed" was untrue
    on a machine that has ffmpeg."""
    from ccsync_companion import proxy_gen

    note = app_mod._proxy_state_note(proxy_gen.STATE_NO_FFMPEG)
    assert "ffprobe" in note and "ffmpeg" in note
    assert "—" not in note  # no em dash in visible text


def _switched_project_name(calls: list):
    """current_project_name as it behaves 5 s after a switch from A to B:
    the 20 s cache still says A; only a fresh read (max_age=0) sees B."""
    def _name(max_age=20.0):
        calls.append(max_age)
        return "B" if max_age == 0.0 else "A"
    return _name


def test_the_canon_relink_limiter_charges_the_project_open_now(tmp_path, monkeypatch):
    """bug-comp-resolve-2: the first unprompted burst after a switch spent
    the PREVIOUS project's daily allowance."""
    from ccsync_companion import resolve_bridge, resolve_journal

    app = _app(tmp_path)
    calls: list = []
    charged: list = []
    monkeypatch.setattr(resolve_bridge, "media_pool_item_is_reachable", lambda item: True)
    monkeypatch.setattr(resolve_bridge, "current_project_name",
                        _switched_project_name(calls))
    monkeypatch.setattr(resolve_journal, "allow_automatic",
                        lambda project, kind: charged.append((project, kind)) or False)

    app._handle_non_canonical(
        [{"file_path": r"D:\Stock\A00001.mov", "media_pool_item": object()}])

    assert charged == [("B", "canon-relink")]


def test_the_proxy_relink_limiter_charges_the_project_open_now(tmp_path, monkeypatch):
    from ccsync_companion import proxy_relink, resolve_bridge, resolve_journal

    app = _app(tmp_path)
    app._local_root_is_broken = lambda: False
    calls: list = []
    charged: list = []
    monkeypatch.setattr(proxy_relink, "plan_relinks", lambda *a, **k: [object()])
    monkeypatch.setattr(resolve_bridge, "current_project_name",
                        _switched_project_name(calls))
    monkeypatch.setattr(resolve_journal, "allow_automatic",
                        lambda project, kind: charged.append((project, kind)) or False)
    applied: list = []
    monkeypatch.setattr(proxy_relink, "apply_relinks",
                        lambda *a, **k: applied.append(a))

    app._relink_proxies_once([{"file_path": "x"}])

    assert charged == [("B", "auto-proxy-relink")]
    assert applied == [], "a refused pass must not relink"


def test_the_ingest_picker_is_handed_the_apps_popup_lock(tmp_path, monkeypatch):
    """bug-comp-ui-1: popup's picker takes this lock non-blocking, but only
    if the app registers it; unregistered, a picker could open beside the
    fixer popup and apply_upgrade's stand-down could not see it."""
    from ccsync_companion import popup

    monkeypatch.setattr(popup, "_picker_popup_lock", None)
    app = _app(tmp_path)
    assert popup._picker_popup_lock is app._popup_active_lock


# ====================================================================
# Owed round 3 (2026-09-25): "sync lanes" in copy the widened scan reads
# ====================================================================

import types as _types  # noqa: E402

import pytest  # noqa: E402

from ccsync_companion.sync.base import STATE_ERROR as _STATE_ERROR  # noqa: E402


class _FailingLane:
    def __init__(self, name, last_error):
        self._status = _types.SimpleNamespace(name=name, state=_STATE_ERROR,
                                              last_error=last_error)

    def status(self):
        return self._status


@pytest.mark.parametrize("last_error", [None, "rclone: something odd"])
def test_the_transport_offline_sentence_says_upload_and_proxy_download(
        last_error, monkeypatch):
    """HEAD: "This computer cannot reach the server: both sync lanes are
    failing" on the tray, the Settings window and the dashboard's machine row.
    Both the no-error branch and the classifier-raised fallback said it."""
    from ccsync_companion import tray as tray_mod
    from ccsync_companion.app import CompanionApp

    def boom(_text):
        raise RuntimeError("classifier broke")

    monkeypatch.setattr(tray_mod, "classify_lane_error", boom)
    stub = _types.SimpleNamespace(_lane_a=_FailingLane("lane_a", last_error),
                                  _lane_b=_FailingLane("lane_b", last_error))
    detail, since = CompanionApp._blocked_candidate(stub, "transport_offline", {})
    assert detail == ("This computer cannot reach the server: upload and proxy "
                      "download are both failing"), detail
    assert since is None


def test_the_broll_readme_says_upload_and_proxy_download():
    from ccsync_companion import broll_server

    text = broll_server.README_SNIPPET
    assert "sync lanes" not in text
    assert "the same rclone remote that upload and proxy download use" in " ".join(
        text.split())
    assert " -- " not in text and "—" not in text
