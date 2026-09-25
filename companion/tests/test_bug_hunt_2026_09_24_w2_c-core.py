"""Wave 2 of the 2026-09-24 hunt's fix pass, group c-core.

bug-comp-core-4: sign-in's /verify carried no `arch` and dropped
    `upgrade_none_reason`.
bug-comp-core-6: a remint of an unreadable machine id never reached the
    reporter's cached "" until the tray restarted.
bug-comp-core-7: a sign-in whose reply token is unusable overwrote a working
    identity.json (and dropped the in-memory identity).
"""

from __future__ import annotations

import base64
import time

from ccsync_companion import identity as identity_mod
from ccsync_companion import machine as machine_mod
from ccsync_companion import upgrade as upgrade_mod
from ccsync_companion.identity import (
    IdentityManager,
    load_identity,
    save_identity,
    verify_credentials,
)
from ccsync_companion.reporter import DashboardReporter


def _token(username="owen", expires_epoch=None):
    if expires_epoch is None:
        expires_epoch = int(time.time()) + 3600
    user = base64.urlsafe_b64encode(username.encode()).decode().rstrip("=")
    return f"v2.identity.{user}.{expires_epoch}.deadbeef"


def _mgr(tmp_path, monkeypatch, http_post):
    monkeypatch.setattr(identity_mod.config_mod, "CONFIG_DIR", tmp_path)
    return IdentityManager({"dashboard_url": "http://dash.example.com"},
                           http_post=http_post)


# -- bug-comp-core-4 ----------------------------------------------------


def test_verify_sends_arch_like_the_report_does():
    seen = {}

    def fake_post(url, data, headers, timeout):
        seen.update(data)
        return {"ok": True, "username": "owen", "token": _token()}

    verify_credentials("http://dash.example.com", "owen", "pw", http_post=fake_post)
    assert seen.get("arch") == upgrade_mod.arch_key()
    assert seen["arch"]


def test_verify_forwards_upgrade_none_reason():
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "owen", "token": _token(),
                "upgrade_none_reason": "retracted"}

    result = verify_credentials("http://dash.example.com", "owen", "pw", http_post=fake_post)
    assert result["upgrade_none_reason"] == "retracted"


def test_verify_reason_absent_from_an_older_dashboard_is_none():
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "owen", "token": _token()}

    result = verify_credentials("http://dash.example.com", "owen", "pw", http_post=fake_post)
    assert result["upgrade_none_reason"] is None


def test_sign_in_keeps_the_whole_upgrade_reply_for_note_report_response(tmp_path, monkeypatch):
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "owen", "token": _token(),
                "upgrade_none_reason": "needs_newer_dashboard"}

    mgr = _mgr(tmp_path, monkeypatch, fake_post)
    ok, _ = mgr.sign_in("owen", "pw")
    assert ok
    assert mgr.last_upgrade_reply == {"upgrade": None,
                                      "upgrade_none_reason": "needs_newer_dashboard"}
    assert mgr.last_upgrade_info is None


def _older_version() -> str:
    from ccsync_companion import config as config_mod

    parts = [int(p) for p in config_mod.VERSION.split(".")[:3]]
    for index in range(len(parts) - 1, -1, -1):
        if parts[index] > 0:
            parts[index] -= 1
            return ".".join(str(p) for p in parts)
    raise AssertionError("VERSION has no older neighbour")


def test_the_kept_reply_does_not_clear_a_standing_refusal(tmp_path, monkeypatch):
    """The end the reply is for: UpgradeManager's clear rule (comp-app-3)
    keeps a refusal when the reply names a reason. The bare
    {"upgrade": last_upgrade_info} app.sign_in builds at HEAD clears it,
    which is the half OWED to c-app."""
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "owen", "token": _token(),
                "upgrade_none_reason": "retracted"}

    mgr = _mgr(tmp_path, monkeypatch, fake_post)
    assert mgr.sign_in("owen", "pw")[0]

    manager = upgrade_mod.UpgradeManager({"dashboard_url": "http://dash.example"},
                                         floor_file=tmp_path / "upgrade_floor.json")
    manager._note_refusal(_older_version(), "signature did not verify")
    manager.note_report_response(mgr.last_upgrade_reply)
    assert manager.refusal() is not None

    manager.note_report_response({"upgrade": mgr.last_upgrade_info})
    assert manager.refusal() is None


# -- bug-comp-core-7 ----------------------------------------------------


def test_unusable_sign_in_reply_leaves_the_working_identity_on_disk(tmp_path, monkeypatch):
    good = _token(username="owen")
    monkeypatch.setattr(identity_mod.config_mod, "CONFIG_DIR", tmp_path)
    save_identity(tmp_path / "identity.json", "owen", good, report_token="r" * 30)

    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "someone", "token": "v3.shape.this.build.cannot"}

    mgr = IdentityManager({"dashboard_url": "http://dash.example.com"}, http_post=fake_post)
    assert mgr.valid()
    ok, error = mgr.sign_in("someone", "pw")
    assert ok is False and error
    # Nothing changed: not on disk, not in memory.
    assert load_identity(tmp_path / "identity.json")["token"] == good
    assert mgr.valid() is True
    assert mgr.username == "owen"
    assert mgr.last_upgrade_reply is None
    # And a fresh start still reads a signed-in machine.
    again = IdentityManager({"dashboard_url": "http://dash.example.com"})
    assert again.valid() is True


