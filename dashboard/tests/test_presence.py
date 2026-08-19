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
                        admin_users=frozenset({"owen"}))
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


def hdr(editor="editor2"):
    """Both companion headers -- X-CCSync-Identity is required on reports."""
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


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
        "editor2", "EDITOR-PC-02", mode="editor",
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
                                 "owen", now)
    conn.commit()
    assert client.post("/api/v1/report", json=payload, headers=hdr("editor2")).status_code == 200

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
    client.post("/api/v1/report", json=report("editor2", "EDITOR-PC-02"),
                headers=hdr("editor2"))
    client.post("/api/v1/report", json=report("jane", "JANE-PC"),
                headers=hdr("jane"))
    # unscoped (admin) sees both editors' transfers
    allv = build_transfers_view(conn)
    assert {t["editor"] for t in allv["transfers"]} == {"editor2", "jane"}
    # scoped to editor2 sees only editor2
    scoped = build_transfers_view(conn, editor="editor2")
    assert {t["editor"] for t in scoped["transfers"]} == {"editor2"}


def test_scope_leak_blocked_over_http(env):
    client, conn, now = env
    client.post("/api/v1/report", json=report("editor2", "EDITOR-PC-02"),
                headers=hdr("editor2"))
    # editor2 logs in -> /api/v1/transfers shows only editor2, even if others exist
    client.post("/api/v1/report", json=report("jane", "JANE-PC"),
                headers=hdr("jane"))
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "editor2"))
    body = client.get("/api/v1/transfers").json()
    assert body["transfers"] and all(t["editor"] == "editor2" for t in body["transfers"])
    # presence for a project shows only editor2's row for a non-admin
    pres = client.get("/api/v1/projects/2026-ff5-energy-transition/presence").json()
    assert all(e["editor"] == "editor2" for e in pres["editors"])


def test_pages_render(env):
    client, conn, now = env
    dbmod.admin_set_project_root(conn, "FF5 Energy Transition",
                                 "2026-ff5-energy-transition", "owen", now)
    conn.commit()
    client.post("/api/v1/report", json=report(
        "editor2", "EDITOR-PC-02", mode="editor",
        media_tree={"FF5 Energy Transition": [
            {"bin_path": "Interviews", "clip_name": "clipA", "file_path": "P:/a.mov",
             "kind": "proxy", "present": True}]},
    ), headers=hdr("editor2"))
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    # transfers page + partial
    assert "LIVE TRANSFERS" in client.get("/transfers").text
    assert "b.mov" in client.get("/partials/transfers").text
    # project page includes the sidebar checkbox + bins partial
    page = client.get("/project/2026-ff5-energy-transition")
    assert page.status_code == 200 and 'type="checkbox"' in page.text
    bins = client.get("/partials/project/2026-ff5-energy-transition/bins")
    assert "MEDIA PRESENCE" in bins.text and "Interviews" in bins.text
    # sidebar checkbox toggle round-trips and returns the sidebar
    r = client.post("/partials/selection/owen/2026-ff5-energy-transition/toggle?view=sidebar")
    assert r.status_code == 200 and "PROJECTS" in r.text


def test_local_manifest_uses_marker_slug_not_slugify_of_rel(env):
    """X-3: a project whose real slug (the marker's immutable identity) no
    longer matches slugify(its current rel) -- e.g. after an adopt where the
    original folder name produced a different slug -- must still get its
    local_manifest rows filed under the REAL slug, found via projects.label,
    not a freshly recomputed slugify(rel)."""
    client, conn, now = env
    # A project registered under a slug that does NOT equal slugify(label) --
    # simulates an adopted/retargeted project (collector.py's _run_provision
    # keeps label in lockstep with the current rel, but the slug is the
    # marker's, independent of it).
    dbmod.upsert_project(conn, "legacy-slug-from-marker", "2026/Weird Case/Odd Name", "/z", now)
    conn.commit()

    payload = report(
        "editor2", "EDITOR-PC-02",
        local_manifest={"2026/Weird Case/Odd Name": {
            "n_originals": 1, "bytes_originals": 100, "n_proxies": 0, "bytes_proxies": 0,
            "truncated": False,
        }},
    )
    assert client.post("/api/v1/report", json=payload,
                       headers=hdr("editor2")).status_code == 200

    # Filed under the marker's real slug (found via label)...
    roll = dbmod.fetch_editor_media_for_project(conn, "legacy-slug-from-marker")
    assert roll and roll[0]["n_originals"] == 1
    # ...NOT under whatever slugify() would have freshly produced for that rel.
    from ccsync_dashboard import provision
    guessed = provision.slugify("2026/Weird Case/Odd Name")
    assert guessed != "legacy-slug-from-marker"   # sanity: the two really differ
    assert dbmod.fetch_editor_media_for_project(conn, guessed) == []


