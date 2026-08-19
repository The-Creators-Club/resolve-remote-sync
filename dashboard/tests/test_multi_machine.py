"""One person, several computers — per-machine sync plans.

docs/MULTI_MACHINE_PLAN.md (2026-08-18). Until this, `selections` was keyed
(editor_username, project_slug) while every consumer of it was per machine,
so the fleet's answer to "Ruskin has a laptop now" was to make a second
PERSON (`alex` and `alex_laptop` are one human). These pin the model that
replaced it: the plan belongs to a computer, the person still owns the
account, and nothing an old companion does silently changes what it syncs.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.api import build_transfers_view
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
TOKEN = "tok"


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "m.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET, report_token=TOKEN,
                        admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, "p1", "2026/One", "/x", now)
        dbmod.upsert_project(conn, "p2", "2026/Two", "/y", now)
        conn.commit()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield client, conn, now


def hdr(editor):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def report(client, editor, machine, **extra):
    body = {"editor_name": editor, "machine": machine,
            "reported_at": "2026-08-18T10:00:00+00:00", "lanes": []}
    body.update(extra)
    resp = client.post("/api/v1/report", json=body, headers=hdr(editor))
    assert resp.status_code == 200, resp.text
    return resp.json()


# -- WP1: the machine registry ----------------------------------------------


def test_a_report_registers_the_computer_it_came_from(env):
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", machine_id="mid-1",
           syncthing_device_id="DEV-1", platform="windows")

    (row,) = dbmod.fetch_machines(conn, "ruskin")
    assert row["machine"] == "DESKTOP-1"
    assert row["machine_id"] == "mid-1"
    assert row["syncthing_device_id"] == "DEV-1"
    assert row["platform"] == "windows"


def test_an_old_companion_still_registers_just_without_an_id(env):
    """0.9.2 and earlier send neither field. They must still appear as a
    computer, or their editor has no column to be ticked in."""
    client, conn, _now = env
    report(client, "leso", "MacBook")

    (row,) = dbmod.fetch_machines(conn, "leso")
    assert row["machine"] == "MacBook"
    assert row["machine_id"] is None


def test_learned_attributes_are_never_unlearned_by_a_lighter_report(env):
    """Syncthing is momentarily unreachable, so the companion sends no device
    id. That is not evidence that what we already knew is wrong."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", machine_id="mid-1", syncthing_device_id="DEV-1")
    report(client, "ruskin", "DESKTOP-1")

    (row,) = dbmod.fetch_machines(conn, "ruskin")
    assert row["machine_id"] == "mid-1"
    assert row["syncthing_device_id"] == "DEV-1"


def test_a_renamed_computer_keeps_its_plan(env):
    """A hostname is a label an editor can change in ten seconds, and the
    plan is keyed on it. Without the minted id this reads as a brand-new
    computer with an empty plan -- a machine that silently stops syncing."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", machine_id="mid-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")

    report(client, "ruskin", "RUSKIN-PC", machine_id="mid-1")

    assert [m["machine"] for m in dbmod.fetch_machines(conn, "ruskin")] == ["RUSKIN-PC"]
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "RUSKIN-PC")] == ["p1"]


def test_another_editors_machine_id_moves_nothing(env):
    """The rename branch only fires within one account: an id from somebody
    else's report names nothing here."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", machine_id="shared-id")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")

    report(client, "leso", "MacBook", machine_id="shared-id")

    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "DESKTOP-1")] == ["p1"]
    assert dbmod.selections_for_machine(conn, "leso", "MacBook") == []


# -- WP2: two computers, two plans ------------------------------------------


def test_one_person_two_computers_two_plans(env):
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", machine_id="mid-1")
    report(client, "ruskin", "LAPTOP-1", machine_id="mid-2")

    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")
    client.put("/api/v1/selection/ruskin/p2?machine=LAPTOP-1")

    desktop = client.get("/api/v1/selection/ruskin?machine=DESKTOP-1").json()
    laptop = client.get("/api/v1/selection/ruskin?machine=LAPTOP-1").json()
    assert [s["slug"] for s in desktop["selection"]] == ["p1"]
    assert [s["slug"] for s in laptop["selection"]] == ["p2"]
    assert desktop["machines"] == ["DESKTOP-1", "LAPTOP-1"]


