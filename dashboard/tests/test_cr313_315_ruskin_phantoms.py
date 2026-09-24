"""CR-313 / CR-314 / CR-315 (2026-09-24): three things on ruskin's row that
were not true, found by checking his machine against the dashboard.

- CR-313: a stall that healed on 2026-09-11 kept "Not syncing: upload has been
  busy for 25 minutes" and a red [ STALLED ] chip on his row for 13 days.
- CR-314: the per-file manifest was capped at 2000 rows for originals and
  proxies TOGETHER, so 100 Civil Defence and 523 Energy Transition proxies
  that were on his drive were listed as a proxy download owed for ever.
- CR-315: two yt-dlp fragments lane A skips on purpose (31.7 GB) were listed
  as an upload owed for ever.
"""

from __future__ import annotations

import re
from pathlib import Path

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import health

NOW = "2026-09-24T12:00:00+00:00"
REPO = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ CR-313

def _stalled(at):
    return {"blocked_reason": "lane_stalled", "stalled_lane": "A",
            "stalled_seconds": 1500, "stalled_killed": True, "stalled_at": at,
            "lanes": []}


def test_a_healed_stall_the_companion_still_reports_is_not_the_why():
    why = health.why_not_syncing(_stalled("2026-09-11T16:26:15+00:00"), NOW)
    assert why is None or why[0] != "lane_stalled"


def test_a_fresh_stall_the_companion_reports_still_is():
    why = health.why_not_syncing(_stalled("2026-09-24T11:30:00+00:00"), NOW)
    assert why is not None and why[0] == "lane_stalled"


def test_a_stall_the_lane_has_passed_since_is_not_the_why():
    row = _stalled("2026-09-24T09:00:00+00:00")
    row["lanes"] = [{"lane": "lane_a_video_up", "last_sync": "2026-09-24T10:50:00+00:00"}]
    why = health.why_not_syncing(row, NOW)
    assert why is None or why[0] != "lane_stalled"


def test_the_stalled_chip_asks_whether_the_stall_is_current():
    html = (REPO / "dashboard/templates/partials/fleet_grid.html").read_text(encoding="utf-8")
    assert "{% if e.guard.stalled_lane and e.guard.stall_current %}" in html
    api = (REPO / "dashboard/src/ccsync_dashboard/api.py").read_text(encoding="utf-8")
    assert 'entry["guard"]["stall_current"] = health.stall_is_current(' in api


# ------------------------------------------------------------------ CR-314

def _pair(conn, slug="p"):
    dbmod.upsert_project(conn, slug, "2026/FF5/P", f"/data/{slug}", NOW)
    dbmod.upsert_machine(conn, "ruskin", "PC", NOW)
    dbmod.add_selection(conn, "ruskin", slug, "owen", NOW, machine="PC")
    dbmod.upsert_editor_media_project(
        conn, editor="ruskin", machine="PC", slug=slug, mode="editor",
        n_originals=0, bytes_originals=0, n_proxies=0, bytes_proxies=0,
        truncated=False, now=NOW)
    return conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()["id"]


def test_originals_cannot_push_proxies_out_of_the_manifest(conn):
    pid = _pair(conn)
    n_orig, n_prox = 827, 1696          # ruskin's Energy Transition, measured
    proxies = [(f"A/Proxy/c{i:04}.mov", "proxy", ".mov", 10, 1) for i in range(n_prox)]
    dbmod.replace_nas_media(conn, pid, proxies, "sig", 1, NOW)
    files = [(f"A/o{i:04}.braw", "original", 100) for i in range(n_orig)]
    files += [(f"A/Proxy/c{i:04}.mov", "proxy", 10) for i in range(n_prox)]
    dbmod.replace_editor_media(conn, "ruskin", "PC", "p", files, NOW)
    conn.commit()
    counts = dict(conn.execute(
        "SELECT kind, COUNT(*) FROM editor_media GROUP BY kind").fetchall())
    assert counts == {"original": n_orig, "proxy": n_prox}
    assert not [q for q in dbmod.fetch_sync_backlog(conn) if q["direction"] == "down"]


def test_each_kind_is_still_capped(conn):
    _pair(conn)
    cap = dbmod.EDITOR_MEDIA_CAP
    files = [(f"o{i}.braw", "original", 1) for i in range(cap + 5)]
    files += [(f"Proxy/p{i}.mov", "proxy", 1) for i in range(cap + 5)]
    dbmod.replace_editor_media(conn, "ruskin", "PC", "p", files, NOW)
    counts = dict(conn.execute(
        "SELECT kind, COUNT(*) FROM editor_media GROUP BY kind").fetchall())
    assert counts == {"original": cap, "proxy": cap}


# ------------------------------------------------------------------ CR-315

def test_ytdl_leftovers_lane_a_skips_are_not_owed_uploads(conn):
    pid = _pair(conn)
    dbmod.replace_nas_media(
        conn, pid, [("Youtube/k/Day5 [xfe3X3yeVaw].mp4", "original", ".mp4", 22, 1)],
        "sig", 1, NOW)
    dbmod.replace_editor_media(conn, "ruskin", "PC", "p", [
        ("Youtube/k/Day5 [xfe3X3yeVaw].f137.mp4", "original", 19_810_000_000),
        ("Youtube/k/Day5 [xfe3X3yeVaw].temp.mp4", "original", 11_930_000_000),
        ("Shoot/A001.braw", "original", 500),
    ], NOW)
    conn.commit()
    up = [q for q in dbmod.fetch_sync_backlog(conn) if q["direction"] == "up"]
    assert len(up) == 1
    assert up[0]["n_files"] == 1 and up[0]["bytes"] == 500
    assert [f["name"] for f in up[0]["files"]] == ["Shoot/A001.braw"]


def test_the_skip_list_matches_the_companions_lane_a_rules():
    """The dashboard's copy may not drift from the rules lane A runs."""
    src = (REPO / "companion/src/ccsync_companion/sync/rclone_lane.py").read_text(
        encoding="utf-8")
    ytdl = re.search(r"YTDL_WORK_EXCLUDE_RULES = \[\n(.*?)\n\]", src, re.S).group(1)
    rules = set(re.findall(r'"- ([^"]+)"', ytdl))
    rules.add(re.search(r'APPLEDOUBLE_EXCLUDE_RULE = "- ([^"]+)"', src).group(1))
    prefix = re.search(r'MOVE_STAGING_PREFIX = "([^"]+)"', src).group(1)
    rules.add(prefix + "*")
    assert rules == set(dbmod.LANE_A_SKIP_GLOBS)
