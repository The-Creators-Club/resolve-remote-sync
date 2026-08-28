"""Dashboard-driven file moves (docs/FILE_MOVES.md, 2026-08-27).

A file uploaded into the wrong project folder is moved on the server by an
admin, and every computer that syncs the source project (or has reported
holding the file) is told to move its own copy through the report reply.
"""
from __future__ import annotations

from pathlib import Path

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


def test_an_undelivered_move_never_expires_but_a_delivered_one_does(env):
    """UX-5 (resilience sweep 2026-08-28). The laptop that was away for the
    shoot is the one machine still holding the file at the old path, so the
    command must still be there when it comes back. What ages out is a
    command that WAS delivered and never answered, and that is loud."""
    client, conn, projects = env
    report(client, "leso", "LESO-PC")
    report(client, "leso", "LESO-LAPTOP")
    as_user(client, "owen")
    client.put(f"/api/v1/selection/leso/{D_SLUG}?machine=LESO-PC")
    client.put(f"/api/v1/selection/leso/{D_SLUG}?machine=LESO-LAPTOP")
    client.post(f"/api/v1/projects/{D_SLUG}/move", json={"path": "B-roll", "to_slug": A_SLUG})
    client.cookies.delete(auth.COOKIE_NAME)
    # LESO-PC hears it; LESO-LAPTOP is away and hears nothing.
    (move,) = report(client, "leso", "LESO-PC")["commands"]["file_moves"]
    conn.execute("UPDATE file_moves SET requested_at='2026-08-01T00:00:00+00:00'")
    conn.execute("UPDATE file_move_targets SET delivered_at='2026-08-01T00:00:00+00:00' "
                 "WHERE machine='LESO-PC'")
    conn.commit()

    from ccsync_dashboard import api as apimod
    settings = client.app.state.settings
    apimod.reconcile_file_moves(settings, conn)

    # The machine that was told and never answered has aged out, loudly...
    (rec,) = dbmod.file_moves_for_project(conn, D_SLUG)
    by_machine = {t["machine"]: t for t in rec["targets"]}
    assert by_machine["LESO-PC"]["expired_at"]
    assert "file_moves" not in report(client, "leso", "LESO-PC")["commands"]
    # ...and the one that was never told still gets its command three weeks on.
    (still,) = report(client, "leso", "LESO-LAPTOP")["commands"]["file_moves"]
    assert still["id"] == move["id"]

    # The project page says so, and offers the re-issue.
    as_user(client, "owen")
    page = client.get(f"/project/{D_SLUG}").text
    assert "[ NOT APPLIED - THIS COMPUTER MAY RE-UPLOAD THE OLD PATH ]" in page
    assert "[ ASK THAT COMPUTER AGAIN ]" in page
    r = client.post(f"/partials/project/{D_SLUG}/moves/{move['id']}/reissue",
                    data={"editor": "leso", "machine": "LESO-PC"})
    assert r.status_code == 200, r.text
    client.cookies.delete(auth.COOKIE_NAME)
    (again,) = report(client, "leso", "LESO-PC")["commands"]["file_moves"]
    assert again["id"] == move["id"]


def test_the_record_is_written_and_committed_before_the_rename(env, monkeypatch):
    """DASH-1: a rename that succeeds and is then interrupted must leave a row
    behind, or no machine is ever told and every holder re-uploads the old
    path. So the row exists (committed, visible to another connection) while
    the rename runs, and a rename that FAILS takes the reservation with it."""
    client, conn, projects = env
    as_user(client, "owen")
    seen: list[dict] = []

    def watched(self, target):
        other = dbmod.connect(projects.parent / "moves.db")
        seen.extend(dict(r) for r in other.execute("SELECT * FROM file_moves"))
        other.close()
        raise OSError("Resolve has it open")

    monkeypatch.setattr(Path, "rename", watched)
    r = client.post(f"/api/v1/projects/{D_SLUG}/move",
                    json={"path": "B-roll/A001_0512.braw", "to_slug": A_SLUG})
    assert r.status_code == 503 and "could not move it" in r.json()["detail"]
    assert [m["state"] for m in seen] == ["pending"]
    monkeypatch.undo()
    # Nothing moved, so nothing is left claiming it did.
    assert (projects / DRONE / "B-roll" / "A001_0512.braw").exists()
    assert dbmod.file_moves_for_project(conn, D_SLUG) == []
    assert conn.execute("SELECT COUNT(*) FROM file_move_targets").fetchone()[0] == 0


