"""CR-311 (2026-09-24): a queued row whose machine has said it cannot move
says so, instead of reading as a queue that is draining.

Seen live: leso's 52 Elections originals (23.5 GB) sat on the transfers page
as a plain amber "upload" for three days while his machine_state row said
`root_absent` since 2026-09-21 - the drive holding them was unplugged.
"""

from __future__ import annotations

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import health
from ccsync_dashboard.api import build_transfers_view

NOW = "2026-09-24T12:00:00+00:00"
SINCE = "2026-09-21T10:10:14+00:00"


def _setup(conn, blocked_reason):
    dbmod.upsert_project(conn, "elections", "2026/FF5/Elections",
                         "/data/Projects/2026/FF5/Elections", NOW)
    dbmod.upsert_machine(conn, "leso", "MBP", NOW)
    dbmod.add_selection(conn, "leso", "elections", "owen", NOW, machine="MBP")
    dbmod.upsert_machine_state(conn, "leso", "MBP", None, NOW)
    conn.execute("UPDATE machine_state SET blocked_reason=?, blocked_since=? "
                 "WHERE editor_username='leso' AND machine='MBP'",
                 (blocked_reason, SINCE if blocked_reason else None))
    pid = conn.execute("SELECT id FROM projects WHERE slug='elections'").fetchone()["id"]
    dbmod.replace_nas_media(conn, pid, [("B-roll/x/Proxy/p.mov", "proxy", ".mov", 10, 1)],
                            "sig", 1, NOW)
    dbmod.upsert_editor_media_project(
        conn, editor="leso", machine="MBP", slug="elections", mode="editor",
        n_originals=1, bytes_originals=100, n_proxies=0, bytes_proxies=0,
        truncated=False, now=NOW)
    dbmod.replace_editor_media(conn, "leso", "MBP", "elections",
                               [("B-roll/x/ff1373.MP4", "original", 100)], NOW)
    conn.commit()


def _rows(conn):
    return {q["lane"]: q for q in build_transfers_view(conn, NOW)["queues"]
            if q["slug"] == "elections" and not q.get("pending")}


def test_an_unplugged_drive_holds_every_lane_and_says_since_when(conn):
    _setup(conn, "root_absent")
    rows = _rows(conn)
    assert set(rows) == {"a", "b"}, rows
    for lane in ("a", "b"):
        held = rows[lane]["held"]
        assert held and held["reason"] == "root_absent"
        assert "sync drive is not there" in held["sentence"]
        assert held["since"] == SINCE


def test_a_lane_b_only_reason_does_not_hold_the_upload(conn):
    _setup(conn, "breaker_tripped")
    rows = _rows(conn)
    assert rows["a"]["held"] is None
    assert rows["b"]["held"]["reason"] == "breaker_tripped"


def test_no_reported_reason_leaves_the_row_as_it_was(conn):
    _setup(conn, None)
    assert all(q["held"] is None for q in _rows(conn).values())


def test_a_stall_is_not_a_hold():
    """The watchdog restarts a stalled lane; calling it held would be wrong."""
    assert health.queue_hold({"blocked_reason": "lane_stalled"}, "a") is None


def test_the_page_renders_the_hold(conn):
    from ccsync_dashboard.ui import templates
    _setup(conn, "root_absent")
    html = templates.get_template("partials/transfers.html").render(
        transfers=build_transfers_view(conn, NOW), scope_admin=True)
    assert "[ ON HOLD ]" in html
    assert "sync drive is not there on this computer" in html
    assert "—" not in html.split("[ QUEUED ]", 1)[1].split("[ HISTORY ]", 1)[0]