def test_a_companion_that_cannot_name_itself_gets_the_union(env):
    """MULTI_MACHINE_PLAN.md §5: an old build that over-syncs fills a drive,
    an old build that under-syncs is an editor who quietly cannot open a
    project. For every single-machine editor the union IS their plan."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    report(client, "ruskin", "LAPTOP-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")
    client.put("/api/v1/selection/ruskin/p2?machine=LAPTOP-1")

    both = client.get("/api/v1/selection/ruskin").json()
    assert sorted(s["slug"] for s in both["selection"]) == ["p1", "p2"]


def test_a_tick_with_no_machine_reaches_every_computer_of_that_person(env):
    """The person-level control (and any old client) means "all of them"."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    report(client, "ruskin", "LAPTOP-1")

    client.put("/api/v1/selection/ruskin/p1")

    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "DESKTOP-1")] == ["p1"]
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "LAPTOP-1")] == ["p1"]


def test_an_untick_with_no_machine_removes_it_everywhere(env):
    """Under-sharing is the safe direction for a removal: "stop syncing this"
    must not leave it running on the person's other computer."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    report(client, "ruskin", "LAPTOP-1")
    client.put("/api/v1/selection/ruskin/p1")

    client.delete("/api/v1/selection/ruskin/p1")

    assert dbmod.selections_for_machine(conn, "ruskin", "DESKTOP-1") == []
    assert dbmod.selections_for_machine(conn, "ruskin", "LAPTOP-1") == []


def test_unticking_one_computer_leaves_the_other_alone(env):
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    report(client, "ruskin", "LAPTOP-1")
    client.put("/api/v1/selection/ruskin/p1")

    client.delete("/api/v1/selection/ruskin/p1?machine=LAPTOP-1")

    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "DESKTOP-1")] == ["p1"]
    assert dbmod.selections_for_machine(conn, "ruskin", "LAPTOP-1") == []


def test_the_unassigned_bucket_applies_only_where_there_is_no_plan(env):
    """A machine that has been given a plan of its own is never ALSO handed
    the bucket -- that would make "untick this on the laptop" impossible."""
    client, conn, now = env
    report(client, "ruskin", "DESKTOP-1")
    report(client, "ruskin", "LAPTOP-1")
    dbmod.add_selection(conn, "ruskin", "p1", "seed", now)          # bucket
    dbmod.add_selection(conn, "ruskin", "p2", "admin", now, machine="LAPTOP-1")
    conn.commit()

    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "DESKTOP-1")] == ["p1"]
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "LAPTOP-1")] == ["p2"]


def test_the_backlog_is_per_computer(env):
    """The lane A/B backlog used to tell one person's laptop it was behind on
    everything their desktop was ticked for."""
    client, conn, now = env
    report(client, "ruskin", "DESKTOP-1")
    report(client, "ruskin", "LAPTOP-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")

    pid = conn.execute("SELECT id FROM projects WHERE slug='p1'").fetchone()["id"]
    dbmod.replace_nas_media(conn, pid, [("A/Proxy/a.mov", "proxy", ".mov", 10, 1)], "sig", 1, now)
    for machine in ("DESKTOP-1", "LAPTOP-1"):
        dbmod.upsert_editor_media_project(
            conn, editor="ruskin", machine=machine, slug="p1", mode="editor",
            n_originals=0, bytes_originals=0, n_proxies=0, bytes_proxies=0,
            truncated=False, now=now)
    conn.commit()

    behind = {(q["editor"], q["machine"]) for q in build_transfers_view(conn)["queues"]
              if q["slug"] == "p1" and not q.get("pending")}
    assert behind == {("ruskin", "DESKTOP-1")}


def test_the_sidebar_checkbox_reaches_every_computer_too(env):
    """It is the PERSON's control (its tooltip says so). Writing the
    unassigned bucket instead would be silently ineffective for anyone whose
    machines already have plans of their own -- the bucket only applies where
    there is none."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    report(client, "ruskin", "LAPTOP-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")   # a plan of its own

    r = client.post("/partials/selection/ruskin/p2/toggle")
    assert r.status_code == 200, r.text

    assert sorted(s["slug"] for s in
                  dbmod.selections_for_machine(conn, "ruskin", "DESKTOP-1")) == ["p1", "p2"]
    assert [s["slug"] for s in
            dbmod.selections_for_machine(conn, "ruskin", "LAPTOP-1")] == ["p2"]


def test_a_tick_for_a_computer_that_does_not_exist_is_refused(env):
    """A stale page after a rename, or a typed URL. Writing a plan for a
    computer nobody has is a row nothing reads and nobody sees."""
    client, _conn, _now = env
    report(client, "ruskin", "DESKTOP-1")

    r = client.put("/api/v1/selection/ruskin/p1?machine=GHOST")
    assert r.status_code == 404
    assert "no computer named" in r.json()["detail"]