def test_expired_sign_in_reply_does_not_write_the_file(tmp_path, monkeypatch):
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "owen",
                "token": _token(expires_epoch=int(time.time()) - 60)}

    mgr = _mgr(tmp_path, monkeypatch, fake_post)
    ok, _ = mgr.sign_in("owen", "pw")
    assert ok is False
    assert not (tmp_path / "identity.json").exists()


# -- bug-comp-core-6 ----------------------------------------------------


def test_reporter_rereads_the_machine_id_after_a_remint(tmp_path):
    answers = iter(["", "", "newid"])
    calls = []

    def getter():
        calls.append(1)
        return next(answers)

    rep = DashboardReporter(lambda: [], {"dashboard_url": "http://d", "dashboard_token": "t"},
                            http_post=lambda *a: {}, get_machine_id=getter)
    assert rep._machine_id() is None
    assert rep._machine_id() is None
    assert len(calls) == 1  # the empty answer is still cached between remints

    # An unreadable machine.json, repaired the way Settings does it.
    target = tmp_path / "machine.json"
    target.write_bytes(b"\x00\x00not json")
    assert machine_mod.machine_id_unreadable(target)
    minted = machine_mod.remint(target)
    assert minted

    # The getter's second answer is still "" (the fake is not the real file),
    # so re-read once more: what matters is that it IS re-read.
    assert rep._machine_id() is None
    assert len(calls) == 2
    machine_mod._note_remint("x")
    assert rep._machine_id() == "newid"
    assert len(calls) == 3


def test_remint_of_a_readable_file_still_invalidates(tmp_path):
    target = tmp_path / "machine.json"
    existing = machine_mod.machine_id(target)
    before = machine_mod.remint_generation()
    assert machine_mod.remint(target) == existing
    assert machine_mod.remint_generation() == before + 1


def test_failed_remint_does_not_bump_the_generation(tmp_path, monkeypatch):
    target = tmp_path / "machine.json"
    target.write_bytes(b"\x00garbage")
    monkeypatch.setattr(machine_mod, "machine_id",
                        lambda path=None, create=True: "")
    before = machine_mod.remint_generation()
    assert machine_mod.remint(target) == ""
    assert machine_mod.remint_generation() == before


# -- owed round: bug-wire-3 (from d-api) ------------------------------------


def _lane_payload(status, queue_info=None):
    from ccsync_companion.reporter import DashboardReporter as _Rep
    rep = _Rep(lambda: [status],
               {"dashboard_url": "http://d", "dashboard_token": "t"},
               http_post=lambda *a: {},
               get_queue_info=queue_info)
    return rep._build_payload()


def test_long_lane_strings_are_capped_to_what_an_older_dashboard_accepts():
    from ccsync_companion.sync.base import STATE_ERROR, LaneStatus
    status = LaneStatus(
        name="lane_a_video_up", state=STATE_ERROR,
        last_error="e" * 5000, detail="d" * 900, current_project="p" * 900,
        transfers=[{"name": "n" * 900, "direction": "upload-and-more-than-16",
                    "project_slug": "s" * 300, "bytes_done": 1}] * 300,
    )
    payload = _lane_payload(status, queue_info=lambda: ([], "q" * 900))
    lane = payload["lanes"][0]
    # The dashboard's caps (api.LaneReportIn / TransferIn), which RAISE on
    # 0.7.58 and older: one character over 422s the whole report.
    assert len(lane["last_error"]) == 2000
    assert len(lane["detail"]) == 500
    assert len(lane["current_project"]) == 512
    assert len(lane["transfers"]) == 256
    t = lane["transfers"][0]
    assert len(t["name"]) == 512 and len(t["project_slug"]) == 128
    assert len(t["direction"]) == 16 and t["bytes_done"] == 1
    assert len(payload["current_project"]) == 512


def test_short_and_absent_lane_strings_pass_through_unchanged():
    from ccsync_companion.sync.base import LaneStatus
    status = LaneStatus(name="lane_b_proxy_down", last_error=None, detail="",
                        current_project=None,
                        transfers=[{"name": "a.mov", "direction": "download"}])
    payload = _lane_payload(status, queue_info=lambda: ([], None))
    lane = payload["lanes"][0]
    assert lane["last_error"] is None
    assert lane["detail"] is None
    assert lane["current_project"] is None
    assert lane["transfers"] == [{"name": "a.mov", "direction": "download"}]
    assert payload["current_project"] is None


