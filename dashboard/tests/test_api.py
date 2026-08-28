from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

DEVICE_ID = "EDITORA-EDITORA-EDITORA-EDITORA-EDITORA-EDITORA-EDITORA-EDITORA"
T = "2026-07-24T10:00:00+00:00"
SECRET = "test-secret"


@pytest.fixture
def app_env(tmp_path):
    db_path = tmp_path / "dash.db"
    settings = Settings(db_path=str(db_path), report_token="sekrit",
                        session_secret=SECRET, admin_users=frozenset({"admin"}))
    app = create_app(settings)
    with TestClient(app) as client:
        # log in as an admin so reads see the whole fleet (the login gate now
        # forbids anonymous access)
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "admin"))
        conn = dbmod.connect(db_path)
        yield client, conn
        conn.close()


def seed(conn):
    now = dbmod.utcnow_iso()
    pid = dbmod.upsert_project(conn, "2025-ff4-nuclear", "2025/FF4/Nuclear", "/data/x", now)
    did = dbmod.upsert_device(conn, DEVICE_ID, "jsmith", False, now)
    dbmod.set_connections(conn, {DEVICE_ID: "100.1.2.3:22000"}, now)
    dbmod.upsert_completion(conn, pid, did, completion=62.5, need_items=45,
                            need_bytes=1_000_000, need_deletes=0,
                            global_items=120, global_bytes=5_000_000, now=now)
    dbmod.replace_missing_files(conn, pid, did, [("Audio/Music/track1.wav", 1234)], False, now)
    dbmod.record_poll_run(conn, "completion", now, now, True, None)
    conn.commit()
    return pid, did


def test_health_endpoint(app_env):
    client, conn = app_env
    body = client.get("/api/v1/health").json()
    assert body["syncthing_reachable"] is False and "version" in body
    seed(conn)
    body = client.get("/api/v1/health").json()
    assert body["syncthing_reachable"] is True
    assert body["last_polls"]["completion"]["ok"] is True


def test_health_detail_requires_authentication(app_env):
    """/api/v1/health is in app.py's _OPEN_EXACT so the Docker healthcheck
    can reach it with no credentials -- which made the whole client roster
    (project slugs, labels, Syncthing folder error strings) readable by
    anyone who could reach the port. Anonymous now gets liveness only."""
    client, conn = app_env
    seed(conn)
    client.cookies.delete(auth.COOKIE_NAME)

    anon = client.get("/api/v1/health")
    # the healthcheck reads `ok` out of this body (DASH-2), and the shape of
    # the anonymous answer must not change under it
    assert anon.status_code == 200
    assert set(anon.json()) == {"ok", "version"}
    assert anon.json()["ok"] is True

    # the companion's shared token unlocks it (it already reads /report)...
    full = client.get("/api/v1/health", headers={"X-CCSync-Token": "sekrit"})
    assert full.status_code == 200
    assert "folder_errors" in full.json() and "last_polls" in full.json()
    assert client.get("/api/v1/health", headers={"X-CCSync-Token": "wrong"}).json().keys() == {
        "ok", "version"}

    # ...and so does any session
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    assert "folder_errors" in client.get("/api/v1/health").json()


def test_a_dead_collector_shows_up_in_ok_while_the_status_stays_200(tmp_path):
    """DASH-2: this is the contract the container healthcheck now depends on.
    A collector that stopped advancing poll_runs clears syncthing_reachable
    (COLLECTOR_STALE_SECONDS), and that has to reach the probe through `ok` --
    while the STATUS stays 200 either way, because ship.ps1's post-deploy poll
    and the macOS wizard's connection test both read a non-200 as 'the
    dashboard is down'."""
    import datetime as dt

    db_path = tmp_path / "hc.db"
    settings = Settings(
        db_path=str(db_path), report_token="sekrit", session_secret=SECRET,
        admin_users=frozenset({"admin"}),
        # `ok` is about Syncthing only where Syncthing is configured at all
        # (api_health's `or not syncthing_url`), so a lab deployment without
        # one stays healthy by definition. Nothing listens on this port.
        syncthing_url="http://127.0.0.1:1",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        # ...otherwise it keeps writing its own failing poll runs underneath
        # these assertions
        client.app.state.collector.stop()
        conn = dbmod.connect(db_path)
        conn.execute("DELETE FROM poll_runs")
        now = dbmod.utcnow_iso()
        dbmod.record_poll_run(conn, "completion", now, now, True, None)
        conn.commit()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "admin"))
        assert client.get("/api/v1/health").json()["ok"] is True

        old = (dt.datetime.now(dt.timezone.utc)
               - dt.timedelta(seconds=dbmod.COLLECTOR_STALE_SECONDS + 60)).isoformat()
        dbmod.record_poll_run(conn, "completion", old, old, True, None)
        conn.commit()

        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False and body["collector_stale"] is True

        client.cookies.delete(auth.COOKIE_NAME)
        anon = client.get("/api/v1/health")
        assert anon.status_code == 200 and anon.json()["ok"] is False
        conn.close()