def test_report_without_media_leaves_tables_untouched(env):
    client, conn, now = env
    # first report WITH media
    dbmod.admin_set_project_root(conn, "FF5", "2026-ff5-energy-transition", "owen", now)
    conn.commit()
    client.post("/api/v1/report", json=report(
        "editor2", "EDITOR-PC-02",
        local_manifest={"2026/FF5/Energy Transition": {"n_originals": 0, "bytes_originals": 0,
                        "n_proxies": 1, "bytes_proxies": 10, "truncated": False}},
    ), headers=hdr("editor2"))
    assert dbmod.fetch_editor_media_for_project(conn, "2026-ff5-energy-transition")
    # a LIGHT report (no local_manifest) must not wipe the rollup
    light = report("editor2", "EDITOR-PC-02")
    client.post("/api/v1/report", json=light, headers=hdr("editor2"))
    assert dbmod.fetch_editor_media_for_project(conn, "2026-ff5-energy-transition")


# -- the full sync queue (transfers page [ QUEUED ] section) ----------------


def _seed_backlog(conn, now):
    """editor2's EDIT-PC selected the project, reported a manifest holding one
    proxy (of the NAS's two) plus one local-only original -- so the backlog
    is: 1 proxy down (lane B), 1 original up (lane A)."""
    dbmod.add_selection(conn, "editor2", "2026-ff5-energy-transition", "editor2", now)
    dbmod.upsert_editor_media_project(
        conn, editor="editor2", machine="EDIT-PC", slug="2026-ff5-energy-transition",
        mode="editor", n_originals=1, bytes_originals=500, n_proxies=1,
        bytes_proxies=10, truncated=False, now=now)
    dbmod.replace_editor_media(conn, "editor2", "EDIT-PC", "2026-ff5-energy-transition", [
        ("B-roll/Proxy/a.mov", "proxy", 10),
        ("B-roll/Editor Added/new.braw", "original", 500),
    ], now)
    conn.commit()


def test_sync_backlog_diffs_both_directions(env):
    client, conn, now = env
    _seed_backlog(conn, now)

    view = build_transfers_view(conn)
    by_lane = {q["lane"]: q for q in view["queues"]}
    assert set(by_lane) == {"a", "b"}

    down = by_lane["b"]
    assert down["direction"] == "down" and down["editor"] == "editor2"
    assert down["n_files"] == 1 and down["bytes"] == 10
    assert down["files"] == [{"name": "B-roll/Proxy/b.mov", "size": 10}]
    assert down["truncated"] is False

    up = by_lane["a"]
    assert up["direction"] == "up"
    assert up["files"] == [{"name": "B-roll/Editor Added/new.braw", "size": 500}]
    assert view["queued_files"] == 2 and view["queued_bytes"] == 510

    # editor scoping hides other people's queues
    assert build_transfers_view(conn, editor="jsmith")["queues"] == []

    # and the transfers partial renders the queue section
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    page = client.get("/partials/transfers")
    assert page.status_code == 200
    assert "[ QUEUED ]" in page.text
    assert "B-roll/Proxy/b.mov" in page.text


def test_sync_backlog_excludes_base_and_unselected(env):
    client, conn, now = env
    # base rig reports a manifest but is never "behind"
    dbmod.upsert_editor_media_project(
        conn, editor="owen", machine="CREATOR_1", slug="2026-ff5-energy-transition",
        mode="base", n_originals=2, bytes_originals=200, n_proxies=2,
        bytes_proxies=20, truncated=False, now=now)
    dbmod.replace_editor_media(conn, "owen", "CREATOR_1", "2026-ff5-energy-transition",
                               [("B-roll/a.braw", "original", 100)], now)
    # jsmith reported a manifest but never selected the project
    dbmod.upsert_editor_media_project(
        conn, editor="jsmith", machine="PC-2", slug="2026-ff5-energy-transition",
        mode="editor", n_originals=0, bytes_originals=0, n_proxies=0,
        bytes_proxies=0, truncated=False, now=now)
    conn.commit()
    assert build_transfers_view(conn)["queues"] == []


