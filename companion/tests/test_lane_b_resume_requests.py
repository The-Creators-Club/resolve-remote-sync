"""comp-lanes-ab-2 (2026-08-21): a dashboard resume is ONE-SHOT.

The dashboard keeps `commands.resume_lane_b` standing on every reply until a
report arrives saying the breaker is clear, and the companion used to apply it
whenever the breaker was tripped, with no memory of which request it had
already honoured. A pass that re-tripped inside the report interval was
therefore resumed again by the next reply, and again, moving another
--max-delete 100 proxies into .ccsync-trash each cycle -- the unbounded
sequence lane_guard.py's breaker exists to stop, restarted by one admin click.

Nothing here touches a real rclone, Syncthing or dashboard.
"""

from __future__ import annotations

import threading
from typing import Any

from ccsync_companion.app import CompanionApp


def _cfg(tmp_path, **overrides) -> dict[str, Any]:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    cfg = {
        "editor_name": "owen",
        "local_root": str(root),
        "canonical_prefix": "P:\\",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/Creators_Club",
        "active_project": "",
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "",
        "popup_enabled": False,
        "sync_enabled": False,
        "lane_b_enabled": False,
    }
    cfg.update(overrides)
    return cfg


def _app(tmp_path, **overrides) -> CompanionApp:
    app = CompanionApp(_cfg(tmp_path, **overrides))
    app._notify_tray = lambda *a, **kw: None
    return app


def _reply(requested_at: str, by: str = "alex") -> dict:
    return {"ok": True, "commands": {"resume_lane_b": {
        "apply": True, "requested_by": by, "requested_at": requested_at}}}


def _join_off_cycle_reports() -> None:
    for thread in list(threading.enumerate()):
        if thread.name == "ccsync-report-off-cycle":
            thread.join(timeout=5)


def test_one_admin_click_resumes_the_breaker_exactly_once(tmp_path):
    app = _app(tmp_path)
    app.lane_b_breaker.trip("the NAS listed the tree as EMPTY")

    app._apply_resume_lane_b(_reply("2026-08-21T10:00:00Z"))
    assert not app.lane_b_breaker.tripped

    # The resumed pass re-trips seconds later, before the reporter's next
    # tick -- so the dashboard has not dropped the request and sends it again.
    app.lane_b_breaker.trip("the NAS listed the tree as EMPTY (again)")
    app._apply_resume_lane_b(_reply("2026-08-21T10:00:00Z"))
    assert app.lane_b_breaker.tripped, (
        "the same request resumed a second, unreviewed trip")


def test_a_fresh_click_resumes_a_later_trip(tmp_path):
    """The one-shot rule must not make the button stop working: a NEW
    request (a new requested_at) is a new judgement about the server."""
    app = _app(tmp_path)
    app.lane_b_breaker.trip("boom")
    app._apply_resume_lane_b(_reply("2026-08-21T10:00:00Z"))
    app.lane_b_breaker.trip("boom again")

    app._apply_resume_lane_b(_reply("2026-08-21T11:30:00Z"))
    assert not app.lane_b_breaker.tripped


def test_the_applied_request_survives_a_tray_restart(tmp_path):
    """Never an in-memory-only latch (CLAUDE.md): the editor's first move is
    to restart the tray, and a request the new process has never heard of
    would resume the trip it was restarted for."""
    app = _app(tmp_path)
    app.lane_b_breaker.trip("boom")
    app._apply_resume_lane_b(_reply("2026-08-21T10:00:00Z"))

    restarted = _app(tmp_path)
    restarted.lane_b_breaker.trip("boom again")
    restarted._apply_resume_lane_b(_reply("2026-08-21T10:00:00Z"))
    assert restarted.lane_b_breaker.tripped


def test_a_resume_posts_a_report_at_once(tmp_path):
    """The dashboard only drops the standing request when it sees a report
    with the breaker clear, and the reporter's next tick was chosen before
    this reply arrived (60 s with nothing SYNCING, the parked state a resume
    ends)."""
    app = _app(tmp_path)
    posts: list[bool] = []
    app.reporter.post_once = lambda light=False: posts.append(light)
    app.lane_b_breaker.trip("boom")

    app._apply_resume_lane_b(_reply("2026-08-21T10:00:00Z"))
    _join_off_cycle_reports()
    assert posts == [True]                      # light: sync_guard rides every tick


def test_the_tray_button_is_unaffected(tmp_path):
    """No request id, no one-shot rule: the editor at the keyboard is the
    original path and clicks as often as they like."""
    app = _app(tmp_path)
    app.lane_b_breaker.trip("boom")
    assert app.resume_lane_b()[0] is True
    app.lane_b_breaker.trip("boom again")
    assert app.resume_lane_b()[0] is True
    _join_off_cycle_reports()