def test_projects_and_detail(app_env):
    client, conn = app_env
    seed(conn)
    body = client.get("/api/v1/projects").json()
    assert body["fleet_status"] == "amber"
    (project,) = body["projects"]
    assert project["slug"] == "2025-ff4-nuclear" and project["status"] == "amber"
    (editor,) = project["editors"]
    assert editor["display_name"] == "jsmith" and editor["unmapped"] is False
    assert editor["have_items"] == 75 and editor["connected"] is True

    detail = client.get("/api/v1/projects/2025-ff4-nuclear")
    assert detail.status_code == 200 and detail.json()["label"] == "2025/FF4/Nuclear"
    assert client.get("/api/v1/projects/nope").status_code == 404


def test_missing_endpoint(app_env):
    client, conn = app_env
    seed(conn)
    body = client.get(f"/api/v1/projects/2025-ff4-nuclear/devices/{DEVICE_ID}/missing").json()
    assert body["files"] == [{"name": "Audio/Music/track1.wav", "size": 1234}]
    assert body["truncated"] is False and body["need_items"] == 45
    assert client.get(f"/api/v1/projects/nope/devices/{DEVICE_ID}/missing").status_code == 404
    assert client.get("/api/v1/projects/2025-ff4-nuclear/devices/NOPE/missing").status_code == 404


def test_ui_pages_render(app_env):
    client, conn = app_env
    seed(conn)
    home = client.get("/")
    assert home.status_code == 200
    # The topbar's brand half is site data now: an app_env that names no org
    # falls back to the product name (2026-08-17, COMMERCIAL_READINESS.md
    # item 10, ui._render brand_org).
    assert "CC SYNC" in home.text and "2025/FF4/Nuclear" in home.text

    page = client.get("/project/2025-ff4-nuclear")
    assert page.status_code == 200
    assert "jsmith" in page.text and "62%" in page.text and "[ MISSING FILES ]" in page.text
    assert client.get("/project/nope").status_code == 404

    partial = client.get(f"/partials/project/2025-ff4-nuclear/missing/{DEVICE_ID}")
    assert partial.status_code == 200 and "Audio/Music/track1.wav" in partial.text


def test_the_fleet_page_builds_the_snapshot_once(app_env, monkeypatch):
    """DASH-6: page_fleet spread _sidebar_context (build_projects_view) and
    then called build_queue_view, whose first act was build_projects_view
    again -- so one render did collector-status + lanes + the N+1
    fetch_projects TWICE, off two independently-taken `now` values, and the
    sidebar's status dots and the queue's percentages came from two different
    reads of the same tables."""
    from ccsync_dashboard import api as apimod
    from ccsync_dashboard import ui as uimod

    client, conn = app_env
    seed(conn)
    dbmod.add_selection(conn, "admin", "2025-ff4-nuclear", "admin", dbmod.utcnow_iso())
    conn.commit()

    calls = {"n": 0}
    real_build = apimod.build_projects_view

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real_build(*args, **kwargs)

    # both namespaces: ui.py imported the name, build_queue_view calls api's
    monkeypatch.setattr(apimod, "build_projects_view", counting)
    monkeypatch.setattr(uimod, "build_projects_view", counting)

    page = client.get("/")
    assert page.status_code == 200
    assert calls["n"] == 1

    # ...and both panels rendered off that one snapshot
    assert "2025/FF4/Nuclear" in page.text
    view = real_build(conn)
    queue = apimod.build_queue_view(conn, "admin", projects_view=view)
    assert queue["generated_at"] == view["generated_at"]
    assert [i["slug"] for i in queue["queue"]] == ["2025-ff4-nuclear"]


