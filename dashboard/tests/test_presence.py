from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import health
from ccsync_dashboard.api import build_presence_view, build_transfers_view
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
TOKEN = "tok"


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "p.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET, report_token=TOKEN,
                        admin_users=frozenset({"alex"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        now = dbmod.utcnow_iso()
        pid = dbmod.upsert_project(conn, "2026-ff5-energy-transition",
                                   "2026/FF5/Energy Transition", "/x", now)
        # NAS has 2 originals + 2 proxies
        dbmod.replace_nas_media(conn, pid, [
            ("B-roll/a.braw", "original", ".braw", 100, 1),
            ("B-roll/b.braw", "original", ".braw", 100, 2),
            ("B-roll/Proxy/a.mov", "proxy", ".mov", 10, 3),
            ("B-roll/Proxy/b.mov", "proxy", ".mov", 10, 4),
        ], "sig", 2, now)
        conn.commit()
        yield client, conn, now


def report(editor, machine, **extra):
    p = {"editor_name": editor, "machine": machine, "reported_at": "2026-07-25T10:00:00+00:00",
         "lanes": [{"name": "lane_b_proxy_down", "state": "syncing", "transfers": [
             {"name": "b.mov", "direction": "down", "percentage": 30.0, "speed_bps": 2000.0,
              "eta_seconds": 12.0}]}]}
    p.update(extra)
    return p


def test_presence_status_roles():
    nas = {"n_originals": 2, "n_proxies": 2}
    # editor proxy-only is green; base missing originals is red
    assert health.presence_status("editor", nas, {"n_originals": 0, "n_proxies": 2}) == "green"
    assert health.presence_status("editor", nas, {"n_originals": 0, "n_proxies": 1}) == "amber"
    assert health.presence_status("base", nas, {"n_originals": 1, "n_proxies": 2}) == "red"
    assert health.presence_status("base", nas, {"n_originals": 2, "n_proxies": 0}) == "green"


def test_report_ingests_media(env):
    client, conn, now = env
    payload = report(
        "ruskin", "RUSKIN-PC", mode="editor",
        local_manifest={"2026/FF5/Energy Transition": {
            "n_originals": 0, "bytes_originals": 0, "n_proxies": 2, "bytes_proxies": 20,
            "truncated": False, "originals": None, "proxies": [["B-roll/Proxy/a.mov", 10]]}},
        media_tree={"FF5 Energy Transition": [
            {"bin_path": "Interviews", "clip_name": "clipA", "file_path": "P:/x/a.mov",
             "kind": "proxy", "present": True},
            {"bin_path": "Interviews", "clip_name": "clipB", "file_path": "P:/x/b.mov",
             "kind": "proxy", "present": False}]},
    )
    # need a project_roots mapping so media_tree (keyed by resolve name) resolves
    dbmod.admin_set_project_root(conn, "FF5 Energy Transition", "2026-ff5-energy-transition",
                                 "alex", now)
    conn.commit()
    assert client.post("/api/v1/report", json=payload, headers={"X-CCSync-Token": TOKEN}).status_code == 200

    # rollup + tree + transfer landed
    roll = dbmod.fetch_editor_media_for_project(conn, "2026-ff5-energy-transition")
    assert roll[0]["n_proxies"] == 2 and roll[0]["mode"] == "editor"
    view = build_presence_view(conn, "2026-ff5-energy-transition")
    e = view["editors"][0]
    assert e["proxy_only"] is True and e["status"] == "green"
    bins = {b["bin_path"]: b for b in e["bins"]}
    assert bins["Interviews"]["present"] == 1 and bins["Interviews"]["total"] == 2
    assert e["offline"] == 1
    # clipB is uploading (matches the active transfer "b.mov")
    clipB = next(c for c in bins["Interviews"]["clips"] if c["clip_name"] == "clipB")
    assert clipB["uploading"] is True


def test_transfers_view_and_scope(env):
    client, conn, now = env
    client.post("/api/v1/report", json=report("ruskin", "RUSKIN-PC"),
                headers={"X-CCSync-Token": TOKEN})
    client.post("/api/v1/report", json=report("jane", "JANE-PC"),
                headers={"X-CCSync-Token": TOKEN})
    # unscoped (admin) sees both editors' transfers
    allv = build_transfers_view(conn)
    assert {t["editor"] for t in allv["transfers"]} == {"ruskin", "jane"}
    # scoped to ruskin sees only ruskin
    scoped = build_transfers_view(conn, editor="ruskin")
    assert {t["editor"] for t in scoped["transfers"]} == {"ruskin"}


def test_scope_leak_blocked_over_http(env):
    client, conn, now = env
    client.post("/api/v1/report", json=report("ruskin", "RUSKIN-PC"),
                headers={"X-CCSync-Token": TOKEN})
    # ruskin logs in -> /api/v1/transfers shows only ruskin, even if others exist
    client.post("/api/v1/report", json=report("jane", "JANE-PC"),
                headers={"X-CCSync-Token": TOKEN})
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "ruskin"))
    body = client.get("/api/v1/transfers").json()
    assert body["transfers"] and all(t["editor"] == "ruskin" for t in body["transfers"])
    # presence for a project shows only ruskin's row for a non-admin
    pres = client.get("/api/v1/projects/2026-ff5-energy-transition/presence").json()
    assert all(e["editor"] == "ruskin" for e in pres["editors"])


def test_pages_render(env):
    client, conn, now = env
    dbmod.admin_set_project_root(conn, "FF5 Energy Transition",
                                 "2026-ff5-energy-transition", "alex", now)
    conn.commit()
    client.post("/api/v1/report", json=report(
        "ruskin", "RUSKIN-PC", mode="editor",
        media_tree={"FF5 Energy Transition": [
            {"bin_path": "Interviews", "clip_name": "clipA", "file_path": "P:/a.mov",
             "kind": "proxy", "present": True}]},
    ), headers={"X-CCSync-Token": TOKEN})
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "alex"))
    # transfers page + partial
    assert "LIVE TRANSFERS" in client.get("/transfers").text
    assert "b.mov" in client.get("/partials/transfers").text
    # project page includes the sidebar checkbox + bins partial
    page = client.get("/project/2026-ff5-energy-transition")
    assert page.status_code == 200 and 'type="checkbox"' in page.text
    bins = client.get("/partials/project/2026-ff5-energy-transition/bins")
    assert "MEDIA PRESENCE" in bins.text and "Interviews" in bins.text
    # sidebar checkbox toggle round-trips and returns the sidebar
    r = client.post("/partials/selection/alex/2026-ff5-energy-transition/toggle?view=sidebar")
    assert r.status_code == 200 and "PROJECTS" in r.text


def test_report_without_media_leaves_tables_untouched(env):
    client, conn, now = env
    # first report WITH media
    dbmod.admin_set_project_root(conn, "FF5", "2026-ff5-energy-transition", "alex", now)
    conn.commit()
    client.post("/api/v1/report", json=report(
        "ruskin", "RUSKIN-PC",
        local_manifest={"2026/FF5/Energy Transition": {"n_originals": 0, "bytes_originals": 0,
                        "n_proxies": 1, "bytes_proxies": 10, "truncated": False}},
    ), headers={"X-CCSync-Token": TOKEN})
    assert dbmod.fetch_editor_media_for_project(conn, "2026-ff5-energy-transition")
    # a LIGHT report (no local_manifest) must not wipe the rollup
    light = report("ruskin", "RUSKIN-PC")
    client.post("/api/v1/report", json=light, headers={"X-CCSync-Token": TOKEN})
    assert dbmod.fetch_editor_media_for_project(conn, "2026-ff5-energy-transition")