def test_queue_excludes_unticked_lane_c_and_in_flight_files(env):
    """2026-07-26 phantom-queue report: stale Syncthing completion rows for
    UNTICKED projects surfaced as 44 GB of queued lane C, and files already
    in the live transfers table double-counted as queued."""
    client, conn, now = env
    _seed_backlog(conn, now)

    # A stale completion row for a project editor2 has NOT ticked: a second
    # project + device pair left over from an old configuration.
    pid2 = dbmod.upsert_project(conn, "2025-old-thing", "2025/Old Thing", "/y", now)
    did = dbmod.upsert_device(conn, "DEV-EDITOR2", "editor2", False, now)
    dbmod.upsert_completion(conn, pid2, did, completion=10.0, need_items=402,
                            need_bytes=44_000_000_000, need_deletes=0,
                            global_items=500, global_bytes=50_000_000_000, now=now)
    conn.commit()
    labels = [q["label"] for q in build_transfers_view(conn)["queues"]]
    assert "2025/Old Thing" not in labels        # unticked -> not queued

    # ...but the same row counts once the project is ticked
    dbmod.add_selection(conn, "editor2", "2025-old-thing", "editor2", now)
    conn.commit()
    labels = [q["label"] for q in build_transfers_view(conn)["queues"]]
    assert "2025/Old Thing" in labels

    # in-flight files leave the queue: editor2's report says b.mov is
    # transferring right now, so the lane B backlog (exactly that file)
    # empties and the group disappears; the lane A upload stays.
    client.post("/api/v1/report", json=report("editor2", "EDIT-PC"), headers=hdr("editor2"))
    view = build_transfers_view(conn)
    down_groups = [q for q in view["queues"] if q["lane"] == "b" and q["editor"] == "editor2"]
    assert down_groups == []
    assert [q["lane"] for q in view["queues"] if q["editor"] == "editor2" and q["lane"] == "a"] == ["a"]


def test_prune_completion_not_shared(env):
    _client, conn, now = env
    pid = dbmod.upsert_project(conn, "p-one", "P/One", "/1", now)
    pid2 = dbmod.upsert_project(conn, "p-two", "P/Two", "/2", now)
    did = dbmod.upsert_device(conn, "DEV-X", "jsmith", False, now)
    for p in (pid, pid2):
        dbmod.upsert_completion(conn, p, did, completion=50.0, need_items=3,
                                need_bytes=30, need_deletes=0,
                                global_items=6, global_bytes=60, now=now)
        dbmod.replace_missing_files(conn, p, did, [("a.wav", 1)], False, now)
    conn.commit()

    removed = dbmod.prune_completion_not_shared(conn, [(pid, did)])
    assert removed == 1
    left = conn.execute("SELECT project_id FROM completion_current").fetchall()
    assert [r["project_id"] for r in left] == [pid]
    assert conn.execute("SELECT COUNT(*) FROM missing_files WHERE project_id=?",
                        (pid2,)).fetchone()[0] == 0


def test_completed_feed_lands_in_history_and_incoming_need_shows(env):
    client, conn, now = env
    payload = report("editor2", "EDIT-PC")
    payload["completed"] = [
        {"name": "Projects/2026/FF5/Energy Transition/B-roll/a.mov",
         "direction": "up", "lane": "lane_a_video_up", "at": "2026-07-26T08:00:00+00:00"},
    ]
    assert client.post("/api/v1/report", json=payload, headers=hdr("editor2")).status_code == 200

    view = build_transfers_view(conn)
    (h,) = view["history"]
    assert h["editor"] == "editor2" and h["direction"] == "up"
    assert h["name"].endswith("B-roll/a.mov")

    # scoping: another editor sees nothing
    assert build_transfers_view(conn, editor="jane")["history"] == []

    # server-side lane C need renders as an incoming project-level row
    conn.execute("UPDATE projects SET need_items=1, need_bytes=420000000")
    conn.commit()
    rows = build_transfers_view(conn)["transfers"]
    (incoming,) = [r for r in rows if r["direction"] == "up" and r["granularity"] == "project"]
    assert "arriving at the server" in incoming["name"]

    # page renders the HISTORY section
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    page = client.get("/partials/transfers")
    assert "[ HISTORY ]" in page.text and "B-roll/a.mov" in page.text


def test_freshly_ticked_project_shows_as_preparing(env):
    """The first minute after a tick has no completion row and no manifest:
    every queue source is silent while sharing spins up, and the page said
    "everything that should be somewhere is there" (2026-07-26)."""
    client, conn, now = env
    dbmod.add_selection(conn, "editor2", "2026-ff5-energy-transition", "editor2", now)
    conn.commit()

    view = build_transfers_view(conn)
    (q,) = [x for x in view["queues"] if x["editor"] == "editor2"]
    assert q.get("pending") is True
    assert view["queued_files"] == 0            # pending rows don't count as files

    # once completion data exists the pending row yields to real state
    pid = conn.execute("SELECT id FROM projects WHERE slug='2026-ff5-energy-transition'").fetchone()["id"]
    did = dbmod.upsert_device(conn, "DEV-R", "editor2", False, now)
    dbmod.upsert_completion(conn, pid, did, completion=100.0, need_items=0,
                            need_bytes=0, need_deletes=0, global_items=5,
                            global_bytes=50, now=now)
    conn.commit()
    view = build_transfers_view(conn)
    assert [x for x in view["queues"] if x.get("pending")] == []

    # and the page renders the preparing chip while pending
    conn.execute("DELETE FROM completion_current")
    conn.commit()
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    assert "GETTING READY" in client.get("/partials/transfers").text