# -- who-has-what: report-only machines + the sidebar tree (2026-07-26) -----


def test_project_view_includes_report_only_machines(app_env):
    """The base rig has no Syncthing (lane C) device, but it reports media
    presence -- it must still appear in the project view's editors table."""
    client, conn = app_env
    seed(conn)
    now = dbmod.utcnow_iso()
    dbmod.upsert_editor_media_project(
        conn, editor="owen", machine="CREATOR_1", slug="2025-ff4-nuclear",
        mode="base", n_originals=69, bytes_originals=10, n_proxies=69,
        bytes_proxies=5, truncated=False, now=now)
    conn.commit()

    body = client.get("/api/v1/projects/2025-ff4-nuclear").json()
    rows = {e["display_name"]: e for e in body["editors"]}
    assert "owen" in rows
    base = rows["owen"]
    assert base["report_only"] is True
    assert base["media"]["n_originals"] == 69
    assert base["media"]["mode"] == "base"
    assert base["completion"] is None      # lane C does not apply
    assert base["device_id"] is None
    # the device-backed row is untouched, and now carries media info too
    assert rows["jsmith"]["report_only"] is False
    assert rows["jsmith"]["media"] is None  # jsmith reported no media yet

    # and the page renders the report-only row (BASE chip, no missing button)
    page = client.get("/project/2025-ff4-nuclear")
    assert page.status_code == 200
    assert "owen" in page.text and "[ BASE ]" in page.text
    assert "69/0 orig" in page.text  # NAS inventory not seeded -> denominator 0


def test_project_view_media_attaches_to_device_rows(app_env):
    client, conn = app_env
    seed(conn)
    now = dbmod.utcnow_iso()
    dbmod.upsert_editor_media_project(
        conn, editor="jsmith", machine="EDIT-PC", slug="2025-ff4-nuclear",
        mode="editor", n_originals=0, bytes_originals=0, n_proxies=42,
        bytes_proxies=5, truncated=False, now=now)
    conn.commit()

    body = client.get("/api/v1/projects/2025-ff4-nuclear").json()
    (editor,) = [e for e in body["editors"] if e["display_name"] == "jsmith"]
    assert editor["report_only"] is False
    assert editor["media"]["n_proxies"] == 42


def test_projects_view_tree_nests_and_shortens(app_env):
    client, conn = app_env
    seed(conn)
    now = dbmod.utcnow_iso()
    dbmod.upsert_project(conn, "2026-cct-website-highlights-website-highlights",
                         "2026/CCT/Website Highlights/Website Highlights", "/data/y", now)
    conn.commit()

    tree = client.get("/api/v1/projects").json()["tree"]
    ff4 = tree["groups"]["2025"]["groups"]["FF4"]
    assert [p["short"] for p in ff4["projects"]] == ["Nuclear"]
    assert ff4["projects"][0]["slug"] == "2025-ff4-nuclear"
    wh = tree["groups"]["2026"]["groups"]["CCT"]["groups"]["Website Highlights"]
    assert [p["short"] for p in wh["projects"]] == ["Website Highlights"]
    # the slugs rollup drives "open the chain containing the current project"
    assert "2026-cct-website-highlights-website-highlights" in tree["groups"]["2026"]["slugs"]
    assert "2025-ff4-nuclear" not in tree["groups"]["2026"]["slugs"]


def test_synced_pct_combines_lane_c_and_proxies(app_env):
    """The SYNCED column is total progress by bytes -- lane C content plus
    proxies, originals excluded (they only live on the server). Lane C
    alone said 0% while 263/283 proxies were already local (2026-07-26)."""
    client, conn = app_env
    pid, _did = seed(conn)   # lane C: global 5,000,000 bytes, need 1,000,000
    now = dbmod.utcnow_iso()
    # NAS holds 10,000,000 bytes of proxies; jsmith has 6,000,000 of them.
    dbmod.replace_nas_media(conn, pid, [
        ("B-roll/Proxy/a.mov", "proxy", ".mov", 6_000_000, 1),
        ("B-roll/Proxy/b.mov", "proxy", ".mov", 4_000_000, 2),
    ], "sig", 2, now)
    dbmod.upsert_editor_media_project(
        conn, editor="jsmith", machine="EDIT-PC", slug="2025-ff4-nuclear",
        mode="editor", n_originals=0, bytes_originals=0, n_proxies=1,
        bytes_proxies=6_000_000, truncated=False, now=now)
    conn.commit()

    body = client.get("/api/v1/projects/2025-ff4-nuclear").json()
    (e,) = [x for x in body["editors"] if x["display_name"] == "jsmith"]
    # have = (5M - 1M lane C) + 6M proxies = 10M of 15M total
    assert e["synced_pct"] == 66.7
    # lane C detail is still available untouched
    assert e["completion"] == 62.5