def test_a_proxy_that_could_not_follow_is_named_and_never_read_as_nothing_happened(env):
    """DASH-1: the proxy loop used to sit inside the fatal try, so one held
    proxy 503d with "the server could not move it" while the original was
    already gone and no row was written at all."""
    client, conn, projects = env
    # Something is already at the proxy's destination: it cannot follow.
    clash = projects / ANIMALS / "Interviewees" / "Pangolin" / "Proxy"
    clash.mkdir(parents=True)
    (clash / "A001_0512.mp4").write_bytes(b"theirs")
    as_user(client, "owen")
    r = client.post(f"/api/v1/projects/{D_SLUG}/move", json={
        "path": "B-roll/A001_0512.braw", "to_slug": A_SLUG,
        "to_path": "Interviewees/Pangolin"})
    assert r.status_code == 207, r.text
    body = r.json()
    assert body["state"] == "partial"
    assert body["proxies_failed"] and "A001_0512.mp4" in body["proxies_failed"][0]
    # The original DID move, and the record says so.
    assert (projects / ANIMALS / "Interviewees" / "Pangolin" / "A001_0512.braw").exists()
    (rec,) = dbmod.file_moves_for_project(conn, D_SLUG)
    assert rec["state"] == "partial" and rec["state_detail"]
    page = client.get(f"/project/{D_SLUG}").text
    assert "[ SOME PROXIES STAYED ]" in page


def test_an_interrupted_move_is_completed_or_quarantined_on_the_next_pass(env):
    """DASH-1's reconciliation: only the destination exists means the rename
    happened, so finish the record and fan it out. Both existing means
    something else is going on, and guessing is the expensive kind of wrong."""
    client, conn, projects = env
    from ccsync_dashboard import api as apimod
    settings = client.app.state.settings
    report(client, "leso", "LESO-PC")
    as_user(client, "owen")
    client.put(f"/api/v1/selection/leso/{D_SLUG}?machine=LESO-PC")
    conn.commit()

    # The crash shape: the row is pending and the file is at the destination.
    dest = projects / ANIMALS / "A001_0512.braw"
    (projects / DRONE / "B-roll" / "A001_0512.braw").rename(dest)
    move_id = dbmod.record_file_move(
        conn, from_slug=D_SLUG, from_project_rel=DRONE, from_rel="B-roll/A001_0512.braw",
        to_slug=A_SLUG, to_project_rel=ANIMALS, to_rel="A001_0512.braw", is_dir=False,
        proxies_moved=0, requested_by="owen", now=dbmod.utcnow_iso(),
        targets=[("leso", "LESO-PC")], state=dbmod.FILE_MOVE_PENDING)
    conn.commit()
    client.cookies.delete(auth.COOKIE_NAME)
    assert "file_moves" not in report(client, "leso", "LESO-PC")["commands"]

    assert apimod.reconcile_file_moves(settings, conn)["completed"] == 1
    (offered,) = report(client, "leso", "LESO-PC")["commands"]["file_moves"]
    assert offered["id"] == move_id

    # Both ends present: quarantined, nobody told, and the page says so.
    (projects / DRONE / "B-roll" / "A002_0513.braw").write_bytes(b"x")
    (projects / ANIMALS / "A002_0513.braw").write_bytes(b"x")
    both = dbmod.record_file_move(
        conn, from_slug=D_SLUG, from_project_rel=DRONE, from_rel="B-roll/A002_0513.braw",
        to_slug=A_SLUG, to_project_rel=ANIMALS, to_rel="A002_0513.braw", is_dir=False,
        proxies_moved=0, requested_by="owen", now=dbmod.utcnow_iso(),
        targets=[("leso", "LESO-PC")], state=dbmod.FILE_MOVE_PENDING)
    conn.commit()
    counts = apimod.reconcile_file_moves(settings, conn)
    assert counts["quarantined"] == 1
    assert [a["id"] for a in apimod.file_move_alarms(conn, D_SLUG)] == [both]
    ids = [m["id"] for m in report(client, "leso", "LESO-PC")["commands"].get("file_moves", [])]
    assert both not in ids
    as_user(client, "owen")
    assert "[ UNFINISHED ON THE SERVER ]" in client.get(f"/project/{D_SLUG}").text


