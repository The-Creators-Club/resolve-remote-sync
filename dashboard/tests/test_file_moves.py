"""Dashboard-driven file moves (docs/FILE_MOVES.md, 2026-08-27).

A file uploaded into the wrong project folder is moved on the server by an
admin, and every computer that syncs the source project (or has reported
holding the file) is told to move its own copy through the report reply.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import provision
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
TOKEN = "companion-token"
DRONE = "2026/Base Drone"
ANIMALS = "2026/FF5/Animals"
D_SLUG = "2026-base-drone"
A_SLUG = "2026-ff5-animals"


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "Projects"
    for rel, slug in ((DRONE, D_SLUG), (ANIMALS, A_SLUG)):
        d = projects / rel
        d.mkdir(parents=True)
        provision.write_marker(d, slug)
    broll = projects / DRONE / "B-roll"
    (broll / "Proxy").mkdir(parents=True)
    (broll / "A001_0512.braw").write_bytes(b"braw")
    (broll / "Proxy" / "A001_0512.mp4").write_bytes(b"proxy")
    (broll / "A002_0513.braw").write_bytes(b"braw2")
    (projects / ANIMALS / "Interviewees" / "Pangolin").mkdir(parents=True)

    settings = Settings(db_path=str(tmp_path / "moves.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "moves.db")
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, D_SLUG, DRONE, f"/data/{D_SLUG}", now)
        dbmod.upsert_project(conn, A_SLUG, ANIMALS, f"/data/{A_SLUG}", now)
        conn.commit()
        yield client, conn, projects
        conn.close()


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def hdr(editor):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def report(client, editor, machine, **extra):
    body = {"editor_name": editor, "machine": machine,
            "reported_at": "2026-08-27T10:00:00+00:00", "lanes": []}
    body.update(extra)
    resp = client.post("/api/v1/report", json=body, headers=hdr(editor))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_file_moves_on_the_server_with_its_proxy(env):
    client, conn, projects = env
    as_user(client, "owen")
    r = client.post(f"/api/v1/projects/{D_SLUG}/move", json={
        "path": "B-roll/A001_0512.braw", "to_slug": A_SLUG,
        "to_path": "Interviewees/Pangolin"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["to"] == f"{ANIMALS}/Interviewees/Pangolin/A001_0512.braw"
    assert body["proxies_moved"] == 1
    assert not (projects / DRONE / "B-roll" / "A001_0512.braw").exists()
    assert not (projects / DRONE / "B-roll" / "Proxy" / "A001_0512.mp4").exists()
    assert (projects / ANIMALS / "Interviewees" / "Pangolin" / "A001_0512.braw").read_bytes() == b"braw"
    assert (projects / ANIMALS / "Interviewees" / "Pangolin" / "Proxy" / "A001_0512.mp4").exists()
    # The sibling that was not named stays exactly where it was.
    assert (projects / DRONE / "B-roll" / "A002_0513.braw").exists()


def test_a_folder_moves_whole(env):
    client, conn, projects = env
    as_user(client, "owen")
    r = client.post(f"/api/v1/projects/{D_SLUG}/move", json={
        "path": "B-roll", "to_slug": A_SLUG, "to_path": "Interviewees/Pangolin"})
    assert r.status_code == 200, r.text
    assert r.json()["is_dir"] is True
    assert (projects / ANIMALS / "Interviewees" / "Pangolin" / "B-roll" / "Proxy" / "A001_0512.mp4").exists()
    assert not (projects / DRONE / "B-roll").exists()


def test_refusals(env):
    client, conn, projects = env
    as_user(client, "owen")
    post = lambda **kw: client.post(f"/api/v1/projects/{D_SLUG}/move", json=kw)
    assert post(path="B-roll/nope.braw", to_slug=A_SLUG).status_code == 404
    assert post(path="../../etc", to_slug=A_SLUG).status_code == 400
    assert post(path="B-roll/Proxy/A001_0512.mp4", to_slug=A_SLUG).status_code == 400
    assert post(path=provision.MARKER_FILENAME, to_slug=A_SLUG).status_code == 400
    assert post(path="B-roll", to_path="B-roll/inside").status_code == 400   # into itself
    (projects / ANIMALS / "A001_0512.braw").write_bytes(b"other")
    r = post(path="B-roll/A001_0512.braw", to_slug=A_SLUG)
    assert r.status_code == 409 and "already exists" in r.json()["detail"]
    assert (projects / DRONE / "B-roll" / "A001_0512.braw").exists()   # nothing moved
    assert post(path="B-roll", to_slug="ghost").status_code == 404


def test_only_an_admin_may_move(env):
    client, conn, projects = env
    assert client.post(f"/api/v1/projects/{D_SLUG}/move",
                       json={"path": "B-roll"}).status_code == 401
    as_user(client, "leso")
    assert client.post(f"/api/v1/projects/{D_SLUG}/move",
                       json={"path": "B-roll"}).status_code == 403
    assert (projects / DRONE / "B-roll").exists()


def test_every_machine_syncing_the_source_project_is_told_until_it_answers(env):
    client, conn, projects = env
    report(client, "leso", "LESO-PC")
    report(client, "leso", "LESO-LAPTOP")
    report(client, "ruskin", "RUSKIN-PC")
    as_user(client, "owen")
    client.put(f"/api/v1/selection/leso/{D_SLUG}?machine=LESO-PC&mode=upload_only")
    client.put(f"/api/v1/selection/ruskin/{A_SLUG}?machine=RUSKIN-PC")   # destination only
    # A machine that no longer syncs the project but reported holding the file.
    now = dbmod.utcnow_iso()
    dbmod.replace_editor_media(conn, "leso", "LESO-LAPTOP", D_SLUG,
                               [("B-roll/A001_0512.braw", "original", 4)], now)
    conn.commit()
    r = client.post(f"/api/v1/projects/{D_SLUG}/move", json={
        "path": "B-roll/A001_0512.braw", "to_slug": A_SLUG, "to_path": "Interviewees/Pangolin"})
    assert r.status_code == 200, r.text
    assert r.json()["machines"] == [
        {"editor": "leso", "machine": "LESO-LAPTOP"},
        {"editor": "leso", "machine": "LESO-PC"},
    ]
    client.cookies.delete(auth.COOKIE_NAME)

    # Delivered in the report reply, and again until answered.
    for _ in range(2):
        cmds = report(client, "leso", "LESO-PC")["commands"]
        (move,) = cmds["file_moves"]
        assert move["from_project_rel"] == DRONE and move["from_rel"] == "B-roll/A001_0512.braw"
        assert move["to_project_rel"] == ANIMALS
        assert move["to_rel"] == "Interviewees/Pangolin/A001_0512.braw"
        assert move["is_dir"] is False and move["requested_by"] == "owen"
    assert "file_moves" not in report(client, "ruskin", "RUSKIN-PC")["commands"]

    # The answer retires it; a failure is an answer too.
    reply = report(client, "leso", "LESO-PC",
                   file_moves_applied=[{"id": move["id"], "ok": True, "detail": "moved, 2 clips relinked"}])
    assert "file_moves" not in reply["commands"]
    report(client, "leso", "LESO-LAPTOP",
           file_moves_applied=[{"id": move["id"], "ok": False, "detail": "destination exists here"}])
    (rec,) = dbmod.file_moves_for_project(conn, A_SLUG)
    by_machine = {t["machine"]: t for t in rec["targets"]}
    assert by_machine["LESO-PC"]["ok"] == 1 and by_machine["LESO-PC"]["applied_at"]
    assert by_machine["LESO-LAPTOP"]["ok"] == 0
    assert rec["waiting"] == 0 and rec["failed"] == 1
    # Both projects' pages list it.
    assert [m["id"] for m in dbmod.file_moves_for_project(conn, D_SLUG)] == [move["id"]]


def test_an_old_move_is_not_replayed_on_a_machine_that_was_away(env):
    client, conn, projects = env
    report(client, "leso", "LESO-PC")
    as_user(client, "owen")
    client.put(f"/api/v1/selection/leso/{D_SLUG}?machine=LESO-PC")
    client.post(f"/api/v1/projects/{D_SLUG}/move", json={"path": "B-roll", "to_slug": A_SLUG})
    conn.execute("UPDATE file_moves SET requested_at='2026-08-01T00:00:00+00:00'")
    conn.commit()
    client.cookies.delete(auth.COOKIE_NAME)
    assert "file_moves" not in report(client, "leso", "LESO-PC")["commands"]


def test_the_project_page_has_the_form_and_the_log_for_admins_only(env):
    client, conn, projects = env
    as_user(client, "owen")
    page = client.get(f"/project/{D_SLUG}").text
    assert "[ MOVE ON THE SERVER AND ON EVERY MACHINE ]" in page
    r = client.post(f"/partials/project/{D_SLUG}/move",
                    data={"path": "B-roll/A001_0512.braw", "to_slug": A_SLUG,
                          "to_path": "Interviewees/Pangolin"})
    assert r.status_code == 200, r.text
    assert "[ MOVED ]" in r.text and "[ DONE ]" in r.text
    r = client.post(f"/partials/project/{D_SLUG}/move", data={"path": "", "to_slug": A_SLUG})
    assert "type the file or folder to move" in r.text
    as_user(client, "leso")
    page = client.get(f"/project/{D_SLUG}").text
    assert "[ MOVE ON THE SERVER AND ON EVERY MACHINE ]" not in page