def test_the_lane_caps_mirror_the_dashboards_declared_caps():
    """The mirror only helps while it matches: read the dashboard's own model
    when that package is importable from this checkout (it is not in the
    companion venv, so fall back to the source text)."""
    import re
    from pathlib import Path
    from ccsync_companion import reporter as rep_mod
    api = (Path(__file__).resolve().parents[2] / "dashboard" / "src"
           / "ccsync_dashboard" / "api.py")
    if not api.exists():
        import pytest
        pytest.skip("no dashboard checkout beside the companion")
    text = api.read_text(encoding="utf-8")
    lane = text[text.index("class LaneReportIn(BaseModel):"):]
    lane = lane[:lane.index("\nclass ")]
    transfer = text[text.index("class TransferIn(BaseModel):"):]
    transfer = transfer[:transfer.index("\nclass ")]

    def cap(block, field):
        m = re.search(rf"\n\s+{field}: [^\n]*max_length=(\d+)", block)
        assert m, field
        return int(m.group(1))

    assert cap(lane, "last_error") == rep_mod.LANE_LAST_ERROR_MAX
    assert cap(lane, "detail") == rep_mod.LANE_DETAIL_MAX
    assert cap(lane, "current_project") == rep_mod.LANE_CURRENT_PROJECT_MAX
    assert cap(lane, "transfers") == rep_mod.LANE_TRANSFERS_MAX
    assert cap(transfer, "name") == rep_mod.TRANSFER_NAME_MAX
    assert cap(transfer, "project_slug") == rep_mod.TRANSFER_PROJECT_SLUG_MAX
    assert cap(transfer, "direction") == rep_mod.TRANSFER_DIRECTION_MAX
    completed = text[text.index("class CompletedIn(BaseModel):"):]
    completed = completed[:completed.index("\nclass ")]
    assert cap(completed, "name") == rep_mod.COMPLETED_NAME_MAX
    assert cap(completed, "direction") == rep_mod.COMPLETED_DIRECTION_MAX
    assert cap(completed, "lane") == rep_mod.COMPLETED_LANE_MAX
    assert cap(completed, "at") == rep_mod.COMPLETED_AT_MAX
    # The report's own list cap (ReportIn.completed) must not be below what
    # the companion sends.
    m = re.search(
        r"\n\s+completed: list\[CompletedIn\][^\n]*max_length=(\d+)", text)
    assert m and int(m.group(1)) >= rep_mod.COMPLETED_MAX


def test_a_long_completion_name_is_capped_like_its_transfer():
    """Review round (bug-wire-3): a finished file's HISTORY record carries the
    same per-file name as its transfer plus a project prefix, so a >512-char
    path that was cut while live went out raw once it finished and 422'd that
    report on a 0.7.58-or-older dashboard."""
    from ccsync_companion.reporter import DashboardReporter as _Rep
    from ccsync_companion.sync.base import LaneStatus
    done = [{"name": "Proj/" + "n" * 900, "direction": "u" * 40,
             "lane": "l" * 100, "at": "t" * 100, "extra": 7}] * 300
    rep = _Rep(lambda: [LaneStatus(name="lane_a_video_up")],
               {"dashboard_url": "http://d", "dashboard_token": "t"},
               http_post=lambda *a: {},
               get_completions=lambda: iter(done))
    payload = rep._build_payload()
    completed = payload["completed"]
    assert len(completed) == 200
    c = completed[0]
    assert len(c["name"]) == 512 and c["name"].startswith("Proj/")
    assert len(c["direction"]) == 16
    assert len(c["lane"]) == 64 and len(c["at"]) == 64
    assert c["extra"] == 7
    # The drained source is not mutated (the lane may still hold it).
    assert len(done[0]["name"]) == 905


def test_short_completions_pass_through_unchanged():
    from ccsync_companion.reporter import DashboardReporter as _Rep
    from ccsync_companion.sync.base import LaneStatus
    done = [{"name": "Proj/a.mov", "direction": "upload",
             "lane": "lane_a_video_up", "at": "2026-09-25T10:00:00Z"}]
    rep = _Rep(lambda: [LaneStatus(name="lane_a_video_up")],
               {"dashboard_url": "http://d", "dashboard_token": "t"},
               http_post=lambda *a: {},
               get_completions=lambda: list(done))
    assert rep._build_payload()["completed"] == done
    empty = _Rep(lambda: [LaneStatus(name="lane_a_video_up")],
                 {"dashboard_url": "http://d", "dashboard_token": "t"},
                 http_post=lambda *a: {},
                 get_completions=lambda: [])
    assert "completed" not in empty._build_payload()


# -- owed round: ui-copy-4 (from c-ytdl) -------------------------------------


def test_the_unusable_sign_in_reply_says_computer(tmp_path, monkeypatch):
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "owen", "token": "v3.shape.this.build.cannot"}

    mgr = _mgr(tmp_path, monkeypatch, fake_post)
    ok, error = mgr.sign_in("owen", "pw")
    assert ok is False
    assert "this computer's clock" in error
    assert "machine" not in error
    assert "—" not in error


# -- owed round: logic-resolve-3 (from c-resolve) ----------------------------


def test_the_factory_luts_knob_is_a_known_default_and_in_the_template():
    import tomllib
    from ccsync_companion import config as config_mod
    assert config_mod.DEFAULTS["resolve_factory_luts_extra"] == ""
    parsed = tomllib.loads(config_mod.DEFAULT_TOML_TEXT)
    assert parsed["resolve_factory_luts_extra"] == ""