def test_synced_pct_falls_back_to_lane_c_without_a_manifest(app_env):
    client, conn = app_env
    seed(conn)
    body = client.get("/api/v1/projects/2025-ff4-nuclear").json()
    (e,) = [x for x in body["editors"] if x["display_name"] == "jsmith"]
    assert e["synced_pct"] == e["completion"] == 62.5


# -- the collector's brakes are visible (DASH-3 / DASH-4 / DASH-14, resilience
#    sweep 2026-08-28). Both refusals used to exist only in the container log,
#    while poll_runs, /api/v1/health and every page said the cycle was fine.

def _seed_refusals(conn):
    now = dbmod.utcnow_iso()
    dbmod.record_enforce_refusal(conn, now, [("2025-ff4-nuclear", DEVICE_ID),
                                             ("2026-ff5-alpha", DEVICE_ID)], 1)
    dbmod.meta_set_json(conn, dbmod.META_DEACTIVATION_REFUSAL, {
        "at": now, "message": "Syncthing reported 0 of 37 folders - not deactivating anything",
        "seen": 0, "active": 37, "would_deactivate": 37, "ceiling": 9, "projects": []})
    dbmod.record_enforce_plan(conn, now, [
        ("2025-ff4-nuclear", {DEVICE_ID}, set()),
        ("2026-ff5-alpha", set(), {DEVICE_ID}),
    ])
    dbmod.record_poll_run(conn, "enforce", now, now, True, "refused 2 share removal(s)")
    conn.commit()


def test_health_reports_the_collector_alarms(app_env):
    client, conn = app_env
    seed(conn)
    _seed_refusals(conn)
    alarms = client.get("/api/v1/health").json()["collector_alarms"]
    assert alarms["enforce_refusal"]["count"] == 2
    assert "0 of 37 folders" in alarms["deactivation_refusal"]["message"]
    assert alarms["enforce_plan"]["n_add"] == 1 and alarms["enforce_plan"]["n_remove"] == 1


def test_the_fleet_page_banners_and_panel_show_the_refusals(app_env):
    client, conn = app_env
    seed(conn)
    _seed_refusals(conn)
    page = client.get("/").text
    assert "SHARE REMOVAL(S) REFUSED" in page and "shares are FROZEN" in page
    assert "0 of 37 folders" in page
    # the health panel + the read-only pending diff
    assert "[ COLLECTOR ]" in page and "[ PENDING SHARE CHANGES ]" in page
    assert "refused 2 share removal(s)" in page
    assert "[ INCOMPLETE ]" in page


def test_an_editor_is_not_shown_the_collector_panel(app_env):
    """It names Syncthing device ids and is an admin diagnostic: the whole
    block goes in _scope_editors_view, so the partial cannot render it."""
    client, conn = app_env
    seed(conn)
    _seed_refusals(conn)
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    page = client.get("/").text
    assert "[ COLLECTOR ]" not in page
    assert "SHARE REMOVAL(S) REFUSED" not in page
    assert "collector" not in client.get("/api/v1/editors").json()


def test_the_project_page_says_a_nas_inventory_was_not_replaced(app_env):
    """DASH-5: a project dir that went missing under the collector used to
    write 0 originals with no error, so this page told the owner the server
    holds none of his footage."""
    client, conn = app_env
    pid, _did = seed(conn)
    dbmod.replace_nas_media(conn, pid, [("B-roll/a.braw", "original", ".braw", 10, 1)],
                            "sig1", 1, T)
    conn.commit()
    assert dbmod.replace_nas_media(conn, pid, [], "sig2", 1, T) is False
    conn.commit()
    page = client.get("/project/2025-ff4-nuclear").text
    assert "[ NAS INVENTORY NOT UPDATED ]" in page
    assert "not replacing" in page