# -- WP3: the enforce cycle shares with a COMPUTER --------------------------


def test_the_share_set_follows_the_machine_that_owns_the_device(env):
    """A folder is shared with a DEVICE. Before the registry, the only way
    back from a device to a plan was its owner's NAME, so both of one
    person's computers got every project either was ticked for."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", machine_id="mid-1", syncthing_device_id="DEV-1")
    report(client, "ruskin", "LAPTOP-1", machine_id="mid-2", syncthing_device_id="DEV-2")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")

    plans = dbmod.fetch_machine_selections(conn)
    assert plans["p1"] == [("ruskin", "DESKTOP-1")]


def test_a_new_computer_can_be_given_another_ones_plan(env):
    """A new machine starts EMPTY by design -- inheritance would silently
    start a 50 GB download on a laptop nobody asked to fill -- so this is the
    affordance that makes that bearable."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")
    client.put("/api/v1/selection/ruskin/p2?machine=DESKTOP-1")
    report(client, "ruskin", "LAPTOP-1")
    assert dbmod.selections_for_machine(conn, "ruskin", "LAPTOP-1") == []

    r = client.post("/api/v1/admin/machines/ruskin/LAPTOP-1/copy-plan?source=DESKTOP-1")
    assert r.status_code == 200, r.text
    assert r.json()["projects"] == 2
    assert sorted(s["slug"] for s in
                  dbmod.selections_for_machine(conn, "ruskin", "LAPTOP-1")) == ["p1", "p2"]


def test_copying_replaces_rather_than_merges(env):
    """"Same as the desktop" has to mean the same, or the laptop keeps
    syncing something nobody can see it was told to."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    report(client, "ruskin", "LAPTOP-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")
    client.put("/api/v1/selection/ruskin/p2?machine=LAPTOP-1")

    client.post("/api/v1/admin/machines/ruskin/LAPTOP-1/copy-plan?source=DESKTOP-1")

    assert [s["slug"] for s in
            dbmod.selections_for_machine(conn, "ruskin", "LAPTOP-1")] == ["p1"]


def test_a_plan_cannot_be_copied_across_people(env):
    client, _conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    report(client, "leso", "MacBook")

    r = client.post("/api/v1/admin/machines/leso/MacBook/copy-plan?source=DESKTOP-1")
    assert r.status_code == 404


# -- pushed updates ---------------------------------------------------------


def test_an_admin_can_ask_one_machine_to_update(env):
    client, conn, now = env
    report(client, "ruskin", "DESKTOP-1", platform="windows", companion_version="0.9.0")
    dbmod.insert_companion_package(
        conn, version="0.9.2", platform="windows", filename="c.exe",
        sha256="a" * 64, size_bytes=1, published_by="owen", now=now)
    dbmod.set_current_package(conn, "windows", "0.9.2", "companion")
    conn.commit()

    r = client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/update")
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "0.9.2"

    reply = report(client, "ruskin", "DESKTOP-1", platform="windows",
                   companion_version="0.9.0")
    assert reply["commands"]["upgrade"] == {
        "apply": True, "version": "0.9.2",
        "requested_by": "owen", "requested_at": reply["commands"]["upgrade"]["requested_at"],
    }


def test_the_request_clears_itself_once_the_machine_is_on_that_build(env):
    """A standing request would re-apply the same build after every restart."""
    client, conn, now = env
    report(client, "ruskin", "DESKTOP-1", platform="windows", companion_version="0.9.0")
    dbmod.insert_companion_package(
        conn, version="0.9.2", platform="windows", filename="c.exe",
        sha256="a" * 64, size_bytes=1, published_by="owen", now=now)
    dbmod.set_current_package(conn, "windows", "0.9.2", "companion")
    conn.commit()
    client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/update")

    reply = report(client, "ruskin", "DESKTOP-1", platform="windows",
                   companion_version="0.9.2")

    assert "upgrade" not in reply["commands"]
    assert dbmod.machine_update_request(conn, "ruskin", "DESKTOP-1") is None


def test_pushing_to_a_machine_nobody_has_seen_is_a_404(env):
    client, _conn, _now = env
    assert client.post("/api/v1/admin/machines/ghost/NOPE/update").status_code == 404


def test_only_an_admin_can_push_an_update(env):
    client, _conn, _now = env
    report(client, "ruskin", "DESKTOP-1", platform="windows")
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "ruskin"))

    assert client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/update").status_code == 403