# -- CR-28: the base rig is not a queue -------------------------------------


def test_a_base_rig_never_appears_in_the_queue(env):
    """CR-28 [seen live 2026-08-18]. `alex · 2026/FF5/Animals [ GETTING
    READY ] ... syncing starts within a minute or two` sat on the fleet page
    for ten hours, on the machine that works directly off the NAS and syncs
    nothing. It never syncs, so it never gets a completion row, so "ticked
    and nothing known yet" is true for as long as the tick is."""
    client, conn, now = env
    client.post("/api/v1/report", json=report("base1", "Creator_1", mode="base"),
                headers=hdr("base1"))
    dbmod.add_selection(conn, "base1", "2026-ff5-energy-transition", "admin", now)
    conn.commit()

    view = build_transfers_view(conn)
    assert [q for q in view["queues"] if q["editor"] == "base1"] == []

    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    assert "GETTING READY" not in client.get("/partials/transfers").text


def test_the_role_is_stored_on_the_machine_not_only_on_its_projects(env):
    """v22. `mode` used to be persisted only onto editor_media_project rows,
    so a base rig that had never sent a media manifest was indistinguishable
    from an editor machine -- which is the state a fresh base rig is in."""
    client, conn, _now = env
    client.post("/api/v1/report", json=report("base1", "Creator_1", mode="base"),
                headers=hdr("base1"))

    row = conn.execute(
        "SELECT mode FROM machine_state WHERE editor_username='base1'").fetchone()
    assert row["mode"] == "base"
    assert dbmod.base_only_editors(conn) == {"base1"}
    # No manifest was ever sent, so the old source knows nothing about it.
    assert conn.execute(
        "SELECT COUNT(*) FROM editor_media_project WHERE editor_username='base1'"
    ).fetchone()[0] == 0


def test_a_report_with_no_mode_keeps_the_stored_role(env):
    """ultrareview 2026-08-19. The COALESCE on machine_state.mode was
    described as CR-28's defence against a build too old to send `mode`,
    but api.py defaulted a missing mode to "editor" BEFORE the upsert, so
    the SQL never saw a NULL and a mode-less report re-labelled the base rig.
    The default now stays with editor_media_project (NOT NULL column); the
    machine row gets None and keeps what it knew."""
    client, conn, _now = env
    client.post("/api/v1/report", json=report("base1", "Creator_1", mode="base"),
                headers=hdr("base1"))
    assert dbmod.base_only_editors(conn) == {"base1"}

    client.post("/api/v1/report", json=report("base1", "Creator_1"), headers=hdr("base1"))

    row = conn.execute(
        "SELECT mode FROM machine_state WHERE editor_username='base1'").fetchone()
    assert row["mode"] == "base"
    assert dbmod.base_only_editors(conn) == {"base1"}
    # An explicit answer still wins, in either direction.
    client.post("/api/v1/report", json=report("base1", "Creator_1", mode="editor"),
                headers=hdr("base1"))
    assert dbmod.base_only_editors(conn) == set()


def test_a_person_with_a_base_rig_and_a_laptop_still_queues(env):
    """base_only_editors means EVERY machine, not any. An editor who also
    keeps a base-mode machine must not have their laptop's backlog hidden."""
    client, conn, now = env
    client.post("/api/v1/report", json=report("mixed", "Creator_1", mode="base"),
                headers=hdr("mixed"))
    client.post("/api/v1/report", json=report("mixed", "Razer", mode="editor"),
                headers=hdr("mixed"))
    dbmod.add_selection(conn, "mixed", "2026-ff5-energy-transition", "admin", now)
    conn.commit()

    assert dbmod.base_only_editors(conn) == set()
    view = build_transfers_view(conn)
    assert [q for q in view["queues"] if q["editor"] == "mixed"]


def test_ticking_a_project_for_a_base_rig_is_refused(env):
    """The tick is what created the phantom row, so the fix closes the hole
    as well as hiding the symptom -- and UNTICKING stays open, or an existing
    one could never be removed."""
    client, conn, now = env
    client.post("/api/v1/report", json=report("base1", "Creator_1", mode="base"),
                headers=hdr("base1"))
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))

    r = client.put("/api/v1/selection/base1/2026-ff5-energy-transition")
    assert r.status_code == 409
    assert "base rig" in r.json()["detail"]
    assert dbmod.fetch_selections(conn, "base1") == []

    dbmod.add_selection(conn, "base1", "2026-ff5-energy-transition", "admin", now)
    conn.commit()
    assert client.delete("/api/v1/selection/base1/2026-ff5-energy-transition").status_code == 200
    assert dbmod.fetch_selections(conn, "base1") == []