def test_a_move_can_be_put_back(env):
    """UX-11: the inverse move, through the same machinery, audited."""
    client, conn, projects = env
    report(client, "leso", "LESO-PC")
    as_user(client, "owen")
    client.put(f"/api/v1/selection/leso/{D_SLUG}?machine=LESO-PC")
    r = client.post(f"/api/v1/projects/{D_SLUG}/move", json={
        "path": "B-roll/A001_0512.braw", "to_slug": A_SLUG,
        "to_path": "Interviewees/Pangolin"})
    move_id = r.json()["move_id"]
    assert "[ UNDO THIS MOVE ]" in client.get(f"/project/{D_SLUG}").text

    undo = client.post(f"/api/v1/projects/{D_SLUG}/moves/{move_id}/undo")
    assert undo.status_code == 200, undo.text
    assert (projects / DRONE / "B-roll" / "A001_0512.braw").exists()
    assert (projects / DRONE / "B-roll" / "Proxy" / "A001_0512.mp4").exists()
    assert not (projects / ANIMALS / "Interviewees" / "Pangolin" / "A001_0512.braw").exists()
    original = dbmod.file_move(conn, move_id)
    assert original["state"] == "undone" and original["undone_by"] == undo.json()["move_id"]
    actions = [r["action"] for r in conn.execute("SELECT action FROM fleet_audit")]
    assert "file.move.undo" in actions
    # It cannot be undone twice, and the machine is told about the inverse.
    assert client.post(f"/api/v1/projects/{D_SLUG}/moves/{move_id}/undo").status_code == 409
    client.cookies.delete(auth.COOKIE_NAME)
    ids = [m["id"] for m in report(client, "leso", "LESO-PC")["commands"]["file_moves"]]
    assert undo.json()["move_id"] in ids


def test_undo_is_refused_while_a_computer_could_not_follow(env):
    client, conn, projects = env
    report(client, "leso", "LESO-PC")
    as_user(client, "owen")
    client.put(f"/api/v1/selection/leso/{D_SLUG}?machine=LESO-PC")
    move_id = client.post(f"/api/v1/projects/{D_SLUG}/move", json={
        "path": "B-roll/A001_0512.braw", "to_slug": A_SLUG}).json()["move_id"]
    client.cookies.delete(auth.COOKIE_NAME)
    report(client, "leso", "LESO-PC",
           file_moves_applied=[{"id": move_id, "ok": False, "state": "blocked",
                                "attempts": 20, "detail": "Resolve has it open"}])
    (rec,) = dbmod.file_moves_for_project(conn, A_SLUG)
    target = rec["targets"][0]
    assert target["state"] == "blocked" and target["attempts"] == 20
    assert rec["undoable"] is False
    as_user(client, "owen")
    r = client.post(f"/api/v1/projects/{D_SLUG}/moves/{move_id}/undo")
    assert r.status_code == 409 and "still at the old path" in r.json()["detail"]
    assert "[ 1 BLOCKED ]" in client.get(f"/project/{D_SLUG}").text


def test_a_retrying_machine_keeps_the_command_and_shows_its_attempts(env):
    """RES-1: "retrying" is an answer that does NOT retire the command."""
    client, conn, projects = env
    report(client, "leso", "LESO-PC")
    as_user(client, "owen")
    client.put(f"/api/v1/selection/leso/{D_SLUG}?machine=LESO-PC")
    move_id = client.post(f"/api/v1/projects/{D_SLUG}/move", json={
        "path": "B-roll/A001_0512.braw", "to_slug": A_SLUG}).json()["move_id"]
    client.cookies.delete(auth.COOKIE_NAME)
    reply = report(client, "leso", "LESO-PC",
                   file_moves_applied=[{"id": move_id, "ok": False, "state": "retrying",
                                        "attempts": 3, "detail": "open in Resolve"}])
    assert [m["id"] for m in reply["commands"]["file_moves"]] == [move_id]
    (rec,) = dbmod.file_moves_for_project(conn, D_SLUG)
    target = rec["targets"][0]
    assert target["applied_at"] is None and target["attempts"] == 3
    assert target["state"] == "retrying" and target["last_error"] == "open in Resolve"
    # And a relink that has not happened yet is carried through to the page.
    report(client, "leso", "LESO-PC",
           file_moves_applied=[{"id": move_id, "ok": True, "detail": "moved",
                                "relink_pending": True}])
    (rec,) = dbmod.file_moves_for_project(conn, D_SLUG)
    assert rec["targets"][0]["relink_pending"] == 1
    as_user(client, "owen")
    assert "Resolve not repointed yet" in client.get(f"/project/{D_SLUG}").text


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
